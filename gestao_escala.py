# ==============================================================================
# == gestao_escala.py  -  Escala da Loja na Web (Gestão › Escala) ===============
# ==============================================================================
# O que o programa escala_loja_main.py (PC) faz no dia a dia, agora pelo navegador:
# ver o dia (mapa, alertas, resumo, fluxo), escalar/editar/excluir turnos, copiar
# a escala, intervalos (automático e manual) e os envios no Telegram e WhatsApp.
#
# As regras são as MESMAS do PC (escala_regras.py). A diferença: aqui todas as
# conferências são refeitas no servidor com a escala lida do banco na hora de salvar
# (se o PC e a Web mexerem no mesmo dia, nada passa sem conferir).
#
# Perguntas ("Escalar mesmo assim?") voltam como {'perguntas': [...]}: a página pergunta
# e manda de novo com 'confirmar' = as chaves aceitas.
# ==============================================================================
import logging
import threading
import time
import uuid
from datetime import date, datetime, timedelta

import config
import database
import escala_fixa
import escala_regras as R

logger = logging.getLogger(__name__)


class ErroEscala(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ------------------------------------------------------------------------------
# Ajudantes
# ------------------------------------------------------------------------------
def _data(texto):
    """'AAAA-MM-DD' -> (texto, date). ErroEscala se inválida."""
    try:
        d = datetime.strptime(str(texto or '')[:10], '%Y-%m-%d').date()
    except ValueError:
        raise ErroEscala("Data inválida.")
    return d.strftime('%Y-%m-%d'), d


def _exigir_banco():
    """
    [DEPURAÇÃO WEB] As funções do banco devolvem lista/dicionário VAZIO quando não conseguem
    conectar: sem esta conferência a tela mostrava um dia "sem ninguém escalado" (e salvar dizia
    "esta posição não está mais no mapa"), em vez de avisar que o banco está fora do ar.
    """
    conn = database.get_db_connection()
    if not conn:
        raise ErroEscala("Sem conexão com o banco de dados. Tente de novo em alguns segundos.", 503)
    try:
        conn.close()
    except Exception:
        pass


def _id(valor, nome="o turno"):
    """[DEPURAÇÃO WEB] número inteiro vindo da página (texto inválido dava erro 500)."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ErroEscala(f"Identificação inválida para {nome}. Atualize a página.")


def _hora(valor, nome):
    try:
        return R.hora_ou_none(valor)
    except ValueError:
        raise ErroEscala(f"'{valor}' não é um horário válido para {nome}. Use HH:MM (ex.: 08:00).")


def _h(v):
    return R.formatar_hora_curta(v)


def _pessoa(chave):
    """'func:12' / 'free:3' -> ('func', 12)."""
    try:
        tipo, num = str(chave or '').split(':')
        if tipo in ('func', 'free'):
            return tipo, int(num)
    except ValueError:
        pass
    raise ErroEscala("Escolha um funcionário ou freelancer.")


def _turno_json(t, pagos, fixos=None):
    tipo = 'func' if t.FuncionarioID else ('free' if getattr(t, 'FreelancerID', None) else None)
    cfg = (fixos or {}).get(t.FuncionarioID) if t.FuncionarioID else None
    return {'id': t.EscalaID, 'posicao_id': t.PosicaoID, 'tipo': tipo,
            'fixo': bool(cfg and cfg['posicao_id'] == t.PosicaoID),       # [ESCALA FIXA] 📌
            'pessoa': f"{tipo}:{t.FuncionarioID or t.FreelancerID}" if tipo else None,
            'nome': t.NomePessoa or '', 'entrada': _h(t.HorarioEntrada), 'saida': _h(t.HorarioSaida),
            'int_ini': _h(t.InicioIntervalo), 'int_fim': _h(t.FimIntervalo), 'foco': t.FocoDoDia or '',
            'tipo_diaria': getattr(t, 'TipoDiaria', None) if tipo == 'free' else None,
            'pago': t.EscalaID in pagos}


def _indisponibilidade(funcionarios, d):
    """{FuncionarioID: motivo ou None} (férias/afastamento, folga fixa, domingo de folga)."""
    return {f.FuncionarioID: database.motivo_indisponibilidade(
        getattr(f, 'DiaDeFolga', None), getattr(f, 'DomingoFolgaMensal', None),
        getattr(f, 'DataInicioAfastamento', None), getattr(f, 'DataFimAfastamento', None), d)
        for f in funcionarios}


def _config_pagamento():
    try:
        return database.buscar_config_pagamento_freelancer()
    except Exception as e:
        logger.warning(f"Valores dos freelancers não lidos (usando o padrão): {e}")
        return dict(database.CONFIG_PAGAMENTO_PADRAO)


def _feriado(data_txt):
    try:
        return database.nome_feriado(data_txt)
    except Exception as e:
        logger.warning(f"Feriados não consultados: {e}")
        return None


def _jornada_horas():
    cfg = database.buscar_configuracoes_escala()
    try:
        return float(getattr(cfg, 'DuracaoJornadaPadrao', 8) or 8)
    except (TypeError, ValueError):
        return 8.0


# ------------------------------------------------------------------------------
# O dia
# ------------------------------------------------------------------------------
def dia(data_txt):
    """Tudo o que a tela precisa para mostrar um dia."""
    data, d = _data(data_txt)
    _exigir_banco()
    cfg_fixos = {}
    try:                                     # [ESCALA FIXA] o fixo entra sozinho (de hoje em diante, menos na folga)
        if d >= date.today():
            escala_fixa.aplicar([d])
        cfg_fixos = escala_fixa.fixos()
    except Exception as e:
        logger.error(f"Escala fixa: não consegui aplicar os fixos em {data}: {e}", exc_info=True)
    posicoes = database.listar_posicoes_loja()
    escala = database.buscar_escala_do_dia(data)
    funcionarios = list(database.listar_funcionarios())
    freelancers = list(database.listar_freelancers())
    motivos = _indisponibilidade(funcionarios, d)
    indisponivel = motivos.get
    folgas = {f.FuncionarioID: R.folga_do_funcionario(f) for f in funcionarios}
    fixos = {}
    for f in funcionarios:
        if getattr(f, 'PosicaoPadraoID', None):
            fixos.setdefault(f.PosicaoPadraoID, (f.FuncionarioID, f.NomeCompleto, f.DiaDeFolga))
    dia_db = R.dia_semana_banco(d)
    escalados = {t.FuncionarioID for ts in escala.values() for t in ts if t.FuncionarioID}
    pagos = database.turnos_pagos(data_escala=data)
    tela = database.tamanho_mapa_escala() or (R.MAPA_IMAGEM_LARGURA, R.MAPA_IMAGEM_ALTURA)

    lista_pos = []
    for pos_id, nome, cx, cy, _ativo, setor in posicoes:
        try:
            vx, vy = float(cx), float(cy)
        except (TypeError, ValueError):
            continue                         # coordenada corrompida: o PC também pula
        x, y = (vx, vy) if vx > 1.0 else (vx * tela[0], vy * tela[1])
        turnos = escala.get(pos_id, [])
        cor, linhas = R.rotulo_e_cor_posicao(nome, turnos, folgas, indisponivel, dia_db,
                                             None if turnos else fixos.get(pos_id), False, escalados)
        tj = [_turno_json(t, pagos, cfg_fixos) for t in turnos]
        if turnos and len(linhas) == len(turnos) + 1:          # [ESCALA FIXA] 📌 no nome de quem é fixo aqui
            linhas = [linhas[0]] + [('📌 ' if j['fixo'] else '') + l for j, l in zip(tj, linhas[1:])]
        lista_pos.append({'id': pos_id, 'nome': nome, 'setor': setor or '', 'x': round(x, 1), 'y': round(y, 1),
                          'cor': cor, 'linhas': linhas[1:], 'turnos': tj})

    alertas = [{'nivel': n, 'texto': t} for n, t in R.analisar_escala_do_dia(escala, posicoes, indisponivel)]

    # [DEPURAÇÃO WEB] turnos em posições REMOVIDAS do mapa: antes só apareciam num alerta e não
    # havia como vê-los nem excluí-los (mas iam no Telegram/WhatsApp). Agora vêm numa lista à parte.
    ativos = {p[0] for p in posicoes}
    ids_fora = [pid for pid in escala if pid not in ativos and escala[pid]]
    nomes_fora = database.nomes_posicoes_loja(ids_fora) if ids_fora else {}
    fora_do_mapa = [{'id': pid, 'nome': nomes_fora.get(pid) or f"Posição {pid}", 'setor': '', 'removida': True,
                     'cor': R.COR_SEM_PESSOA, 'linhas': [f"{t.NomePessoa or '?'} ({_h(t.HorarioEntrada)}-{_h(t.HorarioSaida)})"
                                                          for t in escala[pid]],
                     'turnos': [_turno_json(t, pagos) for t in escala[pid]]} for pid in ids_fora]

    # Resumo (o mesmo do PC)
    feriado = _feriado(data)
    titulo = R.DIAS_SEMANA[d.weekday()].capitalize() + (" (hoje)" if d == date.today() else "") \
        + (f" · 🎉 {feriado}" if feriado else "")
    todos = [t for lista in escala.values() for t in lista]
    frees = [t for t in todos if getattr(t, 'FreelancerID', None)]
    vazias = len([p for p in posicoes if not escala.get(p[0])])
    resumo = f"👥 {len([t for t in todos if t.NomePessoa])} na escala   ⭕ {vazias} posição(ões) vazia(s)"
    cfg_pag = _config_pagamento()
    if frees:
        cfg = cfg_pag
        custo = 0
        for t in frees:
            calc = database.calcular_pagamento_turno(t.HorarioEntrada, t.HorarioSaida, cfg, 0, data,
                                                     getattr(t, 'TipoDiaria', None), t.HorarioEntrada,
                                                     t.HorarioSaida, feriado)
            custo += calc['Total'] if calc else 0
        resumo += f"   🧑‍🍳 {len(frees)} freelancer(s): {R.fmt_reais(custo)}"
        if pagos:
            resumo += f" ({len(pagos)} pago(s))"

    horarios = database.buscar_horarios_ocupacao_hoje(data, 0)
    setores = sorted({p[5] for p in posicoes if p[5]}, key=str.lower)
    fluxo = {'horas': R.HORAS_FLUXO, 'setores': setores,
             'series': {s: R.fluxo_por_hora(horarios, s) for s in [R.SETOR_TODOS] + setores}}

    # [BUSCA DE PESSOA] onde cada um já está hoje, a folga do cadastro e o fixo (para a busca da tela)
    nomes_pos = {p[0]: p[1] for p in posicoes}
    nomes_pos.update({p['id']: p['nome'] for p in fora_do_mapa})
    hoje_em = {}
    for pid, ts in escala.items():
        for t in ts:
            chave = f"func:{t.FuncionarioID}" if t.FuncionarioID else (f"free:{t.FreelancerID}" if getattr(t, 'FreelancerID', None) else None)
            if chave:
                hoje_em.setdefault(chave, []).append(f"{nomes_pos.get(pid, '?')} {_h(t.HorarioEntrada)}–{_h(t.HorarioSaida)}")
    pessoas = []
    for f in funcionarios:
        folga = motivos.get(f.FuncionarioID) or (folgas.get(f.FuncionarioID) == dia_db and "Dia de folga")
        chave = f"func:{f.FuncionarioID}"
        cfg = cfg_fixos.get(f.FuncionarioID)
        pessoas.append({'chave': chave, 'tipo': 'func', 'nome': f.NomeCompleto,
                        'rotulo': f"[Fixo] {f.NomeCompleto}" + (" [FOLGA]" if folga else ""),
                        'folga': str(folga).replace('⚠️', '').strip().rstrip('!') if folga else None,
                        'folga_semana': escala_fixa.texto_folga(f), 'hoje_em': hoje_em.get(chave, []),
                        'fixo': dict(cfg, posicao=nomes_pos.get(cfg['posicao_id']) or f"Posição {cfg['posicao_id']}",
                                     dias_texto=escala_fixa._resumo_dias(cfg['dias'])) if cfg else None})
    for fr in freelancers:
        chave = f"free:{fr.FreelancerID}"
        pessoas.append({'chave': chave, 'tipo': 'free', 'nome': fr.Nome,
                        'rotulo': f"[Free] {fr.Nome}", 'folga': None, 'hoje_em': hoje_em.get(chave, []), 'fixo': None})

    # [FOLHA × FATURAMENTO] clima do dia e o que aconteceu em dias parecidos (ajuda a decidir os freelancers)
    try:
        import folha_faturamento
        dica = folha_faturamento.dica_escala(d)
    except Exception as e:
        logger.warning(f"Escala: dica do clima indisponível ({e})")
        dica = None

    return {'data': data, 'titulo': titulo, 'hoje': d == date.today(), 'feriado': feriado, 'clima': dica,
            'tela': {'largura': tela[0], 'altura': tela[1],
                     'imagem_largura': R.MAPA_IMAGEM_LARGURA, 'imagem_altura': R.MAPA_IMAGEM_ALTURA},
            'posicoes': lista_pos, 'fora_do_mapa': fora_do_mapa, 'alertas': alertas, 'resumo': resumo, 'fluxo': fluxo,
            'setor_todos': R.SETOR_TODOS, 'pessoas': pessoas, 'habituais': _habituais(d),
            'config': {'jornada_horas': _jornada_horas(),
                       'limite_curta_min': int(cfg_pag.get('LimiteCurtaMinutos', 420))}}


DIAS_HABITUAIS = 60


def _habituais(d):
    """
    [BUSCA DE PESSOA] {PosicaoID: [{'chave', 'vezes', 'entrada', 'saida', 'ultima'}]}: quem mais trabalhou em cada
    posição nos últimos 60 dias (aparece primeiro na busca, com o horário da última vez).
    """
    conn = database.get_db_connection()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT PosicaoID, FuncionarioID, FreelancerID, DataEscala, HorarioEntrada, HorarioSaida FROM EscalaDiaria "
                    "WHERE DataEscala >= ? AND DataEscala < ? AND (FuncionarioID IS NOT NULL OR FreelancerID IS NOT NULL)",
                    (d - timedelta(days=DIAS_HABITUAIS)).strftime('%Y-%m-%d'), d.strftime('%Y-%m-%d'))
        linhas = cur.fetchall()
    except Exception as e:
        logger.warning(f"Escala: habituais por posição indisponíveis ({e})")
        return {}
    finally:
        conn.close()
    por_pos = {}
    for pid, fid, frid, data_e, ent, sai in linhas:
        chave = f"func:{fid}" if fid else f"free:{frid}"
        x = por_pos.setdefault(pid, {}).setdefault(chave, {'chave': chave, 'vezes': 0, 'ultima': '', 'entrada': '', 'saida': ''})
        x['vezes'] += 1
        data_txt = str(data_e)[:10]
        if data_txt >= x['ultima']:
            x.update(ultima=data_txt, entrada=_h(ent), saida=_h(sai))
    return {pid: sorted(v.values(), key=lambda x: (-x['vezes'], x['chave']))[:6] for pid, v in por_pos.items()}


def previa_freelancer(dados):
    """Valor do turno do freelancer (o mesmo texto do PC) e a diária sugerida pela duração."""
    data, _d = _data(dados.get('data'))
    try:
        ent = R.hora_ou_none(dados.get('entrada'))
        sai = R.hora_ou_none(dados.get('saida'))
    except ValueError:
        ent = sai = None
    cfg = _config_pagamento()
    faixa = R.faixa_turno(ent, sai) if ent and sai else None
    sugerida = None
    if faixa:
        sugerida = 'curta' if faixa[1] - faixa[0] <= int(cfg.get('LimiteCurtaMinutos', 420)) else 'longa'
    tipo = dados.get('tipo_diaria') if dados.get('tipo_diaria') in ('curta', 'longa') else sugerida
    if not faixa:
        return {'texto': "💰 Preencha entrada e saída para ver o valor.", 'sugerida': None, 'pago': False}
    calc = database.calcular_pagamento_turno(ent, sai, cfg, 0, data, tipo, ent, sai, _feriado(data))
    escala_id = _id(dados['escala_id']) if dados.get('escala_id') else None
    pago = bool(escala_id) and escala_id in database.turnos_pagos([escala_id])
    texto = ("💰 " + R.texto_calculo(calc)) if calc else "💰 Preencha entrada e saída para ver o valor."
    return {'texto': texto + ("   ✅ JÁ PAGO" if pago else ""), 'sugerida': sugerida, 'pago': pago}


# ------------------------------------------------------------------------------
# Turnos
# ------------------------------------------------------------------------------
def salvar_turno(dados, usuario):
    data, d = _data(dados.get('data'))
    try:
        pos_id = int(dados.get('posicao_id'))
    except (TypeError, ValueError):
        raise ErroEscala("Escolha a posição no mapa.")
    escala_id = _id(dados['escala_id']) if dados.get('escala_id') else None
    tipo, pessoa_id = _pessoa(dados.get('pessoa'))
    h_ent = _hora(dados.get('entrada'), "a entrada")
    h_sai = _hora(dados.get('saida'), "a saída")
    h_ini = _hora(dados.get('int_ini'), "o início do intervalo")
    h_fim = _hora(dados.get('int_fim'), "o fim do intervalo")
    foco = str(dados.get('foco') or '').strip()[:500]
    if not h_ent or not h_sai:
        raise ErroEscala("Preencha os horários de Entrada e Saída.")
    if bool(h_ini) != bool(h_fim):
        raise ErroEscala("Preencha o início E o fim do intervalo (ou deixe os dois vazios).")
    if h_ent == h_sai:
        raise ErroEscala("Entrada e saída não podem ser iguais.")
    prob = R.problema_intervalo(h_ent, h_sai, h_ini, h_fim)
    if prob:
        raise ErroEscala(f"O {prob} ({h_ent} às {h_sai}).")

    _exigir_banco()
    posicoes = database.listar_posicoes_loja()
    nomes_pos = {p[0]: p[1] for p in posicoes}
    if pos_id not in nomes_pos:
        raise ErroEscala("Esta posição não está mais no mapa. Atualize a página.", 409)
    if tipo == 'func':
        lista = {f.FuncionarioID: f.NomeCompleto for f in database.listar_funcionarios()}
    else:
        lista = {f.FreelancerID: f.Nome for f in database.listar_freelancers()}
    if pessoa_id not in lista:
        raise ErroEscala("Pessoa não encontrada (foi excluída?). Atualize a página.", 409)
    nome_pessoa = lista[pessoa_id]

    escala = database.buscar_escala_do_dia(data)          # lida AGORA do banco
    turno_antigo = None
    if escala_id:
        turno_antigo = next((t for ts in escala.values() for t in ts if t.EscalaID == escala_id), None)
        if not turno_antigo:
            raise ErroEscala("Este turno não existe mais (foi excluído ou a escala foi copiada). Atualize a página.", 409)

    pessoa = (tipo, pessoa_id)
    erros, avisos = R.conflitos_ao_salvar(escala, escala_id, pessoa, h_ent, h_sai, nome_pessoa, nomes_pos)
    if erros:
        raise ErroEscala("\n".join(erros) + "\n\nAjuste os horários ou escolha outra pessoa.", 409)
    outro = R.conflito_na_posicao(escala, pos_id, escala_id, h_ent, h_sai)
    if outro:
        # [DEPURAÇÃO WEB] antes: "Não foi possível salvar... provável conflito" (sem dizer com quem),
        # e turno que passa da meia-noite nem era conferido pelo banco
        raise ErroEscala(f"Já tem {outro.NomePessoa or 'alguém'} em {nomes_pos[pos_id]} das "
                         f"{_h(outro.HorarioEntrada)} às {_h(outro.HorarioSaida)}: os horários se cruzam.\n\n"
                         "Ajuste os horários ou use outra posição.", 409)

    confirmados = set(dados.get('confirmar') or [])
    perguntas = []
    pessoa_mudou = turno_antigo is None or R.chave_pessoa(turno_antigo) != pessoa
    if tipo == 'func' and pessoa_mudou and 'folga' not in confirmados:
        motivo = database.verificar_status_disponibilidade(pessoa_id, data)
        if motivo:
            perguntas.append({'chave': 'folga', 'titulo': "Funcionário indisponível",
                              'texto': f"{nome_pessoa}: {str(motivo).replace('⚠️', '').strip()}\n\nEscalar mesmo assim?"})
    if avisos and 'jornada' not in confirmados:
        perguntas.append({'chave': 'jornada', 'titulo': "Jornada longa",
                          'texto': "\n".join(avisos) + "\n\nSalvar mesmo assim?"})
    if escala_id and 'pago' not in confirmados and database.turnos_pagos([escala_id]):
        perguntas.append({'chave': 'pago', 'titulo': "Turno já pago", 'texto': (
            "Este turno de freelancer já foi marcado como PAGO.\n\n"
            "Mudar a escala NÃO altera o valor pago (fica registrado como foi pago).\n"
            "Se precisar refazer o valor, use '💰 Pagamentos' → '↩️ Desfazer pagamento'.\n\n"
            "Salvar a alteração na escala mesmo assim?")})
    if perguntas:
        return {'perguntas': perguntas}

    func_id, free_id = (pessoa_id, None) if tipo == 'func' else (None, pessoa_id)
    if not database.salvar_escala_dia_v3(escala_id, data, pos_id, func_id, free_id, h_ent, h_sai, h_ini, h_fim, foco):
        raise ErroEscala("Não foi possível salvar.\n\nProvável conflito de horário com outro turno desta "
                         "posição (ou falha no banco).", 409)
    extra = ""
    if func_id and turno_antigo is not None and getattr(turno_antigo, 'TipoDiaria', None):
        # [DEPURAÇÃO WEB] o turno era de freelancer e virou de funcionário: a diária curta/longa
        # escolhida para o freelancer não vale mais
        database.definir_tipo_diaria_escala(escala_id, None)
    if free_id:
        tipo_d = dados.get('tipo_diaria') if dados.get('tipo_diaria') in ('curta', 'longa') else None
        eid = escala_id or next((t.EscalaID for t in database.buscar_escala_do_dia(data).get(pos_id, [])
                                 if t.FreelancerID == free_id and _h(t.HorarioEntrada) == h_ent), None)
        if eid:
            ok_t, msg_t = database.definir_tipo_diaria_escala(eid, tipo_d)
            extra = (f", diária {tipo_d}" if tipo_d else "") if ok_t else f" ({msg_t})"
    logger.info(f"[GESTÃO] {usuario.get('nome')}: turno de {nome_pessoa} em {nomes_pos[pos_id]} {data} "
                f"{h_ent}-{h_sai} {'atualizado' if escala_id else 'criado'}.")
    mensagem = f"Turno de {nome_pessoa} salvo ({h_ent}–{h_sai}{extra})."
    sem_folga = False
    if func_id and dados.get('fixo') in (True, False):          # [ESCALA FIXA] 📌 marcado/desmarcado no painel
        try:
            cfg = escala_fixa.fixos().get(func_id)
            if dados['fixo'] and not (cfg and cfg['posicao_id'] == pos_id and cfg['entrada'] == h_ent and cfg['saida'] == h_sai
                                      and cfg['int_ini'] == (h_ini or '') and cfg['int_fim'] == (h_fim or '')):
                r = escala_fixa.salvar({'funcionario_id': func_id, 'posicao_id': pos_id, 'entrada': h_ent, 'saida': h_sai,
                                        'int_ini': h_ini, 'int_fim': h_fim}, usuario)
                mensagem += "\n" + r['mensagem']
                sem_folga = r['sem_folga']
            elif not dados['fixo'] and cfg and cfg['posicao_id'] == pos_id:
                mensagem += "\n" + escala_fixa.remover(func_id, usuario)['mensagem']
        except escala_fixa.ErroFixo as e:
            mensagem += f"\n⚠️ O turno foi salvo, mas o fixo não: {e}"
    return {'ok': True, 'mensagem': mensagem, 'sem_folga': sem_folga}


def excluir_turno(escala_id, dados, usuario):
    data, _d = _data(dados.get('data'))
    _exigir_banco()
    escala = database.buscar_escala_do_dia(data)
    turno = next((t for ts in escala.values() for t in ts if t.EscalaID == escala_id), None)
    if not turno:
        raise ErroEscala("Este turno não existe mais. Atualize a página.", 409)
    if 'pago' not in set(dados.get('confirmar') or []) and database.turnos_pagos([escala_id]):
        return {'perguntas': [{'chave': 'pago', 'titulo': "Turno já pago", 'texto': (
            f"Remover a escalação de {turno.NomePessoa or '?'}?\n\n⚠️ Este turno já foi PAGO. O pagamento continua "
            "registrado em '💰 Pagamentos' (marcado como 'turno excluído').")}]}
    if not database.excluir_turno_escala(escala_id):
        raise ErroEscala("Falha ao excluir o registro.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: excluiu o turno {escala_id} de {turno.NomePessoa} em {data}.")
    return {'ok': True, 'mensagem': f"Turno de {turno.NomePessoa or '?'} excluído."}


def copiar(dados, usuario):
    data, d = _data(dados.get('data'))
    if dados.get('origem') not in ('ontem', 'semana'):
        raise ErroEscala("Escolha copiar de ontem ou da semana passada.")
    origem = d - timedelta(days=1 if dados.get('origem') == 'ontem' else 7)
    _exigir_banco()
    if 'substituir' not in set(dados.get('confirmar') or []) and any(database.buscar_escala_do_dia(data).values()):
        return {'perguntas': [{'chave': 'substituir', 'titulo': "Atenção", 'texto': (
            f"Já existem pessoas escaladas para {R.fmt_data_br(d, True)}.\n\n"
            "Se você copiar uma escala anterior, o preenchimento atual SERÁ APAGADO.\n\nDeseja continuar?")}]}
    ok, msg = database.copiar_escala_dia(origem.strftime('%Y-%m-%d'), data)
    if not ok:
        raise ErroEscala(msg)
    try:                                     # [ESCALA FIXA] o dia foi refeito: confere os fixos de novo nele
        escala_fixa.esquecer_dia(data)
        if d >= date.today():
            escala_fixa.aplicar([d])
    except Exception as e:
        logger.error(f"Escala fixa: conferir os fixos depois de copiar {data} falhou: {e}", exc_info=True)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: copiou a escala de {origem} para {data}.")
    return {'ok': True, 'mensagem': f"Escala de {R.fmt_data_br(origem, True)} copiada para {R.fmt_data_br(d, True)}."}


# ------------------------------------------------------------------------------
# [ESCALA FIXA] Funcionários fixos (todo dia na mesma posição e horário, menos na folga)
# ------------------------------------------------------------------------------
def _fixo(funcao, *args):
    try:
        return funcao(*args)
    except escala_fixa.ErroFixo as e:
        raise ErroEscala(str(e), e.status)


def fixos_listar():
    _exigir_banco()
    return {'fixos': _fixo(escala_fixa.listar), 'dias_a_frente': escala_fixa.DIAS_A_FRENTE}


def fixo_salvar(dados, usuario):
    _exigir_banco()
    return _fixo(escala_fixa.salvar, dados, usuario)


def fixo_remover(funcionario_id, usuario):
    _exigir_banco()
    return _fixo(escala_fixa.remover, funcionario_id, usuario)


def fixo_folga(funcionario_id, dados, usuario):
    _exigir_banco()
    return _fixo(escala_fixa.definir_folga, funcionario_id, dados.get('dia_folga'), usuario)


# ------------------------------------------------------------------------------
# Intervalos
# ------------------------------------------------------------------------------
def gerar_intervalos(dados, usuario):
    import calculadora_logica
    data, d = _data(dados.get('data'))
    _exigir_banco()
    escala = database.buscar_escala_do_dia(data)
    pessoas, por_turno = R.pessoas_para_intervalos(escala, database.listar_posicoes_loja(), d)
    if not pessoas:
        raise ErroEscala("Não há funcionários escalados com horário de entrada/saída para calcular.")
    ja_tem = [t for t in por_turno.values() if t.InicioIntervalo and t.FimIntervalo]
    if ja_tem and 'substituir' not in set(dados.get('confirmar') or []):
        return {'perguntas': [{'chave': 'substituir', 'titulo': "Substituir intervalos?", 'texto': (
            f"{len(ja_tem)} turno(s) deste dia já têm intervalo (alguns podem ter sido ajustados à mão).\n\n"
            "O cálculo automático vai SUBSTITUIR esses intervalos.\n\nContinuar?")}]}
    try:
        sugestoes, erros = calculadora_logica.calcular_intervalos_automaticos(pessoas, R.dia_semana_banco(d))
    except Exception as e:
        logger.exception(f"Falha na calculadora de intervalos: {e}")
        raise ErroEscala(f"Falha na calculadora de intervalos: {e}", 500)
    if sugestoes and not R.gravar_intervalos(sugestoes):
        raise ErroEscala("Falha ao gravar os intervalos. Nenhuma alteração foi salva.", 500)
    texto = ("🪄 Intervalos automáticos:\n" + "\n".join(erros)) if erros \
        else "🪄 Intervalos automáticos: cálculo concluído sem conflitos."
    logger.info(f"[GESTÃO] {usuario.get('nome')}: intervalos automáticos em {data} ({len(sugestoes)} gravado(s)).")
    return {'ok': True, 'aplicados': len(sugestoes), 'erros': erros, 'texto': texto}


def listar_intervalos(data_txt):
    data, _d = _data(data_txt)
    _exigir_banco()
    linhas = []
    for r in database.listar_escala_detalhada_ordenada(data) or []:
        ini, fim = _h(r[7]), _h(r[8])
        linhas.append({'id': r[0], 'setor': r[2], 'posicao': r[3], 'nome': r[4] or '?', 'entrada': _h(r[5]),
                       'saida': _h(r[6]), 'int_ini': ini, 'int_fim': fim, 'definido': bool(ini and fim)})
    return {'data': data, 'turnos': linhas}


def salvar_intervalo(dados, usuario):
    data, _d = _data(dados.get('data'))
    try:
        escala_id = int(dados.get('escala_id'))
    except (TypeError, ValueError):
        raise ErroEscala("Escolha o turno na lista.")
    _exigir_banco()
    ini = _hora(dados.get('int_ini'), "o início do intervalo")
    fim = _hora(dados.get('int_fim'), "o fim do intervalo")
    if bool(ini) != bool(fim):
        raise ErroEscala("Preencha o início E o fim do intervalo (ou deixe os dois vazios para remover).")
    linha = next((r for r in database.listar_escala_detalhada_ordenada(data) or [] if r[0] == escala_id), None)
    if not linha:
        raise ErroEscala("Este turno não existe mais. Atualize a lista.", 409)
    h_ent, h_sai = _h(linha[5]), _h(linha[6])
    prob = R.problema_intervalo(h_ent, h_sai, ini, fim)
    if prob:
        raise ErroEscala(f"O {prob} ({h_ent} às {h_sai}).")
    if not database.salvar_escala_dia_v3(escala_id, data, linha[1], linha[9], linha[10], h_ent or None, h_sai or None,
                                         ini, fim, linha[11]):
        raise ErroEscala("Falha ao salvar. Verifique conflitos.", 409)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: intervalo de {linha[4]} em {data}: {ini or '-'}–{fim or '-'}.")
    return {'ok': True, 'int_ini': ini or '', 'int_fim': fim or ''}


# ------------------------------------------------------------------------------
# Envios
# ------------------------------------------------------------------------------
def enviar_telegram(dados, usuario):
    import notificador_telegram
    data, _d = _data(dados.get('data'))
    grupo = getattr(config, 'TODOS_FUNCIONARIOS_GROUP_ID', None)
    if not grupo:
        # [DEPURAÇÃO WEB] sem o grupo no config.py dava "Erro no servidor" sem explicação
        raise ErroEscala("O grupo do Telegram (TODOS_FUNCIONARIOS_GROUP_ID) não está no config.py.", 503)
    _exigir_banco()
    texto = database.gerar_relatorio_escala_texto(data)
    if not texto or texto.startswith(("Erro", "Nenhuma escala")):
        raise ErroEscala(texto or "Escala vazia.")
    resposta = notificador_telegram.enviar_mensagem(grupo, texto)
    if not (resposta and resposta.get('ok')):
        raise ErroEscala(f"O Telegram recusou o envio: {resposta}", 502)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: escala de {data} enviada ao grupo do Telegram.")
    return {'ok': True, 'mensagem': "Escala enviada para o grupo do Telegram! ✅"}


_envios = {}
_trava_envios = threading.Lock()


def previa_whatsapp(data_txt):
    data, _d = _data(data_txt)
    _exigir_banco()
    lista = R.lista_envio_whatsapp(database.buscar_escala_do_dia(data), database.listar_posicoes_loja())
    return {'pessoas': len(lista), 'nomes': [i['nome'] for i in lista]}


def iniciar_whatsapp(dados, usuario):
    """Começa o envio em segundo plano (pode fechar a página). Devolve o andamento."""
    import notificador_whatsapp
    data, _d = _data(dados.get('data'))
    _exigir_banco()
    with _trava_envios:
        for job in list(_envios.values()):              # limpa os antigos
            if job['terminado'] and time.time() - job['criado'] > 3600:
                _envios.pop(job['id'], None)
        andando = next((j for j in _envios.values() if j['data'] == data and not j['terminado']), None)
        if andando:
            return dict(andando)                          # não manda 2 vezes
        lista = R.lista_envio_whatsapp(database.buscar_escala_do_dia(data), database.listar_posicoes_loja())
        if not lista:
            raise ErroEscala("Nenhuma pessoa com telefone encontrada na escala deste dia.")
        job = {'id': uuid.uuid4().hex[:12], 'data': data, 'total': len(lista), 'feitos': 0, 'enviados': 0,
               'erros': 0, 'terminado': False, 'por': usuario.get('nome'), 'criado': time.time()}
        _envios[job['id']] = job

    def progresso(enviados, erros):
        job.update(enviados=enviados, erros=erros, feitos=job['feitos'] + 1)

    def rodar():
        try:
            enviados, erros = R.enviar_confirmacoes_whatsapp(lista, data, notificador_whatsapp.enviar_mensagem_whatsapp,
                                                            database.buscar_descricao_setor, progresso=progresso)
            job.update(enviados=enviados, erros=erros)
        except Exception as e:
            logger.exception(f"[GESTÃO] Envio de WhatsApp da escala de {data} falhou: {e}")
            job['erros'] = job['total'] - job['enviados']
        finally:
            job['terminado'] = True
            logger.info(f"[GESTÃO] {job['por']}: WhatsApp da escala de {data}: {job['enviados']} enviado(s), "
                        f"{job['erros']} falha(s).")
    threading.Thread(target=rodar, daemon=True).start()
    return dict(job)


def andamento_whatsapp(job_id):
    job = _envios.get(job_id)
    if not job:
        raise ErroEscala("Envio não encontrado (o servidor reiniciou?).", 404)
    return dict(job)

# ==============================================================================
# == gestao_folgas.py - [5x2] Gestão › 👥 Equipe › 📅 Folgas ======================
# ==============================================================================
# A tela das folgas dos fixos (a regra fica no folgas.py):
#   - grade de 1 a 8 semanas: quem folga em cada dia, horas de cada semana, quantos trabalham por dia;
#   - o PADRÃO de folgas de cada um, com data de início (5x2 fixo, rodízio de semanas, ou a folga do cadastro);
#   - TROCAS de um dia (dar folga / vai trabalhar / voltar ao padrão);
#   - REGRAS (limite de horas por semana a partir de cada data, domingo, dias seguidos, mínimo de pessoas por setor);
#   - AVISOS: folgas na semana, dias seguidos sem folga, domingos seguidos trabalhando, horas acima do limite,
#     dia com menos gente que o mínimo e gente escalada na folga.
# Ao mudar padrão ou troca, a escala automática dos fixos se acerta sozinha (de amanhã em diante).
# Perguntas ("Salvar mesmo assim?") voltam como {'perguntas': [...]}, igual às outras telas da Gestão.
# ==============================================================================
import logging
from datetime import date, timedelta

import database
import escala_regras as R
import folgas as FG
from gestao_escala import ErroEscala, _data, _exigir_banco, _id

logger = logging.getLogger(__name__)

SEMANAS_PADRAO, SEMANAS_MAX = 4, 8
DIAS_TELA = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
LIMITE_ALERTAS = 60


def _confirmados(dados):
    return set(dados.get('confirmar') or [])


def _br(d, dia=False):
    return f"{DIAS_TELA[d.weekday()].lower()} {d:%d/%m}" if dia else f"{d:%d/%m}"


def _horas(minutos):
    h, m = divmod(int(round(minutos)), 60)
    return f"{h}h{m:02d}" if m else f"{h}h"


def _minutos_turno(ent, sai, ini=None, fim=None):
    """Minutos de trabalho do turno (sem o intervalo)."""
    fx = R.faixa_turno(ent, sai)
    if not fx:
        return 0
    total = fx[1] - fx[0]
    iv = R.faixa_turno(ini, fim) if ini and fim else None
    if iv:
        total -= iv[1] - iv[0]
    return max(total, 0)


def _fixos_escala():
    try:
        import escala_fixa
        return escala_fixa.fixos()
    except Exception as e:
        logger.warning(f"Folgas: fixos da escala indisponíveis ({e})")
        return {}


def _ressincronizar(funcionario_id):
    """A escala automática do fixo se acerta (de amanhã em diante, só nos dias que ninguém mexeu)."""
    try:
        import escala_fixa
        if funcionario_id in escala_fixa.fixos():
            return escala_fixa.ressincronizar(funcionario_id)
    except Exception as e:
        logger.error(f"Folgas: não consegui acertar a escala automática do funcionário {funcionario_id}: {e}", exc_info=True)
    return None


def _turnos(ini, fim):
    """{(FuncionarioID, data): [(minutos, setor)]} da escala do período."""
    conn = database.get_db_connection()
    if not conn:
        raise ErroEscala("Sem conexão com o banco de dados.", 503)
    try:
        cur = conn.cursor()
        cur.execute("""SELECT E.DataEscala, E.FuncionarioID, E.HorarioEntrada, E.HorarioSaida, E.InicioIntervalo, E.FimIntervalo,
                              PL.Setor
                       FROM EscalaDiaria E LEFT JOIN PosicoesLoja PL ON PL.PosicaoID = E.PosicaoID
                       WHERE E.FuncionarioID IS NOT NULL AND E.DataEscala >= ? AND E.DataEscala <= ?""",
                    ini.isoformat(), fim.isoformat())
        saida = {}
        for d, fid, ent, sai, ii, fi, setor in cur.fetchall():
            saida.setdefault((int(fid), FG.como_data(d)), []).append((_minutos_turno(ent, sai, ii, fi), (setor or '').strip()))
        return saida
    finally:
        conn.close()


def _setores():
    nomes = {(p[5] or '').strip() for p in database.listar_posicoes_loja()}
    return sorted(n for n in nomes if n)


def _funcionario(fid):
    f = database.buscar_funcionario_por_id(fid)
    if not f:
        raise ErroEscala("Funcionário não encontrado (foi excluído?). Atualize a página.", 409)
    return f


def _maior_sequencia(trabalha):
    """[(data, trabalha?)] em ordem -> (tamanho, início, fim) da maior sequência de dias trabalhando."""
    melhor, atual, ini = (0, None, None), 0, None
    for d, t in trabalha:
        if t:
            if atual == 0:
                ini = d
            atual += 1
            if atual > melhor[0]:
                melhor = (atual, ini, d)
        else:
            atual = 0
    return melhor


# ------------------------------------------------------------------------------
# A grade
# ------------------------------------------------------------------------------
def grade(dados):
    _exigir_banco()
    hoje = date.today()
    ini = FG.segunda(_data(dados['de'])[1] if dados.get('de') else hoje)
    try:
        semanas = min(max(int(dados.get('semanas') or SEMANAS_PADRAO), 1), SEMANAS_MAX)
    except (TypeError, ValueError):
        semanas = SEMANAS_PADRAO
    dias = [ini + timedelta(days=k) for k in range(7 * semanas)]
    fim = dias[-1]
    padroes, trocas, regras = FG.memoria(forcar=True)
    cfgs = _fixos_escala()
    pos_setor = {p[0]: (p[5] or '').strip() for p in database.listar_posicoes_loja()}
    turnos = _turnos(ini, fim)
    feriados = {}
    for ano in range(ini.year, fim.year + 1):
        try:
            feriados.update({d: n for d, n in database.listar_feriados(ano)})
        except Exception:
            pass
    max_seguidos = int(regras.get('max_dias_seguidos') or 0)
    n_domingos = int(regras.get('domingo_semanas') or 0)
    minimos = regras.get('minimos') or {}
    funcs = sorted(database.listar_funcionarios(), key=lambda f: str(f.NomeCompleto or '').lower())
    cobertura = {d: {} for d in dias}
    pessoas, alertas = [], []

    def situ(f, d):
        return FG.situacao(f, d, padroes=padroes, trocas=trocas)

    for f in funcs:
        fid = int(f.FuncionarioID)
        cfg = cfgs.get(fid)
        tem_padrao = bool(padroes.get(fid))
        celulas, na_escala = [], bool(cfg) or tem_padrao
        for d in dias:
            s = situ(f, d)
            troca = trocas.get((fid, d))
            ts = turnos.get((fid, d), [])
            previsto = False
            if ts:
                minutos, setor, na_escala = sum(m for m, _ in ts), ts[0][1], True
            elif not s and cfg and d >= hoje and R.dia_semana_banco(d) in cfg['dias']:
                minutos = _minutos_turno(cfg['entrada'], cfg['saida'], cfg['int_ini'], cfg['int_fim'])
                setor, previsto = pos_setor.get(cfg['posicao_id'], ''), True
            else:
                minutos, setor = 0, None
            estado = 'A' if s and s['tipo'] == 'afastamento' else ('F' if s else 'T')
            conflito = bool(s) and bool(ts)
            if estado == 'T' and setor is not None and minutos:
                cobertura[d][setor or 'Sem setor'] = cobertura[d].get(setor or 'Sem setor', 0) + 1
            celulas.append({'e': estado, 'troca': troca[0] if troca else '', 'min': minutos, 'prev': previsto,
                            'h': _horas(minutos) if minutos else '', 'conflito': conflito,
                            'tit': (s['texto'] if s else ('Trabalha' + (f" · {_horas(minutos)}" if minutos else '')))
                            + (" · previsto pelo fixo" if previsto else '') + (f" · troca: {troca[1]}" if troca and troca[1] else '')})
            if conflito and d >= hoje:
                alertas.append(('erro', d, f"{f.NomeCompleto} está na escala em {_br(d, True)}, mas é dia de {s['texto'].lower()}."))
        resumo = []
        for w in range(semanas):
            seg = dias[7 * w]
            cs = celulas[7 * w: 7 * w + 7]
            minutos = sum(c['min'] for c in cs)
            n_folgas = sum(1 for c in cs if c['e'] == 'F')
            afast = any(c['e'] == 'A' for c in cs)
            limite = FG.limite_horas(seg + timedelta(days=6), regras)
            p = FG.padrao_no_dia(fid, seg + timedelta(days=6), padroes)
            esperado = len(p[1][FG.semana_do_ciclo(p[0], seg + timedelta(days=6), len(p[1]))]) if p and p[1] else None
            problema = []
            if na_escala and limite and minutos > limite * 60:
                problema.append(f"{_horas(minutos)} (limite {_horas(limite * 60)})")
                alertas.append(('erro', seg, f"{f.NomeCompleto}: {_horas(minutos)} na semana de {_br(seg)} — passa do limite de "
                                             f"{_horas(limite * 60)}."))
            if na_escala and esperado is not None and not afast and n_folgas < esperado:
                problema.append(f"{n_folgas} folga(s)")
                alertas.append(('aviso', seg, f"{f.NomeCompleto}: só {n_folgas} folga(s) na semana de {_br(seg)} "
                                              f"(o padrão tem {esperado})."))
            resumo.append({'h': _horas(minutos) if minutos else '0h', 'folgas': n_folgas, 'limite': limite,
                           'problema': ' · '.join(problema)})
        if na_escala and max_seguidos:
            antes = [ini - timedelta(days=k) for k in range(13, 0, -1)]
            seq = [(d, not situ(f, d)) for d in antes + dias]
            tam, a, b = _maior_sequencia(seq)
            if tam > max_seguidos and b >= ini:
                alertas.append(('erro', a, f"{f.NomeCompleto}: {tam} dias seguidos sem folga ({_br(a, True)} a {_br(b, True)}) — "
                                           f"o máximo combinado é {max_seguidos}."))
        if na_escala and n_domingos:
            seguidos = 0
            dom = ini + timedelta(days=6) - timedelta(days=7 * (n_domingos - 1))
            while dom <= fim:
                if situ(f, dom):
                    seguidos = 0
                else:
                    seguidos += 1
                    if seguidos >= n_domingos and dom >= ini and (seguidos == n_domingos or dom - timedelta(days=7) < ini):
                        alertas.append(('aviso', dom, f"{f.NomeCompleto}: {n_domingos} domingos seguidos trabalhando (até "
                                                      f"{_br(dom)}) — a regra é folgar 1 domingo a cada {n_domingos} semanas."))
                dom += timedelta(days=7)
        p_hoje = FG.padrao_no_dia(fid, max(hoje, ini), padroes)
        futuros = [x for x in padroes.get(fid, []) if x[0] > max(hoje, ini) and x[0] <= fim]
        pessoas.append({'id': fid, 'nome': f.NomeCompleto or '', 'cargo': getattr(f, 'Cargo', '') or '',
                        'padrao': FG.descrever_ciclo(p_hoje[1]) if p_hoje and p_hoje[1] else f"6x1: {FG.descrever_cadastro(f)}",
                        'muda': [f"{x[0]:%d/%m}: {FG.descrever_ciclo(x[1]) if x[1] else '6x1 do cadastro'}" for x in futuros],
                        'na_escala': na_escala, 'celulas': celulas, 'semanas': resumo})
    linhas_cob = [{'setor': 'Todos', 'n': [sum(cobertura[d].values()) for d in dias], 'min': None}]
    for setor in sorted({s for d in dias for s in cobertura[d]} | {s for s, v in minimos.items() if any(v or [])}):
        mins = minimos.get(setor) or []
        linha = {'setor': setor, 'n': [cobertura[d].get(setor, 0) for d in dias],
                 'min': [int(mins[d.weekday()]) if len(mins) == 7 else 0 for d in dias]}
        faltas = [(d, n, m) for d, n, m in zip(dias, linha['n'], linha['min']) if m and n < m and d >= hoje]
        if len(faltas) == 1:
            d, n, m = faltas[0]
            alertas.append(('erro', d, f"{setor}: {n} de {m} pessoas em {_br(d, True)} (falta gente)."))
        elif faltas:                         # um aviso por setor (não um por dia)
            lista = ", ".join(f"{_br(d, True)} ({n}/{m})" for d, n, m in faltas[:6])
            alertas.append(('erro', faltas[0][0], f"{setor}: falta gente em {len(faltas)} dias — {lista}"
                                                   + (f" e mais {len(faltas) - 6}" if len(faltas) > 6 else '') + "."))
        linhas_cob.append(linha)
    alertas.sort(key=lambda a: (a[1], 0 if a[0] == 'erro' else 1))
    return {'de': ini.isoformat(), 'ate': fim.isoformat(), 'semanas': semanas, 'hoje': hoje.isoformat(),
            'dias': [{'iso': d.isoformat(), 'dia': DIAS_TELA[d.weekday()], 'data': f"{d:%d/%m}", 'dom': d.weekday() == 6,
                      'hoje': d == hoje, 'passado': d < hoje, 'feriado': feriados.get(d) or ''} for d in dias],
            'pessoas': pessoas, 'cobertura': linhas_cob,
            'alertas': [{'nivel': n, 'texto': t} for n, _d, t in alertas[:LIMITE_ALERTAS]], 'mais_alertas': max(len(alertas) - LIMITE_ALERTAS, 0),
            'regras': _regras_txt(regras)}


def _regras_txt(regras):
    partes = []
    hoje = date.today()
    lim = FG.limite_horas(hoje, regras)
    if lim:
        partes.append(f"limite hoje {_horas(lim * 60)}/semana")
    for item in sorted(regras.get('limites_horas') or [], key=lambda x: str(x.get('desde'))):
        d = FG.como_data(item.get('desde'))
        if d and d > hoje:
            partes.append(f"{_horas(float(item['horas']) * 60)} a partir de {d:%d/%m/%Y}")
    if regras.get('domingo_semanas'):
        partes.append(f"1 domingo de folga a cada {regras['domingo_semanas']} semanas")
    if regras.get('max_dias_seguidos'):
        partes.append(f"no máximo {regras['max_dias_seguidos']} dias seguidos")
    return " · ".join(partes)


# ------------------------------------------------------------------------------
# Padrão de folgas de um funcionário
# ------------------------------------------------------------------------------
def padrao(funcionario_id):
    _exigir_banco()
    f = _funcionario(funcionario_id)
    padroes, _t, _r = FG.memoria(forcar=True)
    hoje = date.today()
    atual = FG.padrao_no_dia(funcionario_id, hoje, padroes)
    lista = [{'id': pid, 'desde': d.isoformat(), 'desde_txt': f"{d:%d/%m/%Y}", 'semanas': ciclo or [],
              'descricao': FG.descrever_ciclo(ciclo) if ciclo else f"6x1 do cadastro ({FG.descrever_cadastro(f)})",
              'atual': bool(atual) and pid == atual[2], 'futuro': d > hoje}
             for d, ciclo, pid in padroes.get(int(funcionario_id), [])]
    proxima_segunda = FG.segunda(hoje) + timedelta(days=7)
    return {'id': int(funcionario_id), 'nome': f.NomeCompleto or '', 'cadastro': FG.descrever_cadastro(f),
            'hoje_vale': (FG.descrever_ciclo(atual[1]) if atual and atual[1] else f"6x1 do cadastro ({FG.descrever_cadastro(f)})"),
            'padroes': lista, 'hoje': hoje.isoformat(), 'sugestao_data': proxima_segunda.isoformat()}


def _ler_semanas(dados):
    tipo = dados.get('tipo')
    if tipo == 'cadastro':
        return tipo, None
    if tipo not in ('fixo', 'rodizio'):
        raise ErroEscala("Escolha o tipo: 5x2 fixo, rodízio ou a folga do cadastro (6x1).")
    brutas = dados.get('semanas')
    if not isinstance(brutas, list) or not brutas:
        raise ErroEscala("Marque os dias de folga.")
    if tipo == 'fixo':
        brutas = brutas[:1]
    elif not 2 <= len(brutas) <= FG.MAX_SEMANAS_CICLO:
        raise ErroEscala(f"O rodízio tem de 2 a {FG.MAX_SEMANAS_CICLO} semanas.")
    semanas = []
    for k, s in enumerate(brutas, start=1):
        if not isinstance(s, list):
            raise ErroEscala("Dias de folga inválidos. Atualize a página.")
        dias = sorted({int(x) for x in s if str(x).isdigit() and 1 <= int(x) <= 7}, key=FG.ORDEM_SEMANA.index)
        if not dias:
            raise ErroEscala(f"A semana {k} está sem folga: marque pelo menos um dia." if len(brutas) > 1 else "Marque os dias de folga.")
        if len(dias) > 3:
            raise ErroEscala(f"A semana {k} tem {len(dias)} folgas: no máximo 3." if len(brutas) > 1 else "No máximo 3 folgas por semana.")
        semanas.append(dias)
    return tipo, semanas


def _simular(f, desde, semanas, dias_antes=14, dias_depois=None):
    """[(data, trabalha?)] de 2 semanas antes da troca até 3 ciclos depois, com o padrão NOVO a partir de 'desde'."""
    padroes, trocas, _r = FG.memoria()
    fid = int(f.FuncionarioID)
    novos = {k: v for k, v in padroes.items()}
    lista = [p for p in novos.get(fid, []) if p[0] < desde] + [(desde, semanas, -1)]
    novos[fid] = sorted(lista, key=lambda x: x[0])
    dias_depois = dias_depois or 7 * max(len(semanas or [[]]) * 3, 4)
    seq = []
    for k in range(-dias_antes, dias_depois):
        d = desde + timedelta(days=k)
        s = FG.situacao(f, d, padroes=novos, trocas=trocas if k < 0 else {})
        seq.append((d, not s, s))
    return seq


def salvar_padrao(funcionario_id, dados, usuario):
    _exigir_banco()
    f = _funcionario(funcionario_id)
    tipo, semanas = _ler_semanas(dados)
    _txt, desde = _data(dados.get('desde'))
    hoje = date.today()
    if desde < hoje:
        raise ErroEscala("A data de início não pode ser no passado (o que já passou fica como estava). Use hoje ou uma data à frente.")
    regras = FG.regras()
    perguntas, conf = [], _confirmados(dados)
    nome = f.NomeCompleto
    if semanas and 'nao_2' not in conf:
        diferentes = [k for k, s in enumerate(semanas, start=1) if len(s) != 2]
        if diferentes:
            quais = ", ".join(f"semana {k} ({len(semanas[k - 1])})" for k in diferentes) if len(semanas) > 1 else f"{len(semanas[0])} folga(s)"
            perguntas.append({'chave': 'nao_2', 'titulo': "Folgas por semana", 'texto': (
                f"Na 5x2 são 2 folgas por semana. Este padrão tem: {quais}.\n\nSalvar assim mesmo?")})
    if semanas:
        seq = _simular(f, desde, semanas)
        max_seg = int(regras.get('max_dias_seguidos') or 0)
        if max_seg and 'seguidos' not in conf:
            tam, a, b = _maior_sequencia([(d, t) for d, t, _s in seq])
            if tam > max_seg:
                perguntas.append({'chave': 'seguidos', 'titulo': "Dias seguidos sem folga", 'texto': (
                    f"Com este padrão, {nome} trabalha {tam} dias seguidos sem folga ({_br(a, True)} a {_br(b, True)}"
                    + (", na troca do padrão antigo para o novo" if a < desde else '') + f"). O máximo combinado é {max_seg}.\n\n"
                    "Dica: no rodízio, deixe as folgas de uma semana perto das da semana seguinte.\n\nSalvar assim mesmo?")})
        n_dom = int(regras.get('domingo_semanas') or 0)
        if n_dom and 'domingo' not in conf:
            doms = [t for d, t, _s in seq if d >= desde and d.weekday() == 6]
            corrida = maior = 0
            for t in doms:
                corrida = corrida + 1 if t else 0
                maior = max(maior, corrida)
            if maior >= n_dom:
                perguntas.append({'chave': 'domingo', 'titulo': "Folga no domingo", 'texto': (
                    f"Com este padrão, {nome} fica {'sem folgar nenhum domingo' if all(doms) else f'{maior} domingos seguidos trabalhando'}. "
                    f"A regra combinada é folgar 1 domingo a cada {n_dom} semanas (confira com o contador / convenção).\n\n"
                    "Salvar assim mesmo?")})
    if perguntas:
        return {'perguntas': perguntas}
    FG.gravar_padrao(funcionario_id, desde, semanas, (usuario or {}).get('nome') or '')
    r = _ressincronizar(int(funcionario_id))
    desc = FG.descrever_ciclo(semanas) if semanas else f"6x1 do cadastro ({FG.descrever_cadastro(f)})"
    logger.info(f"[GESTÃO] {(usuario or {}).get('nome')}: folgas de {nome} a partir de {desde}: {desc} ({r}).")
    msg = f"📅 Folgas de {nome} a partir de {desde:%d/%m/%Y}: {desc}."
    if desde == hoje:
        msg += "\nHoje continua como está na 🗓️ Escala (o sistema só acerta de amanhã em diante)."
    return {'ok': True, 'mensagem': msg}


def apagar_padrao(funcionario_id, dados, usuario):
    _exigir_banco()
    f = _funcionario(funcionario_id)
    pid = _id(dados.get('padrao_id'), "o padrão")
    padroes, _t, _r = FG.memoria(forcar=True)
    p = next((x for x in padroes.get(int(funcionario_id), []) if x[2] == pid), None)
    if not p:
        raise ErroEscala("Esse padrão não existe mais. Atualize a página.", 409)
    if p[0] <= date.today():
        raise ErroEscala("Esse padrão já está valendo. Para mudar, crie um novo a partir de hoje ou de outra data.")
    FG.apagar_padrao(funcionario_id, pid)
    _ressincronizar(int(funcionario_id))
    logger.info(f"[GESTÃO] {(usuario or {}).get('nome')}: apagou o padrão de folgas de {f.NomeCompleto} que começaria em {p[0]}.")
    return {'ok': True, 'mensagem': f"Padrão de {f.NomeCompleto} que começaria em {p[0]:%d/%m/%Y} apagado."}


# ------------------------------------------------------------------------------
# Troca de um dia
# ------------------------------------------------------------------------------
def trocar_dia(funcionario_id, dados, usuario):
    _exigir_banco()
    f = _funcionario(funcionario_id)
    _txt, d = _data(dados.get('data'))
    hoje = date.today()
    if d < hoje:
        raise ErroEscala("Dia que já passou não muda.")
    acao = dados.get('acao')
    if acao not in ('folga', 'trabalha', 'padrao'):
        raise ErroEscala("Escolha: dar folga, vai trabalhar ou voltar ao padrão.")
    FG.memoria(forcar=True)
    base = FG.situacao(f, d, sem_troca=True)
    if base and base['tipo'] == 'afastamento':
        raise ErroEscala(f"{f.NomeCompleto} está de férias/afastamento em {_br(d, True)}.")
    motivo = ' '.join(str(dados.get('motivo') or '').split())[:150]
    quem = (usuario or {}).get('nome') or ''
    if acao == 'padrao' or (acao == 'folga') == bool(base):
        FG.gravar_troca(funcionario_id, d, None)
        texto = f"{f.NomeCompleto} em {_br(d, True)}: volta ao padrão ({base['texto'].lower() if base else 'trabalha'})."
    else:
        FG.gravar_troca(funcionario_id, d, acao, motivo, quem)
        texto = (f"🌴 {f.NomeCompleto} folga em {_br(d, True)}." if acao == 'folga'
                 else f"💼 {f.NomeCompleto} trabalha em {_br(d, True)} (era {base['texto'].lower()}).")
    if d > hoje:
        _ressincronizar(int(funcionario_id))
    else:
        texto += "\nÉ hoje: ajuste a escala do dia na 🗓️ Escala (o sistema não mexe no dia de hoje)."
    logger.info(f"[GESTÃO] {quem}: troca de folga — {texto.splitlines()[0]}" + (f" ({motivo})" if motivo else ''))
    return {'ok': True, 'mensagem': texto}


# ------------------------------------------------------------------------------
# Regras
# ------------------------------------------------------------------------------
def ver_regras():
    _exigir_banco()
    regras = FG.memoria(forcar=True)[2]
    return {'regras': regras, 'setores': _setores(), 'dias': DIAS_TELA}


def salvar_regras(dados, usuario):
    _exigir_banco()
    brutas = dados.get('regras') if isinstance(dados.get('regras'), dict) else {}
    limites = []
    for item in (brutas.get('limites_horas') or [])[:8]:
        d = FG.como_data((item or {}).get('desde'))
        try:
            horas = float(str((item or {}).get('horas')).replace(',', '.'))
        except (TypeError, ValueError):
            raise ErroEscala("Horas por semana inválidas (ex.: 44, 42, 40).")
        if not d:
            raise ErroEscala("Preencha a data de cada limite de horas.")
        if not 1 <= horas <= 60:
            raise ErroEscala("Horas por semana: entre 1 e 60.")
        limites.append({'desde': d.isoformat(), 'horas': horas})
    if not limites:
        limites = [{'desde': '2000-01-01', 'horas': 44}]
    try:
        dom = int(brutas.get('domingo_semanas') or 0)
        seguidos = int(brutas.get('max_dias_seguidos') or 0)
    except (TypeError, ValueError):
        raise ErroEscala("Use números inteiros nas regras do domingo e dos dias seguidos.")
    if not 0 <= dom <= 8 or not 0 <= seguidos <= 13:
        raise ErroEscala("Domingo: de 0 a 8 semanas. Dias seguidos: de 0 a 13 (0 = não avisa).")
    minimos = {}
    for setor, valores in (brutas.get('minimos') or {}).items():
        setor = ' '.join(str(setor).split())[:40]
        if not setor or not isinstance(valores, list) or len(valores) != 7:
            continue
        try:
            nums = [max(0, min(int(v or 0), 50)) for v in valores]
        except (TypeError, ValueError):
            raise ErroEscala(f"Mínimo de pessoas inválido em {setor}.")
        if any(nums):
            minimos[setor] = nums
    novas = {'limites_horas': sorted(limites, key=lambda x: x['desde']), 'domingo_semanas': dom,
             'max_dias_seguidos': seguidos, 'minimos': minimos}
    FG.gravar_regras(novas)
    logger.info(f"[GESTÃO] {(usuario or {}).get('nome')}: regras das folgas = {novas}.")
    return {'ok': True, 'mensagem': "Regras das folgas salvas."}

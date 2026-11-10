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


# ==============================================================================
# [5x2 ETAPA 3] ✨ Sugerir rodízio (pelo movimento de cada dia) e 📲 mandar as folgas do mês
# ==============================================================================
import html as _html
import random
import re
import threading
import time
import unicodedata
import uuid

import config

POSICAO_DIA = [2, 3, 4, 5, 6, 7, 1]        # posição na semana (0 = segunda ... 6 = domingo) -> dia do banco (1=Dom)
SEMANAS_MOVIMENTO = 12                     # média do faturamento das últimas 12 semanas
TEMPO_MAX_SUGESTAO = 3.0                   # segundos procurando a melhor combinação
# pesos da conta (quanto "custa" cada coisa): regra quebrada >> falta gente >> folga em dia de movimento
P_SEGUIDOS, P_DOMINGO, P_COBERTURA, P_MOVIMENTO, P_JUNTAS, P_ESPALHAR = 1000.0, 500.0, 200.0, 10.0, 6.0, 2.0
P_JUSTO = 3.0                              # divide as folgas "boas" (dias de movimento, fim de semana) entre todos
MAX_TENTATIVAS = 80                        # tentativas com pontos de partida diferentes (fica a melhor)
MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
         'novembro', 'dezembro']
INTERVALO_ENVIO_SEG = 2.5                  # entre uma mensagem e outra (o WhatsApp não gosta de rajada)
SEGUNDO_PLANO = True                       # os testes desligam para conferir na hora
_envios, _trava_envios = {}, threading.Lock()


def _sem_acento(t):
    t = unicodedata.normalize('NFD', ' '.join(str(t or '').split()))
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn').lower()


def movimento(hoje=None):
    """Média do faturamento por dia da semana (seg..dom) e o peso de cada dia (1 = um dia médio)."""
    hoje = hoje or date.today()
    ini = hoje - timedelta(days=7 * SEMANAS_MOVIMENTO)
    valores, atipicos = {}, set()
    conn = database.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT DataApuracao, ValorDia FROM MetasDiariasApuracoes WHERE DataApuracao >= ? AND DataApuracao < ?",
                            ini.isoformat(), hoje.isoformat())
                for d, v in cur.fetchall():
                    d = FG.como_data(d)
                    try:
                        v = float(v or 0)
                    except (TypeError, ValueError):
                        v = 0
                    if d and v > 0:
                        valores[d] = max(valores.get(d, 0), v)          # duas metas no mesmo dia: vale a maior (igual à Folha)
            except Exception as e:
                logger.warning(f"Folgas: faturamento indisponível para o movimento ({e})")
            try:
                cur.execute("SELECT Data FROM DiasAtipicos WHERE Data >= ? AND Data < ?", ini.isoformat(), hoje.isoformat())
                atipicos = {FG.como_data(r[0]) for r in cur.fetchall()}
            except Exception:
                atipicos = set()
        finally:
            conn.close()
    soma, n = [0.0] * 7, [0] * 7
    for d, v in valores.items():
        if d not in atipicos:
            soma[d.weekday()] += v
            n[d.weekday()] += 1
    medias = [soma[i] / n[i] if n[i] else None for i in range(7)]
    if any(m is None for m in medias) or sum(n) < 14:
        return {'medias': medias, 'pesos': [1.0] * 7, 'dias': sum(n),
                'fonte': "Sem faturamento suficiente nas últimas semanas: considerei todos os dias iguais."}
    media = sum(medias) / 7
    return {'medias': medias, 'pesos': [m / media for m in medias], 'dias': sum(n),
            'fonte': f"Média do faturamento das últimas {SEMANAS_MOVIMENTO} semanas ({sum(n)} dias lançados"
                     + (f", sem {len(atipicos & set(valores))} dia(s) atípico(s)" if atipicos & set(valores) else '') + ")."}


class _Rodizio:
    """
    Procura as folgas de cada pessoa em cada semana do ciclo (2 por semana) com a menor "conta":
    regra quebrada (dias seguidos, domingo) >> setor abaixo do mínimo >> folga em dia de movimento >> folgas separadas
    >> muita gente folgando no mesmo dia. Começa por um palpite bom e vai trocando enquanto melhora.
    """
    PARES = [(a, b) for a in range(7) for b in range(a + 1, 7)]

    def __init__(self, setores_pessoas, semanas, pesos, minimos, max_seguidos, n_domingos, juntas):
        self.ps = setores_pessoas                       # índice do setor de cada pessoa
        self.L, self.pesos, self.mins = semanas, pesos, minimos
        self.max_seg, self.n_dom, self.juntas = max_seguidos, n_domingos, juntas
        self.n_s = [self.ps.count(s) for s in range(len(minimos))]
        self.cnt = [[[0] * 7 for _w in range(semanas)] for _s in minimos]
        self.a = [[None] * semanas for _p in self.ps]
        self.pc = [0.0] * len(self.ps)

    def _celula(self, s, w, d, c):
        falta = max(0, self.mins[s][d] - (self.n_s[s] - c))
        return P_COBERTURA * falta + P_ESPALHAR * c * c

    def custo_pessoa(self, pares):
        L, T = self.L, self.L * 7
        folga = [False] * T
        custo = 0.0
        mov = 0.0
        for w, (a, b) in enumerate(pares):
            folga[w * 7 + a] = folga[w * 7 + b] = True
            mov += self.pesos[a] + self.pesos[b]
        custo += P_MOVIMENTO * mov + P_JUSTO * mov * mov / L
        if self.max_seg:
            inicio = folga.index(True) + 1
            seguidos = 0
            for k in range(T + 1):
                if k == T or folga[(inicio + k) % T]:
                    if seguidos > self.max_seg:
                        custo += P_SEGUIDOS * (seguidos - self.max_seg)
                    seguidos = 0
                else:
                    seguidos += 1
        if self.n_dom:
            doms = [folga[w * 7 + 6] for w in range(L)]
            if not any(doms):
                custo += P_DOMINGO * self.n_dom
            else:
                ini = doms.index(True) + 1
                seguidos = maior = 0
                for k in range(L):
                    if doms[(ini + k) % L]:
                        seguidos = 0
                    else:
                        seguidos += 1
                        maior = max(maior, seguidos)
                if maior >= self.n_dom:
                    custo += P_DOMINGO * (maior - self.n_dom + 1)
        if self.juntas:
            custo += P_JUNTAS * sum(1 for i in range(T) if folga[i] and not folga[i - 1] and not folga[(i + 1) % T])
        return custo

    def _delta(self, p, w, novo):
        s, velho = self.ps[p], self.a[p][w]
        dc = 0.0
        if velho is not None:
            for d in set(velho) | set(novo):
                c = self.cnt[s][w][d]
                dc += self._celula(s, w, d, c - (d in velho) + (d in novo)) - self._celula(s, w, d, c)
        else:
            for d in novo:
                c = self.cnt[s][w][d]
                dc += self._celula(s, w, d, c + 1) - self._celula(s, w, d, c)
        pares = list(self.a[p])
        pares[w] = novo
        if any(x is None for x in pares):
            pares = [x if x is not None else novo for x in pares]
        novo_pc = self.custo_pessoa(pares)
        return dc + novo_pc - self.pc[p], novo_pc

    def _por(self, p, w, novo, novo_pc):
        s, velho = self.ps[p], self.a[p][w]
        if velho is not None:
            for d in velho:
                self.cnt[s][w][d] -= 1
        for d in novo:
            self.cnt[s][w][d] += 1
        self.a[p][w] = novo
        self.pc[p] = novo_pc

    def resolver(self, semente, limite=TEMPO_MAX_SUGESTAO):
        rnd = random.Random(semente)
        fim = time.monotonic() + limite
        # 1º palpite: cada pessoa ganha o domingo numa semana diferente (espalhado dentro do setor)
        vez = {}
        for p in sorted(range(len(self.ps)), key=lambda p: (self.ps[p], rnd.random())):
            k = vez.get(self.ps[p], rnd.randrange(self.L))
            vez[self.ps[p]] = k + 1
            dom_semana = k % self.L if self.n_dom else -1
            for w in range(self.L):
                opcoes = [x for x in self.PARES if (6 in x) == (w == dom_semana)]
                melhor = min(opcoes, key=lambda x: (self._delta(p, w, x)[0], rnd.random()))
                self._por(p, w, melhor, self._delta(p, w, melhor)[1])
        for p in range(len(self.ps)):
            self.pc[p] = self.custo_pessoa(self.a[p])
        # depois: troca uma semana de uma pessoa por vez (e troca as folgas de duas pessoas do mesmo setor na mesma
        # semana), enquanto a conta melhorar
        lugares = [(p, w) for p in range(len(self.ps)) for w in range(self.L)]
        melhorou = True
        while melhorou and time.monotonic() < fim:
            melhorou = False
            rnd.shuffle(lugares)
            for p, w in lugares:
                melhor, melhor_d, melhor_pc = None, -1e-9, None
                for x in self.PARES:
                    if x == self.a[p][w]:
                        continue
                    dlt, pc = self._delta(p, w, x)
                    if dlt < melhor_d:
                        melhor, melhor_d, melhor_pc = x, dlt, pc
                if melhor:
                    self._por(p, w, melhor, melhor_pc)
                    melhorou = True
            for p in range(len(self.ps)):
                for q in range(p + 1, len(self.ps)):
                    if self.ps[p] != self.ps[q]:
                        continue
                    for w in range(self.L):
                        if self.a[p][w] == self.a[q][w]:
                            continue
                        np_ = list(self.a[p]); nq = list(self.a[q])
                        np_[w], nq[w] = self.a[q][w], self.a[p][w]
                        cp, cq = self.custo_pessoa(np_), self.custo_pessoa(nq)
                        if cp + cq < self.pc[p] + self.pc[q] - 1e-9:      # as contagens do dia não mudam: só as pessoas
                            self.a[p], self.a[q], self.pc[p], self.pc[q] = np_, nq, cp, cq
                            melhorou = True
        return self.total()

    def total(self):
        return sum(self.pc) + sum(self._celula(s, w, d, self.cnt[s][w][d])
                                  for s in range(len(self.mins)) for w in range(self.L) for d in range(7))


def _setor_da_pessoa(f, cfg, pos_setor, setores):
    if cfg and pos_setor.get(cfg['posicao_id']):
        return pos_setor[cfg['posicao_id']]
    cargo = _sem_acento(getattr(f, 'Cargo', ''))
    return next((s for s in setores if _sem_acento(s) and _sem_acento(s) in cargo), 'Sem setor')


def candidatos_rodizio():
    """Quem pode entrar no rodízio (os fixos; marcados: quem está na escala automática ou já tem padrão 5x2)."""
    _exigir_banco()
    padroes = FG.memoria(forcar=True)[0]
    cfgs = _fixos_escala()
    pos_setor = {p[0]: (p[5] or '').strip() for p in database.listar_posicoes_loja()}
    setores = _setores()
    hoje = date.today()
    lista = []
    for f in sorted(database.listar_funcionarios(), key=lambda f: str(f.NomeCompleto or '').lower()):
        fid = int(f.FuncionarioID)
        p = FG.padrao_no_dia(fid, hoje, padroes)
        lista.append({'id': fid, 'nome': f.NomeCompleto or '', 'setor': _setor_da_pessoa(f, cfgs.get(fid), pos_setor, setores),
                      'marcado': fid in cfgs or bool(padroes.get(fid)),
                      'padrao': FG.descrever_ciclo(p[1]) if p and p[1] else f"6x1: {FG.descrever_cadastro(f)}"})
    regras = FG.regras()
    return {'pessoas': lista, 'semanas': int(regras.get('domingo_semanas') or 0) or 3, 'regras': _regras_txt(regras),
            'movimento': _movimento_json(movimento()), 'desde': (FG.segunda(hoje) + timedelta(days=7)).isoformat()}


def _movimento_json(m):
    return {'fonte': m['fonte'], 'dias': [{'dia': DIAS_TELA[i], 'media': f"R$ {m['medias'][i]:,.0f}".replace(',', '.')
                                           if m['medias'][i] else '—', 'peso': round(m['pesos'][i], 2)} for i in range(7)]}


def sugerir(dados):
    """✨ Monta o rodízio das pessoas escolhidas (não grava nada: a tela mostra e a pessoa decide aplicar)."""
    _exigir_banco()
    try:
        semanas = int(dados.get('semanas') or 3)
        semente = int(dados.get('semente') or 1)
    except (TypeError, ValueError):
        raise ErroEscala("Número de semanas inválido.")
    if not 1 <= semanas <= FG.MAX_SEMANAS_CICLO:
        raise ErroEscala(f"O rodízio tem de 1 a {FG.MAX_SEMANAS_CICLO} semanas.")
    ids = dados.get('ids')
    if not isinstance(ids, list) or not ids:
        raise ErroEscala("Marque quem entra no rodízio.")
    ids = list(dict.fromkeys(_id(i, "o funcionário") for i in ids))[:60]
    juntas = bool(dados.get('juntas', True))
    desde = _data(dados['desde'])[1] if dados.get('desde') else FG.segunda(date.today()) + timedelta(days=7)
    regras = FG.regras()
    cfgs = _fixos_escala()
    pos_setor = {p[0]: (p[5] or '').strip() for p in database.listar_posicoes_loja()}
    setores = _setores()
    funcs = {int(f.FuncionarioID): f for f in database.listar_funcionarios()}
    faltando = [i for i in ids if i not in funcs]
    if faltando:
        raise ErroEscala("Alguém da lista foi excluído. Atualize a página.", 409)
    pessoas = [{'id': i, 'nome': funcs[i].NomeCompleto or '', 'setor': _setor_da_pessoa(funcs[i], cfgs.get(i), pos_setor, setores)}
               for i in ids]
    nomes_setor = sorted({p['setor'] for p in pessoas})
    mins_regra = regras.get('minimos') or {}
    minimos = [[int(x) for x in (mins_regra.get(s) or [0] * 7)] for s in nomes_setor]
    mov = movimento()
    max_seg = int(regras.get('max_dias_seguidos') or 0)
    n_dom = int(regras.get('domingo_semanas') or 0)
    antes = []                                           # quantos dias seguidos cada um já vem trabalhando na virada
    for p in pessoas:
        n_ = 0
        while n_ < 13 and not FG.situacao(funcs[p['id']], desde - timedelta(days=n_ + 1)):
            n_ += 1
        antes.append(n_)
    melhor, fim = None, time.monotonic() + TEMPO_MAX_SUGESTAO
    for k in range(MAX_TENTATIVAS):                      # várias tentativas (pontos de partida diferentes): fica a melhor
        r = _Rodizio([nomes_setor.index(p['setor']) for p in pessoas], semanas, mov['pesos'], minimos, max_seg, n_dom, juntas)
        total = r.resolver(semente * 7919 + k, max(fim - time.monotonic(), 0.05))
        if melhor is None or total < melhor[0]:
            melhor = (total, r)
        if time.monotonic() >= fim:
            break
    r = melhor[1]
    # A VIRADA: trocar o ciclo inteiro entre duas pessoas do MESMO setor não muda quantos trabalham por dia. Quem já vem
    # com mais dias seguidos trabalhando fica com o ciclo que tem a 1ª folga mais cedo.
    primeira = lambda pares: min(w * 7 + d for w, par in enumerate(pares) for d in par)
    for si in range(len(nomes_setor)):
        idx = [p for p in range(len(pessoas)) if r.ps[p] == si]
        ciclos = sorted((r.a[p] for p in idx), key=primeira)
        for p, ciclo in zip(sorted(idx, key=lambda p: -antes[p]), ciclos):
            r.a[p] = ciclo
    virada = []                                          # quem ainda passaria do limite: 1 folga a mais, só nessa semana
    for p, pessoa in enumerate(pessoas):
        k_max = primeira(r.a[p])
        if max_seg and antes[p] + k_max > max_seg:
            janela = range(0, max(0, max_seg - antes[p]) + 1)
            k = min(janela, key=lambda k: (mov['pesos'][(desde + timedelta(days=k)).weekday()], k))
            d = desde + timedelta(days=k)
            virada.append({'id': pessoa['id'], 'nome': pessoa['nome'], 'data': d.isoformat(),
                           'texto': f"{pessoa['nome']}: folga a mais em {_br(d, True)} (senão ficaria {antes[p] + k_max} dias "
                                    "seguidos na troca do padrão antigo para o rodízio)"})
    saida, problemas = [], []
    for p, pessoa in enumerate(pessoas):
        ciclo = [sorted((POSICAO_DIA[a], POSICAO_DIA[b]), key=FG.ORDEM_SEMANA.index) for a, b in r.a[p]]
        saida.append(dict(pessoa, semanas=ciclo, texto=FG.descrever_ciclo(ciclo),
                          folgas=[" e ".join(FG.DIAS_CURTO[d] for d in s) for s in ciclo]))
        um = _Rodizio([0], semanas, mov['pesos'], [[0] * 7], max_seg, n_dom, False)
        m_ = sum(mov['pesos'][a] + mov['pesos'][b] for a, b in r.a[p])
        if um.custo_pessoa(r.a[p]) - P_MOVIMENTO * m_ - P_JUSTO * m_ * m_ / semanas >= P_DOMINGO:
            problemas.append(f"{pessoa['nome']}: não coube a regra do domingo ou dos dias seguidos — ajuste à mão.")
    cobertura = []
    for s, nome in enumerate(nomes_setor):
        n = r.n_s[s]
        linhas = []
        for w in range(semanas):
            trab = [n - r.cnt[s][w][d] for d in range(7)]
            linhas.append({'trabalham': trab, 'min': minimos[s]})
            for d in range(7):
                if minimos[s][d] and trab[d] < minimos[s][d]:
                    problemas.append(f"{nome}: semana {w + 1}, {DIAS_TELA[d].lower()}: {trab[d]} de {minimos[s][d]} pessoas.")
        folga_possivel = sum(max(0, n - m) for m in minimos[s])
        livres_dom = max(n - minimos[s][6], 0)
        if n_dom and n and n > livres_dom * n_dom:
            # cada um precisa de 1 domingo a cada n_dom semanas = n/n_dom folgas de domingo por semana (qualquer ciclo)
            problemas.insert(0, f"{nome}: com {n} pessoa(s) e mínimo de {minimos[s][6]} no domingo, só {livres_dom} pode(m) folgar "
                                f"por domingo; para cada um ter 1 domingo a cada {n_dom} semanas seriam precisas "
                                f"{n / n_dom:.1f}".replace('.', ',') + " folgas de domingo por semana. Diminua o mínimo de domingo "
                                "ou mude a regra do domingo (⚙️ Regras) — ou ponha mais gente nesse setor.")
        if any(minimos[s]) and folga_possivel < 2 * n:
            problemas.insert(0, f"{nome}: com {n} pessoa(s) e esses mínimos a conta não fecha (cabem {folga_possivel} folgas "
                                f"por semana e são precisas {2 * n}). Precisa de mais gente ou de mínimos menores.")
        cobertura.append({'setor': nome, 'pessoas': n, 'semanas': linhas})
    if n_dom and semanas > n_dom and semanas % n_dom:
        problemas.insert(0, f"O ciclo de {semanas} semanas não combina com a regra de 1 domingo a cada {n_dom}: cada pessoa acaba "
                            f"precisando de mais domingos de folga. Use {n_dom} (ou {2 * n_dom}) semanas.")
    return {'pessoas': saida, 'cobertura': cobertura, 'problemas': problemas[:20], 'semanas': semanas, 'semente': semente,
            'desde': desde.isoformat(), 'virada': virada,
            'movimento': _movimento_json(mov), 'juntas': juntas,
            'regras': f"{max_seg or 'sem limite de'} dias seguidos no máximo · "
                      + (f"1 domingo de folga a cada {n_dom} semanas" if n_dom else "sem regra de domingo")}


def aplicar_rodizio(dados, usuario):
    """Grava o rodízio sugerido (um padrão por pessoa, todos com a mesma data de início: as semanas ficam alinhadas)."""
    _exigir_banco()
    _txt, desde = _data(dados.get('desde'))
    if desde < date.today():
        raise ErroEscala("A data de início não pode ser no passado.")
    brutas = dados.get('pessoas')
    if not isinstance(brutas, list) or not brutas or len(brutas) > 60:
        raise ErroEscala("Nada para aplicar. Faça a sugestão de novo.")
    itens = []
    for b in brutas:
        fid = _id((b or {}).get('id'), "o funcionário")
        f = _funcionario(fid)
        semanas = (b or {}).get('semanas')
        tipo, ciclo = _ler_semanas({'tipo': 'rodizio' if isinstance(semanas, list) and len(semanas) > 1 else 'fixo',
                                    'semanas': semanas})
        itens.append((f, ciclo))
    extras = []                                          # [VIRADA] 1 folga a mais (troca) na semana da troca de padrão
    for e in (dados.get('extras') or [])[:60]:
        fid = _id((e or {}).get('id'), "o funcionário")
        f = next((f for f, _c in itens if int(f.FuncionarioID) == fid), None)
        d = _data((e or {}).get('data'))[1]
        if not f or not desde <= d < desde + timedelta(days=14):
            raise ErroEscala("Folga extra da virada inválida. Faça a sugestão de novo.")
        extras.append((f, d))
    if 'aplicar' not in _confirmados(dados):
        padroes = FG.memoria(forcar=True)[0]
        depois = [f.NomeCompleto for f, _c in itens if any(p[0] > desde for p in padroes.get(int(f.FuncionarioID), []))]
        max_seg = int(FG.regras().get('max_dias_seguidos') or 0)
        virada = []
        com_extra = {int(f.FuncionarioID) for f, _d in extras}
        for f, c in itens:
            if int(f.FuncionarioID) in com_extra:
                continue
            tam, a, b = _maior_sequencia([(d, t) for d, t, _s in _simular(f, desde, c, dias_depois=14)])
            if max_seg and tam > max_seg and a < desde:
                virada.append(f"{f.NomeCompleto} ({tam} dias: {_br(a)} a {_br(b)})")
        return {'perguntas': [{'chave': 'aplicar', 'titulo': "Aplicar o rodízio", 'texto': (
            f"Aplicar o rodízio para {len(itens)} pessoa(s) a partir de {desde:%d/%m/%Y}?\n\n"
            + "\n".join(f"• {f.NomeCompleto}: {FG.descrever_ciclo(c)}" for f, c in itens[:15])
            + (f"\n• … e mais {len(itens) - 15}" if len(itens) > 15 else '')
            + (("\n\nFolga a mais na virada:\n" + "\n".join(f"• {f.NomeCompleto}: {_br(d, True)}" for f, d in extras)) if extras else '')
            + "\n\nAté essa data continua valendo o que está hoje. A escala automática se acerta sozinha."
            + (f"\n\n⚠️ {', '.join(depois)} já tem padrão marcado para DEPOIS dessa data: ele continua valendo a partir de lá."
               if depois else '')
            + (f"\n\n⚠️ Na virada ficam muitos dias seguidos sem folga: {'; '.join(virada)}. Depois de aplicar, dê uma folga "
               "a mais nessa semana (toque no dia na grade)." if virada else ''))}]}
    quem = (usuario or {}).get('nome') or ''
    for f, ciclo in itens:
        FG.gravar_padrao(int(f.FuncionarioID), desde, ciclo, quem)
    for f, d in extras:
        if not FG.situacao(f, d, sem_troca=True):        # só se nesse dia o rodízio não já for folga
            FG.gravar_troca(int(f.FuncionarioID), d, 'folga', 'virada para o rodízio', quem)
    for f, _c in itens:
        _ressincronizar(int(f.FuncionarioID))
    logger.info(f"[GESTÃO] {quem}: rodízio aplicado a partir de {desde} para {len(itens)} pessoa(s): "
                + "; ".join(f"{f.NomeCompleto}={FG.texto_ciclo(c)}" for f, c in itens))
    return {'ok': True, 'mensagem': f"✨ Rodízio aplicado para {len(itens)} pessoa(s) a partir de {desde:%d/%m/%Y}."
                                    + (f" {len(extras)} folga(s) a mais na virada." if extras else '')}


# ------------------------------------------------------------------------------
# 📲 Mandar as folgas do mês para cada pessoa (WhatsApp ou Telegram)
# ------------------------------------------------------------------------------
def _mes(texto):
    m = re.fullmatch(r'(\d{4})-(\d{2})', str(texto or ''))
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ErroEscala("Mês inválido.")
    return int(m.group(1)), int(m.group(2))


def _dias_do_mes(ano, mes):
    d = date(ano, mes, 1)
    dias = []
    while d.month == mes:
        dias.append(d)
        d += timedelta(days=1)
    return dias


def texto_folgas(f, ano, mes, canal):
    """A mensagem de UMA pessoa: as folgas do mês semana a semana (e as férias, se tiver)."""
    folgas, ferias = [], []
    for d in _dias_do_mes(ano, mes):
        s = FG.situacao(f, d)
        if s:
            (ferias if s['tipo'] == 'afastamento' else folgas).append(d)
    neg = (lambda t: f"*{t}*") if canal == 'whatsapp' else (lambda t: f"<b>{_html.escape(t)}</b>")
    esc = (lambda t: t) if canal == 'whatsapp' else _html.escape
    primeiro = (str(f.NomeCompleto or '').split() or ['?'])[0]
    linhas = [f"📅 {neg(f'Suas folgas de {MESES[mes - 1]}/{ano}')}", "", f"Olá, {esc(primeiro)}! Estas são as suas folgas:"]
    semanas = {}
    for d in folgas:
        semanas.setdefault(FG.segunda(d), []).append(d)
    for _seg, ds in sorted(semanas.items()):
        linhas.append("• " + " e ".join(f"{DIAS_TELA[d.weekday()].lower()} {d:%d/%m}" for d in ds))
    if not folgas:
        linhas.append("• (nenhuma folga marcada no sistema neste mês — fale com a gestão)")
    if ferias:
        linhas += ["", f"🏖️ Férias/afastamento: {ferias[0]:%d/%m} a {ferias[-1]:%d/%m}"]
    linhas += ["", "Se precisar trocar algum dia, combine antes com a gestão. 😉"]
    empresa = getattr(config, 'NOME_EMPRESA', '') or ''
    if empresa:
        linhas.append(esc(empresa))
    return "\n".join(linhas), len(folgas)


def _contato(f, canal):
    if canal == 'whatsapp':
        return R.numero_whatsapp(getattr(f, 'TelefoneWhatsApp', None))
    chat = str(getattr(f, 'ChatIDTelegram', '') or '').strip()
    return chat if re.fullmatch(r'-?\d{3,20}', chat) else None


def _ler_envio(dados):
    ano, mes = _mes(dados.get('mes'))
    canal = dados.get('canal') if dados.get('canal') in ('whatsapp', 'telegram') else 'whatsapp'
    return ano, mes, canal


def previa_envio(dados):
    _exigir_banco()
    ano, mes, canal = _ler_envio(dados)
    padroes = FG.memoria(forcar=True)[0]
    cfgs = _fixos_escala()
    pessoas = []
    for f in sorted(database.listar_funcionarios(), key=lambda f: str(f.NomeCompleto or '').lower()):
        fid = int(f.FuncionarioID)
        texto, n = texto_folgas(f, ano, mes, canal)
        contato = _contato(f, canal)
        na_escala = fid in cfgs or bool(padroes.get(fid))
        pessoas.append({'id': fid, 'nome': f.NomeCompleto or '', 'contato': bool(contato), 'folgas': n, 'texto': texto,
                        'marcado': na_escala and bool(contato), 'na_escala': na_escala})
    return {'mes': f"{MESES[mes - 1]}/{ano}", 'canal': canal, 'pessoas': pessoas}


def _motivo_falha(canal, resposta):
    """Motivo curto e SEM o texto bruto (o erro de conexão da Z-API pode trazer o endereço com o token)."""
    t = str(resposta or '').lower()
    if 'conex' in t or 'timeout' in t or 'connection' in t:
        return "sem conexão"
    return "o WhatsApp recusou" if canal == 'whatsapp' else "o Telegram recusou"


def enviar_folgas(dados, usuario):
    """📲 Manda as folgas do mês para cada pessoa marcada (em segundo plano, uma de cada vez). Devolve o andamento."""
    _exigir_banco()
    ano, mes, canal = _ler_envio(dados)
    ids = dados.get('ids')
    if not isinstance(ids, list) or not ids:
        raise ErroEscala("Marque para quem mandar.")
    ids = set(_id(i, "o funcionário") for i in ids)
    funcs = [f for f in database.listar_funcionarios() if int(f.FuncionarioID) in ids]
    with _trava_envios:
        for j in list(_envios.values()):
            if j['terminado'] and time.time() - j['criado'] > 3600:
                _envios.pop(j['id'], None)
        andando = next((j for j in _envios.values() if not j['terminado']), None)
        if andando:
            if andando['mes'] == f"{ano}-{mes:02d}" and andando['canal'] == canal:
                return dict(andando)
            raise ErroEscala(f"Ainda estou mandando as folgas ({andando['feitos']} de {andando['total']}). Espere terminar.", 409)
        fila, sem = [], []
        for f in funcs:
            contato = _contato(f, canal)
            if contato:
                fila.append((f, contato, texto_folgas(f, ano, mes, canal)[0]))
            else:
                sem.append(f.NomeCompleto)
        if not fila:
            raise ErroEscala("Ninguém marcado tem " + ("WhatsApp" if canal == 'whatsapp' else "Telegram") + " no cadastro.")
        job = {'id': uuid.uuid4().hex[:12], 'mes': f"{ano}-{mes:02d}", 'canal': canal, 'total': len(fila), 'feitos': 0,
               'enviados': 0, 'falhas': [], 'sem_contato': sem, 'terminado': False, 'por': (usuario or {}).get('nome'),
               'criado': time.time()}
        _envios[job['id']] = job

    def rodar():
        try:
            for k, (f, contato, texto) in enumerate(fila):
                if k and SEGUNDO_PLANO:
                    time.sleep(INTERVALO_ENVIO_SEG)
                try:
                    if canal == 'whatsapp':
                        import notificador_whatsapp
                        ok, resp = notificador_whatsapp.enviar_mensagem_whatsapp(contato, texto)
                    else:
                        import notificador_telegram
                        resp = notificador_telegram.enviar_mensagem(contato, texto, 'HTML')
                        ok = bool(resp) and bool(resp.get('ok'))
                except Exception as e:
                    ok, resp = False, str(e)
                if ok:
                    job['enviados'] += 1
                else:
                    job['falhas'].append({'nome': f.NomeCompleto, 'motivo': _motivo_falha(canal, resp)})
                job['feitos'] += 1
        finally:
            job['terminado'] = True
            logger.info(f"[GESTÃO] {job['por']}: folgas de {MESES[mes - 1]}/{ano} pelo {canal}: {job['enviados']} enviada(s)"
                        + (f", não foram: {', '.join(x['nome'] + ' (' + x['motivo'] + ')' for x in job['falhas'])}" if job['falhas'] else '')
                        + ".")
    if SEGUNDO_PLANO:
        threading.Thread(target=rodar, daemon=True).start()
    else:
        rodar()
    return dict(job)


def andamento_envio(job_id):
    job = _envios.get(str(job_id))
    if not job:
        raise ErroEscala("Envio não encontrado (o servidor reiniciou?).", 404)
    return dict(job)

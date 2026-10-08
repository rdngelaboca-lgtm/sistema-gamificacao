# -*- coding: utf-8 -*-
# ==============================================================================
# == folha_faturamento.py - Folha × Faturamento × Clima, dia a dia ===============
# ==============================================================================
# A folha de pagamento tem que ficar em até 18% do faturamento (a meta muda na tela).
# Para cada dia junta:
#   - FATURAMENTO: o que é lançado na Gamificação (Metas → "Lançar Apuração Diária");
#   - FIXOS: a folha do mês (salários + encargos + benefícios), informada uma vez por
#     mês e dividida pelos dias do mês (o fixo custa igual, trabalhando ou de folga);
#   - FREELANCERS: o valor de cada turno (o mesmo da tela de Pagamentos);
#   - PESSOAS e HORAS: a escala do dia (fixos e freelancers);
#   - CLIMA: máxima, mínima e chuva (clima.py).
# Folha do dia = (fixo do dia + freelancers) ÷ faturamento.
# Mês até hoje = (fixo de TODOS os dias até o último faturamento lançado + freelancers)
#                ÷ faturamento desses dias (dia sem faturamento lançado fica avisado).
# E, com o histórico: faturamento e freelancers médios por faixa de temperatura, e
# para os próximos dias (previsão) quanto se vendeu em dias parecidos.
#
# [MELHORIAS] dia ATÍPICO (feriado prolongado, evento, loja fechada…) fica fora das médias;
# comparação com o mesmo dia da semana passada e do ano passado; lançar o faturamento pela
# Web (mesma regra da Gamificação, com os pontos da meta); e os textos do Telegram: aviso
# antecipado de calor/chuva × escala, lembrete de faturamento e fechamento do mês.
# ==============================================================================
import calendar
import logging
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import clima
import database
import escala_regras as R

logger = logging.getLogger(__name__)

META_PADRAO = Decimal('18')
DIAS_SEMANA = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
NOMES_MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
FAIXAS = [(None, 29, 'até 29°'), (30, 31, '30° a 31°'), (32, 33, '32° a 33°'), (34, 35, '34° a 35°'), (36, None, '36° ou mais')]
PARECIDO_GRAUS = Decimal('1.5')      # "dia parecido" = mesmo tipo de dia e máxima até 1,5° de diferença
MIN_PARECIDOS = 2
PERIODOS = {'90': 90, '180': 180, '365': 365, 'tudo': None}
DIAS_PREVISAO = 7
HORA_RESUMO_HOJE = 21                # o resumo de HOJE só vai ao Telegram depois das 21h (o dia já fechou)
VALOR_MAXIMO = Decimal('10000000')

DIAS_HISTORICO_ESCALA = 180         # a dica da Escala compara com os últimos 6 meses
DIAS_HISTORICO_AVISO = 365          # o aviso antecipado compara com o último ano
MIN_PARECIDOS_AVISO = 3             # só avisa com pelo menos 3 dias parecidos
QUEDA_CHUVA_AVISO = Decimal('15')   # avisa a chuva se em dias de chuva vende 15% menos (ou mais)
DIAS_ESPERA_FECHAMENTO = 5          # o fechamento do mês espera até o dia 5 pelos faturamentos atrasados
MOTIVOS_ATIPICO = ['Feriado prolongado', 'Evento na cidade', 'Loja fechada / fechou mais cedo',
                   'Problema no sistema de vendas', 'Promoção especial']
CACHE_ESCALA_SEG = 600

_tabelas_ok = False
_cache_hist = {}


class ErroFolha(Exception):
    pass


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def _conexao():
    conn = database.get_db_connection()
    if not conn:
        raise ErroFolha("Sem conexão com o banco de dados.")
    return conn


def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    clima.garantir_tabela()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FolhaFixaMensal')
            CREATE TABLE FolhaFixaMensal (
                Ano INT NOT NULL,
                Mes INT NOT NULL,
                Valor DECIMAL(12, 2) NOT NULL,
                AtualizadoEm DATETIME NULL,
                AtualizadoPor NVARCHAR(150) NULL,
                PRIMARY KEY (Ano, Mes)
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'DiasAtipicos')
            CREATE TABLE DiasAtipicos (
                Data DATE NOT NULL PRIMARY KEY,
                Motivo NVARCHAR(200) NULL,
                MarcadoPor NVARCHAR(150) NULL,
                MarcadoEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ParametrosFolha')
            CREATE TABLE ParametrosFolha (
                Chave VARCHAR(40) NOT NULL PRIMARY KEY,
                Valor NVARCHAR(200) NULL
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# Números
# ------------------------------------------------------------------------------
def _d(v):
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _num(v, casas=2):
    return float(Decimal(v).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)) if v is not None else None


def _pct(parte, total):
    if parte is None or not total:
        return None
    return (Decimal(parte) / Decimal(total) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def _valor(texto, nome):
    """'R$ 12.345,67' / '12345,67' / '12345.67' -> Decimal. Vazio -> None."""
    t = str(texto if texto is not None else '').strip().replace('R$', '').replace(' ', '')
    if not t:
        return None
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise ErroFolha(f"{nome} inválido: '{texto}'.")
    if not v.is_finite() or v < 0 or v > VALOR_MAXIMO:
        raise ErroFolha(f"{nome} inválido: '{texto}'.")
    return v


def _mes(texto):
    try:
        a, m = str(texto).split('-')[:2]
        a, m = int(a), int(m)
        if 2000 <= a <= 2100 and 1 <= m <= 12:
            return a, m
    except (ValueError, AttributeError):
        pass
    raise ErroFolha(f"Mês inválido: '{texto}' (use AAAA-MM).")


def nome_mes(ano, mes):
    return f"{NOMES_MES[mes - 1]}/{str(ano)[2:]}"


def _reais(v):
    return R.fmt_reais(v if v is not None else 0)


def _reais_redondo(v):
    """Valor aproximado (média de dias parecidos): ~R$ 8.040 (de 10 em 10, sem centavos)."""
    v = (Decimal(str(v)) / 10).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * 10
    return "R$ " + f"{v:,.0f}".replace(',', '.')


def _n(v):
    """Decimal sem zeros sobrando, com vírgula: 18 -> '18', 17.40 -> '17,4', 20 -> '20' (nunca '2E+1')."""
    return format(Decimal(v).normalize(), 'f').replace('.', ',')


def _pct_txt(p):
    return f"{p}".replace('.', ',') + '%' if p is not None else '—'


def _grau(v):
    return int(Decimal(v).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------------------
# Meta e folha fixa (o que o gestor informa)
# ------------------------------------------------------------------------------
def meta():
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Valor FROM ParametrosFolha WHERE Chave = 'meta_pct'")
        r = cur.fetchone()
    finally:
        conn.close()
    v = _d(r[0]) if r else None
    return v if v and v > 0 else META_PADRAO


def definir_meta(texto, usuario):
    v = _valor(texto, 'Meta')
    if v is None or v <= 0 or v >= 100:
        raise ErroFolha("A meta precisa ser um número entre 0 e 100 (ex.: 18).")
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM ParametrosFolha WHERE Chave = 'meta_pct'")
        cur.execute("INSERT INTO ParametrosFolha (Chave, Valor) VALUES ('meta_pct', ?)", format(v.normalize(), 'f'))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Folha × Faturamento: meta {v}% ({(usuario or {}).get('nome')}).")
    return {'meta': _num(v, 1)}


def folhas_fixas():
    """{(ano, mês): valor} informados."""
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Ano, Mes, Valor FROM FolhaFixaMensal")
        return {(int(a), int(m)): _d(v) for a, m, v in cur.fetchall() if v is not None}
    finally:
        conn.close()


def definir_folha_fixa(mes, texto, usuario):
    """Folha fixa do mês (salários + encargos + benefícios). Vazio = apaga o valor do mês."""
    ano, m = _mes(mes)
    v = _valor(texto, 'Valor da folha')
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM FolhaFixaMensal WHERE Ano = ? AND Mes = ?", ano, m)
        if v is not None:
            cur.execute("INSERT INTO FolhaFixaMensal (Ano, Mes, Valor, AtualizadoEm, AtualizadoPor) VALUES (?, ?, ?, ?, ?)",
                        ano, m, v.quantize(Decimal('0.01')), datetime.now(), (usuario or {}).get('nome'))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Folha × Faturamento: folha fixa de {m:02d}/{ano} = {v} ({(usuario or {}).get('nome')}).")
    return {'mes': f"{ano}-{m:02d}", 'valor': _num(v)}


def _fixo_do_dia(d, folhas):
    """(valor do dia, mês de onde veio se for ESTIMADO, ou None). Mês sem valor usa o mês informado mais perto."""
    dias_mes = calendar.monthrange(d.year, d.month)[1]
    chave = (d.year, d.month)
    if chave in folhas:
        return folhas[chave] / dias_mes, None
    if not folhas:
        return None, None
    antes = [k for k in folhas if k < chave]
    k = max(antes) if antes else min(folhas)
    return folhas[k] / dias_mes, k


# ------------------------------------------------------------------------------
# Leituras do período
# ------------------------------------------------------------------------------
def primeiro_faturamento():
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MIN(DataApuracao) FROM MetasDiariasApuracoes")
        r = cur.fetchone()
        return database._como_data(r[0]) if r else None
    finally:
        conn.close()


def _faturamento(cur, ini, fim):
    """{data: valor}. Só existe uma meta por vez; se o mesmo dia aparecer em duas, vale o maior (não soma 2x)."""
    cur.execute("SELECT DataApuracao, ValorDia FROM MetasDiariasApuracoes WHERE DataApuracao >= ? AND DataApuracao < ?",
                ini, fim + timedelta(days=1))
    por_dia = {}
    for d, v in cur.fetchall():
        d, v = database._como_data(d), _d(v)
        if d is None or v is None:
            continue
        por_dia[d] = max(por_dia.get(d, v), v)
    return por_dia


def _atipicos(cur, ini, fim):
    """{data: motivo} dos dias marcados como atípicos."""
    cur.execute("SELECT Data, Motivo FROM DiasAtipicos WHERE Data >= ? AND Data <= ?", str(ini), str(fim))
    return {database._como_data(d): (m or 'Dia atípico') for d, m in cur.fetchall()}


def _minutos(ent, sai, ini_int=None, fim_int=None):
    f = R.faixa_turno(ent, sai)
    if not f:
        return 0
    total = f[1] - f[0]
    i = R.faixa_turno(ini_int, fim_int)
    if i and 0 < i[1] - i[0] < total:
        total -= i[1] - i[0]
    return total


def _escala(cur, ini, fim):
    """{data: {'fixos': {ids}, 'freelas': {ids}, 'min_fixos', 'min_freelas'}}."""
    cur.execute("""SELECT DataEscala, FuncionarioID, FreelancerID, HorarioEntrada, HorarioSaida, InicioIntervalo, FimIntervalo
                   FROM EscalaDiaria WHERE DataEscala >= ? AND DataEscala <= ?""", str(ini), str(fim))
    por_dia = {}
    for d, fid, frid, ent, sai, ii, fi in cur.fetchall():
        d = database._como_data(d)
        x = por_dia.setdefault(d, {'fixos': set(), 'freelas': set(), 'min_fixos': 0, 'min_freelas': 0})
        m = _minutos(ent, sai, ii, fi)
        if frid:
            x['freelas'].add(frid)
            x['min_freelas'] += m
        elif fid:
            x['fixos'].add(fid)
            x['min_fixos'] += m
    return por_dia


def _freelancers(ini, fim):
    """{data: valor} — o mesmo cálculo da tela de Pagamentos (pagos: valor congelado; pendentes: calculado)."""
    por_dia = {}
    for i in database.listar_pagamentos_freelancers(ini, fim):
        if i.get('Data') is None:
            continue
        por_dia[i['Data']] = por_dia.get(i['Data'], Decimal('0')) + (_d(i.get('Total')) or Decimal('0'))
    return por_dia


def _tipo_dia(d, feriados):
    if d in feriados:
        return 'feriado'
    return 'fds' if d.weekday() >= 5 else 'semana'


def _clima_json(c):
    if not c:
        return None
    return {'max': _num(c['max'], 1), 'min': _num(c['min'], 1), 'chuva': _num(c['chuva'], 1), 'previsao': c['previsao'],
            'chuva_tarde': _num(c.get('chuva_tarde'), 1), 'horas_chuva': c.get('horas_chuva'), 'chuvoso': clima.chuvoso(c),
            'icone': clima.icone(c), 'texto': clima.texto(c), 'texto_chuva': clima.texto_chuva(c)}


def dias(ini, fim, folhas=None, climas=None):
    """Um registro por dia do período (com ou sem faturamento). Valores em Decimal (para somar)."""
    garantir_tabelas()
    folhas = folhas_fixas() if folhas is None else folhas
    conn = _conexao()
    try:
        cur = conn.cursor()
        fat = _faturamento(cur, ini, fim)
        esc = _escala(cur, ini, fim)
        atip = _atipicos(cur, ini, fim)
    finally:
        conn.close()
    freelas = _freelancers(ini, fim)
    climas = clima.do_periodo(ini, fim) if climas is None else climas
    feriados = database._feriados_periodo(ini, fim)
    lista = []
    for n in range((fim - ini).days + 1):
        d = ini + timedelta(days=n)
        e = esc.get(d) or {'fixos': set(), 'freelas': set(), 'min_fixos': 0, 'min_freelas': 0}
        fixo, estimado = _fixo_do_dia(d, folhas)
        freela = freelas.get(d, Decimal('0'))
        faturamento = fat.get(d)
        folha = (fixo or Decimal('0')) + freela
        horas = Decimal(e['min_fixos'] + e['min_freelas']) / 60
        lista.append({
            'data': d, 'tipo': _tipo_dia(d, feriados), 'feriado': feriados.get(d) or '', 'clima': climas.get(d),
            'atipico': atip.get(d),
            'faturamento': faturamento, 'fixo': fixo, 'fixo_estimado': estimado, 'freela': freela,
            'fixos': len(e['fixos']), 'freelas': len(e['freelas']),
            'horas_fixos': Decimal(e['min_fixos']) / 60, 'horas_freelas': Decimal(e['min_freelas']) / 60,
            'folha': folha if fixo is not None or freela else None,
            'pct': _pct(folha, faturamento) if fixo is not None else None,
            'por_hora': (faturamento / horas) if faturamento and horas else None})
    return lista


def _dia_json(x):
    d = x['data']
    return {'data': d.isoformat(), 'dia': DIAS_SEMANA[d.weekday()], 'tipo': x['tipo'], 'feriado': x['feriado'],
            'clima': _clima_json(x['clima']), 'faturamento': _num(x['faturamento']), 'fixo': _num(x['fixo']),
            'fixo_estimado': nome_mes(*x['fixo_estimado']) if x['fixo_estimado'] else None, 'freela': _num(x['freela']),
            'fixos': x['fixos'], 'freelas': x['freelas'], 'horas_fixos': _num(x['horas_fixos'], 1),
            'horas_freelas': _num(x['horas_freelas'], 1), 'folha': _num(x['folha']), 'pct': _num(x['pct'], 1),
            'por_hora': _num(x['por_hora']), 'atipico': x.get('atipico')}


# ------------------------------------------------------------------------------
# Contas
# ------------------------------------------------------------------------------
def acumulado(lista, hoje=None):
    """
    Mês até o último dia com faturamento lançado: fixo de TODOS os dias até lá (folga e loja fechada também
    custam) + freelancers, ÷ faturamento. Dias sem faturamento lançado (até lá) vão em 'faltam_lancar'.
    """
    hoje = hoje or date.today()
    lancados = [x for x in lista if x['faturamento'] is not None]
    if not lancados:
        return None
    ultimo = max(x['data'] for x in lancados)
    ate = [x for x in lista if x['data'] <= ultimo]
    fat = sum((x['faturamento'] or Decimal('0') for x in ate), Decimal('0'))
    sem_fixo = any(x['fixo'] is None for x in ate)
    fixo = sum((x['fixo'] or Decimal('0') for x in ate), Decimal('0'))
    freela = sum((x['freela'] for x in ate), Decimal('0'))
    return {'ate': ultimo, 'faturamento': fat, 'fixo': None if sem_fixo else fixo, 'freela': freela,
            'folha': None if sem_fixo else fixo + freela, 'pct': None if sem_fixo else _pct(fixo + freela, fat),
            'pct_freela': _pct(freela, fat), 'dias': len(ate),
            'faltam_lancar': [x['data'] for x in ate if x['faturamento'] is None and x['data'] < hoje and not x.get('atipico')],
            'estimado': next((x['fixo_estimado'] for x in ate if x['fixo_estimado']), None)}


def _acumulado_json(a):
    if not a:
        return None
    return {'ate': a['ate'].isoformat(), 'faturamento': _num(a['faturamento']), 'fixo': _num(a['fixo']),
            'freela': _num(a['freela']), 'folha': _num(a['folha']), 'pct': _num(a['pct'], 1),
            'pct_freela': _num(a['pct_freela'], 1), 'dias': a['dias'],
            'faltam_lancar': [d.isoformat() for d in a['faltam_lancar']],
            'estimado': nome_mes(*a['estimado']) if a['estimado'] else None}


def _media(valores):
    valores = [v for v in valores if v is not None]
    return sum(valores, Decimal('0')) / len(valores) if valores else None


def _historico_valido(lista, hoje):
    """Dias que entram nas médias: com faturamento, temperatura medida (não previsão) e NÃO marcados como atípicos."""
    return [x for x in lista if x['faturamento'] and x['clima'] and x['clima']['max'] is not None
            and not x['clima']['previsao'] and x['data'] <= hoje and not x.get('atipico')]


def faixas(lista, hoje=None):
    """Médias por faixa de temperatura máxima, para 'todos', 'semana' e 'fds' (sábado, domingo e feriados)."""
    hoje = hoje or date.today()
    validos = _historico_valido(lista, hoje)
    grupos = {'todos': validos, 'semana': [x for x in validos if x['tipo'] == 'semana'],
              'fds': [x for x in validos if x['tipo'] != 'semana']}
    saida = {}
    for nome, xs in grupos.items():
        linhas = []
        for de, ate, rotulo in FAIXAS:
            sel = [x for x in xs if (de is None or _grau(x['clima']['max']) >= de) and (ate is None or _grau(x['clima']['max']) <= ate)]
            if not sel:
                continue
            com_fixo = [x for x in sel if x['fixo'] is not None]
            linhas.append({
                'faixa': rotulo, 'dias': len(sel), 'faturamento': _num(_media([x['faturamento'] for x in sel])),
                'freelas': _num(_media([Decimal(x['freelas']) for x in sel]), 1),
                'freela': _num(_media([x['freela'] for x in sel])),
                'pessoas': _num(_media([Decimal(x['fixos'] + x['freelas']) for x in sel]), 1),
                'pct': _num(_pct(sum((x['folha'] for x in com_fixo), Decimal('0')),
                                 sum((x['faturamento'] for x in com_fixo), Decimal('0'))), 1) if com_fixo else None,
                'chuva': sum(1 for x in sel if clima.chuvoso(x['clima']))})
        chuva = [x for x in xs if clima.chuvoso(x['clima'])]
        seco = [x for x in xs if clima.tem_chuva_info(x['clima']) and not clima.chuvoso(x['clima'])]
        saida[nome] = {'faixas': linhas, 'dias': len(xs),
                       'chuva': {'dias': len(chuva), 'faturamento': _num(_media([x['faturamento'] for x in chuva]))},
                       'seco': {'dias': len(seco), 'faturamento': _num(_media([x['faturamento'] for x in seco]))}}
    return saida


def parecidos(hist, d, c, feriados):
    """
    Dias do histórico do mesmo tipo (semana × fim de semana/feriado), com máxima parecida (até 1,5°) e
    o mesmo "tempo": chuva à tarde compara com dias de chuva à tarde; seco, com dias secos (senão um
    dia quente e chuvoso pediria freelancers de dia quente e seco).
    """
    if not c or c.get('max') is None:
        return None
    fds = _tipo_dia(d, feriados) != 'semana'
    chuva = clima.chuvoso(c)
    sel = [x for x in hist if (x['tipo'] != 'semana') == fds and abs(x['clima']['max'] - c['max']) <= PARECIDO_GRAUS
           and clima.chuvoso(x['clima']) == chuva]
    if len(sel) < MIN_PARECIDOS:
        return {'dias': len(sel), 'chuva': chuva}
    return {'dias': len(sel), 'chuva': chuva, 'faturamento': _num(_media([x['faturamento'] for x in sel])),
            'freelas': _num(_media([Decimal(x['freelas']) for x in sel]), 1),
            'pessoas': _num(_media([Decimal(x['fixos'] + x['freelas']) for x in sel]), 1)}


def proximos(hist_lista, hoje=None, climas=None):
    """Hoje e os próximos 7 dias: previsão do tempo + o que aconteceu em dias parecidos."""
    hoje = hoje or date.today()
    fim = hoje + timedelta(days=DIAS_PREVISAO)
    climas = clima.do_periodo(hoje, fim) if climas is None else climas
    feriados = database._feriados_periodo(hoje, fim)
    hist = _historico_valido(hist_lista, hoje)
    saida = []
    for n in range(DIAS_PREVISAO + 1):
        d = hoje + timedelta(days=n)
        c = climas.get(d)
        if not c:
            continue
        saida.append({'data': d.isoformat(), 'dia': DIAS_SEMANA[d.weekday()], 'tipo': _tipo_dia(d, feriados),
                      'feriado': feriados.get(d) or '', 'clima': _clima_json(c), 'parecidos': parecidos(hist, d, c, feriados)})
    return saida


def dica_escala(d, hoje=None):
    """
    [ESCALA] Para quem monta a escala do dia: o clima (previsão) e o que aconteceu em dias parecidos
    (faturamento, freelancers e pessoas). Usa só o banco (o clima é buscado pelo robô e pela tela da
    Folha); o histórico fica guardado 10 minutos (a escala é salva várias vezes seguidas).
    """
    hoje = hoje or date.today()
    d = database._como_data(d)
    c = clima.do_periodo(d, d).get(d)
    if not c:
        return None
    agora = time.monotonic()
    guardado = _cache_hist.get(hoje)
    if not guardado or agora - guardado[0] > CACHE_ESCALA_SEG:
        _cache_hist.clear()
        guardado = (agora, _historico_valido(dias(hoje - timedelta(days=DIAS_HISTORICO_ESCALA), hoje), hoje))
        _cache_hist[hoje] = guardado
    hist = [x for x in guardado[1] if x['data'] != d]
    return {'clima': _clima_json(c), 'parecidos': parecidos(hist, d, c, database._feriados_periodo(d, d))}


# ------------------------------------------------------------------------------
# [COMPARAR] mesmo dia da semana passada e do ano passado (mesmo dia da semana: 52 semanas antes)
# ------------------------------------------------------------------------------
def _leve(ini, fim):
    """{data: {'faturamento', 'clima', 'freelas', 'atipico'}} — sem o cálculo dos pagamentos (rápido)."""
    if ini > fim:
        return {}
    conn = _conexao()
    try:
        cur = conn.cursor()
        fat = _faturamento(cur, ini, fim)
        esc = _escala(cur, ini, fim)
        atip = _atipicos(cur, ini, fim)
    finally:
        conn.close()
    climas = clima.do_periodo(ini, fim)
    return {ini + timedelta(days=n): {'faturamento': fat.get(ini + timedelta(days=n)), 'clima': climas.get(ini + timedelta(days=n)),
                                      'freelas': len((esc.get(ini + timedelta(days=n)) or {}).get('freelas', ())),
                                      'atipico': atip.get(ini + timedelta(days=n))}
            for n in range((fim - ini).days + 1)}


def _comparacao_json(d_ref, x, fat_ref):
    if not x or x['faturamento'] is None:
        return {'data': d_ref.isoformat(), 'dia': DIAS_SEMANA[d_ref.weekday()], 'faturamento': None,
                'atipico': (x or {}).get('atipico')}
    return {'data': d_ref.isoformat(), 'dia': DIAS_SEMANA[d_ref.weekday()], 'faturamento': _num(x['faturamento']),
            'clima': _clima_json(x['clima']), 'freelas': x['freelas'], 'atipico': x['atipico'],
            'var': _num(_pct(fat_ref - x['faturamento'], x['faturamento']), 1) if fat_ref is not None and x['faturamento'] else None}


def comparativos(lista):
    """{data: {'semana': ..., 'ano': ...}} para os dias da lista (semana passada = 7 dias antes; ano = 364 dias)."""
    if not lista:
        return {}
    ini, fim = min(x['data'] for x in lista), max(x['data'] for x in lista)
    sem = _leve(ini - timedelta(days=7), fim - timedelta(days=7))
    ano = _leve(ini - timedelta(days=364), fim - timedelta(days=364))
    saida = {}
    for x in lista:
        d = x['data']
        ds, da = d - timedelta(days=7), d - timedelta(days=364)
        saida[d] = {'semana': _comparacao_json(ds, sem.get(ds), x['faturamento']),
                    'ano': _comparacao_json(da, ano.get(da), x['faturamento'])}
    return saida


def _linha_comparacao(rotulo, c):
    if not c:
        return f"{rotulo}: sem faturamento lançado"
    d = date.fromisoformat(c['data'])
    quando = f"{c['dia']} {d:%d/%m}{('/' + f'{d:%y}') if rotulo.startswith('Ano') else ''}"
    if c.get('faturamento') is None:
        return f"{rotulo} ({quando}): sem faturamento lançado" + (f" (📌 {c['atipico']})" if c.get('atipico') else '')
    partes = [f"{rotulo} ({quando}): {_reais(c['faturamento'])}"]
    if c.get('clima') and c['clima'].get('max') is not None:
        partes.append(f"{c['clima']['max']:.0f}°{(' ' + c['clima']['icone']) if c['clima'].get('chuvoso') else ''}")
    partes.append(f"{c['freelas']} freela(s)")
    texto = ' · '.join(partes)
    if c.get('var') is not None:
        texto += f" → {'+' if c['var'] > 0 else ''}{_n(Decimal(str(c['var'])))}%"
    if c.get('atipico'):
        texto += f" (📌 {c['atipico']})"
    return texto


# ------------------------------------------------------------------------------
# [ATÍPICO] dia fora do normal: sai das médias e dos "dias parecidos"
# ------------------------------------------------------------------------------
def marcar_atipico(data_txt, motivo, usuario):
    """Marca (motivo) ou desmarca (motivo vazio) um dia como atípico."""
    d = database._como_data(data_txt)
    if not d:
        raise ErroFolha("Data inválida.")
    motivo = ' '.join(str(motivo or '').split())[:200]
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM DiasAtipicos WHERE Data = ?", str(d))
        if motivo:
            cur.execute("INSERT INTO DiasAtipicos (Data, Motivo, MarcadoPor, MarcadoEm) VALUES (?, ?, ?, ?)",
                        str(d), motivo, (usuario or {}).get('nome'), datetime.now())
        conn.commit()
    finally:
        conn.close()
    _cache_hist.clear()                  # a dica da Escala recalcula sem (ou com) este dia
    logger.info(f"Folha × Faturamento: {d} {'marcado como atípico (' + motivo + ')' if motivo else 'desmarcado'} "
                f"por {(usuario or {}).get('nome')}.")
    return {'data': d.isoformat(), 'atipico': motivo or None}


# ------------------------------------------------------------------------------
# [LANÇAR] faturamento do dia pela Web: a MESMA regra da Gamificação (main.py e /lancar do Telegram):
# database.lancar_apuracao_diaria + database.verificar_e_premiar_meta_diaria (pontos da meta do dia,
# com estorno se o valor for corrigido para baixo).
# ------------------------------------------------------------------------------
def _meta_para(cur, d, hoje):
    """
    Meta da apuração: (1) a do lançamento que já existe nesse dia (corrigir = mesma meta, não duplica);
    (2) a meta cujo período tem o dia (de preferência 'Ativa'); (3) a meta ativa hoje (como no PC).
    Devolve (id, nome) ou None.
    """
    cur.execute("SELECT MetaPrincipalID FROM MetasDiariasApuracoes WHERE DataApuracao >= ? AND DataApuracao < ?",
                d, d + timedelta(days=1))
    ja = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT MetaPrincipalID, NomeMeta, DataInicio, DataFim, Status FROM MetasPrincipais")
    metas = [(r[0], r[1] or f"Meta {r[0]}", database._como_data(r[2]), database._como_data(r[3]), r[4]) for r in cur.fetchall()]
    nomes = {m[0]: m[1] for m in metas}
    if ja:
        return ja[0], nomes.get(ja[0], f"Meta {ja[0]}")
    def cobre(m, dia):
        return m[2] and m[3] and m[2] <= dia <= m[3]
    for filtro in (lambda m: cobre(m, d) and m[4] == 'Ativa', lambda m: cobre(m, d), lambda m: cobre(m, hoje) and m[4] == 'Ativa'):
        achadas = [m for m in metas if filtro(m)]
        if achadas:
            m = max(achadas, key=lambda m: m[2])
            return m[0], m[1]
    return None


def consultar_faturamento(data_txt, hoje=None):
    """Para a janela de lançar: o valor que já está lançado no dia e em qual meta vai entrar."""
    hoje = hoje or date.today()
    d = database._como_data(data_txt)
    if not d:
        raise ErroFolha("Data inválida.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        atual = _faturamento(cur, d, d).get(d)
        meta_id = _meta_para(cur, d, hoje)
    finally:
        conn.close()
    return {'data': d.isoformat(), 'valor': _num(atual), 'meta': meta_id[1] if meta_id else None,
            'futuro': d > hoje}


def lancar_faturamento(data_txt, valor_txt, usuario, hoje=None, em_segundo_plano=True):
    """Lança (ou corrige) o faturamento do dia, com os pontos da meta como na Gamificação."""
    hoje = hoje or date.today()
    d = database._como_data(data_txt)
    if not d:
        raise ErroFolha("Data inválida.")
    if d > hoje:
        raise ErroFolha("Não dá para lançar o faturamento de um dia que ainda não chegou.")
    v = _valor(valor_txt, 'Faturamento')
    if v is None:
        raise ErroFolha("Digite o valor do faturamento do dia.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        antes = _faturamento(cur, d, d).get(d)
        meta_id = _meta_para(cur, d, hoje)
    finally:
        conn.close()
    if not meta_id:
        raise ErroFolha(f"Nenhuma meta da Gamificação cobre o dia {d:%d/%m/%Y}. Cadastre ou ative a meta na "
                        "Gamificação (aba Metas) e lance de novo.")
    ok, resultado = database.lancar_apuracao_diaria(meta_id[0], d.isoformat(), float(v), (usuario or {}).get('id'))
    if not ok:
        raise ErroFolha(f"Não consegui gravar o faturamento: {resultado}")
    apuracao_id = resultado

    def premiar():
        try:
            database.verificar_e_premiar_meta_diaria(apuracao_id, d.isoformat(), float(v), meta_id[0])
        except Exception as e:
            logger.error(f"Folha × Faturamento: premiação da meta (ApuracaoID {apuracao_id}) falhou: {e}", exc_info=True)
    if em_segundo_plano:
        import threading
        threading.Thread(target=premiar, daemon=True).start()
    else:
        premiar()
    logger.info(f"Faturamento de {d} lançado pela Web: R$ {v} (antes: {antes}) na meta {meta_id[1]} "
                f"por {(usuario or {}).get('nome')}.")
    return {'data': d.isoformat(), 'valor': _num(v), 'antes': _num(antes), 'meta': meta_id[1]}


# ------------------------------------------------------------------------------
# [TELEGRAM] aviso antecipado, lembrete de faturamento e fechamento do mês
# ------------------------------------------------------------------------------
def _escalados(ini, fim):
    """{data: (fixos, freelas)} pela escala lançada."""
    conn = _conexao()
    try:
        esc = _escala(conn.cursor(), ini, fim)
    finally:
        conn.close()
    return {d: (len(x['fixos']), len(x['freelas'])) for d, x in esc.items()}


def _nome_dia(d, hoje):
    if d == hoje + timedelta(days=1):
        return f"Amanhã ({DIAS_SEMANA[d.weekday()]} {d:%d/%m})"
    nomes = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    return f"{nomes[d.weekday()]} {d:%d/%m}"


def avisos_antecipados(agora=None, enviados=(), dias_frente=(1, 2)):
    """
    Para amanhã e depois de amanhã (previsão):
      - escala com MENOS freelancers do que costuma precisar em dias parecidos (calor);
      - chuva à tarde prevista, quando nos dias de chuva desse tipo a venda cai 15% ou mais.
    Cada dia/aviso vai uma vez só. Devolve (texto, chaves novas) — texto vazio se não há nada.
    """
    agora = agora or datetime.now()
    hoje = agora.date()
    enviados = set(enviados or ())
    alvos = [hoje + timedelta(days=n) for n in dias_frente]
    climas = clima.do_periodo(min(alvos), max(alvos))
    if not any(climas.get(d) for d in alvos):
        return '', []
    hist = _historico_valido(dias(hoje - timedelta(days=DIAS_HISTORICO_AVISO), hoje), hoje)
    feriados = database._feriados_periodo(min(alvos), max(alvos))
    escala = _escalados(min(alvos), max(alvos))
    linhas, chaves = [], []
    for d in alvos:
        c = climas.get(d)
        if not c or c.get('max') is None:
            continue
        tipo_fds = _tipo_dia(d, feriados) != 'semana'
        fixos_esc, freelas_esc = escala.get(d, (0, 0))
        p = parecidos(hist, d, c, feriados)
        chave = f"{d.isoformat()}:freelas"
        if p and p.get('dias', 0) >= MIN_PARECIDOS_AVISO and chave not in enviados and not clima.chuvoso(c):
            esperado = Decimal(str(p['freelas']))
            if esperado.quantize(Decimal('1'), rounding=ROUND_HALF_UP) > freelas_esc:
                icone = '🔥' if c['max'] >= 33 else '📋'
                linhas.append(f"{icone} <b>{_nome_dia(d, hoje)} · {clima.texto(c)}</b>\n"
                              f"   Em {p['dias']} dias parecidos você faturou ~{_reais_redondo(p['faturamento'])} e usou "
                              f"<b>{_n(esperado)} freelancer(s)</b>. A escala ainda tem <b>{freelas_esc}</b>.")
                chaves.append(chave)
        chave = f"{d.isoformat()}:chuva"
        if clima.chuvoso(c) and chave not in enviados:
            mesmos = [x for x in hist if (x['tipo'] != 'semana') == tipo_fds and clima.tem_chuva_info(x['clima'])]
            chuva = [x['faturamento'] for x in mesmos if clima.chuvoso(x['clima'])]
            seco = [x['faturamento'] for x in mesmos if not clima.chuvoso(x['clima'])]
            if len(chuva) >= 2 and len(seco) >= 2:
                m_chuva, m_seco = _media(chuva), _media(seco)
                queda = _pct(m_seco - m_chuva, m_seco)
                if queda is not None and queda >= QUEDA_CHUVA_AVISO:
                    linhas.append(f"🌧️ <b>{_nome_dia(d, hoje)} · {clima.texto(c)}</b>\n"
                                  f"   Em dias de chuva ({'fim de semana/feriado' if tipo_fds else 'dia de semana'}) você vendeu "
                                  f"<b>{_n(queda)}% menos</b> (~{_reais_redondo(m_chuva)} × ~{_reais_redondo(m_seco)} sem chuva). "
                                  f"A escala tem {freelas_esc} freelancer(s)" + (": dá para chamar menos?" if freelas_esc else "."))
                    chaves.append(chave)
    if not linhas:
        return '', []
    return "📣 <b>Clima × escala</b>\n" + "\n".join(linhas) + "\n<i>Gestão › 📊 Folha para ver os detalhes.</i>", chaves


def dias_sem_faturamento(hoje=None, janela=7):
    """Dias (dos últimos 7, até ontem) sem faturamento lançado — sem contar os marcados como atípicos."""
    hoje = hoje or date.today()
    primeiro = primeiro_faturamento()
    if not primeiro:
        return []
    ini = max(primeiro, hoje - timedelta(days=janela))
    fim = hoje - timedelta(days=1)
    if ini > fim:
        return []
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        fat = _faturamento(cur, ini, fim)
        atip = _atipicos(cur, ini, fim)
    finally:
        conn.close()
    return [ini + timedelta(days=n) for n in range((fim - ini).days + 1)
            if ini + timedelta(days=n) not in fat and ini + timedelta(days=n) not in atip]


def texto_lembrete(faltam, hoje=None):
    hoje = hoje or date.today()
    if not faltam:
        return ''
    nomes = [("ontem" if d == hoje - timedelta(days=1) else DIAS_SEMANA[d.weekday()]) + f" {d:%d/%m}" for d in faltam]
    return ("⏰ <b>Faturamento não lançado</b>: " + ", ".join(nomes) + "\n"
            "Lance na Gestão › 📊 Folha (💰 Lançar faturamento), na Gamificação, ou no grupo com /lancar (só o de hoje).\n"
            "Loja fechada nesse dia? Marque como 📌 dia atípico na tabela do dia a dia e o lembrete para.")


def fechamento_pendente(hoje=None, ultimo_enviado=None):
    """(ano, mês) do mês anterior se o fechamento ainda não foi: do dia 1 ao 5 (espera os faturamentos atrasados)."""
    hoje = hoje or date.today()
    ant = date(hoje.year, hoje.month, 1) - timedelta(days=1)
    chave = f"{ant.year}-{ant.month:02d}"
    if ultimo_enviado == chave or hoje.day > DIAS_ESPERA_FECHAMENTO + 2:
        return None
    lista = dias(date(ant.year, ant.month, 1), ant)
    if not any(x['faturamento'] is not None for x in lista):
        return None
    faltam = [x for x in lista if x['faturamento'] is None and not x.get('atipico')]
    if faltam and hoje.day < DIAS_ESPERA_FECHAMENTO:
        return None
    return ant.year, ant.month


def fechamento(ano, mes):
    """Números do mês inteiro (para o Telegram do dia 1)."""
    ini = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    ini_ant = (ini - timedelta(days=1)).replace(day=1)
    lista = dias(ini_ant, fim)
    do_mes = [x for x in lista if x['data'] >= ini]
    ant = [x for x in lista if x['data'] < ini]
    a = acumulado(do_mes, fim + timedelta(days=1))
    a_ant = acumulado(ant, ini)
    validos = [x for x in do_mes if x['faturamento'] and not x.get('atipico')]
    com_clima = [x for x in do_mes if x['clima'] and x['clima'].get('max') is not None and not x['clima']['previsao']]
    return {'ano': ano, 'mes': mes, 'acumulado': a, 'anterior': a_ant, 'nome_ant': nome_mes(ini_ant.year, ini_ant.month),
            'melhor': max(validos, key=lambda x: x['faturamento']) if validos else None,
            'pior': min(validos, key=lambda x: x['faturamento']) if validos else None,
            'diarias': sum(x['freelas'] for x in do_mes),
            'max_media': _media([x['clima']['max'] for x in com_clima]),
            'dias_chuva': sum(1 for x in com_clima if clima.chuvoso(x['clima'])),
            'atipicos': [x for x in do_mes if x.get('atipico')]}


def texto_fechamento(f, hoje=None):
    hoje = hoje or date.today()
    meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
             'novembro', 'dezembro']
    a, ant, meta_pct = f['acumulado'], f['anterior'], meta()
    if not a:
        return ''
    linhas = [f"📅 <b>Fechamento de {meses[f['mes'] - 1]}/{f['ano']}</b> · Folha × Faturamento"]
    var = _pct(a['faturamento'] - ant['faturamento'], ant['faturamento']) if ant and ant['faturamento'] else None
    linhas.append(f"💰 Faturamento: <b>{_reais(a['faturamento'])}</b>"
                  + (f" ({'+' if var > 0 else ''}{_n(var)}% × {f['nome_ant']})" if var is not None else ''))
    if a['fixo'] is not None:
        linhas.append(f"🧾 Fixos {_reais(a['fixo'])}" + (f" (folha de {nome_mes(*a['estimado'])})" if a['estimado'] else '')
                      + f" · 🧑‍🍳 Freelancers {_reais(a['freela'])} ({f['diarias']} diária(s))")
        linhas.append(f"➡️ Folha do mês: {_linha_pct(a['pct'], meta_pct)} (meta {_n(meta_pct)}%)"
                      + (f" · {f['nome_ant']}: {_pct_txt(ant['pct'])}" if ant and ant['pct'] is not None else ''))
    else:
        linhas.append(f"🧑‍🍳 Freelancers {_reais(a['freela'])} ({f['diarias']} diária(s)) · informe a folha fixa para ver a %")
    for rotulo, x in (('🏆 Melhor dia', f['melhor']), ('📉 Pior dia', f['pior'])):
        if x:
            linhas.append(f"{rotulo}: {DIAS_SEMANA[x['data'].weekday()]} {x['data']:%d/%m} · {_reais(x['faturamento'])}"
                          + (f" · {clima.texto(x['clima'])}" if x['clima'] else ''))
    if f['max_media'] is not None:
        linhas.append(f"🌡️ Máxima média {_n(f['max_media'].quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))}° · "
                      f"{f['dias_chuva']} dia(s) de chuva à tarde")
    if a['faltam_lancar']:
        linhas.append(f"⚠️ Sem faturamento lançado: {', '.join(f'{d:%d/%m}' for d in a['faltam_lancar'][:8])}"
                      + ('…' if len(a['faltam_lancar']) > 8 else '') + " (a % fica maior que a real)")
    if f['atipicos']:
        linhas.append("📌 Atípicos (fora das médias): " + ", ".join(f"{x['data']:%d/%m} {x['atipico']}" for x in f['atipicos'][:5]))
    if (hoje.year, hoje.month) not in folhas_fixas():
        linhas.append(f"ℹ️ Informe a folha fixa de {meses[hoje.month - 1]} na Gestão › 📊 Folha (⚙️ Folha fixa e meta).")
    return "\n".join(linhas)


# ------------------------------------------------------------------------------
# Tela (Gestão › Folha × Faturamento)
# ------------------------------------------------------------------------------
def painel(mes=None, periodo='90', hoje=None, http=None):
    hoje = hoje or date.today()
    garantir_tabelas()
    ano, m = _mes(mes) if mes else (hoje.year, hoje.month)
    if periodo not in PERIODOS:
        periodo = '90'
    primeiro = primeiro_faturamento()
    erro_clima = clima.garantir_recente(desde=primeiro, http=http, hoje=hoje)
    ini_mes = date(ano, m, 1)
    fim_mes = min(date(ano, m, calendar.monthrange(ano, m)[1]), hoje)
    n = PERIODOS[periodo]
    ini_hist = (hoje - timedelta(days=n)) if n else (primeiro or hoje - timedelta(days=365))
    folhas = folhas_fixas()
    ini_ant = (ini_mes - timedelta(days=1)).replace(day=1)
    ini = min(ini_ant, ini_hist)
    fim = max(fim_mes, hoje)
    lista = dias(ini, fim, folhas) if ini <= fim else []
    do_mes = [x for x in lista if ini_mes <= x['data'] <= fim_mes]
    hist = [x for x in lista if x['data'] >= ini_hist]
    # mês anterior no MESMO período (dia 1 até o mesmo dia) para comparar
    a_mes = acumulado(do_mes, hoje)
    anterior = None
    if a_mes:
        ult_dia = min(a_mes['ate'].day, calendar.monthrange(ini_ant.year, ini_ant.month)[1])
        a_ant = acumulado([x for x in lista if ini_ant <= x['data'] <= ini_ant.replace(day=ult_dia)], hoje)
        if a_ant:
            anterior = {'nome': nome_mes(ini_ant.year, ini_ant.month), 'ate': a_ant['ate'].isoformat(),
                        'faturamento': _num(a_ant['faturamento']), 'pct': _num(a_ant['pct'], 1),
                        'var': _num(_pct(a_mes['faturamento'] - a_ant['faturamento'], a_ant['faturamento']), 1)}
    comp = comparativos(do_mes)
    meses = []
    if primeiro:
        a, mm = primeiro.year, primeiro.month
        while (a, mm) <= (hoje.year, hoje.month):
            meses.append(f"{a}-{mm:02d}")
            a, mm = (a + 1, 1) if mm == 12 else (a, mm + 1)
    if f"{hoje.year}-{hoje.month:02d}" not in meses:
        meses.append(f"{hoje.year}-{hoje.month:02d}")
    lista_folhas = []
    a, mm = hoje.year, hoje.month
    for _ in range(12):
        lista_folhas.append({'mes': f"{a}-{mm:02d}", 'nome': nome_mes(a, mm), 'valor': _num(folhas.get((a, mm)))})
        a, mm = (a - 1, 12) if mm == 1 else (a, mm - 1)
    return {'mes': f"{ano}-{m:02d}", 'nome_mes': nome_mes(ano, m), 'meses': meses[-24:], 'periodo': periodo,
            'meta': _num(meta(), 1), 'cidade': clima.CIDADE, 'erro_clima': erro_clima,
            'dias': [dict(_dia_json(x), comparar=comp.get(x['data'])) for x in reversed(do_mes)],
            'acumulado': _acumulado_json(a_mes), 'anterior': anterior, 'motivos_atipico': MOTIVOS_ATIPICO,
            'faixas': faixas(hist, hoje), 'proximos': proximos(lista, hoje),
            'folhas': lista_folhas, 'tem_folha': bool(folhas),
            'folha_do_mes': _num(folhas.get((ano, m)))}


def resumo(hoje=None, http=None):
    """Para o card do app: último dia com faturamento lançado + mês até ele + previsão de hoje/amanhã."""
    hoje = hoje or date.today()
    garantir_tabelas()
    erro_clima = clima.garantir_recente(http=http, hoje=hoje)
    ini = date(hoje.year, hoje.month, 1) - timedelta(days=31)
    lista = dias(min(ini, hoje - timedelta(days=90)), hoje)
    lancados = [x for x in lista if x['faturamento'] is not None]
    ultimo = lancados[-1] if lancados else None
    do_mes = [x for x in lista if ultimo and x['data'].year == ultimo['data'].year and x['data'].month == ultimo['data'].month]
    prox = proximos(lista, hoje)
    return {'meta': _num(meta(), 1), 'dia': _dia_json(ultimo) if ultimo else None,
            'acumulado': _acumulado_json(acumulado(do_mes, hoje)) if ultimo else None,
            'hoje': prox[0] if prox and prox[0]['data'] == hoje.isoformat() else None,
            'amanha': next((p for p in prox if p['data'] == (hoje + timedelta(days=1)).isoformat()), None),
            'erro_clima': erro_clima}


# ------------------------------------------------------------------------------
# Telegram: o resumo chega quando o faturamento do dia é lançado
# ------------------------------------------------------------------------------
def dias_para_avisar(enviados, agora=None, janela=7):
    """Dias (dos últimos 7) com faturamento lançado e ainda sem resumo. O de hoje só depois das 21h."""
    agora = agora or datetime.now()
    hoje = agora.date()
    garantir_tabelas()
    conn = _conexao()
    try:
        fat = _faturamento(conn.cursor(), hoje - timedelta(days=janela), hoje)
    finally:
        conn.close()
    enviados = set(enviados or [])
    return sorted(d for d in fat if d.isoformat() not in enviados and (d < hoje or agora.hour >= HORA_RESUMO_HOJE))


def _linha_pct(p, meta_pct):
    if p is None:
        return '—'
    return f"<b>{_pct_txt(p)}</b> {'✅' if p <= meta_pct else '⚠️'}"


def texto_telegram(datas, agora=None):
    """
    Mensagem (HTML) com o dia mais recente em detalhe e os outros em uma linha cada. No fim, a previsão
    do próximo dia de trabalho: amanhã (se já é noite) ou hoje (resumo de ontem que chegou de manhã).
    """
    import html
    agora = agora if isinstance(agora, datetime) else datetime.combine(agora or date.today(), datetime.now().time())
    hoje = agora.date()
    datas = sorted(datas)
    if not datas:
        return ''
    ultimo = datas[-1]
    ini = min(datas[0], date(ultimo.year, ultimo.month, 1))
    folhas = folhas_fixas()
    lista = dias(min(ini, hoje - timedelta(days=90)), max(ultimo, hoje), folhas)
    por_data = {x['data']: x for x in lista}
    meta_pct = meta()
    x = por_data[ultimo]
    a = acumulado([y for y in lista if y['data'].year == ultimo.year and y['data'].month == ultimo.month and y['data'] <= ultimo], hoje)
    linhas = [f"📊 <b>Folha × Faturamento</b> · {DIAS_SEMANA[ultimo.weekday()]} {ultimo:%d/%m}"
              + (f" ({html.escape(x['feriado'])})" if x['feriado'] else '')]
    if x['clima']:
        linhas.append(f"🌡️ {clima.texto(x['clima'])}")
    linhas.append(f"💰 Faturamento: <b>{_reais(x['faturamento'])}</b>")
    horas = x['horas_fixos'] + x['horas_freelas']
    linhas.append(f"👥 {x['fixos']} fixo(s) + {x['freelas']} freelancer(s)" + (f" · {R.fmt_horas(horas=horas)} trabalhadas" if horas else ''))
    if x['fixo'] is not None:
        linhas.append(f"🧾 Fixos {_reais(x['fixo'])} · Freelancers {_reais(x['freela'])}")
        linhas.append(f"➡️ Folha do dia: {_linha_pct(x['pct'], meta_pct)} (meta {_n(meta_pct)}%)")
    else:
        linhas.append(f"🧾 Freelancers {_reais(x['freela'])} ({_pct_txt(_pct(x['freela'], x['faturamento']))} do faturamento)")
        linhas.append("ℹ️ Informe a folha fixa do mês na Gestão › Folha × Faturamento para ver a % da folha.")
    if a and a['pct'] is not None:
        linhas.append(f"📅 Mês até {ultimo:%d/%m}: {_linha_pct(a['pct'], meta_pct)}"
                      + (f" (folha de {nome_mes(*a['estimado'])})" if a['estimado'] else ''))
    if a and a['faltam_lancar']:
        faltam = ', '.join(f"{d:%d/%m}" for d in a['faltam_lancar'][:6]) + ('…' if len(a['faltam_lancar']) > 6 else '')
        linhas.append(f"⚠️ Falta lançar o faturamento de: {faltam}")
    comp = comparativos([x]).get(ultimo) or {}
    if comp.get('semana', {}).get('faturamento') is not None or comp.get('ano', {}).get('faturamento') is not None:
        linhas.append("↔️ " + _linha_comparacao('Semana passada', comp.get('semana')))
        if comp.get('ano', {}).get('faturamento') is not None:
            linhas.append("↔️ " + _linha_comparacao('Ano passado', comp.get('ano')))
    if x.get('atipico'):
        linhas.append(f"📌 Dia atípico: {html.escape(x['atipico'])} (fora das médias)")
    outros = [por_data[d] for d in datas[:-1] if d in por_data]
    if outros:
        linhas.append("Também lançados: " + " · ".join(
            f"{DIAS_SEMANA[y['data'].weekday()]} {y['data']:%d/%m} {_reais(y['faturamento'])}"
            + (f" ({_pct_txt(y['pct'])})" if y['pct'] is not None else '') for y in outros))
    alvo, rotulo = (hoje + timedelta(days=1), 'Amanhã') if agora.hour >= HORA_RESUMO_HOJE else (hoje, 'Hoje')
    prox = next((p for p in proximos(lista, hoje) if p['data'] == alvo.isoformat()), None)
    if prox and prox['clima']:
        p = prox['parecidos'] or {}
        linhas.append(f"🔮 {rotulo} ({prox['dia']}): {prox['clima']['texto']}"
                      + (f" · em dias parecidos: ~{_reais_redondo(p['faturamento'])} e "
                         f"{_n(Decimal(str(p['freelas'])))} freelancer(s)" if p.get('faturamento') else ''))
    return "\n".join(linhas)

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
            'icone': clima.icone(c), 'texto': clima.texto(c)}


def dias(ini, fim, folhas=None, climas=None):
    """Um registro por dia do período (com ou sem faturamento). Valores em Decimal (para somar)."""
    garantir_tabelas()
    folhas = folhas_fixas() if folhas is None else folhas
    conn = _conexao()
    try:
        cur = conn.cursor()
        fat = _faturamento(cur, ini, fim)
        esc = _escala(cur, ini, fim)
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
            'por_hora': _num(x['por_hora'])}


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
            'faltam_lancar': [x['data'] for x in ate if x['faturamento'] is None and x['data'] < hoje],
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
    """Dias que entram nas médias: com faturamento e com temperatura medida (não previsão)."""
    return [x for x in lista if x['faturamento'] and x['clima'] and x['clima']['max'] is not None
            and not x['clima']['previsao'] and x['data'] <= hoje]


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
                'chuva': sum(1 for x in sel if x['clima']['chuva'] is not None and x['clima']['chuva'] >= clima.CHUVA_DIA_MM)})
        chuva = [x for x in xs if x['clima']['chuva'] is not None and x['clima']['chuva'] >= clima.CHUVA_DIA_MM]
        seco = [x for x in xs if x['clima']['chuva'] is not None and x['clima']['chuva'] < clima.CHUVA_DIA_MM]
        saida[nome] = {'faixas': linhas, 'dias': len(xs),
                       'chuva': {'dias': len(chuva), 'faturamento': _num(_media([x['faturamento'] for x in chuva]))},
                       'seco': {'dias': len(seco), 'faturamento': _num(_media([x['faturamento'] for x in seco]))}}
    return saida


def parecidos(hist, d, c, feriados):
    """Dias do histórico do mesmo tipo (semana × fim de semana/feriado) com máxima parecida."""
    if not c or c.get('max') is None:
        return None
    fds = _tipo_dia(d, feriados) != 'semana'
    sel = [x for x in hist if (x['tipo'] != 'semana') == fds and abs(x['clima']['max'] - c['max']) <= PARECIDO_GRAUS]
    if len(sel) < MIN_PARECIDOS:
        return {'dias': len(sel)}
    return {'dias': len(sel), 'faturamento': _num(_media([x['faturamento'] for x in sel])),
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
    ini = min(ini_mes, ini_hist)
    fim = max(fim_mes, hoje)
    lista = dias(ini, fim, folhas) if ini <= fim else []
    do_mes = [x for x in lista if ini_mes <= x['data'] <= fim_mes]
    hist = [x for x in lista if x['data'] >= ini_hist]
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
            'dias': [_dia_json(x) for x in reversed(do_mes)],
            'acumulado': _acumulado_json(acumulado(do_mes, hoje)),
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

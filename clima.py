# -*- coding: utf-8 -*-
# ==============================================================================
# == clima.py - Temperatura máxima/mínima e chuva de cada dia ===================
# ==============================================================================
# [FOLHA × FATURAMENTO] Quanto mais calor, mais venda (e mais freelancer). Aqui o
# sistema guarda o clima de cada dia da loja (Rondonópolis - MT) para cruzar com o
# faturamento e a escala.
#
# Fonte: Open-Meteo (gratuito, sem cadastro e sem chave):
#   - previsão + últimos 14 dias:  api.open-meteo.com/v1/forecast
#   - dias antigos (histórico):    archive-api.open-meteo.com/v1/archive
# Assim o histórico já começa com todos os dias que têm faturamento lançado.
#
# Outra cidade? No config.py: CLIMA_CIDADE, CLIMA_LATITUDE e CLIMA_LONGITUDE.
#
# [CHUVA POR HORÁRIO] Em sorveteria, chuva às 15h derruba a venda; chuva às 6h quase não.
# Além da chuva do dia inteiro, guarda a chuva da TARDE/NOITE (12h às 22h) e quantas horas
# choveu nesse horário. É ela que separa "dia de chuva" de "dia seco" nas contas.
# ==============================================================================
import logging
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

import config
import database

logger = logging.getLogger(__name__)

CIDADE = getattr(config, 'CLIMA_CIDADE', 'Rondonópolis - MT')
LATITUDE = getattr(config, 'CLIMA_LATITUDE', -16.4708)
LONGITUDE = getattr(config, 'CLIMA_LONGITUDE', -54.6356)
FUSO = getattr(config, 'CLIMA_FUSO', 'America/Cuiaba')
URL_PREVISAO = 'https://api.open-meteo.com/v1/forecast'
URL_HISTORICO = 'https://archive-api.open-meteo.com/v1/archive'
CAMPOS = 'temperature_2m_max,temperature_2m_min,precipitation_sum'
DIAS_PASSADOS_PREVISAO = 14     # a API de previsão traz os últimos 14 dias medidos
DIAS_PREVISAO = 8               # hoje + 7 dias
CHUVA_DIA_MM = Decimal('5')     # sem a chuva por horário (dias antigos): 5 mm no dia = "dia de chuva"
HORA_INICIO_TARDE, HORA_FIM_TARDE = 12, 22    # horário que mais vende (chuva aqui é a que pesa)
CHUVA_TARDE_MM = Decimal('2')   # 2 mm entre 12h e 22h = "chuva à tarde"
GAROA_MM = Decimal('0.2')

_tabela_ok = False
_ultima_tentativa = {}          # (só no processo da API) não fica chamando a internet a cada clique


class ErroClima(Exception):
    pass


def garantir_tabela():
    global _tabela_ok
    if _tabela_ok:
        return
    conn = database.get_db_connection()
    if not conn:
        raise ErroClima("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ClimaDiario')
            CREATE TABLE ClimaDiario (
                Data DATE NOT NULL PRIMARY KEY,
                TempMax DECIMAL(4, 1) NULL,
                TempMin DECIMAL(4, 1) NULL,
                ChuvaMM DECIMAL(6, 1) NULL,
                Previsao BIT NOT NULL DEFAULT 0,
                AtualizadoEm DATETIME NULL
            )
        """)
        # [CHUVA POR HORÁRIO] quem já tinha a tabela ganha as colunas (o histórico é refeito sozinho)
        cur.execute("IF COL_LENGTH('ClimaDiario', 'ChuvaTardeMM') IS NULL ALTER TABLE ClimaDiario ADD ChuvaTardeMM DECIMAL(6, 1) NULL")
        cur.execute("IF COL_LENGTH('ClimaDiario', 'HorasChuvaTarde') IS NULL ALTER TABLE ClimaDiario ADD HorasChuvaTarde INT NULL")
        conn.commit()
        _tabela_ok = True
    finally:
        conn.close()


def _dec(v):
    if v is None:
        return None
    try:
        return Decimal(str(v)).quantize(Decimal('0.1'))
    except Exception:
        return None


def _chuva_da_tarde(dados):
    """{data: (mm entre 12h e 22h, horas com chuva nesse horário)} a partir do 'hourly' da Open-Meteo."""
    h = dados.get('hourly') or {}
    horas, chuvas = h.get('time') or [], h.get('precipitation') or []
    por_dia = {}
    for i, txt in enumerate(horas):
        try:
            momento = datetime.fromisoformat(str(txt)[:16])
        except ValueError:
            continue
        if not (HORA_INICIO_TARDE <= momento.hour < HORA_FIM_TARDE):
            continue
        v = _dec(chuvas[i]) if i < len(chuvas) else None
        if v is None:
            continue
        mm, n = por_dia.get(momento.date(), (Decimal('0'), 0))
        por_dia[momento.date()] = (mm + v, n + (1 if v >= GAROA_MM else 0))
    return por_dia


def _baixar(url, params, http=None):
    """[(data, máx, mín, chuva, chuva da tarde, horas de chuva à tarde)] da Open-Meteo. http = como requests.get (testes trocam)."""
    if http is None:
        import requests
        http = requests.get
    p = dict(params, latitude=LATITUDE, longitude=LONGITUDE, daily=CAMPOS, hourly='precipitation', timezone=FUSO)
    try:
        r = http(url, params=p, timeout=20)
        dados = r.json()
    except Exception as e:
        raise ErroClima(f"Não consegui buscar o clima na internet ({e}).")
    if getattr(r, 'status_code', 200) != 200 or not isinstance(dados, dict) or dados.get('error'):
        motivo = dados.get('reason') if isinstance(dados, dict) else ''
        raise ErroClima(f"O serviço de clima recusou o pedido: {motivo or getattr(r, 'status_code', '?')}")
    d = dados.get('daily') or {}
    datas = d.get('time') or []
    maxs, mins, chuvas = (d.get('temperature_2m_max') or [], d.get('temperature_2m_min') or [],
                          d.get('precipitation_sum') or [])
    tarde = _chuva_da_tarde(dados)
    linhas = []
    for i, txt in enumerate(datas):
        try:
            dia = date.fromisoformat(str(txt)[:10])
        except ValueError:
            continue
        pega = lambda lista: _dec(lista[i]) if i < len(lista) else None
        mm, horas = tarde.get(dia, (None, None))
        linhas.append((dia, pega(maxs), pega(mins), pega(chuvas), _dec(mm), horas))
    return linhas


def _gravar(linhas, hoje=None):
    """Grava/atualiza os dias. Dia já medido não volta a ser previsão; dado vazio não apaga o que havia."""
    hoje = hoje or date.today()
    garantir_tabela()
    conn = database.get_db_connection()
    if not conn:
        raise ErroClima("Sem conexão com o banco de dados.")
    gravados = 0
    try:
        cur = conn.cursor()
        agora = datetime.now()
        for linha in linhas:
            dia, tmax, tmin, chuva = linha[:4]
            tarde, horas = (linha[4], linha[5]) if len(linha) > 5 else (None, None)
            if tmax is None and tmin is None:
                continue
            previsao = 1 if dia >= hoje else 0
            cur.execute("SELECT Previsao FROM ClimaDiario WHERE Data = ?", str(dia))
            r = cur.fetchone()
            if r is None:
                cur.execute("INSERT INTO ClimaDiario (Data, TempMax, TempMin, ChuvaMM, ChuvaTardeMM, HorasChuvaTarde, Previsao, "
                            "AtualizadoEm) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", str(dia), tmax, tmin, chuva, tarde, horas, previsao, agora)
            elif previsao and not r[0]:
                continue
            else:
                cur.execute("""UPDATE ClimaDiario SET TempMax = COALESCE(?, TempMax), TempMin = COALESCE(?, TempMin),
                               ChuvaMM = COALESCE(?, ChuvaMM), ChuvaTardeMM = COALESCE(?, ChuvaTardeMM),
                               HorasChuvaTarde = COALESCE(?, HorasChuvaTarde), Previsao = ?, AtualizadoEm = ? WHERE Data = ?""",
                            tmax, tmin, chuva, tarde, horas, previsao, agora, str(dia))
            gravados += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return gravados


def atualizar(http=None, hoje=None):
    """Últimos 14 dias (medidos) + hoje e os próximos 7 (previsão). Devolve quantos dias gravou."""
    linhas = _baixar(URL_PREVISAO, {'past_days': DIAS_PASSADOS_PREVISAO, 'forecast_days': DIAS_PREVISAO}, http)
    n = _gravar(linhas, hoje)
    logger.info(f"Clima: {n} dia(s) atualizado(s) ({CIDADE}).")
    return n


def completar_historico(desde, http=None, hoje=None):
    """
    Busca no histórico os dias desde 'desde' que ainda não têm clima medido (para o cruzamento com o
    faturamento já começar com o passado). Os últimos 14 dias ficam com a previsão (o histórico demora
    alguns dias para sair). Uma chamada só para o período inteiro. Devolve quantos dias gravou.
    """
    hoje = hoje or date.today()
    desde = database._como_data(desde)
    ate = hoje - timedelta(days=DIAS_PASSADOS_PREVISAO + 1)
    if not desde or desde > ate:
        return 0
    garantir_tabela()
    conn = database.get_db_connection()
    if not conn:
        raise ErroClima("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT Data FROM ClimaDiario WHERE Data >= ? AND Data <= ? AND Previsao = 0 AND TempMax IS NOT NULL "
                    "AND ChuvaTardeMM IS NOT NULL", str(desde), str(ate))
        tem = {database._como_data(r[0]) for r in cur.fetchall()}
    finally:
        conn.close()
    faltam = [desde + timedelta(days=i) for i in range((ate - desde).days + 1)]
    faltam = [d for d in faltam if d not in tem]
    if not faltam:
        return 0
    linhas = _baixar(URL_HISTORICO, {'start_date': str(faltam[0]), 'end_date': str(faltam[-1])}, http)
    n = _gravar([l for l in linhas if l[0] in set(faltam)], hoje)
    logger.info(f"Clima: histórico completado com {n} dia(s) ({faltam[0]} a {faltam[-1]}).")
    return n


def do_periodo(ini, fim):
    """{data: {'max', 'min', 'chuva', 'previsao'}} do banco (sem internet)."""
    garantir_tabela()
    conn = database.get_db_connection()
    if not conn:
        raise ErroClima("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT Data, TempMax, TempMin, ChuvaMM, Previsao, ChuvaTardeMM, HorasChuvaTarde FROM ClimaDiario "
                    "WHERE Data >= ? AND Data <= ?", str(ini), str(fim))
        return {database._como_data(r[0]): {'max': _dec(r[1]), 'min': _dec(r[2]), 'chuva': _dec(r[3]), 'previsao': bool(r[4]),
                                            'chuva_tarde': _dec(r[5]), 'horas_chuva': r[6]}
                for r in cur.fetchall()}
    finally:
        conn.close()


def garantir_recente(desde=None, http=None, hoje=None, intervalo_min=30):
    """
    Para a tela: se ainda não tem o clima de hoje (ou o histórico desde 'desde'), busca agora.
    No máximo uma tentativa a cada 30 minutos (sem internet, a tela abre igual, só sem o clima novo).
    Devolve a mensagem de erro (ou None).
    """
    hoje = hoje or date.today()
    agora = time.monotonic()
    erro = None
    try:
        tem = do_periodo(hoje - timedelta(days=1), hoje)
    except ErroClima as e:
        return str(e)
    if (hoje not in tem or (hoje - timedelta(days=1)) not in tem) and \
            agora - _ultima_tentativa.get('recente', -1e9) > intervalo_min * 60:
        _ultima_tentativa['recente'] = agora
        try:
            atualizar(http, hoje)
        except ErroClima as e:
            erro = str(e)
            logger.warning(f"Clima: {e}")
    if desde and agora - _ultima_tentativa.get('historico', -1e9) > intervalo_min * 60:
        _ultima_tentativa['historico'] = agora
        try:
            completar_historico(desde, http, hoje)
        except ErroClima as e:
            erro = erro or str(e)
            logger.warning(f"Clima (histórico): {e}")
    return erro


def chuvoso(c):
    """Dia de chuva para as contas: chuva à TARDE (12h-22h) >= 2 mm; dia antigo sem o horário: 5 mm no dia."""
    if not c:
        return False
    if c.get('chuva_tarde') is not None:
        return c['chuva_tarde'] >= CHUVA_TARDE_MM
    return c.get('chuva') is not None and c['chuva'] >= CHUVA_DIA_MM


def tem_chuva_info(c):
    return bool(c) and (c.get('chuva_tarde') is not None or c.get('chuva') is not None)


def icone(c):
    """☀️ / 🌤️ (choveu só fora do horário) / 🌦️ (garoa à tarde) / 🌧️ (chuva à tarde)."""
    if not tem_chuva_info(c):
        return ''
    if chuvoso(c):
        return '🌧️'
    if c.get('chuva_tarde') is not None:
        if c['chuva_tarde'] >= GAROA_MM:
            return '🌦️'
        return '🌤️' if (c.get('chuva') or 0) >= 1 else '☀️'
    return '🌦️' if c['chuva'] >= 1 else '☀️'


def _mm(v):
    """6.0 -> '6' · 6.5 -> '6,5' · 10.0 -> '10' (nunca '1E+1')."""
    return format(Decimal(v).normalize(), 'f').replace('.', ',')


def texto_chuva(c):
    """'sem chuva' / 'chuva à tarde (6 mm, 3 h)' / 'garoa à tarde' / '4 mm fora do horário de pico'."""
    if not tem_chuva_info(c):
        return ''
    if c.get('chuva_tarde') is not None:
        if chuvoso(c):
            horas = f", {c['horas_chuva']} h" if c.get('horas_chuva') else ''
            return f"chuva à tarde ({_mm(c['chuva_tarde'])} mm{horas})"
        if c['chuva_tarde'] >= GAROA_MM:
            return f"garoa à tarde ({_mm(c['chuva_tarde'])} mm)"
        if (c.get('chuva') or 0) >= 1:
            return f"{_mm(c['chuva'])} mm só fora do horário de pico"
        return 'sem chuva'
    return 'sem chuva' if c['chuva'] < 1 else f"{_mm(c['chuva'])} mm de chuva"


def texto(c):
    """'34° / 23° ☀️ sem chuva' (ou '' sem dados)."""
    if not c or (c.get('max') is None and c.get('min') is None):
        return ''
    temps = f"{c['max']:.0f}° / {c['min']:.0f}°" if c.get('max') is not None and c.get('min') is not None else \
        f"{(c.get('max') or c.get('min')):.0f}°"
    if not tem_chuva_info(c):
        return temps
    return f"{temps} {icone(c)} {texto_chuva(c)}"

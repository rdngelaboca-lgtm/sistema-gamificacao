# ==============================================================================
# == folgas.py - [5x2] As folgas de cada funcionário FIXO (a regra única do sistema)
# ==============================================================================
# Responde UMA pergunta para o sistema inteiro: "fulano está de folga neste dia?".
# A escala automática dos fixos, o robô (tarefas no grupo, avisos do bot), a Escala (PC e Web),
# o ranking e a tela 📅 Folgas perguntam AQUI — assim ninguém discorda de ninguém.
#
# A ordem da resposta:
#   1. Férias/afastamento (o cadastro do funcionário)              -> não trabalha
#   2. Troca avulsa do dia (FolgasExcecao: 'folga' ou 'trabalha')   -> vale o que foi trocado
#   3. O PADRÃO de folgas que vale no dia (FolgasPadrao, com data de início):
#        - 5x2 fixo:   os mesmos dias toda semana              (Ciclo '2,3' = segunda e terça)
#        - 5x2 rodízio: um ciclo de semanas que se repete       (Ciclo '2,3|3,4|1,2')
#        - sem Ciclo:  volta para a folga do cadastro (6x1)
#   4. Sem padrão nenhum: a folga do cadastro (6x1 = folga fixa da semana + domingo do mês), como sempre foi.
#
# Dias da semana no padrão do banco: 1=Dom, 2=Seg ... 7=Sáb. A semana do ciclo vai de SEGUNDA a DOMINGO
# e a 1ª semana é a que tem a data de início.
# As tabelas e as regras ficam numa "memória" de 60 s (o robô e o PC enxergam uma mudança em até 1 minuto).
# ==============================================================================
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta

import database

logger = logging.getLogger(__name__)

TTL_MEMORIA = 60
DIAS_NOME = {1: 'domingo', 2: 'segunda', 3: 'terça', 4: 'quarta', 5: 'quinta', 6: 'sexta', 7: 'sábado'}
DIAS_CURTO = {1: 'Dom', 2: 'Seg', 3: 'Ter', 4: 'Qua', 5: 'Qui', 6: 'Sex', 7: 'Sáb'}
ORDEM_SEMANA = [2, 3, 4, 5, 6, 7, 1]          # a semana da tela: segunda ... domingo
MAX_SEMANAS_CICLO = 8
DIAS_HISTORICO_TROCAS = 400

REGRAS_PADRAO = {
    'limites_horas': [{'desde': '2000-01-01', 'horas': 44}],   # o limite que vale a partir de cada data
    'domingo_semanas': 3,          # avisa quem trabalhar este número de domingos seguidos (0 = não avisa)
    'max_dias_seguidos': 6,        # avisa quem passar disto sem folga (0 = não avisa)
    'minimos': {},                 # {setor: [seg, ter, qua, qui, sex, sáb, dom]} pessoas no mínimo (0 = não avisa)
}

_tabelas_ok = False
_trava = threading.Lock()
_memoria = {'quando': 0.0, 'padroes': {}, 'trocas': {}, 'regras': None}


# ------------------------------------------------------------------------------
# Ajudantes
# ------------------------------------------------------------------------------
def dia_semana(d):
    """date -> 1=Dom, 2=Seg ... 7=Sáb."""
    return (d.isoweekday() % 7) + 1


def segunda(d):
    return d - timedelta(days=d.weekday())


def como_data(valor):
    if valor is None or valor == '':
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _int(valor, padrao=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def ler_ciclo(texto):
    """'2,3|3,4' -> [[2, 3], [3, 4]] (só dias de 1 a 7, sem repetir, em ordem de segunda a domingo)."""
    if not texto:
        return None
    semanas = []
    for parte in str(texto).split('|'):
        dias = []
        for x in parte.split(','):
            n = _int(x.strip(), -1)
            if 1 <= n <= 7 and n not in dias:
                dias.append(n)
        semanas.append(sorted(dias, key=ORDEM_SEMANA.index))
    return semanas or None


def texto_ciclo(semanas):
    return '|'.join(','.join(str(d) for d in sorted(s, key=ORDEM_SEMANA.index)) for s in semanas)


def descrever_ciclo(semanas):
    """[[2, 3]] -> '5x2: seg e ter'; [[2, 3], [7, 1]] -> 'Rodízio de 2 semanas: seg e ter / sáb e dom'."""
    if not semanas:
        return "6x1 (folga do cadastro)"
    partes = [" e ".join(DIAS_CURTO[d].lower() for d in s) or "sem folga" for s in semanas]
    if len(semanas) == 1:
        return f"5x2: {partes[0]}"
    return f"Rodízio de {len(semanas)} semanas: " + " / ".join(partes)


def descrever_cadastro(func):
    """A folga do cadastro (6x1): 'segunda + 2º domingo do mês' / 'sem folga fixa'."""
    partes = []
    folga = _int(getattr(func, 'DiaDeFolga', 0))
    if 1 <= folga <= 7:
        partes.append(DIAS_NOME[folga])
    dom = _int(getattr(func, 'DomingoFolgaMensal', 0))
    if dom > 0:
        partes.append(f"{dom}º domingo do mês")
    return " + ".join(partes) or "sem folga fixa"


# ------------------------------------------------------------------------------
# Tabelas e memória
# ------------------------------------------------------------------------------
def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = database.get_db_connection()
    if not conn:
        raise ConnectionError("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FolgasPadrao')
            CREATE TABLE FolgasPadrao (
                PadraoID INT IDENTITY(1,1) PRIMARY KEY,
                FuncionarioID INT NOT NULL,
                ValidoDesde DATE NOT NULL,
                Ciclo VARCHAR(80) NULL,
                CriadoEm DATETIME NOT NULL DEFAULT GETDATE(),
                CriadoPor NVARCHAR(80) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FolgasExcecao')
            CREATE TABLE FolgasExcecao (
                FuncionarioID INT NOT NULL,
                Data DATE NOT NULL,
                Tipo VARCHAR(10) NOT NULL,
                Motivo NVARCHAR(150) NULL,
                CriadoEm DATETIME NOT NULL DEFAULT GETDATE(),
                CriadoPor NVARCHAR(80) NULL,
                PRIMARY KEY (FuncionarioID, Data)
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FolgasRegras')
            CREATE TABLE FolgasRegras (
                Chave VARCHAR(40) NOT NULL PRIMARY KEY,
                Valor NVARCHAR(MAX) NULL
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def invalidar():
    """Depois de gravar: a próxima pergunta lê o banco de novo."""
    _memoria['quando'] = 0.0


def _ler_banco():
    garantir_tabelas()
    conn = database.get_db_connection()
    if not conn:
        raise ConnectionError("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT PadraoID, FuncionarioID, ValidoDesde, Ciclo FROM FolgasPadrao")
        padroes = {}
        for pid, fid, desde, ciclo in cur.fetchall():
            d = como_data(desde)
            if d:
                padroes.setdefault(int(fid), []).append((d, ler_ciclo(ciclo), int(pid)))
        for lista in padroes.values():
            lista.sort(key=lambda x: (x[0], x[2]))
        limite = (date.today() - timedelta(days=DIAS_HISTORICO_TROCAS)).isoformat()
        cur.execute("SELECT FuncionarioID, Data, Tipo, Motivo FROM FolgasExcecao WHERE Data >= ?", limite)
        trocas = {}
        for fid, d, tipo, motivo in cur.fetchall():
            d = como_data(d)
            if d and tipo in ('folga', 'trabalha'):
                trocas[(int(fid), d)] = (tipo, motivo or '')
        cur.execute("SELECT Valor FROM FolgasRegras WHERE Chave = 'regras'")
        r = cur.fetchone()
        regras = _regras_de(r[0] if r else None)
        return padroes, trocas, regras
    finally:
        conn.close()


def _regras_de(texto):
    regras = json.loads(json.dumps(REGRAS_PADRAO))
    try:
        salvas = json.loads(texto) if texto else {}
    except ValueError:
        salvas = {}
    if isinstance(salvas, dict):
        for k in REGRAS_PADRAO:
            if k in salvas:
                regras[k] = salvas[k]
    return regras


def memoria(forcar=False):
    """(padroes, trocas, regras) lidos do banco no máximo a cada 60 s."""
    agora = time.monotonic()
    if not forcar and _memoria['regras'] is not None and agora - _memoria['quando'] < TTL_MEMORIA:
        return _memoria['padroes'], _memoria['trocas'], _memoria['regras']
    with _trava:
        if not forcar and _memoria['regras'] is not None and time.monotonic() - _memoria['quando'] < TTL_MEMORIA:
            return _memoria['padroes'], _memoria['trocas'], _memoria['regras']
        try:
            padroes, trocas, regras = _ler_banco()
            _memoria.update(quando=time.monotonic(), padroes=padroes, trocas=trocas, regras=regras)
        except Exception as e:
            # banco fora do ar: usa o que já tinha (ou só o cadastro) e tenta de novo daqui a pouco
            logger.warning(f"Folgas: não consegui ler os padrões/trocas ({e}); usando o que já estava na memória.")
            if _memoria['regras'] is None:
                _memoria.update(padroes={}, trocas={}, regras=_regras_de(None))
            _memoria['quando'] = time.monotonic() - TTL_MEMORIA + 10
        return _memoria['padroes'], _memoria['trocas'], _memoria['regras']


def regras():
    return memoria()[2]


# ------------------------------------------------------------------------------
# A pergunta: está de folga?
# ------------------------------------------------------------------------------
def padrao_no_dia(funcionario_id, d, padroes=None):
    """(ValidoDesde, ciclo ou None, PadraoID) do padrão que vale no dia, ou None (vale o cadastro)."""
    padroes = memoria()[0] if padroes is None else padroes
    atual = None
    for p in padroes.get(int(funcionario_id), []):
        if p[0] <= d:
            atual = p
        else:
            break
    return atual


def semana_do_ciclo(desde, d, n):
    """0, 1, ... n-1: em que semana do rodízio o dia cai (a semana da data de início é a 1ª)."""
    return ((segunda(d) - segunda(desde)).days // 7) % max(n, 1)


def situacao(func, d, sem_troca=False, padroes=None, trocas=None):
    """
    None = trabalha neste dia. Senão {'tipo', 'texto', 'origem'}:
      tipo 'afastamento' (férias/atestado), 'folga' (do padrão ou do cadastro), 'domingo' (domingo do mês, 6x1),
      'troca' (folga trocada para este dia).
      origem '5x2' / 'rodizio' / '6x1' / 'troca' / 'cadastro'.
    sem_troca=True: o que o padrão diz (para saber se uma troca é necessária).
    """
    d = como_data(d)
    if d is None or func is None:
        return None
    if padroes is None or trocas is None:
        p_mem, t_mem, _r = memoria()
        padroes = p_mem if padroes is None else padroes
        trocas = t_mem if trocas is None else trocas
    ini = como_data(getattr(func, 'DataInicioAfastamento', None))
    fim = como_data(getattr(func, 'DataFimAfastamento', None))
    if ini and fim and ini <= d <= fim:
        return {'tipo': 'afastamento', 'texto': 'Férias/afastamento', 'origem': 'cadastro'}
    fid = _int(getattr(func, 'FuncionarioID', 0))
    if not sem_troca:
        troca = trocas.get((fid, d))
        if troca:
            if troca[0] == 'trabalha':
                return None
            return {'tipo': 'troca', 'texto': 'Folga trocada' + (f" ({troca[1]})" if troca[1] else ''), 'origem': 'troca'}
    dsem = dia_semana(d)
    p = padrao_no_dia(fid, d, padroes) if fid else None
    if p and p[1]:
        semanas = p[1]
        if dsem in semanas[semana_do_ciclo(p[0], d, len(semanas))]:
            rod = len(semanas) > 1
            return {'tipo': 'folga', 'texto': 'Folga (rodízio)' if rod else 'Folga (5x2)', 'origem': 'rodizio' if rod else '5x2'}
        return None
    # 6x1: a folga do cadastro
    if dsem == _int(getattr(func, 'DiaDeFolga', 0), -1):
        return {'tipo': 'folga', 'texto': 'Folga semanal', 'origem': '6x1'}
    dom = _int(getattr(func, 'DomingoFolgaMensal', 0))
    if dsem == 1 and dom > 0 and (d.day - 1) // 7 + 1 == dom:
        return {'tipo': 'domingo', 'texto': f"Domingo de Folga ({dom}º do mês)", 'origem': '6x1'}
    return None


def esta_de_folga(func, d):
    """True só para FOLGA (padrão, cadastro, domingo ou troca); férias/afastamento não conta aqui."""
    s = situacao(func, d)
    return bool(s) and s['tipo'] != 'afastamento'


class _Cadastro:
    """Para quem só tem os campos do cadastro (ex.: database.motivo_indisponibilidade)."""
    def __init__(self, funcionario_id, dia_folga, domingo, ini, fim):
        self.FuncionarioID = funcionario_id
        self.DiaDeFolga = dia_folga
        self.DomingoFolgaMensal = domingo
        self.DataInicioAfastamento = ini
        self.DataFimAfastamento = fim


def situacao_por_campos(funcionario_id, dia_folga, domingo, ini, fim, d):
    return situacao(_Cadastro(funcionario_id, dia_folga, domingo, ini, fim), d)


# ------------------------------------------------------------------------------
# Gravar (padrão, troca, regras)
# ------------------------------------------------------------------------------
def _conexao():
    garantir_tabelas()
    conn = database.get_db_connection()
    if not conn:
        raise ConnectionError("Sem conexão com o banco de dados.")
    return conn


def gravar_padrao(funcionario_id, desde, semanas, quem=''):
    """Padrão a partir da data (semanas=None: volta para a folga do cadastro). A mesma data: substitui."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        ciclo = texto_ciclo(semanas) if semanas else None
        cur.execute("DELETE FROM FolgasPadrao WHERE FuncionarioID = ? AND ValidoDesde = ?", int(funcionario_id), desde.isoformat())
        cur.execute("INSERT INTO FolgasPadrao (FuncionarioID, ValidoDesde, Ciclo, CriadoEm, CriadoPor) VALUES (?, ?, ?, GETDATE(), ?)",
                    int(funcionario_id), desde.isoformat(), ciclo, (quem or '')[:80] or None)
        conn.commit()
    finally:
        conn.close()
    invalidar()


def apagar_padrao(funcionario_id, padrao_id):
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM FolgasPadrao WHERE PadraoID = ? AND FuncionarioID = ?", int(padrao_id), int(funcionario_id))
        n = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    invalidar()
    return n


def gravar_troca(funcionario_id, d, tipo, motivo='', quem=''):
    """tipo 'folga' / 'trabalha' / None (apaga a troca: volta ao padrão)."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM FolgasExcecao WHERE FuncionarioID = ? AND Data = ?", int(funcionario_id), d.isoformat())
        if tipo in ('folga', 'trabalha'):
            cur.execute("INSERT INTO FolgasExcecao (FuncionarioID, Data, Tipo, Motivo, CriadoEm, CriadoPor) "
                        "VALUES (?, ?, ?, ?, GETDATE(), ?)", int(funcionario_id), d.isoformat(), tipo,
                        (motivo or '')[:150] or None, (quem or '')[:80] or None)
        conn.commit()
    finally:
        conn.close()
    invalidar()


def gravar_regras(novas):
    conn = _conexao()
    try:
        cur = conn.cursor()
        texto = json.dumps(novas, ensure_ascii=False)
        cur.execute("DELETE FROM FolgasRegras WHERE Chave = 'regras'")
        cur.execute("INSERT INTO FolgasRegras (Chave, Valor) VALUES ('regras', ?)", texto)
        conn.commit()
    finally:
        conn.close()
    invalidar()


def limite_horas(d, regras_atuais=None):
    """Horas por semana que valem na data d (o último limite com 'desde' <= d)."""
    regras_atuais = regras_atuais or regras()
    limite = None
    for item in sorted(regras_atuais.get('limites_horas') or [], key=lambda x: str(x.get('desde', ''))):
        desde = como_data(item.get('desde'))
        if desde and desde <= d:
            limite = item.get('horas')
    try:
        return float(limite) if limite else None
    except (TypeError, ValueError):
        return None

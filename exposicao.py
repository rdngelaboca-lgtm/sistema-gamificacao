# ==============================================================================
# == exposicao.py - 🧊 Checklist da FRENTE (o que está à venda nos freezers) ====
# ==============================================================================
# Problema: produto novo chega, vai para a câmara fria e fica lá (ninguém repõe na frente).
#
# Como funciona:
#   - O gestor cadastra os EXPOSITORES (freezers horizontais, vertical...) com quantas caixas cabem e quais
#     produtos ficam em cada um (Gestão Web › 🧊 Frente).
#   - Uma vez por semana o repositor faz o CHECKLIST no app do celular (PIN): freezer por freezer, marca quantas
#     caixas de cada produto estão na frente (0, 1, 2, 3+).
#   - Ao terminar, o sistema devolve a LISTA DO QUE FAZER, freezer por freezer:
#       🧊 buscar na câmara o que ficou com 0 (primeiro os ⭐ campeões e o que acabou de chegar);
#       🔁 sem espaço: tirar 1 caixa de um produto repetido (ex.: Groselha com 2) para pôr o que faltou;
#          se não houver repetido e quem faltou é campeão, sai uma caixa do que menos vende;
#       ➕ sobrou espaço: mais 1 caixa dos campeões;
#       ⚠️ chegou produto que não está em nenhum freezer: avisar o gestor.
#     O repositor marca cada ação: ✅ feito / 🚫 não tem na câmara (vira aviso de compra para o gestor).
#   - ⭐ CAMPEÕES (nunca podem faltar): os que mais vendem em cada freezer — pelo volume COMPRADO nas notas dos
#     últimos 90 dias (a loja compra o que vende; é o mesmo critério do 🍦 Top Sabores) — mais os marcados à mão.
#   - 🆕 CHEGOU: produtos das notas fiscais desde o último checklist (🆕 novo = 1ª compra nos últimos 30 dias).
# ==============================================================================
import logging
import math
import re
from datetime import date, datetime, timedelta

import database

logger = logging.getLogger(__name__)

TIPOS = {'horizontal': 'Freezer horizontal', 'vertical': 'Freezer vertical', 'outro': 'Outro'}
CONFIG_PADRAO = {'dias': 7, 'pct_campeoes': 30, 'dias_venda': 90}
DIAS_NOVO = 30
DIAS_CHEGADA_SEM_CHECKLIST = 14
DIAS_PROTEGIDO = 14                     # chegou há menos disto: não é o escolhido para sair da frente
MAX_CAIXAS = 3                          # o botão "3+" grava 3

_tabelas_ok = False


class ErroFrente(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ------------------------------------------------------------------------------
# Ajudantes
# ------------------------------------------------------------------------------
def _data(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _quando(v):
    if not v:
        return None
    if not hasattr(v, 'strftime'):
        try:
            v = datetime.fromisoformat(str(v)[:19])
        except ValueError:
            return None
    return v


def _int(v, padrao=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return padrao


def _id(v, nome="o item"):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ErroFrente(f"Identificação inválida para {nome}. Atualize a página.")


def _conexao():
    garantir_tabelas()
    conn = database.get_db_connection()
    if not conn:
        raise ErroFrente("Sem conexão com o banco de dados. Tente de novo em alguns segundos.", 503)
    return conn


def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = database.get_db_connection()
    if not conn:
        raise ErroFrente("Sem conexão com o banco de dados.", 503)
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ExpositoresLoja')
            CREATE TABLE ExpositoresLoja (
                ExpositorID INT IDENTITY(1,1) PRIMARY KEY,
                Nome NVARCHAR(60) NOT NULL,
                Tipo VARCHAR(12) NOT NULL DEFAULT 'horizontal',
                Capacidade INT NULL,
                Ordem INT NOT NULL DEFAULT 0,
                Ativo BIT NOT NULL DEFAULT 1,
                CriadoEm DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ExpositorProdutos')
            CREATE TABLE ExpositorProdutos (
                ExpositorID INT NOT NULL,
                ProdutoID INT NOT NULL,
                Ordem INT NOT NULL DEFAULT 0,
                SempreNaFrente BIT NOT NULL DEFAULT 0,
                PRIMARY KEY (ExpositorID, ProdutoID)
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FrenteChecklists')
            CREATE TABLE FrenteChecklists (
                ChecklistID INT IDENTITY(1,1) PRIMARY KEY,
                Codigo VARCHAR(40) NOT NULL UNIQUE,
                FuncionarioID INT NULL,
                NomeFuncionario NVARCHAR(150) NULL,
                Inicio DATETIME NULL,
                Fim DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FrenteChecklistItens')
            CREATE TABLE FrenteChecklistItens (
                ChecklistID INT NOT NULL,
                ExpositorID INT NOT NULL,
                ProdutoID INT NOT NULL,
                Caixas INT NOT NULL,
                Marcado BIT NOT NULL DEFAULT 1,
                PRIMARY KEY (ChecklistID, ExpositorID, ProdutoID)
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FrenteAcoes')
            CREATE TABLE FrenteAcoes (
                AcaoID INT IDENTITY(1,1) PRIMARY KEY,
                ChecklistID INT NOT NULL,
                Ordem INT NOT NULL,
                Tipo VARCHAR(12) NOT NULL,
                ExpositorID INT NULL,
                ProdutoID INT NULL,
                ProdutoTiraID INT NULL,
                Texto NVARCHAR(1000) NOT NULL,
                Situacao VARCHAR(12) NOT NULL DEFAULT 'pendente',
                FeitaEm DATETIME NULL,
                FeitaPor NVARCHAR(150) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FrenteConfig')
            CREATE TABLE FrenteConfig (
                Chave VARCHAR(30) NOT NULL PRIMARY KEY,
                Valor INT NOT NULL
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def config():
    cfg = dict(CONFIG_PADRAO)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Chave, Valor FROM FrenteConfig")
        for k, v in cur.fetchall():
            if k in cfg:
                cfg[k] = int(v)
    finally:
        conn.close()
    return cfg


# ------------------------------------------------------------------------------
# Leitura: expositores, produtos, vendas, chegadas
# ------------------------------------------------------------------------------
def _produtos():
    """{ProdutoID: {'nome', 'categoria', 'unidade', 'ativo'}} do cadastro do estoque."""
    saida = {}
    for p in database.listar_produtos_estoque(levantar_erro=True):
        ativo = getattr(p, 'Ativo', 1)
        saida[int(p.ProdutoID)] = {'nome': p.NomeProduto or '', 'categoria': getattr(p, 'Categoria', '') or '',
                                   'unidade': getattr(p, 'UnidadeMedida', '') or '', 'ativo': ativo is None or bool(ativo)}
    return saida


def _expositores(cur, so_ativos=True):
    cur.execute("SELECT ExpositorID, Nome, Tipo, Capacidade, Ordem, Ativo FROM ExpositoresLoja"
                + (" WHERE Ativo = 1" if so_ativos else "") + " ORDER BY Ordem, Nome")
    exps = [{'id': int(r[0]), 'nome': r[1] or '', 'tipo': r[2] or 'horizontal', 'capacidade': r[3], 'ordem': _int(r[4]),
             'ativo': bool(r[5]), 'produtos': []} for r in cur.fetchall()]
    por_id = {e['id']: e for e in exps}
    cur.execute("SELECT ExpositorID, ProdutoID, Ordem, SempreNaFrente FROM ExpositorProdutos ORDER BY ExpositorID, Ordem, ProdutoID")
    for eid, pid, ordem, sempre in cur.fetchall():
        if int(eid) in por_id:
            por_id[int(eid)]['produtos'].append({'id': int(pid), 'ordem': _int(ordem), 'sempre': bool(sempre)})
    return exps


def vendas(dias=90, hoje=None):
    """{ProdutoID: quantidade comprada nos últimos `dias`} (o que a loja compra = o que vende)."""
    hoje = hoje or date.today()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT PF.ProdutoID, SUM(I.Quantidade)
                       FROM ItensNotaFiscalEntrada I
                       JOIN ProdutosFornecedor PF ON PF.ProdutoFornecedorID = I.ProdutoFornecedorID
                       JOIN NotasFiscaisEntrada NF ON NF.NotaID = I.NotaID
                       WHERE NF.DataEmissao >= ? AND PF.ProdutoID IS NOT NULL
                       GROUP BY PF.ProdutoID""", (hoje - timedelta(days=dias)).isoformat())
        return {int(pid): float(q or 0) for pid, q in cur.fetchall()}
    finally:
        conn.close()


def chegadas(desde, hoje=None):
    """{ProdutoID: {'ultima': date, 'novo': bool}} dos produtos que vieram em nota desde a data."""
    hoje = hoje or date.today()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT PF.ProdutoID, MAX(NF.DataEmissao)
                       FROM ItensNotaFiscalEntrada I
                       JOIN ProdutosFornecedor PF ON PF.ProdutoFornecedorID = I.ProdutoFornecedorID
                       JOIN NotasFiscaisEntrada NF ON NF.NotaID = I.NotaID
                       WHERE NF.DataEmissao >= ? AND PF.ProdutoID IS NOT NULL
                       GROUP BY PF.ProdutoID""", desde.isoformat())
        saida = {int(pid): {'ultima': _data(d), 'novo': False} for pid, d in cur.fetchall()}
        if saida:
            ids = list(saida)
            for k in range(0, len(ids), 500):
                parte = ids[k:k + 500]
                cur.execute(f"""SELECT PF.ProdutoID, MIN(NF.DataEmissao)
                                FROM ItensNotaFiscalEntrada I
                                JOIN ProdutosFornecedor PF ON PF.ProdutoFornecedorID = I.ProdutoFornecedorID
                                JOIN NotasFiscaisEntrada NF ON NF.NotaID = I.NotaID
                                WHERE PF.ProdutoID IN ({','.join('?' * len(parte))})
                                GROUP BY PF.ProdutoID""", *parte)
                for pid, primeira in cur.fetchall():
                    p = _data(primeira)
                    if p and int(pid) in saida:
                        saida[int(pid)]['novo'] = p >= hoje - timedelta(days=DIAS_NOVO)
        return saida
    finally:
        conn.close()


def _ultimo_checklist(cur):
    cur.execute("SELECT TOP 1 ChecklistID, Fim, NomeFuncionario FROM FrenteChecklists ORDER BY Fim DESC, ChecklistID DESC")
    r = cur.fetchone()
    return {'id': int(r[0]), 'fim': _quando(r[1]), 'nome': r[2] or ''} if r else None


def _desde(ult, hoje):
    """O que chegou desde o último checklist (sem checklist: as últimas 2 semanas)."""
    return ult['fim'].date() if ult and ult['fim'] else hoje - timedelta(days=DIAS_CHEGADA_SEM_CHECKLIST)


def campeoes(expositores, venda, pct):
    """{(ExpositorID, ProdutoID)} dos ⭐: os que mais vendem em cada freezer (pct%) + os marcados à mão."""
    saida = set()
    for e in expositores:
        com_venda = sorted((p for p in e['produtos'] if venda.get(p['id'], 0) > 0), key=lambda p: -venda.get(p['id'], 0))
        n = max(1, math.ceil(len(e['produtos']) * pct / 100)) if com_venda else 0
        for p in com_venda[:n]:
            saida.add((e['id'], p['id']))
        for p in e['produtos']:
            if p['sempre']:
                saida.add((e['id'], p['id']))
    return saida


# ------------------------------------------------------------------------------
# App (repositor): o que precisa para fazer o checklist
# ------------------------------------------------------------------------------
def situacao(hoje=None):
    """Para o Início/Estoque do app: último checklist, se está atrasado e o que chegou desde então."""
    hoje = hoje or date.today()
    cfg = config()
    conn = _conexao()
    try:
        cur = conn.cursor()
        ult = _ultimo_checklist(cur)
        cur.execute("SELECT COUNT(1) FROM ExpositoresLoja WHERE Ativo = 1")
        n_exp = int(cur.fetchone()[0] or 0)
        pend = 0
        if ult:
            cur.execute("SELECT COUNT(1) FROM FrenteAcoes WHERE ChecklistID = ? AND Situacao = 'pendente' AND Tipo IN ('buscar', 'trocar')",
                        ult['id'])
            pend = int(cur.fetchone()[0] or 0)
    finally:
        conn.close()
    dias = (hoje - ult['fim'].date()).days if ult and ult['fim'] else None
    return {'configurado': n_exp > 0, 'expositores': n_exp, 'dias_entre': cfg['dias'],
            'ultimo': {'data': ult['fim'].strftime('%d/%m'), 'nome': ult['nome'], 'dias': dias, 'pendentes': pend,
                       'id': ult['id']} if ult else None,
            'atrasado': n_exp > 0 and (dias is None or dias >= cfg['dias'])}


def para_checklist(hoje=None):
    """Os freezers (na ordem), os produtos de cada um (na ordem), ⭐ campeões e 🆕 o que chegou."""
    hoje = hoje or date.today()
    cfg = config()
    prods = _produtos()
    conn = _conexao()
    try:
        cur = conn.cursor()
        exps = _expositores(cur)
        ult = _ultimo_checklist(cur)
    finally:
        conn.close()
    if not exps:
        raise ErroFrente("Nenhum freezer cadastrado ainda. O gestor cadastra em Gestão › 🧊 Frente (no computador).")
    venda = vendas(cfg['dias_venda'], hoje)
    estrelas = campeoes(exps, venda, cfg['pct_campeoes'])
    desde = _desde(ult, hoje)
    cheg = chegadas(desde, hoje)
    saida = []
    for e in exps:
        itens = []
        for p in e['produtos']:
            info = prods.get(p['id'])
            if not info or not info['ativo']:
                continue
            c = cheg.get(p['id'])
            itens.append({'id': p['id'], 'nome': info['nome'], 'categoria': info['categoria'],
                          'campeao': (e['id'], p['id']) in estrelas,
                          'chegou': c['ultima'].strftime('%d/%m') if c and c['ultima'] else '', 'novo': bool(c and c['novo'])})
        saida.append({'id': e['id'], 'nome': e['nome'], 'tipo': e['tipo'], 'capacidade': e['capacidade'], 'itens': itens})
    em_algum = {p['id'] for e in exps for p in e['produtos']}
    sem_lugar = sorted(({'id': pid, 'nome': prods[pid]['nome'], 'chegou': c['ultima'].strftime('%d/%m') if c['ultima'] else ''}
                        for pid, c in cheg.items() if pid not in em_algum and pid in prods and prods[pid]['ativo']),
                       key=lambda x: x['nome'].lower())
    return {'expositores': saida, 'sem_lugar': sem_lugar, 'desde': desde.strftime('%d/%m'),
            'ultimo': {'data': ult['fim'].strftime('%d/%m/%Y'), 'nome': ult['nome']} if ult and ult['fim'] else None}


# ------------------------------------------------------------------------------
# A lista do que fazer (a regra da troca)
# ------------------------------------------------------------------------------
def montar_acoes(expositores, marcas, estrelas, venda, cheg, sem_lugar_nomes=(), recentes=None):
    """
    expositores: [{'id', 'nome', 'capacidade', 'itens': [{'id', 'nome'}]}]; marcas: {(ExpositorID, ProdutoID): caixas}.
    Devolve [{'tipo', 'expositor_id', 'produto_id', 'tira_id', 'texto'}] na ordem de fazer.
    """
    recentes = set(cheg) if recentes is None else set(recentes) | set(cheg)
    acoes = []
    nome = {}
    for e in expositores:
        for it in e['itens']:
            nome[it['id']] = it['nome']
    for e in expositores:
        caixas = {it['id']: max(0, min(_int(marcas.get((e['id'], it['id']), 0)), MAX_CAIXAS)) for it in e['itens']}
        estrela = lambda pid: (e['id'], pid) in estrelas
        vende = lambda pid: venda.get(pid, 0)
        cap = _int(e.get('capacidade'), 0) or None
        livre = (cap - sum(caixas.values())) if cap else None
        faltam = [pid for pid, n in caixas.items() if n == 0]
        faltam.sort(key=lambda pid: (not estrela(pid), not cheg.get(pid), -vende(pid), nome[pid].lower()))
        for pid in faltam:
            motivo = " ⭐ campeão" if estrela(pid) else (f" (chegou {cheg[pid]['ultima']:%d/%m})" if cheg.get(pid) and cheg[pid]['ultima'] else "")
            if livre is None or livre > 0:
                acoes.append({'tipo': 'buscar', 'expositor_id': e['id'], 'produto_id': pid, 'tira_id': None,
                              'texto': f"🧊 Buscar 1 caixa de {nome[pid]}{motivo} na câmara e pôr no {e['nome']}."})
                if livre is not None:
                    livre -= 1
                caixas[pid] = 1
                continue
            # sem espaço: 1º um REPETIDO (o com mais caixas; empate: o que menos vende, campeão por último)
            repetidos = [x for x, n in caixas.items() if n >= 2]
            if repetidos:
                tira = max(repetidos, key=lambda x: (caixas[x], not estrela(x), -vende(x)))
                acoes.append({'tipo': 'trocar', 'expositor_id': e['id'], 'produto_id': pid, 'tira_id': tira,
                              'texto': f"🔁 {e['nome']} cheio: tire 1 caixa de {nome[tira]} (tem {caixas[tira]}) e ponha 1 de "
                                       f"{nome[pid]}{motivo} (buscar na câmara)."})
                caixas[tira] -= 1
                caixas[pid] = 1
                continue
            if estrela(pid):        # campeão não pode faltar: sai o que menos vende (que não é campeão)
                candidatos = [x for x, n in caixas.items() if n == 1 and not estrela(x)]
                if candidatos:
                    # o que acabou de CHEGAR só sai se não houver outro (era justamente o que ficava esquecido na câmara)
                    tira = min(candidatos, key=lambda x: (x in recentes, vende(x), nome[x].lower()))
                    acoes.append({'tipo': 'trocar', 'expositor_id': e['id'], 'produto_id': pid, 'tira_id': tira,
                                  'texto': f"🔁 {e['nome']} cheio: tire {nome[tira]} (vende pouco; volta para a câmara) e ponha "
                                           f"{nome[pid]} ⭐ campeão (buscar na câmara)."})
                    caixas[tira] = 0
                    caixas[pid] = 1
                    continue
            acoes.append({'tipo': 'sem_espaco', 'expositor_id': e['id'], 'produto_id': pid, 'tira_id': None,
                          'texto': f"ℹ️ {e['nome']} sem espaço: {nome[pid]} fica na câmara por enquanto."})
        if livre:                    # sobrou espaço: mais 1 caixa dos campeões que têm só 1
            for pid in sorted((x for x, n in caixas.items() if n == 1 and estrela(x)), key=lambda x: -vende(x)):
                if livre <= 0:
                    break
                acoes.append({'tipo': 'buscar', 'expositor_id': e['id'], 'produto_id': pid, 'tira_id': None,
                              'texto': f"➕ Sobrou espaço no {e['nome']}: mais 1 caixa de {nome[pid]} ⭐ campeão."})
                caixas[pid] += 1
                livre -= 1
    for n in sem_lugar_nomes:
        acoes.append({'tipo': 'sem_lugar', 'expositor_id': None, 'produto_id': None, 'tira_id': None,
                      'texto': f"⚠️ Chegou {n} e não está em nenhum freezer: avise o gestor (ele põe em um freezer no cadastro)."})
    return acoes


def _codigo(texto):
    t = str(texto or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,40}', t):
        raise ErroFrente("Checklist sem código. Atualize o app.")
    return t


def concluir(dados, usuario, hoje=None):
    """O repositor terminou: grava as marcas e devolve a lista do que fazer (o mesmo código 2x = a mesma resposta)."""
    hoje = hoje or date.today()
    codigo = _codigo(dados.get('codigo'))
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ChecklistID FROM FrenteChecklists WHERE Codigo = ?", codigo)
        r = cur.fetchone()
    finally:
        conn.close()
    if r:                                   # reenvio (o app estava sem internet e mandou de novo)
        return resultado(int(r[0]))
    marcas_brutas = dados.get('marcas')
    if not isinstance(marcas_brutas, list) or len(marcas_brutas) > 3000:
        raise ErroFrente("Marcações inválidas. Atualize o app.")
    info = para_checklist(hoje)
    validos = {(e['id'], it['id']) for e in info['expositores'] for it in e['itens']}
    marcas, marcados = {}, set()
    for m in marcas_brutas:
        chave = (_id((m or {}).get('expositor_id'), "o freezer"), _id((m or {}).get('produto_id'), "o produto"))
        if chave in validos and (m or {}).get('caixas') is not None:
            marcas[chave] = max(0, min(_int(m.get('caixas')), MAX_CAIXAS))
            marcados.add(chave)
    if not marcados:
        raise ErroFrente("Nenhum produto marcado.")
    cfg = config()
    conn = _conexao()
    try:
        cur = conn.cursor()
        exps_db = _expositores(cur)
        ult = _ultimo_checklist(cur)
    finally:
        conn.close()
    venda = vendas(cfg['dias_venda'], hoje)
    estrelas = campeoes(exps_db, venda, cfg['pct_campeoes'])
    cheg = chegadas(_desde(ult, hoje), hoje)
    recentes = chegadas(hoje - timedelta(days=DIAS_PROTEGIDO), hoje)
    acoes = montar_acoes(info['expositores'], marcas, estrelas, venda, cheg, [x['nome'] for x in info['sem_lugar']], recentes)
    inicio = _quando(dados.get('inicio'))
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO FrenteChecklists (Codigo, FuncionarioID, NomeFuncionario, Inicio, Fim) VALUES (?, ?, ?, ?, GETDATE()); "
                    "SELECT SCOPE_IDENTITY();", codigo, (usuario or {}).get('id'), ((usuario or {}).get('nome') or '')[:150],
                    inicio.replace(microsecond=0) if inicio else None)
        cur.nextset()                         # SQL Server: o 1º resultado é o do INSERT; o ID vem no seguinte
        cid = int(cur.fetchone()[0])
        for (eid, pid) in validos:
            cur.execute("INSERT INTO FrenteChecklistItens (ChecklistID, ExpositorID, ProdutoID, Caixas, Marcado) VALUES (?, ?, ?, ?, ?)",
                        cid, eid, pid, marcas.get((eid, pid), 0), 1 if (eid, pid) in marcados else 0)
        for k, a in enumerate(acoes):
            cur.execute("INSERT INTO FrenteAcoes (ChecklistID, Ordem, Tipo, ExpositorID, ProdutoID, ProdutoTiraID, Texto, Situacao) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", cid, k, a['tipo'], a['expositor_id'], a['produto_id'], a['tira_id'],
                        a['texto'][:480], 'pendente' if a['tipo'] in ('buscar', 'trocar') else 'info')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"[FRENTE] {(usuario or {}).get('nome')}: checklist {cid} — {len(marcados)} marcado(s) de {len(validos)}, "
                f"{sum(1 for a in acoes if a['tipo'] in ('buscar', 'trocar'))} ação(ões).")
    return resultado(cid)


def resultado(checklist_id):
    """O checklist e a lista do que fazer (com a situação de cada ação)."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ChecklistID, Fim, NomeFuncionario, Inicio FROM FrenteChecklists WHERE ChecklistID = ?", int(checklist_id))
        c = cur.fetchone()
        if not c:
            raise ErroFrente("Checklist não encontrado.", 404)
        cur.execute("SELECT ExpositorID, Nome FROM ExpositoresLoja")
        nomes_exp = {int(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT AcaoID, Ordem, Tipo, ExpositorID, Texto, Situacao, FeitaEm, FeitaPor FROM FrenteAcoes "
                    "WHERE ChecklistID = ? ORDER BY Ordem", int(checklist_id))
        acoes = [{'id': int(r[0]), 'tipo': r[2], 'expositor': nomes_exp.get(r[3], '') if r[3] else '', 'texto': r[4],
                  'situacao': r[5], 'feita_em': _quando(r[6]).strftime('%d/%m %H:%M') if _quando(r[6]) else '', 'feita_por': r[7] or ''}
                 for r in cur.fetchall()]
        cur.execute("SELECT COUNT(1), SUM(CASE WHEN Marcado = 1 THEN 1 ELSE 0 END), SUM(CASE WHEN Caixas = 0 THEN 1 ELSE 0 END) "
                    "FROM FrenteChecklistItens WHERE ChecklistID = ?", int(checklist_id))
        tot, marc, zeros = cur.fetchone()
    finally:
        conn.close()
    fim, ini = _quando(c[1]), _quando(c[3])
    fazer = [a for a in acoes if a['tipo'] in ('buscar', 'trocar')]
    return {'id': int(c[0]), 'data': fim.strftime('%d/%m/%Y %H:%M') if fim else '', 'nome': c[2] or '',
            'minutos': int((fim - ini).total_seconds() // 60) if fim and ini and fim >= ini else None,
            'produtos': int(tot or 0), 'marcados': int(marc or 0), 'faltando': int(zeros or 0),
            'acoes': acoes, 'pendentes': sum(1 for a in fazer if a['situacao'] == 'pendente'),
            'feitas': sum(1 for a in fazer if a['situacao'] == 'feita'),
            'sem_estoque': sum(1 for a in fazer if a['situacao'] == 'sem_estoque')}


def marcar_acao(acao_id, dados, usuario):
    """✅ feito / 🚫 não tem na câmara / ↩️ desfazer, numa ação da lista."""
    sit = dados.get('situacao')
    if sit not in ('feita', 'sem_estoque', 'pendente'):
        raise ErroFrente("Escolha: feito, não tem na câmara ou desfazer.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ChecklistID, Tipo FROM FrenteAcoes WHERE AcaoID = ?", int(acao_id))
        r = cur.fetchone()
        if not r:
            raise ErroFrente("Ação não encontrada. Atualize.", 404)
        if r[1] not in ('buscar', 'trocar'):
            raise ErroFrente("Esta linha é só um aviso.")
        cur.execute("UPDATE FrenteAcoes SET Situacao = ?, FeitaEm = " + ("NULL" if sit == 'pendente' else "GETDATE()")
                    + ", FeitaPor = ? WHERE AcaoID = ?", sit, None if sit == 'pendente' else ((usuario or {}).get('nome') or '')[:150], int(acao_id))
        conn.commit()
        cid = int(r[0])
    finally:
        conn.close()
    return {'ok': True, 'checklist': resultado(cid)}


# ------------------------------------------------------------------------------
# Gestão (gestor): cadastro dos freezers e histórico
# ------------------------------------------------------------------------------
def painel(hoje=None):
    hoje = hoje or date.today()
    cfg = config()
    prods = _produtos()
    conn = _conexao()
    try:
        cur = conn.cursor()
        exps = _expositores(cur, so_ativos=False)
        cur.execute("SELECT TOP 12 ChecklistID, Fim FROM FrenteChecklists ORDER BY Fim DESC, ChecklistID DESC")
        chks = [(int(r[0]), _quando(r[1])) for r in cur.fetchall()]
    finally:
        conn.close()
    venda = vendas(cfg['dias_venda'], hoje)
    estrelas = campeoes([e for e in exps if e['ativo']], venda, cfg['pct_campeoes'])
    for e in exps:
        e['tipo_txt'] = TIPOS.get(e['tipo'], e['tipo'])
        e['produtos'] = [dict(p, nome=prods[p['id']]['nome'], categoria=prods[p['id']]['categoria'], ativo=prods[p['id']]['ativo'],
                              campeao=(e['id'], p['id']) in estrelas, venda=round(venda.get(p['id'], 0)))
                         for p in e['produtos'] if p['id'] in prods]
    em_algum = {p['id'] for e in exps for p in e['produtos']}
    categorias = sorted({p['categoria'] for p in prods.values() if p['ativo'] and p['categoria']})
    produtos = sorted(({'id': pid, 'nome': p['nome'], 'categoria': p['categoria'], 'em_freezer': pid in em_algum}
                       for pid, p in prods.items() if p['ativo']), key=lambda x: x['nome'].lower())
    sit = situacao(hoje)
    historico = [resultado(i) for i, _ in chks]
    # 🚫 o repositor não achou na câmara: o gestor vê os dos últimos 14 dias (com a data), para comprar
    sem_estoque = [f"{c['data'][:5]} · {a['texto']}" for c, (_, fim) in zip(historico, chks)
                   if fim and (hoje - fim.date()).days <= DIAS_PROTEGIDO for a in c['acoes'] if a['situacao'] == 'sem_estoque']
    return {'expositores': exps, 'produtos': produtos, 'categorias': categorias, 'config': cfg, 'tipos': TIPOS,
            'situacao': sit, 'historico': historico, 'sem_estoque': sem_estoque}


def _ler_expositor(dados):
    nome = ' '.join(str(dados.get('nome') or '').split())[:60]
    if not nome:
        raise ErroFrente("Dê um nome ao freezer (ex.: Freezer picolés 1).")
    tipo = dados.get('tipo') if dados.get('tipo') in TIPOS else 'horizontal'
    cap = dados.get('capacidade')
    cap = None if cap in (None, '') else _int(cap, -1)
    if cap is not None and not 1 <= cap <= 200:
        raise ErroFrente("Capacidade: de 1 a 200 caixas (ou deixe em branco se não souber).")
    return nome, tipo, cap


def salvar_expositor(expositor_id, dados, usuario):
    nome, tipo, cap = _ler_expositor(dados)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ExpositorID FROM ExpositoresLoja WHERE Nome = ? AND Ativo = 1" + (" AND ExpositorID <> ?" if expositor_id else ""),
                    *([nome, expositor_id] if expositor_id else [nome]))
        if cur.fetchone():
            raise ErroFrente(f"Já existe um freezer chamado {nome}.")
        if expositor_id:
            cur.execute("UPDATE ExpositoresLoja SET Nome = ?, Tipo = ?, Capacidade = ? WHERE ExpositorID = ?", nome, tipo, cap, expositor_id)
            if cur.rowcount == 0:
                raise ErroFrente("Freezer não encontrado. Atualize a página.", 409)
        else:
            cur.execute("SELECT ISNULL(MAX(Ordem), 0) FROM ExpositoresLoja")
            ordem = int(cur.fetchone()[0] or 0) + 1
            cur.execute("INSERT INTO ExpositoresLoja (Nome, Tipo, Capacidade, Ordem, Ativo) VALUES (?, ?, ?, ?, 1)", nome, tipo, cap, ordem)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[FRENTE] {(usuario or {}).get('nome')}: freezer {nome} {'atualizado' if expositor_id else 'cadastrado'}.")
    return {'ok': True, 'mensagem': f"🧊 {nome}: {'salvo' if expositor_id else 'cadastrado'}."}


def excluir_expositor(expositor_id, usuario):
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Nome FROM ExpositoresLoja WHERE ExpositorID = ?", expositor_id)
        r = cur.fetchone()
        if not r:
            raise ErroFrente("Freezer não encontrado. Atualize a página.", 409)
        cur.execute("UPDATE ExpositoresLoja SET Ativo = 0 WHERE ExpositorID = ?", expositor_id)   # o histórico continua
        cur.execute("DELETE FROM ExpositorProdutos WHERE ExpositorID = ?", expositor_id)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[FRENTE] {(usuario or {}).get('nome')}: tirou o freezer {r[0]}.")
    return {'ok': True, 'mensagem': f"Freezer {r[0]} removido (os checklists antigos continuam no histórico)."}


def ordenar_expositores(dados, usuario):
    ids = dados.get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > 100:
        raise ErroFrente("Ordem inválida. Atualize a página.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        for k, eid in enumerate(ids, start=1):
            cur.execute("UPDATE ExpositoresLoja SET Ordem = ? WHERE ExpositorID = ?", k, _id(eid, "o freezer"))
        conn.commit()
    finally:
        conn.close()
    return {'ok': True, 'mensagem': "Ordem dos freezers salva (é a ordem do checklist no celular)."}


def salvar_produtos(expositor_id, dados, usuario):
    """Os produtos do freezer, NA ORDEM em que estão lá dentro: [{'id', 'sempre'}]."""
    lista = dados.get('produtos')
    if not isinstance(lista, list) or len(lista) > 300:
        raise ErroFrente("Lista de produtos inválida. Atualize a página.")
    prods = _produtos()
    vistos, linhas = set(), []
    for p in lista:
        pid = _id((p or {}).get('id'), "o produto")
        if pid in vistos:
            continue
        if pid not in prods:
            raise ErroFrente("Produto não encontrado no cadastro do estoque. Atualize a página.", 409)
        vistos.add(pid)
        linhas.append((pid, bool((p or {}).get('sempre'))))
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Nome FROM ExpositoresLoja WHERE ExpositorID = ? AND Ativo = 1", expositor_id)
        r = cur.fetchone()
        if not r:
            raise ErroFrente("Freezer não encontrado. Atualize a página.", 409)
        cur.execute("DELETE FROM ExpositorProdutos WHERE ExpositorID = ?", expositor_id)
        for k, (pid, sempre) in enumerate(linhas, start=1):
            cur.execute("INSERT INTO ExpositorProdutos (ExpositorID, ProdutoID, Ordem, SempreNaFrente) VALUES (?, ?, ?, ?)",
                        expositor_id, pid, k, 1 if sempre else 0)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"[FRENTE] {(usuario or {}).get('nome')}: {len(linhas)} produto(s) no freezer {r[0]}.")
    return {'ok': True, 'mensagem': f"🧊 {r[0]}: {len(linhas)} produto(s) salvos."}


def salvar_config(dados, usuario):
    novos = {}
    for k, (mi, ma) in {'dias': (1, 60), 'pct_campeoes': (0, 100), 'dias_venda': (14, 365)}.items():
        v = _int(dados.get(k), -1)
        if not mi <= v <= ma:
            raise ErroFrente({'dias': "De quantos em quantos dias: de 1 a 60.", 'pct_campeoes': "Campeões: de 0% a 100%.",
                              'dias_venda': "Dias de venda: de 14 a 365."}[k])
        novos[k] = v
    conn = _conexao()
    try:
        cur = conn.cursor()
        for k, v in novos.items():
            cur.execute("DELETE FROM FrenteConfig WHERE Chave = ?", k)
            cur.execute("INSERT INTO FrenteConfig (Chave, Valor) VALUES (?, ?)", k, v)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[FRENTE] {(usuario or {}).get('nome')}: configuração {novos}.")
    return {'ok': True, 'mensagem': "Configuração salva."}

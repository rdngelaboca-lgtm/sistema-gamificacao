# ==============================================================================
# == recebimento.py  -  Conferência da mercadoria que chega (app de compras) ===
# ==============================================================================
# O robô baixa o XML da nota assim que o fornecedor emite (nfe_distribuicao.py).
# A nota aparece no app (aba "Receber") como "aguardando conferência". Quando a
# entrega chega, a pessoa abre a nota e bipa os produtos: cada bip soma no item da
# nota. Código que o sistema não conhece: a pessoa diz de qual item da nota ele é
# (fica guardado para as próximas notas do mesmo fornecedor).
# No fim, o que faltou / veio a mais vai para o gestor no Telegram.
#
# Os XMLs ficam na pasta do nfe_distribuicao (e na subpasta 'importadas', depois que
# a nota entra no estoque pelo Gestão de Estoque): a conferência não depende disso.
# ==============================================================================
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import config
import database
from compras_database import ErroCompras, _conectar, _iso, _num, _dec, _como_data, _como_datahora, normalizar_codigo

logger = logging.getLogger(__name__)

ST_AGUARDANDO = 'aguardando'
ST_CONFERIDA = 'conferida'
ST_DIVERGENCIA = 'divergencia'
ST_DISPENSADA = 'dispensada'
DIAS_PENDENTE = int(getattr(config, 'RECEBIMENTO_DIAS', 20) or 20)   # notas emitidas há mais tempo não aparecem
DIAS_CONFERIDAS = 7

_tabelas_ok = False
_cache_xml = {}        # caminho -> (mtime, dados): não relê os mesmos XMLs a cada abertura da lista


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'RecebimentoNotas')
            CREATE TABLE RecebimentoNotas (
                Chave VARCHAR(44) PRIMARY KEY,
                NumeroNF VARCHAR(20) NULL,
                CNPJ VARCHAR(14) NULL,
                Fornecedor NVARCHAR(150) NULL,
                DataEmissao DATE NULL,
                Valor DECIMAL(18, 2) NULL,
                Status VARCHAR(20) NOT NULL,
                ConferidoPorID INT NULL,
                ConferidoPor NVARCHAR(150) NULL,
                ConferidoEm DATETIME NULL,
                Observacao NVARCHAR(500) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'RecebimentoItens')
            CREATE TABLE RecebimentoItens (
                Chave VARCHAR(44) NOT NULL,
                NItem INT NOT NULL,
                Descricao NVARCHAR(255) NULL,
                CodigoFornecedor NVARCHAR(60) NULL,
                EAN VARCHAR(14) NULL,
                NCM VARCHAR(10) NULL,
                Unidade VARCHAR(10) NULL,
                QtdNota DECIMAL(18, 4) NULL,
                QtdConferida DECIMAL(18, 4) NULL,
                PRIMARY KEY (Chave, NItem)
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'RecebimentoCodigos')
            CREATE TABLE RecebimentoCodigos (
                CNPJ VARCHAR(14) NOT NULL,
                CodigoFornecedor NVARCHAR(60) NOT NULL,
                Codigo VARCHAR(14) NOT NULL,
                PorBip DECIMAL(18, 6) NOT NULL,
                CriadoPor NVARCHAR(150) NULL,
                CriadoEm DATETIME NULL,
                PRIMARY KEY (CNPJ, CodigoFornecedor, Codigo)
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def _conexao():
    garantir_tabelas()
    return _conectar()


# ------------------------------------------------------------------------------
# XMLs baixados
# ------------------------------------------------------------------------------
def _pasta():
    import nfe_distribuicao
    return nfe_distribuicao.pasta_xml()


def _caminho_da_chave(chave):
    if not re.fullmatch(r'\d{44}', str(chave or '')):
        raise ErroCompras("Nota inválida.")
    for sub in ('', 'importadas'):
        caminho = os.path.join(_pasta(), sub, f"{chave}.xml")
        if os.path.exists(caminho):
            return caminho
    raise ErroCompras("O XML desta nota não está mais no servidor.")


def _dec_xml(texto):
    try:
        return Decimal(str(texto or '0').strip() or '0')
    except InvalidOperation:
        return Decimal('0')


def ler_nota(caminho):
    """Cabeçalho e itens do XML (procNFe). Fica em memória enquanto o arquivo não mudar."""
    mtime = os.path.getmtime(caminho)
    guardado = _cache_xml.get(caminho)
    if guardado and guardado[0] == mtime:
        return guardado[1]
    raiz = ET.parse(caminho).getroot()
    for el in raiz.iter():                       # tira o namespace (nfe:...)
        if isinstance(el.tag, str) and '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]
    inf = raiz.find('.//infNFe')
    ide, emit, total = raiz.find('.//ide'), raiz.find('.//emit'), raiz.find('.//total/ICMSTot')
    if inf is None or ide is None or emit is None:
        raise ErroCompras("XML de nota fiscal inválido.")
    chave = (inf.get('Id') or '')[3:]
    emissao = (ide.findtext('dhEmi') or ide.findtext('dEmi') or '')[:10]
    itens = []
    for det in raiz.findall('.//det'):
        prod = det.find('prod')
        if prod is None:
            continue
        q_com, q_trib = _dec_xml(prod.findtext('qCom')), _dec_xml(prod.findtext('qTrib'))
        itens.append({
            'n': int(det.get('nItem') or len(itens) + 1),
            'descricao': (prod.findtext('xProd') or '').strip(),
            'cprod': (prod.findtext('cProd') or '').strip(),
            'ean': normalizar_codigo(prod.findtext('cEAN')),
            'ean_trib': normalizar_codigo(prod.findtext('cEANTrib')),
            'ncm': (prod.findtext('NCM') or '').strip(),
            'unidade': (prod.findtext('uCom') or 'UN').strip().upper()[:10],
            'qtd': q_com,
            'unidade_trib': (prod.findtext('uTrib') or '').strip().upper()[:10],
            'qtd_trib': q_trib,
            'valor': _dec_xml(prod.findtext('vProd')),
        })
    dados = {'chave': chave, 'numero': (ide.findtext('nNF') or '').strip(), 'serie': (ide.findtext('serie') or '').strip(),
             'cnpj': re.sub(r'\D', '', emit.findtext('CNPJ') or emit.findtext('CPF') or ''),
             'fornecedor': (emit.findtext('xFant') or emit.findtext('xNome') or '').strip(),
             'emissao': emissao, 'valor': _dec_xml(total.findtext('vNF') if total is not None else 0),
             'finalidade': (ide.findtext('finNFe') or '1').strip(), 'itens': itens}
    _cache_xml[caminho] = (mtime, dados)
    return dados


def qtd_br(valor):
    """3.0 -> '3'   2.5 -> '2,5'   0.1667 -> '0,167'"""
    texto = f"{Decimal(str(valor or 0)):.3f}".rstrip('0').rstrip('.')
    return texto.replace('.', ',') or '0'


def _status_gravados():
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Chave, Status, ConferidoPor, ConferidoEm FROM RecebimentoNotas")
        return {r[0]: {'status': r[1], 'por': r[2], 'em': _como_datahora(r[3])} for r in cur.fetchall()}
    finally:
        conn.close()


def listar_recebimentos(hoje=None):
    """Notas para conferir (emitidas nos últimos DIAS_PENDENTE dias) e as conferidas há pouco."""
    hoje = _como_data(hoje) or date.today()
    gravados = _status_gravados()
    pendentes, feitas = [], []
    limite = hoje - timedelta(days=DIAS_PENDENTE)
    for sub in ('', 'importadas'):
        pasta = os.path.join(_pasta(), sub)
        if not os.path.isdir(pasta):
            continue
        for nome in os.listdir(pasta):
            if not re.fullmatch(r'\d{44}\.xml', nome):
                continue
            try:
                n = ler_nota(os.path.join(pasta, nome))
            except Exception as e:
                logger.warning(f"Recebimento: XML {nome} não abriu: {e}")
                continue
            if n['finalidade'] == '4':               # devolução: não é mercadoria chegando
                continue
            g = gravados.get(n['chave'])
            resumo = {'chave': n['chave'], 'numero': n['numero'], 'fornecedor': n['fornecedor'], 'emissao': n['emissao'],
                      'valor': _num(n['valor'], 2), 'qtd_itens': len(n['itens']),
                      'status': g['status'] if g else ST_AGUARDANDO,
                      'conferido_por': g['por'] if g else None, 'conferido_em': _iso(g['em']) if g else None}
            emissao = _como_data(n['emissao'])
            if resumo['status'] == ST_AGUARDANDO:
                if emissao and emissao >= limite:
                    pendentes.append(resumo)
            elif g and g['em'] and g['em'].date() >= hoje - timedelta(days=DIAS_CONFERIDAS):
                feitas.append(resumo)
    pendentes.sort(key=lambda r: r['emissao'] or '', reverse=True)
    feitas.sort(key=lambda r: r['conferido_em'] or '', reverse=True)
    return {'pendentes': pendentes, 'conferidas': feitas, 'dias': DIAS_PENDENTE}


# ------------------------------------------------------------------------------
# Uma nota: itens + todos os códigos que valem para cada item
# ------------------------------------------------------------------------------
def _codigos_por_produto():
    """{produto_id: [(codigo14, fator)]} de todos os códigos conhecidos (vínculos + cadastrados no app)."""
    import compras_database
    reverso = {}
    for cod, lista in compras_database.listar_codigos().items():
        for p in lista:
            reverso.setdefault(p['produto_id'], []).append((cod, Decimal(str(p['fator'] or 1))))
    return reverso


def obter_recebimento(chave):
    n = ler_nota(_caminho_da_chave(chave))
    forn_id = database.buscar_fornecedor_por_cnpj(n['cnpj'])
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT CodigoFornecedor, Codigo, PorBip FROM RecebimentoCodigos WHERE CNPJ = ?", (n['cnpj'],))
        salvos = {}
        for cprod, cod, por_bip in cur.fetchall():
            salvos.setdefault(cprod, []).append((cod, _dec(por_bip)))
        cur.execute("SELECT Status, ConferidoPor, ConferidoEm, Observacao FROM RecebimentoNotas WHERE Chave = ?", (n['chave'],))
        cab = cur.fetchone()
        cur.execute("SELECT NItem, QtdConferida FROM RecebimentoItens WHERE Chave = ?", (n['chave'],))
        conferidos = {r[0]: _dec(r[1]) for r in cur.fetchall()}
    finally:
        conn.close()
    por_produto = None
    itens = []
    for it in n['itens']:
        codigos = {}
        def soma(cod, por_bip, origem):
            if cod and por_bip > 0 and cod not in codigos:
                codigos[cod] = {'codigo': cod, 'por_bip': _num(por_bip, 6), 'origem': origem}
        soma(it['ean'], Decimal('1'), 'nota')
        if it['ean_trib'] and it['ean_trib'] != it['ean'] and it['qtd_trib'] > 0:
            soma(it['ean_trib'], it['qtd'] / it['qtd_trib'], 'nota (unidade)')     # código da unidade de dentro
        for cod, por_bip in salvos.get(it['cprod'], []):
            soma(cod, por_bip, 'cadastrado')
        produto = None
        if forn_id:
            try:
                v = database.buscar_vinculo_inteligente(forn_id, it['descricao'], it['cprod'], it['ean'])
            except Exception:
                v = None
            if v and v.get('ProdutoID'):
                fator_v = Decimal(str(v.get('Fator') or 1)) or Decimal('1')
                produto = {'id': v['ProdutoID'], 'fator': _num(fator_v)}
                if por_produto is None:
                    por_produto = _codigos_por_produto()
                for cod, fator_c in por_produto.get(v['ProdutoID'], []):
                    soma(cod, fator_c / fator_v, 'produto do estoque')   # ex.: unidade bipada numa nota em caixas
        itens.append({'n': it['n'], 'descricao': it['descricao'], 'cprod': it['cprod'], 'ncm': it['ncm'],
                      'unidade': it['unidade'], 'qtd': _num(it['qtd']), 'unidade_trib': it['unidade_trib'],
                      'qtd_trib': _num(it['qtd_trib']), 'ean': it['ean'], 'produto': produto,
                      'codigos': list(codigos.values()), 'conferido': _num(conferidos[it['n']]) if it['n'] in conferidos else None})
    return {'chave': n['chave'], 'numero': n['numero'], 'serie': n['serie'], 'fornecedor': n['fornecedor'], 'cnpj': n['cnpj'],
            'emissao': n['emissao'], 'valor': _num(n['valor'], 2), 'itens': itens,
            'status': cab[0] if cab else ST_AGUARDANDO, 'conferido_por': cab[1] if cab else None,
            'conferido_em': _iso(_como_datahora(cab[2])) if cab else None, 'observacao': cab[3] if cab else None}


def cadastrar_codigo(chave, n_item, codigo, por_bip, usuario):
    """Código que o sistema não conhecia: passa a valer para este item (e para as próximas notas do fornecedor)."""
    cod = normalizar_codigo(codigo)
    if not cod:
        raise ErroCompras("Código de barras inválido.")
    try:
        por_bip = Decimal(str(por_bip or 1).replace(',', '.'))
    except InvalidOperation:
        raise ErroCompras("Quantidade inválida.")
    if not Decimal('0.0001') <= por_bip <= Decimal('10000'):
        raise ErroCompras("Quantidade inválida.")
    n = ler_nota(_caminho_da_chave(chave))
    item = next((i for i in n['itens'] if i['n'] == int(n_item)), None)
    if not item:
        raise ErroCompras("Item não encontrado na nota.")
    if not item['cprod']:
        raise ErroCompras("Este item da nota não tem código do fornecedor: não dá para guardar o código.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM RecebimentoCodigos WHERE CNPJ = ? AND CodigoFornecedor = ? AND Codigo = ?",
                    (n['cnpj'], item['cprod'][:60], cod))
        cur.execute("""INSERT INTO RecebimentoCodigos (CNPJ, CodigoFornecedor, Codigo, PorBip, CriadoPor, CriadoEm)
                       VALUES (?, ?, ?, ?, ?, ?)""", (n['cnpj'], item['cprod'][:60], cod, por_bip, usuario.get('nome'), datetime.now()))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Recebimento: código {cod} ligado ao item {item['cprod']} de {n['fornecedor']} por {usuario.get('nome')}.")
    return obter_recebimento(chave)


def finalizar(chave, quantidades, observacao, usuario):
    """
    Grava a conferência. quantidades = [{'n': nItem, 'qtd': conferido}] (item sem número = 0).
    Devolve a nota com 'divergencias': [{'descricao','nota','conferido','unidade','tipo'}].
    """
    n = ler_nota(_caminho_da_chave(chave))
    conferido = {}
    for q in quantidades or []:
        try:
            conferido[int(q.get('n'))] = max(Decimal(str(q.get('qtd') or 0)), Decimal('0'))
        except (TypeError, ValueError, InvalidOperation, AttributeError):
            raise ErroCompras("Quantidade conferida inválida.")
    divergencias = []
    for it in n['itens']:
        c = conferido.get(it['n'], Decimal('0'))
        if abs(c - it['qtd']) > Decimal('0.001'):
            divergencias.append({'n': it['n'], 'descricao': it['descricao'], 'unidade': it['unidade'], 'nota': _num(it['qtd']),
                                 'conferido': _num(c), 'tipo': 'faltou' if c < it['qtd'] else 'a mais'})
    status = ST_DIVERGENCIA if divergencias else ST_CONFERIDA
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM RecebimentoItens WHERE Chave = ?", (n['chave'],))
        cur.execute("DELETE FROM RecebimentoNotas WHERE Chave = ?", (n['chave'],))
        cur.execute("""INSERT INTO RecebimentoNotas (Chave, NumeroNF, CNPJ, Fornecedor, DataEmissao, Valor, Status,
                                                     ConferidoPorID, ConferidoPor, ConferidoEm, Observacao)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (n['chave'], n['numero'][:20], n['cnpj'][:14], n['fornecedor'][:150], _como_data(n['emissao']), n['valor'],
                     status, usuario.get('id'), usuario.get('nome'), datetime.now(), (str(observacao or '').strip()[:500] or None)))
        for it in n['itens']:
            cur.execute("""INSERT INTO RecebimentoItens (Chave, NItem, Descricao, CodigoFornecedor, EAN, NCM, Unidade, QtdNota, QtdConferida)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (n['chave'], it['n'], it['descricao'][:255], it['cprod'][:60], it['ean'], it['ncm'][:10] or None,
                         it['unidade'], it['qtd'], conferido.get(it['n'], Decimal('0'))))
        conn.commit()
    finally:
        conn.close()
    _guardar_ncm(n)
    logger.info(f"Recebimento: NF {n['numero']} de {n['fornecedor']} conferida por {usuario.get('nome')} ({status}).")
    resultado = obter_recebimento(chave)
    resultado['divergencias'] = divergencias
    return resultado


def _guardar_ncm(n):
    """[NCM] produto do estoque sem NCM recebe o NCM do XML (pelo vínculo do item)."""
    try:
        forn_id = database.buscar_fornecedor_por_cnpj(n['cnpj'])
        if not forn_id:
            return
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            database._garantir_colunas_estoque()
            for it in n['itens']:
                ncm = database.ncm_valido(it['ncm'])
                if not ncm:
                    continue
                v = database.buscar_vinculo_inteligente(forn_id, it['descricao'], it['cprod'], it['ean'])
                if v and v.get('ProdutoID'):
                    cur.execute("UPDATE ProdutosEstoque SET NCM = ? WHERE ProdutoID = ? AND (NCM IS NULL OR NCM = '')",
                                (ncm, v['ProdutoID']))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Recebimento: NCM não guardado: {e}")


def dispensar(chave, usuario):
    """Gestor: tira a nota da lista sem conferir (ex.: nota antiga, mercadoria já guardada)."""
    n = ler_nota(_caminho_da_chave(chave))
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM RecebimentoNotas WHERE Chave = ?", (n['chave'],))
        cur.execute("""INSERT INTO RecebimentoNotas (Chave, NumeroNF, CNPJ, Fornecedor, DataEmissao, Valor, Status,
                                                     ConferidoPorID, ConferidoPor, ConferidoEm, Observacao)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (n['chave'], n['numero'][:20], n['cnpj'][:14], n['fornecedor'][:150], _como_data(n['emissao']), n['valor'],
                     ST_DISPENSADA, usuario.get('id'), usuario.get('nome'), datetime.now(), 'Dispensada sem conferência'))
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}

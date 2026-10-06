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
# [LANÇAMENTO] Ao finalizar, se todos os itens já têm vínculo (DE/PARA), a nota entra
# sozinha no estoque com a quantidade que CHEGOU (mesmas regras de custo do Gestão de
# Estoque: nota_xml.py). Item sem vínculo: o gestor vincula no app (ou no computador)
# e toca em "Lançar no estoque". O vínculo feito no app é o mesmo do computador.
#
# Os XMLs ficam na pasta do nfe_distribuicao (e na subpasta 'importadas', depois que
# a nota entra no estoque pelo Gestão de Estoque): a conferência não depende disso.
# ==============================================================================
import logging
import os
import re
import threading
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import config
import database
from nota_xml import tipo_item_por_cfop
from compras_database import ErroCompras, _conectar, _iso, _num, _dec, _como_data, _como_datahora, normalizar_codigo

logger = logging.getLogger(__name__)

ST_AGUARDANDO = 'aguardando'
ST_CONFERIDA = 'conferida'
ST_DIVERGENCIA = 'divergencia'
ST_DISPENSADA = 'dispensada'
DIAS_PENDENTE = int(getattr(config, 'RECEBIMENTO_DIAS', 20) or 20)   # notas emitidas há mais tempo não aparecem
DIAS_CONFERIDAS = 7
DIAS_SEM_LANCAR = 60      # nota conferida e ainda fora do estoque continua aparecendo até 60 dias

_tabelas_ok = False
_trava_lancamento = threading.Lock()   # [DEPURAÇÃO] dois toques em "Lançar" ao mesmo tempo não lançam a nota 2 vezes
QTD_MAXIMA = Decimal('1000000')
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
            'ean_xml': (prod.findtext('cEAN') or '').strip(),      # como veio (é o que o vínculo guarda)
            'cfop': (prod.findtext('CFOP') or '').strip(),
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
    pendentes, feitas, conferidas = [], [], []
    vistas = set()
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
            if n['finalidade'] == '4' or n['chave'] in vistas:   # devolução; ou o mesmo XML nas duas pastas
                continue
            vistas.add(n['chave'])
            g = gravados.get(n['chave'])
            resumo = {'chave': n['chave'], 'numero': n['numero'], 'fornecedor': n['fornecedor'], 'emissao': n['emissao'],
                      'valor': _num(n['valor'], 2), 'qtd_itens': len(n['itens']),
                      'status': g['status'] if g else ST_AGUARDANDO,
                      'conferido_por': g['por'] if g else None, 'conferido_em': _iso(g['em']) if g else None}
            emissao = _como_data(n['emissao'])
            if resumo['status'] == ST_AGUARDANDO:
                if emissao and emissao >= limite:
                    pendentes.append((resumo, n))
            elif g and g['em'] and resumo['status'] in (ST_CONFERIDA, ST_DIVERGENCIA) \
                    and g['em'].date() >= hoje - timedelta(days=DIAS_SEM_LANCAR):
                conferidas.append((resumo, n, g['em']))   # recentes, ou ainda fora do estoque (até 60 dias)
            elif g and g['em'] and g['em'].date() >= hoje - timedelta(days=DIAS_CONFERIDAS):
                feitas.append(resumo)
    lancadas = _chaves_lancadas([n for _, n, _ in conferidas] + [n for _, n in pendentes])
    for resumo, n in pendentes:
        resumo['lancada'] = n['chave'] in lancadas   # já entrou pelo computador: o app avisa no cartão
    pendentes = [r for r, _ in pendentes]
    for resumo, n, em in conferidas:
        resumo['lancada'] = n['chave'] in lancadas
        if not resumo['lancada'] or em.date() >= hoje - timedelta(days=DIAS_CONFERIDAS):
            feitas.append(resumo)
    pendentes.sort(key=lambda r: r['emissao'] or '', reverse=True)
    feitas.sort(key=lambda r: r['conferido_em'] or '', reverse=True)
    return {'pendentes': pendentes, 'conferidas': feitas, 'dias': DIAS_PENDENTE,
            'aguardando_xml': _aguardando_xml(hoje, vistas)}


def _aguardando_xml(hoje, vistas):
    """[DEPURAÇÃO] Notas que a SEFAZ já avisou (só o resumo) e cujo XML completo ainda não chegou:
    antes ficavam invisíveis no app. Não dá para conferir ainda, mas a pessoa sabe que existem."""
    try:
        import nfe_distribuicao
        estado = nfe_distribuicao.ler_estado()
    except Exception as e:
        logger.warning(f"Recebimento: não deu para ler as notas esperando XML: {e}")
        return []
    limite = hoje - timedelta(days=DIAS_PENDENTE)
    lista = []
    for chave, v in (estado.get('aguardando_xml') or {}).items():
        emissao = _como_data(v.get('emissao'))
        if chave in vistas or (emissao and emissao < limite) or not re.fullmatch(r'\d{44}', chave):
            continue
        try:
            valor = _num(Decimal(str(v.get('valor') or 0)), 2)
        except InvalidOperation:
            valor = None
        lista.append({'chave': chave, 'numero': str(int(chave[25:34])), 'fornecedor': v.get('emitente') or '',
                      'emissao': v.get('emissao') or '', 'valor': valor, 'ciencia': bool(v.get('ciencia'))})
    lista.sort(key=lambda r: r['emissao'], reverse=True)
    return lista


def buscar_xml_na_sefaz(chave, usuario):
    """Gestor: busca o XML de uma nota que só tem o resumo (consulta pela chave)."""
    if not re.fullmatch(r'\d{44}', str(chave or '')):
        raise ErroCompras("Nota inválida.")
    import nfe_distribuicao
    try:
        r = nfe_distribuicao.buscar_por_chave(chave)
    except nfe_distribuicao.ErroNFe as e:
        raise ErroCompras(str(e))
    logger.info(f"Recebimento: {usuario.get('nome')} buscou a nota {chave} na SEFAZ: {r['situacao']}.")
    return r


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
                v = database.buscar_vinculo_inteligente(forn_id, it['descricao'], it['cprod'], it['ean_xml'])
            except Exception:
                v = None
            if v and v.get('ProdutoID'):
                fator_v = Decimal(str(v.get('Fator') or 1)) or Decimal('1')
                if fator_v <= 0:
                    fator_v = Decimal('1')
                produto = {'id': v['ProdutoID'], 'fator': _num(fator_v)}
                if por_produto is None:
                    por_produto = _codigos_por_produto()
                for cod, fator_c in por_produto.get(v['ProdutoID'], []):
                    soma(cod, fator_c / fator_v, 'produto do estoque')   # ex.: unidade bipada numa nota em caixas
        itens.append({'n': it['n'], 'descricao': it['descricao'], 'cprod': it['cprod'], 'ncm': it['ncm'],
                      'tipo': tipo_item_por_cfop(it['cfop']),
                      'unidade': it['unidade'], 'qtd': _num(it['qtd']), 'unidade_trib': it['unidade_trib'],
                      'qtd_trib': _num(it['qtd_trib']), 'ean': it['ean'], 'produto': produto,
                      'codigos': list(codigos.values()), 'conferido': _num(conferidos[it['n']]) if it['n'] in conferidos else None})
    _nomes_dos_produtos(itens)
    lancada = n['chave'] in _chaves_lancadas([n])
    fechada = bool(cab) and cab[0] in (ST_CONFERIDA, ST_DIVERGENCIA)
    # item que não chegou (conferido 0) não entra no estoque: não precisa de vínculo para lançar
    falta = [i for i in itens if i['tipo'] != 'ignorar' and not i['produto'] and not (fechada and not i['conferido'])]
    return {'chave': n['chave'], 'numero': n['numero'], 'serie': n['serie'], 'fornecedor': n['fornecedor'], 'cnpj': n['cnpj'],
            'emissao': n['emissao'], 'valor': _num(n['valor'], 2), 'itens': itens,
            'lancada': lancada, 'falta_vincular': len(falta),
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
        # [DEPURAÇÃO] um código é de UM item: ligado no item errado e depois no certo, sai do errado
        # (antes ficava nos dois e todo bip perguntava qual era)
        cur.execute("DELETE FROM RecebimentoCodigos WHERE CNPJ = ? AND Codigo = ?", (n['cnpj'], cod))
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
            valor = Decimal(str(q.get('qtd') or 0))
            if not valor.is_finite() or valor > QTD_MAXIMA:      # [DEPURAÇÃO] 'Infinity'/'NaN' quebravam a gravação
                raise InvalidOperation
            conferido[int(q.get('n'))] = max(valor, Decimal('0'))
        except (TypeError, ValueError, InvalidOperation, AttributeError):
            raise ErroCompras("Quantidade conferida inválida.")
    divergencias = []
    for it in n['itens']:
        c = conferido.get(it['n'], Decimal('0'))
        if it['n'] in conferido and abs(c - it['qtd']) <= Decimal('0.001'):
            conferido[it['n']] = c = it['qtd']        # 6 bips de 1/6 de caixa = 1 caixa (sem sobra de arredondamento)
        if abs(c - it['qtd']) > Decimal('0.001'):
            divergencias.append({'n': it['n'], 'descricao': it['descricao'], 'unidade': it['unidade'], 'nota': _num(it['qtd']),
                                 'conferido': _num(c), 'tipo': 'faltou' if c < it['qtd'] else 'a mais'})
    status = ST_DIVERGENCIA if divergencias else ST_CONFERIDA
    anterior = _conferencia_gravada(n['chave'])
    if anterior:
        mesma = all(abs(anterior['itens'].get(it['n'], Decimal('0')) - conferido.get(it['n'], Decimal('0'))) <= Decimal('0.0001')
                    for it in n['itens'])
        if mesma:
            # [DEPURAÇÃO] a mesma conferência chegando de novo (fila do celular que perdeu a resposta): não regrava
            resultado = obter_recebimento(chave)
            resultado['divergencias'], resultado['repetida'] = divergencias, True
            return resultado
        if n['chave'] in _chaves_lancadas([n]):
            # [DEPURAÇÃO] antes regravava: a conferência ficava diferente do que entrou no estoque
            raise ErroCompras(f"Esta nota já foi conferida por {anterior['por'] or 'outra pessoa'} e já entrou no estoque: "
                              "a conferência não pode mais ser mudada. Acerte a diferença na próxima contagem.")
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


def _conferencia_gravada(chave):
    """Conferência já gravada desta nota ({'status','por','itens'}) ou None (aguardando/dispensada)."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Status, ConferidoPor FROM RecebimentoNotas WHERE Chave = ?", (chave,))
        cab = cur.fetchone()
        if not cab or cab[0] not in (ST_CONFERIDA, ST_DIVERGENCIA):
            return None
        cur.execute("SELECT NItem, QtdConferida FROM RecebimentoItens WHERE Chave = ?", (chave,))
        return {'status': cab[0], 'por': cab[1], 'itens': {int(r[0]): _dec(r[1] or 0) for r in cur.fetchall()}}
    finally:
        conn.close()


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
                v = database.buscar_vinculo_inteligente(forn_id, it['descricao'], it['cprod'], it['ean_xml'])
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
    anterior = _conferencia_gravada(n['chave'])
    if anterior:
        # [DEPURAÇÃO] antes apagava a conferência de uma nota já conferida (e até já lançada no estoque)
        raise ErroCompras(f"Esta nota já foi conferida por {anterior['por'] or 'outra pessoa'}: não dá para dispensar.")
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


# ------------------------------------------------------------------------------
# [LANÇAMENTO] Vincular itens pelo app e dar entrada no estoque
# ------------------------------------------------------------------------------
def _chaves_lancadas(notas):
    """Quais destas notas (dicts do ler_nota) já estão no estoque (pela chave ou CNPJ + número)."""
    if not notas:
        return set()
    try:
        return database.notas_ja_lancadas([(n['chave'], n['cnpj'], n['numero'], n['serie']) for n in notas])
    except Exception as e:
        logger.warning(f"Recebimento: não deu para conferir as notas já lançadas: {e}")
        return set()


def _nomes_dos_produtos(itens):
    ids = {i['produto']['id'] for i in itens if i['produto']}
    if not ids:
        return
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        lista = list(ids)
        cur.execute(f"SELECT ProdutoID, NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE ProdutoID IN ({','.join('?' * len(lista))})",
                    lista)
        nomes = {r[0]: (r[1], (r[2] or 'UN').strip() or 'UN') for r in cur.fetchall()}
    finally:
        conn.close()
    for i in itens:
        if i['produto'] and i['produto']['id'] in nomes:
            i['produto']['nome'], i['produto']['unidade'] = nomes[i['produto']['id']]


def _fornecedor_da_nota(n, criar=False):
    forn_id = database.buscar_fornecedor_por_cnpj(n['cnpj'])
    if not forn_id and criar:
        database.criar_fornecedor(n['cnpj'], n['fornecedor'][:150])
        forn_id = database.buscar_fornecedor_por_cnpj(n['cnpj'])
        if not forn_id:
            raise ErroCompras(f"Não consegui cadastrar o fornecedor {n['fornecedor']}.")
    return forn_id


def _fator(valor):
    try:
        f = Decimal(str(valor or 1).replace(',', '.'))
    except InvalidOperation:
        raise ErroCompras("Quantidade por embalagem inválida.")
    if not f.is_finite() or not Decimal('0.0001') <= f <= Decimal('100000'):
        raise ErroCompras("Quantidade por embalagem inválida.")
    return f


def _reais(valor):
    texto = f"{Decimal(str(valor)).quantize(Decimal('0.01')):,.2f}"
    return 'R$ ' + texto.replace(',', 'X').replace('.', ',').replace('X', '.')


def vincular_item(chave, n_item, produto_id, fator, usuario, confirmado=False):
    """
    Gestor: diz qual produto do estoque é o item da nota e quantas unidades do estoque vêm
    em 1 unidade da nota. Grava o MESMO vínculo (DE/PARA) que o Gestão de Estoque usa.
    Se o custo por unidade ficar muito diferente da última compra, devolve {'confirmar': texto}
    sem gravar (fator errado distorce o valor do estoque); com confirmado=True grava assim mesmo.
    """
    if not usuario.get('gestor'):
        raise ErroCompras("Só o gestor vincula produtos.")
    import nota_xml
    caminho = _caminho_da_chave(chave)
    n = ler_nota(caminho)
    item = next((i for i in n['itens'] if i['n'] == int(n_item or 0)), None)
    if not item:
        raise ErroCompras("Item não encontrado na nota.")
    try:
        produto_id = int(produto_id)
    except (TypeError, ValueError):
        raise ErroCompras("Escolha o produto do estoque.")
    fator = _fator(fator)
    forn_id = _fornecedor_da_nota(n, criar=True)
    if database.buscar_vinculo_inteligente(forn_id, item['descricao'], item['cprod'], item['ean_xml']):
        raise ErroCompras("Este item já está vinculado. Para trocar, use a tela Vínculos do Gestão de Estoque.")
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT NomeProduto FROM ProdutosEstoque WHERE ProdutoID = ?", (produto_id,))
        linha = cur.fetchone()
    finally:
        conn.close()
    if not linha:
        raise ErroCompras("Produto do estoque não encontrado.")
    if not confirmado:
        try:
            _, itens_xml = nota_xml.ler_xml_nota_fiscal(caminho)
            custo_xml = next((Decimal(str(i['PrecoCustoUnitario'])) for i in itens_xml if i['NItem'] == item['n']), Decimal('0'))
            anterior = Decimal(str(database.ultimo_custo_real_produto(produto_id) or 0))
        except Exception:
            custo_xml = anterior = Decimal('0')
        if custo_xml > 0 and anterior > 0:
            novo = custo_xml / fator
            razao = novo / anterior
            if not Decimal('0.34') < razao < Decimal('3'):
                sugerido = (custo_xml / anterior).quantize(Decimal('1'))
                return {'confirmar': (f"Com {qtd_br(fator)} por {item['unidade']}, o custo de {linha[0]} vai ficar "
                                      f"{_reais(novo)} por unidade, mas a última compra custou {_reais(anterior)}."
                                      + (f" Para ficar parecido, seria perto de {sugerido} por {item['unidade']}." if sugerido > 0 else "")
                                      + "\n\nUm número errado distorce o valor do estoque. Gravar assim mesmo?")}
    novo_id = database.criar_vinculo_produto_fornecedor(
        produto_id_mestre=produto_id, fornecedor_id=forn_id, descricao_xml=item['descricao'][:255],
        cProd=(item['cprod'] or None), cEAN=item['ean_xml'] or '', NCM=item['ncm'] or '', fator_conversao=fator)
    if not novo_id:
        raise ErroCompras("Não consegui gravar o vínculo (veja o log).")
    logger.info(f"Recebimento: '{item['descricao']}' de {n['fornecedor']} vinculado a {linha[0]} (x{fator}) por {usuario.get('nome')}.")
    return obter_recebimento(chave)


def criar_produto_do_item(chave, n_item, usuario, nome, unidade, categoria='Geral', estoque_minimo=0, fator=1):
    """Gestor: cadastra no catálogo um produto que veio na nota e ainda não existia, já vinculado."""
    if not usuario.get('gestor'):
        raise ErroCompras("Só o gestor cadastra produtos.")
    import compras_database as cd
    nome = re.sub(r'\s+', ' ', str(nome or '')).strip()
    unidade = re.sub(r'[^A-Za-z]', '', str(unidade or '')).upper()[:10]
    categoria = (str(categoria or '').strip() or 'Geral')[:100]
    if len(nome) < 3:
        raise ErroCompras("Digite o nome do produto (pelo menos 3 letras).")
    if len(nome) > 100:
        raise ErroCompras("Nome muito comprido (máximo 100 letras).")
    if not unidade:
        raise ErroCompras("Escolha a unidade (UN, KG, L...).")
    try:
        minimo = Decimal(str(estoque_minimo or 0).replace(',', '.'))
    except InvalidOperation:
        raise ErroCompras("Estoque mínimo inválido.")
    if not minimo.is_finite() or minimo < 0:
        raise ErroCompras("Estoque mínimo inválido.")
    fator = _fator(fator)
    n = ler_nota(_caminho_da_chave(chave))
    if not any(i['n'] == int(n_item or 0) for i in n['itens']):
        raise ErroCompras("Item não encontrado na nota.")
    alvo = cd.database_normalizar(nome)
    for p in cd.buscar_produtos(nome, limite=500):
        if cd.database_normalizar(p['nome']) == alvo:
            raise ErroCompras(f"Já existe o produto '{p['nome']}' no estoque. Use a busca para escolher ele.")
    produto_id = database.criar_produto_estoque(nome, unidade, minimo, categoria)
    if not produto_id:
        raise ErroCompras("Não consegui cadastrar o produto (veja o log).")
    logger.info(f"Produto '{nome}' ({unidade}) cadastrado pelo recebimento por {usuario.get('nome')}.")
    return vincular_item(chave, n_item, int(produto_id), fator, usuario, confirmado=True)


def lancar_no_estoque(chave, usuario):
    """
    Dá entrada da nota CONFERIDA no estoque, com a quantidade que chegou (opção do gestor:
    o estoque fica igual à prateleira; a diferença fica registrada na conferência).
    Custo = o da nota (com ST/frete/rateios); bonificação entra com custo zero; comodato e
    remessa ficam de fora. Item que não chegou nada não entra.
    Devolve a nota (obter_recebimento) com 'aumentos' (preços que subiram).
    Erro (ErroCompras) se faltar vínculo ou se a nota não foi conferida.
    """
    with _trava_lancamento:
        return _lancar_no_estoque(chave, usuario)


def _lancar_no_estoque(chave, usuario):
    import nota_xml
    caminho = _caminho_da_chave(chave)
    n = ler_nota(caminho)
    if n['finalidade'] == '4':
        raise ErroCompras("Nota de devolução não entra no estoque.")
    conf = database.conferencias_recebimento([n['chave']]).get(n['chave'])
    if not conf:
        raise ErroCompras("Finalize a conferência antes de lançar no estoque.")
    if n['chave'] in _chaves_lancadas([n]):
        r = obter_recebimento(chave)
        r['aumentos'], r['ja_estava'] = [], True
        return r
    cab, itens = nota_xml.ler_xml_nota_fiscal(caminho)
    fora, compraveis = Decimal('0'), []
    for it in itens:
        tipo = nota_xml.tipo_item_por_cfop(it.get('CFOP'))
        if tipo == 'ignorar':
            fora += it['ValorItemNota']
            continue
        if tipo == 'bonificacao':
            fora += it['ValorItemNota']
            it = dict(it, PrecoCustoUnitario=Decimal('0'))
        compraveis.append(it)
    compraveis, a_menos = nota_xml.aplicar_conferencia(compraveis, conf['itens'])
    fora += a_menos
    forn_id = _fornecedor_da_nota(n, criar=True)
    prontos, faltam = [], []
    for it in compraveis:
        v = database.buscar_vinculo_inteligente(forn_id, it['DescricaoXML'], it.get('cProd'), it.get('cEAN'))
        if not v or not v.get('ProdutoFornecedorID'):
            faltam.append(it['DescricaoXML'])
            continue
        fator = Decimal(str(v.get('Fator') or 1))
        if fator <= 0:
            fator = Decimal('1')
        prontos.append({'ProdutoFornecedorID': v['ProdutoFornecedorID'], 'Quantidade': nota_xml.qtd_estoque(it, fator),
                        'PrecoCustoUnitario': it['PrecoCustoUnitario'] / fator, 'FatorUsado': fator, 'NCM': it.get('NCM')})
    if faltam:
        raise ErroCompras(f"Falta vincular {len(faltam)} item(ns) para lançar no estoque: " + "; ".join(faltam[:5])
                          + ("…" if len(faltam) > 5 else ""))
    if not prontos:
        raise ErroCompras("Nenhum item desta nota chegou: nada para lançar no estoque.")
    cab['FornecedorID'] = forn_id
    cab['ValorForaDoEstoque'] = fora.quantize(Decimal('0.01'))
    ok, msg = database.salvar_nota_fiscal_completa(cab, prontos)
    if not ok:
        if 'já foi importada' not in (msg or ''):
            raise ErroCompras(msg or "Não consegui lançar a nota no estoque.")
        logger.info(f"Recebimento: NF {n['numero']} já estava no estoque.")
    else:
        logger.info(f"Recebimento: NF {n['numero']} de {n['fornecedor']} lançada no estoque por {usuario.get('nome')} "
                    f"({len(prontos)} itens, quantidade conferida).")
        _arquivar(caminho)
    aumentos = []
    if cab.get('NotaID') and hasattr(database, 'aumentos_de_preco'):
        try:   # [ALERTA PREÇO] o que ficou mais caro que na compra anterior
            aumentos = [database.texto_aumento_preco(a) for a in database.aumentos_de_preco(nota_ids=[cab['NotaID']])]
        except Exception as e:
            logger.error(f"Recebimento: não deu para conferir aumentos de preço: {e}")
    r = obter_recebimento(chave)
    r['aumentos'] = aumentos
    return r


def _arquivar(caminho):
    """XML da nota que entrou no estoque vai para a subpasta 'importadas' (como faz o Gestão de Estoque)."""
    pasta, nome = os.path.split(caminho)
    if os.path.basename(pasta) == 'importadas':
        return
    try:
        os.makedirs(os.path.join(pasta, 'importadas'), exist_ok=True)
        os.replace(caminho, os.path.join(pasta, 'importadas', nome))
        _cache_xml.pop(caminho, None)
    except OSError as e:
        logger.warning(f"Recebimento: não deu para mover {nome} para 'importadas': {e}")

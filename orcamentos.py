# ==============================================================================
# == orcamentos.py  -  Orçamentos / pedidos aos fornecedores (app de compras) ==
# ==============================================================================
# O gestor monta o orçamento (fornecedor, produtos, quantidade, preço esperado) ou
# gera a partir de uma lista de compra aprovada (um orçamento por fornecedor), e
# envia o texto pelo "Compartilhar" do celular (WhatsApp, e-mail...).
# O orçamento fica "enviado" esperando a nota. Quando o XML da nota daquele
# fornecedor chega (nfe_distribuicao.py), o sistema liga a nota ao orçamento e
# compara item por item:
#   quantidade: veio certo / faltou / não veio / veio a mais / veio sem pedir
#   preço:      igual / mais caro / mais barato (custo com impostos, por unidade)
# Situação: rascunho -> enviado -> recebido (nota ligada)   ou   cancelado
# ==============================================================================
import html
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import config
import database
from compras_database import ErroCompras, _conectar, _num, _dec, _iso, _como_data, _como_datahora

logger = logging.getLogger(__name__)

ST_RASCUNHO = 'rascunho'
ST_ENVIADO = 'enviado'
ST_RECEBIDO = 'recebido'
ST_CANCELADO = 'cancelado'
ABERTOS = (ST_RASCUNHO, ST_ENVIADO)
DIAS_HISTORICO = 60            # recebidos/cancelados aparecem por 60 dias
DIAS_NOTAS_CANDIDATAS = 60     # notas que podem ser ligadas à mão
PRECO_IGUAL_PCT = Decimal('1')  # até 1% de diferença = mesmo preço
QTD_TOLERANCIA = Decimal('0.001')
QTD_MAXIMA = Decimal('1000000')

_tabelas_ok = False


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
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraOrcamentos')
            CREATE TABLE CompraOrcamentos (
                OrcamentoID INT IDENTITY(1,1) PRIMARY KEY,
                FornecedorID INT NULL,
                Fornecedor NVARCHAR(150) NULL,
                CNPJ VARCHAR(14) NULL,
                Status VARCHAR(20) NOT NULL,
                ListaCodigo VARCHAR(40) NULL,
                Observacao NVARCHAR(500) NULL,
                CriadoPor NVARCHAR(150) NULL,
                CriadoEm DATETIME NULL,
                EnviadoEm DATETIME NULL,
                ChaveNota VARCHAR(44) NULL,
                VinculadoEm DATETIME NULL,
                VinculadoPor NVARCHAR(150) NULL,
                AvisadoEm DATETIME NULL,
                CanceladoEm DATETIME NULL,
                NotasRecusadas VARCHAR(500) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraOrcamentoItens')
            CREATE TABLE CompraOrcamentoItens (
                OrcamentoID INT NOT NULL,
                ProdutoID INT NOT NULL,
                Ordem INT NOT NULL DEFAULT 0,
                NomeProduto NVARCHAR(255) NULL,
                Unidade VARCHAR(20) NULL,
                Qtd DECIMAL(18, 3) NOT NULL,
                Fator DECIMAL(18, 4) NULL,
                Preco DECIMAL(18, 4) NULL,
                DescricaoFornecedor NVARCHAR(255) NULL,
                CodigoFornecedor NVARCHAR(60) NULL,
                PRIMARY KEY (OrcamentoID, ProdutoID)
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def _conexao():
    garantir_tabelas()
    return _conectar()


def _so_digitos(t):
    return re.sub(r'\D', '', str(t or ''))


# ------------------------------------------------------------------------------
# Fornecedores e produtos
# ------------------------------------------------------------------------------
def listar_fornecedores():
    """Fornecedores do cadastro (os que mais venderam primeiro) para escolher no orçamento."""
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT F.FornecedorID, F.NomeFantasia, F.CNPJ, COUNT(NF.NotaID)
                       FROM Fornecedores F LEFT JOIN NotasFiscaisEntrada NF ON NF.FornecedorID = F.FornecedorID
                       GROUP BY F.FornecedorID, F.NomeFantasia, F.CNPJ""")
        lista = [{'id': r[0], 'nome': (r[1] or f'Fornecedor {r[0]}').strip(), 'cnpj': _so_digitos(r[2]), 'notas': int(r[3] or 0)}
                 for r in cur.fetchall() if _so_digitos(r[2]) != database.CNPJ_FORNECEDOR_INTERNO]
    finally:
        conn.close()
    lista.sort(key=lambda f: (-min(f['notas'], 1), f['nome'].upper()))
    return lista


def _fornecedor(fornecedor_id):
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT FornecedorID, NomeFantasia, CNPJ FROM Fornecedores WHERE FornecedorID = ?", (int(fornecedor_id),))
        r = cur.fetchone()
    finally:
        conn.close()
    if not r:
        raise ErroCompras("Fornecedor não encontrado.")
    return {'id': r[0], 'nome': (r[1] or f'Fornecedor {r[0]}').strip(), 'cnpj': _so_digitos(r[2])}


def _dados_do_produto(cur, produto_id, fornecedor_id, hoje=None):
    """Nome, unidade, embalagem (fator), descrição/código no fornecedor e último preço pago a ele."""
    import compras_database as cdb
    cur.execute("SELECT NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE ProdutoID = ?", (int(produto_id),))
    p = cur.fetchone()
    if not p:
        raise ErroCompras("Produto não encontrado.")
    dados = {'nome': p[0] or f'Produto {produto_id}', 'unidade': (p[1] or 'UN').strip() or 'UN',
             'fator': Decimal('1'), 'preco': None, 'descricao': None, 'codigo': None}
    if fornecedor_id:
        cur.execute("""SELECT ProdutoFornecedorID, DescricaoXML, CodigoFornecedor, FatorConversao FROM ProdutosFornecedor
                       WHERE FornecedorID = ? AND ProdutoID = ?""", (int(fornecedor_id), int(produto_id)))
        vinculos = cur.fetchall()
        if vinculos:
            v = max(vinculos, key=lambda r: r[0])        # o vínculo mais novo
            fator = _dec(v[3]) if v[3] is not None else Decimal('1')
            dados.update(descricao=(v[1] or '').strip() or None, codigo=(v[2] or '').strip() or None,
                         fator=fator if fator > 0 else Decimal('1'))
        precos = cdb._precos_por_produto(cur, [int(produto_id)], hoje or date.today()).get(int(produto_id), [])
        deste = next((x for x in precos if x['FornecedorID'] == int(fornecedor_id)), None)
        if deste:
            # [ROYALTIES] o orçamento guarda o preço DO FORNECEDOR (o que se combina e o que vem na nota);
            # o custo com royalties aparece à parte
            dados['preco'] = deste['CustoUnid'] / database._fatores_custo_adicional(cur).get(int(produto_id), Decimal('1'))
    return dados


# ------------------------------------------------------------------------------
# Criar, ler, editar
# ------------------------------------------------------------------------------
def _novo(cur, fornecedor, usuario, lista_codigo=None):
    cur.execute("""INSERT INTO CompraOrcamentos (FornecedorID, Fornecedor, CNPJ, Status, ListaCodigo, CriadoPor, CriadoEm)
                   VALUES (?, ?, ?, ?, ?, ?, ?);
                   SELECT SCOPE_IDENTITY();""",
                (fornecedor['id'], fornecedor['nome'][:150], fornecedor['cnpj'][:14], ST_RASCUNHO, lista_codigo,
                 usuario.get('nome'), datetime.now()))
    cur.nextset()
    return int(cur.fetchone()[0])


def criar_orcamento(fornecedor_id, usuario):
    if not fornecedor_id:
        raise ErroCompras("Escolha o fornecedor.")
    fornecedor = _fornecedor(fornecedor_id)
    conn = _conexao()
    try:
        cur = conn.cursor()
        novo = _novo(cur, fornecedor, usuario)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Orçamento {novo} ({fornecedor['nome']}) criado por {usuario.get('nome')}.")
    return obter_orcamento(novo)


def _cabecalho(cur, orcamento_id):
    cur.execute("""SELECT OrcamentoID, FornecedorID, Fornecedor, CNPJ, Status, ListaCodigo, Observacao, CriadoPor, CriadoEm,
                          EnviadoEm, ChaveNota, VinculadoEm, VinculadoPor, CanceladoEm
                   FROM CompraOrcamentos WHERE OrcamentoID = ?""", (int(orcamento_id),))
    r = cur.fetchone()
    if not r:
        raise ErroCompras("Orçamento não encontrado.")
    return {'id': r[0], 'fornecedor_id': r[1], 'fornecedor': r[2] or '', 'cnpj': r[3] or '', 'status': r[4],
            'lista': r[5], 'observacao': r[6] or '', 'criado_por': r[7], 'criado_em': _iso(_como_datahora(r[8])),
            'enviado_em': _iso(_como_datahora(r[9])), 'chave_nota': r[10], 'vinculado_em': _iso(_como_datahora(r[11])),
            'vinculado_por': r[12], 'cancelado_em': _iso(_como_datahora(r[13]))}


def _itens(cur, orcamento_id):
    cur.execute("""SELECT ProdutoID, Ordem, NomeProduto, Unidade, Qtd, Fator, Preco, DescricaoFornecedor, CodigoFornecedor
                   FROM CompraOrcamentoItens WHERE OrcamentoID = ? ORDER BY Ordem, ProdutoID""", (int(orcamento_id),))
    itens = []
    for r in cur.fetchall():
        fator = _dec(r[5]) if r[5] is not None and _dec(r[5]) > 0 else Decimal('1')
        itens.append({'produto_id': r[0], 'ordem': r[1], 'nome': r[2] or '', 'unidade': r[3] or 'UN', 'qtd': _dec(r[4]),
                      'fator': fator, 'preco': _dec(r[6]) if r[6] is not None else None,
                      'descricao_fornecedor': r[7], 'codigo_fornecedor': r[8]})
    return itens


def _item_json(i):
    return {'produto_id': i['produto_id'], 'nome': i['nome'], 'unidade': i['unidade'], 'qtd': _num(i['qtd']),
            'fator': _num(i['fator']), 'embalagens': _num(i['qtd'] / i['fator']) if i['fator'] > 1 else None,
            'preco': _num(i['preco'], 4) if i['preco'] is not None else None,
            'preco_embalagem': _num(i['preco'] * i['fator'], 2) if i['preco'] is not None else None,
            'total': _num(i['preco'] * i['qtd'], 2) if i['preco'] is not None else None,
            'descricao_fornecedor': i['descricao_fornecedor'], 'codigo_fornecedor': i['codigo_fornecedor']}


def obter_orcamento(orcamento_id):
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        itens = _itens(cur, orcamento_id)
    finally:
        conn.close()
    cab['itens'] = [_item_json(i) for i in itens]
    cab['valor'] = _num(sum((i['preco'] * i['qtd'] for i in itens if i['preco'] is not None), Decimal('0')), 2)
    # [ROYALTIES] custo real (preço do fornecedor + % da categoria, ex.: Sorvetes +45%)
    fatores = database.fatores_custo_adicional()
    valor_real = Decimal('0')
    for i, j in zip(itens, cab['itens']):
        f = fatores.get(i['produto_id'], Decimal('1'))
        j['royalty_pct'] = _num((f - 1) * 100, 2) if f != 1 else None
        j['preco_real'] = _num(i['preco'] * f, 4) if i['preco'] is not None and f != 1 else None
        if i['preco'] is not None:
            valor_real += i['preco'] * i['qtd'] * f
    cab['valor_real'] = _num(valor_real, 2) if fatores and any(j['royalty_pct'] for j in cab['itens']) else None
    cab['nota'] = None
    cab['comparacao'] = None
    if cab['chave_nota']:
        try:
            cab['comparacao'] = comparar(cab, itens)
            cab['nota'] = cab['comparacao']['nota']
        except ErroCompras as e:
            cab['nota'] = {'chave': cab['chave_nota'], 'erro': str(e)}
    return cab


def _editavel(cab):
    if cab['status'] not in ABERTOS:
        raise ErroCompras("Este orçamento não pode mais ser mudado (" + {
            ST_RECEBIDO: "a nota já chegou: desligue a nota para mudar", ST_CANCELADO: "foi cancelado"}.get(cab['status'], cab['status']) + ").")


def salvar_orcamento(orcamento_id, itens, observacao, usuario):
    """Grava a lista de itens inteira (o app manda tudo de uma vez). itens = [{produto_id, qtd, preco}]."""
    novos = []
    vistos = set()
    for ordem, it in enumerate(itens or []):
        try:
            pid = int(it.get('produto_id'))
            qtd = Decimal(str(it.get('qtd') or 0).replace(',', '.'))
            preco = it.get('preco')
            preco = None if preco in (None, '') else Decimal(str(preco).replace(',', '.'))
        except (TypeError, ValueError, InvalidOperation, AttributeError):
            raise ErroCompras("Quantidade ou preço inválido.")
        if not qtd.is_finite() or qtd <= 0 or qtd > QTD_MAXIMA:
            raise ErroCompras("A quantidade de cada item precisa ser maior que zero.")
        if preco is not None and (not preco.is_finite() or preco < 0 or preco > QTD_MAXIMA):
            raise ErroCompras("Preço inválido.")
        if pid in vistos:
            continue
        vistos.add(pid)
        novos.append((pid, ordem, qtd, preco))
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        _editavel(cab)
        antigos = {i['produto_id']: i for i in _itens(cur, orcamento_id)}
        cur.execute("DELETE FROM CompraOrcamentoItens WHERE OrcamentoID = ?", (int(orcamento_id),))
        for pid, ordem, qtd, preco in novos:
            a = antigos.get(pid)
            if a is None:                    # item novo: busca nome, embalagem e descrição no fornecedor
                d = _dados_do_produto(cur, pid, cab['fornecedor_id'])
                a = {'nome': d['nome'], 'unidade': d['unidade'], 'fator': d['fator'], 'descricao_fornecedor': d['descricao'],
                     'codigo_fornecedor': d['codigo']}
            cur.execute("""INSERT INTO CompraOrcamentoItens (OrcamentoID, ProdutoID, Ordem, NomeProduto, Unidade, Qtd, Fator, Preco,
                                                             DescricaoFornecedor, CodigoFornecedor)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (int(orcamento_id), pid, ordem, a['nome'][:255], a['unidade'][:20], qtd, a['fator'], preco,
                         (a['descricao_fornecedor'] or None) and a['descricao_fornecedor'][:255],
                         (a['codigo_fornecedor'] or None) and a['codigo_fornecedor'][:60]))
        if observacao is not None:
            cur.execute("UPDATE CompraOrcamentos SET Observacao = ? WHERE OrcamentoID = ?",
                        (str(observacao).strip()[:500] or None, int(orcamento_id)))
        conn.commit()
    finally:
        conn.close()
    return obter_orcamento(orcamento_id)


def adicionar_produto(orcamento_id, produto_id, usuario):
    """Põe um produto no orçamento: 1 embalagem do fornecedor e o último preço pago a ele."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        _editavel(cab)
        itens = _itens(cur, orcamento_id)
        if any(i['produto_id'] == int(produto_id) for i in itens):
            raise ErroCompras("Este produto já está no orçamento.")
        d = _dados_do_produto(cur, produto_id, cab['fornecedor_id'])
        cur.execute("""INSERT INTO CompraOrcamentoItens (OrcamentoID, ProdutoID, Ordem, NomeProduto, Unidade, Qtd, Fator, Preco,
                                                         DescricaoFornecedor, CodigoFornecedor)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (int(orcamento_id), int(produto_id), len(itens), d['nome'][:255], d['unidade'][:20], d['fator'], d['fator'],
                     d['preco'], d['descricao'] and d['descricao'][:255], d['codigo'] and d['codigo'][:60]))
        conn.commit()
    finally:
        conn.close()
    return obter_orcamento(orcamento_id)


def _mudar_status(orcamento_id, permitido, novo, extras, usuario):
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        if cab['status'] not in permitido:
            raise ErroCompras("Este orçamento não está mais nessa situação. Atualize a tela.")
        campos = ', '.join(['Status = ?'] + [f'{c} = ?' for c in extras])
        cur.execute(f"UPDATE CompraOrcamentos SET {campos} WHERE OrcamentoID = ?", [novo] + list(extras.values()) + [int(orcamento_id)])
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Orçamento {orcamento_id}: {cab['status']} -> {novo} ({usuario.get('nome')}).")
    return obter_orcamento(orcamento_id)


def marcar_enviado(orcamento_id, usuario):
    o = obter_orcamento(orcamento_id)
    if not o['itens']:
        raise ErroCompras("Coloque pelo menos um produto antes de enviar.")
    if o['status'] == ST_ENVIADO:
        return o
    return _mudar_status(orcamento_id, (ST_RASCUNHO,), ST_ENVIADO, {'EnviadoEm': datetime.now()}, usuario)


def cancelar(orcamento_id, usuario):
    return _mudar_status(orcamento_id, ABERTOS, ST_CANCELADO, {'CanceladoEm': datetime.now()}, usuario)


def reabrir(orcamento_id, usuario):
    """Cancelado volta a rascunho (cancelou sem querer)."""
    return _mudar_status(orcamento_id, (ST_CANCELADO,), ST_RASCUNHO, {'CanceladoEm': None}, usuario)


# ------------------------------------------------------------------------------
# Lista aprovada -> um orçamento por fornecedor
# ------------------------------------------------------------------------------
def gerar_da_lista(codigo, usuario):
    import compras_database as cdb
    lista = cdb.obter_lista(codigo)
    if lista['status'] not in (cdb.ST_APROVADA, cdb.ST_AGUARDANDO):
        raise ErroCompras("Só dá para gerar orçamentos de uma lista aberta (aguardando ou aprovada).")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT OrcamentoID FROM CompraOrcamentos WHERE ListaCodigo = ? AND Status <> ?", (str(codigo), ST_CANCELADO))
        ja = [r[0] for r in cur.fetchall()]
        if ja:
            raise ErroCompras(f"Esta lista já gerou orçamento(s): nº {', '.join(str(x) for x in ja)}. "
                              "Cancele-os antes de gerar de novo.")
        por_fornecedor, sem_fornecedor = {}, []
        for i in lista['itens']:
            if not i['qtd_pedido'] or i['qtd_pedido'] <= 0:
                continue
            if not i['fornecedor_id']:
                sem_fornecedor.append(i['nome'])
                continue
            por_fornecedor.setdefault(i['fornecedor_id'], []).append(i)
        if not por_fornecedor:
            raise ErroCompras("Nenhum item da lista tem fornecedor sugerido (nunca foram comprados com nota)."
                              if sem_fornecedor else "A lista não tem nada para comprar.")
        criados = []
        for forn_id, itens in por_fornecedor.items():
            try:
                fornecedor = _fornecedor(forn_id)
            except ErroCompras:
                sem_fornecedor += [i['nome'] for i in itens]
                continue
            novo = _novo(cur, fornecedor, usuario, lista_codigo=str(codigo))
            fatores = database._fatores_custo_adicional(cur)   # [ROYALTIES] a lista tem o custo real; o orçamento, o do fornecedor
            for ordem, i in enumerate(itens):
                d = _dados_do_produto(cur, i['produto_id'], forn_id)
                fator = Decimal(str(i['fator'] or 1)) if i['fator'] and i['fator'] > 0 else d['fator']
                cur.execute("""INSERT INTO CompraOrcamentoItens (OrcamentoID, ProdutoID, Ordem, NomeProduto, Unidade, Qtd, Fator, Preco,
                                                                 DescricaoFornecedor, CodigoFornecedor)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (novo, i['produto_id'], ordem, d['nome'][:255], d['unidade'][:20], Decimal(str(i['qtd_pedido'])), fator,
                             (Decimal(str(i['custo'])) / fatores.get(i['produto_id'], Decimal('1'))) if i['custo'] is not None else d['preco'],
                             d['descricao'] and d['descricao'][:255], d['codigo'] and d['codigo'][:60]))
            criados.append({'id': novo, 'fornecedor': fornecedor['nome'], 'itens': len(itens)})
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Lista {codigo}: {len(criados)} orçamento(s) gerado(s) por {usuario.get('nome')}.")
    return {'criados': criados, 'sem_fornecedor': sem_fornecedor}


# ------------------------------------------------------------------------------
# Texto para mandar ao fornecedor
# ------------------------------------------------------------------------------
def _qtd_txt(v):
    v = Decimal(str(v))
    t = f"{v:.3f}".rstrip('0').rstrip('.')
    return t.replace('.', ',')


def _reais(v):
    t = f"{Decimal(str(v)).quantize(Decimal('0.01')):,.2f}"
    return 'R$ ' + t.replace(',', 'X').replace('.', ',').replace('X', '.')


def texto_orcamento(orcamento_id, com_precos=False):
    o = obter_orcamento(orcamento_id)
    loja = getattr(config, 'NOME_LOJA', None) or 'Gela Boca'
    linhas = [f"*Pedido de compra nº {o['id']} — {loja}*", f"Data: {date.today().strftime('%d/%m/%Y')}",
              f"Para: {o['fornecedor']}", ""]
    for i in o['itens']:
        if i['descricao_fornecedor']:
            qtd = i['embalagens'] if i['embalagens'] is not None else i['qtd']
            nome = i['descricao_fornecedor'] + (f" (cód. {i['codigo_fornecedor']})" if i['codigo_fornecedor'] else '')
            linha = f"• {_qtd_txt(qtd)} × {nome}"
        else:
            linha = f"• {_qtd_txt(i['qtd'])} {i['unidade']} — {i['nome']}"
        if com_precos and i['preco'] is not None:
            linha += f" · {_reais(i['preco_embalagem'] if i['embalagens'] is not None and i['descricao_fornecedor'] else i['preco'])}"
        linhas.append(linha)
    if com_precos and o['valor']:
        linhas += ["", f"Total estimado: {_reais(o['valor'])}"]
    if o['observacao']:
        linhas += ["", f"Obs.: {o['observacao']}"]
    linhas += ["", "Por favor, confirme preços e prazo de entrega. Obrigado!"]
    return {'texto': "\n".join(linhas)}


# ------------------------------------------------------------------------------
# Nota fiscal: ligar ao orçamento e comparar
# ------------------------------------------------------------------------------
def _notas_xml():
    """[(chave, nota)] de todos os XMLs baixados (pasta e 'importadas'), sem repetir."""
    import os
    import recebimento
    vistas, notas = set(), []
    for sub in ('', 'importadas'):
        pasta = os.path.join(recebimento._pasta(), sub)
        if not os.path.isdir(pasta):
            continue
        for nome in os.listdir(pasta):
            if not re.fullmatch(r'\d{44}\.xml', nome) or nome[:44] in vistas:
                continue
            try:
                n = recebimento.ler_nota(os.path.join(pasta, nome))
            except Exception:
                continue
            if n['finalidade'] == '4':
                continue
            vistas.add(n['chave'])
            notas.append(n)
    return notas


def _chaves_ligadas(cur, exceto=None):
    cur.execute("SELECT OrcamentoID, ChaveNota FROM CompraOrcamentos WHERE ChaveNota IS NOT NULL AND Status <> ?", (ST_CANCELADO,))
    return {r[1] for r in cur.fetchall() if r[0] != exceto}


def notas_candidatas(orcamento_id, todos=False):
    """
    Notas do mesmo fornecedor (CNPJ) dos últimos 60 dias que ainda não estão ligadas a outro orçamento.
    todos=True: de QUALQUER fornecedor (comprou de outro: ao ligar, o orçamento passa para o fornecedor da nota).
    """
    import recebimento
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        ligadas = _chaves_ligadas(cur, exceto=int(orcamento_id))
    finally:
        conn.close()
    limite = date.today() - timedelta(days=DIAS_NOTAS_CANDIDATAS)
    nomes = recebimento._nomes_cadastrados()
    lista = []
    for n in _notas_xml():
        emissao = _como_data(n['emissao'])
        if (n['cnpj'] != cab['cnpj'] and not todos) or n['chave'] in ligadas or (emissao and emissao < limite):
            continue
        lista.append({'chave': n['chave'], 'numero': n['numero'], 'emissao': n['emissao'], 'valor': _num(n['valor'], 2),
                      'qtd_itens': len(n['itens']), 'ligada': n['chave'] == cab['chave_nota'], 'outro_fornecedor': n['cnpj'] != cab['cnpj'],
                      'fornecedor': recebimento.nome_fornecedor(n['cnpj'], n.get('razao') or n['fornecedor'], n.get('fantasia_xml', ''), nomes)})
    lista.sort(key=lambda x: x['emissao'], reverse=True)
    lista.sort(key=lambda x: x['outro_fornecedor'])          # as do fornecedor do orçamento primeiro
    return lista


def ligar_nota(orcamento_id, chave, usuario):
    """Liga (chave) ou desliga (chave vazia) a nota do orçamento."""
    chave = _so_digitos(chave)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        if cab['status'] == ST_CANCELADO:
            raise ErroCompras("Orçamento cancelado.")
        if not chave:
            # a nota desligada não volta sozinha (era a nota errada)
            cur.execute("SELECT NotasRecusadas FROM CompraOrcamentos WHERE OrcamentoID = ?", (int(orcamento_id),))
            recusadas = [c for c in str((cur.fetchone() or [''])[0] or '').split(',') if c]
            if cab['chave_nota'] and cab['chave_nota'] not in recusadas:
                recusadas.append(cab['chave_nota'])
            cur.execute("""UPDATE CompraOrcamentos SET ChaveNota = NULL, VinculadoEm = NULL, VinculadoPor = NULL, AvisadoEm = NULL,
                           Status = ?, NotasRecusadas = ? WHERE OrcamentoID = ?""",
                        (ST_ENVIADO if cab['enviado_em'] else ST_RASCUNHO, ','.join(recusadas[-10:]) or None, int(orcamento_id)))
        else:
            if len(chave) != 44:
                raise ErroCompras("Nota inválida.")
            if chave in _chaves_ligadas(cur, exceto=int(orcamento_id)):
                raise ErroCompras("Esta nota já está ligada a outro orçamento.")
            nota = next((n for n in _notas_xml() if n['chave'] == chave), None)
            if nota and nota['cnpj'] != cab['cnpj']:
                # [TROCAR FORNECEDOR] comprou de outro fornecedor: o orçamento passa a ser dele
                import recebimento
                fid = database.buscar_fornecedor_por_cnpj(nota['cnpj'])
                novo = _fornecedor(fid) if fid else {'id': None, 'cnpj': nota['cnpj'], 'nome': recebimento.nome_fornecedor(
                    nota['cnpj'], nota.get('razao') or nota['fornecedor'], nota.get('fantasia_xml', ''), recebimento._nomes_cadastrados())}
                _aplicar_fornecedor(cur, orcamento_id, novo)
            cur.execute("""UPDATE CompraOrcamentos SET ChaveNota = ?, VinculadoEm = ?, VinculadoPor = ?, Status = ?,
                           EnviadoEm = COALESCE(EnviadoEm, ?), AvisadoEm = ? WHERE OrcamentoID = ?""",
                        (chave, datetime.now(), usuario.get('nome'), ST_RECEBIDO, datetime.now(), datetime.now(), int(orcamento_id)))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Orçamento {orcamento_id}: nota {'ligada ' + chave if chave else 'desligada'} por {usuario.get('nome')}.")
    return obter_orcamento(orcamento_id)


# ------------------------------------------------------------------------------
# [TROCAR FORNECEDOR] comprou de outro fornecedor / mandar o mesmo pedido a outro
# ------------------------------------------------------------------------------
def _aplicar_fornecedor(cur, orcamento_id, fornecedor):
    """Passa o orçamento para outro fornecedor: nome, CNPJ e, em cada item, a embalagem e a descrição dele."""
    cur.execute("UPDATE CompraOrcamentos SET FornecedorID = ?, Fornecedor = ?, CNPJ = ?, NotasRecusadas = NULL WHERE OrcamentoID = ?",
                (fornecedor['id'], (fornecedor['nome'] or '')[:150], (fornecedor['cnpj'] or '')[:14], int(orcamento_id)))
    for i in _itens(cur, orcamento_id):
        d = _dados_do_produto(cur, i['produto_id'], fornecedor['id']) if fornecedor['id'] else \
            {'fator': Decimal('1'), 'descricao': None, 'codigo': None}
        cur.execute("""UPDATE CompraOrcamentoItens SET Fator = ?, DescricaoFornecedor = ?, CodigoFornecedor = ?
                       WHERE OrcamentoID = ? AND ProdutoID = ?""",
                    (d['fator'], d['descricao'] and d['descricao'][:255], d['codigo'] and d['codigo'][:60],
                     int(orcamento_id), i['produto_id']))


def trocar_fornecedor(orcamento_id, fornecedor_id, usuario):
    """
    Muda o fornecedor do orçamento (ex.: pediu ao Atacadão mas comprou no Assaí). Os itens, as
    quantidades e os preços combinados ficam; a nota passa a ser procurada pelo CNPJ do novo.
    """
    if not fornecedor_id:
        raise ErroCompras("Escolha o fornecedor.")
    fornecedor = _fornecedor(fornecedor_id)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        _editavel(cab)
        if cab['fornecedor_id'] == fornecedor['id']:
            return obter_orcamento(orcamento_id)
        _aplicar_fornecedor(cur, orcamento_id, fornecedor)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Orçamento {orcamento_id}: fornecedor {cab['fornecedor']} -> {fornecedor['nome']} ({usuario.get('nome')}).")
    if cab['status'] == ST_ENVIADO:
        try:
            vincular_automatico()            # a nota do novo fornecedor pode já ter chegado
        except Exception as e:
            logger.warning(f"Orçamento {orcamento_id}: não deu para procurar a nota agora: {e}")
    return obter_orcamento(orcamento_id)


def copiar_para(orcamento_id, fornecedor_id, usuario):
    """Novo orçamento (rascunho) com os mesmos produtos e quantidades para OUTRO fornecedor (para comparar preços)."""
    if not fornecedor_id:
        raise ErroCompras("Escolha o fornecedor.")
    fornecedor = _fornecedor(fornecedor_id)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cab = _cabecalho(cur, orcamento_id)
        itens = _itens(cur, orcamento_id)
        if not itens:
            raise ErroCompras("Este orçamento não tem produtos para copiar.")
        novo = _novo(cur, fornecedor, usuario, cab['lista'])
        for ordem, i in enumerate(itens):
            d = _dados_do_produto(cur, i['produto_id'], fornecedor['id'])
            # o preço é o último pago a ESTE fornecedor (o combinado com o outro não vale aqui)
            cur.execute("""INSERT INTO CompraOrcamentoItens (OrcamentoID, ProdutoID, Ordem, NomeProduto, Unidade, Qtd, Fator, Preco,
                                                             DescricaoFornecedor, CodigoFornecedor)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (novo, i['produto_id'], ordem, i['nome'][:255], i['unidade'][:20], i['qtd'], d['fator'], d['preco'],
                         d['descricao'] and d['descricao'][:255], d['codigo'] and d['codigo'][:60]))
        if cab['observacao']:
            cur.execute("UPDATE CompraOrcamentos SET Observacao = ? WHERE OrcamentoID = ?", (cab['observacao'][:500], novo))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Orçamento {orcamento_id} copiado para {fornecedor['nome']} (nº {novo}) por {usuario.get('nome')}.")
    return obter_orcamento(novo)


def vincular_automatico(notas=None):
    """
    Orçamentos ENVIADOS ganham sozinhos a nota do mesmo fornecedor emitida a partir do dia do envio
    (a mais antiga ainda livre; o orçamento mais antigo primeiro). Devolve [(orcamento_id, chave)].
    """
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT OrcamentoID, CNPJ, EnviadoEm, NotasRecusadas FROM CompraOrcamentos WHERE Status = ? AND ChaveNota IS NULL",
                    (ST_ENVIADO,))
        abertos = sorted(((r[0], r[1], _como_datahora(r[2]), set(str(r[3] or '').split(','))) for r in cur.fetchall()),
                         key=lambda x: (x[2] or datetime.min, x[0]))
        if not abertos:
            return []
        ligadas = _chaves_ligadas(cur)
        notas = _notas_xml() if notas is None else notas
        feitos = []
        for oid, cnpj, enviado, recusadas in abertos:
            desde = enviado.date() if enviado else date.today()
            livres = sorted((n for n in notas if n['cnpj'] == cnpj and n['chave'] not in ligadas and n['chave'] not in recusadas
                             and (_como_data(n['emissao']) or date.min) >= desde),
                            key=lambda n: (n['emissao'], n['chave']))
            if not livres:
                continue
            chave = livres[0]['chave']
            cur.execute("""UPDATE CompraOrcamentos SET ChaveNota = ?, VinculadoEm = ?, VinculadoPor = ?, Status = ?
                           WHERE OrcamentoID = ? AND ChaveNota IS NULL""",
                        (chave, datetime.now(), 'automático', ST_RECEBIDO, oid))
            ligadas.add(chave)
            feitos.append((oid, chave))
        conn.commit()
    finally:
        conn.close()
    for oid, chave in feitos:
        logger.info(f"Orçamento {oid}: nota {chave} ligada automaticamente.")
    return feitos


def comparar(cab, itens):
    """Orçamento x nota (x conferência do app, se houver), por produto do estoque."""
    import nota_xml
    import recebimento
    caminho = recebimento._caminho_da_chave(cab['chave_nota'])
    n = recebimento.ler_nota(caminho)
    _, itens_nota = nota_xml.ler_xml_nota_fiscal(caminho)
    forn_id = database.buscar_fornecedor_por_cnpj(n['cnpj']) or cab['fornecedor_id']
    conf = database.conferencias_recebimento([n['chave']]).get(n['chave'])
    veio, sem_vinculo = {}, []
    for it in itens_nota:
        tipo = nota_xml.tipo_item_por_cfop(it.get('CFOP'))
        if tipo == 'ignorar':
            continue
        v = database.buscar_vinculo_inteligente(forn_id, it['DescricaoXML'], it.get('cProd'), it.get('cEAN')) if forn_id else None
        if not v or not v.get('ProdutoID'):
            sem_vinculo.append({'descricao': it['DescricaoXML'], 'qtd': _num(it['Quantidade']),
                                'valor': _num(it['Quantidade'] * it['PrecoCustoUnitario'], 2)})
            continue
        fator = _dec(v.get('Fator') or 1)
        fator = fator if fator > 0 else Decimal('1')
        a = veio.setdefault(v['ProdutoID'], {'qtd': Decimal('0'), 'valor': Decimal('0'), 'chegou': None, 'bonificacao': False,
                                             'descricao': it['DescricaoXML'], 'qtd_paga': Decimal('0'), 'qtd_bonus': Decimal('0'),
                                             'valor_sem_impostos': Decimal('0')})
        a['qtd'] += it['Quantidade'] * fator
        if tipo == 'bonificacao':
            # [DEPURAÇÃO] bonificação separada: antes uma linha de bonificação apagava a comparação de preço
            # do produto inteiro e contava como "veio a mais"
            a['bonificacao'] = True
            a['qtd_bonus'] += it['Quantidade'] * fator
        else:
            a['qtd_paga'] += it['Quantidade'] * fator
            a['valor'] += it['Quantidade'] * it['PrecoCustoUnitario']
            a['valor_sem_impostos'] += it.get('ValorSemImpostos', it['Quantidade'] * it['PrecoCustoUnitario'])
        if conf:
            a['chegou'] = (a['chegou'] or Decimal('0')) + conf['itens'].get(it['NItem'], Decimal('0')) * fator
    linhas = []
    resumo = {'ok': 0, 'faltou': 0, 'nao_veio': 0, 'a_mais': 0, 'mais_caro': 0, 'mais_barato': 0}
    diferenca_valor = Decimal('0')
    pedidos = set()
    for i in itens:
        pedidos.add(i['produto_id'])
        a = veio.get(i['produto_id'])
        qtd_nota = a['qtd_paga'] if a else Decimal('0')      # o que foi COMPRADO (a bonificação vem à parte)
        if not a or (qtd_nota <= 0 and a['qtd_bonus'] <= 0):
            sq = 'nao_veio'
        elif qtd_nota + QTD_TOLERANCIA < i['qtd']:
            sq = 'faltou'
        elif qtd_nota > i['qtd'] + QTD_TOLERANCIA:
            sq = 'a_mais'
        else:
            sq = 'ok'
        resumo['ok' if sq == 'ok' else sq] += 1
        preco_nota = preco_sem = sp = pct = None
        so_impostos = False
        if a and a['qtd_paga'] > 0:
            preco_nota = a['valor'] / a['qtd_paga']
            preco_sem = a['valor_sem_impostos'] / a['qtd_paga']
        if preco_nota is not None and i['preco'] is not None and i['preco'] > 0:
            pct = (preco_nota - i['preco']) / i['preco'] * 100
            sp = 'igual' if abs(pct) < PRECO_IGUAL_PCT else ('mais_caro' if pct > 0 else 'mais_barato')
            # o preço combinado costuma vir SEM ST/IPI: se bate com o preço da mercadoria, a diferença é só imposto
            if sp == 'mais_caro' and preco_sem is not None and abs(preco_sem - i['preco']) / i['preco'] * 100 < PRECO_IGUAL_PCT:
                sp, so_impostos = 'igual', True
            if sp != 'igual':
                resumo[sp] += 1
                diferenca_valor += (preco_nota - i['preco']) * qtd_nota
        linhas.append({'produto_id': i['produto_id'], 'nome': i['nome'], 'unidade': i['unidade'], 'fator': _num(i['fator']),
                       'pedido': _num(i['qtd']), 'nota': _num(qtd_nota), 'chegou': _num(a['chegou']) if a and a['chegou'] is not None else None,
                       'situacao': sq, 'preco_pedido': _num(i['preco'], 4) if i['preco'] is not None else None,
                       'preco_nota': _num(preco_nota, 4) if preco_nota is not None else None,
                       'preco': sp, 'pct': _num(pct, 1) if pct is not None else None, 'bonificacao': bool(a and a['bonificacao']),
                       'bonificacao_qtd': _num(a['qtd_bonus']) if a and a['qtd_bonus'] else None,
                       'preco_sem_impostos': _num(preco_sem, 4) if preco_sem is not None else None, 'so_impostos': so_impostos})
    nao_pedidos = []
    if veio:
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            for pid, a in veio.items():
                if pid in pedidos:
                    continue
                cur.execute("SELECT NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE ProdutoID = ?", (pid,))
                r = cur.fetchone()
                nao_pedidos.append({'produto_id': pid, 'nome': (r[0] if r else a['descricao']), 'unidade': (r[1] if r else 'UN') or 'UN',
                                    'nota': _num(a['qtd']), 'valor': _num(a['valor'], 2)})
        finally:
            conn.close()
    resumo['nao_pedidos'] = len(nao_pedidos)
    resumo['sem_vinculo'] = len(sem_vinculo)
    resumo['diferenca_valor'] = _num(diferenca_valor, 2)
    resumo['tudo_certo'] = not any(resumo[k] for k in ('faltou', 'nao_veio', 'a_mais', 'mais_caro', 'nao_pedidos', 'sem_vinculo'))
    nomes = recebimento._nomes_cadastrados()
    return {'nota': {'chave': n['chave'], 'numero': n['numero'], 'emissao': n['emissao'], 'valor': _num(n['valor'], 2),
                     'fornecedor': recebimento.nome_fornecedor(n['cnpj'], n.get('razao') or n['fornecedor'], n.get('fantasia_xml', ''), nomes),
                     'conferida': bool(conf)},
            'linhas': linhas, 'nao_pedidos': nao_pedidos, 'sem_vinculo': sem_vinculo, 'resumo': resumo}


def texto_resumo(o):
    """Uma linha para o Telegram / a tela do Receber: 'tudo certo' ou as diferenças."""
    c = o.get('comparacao')
    if not c:
        return ''
    r = c['resumo']
    if r['tudo_certo']:
        return "tudo como pedido ✅"
    partes = []
    for chave, nome in (('nao_veio', 'não veio'), ('faltou', 'veio a menos'), ('a_mais', 'veio a mais'),
                        ('nao_pedidos', 'sem pedir'), ('mais_caro', 'mais caro'), ('mais_barato', 'mais barato'),
                        ('sem_vinculo', 'sem vínculo')):
        if r.get(chave):
            partes.append(f"{r[chave]} {nome}")
    texto = ", ".join(partes)
    if r['diferenca_valor']:
        texto += f" (preço: {'+' if r['diferenca_valor'] > 0 else '−'}{_reais(abs(r['diferenca_valor']))})"
    return texto


# ------------------------------------------------------------------------------
# Lista da aba Orçamentos
# ------------------------------------------------------------------------------
def listar_orcamentos(hoje=None):
    hoje = _como_data(hoje) or date.today()
    try:
        vincular_automatico()
    except Exception as e:
        logger.warning(f"Orçamentos: ligação automática das notas falhou: {e}")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT O.OrcamentoID, O.Fornecedor, O.Status, O.CriadoEm, O.EnviadoEm, O.ChaveNota, O.CanceladoEm, O.VinculadoEm,
                              COUNT(I.ProdutoID), SUM(I.Qtd * I.Preco)
                       FROM CompraOrcamentos O LEFT JOIN CompraOrcamentoItens I ON I.OrcamentoID = O.OrcamentoID
                       GROUP BY O.OrcamentoID, O.Fornecedor, O.Status, O.CriadoEm, O.EnviadoEm, O.ChaveNota, O.CanceladoEm, O.VinculadoEm""")
        linhas = cur.fetchall()
    finally:
        conn.close()
    limite = hoje - timedelta(days=DIAS_HISTORICO)
    lista = []
    for oid, forn, st, criado, enviado, chave, cancelado, vinculado, qtd, valor in linhas:
        fim = _como_datahora(cancelado) or _como_datahora(vinculado)
        if st not in ABERTOS and fim and fim.date() < limite:
            continue
        item = {'id': oid, 'fornecedor': forn or '', 'status': st, 'criado_em': _iso(_como_datahora(criado)),
                'enviado_em': _iso(_como_datahora(enviado)), 'qtd_itens': int(qtd or 0), 'valor': _num(valor, 2) if valor is not None else None,
                'nota': None, 'resumo': None}
        if st == ST_RECEBIDO and chave:
            try:
                o = obter_orcamento(oid)
                item['nota'] = {'numero': (o['nota'] or {}).get('numero'), 'emissao': (o['nota'] or {}).get('emissao')}
                item['resumo'] = texto_resumo(o) or (o['nota'] or {}).get('erro')
                item['tudo_certo'] = bool(o['comparacao'] and o['comparacao']['resumo']['tudo_certo'])
            except Exception as e:
                item['resumo'] = f"não deu para comparar: {e}"
        lista.append(item)
    ordem = {ST_RASCUNHO: 0, ST_ENVIADO: 1, ST_RECEBIDO: 2, ST_CANCELADO: 3}
    lista.sort(key=lambda x: (ordem.get(x['status'], 9), -(x['id'])))
    return lista


def orcamento_da_nota(chave):
    """Para a tela de conferência do Receber: o orçamento ligado a esta nota (resumo) ou None."""
    try:
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("SELECT OrcamentoID FROM CompraOrcamentos WHERE ChaveNota = ? AND Status <> ?", (str(chave), ST_CANCELADO))
            r = cur.fetchone()
        finally:
            conn.close()
        if not r:
            return None
        o = obter_orcamento(r[0])
        c = o['comparacao']
        diferencas = [l for l in c['linhas'] if l['situacao'] != 'ok' or l['preco'] in ('mais_caro', 'mais_barato')] if c else []
        return {'id': o['id'], 'resumo': texto_resumo(o), 'tudo_certo': bool(c and c['resumo']['tudo_certo']),
                'diferencas': diferencas[:30], 'nao_pedidos': (c or {}).get('nao_pedidos', [])[:30]}
    except Exception as e:
        logger.warning(f"Orçamentos: não deu para ler o orçamento da nota {chave}: {e}")
        return None


def avisos_pendentes():
    """Orçamentos ligados a uma nota e ainda não avisados no Telegram: [(id, texto)] e marca como avisados."""
    try:
        vincular_automatico()
    except Exception as e:
        logger.warning(f"Orçamentos: ligação automática falhou: {e}")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT OrcamentoID FROM CompraOrcamentos WHERE Status = ? AND ChaveNota IS NOT NULL AND AvisadoEm IS NULL", (ST_RECEBIDO,))
        ids = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    avisos = []
    for oid in ids:
        try:
            o = obter_orcamento(oid)
            nota = o['nota'] or {}
            avisos.append((oid, f"📋 <b>Orçamento nº {oid}</b> · {html.escape(o['fornecedor'])}: chegou a NF {nota.get('numero', '?')} — "
                                f"{html.escape(texto_resumo(o) or nota.get('erro', ''))}. Veja no app, aba Orçamentos."))
        except Exception as e:
            logger.warning(f"Orçamentos: aviso do orçamento {oid} falhou: {e}")
    if ids:
        conn = _conexao()
        try:
            cur = conn.cursor()
            for oid in ids:
                cur.execute("UPDATE CompraOrcamentos SET AvisadoEm = ? WHERE OrcamentoID = ?", (datetime.now(), oid))
            conn.commit()
        finally:
            conn.close()
    return avisos

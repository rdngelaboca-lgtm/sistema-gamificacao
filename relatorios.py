# ==============================================================================
# == relatorios.py - relatórios da aba Gestão do app de compras ================
# ==============================================================================
# Tudo sai das notas de entrada já lançadas no estoque (ItensNotaFiscalEntrada):
# a quantidade e o custo de cada item estão na UNIDADE DO ESTOQUE (o custo já
# com ST/IPI/frete rateados), então dá para comparar fornecedores e embalagens.
#   • gasto_por_categoria: quanto foi em cada categoria no mês x mesmo período do mês anterior
#   • inflacao: quanto os produtos mais comprados subiram em 3, 6 e 12 meses
#   • onde_mais_barato: quanto daria para economizar comprando no fornecedor mais barato
# Bonificação (custo zero) e produção interna (CNPJ_FORNECEDOR_INTERNO) não entram nos preços.
# ==============================================================================
import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal

import database
from compras_database import ErroCompras, _como_data, _dec, _num, categoria_do

logger = logging.getLogger(__name__)

TOP_INFLACAO = 30              # produtos mais comprados (em R$) nos últimos 12 meses
JANELA_PRECO_DIAS = 30         # preço "de uma época" = média paga nos 30 dias até aquela data
TOLERANCIA_PRECO_ANTIGO = 60   # sem compra na janela: vale a última compra até 60 dias antes
JANELA_CONCORRENTE_DIAS = 60   # preço de outro fornecedor vale por 60 dias para comparar
DIFERENCA_MINIMA_PCT = Decimal('1')   # menos de 1% de diferença não é "mais barato"


def _compras(desde):
    """Itens comprados (com produto do estoque) desde a data: lista de dicts."""
    conn = database.get_db_connection()
    if not conn:
        raise ErroCompras("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT NF.DataEmissao, INI.Quantidade, INI.PrecoCustoUnitario, PF.ProdutoID, F.FornecedorID, F.NomeFantasia, F.CNPJ,
                   P.NomeProduto, P.Categoria, P.UnidadeMedida
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
            LEFT JOIN ProdutosEstoque P ON P.ProdutoID = PF.ProdutoID
            WHERE INI.Quantidade > 0 AND NF.DataEmissao >= ?
        """, (desde,))
        linhas = cur.fetchall()
        fatores = database._fatores_custo_adicional(cur)   # [ROYALTIES] custo real = nota + % da categoria
    finally:
        conn.close()
    itens = []
    for d, q, custo, pid, fid, fnome, cnpj, nome, cat, un in linhas:
        d = _como_data(d)
        if not d or pid is None or (cnpj or '').strip() == database.CNPJ_FORNECEDOR_INTERNO:
            continue
        f = fatores.get(pid, Decimal('1'))
        q, custo_nota = _dec(q), _dec(custo)
        custo = custo_nota * f
        itens.append({'data': d, 'qtd': q, 'custo': custo, 'valor': q * custo, 'royalties': q * custo_nota * (f - 1), 'produto_id': pid,
                      'fornecedor_id': fid, 'fornecedor': (fnome or 'Fornecedor').strip(), 'nome': nome or f'Produto {pid}',
                      'categoria': categoria_do(cat), 'unidade': (un or 'UN').strip() or 'UN'})
    return itens


def _total_notas(inicio, fim):
    """Total das notas (ValorTotalNF) no período, sem a produção interna."""
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT NF.DataEmissao, NF.ValorTotalNF, F.CNPJ FROM NotasFiscaisEntrada NF
                       LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID WHERE NF.DataEmissao >= ?""", (inicio,))
        total = Decimal('0')
        for d, v, cnpj in cur.fetchall():
            d = _como_data(d)
            if d and inicio <= d <= fim and (cnpj or '').strip() != database.CNPJ_FORNECEDOR_INTERNO:
                total += _dec(v)
        return total
    finally:
        conn.close()


def _periodos(hoje, mes):
    """
    (inicio, fim, inicio_ant, fim_ant, aberto). Mês corrente: do dia 1 até hoje x o mês anterior até
    o mesmo dia. Mês já fechado ('2026-09'): o mês inteiro x o mês anterior inteiro.
    """
    if mes:
        try:
            ano, m = (int(x) for x in str(mes).split('-')[:2])
            inicio = date(ano, m, 1)
        except (ValueError, TypeError):
            raise ErroCompras("Mês inválido.")
    else:
        inicio = hoje.replace(day=1)
    aberto = inicio == hoje.replace(day=1)
    if inicio > hoje:
        raise ErroCompras("Esse mês ainda não começou.")
    fim = hoje if aberto else date(inicio.year, inicio.month, calendar.monthrange(inicio.year, inicio.month)[1])
    fim_mes_ant = inicio - timedelta(days=1)
    inicio_ant = fim_mes_ant.replace(day=1)
    fim_ant = inicio_ant.replace(day=min(fim.day, fim_mes_ant.day)) if aberto else fim_mes_ant
    return inicio, fim, inicio_ant, fim_ant, aberto


def _pct(novo, antigo):
    return _num((novo - antigo) / antigo * 100, 1) if antigo and antigo > 0 else None


def _meses_recentes(hoje, n=6):
    meses, d = [], hoje.replace(day=1)
    for _ in range(n):
        meses.append(d.strftime('%Y-%m'))
        d = (d - timedelta(days=1)).replace(day=1)
    return meses


# ------------------------------------------------------------------------------
# 1) Gasto por categoria
# ------------------------------------------------------------------------------
def gasto_por_categoria(mes=None, hoje=None):
    hoje = _como_data(hoje) or date.today()
    inicio, fim, inicio_ant, fim_ant, aberto = _periodos(hoje, mes)
    itens = [i for i in _compras(inicio_ant) if i['data'] <= fim]
    cats = {}
    for i in itens:
        c = cats.setdefault(i['categoria'], {'atual': Decimal('0'), 'anterior': Decimal('0'), 'produtos': {}})
        if inicio <= i['data'] <= fim:
            c['atual'] += i['valor']
            p = c['produtos'].setdefault(i['produto_id'], {'nome': i['nome'], 'unidade': i['unidade'], 'valor': Decimal('0'), 'qtd': Decimal('0')})
            p['valor'] += i['valor']
            p['qtd'] += i['qtd']
        elif inicio_ant <= i['data'] <= fim_ant:
            c['anterior'] += i['valor']
    total = sum((c['atual'] for c in cats.values()), Decimal('0'))
    total_ant = sum((c['anterior'] for c in cats.values()), Decimal('0'))
    royalties = sum((i['royalties'] for i in itens if inicio <= i['data'] <= fim), Decimal('0'))
    lista = []
    for nome, c in cats.items():
        if not c['atual'] and not c['anterior']:
            continue
        produtos = sorted(c['produtos'].values(), key=lambda p: -p['valor'])[:8]
        lista.append({'categoria': nome, 'valor': _num(c['atual'], 2), 'anterior': _num(c['anterior'], 2),
                      'pct': _pct(c['atual'], c['anterior']), 'parte': _num(c['atual'] / total * 100, 1) if total else 0,
                      'produtos': [{'nome': p['nome'], 'valor': _num(p['valor'], 2), 'qtd': _num(p['qtd']), 'unidade': p['unidade']}
                                   for p in produtos]})
    lista.sort(key=lambda x: (-x['valor'], -x['anterior']))
    # o que está nas notas mas não é item do estoque (frete à parte, itens "fora do estoque", notas sem vínculo)
    outros = _total_notas(inicio, fim) - (total - royalties)   # as notas não têm os royalties
    return {'inicio': inicio.isoformat(), 'fim': fim.isoformat(), 'inicio_ant': inicio_ant.isoformat(), 'fim_ant': fim_ant.isoformat(),
            'aberto': aberto, 'total': _num(total, 2), 'total_ant': _num(total_ant, 2), 'pct': _pct(total, total_ant),
            'royalties': _num(royalties, 2),
            'fora_do_estoque': _num(outros, 2) if outros > Decimal('0.5') else 0,
            'categorias': lista, 'meses': _meses_recentes(hoje), 'mes': inicio.strftime('%Y-%m')}


# ------------------------------------------------------------------------------
# 2) Inflação dos produtos mais comprados
# ------------------------------------------------------------------------------
def _preco_em(compras_produto, dia):
    """Preço médio pago (ponderado pela quantidade) nos 30 dias até 'dia'; sem compra, a última até 60 dias antes."""
    janela = [c for c in compras_produto if dia - timedelta(days=JANELA_PRECO_DIAS) < c['data'] <= dia]
    if not janela:
        antes = [c for c in compras_produto if dia - timedelta(days=JANELA_PRECO_DIAS + TOLERANCIA_PRECO_ANTIGO) < c['data'] <= dia]
        janela = antes[-1:] if antes else []
    q = sum((c['qtd'] for c in janela), Decimal('0'))
    if not janela or q <= 0:
        return None, None
    return sum((c['valor'] for c in janela), Decimal('0')) / q, janela[-1]['data']


def inflacao(hoje=None):
    hoje = _como_data(hoje) or date.today()
    desde = hoje - timedelta(days=365 + JANELA_PRECO_DIAS + TOLERANCIA_PRECO_ANTIGO)
    pagas = [i for i in _compras(desde) if i['custo'] > 0 and i['data'] <= hoje]
    por_produto = {}
    for i in pagas:
        por_produto.setdefault(i['produto_id'], []).append(i)
    ano = hoje - timedelta(days=365)
    gasto = {pid: sum((c['valor'] for c in cs if c['data'] > ano), Decimal('0')) for pid, cs in por_produto.items()}
    top = [pid for pid, v in sorted(gasto.items(), key=lambda x: -x[1]) if v > 0][:TOP_INFLACAO]
    lista = []
    cesta = {3: [Decimal('0'), Decimal('0')], 6: [Decimal('0'), Decimal('0')], 12: [Decimal('0'), Decimal('0')]}
    for pid in top:
        cs = sorted(por_produto[pid], key=lambda c: c['data'])
        atual, quando = _preco_em(cs, hoje)
        if atual is None:
            continue
        qtd_ano = sum((c['qtd'] for c in cs if c['data'] > ano), Decimal('0'))
        linha = {'produto_id': pid, 'nome': cs[-1]['nome'], 'unidade': cs[-1]['unidade'], 'categoria': cs[-1]['categoria'],
                 'preco': _num(atual, 4), 'ultima_compra': quando.isoformat(), 'gasto_ano': _num(gasto[pid], 2)}
        for meses in (3, 6, 12):
            antigo, _ = _preco_em(cs, hoje - timedelta(days=round(meses * 30.4)))
            linha[f'p{meses}'] = _pct(atual, antigo) if antigo is not None else None
            if antigo is not None:
                # cesta: quanto custaria a quantidade de 1 ano com o preço de antes x com o de hoje
                cesta[meses][0] += antigo * qtd_ano
                cesta[meses][1] += atual * qtd_ano
        lista.append(linha)
    return {'produtos': lista, 'cesta': {str(m): _pct(v[1], v[0]) for m, v in cesta.items()}, 'hoje': hoje.isoformat()}


# ------------------------------------------------------------------------------
# 3) Onde comprar mais barato
# ------------------------------------------------------------------------------
def onde_mais_barato(mes=None, hoje=None):
    """
    Para cada compra do mês: o fornecedor que tinha o menor preço (última compra dele nos 60 dias
    antes) e quanto teria economizado. Também os últimos preços de cada fornecedor (90 dias).
    """
    hoje = _como_data(hoje) or date.today()
    inicio, fim, _, _, aberto = _periodos(hoje, mes)
    pagas = [i for i in _compras(inicio - timedelta(days=JANELA_CONCORRENTE_DIAS + 90)) if i['custo'] > 0 and i['data'] <= fim]
    por_produto = {}
    for i in sorted(pagas, key=lambda c: c['data']):
        por_produto.setdefault(i['produto_id'], []).append(i)
    resultado, economia_total, gasto_total = [], Decimal('0'), Decimal('0')
    for pid, cs in por_produto.items():
        do_mes = [c for c in cs if inicio <= c['data'] <= fim]
        if not do_mes:
            continue
        economia, gasto, melhor = Decimal('0'), Decimal('0'), None
        for c in do_mes:
            gasto += c['valor']
            # último preço de CADA outro fornecedor conhecido até o dia da compra
            ultimos = {}
            for o in cs:
                if o['fornecedor_id'] != c['fornecedor_id'] and c['data'] - timedelta(days=JANELA_CONCORRENTE_DIAS) <= o['data'] <= c['data']:
                    ultimos[o['fornecedor_id']] = o
            if not ultimos:
                continue
            mais_barato = min(ultimos.values(), key=lambda o: o['custo'])
            if (c['custo'] - mais_barato['custo']) / c['custo'] * 100 >= DIFERENCA_MINIMA_PCT:
                economia += (c['custo'] - mais_barato['custo']) * c['qtd']
                if not melhor or mais_barato['custo'] < melhor['custo']:
                    melhor = mais_barato
        gasto_total += gasto
        # preços atuais de cada fornecedor (última compra nos 90 dias até o fim do período)
        atuais = {}
        for o in cs:
            if o['data'] >= fim - timedelta(days=90):
                atuais[o['fornecedor_id']] = o
        precos = sorted(({'fornecedor': o['fornecedor'], 'preco': _num(o['custo'], 4), 'data': o['data'].isoformat()}
                         for o in atuais.values()), key=lambda x: x['preco'])
        if economia <= 0 and len(precos) < 2:
            continue
        qtd = sum((c['qtd'] for c in do_mes), Decimal('0'))
        forn_mes = sorted({c['fornecedor'] for c in do_mes})
        economia_total += economia
        resultado.append({'produto_id': pid, 'nome': cs[-1]['nome'], 'unidade': cs[-1]['unidade'], 'qtd': _num(qtd),
                          'gasto': _num(gasto, 2), 'preco_medio': _num(gasto / qtd, 4) if qtd else None,
                          'comprou_em': forn_mes, 'economia': _num(economia, 2),
                          'mais_barato': {'fornecedor': melhor['fornecedor'], 'preco': _num(melhor['custo'], 4),
                                          'data': melhor['data'].isoformat()} if melhor else None,
                          'precos': precos})
    resultado.sort(key=lambda x: (-x['economia'], -x['gasto']))
    return {'inicio': inicio.isoformat(), 'fim': fim.isoformat(), 'aberto': aberto, 'mes': inicio.strftime('%Y-%m'),
            'meses': _meses_recentes(hoje), 'economia': _num(economia_total, 2), 'gasto': _num(gasto_total, 2),
            'produtos': resultado[:60], 'com_economia': sum(1 for r in resultado if r['economia'] > 0)}

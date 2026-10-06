# ==============================================================================
# == nota_xml.py  -  Leitura do XML da NF-e para dar entrada no estoque ========
# ==============================================================================
# As MESMAS regras para o Gestão de Estoque (aba Importar XMLs) e para o app de
# compras (conferência de recebimento):
#   • custo de cada item = valor + ST + FCP-ST + IPI + frete + seguro + outras − desconto;
#   • ST/frete/etc. que vêm só no TOTAL da nota são divididos entre os itens;
#   • CFOP de bonificação entra com custo zero; comodato/remessa/devolução ficam de fora;
#   • quantidade conferida no app (quando houver) substitui a quantidade da nota.
# ==============================================================================
import logging
import re
from datetime import datetime
from decimal import Decimal

try:
    from lxml import etree as ET
    USANDO_LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    USANDO_LXML = False

logger = logging.getLogger(__name__)

# [MELHORIA VALOR] Tipo da operação de cada item da nota (CFOP, últimos 3 dígitos).
# Bonificação / brinde / amostra grátis: a mercadoria entra no estoque com CUSTO ZERO
# (não foi paga). Comodato (ex: freezer emprestado pela fábrica), remessas, conserto,
# vasilhame e devoluções NÃO são compra: esses itens são ignorados.
CFOP_BONIFICACAO = {'910', '911'}
CFOP_IGNORAR = {'908', '909', '912', '913', '915', '916', '920', '921', '201', '202', '410', '411'}


def so_digitos(texto):
    return re.sub(r'\D', '', str(texto or ''))


def tipo_item_por_cfop(cfop):
    """'compra', 'bonificacao' ou 'ignorar'."""
    final = so_digitos(cfop)[-3:]
    if final in CFOP_BONIFICACAO:
        return 'bonificacao'
    if final in CFOP_IGNORAR:
        return 'ignorar'
    return 'compra'


def ler_xml_nota_fiscal(caminho_arquivo_xml):
    """
    Devolve (cabecalho, itens). Cada item: cProd, cEAN, DescricaoXML, NCM, Quantidade (da nota),
    PrecoCustoUnitario (custo real, com impostos e rateios), ValorItemNota, CFOP e NItem.
    """
    def dec(texto):
        """Número do XML -> Decimal (tag vazia vale 0)."""
        texto = (texto or '').strip()
        return Decimal(texto) if texto else Decimal('0')

    try:
        if USANDO_LXML:
            # resolve_entities=False: não deixa um XML malicioso ler arquivos do computador
            parser = ET.XMLParser(remove_blank_text=True, resolve_entities=False)
            tree = ET.parse(caminho_arquivo_xml, parser)
        else:
            tree = ET.parse(caminho_arquivo_xml)
        root = tree.getroot()

        # Remove namespaces para facilitar a busca das tags
        for elem in root.iter():
            if not isinstance(elem.tag, str):
                continue  # comentários do XML
            i = elem.tag.find('}')
            if i >= 0:
                elem.tag = elem.tag[i + 1:]

        ide = root.find('.//ide')
        emit = root.find('.//emit')
        total = root.find('.//total/ICMSTot')
        if ide is None or emit is None or total is None:
            raise Exception("Estrutura do XML inválida (tags essenciais não encontradas após limpeza).")

        inf_nfe = root.find('.//infNFe')
        chave = (inf_nfe.get('Id') or '').replace('NFe', '') if inf_nfe is not None else ''

        dados_nf = {
            'NumeroNF': (ide.findtext('nNF', default='') or '').strip(),
            'Serie': (ide.findtext('serie', default='') or '').strip(),
            'ChaveAcesso': chave,
            # Alguns XMLs usam dhEmi, outros dEmi. Tenta ambos.
            'DataEmissao': (ide.findtext('dhEmi') or ide.findtext('dEmi') or datetime.now().strftime('%Y-%m-%dT')).split('T')[0],
            'ValorTotalNF': dec(total.findtext('vNF', default='0.0')),
            # Produtor rural emite NF-e com CPF (não CNPJ)
            'FornecedorCNPJ': so_digitos(emit.findtext('CNPJ', default='') or emit.findtext('CPF', default='')),
            'FornecedorNome': (emit.findtext('xNome', default='') or '').strip(),
            # finNFe=4 é nota de DEVOLUÇÃO (não é compra)
            'Finalidade': (ide.findtext('finNFe', default='1') or '1').strip(),
        }

        itens = []
        somas_itens = {k: Decimal('0') for k in ('vST', 'vFCPST', 'vFrete', 'vSeg', 'vOutro', 'vIPI', 'vDesc')}
        for det in root.findall('.//det'):
            prod = det.find('prod')
            if prod is None:
                continue

            qtd_xml = dec(prod.findtext('qCom', default='0.0'))
            vProd = dec(prod.findtext('vProd', default='0.0'))
            vFrete = dec(prod.findtext('vFrete', default='0.0'))
            vSeg = dec(prod.findtext('vSeg', default='0.0'))
            vOutro = dec(prod.findtext('vOutro', default='0.0'))
            vDesc = dec(prod.findtext('vDesc', default='0.0'))
            # O './/' varre qualquer tag de imposto procurando a ST
            vICMSST = dec(det.findtext('.//vICMSST', default='0.0'))
            vIPI = dec(det.findtext('.//vIPI', default='0.0'))
            # FCP-ST (Fundo de Combate à Pobreza cobrado junto com a ST) também é custo
            vFCPST = dec(det.findtext('.//vFCPST', default='0.0'))

            custo_total_item = vProd + vICMSST + vFCPST + vIPI + vFrete + vSeg + vOutro - vDesc
            custo_unit_real = custo_total_item / qtd_xml if qtd_xml > 0 else Decimal('0.0')

            partes_item = {'vST': vICMSST, 'vFCPST': vFCPST, 'vFrete': vFrete, 'vSeg': vSeg,
                           'vOutro': vOutro, 'vIPI': vIPI, 'vDesc': vDesc}
            for chave_parte, valor_parte in partes_item.items():
                somas_itens[chave_parte] += valor_parte

            try:
                n_item = int(det.get('nItem') or len(itens) + 1)
            except ValueError:
                n_item = len(itens) + 1
            itens.append({
                '_vProd': vProd, '_custo_total': custo_total_item,
                'ValorItemNota': custo_total_item,   # valor do item na nota (p/ "fora do estoque")
                'NItem': n_item,                     # nº do item na nota (liga com a conferência do app)
                'cProd': prod.findtext('cProd', default=''),
                'cEAN': (prod.findtext('cEAN', default='') or '').strip(),
                'DescricaoXML': prod.findtext('xProd', default=''),
                'NCM': prod.findtext('NCM', default=''),
                'Quantidade': qtd_xml,
                'PrecoCustoUnitario': custo_unit_real,
                'CFOP': (prod.findtext('CFOP', default='') or '').strip(),
            })

        # [MELHORIA ST] ST/frete/seguro/outras/IPI/desconto que vêm SÓ no total da nota são
        # divididos entre os itens de COMPRA, proporcional ao valor de cada um (vProd).
        ajustes = {}
        compraveis = [i for i in itens if tipo_item_por_cfop(i.get('CFOP')) == 'compra'] or itens
        total_vprod = sum((i['_vProd'] for i in compraveis), Decimal('0'))
        if total_vprod > 0:
            for chave_parte in somas_itens:
                valor_total = dec(total.findtext(chave_parte, default='0'))
                diferenca = valor_total - somas_itens[chave_parte]
                # Só ACRESCENTA o que faltou nos itens
                if diferenca >= Decimal('0.01'):
                    ajustes[chave_parte] = diferenca
            if ajustes:
                sinal = {'vDesc': Decimal('-1')}
                for item in compraveis:
                    parte = item['_vProd'] / total_vprod
                    extra = sum((d * sinal.get(k, Decimal('1')) * parte for k, d in ajustes.items()), Decimal('0'))
                    item['_custo_total'] += extra
                    if item['Quantidade'] > 0:
                        item['PrecoCustoUnitario'] = item['_custo_total'] / item['Quantidade']
                logger.info(f"NF {dados_nf['NumeroNF']}: valores só no total rateados nos itens: "
                            + ", ".join(f"{k}={v}" for k, v in ajustes.items()))
        dados_nf['AjustesRateados'] = ajustes
        for item in itens:
            item.pop('_vProd', None)
            item.pop('_custo_total', None)

        return dados_nf, itens

    except Exception as e:
        logger.error(f"Erro ao ler o arquivo XML '{caminho_arquivo_xml}': {e}", exc_info=True)
        raise Exception(f"Falha estrutural no XML: {e}")


def aplicar_conferencia(itens, conferidos):
    """
    [RECEBIMENTO] Troca a quantidade da nota pela quantidade que CHEGOU (conferida no app).
    conferidos = {NItem: quantidade, na unidade da nota}. O custo unitário não muda.
    Item que não chegou nada sai da lista. Devolve (itens, valor_a_menos): valor_a_menos é o
    valor da nota que não entrou no estoque (negativo se chegou mais do que a nota) e vai
    somado ao "valor fora do estoque" da nota.
    """
    novos, valor_a_menos = [], Decimal('0')
    for it in itens:
        n = it.get('NItem')
        if n not in conferidos:
            novos.append(it)
            continue
        chegou = Decimal(str(conferidos[n]))
        valor_a_menos += (Decimal(str(it['Quantidade'])) - chegou) * Decimal(str(it['PrecoCustoUnitario']))
        if chegou > 0:
            novos.append(dict(it, Quantidade=chegou, QuantidadeNota=it['Quantidade']))
    return novos, valor_a_menos


def qtd_estoque(item, fator):
    """
    Quantidade na unidade do estoque (quantidade x fator). Quando veio da conferência do app,
    arredonda em 3 casas: bips de 1/6 de caixa somam 0,166667 + ... e sobraria 12,000012.
    """
    qtd = Decimal(str(item['Quantidade'])) * Decimal(str(fator))
    return qtd.quantize(Decimal('0.001')) if 'QuantidadeNota' in item else qtd

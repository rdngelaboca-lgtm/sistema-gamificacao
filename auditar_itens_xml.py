# ==============================================================================
# == auditar_itens_xml.py - nenhum item do XML ficou para trás? ================
# ==============================================================================
# Uso:  python3 auditar_itens_xml.py            (todas as notas baixadas da SEFAZ)
#       python3 auditar_itens_xml.py 79272      (só a nota com esse número)
#
# Para cada XML da pasta da SEFAZ (e da subpasta 'importadas') confere:
#   1) LEITURA: quantos <det> (itens) tem o arquivo x quantos o sistema leu
#      (leitura do estoque e leitura do app) e se a soma dos itens bate com o valor da nota;
#   2) ESTOQUE: se a nota já foi lançada, quantos itens foram gravados x quantos deviam
#      (tira os de comodato/remessa e os que a conferência do app disse que não chegaram)
#      e se a soma gravada + "valor fora do estoque" bate com o valor da nota.
# NÃO muda nada no banco nem nos arquivos. Mande o resultado para o Claude.
# ==============================================================================
import os
import re
import sys
from decimal import Decimal

import database
import nfe_distribuicao as nd
import nota_xml
import recebimento

TOLERANCIA = Decimal('0.05')


def so_digitos(t):
    return re.sub(r'\D', '', str(t or ''))


def _dec(v):
    return Decimal(str(v or 0))


def nota_no_banco(cur, cab):
    """(NotaID, ValorForaDoEstoque, NumeroNF) da nota no banco: pela chave ou pelo CNPJ + número."""
    cur.execute("SELECT NotaID, ValorForaDoEstoque, NumeroNF FROM NotasFiscaisEntrada WHERE ChaveAcesso = ?",
                (cab['ChaveAcesso'],))
    r = cur.fetchone()
    if r:
        return r
    numero = so_digitos(cab['NumeroNF']).lstrip('0')
    cur.execute("""SELECT NF.NotaID, NF.ValorForaDoEstoque, NF.NumeroNF, F.CNPJ FROM NotasFiscaisEntrada NF
                   JOIN Fornecedores F ON F.FornecedorID = NF.FornecedorID WHERE NF.NumeroNF LIKE ?""", (f"%{numero}",))
    for nota_id, fora, num, cnpj in cur.fetchall():
        if so_digitos(num).lstrip('0') == numero and so_digitos(cnpj) == cab['FornecedorCNPJ']:
            return nota_id, fora, num
    return None


def main():
    so_numero = so_digitos(sys.argv[1]).lstrip('0') if len(sys.argv) > 1 else None
    pasta = nd.pasta_xml()
    arquivos = []
    for sub in ('', 'importadas'):
        p = os.path.join(pasta, sub)
        if os.path.isdir(p):
            arquivos += [os.path.join(p, f) for f in sorted(os.listdir(p)) if re.fullmatch(r'\d{44}\.xml', f)]
    print(f"Pasta: {pasta}  ({len(arquivos)} XML(s))\n")
    conn = database.get_db_connection()
    if not conn:
        print("Sem conexão com o banco.")
        return
    cur = conn.cursor()
    try:
        database._garantir_colunas_estoque()
    except Exception:
        pass
    vistas, problemas, avisos = set(), [], []
    conferidas = 0
    lancadas = nao_lancadas = 0
    for caminho in arquivos:
        chave = os.path.basename(caminho)[:44]
        if chave in vistas:
            continue
        vistas.add(chave)
        try:
            bruto = open(caminho, 'rb').read()
            texto = bruto.decode('latin-1') if b'ISO-8859-1' in bruto[:100].upper() else bruto.decode('utf-8-sig', 'replace')
            n_det = len(re.findall(r'<(?:\w+:)?det[\s>]', texto))
            cab, itens = nota_xml.ler_xml_nota_fiscal(caminho)
            rec = recebimento.ler_nota(caminho)
        except Exception as e:
            problemas.append(f"{chave[:12]}…: o XML NÃO ABRIU ({e})")
            continue
        if so_numero and so_digitos(cab['NumeroNF']).lstrip('0') != so_numero:
            continue
        conferidas += 1
        nome = f"NF {cab['NumeroNF']} ({cab['FornecedorNome'][:30]})"
        # 1) leitura
        if not (n_det == len(itens) == len(rec['itens'])):
            problemas.append(f"{nome}: o arquivo tem {n_det} itens, o sistema leu {len(itens)} (estoque) / {len(rec['itens'])} (app)")
        soma = sum(i['Quantidade'] * i['PrecoCustoUnitario'] for i in itens)
        if abs(soma - cab['ValorTotalNF']) > TOLERANCIA:
            avisos.append(f"{nome}: soma dos itens R$ {soma:.2f} x valor da nota R$ {cab['ValorTotalNF']:.2f} "
                          "(diferença de valores que a nota não detalha, ex.: ICMS desonerado)")
        if cab.get('Finalidade') == '4':
            continue                                    # devolução: não entra no estoque
        # 2) estoque
        r = nota_no_banco(cur, cab)
        if not r:
            nao_lancadas += 1
            continue
        lancadas += 1
        nota_id, fora, _ = r
        conf = database.conferencias_recebimento([cab['ChaveAcesso']]).get(cab['ChaveAcesso'])
        esperados = [i for i in itens if nota_xml.tipo_item_por_cfop(i['CFOP']) != 'ignorar']
        if conf:
            esperados = [i for i in esperados if conf['itens'].get(i['NItem'], Decimal('1')) > 0]
        cur.execute("SELECT Quantidade, PrecoCustoUnitario FROM ItensNotaFiscalEntrada WHERE NotaID = ?", (nota_id,))
        gravados = cur.fetchall()
        if len(gravados) < len(esperados):
            problemas.append(f"{nome}: {len(esperados) - len(gravados)} ITEM(NS) FICOU(ARAM) FORA DO ESTOQUE "
                             f"(XML {len(esperados)} item(ns) de compra, gravados {len(gravados)})")
        elif len(gravados) > len(esperados):
            avisos.append(f"{nome}: gravados {len(gravados)} itens, o XML tem {len(esperados)} (nota lançada duas vezes juntas?)")
        total = sum(_dec(q) * _dec(p) for q, p in gravados) + _dec(fora)
        if fora is None:
            avisos.append(f"{nome}: lançada antes do controle de 'valor fora do estoque' (não dá para conferir o valor)")
        elif abs(total - cab['ValorTotalNF']) > TOLERANCIA:
            avisos.append(f"{nome}: no estoque R$ {total:.2f} x nota R$ {cab['ValorTotalNF']:.2f}")
    conn.close()
    print(f"Notas conferidas: {conferidas}  ·  já no estoque: {lancadas}  ·  ainda não lançadas: {nao_lancadas}\n")
    if problemas:
        print(f"PROBLEMAS ({len(problemas)}):")
        for p in problemas:
            print("  ✗ " + p)
    else:
        print("✓ Nenhum item ficou para trás: todo item do XML foi lido e todo item de compra está no estoque.")
    if avisos:
        print(f"\nAvisos ({len(avisos)}) - para conferir, não são itens perdidos:")
        for a in avisos[:40]:
            print("  • " + a)
        if len(avisos) > 40:
            print(f"  … e mais {len(avisos) - 40}")
    print("\nCopie tudo acima e mande para o Claude.")


if __name__ == '__main__':
    main()

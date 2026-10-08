# ==============================================================================
# == conferir_nota_sefaz.py - por que uma nota da SEFAZ não sai da lista? ======
# ==============================================================================
# Uso:  python3 conferir_nota_sefaz.py 79272
# Mostra o que está no XML baixado e o que está gravado no banco com esse número
# (fornecedor, CNPJ, série, chave). Não muda nada. Mande o resultado para o Claude.
# ==============================================================================
import os
import re
import sys
import xml.etree.ElementTree as ET

import database
import nfe_distribuicao as nd


def so_digitos(t):
    return re.sub(r'\D', '', str(t or ''))


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 conferir_nota_sefaz.py NUMERO_DA_NOTA")
        return
    numero = str(int(so_digitos(sys.argv[1])))
    pasta = nd.pasta_xml()
    print(f"\n1) XML(s) baixados com o número {numero}:")
    achou = False
    for sub in ('', 'importadas'):
        p = os.path.join(pasta, sub)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if not f.lower().endswith('.xml'):
                continue
            try:
                raiz = ET.parse(os.path.join(p, f)).getroot()
            except ET.ParseError:
                continue
            tx = {el.tag.split('}')[-1]: (el.text or '').strip() for el in raiz.iter() if el.text}
            if tx.get('nNF', '').lstrip('0') != numero:
                continue
            achou = True
            emit = next((el for el in raiz.iter() if el.tag.endswith('emit')), None)
            cnpj = next((so_digitos(el.text) for el in emit.iter() if el.tag.endswith('CNPJ')), '') if emit is not None else ''
            print(f"   {'(importadas) ' if sub else ''}{f[:12]}…  CNPJ {cnpj}  série {tx.get('serie')}  valor {tx.get('vNF')}")
    if not achou:
        print("   nenhum")
    print(f"\n2) Notas no BANCO com o número {numero} (com ou sem zeros na frente):")
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""SELECT NF.NotaID, NF.NumeroNF, NF.Serie, NF.ChaveAcesso, NF.DataEmissao, NF.ValorTotalNF,
                                  F.FornecedorID, F.CNPJ, F.NomeFantasia
                           FROM NotasFiscaisEntrada NF LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
                           WHERE NF.NumeroNF LIKE ?""", (f"%{numero}",))
        except Exception:
            cur.execute("""SELECT NF.NotaID, NF.NumeroNF, NULL, NULL, NF.DataEmissao, NF.ValorTotalNF,
                                  F.FornecedorID, F.CNPJ, F.NomeFantasia
                           FROM NotasFiscaisEntrada NF LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
                           WHERE NF.NumeroNF LIKE ?""", (f"%{numero}",))
        linhas = [r for r in cur.fetchall() if so_digitos(r[1]).lstrip('0') == numero]
        for r in linhas:
            print(f"   NotaID {r[0]}  nº '{r[1]}'  série {r[2]}  chave {'sim' if r[3] else 'não'}  data {r[4]}  "
                  f"valor {r[5]}  fornecedor {r[6]} ({r[8]}) CNPJ '{r[7]}'")
        if not linhas:
            print("   nenhuma: esta nota NÃO está no estoque.")
    finally:
        conn.close()
    print("\nCopie tudo acima e mande para o Claude.")


if __name__ == '__main__':
    main()

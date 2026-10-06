# ==============================================================================
# == auditar_itens_xml.py - nenhum item do XML ficou para trás? ================
# ==============================================================================
# Uso:  python3 auditar_itens_xml.py              (todas as notas baixadas da SEFAZ)
#       python3 auditar_itens_xml.py 79272        (só a nota com esse número)
#       python3 auditar_itens_xml.py --completar  (lança no estoque os itens que ficaram de fora;
#                                                  mostra tudo e pede confirmação antes de gravar)
#
# Para cada XML da pasta da SEFAZ (e da subpasta 'importadas') confere:
#   1) LEITURA: quantos <det> (itens) tem o arquivo x quantos o sistema leu
#      (leitura do estoque e leitura do app) e se a soma dos itens bate com o valor da nota;
#   2) ESTOQUE: se a nota já foi lançada, quantos itens foram gravados x quantos deviam
#      (tira os de comodato/remessa e os que a conferência do app disse que não chegaram)
#      e se a soma gravada + "valor fora do estoque" bate com o valor da nota.
# Sem --completar NÃO muda nada no banco nem nos arquivos. Mande o resultado para o Claude.
#
# Por que acontecia: até 24/09/2026 o Gestão de Estoque salvava a nota com os itens já
# vinculados e deixava de fora (sem avisar) os itens ainda sem vínculo; a nota ficava
# marcada como importada e o resto nunca mais entrava. O --completar põe esses itens
# NA MESMA NOTA (mesma data e custo do XML), sem duplicar o que já está lá.
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


def itens_faltando(cur, forn_id, esperados, nota_id, conf):
    """
    Quais itens do XML NÃO estão gravados na nota. Liga cada item gravado a um item do XML
    (pela descrição/código do vínculo usado, ou pelo produto do estoque, preferindo a mesma
    quantidade). Devolve [(item_xml, vinculo_atual_ou_None, qtd_na_unidade_da_nota)].
    """
    cur.execute("""SELECT INI.ItemNotaID, PF.ProdutoID, INI.Quantidade, INI.FatorConversaoUsado, PF.FatorConversao,
                          PF.DescricaoXML, PF.CodigoFornecedor
                   FROM ItensNotaFiscalEntrada INI LEFT JOIN ProdutosFornecedor PF ON PF.ProdutoFornecedorID = INI.ProdutoFornecedorID
                   WHERE INI.NotaID = ?""", (nota_id,))
    gravados = [{'pid': r[1], 'qtd': _dec(r[2]) / (_dec(r[3] or r[4] or 1) or 1), 'desc': (r[5] or '').strip(),
                 'cod': (r[6] or '').strip(), 'usado': False} for r in cur.fetchall()]
    faltando = []
    for it in esperados:
        qtd = conf['itens'].get(it['NItem'], it['Quantidade']) if conf else it['Quantidade']
        v = database.buscar_vinculo_inteligente(forn_id, it['DescricaoXML'], it.get('cProd'), it.get('cEAN')) if forn_id else None
        pid = v['ProdutoID'] if v else None
        def nota(g):
            if g['usado']:
                return -1
            pontos = 0
            if g['desc'] and g['desc'] == it['DescricaoXML'].strip():
                pontos += 4
            if g['cod'] and g['cod'] == str(it.get('cProd') or '').strip():
                pontos += 2
            if pid and g['pid'] == pid:
                pontos += 2
            if pontos and abs(g['qtd'] - _dec(qtd)) <= Decimal('0.01'):
                pontos += 1
            return pontos
        melhor = max(gravados, key=nota, default=None)
        if melhor is not None and nota(melhor) >= 2:
            melhor['usado'] = True
        else:
            faltando.append((it, v, _dec(qtd)))
    return faltando


def completar(cur, conn, nota_id, faltando):
    """Grava os itens que faltam (só os que já têm vínculo) na nota existente. Devolve quantos gravou."""
    gravou = 0
    for it, v, qtd in faltando:
        if not v or not v.get('ProdutoFornecedorID'):
            continue
        fator = _dec(v.get('Fator') or 1)
        if fator <= 0:
            fator = Decimal('1')
        custo = Decimal('0') if nota_xml.tipo_item_por_cfop(it['CFOP']) == 'bonificacao' else _dec(it['PrecoCustoUnitario'])
        cur.execute("""INSERT INTO ItensNotaFiscalEntrada (NotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario, FatorConversaoUsado)
                       VALUES (?, ?, ?, ?, ?)""", (nota_id, v['ProdutoFornecedorID'], qtd * fator, custo / fator, fator))
        gravou += 1
    conn.commit()
    return gravou


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    modo_completar = '--completar' in sys.argv
    so_numero = so_digitos(args[0]).lstrip('0') if args else None
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
    para_completar = []        # (nome, nota_id, faltando)
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
        faltando = itens_faltando(cur, database.buscar_fornecedor_por_cnpj(cab['FornecedorCNPJ']), esperados, nota_id, conf) \
            if len(gravados) < len(esperados) else []
        if faltando:
            cur.execute("SELECT DataEmissao FROM NotasFiscaisEntrada WHERE NotaID = ?", (nota_id,))
            emissao = str((cur.fetchone() or [''])[0] or '')[:10]
            linhas = [f"{nome} · emitida {emissao}: {len(faltando)} ITEM(NS) FICOU(ARAM) FORA DO ESTOQUE "
                      f"(XML {len(esperados)} item(ns) de compra, gravados {len(gravados)})"]
            for it, v, qtd in faltando:
                destino = (f"→ {_nome_produto(cur, v['ProdutoID'])} (x{_dec(v.get('Fator') or 1).normalize():f})" if v
                           else "→ SEM VÍNCULO (vincule antes de completar)")
                linhas.append(f"      - {it['DescricaoXML'][:45]} · {qtd.normalize():f} · R$ {qtd * _dec(it['PrecoCustoUnitario']):.2f} {destino}")
            problemas.append("\n".join(linhas))
            para_completar.append((nome, nota_id, faltando))
        elif len(gravados) > len(esperados):
            avisos.append(f"{nome}: gravados {len(gravados)} itens, o XML tem {len(esperados)} (nota lançada duas vezes juntas?)")
        total = sum(_dec(q) * _dec(p) for q, p in gravados) + _dec(fora)
        if fora is None:
            avisos.append(f"{nome}: lançada antes do controle de 'valor fora do estoque' (não dá para conferir o valor)")
        elif abs(total - cab['ValorTotalNF']) > TOLERANCIA:
            avisos.append(f"{nome}: no estoque R$ {total:.2f} x nota R$ {cab['ValorTotalNF']:.2f}")
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
    if modo_completar:
        _completar_tudo(cur, conn, para_completar)
    elif para_completar:
        print("\nPara lançar no estoque os itens que ficaram de fora (os que já têm vínculo):"
              "\n   python3 auditar_itens_xml.py --completar")
    conn.close()
    print("\nCopie tudo acima e mande para o Claude.")


def _nome_produto(cur, produto_id):
    cur.execute("SELECT NomeProduto FROM ProdutosEstoque WHERE ProdutoID = ?", (produto_id,))
    r = cur.fetchone()
    return r[0] if r else f"produto {produto_id}"


def _completar_tudo(cur, conn, para_completar):
    com_vinculo = sum(1 for _, _, f in para_completar for _, v, _ in f if v)
    sem_vinculo = sum(1 for _, _, f in para_completar for _, v, _ in f if not v)
    print(f"\n=== COMPLETAR: {com_vinculo} item(ns) podem entrar agora"
          + (f"; {sem_vinculo} ficam esperando vínculo" if sem_vinculo else "") + " ===")
    if not com_vinculo:
        print("Nada para gravar.")
        return
    print("Os itens entram NA MESMA NOTA (mesma data e custo do XML). Confira a lista acima:"
          "\nse algum item realmente NÃO chegou na loja, não confirme.")
    if input("Digite SIM para gravar: ").strip().upper() != 'SIM':
        print("Nada foi gravado.")
        return
    total = 0
    for nome, nota_id, faltando in para_completar:
        n = completar(cur, conn, nota_id, faltando)
        total += n
        if n:
            print(f"  ✓ {nome}: {n} item(ns) lançado(s)")
    print(f"Pronto: {total} item(ns) lançado(s). Rode de novo sem --completar para conferir.")


if __name__ == '__main__':
    main()

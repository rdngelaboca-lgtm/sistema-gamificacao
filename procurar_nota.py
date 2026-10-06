# ==============================================================================
# == procurar_nota.py - por que esta nota não aparece no app (aba Receber)? ====
# ==============================================================================
# Uso:  python3 procurar_nota.py 82310
#       python3 procurar_nota.py 51261012345678000199550010000823101234567890   (chave: 44 números)
#
# Mostra onde a nota está (XML baixado? só o resumo da SEFAZ? conferida? no estoque?)
# e por que ela não aparece no app. Se o XML ainda não chegou e você tiver a chave de
# acesso (44 números embaixo do código de barras do DANFE), busca direto na SEFAZ.
# Só grava o XML da nota (quando a SEFAZ entregar). Mande o resultado para o Claude.
# ==============================================================================
import os
import re
import sys
from datetime import date, datetime

import database
import nfe_distribuicao as nd
import recebimento


def so_digitos(t):
    return re.sub(r'\D', '', str(t or ''))


def numero_da_chave(chave):
    return str(int(chave[25:34])) if len(chave) == 44 else ''


def data_br(iso):
    try:
        return datetime.strptime(str(iso)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return str(iso or '?')


def xmls_baixados(numero, chave=None):
    """[(caminho, nota)] dos XMLs da pasta e de 'importadas' com esse número (ou essa chave)."""
    achados = []
    for sub in ('', 'importadas'):
        pasta = os.path.join(nd.pasta_xml(), sub)
        if not os.path.isdir(pasta):
            continue
        for f in sorted(os.listdir(pasta)):
            if not re.fullmatch(r'\d{44}\.xml', f):
                continue
            if (chave and f[:44] == chave) or (not chave and numero_da_chave(f[:44]) == numero):
                try:
                    achados.append((os.path.join(pasta, f), recebimento.ler_nota(os.path.join(pasta, f))))
                except Exception as e:
                    print(f"   (o XML {f[:12]}… não abriu: {e})")
    return achados


def notas_no_estoque(numero, chave=None):
    """[(data, fornecedor, chave_gravada)] das notas lançadas no estoque com esse número (ou essa chave)."""
    conn = database.get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""SELECT NF.NumeroNF, NF.DataEmissao, F.NomeFantasia, NF.ChaveAcesso FROM NotasFiscaisEntrada NF
                       LEFT JOIN Fornecedores F ON F.FornecedorID = NF.FornecedorID WHERE NF.NumeroNF LIKE ?""", (f"%{numero}",))
        achadas = []
        for num, data, forn, ch in cur.fetchall():
            ch = so_digitos(ch)
            if so_digitos(num).lstrip('0') == numero and (not chave or not ch or ch == chave):
                achadas.append((str(data or '')[:10], forn or '?', ch if len(ch) == 44 else None))
        return achadas
    except Exception as e:
        print(f"   (não deu para olhar o estoque: {e})")
        return []
    finally:
        conn.close()


def explicar_no_app(n):
    """Por que a nota (com XML) aparece ou não na aba Receber."""
    lista = recebimento.listar_recebimentos()
    if any(r['chave'] == n['chave'] for r in lista['pendentes']):
        return "APARECE no app em 'Para conferir'. No celular: saia da aba Receber e entre de novo (ou feche e abra o app)."
    if any(r['chave'] == n['chave'] for r in lista['conferidas']):
        return "APARECE no app em 'Conferidas nos últimos dias' (já foi conferida ou dispensada)."
    if n['finalidade'] == '4':
        return "É nota de DEVOLUÇÃO: não aparece para conferir (não é mercadoria chegando)."
    status = recebimento._status_gravados().get(n['chave'])
    if status and status['status'] != recebimento.ST_AGUARDANDO:
        em = status['em'].strftime('%d/%m/%Y') if status['em'] else '?'
        return (f"Já foi {status['status']} por {status['por'] or '?'} em {em}: sai da lista depois de "
                f"{recebimento.DIAS_CONFERIDAS} dias (ou {recebimento.DIAS_SEM_LANCAR} se ainda não entrou no estoque).")
    emissao = recebimento._como_data(n['emissao'])
    if emissao:
        dias = (date.today() - emissao).days
        if dias > recebimento.DIAS_PENDENTE:
            return (f"Foi emitida há {dias} dias. O app só mostra notas dos últimos {recebimento.DIAS_PENDENTE} dias. "
                    f"Para mostrar mais, ponha no config.py:  RECEBIMENTO_DIAS = {dias + 5}  e reinicie a API.")
    return "Não consegui ver o motivo: mande este resultado para o Claude."


def buscar_na_sefaz(chave):
    print(f"\nBuscando a nota direto na SEFAZ pela chave…")
    try:
        r = nd.buscar_por_chave(chave)
    except nd.ErroNFe as e:
        print(f"   ✗ {e}")
        return
    print(("   ✓ " if r['situacao'] in ('baixada', 'ja_temos') else "   • ") + r['mensagem'])
    if r['situacao'] == 'baixada':
        for _, n in xmls_baixados(None, chave):
            print("   " + explicar_no_app(n))


def main():
    if len(sys.argv) < 2 or not so_digitos(sys.argv[1]):
        print("Uso: python3 procurar_nota.py NUMERO_DA_NOTA   (ou a chave de acesso com 44 números)")
        return
    entrada = so_digitos(sys.argv[1])
    chave = entrada if len(entrada) == 44 else None
    numero = numero_da_chave(chave) if chave else str(int(entrada))
    print(f"\nProcurando a NF {numero}{' (chave ' + chave[:6] + '…' + chave[-4:] + ')' if chave else ''}\n")

    # 1) XML já baixado
    achados = xmls_baixados(numero, chave)
    if achados:
        for caminho, n in achados:
            pasta = "importadas (já lançada no estoque)" if os.sep + 'importadas' + os.sep in caminho else "notas da SEFAZ"
            print(f"1) XML BAIXADO: {n['fornecedor']} · emitida {data_br(n['emissao'])} · R$ {n['valor']:.2f} · pasta {pasta}")
            print("   " + explicar_no_app(n))
        return

    # 2) só o resumo (esperando o XML completo)
    estado = nd.ler_estado()
    resumos = {ch: v for ch, v in estado.get('aguardando_xml', {}).items()
               if (chave and ch == chave) or (not chave and numero_da_chave(ch) == numero)}
    if resumos:
        for ch, v in resumos.items():
            print(f"2) A SEFAZ SÓ MANDOU O RESUMO: {v.get('emitente') or '?'} · emitida {data_br(v.get('emissao'))} · "
                  f"R$ {v.get('valor') or '?'} · desde {data_br(v.get('desde'))}")
            print("   Ciência da Operação: " + ("enviada" if v.get('ciencia') else
                                                f"NÃO aceita ({v.get('erro_ciencia', 'tenta de novo a cada hora')})"))
            print("   O app só mostra a nota quando o XML completo chegar.")
            if input("   Buscar o XML agora direto na SEFAZ? (S/N) [S]: ").strip().upper() in ('', 'S', 'SIM'):
                buscar_na_sefaz(ch)
        return

    # 3) lançada no computador com um XML de outra pasta (o app não tem o XML)
    no_estoque = notas_no_estoque(numero, chave)
    if no_estoque:
        for data, forn, ch in no_estoque:
            print(f"3) A NOTA ESTÁ NO ESTOQUE: {forn} · emitida {data_br(data)} (lançada pelo computador)")
        print("   Mas o XML dela não está na pasta da SEFAZ (foi importada de outro lugar, ex.: e-mail):\n"
              "   por isso não aparece no app para conferir. Baixando o XML ela aparece em 'Para conferir'\n"
              "   (a conferência fica registrada; o estoque não muda de novo).")
        ch = next((c for _, _, c in no_estoque if c), None) or chave
        if ch:
            if input("   Baixar o XML da SEFAZ agora? (S/N) [S]: ").strip().upper() in ('', 'S', 'SIM'):
                buscar_na_sefaz(ch)
            return
        chave = so_digitos(input("   A chave não está gravada. Digite a CHAVE DE ACESSO do DANFE (44 números),\n"
                                 "   ou só ENTER para sair: "))
        if len(chave) == 44:
            buscar_na_sefaz(chave)
        elif chave:
            print("   A chave tem 44 números. Confira e rode de novo:  python3 procurar_nota.py CHAVE")
        return

    # 4) nada ainda
    print("4) A NOTA AINDA NÃO CHEGOU no servidor (nem o XML, nem o resumo da SEFAZ).")
    ultima, proxima = estado.get('ultima_busca'), estado.get('proxima_consulta')
    print(f"   Última busca do robô: {ultima.replace('T', ' ') if ultima else 'nunca'}"
          + (f" · próxima: {proxima.replace('T', ' ')}" if proxima else ""))
    print("   Motivos comuns: a SEFAZ ainda não liberou (pode levar algumas horas depois da emissão);\n"
          "   a nota foi emitida para OUTRO CNPJ (confira o destinatário no DANFE); ou é de mais de 90 dias.")
    if not chave:
        chave = so_digitos(input("\n   Se tiver o DANFE, digite a CHAVE DE ACESSO (44 números) para buscar na SEFAZ,\n"
                                 "   ou só ENTER para sair: "))
        if not chave:
            return
        if len(chave) != 44:
            print("   A chave tem 44 números. Confira e rode de novo:  python3 procurar_nota.py CHAVE")
            return
        if numero_da_chave(chave) != numero:
            print(f"   Atenção: essa chave é da NF {numero_da_chave(chave)}, não da {numero}.")
    buscar_na_sefaz(chave)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()

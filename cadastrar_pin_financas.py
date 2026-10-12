# ==============================================================================
# cadastrar_pin_financas.py - Cadastra quem pode usar o APP DE FINANÇAS da família
# ------------------------------------------------------------------------------
# Como usar (no computador da loja, com o ambiente virtual ativado):
#     python cadastrar_pin_financas.py
# Serve para: cadastrar uma pessoa (nome + PIN de 4 números), TROCAR um PIN
# esquecido, DESBLOQUEAR quem errou 5 vezes e TIRAR o acesso de alguém.
# O app de finanças NÃO usa os funcionários da loja: as pessoas daqui são só da família.
# ==============================================================================
import getpass
import sys

try:
    import financas_database as fd
except Exception as erro:
    print(f"\n[ERRO] Não consegui carregar o financas_database.py: {erro}")
    sys.exit(1)

PINS_FRACOS = {'0000', '1111', '2222', '3333', '4444', '5555', '6666', '7777', '8888', '9999',
               '1234', '4321', '0123', '1212', '2580'}


def mostrar():
    pessoas = fd.listar_usuarios(incluir_inativos=True)
    print("\n  ID   NOME                         ACESSO")
    print("  ---  ---------------------------  ----------")
    if not pessoas:
        print("  (ninguém cadastrado ainda)")
    for p in pessoas:
        print(f"  {p['id']:<4} {p['nome'][:27]:<28} {'ativo' if p['ativo'] else 'sem acesso'}")
    return {p['id']: p for p in pessoas}


def cadastrar():
    nome = input("\nNome (como vai aparecer no app, ex.: Rodrigo). Se já existe, troca o PIN: ").strip()
    if not nome:
        return
    pin = getpass.getpass(f"PIN de 4 números para {nome} (não aparece ao digitar): ").strip()
    try:
        fd.validar_formato_pin(pin)
    except fd.ErroFinancas as e:
        print(f"[!] {e}")
        return
    if pin in PINS_FRACOS:
        print("[!] Esse PIN é fácil de adivinhar. Escolha outro (evite 1234, 0000, 1111...).")
        return
    if getpass.getpass("Digite o PIN de novo: ").strip() != pin:
        print("[!] Os dois PINs não são iguais. Nada foi salvo.")
        return
    fd.definir_usuario(nome, pin)
    print(f"[OK] {nome} pode entrar no app de finanças. Se estava bloqueado, já foi liberado.")


def desativar(pessoas):
    texto = input("\nID da pessoa (ou Enter para voltar): ").strip()
    if not texto.isdigit() or int(texto) not in pessoas:
        return
    if input(f"Tirar o acesso de {pessoas[int(texto)]['nome']}? (s/n): ").strip().lower().startswith('s'):
        fd.desativar_usuario(int(texto))
        print("[OK] Acesso retirado. (Os lançamentos dela continuam no histórico.)")


def main():
    print("=" * 62)
    print("  APP DE FINANÇAS DA FAMÍLIA - CADASTRO DE PIN")
    print(f"  Banco de dados: {fd.ARQUIVO_BANCO}")
    print("=" * 62)
    try:
        fd.garantir_tabelas()
    except Exception as e:
        print(f"\n[ERRO] Não consegui abrir o banco de dados: {e}")
        sys.exit(1)
    while True:
        pessoas = mostrar()
        print("\n  1 = Cadastrar pessoa ou trocar PIN (também desbloqueia)")
        print("  2 = Tirar o acesso de alguém")
        print("  0 = Sair")
        opcao = input("\nEscolha: ").strip()
        try:
            if opcao == '1':
                cadastrar()
            elif opcao == '2':
                desativar(pessoas)
            elif opcao == '0':
                break
        except Exception as e:
            print(f"[ERRO] {e}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nSaindo.")

# ==============================================================================
# cadastrar_pin_compras.py - Cadastra o PIN de quem pode usar o APP DE COMPRAS
# ------------------------------------------------------------------------------
# Como usar (no computador da loja, com o ambiente virtual ativado):
#     python cadastrar_pin_compras.py
# O programa mostra os funcionários e pergunta:
#   - o número (ID) do funcionário
#   - o PIN de 4 números (digitado 2 vezes, não aparece na tela)
#   - se ele é GESTOR (gestor aprova listas e cria rotinas)
# Também serve para TROCAR um PIN esquecido, DESBLOQUEAR quem errou 5 vezes
# e TIRAR o acesso de quem saiu da empresa.
# ==============================================================================
import getpass
import sys

try:
    import compras_database as cd
except Exception as erro:
    print(f"\n[ERRO] Não consegui carregar o compras_database.py: {erro}")
    print("Confira se este arquivo está na mesma pasta do database.py e do config.py.")
    sys.exit(1)

PINS_FRACOS = {'0000', '1111', '2222', '3333', '4444', '5555', '6666', '7777', '8888', '9999',
               '1234', '4321', '0123', '1212', '2580'}


def mostrar_funcionarios():
    funcionarios = cd.listar_funcionarios()
    print("\n  ID   NOME                                   ACESSO AO APP")
    print("  ---  -------------------------------------  -------------------")
    for f in funcionarios:
        if f['TemPin'] and f['Ativo']:
            acesso = "GESTOR" if f['EhGestor'] else "funcionário"
        elif f['TemPin']:
            acesso = "desativado"
        else:
            acesso = "-"
        print(f"  {f['FuncionarioID']:<4} {f['Nome'][:37]:<38} {acesso}")
    return {f['FuncionarioID']: f for f in funcionarios}


def perguntar_id(funcionarios):
    texto = input("\nNúmero (ID) do funcionário (ou Enter para voltar): ").strip()
    if not texto:
        return None
    if not texto.isdigit() or int(texto) not in funcionarios:
        print("[!] ID não encontrado na lista.")
        return None
    return int(texto)


def cadastrar(funcionarios):
    fid = perguntar_id(funcionarios)
    if fid is None:
        return
    nome = funcionarios[fid]['Nome']
    pin = getpass.getpass(f"PIN de 4 números para {nome} (não aparece ao digitar): ").strip()
    try:
        cd.validar_formato_pin(pin)
    except cd.ErroCompras as e:
        print(f"[!] {e}")
        return
    if pin in PINS_FRACOS:
        print("[!] Esse PIN é fácil de adivinhar. Escolha outro (evite 1234, 0000, 1111...).")
        return
    if getpass.getpass("Digite o PIN de novo: ").strip() != pin:
        print("[!] Os dois PINs não são iguais. Nada foi salvo.")
        return
    gestor = input("Esta pessoa é GESTOR? (s/n): ").strip().lower().startswith('s')
    cd.definir_pin(fid, pin, eh_gestor=gestor)
    print(f"[OK] PIN de {nome} salvo{' como GESTOR' if gestor else ''}. Se estava bloqueado, já foi liberado.")


def desativar(funcionarios):
    fid = perguntar_id(funcionarios)
    if fid is None:
        return
    if input(f"Tirar o acesso de {funcionarios[fid]['Nome']}? (s/n): ").strip().lower().startswith('s'):
        if cd.desativar_usuario_app(fid):
            print("[OK] Acesso retirado. Se a pessoa estiver com o app aberto, ela sai no próximo toque.")
        else:
            print("[!] Essa pessoa não tinha acesso ao app.")


def main():
    print("=" * 62)
    print("  APP DE COMPRAS - CADASTRO DE PIN")
    print("=" * 62)
    try:
        cd.garantir_tabelas()
    except Exception as e:
        print(f"\n[ERRO] Não consegui acessar o banco de dados: {e}")
        print("O SQL Server está ligado? O config.py está certo?")
        sys.exit(1)
    while True:
        funcionarios = mostrar_funcionarios()
        print("\n  1 = Cadastrar ou trocar PIN (também desbloqueia)")
        print("  2 = Tirar o acesso de alguém")
        print("  0 = Sair")
        opcao = input("\nEscolha: ").strip()
        try:
            if opcao == '1':
                cadastrar(funcionarios)
            elif opcao == '2':
                desativar(funcionarios)
            elif opcao == '0':
                break
        except Exception as e:
            print(f"[ERRO] {e}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nSaindo.")

import database
import hashlib
import getpass

def gerar_hash(senha):
    """Gera um hash SHA-256 seguro para a senha fornecida."""
    return hashlib.sha256(senha.encode('utf-8')).hexdigest()

def definir_senha_funcionario(funcionario_id, nova_senha):
    """Atualiza o banco de dados com o hash da nova senha."""
    conn = database.get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            senha_hash = gerar_hash(nova_senha)
            sql = "UPDATE Funcionarios SET SenhaHash = ? WHERE FuncionarioID = ?"
            cursor.execute(sql, senha_hash, funcionario_id)
            conn.commit()
            return cursor.rowcount > 0 # Retorna True se uma linha foi afetada
        finally:
            conn.close()
    return False

if __name__ == "__main__":
    print("--- Ferramenta de Definição de Senha ---")
    
    # Lista os funcionários para facilitar
    funcionarios = database.listar_funcionarios()
    if not funcionarios:
        print("Nenhum funcionário encontrado.")
    else:
        print("Funcionários disponíveis:")
        for f in funcionarios:
            print(f"  ID: {f.FuncionarioID} - Nome: {f.NomeCompleto}")

    try:
        f_id = int(input("\nDigite o ID do funcionário para definir a senha: "))
        # getpass esconde a senha enquanto o usuário digita
        senha = getpass.getpass("Digite a nova senha (não aparecerá na tela): ")
        senha_confirm = getpass.getpass("Confirme a nova senha: ")

        if senha != senha_confirm:
            print("\nERRO: As senhas não coincidem!")
        elif not senha:
            print("\nERRO: A senha não pode ser vazia!")
        else:
            if definir_senha_funcionario(f_id, senha):
                print(f"\nSUCESSO! Senha para o funcionário ID {f_id} foi definida.")
            else:
                print(f"\nERRO: Funcionário com ID {f_id} não encontrado.")

    except ValueError:
        print("\nERRO: O ID deve ser um número.")
    except Exception as e:
        print(f"\nERRO inesperado: {e}")
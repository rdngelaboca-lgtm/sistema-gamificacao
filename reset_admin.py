import database
import hashlib
import sys

def forcar_reset_admin():
    print("--- INICIANDO RESET DE USUÁRIO ADMIN ---")
    
    conn = database.get_db_connection()
    if not conn:
        print("❌ Erro: Não foi possível conectar ao Banco de Dados.")
        return

    try:
        cursor = conn.cursor()
        
        # 1. Garante que a tabela existe (caso não tenha sido criada)
        print("1. Verificando tabela...")
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='UsuariosAdmin' AND xtype='U')
            CREATE TABLE UsuariosAdmin (
                UsuarioID INT IDENTITY(1,1) PRIMARY KEY,
                Login VARCHAR(50) UNIQUE NOT NULL,
                SenhaHash VARCHAR(64) NOT NULL,
                NomeExibicao VARCHAR(100),
                NivelAcesso INT DEFAULT 1
            )
        """)
        
        # 2. Remove o admin antigo para evitar duplicidade
        print("2. Limpando usuário admin antigo...")
        cursor.execute("DELETE FROM UsuariosAdmin WHERE Login = 'admin'")
        
        # 3. Cria o novo admin
        print("3. Criando novo admin...")
        # Senha: admin123
        senha_plana = "admin123"
        senha_hash = hashlib.sha256(senha_plana.encode()).hexdigest()
        
        cursor.execute("""
            INSERT INTO UsuariosAdmin (Login, SenhaHash, NomeExibicao, NivelAcesso)
            VALUES (?, ?, ?, ?)
        """, ('admin', senha_hash, 'Administrador Master', 1))
        
        conn.commit()
        print("\n✅ SUCESSO! Usuário recriado.")
        print(f"👤 Usuário: admin")
        print(f"🔑 Senha: {senha_plana}")
        
    except Exception as e:
        print(f"❌ ERRO: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    forcar_reset_admin()

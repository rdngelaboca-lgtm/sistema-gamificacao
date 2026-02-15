# Arquivo: migrate_onboarding_schema.py
import database
import logging

# Configuração de Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================================================================
# 1. FUNÇÃO PARA FORÇAR A CRIAÇÃO DA TABELA ONBOARDINGSTATUS
# ===================================================================
def _force_create_onboarding_table(conn):
    """FORÇA A CRIAÇÃO da tabela OnboardingStatus se ela não existir."""
    try:
        cursor = conn.cursor()
        # Comando SQL que cria a tabela base
        sql = """
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'OnboardingStatus')
            CREATE TABLE OnboardingStatus (
                FuncionarioID INT PRIMARY KEY REFERENCES Funcionarios(FuncionarioID),
                StatusWorkflow VARCHAR(50) NOT NULL DEFAULT 'Pendente',
                UltimaEtapa VARCHAR(100),
                Escolaridade VARCHAR(50),
                EstadoCivil VARCHAR(50),
                QtdFilhos INT DEFAULT 0,
                DadosFilhos NVARCHAR(MAX), -- 🛑 CORRIGIDO: De JSON para NVARCHAR(MAX)
                RG_FileID VARCHAR(255),
                CPF_FileID VARCHAR(255),
                CTPS_FileID VARCHAR(255),
                TituloEleitor_FileID VARCHAR(255)
            )
        """
        cursor.execute(sql)
        conn.commit()
        logging.info("OnboardingStatus: Tabela base verificada/criada com sucesso.")
        return True
    except Exception as e:
        logging.error(f"ERRO ao forçar a criação de OnboardingStatus: {e}")
        return False


def execute_final_schema_migration():
    """
    Executa todos os comandos ALTER TABLE para sincronizar o schema com a aplicação.
    """
    conn = database.get_db_connection()
    if not conn:
        logger.error("FALHA CRÍTICA: Não foi possível conectar ao banco de dados.")
        return

    try:
        # ⚠️ PASSO CRÍTICO: Garante que a tabela OnboardingStatus exista
        if not _force_create_onboarding_table(conn):
             logger.error("MIGRAÇÃO CANCELADA: Não foi possível criar a tabela OnboardingStatus base.")
             return

        cursor = conn.cursor()
        
        # --- FUNÇÃO AUXILIAR PARA CHECAR/CRIAR COLUNA ---
        def check_and_add_column(table, column, definition):
            try:
                # Tenta selecionar a coluna (se falhar, a coluna não existe)
                cursor.execute(f"SELECT {column} FROM {table} WHERE 1=0")
                logger.info(f"Coluna {table}.{column} já existe. Pulando.")
                return True
            except Exception:
                logger.warning(f"Coluna {table}.{column} não encontrada. Adicionando...")
                sql = f"ALTER TABLE {table} ADD {column} {definition}"
                cursor.execute(sql)
                conn.commit()
                logger.info(f"SUCESSO: Coluna {table}.{column} adicionada.")
                return False

        # =============================================================
        # 1. MIGRAÇÃO DA TABELA PRINCIPAL (Funcionarios)
        # =============================================================
        
        check_and_add_column('Funcionarios', 'NivelAcesso', "VARCHAR(50) NULL DEFAULT 'Funcionario'")
        check_and_add_column('Funcionarios', 'VerificadorCPF', "VARCHAR(3) NULL")
        check_and_add_column('Funcionarios', 'Setor', "VARCHAR(50) NULL")

        # =============================================================
        # 2. MIGRAÇÃO DA TABELA ONBOARDINGSTATUS (Campos de Casamento/Admissional)
        # =============================================================
        
        # Campos de Casamento (dados cadastrais)
        check_and_add_column('OnboardingStatus', 'DataCasamento', "VARCHAR(10) NULL") # Usamos VARCHAR(10) para salvar no formato dd/mm/aaaa
        check_and_add_column('OnboardingStatus', 'NomeConjugue', "VARCHAR(100) NULL")
        check_and_add_column('OnboardingStatus', 'CPFConjugue', "VARCHAR(14) NULL")
        
        # Colunas de Admissional (Controle de Bloqueio Final)
        check_and_add_column('OnboardingStatus', 'DataAdmissional', "DATETIME NULL")
        check_and_add_column('OnboardingStatus', 'StatusAdmissional', "VARCHAR(50) NOT NULL DEFAULT 'Pendente'")


        logger.info("MIGRAÇÃO DE SCHEMA CONCLUÍDA COM SUCESSO.")
        
    except Exception as e:
        logger.error(f"ERRO CRÍTICO ao executar a migração de schema: {e}", exc_info=True)
        
    finally:
        conn.close()

if __name__ == '__main__':
    execute_final_schema_migration()

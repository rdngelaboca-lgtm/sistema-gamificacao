# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING ===================================
# ==============================================================================
import logging
import logging.handlers
import sys
import os # Necessário para criar a pasta de logs

# --- Configurações ---
LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs' # Nome da pasta onde os logs serão salvos
LOG_LEVEL = logging.INFO # Nível mínimo para registrar (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024 # Tamanho máximo de cada arquivo de log (10 MB)
LOG_BACKUP_COUNT = 5 # Quantos arquivos de log antigos manter

# --- Cria a pasta de logs se não existir ---
log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        print(f"Pasta de logs criada em: {log_dir}") # Print inicial para confirmar criação
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        # Se não conseguir criar a pasta, tenta logar no diretório atual
        log_dir = os.path.dirname(__file__)

log_filepath = os.path.join(log_dir, LOG_FILENAME)

# --- Configuração do Handler de Arquivo Rotativo ---
# Rotaciona o log quando atinge LOG_MAX_BYTES, mantendo LOG_BACKUP_COUNT arquivos antigos
file_handler = logging.handlers.RotatingFileHandler(
    log_filepath, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
)
file_handler.setLevel(LOG_LEVEL)
file_formatter = logging.Formatter(LOG_FORMAT)
file_handler.setFormatter(file_formatter)

# --- Configuração do Handler do Console ---
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL) # Pode ser diferente do arquivo se quiser (ex: logging.DEBUG)
console_formatter = logging.Formatter(LOG_FORMAT)
console_handler.setFormatter(console_formatter)

# --- Configuração do Logger Raiz ---
# Limpa handlers existentes para evitar duplicação em recargas
logging.getLogger('').handlers = []
# Adiciona os novos handlers
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[file_handler, console_handler])

# Obtém um logger específico para este módulo
logger = logging.getLogger(__name__)

logger.info(f"*** Logging configurado para o módulo: {__name__} ***")
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================


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
    logger.info("--- Ferramenta de Definição de Senha ---")
    
    # Lista os funcionários para facilitar
    funcionarios = database.listar_funcionarios()
    if not funcionarios:
        logger.info("Nenhum funcionário encontrado.")
    else:
        logger.info("Funcionários disponíveis:")
        for f in funcionarios:
            logger.info(f"  ID: {f.FuncionarioID} - Nome: {f.NomeCompleto}")

    try:
        f_id = int(input("\nDigite o ID do funcionário para definir a senha: "))
        # getpass esconde a senha enquanto o usuário digita
        senha = getpass.getpass("Digite a nova senha (não aparecerá na tela): ")
        senha_confirm = getpass.getpass("Confirme a nova senha: ")

        if senha != senha_confirm:
            logger.error("\nERRO: As senhas não coincidem!")
        elif not senha:
            logger.error("\nERRO: A senha não pode ser vazia!")
        else:
            if definir_senha_funcionario(f_id, senha):
                logger.info(f"\nSUCESSO! Senha para o funcionário ID {f_id} foi definida.")
            else:
                logger.error(f"\nERRO: Funcionário com ID {f_id} não encontrado.")

    except ValueError:
        logger.exception("\nERRO: O ID deve ser um número.")
    except Exception as e:
        logger.exception(f"\nERRO inesperado: {e}")

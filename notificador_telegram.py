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




# notificador_telegram.py
import requests
import json 
import config
import os

def enviar_mensagem(chat_id, texto):
    """
    Envia uma mensagem de texto para um chat_id específico via API do Telegram.
    """
    token = config.TELEGRAM_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': texto,
        'parse_mode': 'HTML'
    }
    
    try:
        response = requests.post(url, data=payload)
        logger.info(f"Notificação enviada para chat_id {chat_id}. Resposta API: {response.json()}")
        return response.json()
    except Exception as e:
        logger.error(f"Erro ao enviar notificação para chat_id {chat_id}: {e}", exc_info=True) 
        return None
    
def enviar_mensagem_com_botao(chat_id, texto, reply_markup_obj):
    """Envia uma mensagem com um teclado inline (botões)."""
    token = config.TELEGRAM_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # A biblioteca requests é inteligente o suficiente para converter o objeto
    # para JSON, então não precisamos fazer isso manualmente.
    payload = {
        'chat_id': chat_id,
        'text': texto,
        'parse_mode': 'Markdown', # Alterado para Markdown para suportar os asteriscos
        'reply_markup': reply_markup_obj.to_dict()
    }
    try:
        response = requests.post(url, json=payload) # Usando json=payload que é mais robusto
        logger.info(f"Mensagem com botão enviada para {chat_id}. Resposta: {response.json()}")
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem com botão para {chat_id}: {e}")

def enviar_foto_com_botoes(chat_id, foto, legenda, reply_markup_obj=None): # Tornamos reply_markup_obj opcional
    """
    (VERSÃO MELHORADA)
    Envia uma foto com legenda e, opcionalmente, botões.
    RETORNA a resposta da API.
    """
    token = config.TELEGRAM_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    payload = {
        'chat_id': chat_id,
        'caption': legenda,
        'parse_mode': 'Markdown',
    }
    
    # Adiciona os botões ao payload apenas se eles forem fornecidos
    if reply_markup_obj:
        payload['reply_markup'] = json.dumps(reply_markup_obj.to_dict())
    
    try:
        if os.path.exists(str(foto)):
            with open(foto, 'rb') as f:
                files = {'photo': f}
                response = requests.post(url, data=payload, files=files)
        else:
            # Se a 'foto' não é um caminho de arquivo, asumimos que é um file_id
            payload['photo'] = foto
            response = requests.post(url, data=payload)
        
        resposta_json = response.json()
        if not resposta_json.get('ok'):
            logger.error(f"!!! ERRO DA API DO TELEGRAM: {resposta_json}")
        else:
            logger.info(f"Foto enviada para {chat_id}.")
        
        return resposta_json

    except Exception as e:
        logger.error(f"Erro ao enviar foto para {chat_id}: {e}")
        return None
    

def enviar_documento(chat_id, path_documento, legenda):
    """ Envia um documento (como PDF) para um chat específico. """
    token = config.TELEGRAM_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendDocument"

    payload = {
        'chat_id': chat_id,
        'caption': legenda
    }

    try:
        with open(path_documento, 'rb') as doc:
            files = {'document': doc}
            response = requests.post(url, data=payload, files=files)

        logger.info(f"Documento enviado para {chat_id}. Resposta: {response.json()}")
        return response.json()
    except Exception as e:
        print(f"Erro ao enviar documento para {chat_id}: {e}")
        return None
    
# Em notificador_telegram.py, adicione esta nova função ao final do arquivo:
import json # Garanta que o 'import json' está no topo do arquivo!

def enviar_documento_com_botoes(chat_id, path_documento, legenda, reply_markup_obj):
    """Envia um documento (PDF) com legenda e um teclado inline (botões)."""
    token = config.TELEGRAM_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendDocument"

    # Convertemos o dicionário de botões para uma string no formato JSON
    reply_markup_em_json = json.dumps(reply_markup_obj.to_dict())

    payload = {
        'chat_id': chat_id,
        'caption': legenda,
        'parse_mode': 'Markdown',
        'reply_markup': reply_markup_em_json
    }
    
    try:
        # Abrimos o arquivo em modo de leitura binária ('rb')
        with open(path_documento, 'rb') as doc:
            # O 'files' diz à requisição para enviar este arquivo
            files = {'document': doc}
            response = requests.post(url, data=payload, files=files)
        
        if not response.json().get('ok'):
            logger.error(f"!!! ERRO DA API DO TELEGRAM (sendDocument): {response.json()}")
        else:
            logger.info(f"Documento com botão enviado para {chat_id}. Resposta: {response.json()}")

    except Exception as e:
        logger.error(f"Erro ao enviar documento com botão para {chat_id}: {e}")

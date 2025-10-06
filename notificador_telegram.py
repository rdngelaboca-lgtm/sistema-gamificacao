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
        print(f"Notificação enviada para {chat_id}. Resposta: {response.json()}")
        return response.json()
    except Exception as e:
        print(f"Erro ao enviar notificação para {chat_id}: {e}")
        return None
    
# NO ARQUIVO notificador_telegram.py, ADICIONE ESTA NOVA FUNÇÃO:

# NO ARQUIVO notificador_telegram.py, SUBSTITUA A FUNÇÃO ANTIGA POR ESTA:
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
        print(f"Mensagem com botão enviada para {chat_id}. Resposta: {response.json()}")
    except Exception as e:
        print(f"Erro ao enviar mensagem com botão para {chat_id}: {e}")

# Em notificador_telegram.py, ADICIONE esta função no final:
# Em notificador_telegram.py, SUBSTITUA a função antiga por esta versão corrigida:

# Em notificador_telegram.py, SUBSTITUA a função antiga por esta

# Em notificador_telegram.py, SUBSTITUA a função antiga por esta
def enviar_foto_com_botoes(chat_id, foto, legenda, reply_markup_obj):
    """
    Envia uma foto com legenda e botões.
    O parâmetro 'foto' pode ser um caminho de arquivo local (path) ou uma file_id do Telegram.
    """
    token = config.TELEGRAM_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    reply_markup_em_json = json.dumps(reply_markup_obj.to_dict())

    payload = {
        'chat_id': chat_id,
        'caption': legenda,
        'parse_mode': 'Markdown',
        'reply_markup': reply_markup_em_json
    }
    
    try:
        # Se 'foto' for um caminho de arquivo que existe no PC...
        if os.path.exists(str(foto)):
            with open(foto, 'rb') as f:
                files = {'photo': f}
                # Enviamos como um arquivo multipart
                response = requests.post(url, data=payload, files=files)
        # Se não, assumimos que é uma file_id...
        else:
            payload['photo'] = foto
            # Enviamos como dados normais
            response = requests.post(url, data=payload)
        
        if not response.json().get('ok'):
            print(f"!!! ERRO DA API DO TELEGRAM: {response.json()}")
        else:
            print(f"Foto com botão enviada para {chat_id}.")

    except Exception as e:
        print(f"Erro ao enviar foto com botão para {chat_id}: {e}")

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

        print(f"Documento enviado para {chat_id}. Resposta: {response.json()}")
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
            print(f"!!! ERRO DA API DO TELEGRAM (sendDocument): {response.json()}")
        else:
            print(f"Documento com botão enviado para {chat_id}. Resposta: {response.json()}")

    except Exception as e:
        print(f"Erro ao enviar documento com botão para {chat_id}: {e}")
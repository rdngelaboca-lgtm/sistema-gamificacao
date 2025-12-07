import requests
import logging
import config
import re

# Configuração de Log local
logger = logging.getLogger(__name__)

def enviar_mensagem_whatsapp(numero, texto):
    """
    Envia uma mensagem de texto via Z-API.
    VERSÃO DEBUG: Token fixado manualmente para garantir autenticação.
    """
    # 1. Limpeza do número
    numero_limpo = re.sub(r'\D', '', str(numero))

    # Garante o código do país (Brasil 55) se não tiver
    if len(numero_limpo) <= 11:
        numero_limpo = '55' + numero_limpo

    # 2. Monta o Payload
    payload = {
        "phone": numero_limpo,
        "message": texto
    }

    # --- CORREÇÃO DEFINITIVA ---
    # Fixamos o token aqui para eliminar erro de importação do config.py
    TOKEN_FIXO = "2E1C0A469DC7263738C0F096"
    
    headers = {
        "Content-Type": "application/json",
        "Client-Token": TOKEN_FIXO
    }

    # Log de Debug para confirmar o que está sendo enviado
    logger.info(f"Disparando WPP para {numero_limpo}. Headers: {headers}")

    try:
        # Usa a URL do config, mas garante os headers de segurança
        response = requests.post(
            config.WPP_API_URL, 
            json=payload, 
            headers=headers, 
            timeout=15
        )

        if response.status_code == 200:
            logger.info("WhatsApp enviado com sucesso (Z-API).")
            return True, "Mensagem enviada!"
        else:
            erro_msg = f"Erro Z-API: {response.status_code} - {response.text}"
            logger.error(erro_msg)
            return False, f"Falha no envio: {response.text}"

    except Exception as e:
        erro_critico = f"Erro de conexão: {str(e)}"
        logger.error(erro_critico)
        return False, erro_critico

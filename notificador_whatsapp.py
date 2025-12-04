import requests
import logging
import config
import re

# Configuração de Log local
logger = logging.getLogger(__name__)

def enviar_mensagem_whatsapp(numero, texto):
    """
    Envia uma mensagem de texto via Z-API (Versão Limpa).
    Retorna (True, msg) se sucesso, ou (False, erro) se falha.
    """
    # Validação básica da URL
    if not config.WPP_API_URL:
        return False, "URL da API não configurada no config.py"

    # 1. Limpeza do número
    # A Z-API exige o formato: 5544999998888 (DDI + DDD + Numero)
    numero_limpo = re.sub(r'\D', '', str(numero))

    # Garante o código do país (Brasil 55) se não tiver
    if len(numero_limpo) <= 11:
        numero_limpo = '55' + numero_limpo

    # 2. Monta o Payload específico da Z-API
    payload = {
        "phone": numero_limpo,
        "message": texto
    }

    # --- CORREÇÃO FINAL: Apenas Content-Type, sem tokens de segurança extras ---
    headers = {
        "Content-Type": "application/json"
    }

    try:
        logger.info(f"Tentando enviar WhatsApp via Z-API para {numero_limpo}...")

        response = requests.post(
            config.WPP_API_URL, 
            json=payload, 
            headers=headers, 
            timeout=15
        )

        # Z-API geralmente retorna 200 OK
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

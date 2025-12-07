import requests
import logging
import config
import re

# Configuração de Log local
logger = logging.getLogger(__name__)

def enviar_mensagem_whatsapp(numero, texto):
    """
    Envia uma mensagem de texto via Z-API.
    VERSÃO SEGURA: Com Client-Token ativado.
    """
    # 1. Validação básica da URL
    if not config.WPP_API_URL:
        return False, "URL da API não configurada no config.py"

    # 2. Limpeza do número
    numero_limpo = re.sub(r'\D', '', str(numero))
    
    # Se o número for curto (ex: 4499998888), adiciona 55. 
    if len(numero_limpo) <= 11:
        numero_limpo = '55' + numero_limpo

    # 3. Payload da mensagem
    payload = {
        "phone": numero_limpo,
        "message": texto
    }

    # ==============================================================================
    # 🔒 CONFIGURAÇÃO DE SEGURANÇA (CLIENT TOKEN) 🔒
    # Este token foi gerado na aba "Segurança" do painel Z-API.
    # ==============================================================================
    
    CLIENT_TOKEN_SECRETO = "F7880a7b372194b21b5ca96fb4360cde1S" 
    
    # Cabeçalhos obrigatórios para autenticação segura
    headers = {
        "Content-Type": "application/json",
        "Client-Token": CLIENT_TOKEN_SECRETO
    }

    logger.info(f"Disparando WPP para {numero_limpo} via Z-API Segura...")

    try:
        # A URL usa o Instance Token (config.py) e o Header usa o Client Token.
        response = requests.post(
            config.WPP_API_URL, 
            json=payload, 
            headers=headers, 
            timeout=20
        )

        if response.status_code == 200:
            logger.info("✅ Sucesso Z-API: Mensagem enviada!")
            return True, "Mensagem enviada!"
        else:
            erro_msg = f"❌ Erro Z-API ({response.status_code}): {response.text}"
            logger.error(erro_msg)
            return False, f"Z-API recusou: {response.text}"

    except Exception as e:
        erro_critico = f"Erro de conexão: {str(e)}"
        logger.error(erro_critico)
        return False, erro_critico

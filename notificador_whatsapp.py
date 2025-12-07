import requests
import logging
import config
import re

# Configuração de Log local
logger = logging.getLogger(__name__)

def enviar_mensagem_whatsapp(numero, texto):
    """
    Envia uma mensagem de texto via Z-API.
    VERSÃO DEBUG LIMPA: Deixa o 'requests' gerenciar os cabeçalhos.
    """
    # 1. Validação básica
    if not config.WPP_API_URL:
        return False, "URL da API não configurada no config.py"

    # 2. Limpeza do número
    numero_limpo = re.sub(r'\D', '', str(numero))
    
    # Se o número for curto (ex: 4499998888), adiciona 55. 
    # Se for longo (ex: 554499998888), mantém.
    if len(numero_limpo) <= 11:
        numero_limpo = '55' + numero_limpo

    # 3. Payload
    payload = {
        "phone": numero_limpo,
        "message": texto
    }

    # --- DEBUG: Mostra exatamente o que será enviado ---
    # (Isso aparecerá no seu terminal quando você clicar em enviar)
    logger.info(f"--- INICIANDO ENVIO Z-API ---")
    logger.info(f"URL: {config.WPP_API_URL}")
    logger.info(f"Telefone Processado: {numero_limpo}")
    # Não definimos headers manualmente. O requests fará isso.

    try:
        # Usamos json=payload. O requests cria o Content-Type automaticamente.
        # Removemos qualquer parâmetro 'headers=' para garantir pureza.
        response = requests.post(
            config.WPP_API_URL, 
            json=payload, 
            timeout=20
        )

        # Loga a resposta completa para análise em caso de erro
        if response.status_code == 200:
            logger.info("✅ Sucesso Z-API: Mensagem enviada!")
            return True, "Mensagem enviada!"
        else:
            erro_msg = f"❌ Erro Z-API ({response.status_code}): {response.text}"
            logger.error(erro_msg)
            # Retorna o erro detalhado para o pop-up
            return False, f"Z-API recusou: {response.text}"

    except Exception as e:
        erro_critico = f"Erro de conexão: {str(e)}"
        logger.error(erro_critico)
        return False, erro_critico

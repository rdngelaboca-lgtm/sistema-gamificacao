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
    # Token movido para config.py para segurança.
    # ==============================================================================

    # Cabeçalhos obrigatórios para autenticação segura
    headers = {
        "Content-Type": "application/json",
        "Client-Token": config.ZAPI_CLIENT_TOKEN
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


# ==============================================================================
# [WHATSAPP GRUPO] Avisos da gestão num GRUPO do WhatsApp (Z-API)
# ==============================================================================
# O número da Z-API precisa estar DENTRO do grupo. O "phone" de um grupo é o ID dele
# (ex.: 120363019502650977-group), que a Z-API devolve na lista de grupos. Os avisos são
# escritos para o Telegram (HTML: <b>, <i>…): aqui viram a formatação do WhatsApp (*, _).
# Os tokens ficam no config.py e nunca vão para o log.
import html as _html

TAMANHO_MAXIMO_WPP = 4000


class ErroWhatsApp(Exception):
    pass


def _base_url():
    """https://api.z-api.io/instances/<id>/token/<token> (sem o /send-text)."""
    url = getattr(config, 'WPP_API_URL', '') or ''
    if '/send-text' in url:
        return url.split('/send-text')[0].rstrip('/')
    inst, tok = getattr(config, 'ZAPI_INSTANCE_ID', None), getattr(config, 'ZAPI_TOKEN', None)
    if inst and tok:
        return f"https://api.z-api.io/instances/{inst}/token/{tok}"
    return None


def _cabecalhos():
    h = {"Content-Type": "application/json"}
    if getattr(config, 'ZAPI_CLIENT_TOKEN', None):
        h["Client-Token"] = config.ZAPI_CLIENT_TOKEN
    return h


def html_para_whatsapp(texto):
    """'<b>R$ 8.000</b> <i>obs</i> &amp;' -> '*R$ 8.000* _obs_ &' (o que sobrar de tag some)."""
    t = str(texto or '')

    def marca(simbolo):
        def troca(m):
            dentro = m.group(1)
            if not dentro.strip():
                return dentro
            esq, dir_ = dentro[:len(dentro) - len(dentro.lstrip())], dentro[len(dentro.rstrip()):]
            return f"{esq}{simbolo}{dentro.strip()}{simbolo}{dir_}"
        return troca
    t = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>',
               lambda m: m.group(2) if m.group(1) in m.group(2) else f"{m.group(2)} ({m.group(1)})", t, flags=re.S | re.I)
    t = re.sub(r'<(?:b|strong)>(.*?)</(?:b|strong)>', marca('*'), t, flags=re.S | re.I)
    t = re.sub(r'<(?:i|em)>(.*?)</(?:i|em)>', marca('_'), t, flags=re.S | re.I)
    t = re.sub(r'<(?:code|pre)>(.*?)</(?:code|pre)>', lambda m: f"```{m.group(1)}```", t, flags=re.S | re.I)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'</?[a-zA-Z][^>]*>', '', t)
    return _html.unescape(t)


def _partes(texto):
    partes, atual = [], ""
    for linha in str(texto).split("\n"):
        if len(atual) + len(linha) + 1 > TAMANHO_MAXIMO_WPP and atual:
            partes.append(atual.rstrip("\n"))
            atual = ""
        atual += linha + "\n"
    if atual.strip():
        partes.append(atual.rstrip("\n"))
    return partes


def enviar_para_grupo(grupo_id, texto, http=None):
    """Manda o texto (já no formato do WhatsApp) para o grupo. Devolve (ok, mensagem)."""
    base = _base_url()
    if not base:
        return False, "Z-API não configurada no config.py"
    if not grupo_id:
        return False, "Nenhum grupo escolhido"
    http = http or requests.post
    for parte in _partes(texto):
        try:
            r = http(f"{base}/send-text", json={"phone": str(grupo_id), "message": parte}, headers=_cabecalhos(), timeout=20)
        except Exception as e:
            logger.error(f"WhatsApp (grupo): sem conexão com a Z-API: {e}")
            return False, f"sem conexão com a Z-API ({e.__class__.__name__})"
        if r.status_code != 200:
            logger.error(f"WhatsApp (grupo): Z-API recusou ({r.status_code}): {r.text[:300]}")
            return False, f"a Z-API recusou ({r.status_code}): {r.text[:200]}"
    logger.info(f"WhatsApp (grupo): aviso enviado ({len(texto)} letras).")
    return True, "enviado"


def enviar_documento_para_grupo(grupo_id, caminho, nome_arquivo, legenda='', http=None):
    """
    [DANFE] Manda um arquivo (PDF) para o grupo pela Z-API (send-document, com o arquivo em base64).
    Devolve (ok, mensagem).
    """
    import base64
    import os
    base = _base_url()
    if not base:
        return False, "Z-API não configurada no config.py"
    if not grupo_id:
        return False, "Nenhum grupo escolhido"
    extensao = os.path.splitext(caminho)[1].lstrip('.').lower() or 'pdf'
    try:
        with open(caminho, 'rb') as f:
            conteudo = base64.b64encode(f.read()).decode('ascii')
    except OSError as e:
        return False, f"arquivo não encontrado ({e})"
    corpo = {"phone": str(grupo_id), "document": f"data:application/{extensao};base64,{conteudo}",
             "fileName": os.path.splitext(nome_arquivo)[0]}
    if legenda:
        corpo["caption"] = legenda[:1000]
    http = http or requests.post
    try:
        r = http(f"{base}/send-document/{extensao}", json=corpo, headers=_cabecalhos(), timeout=60)
    except Exception as e:
        logger.error(f"WhatsApp (grupo): sem conexão com a Z-API para mandar o arquivo: {e}")
        return False, f"sem conexão com a Z-API ({e.__class__.__name__})"
    if r.status_code != 200:
        logger.error(f"WhatsApp (grupo): Z-API recusou o arquivo ({r.status_code}): {r.text[:300]}")
        return False, f"a Z-API recusou o arquivo ({r.status_code}): {r.text[:200]}"
    logger.info(f"WhatsApp (grupo): arquivo enviado ({nome_arquivo}).")
    return True, "enviado"


def listar_grupos(http=None):
    """[{'id', 'nome'}] dos grupos em que o número da Z-API está (os mais recentes primeiro)."""
    base = _base_url()
    if not base:
        raise ErroWhatsApp("A Z-API não está configurada no config.py.")
    http = http or requests.get
    ultimo_erro = None
    for caminho in ('/groups', '/chats'):
        try:
            r = http(f"{base}{caminho}", params={'page': 1, 'pageSize': 200}, headers=_cabecalhos(), timeout=20)
        except Exception as e:
            raise ErroWhatsApp(f"Sem conexão com a Z-API ({e.__class__.__name__}).")
        if r.status_code != 200:
            ultimo_erro = f"a Z-API recusou ({r.status_code}): {r.text[:200]}"
            continue
        try:
            dados = r.json()
        except ValueError:
            ultimo_erro = "resposta inválida da Z-API"
            continue
        if isinstance(dados, dict):
            dados = dados.get('data') or dados.get('groups') or dados.get('chats') or []
        grupos = []
        for g in dados if isinstance(dados, list) else []:
            gid = str(g.get('phone') or g.get('id') or '')
            eh_grupo = g.get('isGroup') or gid.endswith('-group') or '-' in gid
            if gid and eh_grupo:
                grupos.append({'id': gid, 'nome': g.get('name') or g.get('subject') or gid})
        if grupos or caminho == '/chats':
            return grupos
    raise ErroWhatsApp(f"Não consegui listar os grupos: {ultimo_erro}")

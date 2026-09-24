# ==============================================================================
# == notificador_telegram.py  -  Envio de mensagens/fotos/documentos ao Telegram
# ==============================================================================
# Usado por: telegram_bot.py, main.py, escala_loja_main.py, api_server.py,
#            database.py, agendador.py e agendador_lembretes.py.
#
# Versão DEPURADA. Procure por [DEPURAÇÃO] para ver cada correção.
# Todas as funções continuam com o MESMO nome e os MESMOS parâmetros de antes
# (os outros arquivos não precisam mudar nada).
#
# Todas devolvem a resposta do Telegram (um dicionário). Para saber se deu certo:
#     resposta = enviar_mensagem(chat_id, "Olá")
#     if resposta and resposta.get('ok'): ...
#
# TESTE RÁPIDO (no terminal, com o ambiente virtual ativado):
#     python notificador_telegram.py SEU_CHAT_ID
# ==============================================================================

# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING ===================================
# ==============================================================================
import logging
import logging.handlers
import sys
import os

LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs'
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# [DEPURAÇÃO] Antes este arquivo APAGAVA a configuração de log de quem o importava
# (logging.getLogger('').handlers = []) e abria mais uma cópia do arquivo de log.
# Como ele é importado por quase todo o sistema, isso duplicava arquivos abertos
# (no Windows a troca do log ao chegar em 10 MB falhava com "arquivo em uso").
# Agora só configura o log se ninguém tiver configurado antes.
if not logging.getLogger().handlers:
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_FOLDER)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        log_dir = os.path.dirname(os.path.abspath(__file__))
    _file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, LOG_FILENAME), maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    _console_handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[_file_handler, _console_handler])

logger = logging.getLogger(__name__)
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================

import html
import json
import re
import time

import requests

import config

# ------------------------------------------------------------------------------
# Limites do Telegram (documentação oficial da Bot API)
# ------------------------------------------------------------------------------
LIMITE_TEXTO = 4096      # caracteres por mensagem
LIMITE_LEGENDA = 1024    # caracteres na legenda de foto/documento
MARGEM = 96              # folga (o bot às vezes acrescenta o "recibo de ciência" na mensagem)

TIMEOUT_TEXTO = 20       # segundos para mensagens de texto
TIMEOUT_ARQUIVO = 90     # segundos para enviar fotos/documentos
ESPERA_MAXIMA_429 = 10   # espera no máximo 10 s quando o Telegram pede "calma" (erro 429)

TAGS_HTML_TELEGRAM = r'(b|strong|i|em|u|ins|s|strike|del|code|pre|a|span|tg-spoiler|blockquote)'
_RE_TEM_HTML = re.compile(r'</?' + TAGS_HTML_TELEGRAM + r'(\s[^>]*)?>', re.IGNORECASE)
_EXTENSOES_ARQUIVO = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.pdf', '.txt', '.csv', '.xlsx', '.docx', '.zip')


# ==============================================================================
# == FUNÇÕES INTERNAS (ajudantes) ==============================================
# ==============================================================================
def _token():
    return str(getattr(config, 'TELEGRAM_TOKEN', '') or '').strip()


def _sem_token(texto):
    """
    [DEPURAÇÃO] Os erros de rede do 'requests' mostram o endereço completo, que tem
    o TOKEN do bot. Antes ele ia parar no arquivo de log. Agora é trocado por ***.
    """
    token = _token()
    texto = str(texto)
    return texto.replace(token, '***TOKEN***') if token else texto


def _falha(descricao):
    """Resposta padrão de erro (mesmo formato que o Telegram usa)."""
    return {'ok': False, 'description': descricao}


def _markdown_para_html(texto):
    """
    Converte o "Markdown" usado no projeto (**negrito**, *negrito*, `código`) em HTML,
    protegendo os caracteres < > & do texto.
    [DEPURAÇÃO] O modo Markdown do Telegram RECUSA a mensagem inteira se o texto tiver
    um "_" ou "*" sozinho (ex: e-mail rh_loja@..., nome de tarefa "Limpar_freezer").
    Em HTML isso não acontece.
    """
    t = html.escape(str(texto), quote=False)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t, flags=re.S)
    t = re.sub(r'(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])', r'<b>\1</b>', t)
    t = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', t)
    return t


def _preparar_texto(texto, parse_mode):
    """
    Decide o formato final e devolve (texto, parse_mode).
      parse_mode=None (automático): se o texto já tem tags HTML (<b>, <i>...), usa HTML;
                                    se não tem, converte o Markdown do projeto para HTML.
      'Markdown': o texto está escrito em Markdown -> convertido para HTML (mais seguro).
      'HTML' ou 'MarkdownV2': usados como estão.
      '' (vazio): texto puro, sem formatação.
    """
    texto = '' if texto is None else str(texto)
    if parse_mode == '':
        return texto, None
    if parse_mode in ('HTML', 'MarkdownV2'):
        if parse_mode == 'HTML':
            # "**negrito**" misturado com HTML também vira negrito (antes aparecia com asteriscos)
            texto = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', texto, flags=re.S)
        return texto, parse_mode
    if parse_mode is None and _RE_TEM_HTML.search(texto):
        return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', texto, flags=re.S), 'HTML'
    return _markdown_para_html(texto), 'HTML'


def _html_para_texto_puro(texto):
    """Tira as tags HTML (usado quando o Telegram não consegue ler a formatação)."""
    return html.unescape(re.sub(r'<[^>]+>', '', str(texto)))


def _dividir_texto(texto, limite):
    """[DEPURAÇÃO] Mensagens acima de 4096 letras eram RECUSADAS inteiras. Agora são divididas."""
    partes = []
    while len(texto) > limite:
        corte = texto.rfind('\n', 0, limite)
        if corte < limite // 2:
            corte = texto.rfind(' ', 0, limite)
        if corte < limite // 2:
            corte = limite
        partes.append(texto[:corte].rstrip())
        texto = texto[corte:].lstrip('\n ')
    if texto.strip() or not partes:
        partes.append(texto)
    return partes


def _markup_para_json(reply_markup_obj):
    """Aceita o teclado do python-telegram-bot, um dicionário ou um texto JSON."""
    if reply_markup_obj is None:
        return None
    if isinstance(reply_markup_obj, str):
        return reply_markup_obj
    if isinstance(reply_markup_obj, dict):
        return json.dumps(reply_markup_obj)
    return json.dumps(reply_markup_obj.to_dict())


def _eh_erro_de_formatacao(resposta):
    desc = str((resposta or {}).get('description', '')).lower()
    return (resposta or {}).get('error_code') == 400 and ("can't parse" in desc or 'unsupported start tag' in desc
                                                          or 'entity' in desc)


def _chamar_api(metodo, dados, arquivo=None, timeout=TIMEOUT_TEXTO):
    """
    Chama a API do Telegram e devolve SEMPRE um dicionário ({'ok': True/False, ...}).
    arquivo = (nome_do_campo, nome_do_arquivo, bytes)
    [DEPURAÇÃO] Antes:
      - enviar_mensagem não tinha TEMPO LIMITE: sem internet, o programa CONGELAVA;
      - se o Telegram respondesse com página de erro (não-JSON), a função quebrava;
      - erro 429 ("muitas mensagens") perdia a mensagem. Agora espera e tenta de novo;
      - queda rápida de conexão perdia a mensagem. Agora tenta mais uma vez.
    """
    token = _token()
    if not token:
        logger.error("TELEGRAM_TOKEN não está configurado no config.py")
        return _falha("TELEGRAM_TOKEN não configurado")
    url = f"https://api.telegram.org/bot{token}/{metodo}"

    for tentativa in (1, 2):
        try:
            files = None
            if arquivo:
                campo, nome, conteudo = arquivo
                files = {campo: (nome, conteudo)}
            resposta_http = requests.post(url, data=dados, files=files, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
            # Não conectou: é seguro tentar de novo (a mensagem não chegou ao Telegram).
            # (ReadTimeout NÃO entra aqui: o Telegram pode ter recebido - repetir duplicaria.)
            if tentativa == 1 and not isinstance(e, requests.exceptions.ReadTimeout):
                logger.warning(f"Falha de conexão com o Telegram ({metodo}); tentando de novo em 2 s...")
                time.sleep(2)
                continue
            logger.error(f"Sem conexão com o Telegram ({metodo}): {_sem_token(e)}")
            return _falha(f"Sem conexão com o Telegram: {_sem_token(e)}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de rede no Telegram ({metodo}): {_sem_token(e)}")
            return _falha(f"Erro de rede: {_sem_token(e)}")

        try:
            resposta = resposta_http.json()
        except ValueError:
            logger.error(f"Telegram respondeu algo que não é JSON ({metodo}, HTTP {resposta_http.status_code})")
            return {'ok': False, 'error_code': resposta_http.status_code,
                    'description': f"Resposta inválida do Telegram (HTTP {resposta_http.status_code})"}

        if resposta.get('error_code') == 429 and tentativa == 1:
            espera = int((resposta.get('parameters') or {}).get('retry_after', 1))
            if espera <= ESPERA_MAXIMA_429:
                logger.warning(f"Telegram pediu para esperar {espera} s (muitas mensagens). Aguardando...")
                time.sleep(espera)
                continue
        return resposta
    return _falha("Não foi possível enviar após 2 tentativas")


def _enviar_texto(chat_id, texto, parse_mode, reply_markup_json=None):
    """Envia uma mensagem (já dividida se for longa). O teclado vai na ÚLTIMA parte."""
    texto_final, modo = _preparar_texto(texto, parse_mode)
    partes = _dividir_texto(texto_final, LIMITE_TEXTO - MARGEM)
    resposta = None
    for i, parte in enumerate(partes):
        dados = {'chat_id': chat_id, 'text': parte}
        if modo:
            dados['parse_mode'] = modo
        if reply_markup_json and i == len(partes) - 1:
            dados['reply_markup'] = reply_markup_json
        resposta = _chamar_api('sendMessage', dados)

        # [DEPURAÇÃO] Se a formatação tiver algum defeito (ex: um nome com "<" ou "&"),
        # o Telegram recusava a mensagem e ela se PERDIA. Agora reenviamos sem formatação.
        if not resposta.get('ok') and modo and _eh_erro_de_formatacao(resposta):
            logger.warning(f"Formatação recusada pelo Telegram ({resposta.get('description')}). Reenviando como texto simples.")
            dados.pop('parse_mode', None)
            dados['text'] = _html_para_texto_puro(parte) if modo == 'HTML' else parte
            resposta = _chamar_api('sendMessage', dados)

        if not resposta.get('ok'):
            logger.error(f"Telegram recusou mensagem para chat_id {chat_id}: {resposta.get('description')}")
            return resposta
    return resposta


def _preparar_legenda(legenda, parse_mode):
    """Legenda de foto/documento: formata e corta no limite de 1024 letras."""
    if legenda is None or legenda == '':
        return None, None
    texto, modo = _preparar_texto(legenda, parse_mode)
    if len(texto) > LIMITE_LEGENDA:
        # [DEPURAÇÃO] legenda longa fazia o Telegram recusar a FOTO inteira.
        # Cortar HTML no meio pode quebrar uma tag: por segurança vira texto simples.
        puro = _html_para_texto_puro(texto) if modo == 'HTML' else texto
        texto, modo = puro[:LIMITE_LEGENDA - 1] + '…', None
    return texto, modo


def _chat_valido(chat_id, funcao):
    """[DEPURAÇÃO] Funcionário sem Telegram cadastrado: antes o pedido ia ao Telegram assim mesmo."""
    if chat_id is None or str(chat_id).strip() in ('', 'None', '0'):
        logger.warning(f"{funcao}: chat_id vazio (funcionário/grupo sem Telegram cadastrado). Nada enviado.")
        return False
    return True


def _ler_arquivo(caminho):
    """Lê o arquivo inteiro (permite repetir o envio sem reabrir). Devolve (nome, bytes) ou None."""
    try:
        with open(caminho, 'rb') as f:
            return os.path.basename(caminho), f.read()
    except OSError as e:
        logger.error(f"Não foi possível abrir o arquivo '{caminho}': {e}")
        return None


def _parece_caminho(valor):
    """True se o texto parece um caminho de arquivo (e não um file_id do Telegram)."""
    v = str(valor)
    return ('/' in v or '\\' in v or v.lower().endswith(_EXTENSOES_ARQUIVO))


def _registrar(resposta, descricao):
    if resposta and resposta.get('ok'):
        logger.info(f"{descricao}: enviado.")
    return resposta


# ==============================================================================
# == FUNÇÕES PÚBLICAS (usadas pelos outros arquivos) ===========================
# ==============================================================================
def enviar_mensagem(chat_id, texto, parse_mode='HTML'):
    """
    Envia uma mensagem de texto em HTML (<b>negrito</b>, <i>itálico</i>).
    Devolve a resposta do Telegram: resposta.get('ok') == True quando deu certo.
    """
    if not _chat_valido(chat_id, 'enviar_mensagem'):
        return _falha("chat_id vazio")
    try:
        return _registrar(_enviar_texto(chat_id, texto, parse_mode), f"Mensagem para {chat_id}")
    except Exception as e:  # nunca deixa um erro inesperado derrubar quem chamou
        logger.error(f"Erro inesperado ao enviar mensagem para {chat_id}: {_sem_token(e)}", exc_info=True)
        return _falha(f"Erro inesperado: {_sem_token(e)}")


def enviar_mensagem_com_botao(chat_id, texto, reply_markup_obj, parse_mode=None):
    """
    Envia uma mensagem com botões (teclado inline).
    [DEPURAÇÃO] Antes:
      - usava SEMPRE o modo Markdown: mensagens escritas em HTML (ex: resumo de fim de
        jornada do agendador) apareciam com "<b>" na tela, e qualquer "_" no texto
        fazia o Telegram RECUSAR a mensagem (a missão do dia não chegava);
      - não devolvia nada (quem chamava não sabia se tinha dado certo);
      - não tinha tempo limite.
    Agora detecta sozinho se o texto é HTML ou Markdown (parse_mode=None).
    """
    if not _chat_valido(chat_id, 'enviar_mensagem_com_botao'):
        return _falha("chat_id vazio")
    try:
        return _registrar(_enviar_texto(chat_id, texto, parse_mode, _markup_para_json(reply_markup_obj)),
                          f"Mensagem com botão para {chat_id}")
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar mensagem com botão para {chat_id}: {_sem_token(e)}", exc_info=True)
        return _falha(f"Erro inesperado: {_sem_token(e)}")


def enviar_foto_com_botoes(chat_id, foto, legenda, reply_markup_obj=None, parse_mode=None):
    """
    Envia uma foto (caminho de arquivo no computador OU file_id do Telegram),
    com legenda e, se quiser, botões. Devolve a resposta do Telegram.
    parse_mode: None = automático (antes o padrão era 'Markdown', que quebrava com "_").
    """
    if not _chat_valido(chat_id, 'enviar_foto_com_botoes'):
        return _falha("chat_id vazio")
    try:
        legenda_final, modo = _preparar_legenda(legenda, parse_mode)
        dados = {'chat_id': chat_id}
        if legenda_final:
            dados['caption'] = legenda_final
            if modo:
                dados['parse_mode'] = modo
        markup = _markup_para_json(reply_markup_obj)
        if markup:
            dados['reply_markup'] = markup

        arquivo = None
        if isinstance(foto, str) and os.path.isfile(foto):
            lido = _ler_arquivo(foto)
            if not lido:
                return _falha(f"Não foi possível abrir a foto: {foto}")
            arquivo = ('photo', lido[0], lido[1])
        elif isinstance(foto, str) and _parece_caminho(foto):
            # [DEPURAÇÃO] Antes um caminho que não existe era enviado como se fosse um
            # file_id, e o erro do Telegram ("wrong file identifier") confundia.
            logger.error(f"Foto não encontrada no computador: {foto}")
            return _falha(f"Foto não encontrada: {foto}")
        else:
            dados['photo'] = foto  # file_id ou link (URL)

        resposta = _chamar_api('sendPhoto', dados, arquivo, timeout=TIMEOUT_ARQUIVO if arquivo else TIMEOUT_TEXTO)
        if not resposta.get('ok') and dados.get('parse_mode') and _eh_erro_de_formatacao(resposta):
            logger.warning("Legenda com formatação inválida; reenviando a foto com legenda simples.")
            dados.pop('parse_mode')
            dados['caption'] = _html_para_texto_puro(dados['caption'])
            resposta = _chamar_api('sendPhoto', dados, arquivo, timeout=TIMEOUT_ARQUIVO if arquivo else TIMEOUT_TEXTO)
        if not resposta.get('ok'):
            logger.error(f"!!! ERRO DA API DO TELEGRAM (sendPhoto) para {chat_id}: {resposta.get('description')}")
        return _registrar(resposta, f"Foto para {chat_id}")
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar foto para {chat_id}: {_sem_token(e)}", exc_info=True)
        return _falha(f"Erro inesperado: {_sem_token(e)}")


def enviar_documento(chat_id, path_documento, legenda, parse_mode=''):
    """
    Envia um documento (PDF, planilha...) com legenda.
    parse_mode='' = legenda em texto simples (igual ao comportamento antigo).
    [DEPURAÇÃO] Antes: sem tempo limite, erro só aparecia com print (não ia para o log)
    e um arquivo inexistente derrubava a função.
    """
    if not _chat_valido(chat_id, 'enviar_documento'):
        return _falha("chat_id vazio")
    return _enviar_documento_generico(chat_id, path_documento, legenda, None, parse_mode)


def enviar_documento_com_botoes(chat_id, path_documento, legenda, reply_markup_obj, parse_mode=None):
    """
    Envia um documento (PDF) com legenda e botões.
    [DEPURAÇÃO] Antes não devolvia a resposta e usava Markdown fixo (mesmos problemas
    da enviar_mensagem_com_botao).
    """
    if not _chat_valido(chat_id, 'enviar_documento_com_botoes'):
        return _falha("chat_id vazio")
    return _enviar_documento_generico(chat_id, path_documento, legenda, reply_markup_obj, parse_mode)


def _enviar_documento_generico(chat_id, path_documento, legenda, reply_markup_obj, parse_mode):
    try:
        lido = _ler_arquivo(path_documento)
        if not lido:
            return _falha(f"Documento não encontrado: {path_documento}")
        dados = {'chat_id': chat_id}
        legenda_final, modo = _preparar_legenda(legenda, parse_mode)
        if legenda_final:
            dados['caption'] = legenda_final
            if modo:
                dados['parse_mode'] = modo
        markup = _markup_para_json(reply_markup_obj)
        if markup:
            dados['reply_markup'] = markup

        arquivo = ('document', lido[0], lido[1])
        resposta = _chamar_api('sendDocument', dados, arquivo, timeout=TIMEOUT_ARQUIVO)
        if not resposta.get('ok') and dados.get('parse_mode') and _eh_erro_de_formatacao(resposta):
            dados.pop('parse_mode')
            dados['caption'] = _html_para_texto_puro(dados['caption'])
            resposta = _chamar_api('sendDocument', dados, arquivo, timeout=TIMEOUT_ARQUIVO)
        if not resposta.get('ok'):
            logger.error(f"!!! ERRO DA API DO TELEGRAM (sendDocument) para {chat_id}: {resposta.get('description')}")
        return _registrar(resposta, f"Documento '{lido[0]}' para {chat_id}")
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar documento para {chat_id}: {_sem_token(e)}", exc_info=True)
        return _falha(f"Erro inesperado: {_sem_token(e)}")


def testar_conexao():
    """
    [DEPURAÇÃO] NOVO: confere se o TOKEN do bot está certo (sem enviar mensagem).
    Devolve (True, "nome do bot") ou (False, "motivo").
    """
    resposta = _chamar_api('getMe', {})
    if resposta.get('ok'):
        return True, resposta['result'].get('username', '?')
    return False, resposta.get('description', 'erro desconhecido')


# ==============================================================================
# == TESTE MANUAL: python notificador_telegram.py SEU_CHAT_ID ==================
# ==============================================================================
if __name__ == '__main__':
    ok, info = testar_conexao()
    if not ok:
        print(f"❌ Não foi possível falar com o Telegram: {info}")
        print("   Confira o TELEGRAM_TOKEN no config.py e a internet.")
        sys.exit(1)
    print(f"✅ Token OK! Bot: @{info}")
    if len(sys.argv) < 2:
        print("Para enviar uma mensagem de teste: python notificador_telegram.py SEU_CHAT_ID")
        sys.exit(0)
    r = enviar_mensagem(sys.argv[1], "🔔 <b>Teste do notificador</b>\nSe você recebeu esta mensagem, está tudo certo!")
    if r.get('ok'):
        print("✅ Mensagem de teste enviada! Confira o Telegram.")
    else:
        print(f"❌ O Telegram recusou: {r.get('description')}")
        print("   Dica: o chat_id está certo? A pessoa já deu /start no bot?")

# ==============================================================================
# == agendador.py  -  Robô Agendador (roda o dia todo em segundo plano) ========
# ==============================================================================
# O que ele faz sozinho:
#   • a cada minuto: missões de grupo, aviso de início de jornada, lembretes e
#     resumo de fim de jornada (com convite para avaliar o dia);
#   • a cada minuto (em paralelo): baixa as fotos de entregas e notas fiscais;
#   • 08:00: fechamento mensal (pódio) nos primeiros dias do mês;
#   • 09:00: lembrete de comunicados sem "ciente";
#   • 09:05: "Drop" das tarefas de quem está de folga/férias.
#
# Como rodar:  python agendador.py        (para parar: Ctrl+C)
#
# Versão DEPURADA: procure por [DEPURAÇÃO] para ver cada correção.
# O main.py usa a função forcar_drop_funcionario_especifico() daqui: ela continua
# com o mesmo nome e devolve (sucesso, mensagem) como antes.
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

PASTA_DO_PROGRAMA = os.path.dirname(os.path.abspath(__file__))

# [DEPURAÇÃO] O main.py importa este arquivo. Antes, ao importar, o agendador APAGAVA
# a configuração de log do main.py. Agora só configura se ninguém configurou antes.
if not logging.getLogger().handlers:
    log_dir = os.path.join(PASTA_DO_PROGRAMA, LOG_FOLDER)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        log_dir = PASTA_DO_PROGRAMA
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
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime, date, timedelta

import requests
import schedule
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
import database
import notificador_telegram

# ------------------------------------------------------------------------------
# Configurações
# ------------------------------------------------------------------------------
# [DEPURAÇÃO] Pastas agora ficam SEMPRE ao lado do programa. Antes eram relativas à
# "pasta atual": iniciado por atalho ou pelo Agendador de Tarefas do Windows, as fotos
# iam parar em outra pasta (ex: C:\Windows\System32\entregas) e o painel não as achava.
PASTA_ENTREGAS = os.path.join(PASTA_DO_PROGRAMA, 'entregas')
PASTA_NOTAS = os.path.join(PASTA_DO_PROGRAMA, 'notas_fiscais')
ARQUIVO_ESTADO = os.path.join(PASTA_DO_PROGRAMA, 'agendador_estado.json')

MAX_MINUTOS_RECUPERAR = 10      # se o robô "travar" alguns minutos, recupera até 10 minutos perdidos
HORARIO_FECHAMENTO = "08:00"
HORARIO_LEMBRETE_COMUNICADOS = "09:00"
HORARIO_DROP = "09:05"
DIAS_PARA_FECHAMENTO = 5        # o fechamento do mês anterior pode rodar do dia 1 ao dia 5

# --- CONTROLE DE CONCORRÊNCIA ---
# Semáforo: no máximo 3 downloads ao mesmo tempo
download_semaphore = threading.BoundedSemaphore(value=3)
_travas_de_tarefa = {}          # [DEPURAÇÃO] impede a MESMA tarefa rodar 2x ao mesmo tempo
_trava_estado = threading.Lock()

# --- MAPA DE ROTEAMENTO DOS DROPS ---
# [DEPURAÇÃO] getattr: se faltar um grupo no config.py, o main.py (que importa este
# arquivo) não quebra mais ao abrir.
_GRUPO_COZINHA = getattr(config, 'COZINHA_GROUP_CHAT_ID', None)
_GRUPO_ATENDIMENTO = getattr(config, 'ATENDIMENTO_GROUP_CHAT_ID', None)
MAPA_SETOR_GRUPO = {
    'cozinha': _GRUPO_COZINHA,
    'producao': _GRUPO_COZINHA,
    'estoque': _GRUPO_COZINHA,
    'atendimento': _GRUPO_ATENDIMENTO,
    'loja': _GRUPO_ATENDIMENTO,
    'caixa': _GRUPO_ATENDIMENTO,
    'salao': _GRUPO_ATENDIMENTO,
}
# (as versões com acento, 'produção' e 'salão', eram desnecessárias: o texto é
#  comparado SEM acento pela função normalizar_texto)


# ==============================================================================
# == FUNÇÕES AUXILIARES ========================================================
# ==============================================================================
def esc(valor):
    """[DEPURAÇÃO] Protege nomes/títulos com < > & (senão o Telegram recusava a mensagem)."""
    return html.escape('' if valor is None else str(valor), quote=False)


def normalizar_texto(texto):
    """Remove acentos e coloca em minúsculas para comparação segura."""
    if not texto:
        return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('ASCII').lower()


def dia_semana_sql(dt):
    """Dia da semana no padrão do projeto: 1=Domingo, 2=Segunda ... 7=Sábado."""
    return (dt.weekday() + 1) % 7 + 1


def _para_int(valor, padrao=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _para_data(valor):
    """Converte date/datetime/texto 'AAAA-MM-DD' em date (ou None)."""
    if valor is None or valor == '':
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _sem_token(texto):
    """[DEPURAÇÃO] Erros de download mostravam a URL com o TOKEN do bot, que ia para o log."""
    token = str(getattr(config, 'TELEGRAM_TOKEN', '') or '')
    texto = str(texto)
    return texto.replace(token, '***TOKEN***') if token else texto


def enviado(resposta):
    """True se o Telegram confirmou o envio."""
    return bool(resposta) and bool(resposta.get('ok'))


def motivo_ausencia_hoje(funcionario, hoje=None):
    """
    Diz se o funcionário está AUSENTE hoje e por quê (ou None se está trabalhando):
    férias/atestado (período de afastamento), folga semanal ou domingo de folga do mês.
    """
    hoje = hoje or date.today()
    dia_sql = dia_semana_sql(hoje)

    ini = _para_data(getattr(funcionario, 'DataInicioAfastamento', None))
    fim = _para_data(getattr(funcionario, 'DataFimAfastamento', None))
    if ini and fim and ini <= hoje <= fim:
        return "Férias/Atestado"

    if _para_int(getattr(funcionario, 'DiaDeFolga', 0)) == dia_sql:
        return "Folga Semanal"

    if dia_sql == 1:  # domingo
        ocorrencia_domingo = (hoje.day - 1) // 7 + 1
        dom_folga = _para_int(getattr(funcionario, 'DomingoFolgaMensal', 0))
        if dom_folga and dom_folga == ocorrencia_domingo:
            return f"Folga de Domingo ({ocorrencia_domingo}º)"
    return None


def executar_com_seguranca(funcao, *args):
    """
    [DEPURAÇÃO] BUG GRAVE: a biblioteca "schedule" NÃO trata erros. Qualquer erro em
    qualquer tarefa (ex: banco fora do ar por 1 minuto, um funcionário excluído no
    meio do fechamento) DERRUBAVA O ROBÔ INTEIRO, e ele ficava parado até alguém
    perceber e abrir de novo. Agora o erro vai para o log e o robô continua.
    """
    try:
        return funcao(*args)
    except Exception as e:
        logger.error(f"Erro na tarefa '{funcao.__name__}': {_sem_token(e)}", exc_info=True)
        return None


def run_threaded(job_func):
    """
    Executa uma tarefa em outra thread (para downloads não travarem o robô).
    [DEPURAÇÃO] Antes, se um download demorasse mais de 1 minuto, a próxima rodada
    começava JUNTO com a anterior e as duas baixavam as mesmas fotos (e avisavam o
    gestor 2 vezes). Agora a mesma tarefa nunca roda duas vezes ao mesmo tempo.
    """
    with _trava_estado:
        trava = _travas_de_tarefa.setdefault(job_func.__name__, threading.Lock())
    if not trava.acquire(blocking=False):
        logger.info(f"'{job_func.__name__}' ainda está rodando; pulando esta rodada.")
        return

    def alvo():
        try:
            executar_com_seguranca(job_func)
        finally:
            trava.release()

    threading.Thread(target=alvo, name=job_func.__name__, daemon=True).start()


# ------------------------------------------------------------------------------
# [DEPURAÇÃO] "Memória" das tarefas diárias (arquivo agendador_estado.json).
# Antes, se o robô fosse aberto depois das 09:05, o Drop do dia NÃO acontecia; e se
# fosse reiniciado às 09:05, o Drop era enviado DUAS vezes.
# ------------------------------------------------------------------------------
def _ler_estado():
    try:
        with open(ARQUIVO_ESTADO, 'r', encoding='utf-8') as f:
            dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def ja_rodou_hoje(nome):
    return _ler_estado().get(nome) == date.today().isoformat()


def marcar_rodou_hoje(nome):
    with _trava_estado:
        estado = _ler_estado()
        estado[nome] = date.today().isoformat()
        try:
            with open(ARQUIVO_ESTADO, 'w', encoding='utf-8') as f:
                json.dump(estado, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"Não foi possível salvar {ARQUIVO_ESTADO}: {e}")


# ==============================================================================
# == MÓDULO 1: MISSÕES DE GRUPO ================================================
# ==============================================================================
cache_tarefas_enviadas = deque(maxlen=500)


def verificar_e_enviar_tarefas_de_grupo(momento=None):
    """Envia as missões de grupo agendadas para este minuto (com proteção anti-duplicação)."""
    momento = momento or datetime.now()
    agora_hm = momento.strftime('%H:%M')
    chave_dia = momento.strftime('%Y-%m-%d')

    tarefas_para_disparar = database.buscar_tarefas_de_grupo_para_disparar(
        agora_hm, str(dia_semana_sql(momento)), str(momento.day))
    if not tarefas_para_disparar:
        return

    logger.info(f"[{agora_hm}] Encontradas {len(tarefas_para_disparar)} potenciais tarefas de grupo.")

    for tarefa in tarefas_para_disparar:
        atribuicao_id, titulo, pontos, nome_grupo, chat_id, *_ = tarefa

        # Mesma tarefa (título) para o mesmo grupo, no mesmo horário/dia: envia uma vez só
        assinatura_envio = (chat_id, titulo, agora_hm, chave_dia)
        if assinatura_envio in cache_tarefas_enviadas:
            continue

        if not chat_id:
            logger.error(f"ERRO: O grupo '{nome_grupo}' não tem Chat ID cadastrado!")
            continue

        # [DEPURAÇÃO] Mensagem em HTML com o título protegido. No formato antigo (Markdown),
        # um "_" no título (ex: "Limpar_freezer") fazia o Telegram recusar a missão.
        mensagem = (
            "🚨 <b>Nova Missão para a Equipe!</b> 🚨\n\n"
            f"<b>Tarefa:</b> {esc(titulo)}\n"
            f"<b>Recompensa:</b> {esc(pontos)} pontos\n\n"
            "O primeiro a aceitar fica responsável pela entrega <b>de hoje</b>. Quem vai encarar?"
        )
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Eu aceito o desafio!", callback_data=f"aceitar_tarefa_{atribuicao_id}")]])

        resposta = notificador_telegram.enviar_mensagem_com_botao(chat_id, mensagem, reply_markup, 'HTML')
        # [DEPURAÇÃO] Antes escrevia "SUCESSO" mesmo quando o Telegram recusava.
        if enviado(resposta):
            cache_tarefas_enviadas.append(assinatura_envio)
            logger.info(f"Missão '{titulo}' enviada para '{nome_grupo}' às {agora_hm}.")
        else:
            logger.error(f"Missão '{titulo}' NÃO foi entregue ao grupo '{nome_grupo}': "
                         f"{(resposta or {}).get('description')}")


# ==============================================================================
# == MÓDULO 2: INÍCIO DA JORNADA ===============================================
# ==============================================================================
_inicio_jornada_enviado = set()   # (FuncionarioID, data) - evita aviso repetido no mesmo dia


def _lista_tarefas_html(tarefas, com_tipo=False, com_pontos=True):
    linhas = []
    for tarefa in tarefas:
        tipo = ""
        if com_tipo:
            tipo = " (Especial)" if getattr(tarefa, 'Tipo', '') == 'Unica' else f" ({esc(getattr(tarefa, 'Tipo', ''))})"
        pontos = f" - <i>{esc(tarefa.Pontos)} pts</i>" if com_pontos else ""
        linhas.append(f"  - {esc(tarefa.Titulo)}{tipo}{pontos}")
    return "\n".join(linhas) + "\n"


def verificar_inicio_jornada(momento=None):
    """Avisa os funcionários que estão começando a jornada neste minuto."""
    momento = momento or datetime.now()
    agora = momento.strftime('%H:%M')

    funcionarios_para_notificar = database.buscar_funcionarios_por_horario(agora)
    if not funcionarios_para_notificar:
        return

    logger.info(f"[{agora}] {len(funcionarios_para_notificar)} funcionário(s) iniciando a jornada!")
    for funcionario in funcionarios_para_notificar:
        chave = (funcionario.FuncionarioID, momento.date())
        if chave in _inicio_jornada_enviado:
            continue
        # [DEPURAÇÃO] Quem está de FÉRIAS/ATESTADO ou no domingo de folga recebia
        # "bom dia, estes são seus desafios" todos os dias. (O banco só olhava a folga semanal.)
        ausencia = motivo_ausencia_hoje(funcionario, momento.date())
        if ausencia:
            logger.info(f"--> {funcionario.NomeCompleto} está ausente hoje ({ausencia}); sem aviso de jornada.")
            continue

        tarefas_do_dia = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)
        mensagem = f"Olá, <b>{esc(funcionario.NomeCompleto)}</b>! 🌤️\n\n"
        if not tarefas_do_dia:
            mensagem += "Você não tem nenhuma tarefa recorrente para hoje. Tenha um excelente dia de trabalho! ✨"
        else:
            mensagem += "Estes são os seus desafios de hoje:\n\n"
            mensagem += _lista_tarefas_html(tarefas_do_dia, com_tipo=True)
            mensagem += "\nUse o comando /tarefas para começar. Bom trabalho! 💪"

        if enviado(notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem)):
            _inicio_jornada_enviado.add(chave)
            logger.info(f"--> Início de jornada enviado para {funcionario.NomeCompleto}.")
        else:
            logger.warning(f"--> Início de jornada NÃO entregue para {funcionario.NomeCompleto}.")


# ==============================================================================
# == MÓDULO 3: LEMBRETES INTERMEDIÁRIOS ========================================
# ==============================================================================
def verificar_lembretes_intermediarios():
    """Lembrete no meio do expediente (3h e 6h depois do início)."""
    agora = datetime.now().strftime('%H:%M')
    funcionarios_para_lembrar = database.buscar_funcionarios_para_lembrete(agora)
    if not funcionarios_para_lembrar:
        return

    logger.info(f"[{agora}] {len(funcionarios_para_lembrar)} funcionário(s) para enviar LEMBRETE!")
    for funcionario in funcionarios_para_lembrar:
        if motivo_ausencia_hoje(funcionario):
            continue
        tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)
        if not tarefas_pendentes:
            logger.info(f"--> {funcionario.NomeCompleto} está com tudo em dia! Nenhum lembrete necessário.")
            continue

        mensagem = (f"Olá, <b>{esc(funcionario.NomeCompleto)}</b>! 👋 Só um lembrete amigável sobre "
                    "seus desafios de hoje que ainda estão em aberto:\n\n")
        mensagem += _lista_tarefas_html(tarefas_pendentes)
        mensagem += "\nUse o comando /tarefas para iniciar uma delas."
        mensagem += "\n\nContinue com o ótimo trabalho! Você consegue! 🚀"
        if not enviado(notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem)):
            logger.warning(f"--> Lembrete NÃO entregue para {funcionario.NomeCompleto}.")


# ==============================================================================
# == MÓDULO 4: FIM DA JORNADA ==================================================
# ==============================================================================
def verificar_fim_jornada():
    """Resumo de fim de expediente com o convite para avaliar o dia."""
    agora = datetime.now().strftime('%H:%M')
    funcionarios_para_resumo = database.buscar_funcionarios_para_resumo_final(agora)
    if not funcionarios_para_resumo:
        return

    logger.info(f"[{agora}] {len(funcionarios_para_resumo)} funcionário(s) finalizando a jornada!")
    for funcionario in funcionarios_para_resumo:
        if motivo_ausencia_hoje(funcionario):
            continue
        tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)

        mensagem = f"<b>{esc(funcionario.NomeCompleto)}</b>, fim de expediente! 🌆\n\n"
        if not tarefas_pendentes:
            mensagem += "Você concluiu todos os seus desafios de hoje. Trabalho incrível! 🏆\n\n"
        else:
            mensagem += "Obrigado pelo seu esforço hoje! 🙌\n\nAs seguintes tarefas ficaram pendentes:\n"
            mensagem += _lista_tarefas_html(tarefas_pendentes, com_pontos=False) + "\n"
        mensagem += "Sua opinião é muito importante para nós! Como você avalia seu dia de trabalho hoje?"

        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Avaliar meu dia", callback_data="avaliar_dia")]])
        # [DEPURAÇÃO] 'HTML': antes esta mensagem (escrita em HTML) era enviada em modo
        # Markdown e o funcionário via "<b>Ana</b>" na tela.
        resposta = notificador_telegram.enviar_mensagem_com_botao(funcionario.ChatIDTelegram, mensagem, reply_markup, 'HTML')
        if enviado(resposta):
            logger.info(f"--> Resumo de fim de jornada enviado para {funcionario.NomeCompleto}.")
        else:
            logger.warning(f"--> Resumo de fim de jornada NÃO entregue para {funcionario.NomeCompleto}.")


# ==============================================================================
# == MÓDULO 5: DROP DE TAREFAS (FOLGAS / FÉRIAS) ===============================
# ==============================================================================
def _grupo_destino(setor_tarefa, cargo_funcionario):
    """Escolhe o grupo do Telegram: primeiro pelo setor da tarefa, depois pelo cargo."""
    for texto in (normalizar_texto(setor_tarefa), normalizar_texto(cargo_funcionario)):
        for chave, chat_id in MAPA_SETOR_GRUPO.items():
            if chave in texto and chat_id:
                return chat_id
    return getattr(config, 'FOLGA_GROUP_CHAT_ID', None)


def _mensagem_drop(titulo_html, subtitulo_html, itens, texto_botao, rodape_html):
    """Monta a mensagem do Drop e os botões. itens = [(tarefa, linha_extra_html)]."""
    mensagem = f"{titulo_html}\n\n{subtitulo_html}\n━━━━━━━━━━━━━━━━━━\n"
    teclado = []
    for i, (tarefa, extra) in enumerate(itens, 1):
        mensagem += f"{i}️⃣ <b>{esc(tarefa.Titulo)}</b>\n     └ {extra}💰 <b>{esc(tarefa.Pontos)} pts</b>\n\n"
        teclado.append([InlineKeyboardButton(f"🚀 {texto_botao} {i}", callback_data=f"aceitar_folga_{tarefa.TarefaID}")])
    mensagem += rodape_html
    return mensagem, InlineKeyboardMarkup(teclado)


def verificar_e_delegar_tarefas_de_folga(forcar=False):
    """
    Verifica folgas fixas, domingos de folga e afastamentos (férias/atestado),
    junta as tarefas dessas pessoas e envia o 'Drop' para os grupos.
    """
    if not forcar and ja_rodou_hoje('drop'):
        logger.info("Drop de hoje já foi enviado. Nada a fazer.")
        return

    logger.info("🎲 Verificando Ausências (Folgas/Férias) para Drop...")
    hoje = date.today()
    dia_sql = dia_semana_sql(hoje)

    todos_funcionarios = database.listar_funcionarios() or []
    ausentes = []
    for f in todos_funcionarios:
        motivo = motivo_ausencia_hoje(f, hoje)
        if motivo:
            ausentes.append((f, motivo))
            logger.info(f"--> Ausência detectada: {f.NomeCompleto} ({motivo})")

    marcar_rodou_hoje('drop')
    if not ausentes:
        logger.info("--> Ninguém de folga ou afastado hoje. Drop cancelado.")
        return

    drop_por_grupo = {}
    for funcionario, motivo in ausentes:
        tarefas_do_dia = database.buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario.FuncionarioID, str(dia_sql))
        if not tarefas_do_dia:
            logger.info(f"--> {funcionario.NomeCompleto} está ausente, mas não tinha tarefas agendadas para hoje.")
            continue
        for tarefa in tarefas_do_dia:
            chat_destino = _grupo_destino(getattr(tarefa, 'Setor', ''), getattr(funcionario, 'Cargo', ''))
            drop_por_grupo.setdefault(chat_destino, []).append((tarefa, funcionario, motivo))

    for chat_id, itens in drop_por_grupo.items():
        if not chat_id:
            logger.error(f"Drop com {len(itens)} tarefa(s) sem grupo de destino (confira FOLGA_GROUP_CHAT_ID no config.py).")
            continue
        linhas = []
        for tarefa, funcionario, motivo in itens:
            primeiro_nome = (funcionario.NomeCompleto or '?').split()[0]
            tag = "🌴" if ("Férias" in motivo or "Atestado" in motivo) else "🏠"
            linhas.append((tarefa, f"{tag} <b>{esc(primeiro_nome)}</b> |  "))

        mensagem, teclado = _mensagem_drop(
            "⚡ <b>DROP DE TAREFAS LIBERADO!</b> ⚡",
            f"Equipe reduzida hoje (Folgas/Férias). Temos <b>{len(itens)} missões extras</b> disponíveis!",
            linhas, "Pegar Missão", "👇 <b>Ajude a equipe e ganhe pontos extras:</b>")

        resposta = notificador_telegram.enviar_mensagem_com_botao(chat_id, mensagem, teclado, 'HTML')
        if enviado(resposta):
            logger.info(f"--> Drop enviado com sucesso para grupo {chat_id} ({len(itens)} tarefas).")
        else:
            logger.error(f"--> Drop NÃO entregue ao grupo {chat_id}: {(resposta or {}).get('description')}")


def forcar_drop_funcionario_especifico(funcionario_id):
    """
    Usado pelo main.py (botão do gestor) quando alguém falta de última hora.
    Devolve (sucesso, mensagem_para_a_tela).
    """
    logger.info(f"--> Iniciando Drop Manual para FuncionarioID: {funcionario_id}...")
    try:
        funcionario = database.buscar_funcionario_por_id(funcionario_id)
        if not funcionario:
            return False, "Funcionário não encontrado."

        hoje_dt = datetime.now()
        tarefas_do_dia = database.buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario_id, str(dia_semana_sql(hoje_dt)))
        if not tarefas_do_dia:
            return False, (f"O funcionário {funcionario.NomeCompleto} não tem tarefas agendadas "
                           f"para hoje ({hoje_dt.strftime('%d/%m')}).")

        # Grupo: primeiro pelo cargo, depois pelo setor da primeira tarefa
        chat_destino = None
        for texto in (normalizar_texto(getattr(funcionario, 'Cargo', '')),
                      normalizar_texto(getattr(tarefas_do_dia[0], 'Setor', ''))):
            for chave, chat_id in MAPA_SETOR_GRUPO.items():
                if chave in texto and chat_id:
                    chat_destino = chat_id
                    break
            if chat_destino:
                break
        chat_destino = chat_destino or getattr(config, 'FOLGA_GROUP_CHAT_ID', None)
        if not chat_destino:
            return False, "Nenhum grupo de destino configurado (confira FOLGA_GROUP_CHAT_ID no config.py)."

        mensagem, teclado = _mensagem_drop(
            "🚨 <b>DROP DE TAREFAS (AUSÊNCIA IMPREVISTA)</b> 🚨",
            f"O colaborador <b>{esc(funcionario.NomeCompleto)}</b> não poderá comparecer/continuar hoje.\n"
            f"Temos <b>{len(tarefas_do_dia)} missões</b> que precisam ser cobertas!",
            [(t, "") for t in tarefas_do_dia], "Assumir Missão",
            "👇 <b>Quem pode cobrir e ganhar esses pontos?</b>")

        resposta = notificador_telegram.enviar_mensagem_com_botao(chat_destino, mensagem, teclado, 'HTML')
        # [DEPURAÇÃO] Antes a tela do gestor dizia "sucesso" mesmo quando o Telegram recusava.
        if enviado(resposta):
            logger.info(f"--> Drop manual enviado para grupo {chat_destino}.")
            return True, f"Drop enviado com sucesso para o grupo (ChatID: {chat_destino})!"
        motivo = (resposta or {}).get('description', 'sem resposta')
        return False, f"O Telegram não aceitou o envio: {motivo}"
    except Exception as e:
        logger.error(f"Erro no Drop Manual: {_sem_token(e)}", exc_info=True)
        return False, f"Erro ao enviar o Drop: {_sem_token(e)}"


# ==============================================================================
# == MÓDULO 6: FECHAMENTO MENSAL ===============================================
# ==============================================================================
PREMIOS_COZINHA = [
    "🏆 1 Pote 2L + Cobertura + Casquinhas (Kit Família)",
    "🥈 1 Taça Especial do Cardápio (Para comer na loja)",
    "🥉 1 Milkshake Grande ou Açaí 500ml",
]
PREMIOS_LOJA = [
    "🏆 1 Torta de Sorvete inteira (ou Pote Especial)",
    "🥈 1 Fondue ou Taça Especial",
    "🥉 1 Pote Pop para levar para casa",
]


def _processar_setor_fechamento(nome_setor, filtro_db, lista_premios, fim_mes_passado):
    logger.info(f"--> Processando ranking: {nome_setor}...")
    ranking = database.calcular_ranking_desempenho(data_final_calculo=fim_mes_passado, setor_filtro=filtro_db)
    if not ranking:
        logger.info(f"   -> Sem dados para {nome_setor}.")
        return

    database.salvar_historico_ranking(ranking)

    # [DEPURAÇÃO] Mensagens em HTML (antes com ** que apareciam como asteriscos)
    texto_gestores = f"🎉 <b>Fechamento {esc(nome_setor)}: Pódio Final!</b> 🎉\n\n"
    vencedores = []
    for i, vencedor in enumerate(ranking[:len(lista_premios)]):
        premio = lista_premios[i]
        texto_gestores += (f"{i + 1}º: {esc(vencedor['NomeCompleto'])} ({esc(vencedor['Desempenho'])}%)\n"
                           f"   - Prêmio: {esc(premio)}\n")
        vencedores.append({'dados': vencedor, 'premio': premio, 'posicao': i + 1})

    if not enviado(notificador_telegram.enviar_mensagem(getattr(config, 'GESTOR_GROUP_CHAT_ID', None), texto_gestores)):
        logger.error(f"Pódio de {nome_setor} NÃO foi entregue ao grupo de gestores.")

    for vencedor in vencedores:
        dados = vencedor['dados']
        # [DEPURAÇÃO] Funcionário excluído depois do mês -> antes dava erro e INTERROMPIA
        # o fechamento (os outros vencedores e o setor seguinte ficavam sem aviso).
        funcionario = database.buscar_funcionario_por_id(dados['FuncionarioID'])
        chat_id = getattr(funcionario, 'ChatIDTelegram', None) if funcionario else None
        if not chat_id:
            logger.warning(f"Vencedor {dados['NomeCompleto']} sem Telegram cadastrado; aviso não enviado.")
            continue
        texto_vencedor = (f"🎉🎊 <b>PARABÉNS, {esc(dados['NomeCompleto'])}!</b> 🎊🎉\n\n"
                          f"Você foi destaque no ranking de <b>{esc(nome_setor)}</b>!\n\n"
                          f"Sua Posição: <b>{vencedor['posicao']}º Lugar</b>\n"
                          f"Sua Recompensa: <b>{esc(vencedor['premio'])}</b>\n\n"
                          "Procure a gestão para retirar seu prêmio!")
        notificador_telegram.enviar_mensagem(chat_id, texto_vencedor)


def executar_fechamento_mensal():
    """Executa o fechamento do mês anterior, separado por setores (Cozinha e Loja)."""
    logger.info("🏆 INICIANDO ROTINA DE FECHAMENTO MENSAL! 🏆")
    hoje = date.today()
    fim_mes_passado = hoje.replace(day=1) - timedelta(days=1)

    if database.verificar_se_fechamento_ja_rodou(fim_mes_passado.year, fim_mes_passado.month):
        logger.info(f"--> O fechamento de {fim_mes_passado.month}/{fim_mes_passado.year} já foi executado.")
        return

    # [DEPURAÇÃO] Cada setor protegido: um erro na Cozinha não impede mais o da Loja
    executar_com_seguranca(_processar_setor_fechamento, "Cozinha", "Cozinha", PREMIOS_COZINHA, fim_mes_passado)
    executar_com_seguranca(_processar_setor_fechamento, "Atendimento/Loja", "Loja", PREMIOS_LOJA, fim_mes_passado)
    logger.info("✅ FECHAMENTO MENSAL CONCLUÍDO! ✅")


def verificar_e_executar_fechamento():
    """
    Roda todo dia às 08:00 (e quando o robô é aberto).
    [DEPURAÇÃO] Antes só rodava se o robô estivesse ligado exatamente no DIA 1 às 08:00.
    Se o computador estivesse desligado nessa hora, o mês ficava SEM fechamento.
    Agora tenta do dia 1 ao dia 5 (o banco impede fazer duas vezes o mesmo mês).
    """
    if date.today().day <= DIAS_PARA_FECHAMENTO:
        executar_fechamento_mensal()
    else:
        logger.info("Verificação de fechamento: fora dos primeiros dias do mês. Nenhuma ação necessária.")


# ==============================================================================
# == MÓDULO 7: LEMBRETE DE COMUNICADOS =========================================
# ==============================================================================
def verificar_e_enviar_lembretes_comunicados(forcar=False):
    """Lembra quem está há mais de 24h sem dar 'ciente' num comunicado."""
    if not forcar and ja_rodou_hoje('lembretes_comunicados'):
        return
    logger.info("Verificando lembretes de comunicados...")
    pendencias = database.buscar_assinaturas_pendentes_antigas(horas_atras=24)
    marcar_rodou_hoje('lembretes_comunicados')
    if not pendencias:
        logger.info("--> Nenhum lembrete de comunicado a ser enviado.")
        return

    logger.info(f"--> Encontradas {len(pendencias)} pendências de comunicados para lembrar!")
    for pendencia in pendencias:
        data_envio = pendencia.DataEnvio.strftime('%d/%m/%Y') if hasattr(pendencia.DataEnvio, 'strftime') else str(pendencia.DataEnvio or '')[:10]
        mensagem = (
            f"Olá, <b>{esc(pendencia.NomeCompleto)}</b>! 👋\n\n"
            "Só um lembrete amigável de que o seguinte comunicado ainda aguarda sua confirmação de ciência:\n\n"
            f"📄 <b>Título:</b> {esc(pendencia.Titulo)}\n"
            f"🗓️ <b>Enviado em:</b> {esc(data_envio)}\n\n"
            "Envie /tarefas (ou qualquer comando) ao bot para aparecer o botão de ciência. Obrigado!"
        )
        if enviado(notificador_telegram.enviar_mensagem(pendencia.ChatIDTelegram, mensagem)):
            logger.info(f"--> Lembrete sobre '{pendencia.Titulo}' enviado para {pendencia.NomeCompleto}.")


# ==============================================================================
# == MÓDULO 8: DOWNLOADS (fotos de entregas e notas fiscais) ===================
# ==============================================================================
def _baixar_arquivo_telegram(file_id, pasta, prefixo):
    """
    Baixa um arquivo do Telegram para a pasta. Devolve o caminho salvo ou None.
    [DEPURAÇÃO] Antes: sempre salvava como .jpg (um PDF virava ".jpg" e não abria);
    arquivo baixado pela metade ficava no disco; o TOKEN aparecia no log em erros.
    """
    token = getattr(config, 'TELEGRAM_TOKEN', '')
    try:
        r_info = requests.get(f"https://api.telegram.org/bot{token}/getFile",
                              params={'file_id': file_id}, timeout=15)
        info = r_info.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning(f"Falha ao consultar arquivo no Telegram: {_sem_token(e)}")
        return None
    if not info.get('ok'):
        # Arquivos acima de 20 MB ou file_id inválido caem aqui
        logger.warning(f"Telegram não liberou o arquivo ({prefixo}): {info.get('description')}")
        return None

    remoto = info['result']['file_path']
    extensao = os.path.splitext(remoto)[1].lower() or '.jpg'
    os.makedirs(pasta, exist_ok=True)
    local_path = os.path.join(pasta, f"{prefixo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extensao}")
    temporario = local_path + '.parcial'
    try:
        with requests.get(f"https://api.telegram.org/file/bot{token}/{remoto}", stream=True, timeout=60) as r_file:
            if r_file.status_code != 200:
                logger.warning(f"Download recusado ({prefixo}): HTTP {r_file.status_code}")
                return None
            with open(temporario, 'wb') as f:
                for chunk in r_file.iter_content(8192):
                    if chunk:
                        f.write(chunk)
        os.replace(temporario, local_path)   # só vira arquivo "de verdade" quando terminou
        return local_path
    except (requests.exceptions.RequestException, OSError) as e:
        logger.warning(f"Falha no download ({prefixo}): {_sem_token(e)}")
        return None
    finally:
        if os.path.exists(temporario):
            try:
                os.remove(temporario)
            except OSError:
                pass


def _notificar_gestor_entrega(entrega_id, foto):
    """Envia a foto da entrega ao grupo de gestores (com Aprovar/Reprovar) e marca a flag."""
    grupo = getattr(config, 'GESTOR_GROUP_CHAT_ID', None)
    detalhes = database.buscar_detalhes_da_entrega(entrega_id)
    if not detalhes or not grupo:
        return False
    caption = (f"<b>Nova Entrega</b>\n👤 {esc(detalhes.NomeCompleto)}\n"
               f"📝 {esc(detalhes.Titulo)}\n📦 ID: {entrega_id}")
    kb = [[InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_gestor_{entrega_id}"),
           InlineKeyboardButton("❌ Reprovar", callback_data=f"reprovar_gestor_{entrega_id}")]]
    resposta = notificador_telegram.enviar_foto_com_botoes(grupo, foto, caption, InlineKeyboardMarkup(kb), 'HTML')
    if enviado(resposta):
        database.marcar_notificacao_gestor_enviada(entrega_id)
        return True
    logger.warning(f"Aviso ao gestor da entrega {entrega_id} não foi entregue: {(resposta or {}).get('description')}")
    return False


def processar_downloads_pendentes_sync():
    """Baixa as fotos de evidência das entregas e avisa o gestor (se ainda não foi avisado)."""
    if not download_semaphore.acquire(blocking=False):
        logger.warning("--> Limite de downloads simultâneos atingido. Tentando na próxima rodada.")
        return
    try:
        entregas = database.buscar_entregas_para_download()
        if not entregas:
            return
        logger.info(f"--> Baixando {len(entregas)} evidências pendentes...")

        for entrega in entregas:
            if not entrega.FileIDTelegram:
                continue
            local_path = _baixar_arquivo_telegram(entrega.FileIDTelegram, PASTA_ENTREGAS, str(entrega.EntregaID))
            if not local_path:
                continue
            try:
                database.finalizar_registro_entrega(entrega.EntregaID, local_path)
                logger.info(f"--> Sucesso: Entrega {entrega.EntregaID} salva em {local_path}")
            except Exception as e_db:
                # Falha no banco: apaga o arquivo para não ficar "órfão" no disco
                logger.error(f"Erro no banco ao salvar entrega {entrega.EntregaID}: {e_db}. Removendo arquivo.")
                if os.path.exists(local_path):
                    os.remove(local_path)
                continue
            # [DEPURAÇÃO] Antes, um erro aqui caía numa "limpeza" que usava um campo que a
            # consulta não traz (PathFotoEvidencia) -> novo erro, e as entregas seguintes
            # da lista ficavam sem download naquela rodada.
            try:
                if not database.verificar_status_notificacao_gestor(entrega.EntregaID):
                    _notificar_gestor_entrega(entrega.EntregaID, local_path)
            except Exception as e:
                logger.error(f"Erro ao avisar o gestor da entrega {entrega.EntregaID}: {_sem_token(e)}")
    finally:
        download_semaphore.release()


def reenviar_avisos_de_entregas_pendentes():
    """
    [DEPURAÇÃO] NOVO. Se o aviso de uma entrega ao grupo de gestores falhasse (sem
    internet naquele momento), ele NUNCA mais era reenviado e a entrega ficava
    esquecida. Agora, a cada 10 minutos, reenvia os avisos das últimas 48h que não
    foram confirmados (no máximo 10 por vez).
    """
    conn = database.get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 10 EntregaID, PathFotoEvidencia
            FROM Entregas
            WHERE StatusValidacao = 'Pendente'
              AND PathFotoEvidencia IS NOT NULL
              AND ISNULL(NotificacaoGestorEnviada, 0) = 0
              AND DataEnvio >= DATEADD(hour, -48, GETDATE())
            ORDER BY DataEnvio
        """)
        pendentes = cursor.fetchall()
    finally:
        conn.close()
    for entrega_id, caminho in pendentes:
        if caminho and os.path.isfile(caminho):
            if _notificar_gestor_entrega(entrega_id, caminho):
                logger.info(f"Aviso da entrega {entrega_id} reenviado aos gestores.")


def processar_downloads_notas_fiscais():
    """Baixa as fotos das notas fiscais enviadas pelo bot."""
    if not download_semaphore.acquire(blocking=False):
        return
    try:
        nfs = database.buscar_notas_para_download()
        for nf in nfs or []:
            # [DEPURAÇÃO] NF sem file_id era consultada no Telegram A CADA MINUTO, para sempre
            if not nf.FileIDTelegram:
                continue
            local_path = _baixar_arquivo_telegram(nf.FileIDTelegram, PASTA_NOTAS, f"NF_{nf.NotaFiscalID}")
            if not local_path:
                continue
            try:
                database.finalizar_download_nota_fiscal(nf.NotaFiscalID, local_path)
            except Exception as e:
                logger.error(f"Erro no banco ao salvar NF {nf.NotaFiscalID}: {e}. Removendo arquivo.")
                if os.path.exists(local_path):
                    os.remove(local_path)
    finally:
        download_semaphore.release()


# ==============================================================================
# == RELÓGIO DO ROBÔ ===========================================================
# ==============================================================================
def processar_minuto(momento):
    """Tarefas que dependem do MINUTO exato (podem ser recuperadas se o robô atrasar)."""
    executar_com_seguranca(verificar_e_enviar_tarefas_de_grupo, momento)
    executar_com_seguranca(verificar_inicio_jornada, momento)


def processar_minuto_atual():
    """Tarefas cujo horário é calculado pelo próprio banco (só valem no minuto atual)."""
    executar_com_seguranca(verificar_lembretes_intermediarios)
    executar_com_seguranca(verificar_fim_jornada)


class RelogioDeMinutos:
    """
    [DEPURAÇÃO] BUG GRAVE: antes era usado schedule.every(1).minutes. Essa forma conta
    60 segundos a partir do FIM da última execução, então o horário vai "escorregando"
    (o tempo da consulta ao banco + até 1 s de espera, a cada minuto). De tempos em
    tempos um minuto inteiro era PULADO - e quem tinha o horário de início naquele
    minuto ficava sem o aviso de jornada (e o grupo, sem a missão).
    Agora o robô confere o relógio a cada segundo e processa CADA minuto uma vez só;
    se atrasar (computador lento), recupera os minutos perdidos (até 10).
    """
    def __init__(self):
        self.ultimo = None

    def verificar(self, agora=None):
        agora = (agora or datetime.now()).replace(second=0, microsecond=0)
        if self.ultimo is None:
            self.ultimo = agora - timedelta(minutes=1)
        if agora <= self.ultimo:
            return 0      # mesmo minuto (ou relógio voltou): nada a fazer
        perdidos = int((agora - self.ultimo).total_seconds() // 60)
        if perdidos > 1:
            logger.warning(f"O robô ficou {perdidos - 1} minuto(s) sem verificar; recuperando...")
        inicio = max(self.ultimo + timedelta(minutes=1), agora - timedelta(minutes=MAX_MINUTOS_RECUPERAR - 1))
        momento = inicio
        processados = 0
        while momento <= agora:
            processar_minuto(momento)
            processados += 1
            momento += timedelta(minutes=1)
        processar_minuto_atual()
        self.ultimo = agora
        return processados


def _passou_do_horario(hhmm, limite_horas=5):
    """True se agora está entre o horário hhmm e algumas horas depois (para recuperar tarefas perdidas)."""
    h, m = map(int, hhmm.split(':'))
    inicio = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    return inicio <= datetime.now() <= inicio + timedelta(hours=limite_horas)


def configurar_agendamentos():
    """Registra as tarefas no 'schedule' (todas protegidas contra erros)."""
    schedule.every().day.at(HORARIO_FECHAMENTO).do(executar_com_seguranca, verificar_e_executar_fechamento)
    schedule.every().day.at(HORARIO_LEMBRETE_COMUNICADOS).do(executar_com_seguranca, verificar_e_enviar_lembretes_comunicados)
    schedule.every().day.at(HORARIO_DROP).do(executar_com_seguranca, verificar_e_delegar_tarefas_de_folga)

    # Downloads em threads separadas (não travam o relógio do robô)
    schedule.every(1).minutes.do(run_threaded, processar_downloads_pendentes_sync)
    schedule.every(1).minutes.do(run_threaded, processar_downloads_notas_fiscais)
    schedule.every(10).minutes.do(run_threaded, reenviar_avisos_de_entregas_pendentes)


def recuperar_tarefas_do_dia():
    """[DEPURAÇÃO] Se o robô foi aberto DEPOIS do horário, roda hoje o que ficou para trás."""
    executar_com_seguranca(verificar_e_executar_fechamento)
    if _passou_do_horario(HORARIO_LEMBRETE_COMUNICADOS):
        executar_com_seguranca(verificar_e_enviar_lembretes_comunicados)
    if _passou_do_horario(HORARIO_DROP):
        executar_com_seguranca(verificar_e_delegar_tarefas_de_folga)


def main():
    print("--- 🤖 Robô Agendador 2.0 Iniciado 🤖 ---")
    print(f"Verifica a cada minuto. Fechamento às {HORARIO_FECHAMENTO}, lembretes às "
          f"{HORARIO_LEMBRETE_COMUNICADOS} e Drop às {HORARIO_DROP}. Para parar: Ctrl+C")
    configurar_agendamentos()
    recuperar_tarefas_do_dia()
    relogio = RelogioDeMinutos()

    while True:
        try:
            relogio.verificar()
            schedule.run_pending()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Robô Ativo. Verificando agendamentos...", end='\r')
        except KeyboardInterrupt:
            raise
        except Exception as e:  # última proteção: o robô NUNCA para sozinho
            logger.error(f"Erro no ciclo principal do robô: {_sem_token(e)}", exc_info=True)
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nRobô Agendador encerrado pelo usuário (Ctrl+C).")

# ==============================================================================
# telegram_bot.py - Bot do Telegram do Sistema de Gamificação
# ------------------------------------------------------------------------------
# VERSÃO DEPURADA
#
# Principais correções desta versão (detalhes no relatório de depuração):
#   1. Cliques em botões: o Telegram só aceita UMA resposta (query.answer) por
#      clique. O código antigo respondia duas vezes, o que quebrava os botões
#      "Ciente" de comunicados, as Notas Fiscais e todos os alertas.
#   2. Onboarding (cadastro): as perguntas estavam "uma etapa adiantadas"
#      (pedia o CPF e salvava como RG). O fluxo foi reescrito.
#   3. Grupo de gestores: supergrupos eram ignorados, então o motivo de
#      recusa nunca era recebido. Agora aceita grupo e supergrupo.
#   4. O comando /cancelar não existia (nunca funcionava). Agora existe.
#   5. Gestores eram bloqueados pela trava de feedback ao aprovar tarefas.
#   6. Toda a formatação foi padronizada em HTML com escape de nomes, evitando
#      o erro "Can't parse entities" quando um nome tem _ * < ou &.
#   7. Compatível com python-telegram-bot 20.x, 21.x e 22.x.
# ==============================================================================

# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING ===================================
# ==============================================================================
import logging
import logging.handlers
import sys
import os  # Necessário para criar a pasta de logs

# --- Configurações ---
LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs'            # Nome da pasta onde os logs serão salvos
LOG_LEVEL = logging.INFO       # Nível mínimo para registrar (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024  # Tamanho máximo de cada arquivo de log (10 MB)
LOG_BACKUP_COUNT = 5              # Quantos arquivos de log antigos manter

# --- Cria a pasta de logs se não existir ---
# abspath garante um caminho completo mesmo se o bot for iniciado de outra pasta.
PASTA_DO_BOT = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(PASTA_DO_BOT, LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        print(f"Pasta de logs criada em: {log_dir}")  # print: o logger ainda não existe
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        log_dir = PASTA_DO_BOT  # Se não conseguir criar a pasta, loga na pasta do bot

log_filepath = os.path.join(log_dir, LOG_FILENAME)

# --- Handler de arquivo rotativo (troca de arquivo ao atingir LOG_MAX_BYTES) ---
file_handler = logging.handlers.RotatingFileHandler(
    log_filepath, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
)
file_handler.setLevel(LOG_LEVEL)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

# --- Handler do console (tela preta do terminal) ---
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

# --- Logger raiz: limpa handlers antigos para não duplicar linhas ---
logging.getLogger('').handlers = []
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[file_handler, console_handler])

# A biblioteca httpx registra CADA requisição ao Telegram em nível INFO,
# o que enche o log (e mostra o token do bot na URL). Deixamos só avisos.
logging.getLogger('httpx').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.info(f"*** Logging configurado para o módulo: {__name__} ***")
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================

# --- Bibliotecas padrão do Python (já vêm instaladas) ---
import calendar                      # Para saber quantos dias tem o mês
import html                          # Para "escapar" textos em mensagens HTML
import json                          # Para salvar os dados dos filhos
import locale                        # Para nomes de meses em português
import math                          # Para arredondar pontos para cima
import re                            # Expressões regulares (padrões de texto)
import unicodedata                   # Para remover acentos (VIÚVO -> VIUVO)
import urllib.parse                  # Para montar o link do WhatsApp
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

# --- Biblioteca do Telegram (pip install python-telegram-bot) ---
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, ForceReply)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          ContextTypes, CallbackQueryHandler)

# --- Módulos do próprio projeto ---
import config
import database
import notificador_telegram

try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    logger.warning("Locale pt_BR.UTF-8 não encontrado. Usando o padrão do sistema.")


# ==============================================================================
# == CONSTANTES ================================================================
# ==============================================================================

# Textos dos botões do menu fixo. Usados no /start, nos handlers e para
# impedir que um clique no menu seja salvo como resposta do cadastro.
BTN_TAREFAS = "📋 Minhas Tarefas"
BTN_RANKING = "🏆 Ranking do Mês"
BTN_METAS = "🎯 Acompanhar Metas"
BTN_SALDO = "💰 Meu Saldo"
BTN_LOJA = "🏪 Loja de Recompensas"
BTN_NF = "🧾 Enviar Nota Fiscal"
BTN_HISTORICO = "📜 Meu Histórico"
BTN_CONFIDENCIAL = "💬 Canal Confidencial"
BTN_CONQUISTAS = "🏅 Minhas Conquistas"
BTN_DOCUMENTOS = "📄 Meus Documentos"
BTN_SOLICITACOES = "📦 Solicitar Compras/Manutenção"
BTN_AJUDA = "❓ Ajuda"

BOTOES_MENU = {
    BTN_TAREFAS, BTN_RANKING, BTN_METAS, BTN_SALDO, BTN_LOJA, BTN_NF,
    BTN_HISTORICO, BTN_CONFIDENCIAL, BTN_CONQUISTAS, BTN_DOCUMENTOS,
    BTN_SOLICITACOES, BTN_AJUDA,
}

TECLADO_MENU = [
    [BTN_TAREFAS, BTN_RANKING, BTN_METAS],
    [BTN_SALDO, BTN_LOJA, BTN_NF],
    [BTN_HISTORICO, BTN_CONFIDENCIAL],
    [BTN_CONQUISTAS, BTN_DOCUMENTOS],
    [BTN_SOLICITACOES],
    [BTN_AJUDA],
]

# Botões usados pelos gestores. A trava de "feedback pendente" não vale para eles.
PREFIXOS_CALLBACK_GESTAO = (
    "aprovar_gestor_", "reprovar_gestor_", "nf_prep_fwd_", "nf_create_task_",
    "nf_ignore_", "ver_pendencias_", "voltar_lista_funcs",
)

NIVEIS_GESTAO = ('Gestor', 'RH')

# ------------------------------------------------------------------------------
# Onboarding (cadastro inicial)
# REGRA ÚNICA: a etapa salva no banco (UltimaEtapa) é a informação que o bot
# está ESPERANDO receber, e 'pergunta' é o texto que PEDE essa informação.
# Ex.: UltimaEtapa='CPF' -> o bot espera o arquivo do CPF.
# ------------------------------------------------------------------------------
ETAPAS_DOCUMENTO = {'RG', 'CPF', 'CTPS', 'TITULO_ELEITOR'}

WORKFLOW_ONBOARDING = {
    'RG': {
        'pergunta': "Vamos começar. Por favor, envie a <b>FOTO ou PDF do seu RG</b> (frente e verso).",
        'campo_db': 'RG_FileID', 'proxima_etapa': 'CPF',
    },
    'CPF': {
        'pergunta': "Ótimo! Agora envie a <b>FOTO ou PDF do seu CPF</b>.",
        'campo_db': 'CPF_FileID', 'proxima_etapa': 'CTPS',
    },
    'CTPS': {
        'pergunta': ("Perfeito. Envie a <b>FOTO da sua Carteira de Trabalho</b> (página da foto) "
                     "ou o <b>PDF</b> exportado, se ela for digital."),
        'campo_db': 'CTPS_FileID', 'proxima_etapa': 'TITULO_ELEITOR',
    },
    'TITULO_ELEITOR': {
        'pergunta': "Quase lá nos documentos! Envie a <b>FOTO ou PDF do Título de Eleitor</b>.",
        'campo_db': 'TituloEleitor_FileID', 'proxima_etapa': 'ESCOLARIDADE',
    },
    'ESCOLARIDADE': {
        'pergunta': "Documentos salvos! ✅ Agora, digite sua <b>Escolaridade</b> (ex.: Ensino Médio Completo).",
        'campo_db': 'Escolaridade', 'proxima_etapa': 'ESTADO_CIVIL',
    },
    'ESTADO_CIVIL': {
        'pergunta': "Qual o seu <b>Estado Civil</b>? (Solteiro, Casado, Divorciado, Separado ou Viúvo)",
        'campo_db': 'EstadoCivil', 'proxima_etapa': None,  # Decidido pela resposta
    },
    'DATA_CASAMENTO': {
        'pergunta': "Ok. Agora, digite a <b>Data de Casamento</b> (dd/mm/aaaa).",
        'campo_db': 'DataCasamento', 'proxima_etapa': 'NOME_CONJUGUE',
    },
    'NOME_CONJUGUE': {
        'pergunta': "Qual o nome completo do seu <b>Cônjuge</b>?",
        'campo_db': 'NomeConjugue', 'proxima_etapa': 'CPF_CONJUGUE',
    },
    'CPF_CONJUGUE': {
        'pergunta': "Qual o <b>CPF do seu Cônjuge</b>? (apenas números)",
        'campo_db': 'CPFConjugue', 'proxima_etapa': 'FILHOS_QTD',
    },
    'FILHOS_QTD': {
        'pergunta': "Quantos <b>filhos menores de idade</b> você tem? (digite apenas o NÚMERO, ex.: 0, 1, 2)",
        'campo_db': 'QtdFilhos', 'proxima_etapa': None,  # Decidido pela resposta
    },
}

# Permite achar a etapa mesmo se o banco tiver 'ESTADOCIVIL' (sem o _)
_MAPA_ETAPAS_SEM_UNDERLINE = {chave.replace('_', ''): chave for chave in WORKFLOW_ONBOARDING}

PADRAO_ETAPA_FILHO = re.compile(r'^DADOS_FILHO_(\d+)_(NOME|NASC|CPF)$')

ESTADOS_CIVIS_CASADO = {'CASADO', 'CASADA'}
ESTADOS_CIVIS_VALIDOS = {
    'SOLTEIRO', 'SOLTEIRA', 'CASADO', 'CASADA', 'DIVORCIADO', 'DIVORCIADA',
    'VIUVO', 'VIUVA', 'SEPARADO', 'SEPARADA',
}
MAX_FILHOS_CADASTRO = 20


# ==============================================================================
# == FUNÇÕES AUXILIARES ========================================================
# ==============================================================================

def esc(valor) -> str:
    """Escapa um valor para uso seguro dentro de mensagens HTML (< > & viram códigos)."""
    if valor is None:
        return ""
    return html.escape(str(valor))


def agora() -> datetime:
    """
    Data/hora atual. Se config.FUSO_HORARIO existir (ex.: 'America/Cuiaba'),
    usa esse fuso; senão, usa o relógio do computador (comportamento antigo).
    """
    fuso = getattr(config, 'FUSO_HORARIO', None)
    if fuso:
        try:
            return datetime.now(ZoneInfo(fuso)).replace(tzinfo=None)
        except Exception as e:
            logger.warning(f"FUSO_HORARIO inválido em config.py ('{fuso}'): {e}")
    return datetime.now()


def hoje() -> date:
    return agora().date()


def sem_acentos(texto: str) -> str:
    """Remove acentos: 'VIÚVO' -> 'VIUVO'."""
    normalizado = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in normalizado if not unicodedata.combining(c))


def eh_gestor(funcionario) -> bool:
    """True se o funcionário tem nível de acesso de gestão (Gestor ou RH)."""
    return bool(funcionario) and getattr(funcionario, 'NivelAcesso', None) in NIVEIS_GESTAO


def eh_encaminhada(message) -> bool:
    """
    True se a mensagem foi encaminhada de outro chat.
    Usa getattr porque a versão 21+ da biblioteca trocou 'forward_from' por
    'forward_origin'. Acessar 'forward_from' direto gerava erro nas versões novas.
    """
    return bool(
        getattr(message, 'forward_origin', None)
        or getattr(message, 'forward_from', None)
        or getattr(message, 'forward_from_chat', None)
    )


def eh_pdf(documento) -> bool:
    """True se o documento enviado é um PDF (mime_type pode vir vazio)."""
    if not documento:
        return False
    mime = (documento.mime_type or '').lower()
    nome = (documento.file_name or '').lower()
    return mime == 'application/pdf' or nome.endswith('.pdf')


def eh_imagem_como_arquivo(documento) -> bool:
    """True se a pessoa enviou uma imagem como 'Arquivo' em vez de 'Foto'."""
    return bool(documento) and (documento.mime_type or '').lower().startswith('image/')


def extrair_file_id_foto_ou_pdf(message):
    """Devolve o file_id de uma foto ou de um PDF. Qualquer outra coisa -> None."""
    if message.photo:
        return message.photo[-1].file_id  # [-1] = maior resolução
    if eh_pdf(message.document):
        return message.document.file_id
    return None


def cpf_valido(cpf_digitos: str) -> bool:
    """Confere o tamanho e os 2 dígitos verificadores do CPF."""
    if len(cpf_digitos) != 11 or cpf_digitos == cpf_digitos[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf_digitos[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11
        if digito == 10:
            digito = 0
        if digito != int(cpf_digitos[tamanho]):
            return False
    return True


def validar_data_passada(texto: str):
    """Aceita 'dd/mm/aaaa' que não esteja no futuro. Devolve o texto padronizado ou None."""
    try:
        data_obj = datetime.strptime(texto.strip(), '%d/%m/%Y').date()
    except ValueError:
        return None
    if data_obj > hoje():
        return None
    return data_obj.strftime('%d/%m/%Y')


def barra_de_progresso(percentual: float) -> str:
    """Barra de 10 blocos. Limita entre 0% e 100% para não 'estourar'."""
    blocos = max(0, min(10, int(percentual // 10)))
    return '▓' * blocos + '░' * (10 - blocos)


def montar_loja(produtos):
    """Monta o texto e os botões da loja (usado no menu e no botão Voltar)."""
    keyboard = []
    if produtos:
        texto = "🏪 <b>Loja de Recompensas</b> 🏪\n\nEscolha um item para ver os detalhes e resgatar:"
        for produto in produtos:
            estoque_str = f" ({produto.EstoqueDisponivel} un.)" if produto.EstoqueDisponivel is not None else ""
            texto_botao = f"{produto.Nome} - {produto.CustoEmPontos} pts{estoque_str}"
            keyboard.append([InlineKeyboardButton(texto_botao, callback_data=f"ver_produto_{produto.ProdutoID}")])
    else:
        texto = ("🏪 <b>Loja de Recompensas</b> 🏪\n\n"
                 "Não temos itens físicos no momento, mas você pode usar seu saldo abaixo:")
    # Botão fixo de Abater na Comanda, sempre no final da lista
    keyboard.append([InlineKeyboardButton("🍔 Abater na Comanda", callback_data="abater_comanda")])
    return texto, InlineKeyboardMarkup(keyboard)


def taxa_de_conversao() -> float:
    """Valor em R$ de 1 ponto. Um único lugar para evitar valores diferentes pelo código."""
    return float(getattr(config, 'TAXA_CONVERSAO_PONTO_REAL', 0.03))


# ===================================================================
# == SALA DE COMANDO (GESTORES) E COMANDA ===========================
# ===================================================================

async def iniciar_abate_comanda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disparado quando o usuário clica no botão 'Abater na Comanda'."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    func = database.buscar_funcionario_por_chat_id(update.effective_user.id)

    if not func:
        await query.answer("❌ Seu Telegram não está vinculado a um cadastro de funcionário.", show_alert=True)
        return

    # Trava: feedback do dia anterior pendente
    if not eh_gestor(func) and not database.verificar_feedback_dia_anterior(func.FuncionarioID):
        await query.answer("⚠️ Ação bloqueada! Você tem feedback pendente do dia anterior.", show_alert=True)
        return

    await query.answer()  # Só confirma o clique depois de passar pelas travas (UMA única vez)

    try:
        # Usa a MESMA fonte de saldo do botão "Meu Saldo"
        saldo_pontos = database.buscar_saldo_funcionario(func.FuncionarioID) or 0
        taxa = taxa_de_conversao()
        saldo_reais = saldo_pontos * taxa

        context.user_data['estado'] = 'aguardando_valor_comanda'

        mensagem = (
            f"🍔 <b>Abater Saldo em Comanda</b>\n\n"
            f"Seu saldo atual é de: <b>R$ {saldo_reais:.2f}</b> ({saldo_pontos} pontos).\n\n"
            f"👉 Digite o valor exato em Reais que você consumiu e deseja abater.\n"
            f"<i>(Exemplo: 15.50 ou 20)</i>\n\n"
            f"Para desistir, digite /cancelar."
        )
        await context.bot.send_message(chat_id=chat_id, text=mensagem, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Erro ao processar abate de comanda: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text="❌ Ocorreu um erro interno ao calcular seu saldo. Tente novamente mais tarde.")


async def processar_valor_comanda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa o valor em R$ digitado e registra a solicitação de abate."""
    texto = update.message.text.strip().replace('R$', '').replace(' ', '').replace(',', '.')

    try:
        valor_reais = round(float(texto), 2)
        if valor_reais <= 0:
            raise ValueError("Valor zerado ou negativo.")
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 15.50) ou /cancelar para sair.")
        return  # Mantém o estado para a pessoa tentar de novo

    func = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not func:
        context.user_data.pop('estado', None)
        await update.message.reply_text("❌ Não encontrei seu cadastro no sistema.")
        return

    taxa = taxa_de_conversao()
    if taxa <= 0:
        context.user_data.pop('estado', None)
        logger.error("TAXA_CONVERSAO_PONTO_REAL precisa ser maior que zero em config.py")
        await update.message.reply_text("❌ Configuração de conversão inválida. Avise o gestor.")
        return

    # Saldo RELIDO do banco agora (pode ter mudado desde o clique no botão)
    saldo_pontos = database.buscar_saldo_funcionario(func.FuncionarioID) or 0
    saldo_reais = saldo_pontos * taxa

    # round(...,6) elimina "sujeira" de ponto flutuante (15/0.03 = 499.9999...)
    # e ceil arredonda para CIMA, para nunca cobrar menos pontos que o devido.
    pontos_necessarios = math.ceil(round(valor_reais / taxa, 6))

    context.user_data.pop('estado', None)  # Daqui em diante a operação termina

    if pontos_necessarios > saldo_pontos:
        await update.message.reply_html(
            f"❌ <b>Saldo Insuficiente!</b>\nVocê tentou abater R$ {valor_reais:.2f}, "
            f"mas possui apenas R$ {saldo_reais:.2f}.\nOperação cancelada."
        )
        return

    sucesso, mensagem, resgate_id = database.registrar_solicitacao_comanda(
        func.FuncionarioID, valor_reais, pontos_necessarios
    )

    if not sucesso:
        await update.message.reply_text(f"❌ Ocorreu um erro: {mensagem}")
        return

    await update.message.reply_html(
        f"⏳ <b>Solicitação Enviada!</b>\n\n{esc(mensagem)}\n"
        f"Os {pontos_necessarios} pontos foram reservados do seu saldo."
    )

    alerta = (
        f"🔔 <b>Nova Solicitação de Abate na Comanda</b> 🔔\n\n"
        f"👤 <b>Funcionário:</b> {esc(func.NomeCompleto)}\n"
        f"💰 <b>Valor a Abater:</b> R$ {valor_reais:.2f}\n"
        f"💎 <b>Pontos:</b> {pontos_necessarios} pts\n\n"
        f"Acesse o sistema para aprovar na aba 'Loja e Resgates'."
    )
    try:
        await context.bot.send_message(chat_id=config.GESTOR_GROUP_CHAT_ID, text=alerta, parse_mode=ParseMode.HTML)
    except TelegramError as e:
        logger.error(f"Solicitação de comanda {resgate_id} registrada, mas falhou ao avisar os gestores: {e}")


async def status_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia o status atual da meta principal para o grupo de gestão."""
    if update.effective_chat.id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando é exclusivo para o grupo de gestão.")
        return

    dados_meta = database.buscar_meta_principal_do_dia()
    if not dados_meta or not dados_meta.get('valor_meta'):
        await update.message.reply_text("Nenhuma meta principal está ativa no momento.")
        return

    nome = dados_meta['nome_meta']
    atingido = float(dados_meta['valor_atingido'] or 0)
    total = float(dados_meta['valor_meta'])
    percentual = (atingido / total) * 100 if total > 0 else 0

    # Projeção: média diária até hoje x total de dias do mês
    data_hoje = hoje()
    dias_no_mes = calendar.monthrange(data_hoje.year, data_hoje.month)[1]
    media_diaria = atingido / data_hoje.day if data_hoje.day > 0 else 0
    projecao = media_diaria * dias_no_mes

    mensagem = (
        f"📊 <b>Status da Meta: {esc(nome)}</b> 📊\n\n"
        f"<code>{barra_de_progresso(percentual)}</code>  <b>{percentual:.2f}%</b>\n\n"
        f"💰 <b>Atingido:</b> <code>R$ {atingido:,.2f}</code>\n"
        f"🎯 <b>Meta:</b> <code>R$ {total:,.2f}</code>\n\n"
        f"📈 <b>Projeção Final:</b> <code>R$ {projecao:,.2f}</code>"
    )
    await update.message.reply_html(mensagem)


async def lancar_venda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra o valor da apuração diária enviado pelo gestor: /lancar 1250.50"""
    if update.effective_chat.id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando é exclusivo para o grupo de gestão.")
        return

    gestor = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not gestor:
        await update.message.reply_text("Erro: Seu usuário do Telegram não foi encontrado no sistema para registrar esta ação.")
        return

    if not context.args:
        await update.message.reply_html("Por favor, informe o valor a ser lançado.\nExemplo: <code>/lancar 1250.50</code>")
        return

    try:
        valor_dia = float(context.args[0].replace('R$', '').replace(',', '.'))
        if valor_dia < 0:
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_html("Valor inválido. Use apenas números.\nExemplo: <code>/lancar 1250.50</code>")
        return

    meta_id = database.buscar_meta_ativa_id_hoje()
    if not meta_id:
        await update.message.reply_text("Erro: Nenhuma meta principal está ativa para hoje. Não é possível lançar.")
        return

    data_hoje_str = hoje().strftime('%Y-%m-%d')
    sucesso, resultado = database.lancar_apuracao_diaria(meta_id, data_hoje_str, valor_dia, gestor.FuncionarioID)

    if not sucesso:
        await update.message.reply_text(f"❌ Falha ao registrar o lançamento.\nErro: {resultado}")
        return

    apuracao_id = resultado
    await update.message.reply_html(
        f"✅ <b>Sucesso!</b> Lançamento de <code>R$ {valor_dia:,.2f}</code> registrado por {esc(gestor.NomeCompleto)}.\n\n"
        "Aguarde, estou atualizando o status..."
    )

    try:
        database.verificar_e_premiar_meta_diaria(apuracao_id, data_hoje_str, valor_dia, meta_id)
        logger.info(f"Verificação de meta diária (ID {apuracao_id}) acionada via Telegram.")
    except Exception as e_premio:
        logger.error(f"Erro ao verificar/premiar meta diária após lançamento via Telegram: {e_premio}", exc_info=True)

    await status_meta(update, context)


async def pendencias_gestor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pendencias - lista funcionários para o gestor ver as tarefas pendentes."""
    if update.effective_chat.id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando só pode ser usado no grupo de gestão.")
        return
    funcionarios = database.listar_funcionarios()
    if not funcionarios:
        await update.message.reply_text("Não há funcionários cadastrados no sistema.")
        return
    keyboard = [[InlineKeyboardButton(f.NomeCompleto, callback_data=f"ver_pendencias_{f.FuncionarioID}")]
                for f in funcionarios]
    await update.message.reply_text("Selecione um funcionário para ver as tarefas pendentes:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))


# ===================================================================
# == COMANDOS GERAIS ================================================
# ===================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)

    if not funcionario:
        await update.message.reply_text(
            "Olá! Parece que seu usuário não foi encontrado no sistema. Por favor, contate seu gestor.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    status_onboarding = database.buscar_onboarding_status(funcionario.FuncionarioID)
    status_workflow = (getattr(status_onboarding, 'StatusWorkflow', None) or '').strip() if status_onboarding else ''

    # Cadastro incompleto: esconde o menu e dá instrução clara
    if status_onboarding and status_workflow != 'Completo' and not eh_gestor(funcionario):
        await update.message.reply_html(
            f"👋 Olá, <b>{esc(funcionario.NomeCompleto)}</b>!\n\n"
            "Precisamos concluir seu cadastro antes de liberar o sistema.\n\n"
            "👉 <b>Digite 'Começar'</b> (ou envie qualquer mensagem) para enviar seus documentos.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    await update.message.reply_html(
        f"Bem-vindo(a) de volta, <b>{esc(funcionario.NomeCompleto)}</b>! 👋\n\nUse os botões abaixo para interagir:",
        reply_markup=ReplyKeyboardMarkup(TECLADO_MENU, resize_keyboard=True)
    )


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /cancelar - limpa qualquer ação em andamento (comanda, compra, denúncia...).
    Antes esse comando não existia: o texto '/cancelar' era filtrado e nunca chegava ao bot.
    """
    context.user_data.clear()
    await update.message.reply_text("Ação cancelada. Use os botões do menu.")

    # Se o cadastro estiver em andamento, lembra a pergunta atual (o progresso fica salvo no banco)
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if funcionario and not eh_gestor(funcionario):
        status = database.buscar_onboarding_status(funcionario.FuncionarioID)
        if status and (getattr(status, 'StatusWorkflow', None) or '').strip() == 'Em Progresso':
            etapa = normalizar_etapa(getattr(status, 'UltimaEtapa', None))
            pergunta = pergunta_da_etapa(etapa)
            if pergunta:
                await update.message.reply_html(
                    "📝 Seu cadastro continua de onde parou. Responda quando puder:\n\n" + pergunta
                )


async def obter_id_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(f"O ID deste chat é: <code>{update.effective_chat.id}</code>")


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto_ajuda = (
        "Olá! Eu sou seu assistente de gamificação. Aqui estão os comandos:\n\n"
        "<b>Comandos Principais (Botões):</b>\n"
        "📋 <b>Minhas Tarefas</b>: Mostra sua lista de tarefas pendentes para hoje.\n"
        "🏆 <b>Ranking do Mês</b>: Exibe a classificação de desempenho atual.\n"
        "🎯 <b>Acompanhar Metas</b>: Mostra o progresso da meta da equipe.\n"
        "💰 <b>Meu Saldo</b>: Mostra seus pontos acumulados e o valor em R$.\n"
        "🏪 <b>Loja de Recompensas</b>: Permite trocar seus pontos por prêmios.\n"
        "🧾 <b>Enviar Nota Fiscal</b>: Envia a foto de uma nota recebida.\n"
        "📜 <b>Meu Histórico</b>: Exibe suas últimas 10 atividades.\n"
        "🏅 <b>Minhas Conquistas</b>: Lista suas conquistas desbloqueadas.\n"
        "📄 <b>Meus Documentos</b>: Acessa documentos pessoais, como holerites.\n\n"
        "💬 <b>Canal Confidencial</b>:\n"
        "   Envia uma sugestão, reclamação ou denúncia de forma <b>100% ANÔNIMA</b> para a gestão.\n\n"
        "↩️ <b>/cancelar</b>: Desiste de qualquer ação em andamento."
    )
    await update.message.reply_html(texto_ajuda)


async def abrir_central_solicitacoes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Botão '📦 Solicitar Compras/Manutenção' (antes era um lambda difícil de depurar)."""
    await update.message.reply_text(
        "Acessando Central...",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Abrir Menu", callback_data="menu_solicitacoes")]])
    )


# ===================================================================
# == FUNÇÕES DO FUNCIONÁRIO =========================================
# ===================================================================

async def tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None) -> None:
    chat_id = update.effective_chat.id
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario:
        await context.bot.send_message(chat_id, "Desculpe, não consegui encontrar seu cadastro no sistema.")
        return

    if await _interceptar_comandos_e_pendencias(update, context):
        return

    tarefas_do_dia = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)
    if not tarefas_do_dia:
        texto = "Você não tem nenhuma tarefa pendente para hoje. Bom trabalho! ✨"
        if query:
            await query.edit_message_text(texto)
        else:
            await context.bot.send_message(chat_id, texto)
        return

    texto = "📋 <b>Suas Tarefas para Hoje:</b>\n\nClique em uma tarefa para ver os detalhes:"
    keyboard = [[InlineKeyboardButton(f"👀 {t.Titulo} ({t.Pontos} pts)", callback_data=f"ver_tarefa_{t.AtribuicaoID}")]
                for t in tarefas_do_dia]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if query:
        await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_message(chat_id, texto, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _interceptar_comandos_e_pendencias(update, context):
        return

    try:
        ranking_cozinha = database.calcular_ranking_desempenho(setor_filtro='Cozinha')
        ranking_loja = database.calcular_ranking_desempenho(setor_filtro='Loja')
    except Exception as e:
        logger.exception(f"Erro ao buscar dados do ranking: {e}")
        await update.message.reply_text(
            "❌ Desculpe, ocorreu um erro ao buscar os dados do ranking no momento.\n"
            "Tente novamente mais tarde ou contate o suporte se o problema persistir."
        )
        return

    if not ranking_cozinha and not ranking_loja:
        await update.message.reply_text("Ainda não há dados suficientes para gerar os rankings este mês.")
        return

    def formatar_setor(titulo: str, lista) -> str:
        bloco = f"\n{titulo}\n"
        if not lista:
            return bloco + "<i>Sem dados para este setor no momento.</i>\n"
        icones = ["🥇", "🥈", "🥉"]
        for i, dados in enumerate(lista):
            posicao = icones[i] if i < len(icones) else f" {i + 1}."
            nome = esc(dados.get('NomeCompleto') or "Desconhecido")
            detalhes = f"(Desemp: {esc(dados.get('Desempenho'))}%, Pts: {esc(dados.get('PontosGanhos'))})"
            bloco += f"{posicao} {nome} - <b>Score: {esc(dados.get('ScoreHibrido'))}</b>\n   {detalhes}\n"
        return bloco

    texto_final = (
        "🏆 <b>Rankings de Desempenho do Mês</b> 🏆\n\n"
        "O <i>Score Final</i> equilibra Confiabilidade e Esforço (50%/50%).\n"
        + formatar_setor("🍳 <b>--- Ranking Cozinha ---</b> 🍳", ranking_cozinha)
        + formatar_setor("🛒 <b>--- Ranking Atendimento/Loja ---</b> 🛒", ranking_loja)
    )
    await update.message.reply_html(texto_final)


async def meu_historico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia ao usuário um resumo de suas últimas 10 atividades."""
    if await _interceptar_comandos_e_pendencias(update, context):
        return

    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario:
        await update.message.reply_text("Desculpe, não consegui encontrar seu cadastro no sistema.")
        return

    historico_completo = database.obter_historico_funcionario(funcionario.FuncionarioID)
    if not historico_completo:
        await update.message.reply_text("Você ainda não possui nenhuma atividade registrada no seu histórico.")
        return

    icones_status = {'Aprovada': "✅", 'Recusada': "❌", 'Pendente (Não Entregue)': "⏳"}
    texto = "📜 <b>Seu Histórico Recente (últimas 10 atividades)</b> 📜\n\n"

    for item in historico_completo[:10]:
        icone = icones_status.get(item.Status, "❓")
        pontos = item.PontosGanhos if item.PontosGanhos is not None else 0
        texto += f"{icone} <b>{esc(item.Titulo or 'Sem Título')}</b>\n"
        texto += f"    - Status: {esc(item.Status)}\n"
        texto += f"    - Pontos: {pontos}\n"
        if item.MotivoRecusa:
            texto += f"    - Motivo: <i>{esc(item.MotivoRecusa)}</i>\n"
        texto += "\n"

    await update.message.reply_html(texto)


async def meu_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra o saldo de pontos cumulativo do funcionário."""
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario:
        await update.message.reply_text("Não encontrei seu cadastro no sistema.")
        return

    saldo_pontos = database.buscar_saldo_funcionario(funcionario.FuncionarioID) or 0
    valor_monetario = saldo_pontos * taxa_de_conversao()

    await update.message.reply_html(
        f"💰 <b>Seu Saldo Atual</b> 💰\n\n"
        f"Você acumulou: <b>{saldo_pontos} pontos</b>\n\n"
        f"Isso equivale a <b>R$ {valor_monetario:.2f}</b> para troca na nossa Loja de Recompensas!\n\n"
        "Continue assim para resgatar prêmios incríveis! ✨"
    )


async def loja_recompensas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe os produtos da loja como um menu de botões."""
    texto, reply_markup = montar_loja(database.listar_produtos_loja())
    await context.bot.send_message(update.effective_chat.id, texto, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def acompanhar_metas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia para o funcionário o status da meta principal em porcentagem."""
    dados_meta = database.buscar_meta_principal_do_dia()
    if not dados_meta or not dados_meta.get('valor_meta'):
        await update.message.reply_text("Nenhuma meta de equipe está ativa no momento. Foco nas tarefas individuais! 💪")
        return

    atingido = float(dados_meta['valor_atingido'] or 0)
    total = float(dados_meta['valor_meta'])
    percentual = (atingido / total) * 100 if total > 0 else 0

    if percentual >= 100:
        frase = "META BATIDA! Parabéns, equipe! 🎉"
    elif percentual >= 75:
        frase = "Estamos quase lá! Este é o nosso progresso até agora:"
    else:
        frase = "Este é o nosso progresso até agora:"

    await update.message.reply_html(
        f"🎯 <b>Meta da Equipe: {esc(dados_meta['nome_meta'])}</b> 🎯\n\n"
        f"{frase}\n\n"
        f"<code>{barra_de_progresso(percentual)}</code>\n\n"
        f"🏁 <b>Progresso: {percentual:.2f}% de 100%</b>\n\n"
        "Vamos com tudo, equipe! 🚀"
    )


async def minhas_conquistas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a lista de conquistas já desbloqueadas pelo funcionário."""
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario:
        await update.message.reply_text("Desculpe, não consegui encontrar seu cadastro no sistema.")
        return

    conquistas_ganhas = database.listar_conquistas_por_funcionario(funcionario.FuncionarioID)
    if not conquistas_ganhas:
        await update.message.reply_text("Você ainda não desbloqueou nenhuma conquista. Continue se esforçando! 💪")
        return

    texto = (f"🏅 <b>Suas Conquistas Desbloqueadas</b> ({len(conquistas_ganhas)}) 🏅\n\n"
             "Parabéns pelas suas realizações!\n")
    for conquista in conquistas_ganhas:
        data_formatada = conquista.DataConquista.strftime('%d/%m/%Y') if conquista.DataConquista else "N/A"
        texto += (
            f"\n--------------------\n"
            f"{esc(conquista.Icone)} <b>{esc(conquista.Nome)}</b>\n"
            f"<i>{esc(conquista.Descricao)}</i>\n"
            f"<pre>Desbloqueada em: {data_formatada}</pre>\n"
        )
    await update.message.reply_html(texto)


async def solicitar_documentos_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia a solicitação de DOCUMENTOS PESSOAIS com verificação de segurança."""
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario or not funcionario.VerificadorCPF:
        await update.message.reply_text(
            "Desculpe, esta funcionalidade não está habilitada para você. "
            "Por favor, contate o RH para cadastrar seu código de verificação."
        )
        return
    context.user_data['aguardando_verificador_cpf'] = True
    await update.message.reply_text("Para sua segurança, por favor, digite os 3 primeiros dígitos do seu CPF.")


async def solicitar_feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o Canal Confidencial (mensagem anônima)."""
    await update.message.reply_html(
        "Este é o seu <b>Canal Confidencial</b>.\n\n"
        "Use este espaço para enviar sugestões, reclamações ou denúncias de forma <b>100% ANÔNIMA</b>.\n\n"
        "⚠️ <b>IMPORTANTE:</b> Sua identidade <b>NÃO</b> será registrada nem enviada à gestão. "
        "O sistema foi programado para descartar seu nome e ID de usuário nesta operação.\n\n"
        "Por favor, digite sua mensagem completa abaixo e pressione Enviar. (Ou digite /cancelar para sair)."
    )
    context.user_data['aguardando_denuncia_anonima'] = True
    context.user_data.pop('aguardando_assunto_feedback', None)


async def solicitar_foto_nf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Define o estado para aguardar a foto da Nota Fiscal."""
    logger.info(f"Solicitação de envio de NF recebida de {update.effective_user.id}")
    context.user_data['aguardando_nota_fiscal'] = True
    await update.message.reply_text(
        "Entendido. Por favor, envie agora a foto da Nota Fiscal que você recebeu.\n\n"
        "(Se mudar de ideia, digite /cancelar)"
    )


# ===================================================================
# == ONBOARDING (CADASTRO INICIAL) ==================================
# ===================================================================

def normalizar_etapa(raw_etapa) -> str:
    """Limpa a etapa vinda do banco (espaços, caracteres invisíveis) e padroniza."""
    if raw_etapa is None:
        return 'INICIO'
    etapa = "".join(c for c in str(raw_etapa) if c.isalnum() or c == '_').upper()
    if not etapa:
        return 'INICIO'
    if etapa in WORKFLOW_ONBOARDING or etapa in ('INICIO', 'CONCLUIR') or PADRAO_ETAPA_FILHO.match(etapa):
        return etapa
    # Tenta achar sem o underline (ex.: 'ESTADOCIVIL' -> 'ESTADO_CIVIL')
    return _MAPA_ETAPAS_SEM_UNDERLINE.get(etapa.replace('_', ''), etapa)


def pergunta_da_etapa(etapa: str):
    """Texto (HTML) que pede a informação da etapa atual. None se a etapa for desconhecida."""
    if etapa in WORKFLOW_ONBOARDING:
        return WORKFLOW_ONBOARDING[etapa]['pergunta']
    if etapa == 'INICIO':
        return WORKFLOW_ONBOARDING['RG']['pergunta']
    combinacao = PADRAO_ETAPA_FILHO.match(etapa)
    if combinacao:
        numero, campo = int(combinacao.group(1)), combinacao.group(2)
        if campo == 'NOME':
            return f"Qual o <b>nome completo</b> do(a) {numero}º filho(a)?"
        if campo == 'NASC':
            return f"Digite a <b>Data de Nascimento</b> (dd/mm/aaaa) do(a) {numero}º filho(a):"
        return (f"Digite o <b>CPF</b> (apenas números) do(a) {numero}º filho(a).\n"
                f"<i>Se ainda não tiver CPF, digite: não tem</i>")
    return None


async def _enviar_html(context, chat_id, texto):
    await context.bot.send_message(chat_id, texto, parse_mode=ParseMode.HTML)


async def onboarding_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Máquina de estados do cadastro inicial. O progresso fica SALVO NO BANCO
    (UltimaEtapa), então nada se perde se o bot reiniciar.
    Recebe fotos/PDFs nas etapas de documento e texto nas demais.
    """
    chat_id = update.effective_chat.id
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario:
        await context.bot.send_message(chat_id, "Desculpe, não consegui encontrar seu cadastro no sistema.")
        return

    status = database.buscar_onboarding_status(funcionario.FuncionarioID)
    if not status:
        await context.bot.send_message(chat_id, "Não há cadastro pendente para você. Contate o RH se achar que isso é um erro.")
        return
    if (getattr(status, 'StatusWorkflow', None) or '').strip() == 'Completo':
        return  # Nada a fazer

    etapa = normalizar_etapa(getattr(status, 'UltimaEtapa', None))
    logger.info(f"ONBOARDING: FuncionarioID={funcionario.FuncionarioID} etapa='{etapa}'")
    func_id = funcionario.FuncionarioID
    msg = update.message  # Pode ser None se veio de um clique em botão

    # --- Etapa INICIO: qualquer interação começa o cadastro ---
    if etapa == 'INICIO':
        database.iniciar_onboarding_funcionario(func_id)   # Status -> 'Em Progresso'
        database.atualizar_onboarding_etapa(func_id, 'RG')  # Agora esperamos o RG
        await _enviar_html(
            context, chat_id,
            "Olá! Para finalizar seu registro, preciso de alguns documentos.\n\n" + WORKFLOW_ONBOARDING['RG']['pergunta']
        )
        return

    # --- Etapa CONCLUIR: tudo coletado, só falta finalizar (ex.: caiu antes de finalizar) ---
    if etapa == 'CONCLUIR':
        await _finalizar_onboarding_e_redirecionar(update, context, funcionario)
        return

    pergunta_atual = pergunta_da_etapa(etapa)
    if pergunta_atual is None:
        logger.error(f"ONBOARDING: etapa desconhecida '{etapa}' para FuncionarioID={func_id}")
        await context.bot.send_message(chat_id, "Houve um problema no seu cadastro. Por favor, avise o RH.")
        return

    # Sem mensagem (veio de botão): apenas repete a pergunta atual
    if msg is None:
        await _enviar_html(context, chat_id, "📝 Continue seu cadastro:\n\n" + pergunta_atual)
        return

    texto = msg.text.strip() if msg.text else None

    # Clique em botão do menu antigo não pode virar resposta do cadastro
    if texto in BOTOES_MENU:
        await _enviar_html(context, chat_id,
                           "⚠️ Primeiro precisamos concluir seu cadastro.\n\n" + pergunta_atual)
        return

    # ---------- ETAPAS DE DOCUMENTO (foto ou PDF) ----------
    if etapa in ETAPAS_DOCUMENTO:
        file_id = extrair_file_id_foto_ou_pdf(msg)
        if not file_id:
            aviso = ("⚠️ Formato não aceito. Envie uma <b>FOTO</b> ou um arquivo <b>PDF</b>."
                     if msg.document else
                     "⚠️ Nesta etapa preciso que você envie uma <b>FOTO</b> ou <b>PDF</b>.")
            await _enviar_html(context, chat_id, f"{aviso}\n\n{pergunta_atual}")
            return

        config_etapa = WORKFLOW_ONBOARDING[etapa]
        proxima = config_etapa['proxima_etapa']
        database.atualizar_onboarding_etapa(func_id, proxima, (config_etapa['campo_db'], file_id))
        await _enviar_html(context, chat_id, pergunta_da_etapa(proxima))
        return

    # ---------- ETAPAS DE TEXTO ----------
    if not texto:
        await _enviar_html(context, chat_id,
                           "⚠️ Nesta etapa preciso que você <b>DIGITE</b> a resposta.\n\n" + pergunta_atual)
        return

    if etapa == 'ESTADO_CIVIL':
        resposta = sem_acentos(texto).upper().replace('(A)', '').strip()
        if resposta not in ESTADOS_CIVIS_VALIDOS:
            await _enviar_html(context, chat_id,
                               "⚠️ Estado Civil inválido. Escolha: Solteiro, Casado, Divorciado, Separado ou Viúvo.")
            return
        proxima = 'DATA_CASAMENTO' if resposta in ESTADOS_CIVIS_CASADO else 'FILHOS_QTD'
        database.atualizar_onboarding_etapa(func_id, proxima, ('EstadoCivil', resposta))
        await _enviar_html(context, chat_id, pergunta_da_etapa(proxima))
        return

    if etapa == 'DATA_CASAMENTO':
        data_ok = validar_data_passada(texto)
        if not data_ok:
            await _enviar_html(context, chat_id,
                               "⚠️ Data inválida. Digite no formato <b>dd/mm/aaaa</b> (ex.: 15/03/2018).")
            return
        database.atualizar_onboarding_etapa(func_id, 'NOME_CONJUGUE', ('DataCasamento', data_ok))
        await _enviar_html(context, chat_id, pergunta_da_etapa('NOME_CONJUGUE'))
        return

    if etapa == 'CPF_CONJUGUE':
        cpf_limpo = ''.join(filter(str.isdigit, texto))
        if not cpf_valido(cpf_limpo):
            await _enviar_html(context, chat_id, "⚠️ CPF inválido. Confira os 11 números e digite novamente.")
            return
        database.atualizar_onboarding_etapa(func_id, 'FILHOS_QTD', ('CPFConjugue', cpf_limpo))
        await _enviar_html(context, chat_id, pergunta_da_etapa('FILHOS_QTD'))
        return

    if etapa == 'FILHOS_QTD':
        try:
            qtd = int(texto)
            if qtd < 0 or qtd > MAX_FILHOS_CADASTRO:
                raise ValueError
        except ValueError:
            await _enviar_html(context, chat_id,
                               "⚠️ Digite apenas um <b>NÚMERO</b> válido para a quantidade de filhos (ex.: 0, 1, 2).")
            return

        if qtd == 0:
            database.atualizar_onboarding_etapa(func_id, 'CONCLUIR', ('QtdFilhos', 0))
            await _finalizar_onboarding_e_redirecionar(update, context, funcionario)
            return

        database.salvar_dados_filhos(func_id, json.dumps([]))  # Começa a lista de filhos do zero
        database.atualizar_onboarding_etapa(func_id, 'DADOS_FILHO_1_NOME', ('QtdFilhos', qtd))
        await _enviar_html(context, chat_id, f"Ok, vamos coletar os dados de <b>{qtd} filho(s)</b>.")
        await _enviar_html(context, chat_id, pergunta_da_etapa('DADOS_FILHO_1_NOME'))
        return

    if PADRAO_ETAPA_FILHO.match(etapa):
        await _coletar_dados_filhos_e_avancar(update, context, funcionario, texto, etapa, status)
        return

    # Etapas simples de texto (ESCOLARIDADE, NOME_CONJUGUE)
    config_etapa = WORKFLOW_ONBOARDING.get(etapa)
    if config_etapa and config_etapa.get('proxima_etapa'):
        proxima = config_etapa['proxima_etapa']
        database.atualizar_onboarding_etapa(func_id, proxima, (config_etapa['campo_db'], texto))
        await _enviar_html(context, chat_id, pergunta_da_etapa(proxima))
        return

    logger.error(f"ONBOARDING: sem regra para a etapa '{etapa}' (FuncionarioID={func_id})")
    await context.bot.send_message(chat_id, "Houve um problema no seu cadastro. Por favor, avise o RH.")


async def _coletar_dados_filhos_e_avancar(update, context, funcionario, valor_recebido, etapa, status_onboarding):
    """
    Coleta Nome -> Nascimento -> CPF de cada filho e salva a lista em JSON.
    Tudo é lido do banco, então funciona mesmo se o bot reiniciar no meio.
    """
    chat_id = update.effective_chat.id
    combinacao = PADRAO_ETAPA_FILHO.match(etapa)
    filho_atual, campo = int(combinacao.group(1)), combinacao.group(2)

    try:
        qtd_filhos = int(getattr(status_onboarding, 'QtdFilhos', 0) or 0)
    except (TypeError, ValueError):
        qtd_filhos = 0
    if qtd_filhos < filho_atual:  # Segurança: nunca menos que o filho em andamento
        qtd_filhos = filho_atual

    try:
        dados_filhos = json.loads(getattr(status_onboarding, 'DadosFilhos', None) or '[]')
        if not isinstance(dados_filhos, list):
            dados_filhos = []
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"DadosFilhos inválido no banco para FuncionarioID={funcionario.FuncionarioID}. Recomeçando lista.")
        dados_filhos = []

    while len(dados_filhos) < filho_atual:
        dados_filhos.append({})
    idx = filho_atual - 1

    if campo == 'NOME':
        dados_filhos[idx]['Nome'] = valor_recebido
        proxima_etapa = f'DADOS_FILHO_{filho_atual}_NASC'

    elif campo == 'NASC':
        data_ok = validar_data_passada(valor_recebido)
        if not data_ok:
            await _enviar_html(context, chat_id, "⚠️ Data inválida. Digite no formato <b>dd/mm/aaaa</b>.")
            return
        dados_filhos[idx]['Nasc'] = data_ok
        proxima_etapa = f'DADOS_FILHO_{filho_atual}_CPF'

    else:  # CPF
        resposta = sem_acentos(valor_recebido).upper().strip()
        if resposta in ('NAO TEM', 'NAO POSSUI', 'NAO', 'NENHUM'):
            dados_filhos[idx]['CPF'] = ''
        else:
            cpf_limpo = ''.join(filter(str.isdigit, valor_recebido))
            if not cpf_valido(cpf_limpo):
                await _enviar_html(context, chat_id,
                                   "⚠️ CPF inválido. Confira os 11 números ou digite <b>não tem</b>.")
                return
            dados_filhos[idx]['CPF'] = cpf_limpo
        proxima_etapa = f'DADOS_FILHO_{filho_atual + 1}_NOME' if filho_atual < qtd_filhos else 'CONCLUIR'

    database.salvar_dados_filhos(funcionario.FuncionarioID, json.dumps(dados_filhos, ensure_ascii=False))
    database.atualizar_onboarding_etapa(funcionario.FuncionarioID, proxima_etapa)

    if proxima_etapa == 'CONCLUIR':
        await _finalizar_onboarding_e_redirecionar(update, context, funcionario)
    else:
        await _enviar_html(context, chat_id, pergunta_da_etapa(proxima_etapa))


async def _finalizar_onboarding_e_redirecionar(update, context, funcionario):
    """Marca o cadastro como completo, avisa o gestor e orienta sobre o exame admissional."""
    database.finalizar_onboarding_e_notificar_gestor(funcionario.FuncionarioID)

    mensagem_final = (
        "🥳 <b>Parabéns! Registro Quase Concluído!</b> 🥳\n\n"
        "Você enviou todos os documentos e informações de registro! Seu gestor já foi notificado.\n\n"
        "⚠️ <b>Acesso Bloqueado:</b> O sistema só será liberado após a aprovação do seu exame admissional.\n\n"
        "➡️ <b>Próxima Ação Obrigatória:</b> Agende imediatamente seu exame admissional no local abaixo:\n\n"
        "🏥 <b>Clínica/Local:</b> Gera Medicina e Segurança do Trabalho\n"
        "📍 <b>Endereço:</b> R. Afonso Pena, 809 - Centro, Rondonópolis - MT, 78700-070\n"
        "📞 <b>Telefone:</b> (66) 3424-0035\n\n"
        "Qualquer dúvida, contate o RH. Aguarde a notificação de liberação! 🔒"
    )
    await _enviar_html(context, update.effective_chat.id, mensagem_final)
    context.user_data.clear()


# ===================================================================
# == INTERCEPTADOR DE PENDÊNCIAS ====================================
# ===================================================================

async def _interceptar_comandos_e_pendencias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Verifica se o usuário tem pendências obrigatórias.
    Retorna True se BLOQUEOU (a função que chamou deve parar), False se pode seguir.
    """
    chat_id = update.effective_chat.id
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)

    if not funcionario:
        await context.bot.send_message(chat_id, "Desculpe, não consegui encontrar seu cadastro no sistema.")
        return True

    if eh_gestor(funcionario):
        return False  # Gestores e RH não são bloqueados

    # --- VERIFICAÇÃO 0: ONBOARDING OBRIGATÓRIO ---
    status_onboarding = database.buscar_onboarding_status(funcionario.FuncionarioID)
    if status_onboarding:
        status_atual = (getattr(status_onboarding, 'StatusWorkflow', None) or '').strip()

        if status_atual != 'Completo':
            if status_atual != 'Em Progresso':
                await _enviar_html(context, chat_id,
                                   "🛑 <b>Ação Obrigatória (Onboarding):</b> Seu registro de documentos está pendente.\n"
                                   "Você deve finalizar este processo antes de usar o sistema.")
            await onboarding_handler(update, context)
            return True

        status_admissional = (getattr(status_onboarding, 'StatusAdmissional', None) or '').strip()
        if status_admissional == 'Pendente':
            await _enviar_html(context, chat_id,
                               "🔒 <b>Acesso Bloqueado:</b> Seu registro de documentos está completo, mas o sistema "
                               "só será liberado após a <b>aprovação do seu exame admissional</b> pelo RH.")
            return True

    # --- VERIFICAÇÃO 1: FEEDBACK DO DIA ANTERIOR ---
    if not database.verificar_feedback_dia_anterior(funcionario.FuncionarioID):
        data_ontem_str = (agora() - timedelta(days=1)).strftime('%d/%m')
        keyboard = [[InlineKeyboardButton("⭐ Avaliar meu dia de ontem", callback_data="avaliar_dia_ontem")]]
        await context.bot.send_message(
            chat_id,
            f"⚠️ <b>Ação Obrigatória:</b> Antes de prosseguir, por favor, avalie seu dia de trabalho referente a <b>{data_ontem_str}</b>.",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
        )
        return True

    # --- VERIFICAÇÃO 2: PENDÊNCIAS DE CIÊNCIA ---
    keyboard = []
    for pendencia in database.buscar_pendencias_criticas(funcionario.FuncionarioID) or []:
        id_pendencia, tipo, titulo, data_envio = pendencia
        if tipo == 'Comunicado':
            data_str = data_envio.strftime('%d/%m') if data_envio else ""
            keyboard.append([InlineKeyboardButton(f"⚠️ Ler Comunicado ({data_str})", callback_data=f"doc_ciente_{id_pendencia}")])

    for doc in database.buscar_documentos_disponiveis(funcionario.FuncionarioID) or []:
        mes_ref = doc.MesAno.strftime('%m/%Y') if doc.MesAno else ""
        keyboard.append([InlineKeyboardButton(f"⚠️ Ver {doc.TipoDocumento} {mes_ref}", callback_data=f"get_documento_{doc.DocumentoID}")])

    if keyboard:
        await context.bot.send_message(
            chat_id,
            f"🛑 <b>Ação Obrigatória:</b> Você possui <b>{len(keyboard)}</b> documento(s) pendente(s) de leitura/ciência. Clique abaixo para resolver.",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
        )
        return True

    return False


# ===================================================================
# == ROTEADOR DE TEXTO (CHAT PRIVADO) ===============================
# ===================================================================

async def roteador_de_texto_privado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Recebe TODAS as mensagens de texto do chat privado que não são comandos nem
    botões do menu, verifica o 'estado' do usuário e direciona para a ação certa.
    """
    user_data = context.user_data
    texto_recebido = update.message.text
    chat_id = update.effective_chat.id

    # Prioridade: processo de abate de comanda em andamento
    if user_data.get('estado') == 'aguardando_valor_comanda':
        await processar_valor_comanda(update, context)
        return

    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario:
        await update.message.reply_text("Olá! Seu usuário não foi encontrado no sistema. Por favor, contate seu gestor.")
        return

    # Bloqueios obrigatórios (cadastro, feedback, ciência). O cadastro é tratado aqui dentro.
    if await _interceptar_comandos_e_pendencias(update, context):
        return

    if user_data.pop('aguardando_verificador_cpf', None):
        verificador_correto = database.buscar_verificador_cpf(funcionario.FuncionarioID)
        if not (verificador_correto and texto_recebido.strip() == str(verificador_correto).strip()):
            await update.message.reply_text("❌ Código de verificação incorreto ou não cadastrado. Inicie o processo novamente ou contate o RH.")
            return

        await update.message.reply_text("✅ Verificação bem-sucedida! Buscando seus documentos pendentes de ciência...")
        documentos = database.buscar_documentos_disponiveis(funcionario.FuncionarioID)
        if not documentos:
            await update.message.reply_text("Você não possui novos documentos pendentes de ciência no momento.")
            return

        keyboard = []
        for doc in documentos:
            if doc.TipoDocumento in ['Holerite', 'Cartão Ponto'] and doc.MesAno:
                sufixo = f" ({doc.MesAno.strftime('%m/%Y')})"
            else:
                sufixo = ""
            keyboard.append([InlineKeyboardButton(f"📄 {doc.TipoDocumento}{sufixo}", callback_data=f"get_documento_{doc.DocumentoID}")])
        await update.message.reply_text("Selecione o documento que deseja visualizar:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if user_data.get('aguardando_dados_compra'):
        texto = texto_recebido.strip()
        categoria = user_data.get('temp_categoria_compra', 'Geral')
        user_data.setdefault('carrinho_compras', []).append({'item': texto, 'categoria': categoria})
        qtd_itens = len(user_data['carrinho_compras'])

        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Mais", callback_data="compra_add_mais")],
            [InlineKeyboardButton("✅ Finalizar Pedido", callback_data="compra_finalizar")],
        ]
        user_data.pop('aguardando_dados_compra', None)  # Evita duplicar item
        await update.message.reply_html(
            f"✅ Item adicionado: <b>{esc(texto)}</b>\n"
            f"📦 Itens no carrinho: {qtd_itens}\n\n"
            f"Deseja adicionar mais itens na categoria <b>{esc(categoria)}</b> ou finalizar?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if user_data.get('aguardando_desc_manutencao'):
        user_data.pop('aguardando_desc_manutencao', None)
        user_data['temp_desc_manutencao'] = texto_recebido
        user_data['aguardando_foto_manutencao'] = True
        await update.message.reply_html("📸 Agora, envie uma <b>FOTO</b> obrigatória do problema para registrarmos.")
        return

    if 'tarefa_nao_aplicavel' in user_data:
        atribuicao_id = user_data.pop('tarefa_nao_aplicavel', None)
        if atribuicao_id:
            database.registrar_tarefa_nao_aplicavel(atribuicao_id, texto_recebido)
            keyboard = [[InlineKeyboardButton("⬅️ Ver Tarefas Restantes", callback_data="voltar_lista_tarefas")]]
            await update.message.reply_text("Ok, justificativa registrada!", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("Ocorreu um erro. Por favor, tente marcar como 'Não Aplicável' novamente.")
        return

    if user_data.get('aguardando_denuncia_anonima'):
        user_data.pop('aguardando_denuncia_anonima', None)
        # IMPORTANTE: nenhum dado do funcionário é enviado ou salvo aqui.
        novo_id = database.registrar_denuncia_anonima(texto_recebido)
        if not novo_id:
            await update.message.reply_text("❌ Ocorreu um erro ao tentar registrar sua mensagem. Tente novamente mais tarde.")
            return

        mensagem_gestor = (
            f"Atenção: Nova mensagem anônima recebida (Protocolo: {novo_id})\n\n"
            f"<b>Mensagem:</b>\n<i>\"{esc(texto_recebido)}\"</i>"
        )
        try:
            notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
        except Exception as e_notify:
            logger.error(f"Falha ao notificar gestores sobre mensagem anônima (Protocolo: {novo_id}): {e_notify}")
        await update.message.reply_text("✅ Sua mensagem anônima foi registrada e enviada à gestão. Obrigado por sua contribuição.")
        return

    # Mensagem sem nenhum contexto esperado
    user_data.clear()
    await update.message.reply_text(
        "Não entendi o que você quis dizer. Use os botões do menu para interagir comigo. "
        "Se precisar, use /ajuda ou digite /cancelar para recomeçar."
    )


# ===================================================================
# == RECEBIMENTO DE FOTOS E ARQUIVOS (CHAT PRIVADO) =================
# ===================================================================

async def receber_foto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Roteador mestre de fotos/documentos.
    Prioridade: Manutenção > Nota Fiscal > Cadastro (onboarding) > Evidência de tarefa.
    """
    if context.user_data.get('aguardando_foto_manutencao'):
        await receber_foto_manutencao(update, context)
        return

    if context.user_data.get('aguardando_nota_fiscal'):
        await receber_nota_fiscal(update, context)
        return

    # Cadastro incompleto: o estado vem do BANCO (sobrevive a reinícios do bot)
    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if funcionario and not eh_gestor(funcionario):
        status = database.buscar_onboarding_status(funcionario.FuncionarioID)
        if status and (getattr(status, 'StatusWorkflow', None) or '').strip() != 'Completo':
            await onboarding_handler(update, context)
            return

    await handler_foto_tarefa(update, context)


async def handler_foto_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recebe a foto (ou PDF) de evidência de uma tarefa e envia para validação."""
    msg = update.message
    try:
        if 'identificador_tarefa' not in context.user_data:
            await msg.reply_text("Parece que você enviou uma foto sem antes selecionar uma tarefa. "
                                 "Use o botão 📋 Minhas Tarefas primeiro.")
            return

        if eh_encaminhada(msg):
            await msg.reply_text("❌ Desculpe, fotos encaminhadas não são aceitas.")
            return
        if eh_imagem_como_arquivo(msg.document):
            await msg.reply_text("❌ Por favor, envie a imagem como 'Foto', e não como 'Arquivo'.")
            return

        file_id = extrair_file_id_foto_ou_pdf(msg)
        if not file_id:
            await msg.reply_text("❌ Formato de arquivo não reconhecido. Envie uma Foto ou um PDF.")
            return  # A tarefa continua selecionada para a pessoa tentar de novo

        # Só agora "consome" a tarefa selecionada
        atribuicao_id = int(context.user_data.pop('identificador_tarefa'))
        funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
        tarefa = database.buscar_tarefa_por_atribuicao(atribuicao_id)
        if not (funcionario and tarefa):
            await msg.reply_text("Ocorreu um erro ao identificar seus dados ou a tarefa.")
            return

        entrega_id = database.registrar_entrega_preliminar(tarefa.TarefaID, funcionario.FuncionarioID, atribuicao_id, file_id)
        if not entrega_id:
            await msg.reply_text("❌ Não consegui registrar sua entrega. Tente novamente em instantes.")
            return

        # Resposta ao funcionário (antes ela não era enviada se faltasse o grupo de gestão)
        await msg.reply_text("✅ Evidência válida! Entrega registrada com sucesso e enviada para validação!")

        if not config.GESTOR_GROUP_CHAT_ID:
            logger.error("GESTOR_GROUP_CHAT_ID não configurado: a entrega foi salva, mas ninguém foi avisado.")
            return

        legenda = (f"<b>Nova Entrega para Validação</b>\n\n"
                   f"👤 <b>Funcionário:</b> {esc(funcionario.NomeCompleto)}\n"
                   f"📝 <b>Tarefa:</b> {esc(tarefa.Titulo)} ({tarefa.Pontos} pts)\n"
                   f"🗓️ <b>Data:</b> {agora().strftime('%d/%m/%Y %H:%M')}")
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_gestor_{entrega_id}"),
            InlineKeyboardButton("❌ Reprovar", callback_data=f"reprovar_gestor_{entrega_id}"),
        ]])

        # Envia a notificação ao gestor ANTES de marcar a flag.
        # Se falhar, a flag fica desmarcada e o agendador reenvia depois.
        try:
            resposta_api = notificador_telegram.enviar_foto_com_botoes(
                config.GESTOR_GROUP_CHAT_ID, file_id, legenda, reply_markup, parse_mode='HTML'
            )
            if resposta_api and resposta_api.get('ok'):
                try:
                    database.marcar_notificacao_gestor_enviada(entrega_id)
                    logger.info(f"Notificação da EntregaID {entrega_id} enviada e flag marcada.")
                except Exception as flag_error:
                    logger.error(f"Notificação enviada, mas falhou ao marcar flag da EntregaID {entrega_id}: {flag_error}", exc_info=True)
            else:
                logger.error(f"Falha ao notificar gestores sobre EntregaID {entrega_id}. Resposta: {resposta_api}. Flag NÃO marcada.")
        except Exception as notify_error:
            logger.error(f"Erro ao notificar gestores sobre EntregaID {entrega_id}: {notify_error}. Flag NÃO marcada.", exc_info=True)

    except Exception as e:
        logger.error(f"Erro crítico em handler_foto_tarefa: {e}", exc_info=True)
        await msg.reply_text("Ocorreu um erro crítico ao registrar sua entrega. Contate o administrador.")


async def receber_nota_fiscal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recebe a foto da Nota Fiscal (só é chamado com o estado 'aguardando_nota_fiscal')."""
    msg = update.message

    # Validações ANTES de limpar o estado: se errar, a pessoa pode tentar de novo
    if eh_encaminhada(msg):
        await msg.reply_text("❌ Fotos encaminhadas não são aceitas. Tire a foto na hora ou envie da galeria.")
        return
    if not msg.photo:
        await msg.reply_text("❌ Por favor, envie a nota como 'Foto' (não como arquivo). Ou digite /cancelar.")
        return

    context.user_data.pop('aguardando_nota_fiscal', None)

    try:
        funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
        if not funcionario:
            await msg.reply_text("Erro: Não consegui encontrar seu cadastro no sistema.")
            return

        file_id = msg.photo[-1].file_id
        nota_fiscal_id = database.registrar_nota_fiscal(funcionario.FuncionarioID, file_id)
        if not nota_fiscal_id:
            await msg.reply_text("❌ Ocorreu um erro interno ao registrar sua nota fiscal. Tente novamente.")
            return

        pontos_bonus = config.PONTOS_BONUS_NOTA_FISCAL
        database.registrar_pontos_de_bonus(
            funcionario.FuncionarioID, pontos_bonus,
            f"Envio de Nota Fiscal (ID: {nota_fiscal_id})", config.TAREFA_ID_NOTA_FISCAL
        )
        database.adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_bonus)
        await msg.reply_html(f"✅ Nota Fiscal enviada com sucesso! Você ganhou <b>{pontos_bonus} pontos</b> pelo recebimento!")

        legenda_gestor = (
            f"🧾 <b>Nova Nota Fiscal Recebida</b> 🧾\n\n"
            f"👤 <b>Enviada por:</b> {esc(funcionario.NomeCompleto)}\n"
            f"🗓️ <b>Data:</b> {agora().strftime('%d/%m/%Y %H:%M')}\n"
            f"🆔 <b>NF ID:</b> {nota_fiscal_id}\n\n"
            "Ações Rápidas:"
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Encaminhar p/ Financeiro", callback_data=f"nf_prep_fwd_{nota_fiscal_id}")],
            [InlineKeyboardButton("📦 Criar Tarefa 'Guardar'", callback_data=f"nf_create_task_{nota_fiscal_id}")],
            [InlineKeyboardButton("👍 Arquivar (Nenhuma Ação)", callback_data=f"nf_ignore_{nota_fiscal_id}")],
        ])
        notificador_telegram.enviar_foto_com_botoes(
            config.GESTOR_GROUP_CHAT_ID, file_id, legenda_gestor, reply_markup, parse_mode='HTML'
        )
        logger.info(f"Nota Fiscal {nota_fiscal_id} encaminhada para o grupo de gestores.")
    except Exception as e:
        logger.error(f"Erro crítico em receber_nota_fiscal: {e}", exc_info=True)
        await msg.reply_text("Ocorreu um erro crítico. Contate o administrador.")


async def receber_foto_manutencao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recebe a foto de um pedido de manutenção, salva no disco e avisa a gestão."""
    msg = update.message
    if not msg.photo:
        await msg.reply_text("❌ Envie o problema como 'Foto' (não como arquivo). Ou digite /cancelar.")
        return  # Mantém o estado para tentar de novo

    context.user_data.pop('aguardando_foto_manutencao', None)
    descricao_problema = context.user_data.pop('temp_desc_manutencao', None) or "(sem descrição)"

    funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
    if not funcionario:
        await msg.reply_text("Erro de identificação. Seu cadastro não foi encontrado.")
        return

    file_id = msg.photo[-1].file_id
    try:
        # Download pela própria biblioteca (assíncrono). O código antigo usava
        # 'requests', que TRAVAVA o bot inteiro durante o download.
        pasta_manut = os.path.join(PASTA_DO_BOT, 'fotos_manutencao')
        os.makedirs(pasta_manut, exist_ok=True)
        nome_arquivo = f"manut_{funcionario.FuncionarioID}_{agora().strftime('%Y%m%d_%H%M%S')}.jpg"
        caminho_local = os.path.join(pasta_manut, nome_arquivo)

        arquivo_telegram = await context.bot.get_file(file_id)
        await arquivo_telegram.download_to_drive(caminho_local)
    except Exception as e:
        logger.error(f"Erro ao baixar foto de manutenção: {e}", exc_info=True)
        await msg.reply_text("Erro ao baixar a foto. Tente novamente pelo menu de solicitações.")
        return

    if not database.criar_solicitacao_interna(funcionario.FuncionarioID, 'Manutencao', 'Predial',
                                              descricao_problema, None, caminho_local):
        await msg.reply_text("Erro ao salvar a solicitação no banco de dados.")
        return

    await msg.reply_text("✅ Solicitação de Manutenção registrada com foto! A gestão foi notificada.")

    # Aviso aos gestores separado: se falhar, a solicitação JÁ está salva
    try:
        await context.bot.send_photo(
            chat_id=config.GESTOR_GROUP_CHAT_ID, photo=file_id,
            caption=(f"🔧 <b>Nova Solicitação de Manutenção</b>\n"
                     f"👤 {esc(funcionario.NomeCompleto)}\n📝 {esc(descricao_problema)}"),
            parse_mode=ParseMode.HTML
        )
    except TelegramError as e:
        logger.error(f"Manutenção salva, mas falhou ao avisar os gestores: {e}")


# ===================================================================
# == TEXTO NO GRUPO DE GESTÃO (MOTIVO DE RECUSA) ====================
# ===================================================================

async def receber_motivo_recusa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recebe o motivo digitado pelo gestor como RESPOSTA à mensagem do bot."""
    msg = update.message
    resposta_a = msg.reply_to_message
    if not (resposta_a and resposta_a.from_user and resposta_a.from_user.id == context.bot.id):
        return  # Ignora conversas normais do grupo

    chat_id_grupo = update.effective_chat.id
    gestor_id = update.effective_user.id
    gestor_nome = update.effective_user.first_name
    motivo = (msg.text or "").strip() or "Sem motivo especificado"  # Texto ORIGINAL (salvo no banco)

    pendencias_grupo = context.bot_data.get('pendencias_recusa', {}).get(chat_id_grupo, {})
    dados_recusa = pendencias_grupo.pop(gestor_id, None)
    if not pendencias_grupo:
        context.bot_data.get('pendencias_recusa', {}).pop(chat_id_grupo, None)

    if not dados_recusa:
        # Bot reiniciou, ou outro gestor respondeu
        await msg.reply_html(
            "⚠️ <b>Sessão Expirada:</b> Não consegui vincular sua resposta à tarefa.\n"
            "Clique no botão <b>❌ Reprovar</b> novamente na mensagem original da tarefa."
        )
        return

    entrega_id = dados_recusa['entrega_id']
    id_mensagem_original = dados_recusa['msg_id']

    detalhes = database.buscar_detalhes_da_entrega(entrega_id)
    if not detalhes or detalhes.StatusValidacao != 'Pendente':
        await msg.reply_text("Esta tarefa já foi validada por outro gestor ou não foi encontrada.")
        return

    # Salva o texto original. O escape é feito só na hora de exibir
    # (antes o banco guardava '&lt;' e o histórico mostrava errado).
    database.recusar_entrega(entrega_id, motivo)

    notificador_telegram.enviar_mensagem(
        detalhes.ChatIDFuncionario,
        f"⚠️ Atenção, <b>{esc(detalhes.NomeCompleto)}</b>!\n\n"
        f"Sua entrega para a tarefa '<b>{esc(detalhes.Titulo)}</b>' foi RECUSADA.\n\n"
        f"<b>Motivo:</b> {esc(motivo)}\n\n"
        "Por favor, corrija e envie novamente."
    )

    legenda_final = (f"<b>Entrega RECUSADA por {esc(gestor_nome)}</b>\n\n"
                     f"👤 <b>Funcionário:</b> {esc(detalhes.NomeCompleto)}\n"
                     f"📝 <b>Tarefa:</b> {esc(detalhes.Titulo)}\n"
                     f"💬 <b>Motivo:</b> {esc(motivo)}")
    try:
        await context.bot.edit_message_caption(chat_id=chat_id_grupo, message_id=id_mensagem_original,
                                               caption=legenda_final, parse_mode=ParseMode.HTML)
    except TelegramError as e_edit:
        logger.warning(f"Não foi possível editar a legenda da recusa {entrega_id}: {e_edit}")
        try:
            await msg.reply_html(legenda_final)
        except TelegramError as e_send:
            logger.error(f"Falha também ao enviar a mensagem de recusa {entrega_id}: {e_send}")


# ===================================================================
# == CLIQUES EM BOTÕES (CALLBACKS) ==================================
# ===================================================================

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Trata TODOS os cliques em botões inline (exceto 'abater_comanda').

    REGRA IMPORTANTE: o Telegram aceita só UMA resposta (query.answer) por clique.
    Por isso usamos a função 'responder' abaixo, que garante resposta única.
    No final (bloco finally), se ninguém respondeu, respondemos em branco
    para o reloginho do botão parar de girar.
    """
    query = update.callback_query
    data = query.data or ""
    user = update.effective_user
    ja_respondido = False

    async def responder(texto=None, alerta=False):
        nonlocal ja_respondido
        if ja_respondido:
            return
        ja_respondido = True
        try:
            await query.answer(texto, show_alert=alerta)
        except BadRequest as e:
            logger.warning(f"Não foi possível responder ao clique '{data}': {e}")

    try:
        # --- TRAVA: feedback do dia anterior pendente (não vale para gestores) ---
        eh_clique_de_feedback = data in ("avaliar_dia", "avaliar_dia_ontem") or data.startswith("nota_dia")
        if not eh_clique_de_feedback and not data.startswith(PREFIXOS_CALLBACK_GESTAO):
            func_check = database.buscar_funcionario_por_chat_id(user.id)
            if (func_check and not eh_gestor(func_check)
                    and not database.verificar_feedback_dia_anterior(func_check.FuncionarioID)):
                await responder("⚠️ Ação bloqueada! Você tem feedback pendente do dia anterior.", alerta=True)
                return

        # ================= SOLICITAÇÕES (COMPRAS / MANUTENÇÃO) =================
        if data == "menu_solicitacoes":
            func_db = database.buscar_funcionario_por_chat_id(user.id)
            pode_acessar = False
            if func_db:
                cargo = sem_acentos((func_db.Cargo or "")).upper()
                if eh_gestor(func_db) or 'LIDER' in cargo or 'GERENTE' in cargo:
                    pode_acessar = True
            if pode_acessar:
                keyboard = [
                    [InlineKeyboardButton("🛒 Compra de Insumos", callback_data="solic_compra")],
                    [InlineKeyboardButton("🔧 Manutenção Predial", callback_data="solic_manut")],
                ]
                await query.edit_message_text("Selecione o tipo de solicitação:", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.edit_message_text("🚫 Acesso restrito a Líderes e Gerentes.")

        elif data == "solic_compra":
            keyboard = [
                [InlineKeyboardButton("🧹 Limpeza", callback_data="cat_limpeza"),
                 InlineKeyboardButton("📠 Escritório", callback_data="cat_escritorio")],
                [InlineKeyboardButton("🍳 Cozinha", callback_data="cat_cozinha"),
                 InlineKeyboardButton("📦 Outros", callback_data="cat_outros")],
            ]
            await query.edit_message_text("Selecione a categoria do produto:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("cat_"):
            categoria = data.split("_", 1)[1].capitalize()
            context.user_data['temp_categoria_compra'] = categoria
            context.user_data['aguardando_dados_compra'] = True
            await query.edit_message_text(
                f"Categoria: <b>{esc(categoria)}</b>.\n\nDigite o <b>Nome do Item e a Quantidade</b> (Ex: 'Detergente 5 litros'):",
                parse_mode=ParseMode.HTML
            )

        elif data == "solic_manut":
            context.user_data['aguardando_desc_manutencao'] = True
            await query.edit_message_text("🔧 Descreva brevemente o problema de manutenção:")

        elif data == "compra_add_mais":
            context.user_data['aguardando_dados_compra'] = True
            categoria = context.user_data.get('temp_categoria_compra', 'Geral')
            await query.edit_message_text(f"Ok, digite o próximo item e quantidade para <b>{esc(categoria)}</b>:",
                                          parse_mode=ParseMode.HTML)

        elif data == "compra_finalizar":
            carrinho = context.user_data.get('carrinho_compras', [])
            funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
            if not carrinho:
                await query.edit_message_text("Seu carrinho está vazio. Abra o menu de solicitações novamente.")
                return
            if not funcionario_db:
                await query.edit_message_text("Erro: seu cadastro não foi encontrado.")
                return

            itens_salvos = []
            for item in carrinho:
                if database.criar_solicitacao_interna(funcionario_db.FuncionarioID, 'Compra',
                                                      item['categoria'], item['item'], None, None):
                    itens_salvos.append(item)
            erros = len(carrinho) - len(itens_salvos)

            if itens_salvos:
                msg_resumo = (f"🛒 <b>Novo Pedido de Compra (Lote)</b>\n"
                              f"👤 {esc(funcionario_db.NomeCompleto)}\n")
                for item in itens_salvos:
                    msg_resumo += f"▫️ {esc(item['item'])} ({esc(item['categoria'])})\n"
                notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, msg_resumo)
                texto_final = f"✅ Pedido enviado!\n\nItens solicitados: {len(itens_salvos)}\n(Aguarde a aprovação da gestão)"
                if erros:
                    texto_final += f"\n\n⚠️ {erros} item(ns) não puderam ser salvos. Tente enviá-los novamente."
            else:
                texto_final = "❌ Não foi possível salvar o pedido. Tente novamente mais tarde."

            await query.edit_message_text(texto_final)
            context.user_data.pop('carrinho_compras', None)
            context.user_data.pop('temp_categoria_compra', None)

        # ================= DOCUMENTOS PESSOAIS =================
        elif data.startswith("get_documento_"):
            await query.edit_message_text("Processando sua solicitação...")
            documento_id = int(data.split('_')[-1])
            dados_documento = database.buscar_dados_documento_para_envio(documento_id)
            if not dados_documento:
                await query.edit_message_text("Erro: Não foi possível encontrar este documento ou ele já foi processado.")
                return

            caminho_arquivo, ciencia_id, funcionario_id_db, mes_ano_obj = dados_documento

            # Segurança: o documento precisa ser de quem clicou
            funcionario = database.buscar_funcionario_por_chat_id(user.id)
            if not funcionario or funcionario.FuncionarioID != funcionario_id_db:
                await query.edit_message_text("Erro de Acesso: Este documento não pertence ao seu usuário.")
                return

            # (O código antigo mostrava o ID do funcionário no lugar do tipo do documento.)
            if mes_ano_obj:
                legenda = (f"Aqui está seu documento referente a {mes_ano_obj.strftime('%B de %Y').capitalize()}.\n\n"
                           "Por favor, confirme o recebimento.")
            else:
                legenda = "Aqui está seu documento.\n\nPor favor, confirme o recebimento."

            keyboard = [[InlineKeyboardButton("✅ Recebi e estou ciente", callback_data=f"doc_pessoal_ciente_{ciencia_id}")]]
            try:
                with open(caminho_arquivo, 'rb') as documento:
                    await context.bot.send_document(chat_id=user.id, document=documento, caption=legenda,
                                                    reply_markup=InlineKeyboardMarkup(keyboard))
                await query.edit_message_text("✔️ Seu documento foi enviado. Verifique a nova mensagem e confirme a ciência.")
            except FileNotFoundError:
                logger.error(f"Arquivo do DocumentoID {documento_id} não encontrado: {caminho_arquivo}")
                await query.edit_message_text("❌ O arquivo do documento não foi encontrado no servidor. Por favor, contate o RH.")
            except Exception as e:
                logger.error(f"Erro ao enviar DocumentoID {documento_id}: {e}", exc_info=True)
                await query.edit_message_text("❌ Ocorreu um erro inesperado ao enviar seu documento. Tente novamente ou contate o RH.")

        elif data.startswith("doc_pessoal_ciente_"):
            ciencia_id = int(data.split('_')[-1])
            if not database.marcar_holerite_como_ciente(ciencia_id):
                await responder("Este documento já foi assinado.", alerta=True)
                return
            notificador_telegram.enviar_mensagem(
                config.GESTOR_GROUP_CHAT_ID,
                f"✍️ O funcionário <b>{esc(user.first_name)}</b> confirmou o recebimento de um documento pessoal (CienciaID: {ciencia_id})."
            )
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except TelegramError as e:
                logger.warning(f"Falha ao remover teclado do documento pessoal: {e}")
            await responder("Recebimento e ciência registrados com sucesso!", alerta=True)

        # ================= LOJA DE RECOMPENSAS =================
        elif data.startswith("ver_produto_"):
            produto_id = int(data.split('_')[-1])
            produto = next((p for p in database.listar_produtos_loja(incluir_inativos=True) if p.ProdutoID == produto_id), None)
            funcionario = database.buscar_funcionario_por_chat_id(user.id)
            if not produto:
                await query.edit_message_text("Este produto não está mais disponível.")
                return
            if not funcionario:
                await query.edit_message_text("Erro: seu cadastro não foi encontrado.")
                return

            saldo_atual = database.buscar_saldo_funcionario(funcionario.FuncionarioID) or 0
            texto = (f"<b>{esc(produto.Nome)}</b>\n\n<i>{esc(produto.Descricao)}</i>\n\n"
                     f"Custo: <b>{produto.CustoEmPontos} pontos</b>\nSeu Saldo: <b>{saldo_atual} pontos</b>")
            keyboard = [[InlineKeyboardButton("✅ Confirmar Resgate", callback_data=f"confirmar_resgate_{produto.ProdutoID}")],
                        [InlineKeyboardButton("⬅️ Voltar para a Loja", callback_data="voltar_loja")]]
            if saldo_atual < produto.CustoEmPontos:
                texto += "\n\n⚠️ Você não tem pontos suficientes para resgatar este item."
                keyboard.pop(0)
            elif produto.EstoqueDisponivel is not None and produto.EstoqueDisponivel <= 0:
                texto += "\n\n⚠️ Produto sem estoque no momento."
                keyboard.pop(0)
            await query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

        elif data.startswith("confirmar_resgate_"):
            produto_id = int(data.split('_')[-1])
            funcionario = database.buscar_funcionario_por_chat_id(user.id)
            if not funcionario:
                await query.edit_message_text("Erro: seu cadastro não foi encontrado.")
                return
            sucesso, mensagem, resgate_id = database.solicitar_resgate(funcionario.FuncionarioID, produto_id)
            await query.edit_message_text(mensagem)
            if sucesso:
                produto = next((p for p in database.listar_produtos_loja(incluir_inativos=True) if p.ProdutoID == produto_id), None)
                nome_produto = produto.Nome if produto else f"Produto {produto_id}"
                custo = produto.CustoEmPontos if produto else "?"
                notificador_telegram.enviar_mensagem(
                    config.GESTOR_GROUP_CHAT_ID,
                    f"🔔 <b>Nova Solicitação de Resgate</b> 🔔\n\n"
                    f"👤 <b>Funcionário:</b> {esc(funcionario.NomeCompleto)}\n"
                    f"🎁 <b>Produto:</b> {esc(nome_produto)}\n"
                    f"💰 <b>Custo:</b> {custo} pontos\n\n"
                    f"Acesse o sistema (<code>main.py</code>) para aprovar."
                )

        elif data == "voltar_loja":
            texto, reply_markup = montar_loja(database.listar_produtos_loja())
            await query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

        # ================= FEEDBACK DE FIM DE JORNADA =================
        elif data in ("avaliar_dia", "avaliar_dia_ontem"):
            prefixo = "nota_dia_ontem_" if data == "avaliar_dia_ontem" else "nota_dia_"
            botoes = [InlineKeyboardButton(str(i), callback_data=f"{prefixo}{i}") for i in range(11)]
            keyboard = [botoes[0:5], botoes[5:10], botoes[10:]]
            if data == "avaliar_dia_ontem":
                texto_base = "Por favor, avalie o dia de ontem (pendência obrigatória):"
            else:
                texto_base = "Como você classificaria seu dia de 0 a 10?\n(0 = Muito Ruim / 10 = Excelente)"
            texto_original = query.message.text if query.message and query.message.text else ""
            await query.edit_message_text(text=f"{texto_original}\n\n{texto_base}".strip(),
                                          reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("nota_dia_"):
            nota = int(data.split('_')[-1])
            if data.startswith("nota_dia_ontem_"):
                data_registro = (agora() - timedelta(days=1)).strftime('%Y-%m-%d')
                msg_pendencia = "Sua pendência de feedback foi resolvida."
            else:
                data_registro = agora().strftime('%Y-%m-%d')
                msg_pendencia = "Seu feedback foi salvo com sucesso."

            funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
            if not funcionario_db:
                await query.edit_message_text("Erro: não foi possível identificar seu usuário.")
                return

            if database.salvar_feedback_do_dia_com_data(funcionario_db.FuncionarioID, nota, data_registro):
                database.registrar_pontos_de_bonus(
                    funcionario_db.FuncionarioID, config.PONTOS_BONUS_FEEDBACK_DIARIO,
                    f"Feedback Diário ({data_registro})", config.TAREFA_ID_FEEDBACK_DIARIO
                )
                database.adicionar_pontos_ao_saldo(funcionario_db.FuncionarioID, config.PONTOS_BONUS_FEEDBACK_DIARIO)
                await query.edit_message_text(
                    f"Obrigado pelo seu feedback! Sua nota foi <b>{nota}</b>.\n\n"
                    f"Você ganhou <b>{config.PONTOS_BONUS_FEEDBACK_DIARIO}</b> pontos por sua participação. "
                    f"Sua opinião nos ajuda a melhorar sempre! 💪\n\n{msg_pendencia}",
                    parse_mode=ParseMode.HTML
                )
            else:
                await query.edit_message_text("Você já enviou seu feedback para esta data. Obrigado!")

        # ================= TAREFAS DE GRUPO / FOLGA =================
        elif data.startswith("aceitar_tarefa_"):
            origem_atribuicao_id = int(data.split('_')[-1])
            funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
            if not funcionario_db:
                await responder("Seu usuário do Telegram não foi encontrado no nosso sistema.", alerta=True)
                return

            nova_atribuicao_id = database.aceitar_tarefa_de_grupo(origem_atribuicao_id, funcionario_db.FuncionarioID)
            tarefa_original = database.buscar_tarefa_por_atribuicao(origem_atribuicao_id)
            tarefa_titulo = tarefa_original.Titulo if tarefa_original else "Tarefa desconhecida"

            if nova_atribuicao_id:
                try:
                    await query.edit_message_text(
                        text=(f"✅ <b>Missão Aceita por {esc(user.first_name)}!</b> ✅\n\n"
                              f"<b>Tarefa:</b> {esc(tarefa_titulo)}\n\n"
                              f"{esc(user.first_name)} agora é o responsável pela entrega <i>de hoje</i>. Boa sorte!"),
                        reply_markup=None, parse_mode=ParseMode.HTML
                    )
                except TelegramError as e:
                    logger.info(f"Não foi possível editar a mensagem do grupo para {origem_atribuicao_id}: {e}")
                try:
                    await context.bot.send_message(
                        chat_id=user.id,
                        text=f"Você aceitou a missão '{tarefa_titulo}' para hoje. Ela já aparece em 📋 Minhas Tarefas. Capriche na entrega! 💪"
                    )
                except Forbidden:
                    logger.info(f"Usuário {user.id} ainda não iniciou conversa privada com o bot.")
                await responder("Missão aceita! 🚀")
            else:
                await responder(f"Que pena, a missão '{tarefa_titulo}' já foi aceita por outro colega hoje.", alerta=True)
                logger.info(f"Funcionário {funcionario_db.FuncionarioID} tentou aceitar a tarefa {origem_atribuicao_id} já aceita.")

        elif data.startswith("aceitar_folga_"):
            tarefa_id = int(data.split('_')[-1])
            funcionario_aceitou = database.buscar_funcionario_por_chat_id(user.id)
            if not funcionario_aceitou:
                await responder("Seu usuário não foi encontrado.", alerta=True)
                return

            novo_atribuicao_id = database.verificar_e_aceitar_tarefa_de_folga(tarefa_id, funcionario_aceitou.FuncionarioID)
            tarefa_info = database.buscar_tarefa_por_atribuicao(novo_atribuicao_id) if novo_atribuicao_id else None

            # Remove do teclado o botão clicado (nos dois casos: sucesso ou já pego)
            novo_teclado = []
            teclado_atual = query.message.reply_markup if query.message else None
            if teclado_atual and teclado_atual.inline_keyboard:
                for linha in teclado_atual.inline_keyboard:
                    nova_linha = [btn for btn in linha if btn.callback_data != data]
                    if nova_linha:
                        novo_teclado.append(nova_linha)

            if novo_atribuicao_id and tarefa_info:
                await responder("Missão aceita com sucesso! Ganhe esses pontos! 🚀", alerta=True)
                try:
                    texto_atual = query.message.text_html or esc(query.message.text or "")
                    novo_texto = texto_atual + f"\n\n✅ <b>{esc(tarefa_info.Titulo)}</b> resgatada por <b>{esc(user.first_name)}</b>!"
                    await query.edit_message_text(text=novo_texto, reply_markup=InlineKeyboardMarkup(novo_teclado),
                                                  parse_mode=ParseMode.HTML)
                except TelegramError as e:
                    logger.warning(f"Erro ao atualizar a mensagem do Drop (a tarefa foi aceita): {e}")
                try:
                    await context.bot.send_message(
                        chat_id=user.id,
                        text=f"🚀 Você assumiu a missão '{tarefa_info.Titulo}'! Ela já está em 📋 Minhas Tarefas."
                    )
                except Forbidden:
                    logger.info(f"Usuário {user.id} ainda não iniciou conversa privada com o bot.")
            else:
                await responder("Que pena! Outro colega foi mais rápido e já pegou essa missão.", alerta=True)
                try:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(novo_teclado))
                except TelegramError:
                    pass

        # ================= PENDÊNCIAS (GESTOR) =================
        elif data.startswith("ver_pendencias_"):
            funcionario_id = int(data.split('_')[-1])
            funcionario = database.buscar_funcionario_por_id(funcionario_id)
            if not funcionario:
                await query.edit_message_text("Erro: Funcionário não encontrado.")
                return
            tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario_id)
            texto_resposta = f"📋 <b>Tarefas Pendentes para {esc(funcionario.NomeCompleto)}</b>\n\n"
            if not tarefas_pendentes:
                texto_resposta += "Nenhuma tarefa pendente no momento. Bom trabalho! ✅"
            else:
                for tarefa in tarefas_pendentes:
                    texto_resposta += f"  - {esc(tarefa.Titulo)} ({tarefa.Pontos} pts)\n"
            keyboard = [[InlineKeyboardButton("⬅️ Voltar para a lista", callback_data="voltar_lista_funcs")]]
            await query.edit_message_text(texto_resposta, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

        elif data == "voltar_lista_funcs":
            funcionarios = database.listar_funcionarios() or []
            keyboard = [[InlineKeyboardButton(f.NomeCompleto, callback_data=f"ver_pendencias_{f.FuncionarioID}")] for f in funcionarios]
            await query.edit_message_text("Selecione um funcionário para ver as tarefas pendentes:",
                                          reply_markup=InlineKeyboardMarkup(keyboard))

        # ================= CIÊNCIA DE COMUNICADOS =================
        elif data.startswith("doc_ciente_"):
            # (O código antigo chamava query.answer() aqui pela 2ª vez e QUEBRAVA sempre.)
            assinatura_id = int(data.split('_')[-1])
            detalhes = database.buscar_detalhes_assinatura_para_bot(assinatura_id)
            if not detalhes:
                await responder("Esta ciência já foi registrada anteriormente.", alerta=True)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except TelegramError:
                    pass
                return

            database.marcar_como_ciente(assinatura_id)
            notificador_telegram.enviar_mensagem(
                config.GESTOR_GROUP_CHAT_ID,
                f"✅ O funcionário <b>{esc(user.first_name)}</b> confirmou ciência do comunicado: <i>'{esc(detalhes.Titulo)}'</i>."
            )

            momento = agora()
            confirmacao = (
                "\n\n---"
                "\n📜 <b>RECIBO DE CIÊNCIA</b> 📜"
                "\n\nSua confirmação de leitura foi registrada com sucesso."
                f"\n\n<b>Protocolo:</b> <code>{assinatura_id}</code>"
                f"\n<b>Data:</b> <code>{momento.strftime('%d/%m/%Y')}</code>"
                f"\n<b>Hora:</b> <code>{momento.strftime('%H:%M:%S')}</code>"
            )
            pontos = detalhes.PontosPorCiencia or 0
            if pontos > 0:
                database.adicionar_pontos_ao_saldo(detalhes.FuncionarioID, pontos)
                database.registrar_pontos_por_leitura(detalhes.FuncionarioID, pontos, detalhes.Titulo)
                confirmacao += f"\n\n🎉 Você ganhou <b>{pontos}</b> pontos por sua agilidade!"

            try:
                if query.message.photo or query.message.document:
                    original = query.message.caption_html or ""
                    await query.edit_message_caption(caption=f"{original}{confirmacao}", parse_mode=ParseMode.HTML, reply_markup=None)
                else:
                    original = query.message.text_html or ""
                    await query.edit_message_text(text=f"{original}{confirmacao}", parse_mode=ParseMode.HTML, reply_markup=None)
                await responder("Ciência registrada!")
            except TelegramError as e:
                logger.error(f"Erro ao editar a mensagem de ciência (ID: {assinatura_id}): {e}")
                await responder("Sua ciência foi registrada!", alerta=True)

        # ================= TAREFAS (FUNCIONÁRIO) =================
        elif data.startswith("ver_tarefa_"):
            atribuicao_id = int(data.split('_')[-1])
            detalhes = database.buscar_detalhes_da_atribuicao(atribuicao_id)
            if not detalhes:
                await query.edit_message_text("Erro: Tarefa não encontrada.")
                return
            keyboard = [[InlineKeyboardButton("✅ Enviar Evidência", callback_data=f"entregar_{atribuicao_id}")],
                        [InlineKeyboardButton("🤷 Não Aplicável", callback_data=f"nao_aplicavel_{atribuicao_id}")],
                        [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_lista_tarefas")]]
            await query.edit_message_text(
                text=f"📄 <b>Detalhes:</b> <i>{esc(detalhes.Descricao)}</i>\n\nO que deseja fazer?",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
            )

        elif data.startswith("entregar_"):
            context.user_data['identificador_tarefa'] = int(data.split('_')[-1])
            context.user_data.pop('tarefa_nao_aplicavel', None)
            await query.edit_message_text(text="Excelente! ✅\nAgora, por favor, envie a foto de evidência.")

        elif data.startswith("nao_aplicavel_"):
            context.user_data['tarefa_nao_aplicavel'] = int(data.split('_')[-1])
            context.user_data.pop('identificador_tarefa', None)
            await query.edit_message_text(text="Entendido. 🤷\nPor favor, diga o motivo (ex: 'Chuva', 'Nenhum cliente').")

        elif data == "voltar_lista_tarefas":
            await tarefas(update, context, query=query)

        # ================= VALIDAÇÃO (GESTOR) =================
        elif data.startswith("aprovar_gestor_"):
            entrega_id = int(data.split('_')[-1])
            gestor_nome = query.from_user.first_name
            detalhes = database.buscar_detalhes_da_entrega(entrega_id)

            if not detalhes:
                await responder("Entrega não encontrada no banco de dados.", alerta=True)
                return
            if detalhes.StatusValidacao != 'Pendente':
                await responder(f"Esta tarefa já foi validada. (Status: {detalhes.StatusValidacao})", alerta=True)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except TelegramError:
                    pass
                return

            novas_conquistas = database.aprovar_entrega(entrega_id, detalhes.FuncionarioID, detalhes.Pontos)

            texto_notificacao = (f"🎉 Parabéns, <b>{esc(detalhes.NomeCompleto)}</b>!\n"
                                 f"Sua entrega para '<b>{esc(detalhes.Titulo)}</b>' foi APROVADA!\n\n"
                                 f"Você ganhou <b>{detalhes.Pontos}</b> pontos. Continue assim!")
            for conquista in novas_conquistas or []:
                texto_notificacao += (
                    f"\n\n✨ <b>NOVA CONQUISTA DESBLOQUEADA!</b> ✨\n"
                    f"{esc(conquista.Icone)} <b>{esc(conquista.Nome)}</b>\n"
                    f"<i>{esc(conquista.Descricao)}</i>\n"
                    f"Você ganhou um bônus de <b>{conquista.PontosBonus}</b> pontos!"
                )
                if conquista.PontosBonus and conquista.PontosBonus > 0:
                    database.adicionar_pontos_ao_saldo(detalhes.FuncionarioID, conquista.PontosBonus)
            notificador_telegram.enviar_mensagem(detalhes.ChatIDFuncionario, texto_notificacao)

            legenda_final = (f"<b>Entrega APROVADA por {esc(gestor_nome)}</b>\n\n"
                             f"👤 <b>Funcionário:</b> {esc(detalhes.NomeCompleto)}\n"
                             f"📝 <b>Tarefa:</b> {esc(detalhes.Titulo)} (+{detalhes.Pontos} pts)")
            try:
                await query.edit_message_caption(caption=legenda_final, reply_markup=None, parse_mode=ParseMode.HTML)
            except TelegramError as e_edit:
                logger.warning(f"Não foi possível editar a mensagem de aprovação {entrega_id}: {e_edit}")
                try:
                    await context.bot.send_message(chat_id=query.message.chat_id, text=legenda_final, parse_mode=ParseMode.HTML)
                except TelegramError as e_send:
                    logger.error(f"Falha também ao enviar a mensagem de aprovação {entrega_id}: {e_send}")

        elif data.startswith("reprovar_gestor_"):
            entrega_id = int(data.split('_')[-1])
            gestor = query.from_user
            chat_id_grupo = query.message.chat_id

            # Guarda "qual entrega este gestor está recusando" (fica na memória do bot)
            context.bot_data.setdefault('pendencias_recusa', {}).setdefault(chat_id_grupo, {})[gestor.id] = {
                'entrega_id': entrega_id,
                'msg_id': query.message.message_id,
            }
            logger.info(f"Recusa da EntregaID {entrega_id} aguardando motivo do GestorID {gestor.id}.")

            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except TelegramError as e:
                logger.warning(f"Não foi possível remover botões ao iniciar a recusa {entrega_id}: {e}")

            # ForceReply abre a "resposta" automaticamente no celular do gestor,
            # e o motivo só é aceito quando é uma RESPOSTA a esta mensagem.
            await query.message.reply_html(
                f'<a href="tg://user?id={gestor.id}">{esc(gestor.first_name)}</a>, '
                "<b>responda a esta mensagem</b> com o motivo da recusa.",
                reply_markup=ForceReply(selective=True, input_field_placeholder="Motivo da recusa")
            )

        # ================= NOTA FISCAL (GESTOR) =================
        elif data.startswith("nf_prep_fwd_"):
            gestor_chat_id = query.from_user.id
            nota_fiscal_id = int(data.split('_')[-1])
            dados_nf = database.buscar_nota_fiscal(nota_fiscal_id)
            if not dados_nf:
                await responder("Não encontrei os dados desta NF no banco.", alerta=True)
                return
            if not dados_nf.PathFoto:
                await responder("O download desta foto ainda está sendo processado. Tente novamente em 1 minuto.", alerta=True)
                return

            texto_wpp = urllib.parse.quote(f"Olá, segue a Nota Fiscal recebida (ID Interno: {nota_fiscal_id})")
            link_wpp = f"https://wa.me/{config.WHATSAPP_CONTATO_FINANCEIRO}?text={texto_wpp}"
            try:
                with open(dados_nf.PathFoto, 'rb') as nf_file:
                    await context.bot.send_document(
                        chat_id=gestor_chat_id, document=nf_file,
                        caption=f"Pronto! Encaminhe este arquivo para o Financeiro.\n\nVocê também pode usar este link:\n{link_wpp}"
                    )
            except Forbidden:
                await responder("Abra uma conversa privada comigo (/start) para eu poder te enviar o arquivo.", alerta=True)
                return
            except FileNotFoundError:
                logger.error(f"Arquivo da NF {nota_fiscal_id} não encontrado: {dados_nf.PathFoto}")
                await responder("O arquivo desta NF não foi encontrado no servidor.", alerta=True)
                return

            await responder("Arquivo enviado no seu privado!")
            await query.edit_message_caption(
                caption=f"{query.message.caption_html or ''}\n\n---\n✅ Encaminhada para o Financeiro por {esc(query.from_user.first_name)}.",
                parse_mode=ParseMode.HTML
            )

        elif data.startswith("nf_create_task_"):
            nota_fiscal_id = int(data.split('_')[-1])
            legenda_original = query.message.caption_html or ""
            dados_nf = database.buscar_nota_fiscal(nota_fiscal_id)
            if not dados_nf:
                await query.edit_message_caption(caption=f"{legenda_original}\n\n---\n❌ Erro: Não encontrei os dados desta NF.",
                                                 parse_mode=ParseMode.HTML)
                return

            nova_atribuicao_id = database.atribuir_tarefa(
                tarefa_id=config.TAREFA_ID_GUARDAR_MERCADORIA_MODELO,
                funcionario_id=dados_nf.FuncionarioID,
                tipo_frequencia='Unica',
                valor_frequencia=None,
                descricao_override="Guarde a mercadoria referente a esta Nota Fiscal.",
                data_agendamento=hoje()
            )
            if not nova_atribuicao_id:
                await query.edit_message_caption(caption=f"{legenda_original}\n\n---\n❌ Erro: Falha ao salvar a nova tarefa no banco.",
                                                 parse_mode=ParseMode.HTML)
                return

            database.atualizar_status_nota_fiscal(nota_fiscal_id, "Processada")
            try:
                await context.bot.send_photo(
                    chat_id=dados_nf.ChatIDFuncionario, photo=dados_nf.FileIDTelegram,
                    caption=("📦 <b>Nova Tarefa Atribuída!</b> 📦\n\n"
                             "Uma tarefa para <i>'Guardar Mercadoria (NF)'</i> foi criada para você com base na nota fiscal que você enviou.\n\n"
                             "Use o botão 📋 Minhas Tarefas para ver e enviar a evidência."),
                    parse_mode=ParseMode.HTML
                )
            except TelegramError as e:
                logger.error(f"Tarefa da NF {nota_fiscal_id} criada, mas falhou ao avisar o funcionário: {e}")
            await query.edit_message_caption(
                caption=f"{legenda_original}\n\n---\n✅ Tarefa 'Guardar' criada para o funcionário por {esc(query.from_user.first_name)}.",
                parse_mode=ParseMode.HTML
            )
            await responder("Tarefa criada!")

        elif data.startswith("nf_ignore_"):
            nota_fiscal_id = int(data.split('_')[-1])
            database.atualizar_status_nota_fiscal(nota_fiscal_id, "Processada")
            await query.edit_message_caption(
                caption=f"{query.message.caption_html or ''}\n\n---\n👍 Nota revisada e arquivada por {esc(query.from_user.first_name)}.",
                parse_mode=ParseMode.HTML
            )
            await responder("Arquivada!")

        else:
            logger.warning(f"Callback desconhecido recebido: '{data}'")
            await responder("Este botão não está mais disponível.", alerta=True)

    except Exception as e:
        logger.error(f"Erro ao processar o clique '{data}': {e}", exc_info=True)
        await responder("❌ Ocorreu um erro ao processar sua ação. Tente novamente.", alerta=True)
    finally:
        await responder()  # Se ninguém respondeu, para o "reloginho" do botão


# ===================================================================
# == TRATAMENTO GLOBAL DE ERROS =====================================
# ===================================================================

async def tratar_erro_global(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra no log qualquer erro não tratado (antes eles podiam sumir sem registro)."""
    logger.error("Exceção não tratada durante o processamento de uma atualização:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == 'private':
        try:
            await context.bot.send_message(update.effective_chat.id,
                                           "❌ Ocorreu um erro inesperado. Tente novamente ou use /cancelar.")
        except TelegramError:
            pass


# ===================================================================
# == INICIALIZAÇÃO DO BOT ===========================================
# ===================================================================

def botao_menu(texto: str):
    """Filtro que reconhece exatamente o texto de um botão do menu fixo."""
    return filters.TEXT & filters.Regex(f'^{re.escape(texto)}$')


def main() -> None:
    application = (Application.builder()
                   .token(config.TELEGRAM_TOKEN)
                   .connect_timeout(30)
                   .read_timeout(30)
                   .build())

    # --- Comandos do grupo de gestão ---
    application.add_handler(CommandHandler("id", obter_id_chat))
    application.add_handler(CommandHandler("pendencias", pendencias_gestor))
    application.add_handler(CommandHandler("status_meta", status_meta))
    application.add_handler(CommandHandler("lancar", lancar_venda))

    # --- Comandos do funcionário ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancelar", cancelar))  # NOVO: antes não existia
    application.add_handler(CommandHandler("tarefas", tarefas))
    application.add_handler(CommandHandler("ranking", ranking))
    application.add_handler(CommandHandler("meuhistorico", meu_historico))
    application.add_handler(CommandHandler("ajuda", ajuda))
    application.add_handler(CommandHandler("meusaldo", meu_saldo))
    application.add_handler(CommandHandler("loja", loja_recompensas))
    application.add_handler(CommandHandler("documentos", solicitar_documentos_inicio))
    application.add_handler(CommandHandler("conquistas", minhas_conquistas))

    # --- Cliques em botões inline (o específico ANTES do genérico) ---
    application.add_handler(CallbackQueryHandler(iniciar_abate_comanda, pattern='^abater_comanda$'))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # --- Botões do menu fixo ---
    application.add_handler(MessageHandler(botao_menu(BTN_TAREFAS), tarefas))
    application.add_handler(MessageHandler(botao_menu(BTN_RANKING), ranking))
    application.add_handler(MessageHandler(botao_menu(BTN_METAS), acompanhar_metas))
    application.add_handler(MessageHandler(botao_menu(BTN_SALDO), meu_saldo))
    application.add_handler(MessageHandler(botao_menu(BTN_LOJA), loja_recompensas))
    application.add_handler(MessageHandler(botao_menu(BTN_NF), solicitar_foto_nf))
    application.add_handler(MessageHandler(botao_menu(BTN_HISTORICO), meu_historico))
    application.add_handler(MessageHandler(botao_menu(BTN_CONFIDENCIAL), solicitar_feedback_start))
    application.add_handler(MessageHandler(botao_menu(BTN_CONQUISTAS), minhas_conquistas))
    application.add_handler(MessageHandler(botao_menu(BTN_DOCUMENTOS), solicitar_documentos_inicio))
    application.add_handler(MessageHandler(botao_menu(BTN_SOLICITACOES), abrir_central_solicitacoes))
    application.add_handler(MessageHandler(botao_menu(BTN_AJUDA), ajuda))

    # --- Fotos e documentos no chat privado ---
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, receber_foto))
    application.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, receber_foto))

    # --- Texto livre no chat privado (justificativas, CPF, cadastro etc.) ---
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
                                           roteador_de_texto_privado))

    # --- Texto no grupo de gestão (motivo de recusa) ---
    # CORREÇÃO: ChatType.GROUPS aceita grupo E supergrupo.
    # Com ChatType.GROUP, supergrupos (a maioria) eram ignorados.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
                                           receber_motivo_recusa))

    application.add_error_handler(tratar_erro_global)

    logger.info("--- BOT INICIADO COM SUCESSO ---")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

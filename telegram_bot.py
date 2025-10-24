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
        logger.info(f"Pasta de logs criada em: {log_dir}") # Print inicial para confirmar criação
    except OSError as e:
        logger.error(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
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

import recibo_generator
import random
import os
import logging, config, database, random, notificador_telegram
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from PIL import Image
import exifread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler, filters, 
                          ContextTypes, CallbackQueryHandler)
from telegram.helpers import escape_markdown
from database import adicionar_pontos_ao_saldo
import locale
try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    print("Locale pt_BR.UTF-8 não encontrado. Usando o padrão do sistema.")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ===================================================================
# == INÍCIO DAS NOVAS FUNÇÕES DA SALA DE COMANDO (GESTORES) =========
# ===================================================================

async def status_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia o status atual da meta principal para o grupo de gestão."""
    chat_id = update.effective_chat.id
    if chat_id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando é exclusivo para o grupo de gestão.")
        return

    dados_meta = database.buscar_meta_principal_do_dia()
    if not dados_meta or not dados_meta.get('valor_meta'):
        await update.message.reply_text("Nenhuma meta principal está ativa no momento.")
        return

    # Coleta de dados (sem alteração)
    nome = dados_meta['nome_meta']
    atingido = dados_meta['valor_atingido']
    total = dados_meta['valor_meta']
    percentual = (atingido / total) * 100 if total > 0 else 0
    
    # Barra de progresso (sem alteração)
    blocos_cheios = int(percentual // 10); blocos_vazios = 10 - blocos_cheios
    barra_progresso = '▓' * blocos_cheios + '░' * blocos_vazios

    # Cálculo da projeção (sem alteração)
    hoje = date.today()
    dias_no_mes = (hoje.replace(month=hoje.month % 12 + 1, day=1) - timedelta(days=1)).day
    dias_corridos = hoje.day
    media_diaria = atingido / dias_corridos if dias_corridos > 0 else 0
    projecao = media_diaria * dias_no_mes if media_diaria > 0 else 0

    # --- A CORREÇÃO DEFINITIVA ESTÁ AQUI ---
    # Usamos tags HTML (<b> para negrito, <code> para fonte monoespaçada)
    mensagem = (
        f"📊 <b>Status da Meta: {nome}</b> 📊\n\n"
        f"<code>{barra_progresso}</code>  <b>{percentual:.2f}%</b>\n\n"
        f"💰 <b>Atingido:</b> <code>R$ {atingido:,.2f}</code>\n"
        f"🎯 <b>Meta:</b> <code>R$ {total:,.2f}</code>\n\n"
        f"📈 <b>Projeção Final:</b> <code>R$ {projecao:,.2f}</code>"
    )

    # Enviamos a mensagem usando reply_html em vez de reply_markdown_v2
    await update.message.reply_html(mensagem)

# Em telegram_bot.py, SUBSTITUA também a função lancar_venda:

async def lancar_venda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra o valor da apuração diária enviado pelo gestor."""
    chat_id = update.effective_chat.id
    gestor = database.buscar_funcionario_por_chat_id(update.effective_user.id)

    if chat_id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando é exclusivo para o grupo de gestão.")
        return
    if not gestor:
        await update.message.reply_text("Erro: Seu usuário do Telegram não foi encontrado no sistema para registrar esta ação.")
        return

    if not context.args:
        await update.message.reply_text("Por favor, informe o valor a ser lançado.\nExemplo: `/lancar 1250.50`")
        return

    try:
        valor_str = context.args[0].replace(',', '.')
        valor_dia = float(valor_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Valor inválido. Por favor, use apenas números.\nExemplo: `/lancar 1250.50`")
        return

    meta_id = database.buscar_meta_ativa_id_hoje()
    if not meta_id:
        await update.message.reply_text("Erro: Nenhuma meta principal está ativa para hoje. Não é possível lançar.")
        return

    data_hoje_str = date.today().strftime('%Y-%m-%d')
    sucesso, resultado = database.lancar_apuracao_diaria(meta_id, data_hoje_str, valor_dia, gestor.FuncionarioID)

    if sucesso:
        # A mensagem de sucesso agora usa HTML para consistência
        await update.message.reply_html(
            f"✅ <b>Sucesso!</b> Lançamento de <code>R$ {valor_dia:,.2f}</code> registrado por {gestor.NomeCompleto}.\n\n"
            "Aguarde, estou atualizando o status..."
        )
        await status_meta(update, context) # Chama a nova status_meta que também usa HTML
    else:
        await update.message.reply_text(f"❌ Falha ao registrar o lançamento.\nErro: {resultado}")


# ===================================================================
# == FIM DAS NOVAS FUNÇÕES DA SALA DE COMANDO =======================
# ===================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = user.id
    funcionario = database.buscar_funcionario_por_chat_id(chat_id)
    REPLY_KEYBOARD = [
    ["📋 Minhas Tarefas", "🏆 Ranking do Mês", "🎯 Acompanhar Metas"],
    ["💰 Meu Saldo", "🏪 Loja de Recompensas"],
    ["📜 Meu Histórico", "💬 Solicitar Feedback"],
    ["🏅 Minhas Conquistas", "📄 Meus Documentos"], # <<< BOTÃO ADICIONADO AQUI
    ["❓ Ajuda"] # Botão Ajuda movido para a última linha
    ]
    reply_markup = ReplyKeyboardMarkup(REPLY_KEYBOARD, resize_keyboard=True)
    if funcionario:
        mensagem = f"Bem-vindo(a) de volta, <b>{funcionario.NomeCompleto}</b>! 👋\n\nUse os botões abaixo para interagir:"
    else:
        mensagem = "Olá! Parece que seu usuário não foi encontrado no sistema. Por favor, contate seu gestor."
    await update.message.reply_html(mensagem, reply_markup=reply_markup)

async def obter_id_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_html(f"O ID deste chat é: <code>{chat_id}</code>")

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto_ajuda = (
        "Olá! Eu sou seu assistente de gamificação. Aqui estão os comandos:\n\n"
        "📋 **Minhas Tarefas**: Mostra sua lista de tarefas pendentes para hoje.\n"
        "🏆 **Ranking do Mês**: Exibe a classificação de desempenho atual.\n"
        "💰 **Meu Saldo**: Mostra seus pontos acumulados e o valor em R$.\n"
        "🏪 **Loja de Recompensas**: Permite trocar seus pontos por prêmios.\n"
        "📜 **Meu Histórico**: Exibe suas últimas 10 atividades.\n"
        "💬 **Solicitar Feedback**: Envia um pedido de feedback ao seu gestor.\n"
        "📄 **Meus Documentos**: Acessa documentos pessoais, como holerites.\n\n"
        "Use os botões abaixo para começar!"
    )
    await update.message.reply_text(texto_ajuda, reply_markup=update.message.reply_markup)

async def pendencias_gestor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando só pode ser usado no grupo de gestão.")
        return
    funcionarios = database.listar_funcionarios()
    if not funcionarios:
        await update.message.reply_text("Não há funcionários cadastrados no sistema.")
        return
    keyboard = []
    for func in funcionarios:
        keyboard.append([
            InlineKeyboardButton(
                func.NomeCompleto, 
                callback_data=f"ver_pendencias_{func.FuncionarioID}"
            )
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Selecione um funcionário para ver as tarefas pendentes:", reply_markup=reply_markup)

async def tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None) -> None:
    chat_id = update.effective_chat.id; funcionario = database.buscar_funcionario_por_chat_id(chat_id)
    if not funcionario: return
    tarefas_do_dia = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)
    if not tarefas_do_dia:
        texto = "Você não tem nenhuma tarefa pendente para hoje. Bom trabalho! ✨"
        if query: await query.edit_message_text(texto)
        else: await context.bot.send_message(chat_id, texto)
        return
    texto = "📋 **Suas Tarefas para Hoje:**\n\nClique em uma tarefa para ver os detalhes:"
    keyboard = [[InlineKeyboardButton(f"👀 {t.Titulo} ({t.Pontos} pts)", callback_data=f"ver_tarefa_{t.AtribuicaoID}")] for t in tarefas_do_dia]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if query: await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode='Markdown')
    else: await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode='Markdown')

async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Chama a função do banco duas vezes, uma para cada setor
    ranking_cozinha = database.calcular_ranking_desempenho(setor_filtro='Cozinha') #
    ranking_loja = database.calcular_ranking_desempenho(setor_filtro='Loja') #

    # Verifica se algum dos rankings tem dados
    if not ranking_cozinha and not ranking_loja:
        await update.message.reply_text("Ainda não há dados suficientes para gerar os rankings este mês.")
        return

    texto_final = "🏆 **Rankings de Desempenho do Mês** 🏆\n\n"
    texto_final += "O *Score Final* equilibra Confiabilidade e Esforço (70%/30%).\n"

    # --- Ranking Cozinha ---
    texto_final += "\n🍳 **--- Ranking Cozinha ---** 🍳\n"
    if not ranking_cozinha:
        texto_final += "_Sem dados para este setor no momento._\n"
    else:
        icones = ["🥇", "🥈", "🥉"]
        for i, dados in enumerate(ranking_cozinha):
            posicao_icone = icones[i] if i < len(icones) else f" {i+1}."
            nome = dados['NomeCompleto']
            score = dados['ScoreHibrido']
            detalhes = f"(Desemp: {dados['Desempenho']}%, Pts: {dados['PontosGanhos']})" # - Usa os dados retornados
            texto_final += f"{posicao_icone} {nome} - **Score: {score}**\n   {detalhes}\n"

    # --- Ranking Atendimento/Loja ---
    texto_final += "\n🛒 **--- Ranking Atendimento/Loja ---** 🛒\n"
    if not ranking_loja:
        texto_final += "_Sem dados para este setor no momento._\n"
    else:
        icones = ["🥇", "🥈", "🥉"]
        for i, dados in enumerate(ranking_loja):
            posicao_icone = icones[i] if i < len(icones) else f" {i+1}."
            nome = dados['NomeCompleto']
            score = dados['ScoreHibrido']
            detalhes = f"(Desemp: {dados['Desempenho']}%, Pts: {dados['PontosGanhos']})" # - Usa os dados retornados
            texto_final += f"{posicao_icone} {nome} - **Score: {score}**\n   {detalhes}\n"

    await update.message.reply_text(texto_final, parse_mode='Markdown') # - Envia a mensagem combinada

async def meu_historico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia ao usuário um resumo de suas últimas 10 atividades."""
    chat_id = update.effective_chat.id
    
    # 1. Identifica o funcionário pelo Chat ID do Telegram
    funcionario = database.buscar_funcionario_por_chat_id(chat_id)
    if not funcionario:
        await update.message.reply_text("Desculpe, não consegui encontrar seu cadastro no sistema.")
        return

    # 2. Busca o histórico completo no banco de dados
    historico_completo = database.obter_historico_funcionario(funcionario.FuncionarioID)

    if not historico_completo:
        await update.message.reply_text("Você ainda não possui nenhuma atividade registrada no seu histórico.")
        return

    # 3. Monta a mensagem de resposta, pegando apenas os 10 itens mais recentes
    texto_historico = f"📜 <b>Seu Histórico Recente (últimas 10 atividades)</b> 📜\n\n"
    
    for item in historico_completo[:10]: # O [:10] fatia a lista para pegar só os 10 primeiros
        status_icone = "❓" # Padrão
        if item.Status == 'Aprovada':
            status_icone = "✅"
        elif item.Status == 'Recusada':
            status_icone = "❌"
        elif item.Status == 'Pendente (Não Entregue)':
            status_icone = "⏳"

        # Formata a data para ficar mais amigável
        data_envio = item.DataEnvio.strftime("%d/%m/%Y") if item.DataEnvio else "N/A"
        pontos = item.PontosGanhos if item.PontosGanhos is not None else 0
        
        texto_historico += f"{status_icone} <b>{item.Titulo}</b>\n"
        texto_historico += f"    - Status: {item.Status}\n"
        texto_historico += f"    - Pontos: {pontos}\n"
        
        # Adiciona o motivo da recusa, se houver
        if item.MotivoRecusa:
            texto_historico += f"    - Motivo: <i>{item.MotivoRecusa}</i>\n"
        
        texto_historico += "\n"

    # 4. Envia a mensagem formatada em HTML para o usuário
    await update.message.reply_html(texto_historico)    


async def meu_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra o saldo de pontos cumulativo do funcionário."""
    chat_id = update.effective_chat.id
    funcionario = database.buscar_funcionario_por_chat_id(chat_id)
    if not funcionario:
        await update.message.reply_text("Não encontrei seu cadastro no sistema.")
        return

    saldo_pontos = database.buscar_saldo_funcionario(funcionario.FuncionarioID)
    # Usamos a taxa de conversão que definimos no config.py
    valor_monetario = saldo_pontos * config.TAXA_CONVERSAO_PONTO_REAL

    texto = (
        f"💰 <b>Seu Saldo Atual</b> 💰\n\n"
        f"Você acumulou: <b>{saldo_pontos} pontos</b>\n\n"
        f"Isso equivale a <b>R$ {valor_monetario:.2f}</b> para troca na nossa Loja de Recompensas!\n\n"
        "Continue assim para resgatar prêmios incríveis! ✨"
    )
    await update.message.reply_html(texto)

async def loja_recompensas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe os produtos da loja como um menu de botões."""
    # Usamos 'update.effective_chat.id' para funcionar tanto com comandos (/loja) quanto com cliques de botão.
    chat_id = update.effective_chat.id
    produtos = database.listar_produtos_loja() # Lista apenas os produtos ativos por padrão

    if not produtos:
        await context.bot.send_message(chat_id, "Nossa loja de recompensas está vazia no momento. Volte em breve!")
        return

    texto = "🏪 **Loja de Recompensas** 🏪\n\nEscolha um item para ver os detalhes e resgatar:"
    keyboard = []
    for produto in produtos:
        # Mostra o estoque se ele for limitado
        estoque_str = f"({produto.EstoqueDisponivel} un.)" if produto.EstoqueDisponivel is not None else ""
        texto_botao = f"{produto.Nome} - {produto.CustoEmPontos} pts {estoque_str}"
        keyboard.append([InlineKeyboardButton(texto_botao, callback_data=f"ver_produto_{produto.ProdutoID}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, texto, reply_markup=reply_markup)

async def solicitar_holerite_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o fluxo de solicitação de holerite com verificação de segurança."""
    chat_id = update.effective_chat.id
    funcionario = database.buscar_funcionario_por_chat_id(chat_id)

    if not funcionario or not funcionario.VerificadorCPF:
        await update.message.reply_text("Desculpe, esta funcionalidade não está habilitada para você. Por favor, contate o RH para cadastrar seu código de verificação.")
        return

    context.user_data['aguardando_verificador_cpf'] = True
    await update.message.reply_text("Para sua segurança, por favor, digite os 3 primeiros dígitos do seu CPF.")


async def roteador_de_texto_privado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Esta função atua como um roteador para todas as mensagens de texto em chat privado.
    Ela verifica o 'estado' do usuário e direciona para a ação correta.
    """
    user_data = context.user_data
    texto_recebido = update.message.text
    chat_id = update.effective_chat.id
    funcionario = database.buscar_funcionario_por_chat_id(chat_id)

    if not funcionario:
        return # Se o funcionário não for encontrado, não faz nada

    # Cenário 1: O usuário está enviando o código de verificação do CPF
    if 'aguardando_verificador_cpf' in user_data:
        user_data.pop('aguardando_verificador_cpf')
        verificador_correto = database.buscar_verificador_cpf(funcionario.FuncionarioID)

        if texto_recebido.strip() == verificador_correto:
            await update.message.reply_text("✅ Verificação bem-sucedida! Buscando seus documentos...")
            
            holerites_disponiveis = database.buscar_holerites_disponiveis(funcionario.FuncionarioID)

            if not holerites_disponiveis:
                await update.message.reply_text("Você não possui novos holerites para visualizar no momento.")
                return

            keyboard = []
            for holerite in holerites_disponiveis:
                # Formata a data para ex: "Setembro/2025"
                mes_ano_str = holerite.MesAno.strftime('%B/%Y').capitalize()
                # Guarda a data no formato do banco para o callback
                data_callback = holerite.MesAno.strftime('%Y-%m-%d')
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"📄 {mes_ano_str}", 
                        callback_data=f"get_holerite_{data_callback}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Selecione o holerite que deseja visualizar:", reply_markup=reply_markup)

        else:
            await update.message.reply_text("❌ Código de verificação incorreto. Por favor, inicie o processo novamente com /holerite ou usando o botão 'Meus Documentos'.")
        return

    # Cenário 2: O usuário está justificando uma tarefa "Não Aplicável"
    if 'tarefa_nao_aplicavel' in user_data:
        atribuicao_id = user_data.pop('tarefa_nao_aplicavel')
        database.registrar_tarefa_nao_aplicavel(atribuicao_id, texto_recebido)
        
        keyboard = [[InlineKeyboardButton("⬅️ Ver Tarefas Restantes", callback_data="voltar_lista_tarefas")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Ok, justificativa registrada!", reply_markup=reply_markup)
        return

    # Cenário 3: O usuário está enviando o assunto para uma solicitação de feedback
    if 'aguardando_assunto_feedback' in user_data:
        user_data.pop('aguardando_assunto_feedback')
        sucesso = database.criar_solicitacao_feedback(funcionario.FuncionarioID, texto_recebido)
        if sucesso:
            mensagem_gestor = (f"📢 **Nova Solicitação de Feedback**\n\n👤 **De:** {funcionario.NomeCompleto}\n📝 **Assunto:** {texto_recebido}")
            notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
            await update.message.reply_text("✅ Sua solicitação de feedback foi enviada com sucesso aos gestores!")
        else:
            await update.message.reply_text("❌ Ocorreu um erro ao salvar sua solicitação. Tente novamente.")
        return

    # Cenário Padrão
    await update.message.reply_text("Não entendi o que você quis dizer. Use os botões do menu para interagir comigo. Se precisar, use o comando /ajuda.")


async def solicitar_feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de solicitação de feedback."""
    await update.message.reply_text(
        "Entendido. Sobre qual tarefa ou assunto você gostaria de solicitar um feedback?"
    )
    # Define um "estado" para o usuário, indicando que a próxima mensagem dele é o assunto.
    context.user_data['aguardando_assunto_feedback'] = True


async def receber_foto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    MAX_SECONDS_DIFFERENCE = 120
    temp_photo_path = None

    try:
        # Camada 1 de Verificação (continua igual)
        if update.message.forward_from or update.message.forward_from_chat:
            await update.message.reply_text("❌ Desculpe, fotos encaminhadas não são aceitas.")
            return
        if update.message.document and 'image' in update.message.document.mime_type:
            await update.message.reply_text("❌ Por favor, envie a imagem como 'Foto', e não como 'Arquivo'.")
            return
        
        # Camada 2 de Verificação (com a lógica de fuso horário e MAIS FLEXÍVEL)
        photo_file = await update.message.photo[-1].get_file()
        message_timestamp_utc = update.message.date 

        temp_photo_path = f"temp_{photo_file.file_id}.jpg"
        await photo_file.download_to_drive(temp_photo_path)

        with open(temp_photo_path, 'rb') as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal")
            
            # --- A LÓGICA FOI AJUSTADA AQUI ---
            # Agora, nós SÓ fazemos a verificação de tempo SE a etiqueta de data existir.
            if "EXIF DateTimeOriginal" in tags:
                date_str = str(tags["EXIF DateTimeOriginal"])
                photo_timestamp_naive = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                
                try:
                    # Tenta usar o fuso de Cuiabá, se não conseguir, usa o de São Paulo como padrão
                    photo_timestamp_aware = photo_timestamp_naive.replace(tzinfo=ZoneInfo("America/Cuiaba"))
                except:
                    photo_timestamp_aware = photo_timestamp_naive.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))

                photo_timestamp_utc = photo_timestamp_aware.astimezone(timezone.utc)
                time_difference = message_timestamp_utc - photo_timestamp_utc
                
                # Se a etiqueta existe E a foto é antiga, aí sim nós recusamos.
                if time_difference.total_seconds() < 0 or time_difference.total_seconds() > MAX_SECONDS_DIFFERENCE:
                    await update.message.reply_text(f"❌ Foto recusada! A evidência parece ser antiga (de mais de 2 minutos atrás). Por favor, envie uma foto tirada na hora.")
                    return
            
            # Se a etiqueta "EXIF DateTimeOriginal" simplesmente não existir, o código não faz nada
            # e segue em frente, confiando nas outras verificações. O 'else' que recusava foi removido.
            # --- FIM DO AJUSTE ---

        # Se chegou até aqui, a foto é válida! O código continua normalmente...
        if 'identificador_tarefa' not in context.user_data: 
            await update.message.reply_text("Parece que você enviou uma foto sem antes selecionar uma tarefa. Por favor, use o comando /tarefas primeiro.")
            return
        
        # ... (O resto da função continua exatamente igual)
        atribuicao_id = int(context.user_data.pop('identificador_tarefa'))
        funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
        tarefa = database.buscar_tarefa_por_atribuicao(atribuicao_id)
        
        if not (funcionario and tarefa):
            await update.message.reply_text("Ocorreu um erro ao identificar seus dados ou a tarefa.")
            return
            
        photo_size = update.message.photo[-1]
        file_id = photo_size.file_id
        entrega_id = database.registrar_entrega_preliminar(tarefa.TarefaID, funcionario.FuncionarioID, atribuicao_id, file_id)

        if entrega_id and config.GESTOR_GROUP_CHAT_ID:
            titulo_sanitizado = escape_markdown(str(tarefa.Titulo), version=2)
            nome_funcionario_sanitizado = escape_markdown(str(funcionario.NomeCompleto), version=2)
            legenda = (f"**Nova Entrega para Validação**\n\n"
                    f"👤 **Funcionário:** {nome_funcionario_sanitizado}\n"
                    f"📝 **Tarefa:** {tarefa.Titulo} ({tarefa.Pontos} pts)\n"
                    f"🗓️ **Data:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")
            keyboard = [[
                InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_gestor_{entrega_id}"),
                InlineKeyboardButton("❌ Reprovar", callback_data=f"reprovar_gestor_{entrega_id}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            notificador_telegram.enviar_foto_com_botoes(config.GESTOR_GROUP_CHAT_ID, file_id, legenda, reply_markup)

        await update.message.reply_text("✅ Evidência válida! Entrega registrada com sucesso e enviada para validação!")

    except Exception as e:
        logger.error(f"Erro crítico em receber_foto: {e}", exc_info=True)
        await update.message.reply_text("Ocorreu um erro crítico ao registrar sua entrega. Contate o administrador.")

    finally:
        if temp_photo_path and os.path.exists(temp_photo_path):
            os.remove(temp_photo_path)
        

async def receber_motivo_recusa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    
    chat_id_grupo = update.effective_chat.id
    if 'aguardando_motivo_recusa' not in context.chat_data or chat_id_grupo != config.GESTOR_GROUP_CHAT_ID:
        return

    entrega_id = context.chat_data.pop('aguardando_motivo_recusa')
    motivo = update.message.text
    gestor_nome = update.effective_user.first_name

    detalhes = database.buscar_detalhes_da_entrega(entrega_id)
    
    if not detalhes or detalhes.StatusValidacao != 'Pendente':
        await update.message.reply_text("Esta tarefa já foi validada por outro gestor ou não foi encontrada.")
        return
    
    database.recusar_entrega(entrega_id, motivo)
    
    texto_notificacao = (f"⚠️ Atenção, <b>{detalhes.NomeCompleto}</b>!\n\n"
                         f"Sua entrega para a tarefa '<b>{detalhes.Titulo}</b>' foi RECUSADA.\n\n"
                         f"<b>Motivo:</b> {motivo}\n\n"
                         "Por favor, corrija e envie novamente.")
    
    notificador_telegram.enviar_mensagem(detalhes.ChatIDFuncionario, texto_notificacao)

    legenda_final = (f"**Entrega RECUSADA por {gestor_nome}**\n\n"
                     f"👤 **Funcionário:** {detalhes.NomeCompleto}\n"
                     f"📝 **Tarefa:** {detalhes.Titulo}\n"
                     f"💬 **Motivo:** {motivo}")
    
    id_mensagem_original = context.chat_data.pop(f'msg_id_{entrega_id}', None)
    if id_mensagem_original:
        try:
            await context.bot.edit_message_caption(chat_id=chat_id_grupo, message_id=id_mensagem_original, caption=legenda_final)
        except Exception as e:
            logger.error(f"Erro ao editar caption da mensagem recusada: {e}")
            await update.message.reply_text(legenda_final)
    
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # --- LÓGICA DE DOCUMENTOS PESSOAIS (HOLERITE) ---
    if data.startswith("get_holerite_"):
        await query.edit_message_text("Processando sua solicitação...")
        mes_ano_iso = data.split('_')[-1]
        funcionario = database.buscar_funcionario_por_chat_id(user.id)
        dados_holerite = database.buscar_dados_holerite_para_envio(funcionario.FuncionarioID, mes_ano_iso)
        if not dados_holerite:
            await query.edit_message_text("Erro: Não foi possível encontrar este documento.")
            return
        caminho_arquivo, ciencia_id = dados_holerite
        keyboard = [[InlineKeyboardButton("✅ Recebi e estou ciente", callback_data=f"holerite_ciente_{ciencia_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            with open(caminho_arquivo, 'rb') as documento:
                await context.bot.send_document(
                    chat_id=user.id,
                    document=documento,
                    caption=f"Aqui está seu documento referente a {datetime.strptime(mes_ano_iso, '%Y-%m-%d').strftime('%B de %Y').capitalize()}.\n\nPor favor, confirme o recebimento.",
                    reply_markup=reply_markup
                )
            await query.edit_message_text("✔️ Seu documento foi enviado. Por favor, verifique a nova mensagem e confirme a ciência.")
        except FileNotFoundError:
            await query.edit_message_text("❌ ERRO CRÍTICO: O arquivo do documento não foi encontrado no servidor. Por favor, contate o RH.")
        except Exception as e:
            await query.edit_message_text(f"❌ Ocorreu um erro inesperado ao enviar seu documento: {e}")

    elif data.startswith("holerite_ciente_"):
        ciencia_id = int(data.split('_')[-1])
        sucesso = database.marcar_holerite_como_ciente(ciencia_id)
        if not sucesso:
            await query.answer("Este documento já foi assinado.", show_alert=True)
            return
        mensagem_gestor = f"✍️ O funcionário **{user.first_name}** confirmou o recebimento de um documento pessoal (Holerite)."
        notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
        mensagem_recibo = (
            f"\n\n---"
            f"\n✍️ **CIÊNCIA REGISTRADA**"
            f"\n**Protocolo:** `{ciencia_id}`"
            f"\n**Data/Hora:** `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`"
        )
        try:
            texto_original = query.message.caption
            await query.edit_message_caption(caption=f"{texto_original}{mensagem_recibo}", parse_mode='Markdown', reply_markup=None)
        except Exception as e:
            logger.error(f"Erro ao editar a legenda do holerite: {e}")
            await query.answer("Recebimento confirmado!", show_alert=True)

    # --- LÓGICA DA LOJA DE RECOMPENSAS ---
    elif data.startswith("ver_produto_"):
        produto_id = int(data.split('_')[-1])
        produtos = database.listar_produtos_loja(incluir_inativos=True)
        produto = next((p for p in produtos if p.ProdutoID == produto_id), None)
        if not produto:
            await query.edit_message_text("Este produto não está mais disponível.")
            return
        funcionario = database.buscar_funcionario_por_chat_id(user.id)
        saldo_atual = database.buscar_saldo_funcionario(funcionario.FuncionarioID)
        texto = (f"<b>{produto.Nome}</b>\n\n<i>{produto.Descricao}</i>\n\nCusto: <b>{produto.CustoEmPontos} pontos</b>\nSeu Saldo: <b>{saldo_atual} pontos</b>")
        keyboard = [[InlineKeyboardButton("✅ Confirmar Resgate", callback_data=f"confirmar_resgate_{produto.ProdutoID}")],
                    [InlineKeyboardButton("⬅️ Voltar para a Loja", callback_data="voltar_loja")]]
        if saldo_atual < produto.CustoEmPontos:
            texto += "\n\n⚠️ Você não tem pontos suficientes para resgatar este item."
            keyboard.pop(0)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode='HTML')

    elif data.startswith("confirmar_resgate_"):
        produto_id = int(data.split('_')[-1])
        funcionario = database.buscar_funcionario_por_chat_id(user.id)
        sucesso, mensagem, resgate_id = database.solicitar_resgate(funcionario.FuncionarioID, produto_id)
        await query.edit_message_text(mensagem)
        if sucesso:
            produto = next((p for p in database.listar_produtos_loja(incluir_inativos=True) if p.ProdutoID == produto_id), None)
            msg_gestor = (f"🔔 **Nova Solicitação de Resgate** 🔔\n\n👤 **Funcionário:** {funcionario.NomeCompleto}\n🎁 **Produto:** {produto.Nome}\n💰 **Custo:** {produto.CustoEmPontos} pontos\n\nAcesse o sistema (`main.py`) para aprovar.")
            notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, msg_gestor)

    elif data == "voltar_loja":
        produtos = database.listar_produtos_loja()
        texto = "🏪 **Loja de Recompensas** 🏪\n\nEscolha um item para ver os detalhes e resgatar:"
        keyboard = []
        for produto in produtos:
            estoque_str = f"({produto.EstoqueDisponivel} un.)" if produto.EstoqueDisponivel is not None else ""
            texto_botao = f"{produto.Nome} - {produto.CustoEmPontos} pts {estoque_str}"
            keyboard.append([InlineKeyboardButton(texto_botao, callback_data=f"ver_produto_{produto.ProdutoID}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')

    # --- LÓGICA DE FEEDBACK DE FIM DE JORNADA ---
    elif data == "avaliar_dia":
        keyboard = []; row = []
        for i in range(11):
            row.append(InlineKeyboardButton(str(i), callback_data=f"nota_dia_{i}"))
            if len(row) == 5 or i == 10: keyboard.append(row); row = []
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=(f"{query.message.text}\n\nComo você classificaria seu dia de 0 a 10?\n(0 = Muito Ruim / 10 = Excelente)"), reply_markup=reply_markup)

    elif data.startswith("nota_dia_"):
        nota = int(data.split('_')[-1])
        funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
        if funcionario_db:
            sucesso = database.salvar_feedback_do_dia(funcionario_db.FuncionarioID, nota)
            if sucesso:
                database.registrar_pontos_por_leitura(funcionario_db.FuncionarioID, config.PONTOS_BONUS_FEEDBACK_DIARIO, "Feedback Diário (Bônus)")
                database.adicionar_pontos_ao_saldo(funcionario_db.FuncionarioID, config.PONTOS_BONUS_FEEDBACK_DIARIO)
                texto_final = (f"Obrigado pelo seu feedback! Sua nota foi **{nota}**.\n\nVocê ganhou **{config.PONTOS_BONUS_FEEDBACK_DIARIO}** pontos por sua participação. Sua opinião nos ajuda a melhorar sempre! 💪")
                await query.edit_message_text(texto_final, parse_mode='Markdown')
            else: await query.edit_message_text("Você já enviou seu feedback hoje. Obrigado!")
        else: await query.edit_message_text("Erro: não foi possível identificar seu usuário.")

    elif data.startswith("aceitar_tarefa_"):
        origem_atribuicao_id = int(data.split('_')[-1]) # ID da tarefa 'GrupoCompetitiva' original
        funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
        if not funcionario_db:
            await context.bot.send_message(chat_id=user.id, text="Seu usuário do Telegram não foi encontrado no nosso sistema.")
            return

        # Chama a NOVA versão da função, que tenta CRIAR a instância 'Unica'
        nova_atribuicao_id_criada = database.aceitar_tarefa_de_grupo(origem_atribuicao_id, funcionario_db.FuncionarioID)

        # Busca o título da tarefa original para as mensagens
        tarefa_original = database.buscar_tarefa_por_atribuicao(origem_atribuicao_id)
        tarefa_titulo = tarefa_original.Titulo if tarefa_original else "Tarefa desconhecida"

        if nova_atribuicao_id_criada:
            # SUCESSO! A instância 'Unica' foi criada para este funcionário HOJE.
            nova_mensagem_grupo = (
                f"✅ **Missão Aceita por {user.first_name}!** ✅\n\n"
                f"**Tarefa:** {tarefa_titulo}\n\n"
                f"{user.first_name} agora é o responsável pela entrega *de hoje*. Boa sorte!"
            )
            try:
                # Tenta editar a mensagem original no grupo (pode falhar para msg antigas)
                await query.edit_message_text(text=nova_mensagem_grupo, reply_markup=None) # Remove o botão
            except Exception as e:
                logger.info(f"Aviso: Não foi possível editar a mensagem original no grupo para {origem_atribuicao_id}. Erro: {e}")
                # Poderia enviar uma nova mensagem ou reply como alternativa aqui.

            await context.bot.send_message(
                chat_id=user.id,
                text=f"Você aceitou a missão '{tarefa_titulo}' para hoje. Agora ela aparecerá na sua lista de /tarefas. Capriche na entrega! 💪"
            )
        else:
            # FALHA! Alguém já aceitou HOJE ou ocorreu outro erro.
            await context.bot.send_message(
                chat_id=user.id,
                text=f"Que pena, parece que um colega foi mais rápido e já aceitou a missão '{tarefa_titulo}' *hoje*. Fique de olho na oferta de amanhã! 👀",
            )

    elif data.startswith("aceitar_folga_"):
        tarefa_id = int(data.split('_')[-1])
        funcionario_aceitou = database.buscar_funcionario_por_chat_id(user.id)
        if not funcionario_aceitou:
            await context.bot.send_message(chat_id=user.id, text="Seu usuário do Telegram não foi encontrado no nosso sistema.")
            return

        tarefas_atuais = database.listar_tarefas_do_dia_por_funcionario(funcionario_aceitou.FuncionarioID)
        ids_tarefas_atuais = [t.TarefaID for t in tarefas_atuais]
        if tarefa_id in ids_tarefas_atuais:
            await context.bot.send_message(chat_id=user.id, text="Você já tem essa tarefa na sua lista de hoje ou ela já foi pega por outro colega. Obrigado pelo interesse!")
            # Edita a mensagem do grupo para refletir que a tarefa já foi pega
            try:
                await query.edit_message_text(text=f"{query.message.text}\n\n--- TAREFA JÁ ATRIBUÍDA ---")
            except:
                pass # Ignora se não conseguir editar
            return

        # --- LÓGICA CORRIGIDA E ROBUSTA ---
        # 1. Atribui a tarefa e captura o novo ID da atribuição
        novo_atribuicao_id = database.atribuir_tarefa(tarefa_id, funcionario_aceitou.FuncionarioID, 'Unica', None)
        
        # 2. Busca os detalhes da tarefa de forma segura, usando o ID que acabamos de obter
        tarefa_info = database.buscar_tarefa_por_atribuicao(novo_atribuicao_id)
        # --- FIM DA CORREÇÃO ---
        
        nova_mensagem_grupo = (
            f"{query.message.text}\n\n"
            f"--- MISSÃO REIVINDICADA! ---\n"
            f"✅ **{funcionario_aceitou.NomeCompleto}** assumiu a tarefa."
        )
        await query.edit_message_text(text=nova_mensagem_grupo, reply_markup=None)
        await context.bot.send_message(
            chat_id=user.id,
            text=f"🚀 Você assumiu a missão extra '{tarefa_info.Titulo}'! Ela já está na sua lista de /tarefas. Bom trabalho!"
        )

    # --- LÓGICA DE VISUALIZAÇÃO DE PENDÊNCIAS (GESTOR) ---
    elif data.startswith("ver_pendencias_"):
        funcionario_id = int(data.split('_')[-1])
        funcionario = database.buscar_funcionario_por_id(funcionario_id)
        tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario_id)
        if not funcionario:
            await query.edit_message_text("Erro: Funcionário não encontrado.")
            return
        texto_resposta = f"📋 **Tarefas Pendentes para {funcionario.NomeCompleto}**\n\n"
        if not tarefas_pendentes:
            texto_resposta += "Nenhuma tarefa pendente no momento. Bom trabalho! ✅"
        else:
            for tarefa in tarefas_pendentes:
                texto_resposta += f"  - {tarefa.Titulo} ({tarefa.Pontos} pts)\n"
        keyboard = [[InlineKeyboardButton("⬅️ Voltar para a lista", callback_data="voltar_lista_funcs")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(texto_resposta, reply_markup=reply_markup, parse_mode='Markdown')

    elif data == "voltar_lista_funcs":
        funcionarios = database.listar_funcionarios()
        keyboard = [[InlineKeyboardButton(f.NomeCompleto, callback_data=f"ver_pendencias_{f.FuncionarioID}")] for f in funcionarios]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Selecione um funcionário para ver as tarefas pendentes:", reply_markup=reply_markup)

    # --- LÓGICA DE CIÊNCIA DE COMUNICADOS ---
    elif data.startswith("doc_ciente_"):
        await query.answer() # Responde ao clique imediatamente para o usuário não ver o "carregando"
        assinatura_id = int(data.split('_')[-1])
        detalhes = database.buscar_detalhes_assinatura_para_bot(assinatura_id)
        
        if not detalhes:
            # Tenta avisar o usuário com um pop-up que é mais garantido
            await query.answer("Esta ciência já foi registrada anteriormente.", show_alert=True)
            return

        # Lógica de backend que já está funcionando perfeitamente
        nome_funcionario = user.first_name 
        mensagem_gestor = f"✅ O funcionário **{nome_funcionario}** confirmou ciência do comunicado: *'{detalhes.Titulo}'*."
        notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
        database.marcar_como_ciente(assinatura_id)
        
        datetime_ciencia = datetime.now()
        mensagem_confirmacao = (
            f"\n\n---"
            f"\n📜 **RECIBO DE CIÊNCIA** 📜"
            f"\n\nSua confirmação de leitura foi registrada com sucesso."
            f"\n\n**Protocolo:** `{assinatura_id}`"
            f"\n**Data:** `{datetime_ciencia.strftime('%d/%m/%Y')}`"
            f"\n**Hora:** `{datetime_ciencia.strftime('%H:%M:%S')}`"
        )
        if detalhes.PontosPorCiencia > 0:
            database.registrar_pontos_por_leitura(detalhes.FuncionarioID, detalhes.PontosPorCiencia, detalhes.Titulo)
            adicionar_pontos_ao_saldo(detalhes.FuncionarioID, detalhes.PontosPorCiencia)
            mensagem_confirmacao += f"\n\n🎉 Você ganhou **{detalhes.PontosPorCiencia}** pontos por sua agilidade!"
        
        # <<< AQUI ESTÁ A LÓGICA DE EDIÇÃO BLINDADA E CORRIGIDA >>>
        try:
            # A verificação mais segura é se a mensagem tem o atributo 'photo'
            if query.message.photo:
                texto_original = query.message.caption
                # A função correta: edit_message_caption
                await query.edit_message_caption(
                    caption=f"{texto_original}{mensagem_confirmacao}",
                    parse_mode='Markdown',
                    reply_markup=None
                )
            # Se não for foto, com certeza é texto
            else:
                texto_original = query.message.text
                # A função para texto: edit_message_text
                await query.edit_message_text(
                    text=f"{texto_original}{mensagem_confirmacao}",
                    parse_mode='Markdown',
                    reply_markup=None
                )
        except Exception as e:
            # Se, mesmo assim, a edição falhar, nós saberemos o porquê
            logger.error(f"!!!!!!!! ERRO AO TENTAR EDITAR A MENSAGEM DE CIÊNCIA: {e} !!!!!!!!")
            # E o usuário receberá um feedback visual
            await query.answer("Sua ciência foi registrada com sucesso!", show_alert=True)

    # --- LÓGICA DE ENTREGA DE TAREFAS (FUNCIONÁRIO) ---
    elif data.startswith("ver_tarefa_"):
        atribuicao_id = int(data.split('_')[-1])
        detalhes = database.buscar_detalhes_da_atribuicao(atribuicao_id)
        if not detalhes: await query.edit_message_text("Erro: Tarefa não encontrada."); return
        texto = f"📄 **Detalhes:** *{detalhes.Descricao}*\n\nO que deseja fazer?"
        keyboard = [[InlineKeyboardButton("✅ Enviar Evidência", callback_data=f"entregar_{atribuicao_id}")],
                    [InlineKeyboardButton("🤷 Não Aplicável", callback_data=f"nao_aplicavel_{atribuicao_id}")],
                    [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_lista_tarefas")]]
        await query.edit_message_text(text=texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data.startswith("entregar_"):
        context.user_data['identificador_tarefa'] = int(data.split('_')[-1])
        await query.edit_message_text(text="Excelente! ✅\nAgora, por favor, envie a foto de evidência.")

    elif data.startswith("nao_aplicavel_"):
        context.user_data['tarefa_nao_aplicavel'] = int(data.split('_')[-1])
        await query.edit_message_text(text="Entendido. 🤷\nPor favor, diga o motivo (ex: 'Chuva', 'Nenhum cliente').")

    elif data == "voltar_lista_tarefas":
        await tarefas(update, context, query=query)

    elif data.startswith("aprovar_gestor_"):
        entrega_id = int(data.split('_')[-1])
        gestor_nome = query.from_user.first_name
        detalhes = database.buscar_detalhes_da_entrega(entrega_id)
        if not detalhes or detalhes.StatusValidacao != 'Pendente':
            await query.edit_message_caption(caption=f"Esta tarefa já foi validada por outro gestor. (Status: {detalhes.StatusValidacao if detalhes else 'N/A'})")
            return
        novas_conquistas_ganhas = database.aprovar_entrega(entrega_id, detalhes.FuncionarioID, detalhes.Pontos)
        texto_notificacao = (f"🎉 Parabéns, <b>{detalhes.NomeCompleto}</b>!\nSua entrega para '<b>{detalhes.Titulo}</b>' foi APROVADA!\n\n"
                             f"Você ganhou <b>{detalhes.Pontos}</b> pontos. Continue assim!")
        if novas_conquistas_ganhas:
            for conquista in novas_conquistas_ganhas:
                texto_notificacao += (
                    f"\n\n✨ <b>NOVA CONQUISTA DESBLOQUEADA!</b> ✨\n"
                    f"{conquista.Icone} <b>{conquista.Nome}</b>\n"
                    f"<i>{conquista.Descricao}</i>\n"
                    f"Você ganhou um bônus de <b>{conquista.PontosBonus}</b> pontos!"
                )
        notificador_telegram.enviar_mensagem(detalhes.ChatIDFuncionario, texto_notificacao)
        legenda_final = (f"**Entrega APROVADA por {gestor_nome}**\n\n"
                         f"👤 **Funcionário:** {detalhes.NomeCompleto}\n"
                         f"📝 **Tarefa:** {detalhes.Titulo} (+{detalhes.Pontos} pts)")
        await query.edit_message_caption(caption=legenda_final)

        if novas_conquistas_ganhas:
            for conquista in novas_conquistas_ganhas:
                texto_notificacao += (
                    f"\n\n✨ <b>NOVA CONQUISTA DESBLOQUEADA!</b> ✨\n"
                    f"{conquista.Icone} <b>{conquista.Nome}</b>\n"
                    f"<i>{conquista.Descricao}</i>\n"
                    f"Você ganhou um bônus de <b>{conquista.PontosBonus}</b> pontos!"
                )
                if conquista.PontosBonus > 0:
                    database.adicionar_pontos_ao_saldo(detalhes.FuncionarioID, conquista.PontosBonus) 

    elif data.startswith("reprovar_gestor_"):
        entrega_id = int(data.split('_')[-1])
        context.chat_data['aguardando_motivo_recusa'] = entrega_id
        context.chat_data[f'msg_id_{entrega_id}'] = query.message.message_id
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Por favor, {query.from_user.first_name}, digite o motivo da recusa para esta tarefa.")

async def acompanhar_metas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia para o funcionário o status da meta principal em formato de porcentagem."""

    dados_meta = database.buscar_meta_principal_do_dia()

    if not dados_meta or not dados_meta.get('valor_meta'):
        await update.message.reply_text("Nenhuma meta de equipe está ativa no momento. Foco nas tarefas individuais! 💪")
        return

    nome = dados_meta['nome_meta']
    atingido = dados_meta['valor_atingido']
    total = dados_meta['valor_meta']
    percentual = (atingido / total) * 100 if total > 0 else 0

    blocos_cheios = int(percentual // 10)
    blocos_vazios = 10 - blocos_cheios
    barra_progresso = '▓' * blocos_cheios + '░' * blocos_vazios

    mensagem = (
        f"🎯 <b>Meta da Equipe: {nome}</b> 🎯\n\n"
        f"Estamos quase lá! Este é o nosso progresso até agora:\n\n"
        f"<code>{barra_progresso}</code>\n\n"
        f"🏁 <b>Progresso: {percentual:.2f}% de 100%</b>\n\n"
        "Vamos com tudo, equipe! 🚀"
    )

    await update.message.reply_html(mensagem)

async def minhas_conquistas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a lista de conquistas já desbloqueadas pelo funcionário."""
    user = update.effective_user
    chat_id = user.id
    funcionario = database.buscar_funcionario_por_chat_id(chat_id) #

    if not funcionario:
        await update.message.reply_text("Desculpe, não consegui encontrar seu cadastro no sistema.") #
        return

    conquistas_ganhas = database.listar_conquistas_por_funcionario(funcionario.FuncionarioID) #

    if not conquistas_ganhas:
        await update.message.reply_text("Você ainda não desbloqueou nenhuma conquista. Continue se esforçando! 💪") #
        return

    texto_conquistas = f"🏅 **Suas Conquistas Desbloqueadas** ({len(conquistas_ganhas)}) 🏅\n\nParabéns pelas suas realizações!\n"

    for conquista in conquistas_ganhas:
        data_formatada = conquista.DataConquista.strftime('%d/%m/%Y') # - Formata a data
        texto_conquistas += (
            f"\n--------------------\n"
            f"{conquista.Icone} <b>{conquista.Nome}</b>\n" # - Usa os dados do banco
            f"<i>{conquista.Descricao}</i>\n" #
            f"<pre>Desbloqueada em: {data_formatada}</pre>\n" # - Usa <pre> para monoespaçado
        )

    await update.message.reply_html(texto_conquistas) #

def main() -> None:
    application = Application.builder().token(config.TELEGRAM_TOKEN).connect_timeout(30).read_timeout(30).build()
    
    # --- Comandos do Admin ---
    application.add_handler(CommandHandler("id", obter_id_chat))
    application.add_handler(CommandHandler("pendencias", pendencias_gestor))
    application.add_handler(CommandHandler("status_meta", status_meta))
    application.add_handler(CommandHandler("lancar", lancar_venda))

    # --- Comandos do Funcionário ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tarefas", tarefas))
    application.add_handler(CommandHandler("ranking", ranking))
    application.add_handler(CommandHandler("meuhistorico", meu_historico))
    application.add_handler(CommandHandler("ajuda", ajuda))
    application.add_handler(CommandHandler("meusaldo", meu_saldo))
    application.add_handler(CommandHandler("loja", loja_recompensas))
    application.add_handler(CommandHandler("holerite", solicitar_holerite_inicio)) 
    application.add_handler(CommandHandler("conquistas", minhas_conquistas)) # <<< NOVO COMANDO
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏅 Minhas Conquistas$'), minhas_conquistas)) # <<< NOVO BOTÃO
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # --- Handlers para os Botões do Menu Fixo ---
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📋 Minhas Tarefas$'), tarefas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏆 Ranking do Mês$'), ranking))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🎯 Acompanhar Metas$'), acompanhar_metas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📜 Meu Histórico$'), meu_historico))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^❓ Ajuda$'), ajuda))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💰 Meu Saldo$'), meu_saldo))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏪 Loja de Recompensas$'), loja_recompensas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💬 Solicitar Feedback$'), solicitar_feedback_start)) 
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📄 Meus Documentos$'), solicitar_holerite_inicio)) 
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏅 Minhas Conquistas$'), minhas_conquistas)) # <<< NOVO BOTÃO
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, receber_foto))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, roteador_de_texto_privado))
    
    logger.info("--- BOT INICIADO COM SUCESSO ---")
    application.run_polling()

if __name__ == '__main__':
    main()

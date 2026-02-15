<<<<<<< HEAD
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

# Em telegram_bot.py
# --- Cria a pasta de logs se não existir ---
log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        # CORREÇÃO: Usar print() antes do logger ser definido.
        print(f"Pasta de logs criada em: {log_dir}") 
    except OSError as e:
        # CORREÇÃO: Usar print() antes do logger ser definido.
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
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
import urllib.parse
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

async def lancar_venda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra o valor da apuração diária enviado pelo gestor."""
    chat_id = update.effective_chat.id
    gestor = database.buscar_funcionario_por_chat_id(update.effective_user.id)

    # Verifica se é o grupo de gestão
    if chat_id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando é exclusivo para o grupo de gestão.")
        return
    # Verifica se o gestor foi encontrado no banco
    if not gestor:
        await update.message.reply_text("Erro: Seu usuário do Telegram não foi encontrado no sistema para registrar esta ação.")
        return

    # Verifica se o valor foi fornecido
    if not context.args:
        await update.message.reply_text("Por favor, informe o valor a ser lançado.\nExemplo: `/lancar 1250.50`")
        return

    # Tenta converter o valor para float
    try:
        valor_str = context.args[0].replace(',', '.')
        valor_dia = float(valor_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Valor inválido. Por favor, use apenas números.\nExemplo: `/lancar 1250.50`")
        return

    # Busca o ID da meta principal ativa para hoje
    meta_id = database.buscar_meta_ativa_id_hoje()
    if not meta_id:
        await update.message.reply_text("Erro: Nenhuma meta principal está ativa para hoje. Não é possível lançar.")
        return

    # Pega a data de hoje e formata para o banco
    data_hoje_obj = date.today() # Pega o objeto date
    data_hoje_str = data_hoje_obj.strftime('%Y-%m-%d')

    # Tenta lançar a apuração no banco
    sucesso, resultado = database.lancar_apuracao_diaria(meta_id, data_hoje_str, valor_dia, gestor.FuncionarioID)

    if sucesso:
        apuracao_id = resultado # Captura o ID da apuração retornado pelo banco

        # Envia mensagem de sucesso
        await update.message.reply_html(
            f"✅ <b>Sucesso!</b> Lançamento de <code>R$ {valor_dia:,.2f}</code> registrado por {gestor.NomeCompleto}.\n\n"
            "Aguarde, estou atualizando o status..."
        )

        try:
            # --- A CORREÇÃO ESTÁ AQUI ---
            # A função correta em database.py NÃO tem o underscore no início.
            database.verificar_e_premiar_meta_diaria(apuracao_id, data_hoje_str, valor_dia, meta_id)
            # --- FIM DA CORREÇÃO ---
            logger.info(f"Verificação de meta diária (ID {apuracao_id}) acionada via Telegram.")
        except NameError:
            logger.error("!!! ERRO: Função verificar_e_premiar_meta_diaria não encontrada/importada corretamente. Premiação diária via Telegram falhou.")
        except Exception as e_premio:
            logger.error(f"Erro ao tentar verificar/premiar meta diária após lançamento via Telegram: {e_premio}", exc_info=True)
        # --- FIM DA CORREÇÃO ---
        # Mostra o status atualizado da meta principal
        await status_meta(update, context)

    else:
        # Envia mensagem de falha
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
    ["💰 Meu Saldo", "🏪 Loja de Recompensas", "🧾 Enviar Nota Fiscal"],
    ["📜 Meu Histórico", "💬 Canal Confidencial"],
    ["🏅 Minhas Conquistas", "📄 Meus Documentos"],
    ["❓ Ajuda"]
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
        "<b>Comandos Principais (Botões):</b>\n"
        "📋 **Minhas Tarefas**: Mostra sua lista de tarefas pendentes para hoje.\n"
        "🏆 **Ranking do Mês**: Exibe a classificação de desempenho atual.\n"
        "💰 **Meu Saldo**: Mostra seus pontos acumulados e o valor em R$.\n"
        "🏪 **Loja de Recompensas**: Permite trocar seus pontos por prêmios.\n"
        "📜 **Meu Histórico**: Exibe suas últimas 10 atividades.\n"
        "🏅 **Minhas Conquistas**: Lista suas conquistas desbloqueadas.\n"
        "📄 **Meus Documentos**: Acessa documentos pessoais, como holerites.\n\n"
        "💬 **Canal Confidencial** (Botão 'Solicitar Feedback'):\n"
        "   Envia uma sugestão, reclamação ou denúncia de forma <b>100% ANÔNIMA</b> para a gestão.\n"
    )
    # Usamos reply_html por causa do <b>
    await update.message.reply_html(texto_ajuda, reply_markup=update.message.reply_markup)

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
    ranking_cozinha = []
    ranking_loja = []
    erro_db = None

    try: # <<< ADICIONADO TRY >>>
        # Tenta buscar ambos os rankings
        ranking_cozinha = database.calcular_ranking_desempenho(setor_filtro='Cozinha')
        ranking_loja = database.calcular_ranking_desempenho(setor_filtro='Loja')

    except Exception as e: # <<< ADICIONADO EXCEPT >>>
        logger.exception(f"Erro ao buscar dados do ranking para o comando /ranking do Telegram: {e}")
        erro_db = e # Guarda o erro para informar o usuário

    # --- Lógica de exibição com tratamento de erro ---
    if erro_db:
        await update.message.reply_text(f"❌ Desculpe, ocorreu um erro ao buscar os dados do ranking no momento.\nPor favor, tente novamente mais tarde ou contate o suporte se o problema persistir.")
        return # Interrompe se houve erro no banco

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
            detalhes = f"(Desemp: {dados['Desempenho']}%, Pts: {dados['PontosGanhos']})"
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
            detalhes = f"(Desemp: {dados['Desempenho']}%, Pts: {dados['PontosGanhos']})"
            texto_final += f"{posicao_icone} {nome} - **Score: {score}**\n   {detalhes}\n"

    # Envia a mensagem formatada (usando Markdown para compatibilidade anterior)
    await update.message.reply_text(texto_final, parse_mode='Markdown')

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

    # Comando /cancelar para limpar estado
    if texto_recebido.strip().lower() == '/cancelar':
        user_data.clear()
        await update.message.reply_text("Ação cancelada. Use os botões do menu.")
        return

    # Verifica estados específicos PRIMEIRO
    if user_data.get('aguardando_verificador_cpf'): # Usar .get() é mais seguro
        user_data.pop('aguardando_verificador_cpf', None) # Limpa mesmo se falhar
        verificador_correto = database.buscar_verificador_cpf(funcionario.FuncionarioID)

        if verificador_correto and texto_recebido.strip() == verificador_correto: # Adiciona verificação se verificador_correto existe
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
            await update.message.reply_text("❌ Código de verificação incorreto ou não cadastrado. Por favor, inicie o processo novamente ou contate o RH.")
        return # Importante retornar após tratar um estado

    elif user_data.get('tarefa_nao_aplicavel'):
        atribuicao_id = user_data.pop('tarefa_nao_aplicavel', None)
        if atribuicao_id: # Só prossegue se conseguiu pegar o ID
            database.registrar_tarefa_nao_aplicavel(atribuicao_id, texto_recebido)
            keyboard = [[InlineKeyboardButton("⬅️ Ver Tarefas Restantes", callback_data="voltar_lista_tarefas")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Ok, justificativa registrada!", reply_markup=reply_markup)
        else:
             await update.message.reply_text("Ocorreu um erro. Por favor, tente marcar como 'Não Aplicável' novamente.")
        return

    elif user_data.get('aguardando_denuncia_anonima'):
        # Limpa o estado
        user_data.pop('aguardando_denuncia_anonima', None)

        # IMPORTANTE: NÃO HÁ 'funcionario.FuncionarioID' aqui.
        # Salva a mensagem anonimamente no banco
        # (Certifique-se que a função registrar_denuncia_anonima e a tabela DenunciasAnonimas foram criadas no banco)
        novo_id = database.registrar_denuncia_anonima(texto_recebido)

        if novo_id:
            # Envia a confirmação ANÔNIMA para o gestor
            mensagem_gestor = (
                f"Atenção: Nova mensagem anônima recebida (Protocolo: {novo_id})\n\n"
                f"<b>Mensagem:</b>\n"
                f"<i>\"{texto_recebido}\"</i>"
            )
            # Envia para o grupo de gestão
            try:
                notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
            except Exception as e_notify:
                logger.error(f"Falha ao notificar gestores sobre denuncia anonima (ID: {novo_id}): {e_notify}")
                # O usuário não precisa saber se a notificação falhou, apenas que foi registrada.

            # Envia a confirmação para o usuário que enviou
            await update.message.reply_text(
                "✅ Sua mensagem anônima foi registrada e enviada à gestão. Obrigado por sua contribuição."
            )
        else:
            await update.message.reply_text("❌ Ocorreu um erro ao tentar registrar sua mensagem. Tente novamente mais tarde.")
        return # Fim do fluxo

    # Se não caiu em nenhum estado específico, é uma mensagem normal não esperada
    else:
         # Limpa qualquer estado residual por segurança
         user_data.clear()
         await update.message.reply_text("Não entendi o que você quis dizer. Use os botões do menu para interagir comigo. Se precisar, use o comando /ajuda ou digite /cancelar para recomeçar.")
         

async def solicitar_feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(REAPROVEITADO) Inicia o processo de Denúncia/Sugestão Anônima."""

    # Envia a mensagem explicativa conforme solicitado
    texto_explicativo = (
        "Este é o seu <b>Canal Confidencial</b>.\n\n"
        "Use este espaço para enviar sugestões, reclamações ou denúncias de forma <b>100% ANÔNIMA</b>.\n\n"
        "⚠️ <b>IMPORTANTE:</b> Sua identidade <b>NÃO</b> será registrada nem enviada à gestão. O sistema foi programado para descartar seu nome e ID de usuário nesta operação.\n\n"
        "Por favor, digite sua mensagem completa abaixo e pressione Enviar. (Ou digite /cancelar para sair)."
    )

    await update.message.reply_html(texto_explicativo) # Usar HTML por causa do <b>

    # Define o NOVO estado para o roteador
    context.user_data['aguardando_denuncia_anonima'] = True
    # Remove o estado antigo, caso exista (segurança)
    context.user_data.pop('aguardando_assunto_feedback', None)

async def handler_foto_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    MAX_SECONDS_DIFFERENCE = config.MAX_DIFERENCA_FOTO_SEGUNDOS # Usa valor do config.py
    temp_photo_path = None

    try:
        # Camada 1 de Verificação (sem alteração)
        if update.message.forward_from or update.message.forward_from_chat:
            await update.message.reply_text("❌ Desculpe, fotos encaminhadas não são aceitas.")
            return
        if update.message.document and 'image' in update.message.document.mime_type:
            await update.message.reply_text("❌ Por favor, envie a imagem como 'Foto', e não como 'Arquivo'.")
            return

        # Camada 2 de Verificação (LÓGICA AJUSTADA)
        photo_file = await update.message.photo[-1].get_file()
        message_timestamp_utc = update.message.date # Timestamp do Telegram (já em UTC)

        temp_photo_path = f"temp_{photo_file.file_id}.jpg"
        await photo_file.download_to_drive(temp_photo_path)

        # <<< VALIDAÇÃO DE DATA/HORA DA FOTO (EXIF) REMOVIDA COMPLETAMENTE >>>
        # A foto será aceita independentemente dos metadados de data/hora ou da idade da foto.
        pass # Usamos 'pass' como um placeholder explícito indicando que a lógica foi removida intencionalmente.

        # Se chegou até aqui, a foto é considerada válida (ou sem EXIF confiável)
        if 'identificador_tarefa' not in context.user_data:
            await update.message.reply_text("Parece que você enviou uma foto sem antes selecionar uma tarefa. Por favor, use o comando /tarefas primeiro.")
            # Limpa o caminho temporário antes de retornar
            if temp_photo_path and os.path.exists(temp_photo_path): os.remove(temp_photo_path)
            return

        # Continua com o registro da entrega...
        atribuicao_id = int(context.user_data.pop('identificador_tarefa'))
        funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id) #
        tarefa = database.buscar_tarefa_por_atribuicao(atribuicao_id) #

        if not (funcionario and tarefa):
            await update.message.reply_text("Ocorreu um erro ao identificar seus dados ou a tarefa.")
            # Limpa o caminho temporário antes de retornar
            if temp_photo_path and os.path.exists(temp_photo_path): os.remove(temp_photo_path)
            return

        photo_size = update.message.photo[-1]
        file_id = photo_size.file_id
        # Registra preliminarmente com file_id
        entrega_id = database.registrar_entrega_preliminar(tarefa.TarefaID, funcionario.FuncionarioID, atribuicao_id, file_id) #

        if entrega_id and config.GESTOR_GROUP_CHAT_ID: #
            # Prepara notificação para gestor
            # Usar html.escape para segurança se os títulos puderem conter < ou >
            # import html
            # titulo_escaped = html.escape(tarefa.Titulo)
            # nome_funcionario_escaped = html.escape(funcionario.NomeCompleto)
            legenda = (f"<b>Nova Entrega para Validação</b>\n\n"
                    f"👤 <b>Funcionário:</b> {funcionario.NomeCompleto}\n"
                    f"📝 <b>Tarefa:</b> {tarefa.Titulo} ({tarefa.Pontos} pts)\n"
                    f"🗓️ <b>Data:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}")
            keyboard = [[
                InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_gestor_{entrega_id}"),
                InlineKeyboardButton("❌ Reprovar", callback_data=f"reprovar_gestor_{entrega_id}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # --- CORREÇÃO: Enviar a notificação ANTES de marcar a flag ---

            # Tenta enviar a notificação para o gestor PRIMEIRO
            try:
                resposta_api = notificador_telegram.enviar_foto_com_botoes( # Captura a resposta
                    config.GESTOR_GROUP_CHAT_ID,
                    file_id,
                    legenda,
                    reply_markup,
                    parse_mode='HTML' # Mantenha como HTML
                )

                # SE (e somente SE) o envio foi um sucesso, marcamos a flag
                if resposta_api and resposta_api.get('ok'):
                    try:
                        database.marcar_notificacao_gestor_enviada(entrega_id)
                        logger.info(f"Notificação inicial para gestor (EntregaID {entrega_id}) enviada com sucesso E flag marcada.")
                    except Exception as flag_error:
                        logger.error(f"Notificação enviada, MAS FALHOU AO MARCAR FLAG para EntregaID {entrega_id}: {flag_error}", exc_info=True)
                        # Trade-off: O agendador pode enviar uma duplicata, o que é aceitável.
                else:
                    # Se falhou, logamos o erro e NÃO marcamos a flag.
                    # O agendador.py vai pegar esta entrega.
                    logger.error(f"Falha ao enviar notificação inicial para gestores sobre EntregaID {entrega_id}. Resposta API: {resposta_api}. Flag NÃO marcada.")

            except Exception as notify_error:
                # Se ocorreu um erro de rede/timeout, também NÃO marcamos a flag.
                # O agendador.py vai pegar esta entrega.
                logger.error(f"Erro inesperado durante o envio da notificação inicial para gestor (EntregaID {entrega_id}): {notify_error}. Flag NÃO marcada.", exc_info=True)

            # --- FIM DA CORREÇÃO ---

            # Envia confirmação para o usuário (esta linha já existe depois do bloco acima)
            await update.message.reply_text("✅ Evidência válida! Entrega registrada com sucesso e enviada para validação!")

    except Exception as e:
        logger.error(f"Erro crítico em receber_foto: {e}", exc_info=True)
        await update.message.reply_text("Ocorreu um erro crítico ao registrar sua entrega. Contate o administrador.")

    finally:
        # Garante que o arquivo temporário seja sempre removido
        if temp_photo_path and os.path.exists(temp_photo_path):
            try:
                os.remove(temp_photo_path)
            except Exception as del_err:
                logger.error(f"Erro ao remover arquivo temporário {temp_photo_path}: {del_err}")        

# Em telegram_bot.py, SUBSTITUA a função receber_motivo_recusa por esta:

async def receber_motivo_recusa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id_grupo = update.effective_chat.id
    gestor_id = update.effective_user.id
    gestor_nome = update.effective_user.first_name
    motivo = update.message.text

    # --- Bloco de leitura (sem alteração) ---
    dados_recusa = None
    if 'pendencias_recusa' in context.bot_data and \
    chat_id_grupo in context.bot_data['pendencias_recusa'] and \
    gestor_id in context.bot_data['pendencias_recusa'][chat_id_grupo]:
        dados_recusa = context.bot_data['pendencias_recusa'][chat_id_grupo].pop(gestor_id)
        logger.info(f"Dados de recusa encontrados em bot_data para GestorID {gestor_id} no ChatID {chat_id_grupo}.")
        if not context.bot_data['pendencias_recusa'][chat_id_grupo]:
            context.bot_data['pendencias_recusa'].pop(chat_id_grupo)
        if not context.bot_data['pendencias_recusa']:
            context.bot_data.pop('pendencias_recusa')
    # --- Fim do Bloco de leitura ---

    if not dados_recusa:
        logger.debug(f"Mensagem de GestorID {gestor_id} no ChatID {chat_id_grupo} ignorada (sem pendência).")
        return

    # --- CORREÇÃO APLICADA AQUI ---
    # Extrai os dados recuperados de bot_data (que já continha o msg_id)
    entrega_id = dados_recusa['entrega_id']
    id_mensagem_original = dados_recusa['msg_id'] # <-- USAMOS O VALOR CORRETO
    # --- FIM DA CORREÇÃO ---

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

    # A linha "context.chat_data.pop" foi removida.
    if id_mensagem_original: # Agora usamos a variável correta
        try:
            await context.bot.edit_message_caption(chat_id=chat_id_grupo, message_id=id_mensagem_original, caption=legenda_final)
        except Exception as e_edit:
            logger.error(f"Erro ao editar caption da mensagem recusada (ID: {entrega_id}): {e_edit}")
            try:
                await update.message.reply_text(legenda_final)
            except Exception as e_send:
                logger.error(f"Falha também ao enviar mensagem de fallback para recusa {entrega_id}: {e_send}")
    else:
        logger.warning(f"Não foi possível encontrar msg_id original para recusa {entrega_id}. Enviando status como nova mensagem.")
        try:
            await update.message.reply_text(legenda_final)
        except Exception as e_send:
            logger.error(f"Falha ao enviar mensagem de fallback (sem msg_id) para recusa {entrega_id}: {e_send}")


async def solicitar_foto_nf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Define o estado para aguardar a foto da Nota Fiscal."""
    logger.info(f"Solicitação de envio de NF recebida de {update.effective_user.id}")
    context.user_data['aguardando_nota_fiscal'] = True
    await update.message.reply_text(
        "Entendido. Por favor, envie agora a foto da Nota Fiscal que você recebeu.\n\n"
        "(Se mudar de ideia, digite /cancelar)"
    )

async def receber_nota_fiscal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler dedicado para receber a foto da Nota Fiscal (Regras 1, 2, 3).
    Este handler SÓ é ativado se o estado 'aguardando_nota_fiscal' for True.
    """
    # Limpa o estado imediatamente
    context.user_data.pop('aguardando_nota_fiscal', None)

    # 1. Validações básicas (não encaminhada, não arquivo)
    if update.message.forward_from or update.message.forward_from_chat:
        await update.message.reply_text("❌ Desculpe, fotos encaminhadas não são aceitas. Por favor, tire a foto na hora ou envie da sua galeria.")
        return
    if update.message.document and 'image' in update.message.document.mime_type:
        await update.message.reply_text("❌ Por favor, envie a imagem como 'Foto', e não como 'Arquivo'.")
        return

    try:
        funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
        if not funcionario:
            await update.message.reply_text("Erro: Não consegui encontrar seu cadastro no sistema.")
            return

        file_id = update.message.photo[-1].file_id

        # 2. Salva o registro preliminar no banco (tabela NotasFiscais)
        nota_fiscal_id = database.registrar_nota_fiscal(funcionario.FuncionarioID, file_id)
        if not nota_fiscal_id:
            await update.message.reply_text("❌ Ocorreu um erro interno ao tentar registrar sua nota fiscal. Tente novamente.")
            return

        # 3. Dá os pontos bônus (Regra 1)
        pontos_bonus = config.PONTOS_BONUS_NOTA_FISCAL
        database.registrar_pontos_de_bonus(
            funcionario.FuncionarioID,
            pontos_bonus,
            f"Envio de Nota Fiscal (ID: {nota_fiscal_id})",
            config.TAREFA_ID_NOTA_FISCAL
        )
        database.adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_bonus)

        await update.message.reply_text(f"✅ Nota Fiscal enviada com sucesso! Você ganhou *{pontos_bonus} pontos* pelo recebimento!", parse_mode='Markdown')

        # 4. Encaminha para os Gestores (Regras 2, 3, 4)
        legenda_gestor = (
            f"🧾 **Nova Nota Fiscal Recebida** 🧾\n\n"
            f"👤 **Enviada por:** {funcionario.NomeCompleto}\n"
            f"🗓️ **Data:** {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"🆔 **NF ID:** {nota_fiscal_id}\n\n"
            "Ações Rápidas:"
        )

        # Prepara botões com o ID da NF para rastreio
        keyboard = [
            [InlineKeyboardButton("📲 Encaminhar p/ Financeiro", callback_data=f"nf_prep_fwd_{nota_fiscal_id}")],
            [InlineKeyboardButton("📦 Criar Tarefa 'Guardar'", callback_data=f"nf_create_task_{nota_fiscal_id}")],
            [InlineKeyboardButton("👍 Arquivar (Nenhuma Ação)", callback_data=f"nf_ignore_{nota_fiscal_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        notificador_telegram.enviar_foto_com_botoes(
            config.GESTOR_GROUP_CHAT_ID,
            file_id,
            legenda_gestor,
            reply_markup,
            parse_mode='HTML'
        )
        logger.info(f"Nota Fiscal {nota_fiscal_id} encaminhada para o grupo de gestores.")

    except Exception as e:
        logger.error(f"Erro crítico em receber_nota_fiscal: {e}", exc_info=True)
        await update.message.reply_text("Ocorreu um erro crítico. Contate o administrador.")

async def receber_foto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Roteador principal para fotos privadas.
    Verifica o estado do usuário e decide qual handler de foto chamar.
    """
    # Verifica primeiro se o usuário está no estado de enviar NF
    if context.user_data.get('aguardando_nota_fiscal', False):
        await receber_nota_fiscal(update, context)

    # Se não, chama o handler padrão de envio de fotos de tarefas
    else:
        await handler_foto_tarefa(update, context)


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
                
                # --- CORREÇÃO APLICADA AQUI ---
                # Usamos a nova função genérica de bônus, especificando o ID correto da tarefa de feedback.
                database.registrar_pontos_de_bonus(
                    funcionario_db.FuncionarioID, 
                    config.PONTOS_BONUS_FEEDBACK_DIARIO, 
                    "Feedback Diário (Bônus)",
                    config.TAREFA_ID_FEEDBACK_DIARIO # <-- Usa o ID correto (ex: 5)
                )
                # --- FIM DA CORREÇÃO ---
                
                database.adicionar_pontos_ao_saldo(funcionario_db.FuncionarioID, config.PONTOS_BONUS_FEEDBACK_DIARIO)
                texto_final = (f"Obrigado pelo seu feedback! Sua nota foi **{nota}**.\n\nVocê ganhou **{config.PONTOS_BONUS_FEEDBACK_DIARIO}** pontos por sua participação. Sua opinião nos ajuda a melhorar sempre! 💪")
                await query.edit_message_text(texto_final, parse_mode='Markdown')
            else: await query.edit_message_text("Você já enviou seu feedback hoje. Obrigado!")
        else: await query.edit_message_text("Erro: não foi possível identificar seu usuário.")

    elif data.startswith("aceitar_tarefa_"):
        origem_atribuicao_id = int(data.split('_')[-1])
        funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
        if not funcionario_db:
            await query.answer("Seu usuário do Telegram não foi encontrado no nosso sistema.", show_alert=True) # Avisa via popup
            return

        # Chama a função do banco
        nova_atribuicao_id_criada = database.aceitar_tarefa_de_grupo(origem_atribuicao_id, funcionario_db.FuncionarioID)

        # Busca o título da tarefa original para as mensagens
        tarefa_original = database.buscar_tarefa_por_atribuicao(origem_atribuicao_id)
        tarefa_titulo = tarefa_original.Titulo if tarefa_original else "Tarefa desconhecida"

        # <<< CORREÇÃO: Verifica se a atribuição foi criada com sucesso >>>
        if nova_atribuicao_id_criada:
            # SUCESSO! A instância 'Unica' foi criada para este funcionário HOJE.
            nova_mensagem_grupo = (
                f"✅ **Missão Aceita por {user.first_name}!** ✅\n\n"
                f"**Tarefa:** {tarefa_titulo}\n\n"
                f"{user.first_name} agora é o responsável pela entrega *de hoje*. Boa sorte!"
            )
            try:
                await query.edit_message_text(text=nova_mensagem_grupo, reply_markup=None)
            except Exception as e:
                logger.info(f"Aviso: Não foi possível editar a mensagem original no grupo para {origem_atribuicao_id}. Erro: {e}")

            # Mensagem privada de sucesso
            await context.bot.send_message(
                chat_id=user.id,
                text=f"Você aceitou a missão '{tarefa_titulo}' para hoje. Agora ela aparecerá na sua lista de /tarefas. Capriche na entrega! 💪"
            )
        else:
            # FALHA! Alguém já aceitou HOJE ou ocorreu outro erro no banco.
            # Avisa o usuário que clicou via popup (show_alert=True)
            await query.answer(f"Que pena, parece que a missão '{tarefa_titulo}' já foi aceita por outro colega hoje.", show_alert=True)
            # Opcional: Logar que a tentativa falhou
            logger.info(f"Funcionário {funcionario_db.FuncionarioID} tentou aceitar tarefa {origem_atribuicao_id} que já foi aceita hoje ou falhou no DB.")



    # Em telegram_bot.py, SUBSTITUA a lógica do 'aceitar_folga_' dentro de button_callback_handler

    elif data.startswith("aceitar_folga_"):
        tarefa_id = int(data.split('_')[-1])
        funcionario_aceitou = database.buscar_funcionario_por_chat_id(user.id)
        if not funcionario_aceitou:
            await context.bot.send_message(chat_id=user.id, text="Seu usuário do Telegram não foi encontrado.")
            return

        # --- LÓGICA CORRIGIDA E ROBUSTA ---
        # 1. Chama a nova função transacional do banco
        novo_atribuicao_id = database.verificar_e_aceitar_tarefa_de_folga(tarefa_id, funcionario_aceitou.FuncionarioID)

        # 2. Busca os detalhes da tarefa (apenas para a mensagem de confirmação)
        tarefa_info = database.buscar_tarefa_por_atribuicao(novo_atribuicao_id) if novo_atribuicao_id else None

        # 3. Verifica o resultado da transação
        if novo_atribuicao_id:
            # SUCESSO! A pessoa pegou a tarefa.
            nova_mensagem_grupo = (
                f"{query.message.text}\n\n"
                f"--- MISSÃO REIVINDICADA! ---\n"
                f"✅ **{funcionario_aceitou.NomeCompleto}** assumiu a tarefa."
            )
            # Tenta editar a mensagem do grupo para "travar" (remover o botão)
            try:
                await query.edit_message_text(text=nova_mensagem_grupo, reply_markup=None)
            except Exception as e:
                logger.warning(f"Não foi possível editar a msg de 'aceitar_folga_' (provavelmente já editada): {e}")

            # Envia a confirmação privada
            await context.bot.send_message(
                chat_id=user.id,
                text=f"🚀 Você assumiu a missão extra '{tarefa_info.Titulo}'! Ela já está na sua lista de /tarefas. Bom trabalho!"
            )
        else:
            # FALHA! (Função retornou False ou None)
            # Avisa o usuário que clicou (mas não conseguiu) via popup
            await query.answer("Que pena! Parece que outro colega já pegou esta missão.", show_alert=True)
        # --- FIM DA CORREÇÃO ---



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

    elif data.startswith("doc_ciente_"):
        await query.answer()
        assinatura_id = int(data.split('_')[-1])
        detalhes = database.buscar_detalhes_assinatura_para_bot(assinatura_id)

        # <<< CORREÇÃO: Verifica se 'detalhes' foi encontrado (ou seja, se a assinatura ainda estava pendente) >>>
        if not detalhes:
            await query.answer("Esta ciência já foi registrada anteriormente.", show_alert=True)
            # Tenta remover o botão se a edição anterior falhou
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass # Ignora erro se não conseguir editar
            return # Interrompe a execução aqui

        # Se 'detalhes' existe, prossegue com a lógica original
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
            # Adiciona pontos ao saldo PRIMEIRO (mais crítico)
            database.adicionar_pontos_ao_saldo(detalhes.FuncionarioID, detalhes.PontosPorCiencia)
            # DEPOIS registra no histórico (menos crítico se falhar)
            database.registrar_pontos_por_leitura(detalhes.FuncionarioID, detalhes.PontosPorCiencia, detalhes.Titulo)
            mensagem_confirmacao += f"\n\n🎉 Você ganhou **{detalhes.PontosPorCiencia}** pontos por sua agilidade!"

        # Lógica de edição da mensagem (permanece a mesma, já corrigida anteriormente)
        try:
            if query.message.photo:
                texto_original = query.message.caption
                await query.edit_message_caption(
                    caption=f"{texto_original}{mensagem_confirmacao}",
                    parse_mode='Markdown',
                    reply_markup=None
                )
            else:
                texto_original = query.message.text
                await query.edit_message_text(
                    text=f"{texto_original}{mensagem_confirmacao}",
                    parse_mode='Markdown',
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Erro ao editar a mensagem de ciência (ID: {assinatura_id}): {e}")
            await query.answer("Sua ciência foi registrada!", show_alert=True) # Feedback mínimo

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
        detalhes = database.buscar_detalhes_da_entrega(entrega_id) # Busca detalhes uma vez

        # <<< CORREÇÃO: Verifica o status ANTES de tentar aprovar >>>
        if not detalhes:
            try: await query.edit_message_caption(caption="ERRO: Entrega não encontrada no banco de dados.")
            except Exception: pass
            return
        if detalhes.StatusValidacao != 'Pendente':
            try: await query.edit_message_caption(caption=f"Esta tarefa já foi validada anteriormente. (Status: {detalhes.StatusValidacao})")
            except Exception: pass
            return

        # Se passou nas verificações, tenta aprovar no banco
        novas_conquistas_ganhas = database.aprovar_entrega(entrega_id, detalhes.FuncionarioID, detalhes.Pontos)

        # Prepara notificação para funcionário (mesma lógica de antes)
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
                # Adiciona pontos bônus AO SALDO aqui, pois aprovar_entrega só registra
                if conquista.PontosBonus > 0:
                    database.adicionar_pontos_ao_saldo(detalhes.FuncionarioID, conquista.PontosBonus)

        notificador_telegram.enviar_mensagem(detalhes.ChatIDFuncionario, texto_notificacao)

        # Edita a mensagem no grupo GESTOR
        legenda_final = (f"**Entrega APROVADA por {gestor_nome}**\n\n"
                        f"👤 **Funcionário:** {detalhes.NomeCompleto}\n"
                        f"📝 **Tarefa:** {detalhes.Titulo} (+{detalhes.Pontos} pts)")

                # <<< CORREÇÃO REVISADA: Adiciona try/except e fallback com nova mensagem >>>
        try:
            await query.edit_message_caption(caption=legenda_final, reply_markup=None) # Remove botões também
        except Exception as e_edit:
            logger.warning(f"Não foi possível editar a mensagem de aprovação {entrega_id} no grupo gestor: {e_edit}")
            # Fallback: Envia uma nova mensagem se a edição falhar
            try:
                await context.bot.send_message(chat_id=query.message.chat_id, text=legenda_final)
            except Exception as e_send:
                logger.error(f"Falha também ao enviar mensagem de fallback para aprovação {entrega_id}: {e_send}")
    # --- INÍCIO: LÓGICA DE GERENCIAMENTO DE NOTA FISCAL (GESTOR) ---

    elif data.startswith("nf_prep_fwd_"):
        # Regra 3: Encaminhar para o WhatsApp
        await query.answer("Processando...")
        gestor_chat_id = query.from_user.id
        try:
            nota_fiscal_id = int(data.split('_')[-1])
            dados_nf = database.buscar_nota_fiscal(nota_fiscal_id)

            if not dados_nf:
                await context.bot.send_message(gestor_chat_id, "Erro: Não encontrei os dados desta NF no banco.")
                return

            if not dados_nf.PathFoto:
                await context.bot.send_message(gestor_chat_id, "O download desta foto ainda está sendo processado pelo servidor. Tente novamente em 1 minuto.")
                return

            # Constrói o link do WhatsApp
            texto_mensagem_wpp = urllib.parse.quote(f"Olá, segue a Nota Fiscal recebida (ID Interno: {nota_fiscal_id})")
            link_wpp = f"https://wa.me/{config.WHATSAPP_CONTATO_FINANCEIRO}?text={texto_mensagem_wpp}"

            # Envia o arquivo da NF (do disco) PRIVADAMENTE para o gestor
            with open(dados_nf.PathFoto, 'rb') as nf_file:
                await context.bot.send_document(
                    chat_id=gestor_chat_id,
                    document=nf_file,
                    caption=f"Pronto! Por favor, encaminhe este arquivo para o Financeiro.\n\nVocê também pode usar este link:\n{link_wpp}"
                )
            # Atualiza o status no grupo
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n✅ Encaminhada para o Financeiro por {query.from_user.first_name}.")

        except Exception as e:
            logger.error(f"Erro em nf_prep_fwd: {e}", exc_info=True)
            await context.bot.send_message(gestor_chat_id, f"Ocorreu um erro ao preparar o encaminhamento: {e}")

    elif data.startswith("nf_create_task_"):
        # Regra 4: Criar Tarefa "Guardar Mercadoria"
        await query.answer("Criando tarefa...")
        try:
            nota_fiscal_id = int(data.split('_')[-1])
            dados_nf = database.buscar_nota_fiscal(nota_fiscal_id)

            if not dados_nf:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n❌ Erro: Não encontrei os dados desta NF.")
                return

            # Cria a nova tarefa 'Unica'
            nova_atribuicao_id = database.atribuir_tarefa(
                tarefa_id=config.TAREFA_ID_GUARDAR_MERCADORIA_MODELO,
                funcionario_id=dados_nf.FuncionarioID,
                tipo_frequencia='Unica',
                valor_frequencia=None,
                descricao_override="Guarde a mercadoria referente a esta Nota Fiscal.",
                data_agendamento=datetime.now().date() # Agenda para hoje
            )

            if not nova_atribuicao_id:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n❌ Erro: Falha ao salvar a nova tarefa no banco.")
                return

            # Atualiza o status da NF
            database.atualizar_status_nota_fiscal(nota_fiscal_id, "Processada")

            # Notifica o funcionário PRIVADAMENTE
            await context.bot.send_photo(
                chat_id=dados_nf.ChatIDFuncionario,
                photo=dados_nf.FileIDTelegram,
                caption="📦 **Nova Tarefa Atribuída!** 📦\n\nUma tarefa para *'Guardar Mercadoria (NF)'* foi criada para você com base na nota fiscal que você enviou.\n\nUse o comando /tarefas para ver e enviar a evidência."
            )

            # Atualiza a mensagem no grupo
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n✅ Tarefa 'Guardar' criada para o funcionário por {query.from_user.first_name}.")

        except Exception as e:
            logger.error(f"Erro em nf_create_task: {e}", exc_info=True)
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n❌ Erro inesperado ao criar tarefa: {e}")

    elif data.startswith("nf_ignore_"):
        # Ação de arquivar/ignorar
        await query.answer("Arquivando...")
        try:
            nota_fiscal_id = int(data.split('_')[-1])
            database.atualizar_status_nota_fiscal(nota_fiscal_id, "Processada")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n👍 Nota revisada e arquivada por {query.from_user.first_name}.")
        except Exception as e:
            logger.error(f"Erro em nf_ignore: {e}", exc_info=True)

    # --- FIM: LÓGICA DE GERENCIAMENTO DE NOTA FISCAL (GESTOR) ---

    elif data.startswith("reprovar_gestor_"):
        entrega_id = int(data.split('_')[-1])
        gestor_id = query.from_user.id
        chat_id_grupo = query.message.chat_id
        msg_id_original = query.message.message_id

        # --- CORREÇÃO: Usar bot_data ---
        # Garante que a estrutura de dicionários exista
        if 'pendencias_recusa' not in context.bot_data:
            context.bot_data['pendencias_recusa'] = {}
        if chat_id_grupo not in context.bot_data['pendencias_recusa']:
            context.bot_data['pendencias_recusa'][chat_id_grupo] = {}

        # Armazena os dados associados ao gestor que clicou dentro do chat específico
        context.bot_data['pendencias_recusa'][chat_id_grupo][gestor_id] = {
            'entrega_id': entrega_id,
            'msg_id': msg_id_original
        }
        logger.info(f"Estado de recusa para EntregaID {entrega_id} armazenado em bot_data para GestorID {gestor_id} no ChatID {chat_id_grupo}.")
        # --- FIM CORREÇÃO ---

        # Remove botões da mensagem original (pode falhar, mas o estado já está salvo)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e_edit_markup:
            logger.warning(f"Não foi possível remover botões ao iniciar recusa {entrega_id}: {e_edit_markup}")

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
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🧾 Enviar Nota Fiscal$'), solicitar_foto_nf))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # --- Handlers para os Botões do Menu Fixo ---
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📋 Minhas Tarefas$'), tarefas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏆 Ranking do Mês$'), ranking))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🎯 Acompanhar Metas$'), acompanhar_metas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📜 Meu Histórico$'), meu_historico))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^❓ Ajuda$'), ajuda))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💰 Meu Saldo$'), meu_saldo))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏪 Loja de Recompensas$'), loja_recompensas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💬 Canal Confidencial$'), solicitar_feedback_start)) 
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📄 Meus Documentos$'), solicitar_holerite_inicio)) 
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏅 Minhas Conquistas$'), minhas_conquistas)) # <<< NOVO BOTÃO
    # Handler de FOTO para Nota Fiscal (verifica o estado 'aguardando_nota_fiscal')
    # Handler de FOTO (Roteador):
    # Esta única linha agora chama a nossa nova função roteadora "receber_foto".
    # Ela cuidará de direcionar para "receber_nota_fiscal" ou "handler_foto_tarefa".
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, receber_foto))

    # Handler de TEXTO genérico (para justificativas, cpf, etc.)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, roteador_de_texto_privado))
    # --- CORREÇÃO ADICIONADA AQUI ---
    # Adiciona o handler para capturar o "motivo da recusa" digitado pelo gestor no GRUPO.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUP, receber_motivo_recusa))
    # --- FIM DA CORREÇÃO ---
    logger.info("--- BOT INICIADO COM SUCESSO ---")
    application.run_polling()

if __name__ == '__main__':
    main()

=======
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

# Em telegram_bot.py
# --- Cria a pasta de logs se não existir ---
log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        # CORREÇÃO: Usar print() antes do logger ser definido.
        print(f"Pasta de logs criada em: {log_dir}") 
    except OSError as e:
        # CORREÇÃO: Usar print() antes do logger ser definido.
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
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
import urllib.parse
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

async def lancar_venda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra o valor da apuração diária enviado pelo gestor."""
    chat_id = update.effective_chat.id
    gestor = database.buscar_funcionario_por_chat_id(update.effective_user.id)

    # Verifica se é o grupo de gestão
    if chat_id != config.GESTOR_GROUP_CHAT_ID:
        await update.message.reply_text("Este comando é exclusivo para o grupo de gestão.")
        return
    # Verifica se o gestor foi encontrado no banco
    if not gestor:
        await update.message.reply_text("Erro: Seu usuário do Telegram não foi encontrado no sistema para registrar esta ação.")
        return

    # Verifica se o valor foi fornecido
    if not context.args:
        await update.message.reply_text("Por favor, informe o valor a ser lançado.\nExemplo: `/lancar 1250.50`")
        return

    # Tenta converter o valor para float
    try:
        valor_str = context.args[0].replace(',', '.')
        valor_dia = float(valor_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Valor inválido. Por favor, use apenas números.\nExemplo: `/lancar 1250.50`")
        return

    # Busca o ID da meta principal ativa para hoje
    meta_id = database.buscar_meta_ativa_id_hoje()
    if not meta_id:
        await update.message.reply_text("Erro: Nenhuma meta principal está ativa para hoje. Não é possível lançar.")
        return

    # Pega a data de hoje e formata para o banco
    data_hoje_obj = date.today() # Pega o objeto date
    data_hoje_str = data_hoje_obj.strftime('%Y-%m-%d')

    # Tenta lançar a apuração no banco
    sucesso, resultado = database.lancar_apuracao_diaria(meta_id, data_hoje_str, valor_dia, gestor.FuncionarioID)

    if sucesso:
        apuracao_id = resultado # Captura o ID da apuração retornado pelo banco

        # Envia mensagem de sucesso
        await update.message.reply_html(
            f"✅ <b>Sucesso!</b> Lançamento de <code>R$ {valor_dia:,.2f}</code> registrado por {gestor.NomeCompleto}.\n\n"
            "Aguarde, estou atualizando o status..."
        )

        try:
            # --- A CORREÇÃO ESTÁ AQUI ---
            # A função correta em database.py NÃO tem o underscore no início.
            database.verificar_e_premiar_meta_diaria(apuracao_id, data_hoje_str, valor_dia, meta_id)
            # --- FIM DA CORREÇÃO ---
            logger.info(f"Verificação de meta diária (ID {apuracao_id}) acionada via Telegram.")
        except NameError:
            logger.error("!!! ERRO: Função verificar_e_premiar_meta_diaria não encontrada/importada corretamente. Premiação diária via Telegram falhou.")
        except Exception as e_premio:
            logger.error(f"Erro ao tentar verificar/premiar meta diária após lançamento via Telegram: {e_premio}", exc_info=True)
        # --- FIM DA CORREÇÃO ---
        # Mostra o status atualizado da meta principal
        await status_meta(update, context)

    else:
        # Envia mensagem de falha
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
    ["💰 Meu Saldo", "🏪 Loja de Recompensas", "🧾 Enviar Nota Fiscal"],
    ["📜 Meu Histórico", "💬 Canal Confidencial"],
    ["🏅 Minhas Conquistas", "📄 Meus Documentos"],
    ["❓ Ajuda"]
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
        "<b>Comandos Principais (Botões):</b>\n"
        "📋 **Minhas Tarefas**: Mostra sua lista de tarefas pendentes para hoje.\n"
        "🏆 **Ranking do Mês**: Exibe a classificação de desempenho atual.\n"
        "💰 **Meu Saldo**: Mostra seus pontos acumulados e o valor em R$.\n"
        "🏪 **Loja de Recompensas**: Permite trocar seus pontos por prêmios.\n"
        "📜 **Meu Histórico**: Exibe suas últimas 10 atividades.\n"
        "🏅 **Minhas Conquistas**: Lista suas conquistas desbloqueadas.\n"
        "📄 **Meus Documentos**: Acessa documentos pessoais, como holerites.\n\n"
        "💬 **Canal Confidencial** (Botão 'Solicitar Feedback'):\n"
        "   Envia uma sugestão, reclamação ou denúncia de forma <b>100% ANÔNIMA</b> para a gestão.\n"
    )
    # Usamos reply_html por causa do <b>
    await update.message.reply_html(texto_ajuda, reply_markup=update.message.reply_markup)

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
    ranking_cozinha = []
    ranking_loja = []
    erro_db = None

    try: # <<< ADICIONADO TRY >>>
        # Tenta buscar ambos os rankings
        ranking_cozinha = database.calcular_ranking_desempenho(setor_filtro='Cozinha')
        ranking_loja = database.calcular_ranking_desempenho(setor_filtro='Loja')

    except Exception as e: # <<< ADICIONADO EXCEPT >>>
        logger.exception(f"Erro ao buscar dados do ranking para o comando /ranking do Telegram: {e}")
        erro_db = e # Guarda o erro para informar o usuário

    # --- Lógica de exibição com tratamento de erro ---
    if erro_db:
        await update.message.reply_text(f"❌ Desculpe, ocorreu um erro ao buscar os dados do ranking no momento.\nPor favor, tente novamente mais tarde ou contate o suporte se o problema persistir.")
        return # Interrompe se houve erro no banco

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
            detalhes = f"(Desemp: {dados['Desempenho']}%, Pts: {dados['PontosGanhos']})"
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
            detalhes = f"(Desemp: {dados['Desempenho']}%, Pts: {dados['PontosGanhos']})"
            texto_final += f"{posicao_icone} {nome} - **Score: {score}**\n   {detalhes}\n"

    # Envia a mensagem formatada (usando Markdown para compatibilidade anterior)
    await update.message.reply_text(texto_final, parse_mode='Markdown')

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

    # Comando /cancelar para limpar estado
    if texto_recebido.strip().lower() == '/cancelar':
        user_data.clear()
        await update.message.reply_text("Ação cancelada. Use os botões do menu.")
        return

    # Verifica estados específicos PRIMEIRO
    if user_data.get('aguardando_verificador_cpf'): # Usar .get() é mais seguro
        user_data.pop('aguardando_verificador_cpf', None) # Limpa mesmo se falhar
        verificador_correto = database.buscar_verificador_cpf(funcionario.FuncionarioID)

        if verificador_correto and texto_recebido.strip() == verificador_correto: # Adiciona verificação se verificador_correto existe
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
            await update.message.reply_text("❌ Código de verificação incorreto ou não cadastrado. Por favor, inicie o processo novamente ou contate o RH.")
        return # Importante retornar após tratar um estado

    elif user_data.get('tarefa_nao_aplicavel'):
        atribuicao_id = user_data.pop('tarefa_nao_aplicavel', None)
        if atribuicao_id: # Só prossegue se conseguiu pegar o ID
            database.registrar_tarefa_nao_aplicavel(atribuicao_id, texto_recebido)
            keyboard = [[InlineKeyboardButton("⬅️ Ver Tarefas Restantes", callback_data="voltar_lista_tarefas")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Ok, justificativa registrada!", reply_markup=reply_markup)
        else:
             await update.message.reply_text("Ocorreu um erro. Por favor, tente marcar como 'Não Aplicável' novamente.")
        return

    elif user_data.get('aguardando_denuncia_anonima'):
        # Limpa o estado
        user_data.pop('aguardando_denuncia_anonima', None)

        # IMPORTANTE: NÃO HÁ 'funcionario.FuncionarioID' aqui.
        # Salva a mensagem anonimamente no banco
        # (Certifique-se que a função registrar_denuncia_anonima e a tabela DenunciasAnonimas foram criadas no banco)
        novo_id = database.registrar_denuncia_anonima(texto_recebido)

        if novo_id:
            # Envia a confirmação ANÔNIMA para o gestor
            mensagem_gestor = (
                f"Atenção: Nova mensagem anônima recebida (Protocolo: {novo_id})\n\n"
                f"<b>Mensagem:</b>\n"
                f"<i>\"{texto_recebido}\"</i>"
            )
            # Envia para o grupo de gestão
            try:
                notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
            except Exception as e_notify:
                logger.error(f"Falha ao notificar gestores sobre denuncia anonima (ID: {novo_id}): {e_notify}")
                # O usuário não precisa saber se a notificação falhou, apenas que foi registrada.

            # Envia a confirmação para o usuário que enviou
            await update.message.reply_text(
                "✅ Sua mensagem anônima foi registrada e enviada à gestão. Obrigado por sua contribuição."
            )
        else:
            await update.message.reply_text("❌ Ocorreu um erro ao tentar registrar sua mensagem. Tente novamente mais tarde.")
        return # Fim do fluxo

    # Se não caiu em nenhum estado específico, é uma mensagem normal não esperada
    else:
         # Limpa qualquer estado residual por segurança
         user_data.clear()
         await update.message.reply_text("Não entendi o que você quis dizer. Use os botões do menu para interagir comigo. Se precisar, use o comando /ajuda ou digite /cancelar para recomeçar.")
         

async def solicitar_feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(REAPROVEITADO) Inicia o processo de Denúncia/Sugestão Anônima."""

    # Envia a mensagem explicativa conforme solicitado
    texto_explicativo = (
        "Este é o seu <b>Canal Confidencial</b>.\n\n"
        "Use este espaço para enviar sugestões, reclamações ou denúncias de forma <b>100% ANÔNIMA</b>.\n\n"
        "⚠️ <b>IMPORTANTE:</b> Sua identidade <b>NÃO</b> será registrada nem enviada à gestão. O sistema foi programado para descartar seu nome e ID de usuário nesta operação.\n\n"
        "Por favor, digite sua mensagem completa abaixo e pressione Enviar. (Ou digite /cancelar para sair)."
    )

    await update.message.reply_html(texto_explicativo) # Usar HTML por causa do <b>

    # Define o NOVO estado para o roteador
    context.user_data['aguardando_denuncia_anonima'] = True
    # Remove o estado antigo, caso exista (segurança)
    context.user_data.pop('aguardando_assunto_feedback', None)

async def handler_foto_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    MAX_SECONDS_DIFFERENCE = config.MAX_DIFERENCA_FOTO_SEGUNDOS # Usa valor do config.py
    temp_photo_path = None

    try:
        # Camada 1 de Verificação (sem alteração)
        if update.message.forward_from or update.message.forward_from_chat:
            await update.message.reply_text("❌ Desculpe, fotos encaminhadas não são aceitas.")
            return
        if update.message.document and 'image' in update.message.document.mime_type:
            await update.message.reply_text("❌ Por favor, envie a imagem como 'Foto', e não como 'Arquivo'.")
            return

        # Camada 2 de Verificação (LÓGICA AJUSTADA)
        photo_file = await update.message.photo[-1].get_file()
        message_timestamp_utc = update.message.date # Timestamp do Telegram (já em UTC)

        temp_photo_path = f"temp_{photo_file.file_id}.jpg"
        await photo_file.download_to_drive(temp_photo_path)

        # <<< VALIDAÇÃO DE DATA/HORA DA FOTO (EXIF) REMOVIDA COMPLETAMENTE >>>
        # A foto será aceita independentemente dos metadados de data/hora ou da idade da foto.
        pass # Usamos 'pass' como um placeholder explícito indicando que a lógica foi removida intencionalmente.

        # Se chegou até aqui, a foto é considerada válida (ou sem EXIF confiável)
        if 'identificador_tarefa' not in context.user_data:
            await update.message.reply_text("Parece que você enviou uma foto sem antes selecionar uma tarefa. Por favor, use o comando /tarefas primeiro.")
            # Limpa o caminho temporário antes de retornar
            if temp_photo_path and os.path.exists(temp_photo_path): os.remove(temp_photo_path)
            return

        # Continua com o registro da entrega...
        atribuicao_id = int(context.user_data.pop('identificador_tarefa'))
        funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id) #
        tarefa = database.buscar_tarefa_por_atribuicao(atribuicao_id) #

        if not (funcionario and tarefa):
            await update.message.reply_text("Ocorreu um erro ao identificar seus dados ou a tarefa.")
            # Limpa o caminho temporário antes de retornar
            if temp_photo_path and os.path.exists(temp_photo_path): os.remove(temp_photo_path)
            return

        photo_size = update.message.photo[-1]
        file_id = photo_size.file_id
        # Registra preliminarmente com file_id
        entrega_id = database.registrar_entrega_preliminar(tarefa.TarefaID, funcionario.FuncionarioID, atribuicao_id, file_id) #

        if entrega_id and config.GESTOR_GROUP_CHAT_ID: #
            # Prepara notificação para gestor
            # Usar html.escape para segurança se os títulos puderem conter < ou >
            # import html
            # titulo_escaped = html.escape(tarefa.Titulo)
            # nome_funcionario_escaped = html.escape(funcionario.NomeCompleto)
            legenda = (f"<b>Nova Entrega para Validação</b>\n\n"
                    f"👤 <b>Funcionário:</b> {funcionario.NomeCompleto}\n"
                    f"📝 <b>Tarefa:</b> {tarefa.Titulo} ({tarefa.Pontos} pts)\n"
                    f"🗓️ <b>Data:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}")
            keyboard = [[
                InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_gestor_{entrega_id}"),
                InlineKeyboardButton("❌ Reprovar", callback_data=f"reprovar_gestor_{entrega_id}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # --- CORREÇÃO: Enviar a notificação ANTES de marcar a flag ---

            # Tenta enviar a notificação para o gestor PRIMEIRO
            try:
                resposta_api = notificador_telegram.enviar_foto_com_botoes( # Captura a resposta
                    config.GESTOR_GROUP_CHAT_ID,
                    file_id,
                    legenda,
                    reply_markup,
                    parse_mode='HTML' # Mantenha como HTML
                )

                # SE (e somente SE) o envio foi um sucesso, marcamos a flag
                if resposta_api and resposta_api.get('ok'):
                    try:
                        database.marcar_notificacao_gestor_enviada(entrega_id)
                        logger.info(f"Notificação inicial para gestor (EntregaID {entrega_id}) enviada com sucesso E flag marcada.")
                    except Exception as flag_error:
                        logger.error(f"Notificação enviada, MAS FALHOU AO MARCAR FLAG para EntregaID {entrega_id}: {flag_error}", exc_info=True)
                        # Trade-off: O agendador pode enviar uma duplicata, o que é aceitável.
                else:
                    # Se falhou, logamos o erro e NÃO marcamos a flag.
                    # O agendador.py vai pegar esta entrega.
                    logger.error(f"Falha ao enviar notificação inicial para gestores sobre EntregaID {entrega_id}. Resposta API: {resposta_api}. Flag NÃO marcada.")

            except Exception as notify_error:
                # Se ocorreu um erro de rede/timeout, também NÃO marcamos a flag.
                # O agendador.py vai pegar esta entrega.
                logger.error(f"Erro inesperado durante o envio da notificação inicial para gestor (EntregaID {entrega_id}): {notify_error}. Flag NÃO marcada.", exc_info=True)

            # --- FIM DA CORREÇÃO ---

            # Envia confirmação para o usuário (esta linha já existe depois do bloco acima)
            await update.message.reply_text("✅ Evidência válida! Entrega registrada com sucesso e enviada para validação!")

    except Exception as e:
        logger.error(f"Erro crítico em receber_foto: {e}", exc_info=True)
        await update.message.reply_text("Ocorreu um erro crítico ao registrar sua entrega. Contate o administrador.")

    finally:
        # Garante que o arquivo temporário seja sempre removido
        if temp_photo_path and os.path.exists(temp_photo_path):
            try:
                os.remove(temp_photo_path)
            except Exception as del_err:
                logger.error(f"Erro ao remover arquivo temporário {temp_photo_path}: {del_err}")        

# Em telegram_bot.py, SUBSTITUA a função receber_motivo_recusa por esta:

async def receber_motivo_recusa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id_grupo = update.effective_chat.id
    gestor_id = update.effective_user.id
    gestor_nome = update.effective_user.first_name
    motivo = update.message.text

    # --- Bloco de leitura (sem alteração) ---
    dados_recusa = None
    if 'pendencias_recusa' in context.bot_data and \
    chat_id_grupo in context.bot_data['pendencias_recusa'] and \
    gestor_id in context.bot_data['pendencias_recusa'][chat_id_grupo]:
        dados_recusa = context.bot_data['pendencias_recusa'][chat_id_grupo].pop(gestor_id)
        logger.info(f"Dados de recusa encontrados em bot_data para GestorID {gestor_id} no ChatID {chat_id_grupo}.")
        if not context.bot_data['pendencias_recusa'][chat_id_grupo]:
            context.bot_data['pendencias_recusa'].pop(chat_id_grupo)
        if not context.bot_data['pendencias_recusa']:
            context.bot_data.pop('pendencias_recusa')
    # --- Fim do Bloco de leitura ---

    if not dados_recusa:
        logger.debug(f"Mensagem de GestorID {gestor_id} no ChatID {chat_id_grupo} ignorada (sem pendência).")
        return

    # --- CORREÇÃO APLICADA AQUI ---
    # Extrai os dados recuperados de bot_data (que já continha o msg_id)
    entrega_id = dados_recusa['entrega_id']
    id_mensagem_original = dados_recusa['msg_id'] # <-- USAMOS O VALOR CORRETO
    # --- FIM DA CORREÇÃO ---

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

    # A linha "context.chat_data.pop" foi removida.
    if id_mensagem_original: # Agora usamos a variável correta
        try:
            await context.bot.edit_message_caption(chat_id=chat_id_grupo, message_id=id_mensagem_original, caption=legenda_final)
        except Exception as e_edit:
            logger.error(f"Erro ao editar caption da mensagem recusada (ID: {entrega_id}): {e_edit}")
            try:
                await update.message.reply_text(legenda_final)
            except Exception as e_send:
                logger.error(f"Falha também ao enviar mensagem de fallback para recusa {entrega_id}: {e_send}")
    else:
        logger.warning(f"Não foi possível encontrar msg_id original para recusa {entrega_id}. Enviando status como nova mensagem.")
        try:
            await update.message.reply_text(legenda_final)
        except Exception as e_send:
            logger.error(f"Falha ao enviar mensagem de fallback (sem msg_id) para recusa {entrega_id}: {e_send}")


async def solicitar_foto_nf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Define o estado para aguardar a foto da Nota Fiscal."""
    logger.info(f"Solicitação de envio de NF recebida de {update.effective_user.id}")
    context.user_data['aguardando_nota_fiscal'] = True
    await update.message.reply_text(
        "Entendido. Por favor, envie agora a foto da Nota Fiscal que você recebeu.\n\n"
        "(Se mudar de ideia, digite /cancelar)"
    )

async def receber_nota_fiscal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler dedicado para receber a foto da Nota Fiscal (Regras 1, 2, 3).
    Este handler SÓ é ativado se o estado 'aguardando_nota_fiscal' for True.
    """
    # Limpa o estado imediatamente
    context.user_data.pop('aguardando_nota_fiscal', None)

    # 1. Validações básicas (não encaminhada, não arquivo)
    if update.message.forward_from or update.message.forward_from_chat:
        await update.message.reply_text("❌ Desculpe, fotos encaminhadas não são aceitas. Por favor, tire a foto na hora ou envie da sua galeria.")
        return
    if update.message.document and 'image' in update.message.document.mime_type:
        await update.message.reply_text("❌ Por favor, envie a imagem como 'Foto', e não como 'Arquivo'.")
        return

    try:
        funcionario = database.buscar_funcionario_por_chat_id(update.effective_user.id)
        if not funcionario:
            await update.message.reply_text("Erro: Não consegui encontrar seu cadastro no sistema.")
            return

        file_id = update.message.photo[-1].file_id

        # 2. Salva o registro preliminar no banco (tabela NotasFiscais)
        nota_fiscal_id = database.registrar_nota_fiscal(funcionario.FuncionarioID, file_id)
        if not nota_fiscal_id:
            await update.message.reply_text("❌ Ocorreu um erro interno ao tentar registrar sua nota fiscal. Tente novamente.")
            return

        # 3. Dá os pontos bônus (Regra 1)
        pontos_bonus = config.PONTOS_BONUS_NOTA_FISCAL
        database.registrar_pontos_de_bonus(
            funcionario.FuncionarioID,
            pontos_bonus,
            f"Envio de Nota Fiscal (ID: {nota_fiscal_id})",
            config.TAREFA_ID_NOTA_FISCAL
        )
        database.adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_bonus)

        await update.message.reply_text(f"✅ Nota Fiscal enviada com sucesso! Você ganhou *{pontos_bonus} pontos* pelo recebimento!", parse_mode='Markdown')

        # 4. Encaminha para os Gestores (Regras 2, 3, 4)
        legenda_gestor = (
            f"🧾 **Nova Nota Fiscal Recebida** 🧾\n\n"
            f"👤 **Enviada por:** {funcionario.NomeCompleto}\n"
            f"🗓️ **Data:** {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"🆔 **NF ID:** {nota_fiscal_id}\n\n"
            "Ações Rápidas:"
        )

        # Prepara botões com o ID da NF para rastreio
        keyboard = [
            [InlineKeyboardButton("📲 Encaminhar p/ Financeiro", callback_data=f"nf_prep_fwd_{nota_fiscal_id}")],
            [InlineKeyboardButton("📦 Criar Tarefa 'Guardar'", callback_data=f"nf_create_task_{nota_fiscal_id}")],
            [InlineKeyboardButton("👍 Arquivar (Nenhuma Ação)", callback_data=f"nf_ignore_{nota_fiscal_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        notificador_telegram.enviar_foto_com_botoes(
            config.GESTOR_GROUP_CHAT_ID,
            file_id,
            legenda_gestor,
            reply_markup,
            parse_mode='HTML'
        )
        logger.info(f"Nota Fiscal {nota_fiscal_id} encaminhada para o grupo de gestores.")

    except Exception as e:
        logger.error(f"Erro crítico em receber_nota_fiscal: {e}", exc_info=True)
        await update.message.reply_text("Ocorreu um erro crítico. Contate o administrador.")

async def receber_foto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Roteador principal para fotos privadas.
    Verifica o estado do usuário e decide qual handler de foto chamar.
    """
    # Verifica primeiro se o usuário está no estado de enviar NF
    if context.user_data.get('aguardando_nota_fiscal', False):
        await receber_nota_fiscal(update, context)

    # Se não, chama o handler padrão de envio de fotos de tarefas
    else:
        await handler_foto_tarefa(update, context)


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
                
                # --- CORREÇÃO APLICADA AQUI ---
                # Usamos a nova função genérica de bônus, especificando o ID correto da tarefa de feedback.
                database.registrar_pontos_de_bonus(
                    funcionario_db.FuncionarioID, 
                    config.PONTOS_BONUS_FEEDBACK_DIARIO, 
                    "Feedback Diário (Bônus)",
                    config.TAREFA_ID_FEEDBACK_DIARIO # <-- Usa o ID correto (ex: 5)
                )
                # --- FIM DA CORREÇÃO ---
                
                database.adicionar_pontos_ao_saldo(funcionario_db.FuncionarioID, config.PONTOS_BONUS_FEEDBACK_DIARIO)
                texto_final = (f"Obrigado pelo seu feedback! Sua nota foi **{nota}**.\n\nVocê ganhou **{config.PONTOS_BONUS_FEEDBACK_DIARIO}** pontos por sua participação. Sua opinião nos ajuda a melhorar sempre! 💪")
                await query.edit_message_text(texto_final, parse_mode='Markdown')
            else: await query.edit_message_text("Você já enviou seu feedback hoje. Obrigado!")
        else: await query.edit_message_text("Erro: não foi possível identificar seu usuário.")

    elif data.startswith("aceitar_tarefa_"):
        origem_atribuicao_id = int(data.split('_')[-1])
        funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
        if not funcionario_db:
            await query.answer("Seu usuário do Telegram não foi encontrado no nosso sistema.", show_alert=True) # Avisa via popup
            return

        # Chama a função do banco
        nova_atribuicao_id_criada = database.aceitar_tarefa_de_grupo(origem_atribuicao_id, funcionario_db.FuncionarioID)

        # Busca o título da tarefa original para as mensagens
        tarefa_original = database.buscar_tarefa_por_atribuicao(origem_atribuicao_id)
        tarefa_titulo = tarefa_original.Titulo if tarefa_original else "Tarefa desconhecida"

        # <<< CORREÇÃO: Verifica se a atribuição foi criada com sucesso >>>
        if nova_atribuicao_id_criada:
            # SUCESSO! A instância 'Unica' foi criada para este funcionário HOJE.
            nova_mensagem_grupo = (
                f"✅ **Missão Aceita por {user.first_name}!** ✅\n\n"
                f"**Tarefa:** {tarefa_titulo}\n\n"
                f"{user.first_name} agora é o responsável pela entrega *de hoje*. Boa sorte!"
            )
            try:
                await query.edit_message_text(text=nova_mensagem_grupo, reply_markup=None)
            except Exception as e:
                logger.info(f"Aviso: Não foi possível editar a mensagem original no grupo para {origem_atribuicao_id}. Erro: {e}")

            # Mensagem privada de sucesso
            await context.bot.send_message(
                chat_id=user.id,
                text=f"Você aceitou a missão '{tarefa_titulo}' para hoje. Agora ela aparecerá na sua lista de /tarefas. Capriche na entrega! 💪"
            )
        else:
            # FALHA! Alguém já aceitou HOJE ou ocorreu outro erro no banco.
            # Avisa o usuário que clicou via popup (show_alert=True)
            await query.answer(f"Que pena, parece que a missão '{tarefa_titulo}' já foi aceita por outro colega hoje.", show_alert=True)
            # Opcional: Logar que a tentativa falhou
            logger.info(f"Funcionário {funcionario_db.FuncionarioID} tentou aceitar tarefa {origem_atribuicao_id} que já foi aceita hoje ou falhou no DB.")



    # Em telegram_bot.py, SUBSTITUA a lógica do 'aceitar_folga_' dentro de button_callback_handler

    elif data.startswith("aceitar_folga_"):
        tarefa_id = int(data.split('_')[-1])
        funcionario_aceitou = database.buscar_funcionario_por_chat_id(user.id)
        if not funcionario_aceitou:
            await context.bot.send_message(chat_id=user.id, text="Seu usuário do Telegram não foi encontrado.")
            return

        # --- LÓGICA CORRIGIDA E ROBUSTA ---
        # 1. Chama a nova função transacional do banco
        novo_atribuicao_id = database.verificar_e_aceitar_tarefa_de_folga(tarefa_id, funcionario_aceitou.FuncionarioID)

        # 2. Busca os detalhes da tarefa (apenas para a mensagem de confirmação)
        tarefa_info = database.buscar_tarefa_por_atribuicao(novo_atribuicao_id) if novo_atribuicao_id else None

        # 3. Verifica o resultado da transação
        if novo_atribuicao_id:
            # SUCESSO! A pessoa pegou a tarefa.
            nova_mensagem_grupo = (
                f"{query.message.text}\n\n"
                f"--- MISSÃO REIVINDICADA! ---\n"
                f"✅ **{funcionario_aceitou.NomeCompleto}** assumiu a tarefa."
            )
            # Tenta editar a mensagem do grupo para "travar" (remover o botão)
            try:
                await query.edit_message_text(text=nova_mensagem_grupo, reply_markup=None)
            except Exception as e:
                logger.warning(f"Não foi possível editar a msg de 'aceitar_folga_' (provavelmente já editada): {e}")

            # Envia a confirmação privada
            await context.bot.send_message(
                chat_id=user.id,
                text=f"🚀 Você assumiu a missão extra '{tarefa_info.Titulo}'! Ela já está na sua lista de /tarefas. Bom trabalho!"
            )
        else:
            # FALHA! (Função retornou False ou None)
            # Avisa o usuário que clicou (mas não conseguiu) via popup
            await query.answer("Que pena! Parece que outro colega já pegou esta missão.", show_alert=True)
        # --- FIM DA CORREÇÃO ---



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

    elif data.startswith("doc_ciente_"):
        await query.answer()
        assinatura_id = int(data.split('_')[-1])
        detalhes = database.buscar_detalhes_assinatura_para_bot(assinatura_id)

        # <<< CORREÇÃO: Verifica se 'detalhes' foi encontrado (ou seja, se a assinatura ainda estava pendente) >>>
        if not detalhes:
            await query.answer("Esta ciência já foi registrada anteriormente.", show_alert=True)
            # Tenta remover o botão se a edição anterior falhou
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass # Ignora erro se não conseguir editar
            return # Interrompe a execução aqui

        # Se 'detalhes' existe, prossegue com a lógica original
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
            # Adiciona pontos ao saldo PRIMEIRO (mais crítico)
            database.adicionar_pontos_ao_saldo(detalhes.FuncionarioID, detalhes.PontosPorCiencia)
            # DEPOIS registra no histórico (menos crítico se falhar)
            database.registrar_pontos_por_leitura(detalhes.FuncionarioID, detalhes.PontosPorCiencia, detalhes.Titulo)
            mensagem_confirmacao += f"\n\n🎉 Você ganhou **{detalhes.PontosPorCiencia}** pontos por sua agilidade!"

        # Lógica de edição da mensagem (permanece a mesma, já corrigida anteriormente)
        try:
            if query.message.photo:
                texto_original = query.message.caption
                await query.edit_message_caption(
                    caption=f"{texto_original}{mensagem_confirmacao}",
                    parse_mode='Markdown',
                    reply_markup=None
                )
            else:
                texto_original = query.message.text
                await query.edit_message_text(
                    text=f"{texto_original}{mensagem_confirmacao}",
                    parse_mode='Markdown',
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Erro ao editar a mensagem de ciência (ID: {assinatura_id}): {e}")
            await query.answer("Sua ciência foi registrada!", show_alert=True) # Feedback mínimo

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
        detalhes = database.buscar_detalhes_da_entrega(entrega_id) # Busca detalhes uma vez

        # <<< CORREÇÃO: Verifica o status ANTES de tentar aprovar >>>
        if not detalhes:
            try: await query.edit_message_caption(caption="ERRO: Entrega não encontrada no banco de dados.")
            except Exception: pass
            return
        if detalhes.StatusValidacao != 'Pendente':
            try: await query.edit_message_caption(caption=f"Esta tarefa já foi validada anteriormente. (Status: {detalhes.StatusValidacao})")
            except Exception: pass
            return

        # Se passou nas verificações, tenta aprovar no banco
        novas_conquistas_ganhas = database.aprovar_entrega(entrega_id, detalhes.FuncionarioID, detalhes.Pontos)

        # Prepara notificação para funcionário (mesma lógica de antes)
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
                # Adiciona pontos bônus AO SALDO aqui, pois aprovar_entrega só registra
                if conquista.PontosBonus > 0:
                    database.adicionar_pontos_ao_saldo(detalhes.FuncionarioID, conquista.PontosBonus)

        notificador_telegram.enviar_mensagem(detalhes.ChatIDFuncionario, texto_notificacao)

        # Edita a mensagem no grupo GESTOR
        legenda_final = (f"**Entrega APROVADA por {gestor_nome}**\n\n"
                        f"👤 **Funcionário:** {detalhes.NomeCompleto}\n"
                        f"📝 **Tarefa:** {detalhes.Titulo} (+{detalhes.Pontos} pts)")

                # <<< CORREÇÃO REVISADA: Adiciona try/except e fallback com nova mensagem >>>
        try:
            await query.edit_message_caption(caption=legenda_final, reply_markup=None) # Remove botões também
        except Exception as e_edit:
            logger.warning(f"Não foi possível editar a mensagem de aprovação {entrega_id} no grupo gestor: {e_edit}")
            # Fallback: Envia uma nova mensagem se a edição falhar
            try:
                await context.bot.send_message(chat_id=query.message.chat_id, text=legenda_final)
            except Exception as e_send:
                logger.error(f"Falha também ao enviar mensagem de fallback para aprovação {entrega_id}: {e_send}")
    # --- INÍCIO: LÓGICA DE GERENCIAMENTO DE NOTA FISCAL (GESTOR) ---

    elif data.startswith("nf_prep_fwd_"):
        # Regra 3: Encaminhar para o WhatsApp
        await query.answer("Processando...")
        gestor_chat_id = query.from_user.id
        try:
            nota_fiscal_id = int(data.split('_')[-1])
            dados_nf = database.buscar_nota_fiscal(nota_fiscal_id)

            if not dados_nf:
                await context.bot.send_message(gestor_chat_id, "Erro: Não encontrei os dados desta NF no banco.")
                return

            if not dados_nf.PathFoto:
                await context.bot.send_message(gestor_chat_id, "O download desta foto ainda está sendo processado pelo servidor. Tente novamente em 1 minuto.")
                return

            # Constrói o link do WhatsApp
            texto_mensagem_wpp = urllib.parse.quote(f"Olá, segue a Nota Fiscal recebida (ID Interno: {nota_fiscal_id})")
            link_wpp = f"https://wa.me/{config.WHATSAPP_CONTATO_FINANCEIRO}?text={texto_mensagem_wpp}"

            # Envia o arquivo da NF (do disco) PRIVADAMENTE para o gestor
            with open(dados_nf.PathFoto, 'rb') as nf_file:
                await context.bot.send_document(
                    chat_id=gestor_chat_id,
                    document=nf_file,
                    caption=f"Pronto! Por favor, encaminhe este arquivo para o Financeiro.\n\nVocê também pode usar este link:\n{link_wpp}"
                )
            # Atualiza o status no grupo
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n✅ Encaminhada para o Financeiro por {query.from_user.first_name}.")

        except Exception as e:
            logger.error(f"Erro em nf_prep_fwd: {e}", exc_info=True)
            await context.bot.send_message(gestor_chat_id, f"Ocorreu um erro ao preparar o encaminhamento: {e}")

    elif data.startswith("nf_create_task_"):
        # Regra 4: Criar Tarefa "Guardar Mercadoria"
        await query.answer("Criando tarefa...")
        try:
            nota_fiscal_id = int(data.split('_')[-1])
            dados_nf = database.buscar_nota_fiscal(nota_fiscal_id)

            if not dados_nf:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n❌ Erro: Não encontrei os dados desta NF.")
                return

            # Cria a nova tarefa 'Unica'
            nova_atribuicao_id = database.atribuir_tarefa(
                tarefa_id=config.TAREFA_ID_GUARDAR_MERCADORIA_MODELO,
                funcionario_id=dados_nf.FuncionarioID,
                tipo_frequencia='Unica',
                valor_frequencia=None,
                descricao_override="Guarde a mercadoria referente a esta Nota Fiscal.",
                data_agendamento=datetime.now().date() # Agenda para hoje
            )

            if not nova_atribuicao_id:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n❌ Erro: Falha ao salvar a nova tarefa no banco.")
                return

            # Atualiza o status da NF
            database.atualizar_status_nota_fiscal(nota_fiscal_id, "Processada")

            # Notifica o funcionário PRIVADAMENTE
            await context.bot.send_photo(
                chat_id=dados_nf.ChatIDFuncionario,
                photo=dados_nf.FileIDTelegram,
                caption="📦 **Nova Tarefa Atribuída!** 📦\n\nUma tarefa para *'Guardar Mercadoria (NF)'* foi criada para você com base na nota fiscal que você enviou.\n\nUse o comando /tarefas para ver e enviar a evidência."
            )

            # Atualiza a mensagem no grupo
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n✅ Tarefa 'Guardar' criada para o funcionário por {query.from_user.first_name}.")

        except Exception as e:
            logger.error(f"Erro em nf_create_task: {e}", exc_info=True)
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n❌ Erro inesperado ao criar tarefa: {e}")

    elif data.startswith("nf_ignore_"):
        # Ação de arquivar/ignorar
        await query.answer("Arquivando...")
        try:
            nota_fiscal_id = int(data.split('_')[-1])
            database.atualizar_status_nota_fiscal(nota_fiscal_id, "Processada")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n---\n👍 Nota revisada e arquivada por {query.from_user.first_name}.")
        except Exception as e:
            logger.error(f"Erro em nf_ignore: {e}", exc_info=True)

    # --- FIM: LÓGICA DE GERENCIAMENTO DE NOTA FISCAL (GESTOR) ---

    elif data.startswith("reprovar_gestor_"):
        entrega_id = int(data.split('_')[-1])
        gestor_id = query.from_user.id
        chat_id_grupo = query.message.chat_id
        msg_id_original = query.message.message_id

        # --- CORREÇÃO: Usar bot_data ---
        # Garante que a estrutura de dicionários exista
        if 'pendencias_recusa' not in context.bot_data:
            context.bot_data['pendencias_recusa'] = {}
        if chat_id_grupo not in context.bot_data['pendencias_recusa']:
            context.bot_data['pendencias_recusa'][chat_id_grupo] = {}

        # Armazena os dados associados ao gestor que clicou dentro do chat específico
        context.bot_data['pendencias_recusa'][chat_id_grupo][gestor_id] = {
            'entrega_id': entrega_id,
            'msg_id': msg_id_original
        }
        logger.info(f"Estado de recusa para EntregaID {entrega_id} armazenado em bot_data para GestorID {gestor_id} no ChatID {chat_id_grupo}.")
        # --- FIM CORREÇÃO ---

        # Remove botões da mensagem original (pode falhar, mas o estado já está salvo)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e_edit_markup:
            logger.warning(f"Não foi possível remover botões ao iniciar recusa {entrega_id}: {e_edit_markup}")

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
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🧾 Enviar Nota Fiscal$'), solicitar_foto_nf))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # --- Handlers para os Botões do Menu Fixo ---
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📋 Minhas Tarefas$'), tarefas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏆 Ranking do Mês$'), ranking))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🎯 Acompanhar Metas$'), acompanhar_metas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📜 Meu Histórico$'), meu_historico))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^❓ Ajuda$'), ajuda))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💰 Meu Saldo$'), meu_saldo))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏪 Loja de Recompensas$'), loja_recompensas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💬 Canal Confidencial$'), solicitar_feedback_start)) 
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📄 Meus Documentos$'), solicitar_holerite_inicio)) 
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏅 Minhas Conquistas$'), minhas_conquistas)) # <<< NOVO BOTÃO
    # Handler de FOTO para Nota Fiscal (verifica o estado 'aguardando_nota_fiscal')
    # Handler de FOTO (Roteador):
    # Esta única linha agora chama a nossa nova função roteadora "receber_foto".
    # Ela cuidará de direcionar para "receber_nota_fiscal" ou "handler_foto_tarefa".
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, receber_foto))

    # Handler de TEXTO genérico (para justificativas, cpf, etc.)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, roteador_de_texto_privado))
    # --- CORREÇÃO ADICIONADA AQUI ---
    # Adiciona o handler para capturar o "motivo da recusa" digitado pelo gestor no GRUPO.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUP, receber_motivo_recusa))
    # --- FIM DA CORREÇÃO ---
    logger.info("--- BOT INICIADO COM SUCESSO ---")
    application.run_polling()

if __name__ == '__main__':
    main()

>>>>>>> master

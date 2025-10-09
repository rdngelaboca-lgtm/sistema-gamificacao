import recibo_generator
import random
import os
import logging, config, database, random, notificador_telegram
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from PIL import Image
import exifread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler, filters, 
                          ContextTypes, CallbackQueryHandler)
from telegram.helpers import escape_markdown
from database import adicionar_pontos_ao_saldo

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = user.id
    funcionario = database.buscar_funcionario_por_chat_id(chat_id)
    
    # --- NOVO LAYOUT DO TECLADO ---
    REPLY_KEYBOARD = [
        ["📋 Minhas Tarefas", "🏆 Ranking do Mês"],
        ["💰 Meu Saldo", "🏪 Loja de Recompensas"], # <<< NOVA LINHA
        ["📜 Meu Histórico", "💬 Solicitar Feedback"],
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
        "📋 **Minhas Tarefas**: Mostra sua lista de tarefas pendentes para hoje.\n\n"
        "🏆 **Ranking do Mês**: Exibe a classificação de desempenho atual de todos os funcionários.\n\n"
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

# Em telegram_bot.py, SUBSTITUA a função ranking inteira:
async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ranking_data = database.calcular_ranking_desempenho()
    if not ranking_data:
        await update.message.reply_text("Ainda não há dados para gerar um ranking este mês.")
        return

    texto_ranking = "🏆 **Ranking de Desempenho do Mês** 🏆\n\n"
    texto_ranking += "O *Score Final* equilibra a Confiabilidade (fazer o que foi pedido) e o Esforço (volume de pontos).\n\n"
    
    icones = ["🥇", "🥈", "🥉"]
    for i, dados in enumerate(ranking_data):
        posicao_icone = icones[i] if i < len(icones) else f" {i+1}."
        nome = dados['NomeCompleto']
        score = dados['ScoreHibrido']
        # Adicionamos os detalhes para que o funcionário entenda a composição da nota
        detalhes = f"(Desempenho: {dados['Desempenho']}%, Pontos: {dados['PontosGanhos']})"
        
        texto_ranking += f"{posicao_icone} {nome} - **Score Final: {score}**\n   {detalhes}\n"

    await update.message.reply_text(texto_ranking, parse_mode='Markdown')

# Em telegram_bot.py, ADICIONE esta nova função:

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

async def solicitar_feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de solicitação de feedback."""
    await update.message.reply_text(
        "Entendido. Sobre qual tarefa ou assunto você gostaria de solicitar um feedback?"
    )
    # Define um "estado" para o usuário, indicando que a próxima mensagem dele é o assunto.
    context.user_data['aguardando_assunto_feedback'] = True

async def receber_assunto_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa a mensagem de texto do usuário contendo o assunto do feedback."""
    # Primeiro, verificamos se o bot está realmente esperando por essa resposta.
    if 'aguardando_assunto_feedback' not in context.user_data:
        # Se não estiver, chamamos a função que lida com outras mensagens de texto.
        # Isso evita que a função de feedback "roube" a justificativa de tarefa não aplicável.
        await receber_justificativa_na(update, context)
        return

    # Se o estado estiver correto, processamos a solicitação.
    assunto = update.message.text
    chat_id = update.effective_chat.id
    funcionario = database.buscar_funcionario_por_chat_id(chat_id)

    if funcionario:
        sucesso = database.criar_solicitacao_feedback(funcionario.FuncionarioID, assunto)
        if sucesso:
            # Notifica o grupo de gestores
            mensagem_gestor = (
                f"📢 **Nova Solicitação de Feedback**\n\n"
                f"👤 **De:** {funcionario.NomeCompleto}\n"
                f"📝 **Assunto:** {assunto}"
            )
            notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
            
            # Confirma para o funcionário
            await update.message.reply_text("✅ Sua solicitação de feedback foi enviada com sucesso aos gestores!")
        else:
            await update.message.reply_text("❌ Ocorreu um erro ao salvar sua solicitação. Tente novamente.")
    
    # Limpa o estado para finalizar a conversa
    context.user_data.pop('aguardando_assunto_feedback')

# SUBSTITUA TODA A SUA FUNÇÃO 'receber_foto' POR ESTA VERSÃO CORRIGIDA

# Em telegram_bot.py, SUBSTITUA a função receber_foto inteira por esta:

# Em telegram_bot.py, SUBSTITUA a função receber_foto inteira por esta:

# Em telegram_bot.py, SUBSTITUA a função receber_foto inteira por esta versão FLEXÍVEL:

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
        print(f"ERRO CRÍTICO em receber_foto: {e}")
        await update.message.reply_text("Ocorreu um erro crítico ao registrar sua entrega. Contate o administrador.")

    finally:
        if temp_photo_path and os.path.exists(temp_photo_path):
            os.remove(temp_photo_path)
        
async def receber_justificativa_na(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if 'tarefa_nao_aplicavel' not in context.user_data: return
    atribuicao_id = context.user_data.pop('tarefa_nao_aplicavel')
    database.registrar_tarefa_nao_aplicavel(atribuicao_id, update.message.text)
    keyboard = [[InlineKeyboardButton("⬅️ Ver Tarefas Restantes", callback_data="voltar_lista_tarefas")]]; reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Ok, registrado!", reply_markup=reply_markup)

# Em telegram_bot.py, SUBSTITUA a função antiga por esta versão COM PRINTS:

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
            print(f"Erro ao editar caption da mensagem recusada: {e}")
            await update.message.reply_text(legenda_final)
    
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # --- INÍCIO DA LÓGICA DA LOJA DE RECOMPENSAS (NOVA) ---
    if data.startswith("ver_produto_"):
        produto_id = int(data.split('_')[-1])
        produtos = database.listar_produtos_loja(incluir_inativos=True)
        produto = next((p for p in produtos if p.ProdutoID == produto_id), None)

        if not produto:
            await query.edit_message_text("Este produto não está mais disponível.")
            return

        funcionario = database.buscar_funcionario_por_chat_id(user.id)
        saldo_atual = database.buscar_saldo_funcionario(funcionario.FuncionarioID)
        
        texto = (
            f"<b>{produto.Nome}</b>\n\n"
            f"<i>{produto.Descricao}</i>\n\n"
            f"Custo: <b>{produto.CustoEmPontos} pontos</b>\n"
            f"Seu Saldo: <b>{saldo_atual} pontos</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar Resgate", callback_data=f"confirmar_resgate_{produto.ProdutoID}")],
            [InlineKeyboardButton("⬅️ Voltar para a Loja", callback_data="voltar_loja")]
        ]
        
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
            
            msg_gestor = (
                f"🔔 **Nova Solicitação de Resgate** 🔔\n\n"
                f"👤 **Funcionário:** {funcionario.NomeCompleto}\n"
                f"🎁 **Produto:** {produto.Nome}\n"
                f"💰 **Custo:** {produto.CustoEmPontos} pontos\n\n"
                f"Acesse o sistema (`main.py`) para aprovar."
            )
            notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, msg_gestor)

    # Dentro de button_callback_handler, substitua o "voltar_loja" por este:
    elif data == "voltar_loja":
        # Recria a mensagem da loja para o usuário, mas editando a mensagem atual
        produtos = database.listar_produtos_loja()
        texto = "🏪 **Loja de Recompensas** 🏪\n\nEscolha um item para ver os detalhes e resgatar:"
        keyboard = []
        for produto in produtos:
            estoque_str = f"({produto.EstoqueDisponivel} un.)" if produto.EstoqueDisponivel is not None else ""
            texto_botao = f"{produto.Nome} - {produto.CustoEmPontos} pts {estoque_str}"
            keyboard.append([InlineKeyboardButton(texto_botao, callback_data=f"ver_produto_{produto.ProdutoID}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # A mágica está aqui: usamos query.edit_message_text para modificar a mensagem existente
        await query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')

    # --- LÓGICA DE FEEDBACK DE FIM DE JORNADA ---
    elif data == "avaliar_dia":
        keyboard = []
        row = []
        for i in range(11):
            row.append(InlineKeyboardButton(str(i), callback_data=f"nota_dia_{i}"))
            if len(row) == 5 or i == 10:
                keyboard.append(row)
                row = []

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text=(f"{query.message.text}\n\n"
                  "Como você classificaria seu dia de 0 a 10?\n(0 = Muito Ruim / 10 = Excelente)"),
            reply_markup=reply_markup
        )

    elif data.startswith("nota_dia_"):
        nota = int(data.split('_')[-1])
        funcionario_db = database.buscar_funcionario_por_chat_id(user.id)

        if funcionario_db:
            sucesso = database.salvar_feedback_do_dia(funcionario_db.FuncionarioID, nota)
            if sucesso:
                TAREFA_ID_FEEDBACK = 40  # ATENÇÃO: Verifique se este é o ID correto da sua tarefa "Feedback Diário"
                PONTOS_FEEDBACK = 5      
                database.registrar_pontos_por_leitura(
                    funcionario_db.FuncionarioID, PONTOS_FEEDBACK, "Feedback Diário (Bônus)"
                )
                texto_final = (
                    f"Obrigado pelo seu feedback! Sua nota foi **{nota}**.\n\n"
                    f"Você ganhou **{PONTOS_FEEDBACK}** pontos por sua participação. "
                    f"Sua opinião nos ajuda a melhorar sempre! 💪"
                )
                await query.edit_message_text(texto_final, parse_mode='Markdown')
            else:
                await query.edit_message_text("Você já enviou seu feedback hoje. Obrigado!")
        else:
            await query.edit_message_text("Erro: não foi possível identificar seu usuário.")

    # --- LÓGICA DE ACEITE DE TAREFAS DE GRUPO E DE FOLGA ---
    elif data.startswith("aceitar_tarefa_"):
        atribuicao_id = int(data.split('_')[-1])
        funcionario_db = database.buscar_funcionario_por_chat_id(user.id)
        if not funcionario_db:
            await context.bot.send_message(chat_id=user.id, text="Seu usuário do Telegram não foi encontrado no nosso sistema.")
            return
        sucesso = database.aceitar_tarefa_de_grupo(atribuicao_id, funcionario_db.FuncionarioID)
        tarefa = database.buscar_tarefa_por_atribuicao(atribuicao_id)
        tarefa_titulo = tarefa.Titulo if tarefa else "Tarefa desconhecida"
        if sucesso:
            nova_mensagem_grupo = (
                f"✅ **Missão Aceita por {user.first_name}!** ✅\n\n"
                f"**Tarefa:** {tarefa_titulo}\n\n"
                f"{user.first_name} agora é o responsável pela entrega. Boa sorte!"
            )
            await query.edit_message_text(text=nova_mensagem_grupo)
            await context.bot.send_message(
                chat_id=user.id,
                text=f"Você aceitou a missão '{tarefa_titulo}'. Agora ela aparecerá na sua lista de /tarefas. Capriche na entrega! 💪"
            )
        else:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"Que pena, parece que um colega foi mais rápido e já aceitou a missão '{tarefa_titulo}'. Fique de olho na próxima! 👀",
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
            return
        database.atribuir_tarefa(tarefa_id, funcionario_aceitou.FuncionarioID, 'Unica', None)
        tarefa_info = database.buscar_tarefa_por_atribuicao(database.listar_tarefas_do_dia_por_funcionario(funcionario_aceitou.FuncionarioID)[-1].AtribuicaoID)
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
            print(f"!!!!!!!! ERRO AO TENTAR EDITAR A MENSAGEM DE CIÊNCIA: {e} !!!!!!!!")
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

    # --- LÓGICA DE VALIDAÇÃO DE TAREFAS (GESTOR, NO GRUPO) ---
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

    elif data.startswith("reprovar_gestor_"):
        entrega_id = int(data.split('_')[-1])
        context.chat_data['aguardando_motivo_recusa'] = entrega_id
        context.chat_data[f'msg_id_{entrega_id}'] = query.message.message_id
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Por favor, {query.from_user.first_name}, digite o motivo da recusa para esta tarefa.")

def main() -> None:
    application = Application.builder().token(config.TELEGRAM_TOKEN).connect_timeout(30).read_timeout(30).build()
    
    # --- Comandos do Admin ---
    application.add_handler(CommandHandler("id", obter_id_chat))
    application.add_handler(CommandHandler("pendencias", pendencias_gestor))

    # --- Comandos do Funcionário ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tarefas", tarefas))
    application.add_handler(CommandHandler("ranking", ranking))
    application.add_handler(CommandHandler("meuhistorico", meu_historico))
    application.add_handler(CommandHandler("solicitarfeedback", solicitar_feedback_start))
    application.add_handler(CommandHandler("ajuda", ajuda))
    
    # --- NOVOS COMANDOS DA LOJA ---
    application.add_handler(CommandHandler("meusaldo", meu_saldo))
    application.add_handler(CommandHandler("loja", loja_recompensas))

    # --- Handlers para os Botões do Menu Fixo ---
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📋 Minhas Tarefas$'), tarefas))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏆 Ranking do Mês$'), ranking))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📜 Meu Histórico$'), meu_historico))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💬 Solicitar Feedback$'), solicitar_feedback_start))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^❓ Ajuda$'), ajuda))
    
    # --- NOVOS HANDLERS DA LOJA ---
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💰 Meu Saldo$'), meu_saldo))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏪 Loja de Recompensas$'), loja_recompensas))

    # --- Handlers de Interação e Respostas ---
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, receber_foto))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, receber_assunto_feedback))
    # (e seus outros handlers de mensagem de texto...)

    print("🚀 Bot (v4.0 com Loja) iniciado com sucesso! 🚀")
    application.run_polling()

if __name__ == '__main__':
    main()

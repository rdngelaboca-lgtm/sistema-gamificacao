# agendador.py (O Robô Notificador 2.0 - Versão Jornada de Trabalho)

import schedule
import time
import database
import notificador_telegram
import config
import os
from datetime import datetime, date, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# --- MÓDULO 1: TAREFAS DE GRUPO (sem alteração) ---
def verificar_e_enviar_tarefas_de_grupo():
    """Verifica e envia tarefas competitivas agendadas para grupos."""
    agora = datetime.now().strftime('%H:%M')
    # print(f"[{agora}] Verificando tarefas de grupo...") # Log opcional

    tarefas_para_disparar = database.buscar_tarefas_de_grupo_para_disparar(agora)
    
    if not tarefas_para_disparar:
        return

    print(f"[{agora}] Encontradas {len(tarefas_para_disparar)} tarefas de GRUPO para disparar!")
    for tarefa in tarefas_para_disparar:
        atribuicao_id, titulo, pontos, nome_grupo, chat_id, *_ = tarefa
        
        mensagem = (
            f"🚨 **Nova Missão para a Equipe!** 🚨\n\n"
            f"**Tarefa:** {titulo}\n"
            f"**Recompensa:** {pontos} pontos\n\n"
            "O primeiro a aceitar fica responsável pela entrega. Quem vai encarar?"
        )
        
        keyboard = [[InlineKeyboardButton("✅ Eu aceito o desafio!", callback_data=f"aceitar_tarefa_{atribuicao_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        notificador_telegram.enviar_mensagem_com_botao(chat_id, mensagem, reply_markup)
        print(f"--> Missão de grupo '{titulo}' enviada para '{nome_grupo}'.")

# --- MÓDULO 2: INÍCIO DA JORNADA (Lógica antiga, agora focada) ---
def verificar_inicio_jornada():
    """Verifica e notifica funcionários que estão começando a jornada AGORA."""
    agora = datetime.now().strftime('%H:%M')
    
    funcionarios_para_notificar = database.buscar_funcionarios_por_horario(agora)

    if not funcionarios_para_notificar:
        return

    print(f"[{agora}] {len(funcionarios_para_notificar)} funcionário(s) iniciando a jornada!")
    
    for funcionario in funcionarios_para_notificar:
        print(f"--> Processando início de jornada para: {funcionario.NomeCompleto}")
        
        tarefas_do_dia = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)
        
        mensagem = f"Olá, <b>{funcionario.NomeCompleto}</b>! 🌤️\n\n"
        if not tarefas_do_dia:
            mensagem += "Você não tem nenhuma tarefa recorrente para hoje. Tenha um excelente dia de trabalho! ✨"
        else:
            mensagem += "Estes são os seus desafios de hoje:\n\n"
            for tarefa in tarefas_do_dia:
                tipo_str = f"({tarefa.Tipo})" if tarefa.Tipo != 'Unica' else "(Especial)"
                mensagem += f"  - {tarefa.Titulo} {tipo_str} - <i>{tarefa.Pontos} pts</i>\n"
            mensagem += "\nUse o comando /tarefas para começar. Bom trabalho! 💪"
            
        notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem)
        print(f"--> Notificação de início de jornada enviada com sucesso para {funcionario.NomeCompleto}.")

# --- MÓDULO 3: LEMBRETES INTERMEDIÁRIOS (Lógica Nova!) ---
def verificar_lembretes_intermediarios():
    """Verifica e envia lembretes para funcionários no meio do expediente."""
    agora = datetime.now().strftime('%H:%M')

    funcionarios_para_lembrar = database.buscar_funcionarios_para_lembrete(agora)

    if not funcionarios_para_lembrar:
        return

    print(f"[{agora}] {len(funcionarios_para_lembrar)} funcionário(s) para enviar LEMBRETE!")
    
    for funcionario in funcionarios_para_lembrar:
        tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)

        if tarefas_pendentes:
            print(f"--> {funcionario.NomeCompleto} tem tarefas pendentes. Enviando lembrete.")
            mensagem = f"Olá, <b>{funcionario.NomeCompleto}</b>! 👋 Só um lembrete amigável sobre seus desafios de hoje que ainda estão em aberto:\n\n"
            for tarefa in tarefas_pendentes:
                mensagem += f"  - {tarefa.Titulo} - <i>{tarefa.Pontos} pts</i>\n"
            
            ### ALTERAÇÃO AQUI ###
            # Adicionamos a chamada para ação antes da mensagem de incentivo.
            mensagem += "\nUse o comando /tarefas para iniciar uma delas."
            mensagem += "\n\nContinue com o ótimo trabalho! Você consegue! 🚀"
            
            notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem)
        else:
            print(f"--> {funcionario.NomeCompleto} está com tudo em dia! Nenhum lembrete necessário.")

def verificar_fim_jornada():
    """Verifica e envia um resumo para funcionários que terminaram o expediente."""
    agora = datetime.now().strftime('%H:%M')

    funcionarios_para_resumo = database.buscar_funcionarios_para_resumo_final(agora)

    if not funcionarios_para_resumo:
        return

    print(f"[{agora}] {len(funcionarios_para_resumo)} funcionário(s) finalizando a jornada!")

    for funcionario in funcionarios_para_resumo:
        tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)

        mensagem = f"<b>{funcionario.NomeCompleto}</b>, fim de expediente! 🌆\n\n"
        if not tarefas_pendentes:
            mensagem += "Você concluiu todos os seus desafios de hoje. Trabalho incrível! 🏆\n\n"
        else:
            mensagem += "Obrigado pelo seu esforço hoje! 🙌\n\nAs seguintes tarefas ficaram pendentes:\n"
            for tarefa in tarefas_pendentes:
                mensagem += f"  - {tarefa.Titulo}\n"
            mensagem += "\n"

        # --- NOVA PARTE: CONVITE PARA FEEDBACK ---
        mensagem += "Sua opinião é muito importante para nós! Como você avalia seu dia de trabalho hoje?"

        keyboard = [[InlineKeyboardButton("⭐ Avaliar meu dia", callback_data="avaliar_dia")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Usamos o enviar_mensagem_com_botao que já existe no notificador
        notificador_telegram.enviar_mensagem_com_botao(funcionario.ChatIDTelegram, mensagem, reply_markup)
        print(f"--> Resumo de fim de jornada com convite de feedback enviado para {funcionario.NomeCompleto}.")

# Em agendador.py, adicione esta nova função

def verificar_e_delegar_tarefas_de_folga():
    """
    Verifica quem está de folga e oferece as tarefas recorrentes da pessoa
    para o grupo geral como uma missão extra.
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}]  delegando tarefas de quem está de folga...  Delegando...!")
    
    funcionarios_de_folga = database.buscar_funcionarios_de_folga_hoje()
    
    if not funcionarios_de_folga:
        print("--> Nenhum funcionário de folga hoje. Nenhuma tarefa a ser delegada.")
        return

    print(f"--> Encontrados {len(funcionarios_de_folga)} funcionário(s) de folga hoje.")
    for funcionario in funcionarios_de_folga:
        tarefas_do_dia = database.buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario.FuncionarioID)
        
        if not tarefas_do_dia:
            continue

        for tarefa in tarefas_do_dia:
            mensagem = (
                f"📢 **Missão Extra Disponível!** 📢\n\n"
                f"O(a) colega **{funcionario.NomeCompleto}** está de folga hoje, mas a tarefa abaixo precisa ser feita:\n\n"
                f"**Tarefa:** {tarefa.Titulo}\n"
                f"**Recompensa:** {tarefa.Pontos} pontos\n\n"
                "Quem pode assumir essa missão e garantir os pontos?"
            )
            
            # Criamos um callback único para esta tarefa específica
            callback_data = f"aceitar_folga_{tarefa.TarefaID}"
            
            keyboard = [[InlineKeyboardButton("✅ Eu aceito!", callback_data=callback_data)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            notificador_telegram.enviar_mensagem_com_botao(config.FOLGA_GROUP_CHAT_ID, mensagem, reply_markup)
            print(f"--> Tarefa '{tarefa.Titulo}' de {funcionario.NomeCompleto} delegada para o grupo.")

# Em agendador.py, SUBSTITUA a função antiga por esta versão mais segura:
def executar_fechamento_mensal():
    """
    Executa toda a lógica de finalização do mês, agora com verificação
    para não rodar duas vezes.
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🏆 INICIANDO ROTINA DE FECHAMENTO MENSAL! 🏆")
    
    hoje = date.today()
    fim_mes_passado = hoje.replace(day=1) - timedelta(days=1)
    ano_fechamento = fim_mes_passado.year
    mes_fechamento = fim_mes_passado.month

    # --- NOVA ETAPA DE SEGURANÇA ---
    if database.verificar_se_fechamento_ja_rodou(ano_fechamento, mes_fechamento):
        print(f"--> ATENÇÃO: O fechamento para o mês {mes_fechamento}/{ano_fechamento} já foi executado. Ação abortada.")
        return
    # --------------------------------

    ranking_final = database.calcular_ranking_desempenho(data_final_calculo=fim_mes_passado)
    
    if not ranking_final:
        print("--> Nenhum dado de ranking para o mês passado. Fechamento abortado.")
        return

    database.salvar_historico_ranking(ranking_final)
    
    # ... O resto da função continua exatamente igual ...
    prizes = [
        "🏆 1 dia de folga + R$50 para ir ao cinema",
        "🥈 Meio dia de folga + 1 Pote Pop da Gela Boca",
        "🥉 1 Taça do nosso cardápio",
        "🏅 1 sacolada com 10 picolés"
    ]
    texto_gestores = "🎉 **Fechamento do Mês: Pódio Final!** 🎉\n\n"
    vencedores_para_notificar = []
    
    for i, vencedor in enumerate(ranking_final[:len(prizes)]):
        premio = prizes[i]
        texto_gestores += f"{i+1}º: {vencedor['NomeCompleto']} ({vencedor['Desempenho']}%)\n   - Prêmio: {premio}\n"
        vencedores_para_notificar.append({'dados': vencedor, 'premio': premio, 'posicao': i+1})

    notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, texto_gestores)
    
    for vencedor in vencedores_para_notificar:
        dados = vencedor['dados']
        chat_id = database.buscar_funcionario_por_id(dados['FuncionarioID']).ChatIDTelegram
        texto_vencedor = (f"🎉🎊 **PARABÉNS, {dados['NomeCompleto']}!** 🎊🎉\n\n"
                          f"Você foi um dos campeões do mês no nosso jogo de gamificação!\n\n"
                          f"Sua Posição: **{vencedor['posicao']}º Lugar** com **{dados['Desempenho']}%** de desempenho.\n"
                          f"Sua Recompensa: **{vencedor['premio']}**\n\n"
                          "Procure o seu gestor para combinar o recebimento. Continue com o trabalho incrível!")
        notificador_telegram.enviar_mensagem(chat_id, texto_vencedor)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ FECHAMENTO MENSAL CONCLUÍDO! ✅")

def verificar_e_executar_fechamento():
    """
    Função que o agendador chama todo dia. Ela verifica se hoje é o dia
    correto para rodar a rotina de fechamento.
    """
    # A lógica só roda se hoje for o dia 1 do mês.
    if datetime.now().day == 1:
        executar_fechamento_mensal()
    else:
        # Apenas um log para sabermos que a verificação foi feita.
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificação de fechamento: hoje não é dia 1. Nenhuma ação necessária.", end='\r')

# Em agendador.py, ADICIONE esta nova função

def verificar_e_enviar_lembretes_comunicados():
    """Verifica e envia lembretes de comunicados pendentes há mais de 24h."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando lembretes de comunicados...")

    pendencias = database.buscar_assinaturas_pendentes_antigas(horas_atras=24)

    if not pendencias:
        print("--> Nenhum lembrete de comunicado a ser enviado.")
        return

    print(f"--> Encontradas {len(pendencias)} pendências de comunicados para lembrar!")
    for pendencia in pendencias:
        mensagem = (
            f"Olá, <b>{pendencia.NomeCompleto}</b>! 👋\n\n"
            "Só um lembrete amigável de que o seguinte comunicado ainda aguarda sua confirmação de ciência:\n\n"
            f"📄 <b>Título:</b> {pendencia.Titulo}\n"
            f"🗓️ <b>Enviado em:</b> {pendencia.DataEnvio.strftime('%d/%m/%Y')}\n\n"
            "Por favor, verifique seu histórico de mensagens para dar o ciente. Obrigado!"
        )
        notificador_telegram.enviar_mensagem(pendencia.ChatIDTelegram, mensagem)
        print(f"--> Lembrete sobre '{pendencia.Titulo}' enviado para {pendencia.NomeCompleto}.")

# Em agendador.py, SUBSTITUA a função antiga por esta versão async

async def processar_downloads_pendentes_async():
    """Busca por entregas sem foto baixada e tenta fazer o download (VERSÃO ASYNC)."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando downloads de fotos pendentes...")
    
    entregas_para_baixar = database.buscar_entregas_para_download()
    if not entregas_para_baixar:
        return

    print(f"--> Encontradas {len(entregas_para_baixar)} fotos para baixar.")
    
    from telegram.ext import Application
    # Criamos uma instância da aplicação apenas para usar suas ferramentas de rede
    app = Application.builder().token(config.TELEGRAM_TOKEN).connect_timeout(30).read_timeout(30).build()

    for entrega in entregas_para_baixar:
        try:
            print(f"--> Baixando foto para EntregaID: {entrega.EntregaID}...")
            # A CORREÇÃO MÁGICA: Usamos 'await' para esperar a chamada de rede
            file_info = await app.bot.get_file(entrega.FileIDTelegram)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join('entregas', f'{timestamp}_{entrega.EntregaID}.jpg')
            
            # E usamos 'await' aqui também para esperar o download
            await file_info.download_to_drive(file_path)
            
            database.finalizar_registro_entrega(entrega.EntregaID, file_path)
            print(f"--> SUCESSO! Foto da EntregaID {entrega.EntregaID} salva em {file_path}")
        except Exception as e:
            print(f"--> FALHA ao baixar foto da EntregaID {entrega.EntregaID}. Erro: {e}. Tentaremos novamente no próximo minuto.")

# Função "empacotadora" que o schedule pode chamar
def processar_downloads_pendentes():
    import asyncio
    asyncio.run(processar_downloads_pendentes_async())

if __name__ == "__main__":
    print("--- 🤖 Robô Agendador 2.0 Iniciado 🤖 ---")
    print("O sistema verificará a cada minuto e o fechamento mensal às 08:00.")

    schedule.every(1).minutes.do(verificar_inicio_jornada)
    schedule.every(1).minutes.do(verificar_lembretes_intermediarios)
    schedule.every(1).minutes.do(verificar_fim_jornada)
    schedule.every(1).minutes.do(verificar_e_enviar_tarefas_de_grupo)
    
    schedule.every().day.at("08:00").do(verificar_e_executar_fechamento)
    schedule.every().day.at("09:05").do(verificar_e_delegar_tarefas_de_folga)
    schedule.every().day.at("09:00").do(verificar_e_enviar_lembretes_comunicados)
    schedule.every(1).minutes.do(processar_downloads_pendentes)

    while True:
        schedule.run_pending()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Robô Ativo. Verificando agendamentos...", end='\r')
        time.sleep(1)
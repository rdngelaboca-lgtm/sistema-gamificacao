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
        print(f"Pasta de logs criada em: {log_dir}") # Print inicial para confirmar criação
    except OSError as e:
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

import schedule
import time
import database
import notificador_telegram
import config
import os
from datetime import datetime, date, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import requests

# Em agendador.py, SUBSTITUA a função verificar_e_enviar_tarefas_de_grupo por esta:
def verificar_e_enviar_tarefas_de_grupo():
    """
    (VERSÃO FINAL - SUPORTA DIARIA/SEMANAL/MENSAL)
    Verifica e envia tarefas recorrentes agendadas para grupos,
    considerando a frequência correta.
    """
    agora_dt = datetime.now()
    agora_hm = agora_dt.strftime('%H:%M')
    # Obter dia da semana no formato SQL: Domingo=1, Segunda=2, ..., Sábado=7
    dia_semana_sql = (agora_dt.weekday() + 1) % 7 + 1
    # Obter dia do mês
    dia_mes = agora_dt.day


    # Passamos os novos parâmetros para a função do banco
    tarefas_para_disparar = database.buscar_tarefas_de_grupo_para_disparar(agora_hm, str(dia_semana_sql), str(dia_mes))

    if not tarefas_para_disparar:
        return

    logger.info(f"[{agora_hm}] Encontradas {len(tarefas_para_disparar)} tarefas de GRUPO para disparar!")
    for tarefa in tarefas_para_disparar:
        atribuicao_id, titulo, pontos, nome_grupo, chat_id, *_ = tarefa

        mensagem = (
            f"🚨 **Nova Missão para a Equipe!** 🚨\n\n"
            f"**Tarefa:** {titulo}\n"
            f"**Recompensa:** {pontos} pontos\n\n"
            "O primeiro a aceitar fica responsável pela entrega *de hoje*. Quem vai encarar?"
        )

        keyboard = [[InlineKeyboardButton("✅ Eu aceito o desafio!", callback_data=f"aceitar_tarefa_{atribuicao_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        notificador_telegram.enviar_mensagem_com_botao(chat_id, mensagem, reply_markup)
        print(f"--> Missão de grupo '{titulo}' (ID Origem: {atribuicao_id}) enviada para '{nome_grupo}'.")

# --- MÓDULO 2: INÍCIO DA JORNADA (Lógica antiga, agora focada) ---
def verificar_inicio_jornada():
    """Verifica e notifica funcionários que estão começando a jornada AGORA."""
    agora = datetime.now().strftime('%H:%M')
    
    funcionarios_para_notificar = database.buscar_funcionarios_por_horario(agora)

    if not funcionarios_para_notificar:
        return

    logger.info(f"[{agora}] {len(funcionarios_para_notificar)} funcionário(s) iniciando a jornada!")
    
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
        logger.info(f"--> Notificação de início de jornada enviada com sucesso para {funcionario.NomeCompleto}.")

# --- MÓDULO 3: LEMBRETES INTERMEDIÁRIOS (Lógica Nova!) ---
def verificar_lembretes_intermediarios():
    """Verifica e envia lembretes para funcionários no meio do expediente."""
    agora = datetime.now().strftime('%H:%M')

    funcionarios_para_lembrar = database.buscar_funcionarios_para_lembrete(agora)

    if not funcionarios_para_lembrar:
        return

    logger.info(f"[{agora}] {len(funcionarios_para_lembrar)} funcionário(s) para enviar LEMBRETE!")
    
    for funcionario in funcionarios_para_lembrar:
        tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)

        if tarefas_pendentes:
            logger.info(f"--> {funcionario.NomeCompleto} tem tarefas pendentes. Enviando lembrete.")
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

    logger.info(f"[{agora}] {len(funcionarios_para_resumo)} funcionário(s) finalizando a jornada!")

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

# Em agendador.py, SUBSTITUA a função antiga por esta versão com suporte a múltiplos cargos:

# Em agendador.py, SUBSTITUA a função antiga por esta versão com notificações individuais:

def verificar_e_delegar_tarefas_de_folga():
    """
    (VERSÃO FINAL COM NOTIFICAÇÕES INDIVIDUAIS)
    Verifica folgas, envia a oferta para os grupos corretos e notifica
    cada membro do grupo no privado.
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}]  Verificando tarefas de funcionários de folga...")
    
    hoje = datetime.now()
    dia_da_semana_hoje = hoje.isoweekday() + 1
    if dia_da_semana_hoje == 8:
        dia_da_semana_hoje = 1
    
    funcionarios_de_folga = database.buscar_funcionarios_de_folga_hoje(dia_da_semana_hoje)
    
    if not funcionarios_de_folga:
        print("--> Nenhum funcionário de folga hoje. Nenhuma tarefa a ser delegada.")
        return

    print(f"--> Encontrados {len(funcionarios_de_folga)} funcionário(s) de folga hoje.")
    for funcionario in funcionarios_de_folga:
        tarefas_do_dia = database.buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario.FuncionarioID, dia_da_semana_hoje)
        
        if not tarefas_do_dia:
            continue

        lista_de_destinos = []
        if 'Atendimento' in funcionario.Cargo:
            lista_de_destinos.append(config.ATENDIMENTO_GROUP_CHAT_ID)
            print(f"--> Funcionário '{funcionario.NomeCompleto}' tem cargo de Atendimento. Adicionando grupo de Atendimento.")
        if 'Cozinha' in funcionario.Cargo:
            lista_de_destinos.append(config.COZINHA_GROUP_CHAT_ID)
            print(f"--> Funcionário '{funcionario.NomeCompleto}' tem cargo de Cozinha. Adicionando grupo de Cozinha.")

        cargo_funcionario = funcionario.Cargo if funcionario.Cargo else "" # Garante que não seja None

        # Verifica se contém as palavras-chave, independentemente de outros termos
        if 'Atendimento' in cargo_funcionario:
            lista_de_destinos.append(config.ATENDIMENTO_GROUP_CHAT_ID)
            print(f"--> Funcionário '{funcionario.NomeCompleto}' (Cargo: '{cargo_funcionario}') tem cargo de Atendimento. Adicionando grupo de Atendimento.")
        if 'Cozinha' in cargo_funcionario:
            lista_de_destinos.append(config.COZINHA_GROUP_CHAT_ID)
            print(f"--> Funcionário '{funcionario.NomeCompleto}' (Cargo: '{cargo_funcionario}') tem cargo de Cozinha. Adicionando grupo de Cozinha.")

        # Se NENHUM grupo específico foi adicionado, usa o grupo geral de FOLGA como fallback
        if not lista_de_destinos:
            lista_de_destinos.append(config.FOLGA_GROUP_CHAT_ID) # <--- ALTERAÇÃO AQUI
            print(f"--> AVISO: Cargo '{cargo_funcionario}' não mapeado ou vazio. Usando o grupo geral de folgas ID: {config.FOLGA_GROUP_CHAT_ID}.")
            # Opcional: Notificar gestores também neste caso
            # notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, f"Tarefa de {funcionario.NomeCompleto} (folga, cargo '{cargo_funcionario}') enviada para o grupo geral de folgas.")

        for tarefa in tarefas_do_dia:
            mensagem_grupo = (
                f"📢 **Missão Extra Disponível!** 📢\n\n"
                f"O(a) colega **{funcionario.NomeCompleto}** está de folga hoje, mas a tarefa abaixo precisa ser feita:\n\n"
                f"**Setor:** {tarefa.Setor or 'Geral'}\n"
                f"**Tarefa:** {tarefa.Titulo}\n"
                f"**Recompensa:** {tarefa.Pontos} pontos\n\n"
                "Quem pode assumir essa missão e garantir os pontos?"
            )
            callback_data = f"aceitar_folga_{tarefa.TarefaID}"
            keyboard = [[InlineKeyboardButton("✅ Eu aceito!", callback_data=callback_data)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            for chat_id_destino in lista_de_destinos:
                # 1. Envia a mensagem principal para o grupo
                notificador_telegram.enviar_mensagem_com_botao(chat_id_destino, mensagem_grupo, reply_markup)
                print(f"--> Tarefa '{tarefa.Titulo}' delegada com sucesso para o grupo ID: {chat_id_destino}.")

                # --- NOVA LÓGICA DE NOTIFICAÇÃO INDIVIDUAL ---
                membros_do_grupo = database.listar_membros_por_chat_id_grupo(chat_id_destino)
                if not membros_do_grupo:
                    print(f"--> AVISO: Nenhum membro encontrado para o grupo {chat_id_destino}. Notificações individuais não enviadas.")
                    continue

                print(f"--> Encontrados {len(membros_do_grupo)} membros no grupo. Enviando notificações individuais...")
                
                grupo_info = database.buscar_grupo_por_chat_id(chat_id_destino)
                nome_grupo = grupo_info.NomeGrupo if grupo_info else "do seu time"

                mensagem_privada = (
                    f"🚀 **Oportunidade de Pontos Extras!** 🚀\n\n"
                    f"Uma nova 'Missão Extra' foi postada no grupo **{nome_grupo}**.\n\n"
                    f"É a tarefa *'{tarefa.Titulo}'* que vale **{tarefa.Pontos} pontos**!\n\n"
                    "Seja o primeiro(a) a aceitar no grupo e garanta a pontuação. Boa sorte! 💪"
                )

                for membro in membros_do_grupo:
                    # Regra de segurança: não notifica a pessoa que já está de folga.
                    if membro.FuncionarioID == funcionario.FuncionarioID:
                        continue
                        
                    notificador_telegram.enviar_mensagem(membro.ChatIDTelegram, mensagem_privada)
                    time.sleep(0.1) # Pausa de 0.1s para não sobrecarregar a API do Telegram
                
                logger.info(f"--> Notificações individuais enviadas para os membros do grupo {nome_grupo}.")

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

# Em agendador.py

def processar_downloads_pendentes_sync():
    """Busca por entregas sem foto baixada e tenta fazer o download (VERSÃO SÍNCRONA COM REQUESTS)."""
    # Usando logger em vez de print para consistência
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando downloads de fotos pendentes...")

    entregas_para_baixar = database.buscar_entregas_para_download()
    if not entregas_para_baixar:
        logger.debug("--> Nenhuma foto pendente para download.") # Usando debug para menos poluição no log normal
        return

    logger.info(f"--> Encontradas {len(entregas_para_baixar)} fotos para baixar.")

    token = config.TELEGRAM_TOKEN # Pega o token do config

    for entrega in entregas_para_baixar:
        try:
            logger.info(f"--> Baixando foto para EntregaID: {entrega.EntregaID} (FileID: {entrega.FileIDTelegram})...")

            # 1. Obter informações do arquivo (incluindo file_path)
            get_file_url = f"https://api.telegram.org/bot{token}/getFile"
            params = {'file_id': entrega.FileIDTelegram}
            # Adiciona timeout para evitar bloqueios indefinidos
            response_file_info = requests.get(get_file_url, params=params, timeout=30)
            response_file_info.raise_for_status() # Lança erro se a requisição falhar
            file_info = response_file_info.json()

            if not file_info.get('ok'):
                logger.error(f"--> FALHA API getFile para EntregaID {entrega.EntregaID}: {file_info.get('description')}")
                continue # Pula para a próxima entrega

            telegram_file_path = file_info['result']['file_path']

            # 2. Construir a URL de download
            download_url = f"https://api.telegram.org/file/bot{token}/{telegram_file_path}"

            # 3. Fazer o download do arquivo
            # Adiciona timeout para o download
            response_download = requests.get(download_url, stream=True, timeout=60)
            response_download.raise_for_status() # Lança erro se o download falhar

            # 4. Salvar o arquivo localmente
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Cria a pasta 'entregas' se não existir (melhor prática)
            pasta_entregas = 'entregas'
            if not os.path.exists(pasta_entregas):
                try:
                    os.makedirs(pasta_entregas)
                    logger.info(f"Pasta '{pasta_entregas}' criada.")
                except OSError as e:
                    logger.error(f"Erro ao criar pasta '{pasta_entregas}': {e}", exc_info=True)
                    continue # Pula esta entrega se não conseguir criar a pasta

            local_file_path = os.path.join(pasta_entregas, f'{timestamp}_{entrega.EntregaID}.jpg')

            with open(local_file_path, 'wb') as f:
                for chunk in response_download.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 5. Atualizar o banco de dados
            database.finalizar_registro_entrega(entrega.EntregaID, local_file_path)
            logger.info(f"--> SUCESSO! Foto da EntregaID {entrega.EntregaID} salva em {local_file_path}")

        except requests.exceptions.Timeout:
            logger.warning(f"--> TIMEOUT ao tentar baixar foto da EntregaID {entrega.EntregaID}. Tentaremos novamente.")
        except requests.exceptions.RequestException as req_err:
             logger.error(f"--> FALHA DE REDE ao baixar foto da EntregaID {entrega.EntregaID}. Erro: {req_err}. Tentaremos novamente.")
        except Exception as e:
             logger.error(f"--> FALHA GERAL ao baixar foto da EntregaID {entrega.EntregaID}. Erro: {e}. Tentaremos novamente.", exc_info=True)


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
    schedule.every(1).minutes.do(processar_downloads_pendentes_sync)

    while True:
        schedule.run_pending()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Robô Ativo. Verificando agendamentos...", end='\r')
        time.sleep(1)

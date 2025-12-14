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
import urllib.parse
from collections import deque
import threading # Adicionado para concorrência

def run_threaded(job_func):
    """Executa uma função agendada em uma nova thread para não bloquear o loop principal."""
    job_thread = threading.Thread(target=job_func)
    job_thread.start()



cache_tarefas_enviadas = deque(maxlen=500)

def verificar_e_enviar_tarefas_de_grupo():
    """
    (VERSÃO CORRIGIDA COM CACHE ANTI-DUPLICAÇÃO)
    Verifica e envia tarefas de grupo, evitando envios repetidos no mesmo minuto.
    """
    agora_dt = datetime.now()
    agora_hm = agora_dt.strftime('%H:%M')

    chave_dia_atual = agora_dt.strftime('%Y-%m-%d')
    

    dia_python = agora_dt.weekday()
    dia_semana_sql = (dia_python + 1) % 7 + 1
    dia_mes = agora_dt.day

    # Busca tarefas no banco
    tarefas_para_disparar = database.buscar_tarefas_de_grupo_para_disparar(
        agora_hm, 
        str(dia_semana_sql), 
        str(dia_mes)
    )

    if not tarefas_para_disparar:
        return

    logger.info(f"[{agora_hm}] Encontradas {len(tarefas_para_disparar)} potenciais tarefas de grupo.")
    
    for tarefa in tarefas_para_disparar:
        atribuicao_id, titulo, pontos, nome_grupo, chat_id, *_ = tarefa

        # --- LÓGICA ANTI-DUPLICAÇÃO (CORRIGIDA) ---
        # Alteramos a chave para usar Título + Chat + Horário. 
        # Isso impede que tarefas duplicadas no banco (IDs diferentes, mesmo conteúdo) sejam enviadas duas vezes.
        assinatura_envio = (chat_id, titulo, agora_hm, chave_dia_atual)

        if assinatura_envio in cache_tarefas_enviadas:
            # Log silencioso para não poluir o terminal se houver muitas duplicatas
            # print(f"--> [ANTI-FLOOD] Tarefa '{titulo}' já enviada para este grupo neste horário. Ignorando.")
            continue
        
        # Se não está no cache, adiciona
        cache_tarefas_enviadas.append(assinatura_envio)
        # -----------------------------

        if not chat_id:
            logger.error(f"ERRO: O grupo '{nome_grupo}' não tem Chat ID cadastrado!")
            continue

        mensagem = (
            f"🚨 **Nova Missão para a Equipe!** 🚨\n\n"
            f"**Tarefa:** {titulo}\n"
            f"**Recompensa:** {pontos} pontos\n\n"
            "O primeiro a aceitar fica responsável pela entrega *de hoje*. Quem vai encarar?"
        )

        keyboard = [[InlineKeyboardButton("✅ Eu aceito o desafio!", callback_data=f"aceitar_tarefa_{atribuicao_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            notificador_telegram.enviar_mensagem_com_botao(chat_id, mensagem, reply_markup)
            print(f"--> SUCESSO: Missão '{titulo}' enviada para '{nome_grupo}' às {agora_hm}.")
        except Exception as e:
            print(f"--> ERRO AO ENVIAR no Telegram: {e}")

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

def verificar_e_delegar_tarefas_de_folga():
    """
    (VERSÃO V4 - COM SUPORTE A 6x1 E AFASTAMENTOS)
    Verifica folgas fixas, domingos de folga e afastamentos (férias/atestado).
    Agrega todas as tarefas desses ausentes e envia o 'Drop' (Boletim).
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🎲 Verificando Ausências (Folgas/Férias) para Drop...")
    
    hoje_dt = datetime.now()
    hoje_date = hoje_dt.date()
    
    # 1. Determina Dia da Semana (SQL Padrão: 1=Dom ... 7=Sab)
    dia_semana_sql = (hoje_dt.weekday() + 1) % 7 + 1
    
    # 2. Determina qual Domingo do Mês é hoje (se for domingo)
    ocorrencia_domingo = 0
    if dia_semana_sql == 1: # É Domingo
        # Divisão inteira do dia por 7 arredondada para cima dá a ocorrência (1º, 2º...)
        ocorrencia_domingo = (hoje_dt.day - 1) // 7 + 1

    funcionarios_ausentes = []
    
    # Busca TODOS os funcionários para checar as 3 condições
    todos_funcionarios = database.listar_funcionarios()
    
    for f in todos_funcionarios:
        motivo_ausencia = None
        
        # A. Folga Fixa Semanal (Ex: Toda Segunda)
        if f.DiaDeFolga == dia_semana_sql:
            motivo_ausencia = "Folga Semanal"
            
        # B. Folga de Domingo Específico (Escala 6x1)
        # Verifica se hoje é domingo E se o funcionário folga neste número de domingo (1, 2, etc)
        elif dia_semana_sql == 1 and hasattr(f, 'DomingoFolgaMensal') and f.DomingoFolgaMensal == ocorrencia_domingo:
            motivo_ausencia = f"Folga de Domingo ({ocorrencia_domingo}º)"
            
        # C. Período de Afastamento (Férias/Atestado)
        # Verifica se hoje está entre Inicio e Fim (inclusive)
        elif hasattr(f, 'DataInicioAfastamento') and f.DataInicioAfastamento and f.DataFimAfastamento:
            # Garante comparação segura de datas
            ini = f.DataInicioAfastamento
            fim = f.DataFimAfastamento
            if isinstance(ini, datetime): ini = ini.date()
            if isinstance(fim, datetime): fim = fim.date()
                
            if ini <= hoje_date <= fim:
                motivo_ausencia = "Férias/Atestado"

        if motivo_ausencia:
            # Adiciona atributo temporário para usar na mensagem
            f.MotivoLog = motivo_ausencia
            funcionarios_ausentes.append(f)

    if not funcionarios_ausentes:
        print("--> Ninguém de folga ou afastado hoje. Drop cancelado.")
        return

    # Dicionário para agrupar tarefas por ChatID de destino
    drop_por_grupo = {}

    for funcionario in funcionarios_ausentes:
        # Busca tarefas recorrentes agendadas para HOJE (dia da semana atual)
        # Nota: Mesmo em férias, pegamos o que ele faria 'hoje' se estivesse trabalhando
        tarefas_do_dia = database.buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario.FuncionarioID, dia_semana_sql)
        
        if not tarefas_do_dia: continue
        
        print(f"--> Processando ausência de {funcionario.NomeCompleto} ({funcionario.MotivoLog})...")

        for tarefa in tarefas_do_dia:
            # --- Lógica de Roteamento ---
            destinos = set()
            MAPA_ROTEAMENTO = {
                'cozinha': config.COZINHA_GROUP_CHAT_ID,
                'produção': config.COZINHA_GROUP_CHAT_ID,
                'atendimento': config.ATENDIMENTO_GROUP_CHAT_ID,
                'loja': config.ATENDIMENTO_GROUP_CHAT_ID,
            }

            # 1. Por Setor
            texto_primario = (tarefa.Setor or "").lower()
            encontrou = False
            for k, v in MAPA_ROTEAMENTO.items():
                if k in texto_primario:
                    destinos.add(v); encontrou = True; break
            
            # 2. Por Cargo
            if not encontrou:
                texto_secundario = (funcionario.Cargo or "").lower()
                for k, v in MAPA_ROTEAMENTO.items():
                    if k in texto_secundario:
                        destinos.add(v); encontrou = True; break
            
            # 3. Fallback
            if not encontrou: destinos.add(config.FOLGA_GROUP_CHAT_ID)
            
            # Adiciona ao Drop
            for chat_id in destinos:
                if chat_id not in drop_por_grupo: drop_por_grupo[chat_id] = []
                drop_por_grupo[chat_id].append({'tarefa': tarefa, 'origem': funcionario.NomeCompleto, 'motivo': funcionario.MotivoLog})

    # --- Envio dos Drops ---
    for chat_id, itens in drop_por_grupo.items():
        if not itens: continue
        
        qtd = len(itens)
        mensagem = (
            f"⚡ **DROP DE TAREFAS LIBERADO!** ⚡\n\n"
            f"Equipe reduzida hoje (Folgas/Férias). Temos **{qtd} missões extras** disponíveis!\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        )
        keyboard = []
        for i, item in enumerate(itens):
            t = item['tarefa']
            origem = item['origem'].split()[0]
            # Adiciona motivo curto na mensagem (ex: Ana (Férias))
            tag_motivo = "🌴" if "Férias" in item['motivo'] else "🏠"
            
            mensagem += f"{i+1}️⃣ **{t.Titulo}**\n     └ {tag_motivo} *{origem}* |  💰 *{t.Pontos} pts*\n\n"
            
            callback = f"aceitar_folga_{t.TarefaID}"
            keyboard.append([InlineKeyboardButton(f"🚀 Pegar Missão {i+1}", callback_data=callback)])

        mensagem += "👇 **Ajude a equipe e ganhe pontos extras:**"
        try:
            notificador_telegram.enviar_mensagem_com_botao(chat_id, mensagem, InlineKeyboardMarkup(keyboard))
            print(f"--> Drop enviado para grupo {chat_id}.")
        except Exception as e:
            print(f"--> Erro envio Drop: {e}")
                        
def executar_fechamento_mensal():
    """
    Executa o fechamento separado por setores (Cozinha e Loja).
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🏆 INICIANDO ROTINA DE FECHAMENTO MENSAL! 🏆")

    hoje = date.today()
    fim_mes_passado = hoje.replace(day=1) - timedelta(days=1)
    ano_fechamento = fim_mes_passado.year
    mes_fechamento = fim_mes_passado.month

    # Verificação de segurança
    if database.verificar_se_fechamento_ja_rodou(ano_fechamento, mes_fechamento):
        print(f"--> ATENÇÃO: O fechamento para {mes_fechamento}/{ano_fechamento} já foi executado.")
        return

    premios_cozinha = [
        "🏆 1 Pote 2L + Cobertura + Casquinhas (Kit Família)",
        "🥈 1 Taça Especial do Cardápio (Para comer na loja)",
        "🥉 1 Milkshake Grande ou Açaí 500ml"
    ]

    premios_loja = [
        "🏆 1 Torta de Sorvete inteira (ou Pote Especial)",
        "🥈 1 Fondue ou Taça Especial",
        "🥉 1 Pote Pop para levar para casa"
]
    # ==============================================================================

    def processar_setor(nome_setor, filtro_db, lista_premios):
        print(f"--> Processando ranking: {nome_setor}...")
        # Calcula ranking filtrado
        ranking = database.calcular_ranking_desempenho(data_final_calculo=fim_mes_passado, setor_filtro=filtro_db)

        if not ranking:
            print(f"   -> Sem dados para {nome_setor}.")
            return

        # Salva no histórico
        database.salvar_historico_ranking(ranking)

        # Monta mensagem para os Gestores
        texto_gestores = f"🎉 **Fechamento {nome_setor}: Pódio Final!** 🎉\n\n"
        vencedores_para_notificar = []

        for i, vencedor in enumerate(ranking[:len(lista_premios)]):
            premio = lista_premios[i]
            texto_gestores += f"{i+1}º: {vencedor['NomeCompleto']} ({vencedor['Desempenho']}%)\n   - Prêmio: {premio}\n"
            vencedores_para_notificar.append({'dados': vencedor, 'premio': premio, 'posicao': i+1})

        # Envia para o Grupo de Gestão
        notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, texto_gestores)

        # Envia Mensagem Privada para os Vencedores
        for vencedor in vencedores_para_notificar:
            dados = vencedor['dados']
            # Busca o ChatID atualizado
            chat_id = database.buscar_funcionario_por_id(dados['FuncionarioID']).ChatIDTelegram
            if chat_id:
                texto_vencedor = (f"🎉🎊 **PARABÉNS, {dados['NomeCompleto']}!** 🎊🎉\n\n"
                                  f"Você foi destaque no ranking de **{nome_setor}**!\n\n"
                                  f"Sua Posição: **{vencedor['posicao']}º Lugar**\n"
                                  f"Sua Recompensa: **{vencedor['premio']}**\n\n"
                                  "Procure a gestão para retirar seu prêmio!")
                notificador_telegram.enviar_mensagem(chat_id, texto_vencedor)

    # --- EXECUTA PARA OS DOIS SETORES ---
    processar_setor("Cozinha", "Cozinha", premios_cozinha)
    processar_setor("Atendimento/Loja", "Loja", premios_loja)

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

def processar_downloads_pendentes_sync():
    """Busca por entregas sem foto baixada, tenta fazer o download e envia notificação ao gestor se necessário."""
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando downloads de fotos pendentes...")

    try: # Adiciona um try geral para buscar_entregas_para_download
        entregas_para_baixar = database.buscar_entregas_para_download()
    except Exception as db_err:
        logger.error(f"Erro ao buscar entregas para download: {db_err}", exc_info=True)
        return # Interrompe a execução desta vez se não conseguir buscar

    if not entregas_para_baixar:
        logger.debug("--> Nenhuma foto pendente para download.")
        return

    logger.info(f"--> Encontradas {len(entregas_para_baixar)} fotos para baixar.")

    token = config.TELEGRAM_TOKEN

    for entrega in entregas_para_baixar:
        local_file_path = None
        download_sucesso = False # Flag para controlar se o download funcionou

        # --- Bloco de Download da Foto ---
        try:
            logger.info(f"--> Baixando foto para EntregaID: {entrega.EntregaID} (FileID: {entrega.FileIDTelegram})...")

            get_file_url = f"https://api.telegram.org/bot{token}/getFile"
            params = {'file_id': entrega.FileIDTelegram}
            response_file_info = requests.get(get_file_url, params=params, timeout=30)
            response_file_info.raise_for_status()
            file_info = response_file_info.json()

            if not file_info.get('ok'):
                logger.error(f"--> FALHA API getFile para EntregaID {entrega.EntregaID}: {file_info.get('description')}")
                continue

            telegram_file_path = file_info['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{token}/{telegram_file_path}"
            response_download = requests.get(download_url, stream=True, timeout=60)
            response_download.raise_for_status()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pasta_entregas = 'entregas'
            if not os.path.exists(pasta_entregas):
                try:
                    os.makedirs(pasta_entregas)
                    logger.info(f"Pasta '{pasta_entregas}' criada.")
                except OSError as e:
                    logger.error(f"Erro ao criar pasta '{pasta_entregas}': {e}", exc_info=True)
                    continue

            local_file_path = os.path.join(pasta_entregas, f'{timestamp}_{entrega.EntregaID}.jpg')

            with open(local_file_path, 'wb') as f:
                for chunk in response_download.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Marca que o download foi bem-sucedido
            download_sucesso = True
            logger.info(f"--> Download SUCESSO! Foto da EntregaID {entrega.EntregaID} salva temporariamente em {local_file_path}")

        except requests.exceptions.Timeout:
            logger.warning(f"--> TIMEOUT ao tentar baixar foto da EntregaID {entrega.EntregaID}. Tentaremos novamente.")
            continue # Pula para a próxima entrega nesta iteração
        except requests.exceptions.RequestException as req_err:
            logger.error(f"--> FALHA DE REDE ao baixar foto da EntregaID {entrega.EntregaID}. Erro: {req_err}. Tentaremos novamente.")
            continue # Pula para a próxima entrega nesta iteração
        except Exception as e:
            logger.error(f"--> FALHA GERAL ao baixar foto da EntregaID {entrega.EntregaID}. Erro: {e}. Tentaremos novamente.", exc_info=True)
            continue # Pula para a próxima entrega nesta iteração

        # --- Bloco de Atualização do Banco e Notificação (Só executa se o download funcionou) ---
        if download_sucesso and local_file_path:
            try:
                # 1. Finaliza o registro no banco com o caminho da foto
                database.finalizar_registro_entrega(entrega.EntregaID, local_file_path)
                logger.info(f"--> Registro da EntregaID {entrega.EntregaID} finalizado no banco com path: {local_file_path}")

                # 2. Verifica e Reenvia Notificação ao Gestor (Lógica com Dupla Verificação)
                try:
                    # Primeira verificação da flag
                    notificacao_ja_enviada = database.verificar_status_notificacao_gestor(entrega.EntregaID)

                    if not notificacao_ja_enviada:
                        # Segunda verificação da flag (imediatamente antes de enviar)
                        logger.debug(f"--> Primeira verificação indicou notificação pendente para EntregaID {entrega.EntregaID}. Verificando novamente...")
                        notificacao_ainda_pendente = not database.verificar_status_notificacao_gestor(entrega.EntregaID)

                        if notificacao_ainda_pendente:
                            logger.info(f"--> Notificação para Gestor da EntregaID {entrega.EntregaID} AINDA pendente. Tentando enviar via agendador...")

                            detalhes_entrega_para_notif = database.buscar_detalhes_da_entrega(entrega.EntregaID)

                            if detalhes_entrega_para_notif and config.GESTOR_GROUP_CHAT_ID:

                            # --- CORREÇÃO APLICADA AQUI ---
                            # Verifica se o campo DataEnvio (adicionado na Correção A) existe e o formata
                                if detalhes_entrega_para_notif.DataEnvio:
                                    data_envio_original_str = detalhes_entrega_para_notif.DataEnvio.strftime('%d/%m/%Y %H:%M:%S')
                                else:
                                    data_envio_original_str = "(data indisponível)"
                                # --- FIM DA CORREÇÃO ---

                                legenda = (f"<b>Nova Entrega para Validação (Via Agendador)</b>\n\n"
                                        f"👤 <b>Funcionário:</b> {detalhes_entrega_para_notif.NomeCompleto}\n"
                                        f"📝 <b>Tarefa:</b> {detalhes_entrega_para_notif.Titulo} ({detalhes_entrega_para_notif.Pontos} pts)\n"
                                        f"🗓️ <b>Data Envio Original:</b> {data_envio_original_str}\n"
                                        f"📦 <b>Entrega ID:</b> {entrega.EntregaID}")
                            
                                keyboard = [[
                                    InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_gestor_{entrega.EntregaID}"),
                                    InlineKeyboardButton("❌ Reprovar", callback_data=f"reprovar_gestor_{entrega.EntregaID}")
                                ]]
                                reply_markup = InlineKeyboardMarkup(keyboard)

                                # Envia a foto recém-baixada
                                resposta_api = notificador_telegram.enviar_foto_com_botoes(
                                    config.GESTOR_GROUP_CHAT_ID,
                                    local_file_path, # Usa o caminho da foto baixada
                                    legenda,
                                    reply_markup,
                                    parse_mode='HTML'
                                )

                                # Se o envio pelo agendador funcionou, marca a flag
                                if resposta_api and resposta_api.get('ok'):
                                    database.marcar_notificacao_gestor_enviada(entrega.EntregaID)
                                    logger.info(f"--> Notificação para Gestor da EntregaID {entrega.EntregaID} enviada com sucesso pelo agendador.")
                                else:
                                    logger.error(f"--> Falha ao enviar notificação para Gestor (EntregaID {entrega.EntregaID}) pelo agendador. Resposta API: {resposta_api}")
                            else:
                                logger.warning(f"--> Não foi possível obter detalhes completos ou GESTOR_GROUP_CHAT_ID para notificar sobre EntregaID {entrega.EntregaID}.")
                        else:
                            logger.info(f"--> Segunda verificação: Notificação para Gestor da EntregaID {entrega.EntregaID} já foi enviada. Fallback NÃO enviado.")
                    else:
                        logger.debug(f"--> Notificação para Gestor da EntregaID {entrega.EntregaID} já havia sido enviada anteriormente (verificado na primeira checagem).")

                except Exception as check_notify_err:
                    logger.error(f"--> Erro ao verificar/reenviar notificação gestor para EntregaID {entrega.EntregaID}: {check_notify_err}", exc_info=True)

            except Exception as db_update_err:
                 logger.error(f"--> FALHA GERAL ao finalizar registro ou notificar para EntregaID {entrega.EntregaID}. Erro: {db_update_err}. Tentaremos novamente.", exc_info=True)

def processar_downloads_notas_fiscais():
    """Busca por NFs sem foto baixada, tenta fazer o download e salva o caminho."""
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando downloads de NOTAS FISCAIS pendentes...")

    try:
        notas_para_baixar = database.buscar_notas_para_download()
    except Exception as db_err:
        logger.error(f"Erro ao buscar Notas Fiscais para download: {db_err}", exc_info=True)
        return

    if not notas_para_baixar:
        logger.debug("--> Nenhuma Nota Fiscal pendente para download.")
        return

    logger.info(f"--> Encontradas {len(notas_para_baixar)} Notas Fiscais para baixar.")
    token = config.TELEGRAM_TOKEN
    pasta_notas_fiscais = 'notas_fiscais' # Pasta para salvar as NFs

    if not os.path.exists(pasta_notas_fiscais):
        try:
            os.makedirs(pasta_notas_fiscais)
            logger.info(f"Pasta '{pasta_notas_fiscais}' criada.")
        except OSError as e:
            logger.error(f"Erro ao criar pasta '{pasta_notas_fiscais}': {e}", exc_info=True)
            return

    for nf in notas_para_baixar:
        local_file_path = None
        download_sucesso = False
        nf_id = nf.NotaFiscalID
        file_id = nf.FileIDTelegram

        try:
            logger.info(f"--> Baixando foto para NotaFiscalID: {nf_id} (FileID: {file_id})...")
            get_file_url = f"https://api.telegram.org/bot{token}/getFile"
            params = {'file_id': file_id}
            response_file_info = requests.get(get_file_url, params=params, timeout=30)
            response_file_info.raise_for_status()
            file_info = response_file_info.json()

            if not file_info.get('ok'):
                logger.error(f"--> FALHA API getFile para NotaFiscalID {nf_id}: {file_info.get('description')}")
                continue

            telegram_file_path = file_info['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{token}/{telegram_file_path}"
            response_download = requests.get(download_url, stream=True, timeout=60)
            response_download.raise_for_status()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            local_file_path = os.path.join(pasta_notas_fiscais, f'NF_{timestamp}_{nf_id}.jpg')

            with open(local_file_path, 'wb') as f:
                for chunk in response_download.iter_content(chunk_size=8192):
                    f.write(chunk)

            download_sucesso = True
            logger.info(f"--> Download SUCESSO! Foto da NotaFiscalID {nf_id} salva em {local_file_path}")

        except requests.exceptions.RequestException as req_err:
            logger.warning(f"--> Erro de REDE ao baixar NF {nf_id}: {req_err}")
            continue # Tenta na próxima execução
        except Exception as e:
            logger.error(f"--> ERRO DE LÓGICA/ARQUIVO ao baixar NF {nf_id}: {e}", exc_info=True)
            continue # Pula para a próxima NF para não travar o loop

        # Bloco de Persistência (Separado para clareza)
        if download_sucesso and local_file_path:
            try:
                database.finalizar_download_nota_fiscal(nf_id, local_file_path)
                logger.info(f"--> Registro da NotaFiscalID {nf_id} finalizado no banco.")
            except Exception as db_err:
                logger.error(f"--> ERRO DE BANCO ao salvar caminho da NF {nf_id}: {db_err}", exc_info=True)
                # Não removemos o arquivo, pois o download foi sucesso. O próximo loop tentará baixar e sobrescrever, ou podemos implementar lógica de retry.

if __name__ == "__main__":
    print("--- 🤖 Robô Agendador 2.0 Iniciado 🤖 ---")
    print("O sistema verificará a cada minuto e o fechamento mensal às 08:00.")

    schedule.every(1).minutes.do(verificar_inicio_jornada)
    schedule.every(1).minutes.do(verificar_lembretes_intermediarios)
    schedule.every(1).minutes.do(verificar_fim_jornada)
    schedule.every(30).seconds.do(verificar_e_enviar_tarefas_de_grupo)

    schedule.every().day.at("08:00").do(verificar_e_executar_fechamento)
    schedule.every().day.at("09:05").do(verificar_e_delegar_tarefas_de_folga)
    schedule.every().day.at("09:00").do(verificar_e_enviar_lembretes_comunicados)

    # CORREÇÃO: Downloads agora rodam em threads separadas para não bloquear o agendador
    schedule.every(1).minutes.do(run_threaded, processar_downloads_pendentes_sync)
    schedule.every(1).minutes.do(run_threaded, processar_downloads_notas_fiscais)


    while True:
        schedule.run_pending()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Robô Ativo. Verificando agendamentos...", end='\r')
        time.sleep(1)

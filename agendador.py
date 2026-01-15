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

import unicodedata

# --- CONTROLE DE CONCORRÊNCIA ---
# Semáforo para limitar downloads simultâneos (máx 3 threads baixando ao mesmo tempo)
download_semaphore = threading.BoundedSemaphore(value=3)

# --- MAPA DE ROTEAMENTO ROBUSTO ---
# Centraliza a lógica de para onde vai cada drop
MAPA_SETOR_GRUPO = {
    'cozinha': config.COZINHA_GROUP_CHAT_ID,
    'producao': config.COZINHA_GROUP_CHAT_ID,
    'produção': config.COZINHA_GROUP_CHAT_ID,
    'estoque': config.COZINHA_GROUP_CHAT_ID,

    'atendimento': config.ATENDIMENTO_GROUP_CHAT_ID,
    'loja': config.ATENDIMENTO_GROUP_CHAT_ID,
    'caixa': config.ATENDIMENTO_GROUP_CHAT_ID,
    'salao': config.ATENDIMENTO_GROUP_CHAT_ID,
    'salão': config.ATENDIMENTO_GROUP_CHAT_ID,
}

def normalizar_texto(texto):
    """Remove acentos e coloca em minúsculas para comparação segura."""
    if not texto: return ""
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII').lower()

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
    (VERSÃO V5 - CORRIGIDA E ROBUSTA)
    Verifica folgas fixas, domingos de folga e afastamentos (férias/atestado).
    Agrega todas as tarefas desses ausentes e envia o 'Drop' (Boletim).
    """
    logger.info(f"🎲 Verificando Ausências (Folgas/Férias) para Drop...")
    
    hoje_dt = datetime.now()
    hoje_date = hoje_dt.date()
    
    # 1. Determina Dia da Semana (SQL Padrão: 1=Dom ... 7=Sab)
    dia_semana_sql = (hoje_dt.weekday() + 1) % 7 + 1
    
    # 2. Determina qual Domingo do Mês é hoje (se for domingo)
    ocorrencia_domingo = 0
    if dia_semana_sql == 1: # É Domingo
        ocorrencia_domingo = (hoje_dt.day - 1) // 7 + 1

    funcionarios_ausentes = []
    
    try:
        todos_funcionarios = database.listar_funcionarios()
    except Exception as e:
        logger.error(f"Erro ao listar funcionários para Drop: {e}")
        return

    for f in todos_funcionarios:
        motivo_ausencia = None

        # A. Período de Afastamento (Férias/Atestado) - TRATAMENTO ROBUSTO DE DATA
        try:
            data_ini_raw = getattr(f, 'DataInicioAfastamento', None)
            data_fim_raw = getattr(f, 'DataFimAfastamento', None)

            if data_ini_raw and data_fim_raw:
                # Normalização forçada para datetime.date
                ini = data_ini_raw.date() if isinstance(data_ini_raw, datetime) else data_ini_raw
                fim = data_fim_raw.date() if isinstance(data_fim_raw, datetime) else data_fim_raw
                
                # Caso venha como string (raro, mas possível via drivers antigos)
                if isinstance(ini, str): ini = datetime.strptime(ini[:10], '%Y-%m-%d').date()
                if isinstance(fim, str): fim = datetime.strptime(fim[:10], '%Y-%m-%d').date()

                if ini <= hoje_date <= fim:
                    motivo_ausencia = "Férias/Atestado"
                    logger.info(f"--> Ausência detectada: {f.NomeCompleto} (Período: {ini} a {fim})")
        except Exception as e_date:
            logger.error(f"Falha ao processar datas de {f.NomeCompleto}: {e_date}")

        # B. Folga Fixa Semanal
        if not motivo_ausencia and f.DiaDeFolga == dia_semana_sql:
            motivo_ausencia = "Folga Semanal"

        # C. Folga de Domingo Específico (6x1)
        if not motivo_ausencia and dia_semana_sql == 1:
            # Verifica se o campo existe e tem valor
            dom_folga = getattr(f, 'DomingoFolgaMensal', 0)
            if dom_folga and dom_folga == ocorrencia_domingo:
                motivo_ausencia = f"Folga de Domingo ({ocorrencia_domingo}º)"

        if motivo_ausencia:            
            f.MotivoLog = motivo_ausencia
            funcionarios_ausentes.append(f)

    if not funcionarios_ausentes:
        logger.info("--> Ninguém de folga ou afastado hoje. Drop cancelado.")
        return

    # Dicionário para agrupar tarefas por ChatID de destino
    drop_por_grupo = {}

    for funcionario in funcionarios_ausentes:
        dia_semana_str = str(dia_semana_sql)
        # Busca tarefas recorrentes que seriam para HOJE
        tarefas_do_dia = database.buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario.FuncionarioID, dia_semana_str)
        
        if not tarefas_do_dia:
            logger.info(f"--> {funcionario.NomeCompleto} está ausente, mas não tinha tarefas agendadas para hoje.")
            continue
        
        logger.info(f"--> Processando {len(tarefas_do_dia)} tarefas de {funcionario.NomeCompleto} ({funcionario.MotivoLog})...")

        for tarefa in tarefas_do_dia:
            chat_destino = config.FOLGA_GROUP_CHAT_ID # Padrão (Fallback)

            # Normalização para roteamento
            setor_t = normalizar_texto(tarefa.Setor or "")
            cargo_f = normalizar_texto(funcionario.Cargo or "")

            encontrou = False

            # 1. Roteamento por Setor da Tarefa
            for chave, chat_id in MAPA_SETOR_GRUPO.items():
                if chave in setor_t:
                    chat_destino = chat_id; encontrou = True; break

            # 2. Roteamento por Cargo do Funcionário
            if not encontrou:
                for chave, chat_id in MAPA_SETOR_GRUPO.items():
                    if chave in cargo_f:
                        chat_destino = chat_id; encontrou = True; break

            if chat_destino not in drop_por_grupo: drop_por_grupo[chat_destino] = []
            
            # Adiciona item ao grupo
            drop_por_grupo[chat_destino].append({
                'tarefa': tarefa, 
                'origem': funcionario.NomeCompleto, 
                'motivo': getattr(funcionario, 'MotivoLog', 'Ausência')
            })

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
            origem_nome = item['origem'].split()[0]
            motivo_desc = item['motivo']
            
            tag_motivo = "🌴" if "Férias" in motivo_desc or "Atestado" in motivo_desc else "🏠"
            
            mensagem += f"{i+1}️⃣ **{t.Titulo}**\n     └ {tag_motivo} *{origem_nome}* |  💰 *{t.Pontos} pts*\n\n"
            
            callback = f"aceitar_folga_{t.TarefaID}"
            keyboard.append([InlineKeyboardButton(f"🚀 Pegar Missão {i+1}", callback_data=callback)])

        mensagem += "👇 **Ajude a equipe e ganhe pontos extras:**"
        try:
            notificador_telegram.enviar_mensagem_com_botao(chat_id, mensagem, InlineKeyboardMarkup(keyboard))
            logger.info(f"--> Drop enviado com sucesso para grupo {chat_id} ({qtd} tarefas).")
        except Exception as e:
            logger.error(f"--> Erro crítico ao enviar Drop para grupo {chat_id}: {e}")
                                    
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
    """
    (VERSÃO CORRIGIDA: SEMÁFORO E ATOMICIDADE)
    Baixa evidências com controle de concorrência e limpeza em caso de falha.
    """
    # 1. Tenta adquirir o semáforo. Se estiver cheio, retorna imediatamente (não bloqueia a thread).
    if not download_semaphore.acquire(blocking=False):
        logger.warning("--> Limite de downloads simultâneos atingido. Tentando na próxima rodada.")
        return

    try:
        entregas = database.buscar_entregas_para_download()
        if not entregas: return

        logger.info(f"--> Baixando {len(entregas)} evidências pendentes...")
        token = config.TELEGRAM_TOKEN
        pasta = 'entregas'
        if not os.path.exists(pasta): os.makedirs(pasta)

        for entrega in entregas:
            # --- CORREÇÃO 4: PREVENÇÃO DE ZOMBIE FILES ---
            local_path = None
            try:
                # Busca info do arquivo
                r_info = requests.get(f"https://api.telegram.org/bot{token}/getFile?file_id={entrega.FileIDTelegram}", timeout=10)
                if not r_info.json().get('ok'): continue

                remoto_path = r_info.json()['result']['file_path']
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                local_path = os.path.join(pasta, f'{ts}_{entrega.EntregaID}.jpg')

                # Baixa conteúdo
                r_file = requests.get(f"https://api.telegram.org/file/bot{token}/{remoto_path}", stream=True, timeout=30)
                if r_file.status_code == 200:
                    with open(local_path, 'wb') as f:
                        for chunk in r_file.iter_content(8192): f.write(chunk)

                    # TENTA atualizar o banco
                    try:
                        database.finalizar_registro_entrega(entrega.EntregaID, local_path)
                        logger.info(f"--> Sucesso: Entrega {entrega.EntregaID} salva em {local_path}")

                        # Notificação ao Gestor (apenas se salvou no banco)
                        if not database.verificar_status_notificacao_gestor(entrega.EntregaID):
                            detalhes = database.buscar_detalhes_da_entrega(entrega.EntregaID)
                            if detalhes and config.GESTOR_GROUP_CHAT_ID:
                                caption = (f"<b>Nova Entrega</b>\n👤 {detalhes.NomeCompleto}\n📝 {detalhes.Titulo}\n📦 ID: {entrega.EntregaID}")
                                kb = [[InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_gestor_{entrega.EntregaID}"),
                                       InlineKeyboardButton("❌ Reprovar", callback_data=f"reprovar_gestor_{entrega.EntregaID}")]]
                                resp = notificador_telegram.enviar_foto_com_botoes(config.GESTOR_GROUP_CHAT_ID, local_path, caption, InlineKeyboardMarkup(kb), 'HTML')
                                if resp and resp.get('ok'): database.marcar_notificacao_gestor_enviada(entrega.EntregaID)

                    except Exception as e_db:
                        # FALHA NO BANCO: Apaga o arquivo para não virar zumbi
                        logger.error(f"Erro BD ao salvar entrega {entrega.EntregaID}. Removendo arquivo.")
                        if os.path.exists(local_path): os.remove(local_path)
                        raise e_db # Relança para o log externo

            except Exception as e:
                logger.error(f"Erro download entrega {entrega.EntregaID}: {e}")
                # Limpeza de segurança final
                if local_path and os.path.exists(local_path) and not database.buscar_detalhes_da_entrega(entrega.EntregaID).PathFotoEvidencia:
                     os.remove(local_path)

    finally:
        # Sempre libera o semáforo
        download_semaphore.release()

def processar_downloads_notas_fiscais():
    """Baixa NFs com controle de concorrência."""
    if not download_semaphore.acquire(blocking=False): return

    try:
        nfs = database.buscar_notas_para_download()
        if not nfs: return

        token = config.TELEGRAM_TOKEN
        pasta = 'notas_fiscais'
        if not os.path.exists(pasta): os.makedirs(pasta)

        for nf in nfs:
            local_path = None
            try:
                r_info = requests.get(f"https://api.telegram.org/bot{token}/getFile?file_id={nf.FileIDTelegram}", timeout=10)
                if not r_info.json().get('ok'): continue

                remoto = r_info.json()['result']['file_path']
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                local_path = os.path.join(pasta, f'NF_{ts}_{nf.NotaFiscalID}.jpg')

                r_file = requests.get(f"https://api.telegram.org/file/bot{token}/{remoto}", stream=True, timeout=30)
                if r_file.status_code == 200:
                    with open(local_path, 'wb') as f:
                        for chunk in r_file.iter_content(8192): f.write(chunk)

                    try:
                        database.finalizar_download_nota_fiscal(nf.NotaFiscalID, local_path)
                    except Exception:
                        if os.path.exists(local_path): os.remove(local_path)
                        raise

            except Exception as e:
                logger.error(f"Erro download NF {nf.NotaFiscalID}: {e}")
                if local_path and os.path.exists(local_path): os.remove(local_path)
    finally:
        download_semaphore.release()


def forcar_drop_funcionario_especifico(funcionario_id):
    """
    Função manual para gestores dispararem o Drop de um funcionário específico
    que faltou de última hora (fora do horário automático).
    """
    print(f"--> Iniciando Drop Manual para FuncionarioID: {funcionario_id}...")
    
    # 1. Busca dados do funcionário
    funcionario = database.buscar_funcionario_por_id(funcionario_id)
    if not funcionario:
        return False, "Funcionário não encontrado."

    hoje_dt = datetime.now()
    # SQL Padrão: 1=Dom ... 7=Sab
    dia_semana_sql = (hoje_dt.weekday() + 1) % 7 + 1

    # 2. Busca tarefas de hoje
    tarefas_do_dia = database.buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario_id, dia_semana_sql)
    
    if not tarefas_do_dia:
        return False, f"O funcionário {funcionario.NomeCompleto} não tem tarefas agendadas para hoje ({hoje_dt.strftime('%d/%m')})."

    # 3. Define o Grupo de Destino (Lógica de Roteamento)
    chat_destino = config.FOLGA_GROUP_CHAT_ID # Padrão
    
    # Tenta rotear pelo Cargo
    cargo_f = normalizar_texto(funcionario.Cargo or "")
    encontrou_grupo = False
    
    for chave, chat_id in MAPA_SETOR_GRUPO.items():
        if chave in cargo_f:
            chat_destino = chat_id
            encontrou_grupo = True
            break
            
    # Se não achou pelo cargo, tenta pelo setor da primeira tarefa (heurística)
    if not encontrou_grupo and tarefas_do_dia:
        setor_t = normalizar_texto(tarefas_do_dia[0].Setor or "")
        for chave, chat_id in MAPA_SETOR_GRUPO.items():
            if chave in setor_t:
                chat_destino = chat_id
                break

    # 4. Monta e Envia a Mensagem
    qtd = len(tarefas_do_dia)
    mensagem = (
        f"🚨 **DROP DE TAREFAS (AUSÊNCIA IMPREVISTA)** 🚨\n\n"
        f"O colaborador **{funcionario.NomeCompleto}** não poderá comparecer/continuar hoje.\n"
        f"Temos **{qtd} missões** que precisam ser cobertas!\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    
    keyboard = []
    for i, t in enumerate(tarefas_do_dia):
        mensagem += f"{i+1}️⃣ **{t.Titulo}**\n     └ 💰 *{t.Pontos} pts*\n\n"
        callback = f"aceitar_folga_{t.TarefaID}"
        keyboard.append([InlineKeyboardButton(f"🚀 Assumir Missão {i+1}", callback_data=callback)])

    mensagem += "👇 **Quem pode cobrir e ganhar esses pontos?**"

    try:
        notificador_telegram.enviar_mensagem_com_botao(chat_destino, mensagem, InlineKeyboardMarkup(keyboard))
        print(f"--> Drop manual enviado para grupo {chat_destino}.")
        return True, f"Drop enviado com sucesso para o grupo (ChatID: {chat_destino})!"
    except Exception as e:
        print(f"--> Erro envio Drop Manual: {e}")
        return False, f"Erro ao enviar para o Telegram: {e}"
        
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

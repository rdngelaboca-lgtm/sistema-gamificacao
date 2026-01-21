# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING ===================================
# ==============================================================================
import logging
import logging.handlers
import sys
import os 
import notificador_whatsapp 
import random 

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
        logger.info(f"Pasta de logs criada em: {log_dir}") # logger.info inicial para confirmar criação
    except OSError as e:
        logger.info(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
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
from datetime import datetime, date, timedelta
import locale
import re
from itertools import groupby

try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    logger.info("Locale pt_BR.UTF-8 não encontrado. Usando o padrão do sistema.")

def formatar_data_pt_br(dt_obj, formato_str):
    """Uma função 'tradutora' para garantir que as datas saiam em português."""
    dias = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
    meses = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]
    
    data_formatada = dt_obj.strftime(formato_str)
    data_formatada = data_formatada.replace(dt_obj.strftime('%A'), dias[dt_obj.weekday()])
    data_formatada = data_formatada.replace(dt_obj.strftime('%B'), meses[dt_obj.month - 1])
    return data_formatada

def criar_link_whatsapp(telefone):
    """Limpa o número de telefone e cria um link 'wa.me'."""
    if not telefone or not telefone.strip():
        return None, None
    numeros = re.sub(r'\D', '', telefone)
    if len(numeros) <= 11:
        numeros = "55" + numeros
    link = f"https://wa.me/{numeros}"
    return telefone, link


# Em agendador_lembretes.py, adicione esta função
def enviar_lembretes_hoje():
    """Busca os agendamentos de HOJE e envia um resumo para o grupo."""
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos de HOJE...")

    hoje = date.today()
    agendamentos_de_hoje = database.buscar_agendamentos_para_periodo(hoje, hoje)
    data_formatada = formatar_data_pt_br(hoje, '%A, %d de %B')

    if not agendamentos_de_hoje:
        logger.info("--> Nenhum agendamento para hoje. Nenhuma mensagem enviada.")
        return
    else:
        mensagem = f"🔔 **Agenda de Hoje ({data_formatada})** 🔔\n"
        # ... (Lógica de formatação da mensagem)
        for i, ag in enumerate(agendamentos_de_hoje):
            hora_formatada = ag.DataEvento.strftime('%H:%M')
            mensagem += f"\n🔹 **{ag.TipoEvento}**\n"
            mensagem += f"  - ⏰ **{hora_formatada}**\n"
            mensagem += f"  - 👤 **Cliente:** {ag.NomeCliente}\n"
            telefone_limpo, link_wpp = criar_link_whatsapp(ag.TelefoneCliente)
            if telefone_limpo:
                mensagem += f"  - 📞 **Telefone:** [{telefone_limpo}]({link_wpp})\n"
            if ag.CPFCliente and ag.CPFCliente.strip():
                mensagem += f"  - 📄 **CPF:** {ag.CPFCliente.strip()}\n"
            status_pag = "PAGO" if ag.StatusPagamento == "Pago" else "RECEBER (Pendente)"
            mensagem += f"  - 💰 **Pagamento:** **{status_pag}**\n"
            if ag.Observacoes and ag.Observacoes.strip():
                mensagem += "  - 📝 **Observações:**\n"
                for linha in ag.Observacoes.strip().splitlines():
                    mensagem += f"    > _{linha.strip()}_\n"
            if i < len(agendamentos_de_hoje) - 1:
                mensagem += "\n`- - - - - - - - - - - - - - - - -`\n"

    notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    logger.info("--> Lembrete de HOJE enviado com sucesso!")


def enviar_lembretes_diarios():
    """Busca os agendamentos de AMANHÃ e envia um resumo completo."""
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos de amanhã...")
    amanha = date.today() + timedelta(days=1)
    agendamentos_de_amanha = database.buscar_agendamentos_para_periodo(amanha, amanha)
    data_formatada = formatar_data_pt_br(amanha, '%A, %d de %B')

    if not agendamentos_de_amanha:
        mensagem = f"🗓️ **Agenda para Amanhã ({data_formatada})** 🗓️\n\nNenhum agendamento encontrado. ✅"
    else:
        mensagem = f"📢 **Lembretes para Amanhã ({data_formatada})** 📢\n"
        for i, ag in enumerate(agendamentos_de_amanha):
            hora_formatada = ag.DataEvento.strftime('%H:%M')
            mensagem += f"\n🔹 **{ag.TipoEvento}**\n"
            mensagem += f"  - ⏰ **{hora_formatada}**\n"
            mensagem += f"  - 👤 **Cliente:** {ag.NomeCliente}\n"
            
            telefone_limpo, link_wpp = criar_link_whatsapp(ag.TelefoneCliente)
            if telefone_limpo:
                mensagem += f"  - 📞 **Telefone:** [{telefone_limpo}]({link_wpp})\n"
            if ag.CPFCliente and ag.CPFCliente.strip():
                mensagem += f"  - 📄 **CPF:** {ag.CPFCliente.strip()}\n"
            status_pag = "PAGO" if ag.StatusPagamento == "Pago" else "RECEBER (Pendente)"
            mensagem += f"  - 💰 **Pagamento:** **{status_pag}**\n"

            if ag.Observacoes and ag.Observacoes.strip():
                mensagem += "  - 📝 **Observações:**\n"
                for linha in ag.Observacoes.strip().splitlines():
                    mensagem += f"    > _{linha.strip()}_\n"
            
            if i < len(agendamentos_de_amanha) - 1:
                mensagem += "\n`- - - - - - - - - - - - - - - - -`\n"
    notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    logger.info("--> Lembrete diário enviado com sucesso!")


# Em agendador_lembretes.py
def enviar_lembretes_semanais():
    """Busca os agendamentos da SEMANA ATUAL (que se inicia) e envia um resumo completo."""
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos da SEMANA ATUAL...")
    hoje = date.today()
    # --- CORREÇÃO APLICADA AQUI ---
    # Removemos 'weeks=1'. Agora, se rodar na Segunda-feira (weekday=0),
    # 'inicio_semana' será a própria Segunda-feira (hoje).
    inicio_semana = hoje + timedelta(days=-hoje.weekday())
    # --- FIM DA CORREÇÃO ---
    fim_semana = inicio_semana + timedelta(days=6)
    agendamentos_semana = database.buscar_agendamentos_para_periodo(inicio_semana, fim_semana)
    periodo_str = f"de {inicio_semana.strftime('%d/%m')} a {fim_semana.strftime('%d/%m')}"

    if not agendamentos_semana:
        mensagem = f"🗓️ **Agenda da Próxima Semana ({periodo_str})** 🗓️\n\nNenhum agendamento encontrado."
    else:
        mensagem = f"📅 **Prévia da Próxima Semana ({periodo_str})** 📅\n"
        agendamentos_agrupados = groupby(agendamentos_semana, key=lambda ag: ag.DataEvento.date())

        for dia, ags_do_dia_iter in agendamentos_agrupados:
            ags_do_dia = list(ags_do_dia_iter)
            data_formatada = formatar_data_pt_br(dia, '%A, %d/%m')
            mensagem += f"\n{'=' * 40}\n**{data_formatada}**\n{'=' * 40}\n"
            
            for i, ag in enumerate(ags_do_dia):
                hora_formatada = ag.DataEvento.strftime('%H:%M')
                mensagem += f"\n🔹 **{ag.TipoEvento}**\n"
                mensagem += f"  - ⏰ **{hora_formatada}**\n"
                mensagem += f"  - 👤 **Cliente:** {ag.NomeCliente}\n"
                
                telefone_limpo, link_wpp = criar_link_whatsapp(ag.TelefoneCliente)
                if telefone_limpo:
                    mensagem += f"  - 📞 **Telefone:** [{telefone_limpo}]({link_wpp})\n"
                if ag.CPFCliente and ag.CPFCliente.strip():
                    mensagem += f"  - 📄 **CPF:** {ag.CPFCliente.strip()}\n"
                status_pag = "PAGO" if ag.StatusPagamento == "Pago" else "RECEBER (Pendente)"
                mensagem += f"  - 💰 **Pagamento:** **{status_pag}**\n"

                if ag.Observacoes and ag.Observacoes.strip():
                    mensagem += "  - 📝 **Observações:**\n"
                    for linha in ag.Observacoes.strip().splitlines():
                        mensagem += f"    > _{linha.strip()}_\n"

                if i < len(ags_do_dia) - 1:
                    mensagem += "\n`- - - - - - - - - - - - - - - - -`\n"
    notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    logger.info("--> Lembrete semanal enviado com sucesso!")

# ===================================================================
# == NOVAS ROTINAS DE AUTOMACAO WHATSAPP ============================
# ===================================================================

def enviar_confirmacoes_whatsapp():
    """
    Rotina D-1: Envia mensagem de confirmação para agendamentos de AMANHÃ.
    """
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 Iniciando rotina de confirmação WhatsApp (D-1)...")
    
    amanha = date.today() + timedelta(days=1)
    amanha_str = amanha.strftime('%Y-%m-%d')
    data_fmt = amanha.strftime('%d/%m') # Ex: 25/10
    
    # Busca no banco quem é de amanhã e ainda não recebeu 'MsgConfirmacaoEnviada'
    pendentes = database.buscar_agendamentos_pendentes_confirmacao(amanha_str)
    
    if not pendentes:
        logger.info("--> Nenhuma confirmação pendente para amanhã.")
        return

    enviados = 0
    for ag in pendentes:
        try:
            # Formatação da mensagem amigável
            hora_evento = ag['DataEvento'].strftime('%H:%M')
            nome_cliente = ag['NomeCliente'].split()[0] # Pega só o primeiro nome
            
            # Formata a observação se houver
            obs_texto = ""
            if ag['Observacoes'] and str(ag['Observacoes']).strip():
                obs_texto = f"\n📝 *Obs:* {ag['Observacoes']}\n"

            mensagem = (
                f"Olá, *{nome_cliente}*! Tudo bem? 👋\n\n"
                f"Passando para confirmar seu agendamento de *{ag['TipoEvento']}* para amanhã, dia *{data_fmt}* às *{hora_evento}*.\n"
                f"{obs_texto}\n"
                f"Está tudo certo por aqui! Qualquer dúvida, estamos à disposição. 🍦"
            )
            
            # Envia via Z-API
            sucesso, resp = notificador_whatsapp.enviar_mensagem_whatsapp(ag['TelefoneCliente'], mensagem)
            
            if sucesso:
                database.marcar_flag_agendamento(ag['AgendamentoID'], 'confirmacao')
                logger.info(f"--> Confirmação enviada para {nome_cliente} (ID: {ag['AgendamentoID']})")
                enviados += 1
                time.sleep(45, 90) # Pausa para não bloquear a API
            else:
                logger.error(f"--> Falha ao enviar para {nome_cliente}: {resp}")
                
        except Exception as e:
            logger.error(f"--> Erro ao processar agendamento {ag.get('AgendamentoID')}: {e}")

    logger.info(f"--> Rotina de Confirmação finalizada. Total enviados: {enviados}/{len(pendentes)}")


def enviar_posvenda_whatsapp():
    """
    Rotina D+1: Envia mensagem de pós-venda para agendamentos de ONTEM.
    """
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 Iniciando rotina de Pós-Venda WhatsApp (D+1)...")
    
    ontem = date.today() - timedelta(days=1)
    ontem_str = ontem.strftime('%Y-%m-%d')
    
    # Busca no banco quem foi ontem e ainda não recebeu 'MsgPosVendaEnviada'
    pendentes = database.buscar_agendamentos_pendentes_posvenda(ontem_str)
    
    if not pendentes:
        logger.info("--> Nenhum pós-venda pendente para ontem.")
        return

    enviados = 0
    for ag in pendentes:
        try:
            nome_cliente = ag['NomeCliente'].split()[0]
            
            mensagem = (
                f"Oi, *{nome_cliente}*! Esperamos que seu evento ontem tenha sido incrível! 🥳\n\n"
                f"Deu tudo certo com o nosso serviço de *{ag['TipoEvento']}*? \n"
                f"Adoraríamos saber sua opinião para melhorarmos sempre.\n\n"
                f"Obrigado pela preferência! ❤️"
            )
            
            sucesso, resp = notificador_whatsapp.enviar_mensagem_whatsapp(ag['TelefoneCliente'], mensagem)
            
            if sucesso:
                database.marcar_flag_agendamento(ag['AgendamentoID'], 'posvenda')
                logger.info(f"--> Pós-venda enviado para {nome_cliente} (ID: {ag['AgendamentoID']})")
                enviados += 1
                time.sleep(45, 90)
            else:
                logger.error(f"--> Falha ao enviar pós-venda para {nome_cliente}: {resp}")
                
        except Exception as e:
            logger.error(f"--> Erro ao processar agendamento {ag.get('AgendamentoID')}: {e}")

    logger.info(f"--> Rotina de Pós-Venda finalizada. Total enviados: {enviados}/{len(pendentes)}")

if __name__ == "__main__":
    logger.info("--- 🤖 Robô de Lembretes de Agendamento v2.0 Iniciado 🤖 ---")
    logger.info("Verificação diária às 20:00 e semanal às sextas-feiras às 18:00.")

    schedule.every().day.at("08:00").do(enviar_lembretes_hoje)

    # Alerta diário para os carrinhos de amanhã
    schedule.every().day.at("09:00").do(enviar_lembretes_diarios)

    # Toda sexta-feira às 18:00, envia a prévia da semana que vem
    schedule.every().monday.at("08:00").do(enviar_lembretes_semanais)

    # --- NOVOS AGENDAMENTOS WHATSAPP ---
    # Confirmação (D-1)
    schedule.every().day.at("10:00").do(enviar_confirmacoes_whatsapp)
    
    # Pós-Venda (D+1)
    schedule.every().day.at("14:10").do(enviar_posvenda_whatsapp)

    # Loop infinito para manter o script rodando
    while True:
        schedule.run_pending()
        time.sleep(10)

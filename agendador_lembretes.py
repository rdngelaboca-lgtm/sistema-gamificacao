### ARQUIVO COMPLETO E ATUALIZADO: agendador_lembretes.py ###

import schedule
import time
import database
import notificador_telegram
import config
from datetime import datetime, date, timedelta
import locale

try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    print("Locale pt_BR.UTF-8 não encontrado. Usando o padrão do sistema.")

# Em agendador_lembretes.py, substitua as duas funções de envio de lembrete

def enviar_lembretes_diarios():
    """
    Busca os agendamentos de AMANHÃ e envia um resumo para o grupo.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos de amanhã...")

    amanha = date.today() + timedelta(days=1)
    agendamentos_de_amanha = database.buscar_agendamentos_para_periodo(amanha, amanha) # Busca todos os tipos

    data_formatada = amanha.strftime("%A, %d de %B").capitalize()

    if not agendamentos_de_amanha:
        mensagem = f"🗓️ **Agenda para Amanhã ({data_formatada})** 🗓️\n\nNenhum agendamento encontrado. ✅"
    else:
        mensagem = f"📢 **Lembretes para Amanhã ({data_formatada})** 📢\n\n"
        for ag in agendamentos_de_amanha:
            hora_formatada = ag.DataEvento.strftime('%H:%M')
            mensagem += f"  - ⏰ **{hora_formatada}**: {ag.TipoEvento} - Cliente: {ag.NomeCliente}\n"
            if ag.Observacoes and ag.Observacoes.strip():
                mensagem += f"    *Obs: {ag.Observacoes.strip()}*\n"

    notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    print("--> Lembrete diário enviado com sucesso!")

def enviar_lembretes_semanais():
    """
    Busca os agendamentos da PRÓXIMA SEMANA, agrupa por dia e envia um resumo.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos da PRÓXIMA SEMANA...")

    hoje = date.today()
    inicio_semana = hoje + timedelta(days=-hoje.weekday(), weeks=1)
    fim_semana = inicio_semana + timedelta(days=6)

    agendamentos_semana = database.buscar_agendamentos_para_periodo(inicio_semana, fim_semana)

    periodo_str = f"de {inicio_semana.strftime('%d/%m')} a {fim_semana.strftime('%d/%m')}"

    if not agendamentos_semana:
        mensagem = f"🗓️ **Agenda da Próxima Semana ({periodo_str})** 🗓️\n\nNenhum agendamento encontrado para a próxima semana."
    else:
        mensagem = f"📅 **Prévia da Próxima Semana ({periodo_str})** 📅\n"
        data_atual = None
        for ag in agendamentos_semana:
            if ag.DataEvento.date() != data_atual:
                data_atual = ag.DataEvento.date()
                data_formatada = data_atual.strftime('%A, %d/%m').capitalize()
                mensagem += f"\n--- **{data_formatada}** ---\n"
            
            hora_formatada = ag.DataEvento.strftime('%H:%M')
            mensagem += f"  - ⏰ **{hora_formatada}**: {ag.TipoEvento} - Cliente: {ag.NomeCliente}\n"
            if ag.Observacoes and ag.Observacoes.strip():
                mensagem += f"    *Obs: {ag.Observacoes.strip()}*\n"

    notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    print("--> Lembrete semanal enviado com sucesso!")

if __name__ == "__main__":
    print("--- 🤖 Robô de Lembretes de Agendamento v2.0 Iniciado 🤖 ---")
    print("Verificação diária às 20:00 e semanal às sextas-feiras às 18:00.")

    # Alerta diário para os carrinhos de amanhã
    schedule.every().day.at("10:40").do(enviar_lembretes_diarios)

    # NOVO ALERTA: Toda sexta-feira às 18:00, envia a prévia da semana que vem
    schedule.every().Monday.at("08:00").do(enviar_lembretes_semanais)

    # Loop infinito para manter o script rodando
    while True:
        schedule.run_pending()
        time.sleep(10)

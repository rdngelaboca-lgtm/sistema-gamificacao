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

def enviar_lembretes_diarios():
    """
    Busca os agendamentos de AMANHÃ e envia um resumo para o grupo.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos de amanhã...")

    amanha = date.today() + timedelta(days=1)
    # AJUSTE: Agora usamos a função de período para buscar apenas carrinhos
    agendamentos_de_amanha = database.buscar_agendamentos_para_periodo(amanha, amanha, tipo_evento_filtro='Carrinho de Sorvete')

    data_formatada = amanha.strftime("%A, %d de %B").capitalize()

    if not agendamentos_de_amanha:
        mensagem = f"🗓️ **Carrinhos para Amanhã ({data_formatada})** 🗓️\n\nNenhum carrinho de sorvete agendado. ✅"
    else:
        mensagem = f"🍦 **Lembrete de Carrinhos para Amanhã ({data_formatada})** 🍦\n\n"
        # Usamos .DataEvento completo para ordenar, mas mostramos só a hora
        for ag in agendamentos_de_amanha:
            hora_formatada = ag.DataEvento.strftime('%H:%M')
            mensagem += f"  - ⏰ **{hora_formatada}**: Cliente: {ag.NomeCliente}\n"

    notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    print("--> Lembrete diário enviado com sucesso!")

def enviar_lembretes_semanais():
    """
    (NOVA FUNÇÃO)
    Busca os agendamentos da PRÓXIMA SEMANA e envia um resumo.
    Roda toda sexta-feira.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos da PRÓXIMA SEMANA...")

    hoje = date.today()
    # Pega a data da próxima segunda-feira
    inicio_semana = hoje + timedelta(days=-hoje.weekday(), weeks=1)
    # Pega a data do próximo domingo
    fim_semana = inicio_semana + timedelta(days=6)

    agendamentos_semana = database.buscar_agendamentos_para_periodo(inicio_semana, fim_semana, tipo_evento_filtro='Carrinho de Sorvete')

    # Formata o período para a mensagem, ex: "de 13/10 a 19/10"
    periodo_str = f"de {inicio_semana.strftime('%d/%m')} a {fim_semana.strftime('%d/%m')}"

    if not agendamentos_semana:
        mensagem = f"🗓️ **Agenda da Próxima Semana ({periodo_str})** 🗓️\n\nNenhum carrinho de sorvete agendado para a próxima semana."
    else:
        mensagem = f"📅 **Prévia de Carrinhos da Próxima Semana ({periodo_str})** 📅\n\n"
        for ag in agendamentos_semana:
            # Agora incluímos o dia da semana na notificação
            data_hora_formatada = ag.DataEvento.strftime('%A, %d/%m às %H:%M').capitalize()
            mensagem += f"  - 🍦 **{data_hora_formatada}**: Cliente: {ag.NomeCliente}\n"

    notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    print("--> Lembrete semanal enviado com sucesso!")


if __name__ == "__main__":
    print("--- 🤖 Robô de Lembretes de Agendamento v2.0 Iniciado 🤖 ---")
    print("Verificação diária às 20:00 e semanal às sextas-feiras às 18:00.")

    # Alerta diário para os carrinhos de amanhã
    schedule.every().day.at("20:00").do(enviar_lembretes_diarios)

    # NOVO ALERTA: Toda sexta-feira às 18:00, envia a prévia da semana que vem
    schedule.every().friday.at("18:00").do(enviar_lembretes_semanais)

    # Loop infinito para manter o script rodando
    while True:
        schedule.run_pending()
        time.sleep(60)

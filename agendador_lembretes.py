### ARQUIVO COMPLETO E ATUALIZADO: agendador_lembretes.py ###

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
    print("Locale pt_BR.UTF-8 não encontrado. Usando o padrão do sistema.")

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
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos de HOJE...")

    hoje = date.today()
    agendamentos_de_hoje = database.buscar_agendamentos_para_periodo(hoje, hoje)
    data_formatada = formatar_data_pt_br(hoje, '%A, %d de %B')

    if not agendamentos_de_hoje:
        print("--> Nenhum agendamento para hoje. Nenhuma mensagem enviada.")
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
    print("--> Lembrete de HOJE enviado com sucesso!")


def enviar_lembretes_diarios():
    """Busca os agendamentos de AMANHÃ e envia um resumo completo."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos de amanhã...")
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
    print("--> Lembrete diário enviado com sucesso!")


def enviar_lembretes_semanais():
    """Busca os agendamentos da PRÓXIMA SEMANA e envia um resumo completo."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Verificando agendamentos da PRÓXIMA SEMANA...")
    hoje = date.today()
    inicio_semana = hoje + timedelta(days=-hoje.weekday(), weeks=1)
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
    print("--> Lembrete semanal enviado com sucesso!")

if __name__ == "__main__":
    print("--- 🤖 Robô de Lembretes de Agendamento v2.0 Iniciado 🤖 ---")
    print("Verificação diária às 20:00 e semanal às sextas-feiras às 18:00.")

    schedule.every().day.at("08:00").do(enviar_lembretes_hoje)

    # Alerta diário para os carrinhos de amanhã
    schedule.every().day.at("09:00").do(enviar_lembretes_diarios)

    # NOVO ALERTA: Toda sexta-feira às 18:00, envia a prévia da semana que vem
    schedule.every().monday.at("08:00").do(enviar_lembretes_semanais)

    # Loop infinito para manter o script rodando
    while True:
        schedule.run_pending()
        time.sleep(10)
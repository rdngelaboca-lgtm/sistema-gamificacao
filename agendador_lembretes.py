# ==============================================================================
# == agendador_lembretes.py  -  Robô de Lembretes de Agendamento ===============
# ==============================================================================
# O que ele faz sozinho, todos os dias:
#   • 08:00  -> Telegram (grupo): agenda de HOJE (só envia se houver agendamento)
#   • 09:00  -> Telegram (grupo): agenda de AMANHÃ
#   • 08:00 das segundas-feiras -> Telegram (grupo): agenda da SEMANA (seg a dom)
#   • 10:00  -> WhatsApp (cliente): confirmação dos eventos de AMANHÃ (D-1)
#   • 14:10  -> WhatsApp (cliente): pós-venda dos eventos de ONTEM (D+1)
#
# Como rodar:  python agendador_lembretes.py        (para parar: Ctrl+C)
#
# Versão DEPURADA: procure por [DEPURAÇÃO] para ver cada correção.
#
# [DEPURAÇÃO] NOVIDADES IMPORTANTES:
#   1) Se o computador for ligado DEPOIS do horário (ex: 08:40), o lembrete das 08:00
#      é enviado assim que o robô abrir (antes ele era perdido até o dia seguinte).
#      Cada tarefa tem um "horário limite": depois dele, não envia mais nada daquele
#      dia (para não mandar "confirmação" para cliente às 23h, por exemplo).
#   2) O robô anota no arquivo "lembretes_estado.json" o que já foi enviado hoje.
#      Se você fechar e abrir de novo, NADA é enviado em dobro.
#   3) Se o Telegram/WhatsApp falhar, ele tenta de novo mais tarde (sozinho).
#   4) Um erro em uma tarefa não derruba mais o robô inteiro.
#   5) A biblioteca "schedule" não é mais necessária para este arquivo.
# ==============================================================================

# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING ===================================
# ==============================================================================
import logging
import logging.handlers
import sys
import os

LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs'
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

PASTA_DO_PROGRAMA = os.path.dirname(os.path.abspath(__file__))

# [DEPURAÇÃO] Antes, se a pasta "logs" não existisse, o programa usava "logger" ANTES
# de criá-lo (linha 24 do original) e fechava na hora com NameError, logo ao abrir.
# Também APAGAVA a configuração de log de quem importasse este arquivo.
# Agora a pasta é criada com segurança e o log só é configurado se ninguém configurou.
if not logging.getLogger().handlers:
    log_dir = os.path.join(PASTA_DO_PROGRAMA, LOG_FOLDER)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        log_dir = PASTA_DO_PROGRAMA
    _file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, LOG_FILENAME), maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    _console_handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[_file_handler, _console_handler])

logger = logging.getLogger(__name__)
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================

import html
import json
import random
import re
import time
from datetime import datetime, date, timedelta

import config
import database
import notificador_telegram
import notificador_whatsapp

# ------------------------------------------------------------------------------
# Configurações (pode mudar os horários aqui, sempre no formato "HH:MM")
# ------------------------------------------------------------------------------
ARQUIVO_ESTADO = os.path.join(PASTA_DO_PROGRAMA, 'lembretes_estado.json')

# Pausa entre uma mensagem de WhatsApp e outra (segundos), para a Z-API / WhatsApp
# não considerarem os envios como SPAM.
PAUSA_WHATSAPP_MIN = 45
PAUSA_WHATSAPP_MAX = 90

# De quanto em quanto tempo (segundos) o robô confere se tem tarefa para fazer.
INTERVALO_VERIFICACAO = 30

# Enviar as "Observações" do agendamento para o CLIENTE na confirmação do WhatsApp?
# ATENÇÃO: as observações são escritas pela equipe. Se vocês anotam coisas internas
# ali (ex: "cobrar sinal", "cliente difícil"), coloque no config.py:
#     WPP_ENVIAR_OBSERVACOES_AO_CLIENTE = False
ENVIAR_OBS_AO_CLIENTE = getattr(config, 'WPP_ENVIAR_OBSERVACOES_AO_CLIENTE', True)

DIAS_SEMANA = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
               "Sexta-feira", "Sábado", "Domingo"]
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


# ==============================================================================
# == FUNÇÕES AUXILIARES ========================================================
# ==============================================================================
def esc(valor):
    """
    [DEPURAÇÃO] Protege textos digitados (nome, observação...) na mensagem HTML.
    Um "<" ou "&" numa observação fazia o Telegram recusar a formatação.
    """
    return html.escape(str(valor)) if valor is not None else ""


def data_por_extenso(d):
    """Ex: 'Sexta-feira, 25 de Outubro'."""
    # [DEPURAÇÃO] A versão antiga dependia do idioma do Windows (locale) e trocava
    # textos com replace(); montar direto em português é mais simples e sempre funciona.
    return f"{DIAS_SEMANA[d.weekday()]}, {d.day:02d} de {MESES[d.month - 1]}"


def data_curta(d):
    """Ex: 'Sexta-feira, 25/10'."""
    return f"{DIAS_SEMANA[d.weekday()]}, {d.strftime('%d/%m')}"


def criar_link_whatsapp(telefone):
    """Limpa o número de telefone e cria um link 'wa.me'. Devolve (telefone, link)."""
    if not telefone or not str(telefone).strip():
        return None, None
    numeros = re.sub(r'\D', '', str(telefone))
    if not numeros:  # [DEPURAÇÃO] telefone só com letras gerava o link "https://wa.me/55"
        return str(telefone).strip(), None
    if len(numeros) <= 11:
        numeros = "55" + numeros
    return str(telefone).strip(), f"https://wa.me/{numeros}"


def primeiro_nome(nome_completo):
    """[DEPURAÇÃO] Nome vazio fazia '.split()[0]' dar erro e o cliente ficava sem mensagem."""
    partes = str(nome_completo or '').split()
    return partes[0] if partes else ''


def _campo(ag, nome, padrao=None):
    """Lê um campo tanto de linha do banco (ag.Campo) quanto de dicionário (ag['Campo'])."""
    if isinstance(ag, dict):
        return ag.get(nome, padrao)
    return getattr(ag, nome, padrao)


def _esta_cancelado(ag):
    return str(_campo(ag, 'StatusAgendamento', '') or '').strip().lower() == 'cancelado'


def agendamentos_validos(lista):
    """
    [DEPURAÇÃO] A busca do banco traz TAMBÉM os agendamentos cancelados: a equipe
    recebia no grupo o lembrete de um carrinho que o cliente já tinha cancelado.
    Também tira os que estão sem data (que derrubavam o robô) e ordena por horário.
    """
    validos = [ag for ag in (lista or [])
               if isinstance(_campo(ag, 'DataEvento'), datetime) and not _esta_cancelado(ag)]
    return sorted(validos, key=lambda ag: _campo(ag, 'DataEvento'))


def resposta_ok(resposta):
    """True se o Telegram aceitou a mensagem (funciona com o notificador novo e o antigo)."""
    if isinstance(resposta, dict):
        return bool(resposta.get('ok'))
    try:
        return bool(resposta.json().get('ok'))
    except Exception:
        return bool(resposta)


def formatar_agendamento_html(ag):
    """
    Monta o bloco de UM agendamento para o grupo do Telegram.
    [DEPURAÇÃO] O texto antigo era escrito em Markdown (**negrito**, [link](url),
    _itálico_, `código`), mas o notificador envia em HTML: no grupo apareciam os
    colchetes, os sublinhados e as crases, e o link do WhatsApp não era clicável.
    """
    hora = _campo(ag, 'DataEvento').strftime('%H:%M')
    texto = f"\n🔹 <b>{esc(_campo(ag, 'TipoEvento'))}</b>\n"
    texto += f"  - ⏰ <b>{hora}</b>\n"
    texto += f"  - 👤 <b>Cliente:</b> {esc(_campo(ag, 'NomeCliente'))}\n"

    telefone, link = criar_link_whatsapp(_campo(ag, 'TelefoneCliente'))
    if telefone and link:
        texto += f'  - 📞 <b>Telefone:</b> <a href="{link}">{esc(telefone)}</a>\n'
    elif telefone:
        texto += f"  - 📞 <b>Telefone:</b> {esc(telefone)}\n"

    cpf = str(_campo(ag, 'CPFCliente') or '').strip()
    if cpf:
        texto += f"  - 📄 <b>CPF:</b> {esc(cpf)}\n"

    status_pag = "PAGO" if _campo(ag, 'StatusPagamento') == "Pago" else "RECEBER (Pendente)"
    texto += f"  - 💰 <b>Pagamento: {status_pag}</b>\n"

    obs = str(_campo(ag, 'Observacoes') or '').strip()
    if obs:
        texto += "  - 📝 <b>Observações:</b>\n"
        for linha in obs.splitlines():
            if linha.strip():
                texto += f"    &gt; <i>{esc(linha.strip())}</i>\n"
    return texto


SEPARADOR = "\n<code>- - - - - - - - - - - - - - - - -</code>\n"


def enviar_para_grupo(mensagem, descricao):
    """Envia ao grupo de agendamentos e CONFERE se o Telegram aceitou."""
    # [DEPURAÇÃO] Antes o log dizia "enviado com sucesso" mesmo quando o Telegram recusava.
    resposta = notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
    if resposta_ok(resposta):
        logger.info(f"--> {descricao} enviado com sucesso!")
        return True
    logger.error(f"--> {descricao} NÃO foi enviado. Resposta do Telegram: {resposta}")
    return False


# ==============================================================================
# == LEMBRETES PARA O GRUPO (TELEGRAM) =========================================
# ==============================================================================
# Cada tarefa devolve True quando terminou (não precisa repetir hoje) ou False
# quando algo falhou (o robô tenta de novo mais tarde).

def enviar_lembretes_hoje():
    """Busca os agendamentos de HOJE e envia um resumo para o grupo."""
    logger.info("Verificando agendamentos de HOJE...")
    hoje = date.today()
    agendamentos = agendamentos_validos(database.buscar_agendamentos_para_periodo(hoje, hoje))

    if not agendamentos:
        logger.info("--> Nenhum agendamento para hoje. Nenhuma mensagem enviada.")
        return True

    mensagem = f"🔔 <b>Agenda de Hoje ({data_por_extenso(hoje)})</b> 🔔\n"
    mensagem += SEPARADOR.join(formatar_agendamento_html(ag) for ag in agendamentos)
    return enviar_para_grupo(mensagem, "Lembrete de HOJE")


def enviar_lembretes_diarios():
    """Busca os agendamentos de AMANHÃ e envia um resumo completo."""
    logger.info("Verificando agendamentos de AMANHÃ...")
    amanha = date.today() + timedelta(days=1)
    agendamentos = agendamentos_validos(database.buscar_agendamentos_para_periodo(amanha, amanha))
    data_txt = data_por_extenso(amanha)

    if not agendamentos:
        mensagem = f"🗓️ <b>Agenda para Amanhã ({data_txt})</b> 🗓️\n\nNenhum agendamento encontrado. ✅"
    else:
        mensagem = f"📢 <b>Lembretes para Amanhã ({data_txt})</b> 📢\n"
        mensagem += SEPARADOR.join(formatar_agendamento_html(ag) for ag in agendamentos)
    return enviar_para_grupo(mensagem, "Lembrete de AMANHÃ")


def enviar_lembretes_semanais():
    """Busca os agendamentos da SEMANA ATUAL (segunda a domingo) e envia um resumo."""
    logger.info("Verificando agendamentos da SEMANA...")
    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())  # segunda-feira desta semana
    fim_semana = inicio_semana + timedelta(days=6)          # domingo desta semana
    agendamentos = agendamentos_validos(
        database.buscar_agendamentos_para_periodo(inicio_semana, fim_semana))
    periodo = f"de {inicio_semana.strftime('%d/%m')} a {fim_semana.strftime('%d/%m')}"

    # [DEPURAÇÃO] O título dizia "Próxima Semana", mas a lista é da semana ATUAL
    # (o envio é na segunda-feira de manhã, cobrindo de segunda a domingo).
    if not agendamentos:
        mensagem = f"🗓️ <b>Agenda da Semana ({periodo})</b> 🗓️\n\nNenhum agendamento encontrado. ✅"
        return enviar_para_grupo(mensagem, "Lembrete SEMANAL")

    mensagem = f"📅 <b>Agenda da Semana ({periodo})</b> 📅\n"
    dia_atual = None
    for ag in agendamentos:
        dia = _campo(ag, 'DataEvento').date()
        if dia != dia_atual:
            dia_atual = dia
            mensagem += f"\n{'=' * 30}\n<b>{data_curta(dia)}</b>\n{'=' * 30}\n"
        else:
            mensagem += SEPARADOR
        mensagem += formatar_agendamento_html(ag)
    return enviar_para_grupo(mensagem, "Lembrete SEMANAL")


# ==============================================================================
# == AUTOMAÇÃO WHATSAPP (CLIENTE) ==============================================
# ==============================================================================
# [DEPURAÇÃO] Guarda (na memória) quem JÁ recebeu hoje. Se o banco falhar ao marcar
# a "flag" de enviado, a nova tentativa não manda a mesma mensagem duas vezes.
_ja_enviados_hoje = {}


def _registrar_envio(tipo, agendamento_id):
    chave = (tipo, date.today().isoformat())
    _ja_enviados_hoje.setdefault(chave, set()).add(agendamento_id)


def _ja_enviado(tipo, agendamento_id):
    return agendamento_id in _ja_enviados_hoje.get((tipo, date.today().isoformat()), set())


def pausa_entre_mensagens():
    """[DEPURAÇÃO] Era 'time.sleep(45, 90)', que dá ERRO (sleep só aceita um número).
    Resultado: NÃO havia pausa nenhuma e as mensagens saíam todas de uma vez
    (risco de o número da loja ser bloqueado pelo WhatsApp), e o log mostrava erro."""
    segundos = random.randint(PAUSA_WHATSAPP_MIN, PAUSA_WHATSAPP_MAX)
    logger.info(f"--> Aguardando {segundos}s antes da próxima mensagem de WhatsApp...")
    time.sleep(segundos)


def _disparar_whatsapp(tipo, pendentes, montar_mensagem, flag_banco, nome_rotina):
    """
    Envia as mensagens de WhatsApp de uma lista de agendamentos.
    Devolve True se TODOS foram enviados (ou não havia nenhum).
    """
    pendentes = [ag for ag in (pendentes or [])
                 if not _esta_cancelado(ag) and not _ja_enviado(tipo, _campo(ag, 'AgendamentoID'))]
    if not pendentes:
        logger.info(f"--> {nome_rotina}: nada pendente.")
        return True

    enviados, falhas = 0, 0
    for i, ag in enumerate(pendentes):
        ag_id = _campo(ag, 'AgendamentoID')
        try:
            nome = primeiro_nome(_campo(ag, 'NomeCliente'))
            mensagem = montar_mensagem(ag, nome)
            sucesso, resposta = notificador_whatsapp.enviar_mensagem_whatsapp(
                _campo(ag, 'TelefoneCliente'), mensagem)
        except Exception as e:
            logger.error(f"--> {nome_rotina}: erro ao processar agendamento {ag_id}: {e}", exc_info=True)
            falhas += 1
            continue

        if sucesso:
            enviados += 1
            _registrar_envio(tipo, ag_id)
            try:
                if database.marcar_flag_agendamento(ag_id, flag_banco) is False:
                    logger.warning(f"--> Mensagem enviada, mas o banco não marcou a flag '{flag_banco}' (ID {ag_id}).")
            except Exception as e:
                logger.warning(f"--> Mensagem enviada, mas erro ao marcar a flag '{flag_banco}' (ID {ag_id}): {e}")
            logger.info(f"--> {nome_rotina}: enviado para {nome or 'cliente'} (ID: {ag_id})")
        else:
            falhas += 1
            logger.error(f"--> {nome_rotina}: falha ao enviar para {nome or 'cliente'} (ID {ag_id}): {resposta}")

        # Pausa só ENTRE mensagens (não depois da última) e só se houve envio
        if sucesso and i < len(pendentes) - 1:
            pausa_entre_mensagens()

    logger.info(f"--> {nome_rotina} finalizada. Enviados: {enviados}/{len(pendentes)}. Falhas: {falhas}.")
    return falhas == 0


def _texto_hora(ag):
    dt = _campo(ag, 'DataEvento')
    return dt.strftime('%H:%M') if isinstance(dt, datetime) else "horário combinado"


def _mensagem_confirmacao(ag, nome):
    data_fmt = (date.today() + timedelta(days=1)).strftime('%d/%m')
    saudacao = f"Olá, *{nome}*! Tudo bem? 👋" if nome else "Olá! Tudo bem? 👋"
    obs_texto = ""
    obs = str(_campo(ag, 'Observacoes') or '').strip()
    if obs and ENVIAR_OBS_AO_CLIENTE:
        obs_texto = f"\n📝 *Obs:* {obs}\n"
    return (
        f"{saudacao}\n\n"
        f"Passando para confirmar seu agendamento de *{_campo(ag, 'TipoEvento')}* para amanhã, "
        f"dia *{data_fmt}* às *{_texto_hora(ag)}*.\n"
        f"{obs_texto}\n"
        f"Está tudo certo por aqui! Qualquer dúvida, estamos à disposição. 🍦"
    )


def _mensagem_posvenda(ag, nome):
    saudacao = f"Oi, *{nome}*!" if nome else "Oi!"
    return (
        f"{saudacao} Esperamos que seu evento ontem tenha sido incrível! 🥳\n\n"
        f"Deu tudo certo com o nosso serviço de *{_campo(ag, 'TipoEvento')}*? \n"
        f"Adoraríamos saber sua opinião para melhorarmos sempre.\n\n"
        f"Obrigado pela preferência! ❤️"
    )


def enviar_confirmacoes_whatsapp():
    """Rotina D-1: mensagem de confirmação para os agendamentos de AMANHÃ."""
    logger.info("🤖 Iniciando rotina de confirmação WhatsApp (D-1)...")
    amanha_str = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
    pendentes = database.buscar_agendamentos_pendentes_confirmacao(amanha_str)
    return _disparar_whatsapp('confirmacao', pendentes, _mensagem_confirmacao,
                              'confirmacao', "Confirmação WhatsApp")


def enviar_posvenda_whatsapp():
    """Rotina D+1: mensagem de pós-venda para os agendamentos de ONTEM."""
    logger.info("🤖 Iniciando rotina de Pós-Venda WhatsApp (D+1)...")
    ontem_str = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    pendentes = database.buscar_agendamentos_pendentes_posvenda(ontem_str)
    return _disparar_whatsapp('posvenda', pendentes, _mensagem_posvenda,
                              'posvenda', "Pós-Venda WhatsApp")


# ==============================================================================
# == AGENDA DO ROBÔ ============================================================
# ==============================================================================
# [DEPURAÇÃO] Substitui a biblioteca "schedule". Problemas que existiam antes:
#   • qualquer erro dentro de uma tarefa DERRUBAVA o robô inteiro (o schedule não
#     segura erros) e ninguém percebia até faltar um lembrete;
#   • computador ligado depois do horário = lembrete perdido;
#   • falha do Telegram/WhatsApp = ninguém tentava de novo.
#
# Campos de cada tarefa:
#   nome        -> identificação (usada no arquivo lembretes_estado.json)
#   funcao      -> o que executar
#   inicio      -> horário normal ("HH:MM")
#   limite      -> depois deste horário, não envia mais naquele dia
#   dias        -> dias da semana (0=segunda ... 6=domingo); None = todos os dias
#   repetir_min -> se falhar, tenta de novo depois de X minutos
#   tentativas  -> máximo de tentativas por dia
TAREFAS = [
    dict(nome='lembrete_hoje',        funcao=enviar_lembretes_hoje,        inicio="08:00", limite="18:00", dias=None, repetir_min=10, tentativas=5),
    dict(nome='lembrete_amanha',      funcao=enviar_lembretes_diarios,     inicio="09:00", limite="21:00", dias=None, repetir_min=10, tentativas=5),
    dict(nome='lembrete_semanal',     funcao=enviar_lembretes_semanais,    inicio="08:00", limite="20:00", dias={0},  repetir_min=10, tentativas=5),
    dict(nome='whatsapp_confirmacao', funcao=enviar_confirmacoes_whatsapp, inicio="10:00", limite="20:00", dias=None, repetir_min=30, tentativas=3),
    dict(nome='whatsapp_posvenda',    funcao=enviar_posvenda_whatsapp,     inicio="14:10", limite="20:00", dias=None, repetir_min=30, tentativas=3),
]

# Tentativas feitas hoje (na memória): {nome: {'data': 'AAAA-MM-DD', 'qtd': n, 'ultima': datetime}}
_tentativas = {}


def _hora(texto):
    return datetime.strptime(texto, "%H:%M").time()


def carregar_estado():
    try:
        with open(ARQUIVO_ESTADO, 'r', encoding='utf-8') as f:
            estado = json.load(f)
            return estado if isinstance(estado, dict) else {}
    except (OSError, ValueError):
        return {}


def ja_feito_hoje(nome, hoje=None):
    hoje = hoje or date.today()
    return carregar_estado().get(nome) == hoje.isoformat()


def marcar_feito_hoje(nome, hoje=None):
    hoje = hoje or date.today()
    estado = carregar_estado()
    estado[nome] = hoje.isoformat()
    temporario = ARQUIVO_ESTADO + '.tmp'
    try:
        with open(temporario, 'w', encoding='utf-8') as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
        os.replace(temporario, ARQUIVO_ESTADO)  # troca de uma vez (não corrompe o arquivo)
    except OSError as e:
        logger.warning(f"Não foi possível salvar {ARQUIVO_ESTADO}: {e}")


def executar_com_seguranca(tarefa):
    """Roda a tarefa sem deixar um erro derrubar o robô. Devolve True/False."""
    try:
        resultado = tarefa['funcao']()
        return resultado is not False
    except Exception as e:
        logger.error(f"!!! ERRO na tarefa '{tarefa['nome']}': {e}", exc_info=True)
        return False


def tarefa_deve_rodar(tarefa, agora):
    """Decide se a tarefa precisa rodar AGORA."""
    if tarefa['dias'] is not None and agora.weekday() not in tarefa['dias']:
        return False
    if not (_hora(tarefa['inicio']) <= agora.time() < _hora(tarefa['limite'])):
        return False
    if ja_feito_hoje(tarefa['nome'], agora.date()):
        return False

    controle = _tentativas.get(tarefa['nome'])
    if controle and controle['data'] == agora.date().isoformat():
        if controle['qtd'] >= tarefa['tentativas']:
            return False
        if agora - controle['ultima'] < timedelta(minutes=tarefa['repetir_min']):
            return False
    return True


def verificar_tarefas(agora=None):
    """Confere todas as tarefas e executa as que estão na hora. Devolve os nomes executados."""
    agora = agora or datetime.now()
    executadas = []
    for tarefa in TAREFAS:
        if not tarefa_deve_rodar(tarefa, agora):
            continue
        nome = tarefa['nome']
        controle = _tentativas.get(nome)
        if not controle or controle['data'] != agora.date().isoformat():
            controle = {'data': agora.date().isoformat(), 'qtd': 0, 'ultima': agora}
        controle['qtd'] += 1
        controle['ultima'] = agora
        _tentativas[nome] = controle

        logger.info(f"▶ Executando '{nome}' (tentativa {controle['qtd']}/{tarefa['tentativas']})")
        executadas.append(nome)
        if executar_com_seguranca(tarefa):
            marcar_feito_hoje(nome, agora.date())
        elif controle['qtd'] < tarefa['tentativas']:
            logger.warning(f"'{nome}' falhou. Nova tentativa em {tarefa['repetir_min']} minutos.")
        else:
            logger.error(f"'{nome}' falhou {controle['qtd']} vezes hoje. Desistindo até amanhã.")
    return executadas


if __name__ == "__main__":
    logger.info("--- 🤖 Robô de Lembretes de Agendamento v2.1 (depurado) Iniciado 🤖 ---")
    # [DEPURAÇÃO] O aviso antigo dizia "diária às 20:00 e semanal às sextas 18:00",
    # mas os horários reais eram outros. Agora a lista é gerada da própria agenda.
    nomes_dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    for t in TAREFAS:
        dias = "todos os dias" if t['dias'] is None else ", ".join(nomes_dias[d] for d in sorted(t['dias']))
        logger.info(f"   • {t['nome']}: {t['inicio']} ({dias}) - envia até {t['limite']}")

    try:
        while True:
            try:
                verificar_tarefas()
            except Exception as e:  # proteção extra: o robô nunca para sozinho
                logger.error(f"!!! Erro inesperado no ciclo do robô: {e}", exc_info=True)
            time.sleep(INTERVALO_VERIFICACAO)
    except KeyboardInterrupt:
        logger.info("Robô de lembretes encerrado pelo usuário (Ctrl+C).")

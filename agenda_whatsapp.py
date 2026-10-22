# ==============================================================================
# == agenda_whatsapp.py - 📅 WhatsApp da AGENDA para o cliente ==================
# ==============================================================================
# A confirmação do agendamento (na hora em que é criado), o lembrete do dia anterior (D-1) e o pós-venda (D+1).
# Saem pelo NÚMERO DOS CLIENTES (a 2ª instância da Z-API, o mesmo da 💬 Central de Atendimento): a resposta do
# cliente cai na central, e a mensagem da agenda já está na conversa ("📅 Agenda"), para quem for atender.
# Chave em Gestão › 📢 Clientes › ⚙️ Ajustes: 'clientes' (padrão) ou 'loja' (o número da escala e dos avisos,
# como era antes). Sem o número dos clientes configurado, sai pelo da loja (e o log avisa).
# Os tokens ficam no banco (número dos clientes) e no config.py (número da loja): nunca vão para o log.
# ==============================================================================
import logging

logger = logging.getLogger(__name__)

CLIENTES, LOJA = 'clientes', 'loja'
NUMEROS = {CLIENTES: "📱 Número dos clientes (o da 💬 Central)", LOJA: "🏪 Número da loja (o da escala e dos avisos)"}


def escolha():
    """Por qual número saem as mensagens da agenda: 'clientes' (padrão) ou 'loja'."""
    import clientes
    try:
        valor = clientes._params('agenda_numero').get('agenda_numero')
    except Exception as e:
        logger.error(f"[AGENDA] Não deu para ler a escolha do número (vai o dos clientes): {e}")
        valor = None
    return valor if valor in NUMEROS else CLIENTES


def ajustes():
    import clientes
    return {'numero': escolha(), 'opcoes': [{'chave': k, 'nome': n} for k, n in NUMEROS.items()],
            'clientes_configurado': clientes.configurado()}


def salvar(dados, usuario):
    import clientes
    valor = (dados or {}).get('numero') if isinstance(dados, dict) else None
    if valor not in NUMEROS:
        raise clientes.ErroClientes("Escolha por qual número saem as mensagens da agenda.")
    if valor == CLIENTES and not clientes.configurado():
        raise clientes.ErroClientes("Configure antes o número dos clientes (📱 acima): sem ele, a agenda continua "
                                    "saindo pelo número da loja.")
    clientes._salvar_params({'agenda_numero': valor})
    logger.info(f"[AGENDA] {usuario.get('nome')}: mensagens da agenda pelo {'número dos clientes' if valor == CLIENTES else 'número da loja'}.")
    return {'ok': True, 'mensagem': f"Mensagens da agenda: {NUMEROS[valor]}."}


def enviar(telefone, texto, nome=None):
    """(True, 'Mensagem enviada!') ou (False, motivo): o mesmo jeito do notificador_whatsapp (a agenda não muda nada)."""
    import clientes
    import notificador_whatsapp
    if escolha() == CLIENTES:
        if clientes.configurado():
            return _pelo_numero_dos_clientes(telefone, texto, nome)
        logger.warning("[AGENDA] O número dos clientes não está configurado (📢 Clientes › ⚙️ Ajustes): "
                       "a mensagem da agenda saiu pelo número da loja.")
    return notificador_whatsapp.enviar_mensagem_whatsapp(telefone, texto)


def _pelo_numero_dos_clientes(telefone, texto, nome):
    import clientes
    import atendimento
    try:
        tel = clientes.normalizar_telefone(telefone)
    except clientes.ErroClientes as e:
        return False, str(e)
    msg_id = None
    try:                                              # entra na 💬 Central antes (a cópia da Z-API não vira "pelo celular")
        msg_id = atendimento.agenda_antes(tel, texto, nome)
    except Exception as e:
        logger.error(f"[AGENDA] A mensagem não entrou na 💬 Central (o envio segue): {e}")
    try:
        ok, r = clientes.enviar_para(tel, texto)
    except Exception as e:
        ok, r = False, f"erro no envio ({e})"
    if msg_id:
        try:
            atendimento.agenda_depois(msg_id, ok, r if ok else None)
        except Exception as e:
            logger.error(f"[AGENDA] A situação da mensagem {msg_id} na 💬 Central não foi gravada: {e}")
    if ok:
        logger.info(f"[AGENDA] WhatsApp para …{tel[-4:]} pelo número dos clientes.")
        return True, "Mensagem enviada!"
    motivo = clientes._sem_segredo(str(r))
    logger.error(f"[AGENDA] WhatsApp para …{tel[-4:]} não foi (número dos clientes): {motivo}")
    return False, motivo

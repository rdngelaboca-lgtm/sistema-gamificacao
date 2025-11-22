from datetime import datetime, timedelta

# --- Regras de Negócio Configuráveis ---
HORA_BLOQUEIO_INICIO = "16:30"
HORA_BLOQUEIO_FIM = "18:30"
MAX_HORAS_SEM_PAUSA = 5
DURACAO_INTERVALO = 1 # horas

def calcular_intervalos_automaticos(dados_escala, dia_semana_iso):
    """
    Calcula os horários de intervalo baseados nas regras de fluxo e CLT.

    Args:
        dados_escala: Lista de dicionários contendo dados dos funcionários escalados.
        dia_semana_iso: Inteiro (1=Segunda ... 7=Domingo).

    Returns:
        tuple: (sugestoes, log_erros)
    """
    log_erros = []
    sugestoes = {} # {posicao_id: (inicio_intervalo, fim_intervalo)}

    # 1. Agrupar funcionários por Setor
    por_setor = {}
    for p in dados_escala:
        setor = p['setor']
        if not setor: 
            setor = "Sem Setor"
        if setor not in por_setor: 
            por_setor[setor] = []
        por_setor[setor].append(p)

    # 2. Processar cada Setor individualmente
    for setor, pessoas in por_setor.items():
        if setor == "Sem Setor": 
            if pessoas:
                log_erros.append(f"⚠️ {len(pessoas)} funcionário(s) ignorado(s) pois a posição não tem 'Setor' definido no mapa.")
            continue

    # Regra: Setor não pode ficar sozinho (exceto se só houver 1 pessoa escalada no total)
        if len(pessoas) < 2:
            log_erros.append(f"⚠️ Setor '{setor}' tem apenas 1 pessoa. Intervalo automático não agendado (risco de ficar sozinho).")
            continue

        # Ordena pessoas por horário de entrada (quem chega antes, sai antes)
        pessoas.sort(key=lambda x: x['entrada'])

        ultimo_fim_intervalo = None

        for pessoa in pessoas:
            entrada = pessoa['entrada']
            saida = pessoa['saida']

            # Definição da Janela Válida para sair:
            # Mínimo: Entrada + 2h (evita sair logo que chega)
            # Máximo: Entrada + 5h (Limite legal para início do descanso)
            janela_inicio = entrada + timedelta(hours=2)
            janela_fim_limite = entrada + timedelta(hours=MAX_HORAS_SEM_PAUSA)

            # Define o início proposto
            # Tenta o mais cedo possível (janela_inicio), mas respeitando a fila (ultimo_fim_intervalo)
            proposta_inicio = janela_inicio

            if ultimo_fim_intervalo and ultimo_fim_intervalo > proposta_inicio:
                proposta_inicio = ultimo_fim_intervalo

            proposta_fim = proposta_inicio + timedelta(hours=DURACAO_INTERVALO)

            # Regra: Bloqueio de Pico (Apenas Sábado e Domingo)
            if dia_semana_iso in [6, 7]: # 6=Sábado, 7=Domingo
                bloqueio_ini = datetime.combine(entrada.date(), datetime.strptime(HORA_BLOQUEIO_INICIO, "%H:%M").time())
                bloqueio_fim = datetime.combine(entrada.date(), datetime.strptime(HORA_BLOQUEIO_FIM, "%H:%M").time())

                # Verifica se o intervalo proposto colide com o horário de pico
                if (proposta_inicio < bloqueio_fim) and (proposta_fim > bloqueio_ini):
                    # Se colidir, empurra o intervalo para DEPOIS do pico
                    proposta_inicio = bloqueio_fim
                    proposta_fim = proposta_inicio + timedelta(hours=DURACAO_INTERVALO)

            # Validação Final: Estouro das 5h
            if proposta_inicio > janela_fim_limite:
                log_erros.append(f"❌ Conflito em '{setor}': {pessoa['nome']} passaria de 5h sem pausa para respeitar a fila/pico. Ajuste manual necessário.")
                continue

            # Validação Final: Término do Expediente
            if proposta_fim > saida:
                log_erros.append(f"⚠️ {pessoa['nome']} tem turno curto demais para encaixar o intervalo proposto.")
                continue

            # Se passou em tudo, registra a sugestão
            sugestoes[pessoa['id_posicao']] = (proposta_inicio, proposta_fim)
            ultimo_fim_intervalo = proposta_fim

    return sugestoes, log_erros

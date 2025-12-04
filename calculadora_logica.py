from datetime import datetime, timedelta

import database
from datetime import datetime, timedelta

# --- Regras de Negócio Configuráveis (agora dinâmicas) ---

# Setores que NÃO precisam de cobertura (podem sair para intervalo mesmo estando sozinhos)
SETORES_SOLO_PERMITIDO = ["Buffet", "Limpeza", "Camara Fria"]

def calcular_intervalos_automaticos(dados_escala, dia_semana_iso):
    """
    Calcula os horários de intervalo baseados nas regras de fluxo e CLT,
    lendo os parâmetros dinamicamente do banco de dados.
    """
    # 1. Carregar Configurações Dinâmicas
    config_global = database.buscar_configuracoes_escala()
    config_pico = database.listar_configuracoes_pico_diario() # Busca o pico para todos os 7 dias
    
    # 1.1. Busca o pico específico para o dia de hoje
    pico_hoje = next((p for p in config_pico if p.DiaSemanaID == dia_semana_iso), None)

    if not config_global:
        # Fallback se o banco não estiver disponível (usa valores padrão)
        MAX_HORAS_SEM_PAUSA = 5
        DURACAO_INTERVALO = 1 
    else:
        MAX_HORAS_SEM_PAUSA = config_global.MaxHorasSemPausa
        DURACAO_INTERVALO = config_global.DuracaoIntervalo # horas (assumindo que vem como int/float)
        
    # 1.2. Define o pico de hoje (usando None se não houver)
    HORA_BLOQUEIO_INICIO = str(pico_hoje.HoraBloqueioInicio)[:5] if pico_hoje and pico_hoje.HoraBloqueioInicio else None
    HORA_BLOQUEIO_FIM = str(pico_hoje.HoraBloqueioFim)[:5] if pico_hoje and pico_hoje.HoraBloqueioFim else None

    log_erros = []
    sugestoes = {} # {posicao_id: (inicio_intervalo, fim_intervalo)}

    # 2. Agrupar funcionários por Setor
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

        # Regra: Setor não pode ficar sozinho
        # EXCEÇÃO: Se o setor estiver na lista de permitidos (ex: Buffet, Limpeza), ignora essa regra.
        if len(pessoas) < 2 and setor not in SETORES_SOLO_PERMITIDO:
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

            # Regra: Bloqueio de Pico (AGORA DINÂMICO POR DIA)
            if HORA_BLOQUEIO_INICIO and HORA_BLOQUEIO_FIM: 
                # Se há horários definidos para HOJE, aplica o bloqueio.
                try:
                    bloqueio_ini = datetime.combine(entrada.date(), datetime.strptime(HORA_BLOQUEIO_INICIO, "%H:%M").time())
                    bloqueio_fim = datetime.combine(entrada.date(), datetime.strptime(HORA_BLOQUEIO_FIM, "%H:%M").time())

                    # Verifica se o intervalo proposto colide com o horário de pico
                    if (proposta_inicio < bloqueio_fim) and (proposta_fim > bloqueio_ini):
                        # Se colidir, empurra o intervalo para DEPOIS do pico
                        proposta_inicio = bloqueio_fim
                        # Usamos o parâmetro dinâmico DURACAO_INTERVALO
                        proposta_fim = proposta_inicio + timedelta(hours=DURACAO_INTERVALO)
                except ValueError:
                    log_erros.append(f"❌ Erro de formato nos horários de pico (Conf. Dia {dia_semana_iso}). Verifique as configurações.")

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

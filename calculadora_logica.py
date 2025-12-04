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
    
    # Tenta buscar as configurações globais ou usa fallback
    config_global = database.buscar_configuracoes_escala()
    MAX_HORAS_SEM_PAUSA = getattr(config_global, 'MaxHorasSemPausa', 5)
    DURACAO_INTERVALO = getattr(config_global, 'DuracaoIntervalo', 1) 
    
    # Busca as configurações de pico diário
    config_pico = database.listar_configuracoes_pico_diario() 
    
    # 1.1. Busca o pico específico para o dia de hoje
    pico_hoje = next((p for p in config_pico if p.DiaSemanaID == dia_semana_iso), None)
        
    # 1.2. Define o pico de hoje (usando None se não houver)
    # Garante que, se for objeto de tempo, use o formato HH:MM
    h_ini_obj = pico_hoje.HoraBloqueioInicio if pico_hoje else None
    h_fim_obj = pico_hoje.HoraBloqueioFim if pico_hoje else None

    # HORA_BLOQUEIO_INICIO agora armazena o objeto de tempo (ou None)
    HORA_BLOQUEIO_INICIO = h_ini_obj
    HORA_BLOQUEIO_FIM = h_fim_obj

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
            # Mínimo: Entrada + 3h (Ajuste de preferência: trabalhar pelo menos 3h antes do intervalo)
            # Máximo: Entrada + 5h (Limite legal para início do descanso)
            janela_inicio = entrada + timedelta(hours=3)
            janela_fim_limite = entrada + timedelta(hours=MAX_HORAS_SEM_PAUSA)

            # Define o início proposto
            # Tenta o mais cedo possível (janela_inicio), mas respeitando a fila (ultimo_fim_intervalo)
            proposta_inicio = janela_inicio

            if ultimo_fim_intervalo and ultimo_fim_intervalo > proposta_inicio:
                proposta_inicio = ultimo_fim_intervalo

            proposta_fim = proposta_inicio + timedelta(hours=DURACAO_INTERVALO)

            # Regra: Bloqueio de Pico (AGORA DINÂMICO POR DIA)
            if HORA_BLOQUEIO_INICIO and HORA_BLOQUEIO_FIM: 
                try:
                    bloqueio_ini = datetime.combine(entrada.date(), HORA_BLOQUEIO_INICIO)
                    bloqueio_fim = datetime.combine(entrada.date(), HORA_BLOQUEIO_FIM)

                    if (proposta_inicio < bloqueio_fim) and (proposta_fim > bloqueio_ini):
                        proposta_inicio = bloqueio_fim
                        proposta_fim = proposta_inicio + timedelta(hours=DURACAO_INTERVALO)
                except Exception as e:
                    log_erros.append(f"❌ Erro ao aplicar pico. Detalhe: {e}")

            # --- NOVA REGRA: VERIFICAÇÃO DE COBERTURA REAL ---
            tem_cobertura = False
            
            # Se o setor permite ficar sozinho (ex: Limpeza), tem cobertura automática
            if setor in SETORES_SOLO_PERMITIDO:
                tem_cobertura = True
            else:
                # Verifica se existe ALGUM colega presente durante todo o intervalo proposto
                for colega in pessoas:
                    if colega['id_posicao'] == pessoa['id_posicao']:
                        continue # Não conta a si mesmo

                    # O colega precisa ter chegado ANTES do início do intervalo
                    # E precisa sair DEPOIS do fim do intervalo
                    if colega['entrada'] <= proposta_inicio and colega['saida'] >= proposta_fim:
                        tem_cobertura = True
                        break # Achou um, já basta
            
            if not tem_cobertura:
                hora_formatada = proposta_inicio.strftime('%H:%M')
                log_erros.append(f"⚠️ Intervalo de {pessoa['nome']} ({hora_formatada}) cancelado: O setor '{setor}' ficaria vazio neste horário (sem cobertura).")
                continue # Pula este agendamento
            # ------------------------------------------------

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

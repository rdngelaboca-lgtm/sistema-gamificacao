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
        logger.error(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
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


import pyodbc
from datetime import datetime, date, timedelta 
import calendar 
import hashlib
import config 
import notificador_telegram
import logging
import random


CONNECTION_STRING = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"  
    f"SERVER={config.DB_SERVER};"
    f"DATABASE={config.DB_DATABASE};"
    f"UID={config.DB_UID};"
    f"PWD={config.DB_PWD};"
    f"TrustServerCertificate=yes;"
)


def get_db_connection():
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
        return conn
    except pyodbc.Error as ex:
        logger.critical(f"FALHA CRÍTICA na conexão com o banco de dados: {ex}", exc_info=True) # Usamos critical e exc_info para detalhes
        return None

def buscar_proximos_agendamentos(limite=5):
    """Busca os próximos 'limite' agendamentos a partir de hoje."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Query otimizada para buscar apenas os próximos 'limite' agendamentos
            # Usando CAST para garantir que GETDATE() compare apenas a data
            # Adicionado tratamento para StatusAgendamento (ex: 'Confirmado')
            sql = f"""
                SELECT TOP ({int(limite)})
                    A.NomeCliente, A.TipoEvento, A.DataEvento, A.TelefoneCliente -- Adicionado Telefone
                FROM Agendamentos A
                WHERE A.DataEvento >= CAST(GETDATE() AS DATE) -- Apenas agendamentos futuros (a partir de hoje)
                  AND A.StatusAgendamento = 'Confirmado' -- Apenas confirmados (ou ajuste conforme necessário)
                ORDER BY A.DataEvento ASC
            """
            cursor.execute(sql)
            cols = [column[0] for column in cursor.description]
            agendamentos = []
            for row in cursor.fetchall():
                ag_dict = dict(zip(cols, row))
                # Formata a data/hora para o JS (dd/mm/yyyy HH:MM)
                ag_dict['data_evento'] = ag_dict['DataEvento'].strftime('%d/%m/%Y %H:%M')
                # Renomeia as chaves para corresponder ao JS (se necessário, mas o JS será ajustado)
                ag_dict['nome_cliente'] = ag_dict.pop('NomeCliente')
                ag_dict['tipo_evento'] = ag_dict.pop('TipoEvento')
                ag_dict['telefone_cliente'] = ag_dict.pop('TelefoneCliente') # Adicionado
                del ag_dict['DataEvento'] # Remove a chave original
                agendamentos.append(ag_dict)
            return agendamentos
        except Exception as e:
            logger.error(f"Erro ao buscar próximos agendamentos: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []


def criar_agendamento(dados_agendamento):
    """(VERSÃO FINAL CORRIGIDA) Insere um novo agendamento e RETORNA o ID criado."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO Agendamentos 
                (NomeCliente, CPFCliente, TelefoneCliente, TipoEvento, DataEvento, 
                 StatusAgendamento, StatusPagamento, FuncionarioID, Observacoes) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql,
                         dados_agendamento['nome_cliente'],
                         dados_agendamento.get('cpf_cliente'),
                         dados_agendamento.get('telefone_cliente'),
                         dados_agendamento['tipo_evento'],
                         dados_agendamento['data_evento'],
                         'Confirmado', 'Pendente',
                         dados_agendamento['funcionario_id'],
                         dados_agendamento.get('observacoes'))
            
            cursor.nextset()
            
            novo_id = cursor.fetchone()[0]
            conn.commit()
            return True, novo_id
        except Exception as e:
            logger.error(f"ERRO ao criar agendamento: {e}")
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()
    return False, "Não foi possível conectar ao banco de dados."

def listar_agendamentos():
    """Retorna uma lista de todos os agendamentos."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT A.*, F.NomeCompleto AS NomeFuncionario
                FROM Agendamentos A JOIN Funcionarios F ON A.FuncionarioID = F.FuncionarioID
                ORDER BY A.DataEvento ASC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_agendamento_por_id(agendamento_id):
    """Busca todos os detalhes de um único agendamento pelo seu ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT A.*, F.NomeCompleto AS NomeFuncionario
                FROM Agendamentos A JOIN Funcionarios F ON A.FuncionarioID = F.FuncionarioID
                WHERE A.AgendamentoID = ?
            """
            cursor.execute(sql, agendamento_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def atualizar_agendamento(agendamento_id, dados_agendamento):
    """Atualiza um agendamento existente com novos dados."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE Agendamentos SET
                    NomeCliente = ?, CPFCliente = ?, TelefoneCliente = ?, TipoEvento = ?,
                    DataEvento = ?, StatusAgendamento = ?, StatusPagamento = ?,
                    FuncionarioID = ?, Observacoes = ?
                WHERE AgendamentoID = ?
            """
            # <<< A CORREÇÃO DA ORDEM ESTÁ AQUI >>>
            cursor.execute(sql,
                         dados_agendamento['nome_cliente'],
                         dados_agendamento.get('cpf_cliente'),
                         dados_agendamento.get('telefone_cliente'),
                         dados_agendamento['tipo_evento'],
                         dados_agendamento['data_evento'], # <-- Formato AAAA-MM-DD
                         dados_agendamento.get('status_agendamento', 'Confirmado'),
                         dados_agendamento.get('status_pagamento', 'Pendente'),
                         dados_agendamento['funcionario_id'],
                         dados_agendamento.get('observacoes'),
                         agendamento_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao atualizar agendamento: {e}")
            conn.rollback() # Adicionado por segurança
            return False
        finally:
            conn.close()
    return False

def excluir_agendamento(agendamento_id):
    """Exclui um agendamento do banco de dados."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM Agendamentos WHERE AgendamentoID = ?"
            cursor.execute(sql, agendamento_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao excluir agendamento: {e}")
            return False
        finally:
            conn.close()
    return False

def atualizar_status_pagamento(agendamento_id, novo_status):
    """Atualiza apenas o status de pagamento de um agendamento."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Agendamentos SET StatusPagamento = ? WHERE AgendamentoID = ?"
            cursor.execute(sql, novo_status, agendamento_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao atualizar status de pagamento: {e}")
            return False
        finally:
            conn.close()
    return False

def buscar_agendamentos_para_periodo(data_inicio, data_fim):
    """
    Busca agendamentos cuja DataEvento esteja DENTRO de um período específico (inclusive).
    (Esta função estava faltando e foi adicionada para o agendador_lembretes.py).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Adiciona uma cláusula WHERE para filtrar entre data_inicio e data_fim.
            # Usa CAST(DataEvento AS DATE) para ignorar a hora na comparação de datas.
            sql = """
                SELECT A.*, F.NomeCompleto AS NomeFuncionario
                FROM Agendamentos A 
                JOIN Funcionarios F ON A.FuncionarioID = F.FuncionarioID
                WHERE CAST(A.DataEvento AS DATE) BETWEEN ? AND ?
                ORDER BY A.DataEvento ASC
            """
            cursor.execute(sql, data_inicio, data_fim)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao buscar agendamentos por período: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []

# --- Nova Função para a Opção "Não Aplicável" ---
def registrar_tarefa_nao_aplicavel(atribuicao_id, justificativa):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Primeiro, precisamos buscar os IDs da tarefa e do funcionário a partir da atribuição
            sql_busca = "SELECT TarefaID, FuncionarioID FROM TarefasAtribuidas WHERE AtribuicaoID = ?"
            cursor.execute(sql_busca, atribuicao_id)
            resultado = cursor.fetchone()
            if resultado:
                tarefa_id, funcionario_id = resultado
                # Agora, inserimos na tabela de Entregas com status especial
                sql_insert = """
                    INSERT INTO Entregas 
                    (TarefaID, FuncionarioID, AtribuicaoID, StatusValidacao, PontosGanhos, MotivoRecusa, DataEnvio)
                    VALUES (?, ?, ?, 'Aprovada', 0, ?, GETDATE())
                """
                cursor.execute(sql_insert, tarefa_id, funcionario_id, atribuicao_id, f"Não aplicável: {justificativa}")
                conn.commit()
        finally:
            conn.close()

def atualizar_funcionario(funcionario_id, nome, chat_id, cargo, horario_notificacao, dia_folga, verificador_cpf): # 1. Novo parâmetro
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE Funcionarios 
                SET NomeCompleto = ?, ChatIDTelegram = ?, Cargo = ?, HorarioNotificacao = ?, DiaDeFolga = ?, VerificadorCPF = ? -- 2. Nova coluna
                WHERE FuncionarioID = ?
            """
            cursor.execute(sql, nome, chat_id, cargo, horario_notificacao, dia_folga, verificador_cpf, funcionario_id) # 3. Novo valor
            conn.commit()
        finally:
            conn.close()

# Em database.py, esta é a ÚNICA versão da função que deve existir no seu código.

def listar_funcionarios_por_tarefa(tarefa_id):
    """
    Retorna duas listas de funcionários: os que JÁ ESTÃO atribuídos a uma tarefa ATIVA
    e os que AINDA NÃO ESTÃO. (VERSÃO FINAL E CORRETA)
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Pergunta 1: Quem JÁ tem essa tarefa ATIVA?
            # A query verifica se a tarefa não foi encerrada (DataFimVigencia IS NULL).
            sql_atribuidos = """
                SELECT 
                    TA.AtribuicaoID, F.NomeCompleto, 
                    TA.TipoFrequencia + 
                    CASE 
                        WHEN TA.TipoFrequencia = 'Semanal' THEN ' (' + 
                            CASE TA.ValorFrequencia 
                                WHEN '1' THEN 'Dom' WHEN '2' THEN 'Seg' WHEN '3' THEN 'Ter'
                                WHEN '4' THEN 'Qua' WHEN '5' THEN 'Qui' WHEN '6' THEN 'Sex'
                                WHEN '7' THEN 'Sab'
                            END + ')'
                        WHEN TA.TipoFrequencia = 'Mensal' THEN ' (Dia ' + CAST(TA.ValorFrequencia AS VARCHAR) + ')'
                        ELSE '' 
                    END AS FrequenciaCompleta
                FROM Funcionarios F
                JOIN TarefasAtribuidaS TA ON F.FuncionarioID = TA.FuncionarioID
                WHERE TA.TarefaID = ? AND TA.DataFimVigencia IS NULL
                ORDER BY F.NomeCompleto
            """
            cursor.execute(sql_atribuidos, tarefa_id)
            atribuidos = cursor.fetchall()
            
            # Pergunta 2: Quem AINDA NÃO tem essa tarefa ATIVA?
            # A subquery ignora tarefas que já foram encerradas.
            sql_disponiveis = """
                SELECT * FROM Funcionarios F
                WHERE NOT EXISTS (
                    SELECT 1 FROM TarefasAtribuidas TA
                    WHERE TA.TarefaID = ? AND TA.FuncionarioID = F.FuncionarioID AND TA.DataFimVigencia IS NULL
                )
                ORDER BY F.NomeCompleto
            """
            cursor.execute(sql_disponiveis, tarefa_id)
            disponiveis = cursor.fetchall()
            
            return atribuidos, disponiveis
        finally:
            conn.close()
    return [], []    

 ### ADICIONE ESTA FUNÇÃO AO SEU ARQUIVO database.py ###

def buscar_funcionarios_por_horario(horario_atual):
    """Busca funcionários para notificação de início, RESPEITANDO O DIA DE FOLGA."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A NOVA REGRA: AND (DiaDeFolga = 0 OR DiaDeFolga != DATEPART(weekday, GETDATE()))
            sql = """
                SELECT * FROM Funcionarios 
                WHERE CONVERT(VARCHAR(5), HorarioNotificacao, 108) = ?
                AND (DiaDeFolga = 0 OR DiaDeFolga != DATEPART(weekday, GETDATE()))
            """
            cursor.execute(sql, horario_atual)
            return cursor.fetchall()
        finally:
            conn.close()
    return []         

# Em database.py, SUBSTITUA a função listar_tarefas_do_dia_por_funcionario:
def listar_tarefas_do_dia_por_funcionario(funcionario_id):
    """
    (VERSÃO 7 - COM CORREÇÃO PARA TAREFAS 'Unica')
    Busca todas as tarefas do dia, agora incluindo as tarefas únicas aceitas de folgas.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    TA.AtribuicaoID, T.TarefaID, T.Titulo, T.Pontos, TA.TipoFrequencia AS Tipo,
                    ISNULL(TA.DescricaoOverride, T.Descricao) AS Descricao
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE
                    TA.FuncionarioID = ? AND TA.DataFimVigencia IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM Entregas E
                        WHERE E.AtribuicaoID = TA.AtribuicaoID
                        AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE())
                        AND E.StatusValidacao IN ('Aprovada', 'Pendente') -- Exclui Aprovada ou Pendente HOJE
                    )
                    AND (
                        -- Condições existentes para Diaria, Semanal, Mensal, Agendada
                        TA.TipoFrequencia = 'Diaria'
                        OR (
                            TA.TipoFrequencia = 'Semanal' AND
                            CAST(TA.ValorFrequencia AS INT) =
                                CASE DATENAME(weekday, GETDATE())
                                    WHEN 'Sunday' THEN 1 WHEN 'Domingo' THEN 1
                                    WHEN 'Monday' THEN 2 WHEN 'Segunda-feira' THEN 2
                                    WHEN 'Tuesday' THEN 3 WHEN 'Terça-feira' THEN 3
                                    WHEN 'Wednesday' THEN 4 WHEN 'Quarta-feira' THEN 4
                                    WHEN 'Thursday' THEN 5 WHEN 'Quinta-feira' THEN 5
                                    WHEN 'Friday' THEN 6 WHEN 'Sexta-feira' THEN 6
                                    WHEN 'Saturday' THEN 7 WHEN 'Sábado' THEN 7
                                END
                        )
                        OR (TA.TipoFrequencia = 'Mensal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(day, GETDATE()))
                        OR (TA.DataAgendamento IS NOT NULL AND CONVERT(date, TA.DataAgendamento) = CONVERT(date, GETDATE()))

                        -- --- A CORREÇÃO ESTÁ AQUI ---
                        -- Adicionamos a condição para incluir tarefas do tipo 'Unica' que foram criadas HOJE.
                        OR (TA.TipoFrequencia = 'Unica' AND CONVERT(date, TA.DataInicioVigencia) = CONVERT(date, GETDATE()))
                        -- --- FIM DA CORREÇÃO ---
                    )
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        except Exception as e:
            # Log aprimorado
            logger.exception(f"!!! ERRO CRÍTICO em listar_tarefas_do_dia_por_funcionario para ID {funcionario_id}: {e}")
            return []
        finally:
            if conn:
                conn.close()
    return []

def adicionar_funcionario(nome, chat_id, cargo, horario_notificacao, dia_folga):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO Funcionarios (NomeCompleto, ChatIDTelegram, Cargo, HorarioNotificacao, DiaDeFolga) VALUES (?, ?, ?, ?, ?)"
            cursor.execute(sql, nome, chat_id, cargo, horario_notificacao, dia_folga)
            conn.commit()
        finally: 
            conn.close()

def listar_funcionarios():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "SELECT * FROM Funcionarios ORDER BY NomeCompleto"; cursor.execute(sql); return cursor.fetchall()
        finally: conn.close()
    return []
def buscar_funcionario_por_chat_id(chat_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "SELECT * FROM Funcionarios WHERE ChatIDTelegram = ?"; cursor.execute(sql, str(chat_id)); return cursor.fetchone()
        finally: conn.close()
    return None

def buscar_funcionario_por_id(funcionario_id):
    """Busca um funcionário pelo seu ID (chave primária)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM Funcionarios WHERE FuncionarioID = ?"
            cursor.execute(sql, funcionario_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def excluir_funcionario(funcionario_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "DELETE FROM Funcionarios WHERE FuncionarioID = ?"; cursor.execute(sql, funcionario_id); conn.commit()
        finally: conn.close()
def obter_historico_funcionario(funcionario_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT T.Titulo, TA.DataAtribuicao, E.DataEnvio, ISNULL(E.StatusValidacao, 'Pendente (Não Entregue)') AS Status, E.PontosGanhos, E.MotivoRecusa
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                LEFT JOIN Entregas E ON TA.AtribuicaoID = E.AtribuicaoID
                WHERE TA.FuncionarioID = ? ORDER BY TA.DataAtribuicao DESC
            """
            cursor.execute(sql, funcionario_id); return cursor.fetchall()
        finally: conn.close()
    return []

def criar_tarefa(titulo, descricao, pontos, setor): # Adicionamos 'setor'
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Adicionamos a coluna Setor ao INSERT
            sql = "INSERT INTO Tarefas (Titulo, Descricao, Pontos, Setor) VALUES (?, ?, ?, ?)"
            cursor.execute(sql, titulo, descricao, pontos, setor) # Adicionamos 'setor' aos parâmetros
            conn.commit()
        finally: conn.close()

def atualizar_tarefa(tarefa_id, titulo, descricao, pontos, setor): # 1. Adicionado 'setor' aqui
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 2. Adicionado 'Setor = ?' ao comando SQL
            sql = "UPDATE Tarefas SET Titulo = ?, Descricao = ?, Pontos = ?, Setor = ? WHERE TarefaID = ?"
            # 3. Adicionado 'setor' na lista de parâmetros a serem executados
            cursor.execute(sql, titulo, descricao, pontos, setor, tarefa_id)
            conn.commit()
        finally: conn.close()

def excluir_tarefa(tarefa_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "DELETE FROM Tarefas WHERE TarefaID = ?"; cursor.execute(sql, tarefa_id); conn.commit()
        finally: conn.close()
def listar_todas_as_tarefas():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "SELECT * FROM Tarefas ORDER BY Titulo"; cursor.execute(sql); return cursor.fetchall()
        finally: conn.close()
    return []
def buscar_tarefa_por_atribuicao(atribuicao_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "SELECT T.* FROM Tarefas T JOIN TarefasAtribuidas TA ON T.TarefaID = TA.TarefaID WHERE TA.AtribuicaoID = ?"; cursor.execute(sql, atribuicao_id); return cursor.fetchone()
        finally: conn.close()
    return None
# Em database.py, SUBSTITUA a função existente por esta:

# Em database.py, SUBSTITUA a função listar_tarefas_para_atribuicao por esta:

def listar_tarefas_para_atribuicao(filtro_setor=None):
    """
    (VERSÃO CORRIGIDA - SEMPRE MOSTRA TODOS OS MODELOS)
    Retorna uma lista de TODOS os modelos de tarefa do catálogo.
    Se um 'filtro_setor' for fornecido, retorna apenas tarefas daquele setor.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # REMOVEMOS A CLÁUSULA WHERE NOT EXISTS COMPLETAMENTE
            sql = "SELECT T.* FROM Tarefas T"

            params = [] # Lista para guardar os parâmetros da consulta

            # Adicionamos a cláusula WHERE do filtro (SE HOUVER FILTRO)
            where_clauses = []
            if filtro_setor:
                if filtro_setor == "Outras Tarefas":
                     where_clauses.append("(T.Setor IS NULL OR T.Setor = '')")
                else:
                    where_clauses.append("T.Setor = ?")
                    params.append(filtro_setor)

            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)

            # O final da consulta também é o mesmo
            sql += " ORDER BY ISNULL(T.Setor, 'Z-Sem Setor'), T.Titulo"

            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def atribuir_tarefa_recorrente_para_grupo(tarefa_id, grupo_id, tipo_frequencia, valor_frequencia):
    """
    Cria uma nova atribuição de tarefa para um GRUPO inteiro.
    O FuncionarioID fica NULO neste caso.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO TarefasAtribuidas 
                (TarefaID, GrupoID, TipoFrequencia, ValorFrequencia) 
                VALUES (?, ?, ?, ?)
            """
            cursor.execute(sql, tarefa_id, grupo_id, tipo_frequencia, valor_frequencia)
            conn.commit()
        finally:
            conn.close()

# Em database.py, substitua a função 'atribuir_tarefa' por esta:

def atribuir_tarefa(tarefa_id, funcionario_id, tipo_frequencia, valor_frequencia, descricao_override=None, data_agendamento=None, agendamento_id=None):
    """Função universal para atribuir tarefas. AGORA RETORNA O NOVO ID DA ATRIBUIÇÃO."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO TarefasAtribuidas 
                (TarefaID, FuncionarioID, TipoFrequencia, ValorFrequencia, DataInicioVigencia, DescricaoOverride, DataAgendamento, AgendamentoID) 
                VALUES (?, ?, ?, ?, GETDATE(), ?, ?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, tarefa_id, funcionario_id, tipo_frequencia, valor_frequencia, descricao_override, data_agendamento, agendamento_id)
            
            # --- ADIÇÃO IMPORTANTE ---
            cursor.nextset()
            novo_atribuicao_id = cursor.fetchone()[0]
            conn.commit()
            return novo_atribuicao_id # Retorna o ID que acabamos de criar
            # --- FIM DA ADIÇÃO ---
            
        finally:
            conn.close()
    return None # Retorna None em caso de falha


def encerrar_atribuicao_tarefa(atribuicao_id):
    """
    NÃO DELETA a atribuição. Em vez disso, define a DataFimVigencia para hoje,
    encerrando a validade da tarefa e preservando o histórico.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A mágica está aqui: de DELETE para UPDATE!
            sql = "UPDATE TarefasAtribuidas SET DataFimVigencia = GETDATE() WHERE AtribuicaoID = ?"
            cursor.execute(sql, atribuicao_id)
            conn.commit()
            logger.info(f"Atribuição {atribuicao_id} encerrada com sucesso.")
        except Exception as e:
            print(f"--> [DATABASE.PY] ERRO ao encerrar a AtribuiçãoID {atribuicao_id}: {e}")
        finally:
            conn.close()

def verificar_atribuicao_especifica_existente(tarefa_id, funcionario_id, tipo_frequencia, valor_frequencia):
    """
    Verifica se uma atribuição ATIVA e EXATA (mesma tarefa, func, freq e valor) já existe.
    Retorna True se existir, False caso contrário.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT COUNT(1) 
                FROM TarefasAtribuidas 
                WHERE TarefaID = ? 
                  AND FuncionarioID = ? 
                  AND TipoFrequencia = ?
                  AND ValorFrequencia = ?
                  AND DataFimVigencia IS NULL
            """
            # Para 'Diaria' ou 'Unica', o valor_frequencia é None, o SQL precisa ser 'IS NULL'
            if valor_frequencia is None:
                sql = """
                    SELECT COUNT(1) 
                    FROM TarefasAtribuidas 
                    WHERE TarefaID = ? 
                      AND FuncionarioID = ? 
                      AND TipoFrequencia = ?
                      AND ValorFrequencia IS NULL
                      AND DataFimVigencia IS NULL
                """
                cursor.execute(sql, tarefa_id, funcionario_id, tipo_frequencia)
            else:
                cursor.execute(sql, tarefa_id, funcionario_id, tipo_frequencia, valor_frequencia)

            return cursor.fetchone()[0] > 0
        except Exception as e:
            logger.error(f"Erro ao verificar atribuição específica: {e}", exc_info=True)
            return True # Assume que existe para evitar falha
        finally:
            conn.close()
    return True # Assume que existe para evitar falha

def verificar_atribuicao_existente(tarefa_id, funcionario_id):
    """
    Verifica se já existe uma atribuição ATIVA (sem data de fim)
    para uma combinação de tarefa e funcionário.
    Retorna True se existir, False caso contrário.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT COUNT(1) 
                FROM TarefasAtribuidas 
                WHERE TarefaID = ? 
                  AND FuncionarioID = ? 
                  AND DataFimVigencia IS NULL
            """
            cursor.execute(sql, tarefa_id, funcionario_id)
            # Se a contagem for maior que 0, significa que já existe.
            return cursor.fetchone()[0] > 0
        finally:
            conn.close()
    return False

# Em database.py, SUBSTITUA a função registrar_entrega pela versão abaixo:

def registrar_entrega(tarefa_id, funcionario_id, path_foto, atribuicao_id=None):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # SQL CORRIGIDO: Agora inserimos a data e hora exata do envio.
            sql = """
                INSERT INTO Entregas 
                (TarefaID, FuncionarioID, PathFotoEvidencia, AtribuicaoID, DataEnvio) 
                VALUES (?, ?, ?, ?, GETDATE()); 
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, tarefa_id, funcionario_id, path_foto, atribuicao_id)
            cursor.nextset() 
            new_id = cursor.fetchone()[0]
            conn.commit()
            return new_id
        finally: 
            conn.close()
    return None

# Em database.py, SUBSTITUA a função antiga por esta versão completa e corrigida:

def listar_atribuicoes_ativas():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # O SQL foi atualizado com uma nova regra na cláusula WHERE
            sql = """
                SELECT 
                    TA.AtribuicaoID, 
                    ISNULL(F.NomeCompleto, G.NomeGrupo + ' (Grupo)') AS Alvo,
                    T.Titulo, 
                    TA.TipoFrequencia + 
                    CASE 
                        WHEN TA.TipoFrequencia = 'Semanal' THEN ' (' + 
                            CASE TA.ValorFrequencia 
                                WHEN '1' THEN 'Dom' WHEN '2' THEN 'Seg' WHEN '3' THEN 'Ter'
                                WHEN '4' THEN 'Qua' WHEN '5' THEN 'Qui' WHEN '6' THEN 'Sex'
                                WHEN '7' THEN 'Sab'
                            END + ')'
                        WHEN TA.TipoFrequencia = 'Mensal' THEN ' (Dia ' + CAST(TA.ValorFrequencia AS VARCHAR) + ')'
                        WHEN TA.TipoFrequencia = 'GrupoCompetitiva' THEN ' (às ' + CONVERT(VARCHAR(5), TA.HorarioDisparo, 108) + ')'
                        ELSE '' 
                    END AS FrequenciaCompleta
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                LEFT JOIN Funcionarios F ON TA.FuncionarioID = F.FuncionarioID
                LEFT JOIN Grupos G ON TA.GrupoID = G.GrupoID
                WHERE
                    -- Regra 1: A atribuição não pode ter sido encerrada manualmente.
                    TA.DataFimVigencia IS NULL
                    -- E AQUI ESTÁ A NOVA REGRA INTELIGENTE:
                    AND NOT (
                        TA.TipoFrequencia = 'Unica' AND EXISTS (
                            SELECT 1 FROM Entregas E
                            WHERE E.AtribuicaoID = TA.AtribuicaoID AND E.StatusValidacao = 'Aprovada'
                        )
                    )
                ORDER BY Alvo, T.Titulo
            """
            cursor.execute(sql)
            rows_do_banco = cursor.fetchall()
            resultados_em_tupla = [tuple(row) for row in rows_do_banco]
            return resultados_em_tupla
        finally:
            conn.close()
    return []

def listar_entregas_pendentes():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT E.EntregaID, E.PathFotoEvidencia, E.FuncionarioID, F.NomeCompleto, F.ChatIDTelegram, T.Titulo, T.Pontos
                FROM Entregas E JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID JOIN Tarefas T ON E.TarefaID = T.TarefaID
                WHERE E.StatusValidacao = 'Pendente' ORDER BY E.DataEnvio ASC
            """
            cursor.execute(sql); return cursor.fetchall()
        finally: conn.close()
    return []
# Em database.py, substitua a função antiga por esta versão mais simples e correta:

# Em database.py, SUBSTITUA a função aprovar_entrega por esta:

def aprovar_entrega(entrega_id, funcionario_id, pontos):
    """
    (VERSÃO CORRIGIDA - NÃO SOBRESCREVE DataEnvio)
    Aprova uma entrega, registra os pontos, ADICIONA OS PONTOS AO SALDO GERAL,
    verifica conquistas e garante rollback em caso de erro.
    """
    conn = get_db_connection()
    if not conn:
        logger.error(f"Falha de conexão ao tentar aprovar entrega {entrega_id}.")
        return [] # Retorna lista vazia indicando falha

    novas_conquistas = [] # Inicializa fora do try

    try:
        cursor = conn.cursor()

        # --- CORREÇÃO APLICADA AQUI ---
        # Removemos a atualização do DataEnvio. Agora, apenas o status e os pontos são definidos.
        # O DataEnvio original (do momento da submissão) é preservado.
        # (Opcional: Adicionar "DataValidacao = GETDATE()" se a coluna existir)
        sql_update_entrega = """
            UPDATE Entregas 
            SET StatusValidacao = 'Aprovada', PontosGanhos = ?
            WHERE EntregaID = ?
        """
        # --- FIM DA CORREÇÃO ---

        cursor.execute(sql_update_entrega, pontos, entrega_id)
        logger.debug(f"UPDATE Entregas executado para EntregaID {entrega_id}.")


        # 2. Adiciona os pontos ao saldo (delegação para função com seu próprio tratamento)
        adicionar_pontos_ao_saldo(funcionario_id, pontos)
        logger.debug(f"adicionar_pontos_ao_saldo chamado para FuncionarioID {funcionario_id} com {pontos} pontos.")

        # 3. Commita as operações da entrega e saldo juntas
        conn.commit()
        logger.info(f"Entrega {entrega_id} aprovada e {pontos} pontos adicionados ao saldo de FuncionarioID {funcionario_id}. Commit realizado.")

        # 4. Verifica conquistas (após o commit principal)
        novas_conquistas = verificar_e_conceder_conquistas(funcionario_id)
        logger.debug(f"Verificação de conquistas concluída para FuncionarioID {funcionario_id}. Novas conquistas: {len(novas_conquistas)}")

    except pyodbc.Error as db_err:
        logger.exception(f"Erro de Banco de Dados Crítico ao aprovar entrega {entrega_id}. Iniciando Rollback: {db_err}")
        if conn:
            try:
                conn.rollback()
                logger.info(f"Rollback realizado com sucesso para entrega {entrega_id}.")
            except Exception as rb_err:
                logger.error(f"Erro adicional durante o rollback da entrega {entrega_id}: {rb_err}")
        novas_conquistas = [] # Garante retorno vazio em caso de erro

    except Exception as e:
        logger.exception(f"Erro inesperado ao aprovar entrega {entrega_id}. Iniciando Rollback: {e}")
        if conn:
            try:
                conn.rollback()
                logger.info(f"Rollback realizado com sucesso para entrega {entrega_id}.")
            except Exception as rb_err:
                logger.error(f"Erro adicional durante o rollback da entrega {entrega_id}: {rb_err}")
        novas_conquistas = [] # Garante retorno vazio em caso de erro

    finally:
        if conn:
            conn.close()
            logger.debug(f"Conexão do banco fechada para aprovação da entrega {entrega_id}.")

    return novas_conquistas # Retorna a lista (vazia ou não)


def recusar_entrega(entrega_id, motivo):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "UPDATE Entregas SET StatusValidacao = 'Recusada', MotivoRecusa = ? WHERE EntregaID = ?"; cursor.execute(sql, motivo, entrega_id); conn.commit()
        finally: conn.close()
def obter_ranking():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(); sql = "SELECT NomeCompleto, PontosTotal FROM Funcionarios ORDER BY PontosTotal DESC"; cursor.execute(sql); return cursor.fetchall()
        finally: conn.close()
    return []
def relatorio_pendencias(funcionario_id, data):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT T.Titulo, T.Pontos
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE TA.FuncionarioID = ?
                AND (
                    (TA.TipoFrequencia = 'Diaria' AND CONVERT(date, TA.DataAtribuicao) <= ?) OR
                    (TA.TipoFrequencia = 'Semanal' AND TA.ValorFrequencia = DATEPART(weekday, ?) AND CONVERT(date, TA.DataAtribuicao) <= ?) OR
                    (TA.TipoFrequencia = 'Mensal' AND TA.ValorFrequencia = DATEPART(day, ?) AND CONVERT(date, TA.DataAtribuicao) <= ?)
                )
                AND NOT EXISTS (
                    SELECT 1 FROM Entregas E
                    WHERE E.AtribuicaoID = TA.AtribuicaoID AND CONVERT(date, E.DataEnvio) = ?
                )
            """
            cursor.execute(sql, funcionario_id, data, data, data, data, data, data); return cursor.fetchall()
        finally: conn.close()
    return []

# --- FUNÇÕES DE GERENCIAMENTO DE GRUPOS ---
def criar_grupo(nome_grupo, chat_id):
    """Cria um novo grupo na tabela Grupos."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO Grupos (NomeGrupo, ChatIDTelegram) VALUES (?, ?)"
            cursor.execute(sql, nome_grupo, chat_id)
            conn.commit()
        finally:
            conn.close()

def listar_grupos():
    """Retorna uma lista de todos os grupos."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM Grupos ORDER BY NomeGrupo"
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def atualizar_grupo(grupo_id, nome_grupo, chat_id):
    """Atualiza o nome e o ChatID de um grupo existente."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Grupos SET NomeGrupo = ?, ChatIDTelegram = ? WHERE GrupoID = ?"
            cursor.execute(sql, nome_grupo, chat_id, grupo_id)
            conn.commit()
        finally:
            conn.close()

def excluir_grupo(grupo_id):
    """Exclui um grupo. A deleção em cascata cuidará dos membros."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM Grupos WHERE GrupoID = ?"
            cursor.execute(sql, grupo_id)
            conn.commit()
        finally:
            conn.close()

def listar_membros_e_nao_membros(grupo_id):
    """Retorna duas listas: membros de um grupo e funcionários que não são membros."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Membros
            sql_membros = """
                SELECT F.FuncionarioID, F.NomeCompleto 
                FROM Funcionarios F
                JOIN FuncionariosGrupos FG ON F.FuncionarioID = FG.FuncionarioID
                WHERE FG.GrupoID = ? ORDER BY F.NomeCompleto
            """
            cursor.execute(sql_membros, grupo_id)
            membros = cursor.fetchall()
            
            # Não Membros
            sql_nao_membros = """
                SELECT F.FuncionarioID, F.NomeCompleto 
                FROM Funcionarios F
                WHERE NOT EXISTS (
                    SELECT 1 FROM FuncionariosGrupos FG
                    WHERE FG.GrupoID = ? AND FG.FuncionarioID = F.FuncionarioID
                ) ORDER BY F.NomeCompleto
            """
            cursor.execute(sql_nao_membros, grupo_id)
            nao_membros = cursor.fetchall()
            
            return membros, nao_membros
        finally:
            conn.close()
    return [], []

def adicionar_membro_ao_grupo(funcionario_id, grupo_id):
    """Adiciona um funcionário a um grupo."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO FuncionariosGrupos (FuncionarioID, GrupoID) VALUES (?, ?)"
            cursor.execute(sql, funcionario_id, grupo_id)
            conn.commit()
        finally:
            conn.close()

def remover_membro_do_grupo(funcionario_id, grupo_id):
    """Remove um funcionário de um grupo."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM FuncionariosGrupos WHERE FuncionarioID = ? AND GrupoID = ?"
            cursor.execute(sql, funcionario_id, grupo_id)
            conn.commit()
        finally:
            conn.close()

# Em database.py, ADICIONE esta nova função (pode remover a antiga 'agendar_tarefa_competitiva_para_grupo' se quiser)
def agendar_tarefa_recorrente_para_grupo(tarefa_id, grupo_id, tipo_frequencia_grupo, valor_frequencia, horario_disparo):
    """
    Agenda uma nova tarefa recorrente ('GrupoDiaria', 'GrupoSemanal', 'GrupoMensal')
    para um grupo em um horário específico, com o valor de frequência apropriado.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Usamos as colunas existentes TipoFrequencia e ValorFrequencia
            sql = """
                INSERT INTO TarefasAtribuidas
                (TarefaID, GrupoID, TipoFrequencia, ValorFrequencia, HorarioDisparo, StatusTarefaGrupo)
                VALUES (?, ?, ?, ?, ?, 'Disponivel')
            """
            # Para 'GrupoDiaria', o valor_frequencia pode ser None
            cursor.execute(sql, tarefa_id, grupo_id, tipo_frequencia_grupo, valor_frequencia, horario_disparo)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao agendar tarefa recorrente para grupo: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

# Em database.py, SUBSTITUA a função buscar_tarefas_de_grupo_para_disparar por esta versão inteligente:
def buscar_tarefas_de_grupo_para_disparar(horario_atual, dia_semana_hoje, dia_mes_hoje):
    """
    (VERSÃO FINAL - SUPORTA DIARIA/SEMANAL/MENSAL)
    Busca tarefas de grupo agendadas para o horário atual E que correspondam
    à frequência (diária, dia da semana específico ou dia do mês específico).
    'dia_semana_hoje' usa a convenção SQL (Dom=1, Seg=2, ..., Sab=7).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A query agora tem uma cláusula WHERE mais complexa
            sql = """
                SELECT TA.AtribuicaoID, T.Titulo, T.Pontos, G.NomeGrupo, G.ChatIDTelegram
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                JOIN Grupos G ON TA.GrupoID = G.GrupoID
                WHERE
                    -- Condição 1: O horário deve bater
                    CONVERT(VARCHAR(5), TA.HorarioDisparo, 108) = ?
                    -- Condição 2: E a frequência deve corresponder ao dia de hoje
                    AND (
                        -- Se for Diaria, sempre dispara
                        TA.TipoFrequencia = 'GrupoDiaria'
                        -- Ou se for Semanal E o dia da semana bate
                        OR (TA.TipoFrequencia = 'GrupoSemanal' AND TA.ValorFrequencia = ?)
                        -- Ou se for Mensal E o dia do mês bate
                        OR (TA.TipoFrequencia = 'GrupoMensal' AND TA.ValorFrequencia = ?)
                    )
            """
            cursor.execute(sql, horario_atual, dia_semana_hoje, dia_mes_hoje)
            return cursor.fetchall()
        finally:
            conn.close()
    return []


# Em database.py
def aceitar_tarefa_de_grupo(origem_atribuicao_id, funcionario_id):
    """
    (VERSÃO CORRIGIDA COM TRANSAÇÃO PARA EVITAR RACE CONDITION)
    Verifica e cria uma atribuição 'Unica' para o funcionário de forma atômica.
    Retorna o ID da NOVA atribuição criada ou None se falhar/já aceita hoje.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Inicia a transação (implícito, mas o commit/rollback é o controle)

            # 1. Buscar o TarefaID da atribuição original
            cursor.execute("SELECT TarefaID FROM TarefasAtribuidas WHERE AtribuicaoID = ?", origem_atribuicao_id)
            result = cursor.fetchone()
            if not result:
                logger.warning(f"--> [ACEITAR GRUPO] Atribuição de origem {origem_atribuicao_id} não encontrada.")
                conn.rollback() # Cancela a transação
                return None
            tarefa_id_original = result[0]

            # 2. Verificar se alguém já aceitou HOJE para esta tarefa de origem
            #    Adicionamos WITH (UPDLOCK, HOLDLOCK) para travar o resultado da verificação
            #    até que a transação seja concluída (commit ou rollback).
            sql_check = """
                SELECT AtribuicaoID
                FROM TarefasAtribuidas WITH (UPDLOCK, HOLDLOCK)
                WHERE OrigemAtribuicaoID = ?
                  AND CONVERT(date, DataAgendamento) = CONVERT(date, GETDATE())
            """
            cursor.execute(sql_check, origem_atribuicao_id)

            if cursor.fetchone():
                # Se encontrou, significa que outro processo já inseriu E COMITOU (ou este processo está esperando o lock).
                logger.info(f"--> [ACEITAR GRUPO] Tarefa de origem {origem_atribuicao_id} já foi aceita hoje (detectado pela transação).")
                conn.rollback() # Cancela a transação
                return None # Retorna None indicando que já foi pega hoje

            # 3. Se ninguém aceitou (e a tabela está travada), INSERIR a nova instância 'Unica'
            sql_insert = """
                INSERT INTO TarefasAtribuidas
                (TarefaID, FuncionarioID, TipoFrequencia, DataInicioVigencia, DataAgendamento, OrigemAtribuicaoID, StatusTarefaGrupo)
                VALUES (?, ?, 'Unica', GETDATE(), GETDATE(), ?, 'Aceita');
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql_insert, tarefa_id_original, funcionario_id, origem_atribuicao_id)
            cursor.nextset()
            nova_atribuicao_id = cursor.fetchone()[0]

            conn.commit() # Confirma a transação, liberando o lock

            logger.info(f"--> [ACEITAR GRUPO] Nova atribuição 'Unica' (ID: {nova_atribuicao_id}) criada para FuncionarioID {funcionario_id} a partir da Origem {origem_atribuicao_id}.")
            return nova_atribuicao_id # Retorna o ID da nova tarefa criada

        except Exception as e:
            logger.error(f"ERRO CRÍTICO em aceitar_tarefa_de_grupo (transacional): {e}", exc_info=True)
            if conn:
                conn.rollback() # Garante rollback em qualquer erro
            return None
        finally:
            if conn:
                conn.close()
    return None # Erro de conexão


def buscar_detalhes_da_atribuicao(atribuicao_id):
    """Busca todos os detalhes de uma tarefa (título, descrição, pontos) a partir do ID da atribuição."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT T.Titulo, T.Descricao, T.Pontos
                FROM Tarefas T
                JOIN TarefasAtribuidas TA ON T.TarefaID = TA.TarefaID
                WHERE TA.AtribuicaoID = ?
            """
            cursor.execute(sql, atribuicao_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def buscar_funcionarios_para_lembrete(horario_atual):
    """Busca funcionários para lembrete, RESPEITANDO O DIA DE FOLGA."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT * FROM Funcionarios
                WHERE
                    (DATEDIFF(minute, CONVERT(TIME, GETDATE()), CONVERT(TIME, DATEADD(HOUR, 3, HorarioNotificacao))) = 0 OR
                    DATEDIFF(minute, CONVERT(TIME, GETDATE()), CONVERT(TIME, DATEADD(HOUR, 6, HorarioNotificacao))) = 0)
                    AND (DiaDeFolga = 0 OR DiaDeFolga IS NULL OR DiaDeFolga != DATEPART(weekday, GETDATE()))
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_funcionarios_para_resumo_final(horario_atual):
    """Busca funcionários para resumo final, RESPEITANDO O DIA DE FOLGA."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT * FROM Funcionarios
                WHERE
                    DATEDIFF(minute, CONVERT(TIME, GETDATE()), CONVERT(TIME, DATEADD(MINUTE, 500, HorarioNotificacao))) = 0
                    AND (DiaDeFolga = 0 OR DiaDeFolga IS NULL OR DiaDeFolga != DATEPART(weekday, GETDATE()))
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

# Em database.py
def buscar_detalhes_da_entrega(entrega_id):
    """Busca todos os detalhes de uma entrega para as notificações."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    E.StatusValidacao,
                    E.DataEnvio, -- <-- CAMPO ADICIONADO
                    F.NomeCompleto, F.ChatIDTelegram AS ChatIDFuncionario,
                    T.Titulo, T.Pontos,
                    E.FuncionarioID, E.EntregaID
                FROM Entregas E
                JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID
                JOIN Tarefas T ON E.TarefaID = T.TarefaID
                WHERE E.EntregaID = ?
            """
            cursor.execute(sql, entrega_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def _get_date_part(dt_object):
    """
    Função auxiliar segura que retorna a parte 'date' de um objeto.
    Funciona tanto para objetos 'datetime' quanto para 'date'.
    """
    if hasattr(dt_object, 'date'): # Se for um objeto datetime completo
        return dt_object.date()
    return dt_object # Se já for um objeto date

# Em database.py, SUBSTITUA a função calcular_ranking_desempenho por esta versão com filtro:

def calcular_ranking_desempenho(data_final_calculo=None, setor_filtro=None): # <<< NOVO PARÂMETRO
    """
    Calcula o ranking com SCORE HÍBRIDO, filtrado opcionalmente por setor.
    PESOS: 70% Desempenho (Confiabilidade), 30% Pontos Brutos (Esforço).
    """
    conn = get_db_connection()
    if not conn: return []

    PESO_A_DESEMPENHO = 0.7
    PESO_B_PONTOS_BRUTOS = 0.3

    try:
        cursor = conn.cursor()
        sql_tarefas_atribuidas = """
            SELECT F.FuncionarioID, F.NomeCompleto, F.Cargo, F.DiaDeFolga, -- <<< Adicionado F.Cargo
                   TA.AtribuicaoID, TA.TipoFrequencia, TA.ValorFrequencia,
                   T.Pontos, TA.DataInicioVigencia, TA.DataFimVigencia,
                   TA.DataAceite
            FROM Funcionarios F
            LEFT JOIN TarefasAtribuidas TA ON F.FuncionarioID = TA.FuncionarioID
            LEFT JOIN Tarefas T ON TA.TarefaID = T.TarefaID
            WHERE TA.AtribuicaoID IS NOT NULL
            ORDER BY F.FuncionarioID
        """ #
        cursor.execute(sql_tarefas_atribuidas) #
        todas_as_atribuicoes = cursor.fetchall() #

        data_final = data_final_calculo if data_final_calculo else date.today() #
        inicio_mes = data_final.replace(day=1) #

        ranking_parcial = [] #

        # --- FILTRAGEM INICIAL POR SETOR ---
        funcionarios_todos = listar_funcionarios() #
        funcionarios_filtrados = []
        if setor_filtro == 'Cozinha':
            # Filtro 1: Apenas quem tem 'Cozinha' no cargo
            funcionarios_filtrados = [f for f in funcionarios_todos if f.Cargo and 'Cozinha' in f.Cargo]
        elif setor_filtro == 'Loja':
            # Filtro 2: Apenas quem tem 'Loja' OU 'Atendimento' no cargo
            funcionarios_filtrados = [f for f in funcionarios_todos if f.Cargo and ('Loja' in f.Cargo or 'Atendimento' in f.Cargo)]
        else: # Nenhum filtro ou filtro 'Geral'
            funcionarios_filtrados = funcionarios_todos

        # ------------------------------------

        if not funcionarios_filtrados: return [] # Retorna vazio se o setor não tiver funcionários

        atribuicoes_por_funcionario = {} #
        # Cria a estrutura apenas para os funcionários filtrados
        for func in funcionarios_filtrados:
             atribuicoes_por_funcionario[func.FuncionarioID] = {
                'NomeCompleto': func.NomeCompleto,
                'Cargo': func.Cargo, # Guarda o cargo
                'DiaDeFolga': func.DiaDeFolga,
                'tarefas': []
            } #

        # Preenche com as atribuições apenas dos funcionários filtrados
        for atribuicao in todas_as_atribuicoes:
            if atribuicao.FuncionarioID in atribuicoes_por_funcionario:
                atribuicoes_por_funcionario[atribuicao.FuncionarioID]['tarefas'].append(atribuicao) #

                # O cálculo de pontos possíveis e ganhos agora só roda para os funcionários filtrados
        for func_id, dados in atribuicoes_por_funcionario.items():
            pontos_possiveis_total = 0 #
            # --- Início da Lógica de Cálculo de Pontos Possíveis (EXISTENTE, SEM ALTERAÇÃO) ---
            # (Itera sobre tarefas, verifica frequência, datas, folga, etc.)
            for tarefa in dados['tarefas']:
                if tarefa.TipoFrequencia in ('GrupoCompetitiva', 'Unica'):
                    data_ref = tarefa.DataAceite if tarefa.TipoFrequencia == 'GrupoCompetitiva' else tarefa.DataInicioVigencia
                    if data_ref and inicio_mes <= _get_date_part(data_ref) <= data_final:
                        # Considera apenas se a atribuição estava ativa no período
                        data_fim_vigencia = _get_date_part(tarefa.DataFimVigencia) if tarefa.DataFimVigencia else data_final # Usa data_fim se for nulo
                        if data_fim_vigencia >= inicio_mes: # Garante que não encerrou antes do período começar
                            pontos_possiveis_total += tarefa.Pontos
                    continue
                dias_ocorrencia = 0
                start_date_tarefa = _get_date_part(tarefa.DataInicioVigencia) if tarefa.DataInicioVigencia else inicio_mes
                end_date_tarefa = _get_date_part(tarefa.DataFimVigencia) if tarefa.DataFimVigencia else data_final
                start_date_calc = max(start_date_tarefa, inicio_mes)
                end_date_calc = min(end_date_tarefa, data_final)
                if end_date_calc < start_date_calc: continue
                for dia_atual in (start_date_calc + timedelta(days=n) for n in range((end_date_calc - start_date_calc).days + 1)):
                    dia_da_semana_sql = (dia_atual.weekday() + 1) % 7 + 1
                    if str(dia_da_semana_sql) == str(dados['DiaDeFolga']): continue # PULA O DIA SE FOR FOLGA!
                    if tarefa.TipoFrequencia == 'Diaria': dias_ocorrencia += 1
                    elif tarefa.TipoFrequencia == 'Semanal':
                        if str(dia_da_semana_sql) == str(tarefa.ValorFrequencia): dias_ocorrencia += 1
                    elif tarefa.TipoFrequencia == 'Mensal':
                        if dia_atual.day == int(tarefa.ValorFrequencia): dias_ocorrencia += 1
                pontos_possiveis_total += dias_ocorrencia * tarefa.Pontos
            # --- Fim da Lógica de Cálculo de Pontos Possíveis ---

            # --- CORREÇÃO APLICADA AQUI ---
            # 1. Calcula os pontos ganhos APENAS de tarefas regulares para o PERCENTUAL
            pontos_ganhos_regulares = calcular_pontos_ganhos_tarefas_regulares(func_id, inicio_mes, data_final) # <<< USA A NOVA FUNÇÃO

            # 2. Calcula o percentual usando os pontos regulares
            percentual_desempenho = (pontos_ganhos_regulares / pontos_possiveis_total) * 100 if pontos_possiveis_total > 0 else 0

            # 3. Calcula os pontos ganhos TOTAIS (incluindo bônus) para a COLUNA "Pontos (Esforço)"
            pontos_ganhos_totais = calcular_pontos_ganhos_no_periodo(func_id, inicio_mes, data_final) # <<< USA A FUNÇÃO ORIGINAL
            # --- FIM DA CORREÇÃO ---

            ranking_parcial.append({
                'FuncionarioID': func_id, 'NomeCompleto': dados['NomeCompleto'],
                'PontosGanhos': pontos_ganhos_totais, # <<< Exibe o total (com bônus)
                'PontosPossiveis': pontos_possiveis_total,
                'Desempenho': round(percentual_desempenho, 2) # <<< Exibe o percentual (sem bônus, <= 100%)
            })

        if not ranking_parcial: return [] #

        # --- AJUSTE NO CÁLCULO DO MAX ---
        # Calcula o máximo de pontos ganhos APENAS DENTRO DO GRUPO FILTRADO
        max_pontos_ganhos_no_setor = max(p['PontosGanhos'] for p in ranking_parcial) if any(p['PontosGanhos'] for p in ranking_parcial) else 1
        # --------------------------------

        ranking_final = [] #
        for dados_func in ranking_parcial:
            # Usa o máximo do setor para normalizar o esforço
            percentual_pontos_brutos = (dados_func['PontosGanhos'] / max_pontos_ganhos_no_setor) * 100 #
            score_hibrido = (dados_func['Desempenho'] * PESO_A_DESEMPENHO) + (percentual_pontos_brutos * PESO_B_PONTOS_BRUTOS) #
            dados_func['ScoreHibrido'] = round(score_hibrido, 2) #
            ranking_final.append(dados_func) #

        ranking_ordenado = sorted(ranking_final, key=lambda x: x['ScoreHibrido'], reverse=True) #
        return ranking_ordenado #

    except Exception as e:
        logger.error(f"ERRO ao calcular ranking de desempenho HÍBRIDO com filtro '{setor_filtro}': {e}") #
        return [] #
    finally:
        if conn: conn.close() #

def salvar_historico_ranking(ranking_do_mes):
    """Salva os resultados finais do ranking de um mês na tabela de histórico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            hoje = date.today()
            ano = (hoje.replace(day=1) - timedelta(days=1)).year
            mes = (hoje.replace(day=1) - timedelta(days=1)).month

            sql = """
                INSERT INTO HistoricoRanking 
                (Ano, Mes, Posicao, FuncionarioID, NomeFuncionario, PontosGanhos, PontosPossiveis, PercentualDesempenho) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            for i, dados_vencedor in enumerate(ranking_do_mes):
                cursor.execute(sql,
                               ano,
                               mes,
                               i + 1, # Posição no ranking
                               dados_vencedor['FuncionarioID'],
                               dados_vencedor['NomeCompleto'],
                               dados_vencedor['PontosGanhos'],
                               dados_vencedor['PontosPossiveis'],
                               dados_vencedor['Desempenho']
                               )
            conn.commit()
            print(f"--> [DATABASE.PY] Histórico do ranking de {mes}/{ano} salvo com sucesso.")
        except Exception as e:
            logger.error(f"ERRO ao salvar histórico do ranking: {e}")
        finally:
            conn.close()

def verificar_se_fechamento_ja_rodou(ano, mes):
    """Verifica na tabela de histórico se o fechamento para um dado mês/ano já foi salvo."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT COUNT(1) FROM HistoricoRanking WHERE Ano = ? AND Mes = ?"
            cursor.execute(sql, ano, mes)
            return cursor.fetchone()[0] > 0
        finally:
            conn.close()
    return False

def calcular_pontos_ganhos_no_periodo(funcionario_id, inicio_periodo, fim_periodo):
    """
    Soma os pontos de todas as entregas APROVADAS de um funcionário
    dentro de um período de datas específico.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT SUM(ISNULL(PontosGanhos, 0))
                FROM Entregas
                WHERE FuncionarioID = ?
                  AND StatusValidacao = 'Aprovada'
                  AND CONVERT(DATE, DataEnvio) BETWEEN ? AND ?
            """
            cursor.execute(sql, funcionario_id, inicio_periodo, fim_periodo)
            resultado = cursor.fetchone()[0]
            # Se o resultado for None (nenhuma entrega), retorna 0
            return resultado if resultado is not None else 0
        finally:
            conn.close()
    return 0

def calcular_pontos_ganhos_tarefas_regulares(funcionario_id, inicio_periodo, fim_periodo):
    """
    Soma os pontos das entregas APROVADAS de um funcionário em um período,
    EXCLUINDO pontos de tarefas de bônus (Leitura, Feedback, Metas).
    Usado especificamente para o cálculo do percentual de desempenho/confiabilidade.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Lista de IDs de tarefas consideradas "bônus" ou não regulares
            # Certifique-se que TAREFA_ID_LEITURA, TAREFA_ID_FEEDBACK_DIARIO, TAREFA_ID_PONTOS_META
            # existem e estão corretos em config.py
            ids_bonus = (
                config.TAREFA_ID_LEITURA,
                config.TAREFA_ID_FEEDBACK_DIARIO,
                config.TAREFA_ID_PONTOS_META
                # Adicione outros IDs de tarefas "bônus" se existirem
            )
            # Cria os placeholders (?) para a cláusula NOT IN dinamicamente
            placeholders = ','.join('?' * len(ids_bonus))

            sql = f"""
                SELECT SUM(ISNULL(PontosGanhos, 0))
                FROM Entregas
                WHERE FuncionarioID = ?
                  AND StatusValidacao = 'Aprovada'
                  AND CONVERT(DATE, DataEnvio) BETWEEN ? AND ?
                  AND TarefaID NOT IN ({placeholders}) -- Exclui tarefas de bônus
            """
            params = [funcionario_id, inicio_periodo, fim_periodo] + list(ids_bonus)

            cursor.execute(sql, params)
            resultado = cursor.fetchone()[0]
            return resultado if resultado is not None else 0
        except AttributeError as e:
             # Log específico se alguma constante não existir em config.py
             logger.error(f"Erro ao calcular pontos regulares: Constante de Tarefa Bônus não encontrada em config.py? Detalhe: {e}")
             return 0 # Retorna 0 em caso de erro na configuração
        except Exception as e:
             logger.error(f"Erro ao calcular pontos ganhos (tarefas regulares): {e}", exc_info=True)
             return 0 # Retorna 0 em caso de erro genérico
        finally:
            conn.close()
    return 0

def limpar_entregas_do_mes_por_funcionario(funcionario_id):
    """
    (A "BOMBA ATÔMICA")
    DELETA todas as entregas de um funcionário feitas no mês e ano correntes.
    Esta é uma operação DESTRUTIVA e irreversível.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                DELETE FROM Entregas
                WHERE FuncionarioID = ?
                  AND MONTH(DataEnvio) = MONTH(GETDATE())
                  AND YEAR(DataEnvio) = YEAR(GETDATE())
            """
            cursor.execute(sql, funcionario_id)
            conn.commit()
            print(f"--> [BOMBA ATÔMICA] Entregas do mês corrente para o funcionário {funcionario_id} foram DELETADAS.")
        except Exception as e:
            logger.error(f"ERRO ao limpar as entregas do mês para o funcionário {funcionario_id}: {e}")
        finally:
            conn.close()

def criar_documento(titulo, conteudo, criador_id, pontos, telegram_file_id_foto=None): # 1. Novo Parâmetro Opcional
    """
    Insere um novo documento na tabela Documentos e retorna o ID do novo registro.
    Agora suporta um file_id de foto opcional.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO Documentos (Titulo, Conteudo, FuncionarioCriadorID, PontosPorCiencia, TelegramFileIDFoto) -- 2. Nova Coluna no INSERT
                VALUES (?, ?, ?, ?, ?); -- 3. Novo '?' para o valor
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, titulo, conteudo, criador_id, pontos, telegram_file_id_foto)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            return novo_id
        except Exception as e:
            logger.error(f"ERRO ao criar documento: {e}")
            return None
        finally:
            conn.close()

def registrar_pendencia_assinatura(documento_id, funcionario_id):
    """
    Cria um registro de 'Pendente' para um funcionário em um documento específico.
    Retorna o ID da nova pendência (AssinaturaID).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO DocumentosAssinaturas (DocumentoID, FuncionarioID)
                VALUES (?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, documento_id, funcionario_id)
            cursor.nextset() # <<< A CORREÇÃO MÁGICA ESTÁ AQUI
            assinatura_id = cursor.fetchone()[0]
            conn.commit()
            return assinatura_id
        except Exception as e:
            logger.error(f"ERRO ao registrar pendência de assinatura: {e}")
            return None
        finally:
            conn.close()

def buscar_detalhes_assinatura_para_bot(assinatura_id):
    """
    Busca informações cruciais sobre uma assinatura pendente para o bot usar.
    Retorna o ID do funcionário, os pontos a serem ganhos e o chat_id do telegram.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    DA.FuncionarioID,
                    D.PontosPorCiencia,
                    F.ChatIDTelegram,
                    D.Titulo
                FROM DocumentosAssinaturas DA
                JOIN Documentos D ON DA.DocumentoID = D.DocumentoID
                JOIN Funcionarios F ON DA.FuncionarioID = F.FuncionarioID
                WHERE DA.AssinaturaID = ? AND DA.StatusAssinatura = 'Pendente'
            """
            cursor.execute(sql, assinatura_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def marcar_como_ciente(assinatura_id):
    """
    Atualiza uma pendência de assinatura para 'Ciente' e preenche a data/hora.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE DocumentosAssinaturas
                SET StatusAssinatura = 'Ciente', DataCiencia = GETDATE()
                WHERE AssinaturaID = ?
            """
            cursor.execute(sql, assinatura_id)
            conn.commit()
        finally:
            conn.close()

def registrar_pontos_por_leitura(funcionario_id, pontos, titulo_documento):
    """
    (O "TRUQUE MÁGICO")
    Insere um registro na tabela Entregas para contabilizar os pontos no ranking.
    """
    conn = get_db_connection()
    TAREFA_ID_LEITURA = 38 # <<< MUDE ESTE NÚMERO PARA O SEU ID CORRETO!

    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO Entregas
                (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa)
                VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?)
            """
            motivo = f"Ciência do comunicado: {titulo_documento}"
            cursor.execute(sql, TAREFA_ID_LEITURA, funcionario_id, pontos, motivo)
            conn.commit()
            print(f"--> [PONTOS] {pontos} pts registrados para FuncionarioID {funcionario_id} pela leitura.")
        except Exception as e:
            logger.error(f"ERRO ao registrar pontos por leitura: {e}")
        finally:
            conn.close()


# Em database.py
def registrar_pontos_de_bonus(funcionario_id, pontos, motivo_log, tarefa_id_bonus, vinculo_id=None):
    """
    Insere um registro na tabela Entregas para contabilizar pontos de bônus
    contra um TAREFA_ID específico (ex: Meta, Feedback, Conquista).
    Opcionalmente, salva um 'vinculo_id' (como um ApuracaoID) no campo AtribuicaoID.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO Entregas
                (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa, AtribuicaoID)
                VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?, ?)
            """
            cursor.execute(sql, tarefa_id_bonus, funcionario_id, pontos, motivo_log, vinculo_id)
            conn.commit()
            logger.info(f"--> [BÔNUS] {pontos} pts (TarefaID: {tarefa_id_bonus}, Vínculo: {vinculo_id}) registrados para FuncID {funcionario_id}. Motivo: {motivo_log}")
        except Exception as e:
            logger.error(f"ERRO ao registrar pontos de bônus (TarefaID: {tarefa_id_bonus}): {e}", exc_info=True)
        finally:
            conn.close()


def listar_comunicados_com_status(filtro_titulo=None):
    """
    Lista todos os documentos com status. Se um filtro_titulo for fornecido,
    retorna apenas os documentos cujo título contém o texto do filtro.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql_base = """
                SELECT
                    D.DocumentoID, D.Titulo, D.DataCriacao,
                    COUNT(DA.AssinaturaID) AS TotalEnviado,
                    SUM(CASE WHEN DA.StatusAssinatura = 'Ciente' THEN 1 ELSE 0 END) AS TotalCientes
                FROM Documentos D
                LEFT JOIN DocumentosAssinaturas DA ON D.DocumentoID = DA.DocumentoID
            """

            params = [] # Lista para guardar os parâmetros da consulta
            if filtro_titulo:
                sql_base += " WHERE D.Titulo LIKE ?" # O 'LIKE' permite buscas parciais
                params.append(f"%{filtro_titulo}%") # Os '%' são coringas: buscam o texto em qualquer parte do título

            sql_final = """
                GROUP BY D.DocumentoID, D.Titulo, D.DataCriacao
                ORDER BY D.DataCriacao DESC
            """

            sql_completa = sql_base + sql_final
            cursor.execute(sql_completa, params)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def listar_destinatarios_de_documento(documento_id):
    """
    Função de relatório para o gestor. Mostra o status detalhado de
    cada funcionário para um documento específico, AGORA INCLUINDO O ID DA ASSINATURA.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    DA.AssinaturaID, 
                    F.NomeCompleto,
                    DA.StatusAssinatura,
                    DA.DataCiencia
                FROM DocumentosAssinaturas DA
                JOIN Funcionarios F ON DA.FuncionarioID = F.FuncionarioID
                WHERE DA.DocumentoID = ?
                ORDER BY F.NomeCompleto
            """
            cursor.execute(sql, documento_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

if __name__ == '__main__':
    GESTOR_ID_TESTE = 3 # ID de um funcionário para ser o "criador"
    FUNCIONARIO_ID_TESTE = 3 # ID de um funcionário para receber o comunicado

    print("--- INICIANDO TESTE DO MÓDULO DE COMUNICADOS ---")
    print("\n[TESTE 1] Criando um novo documento que vale 25 pontos...")
    id_doc = criar_documento(
        "Documento de Teste com Pontos",
        "Este é o conteúdo do nosso teste automatizado.",
        GESTOR_ID_TESTE,
        25
    )
    if id_doc:
        print(f"--> SUCESSO! Documento criado com ID: {id_doc}")
    else:
        print("--> FALHA! Não foi possível criar o documento.")
        exit()
    print(f"\n[TESTE 2] Registrando pendência do Doc ID {id_doc} para o Funcionário ID {FUNCIONARIO_ID_TESTE}...")
    id_assinatura = registrar_pendencia_assinatura(id_doc, FUNCIONARIO_ID_TESTE)
    if id_assinatura:
        print(f"--> SUCESSO! Pendência registrada com AssinaturaID: {id_assinatura}")
    else:
        print("--> FALHA! Não foi possível registrar a pendência.")
        exit()

    print(f"\n[TESTE 3] Buscando detalhes da assinatura ID {id_assinatura}...")
    detalhes = buscar_detalhes_assinatura_para_bot(id_assinatura)
    if detalhes:
        print(f"--> SUCESSO! Detalhes encontrados: FuncID={detalhes.FuncionarioID}, Pontos={detalhes.PontosPorCiencia}")

        print(f"\n[TESTE 4] Marcando a assinatura ID {id_assinatura} como 'Ciente'...")
        marcar_como_ciente(id_assinatura)
        print("--> SUCESSO! Status atualizado.")

        if detalhes.PontosPorCiencia > 0:
            print(f"\n[TESTE 5] Registrando {detalhes.PontosPorCiencia} pontos pela leitura...")
            registrar_pontos_por_leitura(detalhes.FuncionarioID, detalhes.PontosPorCiencia, detalhes.Titulo)
            print("--> SUCESSO! Pontos registrados na tabela Entregas.")
    else:
        print("--> FALHA! Não foi possível buscar os detalhes da assinatura.")

    print("\n--- TESTE FINALIZADO ---")
    print("Verifique as tabelas Documentos, DocumentosAssinaturas e Entregas no SSMS para confirmar os resultados.")

def buscar_assinaturas_pendentes_antigas(horas_atras=24):
    """
    Busca assinaturas que continuam 'Pendente' após um determinado número de horas do envio.
    Retorna uma lista com Nome, ChatID e Título do documento para o lembrete.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    F.NomeCompleto,
                    F.ChatIDTelegram,
                    D.Titulo,
                    DA.DataEnvio
                FROM DocumentosAssinaturas DA
                JOIN Funcionarios F ON DA.FuncionarioID = F.FuncionarioID
                JOIN Documentos D ON DA.DocumentoID = D.DocumentoID
                WHERE
                    DA.StatusAssinatura = 'Pendente'
                    AND DA.DataEnvio < DATEADD(hour, -?, GETDATE())
            """
            cursor.execute(sql, horas_atras)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_detalhes_completos_documento(documento_id):
    """
    Busca todos os campos de um documento específico, incluindo seu conteúdo completo.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT Titulo, Conteudo FROM Documentos WHERE DocumentoID = ?"
            cursor.execute(sql, documento_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def excluir_documento(documento_id):
    """
    Exclui um documento e todas as suas assinaturas pendentes ou cientes.
    A exclusão em cascata deve estar configurada no banco de dados para segurança,
    mas faremos a exclusão em duas etapas para garantir.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql_assinaturas = "DELETE FROM DocumentosAssinaturas WHERE DocumentoID = ?"
            cursor.execute(sql_assinaturas, documento_id)
            sql_documento = "DELETE FROM Documentos WHERE DocumentoID = ?"
            cursor.execute(sql_documento, documento_id)

            conn.commit()
            print(f"--> [DATABASE] Documento ID {documento_id} e suas assinaturas foram excluídos.")
        except Exception as e:
            logger.error(f"ERRO ao excluir documento: {e}")
            conn.rollback() # Desfaz a operação em caso de erro
        finally:
            conn.close()

def buscar_dados_completos_para_recibo(assinatura_id):
    """
    Busca todos os dados necessários para gerar o recibo em PDF a partir do ID da assinatura.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    F.NomeCompleto,
                    D.Titulo,
                    D.Conteudo,
                    DA.DataCiencia
                FROM DocumentosAssinaturas DA
                JOIN Funcionarios F ON DA.FuncionarioID = F.FuncionarioID
                JOIN Documentos D ON DA.DocumentoID = D.DocumentoID
                WHERE DA.AssinaturaID = ?
            """
            cursor.execute(sql, assinatura_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def listar_funcionarios_nao_destinatarios(documento_id):
    """
    Retorna uma lista de funcionários que AINDA NÃO estão associados a um
    documento específico, AGORA INCLUINDO O CHAT ID PARA NOTIFICAÇÃO.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT F.FuncionarioID, F.NomeCompleto, F.ChatIDTelegram
                FROM Funcionarios F
                WHERE NOT EXISTS (
                    SELECT 1 FROM DocumentosAssinaturas DA
                    WHERE DA.DocumentoID = ? AND DA.FuncionarioID = F.FuncionarioID
                )
                ORDER BY F.NomeCompleto
            """
            cursor.execute(sql, documento_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def salvar_feedback_do_dia(funcionario_id, nota):
    """Salva a nota de feedback do funcionário para a data atual."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql_check = "SELECT 1 FROM Feedbacks WHERE FuncionarioID = ? AND DataFeedback = CONVERT(date, GETDATE())"
            cursor.execute(sql_check, funcionario_id)
            if cursor.fetchone():
                print(f"--> [FEEDBACK] Feedback já recebido hoje para o funcionário {funcionario_id}.")
                return False

            sql_insert = "INSERT INTO Feedbacks (FuncionarioID, DataFeedback, NotaDia) VALUES (?, GETDATE(), ?)"
            cursor.execute(sql_insert, funcionario_id, nota)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def buscar_feedbacks(funcionario_id=None, data_inicio=None, data_fim=None):
    """
    Busca os feedbacks no banco de dados, com filtros opcionais.
    - Retorna todos se nenhum filtro for passado.
    - Filtra por funcionário, por período ou por ambos.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    F.FeedbackID,
                    FUNC.NomeCompleto,
                    F.DataFeedback,
                    F.NotaDia
                FROM Feedbacks F
                JOIN Funcionarios FUNC ON F.FuncionarioID = FUNC.FuncionarioID
            """

            condicoes = []
            params = []

            if funcionario_id:
                condicoes.append("F.FuncionarioID = ?")
                params.append(funcionario_id)

            if data_inicio:
                condicoes.append("F.DataFeedback >= ?")
                params.append(data_inicio)

            if data_fim:
                condicoes.append("F.DataFeedback <= ?")
                params.append(data_fim)

            if condicoes:
                sql += " WHERE " + " AND ".join(condicoes)

            sql += " ORDER BY F.DataFeedback DESC" # Ordena do mais recente para o mais antigo

            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def relatorio_analise_tarefas(data_inicio, data_fim):
    """
    Busca no banco um resumo das tarefas que foram mais recusadas ou
    marcadas como "Não Aplicável" dentro de um período.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = sql = """
                SELECT
                    T.Titulo,
                    SUM(CASE WHEN E.StatusValidacao = 'Recusada' THEN 1 ELSE 0 END) AS QtdRecusada,
                    SUM(CASE WHEN E.MotivoRecusa LIKE 'Não aplicável:%' THEN 1 ELSE 0 END) AS QtdNaoAplicavel,
                    -- A CORREÇÃO LÓGICA ESTÁ AQUI: Somamos os dois casos acima
                    SUM(CASE WHEN E.StatusValidacao = 'Recusada' THEN 1 ELSE 0 END) +
                    SUM(CASE WHEN E.MotivoRecusa LIKE 'Não aplicável:%' THEN 1 ELSE 0 END) AS TotalEntregasProblematicas
                FROM Entregas E
                JOIN Tarefas T ON E.TarefaID = T.TarefaID
                WHERE
                    (E.StatusValidacao = 'Recusada' OR E.MotivoRecusa LIKE 'Não aplicável:%')
                    AND CONVERT(DATE, E.DataEnvio) BETWEEN ? AND ?
                GROUP BY
                    T.Titulo
                ORDER BY
                    TotalEntregasProblematicas DESC
            """
            cursor.execute(sql, data_inicio, data_fim)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def criar_solicitacao_feedback(funcionario_id, assunto):
    """Salva uma nova solicitação de feedback na tabela FeedbackSolicitacoes."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO FeedbackSolicitacoes (FuncionarioID, TextoAssunto) VALUES (?, ?)"
            cursor.execute(sql, funcionario_id, assunto)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao criar solicitação de feedback: {e}")
            return False
        finally:
            conn.close()
    return False

def listar_solicitacoes_pendentes():
    """Busca no banco todas as solicitações de feedback com status 'Pendente'."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    FS.SolicitacaoID,
                    F.NomeCompleto,
                    FS.DataSolicitacao,
                    FS.TextoAssunto
                FROM FeedbackSolicitacoes FS
                JOIN Funcionarios F ON FS.FuncionarioID = F.FuncionarioID
                WHERE FS.Status = 'Pendente'
                ORDER BY FS.DataSolicitacao ASC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def responder_solicitacao_feedback(solicitacao_id, texto_resposta):
    """Atualiza uma solicitação com a resposta do gestor e muda o status."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE FeedbackSolicitacoes
                SET Status = 'Respondido',
                    TextoResposta = ?,
                    DataResposta = GETDATE()
                WHERE SolicitacaoID = ?
            """
            cursor.execute(sql, texto_resposta, solicitacao_id)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def buscar_dados_para_notificacao_feedback(solicitacao_id):
    """Busca o nome e o ChatID de um funcionário a partir de uma solicitação."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    F.NomeCompleto,
                    F.ChatIDTelegram
                FROM FeedbackSolicitacoes FS
                JOIN Funcionarios F ON FS.FuncionarioID = F.FuncionarioID
                WHERE FS.SolicitacaoID = ?
            """
            cursor.execute(sql, solicitacao_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def registrar_entrega_preliminar(tarefa_id, funcionario_id, atribuicao_id, file_id):
    """Cria um registro inicial na tabela Entregas, apenas com a file_id."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO Entregas (TarefaID, FuncionarioID, AtribuicaoID, FileIDTelegram, DataEnvio, StatusValidacao) 
                VALUES (?, ?, ?, ?, GETDATE(), 'Pendente'); 
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, tarefa_id, funcionario_id, atribuicao_id, file_id)
            
            cursor.nextset() 
            
            new_id = cursor.fetchone()[0]
            conn.commit()
            return new_id
        finally: 
            conn.close()
    return None

def buscar_entregas_para_download():
    """Busca entregas que foram registradas preliminarmente mas ainda não tiveram a foto baixada."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT EntregaID, FileIDTelegram FROM Entregas WHERE FileIDTelegram IS NOT NULL AND PathFotoEvidencia IS NULL"
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def finalizar_registro_entrega(entrega_id, path_foto):
    """Atualiza o registro da entrega com o caminho da foto baixada."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Entregas SET PathFotoEvidencia = ? WHERE EntregaID = ?"
            cursor.execute(sql, path_foto, entrega_id)
            conn.commit()
        finally:
            conn.close()

def marcar_notificacao_gestor_enviada(entrega_id):
    """Atualiza a flag indicando que a notificação ao gestor foi enviada com sucesso."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Entregas SET NotificacaoGestorEnviada = 1 WHERE EntregaID = ?"
            cursor.execute(sql, entrega_id)
            conn.commit()
            logger.info(f"Flag NotificacaoGestorEnviada marcada para EntregaID {entrega_id}.")
        except Exception as e:
            logger.error(f"Erro ao marcar flag NotificacaoGestorEnviada para EntregaID {entrega_id}: {e}", exc_info=True)
        finally:
            if conn:
                conn.close()

def verificar_status_notificacao_gestor(entrega_id):
    """Verifica se a flag de notificação ao gestor está marcada como enviada."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT NotificacaoGestorEnviada FROM Entregas WHERE EntregaID = ?"
            cursor.execute(sql, entrega_id)
            resultado = cursor.fetchone()
            # Retorna True se for 1, False caso contrário (incluindo NULL ou 0)
            return resultado[0] == 1 if resultado else False
        except Exception as e:
            logger.error(f"Erro ao verificar flag NotificacaoGestorEnviada para EntregaID {entrega_id}: {e}", exc_info=True)
            return False # Assume que não foi enviada em caso de erro
        finally:
            if conn:
                conn.close()
    return False # Assume que não foi enviada se a conexão falhar

def listar_atribuicoes_ativas_por_funcionario(funcionario_id):
    """Retorna todas as tarefas ativas para um funcionário específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    TA.AtribuicaoID, 
                    T.Titulo, 
                    TA.TipoFrequencia + 
                    CASE 
                        WHEN TA.TipoFrequencia = 'Semanal' THEN ' (' + 
                            CASE TA.ValorFrequencia 
                                WHEN '1' THEN 'Dom' WHEN '2' THEN 'Seg' WHEN '3' THEN 'Ter'
                                WHEN '4' THEN 'Qua' WHEN '5' THEN 'Qui' WHEN '6' THEN 'Sex'
                                WHEN '7' THEN 'Sab'
                            END + ')'
                        WHEN TA.TipoFrequencia = 'Mensal' THEN ' (Dia ' + CAST(TA.ValorFrequencia AS VARCHAR) + ')'
                        ELSE '' 
                    END AS FrequenciaCompleta
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE
                    TA.FuncionarioID = ? AND TA.DataFimVigencia IS NULL
                    AND NOT (
                        TA.TipoFrequencia = 'Unica' AND EXISTS (
                            SELECT 1 FROM Entregas E
                            WHERE E.AtribuicaoID = TA.AtribuicaoID AND E.StatusValidacao = 'Aprovada'
                        )
                    )
                ORDER BY T.Titulo
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_justificativas_nao_aplicavel(titulo_tarefa, data_inicio, data_fim):
    """Busca as justificativas para uma tarefa marcada como 'Não Aplicável' em um período."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    E.DataEnvio,
                    F.NomeCompleto,
                    E.MotivoRecusa
                FROM Entregas E
                JOIN Tarefas T ON E.TarefaID = T.TarefaID
                JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID
                WHERE
                    T.Titulo = ?
                    AND E.MotivoRecusa LIKE 'Não aplicável:%'
                    AND CONVERT(DATE, E.DataEnvio) BETWEEN ? AND ?
                ORDER BY E.DataEnvio DESC
            """
            cursor.execute(sql, titulo_tarefa, data_inicio, data_fim)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def listar_agenda_semanal_por_funcionario(funcionario_id):
    """Busca todas as tarefas ativas de um funcionário e retorna o dia da semana para tarefas semanais."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    T.Titulo,
                    TA.TipoFrequencia,
                    TA.ValorFrequencia
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE
                    TA.FuncionarioID = ? 
                    AND TA.DataFimVigencia IS NULL
                    AND TA.TipoFrequencia IN ('Diaria', 'Semanal')
                ORDER BY T.Titulo
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_funcionarios_de_folga_hoje(dia_da_semana):
    """Busca no banco todos os funcionários cujo dia de folga corresponde ao dia da semana fornecido."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT * FROM Funcionarios 
                WHERE DiaDeFolga = ?
            """
            cursor.execute(sql, dia_da_semana)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario_id, dia_da_semana):
    """
    (VERSÃO CORRIGIDA) Busca tarefas recorrentes, AGORA INCLUINDO O SETOR.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT T.TarefaID, T.Titulo, T.Pontos, T.Setor
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE TA.FuncionarioID = ? 
                  AND TA.DataFimVigencia IS NULL
                  AND (
                    TA.TipoFrequencia = 'Diaria' OR
                    (TA.TipoFrequencia = 'Semanal' AND TA.ValorFrequencia = ?)
                  )
            """
            cursor.execute(sql, funcionario_id, dia_da_semana)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def listar_setores_unicos():
    """Retorna uma lista com todos os nomes de setores distintos já cadastrados."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT DISTINCT Setor FROM Tarefas WHERE Setor IS NOT NULL AND Setor != '' ORDER BY Setor"
            cursor.execute(sql)
            return [row.Setor for row in cursor.fetchall()]
        finally:
            conn.close()
    return []

def adicionar_pontos_ao_saldo(funcionario_id, pontos_a_adicionar):
    """Adiciona pontos ao saldo cumulativo de um funcionário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Funcionarios SET SaldoPontos = SaldoPontos + ? WHERE FuncionarioID = ?"
            cursor.execute(sql, pontos_a_adicionar, funcionario_id)
            conn.commit()
        finally:
            conn.close()

def buscar_saldo_funcionario(funcionario_id):
    """Busca o saldo de pontos atual de um funcionário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT SaldoPontos FROM Funcionarios WHERE FuncionarioID = ?"
            cursor.execute(sql, funcionario_id)
            resultado = cursor.fetchone()
            return resultado[0] if resultado else 0
        finally:
            conn.close()
    return 0

def listar_produtos_loja(incluir_inativos=False):
    """Lista os produtos da loja. Por padrão, lista apenas os ativos."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM ProdutosLoja"
            if not incluir_inativos:
                sql += " WHERE Ativo = 1"
            sql += " ORDER BY CustoEmPontos"
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def criar_produto_loja(nome, descricao, custo, estoque, ativo):
    """Cria um novo produto na loja de recompensas."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO ProdutosLoja (Nome, Descricao, CustoEmPontos, EstoqueDisponivel, Ativo) VALUES (?, ?, ?, ?, ?)"
            cursor.execute(sql, nome, descricao, custo, estoque, ativo)
            conn.commit()
        finally:
            conn.close()

def atualizar_produto_loja(produto_id, nome, descricao, custo, estoque, ativo):
    """Atualiza um produto existente na loja."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """UPDATE ProdutosLoja SET Nome = ?, Descricao = ?, CustoEmPontos = ?, 
                     EstoqueDisponivel = ?, Ativo = ? WHERE ProdutoID = ?"""
            cursor.execute(sql, nome, descricao, custo, estoque, ativo, produto_id)
            conn.commit()
        finally:
            conn.close()

# --- Funções de Gestão de Resgates ---

def solicitar_resgate(funcionario_id, produto_id):
    """
    Processa uma solicitação de resgate.
    Retorna uma tupla: (True, "Mensagem de Sucesso") ou (False, "Mensagem de Erro").
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Pega os detalhes do produto e o saldo do funcionário de uma vez
            sql_check = """
                SELECT P.CustoEmPontos, P.Nome, F.SaldoPontos 
                FROM ProdutosLoja P, Funcionarios F
                WHERE P.ProdutoID = ? AND F.FuncionarioID = ? AND P.Ativo = 1
            """
            cursor.execute(sql_check, produto_id, funcionario_id)
            resultado = cursor.fetchone()
            if not resultado:
                return (False, "Produto não encontrado ou indisponível.")

            custo_produto, nome_produto, saldo_atual = resultado

            # 2. Verifica se há saldo suficiente
            if saldo_atual < custo_produto:
                return (False, f"Saldo insuficiente! Você tem {saldo_atual} pontos, mas o item '{nome_produto}' custa {custo_produto}.")

            # 3. Se chegou até aqui, pode resgatar!
            # Debita os pontos do saldo do funcionário
            sql_debitar = "UPDATE Funcionarios SET SaldoPontos = SaldoPontos - ? WHERE FuncionarioID = ?"
            cursor.execute(sql_debitar, custo_produto, funcionario_id)

            # Insere o registro de resgate como 'Pendente'
            sql_resgate = "INSERT INTO Resgates (FuncionarioID, ProdutoID, PontosGastos) VALUES (?, ?, ?); SELECT SCOPE_IDENTITY();"
            cursor.execute(sql_resgate, funcionario_id, produto_id, custo_produto)
            cursor.nextset()
            resgate_id = cursor.fetchone()[0]
            
            conn.commit()
            return (True, f"Resgate do item '{nome_produto}' solicitado com sucesso! Aguarde a aprovação do seu gestor.", resgate_id)
        except Exception as e:
            conn.rollback() # Segurança: Desfaz tudo em caso de erro
            logger.error(f"ERRO CRÍTICO em solicitar_resgate: {e}")
            return (False, f"Ocorreu um erro inesperado no servidor. Tente novamente mais tarde.", None)
        finally:
            conn.close()

def listar_resgates_pendentes():
    """Busca todos os resgates com status 'Pendente' para o gestor aprovar."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT R.ResgateID, F.NomeCompleto, P.Nome, R.PontosGastos, R.DataSolicitacao
                FROM Resgates R
                JOIN Funcionarios F ON R.FuncionarioID = F.FuncionarioID
                JOIN ProdutosLoja P ON R.ProdutoID = P.ProdutoID
                WHERE R.Status = 'Pendente'
                ORDER BY R.DataSolicitacao ASC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def aprovar_resgate(resgate_id, gestor_id):
    """Muda o status de um resgate para 'Aprovado'."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Resgates SET Status = 'Aprovado', GestorID_Aprovacao = ?, DataAprovacao = GETDATE() WHERE ResgateID = ?"
            cursor.execute(sql, gestor_id, resgate_id)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def recusar_resgate(resgate_id, gestor_id):
    """Muda o status para 'Recusado' e DEVOLVE os pontos para o funcionário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Primeiro, busca quantos pontos foram gastos e para qual funcionário
            sql_find = "SELECT FuncionarioID, PontosGastos FROM Resgates WHERE ResgateID = ?"
            cursor.execute(sql_find, resgate_id)
            resgate = cursor.fetchone()
            if resgate:
                funcionario_id, pontos_gastos = resgate
                # Devolve os pontos
                sql_refund = "UPDATE Funcionarios SET SaldoPontos = SaldoPontos + ? WHERE FuncionarioID = ?"
                cursor.execute(sql_refund, pontos_gastos, funcionario_id)

                # Atualiza o status do resgate
                sql_update = "UPDATE Resgates SET Status = 'Recusado', GestorID_Aprovacao = ?, DataAprovacao = GETDATE() WHERE ResgateID = ?"
                cursor.execute(sql_update, gestor_id, resgate_id)
                conn.commit()
                return True
        except Exception as e:
            conn.rollback()
            logger.error(f"ERRO ao recusar resgate: {e}")
        finally:
            conn.close()
    return False

def buscar_dados_resgate_para_notificacao(resgate_id):
    """Busca dados para notificar o funcionário sobre o status do resgate."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT F.NomeCompleto, F.ChatIDTelegram, P.Nome 
                FROM Resgates R
                JOIN Funcionarios F ON R.FuncionarioID = F.FuncionarioID
                JOIN ProdutosLoja P ON R.ProdutoID = P.ProdutoID
                WHERE R.ResgateID = ?
            """
            cursor.execute(sql, resgate_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

# ===================================================================
# == INÍCIO DO MÓDULO DE CONQUISTAS (BADGES) ========================
# ===================================================================

def listar_modelos_conquistas():
    """Lista todos os modelos de conquistas disponíveis para gerenciamento."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Conquistas ORDER BY Nome")
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def listar_conquistas_por_funcionario(funcionario_id):
    """Lista todas as conquistas que um funcionário específico já ganhou."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT C.Nome, C.Descricao, C.Icone, CF.DataConquista
                FROM ConquistasFuncionarios CF
                JOIN Conquistas C ON CF.ConquistaID = C.ConquistaID
                WHERE CF.FuncionarioID = ?
                ORDER BY CF.DataConquista DESC
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def verificar_e_conceder_conquistas(funcionario_id):
    """
    (VERSÃO EXPANDIDA COM MAIS CRITÉRIOS)
    Verifica critérios de conquistas para um funcionário após um evento relevante.
    Retorna uma lista de objetos das novas conquistas desbloqueadas.
    """
    conn = get_db_connection()
    if not conn: return []

    novas_conquistas_ganhas = []

    try:
        cursor = conn.cursor()
        sql_conquistas_a_verificar = """
            SELECT * FROM Conquistas
            WHERE ConquistaID NOT IN (
                SELECT ConquistaID FROM ConquistasFuncionarios WHERE FuncionarioID = ?
            )
        """
        cursor.execute(sql_conquistas_a_verificar, funcionario_id)
        conquistas_a_verificar = cursor.fetchall()

        if not conquistas_a_verificar:
            return [] # Nenhuma nova conquista possível para verificar

        # --- DADOS NECESSÁRIOS PARA AS VERIFICAÇÕES ---
        # (Buscamos uma vez para otimizar)
        
        # Total de tarefas aprovadas (usado por 'total_tarefas_aprovadas')
        sql_total_aprovadas = "SELECT COUNT(*) FROM Entregas WHERE FuncionarioID = ? AND StatusValidacao = 'Aprovada'"
        cursor.execute(sql_total_aprovadas, funcionario_id)
        total_tarefas_aprovadas = cursor.fetchone()[0] or 0

        # Datas das últimas N tarefas aprovadas (usado por 'tarefas_aprovadas_periodo' e 'sequencia_dias_tarefas')
        # Buscamos mais do que o necessário (ex: 10) para garantir que temos dados suficientes para sequências
        sql_datas_aprovadas = """
            SELECT DISTINCT TOP 10 CONVERT(DATE, DataEnvio) as Data
            FROM Entregas
            WHERE FuncionarioID = ? AND StatusValidacao = 'Aprovada'
            ORDER BY Data DESC
        """
        cursor.execute(sql_datas_aprovadas, funcionario_id)
        datas_tarefas_aprovadas = [row.Data for row in cursor.fetchall()]

        # Total de tarefas de grupo competitivo aprovadas (usado por 'tarefas_grupo_competitivo_aceitas')
        sql_total_grupo_comp = """
            SELECT COUNT(E.EntregaID)
            FROM Entregas E
            JOIN TarefasAtribuidas TA ON E.AtribuicaoID = TA.AtribuicaoID
            WHERE E.FuncionarioID = ?
              AND E.StatusValidacao = 'Aprovada'
              AND TA.OrigemAtribuicaoID IS NOT NULL -- Identifica tarefas criadas a partir de um grupo competitivo
              AND TA.TipoFrequencia = 'Unica'      -- Confirma que é a instância aceita
        """
        cursor.execute(sql_total_grupo_comp, funcionario_id)
        total_grupo_competitivo_aprovadas = cursor.fetchone()[0] or 0
        
        # Total de comunicados cientes (usado por 'total_comunicados_cientes')
        sql_total_cientes = "SELECT COUNT(*) FROM DocumentosAssinaturas WHERE FuncionarioID = ? AND StatusAssinatura = 'Ciente'"
        cursor.execute(sql_total_cientes, funcionario_id)
        total_comunicados_cientes = cursor.fetchone()[0] or 0

        # Datas dos últimos N feedbacks (usado por 'sequencia_feedback_diario')
        sql_datas_feedback = """
            SELECT DISTINCT TOP 10 DataFeedback as Data
            FROM Feedbacks
            WHERE FuncionarioID = ?
            ORDER BY Data DESC
        """
        cursor.execute(sql_datas_feedback, funcionario_id)
        datas_feedback = [row.Data for row in cursor.fetchall()]


        # --- LOOP DE VERIFICAÇÃO ---
        for conquista in conquistas_a_verificar:
            atingiu_criterio = False
            
            # --- CRITÉRIO 1: Total de Tarefas Aprovadas (Já Existia) ---
            if conquista.CriterioTipo == 'total_tarefas_aprovadas':
                if total_tarefas_aprovadas >= conquista.CriterioValor:
                    atingiu_criterio = True
            
            elif conquista.CriterioTipo == 'tarefas_aprovadas_periodo':
                try: # Adiciona try/except para conversão segura
                    # Assume que CriterioValor é o NÚMERO DE TAREFAS necessárias.
                    num_tarefas_necessarias = int(conquista.CriterioValor)
                    # Assume um PERÍODO FIXO para este tipo de critério (ex: 7 dias).
                    # Se precisar de períodos variáveis, a estrutura do banco precisaria mudar.
                    dias_periodo_fixo = 7 # Ex: Para "Semana de Estreia"
                    data_limite = date.today() - timedelta(days=dias_periodo_fixo)

                    # Conta quantas das datas recentes (datas_tarefas_aprovadas)
                    # estão DENTRO do período definido pela data_limite.
                    count_dentro_periodo = sum(1 for dt in datas_tarefas_aprovadas if dt >= data_limite)

                    # Compara a contagem com o número de tarefas necessárias.
                    if count_dentro_periodo >= num_tarefas_necessarias:
                        atingiu_criterio = True
                except (ValueError, TypeError):
                    logger.warning(f"Valor de critério inválido para conquista ID {conquista.ConquistaID} (tipo 'tarefas_aprovadas_periodo'). Esperado um número, recebido: {conquista.CriterioValor}")
                    atingiu_criterio = False # Garante que não conceda a conquista


            # --- CRITÉRIO 3: Sequência de Dias com Tarefas ---
            elif conquista.CriterioTipo == 'sequencia_dias_tarefas':
                dias_sequencia_necessaria = conquista.CriterioValor
                if len(datas_tarefas_aprovadas) >= dias_sequencia_necessaria:
                    sequencia_encontrada = True
                    for i in range(dias_sequencia_necessaria - 1):
                        # Verifica se a diferença entre dias consecutivos é exatamente 1
                        if (datas_tarefas_aprovadas[i] - datas_tarefas_aprovadas[i+1]).days != 1:
                            sequencia_encontrada = False
                            break
                    if sequencia_encontrada:
                        atingiu_criterio = True

            # --- CRITÉRIO 4: Tarefas de Grupo Competitivo Aceitas ---
            elif conquista.CriterioTipo == 'tarefas_grupo_competitivo_aceitas':
                 if total_grupo_competitivo_aprovadas >= conquista.CriterioValor:
                     atingiu_criterio = True

            # --- CRITÉRIO 5: Total de Comunicados Cientes ---
            elif conquista.CriterioTipo == 'total_comunicados_cientes':
                if total_comunicados_cientes >= conquista.CriterioValor:
                    atingiu_criterio = True

            # --- CRITÉRIO 6: Sequência de Dias com Feedback ---
            elif conquista.CriterioTipo == 'sequencia_feedback_diario':
                dias_sequencia_necessaria = conquista.CriterioValor
                if len(datas_feedback) >= dias_sequencia_necessaria:
                    sequencia_encontrada = True
                    for i in range(dias_sequencia_necessaria - 1):
                        # Verifica se a diferença entre dias consecutivos é exatamente 1
                        if (datas_feedback[i] - datas_feedback[i+1]).days != 1:
                            sequencia_encontrada = False
                            break
                    if sequencia_encontrada:
                        atingiu_criterio = True

            # --- FIM DAS VERIFICAÇÕES DE CRITÉRIOS ---

            # Se qualquer um dos critérios acima foi atingido:
            if atingiu_criterio:
                try:
                    # Concede a conquista (insere na tabela ConquistasFuncionarios)
                    sql_grant = "INSERT INTO ConquistasFuncionarios (FuncionarioID, ConquistaID) VALUES (?, ?)"
                    cursor.execute(sql_grant, funcionario_id, conquista.ConquistaID)
                    conn.commit()
                    novas_conquistas_ganhas.append(conquista) # Adiciona à lista para notificação
                    print(f"--> [CONQUISTA] '{conquista.Nome}' concedida para FuncionarioID {funcionario_id}!")

                    # Concede os pontos de bônus, se houver
                    if conquista.PontosBonus > 0:

                        # --- CHAMADA CORRIGIDA ---
                        # (Assumindo que temos um ID para "Bônus de Conquista",
                        # se não tiver, podemos manter o TAREFA_ID_LEITURA como fallback
                        # ou criar um TAREFA_ID_CONQUISTA. Vamos usar TAREFA_ID_LEITURA
                        # por enquanto, mas com a função nova.)

                        motivo_log = f"Bônus pela conquista: {conquista.Nome}"

                        registrar_pontos_de_bonus(
                            funcionario_id,
                            conquista.PontosBonus,
                            motivo_log,
                            config.TAREFA_ID_LEITURA # <-- Manter este ID se for o "ID de Bônus" geral
                        )
                        
                except pyodbc.IntegrityError:
                    # Ignora erro se, por alguma concorrência rara, a conquista já foi inserida
                    conn.rollback()
                    print(f"--> [CONQUISTA] Aviso: Tentativa de inserir conquista duplicada para FuncionarioID {funcionario_id} e ConquistaID {conquista.ConquistaID}. Ignorando.")
                except Exception as e_grant:
                    conn.rollback()
                    logger.error(f"ERRO CRÍTICO ao conceder conquista ID {conquista.ConquistaID} para FuncionarioID {funcionario_id}: {e_grant}")

        return novas_conquistas_ganhas

    except Exception as e_main:
        logger.error(f"ERRO CRÍTICO GERAL em verificar_e_conceder_conquistas para FuncionarioID {funcionario_id}: {e_main}")
        return [] # Retorna lista vazia em caso de erro grave
    finally:
        if conn:
            conn.close()

# Em database.py, adicione esta nova função
def atualizar_documento_com_file_id(documento_id, file_id):
    """Atualiza um registro de documento existente para adicionar o file_id da foto."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Documentos SET TelegramFileIDFoto = ? WHERE DocumentoID = ?"
            cursor.execute(sql, file_id, documento_id)
            conn.commit()
        finally:
            conn.close()

# Em database.py, adicione este bloco inteiro no final do arquivo

# ===================================================================
# == INÍCIO DO MÓDULO DE DOCUMENTOS PESSOAIS (RH) ===================
# ===================================================================

def salvar_documento_pessoal(funcionario_id, tipo_documento, mes_ano, caminho_arquivo):
    """
    Salva um novo documento pessoal (como um holerite) no catálogo e retorna o ID do novo documento.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO DocumentosPessoais (FuncionarioID, TipoDocumento, MesAno, CaminhoArquivo)
                VALUES (?, ?, ?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, funcionario_id, tipo_documento, mes_ano, caminho_arquivo)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            return novo_id
        except Exception as e:
            logger.error(f"ERRO ao salvar documento pessoal: {e}")
            return None
        finally:
            conn.close()

def criar_pendencia_ciencia_documento_pessoal(documento_id, funcionario_id):
    """
    Cria o registro de 'Pendente' na tabela de ciência para um novo documento pessoal.
    Retorna o ID da nova pendência (CienciaID).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO DocumentosPessoaisCiencia (DocumentoID, FuncionarioID)
                VALUES (?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, documento_id, funcionario_id)
            cursor.nextset()
            ciencia_id = cursor.fetchone()[0]
            conn.commit()
            return ciencia_id
        except Exception as e:
            logger.error(f"ERRO ao criar pendência de ciência para documento pessoal: {e}")
            return None
        finally:
            conn.close()

def atualizar_verificador_cpf(funcionario_id, verificador):
    """Atualiza ou insere os 3 dígitos do CPF para verificação de segurança."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Funcionarios SET VerificadorCPF = ? WHERE FuncionarioID = ?"
            cursor.execute(sql, verificador, funcionario_id)
            conn.commit()
        finally:
            conn.close()

def buscar_verificador_cpf(funcionario_id):
    """Busca o verificador de CPF de um funcionário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT VerificadorCPF FROM Funcionarios WHERE FuncionarioID = ?"
            cursor.execute(sql, funcionario_id)
            resultado = cursor.fetchone()
            return resultado[0] if resultado else None
        finally:
            conn.close()
    return None

def buscar_caminho_documento(documento_id):
    """Busca o caminho completo de um arquivo no servidor a partir do seu ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT CaminhoArquivo FROM DocumentosPessoais WHERE DocumentoID = ?"
            cursor.execute(sql, documento_id)
            resultado = cursor.fetchone()
            return resultado[0] if resultado else None
        finally:
            conn.close()
    return None

def buscar_holerites_disponiveis(funcionario_id):
    """
    Busca os holerites que um funcionário ainda não deu ciência
    e retorna o MesAno para exibição nos botões do Telegram.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT DP.MesAno
                FROM DocumentosPessoais DP
                JOIN DocumentosPessoaisCiencia DPC ON DP.DocumentoID = DPC.DocumentoID
                WHERE DP.FuncionarioID = ? AND DP.TipoDocumento = 'Holerite' AND DPC.Status = 'Pendente'
                ORDER BY DP.MesAno DESC;
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_dados_holerite_para_envio(funcionario_id, mes_ano):
    """
    Busca o caminho do arquivo do holerite e o ID da pendência de ciência
    para um funcionário e mês específicos.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT DP.CaminhoArquivo, DPC.CienciaID
                FROM DocumentosPessoais DP
                JOIN DocumentosPessoaisCiencia DPC ON DP.DocumentoID = DPC.DocumentoID
                WHERE DP.FuncionarioID = ? AND DP.MesAno = ? AND DP.TipoDocumento = 'Holerite'
            """
            cursor.execute(sql, funcionario_id, mes_ano)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def marcar_holerite_como_ciente(ciencia_id):
    """
    Atualiza uma pendência de assinatura de holerite para 'Ciente'
    e preenche a data/hora da confirmação.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE DocumentosPessoaisCiencia
                SET Status = 'Ciente', DataCiencia = GETDATE()
                WHERE CienciaID = ? AND Status = 'Pendente'
            """
            cursor.execute(sql, ciencia_id)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    return False

def listar_documentos_por_funcionario(funcionario_id):
    """Busca os documentos de um funcionário, incluindo o status de ciência."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # AGORA FAZEMOS UM JOIN PARA BUSCAR OS DADOS DA TABELA DE CIÊNCIA
            sql = """
                SELECT 
                    DP.DocumentoID, DP.TipoDocumento, DP.MesAno, DP.DataUpload,
                    DPC.Status, DPC.DataCiencia
                FROM DocumentosPessoais DP
                LEFT JOIN DocumentosPessoaisCiencia DPC ON DP.DocumentoID = DPC.DocumentoID
                WHERE DP.FuncionarioID = ?
                ORDER BY DP.MesAno DESC
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []


def buscar_dados_para_painel_kanban():
    """
    Busca e organiza todas as tarefas para o painel de ação diária.
    (VERSÃO CORRIGIDA - Inclui Tarefas de Grupo no 'PARA FAZER' e na contagem)
    """
    conn = get_db_connection()
    if not conn:
        return {'para_fazer': [], 'validacao': [], 'concluidas': [], 'progresso': {}}

    try:
        cursor = conn.cursor()

        # --- SQL CORRIGIDA ---
        # A query agora tem 3 PARTES:
        # 1. Tarefas Individuais de Hoje
        # 2. Tarefas Individuais Atrasadas
        # 3. Tarefas de Grupo (Competitivas) de Hoje
        sql_para_fazer = """
            WITH Datas AS (
                SELECT
                    GETDATE() as DataHoje,
                    DATEADD(day, -1, GETDATE()) as DataOntem,
                    CASE DATENAME(weekday, GETDATE())
                        WHEN 'Sunday' THEN 1 WHEN 'Domingo' THEN 1 WHEN 'Monday' THEN 2 WHEN 'Segunda-feira' THEN 2
                        WHEN 'Tuesday' THEN 3 WHEN 'Terça-feira' THEN 3 WHEN 'Wednesday' THEN 4 WHEN 'Quarta-feira' THEN 4
                        WHEN 'Thursday' THEN 5 WHEN 'Quinta-feira' THEN 5 WHEN 'Friday' THEN 6 WHEN 'Sexta-feira' THEN 6
                        WHEN 'Saturday' THEN 7 WHEN 'Sábado' THEN 7
                    END as DiaSemanaID_Hoje,
                    CASE DATENAME(weekday, DATEADD(day, -1, GETDATE()))
                        WHEN 'Sunday' THEN 1 WHEN 'Domingo' THEN 1 WHEN 'Monday' THEN 2 WHEN 'Segunda-feira' THEN 2
                        WHEN 'Tuesday' THEN 3 WHEN 'Terça-feira' THEN 3 WHEN 'Wednesday' THEN 4 WHEN 'Quarta-feira' THEN 4
                        WHEN 'Thursday' THEN 5 WHEN 'Quinta-feira' THEN 5 WHEN 'Friday' THEN 6 WHEN 'Sexta-feira' THEN 6
                        WHEN 'Saturday' THEN 7 WHEN 'Sábado' THEN 7
                    END as DiaSemanaID_Ontem
            )

            -- Parte 1: Tarefas Individuais de HOJE (FuncionarioID IS NOT NULL)
            SELECT T.Titulo, F.NomeCompleto, T.Pontos, 'Hoje' as Categoria, TA.DataAtribuicao, D.DataHoje as DataReferencia
            FROM TarefasAtribuidas TA JOIN Tarefas T ON TA.TarefaID = T.TarefaID JOIN Funcionarios F ON TA.FuncionarioID = F.FuncionarioID JOIN Datas D ON 1=1
            WHERE TA.FuncionarioID IS NOT NULL AND TA.DataFimVigencia IS NULL
            AND NOT EXISTS (SELECT 1 FROM Entregas E WHERE E.AtribuicaoID = TA.AtribuicaoID AND CONVERT(date, E.DataEnvio) = CONVERT(date, D.DataHoje) AND E.StatusValidacao != 'Recusada')
            AND ( TA.TipoFrequencia = 'Diaria' OR
                    (TA.TipoFrequencia = 'Semanal' AND CAST(TA.ValorFrequencia AS INT) = D.DiaSemanaID_Hoje) OR
                    (TA.TipoFrequencia = 'Mensal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(day, D.DataHoje)) OR
                    (TA.DataAgendamento IS NOT NULL AND CONVERT(date, TA.DataAgendamento) = CONVERT(date, D.DataHoje)) OR
                    (TA.TipoFrequencia = 'Unica' AND CONVERT(date, TA.DataInicioVigencia) = CONVERT(date, D.DataHoje))
                )
            AND (F.DiaDeFolga IS NULL OR F.DiaDeFolga = 0 OR F.DiaDeFolga != D.DiaSemanaID_Hoje)


            UNION ALL

            -- Parte 3: Tarefas de GRUPO de HOJE (GrupoID IS NOT NULL)
            SELECT T.Titulo, G.NomeGrupo AS NomeCompleto, T.Pontos, 'Hoje' as Categoria, TA.DataAtribuicao, D.DataHoje as DataReferencia
            FROM TarefasAtribuidas TA JOIN Tarefas T ON TA.TarefaID = T.TarefaID JOIN Grupos G ON TA.GrupoID = G.GrupoID JOIN Datas D ON 1=1
            WHERE TA.GrupoID IS NOT NULL AND TA.DataFimVigencia IS NULL
            -- Verifica se NÃO existe uma 'Unica' ACEITA para esta origem HOJE
            AND NOT EXISTS (
                SELECT 1 FROM TarefasAtribuidas TA_Aceita
                WHERE TA_Aceita.OrigemAtribuicaoID = TA.AtribuicaoID
                AND CONVERT(date, TA_Aceita.DataAgendamento) = CONVERT(date, D.DataHoje)
                AND TA_Aceita.StatusTarefaGrupo = 'Aceita'
            )
            -- Verifica se o horário de disparo é HOJE
            AND (
                (TA.TipoFrequencia = 'GrupoDiaria') OR
                (TA.TipoFrequencia = 'GrupoSemanal' AND TA.ValorFrequencia = D.DiaSemanaID_Hoje) OR
                (TA.TipoFrequencia = 'GrupoMensal' AND TA.ValorFrequencia = DATEPART(day, D.DataHoje))
            )

            ORDER BY NomeCompleto, Categoria DESC;
        """
        # --- FIM DA SQL CORRIGIDA ---

        cursor.execute(sql_para_fazer)
        para_fazer_cols = [column[0] for column in cursor.description]
        para_fazer_rows = cursor.fetchall()

        # O restante do código permanece o MESMO
        sql_validacao = "SELECT T.Titulo, F.NomeCompleto, E.DataEnvio, T.Pontos FROM Entregas E JOIN Tarefas T ON E.TarefaID = T.TarefaID JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID WHERE E.StatusValidacao = 'Pendente' ORDER BY E.DataEnvio;"
        cursor.execute(sql_validacao)
        validacao_cols = [column[0] for column in cursor.description]
        validacao_rows = cursor.fetchall()

        sql_concluidas = "SELECT T.Titulo, F.NomeCompleto, E.DataEnvio, E.PontosGanhos as Pontos FROM Entregas E JOIN Tarefas T ON E.TarefaID = T.TarefaID JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID WHERE E.StatusValidacao = 'Aprovada' AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE()) ORDER BY E.DataEnvio DESC;"
        cursor.execute(sql_concluidas)
        concluidas_cols = [column[0] for column in cursor.description]
        concluidas_rows = cursor.fetchall()

        para_fazer_lista = [dict(zip(para_fazer_cols, row)) for row in para_fazer_rows]
        concluidas_lista = [dict(zip(concluidas_cols, row)) for row in concluidas_rows]

        # Esta lógica agora está CORRETA, pois 'para_fazer_lista' inclui tarefas de grupo e individuais
        tarefas_hoje_e_atrasadas_pendentes = len(para_fazer_lista)
        total_concluidas_hoje = len(concluidas_lista)
        total_tarefas_do_dia_ou_atrasadas = tarefas_hoje_e_atrasadas_pendentes + total_concluidas_hoje

        progresso = { "concluidas": total_concluidas_hoje, "total": total_tarefas_do_dia_ou_atrasadas }


        return {
            'para_fazer': para_fazer_lista,
            'validacao': [dict(zip(validacao_cols, row)) for row in validacao_rows],
            'concluidas': concluidas_lista,
            'progresso': progresso
        }
    except Exception as e:
        logger.exception(f"ERRO ao buscar dados para o painel Kanban: {e}") # Use logger.exception
        return {'para_fazer': [], 'validacao': [], 'concluidas': [], 'progresso': {}}
    finally:
        if conn:
            conn.close()



def buscar_ranking_do_dia():
    """
    Calcula o ranking dos 3 funcionários com mais pontos APROVADOS HOJE.
    (VERSÃO CORRIGIDA - já retorna uma lista de dicionários)
    """
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        sql = """
            SELECT TOP 3
                F.NomeCompleto,
                SUM(E.PontosGanhos) as TotalPontosHoje
            FROM Entregas E
            JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID
            WHERE E.StatusValidacao = 'Aprovada'
              AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE())
            GROUP BY
                F.NomeCompleto
            ORDER BY
                TotalPontosHoje DESC;
        """
        cursor.execute(sql)
        # CORREÇÃO: Converte o resultado para uma lista de dicionários aqui dentro
        cols = [column[0] for column in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    finally:
        if conn: conn.close()

def buscar_feed_de_atividades(limite=5):
    """
    Busca os últimos eventos (tarefas aprovadas e conquistas) para o feed.
    (VERSÃO CORRIGIDA - TOP N dinâmico)
    """
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        # --- CORREÇÃO APLICADA AQUI ---
        # Construímos a string SQL com f-string para incluir o TOP N dinamicamente.
        # É seguro aqui porque 'limite' é um número controlado internamente.
        sql = f"""
            SELECT TOP ({int(limite)}) * FROM (
                -- Evento do tipo 'tarefa_concluida'
                SELECT
                    E.DataEnvio as Timestamp,
                    'tarefa_concluida' as TipoEvento,
                    F.NomeCompleto as TextoPrincipal,
                    T.Titulo as TextoSecundario,
                    E.PontosGanhos as Pontos
                FROM Entregas E
                JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID
                JOIN Tarefas T ON E.TarefaID = T.TarefaID
                WHERE E.StatusValidacao = 'Aprovada'

                UNION ALL

                -- Evento do tipo 'conquista'
                SELECT
                    CF.DataConquista as Timestamp,
                    'conquista' as TipoEvento,
                    F.NomeCompleto as TextoPrincipal,
                    C.Nome as TextoSecundario,
                    C.PontosBonus as Pontos
                FROM ConquistasFuncionarios CF
                JOIN Funcionarios F ON CF.FuncionarioID = F.FuncionarioID
                JOIN Conquistas C ON CF.ConquistaID = C.ConquistaID
            ) as FeedEventos
            ORDER BY Timestamp DESC;
        """
        # Executamos a query SEM parâmetros adicionais para o TOP
        cursor.execute(sql)
        # --- FIM DA CORREÇÃO ---

        cols = [column[0] for column in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    except Exception as e:
        # Mantém o log de erro detalhado
        logger.exception(f"Erro crítico dentro de buscar_feed_de_atividades: {e}") # Usando logger.exception
        return [] # Retorna lista vazia em caso de erro
    finally:
        if conn: conn.close()

# COLE ESTA FUNÇÃO DE VOLTA NO SEU ARQUIVO database.py
def autenticar_funcionario(funcionario_id):
    """
    Busca todos os dados de um funcionário pelo ID, incluindo o hash da senha,
    para o processo de autenticação.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM Funcionarios WHERE FuncionarioID = ?"
            cursor.execute(sql, funcionario_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

# ADICIONE ESTA NOVA FUNÇÃO EM database.py
def buscar_chat_id_por_nome_grupo(nome_grupo):
    """Busca o Chat ID de um grupo a partir do seu nome exato."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT ChatIDTelegram FROM Grupos WHERE NomeGrupo = ?"
            cursor.execute(sql, nome_grupo)
            resultado = cursor.fetchone()
            return resultado[0] if resultado else None
        finally:
            conn.close()
    return None

# ADICIONE ESTAS DUAS NOVAS FUNÇÕES EM database.py

def listar_funcionarios_por_setor(setor):
    """Retorna uma lista de todos os funcionários de um setor específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Usamos a coluna Cargo para identificar o setor do funcionário
            sql = "SELECT * FROM Funcionarios WHERE Cargo LIKE ?"
            cursor.execute(sql, f"%{setor}%")
            return cursor.fetchall()
        finally:
            conn.close()
    return []


# Em database.py, adicione esta função auxiliar (pode ser perto de 'registrar_pontos_por_meta_equipe')

def _reverter_pontos_meta_diaria(apuracao_id, pontos_a_remover, meta_principal_id):
    """
    Função auxiliar interna para reverter pontos de meta diária.
    Remove o valor do saldo e exclui o registro de 'Entregas'.
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        # 1. Buscar o setor alvo da meta principal associada
        cursor.execute("SELECT SetorAlvo FROM MetasPrincipais WHERE MetaPrincipalID = ?", meta_principal_id)
        meta_detalhes = cursor.fetchone()
        if not meta_detalhes or not meta_detalhes.SetorAlvo:
            logger.error(f"Clawback falhou: Não foi possível encontrar SetorAlvo para MetaID {meta_principal_id} (ApuracaoID: {apuracao_id})")
            return False

        setor_alvo = meta_detalhes.SetorAlvo

        # 2. Buscar os funcionários desse setor
        funcionarios_do_setor = listar_funcionarios_por_setor(setor_alvo) # Reusa a função existente
        if not funcionarios_do_setor:
            logger.warning(f"Clawback: Nenhum funcionário encontrado no setor '{setor_alvo}' para reverter pontos.")
            return True # Não é um erro, apenas não há ninguém para reverter

        ids_funcionarios = [f.FuncionarioID for f in funcionarios_do_setor]
        placeholders = ','.join('?' * len(ids_funcionarios))

        # 3. Remover os pontos do saldo desses funcionários
        sql_saldo = f"UPDATE Funcionarios SET SaldoPontos = SaldoPontos - ? WHERE FuncionarioID IN ({placeholders})"
        params_saldo = [pontos_a_remover] + ids_funcionarios
        cursor.execute(sql_saldo, params_saldo)
        logger.info(f"Clawback: Saldo de {len(ids_funcionarios)} funcionários (Setor: {setor_alvo}) revertido em -{pontos_a_remover} pontos.")

        # ignorando a data.
        sql_del_entregas = f"""
            DELETE FROM Entregas
            WHERE TarefaID = ? 
              AND AtribuicaoID = ? 
              AND FuncionarioID IN ({placeholders})
        """
        params_del = [config.TAREFA_ID_PONTOS_META, apuracao_id] + ids_funcionarios
        cursor.execute(sql_del_entregas, params_del)
        logger.info(f"Clawback: Registros de 'Entregas' (TarefaID {config.TAREFA_ID_PONTOS_META}) vinculados ao ApuracaoID {apuracao_id} para o setor '{setor_alvo}' excluídos.")
        # --- FIM DA CORREÇÃO ---
        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"ERRO CRÍTICO no clawback de pontos (ApuracaoID: {apuracao_id}): {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()

# Em database.py, SUBSTITUA a função 'excluir_apuracao_diaria' por esta:

def excluir_apuracao_diaria(meta_principal_id, data_apuracao):
    """
    Exclui um registro de apuração diária específico.
    Se esse registro gerou prêmios, executa o 'clawback' (reversão) dos pontos.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # 1. Buscar os detalhes ANTES de excluir
            sql_find = """
                SELECT ApuracaoID, PontosMetaDiariaGanhos 
                FROM MetasDiariasApuracoes 
                WHERE MetaPrincipalID = ? AND DataApuracao = ?
            """
            cursor.execute(sql_find, meta_principal_id, data_apuracao)
            apuracao_dados = cursor.fetchone()

            if not apuracao_dados:
                logger.warning(f"Exclusão falhou: Apuração para MetaID {meta_principal_id} na data {data_apuracao} não encontrada.")
                return False

            apuracao_id, pontos_gerados = apuracao_dados
            pontos_gerados = pontos_gerados or 0 # Garante que não seja None

            # 2. Se gerou pontos, reverter
            if pontos_gerados > 0:
                logger.warning(f"Excluindo ApuracaoID {apuracao_id} que gerou {pontos_gerados} pontos. Iniciando Clawback...")
                if not _reverter_pontos_meta_diaria(apuracao_id, pontos_gerados, meta_principal_id):
                    # Se a reversão falhar, abortamos a exclusão
                    logger.error("Falha no Clawback. A exclusão da apuração foi ABORTADA.")
                    conn.rollback()
                    return False

            # 3. Excluir o registro de apuração
            sql_delete = "DELETE FROM MetasDiariasApuracoes WHERE ApuracaoID = ?"
            cursor.execute(sql_delete, apuracao_id)

            conn.commit()
            logger.info(f"ApuracaoID {apuracao_id} (Data: {data_apuracao}) excluída com sucesso.")
            return cursor.rowcount > 0

        except Exception as e:
            logger.error(f"ERRO ao excluir apuração diária: {e}", exc_info=True)
            if conn: conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    return False



def registrar_pontos_por_meta_equipe(lista_funcionarios, pontos_ganhos, meta_vendas, total_vendido):
    """
    Registra pontos de meta para uma lista de funcionários.
    Cria uma entrega 'Aprovada' para cada um e adiciona os pontos ao saldo.
    """
    conn = get_db_connection()
    # ATENÇÃO: Coloque aqui o ID da tarefa "Performance de Equipe (Metas)" que você criou.
    TAREFA_ID_META = 121 # <<< MUDE ESTE NÚMERO PARA O SEU ID CORRETO!

    if not conn or not lista_funcionarios:
        return False
    
    try:
        cursor = conn.cursor()
        sql_entrega = """
            INSERT INTO Entregas
            (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa)
            VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?)
        """
        motivo = f"Meta de Vendas Atingida! (Vendido: R${total_vendido:.2f} / Meta: R${meta_vendas:.2f})"
        
        for funcionario in lista_funcionarios:
            # 1. Insere um registro na tabela Entregas para o ranking do mês.
            cursor.execute(sql_entrega, TAREFA_ID_META, funcionario.FuncionarioID, pontos_ganhos, motivo)
            
            # 2. Adiciona os pontos ao saldo geral do funcionário.
            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_ganhos)

        conn.commit()
        print(f"--> [METAS EQUIPE] {pontos_ganhos} pts registrados para {len(lista_funcionarios)} funcionário(s).")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"ERRO ao registrar pontos por meta de equipe: {e}")
        return False
    finally:
        if conn:
            conn.close()


# ===================================================================
# == INÍCIO DO NOVO MÓDULO DE GESTÃO DE METAS CONTÍNUAS (V2) ========
# ===================================================================

def criar_meta_principal(nome, desc, valor_total, data_inicio, data_fim, pontos, setor):
    """Cria uma nova meta principal (ex: mensal) no banco de dados."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO MetasPrincipais 
                (NomeMeta, Descricao, ValorMetaTotal, DataInicio, DataFim, PontosPremio, SetorAlvo) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(sql, nome, desc, valor_total, data_inicio, data_fim, pontos, setor)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao criar meta principal: {e}")
            return False
        finally:
            conn.close()

def listar_metas_principais():
    """Lista todas as metas principais cadastradas, das mais novas para as mais antigas."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM MetasPrincipais ORDER BY DataInicio DESC"
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

# Em database.py, SUBSTITUA a sua função lancar_apuracao_diaria por esta versão final:

def lancar_apuracao_diaria(meta_principal_id, data_apuracao, valor_dia, funcionario_id):
    """(VERSÃO V3.1 FINAL) Salva a apuração usando MERGE e RETORNA o ID da apuração."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                MERGE INTO MetasDiariasApuracoes AS target
                USING (SELECT ? AS MetaPrincipalID, ? AS DataApuracao) AS source
                ON (target.MetaPrincipalID = source.MetaPrincipalID AND target.DataApuracao = source.DataApuracao)
                WHEN MATCHED THEN
                    UPDATE SET ValorDia = ?, FuncionarioID_Lancamento = ?
                WHEN NOT MATCHED THEN
                    INSERT (MetaPrincipalID, DataApuracao, ValorDia, FuncionarioID_Lancamento)
                    VALUES (?, ?, ?, ?);

                SELECT ApuracaoID FROM MetasDiariasApuracoes WHERE MetaPrincipalID = ? AND DataApuracao = ?;
            """
            params = (
                meta_principal_id, data_apuracao, # Para o USING
                valor_dia, funcionario_id,         # Para o UPDATE
                meta_principal_id, data_apuracao, valor_dia, funcionario_id, # Para o INSERT
                meta_principal_id, data_apuracao  # Para o SELECT final
            )
            cursor.execute(sql, params)
            
            # --- A CORREÇÃO MÁGICA ESTÁ AQUI ---
            # Diz ao driver para avançar para o próximo resultado (o do SELECT).
            cursor.nextset()
            # ------------------------------------
            
            apuracao_id = cursor.fetchone()[0]
            conn.commit()
            return True, apuracao_id
        except Exception as e:
            logger.error(f"ERRO ao lançar apuração diária: {e}")
            if conn:
                conn.rollback()
            return False, str(e)
        finally:
            if conn:
                conn.close()
    return False, "Erro de conexão com o banco."

def buscar_meta_principal_do_dia():
    """
    Busca a meta principal ativa para hoje e calcula o total já atingido
    somando todas as apurações diárias vinculadas a ela.
    Esta é a função que a API usará para o painel.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Esta query faz tudo: encontra a meta ativa e já calcula a soma do "extrato"
            sql = """
                SELECT TOP 1
                    MP.MetaPrincipalID,
                    MP.NomeMeta,
                    MP.ValorMetaTotal,
                    (SELECT SUM(ValorDia) FROM MetasDiariasApuracoes MDA WHERE MDA.MetaPrincipalID = MP.MetaPrincipalID) as ValorAtingidoTotal
                FROM MetasPrincipais MP
                WHERE GETDATE() BETWEEN MP.DataInicio AND MP.DataFim AND MP.Status = 'Ativa'
            """
            cursor.execute(sql)
            meta_ativa = cursor.fetchone()
            if meta_ativa:
                return {
                    "nome_meta": meta_ativa.NomeMeta,
                    "valor_meta": float(meta_ativa.ValorMetaTotal),
                    # Se não houver nenhum lançamento, o ValorAtingidoTotal será None. Garantimos que ele vire 0.
                    "valor_atingido": float(meta_ativa.ValorAtingidoTotal or 0)
                }
            return None # Nenhuma meta ativa para o dia de hoje
        finally:
            conn.close()
    return None

# Em database.py, adicione esta nova função no final do bloco de metas

def listar_apuracoes_por_meta_principal(meta_principal_id):
    """Busca o 'extrato' de todos os lançamentos diários para uma meta principal específica."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT DataApuracao, ValorDia 
                FROM MetasDiariasApuracoes 
                WHERE MetaPrincipalID = ? 
                ORDER BY DataApuracao DESC
            """
            cursor.execute(sql, meta_principal_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

# Em database.py, ADICIONE este bloco inteiro no final do arquivo

# ===================================================================
# == INÍCIO DO MÓDULO DE METAS DIÁRIAS POR DIA DA SEMANA ============
# ===================================================================

def listar_modelos_metas_diarias():
    """Busca os 7 modelos de metas, um para cada dia da semana."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM MetasDiariasModelos ORDER BY DiaSemanaID"
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def atualizar_modelo_meta_diaria(dia_semana_id, valor_meta, pontos_premio):
    """Atualiza o valor e os pontos de um modelo de meta diária."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE MetasDiariasModelos SET ValorMeta = ?, PontosPremio = ? WHERE DiaSemanaID = ?"
            cursor.execute(sql, valor_meta, pontos_premio, dia_semana_id)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def buscar_modelo_meta_para_data(data_apuracao):
    """Busca o modelo de meta diária correspondente a uma data específica."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Esta query usa a data para descobrir o dia da semana correspondente no SQL Server
            sql = """
                SELECT * FROM MetasDiariasModelos 
                WHERE DiaSemanaID = DATEPART(weekday, ?)
            """
            cursor.execute(sql, data_apuracao)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

# Em database.py, SUBSTITUA a sua função registrar_pontos_meta_diaria por esta:

def registrar_pontos_meta_diaria(apuracao_id, pontos_ganhos, setor):
    """
    (VERSÃO V2) Marca uma apuração como premiada, distribui os pontos e
    RETORNA A LISTA de funcionários que foram premiados.
    """
    conn = get_db_connection()
    TAREFA_ID_META = 121

    if not conn: return [] # Retorna lista vazia em caso de erro

    try:
        cursor = conn.cursor()
        sql_marcar = "UPDATE MetasDiariasApuracoes SET PontosMetaDiariaGanhos = ? WHERE ApuracaoID = ?"
        cursor.execute(sql_marcar, pontos_ganhos, apuracao_id)

        funcionarios_do_setor = listar_funcionarios_por_setor(setor)
        if not funcionarios_do_setor:
            conn.commit()
            return [] # Retorna lista vazia se não houver funcionários

        sql_entrega = """
            INSERT INTO Entregas (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa)
            VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?)
        """
        motivo = f"Prêmio por atingir a meta diária do setor '{setor}'."
        
        print(f"--- DEBUG REGISTRAR PONTOS META ---")
        print(f"Setor Alvo Recebido: '{setor}'")
        print(f"Funcionários Encontrados no Setor: {len(funcionarios_do_setor)}")
        if funcionarios_do_setor:
            print(f"IDs dos funcionários encontrados: {[f.FuncionarioID for f in funcionarios_do_setor]}")

        for funcionario in funcionarios_do_setor:
            cursor.execute(sql_entrega, TAREFA_ID_META, funcionario.FuncionarioID, pontos_ganhos, motivo)
            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_ganhos)

        conn.commit()
        print(f"--> [METAS DIÁRIAS] {pontos_ganhos} pts registrados para {len(funcionarios_do_setor)} funcionário(s) do setor '{setor}'.")
        return funcionarios_do_setor # <-- A MÁGICA! Retorna a lista de funcionários.
    except Exception as e:
        conn.rollback()
        logger.error(f"ERRO ao registrar pontos por meta diária: {e}")
        return []
    finally:
        if conn:
            conn.close()

def marcar_meta_principal_como_concluida(meta_id):
    """Atualiza o status de uma meta principal para 'Concluida'."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE MetasPrincipais SET Status = 'Concluida' WHERE MetaPrincipalID = ?"
            cursor.execute(sql, meta_id)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def distribuir_premio_meta_principal(meta_id):
    """
    Busca os detalhes da meta principal, encontra os funcionários do setor alvo,
    distribui os pontos de prêmio e RETORNA a lista de funcionários premiados.
    """
    conn = get_db_connection()
    if not conn: return []

    try:
        cursor = conn.cursor()
        # Etapa 1: Buscar os detalhes da meta
        cursor.execute("SELECT PontosPremio, SetorAlvo FROM MetasPrincipais WHERE MetaPrincipalID = ?", meta_id)
        meta_detalhes = cursor.fetchone()
        if not meta_detalhes: return []

        pontos_premio, setor_alvo = meta_detalhes

        # Etapa 2: Usar a função que já temos para buscar os funcionários
        funcionarios_do_setor = listar_funcionarios_por_setor(setor_alvo)
        if not funcionarios_do_setor: return []

        # Etapa 3: Distribuir os pontos (reutilizando a lógica da meta diária)
        TAREFA_ID_META = 121
        sql_entrega = "INSERT INTO Entregas (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa) VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?)"
        motivo = f"Prêmio por atingir a META MENSAL do setor '{setor_alvo}'!"
        
        for funcionario in funcionarios_do_setor:
            cursor.execute(sql_entrega, TAREFA_ID_META, funcionario.FuncionarioID, pontos_premio, motivo)
            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_premio)

        # Etapa 4: Marcar a meta como concluída para não premiar de novo
        marcar_meta_principal_como_concluida(meta_id)
        
        conn.commit()
        return funcionarios_do_setor

    except Exception as e:
        conn.rollback()
        logger.error(f"ERRO ao distribuir prêmio de meta principal: {e}")
        return []
    finally:
        if conn: conn.close()

# Em database.py, SUBSTITUA a função buscar_meta_ativa_id_hoje por esta:

# Em database.py, SUBSTITUA a função buscar_meta_ativa_id_hoje por esta:

def buscar_meta_ativa_id_hoje():
    """Busca apenas o ID da meta principal ativa na data de hoje."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # --- CORREÇÃO APLICADA AQUI ---
            # Usamos CONVERT(DATE, ...) para ignorar as horas, minutos e segundos.
            # Isso garante que a data de hoje (ex: 31/10 23:00) seja
            # considerada "entre" a data de início (01/10 00:00) e a data de fim (31/10 00:00).
            sql = """
                SELECT TOP 1 MetaPrincipalID
                FROM MetasPrincipais MP
                WHERE CONVERT(DATE, GETDATE()) BETWEEN CONVERT(DATE, MP.DataInicio) AND CONVERT(DATE, MP.DataFim)
                  AND MP.Status = 'Ativa'
            """
            # --- FIM DA CORREÇÃO ---
            
            cursor.execute(sql)
            resultado = cursor.fetchone()
            # Adiciona um log para sabermos se encontrou
            if resultado:
                logger.info(f"Meta ativa ID {resultado[0]} encontrada para hoje.")
            else:
                logger.warning("Nenhuma meta principal ativa encontrada para hoje na verificação (buscar_meta_ativa_id_hoje).")
            
            return resultado[0] if resultado else None
        
        except Exception as e:
            # Adiciona log de erro para esta função específica
            logger.error(f"Erro ao buscar meta ativa ID hoje: {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()
    return None
def excluir_apuracao_diaria(meta_principal_id, data_apuracao):
    """Exclui um registro de apuração diária específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                DELETE FROM MetasDiariasApuracoes 
                WHERE MetaPrincipalID = ? AND DataApuracao = ?
            """
            cursor.execute(sql, meta_principal_id, data_apuracao)
            conn.commit()
            return cursor.rowcount > 0 # Retorna True se uma linha foi afetada
        except Exception as e:
            logger.error(f"ERRO ao excluir apuração diária: {e}")
            return False
        finally:
            conn.close()
    return False

def buscar_dados_meta_diaria_hoje():
    """
    Busca o modelo da meta para o dia de hoje e o valor já apurado para hoje.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    (SELECT ValorMeta FROM MetasDiariasModelos WHERE DiaSemanaID = DATEPART(weekday, GETDATE())) as MetaDoDia,
                    (SELECT SUM(ValorDia) FROM MetasDiariasApuracoes WHERE CONVERT(date, DataApuracao) = CONVERT(date, GETDATE())) as AtingidoHoje
            """
            cursor.execute(sql)
            resultado = cursor.fetchone()
            if resultado:
                return {
                    "valor_meta_diaria": float(resultado.MetaDoDia or 0),
                    "valor_atingido_hoje": float(resultado.AtingidoHoje or 0)
                }
            return None
        finally:
            conn.close()
    return None

def buscar_grupo_por_chat_id(chat_id):
    """Busca os detalhes de um grupo a partir do seu Chat ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM Grupos WHERE ChatIDTelegram = ?"
            cursor.execute(sql, chat_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def listar_membros_por_chat_id_grupo(chat_id):
    """Busca todos os funcionários que são membros de um grupo a partir do Chat ID do grupo."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT F.FuncionarioID, F.NomeCompleto, F.ChatIDTelegram
                FROM Funcionarios F
                JOIN FuncionariosGrupos FG ON F.FuncionarioID = FG.FuncionarioID
                JOIN Grupos G ON FG.GrupoID = G.GrupoID
                WHERE G.ChatIDTelegram = ?
            """
            cursor.execute(sql, chat_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def criar_conquista(nome, descricao, icone, criterio_tipo, criterio_valor, pontos_bonus):
    """Insere um novo modelo de conquista no banco."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO Conquistas (Nome, Descricao, Icone, CriterioTipo, CriterioValor, PontosBonus)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            cursor.execute(sql, nome, descricao, icone, criterio_tipo, criterio_valor, pontos_bonus)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao criar conquista: {e}")
            return False
        finally:
            conn.close()
    return False

def atualizar_conquista(conquista_id, nome, descricao, icone, criterio_tipo, criterio_valor, pontos_bonus):
    """Atualiza um modelo de conquista existente."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE Conquistas
                SET Nome = ?, Descricao = ?, Icone = ?, CriterioTipo = ?, CriterioValor = ?, PontosBonus = ?
                WHERE ConquistaID = ?
            """
            cursor.execute(sql, nome, descricao, icone, criterio_tipo, criterio_valor, pontos_bonus, conquista_id)
            conn.commit()
            return cursor.rowcount > 0 # Retorna True se alguma linha foi afetada
        except Exception as e:
            logger.error(f"ERRO ao atualizar conquista: {e}")
            return False
        finally:
            conn.close()
    return False

def excluir_conquista(conquista_id):
    """Exclui um modelo de conquista e as associações com funcionários."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Primeiro, remove dos funcionários que a ganharam
            sql_assoc = "DELETE FROM ConquistasFuncionarios WHERE ConquistaID = ?"
            cursor.execute(sql_assoc, conquista_id)
            # Depois, remove o modelo da conquista
            sql_modelo = "DELETE FROM Conquistas WHERE ConquistaID = ?"
            cursor.execute(sql_modelo, conquista_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao excluir conquista: {e}")
            conn.rollback() # Desfaz se der erro em uma das exclusões
            return False
        finally:
            conn.close()
    return False

# Em database.py, ADICIONE estas funções no final:

def buscar_atribuicoes_periodo(funcionario_id, data_inicio, data_fim):
    """Busca tarefas atribuídas a um funcionário dentro de um período específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Seleciona atribuições cuja vigência INTERSECTA o período solicitado
            sql = """
                SELECT
                    TA.AtribuicaoID, T.Titulo, T.Pontos, TA.TipoFrequencia, TA.ValorFrequencia,
                    TA.DataInicioVigencia, TA.DataFimVigencia, TA.DataAceite
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE TA.FuncionarioID = ?
                  AND (TA.DataFimVigencia IS NULL OR TA.DataFimVigencia >= ?) -- Não encerrada antes do início do período
                  AND (TA.DataInicioVigencia <= ?) -- Iniciada antes ou durante o fim do período
                ORDER BY TA.DataInicioVigencia DESC
            """
            cursor.execute(sql, funcionario_id, data_inicio, data_fim)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_entregas_aprovadas_periodo(funcionario_id, data_inicio, data_fim):
    """Busca entregas aprovadas de um funcionário dentro de um período específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT E.EntregaID, T.Titulo, E.DataEnvio, E.PontosGanhos
                FROM Entregas E
                JOIN Tarefas T ON E.TarefaID = T.TarefaID
                WHERE E.FuncionarioID = ?
                  AND E.StatusValidacao = 'Aprovada'
                  AND CONVERT(DATE, E.DataEnvio) BETWEEN ? AND ?
                ORDER BY E.DataEnvio DESC
            """
            cursor.execute(sql, funcionario_id, data_inicio, data_fim)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def calcular_pontos_possiveis_debug(funcionario_id, data_inicio, data_fim):
    """
    REPLICA a lógica de cálculo de pontos possíveis da função de ranking,
    mas para um período específico, para fins de depuração.
    Retorna o total de pontos possíveis calculados.
    """
    conn = get_db_connection()
    if not conn: return 0

    try:
        cursor = conn.cursor()
        # Busca as atribuições ativas E o dia de folga do funcionário
        sql_tarefas_atribuidas = """
            SELECT
                   TA.AtribuicaoID, TA.TipoFrequencia, TA.ValorFrequencia,
                   T.Pontos, TA.DataInicioVigencia, TA.DataFimVigencia,
                   TA.DataAceite, F.DiaDeFolga
            FROM TarefasAtribuidas TA
            JOIN Tarefas T ON TA.TarefaID = T.TarefaID
            JOIN Funcionarios F ON TA.FuncionarioID = F.FuncionarioID
            WHERE TA.FuncionarioID = ?
        """
        cursor.execute(sql_tarefas_atribuidas, funcionario_id)
        tarefas_funcionario = cursor.fetchall()

        pontos_possiveis_total = 0
        dia_folga_func = None # Pega a folga da primeira tarefa (deve ser a mesma para todas)

        for tarefa in tarefas_funcionario:
            if dia_folga_func is None: # Pega o dia de folga apenas uma vez
                 dia_folga_func = tarefa.DiaDeFolga

            # Lógica para tarefas 'Unica' ou 'GrupoCompetitiva'
            if tarefa.TipoFrequencia in ('GrupoCompetitiva', 'Unica'):
                data_ref = tarefa.DataAceite if tarefa.TipoFrequencia == 'GrupoCompetitiva' else tarefa.DataInicioVigencia
                if data_ref and data_inicio <= _get_date_part(data_ref) <= data_fim: # Verifica se está DENTRO do período
                    # Considera apenas se a atribuição estava ativa no período
                    data_fim_vigencia = _get_date_part(tarefa.DataFimVigencia) if tarefa.DataFimVigencia else data_fim # Usa data_fim se for nulo
                    if data_fim_vigencia >= data_inicio: # Garante que não encerrou antes do período começar
                        pontos_possiveis_total += tarefa.Pontos
                continue

            # Lógica para tarefas recorrentes
            dias_ocorrencia = 0
            # Define o período de cálculo (intersecção da vigência da tarefa com o período solicitado)
            start_date_tarefa = _get_date_part(tarefa.DataInicioVigencia) if tarefa.DataInicioVigencia else data_inicio
            end_date_tarefa = _get_date_part(tarefa.DataFimVigencia) if tarefa.DataFimVigencia else data_fim

            start_date_calc = max(start_date_tarefa, data_inicio)
            end_date_calc = min(end_date_tarefa, data_fim)

            if end_date_calc < start_date_calc: continue

            for dia_atual in (start_date_calc + timedelta(days=n) for n in range((end_date_calc - start_date_calc).days + 1)):
                dia_da_semana_sql = (dia_atual.weekday() + 1) % 7 + 1
                if str(dia_da_semana_sql) == str(dia_folga_func):
                    continue # PULA O DIA SE FOR FOLGA!

                if tarefa.TipoFrequencia == 'Diaria': dias_ocorrencia += 1
                elif tarefa.TipoFrequencia == 'Semanal':
                    if str(dia_da_semana_sql) == str(tarefa.ValorFrequencia): dias_ocorrencia += 1
                elif tarefa.TipoFrequencia == 'Mensal':
                    # Verifica se o dia do mês é o correto E se está dentro do período da tarefa
                    if dia_atual.day == int(tarefa.ValorFrequencia): dias_ocorrencia += 1

            pontos_possiveis_total += dias_ocorrencia * tarefa.Pontos

        return pontos_possiveis_total

    except Exception as e:
        logger.error(f"ERRO ao calcular pontos possíveis (debug): {e}")
        return 0
    finally:
        if conn: conn.close()

# Em database.py

def excluir_entrega(entrega_id):
    """Exclui um registro específico da tabela Entregas E AJUSTA O SALDO DE PONTOS."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # 1. Buscar os dados ANTES de excluir
            sql_find = "SELECT FuncionarioID, PontosGanhos FROM Entregas WHERE EntregaID = ?"
            cursor.execute(sql_find, entrega_id)
            entrega_dados = cursor.fetchone()

            if not entrega_dados:
                logger.warning(f"Tentativa de excluir EntregaID {entrega_id} que não foi encontrada.")
                return False # Entrega não existe

            funcionario_id, pontos_a_remover = entrega_dados
            # Garante que pontos_a_remover seja 0 se for None (caso a entrega não tivesse pontos)
            pontos_a_remover = pontos_a_remover or 0

            # 2. Excluir a entrega
            sql_delete = "DELETE FROM Entregas WHERE EntregaID = ?"
            cursor.execute(sql_delete, entrega_id)
            rows_affected = cursor.rowcount # Verifica se realmente excluiu algo

            # 3. Subtrair os pontos do saldo (APENAS se a exclusão foi bem-sucedida E havia pontos a remover)
            if rows_affected > 0 and pontos_a_remover != 0: # Verifica se pontos_a_remover é diferente de zero
                 # Usamos a função adicionar_pontos_ao_saldo com valor negativo
                 # A função adicionar_pontos_ao_saldo já existe e lida com a conexão
                 adicionar_pontos_ao_saldo(funcionario_id, -pontos_a_remover)
                 logger.info(f"Saldo ajustado em {-pontos_a_remover} pontos para FuncionarioID {funcionario_id} após exclusão da EntregaID {entrega_id}.")

            conn.commit()
            return rows_affected > 0 # Retorna True se deletou algo

        except Exception as e:
            conn.rollback() # Desfaz tudo em caso de erro
            logger.error(f"ERRO CRÍTICO ao excluir entrega e ajustar saldo (EntregaID: {entrega_id}): {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    return False

def editar_pontos_entrega(entrega_id, novos_pontos):
    """Edita apenas o valor de PontosGanhos para uma entrega específica."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Busca o funcionário ID para recalcular o saldo depois
            cursor.execute("SELECT FuncionarioID, PontosGanhos FROM Entregas WHERE EntregaID = ?", entrega_id)
            res = cursor.fetchone()
            if not res: return False
            funcionario_id, pontos_antigos = res
            pontos_antigos = pontos_antigos or 0 # Garante que não seja None

            # Atualiza os pontos na entrega
            sql_update = "UPDATE Entregas SET PontosGanhos = ? WHERE EntregaID = ?"
            cursor.execute(sql_update, novos_pontos, entrega_id)

            # Recalcula o saldo do funcionário (remove o antigo, adiciona o novo)
            diferenca = novos_pontos - pontos_antigos
            adicionar_pontos_ao_saldo(funcionario_id, diferenca) # Usa a função existente

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"ERRO ao editar pontos da entrega: {e}")
            return False
        finally:
            conn.close()
    return False

def buscar_extrato_pontos_funcionario(funcionario_id, data_inicio, data_fim):
    """
    Busca um extrato completo de todas as transações de pontos (entradas e saídas)
    para um funcionário dentro de um período, ordenado por data.
    Retorna uma lista de dicionários ou lista vazia se erro/sem dados.
    """
    conn = get_db_connection()
    extrato = []
    if conn:
        try:
            cursor = conn.cursor()
            # Query que une Entregas (pontos ganhos) e Resgates (pontos gastos)
            # Inclui um Saldo Parcial calculado na hora (requer SQL Server 2012+)
            sql = """
                WITH Transacoes AS (
                    -- Entradas de Pontos (Tarefas Aprovadas, Bônus)
                    SELECT
                        E.DataEnvio AS DataTransacao, -- Usamos DataEnvio (que agora é data da aprovação)
                        CASE
                            WHEN E.TarefaID = ? THEN 'Bônus: Feedback Diário'
                            WHEN E.TarefaID = ? THEN 'Bônus: Leitura Comunicado'
                            WHEN E.TarefaID = ? THEN 'Bônus: Meta Equipe Atingida'
                            -- Adicione mais casos para outros bônus se necessário
                            ELSE ISNULL(T.Titulo, 'Entrada Desconhecida')
                        END AS Descricao,
                        ISNULL(E.PontosGanhos, 0) AS Pontos -- Pontos positivos
                    FROM Entregas E
                    LEFT JOIN Tarefas T ON E.TarefaID = T.TarefaID
                    WHERE E.FuncionarioID = ?
                      AND E.StatusValidacao = 'Aprovada'
                      AND CONVERT(DATE, E.DataEnvio) BETWEEN ? AND ?
                      AND ISNULL(E.PontosGanhos, 0) != 0 -- Ignora entradas com 0 pontos

                    UNION ALL

                    -- Saídas de Pontos (Resgates Aprovados)
                    SELECT
                        R.DataAprovacao AS DataTransacao,
                        'Resgate: ' + P.Nome AS Descricao,
                        -R.PontosGastos AS Pontos -- Pontos negativos
                    FROM Resgates R
                    JOIN ProdutosLoja P ON R.ProdutoID = P.ProdutoID
                    WHERE R.FuncionarioID = ?
                      AND R.Status = 'Aprovado'
                      AND R.DataAprovacao IS NOT NULL
                      AND CONVERT(DATE, R.DataAprovacao) BETWEEN ? AND ?
                )
                -- Seleciona as transações e calcula o saldo acumulado
                SELECT
                    DataTransacao,
                    Descricao,
                    Pontos
                FROM Transacoes
                ORDER BY DataTransacao ASC; -- Ordena do mais antigo para o mais recente
            """

            # Passa os IDs das tarefas de bônus e os parâmetros do funcionário/datas
            params = [
                config.TAREFA_ID_FEEDBACK_DIARIO,
                config.TAREFA_ID_LEITURA,
                config.TAREFA_ID_PONTOS_META,
                funcionario_id, data_inicio, data_fim, # Para Entregas
                funcionario_id, data_inicio, data_fim  # Para Resgates
            ]

            cursor.execute(sql, params)
            cols = [column[0] for column in cursor.description]
            extrato = [dict(zip(cols, row)) for row in cursor.fetchall()]

            # --- Cálculo do Saldo Inicial e Acumulado (feito em Python) ---
            # 1. Buscar saldo ANTES da data de início
            sql_saldo_inicial = """
                SELECT ISNULL(SUM(CASE WHEN Tipo = 'Entrada' THEN Pontos ELSE -Pontos END), 0)
                FROM (
                    SELECT 'Entrada' as Tipo, ISNULL(PontosGanhos, 0) as Pontos, DataEnvio as DataOp
                    FROM Entregas WHERE FuncionarioID = ? AND StatusValidacao = 'Aprovada' AND CONVERT(DATE, DataEnvio) < ?
                    UNION ALL
                    SELECT 'Saida' as Tipo, PontosGastos as Pontos, DataAprovacao as DataOp
                    FROM Resgates WHERE FuncionarioID = ? AND Status = 'Aprovado' AND DataAprovacao IS NOT NULL AND CONVERT(DATE, DataAprovacao) < ?
                ) as SaldoAntes;
            """
            cursor.execute(sql_saldo_inicial, funcionario_id, data_inicio, funcionario_id, data_inicio)
            saldo_inicial = cursor.fetchone()[0] or 0

            # 2. Adicionar Saldo Acumulado ao extrato
            saldo_acumulado = saldo_inicial
            for transacao in extrato:
                saldo_acumulado += transacao['Pontos']
                transacao['SaldoNaData'] = saldo_acumulado # Adiciona nova chave

            return extrato, saldo_inicial # Retorna o extrato e o saldo inicial

        except Exception as e:
            logger.error(f"Erro ao buscar extrato de pontos: {e}", exc_info=True)
            return [], 0 # Retorna vazio e saldo 0 em caso de erro
        finally:
            if conn:
                conn.close()
    return [], 0 # Retorna vazio e saldo 0 se conexão falhar


# --- COLE ESTE BLOCO NO FINAL DO ARQUIVO database.py ---

# Certifique-se de que 'import notificador_telegram' e 'import logging' (e datetime)
# estão no topo do arquivo database.py
# ===================================================================
# == INÍCIO DO MÓDULO DE HISTÓRICO DE LUCRO MENSAL ==================
# ===================================================================
import locale # Adicione esta importação se ainda não existir no topo do arquivo database.py

def salvar_lucro_mensal(ano, mes, percentual):
    """
    Salva ou atualiza o percentual de lucro para um ano/mês específico.
    Retorna True em caso de sucesso, False em caso de erro.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                MERGE INTO LucroMensalHistorico AS target
                USING (SELECT ? AS Ano, ? AS Mes) AS source
                ON (target.Ano = source.Ano AND target.Mes = source.Mes)
                WHEN MATCHED THEN
                    UPDATE SET PercentualLucro = ?, DataRegistro = GETDATE()
                WHEN NOT MATCHED THEN
                    INSERT (Ano, Mes, PercentualLucro)
                    VALUES (?, ?, ?);
            """
            cursor.execute(sql,
                           ano, mes, # Para o USING
                           percentual, # Para o UPDATE
                           ano, mes, percentual) # Para o INSERT
            conn.commit()
            logger.info(f"Lucro de {mes}/{ano} salvo/atualizado para {percentual}%.")
            return True
        except Exception as e:
            logger.error(f"ERRO ao salvar lucro mensal para {mes}/{ano}: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    return False

def buscar_historico_lucro_ultimos_meses(num_meses=3):
    """
    Busca o histórico de lucro dos últimos 'num_meses' registrados.
    Retorna uma lista de dicionários: [{'mes': 'NomeMes', 'percentual': 18.5}, ...]
    """
    conn = get_db_connection()
    historico = []
    if conn:
        try:
            cursor = conn.cursor()
            # Busca os últimos N meses registrados, ordenados do mais recente para o mais antigo
            sql = f"""
                SELECT TOP ({int(num_meses)})
                    Ano, Mes, PercentualLucro
                FROM LucroMensalHistorico
                ORDER BY Ano DESC, Mes DESC
            """
            cursor.execute(sql)
            resultados = cursor.fetchall()

            # Tenta configurar o locale para português para nomes dos meses
            try:
                locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
                locale_ok = True
            except locale.Error:
                logger.warning("Locale pt_BR.UTF-8 não disponível para nomes de meses no histórico de lucro.")
                locale_ok = False

            for row in reversed(resultados): # Inverte para mostrar do mais antigo para o mais recente
                # Cria um objeto date para facilitar a formatação do nome do mês
                try:
                     # Cria uma data (dia 1 do mês/ano)
                    data_obj = date(row.Ano, row.Mes, 1)
                    if locale_ok:
                        nome_mes = data_obj.strftime('%B').capitalize()
                    else:
                         # Fallback manual simples se o locale falhar
                        meses_pt = ["Inválido", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
                        nome_mes = meses_pt[row.Mes] if 1 <= row.Mes <= 12 else "Mês?"
                except ValueError:
                     nome_mes = f"Data Inv. ({row.Mes}/{row.Ano})"


                historico.append({"mes": nome_mes, "percentual": float(row.PercentualLucro)})

            # Garante que sempre retorne 'num_meses' itens, preenchendo com N/A se faltar
            while len(historico) < num_meses:
                historico.insert(0, {"mes": "N/A", "percentual": 0.0})

            return historico

        except Exception as e:
            logger.error(f"Erro ao buscar histórico de lucro: {e}", exc_info=True)
            # Retorna N/A se der erro
            return [{"mes": "Erro", "percentual": 0.0}] * num_meses
        finally:
            if conn:
                conn.close()
    # Retorna N/A se der erro de conexão
    return [{"mes": "Erro DB", "percentual": 0.0}] * num_meses


# ===================================================================
# == FIM DO MÓDULO DE HISTÓRICO DE LUCRO MENSAL =====================
# ===================================================================

def listar_lucros_mensais():
    """Busca todos os lucros mensais lançados, ordenados por data."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Adicionamos o LucroID para permitir edição/exclusão
            sql = """
                SELECT HistoricoID, Ano, Mes, PercentualLucro 
                FROM LucroMensalHistorico 
                ORDER BY Ano DESC, Mes DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao listar lucros mensais: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def atualizar_lucro_mensal(lucro_id, novo_percentual):
    """Atualiza o percentual de um lançamento de lucro específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE LucroMensalHistorico SET PercentualLucro = ? WHERE HistoricoID = ?"
            cursor.execute(sql, novo_percentual, lucro_id)
            conn.commit()
            return cursor.rowcount > 0 # Retorna True se a atualização foi bem-sucedida
        except Exception as e:
            logger.error(f"Erro ao atualizar lucro mensal (ID: {lucro_id}): {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    return False

def excluir_lucro_mensal(lucro_id):
    """Exclui um lançamento de lucro mensal específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM LucroMensalHistorico WHERE HistoricoID = ?"
            cursor.execute(sql, lucro_id)
            conn.commit()
            return cursor.rowcount > 0 # Retorna True se a exclusão foi bem-sucedida
        except Exception as e:
            logger.error(f"Erro ao excluir lucro mensal (ID: {lucro_id}): {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    return False
# O logger já deve estar configurado pelo bloco no início do arquivo.

def buscar_resgates_recentes(limite=5):
    """
    Busca os últimos resgates APROVADOS para o novo feed de Resgates Recentes.
    """
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        # Busca os últimos N resgates aprovados
        sql = f"""
            SELECT TOP ({int(limite)})
                F.NomeCompleto AS TextoPrincipal,
                P.Nome AS TextoSecundario,
                R.PontosGastos AS Pontos,
                R.DataAprovacao AS Timestamp
            FROM Resgates R
            JOIN Funcionarios F ON R.FuncionarioID = F.FuncionarioID
            JOIN ProdutosLoja P ON R.ProdutoID = P.ProdutoID
            WHERE R.Status = 'Aprovado' AND R.DataAprovacao IS NOT NULL
            ORDER BY R.DataAprovacao DESC;
        """
        cursor.execute(sql)
        cols = [column[0] for column in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    except Exception as e:
        logger.exception(f"Erro crítico dentro de buscar_resgates_recentes: {e}")
        return [] # Retorna lista vazia em caso de erro
    finally:
        if conn: conn.close()

# Em database.py, SUBSTITUA a função verificar_e_premiar_meta_diaria por esta:

def verificar_e_premiar_meta_diaria(apuracao_id, data_apuracao_str, valor_dia, meta_principal_id):
    """
    Função auxiliar para verificar se a meta diária foi atingida e premiar a equipe DO SETOR CORRETO.
    (VERSÃO CORRIGIDA COM LÓGICA DE CLAWBACK)
    """
    try:
        modelo_meta_diaria = buscar_modelo_meta_para_data(data_apuracao_str) # Chamada interna

        # Buscar o status de premiação ANTES de qualquer ação
        conn_check = get_db_connection()
        ja_premiada = False
        pontos_premiados_anteriormente = 0 # << NOVO
        if conn_check:
            try:
                cursor_check = conn_check.cursor()
                cursor_check.execute("SELECT PontosMetaDiariaGanhos FROM MetasDiariasApuracoes WHERE ApuracaoID = ?", apuracao_id)
                res_check = cursor_check.fetchone()
                # Verifica se res_check não é None e se o valor é maior que 0
                if res_check and res_check[0] is not None and res_check[0] > 0:
                    ja_premiada = True
                    pontos_premiados_anteriormente = res_check[0] # << NOVO
            except Exception as e_check:
                 logger.error(f"Erro ao verificar se ApuracaoID {apuracao_id} já foi premiada: {e_check}")
            finally:
                if conn_check: conn_check.close()

        # --- INÍCIO DA NOVA LÓGICA DE DECISÃO ---

        meta_foi_batida = modelo_meta_diaria and valor_dia >= modelo_meta_diaria.ValorMeta and modelo_meta_diaria.PontosPremio > 0

        if meta_foi_batida and not ja_premiada:
            # Cenário 1: Meta batida, ainda não premiada (Lançamento Original ou Edição para Cima)
            logger.info(f"Meta diária ATINGIDA (ApuracaoID: {apuracao_id}). Valor: {valor_dia} >= {modelo_meta_diaria.ValorMeta}. Premiando...")

            # (Lógica de premiação existente)
            meta_principal = None
            conn_meta = get_db_connection()
            if conn_meta:
                try:
                    cursor_meta = conn_meta.cursor()
                    cursor_meta.execute("SELECT * FROM MetasPrincipais WHERE MetaPrincipalID = ?", meta_principal_id)
                    meta_principal = cursor_meta.fetchone()
                finally:
                    conn_meta.close()

            if meta_principal and meta_principal.SetorAlvo:
                setor_alvo_diario = meta_principal.SetorAlvo
                pontos_premio_diario = modelo_meta_diaria.PontosPremio

                # Marca a apuração como premiada
                conn_interno = get_db_connection()
                if conn_interno:
                    try:
                        cursor_interno = conn_interno.cursor()
                        sql_marcar = "UPDATE MetasDiariasApuracoes SET PontosMetaDiariaGanhos = ? WHERE ApuracaoID = ?"
                        cursor_interno.execute(sql_marcar, pontos_premio_diario, apuracao_id)
                        conn_interno.commit()
                    except Exception as e_marcar:
                        logger.error(f"Erro ao marcar ApuracaoID {apuracao_id} como premiada: {e_marcar}")
                        if conn_interno: conn_interno.rollback()
                    finally:
                        if conn_interno: conn_interno.close()

                funcionarios_do_setor = listar_funcionarios_por_setor(setor_alvo_diario)

                if funcionarios_do_setor:
                    logger.info(f"--> Meta diária atingida! Distribuindo {pontos_premio_diario} pontos para {len(funcionarios_do_setor)} funcionários do setor '{setor_alvo_diario}'.")
                    mensagem_base = random.choice(config.MENSAGENS_META_DIARIA_CUMPRIDA)
                    mensagem_telegram = mensagem_base.format(pontos=pontos_premio_diario)

                    for funcionario in funcionarios_do_setor:
                        try:



                                # Em database.py, dentro de verificar_e_premiar_meta_diaria
                            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_premio_diario)
                            motivo_log = f"Meta Diária Atingida ({data_apuracao_str}) - Setor: {setor_alvo_diario}"

                            # --- CORREÇÃO APLICADA AQUI ---
                            # Passamos o ApuracaoID como o quinto parâmetro (vinculo_id)
                            registrar_pontos_de_bonus(
                                funcionario.FuncionarioID,
                                pontos_premio_diario,
                                motivo_log,
                                config.TAREFA_ID_PONTOS_META,
                                vinculo_id=apuracao_id
                            )
                            # --- FIM DA CORREÇÃO ---

                            if funcionario.ChatIDTelegram:



                                notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem_telegram)
                        except Exception as e_func:
                            logger.error(f"Erro ao processar prêmio/notificação para {funcionario.NomeCompleto} (ID: {funcionario.FuncionarioID}): {e_func}", exc_info=True)
                else:
                     logger.warning(f"--> Nenhum funcionário encontrado no setor '{setor_alvo_diario}' para premiar pela meta diária.")
            else:
                logger.warning(f"Meta diária ({data_apuracao_str}) atingida, mas a Meta Principal ID {meta_principal_id} não foi encontrada ou não tem SetorAlvo definido. Prêmio diário NÃO distribuído.")

        elif not meta_foi_batida and ja_premiada:
            # Cenário 2: Meta NÃO batida, mas JÁ ESTAVA premiada (Edição para Baixo - CLAWBACK!)
            logger.warning(f"Meta diária NÃO ATINGIDA (ApuracaoID: {apuracao_id}). Valor: {valor_dia}. REVERTENDO {pontos_premiados_anteriormente} pontos...")

            # 1. Reverter os pontos dos funcionários
            reversao_ok = _reverter_pontos_meta_diaria(apuracao_id, pontos_premiados_anteriormente, meta_principal_id)

            if reversao_ok:
                # 2. Zerar os pontos no registro da apuração
                conn_zero = get_db_connection()
                if conn_zero:
                    try:
                        cursor_zero = conn_zero.cursor()
                        sql_zero = "UPDATE MetasDiariasApuracoes SET PontosMetaDiariaGanhos = 0 WHERE ApuracaoID = ?"
                        cursor_zero.execute(sql_zero, apuracao_id)
                        conn_zero.commit()
                        logger.info(f"Clawback concluído. ApuracaoID {apuracao_id} zerada.")
                    except Exception as e_zero:
                        logger.error(f"Erro ao zerar pontos (ApuracaoID {apuracao_id}): {e_zero}")
                        if conn_zero: conn_zero.rollback()
                    finally:
                        if conn_zero: conn_zero.close()
            else:
                logger.error(f"FALHA CRÍTICA NO CLAWBACK para ApuracaoID {apuracao_id}. Os pontos não foram revertidos, mas a apuração foi editada.")

        elif meta_foi_batida and ja_premiada:
            # Cenário 3: Meta batida e já premiada (Ex: Editar 1200 para 1100). Nenhuma ação necessária.
            logger.info(f"Meta diária (ApuracaoID: {apuracao_id}) permanece atingida. Nenhuma alteração nos pontos.")

        else: # not meta_foi_batida and not ja_premiada
            # Cenário 4: Meta não batida e não premiada (Ex: Editar 900 para 800). Nenhuma ação necessária.
            logger.info(f"Meta diária (ApuracaoID: {apuracao_id}) permanece não atingida.")

        # --- FIM DA NOVA LÓGICA DE DECISÃO ---

    except Exception as e:
        logger.exception(f"!!! ERRO GERAL durante a verificação/premiação da meta diária (ApuracaoID: {apuracao_id}): {e}")


def registrar_nota_fiscal(funcionario_id, file_id):
    """
    Salva uma nova Nota Fiscal na tabela de rastreio.
    Retorna o ID da nova NF ou None se falhar.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO NotasFiscais (FuncionarioID, FileIDTelegram, Status) 
                VALUES (?, ?, 'Pendente');
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, funcionario_id, file_id)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Nova Nota Fiscal (ID: {novo_id}) registrada para FuncionarioID {funcionario_id}.")
            return novo_id
        except Exception as e:
            logger.error(f"ERRO ao registrar Nota Fiscal: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()
    return None

def buscar_nota_fiscal(nota_fiscal_id):
    """Busca todos os dados de uma nota fiscal pelo seu ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    NF.NotaFiscalID, NF.FuncionarioID, NF.FileIDTelegram, 
                    NF.PathFoto, NF.Status, NF.DataRecebimento,
                    F.NomeCompleto as NomeFuncionario,
                    F.ChatIDTelegram as ChatIDFuncionario
                FROM NotasFiscais NF
                JOIN Funcionarios F ON NF.FuncionarioID = F.FuncionarioID
                WHERE NF.NotaFiscalID = ?
            """
            cursor.execute(sql, nota_fiscal_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def buscar_notas_para_download():
    """Busca NFs que foram registradas mas ainda não tiveram a foto baixada."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT NotaFiscalID, FileIDTelegram FROM NotasFiscais WHERE PathFoto IS NULL"
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def finalizar_download_nota_fiscal(nota_fiscal_id, path_foto):
    """Atualiza o registro da NF com o caminho da foto baixada."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE NotasFiscais SET PathFoto = ? WHERE NotaFiscalID = ?"
            cursor.execute(sql, path_foto, nota_fiscal_id)
            conn.commit()
        finally:
            conn.close()

def atualizar_status_nota_fiscal(nota_fiscal_id, novo_status):
    """Atualiza o status de uma NF (ex: 'Processada')."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE NotasFiscais SET Status = ? WHERE NotaFiscalID = ?"
            cursor.execute(sql, novo_status, nota_fiscal_id)
            conn.commit()
        finally:
            conn.close()

def buscar_notas_fiscais_historico(data_inicio=None, data_fim=None, funcionario_id=None, status=None):
    """
    Busca o histórico de notas fiscais com base em filtros para o painel de gestor.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    NF.NotaFiscalID,
                    NF.DataRecebimento,
                    F.NomeCompleto,
                    NF.Status,
                    NF.PathFoto
                FROM NotasFiscais NF
                JOIN Funcionarios F ON NF.FuncionarioID = F.FuncionarioID
            """
            condicoes = []
            params = []

            if data_inicio:
                condicoes.append("CONVERT(DATE, NF.DataRecebimento) >= ?")
                params.append(data_inicio)
            if data_fim:
                condicoes.append("CONVERT(DATE, NF.DataRecebimento) <= ?")
                params.append(data_fim)
            if funcionario_id:
                condicoes.append("NF.FuncionarioID = ?")
                params.append(funcionario_id)
            if status and status != 'Todos':
                condicoes.append("NF.Status = ?")
                params.append(status)

            if condicoes:
                sql += " WHERE " + " AND ".join(condicoes)

            sql += " ORDER BY NF.DataRecebimento DESC"

            cursor.execute(sql, params)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao buscar histórico de NFs: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []

# ===================================================================
# == FIM DO MÓDULO DE NOTAS FISCAIS (NF) ============================
# ===================================================================


# ===================================================================
# == INÍCIO DO MÓDULO DE DENÚNCIA ANÔNIMA ==========================
# ===================================================================

def registrar_denuncia_anonima(mensagem):
    """
    Salva uma nova denúncia/sugestão anônima.
    IMPORTANTE: Não salva o FuncionarioID.
    Retorna o ID da nova denúncia ou None se falhar.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO DenunciasAnonimas (Mensagem) 
                VALUES (?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, mensagem)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Nova denúncia anônima (ID: {novo_id}) registrada com sucesso.")
            return novo_id
        except Exception as e:
            logger.error(f"ERRO ao registrar denúncia anônima: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()
    return None

# Em database.py, adicione esta nova função (pode ser perto de 'aceitar_tarefa_de_grupo')

# Em database.py
def verificar_e_aceitar_tarefa_de_folga(tarefa_id, funcionario_id):
    """
    (VERSÃO CORRIGIDA COM TRANSAÇÃO E LOCK)
    Verifica se uma tarefa de folga (baseada no TarefaID) já foi aceita hoje
    por qualquer pessoa. Se não, atribui ao funcionário e retorna True.
    Executa de forma transacional e atômica para evitar race conditions.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Inicia a transação (implícito, mas o commit/rollback é o controle)

            # 1. Verifica se alguém já pegou uma 'Unica' desta TarefaID HOJE
            #    Adicionamos WITH (UPDLOCK, HOLDLOCK) para travar o resultado da verificação
            sql_check = """
                SELECT 1
                FROM TarefasAtribuidas WITH (UPDLOCK, HOLDLOCK)
                WHERE TarefaID = ?
                  AND TipoFrequencia = 'Unica'
                  AND CONVERT(date, DataInicioVigencia) = CONVERT(date, GETDATE())
            """
            cursor.execute(sql_check, tarefa_id)

            if cursor.fetchone():
                # Alguém já pegou! (Ou outro processo está inserindo agora)
                conn.rollback() # Cancela a transação
                logger.info(f"--> [TAREFA FOLGA] FuncionarioID {funcionario_id} tentou pegar TarefaID {tarefa_id} que já foi aceita.")
                return None # Retorna None (já foi pega)

            # 2. Se ninguém pegou (e a tabela está travada), atribui ao funcionário
            sql_insert = """
                INSERT INTO TarefasAtribuidas
                (TarefaID, FuncionarioID, TipoFrequencia, ValorFrequencia, DataInicioVigencia, DataAgendamento)
                VALUES (?, ?, 'Unica', NULL, GETDATE(), GETDATE());
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql_insert, tarefa_id, funcionario_id)
            cursor.nextset()
            novo_atribuicao_id = cursor.fetchone()[0]

            conn.commit() # Confirma a transação
            logger.info(f"--> [TAREFA FOLGA] FuncionarioID {funcionario_id} aceitou a TarefaID {tarefa_id}. Nova AtribuicaoID: {novo_atribuicao_id}.")
            return novo_atribuicao_id # Retorna o ID da nova atribuição (Sucesso)

        except Exception as e:
            logger.error(f"ERRO CRÍTICO em verificar_e_aceitar_tarefa_de_folga: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return None # Retorna None (Erro)
        finally:
            if conn:
                conn.close()
    return None # Retorna None (Erro de conexão)

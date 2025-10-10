import pyodbc
from datetime import datetime, date, timedelta 
import calendar 
import hashlib

SERVER = '192.168.2.23'
DATABASE = 'gamificacao_db'
CONNECTION_STRING = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"  
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"UID=sa;"  # Informamos o usuário correto
    f"PWD=Gamificacao#2025;" # << COLOQUE A SENHA AQUI
    f"TrustServerCertificate=yes;"  # Necessário para aceitar o certificado do servidor
)

def get_db_connection():
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
        return conn
    except pyodbc.Error as ex:
        print(f"ERRO de conexão com o banco de dados: {ex}")
        return None

# Em database.py, SUBSTITUA a função criar_agendamento por esta:

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
            print(f"ERRO ao criar agendamento: {e}")
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
            print(f"ERRO ao atualizar agendamento: {e}")
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
            print(f"ERRO ao excluir agendamento: {e}")
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
            print(f"ERRO ao atualizar status de pagamento: {e}")
            return False
        finally:
            conn.close()
    return False

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

# Em database.py, SUBSTITUA a função antiga por esta versão final e corrigida:

def listar_tarefas_do_dia_por_funcionario(funcionario_id):
    """
    (VERSÃO 3 - DEFINITIVA E CORRIGIDA)
    Busca todas as tarefas pendentes para um funcionário no dia de HOJE,
    unificando a lógica para tarefas recorrentes e tarefas agendadas.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Esta consulta foi reestruturada para avaliar cada tipo de tarefa de forma independente e clara.
            sql = """
                -- PASSO 1: Garantimos que o SQL Server entenda a semana começando no Domingo (Domingo=1),
                -- para ser compatível com os dados salvos pela interface do gestor.
                SET DATEFIRST 7;

                SELECT
                    TA.AtribuicaoID, T.TarefaID, T.Titulo, T.Pontos, TA.TipoFrequencia AS Tipo,
                    ISNULL(TA.DescricaoOverride, T.Descricao) AS Descricao
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE
                    -- Condições Base: Pegar apenas tarefas do funcionário certo e que estão ativas.
                    TA.FuncionarioID = ? AND TA.DataFimVigencia IS NULL

                    -- Condição de Exclusão: Ignorar tarefas que já foram entregues (Aprovadas ou Pendentes) HOJE.
                    AND NOT EXISTS (
                        SELECT 1 FROM Entregas E
                        WHERE E.AtribuicaoID = TA.AtribuicaoID
                        AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE())
                        AND E.StatusValidacao IN ('Aprovada', 'Pendente')
                    )

                    -- Condição Principal de Lógica: Uma tarefa é para hoje SE...
                    AND (
                        -- Cenário 1: A tarefa é 'Diaria'.
                        TA.TipoFrequencia = 'Diaria'

                        -- Cenário 2: A tarefa é 'Semanal' E o dia da semana de hoje bate com o dia salvo.
                        -- (Usando CAST para garantir a comparação correta de número com texto)
                        OR (TA.TipoFrequencia = 'Semanal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(weekday, GETDATE()))

                        -- Cenário 3: A tarefa é 'Mensal' E o dia do mês de hoje bate com o dia salvo.
                        OR (TA.TipoFrequencia = 'Mensal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(day, GETDATE()))

                        -- Cenário 4: A tarefa tem uma DataAgendamento específica que é HOJE.
                        -- (Isso cobre as tarefas de 'Unica' vindas dos agendamentos de carrinho).
                        OR (TA.DataAgendamento IS NOT NULL AND CONVERT(date, TA.DataAgendamento) = CONVERT(date, GETDATE()))

                        -- Cenário 5: A tarefa é do tipo 'GrupoCompetitiva' e foi aceita HOJE.
                        OR (TA.TipoFrequencia = 'GrupoCompetitiva' AND CONVERT(date, TA.DataAceite) = CONVERT(date, GETDATE()))
                    )
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        except Exception as e:
            print(f"!!! ERRO CRÍTICO em listar_tarefas_do_dia_por_funcionario: {e}")
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

def listar_tarefas_para_atribuicao(filtro_setor=None):
    """
    (VERSÃO FINAL COM FILTRO)
    Retorna uma lista de tarefas disponíveis para serem atribuídas.
    Se um 'filtro_setor' for fornecido, retorna apenas tarefas daquele setor.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # A base da nossa consulta SQL é a mesma
            sql = """
                SELECT T.*
                FROM Tarefas T
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM TarefasAtribuidas TA
                    JOIN Entregas E ON TA.AtribuicaoID = E.AtribuicaoID
                    WHERE TA.TarefaID = T.TarefaID
                      AND TA.TipoFrequencia = 'Unica'
                      AND E.StatusValidacao = 'Aprovada'
                )
            """
            
            params = [] # Lista para guardar os parâmetros da consulta

            # A MÁGICA ACONTECE AQUI: Adicionamos a cláusula WHERE do filtro dinamicamente
            if filtro_setor:
                if filtro_setor == "Outras Tarefas":
                     sql += " AND (T.Setor IS NULL OR T.Setor = '')"
                else:
                    sql += " AND T.Setor = ?"
                    params.append(filtro_setor)

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

def atribuir_tarefa(tarefa_id, funcionario_id, tipo_frequencia, valor_frequencia, descricao_override=None, data_agendamento=None, agendamento_id=None):
    """Função universal para atribuir tarefas."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO TarefasAtribuidas 
                (TarefaID, FuncionarioID, TipoFrequencia, ValorFrequencia, DataInicioVigencia, DescricaoOverride, DataAgendamento, AgendamentoID) 
                VALUES (?, ?, ?, ?, GETDATE(), ?, ?, ?)
            """
            cursor.execute(sql, tarefa_id, funcionario_id, tipo_frequencia, valor_frequencia, descricao_override, data_agendamento, agendamento_id)
            conn.commit()
        finally:
            conn.close()

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
            print(f"--> [DATABASE.PY] Atribuição {atribuicao_id} encerrada com sucesso.")
        except Exception as e:
            print(f"--> [DATABASE.PY] ERRO ao encerrar a AtribuiçãoID {atribuicao_id}: {e}")
        finally:
            conn.close()

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

def aprovar_entrega(entrega_id, funcionario_id, pontos):
    """
    (VERSÃO FINAL COM SALDO)
    Aprova uma entrega, registra os pontos e ADICIONA OS PONTOS AO SALDO GERAL.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Atualiza o status da entrega
            sql_update_entrega = "UPDATE Entregas SET StatusValidacao = 'Aprovada', PontosGanhos = ? WHERE EntregaID = ?"
            cursor.execute(sql_update_entrega, pontos, entrega_id)
            
            # --- A NOVA ENGRENAGEM! ---
            # Adiciona os pontos ganhos na tarefa ao saldo cumulativo do funcionário.
            adicionar_pontos_ao_saldo(funcionario_id, pontos)

            # Commita as duas operações juntas para garantir consistência.
            conn.commit() 
            
            # (O código de verificação de conquistas continua o mesmo)
            novas_conquistas = verificar_e_conceder_conquistas(funcionario_id)
            return novas_conquistas

        except pyodbc.Error as e: 
            conn.rollback() # Desfaz tudo se uma das operações falhar
            print(f"Erro ao aprovar entrega e adicionar saldo: {e}")
        finally: 
            conn.close()
    return [] # Retorna uma lista vazia em caso de falha

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

# NO ARQUIVO database.py, ADICIONE ESTAS 3 NOVAS FUNÇÕES NO FINAL:

def agendar_tarefa_competitiva_para_grupo(tarefa_id, grupo_id, horario_disparo):
    """
    Agenda uma nova tarefa "competitiva" para um grupo em um horário específico.
    O FuncionarioID fica NULO inicialmente.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO TarefasAtribuidas 
                (TarefaID, GrupoID, TipoFrequencia, HorarioDisparo, StatusTarefaGrupo) 
                VALUES (?, ?, 'GrupoCompetitiva', ?, 'Disponivel')
            """
            cursor.execute(sql, tarefa_id, grupo_id, horario_disparo)
            conn.commit()
        finally:
            conn.close()

def buscar_tarefas_de_grupo_para_disparar(horario_atual):
    """Busca tarefas de grupo que estão agendadas para o minuto atual."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # CONSULTA MELHORADA: Converte a hora do banco para o formato 'HH:MM' antes de comparar
            sql = """
                SELECT TA.AtribuicaoID, T.Titulo, T.Pontos, G.NomeGrupo, G.ChatIDTelegram
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                JOIN Grupos G ON TA.GrupoID = G.GrupoID
                WHERE TA.StatusTarefaGrupo = 'Disponivel' 
                AND TA.TipoFrequencia = 'GrupoCompetitiva'
                AND CONVERT(VARCHAR(5), TA.HorarioDisparo, 108) = ?
            """
            cursor.execute(sql, horario_atual)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def aceitar_tarefa_de_grupo(atribuicao_id, funcionario_id):
    """
    Tenta atribuir uma tarefa de grupo a um funcionário.
    Usa uma "trava" (UPDATE ... WHERE Status = 'Disponivel') para garantir que só o primeiro consiga.
    Retorna True se foi bem-sucedido, False caso contrário.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Esta é a parte mágica: só atualiza a linha se ela AINDA estiver 'Disponivel'
            sql = """
                UPDATE TarefasAtribuidas 
                SET FuncionarioID = ?, StatusTarefaGrupo = 'Aceita', DataAceite = GETDATE()
                WHERE AtribuicaoID = ? AND StatusTarefaGrupo = 'Disponivel'
            """
            cursor.execute(sql, funcionario_id, atribuicao_id)
            conn.commit()
            # Se o número de linhas afetadas for 1, significa que NÓS conseguimos a tarefa!
            if cursor.rowcount > 0:
                return True
            else:
                return False # Alguém foi mais rápido
        finally:
            conn.close()
    return False           

# NO ARQUIVO database.py, ADICIONE ESTA NOVA FUNÇÃO:

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
                    AND (DiaDeFolga = 0 OR DiaDeFolga != DATEPART(weekday, GETDATE()))
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
                    AND (DiaDeFolga = 0 OR DiaDeFolga != DATEPART(weekday, GETDATE()))
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

# Em database.py, ADICIONE esta função no final do arquivo:
def buscar_detalhes_da_entrega(entrega_id):
    """Busca todos os detalhes de uma entrega para as notificações."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    E.StatusValidacao,
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

# Agora, SUBSTITUA a calculadora inteira pela sua versão final e corrigida:

# Em database.py, SUBSTITUA a função antiga por esta versão HÍBRIDA E JUSTA

# Em database.py, SUBSTITUA a função de ranking pela versão final e 100% justa

def calcular_ranking_desempenho(data_final_calculo=None):
    """
    Calcula o ranking com SCORE HÍBRIDO. (VERSÃO 4.1 - COM LÓGICA DE FOLGA)
    Agora, desconsidera tarefas recorrentes nos dias de folga do funcionário.
    """
    conn = get_db_connection()
    if not conn: return []

    PESO_A_DESEMPENHO = 0.5
    PESO_B_PONTOS_BRUTOS = 0.5

    try:
        cursor = conn.cursor()
        sql_tarefas_atribuidas = """
            SELECT F.FuncionarioID, F.NomeCompleto, F.DiaDeFolga,
                   TA.AtribuicaoID, TA.TipoFrequencia, TA.ValorFrequencia,
                   T.Pontos, TA.DataInicioVigencia, TA.DataFimVigencia,
                   TA.DataAceite
            FROM Funcionarios F
            LEFT JOIN TarefasAtribuidas TA ON F.FuncionarioID = TA.FuncionarioID
            LEFT JOIN Tarefas T ON TA.TarefaID = T.TarefaID
            WHERE TA.AtribuicaoID IS NOT NULL
            ORDER BY F.FuncionarioID
        """
        cursor.execute(sql_tarefas_atribuidas)
        todas_as_atribuicoes = cursor.fetchall()
        
        data_final = data_final_calculo if data_final_calculo else date.today()
        inicio_mes = data_final.replace(day=1)
        
        ranking_parcial = []
        
        atribuicoes_por_funcionario = {}
        funcionarios_todos = listar_funcionarios()
        for func in funcionarios_todos:
             atribuicoes_por_funcionario[func.FuncionarioID] = {
                'NomeCompleto': func.NomeCompleto,
                'DiaDeFolga': func.DiaDeFolga, # <<< IMPORTANTE: Guardar a folga
                'tarefas': []
            }

        for atribuicao in todas_as_atribuicoes:
            if atribuicao.FuncionarioID in atribuicoes_por_funcionario:
                atribuicoes_por_funcionario[atribuicao.FuncionarioID]['tarefas'].append(atribuicao)

        for func_id, dados in atribuicoes_por_funcionario.items():
            pontos_possiveis_total = 0
            
            for tarefa in dados['tarefas']:
                if tarefa.TipoFrequencia in ('GrupoCompetitiva', 'Unica'):
                    data_ref = tarefa.DataAceite if tarefa.TipoFrequencia == 'GrupoCompetitiva' else tarefa.DataInicioVigencia
                    if data_ref and inicio_mes <= _get_date_part(data_ref) <= data_final:
                        pontos_possiveis_total += tarefa.Pontos
                    continue
                
                dias_ocorrencia = 0
                start_date = max(_get_date_part(tarefa.DataInicioVigencia), inicio_mes) if tarefa.DataInicioVigencia else inicio_mes
                end_date = min(_get_date_part(tarefa.DataFimVigencia), data_final) if tarefa.DataFimVigencia else data_final

                if end_date < start_date: continue

                for dia_atual in (start_date + timedelta(days=n) for n in range((end_date - start_date).days + 1)):
                    if dia_atual > data_final: break
                    
                    # --- A MÁGICA DA JUSTIÇA ACONTECE AQUI! ---
                    dia_da_semana_sql = (dia_atual.weekday() + 2) % 7 # Segunda=2, Terça=3, ..., Domingo=1
                    if dia_da_semana_sql == 0: dia_da_semana_sql = 1 # Ajuste para domingo

                    if str(dia_da_semana_sql) == str(dados['DiaDeFolga']):
                        continue # PULA ESTE DIA, POIS É FOLGA! NÃO CONTA PONTOS POSSÍVEIS.
                    # -----------------------------------------------

                    if tarefa.TipoFrequencia == 'Diaria': dias_ocorrencia += 1
                    elif tarefa.TipoFrequencia == 'Semanal':
                        if str(dia_da_semana_sql) == str(tarefa.ValorFrequencia): dias_ocorrencia += 1
                    elif tarefa.TipoFrequencia == 'Mensal':
                        if dia_atual.day == int(tarefa.ValorFrequencia): dias_ocorrencia += 1
                pontos_possiveis_total += dias_ocorrencia * tarefa.Pontos

            pontos_ganhos = calcular_pontos_ganhos_no_periodo(func_id, inicio_mes, data_final)
            percentual_desempenho = (pontos_ganhos / pontos_possiveis_total) * 100 if pontos_possiveis_total > 0 else 0
            
            ranking_parcial.append({
                'FuncionarioID': func_id, 'NomeCompleto': dados['NomeCompleto'],
                'PontosGanhos': pontos_ganhos, 'PontosPossiveis': pontos_possiveis_total,
                'Desempenho': round(percentual_desempenho, 2)
            })

        if not ranking_parcial: return []
        
        max_pontos_ganhos = max(p['PontosGanhos'] for p in ranking_parcial) if any(p['PontosGanhos'] for p in ranking_parcial) else 1

        ranking_final = []
        for dados_func in ranking_parcial:
            percentual_pontos_brutos = (dados_func['PontosGanhos'] / max_pontos_ganhos) * 100
            score_hibrido = (dados_func['Desempenho'] * PESO_A_DESEMPENHO) + (percentual_pontos_brutos * PESO_B_PONTOS_BRUTOS)
            dados_func['ScoreHibrido'] = round(score_hibrido, 2)
            ranking_final.append(dados_func)

        ranking_ordenado = sorted(ranking_final, key=lambda x: x['ScoreHibrido'], reverse=True)
        return ranking_ordenado

    except Exception as e:
        print(f"ERRO ao calcular ranking de desempenho HÍBRIDO: {e}")
        return []
    finally:
        if conn: conn.close()

# Em database.py, adicione esta função ao final do arquivo:
def salvar_historico_ranking(ranking_do_mes):
    """Salva os resultados finais do ranking de um mês na tabela de histórico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            hoje = date.today()
            # Pega o ano e o mês do mês passado
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
            print(f"ERRO ao salvar histórico do ranking: {e}")
        finally:
            conn.close()

# Em database.py, adicione esta função no final:
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

# Em database.py, adicione esta função no final do arquivo:

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

# Em database.py, adicione esta NOVA função no final do arquivo:

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
            # Este comando SQL é o coração da nossa ferramenta.
            # Ele deleta linhas da tabela de Entregas...
            # ...onde o FuncionarioID corresponda ao que foi passado...
            # ...e onde o MÊS e o ANO da DataEnvio sejam os mesmos do MÊS e ANO de AGORA.
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
            print(f"ERRO ao limpar as entregas do mês para o funcionário {funcionario_id}: {e}")
        finally:
            conn.close()

# ===================================================================
# == INÍCIO DO MÓDULO DE CIÊNCIA DE COMUNICADOS (NOVAS FUNÇÕES) =====
# ===================================================================

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
            # 4. Passando o novo parâmetro para o comando execute
            cursor.execute(sql, titulo, conteudo, criador_id, pontos, telegram_file_id_foto)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            return novo_id
        except Exception as e:
            print(f"ERRO ao criar documento: {e}")
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
            print(f"ERRO ao registrar pendência de assinatura: {e}")
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
    # ATENÇÃO: Coloque aqui o ID da tarefa "Leitura de Comunicado" que você criou no Passo 6.
    # Se você não sabe o ID, execute 'SELECT TarefaID FROM Tarefas WHERE Titulo = 'Leitura de Comunicado''
    TAREFA_ID_LEITURA = 38 # <<< MUDE ESTE NÚMERO PARA O SEU ID CORRETO!

    if conn:
        try:
            cursor = conn.cursor()
            # Inserimos uma entrega já 'Aprovada' diretamente
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
            print(f"ERRO ao registrar pontos por leitura: {e}")
        finally:
            conn.close()

# Em database.py, SUBSTITUA a função antiga por esta versão com filtro
def listar_comunicados_com_status(filtro_titulo=None):
    """
    Lista todos os documentos com status. Se um filtro_titulo for fornecido,
    retorna apenas os documentos cujo título contém o texto do filtro.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A base da nossa consulta SQL continua a mesma
            sql_base = """
                SELECT
                    D.DocumentoID, D.Titulo, D.DataCriacao,
                    COUNT(DA.AssinaturaID) AS TotalEnviado,
                    SUM(CASE WHEN DA.StatusAssinatura = 'Ciente' THEN 1 ELSE 0 END) AS TotalCientes
                FROM Documentos D
                LEFT JOIN DocumentosAssinaturas DA ON D.DocumentoID = DA.DocumentoID
            """

            params = [] # Lista para guardar os parâmetros da consulta

            # A MÁGICA ACONTECE AQUI: Adicionamos a cláusula WHERE dinamicamente
            if filtro_titulo:
                sql_base += " WHERE D.Titulo LIKE ?" # O 'LIKE' permite buscas parciais
                params.append(f"%{filtro_titulo}%") # Os '%' são coringas: buscam o texto em qualquer parte do título

            # O final da consulta também é o mesmo
            sql_final = """
                GROUP BY D.DocumentoID, D.Titulo, D.DataCriacao
                ORDER BY D.DataCriacao DESC
            """

            # Juntamos tudo e executamos
            sql_completa = sql_base + sql_final
            cursor.execute(sql_completa, params)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

# Em database.py, substitua a função antiga por esta versão aprimorada

def listar_destinatarios_de_documento(documento_id):
    """
    Função de relatório para o gestor. Mostra o status detalhado de
    cada funcionário para um documento específico, AGORA INCLUINDO O ID DA ASSINATURA.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A ÚNICA MUDANÇA É ADICIONAR "DA.AssinaturaID" NO COMEÇO DO SELECT
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
    # Este código só roda quando executamos 'python database.py' diretamente
    # Ele não vai atrapalhar nossos outros programas.

    # --- ATENÇÃO: Verifique se os IDs abaixo existem na sua tabela de Funcionarios! ---
    GESTOR_ID_TESTE = 3 # ID de um funcionário para ser o "criador"
    FUNCIONARIO_ID_TESTE = 3 # ID de um funcionário para receber o comunicado

    print("--- INICIANDO TESTE DO MÓDULO DE COMUNICADOS ---")

    # 1. Testar criação de documento com pontos
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

    # 2. Registrar pendência para um funcionário
    print(f"\n[TESTE 2] Registrando pendência do Doc ID {id_doc} para o Funcionário ID {FUNCIONARIO_ID_TESTE}...")
    id_assinatura = registrar_pendencia_assinatura(id_doc, FUNCIONARIO_ID_TESTE)
    if id_assinatura:
        print(f"--> SUCESSO! Pendência registrada com AssinaturaID: {id_assinatura}")
    else:
        print("--> FALHA! Não foi possível registrar a pendência.")
        exit()

    # 3. Simular o clique do bot
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

# Em database.py, ADICIONE esta nova função no final do arquivo

def buscar_assinaturas_pendentes_antigas(horas_atras=24):
    """
    Busca assinaturas que continuam 'Pendente' após um determinado número de horas do envio.
    Retorna uma lista com Nome, ChatID e Título do documento para o lembrete.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # DATEADD(hour, -24, GETDATE()) calcula a data e hora de 24h atrás.
            # A consulta busca por pendências cujo envio foi ANTES desse horário.
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

# Em database.py, adicione estas duas novas funções ao final do arquivo

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
            # Etapa 1: Excluir as assinaturas associadas
            sql_assinaturas = "DELETE FROM DocumentosAssinaturas WHERE DocumentoID = ?"
            cursor.execute(sql_assinaturas, documento_id)

            # Etapa 2: Excluir o documento principal
            sql_documento = "DELETE FROM Documentos WHERE DocumentoID = ?"
            cursor.execute(sql_documento, documento_id)

            conn.commit()
            print(f"--> [DATABASE] Documento ID {documento_id} e suas assinaturas foram excluídos.")
        except Exception as e:
            print(f"ERRO ao excluir documento: {e}")
            conn.rollback() # Desfaz a operação em caso de erro
        finally:
            conn.close()

# Em database.py, adicione esta nova função ao final
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

# Em database.py, adicione esta nova função na seção de comunicados

# Em database.py, substitua a função antiga por esta versão corrigida

def listar_funcionarios_nao_destinatarios(documento_id):
    """
    Retorna uma lista de funcionários que AINDA NÃO estão associados a um
    documento específico, AGORA INCLUINDO O CHAT ID PARA NOTIFICAÇÃO.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A CORREÇÃO ESTÁ AQUI: Adicionamos F.ChatIDTelegram ao SELECT
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

# Em database.py, adicione esta nova função

def salvar_feedback_do_dia(funcionario_id, nota):
    """Salva a nota de feedback do funcionário para a data atual."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Impede o envio de feedback duplicado no mesmo dia
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

# Em database.py, adicione esta nova função ao final do arquivo

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
            # A consulta base que une as tabelas para pegar o nome do funcionário
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

            # Adiciona as condições de filtro dinamicamente
            if funcionario_id:
                condicoes.append("F.FuncionarioID = ?")
                params.append(funcionario_id)

            if data_inicio:
                condicoes.append("F.DataFeedback >= ?")
                params.append(data_inicio)

            if data_fim:
                condicoes.append("F.DataFeedback <= ?")
                params.append(data_fim)

            # Se houver alguma condição, monta a cláusula WHERE
            if condicoes:
                sql += " WHERE " + " AND ".join(condicoes)

            sql += " ORDER BY F.DataFeedback DESC" # Ordena do mais recente para o mais antigo

            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

# Em database.py, adicione esta nova função
def relatorio_analise_tarefas(data_inicio, data_fim):
    """
    Busca no banco um resumo das tarefas que foram mais recusadas ou
    marcadas como "Não Aplicável" dentro de um período.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Esta consulta agrupa por título da tarefa e conta as ocorrências
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

# Em database.py, adicione esta nova função

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
            print(f"ERRO ao criar solicitação de feedback: {e}")
            return False
        finally:
            conn.close()
    return False

# Em database.py, adicione estas três novas funções no final

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
            
            # A CORREÇÃO MÁGICA ESTÁ AQUI:
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
            # Procura por entregas com file_id mas sem caminho de foto local
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

# Em database.py, adicione esta nova função
def listar_atribuicoes_ativas_por_funcionario(funcionario_id):
    """Retorna todas as tarefas ativas para um funcionário específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Este SQL é uma versão filtrada do que já tínhamos
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

# Em database.py, adicione esta nova função
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

# Em database.py, adicione esta nova função
def listar_agenda_semanal_por_funcionario(funcionario_id):
    """Busca todas as tarefas ativas de um funcionário e retorna o dia da semana para tarefas semanais."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A consulta foi adaptada para focar nas tarefas recorrentes e seu dia
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

# Em database.py, adicione estas duas funções no final do arquivo

def buscar_funcionarios_de_folga_hoje():
    """Busca no banco todos os funcionários cujo dia de folga é hoje."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A lógica é o inverso do que já temos: busca quem TEM o DiaDeFolga IGUAL a hoje.
            sql = """
                SELECT * FROM Funcionarios 
                WHERE DiaDeFolga = DATEPART(weekday, GETDATE())
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario_id):
    """
    Busca todas as tarefas DIÁRIAS ou SEMANAIS (para o dia de hoje)
    atribuídas a um funcionário, ignorando se já foram feitas ou não.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT T.TarefaID, T.Titulo, T.Pontos
                FROM TarefasAtribuidas TA
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE TA.FuncionarioID = ? 
                  AND TA.DataFimVigencia IS NULL
                  AND (
                    TA.TipoFrequencia = 'Diaria' OR
                    (TA.TipoFrequencia = 'Semanal' AND TA.ValorFrequencia = DATEPART(weekday, GETDATE()))
                  )
            """
            cursor.execute(sql, funcionario_id)
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
            # A linha abaixo transforma o resultado (que é uma lista de tuplas) em uma lista de strings
            return [row.Setor for row in cursor.fetchall()]
        finally:
            conn.close()
    return []

# ===================================================================
# == INÍCIO DO MÓDULO DE LOJA DE RECOMPENSAS ========================
# ===================================================================

def adicionar_pontos_ao_saldo(funcionario_id, pontos_a_adicionar):
    """Adiciona pontos ao saldo cumulativo de um funcionário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Esta query é "atômica": ela lê o valor atual e soma o novo em uma única operação.
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

# --- Funções de Gestão de Produtos (para o main.py do gestor) ---

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
            print(f"ERRO CRÍTICO em solicitar_resgate: {e}")
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
            print(f"ERRO ao recusar resgate: {e}")
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
    Função principal que verifica todos os critérios de conquistas para um funcionário.
    Esta função será chamada após eventos importantes (ex: aprovar uma entrega, fechar o mês).
    """
    conn = get_db_connection()
    if not conn: return []

    novas_conquistas_ganhas = [] # Lista para notificar o usuário

    try:
        cursor = conn.cursor()
        # 1. Busca todas as conquistas que o funcionário AINDA NÃO TEM.
        sql_conquistas_a_verificar = """
            SELECT * FROM Conquistas
            WHERE ConquistaID NOT IN (
                SELECT ConquistaID FROM ConquistasFuncionarios WHERE FuncionarioID = ?
            )
        """
        cursor.execute(sql_conquistas_a_verificar, funcionario_id)
        conquistas_a_verificar = cursor.fetchall()

        for conquista in conquistas_a_verificar:
            atingiu_criterio = False
            # 2. Verifica cada tipo de critério
            if conquista.CriterioTipo == 'total_tarefas_aprovadas':
                sql_check = "SELECT COUNT(*) FROM Entregas WHERE FuncionarioID = ? AND StatusValidacao = 'Aprovada'"
                cursor.execute(sql_check, funcionario_id)
                total = cursor.fetchone()[0]
                if total and total >= conquista.CriterioValor:
                    atingiu_criterio = True
            
            # Adicionar mais 'elifs' aqui para outros critérios no futuro...
            # elif conquista.CriterioTipo == 'desempenho_mensal': ...
            # elif conquista.CriterioTipo == 'tarefas_de_folga_assumidas': ...

            # 3. Se o critério foi atingido, concede a conquista
            if atingiu_criterio:
                sql_grant = "INSERT INTO ConquistasFuncionarios (FuncionarioID, ConquistaID) VALUES (?, ?)"
                cursor.execute(sql_grant, funcionario_id, conquista.ConquistaID)
                conn.commit()
                novas_conquistas_ganhas.append(conquista)

                # 4. Concede os pontos de bônus, se houver
                if conquista.PontosBonus > 0:
                    # Reutilizamos a função de pontos de leitura!
                    registrar_pontos_por_leitura(
                        funcionario_id, 
                        conquista.PontosBonus, 
                        f"Bônus pela conquista: {conquista.Nome}"
                    )
        
        return novas_conquistas_ganhas

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
            print(f"ERRO ao salvar documento pessoal: {e}")
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
            print(f"ERRO ao criar pendência de ciência para documento pessoal: {e}")
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


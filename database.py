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
from decimal import Decimal
from collections import deque

# Cache para armazenar (ID_Atribuicao, Data_Hora_Minuto) das tarefas já enviadas
cache_tarefas_enviadas = deque(maxlen=50)

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
        logger.critical(f"FALHA CRÍTICA na conexão com o banco de dados: {ex}", exc_info=True)
        return None

# --- MIGRAÇÃO DE SCHEMA (RH AVANÇADO) - MOVIDO PARA LOCAL SEGURO ---
def verificar_migracao_rh_avancado():
    """Garante que as colunas de Telefone, Folga Domingo e Afastamento existam."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Telefone
            try:
                cursor.execute("SELECT TelefoneWhatsApp FROM Funcionarios WHERE 1=0")
            except:
                cursor.execute("ALTER TABLE Funcionarios ADD TelefoneWhatsApp VARCHAR(20)")
                logger.info("Migração: Coluna TelefoneWhatsApp adicionada.")
            
            # 2. Domingo de Folga (1=1º dom, 2=2º dom, etc. 0=Não usa)
            try:
                cursor.execute("SELECT DomingoFolgaMensal FROM Funcionarios WHERE 1=0")
            except:
                cursor.execute("ALTER TABLE Funcionarios ADD DomingoFolgaMensal INT DEFAULT 0")
                logger.info("Migração: Coluna DomingoFolgaMensal adicionada.")

            # 3. Afastamento (Datas)
            try:
                cursor.execute("SELECT DataInicioAfastamento FROM Funcionarios WHERE 1=0")
            except:
                cursor.execute("ALTER TABLE Funcionarios ADD DataInicioAfastamento DATE NULL")
                cursor.execute("ALTER TABLE Funcionarios ADD DataFimAfastamento DATE NULL")
                logger.info("Migração: Colunas de Afastamento adicionadas.")
                
            conn.commit()
        except Exception as e:
            logger.error(f"Erro na migração RH Avançado: {e}")
        finally:
            conn.close()

# Executa ao importar (AGORA NO LUGAR CERTO, APÓS get_db_connection EXISTIR)
verificar_migracao_rh_avancado()

def verificar_migracao_banco():
    """Verifica se as tabelas de migração estão no banco. Se não, cria."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Migração de PosicoesLoja (Setor)
            try:
                cursor.execute("SELECT TOP 1 Setor FROM PosicoesLoja")
            except Exception:
                logger.info("Coluna 'Setor' não encontrada. Iniciando migração da tabela PosicoesLoja...")
                cursor.execute("ALTER TABLE PosicoesLoja ADD Setor VARCHAR(50)")
                conn.commit()
                logger.info("Migração concluída: Coluna 'Setor' adicionada com sucesso.")
                
            # 2. Migração de ProdutosFornecedor (FatorConversao)
            try:
                cursor.execute("SELECT TOP 1 FatorConversao FROM ProdutosFornecedor")
            except Exception:
                logger.info("Coluna 'FatorConversao' não encontrada. Criando...")
                cursor.execute("ALTER TABLE ProdutosFornecedor ADD FatorConversao DECIMAL(10,4) DEFAULT 1.0")
                conn.commit()
                logger.info("Migração concluída: Coluna 'FatorConversao' adicionada.")

                # 2.1. GARANTIA DE TAREFAS DE SISTEMA (Auto-Reparo de FK)
                # Verifica se a tarefa de Feedback (ID 5) existe. Se não, cria forçadamente.
                try:
                    # TAREFA ID 5: Feedback Diário
                    cursor.execute("SELECT 1 FROM Tarefas WHERE TarefaID = 5")
                    if not cursor.fetchone():
                        logger.warning("Tarefa de Sistema ID 5 (Feedback) não encontrada. Recriando...")
                        cursor.execute("""
                            SET IDENTITY_INSERT Tarefas ON;
                            INSERT INTO Tarefas (TarefaID, Titulo, Descricao, Pontos, Setor)
                            VALUES (5, 'Feedback Diário', 'Pontos automáticos por responder o feedback', 5, 'Geral');
                            SET IDENTITY_INSERT Tarefas OFF;
                        """)
                        conn.commit()
                        logger.info("Tarefa de Sistema ID 5 recriada com sucesso.")

                    # TAREFA ID 38: Leitura de Comunicado (Preventivo)
                    cursor.execute("SELECT 1 FROM Tarefas WHERE TarefaID = 38")
                    if not cursor.fetchone():
                        logger.warning("Tarefa de Sistema ID 38 (Leitura) não encontrada. Recriando...")
                        cursor.execute("""
                            SET IDENTITY_INSERT Tarefas ON;
                            INSERT INTO Tarefas (TarefaID, Titulo, Descricao, Pontos, Setor)
                            VALUES (38, 'Leitura de Comunicado', 'Pontos por confirmar leitura de documento', 10, 'Geral');
                            SET IDENTITY_INSERT Tarefas OFF;
                        """)
                        conn.commit()
                        logger.info("Tarefa de Sistema ID 38 recriada com sucesso.")

                except Exception as e_sys_task:
                    logger.error(f"Erro ao garantir tarefas de sistema (Auto-Reparo): {e_sys_task}")

            # 3. Migração para nova tabela de Configurações de Escala (AGORA SEM O BLOQUEIO GERAL)
            try:
                # 3.1. Cria ou Ajusta a Tabela Global de Configurações (Remove HoraBloqueio se existir)
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ConfiguracoesEscala')
                    BEGIN
                        CREATE TABLE ConfiguracoesEscala (
                            ConfigID INT PRIMARY KEY IDENTITY(1,1),
                            MaxHorasSemPausa INT NOT NULL,
                            DuracaoIntervalo INT NOT NULL,
                            DataAtualizacao DATETIME DEFAULT GETDATE()
                        );
                        INSERT INTO ConfiguracoesEscala (MaxHorasSemPausa, DuracaoIntervalo) VALUES (5, 1);
                    END
                    -- Migração Req 1: Adicionar Duração Jornada Padrão
                    IF NOT EXISTS (SELECT * FROM syscolumns WHERE id=OBJECT_ID('ConfiguracoesEscala') AND name='DuracaoJornadaPadrao')
                    BEGIN
                        ALTER TABLE ConfiguracoesEscala ADD DuracaoJornadaPadrao INT DEFAULT 8;
                        -- Atualiza registro existente se houver
                        UPDATE ConfiguracoesEscala SET DuracaoJornadaPadrao = 8 WHERE DuracaoJornadaPadrao IS NULL;
                    END
                    ELSE IF EXISTS (SELECT * FROM syscolumns WHERE id=OBJECT_ID('ConfiguracoesEscala') AND name='HoraBloqueioInicio')
                    BEGIN
                        ALTER TABLE ConfiguracoesEscala DROP COLUMN HoraBloqueioInicio;
                        ALTER TABLE ConfiguracoesEscala DROP COLUMN HoraBloqueioFim;
                        -- Se já existia, garante o valor padrão para os novos campos
                        IF (SELECT COUNT(*) FROM ConfiguracoesEscala) = 0 BEGIN
                            INSERT INTO ConfiguracoesEscala (MaxHorasSemPausa, DuracaoIntervalo) VALUES (5, 1);
                        END
                    END
                """)

                # 3.2. Cria a Tabela de Bloqueio Diário
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'PicoDiario')
                    CREATE TABLE PicoDiario (
                        DiaSemanaID INT PRIMARY KEY, -- 1=Dom, 2=Seg, ..., 7=Sab
                        NomeDia VARCHAR(20) NOT NULL,
                        HoraBloqueioInicio TIME,
                        HoraBloqueioFim TIME,
                    )
                """)
                
                # 3.3. Garante que os 7 dias existam com valores padrão (Pico só Sáb/Dom)
                # CORREÇÃO: Usar None (Python) no lugar de NULL (SQL)
                dias_padrao = [
                    (1, 'Domingo', '17:00:00', '18:30:00'),
                    (2, 'Segunda', None, None),
                    (3, 'Terça', None, None),
                    (4, 'Quarta', None, None),
                    (5, 'Quinta', None, None),
                    (6, 'Sexta', None, None),
                    (7, 'Sábado', '17:00:00', '18:30:00'),
                ]
                
                for dia_id, nome, h_ini, h_fim in dias_padrao:
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM PicoDiario WHERE DiaSemanaID = ?)
                        INSERT INTO PicoDiario (DiaSemanaID, NomeDia, HoraBloqueioInicio, HoraBloqueioFim)
                        VALUES (?, ?, ?, ?)
                        ELSE
                        UPDATE PicoDiario SET NomeDia = ? WHERE DiaSemanaID = ?
                    """, dia_id, dia_id, nome, h_ini, h_fim, nome, dia_id)

                conn.commit()
                logger.info("Tabelas ConfiguracoesEscala e PicoDiario verificadas/criadas com sucesso.")

            except Exception as e:
                logger.error(f"Erro na migração das tabelas de Escala Dinâmica: {e}")
        except Exception as e:
            logger.error(f"Erro na migração de banco: {e}")
        finally:
            conn.close()

# Executa a verificação ao importar o módulo
verificar_migracao_banco()


def verificar_migracao_agendamentos_flags():
    """
    Cria as colunas de controle de mensagens na tabela Agendamentos se não existirem.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Lista de colunas a verificar/criar
            colunas = [
                "MsgCriacaoEnviada",      # Para mensagem imediata
                "MsgConfirmacaoEnviada",  # Para mensagem de D-1 (Amanhã)
                "MsgPosVendaEnviada"      # Para mensagem de D+1 (Ontem)
            ]
            
            alteracoes_feitas = False
            for col in colunas:
                try:
                    # Tenta selecionar a coluna para ver se existe
                    cursor.execute(f"SELECT TOP 1 {col} FROM Agendamentos")
                except Exception:
                    # Se der erro, é porque não existe. Cria a coluna.
                    logger.info(f"Coluna '{col}' não encontrada em Agendamentos. Criando...")
                    # DEFAULT 0 significa "Não Enviada"
                    cursor.execute(f"ALTER TABLE Agendamentos ADD {col} INT DEFAULT 0")
                    alteracoes_feitas = True
            
            if alteracoes_feitas:
                conn.commit()
                logger.info("Migração de Flags de Agendamento concluída com sucesso.")
            else:
                # logger.info("Tabela Agendamentos já possui todas as flags.") # Opcional para não poluir log
                pass

        except Exception as e:
            logger.error(f"Erro na migração de flags de agendamento: {e}")
            if conn: conn.rollback()
        finally:
            conn.close()

# Executa a verificação imediatamente ao iniciar
verificar_migracao_agendamentos_flags()


def verificar_migracao_solicitacoes():
    """Cria a tabela de Solicitações Internas se não existir."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'SolicitacoesInternas')
                CREATE TABLE SolicitacoesInternas (
                    SolicitacaoID INT PRIMARY KEY IDENTITY(1,1),
                    FuncionarioID INT REFERENCES Funcionarios(FuncionarioID),
                    DataSolicitacao DATETIME DEFAULT GETDATE(),
                    Tipo VARCHAR(20) NOT NULL, -- 'Compra' ou 'Manutencao'
                    Categoria VARCHAR(50),
                    Descricao NVARCHAR(MAX),
                    Quantidade DECIMAL(10,2),
                    CaminhoFoto VARCHAR(255),
                    Status VARCHAR(20) DEFAULT 'Pendente', -- Pendente, Aprovado, Recusado
                    MotivoRecusa NVARCHAR(MAX),
                    DataConclusao DATETIME
                )
            """
            cursor.execute(sql)
            conn.commit()
            logger.info("Tabela SolicitacoesInternas verificada/criada.")
        except Exception as e:
            logger.error(f"Erro na migração de solicitações: {e}")
        finally:
            conn.close()

# Executa a verificação
verificar_migracao_solicitacoes()

def garantir_tabela_descricoes_setores():
    """Cria tabela de descrições por setor e insere padrões se não existirem."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql_create = """
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ConfiguracoesSetores')
                CREATE TABLE ConfiguracoesSetores (
                    Setor VARCHAR(50) PRIMARY KEY,
                    DescricaoPadrao NVARCHAR(MAX)
                )
            """
            cursor.execute(sql_create)
            
            # Insere padrões básicos (apenas se não existir)
            setores_padrao = [
                ("Cozinha", "👨‍🍳 *Foco do Setor:* Manter a higiene, seguir as fichas técnicas rigorosamente e garantir a saída rápida dos pedidos."),
                ("Caixa", "💰 *Foco do Setor:* Atenção no fechamento, oferecer produtos adicionais e sorriso no rosto ao receber o cliente."),
                ("Atendimento", "👋 *Foco do Setor:* Agilidade na entrega, verificar satisfação do cliente e manter as mesas limpas."),
                ("Limpeza", "✨ *Foco do Setor:* Manter o salão impecável, verificar banheiros a cada 30min e repor insumos."),
                ("Varanda", "🍃 *Foco do Setor:* Organização das mesas externas e suporte rápido aos clientes da área externa."),
                ("Buffet", "🍦 *Foco do Setor:* Reposição constante, limpeza da pista e verificação de temperatura."),
                ("Camara Fria", "❄️ *Foco do Setor:* Organização FIFO (Primeiro que entra, primeiro que sai) e controle de validade.")
            ]
            
            for setor, desc in setores_padrao:
                # Usa a mesma lógica determinística da função de atualização:
                # Verifica explicitamente se já existe antes de tentar inserir.
                cursor.execute("SELECT 1 FROM ConfiguracoesSetores WHERE Setor = ?", setor)
                if not cursor.fetchone():
                    # Se não existe, insere.
                    cursor.execute("INSERT INTO ConfiguracoesSetores (Setor, DescricaoPadrao) VALUES (?, ?)", setor, desc)
                
            conn.commit()
            logger.info("Tabela ConfiguracoesSetores verificada.")
        except Exception as e:
            logger.error(f"Erro na migração de setores: {e}")
        finally:
            conn.close()

# Executa imediatamente
garantir_tabela_descricoes_setores()

def buscar_descricao_setor(nome_setor):
    """Busca a descrição padrão de um setor."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DescricaoPadrao FROM ConfiguracoesSetores WHERE Setor = ?", nome_setor)
            res = cursor.fetchone()
            return res[0] if res else None
        finally:
            conn.close()
    return None

def listar_todas_diretrizes_setores():
    """Retorna lista de (Setor, Descricao) para o editor."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT Setor, DescricaoPadrao FROM ConfiguracoesSetores ORDER BY Setor")
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def atualizar_diretriz_setor(setor, nova_descricao):
    """
    Atualiza a diretriz de um setor usando a estratégia DELETE/INSERT.
    Isso elimina problemas de atualização de campos TEXT/NVARCHAR(MAX) via ODBC.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # 1. Remove qualquer registro existente para este setor
            cursor.execute("DELETE FROM ConfiguracoesSetores WHERE Setor = ?", setor)
            
            # 2. Insere o novo registro limpo
            sql_insert = "INSERT INTO ConfiguracoesSetores (Setor, DescricaoPadrao) VALUES (?, ?)"
            cursor.execute(sql_insert, setor, nova_descricao)
            
            conn.commit()
            print(f"--> [DB] Diretriz do setor '{setor}' salva com sucesso (Mode: DELETE/INSERT).")
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar diretriz do setor {setor}: {e}", exc_info=True)
            if conn: conn.rollback()
            return False
        finally:
            if conn: conn.close()
    return False

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

def atualizar_funcionario(funcionario_id, nome, chat_id, cargo, horario_notificacao, dia_folga, verificador_cpf, telefone=None, domingo_folga=0, inicio_afastamento=None, fim_afastamento=None):
    """Atualiza dados do funcionário, incluindo novos campos de RH (Telefone, Escala 6x1, Férias)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Trata datas vazias ou strings vazias como None para o banco
            inicio = inicio_afastamento if (inicio_afastamento and str(inicio_afastamento).strip()) else None
            fim = fim_afastamento if (fim_afastamento and str(fim_afastamento).strip()) else None
            domingo = int(domingo_folga) if domingo_folga else 0

            sql = """
                UPDATE Funcionarios 
                SET NomeCompleto = ?, ChatIDTelegram = ?, Cargo = ?, 
                    HorarioNotificacao = ?, DiaDeFolga = ?, VerificadorCPF = ?,
                    TelefoneWhatsApp = ?, DomingoFolgaMensal = ?,
                    DataInicioAfastamento = ?, DataFimAfastamento = ?
                WHERE FuncionarioID = ?
            """
            cursor.execute(sql, nome, chat_id, cargo, horario_notificacao, dia_folga, verificador_cpf, 
                           telefone, domingo, inicio, fim, funcionario_id)
            conn.commit()
        except Exception as e:
            logger.error(f"Erro ao atualizar funcionário completo: {e}", exc_info=True)
            raise e # Relança para a interface mostrar o erro
        finally:
            conn.close()

# Em database.py, esta é a ÚNICA versão da função que deve existir no seu código.

def listar_funcionarios():
    """
    (CORREÇÃO FINAL DE SCHEMA) Lista TODOS os campos de Funcionarios, incluindo RH Avançado,
    para garantir que o agendador veja as folgas e férias.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # ADICIONADOS: DomingoFolgaMensal, DataInicioAfastamento, DataFimAfastamento
            sql = """
                SELECT 
                    FuncionarioID, NomeCompleto, CPF, ChatIDTelegram, TelefoneWhatsApp, 
                    Cargo, Setor, SaldoPontos, HorarioNotificacao, DiaDeFolga, 
                    VerificadorCPF, NivelAcesso, PosicaoPadraoID,
                    DomingoFolgaMensal, DataInicioAfastamento, DataFimAfastamento
                FROM Funcionarios 
                ORDER BY NomeCompleto
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_funcionarios_por_horario(horario_atual):
    """Busca funcionários para notificação de início, RESPEITANDO O DIA DE FOLGA."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Lógica corrigida para Folga: Usa DATENAME para ser agnóstico à configuração @@DATEFIRST
            sql = """
                SELECT * FROM Funcionarios F
                WHERE CONVERT(VARCHAR(5), F.HorarioNotificacao, 108) = ?
                -- Lógica da Folga: Se DiaDeFolga for 0 (sem folga) OU o DiaDeFolga for diferente do dia da semana atual
                AND (
                    F.DiaDeFolga = 0 OR 
                    F.DiaDeFolga IS NULL OR
                    -- Converte o dia da semana SQL para o nosso padrão (1=Dom, 2=Seg... 7=Sáb)
                    F.DiaDeFolga != (((DATEPART(dw, GETDATE()) + @@DATEFIRST - 1) % 7) + 1)
                )
            """
            cursor.execute(sql, horario_atual)
            return cursor.fetchall()
        finally:
            conn.close()
    return []         

def listar_tarefas_do_dia_por_funcionario(funcionario_id):
    """
    (VERSÃO 13 - ESTRITAMENTE HOJE)
    Correções:
    1. O bug das 'Tarefas Zumbis' continua resolvido.
    2. ALTERAÇÃO: Tarefas 'Unica' atrasadas NÃO aparecem mais. Mostra apenas o que é para HOJE.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            sql = """
                WITH TarefasFiltradas AS (
                    SELECT 
                        TA.AtribuicaoID, 
                        T.TarefaID, 
                        T.Titulo, 
                        T.Pontos, 
                        TA.TipoFrequencia,
                        ISNULL(TA.DescricaoOverride, T.Descricao) as Descricao,
                        ROW_NUMBER() OVER(
                            PARTITION BY T.TarefaID, TA.TipoFrequencia 
                            ORDER BY TA.AtribuicaoID DESC
                        ) as NumeroDaLinha
                    FROM TarefasAtribuidas TA
                    JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                    WHERE
                        TA.FuncionarioID = ? 
                        AND TA.DataFimVigencia IS NULL
                        
                        -- 1. FILTRO DE AGENDAMENTO (QUANDO MOSTRAR)
                        AND (
                            -- Recorrentes: Aparecem nos dias corretos
                            TA.TipoFrequencia = 'Diaria'
                            OR (TA.TipoFrequencia = 'Semanal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(weekday, GETDATE()))
                            OR (TA.TipoFrequencia = 'Mensal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(day, GETDATE()))
                            
                            -- Únicas: Aparecem APENAS SE A DATA FOR HOJE (Mudança de <= para =)
                            OR (
                                TA.TipoFrequencia = 'Unica' 
                                AND (
                                    TA.DataAgendamento IS NULL -- Se não tiver data, mostra (opcional)
                                OR 
                                CONVERT(date, TA.DataAgendamento) <= CONVERT(date, GETDATE()) -- CORREÇÃO: Acumula pendências antigas
                            )
                        )
                    )
                        
                        -- 2. FILTRO DE CONCLUSÃO (SE JÁ FEZ, ESCONDE)
                        AND NOT EXISTS (
                            SELECT 1 FROM Entregas E
                            WHERE E.AtribuicaoID = TA.AtribuicaoID
                            AND E.StatusValidacao IN ('Aprovada', 'Pendente')
                            AND (
                                -- Regra A: Se for recorrente, esconde se fez HOJE
                                (TA.TipoFrequencia IN ('Diaria', 'Semanal', 'Mensal') AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE()))
                                OR
                                -- Regra B: Se for Única, esconde se fez EM QUALQUER DIA
                                (TA.TipoFrequencia = 'Unica')
                            )
                        )
                )
                SELECT AtribuicaoID, TarefaID, Titulo, Pontos, TipoFrequencia as Tipo, Descricao
                FROM TarefasFiltradas
                WHERE NumeroDaLinha = 1
                ORDER BY Titulo ASC
            """
            
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
            
        except Exception as e:
            logger.exception(f"!!! ERRO CRÍTICO em listar_tarefas (v13) para ID {funcionario_id}: {e}")
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
    """
    (VERSÃO CORRIGIDA V2 - COM AFASTAMENTOS)
    Lista todos os campos, incluindo dados de Férias/Afastamento e Domingo de Folga.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # ADICIONADOS: DomingoFolgaMensal, DataInicioAfastamento, DataFimAfastamento
            sql = """
                SELECT 
                    FuncionarioID, NomeCompleto, CPF, ChatIDTelegram, TelefoneWhatsApp, 
                    Cargo, Setor, SaldoPontos, HorarioNotificacao, DiaDeFolga, 
                    VerificadorCPF, NivelAcesso, PosicaoPadraoID,
                    DomingoFolgaMensal, DataInicioAfastamento, DataFimAfastamento
                FROM Funcionarios 
                ORDER BY NomeCompleto
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao listar funcionários (V2): {e}")
            return []
        finally:
            conn.close()
    return []

def buscar_funcionario_por_chat_id(chat_id):
    conn = get_db_connection()
    if conn:
        try:
            # CORREÇÃO: Usamos SELECT * para garantir que todos os atributos 
            # (como HorarioNotificacao, DiaDeFolga, NivelAcesso) existam 
            # no objeto pyodbc.Row para evitar AttributeError em main.py e ranking.
            sql = "SELECT * FROM Funcionarios WHERE ChatIDTelegram = ?"
            cursor = conn.cursor()
            cursor.execute(sql, str(chat_id))
            return cursor.fetchone()
        finally:
            conn.close()
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
    """
    Exclui um funcionário e TODOS os seus dados relacionados (Cascata Manual)
    para evitar erro de Integridade Referencial (FK).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # 1. Limpeza de Dependências (Tabelas Filhas)
            # Removemos registros onde o FuncionarioID aparece antes de remover o pai.

            # Gamificação e Histórico
            cursor.execute("DELETE FROM HistoricoRanking WHERE FuncionarioID = ?", funcionario_id)
            cursor.execute("DELETE FROM Entregas WHERE FuncionarioID = ?", funcionario_id)
            cursor.execute("DELETE FROM TarefasAtribuidas WHERE FuncionarioID = ?", funcionario_id)
            cursor.execute("DELETE FROM ConquistasFuncionarios WHERE FuncionarioID = ?", funcionario_id)

            # Financeiro e Feedback
            cursor.execute("DELETE FROM Resgates WHERE FuncionarioID = ?", funcionario_id)
            cursor.execute("DELETE FROM Feedbacks WHERE FuncionarioID = ?", funcionario_id)
            cursor.execute("DELETE FROM FeedbackSolicitacoes WHERE FuncionarioID = ?", funcionario_id)

            # Documentos e Assinaturas
            cursor.execute("DELETE FROM DocumentosAssinaturas WHERE FuncionarioID = ?", funcionario_id)
            cursor.execute("DELETE FROM DocumentosPessoaisCiencia WHERE FuncionarioID = ?", funcionario_id)
            cursor.execute("DELETE FROM DocumentosPessoais WHERE FuncionarioID = ?", funcionario_id)

            # Grupos e Metas
            cursor.execute("DELETE FROM FuncionariosGrupos WHERE FuncionarioID = ?", funcionario_id)
            # Onboarding (Correção do Erro FK)
            cursor.execute("DELETE FROM OnboardingStatus WHERE FuncionarioID = ?", funcionario_id)

            # Outros (Notas Fiscais, Escalas)
            cursor.execute("DELETE FROM NotasFiscais WHERE FuncionarioID = ?", funcionario_id)
            # Para escalas, definimos como NULL (Vazio) em vez de deletar o dia inteiro, preservando o histórico da posição
            cursor.execute("UPDATE EscalaDiaria SET FuncionarioID = NULL WHERE FuncionarioID = ?", funcionario_id)
            # Estoque (Contagens Realizadas) - Limpa itens das contagens deste funcionário, depois as contagens
            cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID IN (SELECT ContagemID FROM ContagensEstoque WHERE FuncionarioID = ?)", funcionario_id)
            cursor.execute("DELETE FROM ContagensEstoque WHERE FuncionarioID = ?", funcionario_id)
            # Agendamentos (Eventos/Festas)
            cursor.execute("DELETE FROM Agendamentos WHERE FuncionarioID = ?", funcionario_id)
            # 2. Exclusão do Registro Principal
            sql = "DELETE FROM Funcionarios WHERE FuncionarioID = ?"
            cursor.execute(sql, funcionario_id)

            conn.commit()
            print(f"--> [DATABASE] Funcionário {funcionario_id} e todos os seus dados vinculados foram excluídos.")
        except Exception as e:
            print(f"ERRO ao excluir funcionário {funcionario_id}: {e}")
            conn.rollback()
            raise e # Repassa o erro para a interface mostrar o alerta
        finally: 
            conn.close()

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

# CORREÇÃO: setor=None permite que códigos antigos chamem esta função sem quebrar
def criar_tarefa(titulo, descricao, pontos, setor=None): 
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO Tarefas (Titulo, Descricao, Pontos, Setor) VALUES (?, ?, ?, ?)"
            cursor.execute(sql, titulo, descricao, pontos, setor)
            conn.commit()
        finally: conn.close()

# CORREÇÃO: setor=None para compatibilidade
def atualizar_tarefa(tarefa_id, titulo, descricao, pontos, setor=None): 
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Tarefas SET Titulo = ?, Descricao = ?, Pontos = ?, Setor = ? WHERE TarefaID = ?"
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

def verificar_atribuicao_existente(tarefa_id, funcionario_id, tipo_frequencia=None):
    """
    (VERSÃO CORRIGIDA)
    Verifica se já existe uma atribuição ATIVA.
    Se 'tipo_frequencia' for passado, verifica se existe EXATAMENTE aquele tipo.
    Se não, verifica qualquer uma.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            if tipo_frequencia:
                # Verificação Específica (Permite ter uma 'Mensal' e uma 'Unica' da mesma tarefa, por exemplo)
                sql = """
                    SELECT COUNT(1) 
                    FROM TarefasAtribuidas 
                    WHERE TarefaID = ? 
                      AND FuncionarioID = ? 
                      AND TipoFrequencia = ?
                      AND DataFimVigencia IS NULL
                """
                cursor.execute(sql, tarefa_id, funcionario_id, tipo_frequencia)
            else:
                # Verificação Genérica (Bloqueia qualquer duplicidade)
                sql = """
                    SELECT COUNT(1) 
                    FROM TarefasAtribuidas 
                    WHERE TarefaID = ? 
                      AND FuncionarioID = ? 
                      AND DataFimVigencia IS NULL
                """
                cursor.execute(sql, tarefa_id, funcionario_id)
                
            return cursor.fetchone()[0] > 0
        finally:
            conn.close()
    return False

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

        # [CORREÇÃO DE FLUXO] Atualizamos DataEnvio para GETDATE() no momento da aprovação.
        # Isso garante que os pontos contem para o Ranking Diário do dia em que o esforço
        # foi reconhecido/validado, evitando que entregas noturnas fiquem sem pontuar no painel.
        sql_update_entrega = """
            UPDATE Entregas 
            SET StatusValidacao = 'Aprovada', 
                PontosGanhos = ?,
                DataEnvio = GETDATE() 
            WHERE EntregaID = ?
        """

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
            # CORREÇÃO: Havia 8 variáveis 'data' para 7 '?', removido um excesso.
            cursor.execute(sql, funcionario_id, data, data, data, data, data, data) 
            return cursor.fetchall()
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

def agendar_tarefa_recorrente_para_grupo(tarefa_id, grupo_id, tipo_frequencia_grupo, valor_frequencia, horario_disparo):
    """
    (VERSÃO CORRIGIDA V3 - PERMITE MÚLTIPLOS HORÁRIOS)
    Agenda uma tarefa recorrente.
    IMPORTANTE: Só remove agendamentos anteriores se forem para o MESMO GRUPO e MESMO HORÁRIO.
    Isso permite ter a mesma tarefa às 18:00 e às 20:00, mas evita duplicidade no mesmo horário.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # 1. LIMPEZA ESPECÍFICA: Encerra agendamentos ativos idênticos (mesma tarefa, grupo E HORÁRIO)
            # A mudança está aqui: adicionamos "AND HorarioDisparo = ?"
            sql_limpeza = """
                UPDATE TarefasAtribuidas 
                SET DataFimVigencia = GETDATE() 
                WHERE TarefaID = ? 
                  AND GrupoID = ? 
                  AND DataFimVigencia IS NULL
                  -- Converte para string HH:MM para garantir comparação correta independente de data
                  AND CONVERT(VARCHAR(5), HorarioDisparo, 108) = ?
            """
            cursor.execute(sql_limpeza, tarefa_id, grupo_id, horario_disparo)
            
            # 2. Cria o novo agendamento
            sql_insert = """
                INSERT INTO TarefasAtribuidas
                (TarefaID, GrupoID, TipoFrequencia, ValorFrequencia, HorarioDisparo, StatusTarefaGrupo, DataInicioVigencia)
                VALUES (?, ?, ?, ?, ?, 'Disponivel', GETDATE())
            """
            cursor.execute(sql_insert, tarefa_id, grupo_id, tipo_frequencia_grupo, valor_frequencia, horario_disparo)
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao agendar tarefa recorrente para grupo: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

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
                    -- Condição 0: A tarefa deve estar ATIVA (não excluída) - CORREÇÃO CRÍTICA
                    TA.DataFimVigencia IS NULL

                    -- Condição 1: O horário deve bater
                    AND CONVERT(VARCHAR(5), TA.HorarioDisparo, 108) = ?

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

def calcular_ranking_desempenho(data_final_calculo=None, setor_filtro=None): # <<< NOVO PARÂMETRO
    """
    Calcula o ranking com SCORE HÍBRIDO, filtrado opcionalmente por setor.
    PESOS: 50% Desempenho (Confiabilidade), 50% Pontos Brutos (Esforço).
    """
    conn = get_db_connection()
    if not conn: return []

    PESO_A_DESEMPENHO = 0.5
    PESO_B_PONTOS_BRUTOS = 0.5

    try:
        cursor = conn.cursor()
        # Busca todas as atribuições, incluindo dados do funcionário
        sql_tarefas_atribuidas = """
            -- CORREÇÃO: Selecionamos todos os campos do Funcionarios (F.*) para garantir 
            -- a inclusão de DiaDeFolga e Cargo para a lógica posterior.
            SELECT F.*, 
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

        # --- FILTRAGEM INICIAL POR SETOR ---
        funcionarios_todos = listar_funcionarios() 
        funcionarios_filtrados = []

        # Normaliza o filtro para minúsculas para comparação segura
        filtro_norm = setor_filtro.lower() if setor_filtro else None

        if filtro_norm == 'cozinha':
            # Filtro 1: Apenas quem tem 'Cozinha' no cargo
            funcionarios_filtrados = [f for f in funcionarios_todos if f.Cargo and 'cozinha' in f.Cargo.lower()]
        elif filtro_norm == 'loja':
            # Filtro 2: Apenas quem tem 'Loja' OU 'Atendimento' no cargo
            funcionarios_filtrados = [f for f in funcionarios_todos if f.Cargo and ('loja' in f.Cargo.lower() or 'atendimento' in f.Cargo.lower())]
        else: # Nenhum filtro ou filtro 'Geral'
            funcionarios_filtrados = funcionarios_todos

        # ------------------------------------

        if not funcionarios_filtrados: return [] # Retorna vazio se o setor não tiver funcionários

        # Cria mapa de dados apenas para os funcionários filtrados
        atribuicoes_por_funcionario = {} 
        for func in funcionarios_filtrados:
             atribuicoes_por_funcionario[func.FuncionarioID] = {
                'NomeCompleto': func.NomeCompleto,
                'Cargo': func.Cargo, 
                'DiaDeFolga': func.DiaDeFolga,
                'tarefas': []
            } 

        # Preenche com as atribuições apenas dos funcionários filtrados
        for atribuicao in todas_as_atribuicoes:
            if atribuicao.FuncionarioID in atribuicoes_por_funcionario:
                atribuicoes_por_funcionario[atribuicao.FuncionarioID]['tarefas'].append(atribuicao) 

        # Loop de Cálculo
        for func_id, dados in atribuicoes_por_funcionario.items():
            pontos_possiveis_total = 0 

            # --- Lógica de Cálculo de Pontos Possíveis (REVISADA) ---
            for tarefa in dados['tarefas']:
                # 1. Tarefas Pontuais (Única ou GrupoCompetitiva)
                if tarefa.TipoFrequencia in ('GrupoCompetitiva', 'Unica'):
                    data_ref = tarefa.DataAceite if tarefa.TipoFrequencia == 'GrupoCompetitiva' else tarefa.DataInicioVigencia
                    # Verifica se a data de referência existe e está dentro do mês
                    if data_ref:
                        dt_ref_date = _get_date_part(data_ref)
                        if inicio_mes <= dt_ref_date <= data_final:
                            pontos_possiveis_total += tarefa.Pontos
                    continue

                # 2. Tarefas Recorrentes (Diária, Semanal, Mensal)
                dias_ocorrencia = 0

                # Define vigência da tarefa
                start_date_tarefa = _get_date_part(tarefa.DataInicioVigencia) if tarefa.DataInicioVigencia else inicio_mes
                end_date_tarefa = _get_date_part(tarefa.DataFimVigencia) if tarefa.DataFimVigencia else data_final

                # Intersecção: O período válido é a sobreposição entre (Vigência da Tarefa) e (Mês Atual)
                start_date_calc = max(start_date_tarefa, inicio_mes)
                end_date_calc = min(end_date_tarefa, data_final)

                # Se a tarefa começou depois do fim do mês ou acabou antes do início, ignora
                if end_date_calc < start_date_calc: continue

                # Itera dia a dia no período válido
                for n in range((end_date_calc - start_date_calc).days + 1):
                    dia_atual = start_date_calc + timedelta(days=n)

                    # Verifica Folga (SQL: 1=Dom ... 7=Sab)
                    dia_da_semana_sql = (dia_atual.weekday() + 1) % 7 + 1
                    if str(dia_da_semana_sql) == str(dados['DiaDeFolga']): 
                        continue # PULA O DIA SE FOR FOLGA!

                    # Verifica Frequência
                    if tarefa.TipoFrequencia == 'Diaria': 
                        dias_ocorrencia += 1
                    elif tarefa.TipoFrequencia == 'Semanal':
                        if str(dia_da_semana_sql) == str(tarefa.ValorFrequencia): 
                            dias_ocorrencia += 1
                    elif tarefa.TipoFrequencia == 'Mensal':
                        # CORREÇÃO: Compara o dia atual (int) com a frequência (string) de forma segura.
                        # Convertendo dia_atual.day para str e ValorFrequencia para str.
                        if str(dia_atual.day) == str(tarefa.ValorFrequencia): 
                            dias_ocorrencia += 1

                pontos_possiveis_total += dias_ocorrencia * tarefa.Pontos
            # --- Fim da Lógica Revisada ---

            # 1. Calcula os pontos ganhos APENAS de tarefas regulares para o PERCENTUAL
            pontos_ganhos_regulares = calcular_pontos_ganhos_tarefas_regulares(func_id, inicio_mes, data_final) 

            # 2. Calcula o percentual (Proteção contra divisão por zero)
            if pontos_possiveis_total > 0:
                # Trava em 100% caso haja bônus extras não mapeados que excedam o possível
                percentual_desempenho = min((pontos_ganhos_regulares / pontos_possiveis_total) * 100, 100.0)
            else:
                percentual_desempenho = 0.0

            # 3. Calcula os pontos ganhos TOTAIS (incluindo bônus) para a COLUNA "Pontos (Esforço)"
            pontos_ganhos_totais = calcular_pontos_ganhos_no_periodo(func_id, inicio_mes, data_final) 

            ranking_parcial.append({
                'FuncionarioID': func_id, 
                'NomeCompleto': dados['NomeCompleto'],
                'PontosGanhos': pontos_ganhos_totais, 
                'PontosPossiveis': pontos_possiveis_total,
                'Desempenho': round(percentual_desempenho, 2)
            })

        if not ranking_parcial: return [] 

        # Calcula o máximo de pontos ganhos APENAS DENTRO DO GRUPO FILTRADO para normalização
        max_pontos_ganhos_no_setor = max((p['PontosGanhos'] for p in ranking_parcial), default=1)
        if max_pontos_ganhos_no_setor == 0: max_pontos_ganhos_no_setor = 1

        ranking_final = [] 
        for dados_func in ranking_parcial:
            # Normaliza o esforço (0 a 100 baseado no líder do setor)
            percentual_pontos_brutos = (dados_func['PontosGanhos'] / max_pontos_ganhos_no_setor) * 100 

            # Fórmula Híbrida
            score_hibrido = (dados_func['Desempenho'] * PESO_A_DESEMPENHO) + (percentual_pontos_brutos * PESO_B_PONTOS_BRUTOS) 

            dados_func['ScoreHibrido'] = round(score_hibrido, 2) 
            ranking_final.append(dados_func) 

        ranking_ordenado = sorted(ranking_final, key=lambda x: x['ScoreHibrido'], reverse=True) 
        return ranking_ordenado 

    except Exception as e:
        logger.error(f"ERRO ao calcular ranking de desempenho HÍBRIDO com filtro '{setor_filtro}': {e}", exc_info=True) 
        return [] 
    finally:
        if conn: conn.close()

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

def registrar_pontos_de_bonus(funcionario_id, pontos, motivo_log, tarefa_id_bonus, vinculo_id=None, cursor=None):
    """
    Insere um registro na tabela Entregas para contabilizar pontos de bônus.
    
    Argumentos:
        cursor (opcional): Se fornecido, usa a transação existente. 
                           Se None, abre uma nova conexão independente.
    """
    conn = None
    close_conn = False # Flag para saber se devemos fechar a conexão ao final

    # Lógica de Seleção de Conexão
    if cursor is None:
        conn = get_db_connection()
        if not conn: 
            return # Falha silenciosa ou logar erro de conexão
        cursor = conn.cursor()
        close_conn = True # Nós abrimos, nós fechamos e commitamos
    
    try:
        sql = """
            INSERT INTO Entregas
            (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa, AtribuicaoID)
            VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?, ?)
        """
        cursor.execute(sql, tarefa_id_bonus, funcionario_id, pontos, motivo_log, vinculo_id)
        
        # Só faz commit se a conexão for "nossa" (isolada)
        # Se o cursor veio de fora, o pai fará o commit.
        if close_conn:
            conn.commit()
        
        logger.info(f"--> [BÔNUS] {pontos} pts (TarefaID: {tarefa_id_bonus}, Vínculo: {vinculo_id}) registrados para FuncID {funcionario_id}. Motivo: {motivo_log}")

    except Exception as e:
        logger.error(f"ERRO ao registrar pontos de bônus (TarefaID: {tarefa_id_bonus}): {e}", exc_info=True)
        
        # Rollback apenas se a conexão for nossa
        if close_conn and conn:
            conn.rollback()
        
        # Se estamos numa transação externa (cursor injetado), RELANÇAMOS o erro
        # para que a função pai saiba que deve fazer rollback de tudo.
        if not close_conn:
            raise e

    finally:
        # Fecha apenas se abrimos
        if close_conn and conn:
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

def salvar_feedback_do_dia_com_data(funcionario_id, nota, data_registro):
    """Salva a nota de feedback do funcionário para a data de registro fornecida."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Checa se já existe para a data fornecida
            sql_check = "SELECT 1 FROM Feedbacks WHERE FuncionarioID = ? AND CONVERT(DATE, DataFeedback) = ?"
            cursor.execute(sql_check, funcionario_id, data_registro)
            if cursor.fetchone():
                print(f"--> [FEEDBACK] Feedback já recebido para a data {data_registro} (ID: {funcionario_id}).")
                return False

            # 2. Insere na data fornecida
            sql_insert = "INSERT INTO Feedbacks (FuncionarioID, DataFeedback, NotaDia) VALUES (?, ?, ?)"
            cursor.execute(sql_insert, funcionario_id, data_registro, nota)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao salvar feedback para a data {data_registro}: {e}", exc_info=True)
            return False
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

def verificar_status_disponibilidade(pessoa_id, data_verificacao, tipo='func'):
    """
    Verifica disponibilidade para Funcionários (Folgas/Férias) ou Freelancers (Conflitos).
    """
    if tipo == 'free':
        # Implementação conservadora: Verifica apenas se já está na escala desta data
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM EscalaDiaria WHERE FreelancerID = ? AND DataEscala = ?", pessoa_id, data_verificacao)
        return "⚠️ Freelancer já alocado hoje!" if cursor.fetchone() else None

    # Lógica original para funcionários mantida abaixo
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Pega dados de folga e afastamento
            sql = """
                SELECT DiaDeFolga, DomingoFolgaMensal, DataInicioAfastamento, DataFimAfastamento 
                FROM Funcionarios WHERE FuncionarioID = ?
            """
            cursor.execute(sql, pessoa_id)
            row = cursor.fetchone()

            if not row: return None

            dia_folga_semanal, dom_folga_mensal, inicio_afast, fim_afast = row

            # Conversão da data de verificação
            if isinstance(data_verificacao, str):
                dt_check = datetime.strptime(data_verificacao, '%Y-%m-%d').date()
            else:
                dt_check = data_verificacao

            # 1. Verifica Afastamento (Férias/Atestado)
            if inicio_afast and fim_afast:
                if inicio_afast <= dt_check <= fim_afast:
                    return "⚠️ Funcionário em Férias/Afastamento!"

            # 2. Verifica Folga Semanal Fixa
            # Python weekday: 0=Seg ... 6=Dom. SQL (nosso padrão): 1=Dom ... 7=Sab
            dia_semana_sql = (dt_check.weekday() + 1) % 7 + 1
            if dia_semana_sql == dia_folga_semanal:
                return "⚠️ Dia de Folga Fixa Semanal!"

            # 3. Verifica Domingo de Folga (6x1)
            if dia_semana_sql == 1 and dom_folga_mensal and dom_folga_mensal > 0:
                # Calcula qual ocorrência de domingo é este no mês
                ocorrencia = (dt_check.day - 1) // 7 + 1
                if ocorrencia == dom_folga_mensal:
                    return f"⚠️ Domingo de Folga ({dom_folga_mensal}º do mês)!"

            return None # Disponível
        except Exception as e:
            logger.error(f"Erro ao verificar disponibilidade: {e}")
            return None
        finally:
            conn.close()
    return None

def buscar_tarefas_recorrentes_agendadas_para_hoje(funcionario_id, dia_da_semana):
    """
    (CORREÇÃO SEGURA) Busca tarefas ativas agendadas para HOJE considerando folgas/férias.
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
                    TA.TipoFrequencia = 'Diaria' 
                    OR (TA.TipoFrequencia = 'Semanal' AND TA.ValorFrequencia = CAST(? AS VARCHAR))
                    OR (TA.TipoFrequencia = 'Mensal' AND TA.ValorFrequencia = CAST(DATEPART(day, GETDATE()) AS VARCHAR))
                    OR (TA.TipoFrequencia = 'Unica' AND CONVERT(date, TA.DataAgendamento) = CONVERT(date, GETDATE()))
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

def adicionar_pontos_ao_saldo(funcionario_id, pontos_a_adicionar, cursor=None):
    """Adiciona pontos ao saldo cumulativo de um funcionário (usa cursor se fornecido)."""
    if cursor:
        sql = "UPDATE Funcionarios SET SaldoPontos = SaldoPontos + ? WHERE FuncionarioID = ?"
        cursor.execute(sql, pontos_a_adicionar, funcionario_id)
        return True
    
    # Fallback se chamada sem cursor (comportamento original)
    conn = get_db_connection()
    if conn:
        try:
            cursor_fallback = conn.cursor()
            sql = "UPDATE Funcionarios SET SaldoPontos = SaldoPontos + ? WHERE FuncionarioID = ?"
            cursor_fallback.execute(sql, pontos_a_adicionar, funcionario_id)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

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
                FROM ProdutosLoja P, Funcionarios F WITH (UPDLOCK)
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

def buscar_documentos_disponiveis(funcionario_id):
    """
    (REFATORADA) Busca TODOS os documentos que o funcionário ainda não deu ciência.
    Retorna DocumentoID, TipoDocumento, MesAno e DataUpload para a interface.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Retorna todos os campos necessários para montar o botão e o callback
            sql = """
                SELECT 
                    DP.DocumentoID, DP.TipoDocumento, DP.MesAno, DP.DataUpload
                FROM DocumentosPessoais DP
                JOIN DocumentosPessoaisCiencia DPC ON DP.DocumentoID = DPC.DocumentoID
                WHERE DP.FuncionarioID = ? AND DPC.Status = 'Pendente'
                ORDER BY DP.DataUpload DESC;
            """
            cursor.execute(sql, funcionario_id)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def buscar_dados_documento_para_envio(documento_id):
    """
    (REFATORADA) Busca o caminho do arquivo e o ID da pendência de ciência
    a partir de um DocumentoID único.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A query precisa do FuncionarioID para o JOIN com a tabela de ciência
            sql = """
                SELECT DP.CaminhoArquivo, DPC.CienciaID, DP.FuncionarioID, DP.MesAno
                FROM DocumentosPessoais DP
                JOIN DocumentosPessoaisCiencia DPC ON DP.DocumentoID = DPC.DocumentoID
                WHERE DP.DocumentoID = ?
            """
            cursor.execute(sql, documento_id)
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

# ===================================================================
# == FUNÇÕES CRUD DOCUMENTOS PESSOAIS (RH) ==========================
# ===================================================================

def buscar_caminho_e_dados_documento(documento_id):
    """Busca o caminho físico e os metadados de um documento."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT CaminhoArquivo, TipoDocumento, MesAno FROM DocumentosPessoais WHERE DocumentoID = ?"
            cursor.execute(sql, documento_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def atualizar_documento_pessoal_metadados(documento_id, novo_tipo, novo_mes_ano):
    """Atualiza o Tipo e Mês/Ano de Referência de um documento pessoal."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE DocumentosPessoais SET TipoDocumento = ?, MesAno = ? WHERE DocumentoID = ?"
            cursor.execute(sql, novo_tipo, novo_mes_ano, documento_id)
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"ERRO ao atualizar metadados do documento ID {documento_id}: {e}")
            return False
        finally:
            conn.close()
    return False

def excluir_documento_pessoal_completo(documento_id):
    """
    Exclui o registro de um documento pessoal e suas pendências de ciência.
    Retorna (True/False, CaminhoArquivo)
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # 1. Buscar o caminho do arquivo ANTES de excluir (para excluir do disco depois)
            caminho_dados = buscar_caminho_e_dados_documento(documento_id)
            caminho_arquivo = caminho_dados.CaminhoArquivo if caminho_dados else None

            # 2. Excluir Pendências de Ciência
            cursor.execute("DELETE FROM DocumentosPessoaisCiencia WHERE DocumentoID = ?", documento_id)
            
            # 3. Excluir o Registro Principal
            cursor.execute("DELETE FROM DocumentosPessoais WHERE DocumentoID = ?", documento_id)
            
            conn.commit()
            
            return True, caminho_arquivo # Retorna o caminho para exclusão do disco
        except Exception as e:
            logger.error(f"ERRO CRÍTICO ao excluir documento pessoal ID {documento_id}: {e}")
            conn.rollback()
            return False, None
        finally:
            conn.close()
    return False, None

def buscar_dados_para_painel_kanban():
    """
    (VERSÃO CORRIGIDA E ROBUSTA)
    Busca dados para o painel Kanban aplicando as regras de negócio:
    1. Filtra tarefas por dia da semana/mês (não mostra tarefas de sexta na segunda).
    2. Remove tarefas da coluna 'Para Fazer' se já estiverem em 'Validação' ou 'Concluídas'.
    3. Retorna o HorárioDisparo correto para os alertas visuais.
    """
    conn = get_db_connection()
    # Estrutura padrão de retorno
    retorno_padrao = {'para_fazer': [], 'validacao': [], 'concluidas': [], 'progresso': {'concluidas': 0, 'total': 0}}

    if not conn:
        return retorno_padrao

    try:
        cursor = conn.cursor()

        # 1. Tarefas PARA FAZER (A Query Inteligente)
        # Esta query filtra o que é para HOJE e remove o que já tem entrega registrada
        sql_para_fazer = """
            SELECT 
                T.Titulo, 
                F.NomeCompleto, 
                T.Pontos, 
                TA.TipoFrequencia,
                -- Formata o horário para HH:MM, ou retorna vazio se nulo
                ISNULL(CONVERT(VARCHAR(5), TA.HorarioDisparo, 108), '') AS HorarioDisparo
            FROM TarefasAtribuidas TA
            JOIN Tarefas T ON TA.TarefaID = T.TarefaID
            JOIN Funcionarios F ON TA.FuncionarioID = F.FuncionarioID
            WHERE 
                TA.DataFimVigencia IS NULL
                
                -- REGRA 1: É PARA HOJE?
                AND (
                    TA.TipoFrequencia = 'Diaria'
                    OR (TA.TipoFrequencia = 'Semanal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(weekday, GETDATE()))
                    OR (TA.TipoFrequencia = 'Mensal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(day, GETDATE()))
                    OR (TA.TipoFrequencia = 'Unica' AND CONVERT(date, TA.DataInicioVigencia) <= CONVERT(date, GETDATE()))
                    OR (TA.TipoFrequencia = 'GrupoCompetitiva') -- Tarefas de grupo aparecem até alguém pegar
                )

                -- REGRA 2: JÁ FOI FEITA/ENVIADA? (Anti-Duplicidade)
                AND NOT EXISTS (
                    SELECT 1 FROM Entregas E
                    WHERE E.AtribuicaoID = TA.AtribuicaoID
                    AND E.StatusValidacao IN ('Aprovada', 'Pendente')
                    AND (
                        -- Se for recorrente, verifica se já foi feita HOJE
                        (TA.TipoFrequencia IN ('Diaria', 'Semanal', 'Mensal', 'GrupoCompetitiva') AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE()))
                        OR
                        -- Se for Única, verifica se já foi feita ALGUM DIA
                        (TA.TipoFrequencia = 'Unica')
                    )
                )
            ORDER BY TA.HorarioDisparo ASC, F.NomeCompleto
        """
        cursor.execute(sql_para_fazer)
        
        para_fazer = []
        for row in cursor.fetchall():
            para_fazer.append({
                "Titulo": row.Titulo,
                "NomeCompleto": row.NomeCompleto,
                "Pontos": row.Pontos,
                "HorarioDisparo": row.HorarioDisparo # Agora traz o dado real do banco
            })

        # 2. Tarefas EM VALIDAÇÃO (Sem alterações na lógica, apenas formatação)
        sql_validacao = """
            SELECT T.Titulo, F.NomeCompleto, E.DataEnvio, T.Pontos 
            FROM Entregas E 
            JOIN Tarefas T ON E.TarefaID = T.TarefaID 
            JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID 
            WHERE E.StatusValidacao = 'Pendente'
            ORDER BY E.DataEnvio DESC
        """
        cursor.execute(sql_validacao)
        validacao = []
        for row in cursor.fetchall():
            validacao.append({
                "Titulo": row.Titulo,
                "NomeCompleto": row.NomeCompleto,
                "DataEnvio": row.DataEnvio, 
                "Pontos": row.Pontos
            })

        # 3. Tarefas CONCLUÍDAS (Apenas de hoje)
        sql_concluidas = """
            SELECT T.Titulo, F.NomeCompleto, E.DataEnvio, E.PontosGanhos 
            FROM Entregas E 
            JOIN Tarefas T ON E.TarefaID = T.TarefaID 
            JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID 
            WHERE E.StatusValidacao = 'Aprovada' 
            AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE())
            ORDER BY E.DataEnvio DESC
        """
        cursor.execute(sql_concluidas)
        concluidas = []
        for row in cursor.fetchall():
            concluidas.append({
                "Titulo": row.Titulo,
                "NomeCompleto": row.NomeCompleto,
                "DataEnvio": row.DataEnvio,
                "Pontos": row.PontosGanhos
            })

        progresso = {"concluidas": len(concluidas), "total": len(para_fazer) + len(validacao) + len(concluidas)}

        return {'para_fazer': para_fazer, 'validacao': validacao, 'concluidas': concluidas, 'progresso': progresso}

    except Exception as e:
        logger.error(f"ERRO CRÍTICO KANBAN: {e}", exc_info=True) 
        return retorno_padrao
    finally:
        if conn: conn.close()
                                        
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
                    E.PontosGanhos as Pontos,
                    E.PathFotoEvidencia as CaminhoFoto -- Adicionado
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
                    C.PontosBonus as Pontos,
                    NULL as CaminhoFoto -- Conquistas nao tem foto
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
            WHERE CONVERT(DATE, GETDATE()) BETWEEN MP.DataInicio AND MP.DataFim AND MP.Status = 'Ativa'
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
            # 1. Insere o registro de Entrega/Bônus (usa o cursor principal)
            cursor.execute(sql_entrega, TAREFA_ID_META, funcionario.FuncionarioID, pontos_premio_diario, motivo)
            
            # 2. Adiciona os pontos ao saldo (usa o cursor principal)
            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_premio_diario, cursor=cursor)

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
            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_premio, cursor=cursor) # Mantendo para consistência com A e B

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


def verificar_e_premiar_meta_diaria(apuracao_id, data_apuracao_str, valor_dia, meta_principal_id):
    """
    Função auxiliar para verificar se a meta diária foi atingida e premiar a equipe DO SETOR CORRETO.
    (VERSÃO CORRIGIDA - CONEXÃO MANTIDA ABERTA)
    """
    try:
        modelo_meta_diaria = buscar_modelo_meta_para_data(data_apuracao_str) # Chamada interna

        # Buscar o status de premiação ANTES de qualquer ação
        conn_check = get_db_connection()
        ja_premiada = False
        pontos_premiados_anteriormente = 0
        if conn_check:
            try:
                cursor_check = conn_check.cursor()
                cursor_check.execute("SELECT PontosMetaDiariaGanhos FROM MetasDiariasApuracoes WHERE ApuracaoID = ?", apuracao_id)
                res_check = cursor_check.fetchone()
                if res_check and res_check[0] is not None and res_check[0] > 0:
                    ja_premiada = True
                    pontos_premiados_anteriormente = res_check[0]
            except Exception as e_check:
                 logger.error(f"Erro ao verificar se ApuracaoID {apuracao_id} já foi premiada: {e_check}")
            finally:
                if conn_check: conn_check.close()

        meta_foi_batida = modelo_meta_diaria and valor_dia >= modelo_meta_diaria.ValorMeta and modelo_meta_diaria.PontosPremio > 0

        if meta_foi_batida and not ja_premiada:
            # Cenário 1: Meta batida, ainda não premiada
            logger.info(f"Meta diária ATINGIDA (ApuracaoID: {apuracao_id}). Valor: {valor_dia} >= {modelo_meta_diaria.ValorMeta}. Premiando...")

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

                # --- CORREÇÃO AQUI: Abrimos a conexão UMA VEZ e mantemos até o final ---
                conn_interno = get_db_connection()
                if conn_interno:
                    try:
                        cursor_interno = conn_interno.cursor()
                        
                        # 1. Marca a apuração como premiada
                        sql_marcar = "UPDATE MetasDiariasApuracoes SET PontosMetaDiariaGanhos = ? WHERE ApuracaoID = ?"
                        cursor_interno.execute(sql_marcar, pontos_premio_diario, apuracao_id)
                        
                        funcionarios_do_setor = listar_funcionarios_por_setor(setor_alvo_diario)

                        if funcionarios_do_setor:
                            logger.info(f"--> Meta diária atingida! Distribuindo {pontos_premio_diario} pontos para {len(funcionarios_do_setor)} funcionários do setor '{setor_alvo_diario}'.")
                            
                            # 2. Distribui os pontos (USANDO O MESMO CURSOR ABERTO)
                            for funcionario in funcionarios_do_setor:
                                try:
                                    # Adiciona ao saldo (função segura, abre própria conexão)
                                    adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_premio_diario)
                                    
                                    # Registra histórico (USA O CURSOR INTERNO JÁ ABERTO)
                                    motivo_log = f"Meta Diária Atingida ({data_apuracao_str}) - Setor: {setor_alvo_diario}"
                                    registrar_pontos_de_bonus(
                                        funcionario.FuncionarioID,
                                        pontos_premio_diario,
                                        motivo_log,
                                        config.TAREFA_ID_PONTOS_META,
                                        vinculo_id=apuracao_id,
                                        cursor=cursor_interno # <--- AQUI ESTAVA O ERRO ANTES
                                    )
                                    
                                    # Notifica (Opcional, fora da transação de banco)
                                    if funcionario.ChatIDTelegram:
                                        mensagem_base = random.choice(config.MENSAGENS_META_DIARIA_CUMPRIDA)
                                        mensagem_telegram = mensagem_base.format(pontos=pontos_premio_diario)
                                        notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem_telegram)
                                except Exception as e_func:
                                    logger.error(f"Erro ao processar prêmio para {funcionario.NomeCompleto}: {e_func}")

                        # 3. Commita tudo de uma vez no final
                        conn_interno.commit()
                        
                    except Exception as e_proc:
                        logger.error(f"Erro durante o processo de premiação: {e_proc}")
                        if conn_interno: conn_interno.rollback()
                    finally:
                        # 4. SÓ AGORA FECHA A CONEXÃO
                        if conn_interno: conn_interno.close()
                
            else:
                logger.warning(f"Meta diária atingida, mas falha ao identificar SetorAlvo.")

        elif not meta_foi_batida and ja_premiada:
            # Cenário 2: Clawback (Reversão)
            logger.warning(f"Meta diária NÃO ATINGIDA (ApuracaoID: {apuracao_id}). REVERTENDO {pontos_premiados_anteriormente} pontos...")
            reversao_ok = _reverter_pontos_meta_diaria(apuracao_id, pontos_premiados_anteriormente, meta_principal_id)

            if reversao_ok:
                conn_zero = get_db_connection()
                if conn_zero:
                    try:
                        cursor_zero = conn_zero.cursor()
                        sql_zero = "UPDATE MetasDiariasApuracoes SET PontosMetaDiariaGanhos = 0 WHERE ApuracaoID = ?"
                        cursor_zero.execute(sql_zero, apuracao_id)
                        conn_zero.commit()
                        logger.info("Clawback concluído com sucesso.")
                    finally:
                        conn_zero.close()

    except Exception as e:
        logger.exception(f"!!! ERRO GERAL na verificação de meta diária: {e}")

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


def buscar_documentos_onboarding_para_download(funcionario_id):
    """Busca todos os FileIDs e o nome dos campos para download pelo gestor."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    RG_FileID, CPF_FileID, CTPS_FileID, TituloEleitor_FileID
                FROM OnboardingStatus
                WHERE FuncionarioID = ?
            """
            cursor.execute(sql, funcionario_id)
            resultado = cursor.fetchone()
            
            if resultado:
                # Mapeia as colunas para o nome do documento
                documentos = {
                    'RG': resultado.RG_FileID,
                    'CPF': resultado.CPF_FileID,
                    'CTPS': resultado.CTPS_FileID,
                    'TituloEleitor': resultado.TituloEleitor_FileID
                }
                # Filtra apenas FileIDs válidos
                return {doc: file_id for doc, file_id in documentos.items() if file_id}
            
            return {}
        except Exception as e:
            logger.error(f"ERRO ao buscar FileIDs de onboarding para download: {e}", exc_info=True)
            return {}
        finally:
            if conn:
                conn.close()
    return {}

# ===================================================================
# == FUNÇÕES DE ONBOARDING E GESTÃO DE DOCUMENTOS DE ADMISSÃO =======
# ===================================================================

def criar_tabela_onboarding():
    """Cria a tabela OnboardingStatus para rastrear o progresso do funcionário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 🛑 CORREÇÃO FINAL: Usamos NVARCHAR(MAX) no lugar de JSON
            sql = """
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'OnboardingStatus')
                CREATE TABLE OnboardingStatus (
                    FuncionarioID INT PRIMARY KEY REFERENCES Funcionarios(FuncionarioID),
                    StatusWorkflow VARCHAR(50) NOT NULL DEFAULT 'Pendente',
                    UltimaEtapa VARCHAR(100),
                    Escolaridade VARCHAR(50),
                    EstadoCivil VARCHAR(50),
                    DataCasamento VARCHAR(10),
                    NomeConjugue VARCHAR(100),
                    CPFConjugue VARCHAR(14),
                    QtdFilhos INT DEFAULT 0,
                    DadosFilhos NVARCHAR(MAX), 
                    RG_FileID VARCHAR(255),
                    CPF_FileID VARCHAR(255),
                    CTPS_FileID VARCHAR(255),
                    TituloEleitor_FileID VARCHAR(255)
                )
            """
            cursor.execute(sql)
            conn.commit()
            logger.info("Tabela OnboardingStatus verificada/criada.")
        except Exception as e:
            logger.error(f"ERRO CRÍTICO ao criar OnboardingStatus: {e}", exc_info=True)
        finally:
            if conn:
                conn.close()

criar_tabela_onboarding() # Executa a criação da tabela no startup do módulo database

criar_tabela_onboarding() # Executa a criação da tabela no startup do módulo database

def adicionar_colunas_admissional_onboarding():
    """Adiciona a coluna DataAdmissional e StatusAdmissional ao OnboardingStatus."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # --- Adicionar DataAdmissional ---
            try:
                # Tentativa de SELECT * para garantir que a coluna RG_FileID existe
                # (Assumimos que o OnboardingStatus já existe aqui)
                cursor.execute("SELECT DataAdmissional FROM OnboardingStatus WHERE 1=0")
                logger.info("Coluna DataAdmissional já existe.")
            except Exception:
                cursor.execute("ALTER TABLE OnboardingStatus ADD DataAdmissional DATETIME NULL")
                logger.info("SUCESSO: Coluna DataAdmissional adicionada.")

            # --- Adicionar StatusAdmissional ---
            try:
                cursor.execute("SELECT StatusAdmissional FROM OnboardingStatus WHERE 1=0")
                logger.info("Coluna StatusAdmissional já existe.")
            except Exception:
                # O valor padrão é 'Pendente' (Bloqueado até aprovação)
                cursor.execute("ALTER TABLE OnboardingStatus ADD StatusAdmissional VARCHAR(50) NOT NULL DEFAULT 'Pendente'")
                logger.info("SUCESSO: Coluna StatusAdmissional adicionada.")
                
            conn.commit()
        except Exception as e:
            # Em caso de falha, tenta comitar a parte que deu certo e loga o erro
            if conn:
                conn.rollback() # Rollback de segurança se falhar no meio
            logger.error(f"ERRO ao adicionar colunas de Admissional: {e}", exc_info=True)
        finally:
            if conn:
                conn.close()

adicionar_colunas_admissional_onboarding() # Executa a verificação ao iniciar o database

def iniciar_onboarding_funcionario(funcionario_id):
    """Cria ou reseta o registro de onboarding para 'Pendente'."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Usa MERGE para inserir ou atualizar para 'Pendente'
            sql = """
                MERGE INTO OnboardingStatus AS target
                USING (SELECT ? AS FuncionarioID) AS source
                ON (target.FuncionarioID = source.FuncionarioID)
                WHEN MATCHED THEN
                    UPDATE SET StatusWorkflow = 'Pendente', UltimaEtapa = NULL, DadosFilhos = NULL 
                WHEN NOT MATCHED THEN
                    INSERT (FuncionarioID, StatusWorkflow)
                    VALUES (?, 'Pendente');
            """
            cursor.execute(sql, funcionario_id, funcionario_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao iniciar/resetar onboarding para ID {funcionario_id}: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    return False

def resetar_onboarding_completo(funcionario_id):
    """
    Limpa TODOS os dados de onboarding do funcionário para permitir um reinício limpo,
    mas mantém o funcionário no sistema.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE OnboardingStatus
                SET StatusWorkflow = 'Pendente',
                    StatusAdmissional = 'Pendente',
                    UltimaEtapa = NULL,
                    Escolaridade = NULL,
                    EstadoCivil = NULL,
                    DataCasamento = NULL,
                    NomeConjugue = NULL,
                    CPFConjugue = NULL,
                    QtdFilhos = 0,
                    DadosFilhos = NULL,
                    RG_FileID = NULL,
                    CPF_FileID = NULL,
                    CTPS_FileID = NULL,
                    TituloEleitor_FileID = NULL
                WHERE FuncionarioID = ?
            """
            cursor.execute(sql, funcionario_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao resetar onboarding para ID {funcionario_id}: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    return False

def buscar_onboarding_status(funcionario_id):
    """Retorna o status completo e a última etapa de um funcionário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM OnboardingStatus WHERE FuncionarioID = ?"
            cursor.execute(sql, funcionario_id)
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"ERRO ao buscar status de onboarding para ID {funcionario_id}: {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()
    return None

def atualizar_onboarding_etapa(funcionario_id, nova_etapa, campo_valor=None):
    """
    Atualiza o status do workflow e um campo específico (ex: RG_FileID ou Escolaridade).
    Retorna True se atualizar.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Divide o campo e o valor
            if isinstance(campo_valor, tuple) and len(campo_valor) == 2:
                campo, valor = campo_valor
                sql = f"UPDATE OnboardingStatus SET StatusWorkflow = 'Em Progresso', UltimaEtapa = ?, {campo} = ? WHERE FuncionarioID = ?"
                cursor.execute(sql, nova_etapa, valor, funcionario_id)
            else:
                sql = "UPDATE OnboardingStatus SET StatusWorkflow = 'Em Progresso', UltimaEtapa = ? WHERE FuncionarioID = ?"
                cursor.execute(sql, nova_etapa, funcionario_id)

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao atualizar etapa '{nova_etapa}' para ID {funcionario_id}: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    return False

def finalizar_onboarding_e_notificar_gestor(funcionario_id):
    """
    Marca o StatusWorkflow como 'Completo', define StatusAdmissional como 'Pendente' 
    (o novo bloqueio) e notifica o gestor do RH.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Atualiza StatusWorkflow E StatusAdmissional
            sql = "UPDATE OnboardingStatus SET StatusWorkflow = 'Completo', StatusAdmissional = 'Pendente', UltimaEtapa = 'Finalizado' WHERE FuncionarioID = ?"
            cursor.execute(sql, funcionario_id)
            conn.commit()
            
            # --- Notificação para o Gestor RH ---
            # CORREÇÃO AQUI: Chamamos a função diretamente, sem 'database.' antes
            funcionario = buscar_funcionario_por_id(funcionario_id)
            
            if funcionario:
                mensagem_gestor = (
                    f"🟢 **NOVO ONBOARDING DE DOCUMENTOS CONCLUÍDO!** 🟢\n\n"
                    f"O funcionário **{funcionario.NomeCompleto}** finalizou o envio de todos os documentos e informações de registro.\n"
                    f"➡️ **Ação:** O funcionário foi liberado para fazer o exame admissional. Por favor, libere o acesso total após a aprovação no painel RH."
                )
                notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)

            return True
        except Exception as e:
            logger.error(f"ERRO ao finalizar onboarding para ID {funcionario_id}: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    return False

def salvar_dados_filhos(funcionario_id, dados_filhos_json):
    """Salva a string JSON dos dados dos filhos."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE OnboardingStatus SET DadosFilhos = ? WHERE FuncionarioID = ?"
            cursor.execute(sql, dados_filhos_json, funcionario_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"ERRO ao salvar dados de filhos para ID {funcionario_id}: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    return False


def aprovar_exame_admissional(funcionario_id, data_admissional):
    """
    Atualiza o status final e a data do exame admissional, removendo o bloqueio.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE OnboardingStatus 
                SET StatusAdmissional = 'Aprovado', DataAdmissional = ?
                WHERE FuncionarioID = ?
            """
            cursor.execute(sql, data_admissional, funcionario_id)
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"ERRO ao aprovar exame admissional para ID {funcionario_id}: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    return False

def buscar_onboarding_lista_rh():
    """
    Busca lista de funcionários com onboarding completo (prontos para admissional)
    ou com admissional pendente (prontos para liberação).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    F.FuncionarioID, F.NomeCompleto, 
                    OS.StatusWorkflow, OS.StatusAdmissional, OS.UltimaEtapa, OS.DataAdmissional
                FROM Funcionarios F
                JOIN OnboardingStatus OS ON F.FuncionarioID = OS.FuncionarioID
                WHERE OS.StatusWorkflow = 'Completo' AND OS.StatusAdmissional IN ('Pendente', 'Aprovado')
                ORDER BY OS.StatusAdmissional, F.NomeCompleto
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao listar onboarding para RH: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def buscar_pendencias_criticas(funcionario_id):
    """
    Busca todas as pendências que exigem ação imediata (Ciência de Comunicado/Documento).
    Retorna uma lista de tuplas: (ID, Tipo, DataEnvio)
    """
    conn = get_db_connection()
    pendencias = []
    if conn:
        try:
            cursor = conn.cursor()
            
            # Pendências de COMUNICADO GERAL
            sql_comunicados = """
                SELECT 
                    DA.AssinaturaID, 'Comunicado' as Tipo, D.Titulo as Titulo, D.DataCriacao as DataEnvio
                FROM DocumentosAssinaturas DA
                JOIN Documentos D ON DA.DocumentoID = D.DocumentoID
                WHERE DA.FuncionarioID = ? AND DA.StatusAssinatura = 'Pendente'
            """
            cursor.execute(sql_comunicados, funcionario_id)
            pendencias.extend(cursor.fetchall())
            
            # Pendências de DOCUMENTO PESSOAL/RH
            sql_pessoais = """
                SELECT 
                    DPC.CienciaID, DP.TipoDocumento as Tipo, 
                    DP.TipoDocumento + ' ref. ' + CONVERT(VARCHAR, DP.MesAno, 103) as Titulo,
                    DP.DataUpload as DataEnvio
                FROM DocumentosPessoaisCiencia DPC
                JOIN DocumentosPessoais DP ON DPC.DocumentoID = DP.DocumentoID
                WHERE DPC.FuncionarioID = ? AND DPC.Status = 'Pendente'
            """
            cursor.execute(sql_pessoais, funcionario_id)
            # Para manter a consistência, mapeamos CienciaID para o primeiro campo (AssinaturaID)
            for row in cursor.fetchall():
                 pendencias.append((row.CienciaID, row.Tipo, row.Titulo, row.DataEnvio))
            
            return pendencias
        except Exception as e:
            logger.error(f"ERRO ao buscar pendências críticas de ciência: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def verificar_feedback_dia_anterior(funcionario_id):
    """
    Verifica se o funcionário deu o feedback (nota) referente ao dia anterior.
    Retorna True se o feedback foi dado, False caso contrário.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Calcula a data de ontem
            data_ontem = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            # 1. Checa se o feedback de ONTEM já existe
            sql_check = "SELECT 1 FROM Feedbacks WHERE FuncionarioID = ? AND CONVERT(DATE, DataFeedback) = ?"
            cursor.execute(sql_check, funcionario_id, data_ontem)
            if cursor.fetchone():
                return True # Feedback já dado
            
            # 2. Se o dia anterior for Domingo (Folga Padrão), consideramos como dado
            # O dia da semana no Python (0=Seg, 6=Dom). Queremos bloquear na Segunda (ontem foi Domingo)
            # Ou seja, só bloqueamos se HOJE for Terça-feira a Sábado (ontem foi Seg a Sex).
            if datetime.now().weekday() == 0: # Se hoje é Segunda (0)
                 return True # Não exigimos feedback de Domingo
                
            return False # Feedback NÃO dado
        except Exception as e:
            logger.error(f"ERRO ao verificar feedback do dia anterior: {e}", exc_info=True)
            return True # Assume True para não bloquear em caso de erro no banco
        finally:
            if conn:
                conn.close()
    return True # Assume True para não bloquear em caso de erro na conexão

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

# ===================================================================
# == INÍCIO DO MÓDULO DE GESTÃO DE ESTOQUE (CATÁLOGO MESTRE) =========
# ===================================================================

def criar_produto_estoque(nome, unidade, estoque_min):
    """Insere um novo produto mestre na tabela ProdutosEstoque.
    RETORNA O ID do novo produto criado."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO ProdutosEstoque (NomeProduto, UnidadeMedida, EstoqueMinimo)
                VALUES (?, ?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, nome, unidade, estoque_min)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Novo produto mestre criado (ID: {novo_id}): {nome}")
            return novo_id # <-- MUDANÇA IMPORTANTE
        except Exception as e:
            logger.error(f"ERRO ao criar produto mestre: {e}", exc_info=True)
            if conn: conn.rollback()
            raise e # Lança o erro para que a interface (Tkinter) possa capturá-lo
        finally:
            if conn:
                conn.close()
    return None # Retorna None se a conexão falhar

def listar_produtos_estoque():
    """Lista todos os produtos do catálogo mestre (ProdutosEstoque)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM ProdutosEstoque ORDER BY NomeProduto"
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao listar produtos mestre: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def atualizar_produto_estoque(produto_id, nome, unidade, estoque_min):
    """Atualiza um produto mestre existente na tabela ProdutosEstoque."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE ProdutosEstoque
                SET NomeProduto = ?, UnidadeMedida = ?, EstoqueMinimo = ?
                WHERE ProdutoID = ?
            """
            cursor.execute(sql, nome, unidade, estoque_min, produto_id)
            conn.commit()
            logger.info(f"Produto mestre ID {produto_id} ({nome}) atualizado.")
        except Exception as e:
            logger.error(f"ERRO ao atualizar produto mestre ID {produto_id}: {e}", exc_info=True)
            raise e # Lança o erro para a interface
        finally:
            if conn:
                conn.close()

def excluir_produto_estoque(produto_id):
    """Exclui um produto mestre da tabela ProdutosEstoque."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM ProdutosEstoque WHERE ProdutoID = ?"
            cursor.execute(sql, produto_id)
            conn.commit()
            logger.info(f"Produto mestre ID {produto_id} excluído.")
        except Exception as e:
            logger.error(f"ERRO ao excluir produto mestre ID {produto_id}: {e}", exc_info=True)
            raise e # Lança o erro (provavelmente por restrição de chave estrangeira)
        finally:
            if conn:
                conn.close()

# ===================================================================
# == FIM DO MÓDULO DE GESTÃO DE ESTOQUE (CATÁLOGO MESTRE) ===========
# ===================================================================

# ===================================================================
# == INÍCIO DO MÓDULO DE GESTÃO DE ESTOQUE (FORNECEDORES) ============
# ===================================================================

def criar_fornecedor(cnpj, nome_fantasia):
    """Insere um novo fornecedor na tabela Fornecedores."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO Fornecedores (CNPJ, NomeFantasia) VALUES (?, ?)"
            cursor.execute(sql, cnpj, nome_fantasia)
            conn.commit()
            logger.info(f"Novo fornecedor criado: {nome_fantasia}")
        except Exception as e:
            logger.error(f"ERRO ao criar fornecedor: {e}", exc_info=True)
            raise e
        finally:
            if conn:
                conn.close()

def listar_fornecedores():
    """Lista todos os fornecedores cadastrados."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM Fornecedores ORDER BY NomeFantasia"
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao listar fornecedores: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def atualizar_fornecedor(fornecedor_id, cnpj, nome_fantasia):
    """Atualiza um fornecedor existente."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Fornecedores SET CNPJ = ?, NomeFantasia = ? WHERE FornecedorID = ?"
            cursor.execute(sql, cnpj, nome_fantasia, fornecedor_id)
            conn.commit()
            logger.info(f"Fornecedor ID {fornecedor_id} ({nome_fantasia}) atualizado.")
        except Exception as e:
            logger.error(f"ERRO ao atualizar fornecedor ID {fornecedor_id}: {e}", exc_info=True)
            raise e
        finally:
            if conn:
                conn.close()

def excluir_fornecedor(fornecedor_id):
    """Exclui um fornecedor."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM Fornecedores WHERE FornecedorID = ?"
            cursor.execute(sql, fornecedor_id)
            conn.commit()
            logger.info(f"Fornecedor ID {fornecedor_id} excluído.")
        except Exception as e:
            logger.error(f"ERRO ao excluir fornecedor ID {fornecedor_id}: {e}", exc_info=True)
            raise e
        finally:
            if conn:
                conn.close()

# ===================================================================
# == FIM DO MÓDULO DE GESTÃO DE ESTOQUE (FORNECEDORES) ==============
# ===================================================================
# ===================================================================
# == INÍCIO DO MÓDULO DE GESTÃO DE ESTOQUE (IMPORTAÇÃO XML) =========
# ===================================================================

def buscar_fornecedor_por_cnpj(cnpj):
    """Busca um fornecedor pelo CNPJ e retorna seu ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT FornecedorID FROM Fornecedores WHERE CNPJ = ?"
            cursor.execute(sql, cnpj)
            resultado = cursor.fetchone()
            return resultado[0] if resultado else None
        except Exception as e:
            logger.error(f"ERRO ao buscar fornecedor por CNPJ: {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()
    return None

def buscar_vinculo_produto_fornecedor(fornecedor_id, descricao_xml):
    """Verifica se um vínculo já existe e RETORNA O FATOR também."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Agora retorna 3 valores: ID do Vinculo, ID do Produto Mestre, Fator
            sql = "SELECT ProdutoFornecedorID, ProdutoID, FatorConversao FROM ProdutosFornecedor WHERE FornecedorID = ? AND DescricaoXML = ?"
            cursor.execute(sql, fornecedor_id, descricao_xml)
            return cursor.fetchone() 
        except Exception as e:
            logger.error(f"ERRO ao buscar vínculo DE/PARA: {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()
    return None

def criar_vinculo_produto_fornecedor(produto_id_mestre, fornecedor_id, descricao_xml, cProd, cEAN, NCM, fator_conversao=1.0):
    """Cria um novo vínculo 'DE/PARA' incluindo o Fator de Conversão."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO ProdutosFornecedor 
                (ProdutoID, FornecedorID, DescricaoXML, CodigoFornecedor, EAN, NCM, FatorConversao)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, produto_id_mestre, fornecedor_id, descricao_xml, cProd, cEAN, NCM, fator_conversao)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Vínculo criado (ID: {novo_id}) Fator: {fator_conversao}")
            return novo_id
        except Exception as e:
            logger.error(f"ERRO ao criar vínculo DE/PARA: {e}", exc_info=True)
            if conn: conn.rollback()
            return None
        finally:
            if conn:
                conn.close()
    return None

def salvar_nota_fiscal_completa(dados_nf_cabecalho, lista_itens_nf):
    """
    Salva a Nota Fiscal (cabeçalho e itens) de forma transacional.
    'dados_nf_cabecalho' é um dict: {'NumeroNF', 'FornecedorID', 'DataEmissao', 'ValorTotalNF'}
    'lista_itens_nf' é uma lista de dicts: [{'ProdutoFornecedorID', 'Quantidade', 'PrecoCustoUnitario'}]
    """
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco."
    
    # 0. IMPLEMENTAÇÃO DO BLOQUEIO DE DUPLICIDADE
    numero_nf = dados_nf_cabecalho['NumeroNF']
    fornecedor_id = dados_nf_cabecalho['FornecedorID']

    if verificar_nota_fiscal_existente(numero_nf, fornecedor_id):
        return False, f"Nota Fiscal {numero_nf} já foi importada anteriormente para este fornecedor."
        
    try:
        cursor = conn.cursor()
        
        # 1. Inserir o Cabeçalho da NF
        sql_nf = """
            INSERT INTO NotasFiscaisEntrada (NumeroNF, FornecedorID, DataEmissao, ValorTotalNF)
            VALUES (?, ?, ?, ?);
            SELECT SCOPE_IDENTITY();
        """
        cursor.execute(sql_nf, 
                       dados_nf_cabecalho['NumeroNF'], 
                       dados_nf_cabecalho['FornecedorID'], 
                       dados_nf_cabecalho['DataEmissao'], 
                       dados_nf_cabecalho['ValorTotalNF'])
        
        cursor.nextset()
        nova_nota_id = cursor.fetchone()[0]
        
        if not nova_nota_id:
            raise Exception("Falha ao obter o ID da nova Nota Fiscal.")
            
        # 2. Inserir os Itens da NF
        sql_item = """
            INSERT INTO ItensNotaFiscalEntrada (NotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario)
            VALUES (?, ?, ?, ?)
        """
        # Prepara os dados para executemany (mais rápido)
        itens_para_inserir = [
            (nova_nota_id, item['ProdutoFornecedorID'], item['Quantidade'], item['PrecoCustoUnitario'])
            for item in lista_itens_nf
        ]
        
        cursor.executemany(sql_item, itens_para_inserir)
        
        # 3. Se tudo deu certo, commita a transação
        conn.commit()
        logger.info(f"Nota Fiscal {dados_nf_cabecalho['NumeroNF']} (ID: {nova_nota_id}) e seus {len(itens_para_inserir)} itens foram salvos com sucesso.")
        return True, f"Nota Fiscal {dados_nf_cabecalho['NumeroNF']} salva com sucesso."

    except Exception as e:
        if conn: conn.rollback() # Desfaz tudo em caso de erro
        logger.error(f"ERRO CRÍTICO ao salvar NF completa (NF: {dados_nf_cabecalho.get('NumeroNF', 'N/A')}): {e}", exc_info=True)
        return False, f"Erro ao salvar NF: {e}"
    finally:
        if conn:
            conn.close()


def listar_notas_fiscais_entrada_completa():
    """Lista todas as notas fiscais de entrada salvas no banco para gestão."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT NF.NotaID, NF.NumeroNF, F.NomeFantasia, NF.DataEmissao, NF.ValorTotalNF,
                       (SELECT COUNT(*) FROM ItensNotaFiscalEntrada WHERE NotaID = NF.NotaID) as QtdItens
                FROM NotasFiscaisEntrada NF
                JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
                ORDER BY NF.DataEmissao DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao listar notas fiscais: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []

def excluir_nota_fiscal_entrada(nota_id):
    """Exclui uma Nota Fiscal de entrada e seus itens."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Excluir Itens
            cursor.execute("DELETE FROM ItensNotaFiscalEntrada WHERE NotaID = ?", nota_id)
            # 2. Excluir Cabeçalho
            cursor.execute("DELETE FROM NotasFiscaisEntrada WHERE NotaID = ?", nota_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao excluir Nota Fiscal ID {nota_id}: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            conn.close()
    return False        
            

def salvar_contagem_estoque(data_contagem, funcionario_id, lista_itens_contados):
    """
    Salva uma nova contagem de estoque e seus itens de forma transacional.
    'lista_itens_contados' é uma lista de dicts: [{'ProdutoID', 'QuantidadeContada'}]
    """
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco."

    try:
        cursor = conn.cursor()
        
        # 1. Inserir o Cabeçalho da Contagem
        sql_contagem = """
            INSERT INTO ContagensEstoque (DataContagem, FuncionarioID)
            VALUES (?, ?);
            SELECT SCOPE_IDENTITY();
        """
        cursor.execute(sql_contagem, data_contagem, funcionario_id)
        
        cursor.nextset()
        nova_contagem_id = cursor.fetchone()[0]
        
        if not nova_contagem_id:
            raise Exception("Falha ao obter o ID da nova Contagem.")
            
        # 2. Inserir os Itens da Contagem
        sql_item = """
            INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada)
            VALUES (?, ?, ?)
        """
        itens_para_inserir = [
            (nova_contagem_id, item['ProdutoID'], item['QuantidadeContada'])
            for item in lista_itens_contados
        ]
        
        cursor.executemany(sql_item, itens_para_inserir)
        
        # 3. Commita a transação
        conn.commit()
        logger.info(f"Contagem ID {nova_contagem_id} (Data: {data_contagem}) salva com {len(itens_para_inserir)} itens.")
        return True, f"Contagem de {data_contagem} salva com sucesso."

    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"ERRO CRÍTICO ao salvar contagem de estoque: {e}", exc_info=True)
        return False, f"Erro ao salvar contagem: {e}"
    finally:
        if conn:
            conn.close()

def listar_contagens_cabecalho():
    """Lista os cabeçalhos das contagens de estoque já realizadas."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT C.ContagemID, C.DataContagem, F.NomeCompleto
                FROM ContagensEstoque C
                JOIN Funcionarios F ON C.FuncionarioID = F.FuncionarioID
                ORDER BY C.DataContagem DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao listar cabeçalhos de contagem: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def buscar_itens_contagem(contagem_id):
    """Busca os itens de uma contagem específica."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT P.NomeProduto, IC.QuantidadeContada, P.UnidadeMedida
                FROM ItensContagemEstoque IC
                JOIN ProdutosEstoque P ON IC.ProdutoID = P.ProdutoID
                WHERE IC.ContagemID = ?
                ORDER BY P.NomeProduto
            """
            cursor.execute(sql, contagem_id)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao buscar itens da contagem ID {contagem_id}: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def excluir_contagem_estoque(contagem_id):
    """Exclui uma Contagem de Estoque e seus itens."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Excluir Itens
            cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ?", contagem_id)
            # 2. Excluir Cabeçalho
            cursor.execute("DELETE FROM ContagensEstoque WHERE ContagemID = ?", contagem_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao excluir Contagem ID {contagem_id}: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

# ===================================================================
# == FIM DO MÓDULO DE GESTÃO DE ESTOQUE (CONTAGEM) ==================
# ===================================================================

# ===================================================================
# == INÍCIO DO MÓDULO DE GESTÃO DE ESTOQUE (SUGESTÃO DE COMPRA) =====
# == (VERSÃO 3 - LÓGICA CORRIGIDA POR PERÍODO DE CONTAGEM) ==========
# ===================================================================

def _somar_compras_no_periodo(cursor, produto_id_mestre, data_inicio, data_fim):
    """Função auxiliar para somar todas as compras (XMLs) num período."""
    sql = """
        SELECT SUM(INI.Quantidade) as TotalComprado
        FROM ItensNotaFiscalEntrada INI
        JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
        JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
        WHERE PF.ProdutoID = ?
          AND NF.DataEmissao > ? AND NF.DataEmissao <= ?
    """
    cursor.execute(sql, produto_id_mestre, data_inicio, data_fim)
    resultado = cursor.fetchone()
    # Garante que o retorno seja Decimal
    return resultado.TotalComprado if resultado and resultado.TotalComprado else Decimal('0.0')

def gerar_sugestao_por_periodo(contagem_id_inicio, contagem_id_fim):
    """
    Função principal que calcula o Perfil de Consumo (UMD) e o Estoque Atual.
    Suporta dois modos:
    1. Período Fixo: Entre Contagem A e Contagem B.
    2. Modo Histórico: Desde a Primeira Compra (contagem_id_inicio = -1) até Contagem B.
    """
    conn = get_db_connection()
    if not conn:
        return []

    relatorio_final = []
    
    try:
        cursor = conn.cursor()
        
        # 1. Busca os detalhes da contagem final (Ponto B - OBRIGATÓRIO)
        sql_fim = "SELECT ContagemID, DataContagem FROM ContagensEstoque WHERE ContagemID = ?"
        cursor.execute(sql_fim, contagem_id_fim)
        contagem_B = cursor.fetchone()
        if not contagem_B:
            raise Exception(f"Contagem Final ID {contagem_id_fim} não encontrada.")
            
        data_final = contagem_B.DataContagem
        
        # 2. Configura o Modo de Operação (Fixo ou Dinâmico)
        modo_primeira_compra = (contagem_id_inicio == -1)
        data_inicial_fixa = None
        
        if not modo_primeira_compra:
            # Modo Padrão: Busca a data da Contagem A
            sql_inicio = "SELECT ContagemID, DataContagem FROM ContagensEstoque WHERE ContagemID = ?"
            cursor.execute(sql_inicio, contagem_id_inicio)
            contagem_A = cursor.fetchone()
            if not contagem_A:
                raise Exception(f"Contagem Inicial ID {contagem_id_inicio} não encontrada.")
            data_inicial_fixa = contagem_A.DataContagem
            
            # Validação de data apenas para modo fixo
            if (data_final - data_inicial_fixa).days <= 0:
                 if (data_final - data_inicial_fixa).days == 0:
                     pass # Aceita mesmo dia
                 else:
                    raise Exception("A Data da Contagem Final deve ser posterior à Inicial.")
        # 3. Busca os ITENS da Contagem FINAL (Estoque Atual Real)
        # CORREÇÃO: Uso de LEFT JOIN para trazer itens mesmo se o Produto Mestre tiver sido deletado.
        # ISNULL garante que o sistema não quebre ao tentar ler o nome ou unidade.
        sql_itens_fim = """
            SELECT 
                IC.ProdutoID, 
                ISNULL(P.NomeProduto, 'PRODUTO DELETADO (ID: ' + CAST(IC.ProdutoID AS VARCHAR) + ')') as NomeProduto, 
                ISNULL(P.UnidadeMedida, 'UN') as UnidadeMedida, 
                ISNULL(P.EstoqueMinimo, 0) as EstoqueMinimo, 
                IC.QuantidadeContada
            FROM ItensContagemEstoque IC
            LEFT JOIN ProdutosEstoque P ON IC.ProdutoID = P.ProdutoID
            WHERE IC.ContagemID = ?
        """
        cursor.execute(sql_itens_fim, contagem_id_fim)
        itens_contagem_final = cursor.fetchall()
        
        if not itens_contagem_final:
            raise Exception("A Contagem Final selecionada não possui itens.")
        # 4. Processamento Item a Item - LÓGICA CORRIGIDA
        for item in itens_contagem_final:
            produto_id = item.ProdutoID

            # [CORREÇÃO] Acesso direto às colunas retornadas pela query sql_itens_fim
            # A query retorna: ProdutoID, NomeProduto, UnidadeMedida, EstoqueMinimo, QuantidadeContada
            estoque_final = Decimal(str(item.QuantidadeContada)) if item.QuantidadeContada is not None else Decimal('0.0')
            estoque_minimo = Decimal(str(item.EstoqueMinimo)) if item.EstoqueMinimo is not None else Decimal('0.0')

            # VARIÁVEIS DINÂMICAS
            data_ini_calc = None
            estoque_inicial = Decimal('0.0')

            if modo_primeira_compra:
                # --- MODO HISTÓRICO COMPLETO ---
                sql_primeira_compra = """
                    SELECT MIN(NF.DataEmissao) as PrimeiraData
                    FROM ItensNotaFiscalEntrada INI
                    JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
                    JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
                    WHERE PF.ProdutoID = ?
                """
                cursor.execute(sql_primeira_compra, produto_id)
                res_data = cursor.fetchone()

                if res_data and res_data.PrimeiraData:
                    data_ini_calc = res_data.PrimeiraData
                    estoque_inicial = Decimal('0.0') # Antes da primeira compra, estoque era zero
                else:
                    data_ini_calc = data_final - timedelta(days=30) # Fallback

            else:
                # --- MODO ENTRE CONTAGENS ---
                data_ini_calc = data_inicial_fixa

                # Busca o estoque que havia na Contagem INICIAL
                sql_item_inicio = "SELECT QuantidadeContada FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?"
                cursor.execute(sql_item_inicio, contagem_id_inicio, produto_id)
                resultado_inicio = cursor.fetchone()

                qtd_inicial_raw = resultado_inicio.QuantidadeContada if resultado_inicio else 0
                estoque_inicial = Decimal(str(qtd_inicial_raw))

            # Validação de Datas
            dias_periodo = (data_final - data_ini_calc).days
            if dias_periodo <= 0: dias_periodo = 1

            # 5. Soma compras no período (Função Auxiliar já existente)
            total_comprado = _somar_compras_no_periodo(cursor, produto_id, data_ini_calc, data_final)
            if total_comprado is None: total_comprado = Decimal('0.0')

            # 6. Cálculo de Consumo: (O que tinha + O que entrou) - O que tem agora = O que saiu
            uso_total_periodo = (estoque_inicial + total_comprado) - estoque_final

            # 7. Média Diária (UMD)
            uso_medio_diario = uso_total_periodo / dias_periodo
            if uso_medio_diario < 0: uso_medio_diario = Decimal('0.0') # Evita consumo negativo

            # 8. Monta Relatório com Chaves que o Frontend espera
            relatorio_final.append({
                "ProdutoID": item.ProdutoID,
                "NomeProduto": item.NomeProduto,
                "Unidade": item.UnidadeMedida,
                "EstoqueAtual": estoque_final,
                "UsoMedioDiario": uso_medio_diario,
                "EstoqueMinimo": estoque_minimo,
                "Status": "OK",
                "TotalComprado": total_comprado,
                "DiasPeriodo": dias_periodo
            })
        return relatorio_final

    except Exception as e:
        logger.error(f"ERRO CRÍTICO ao gerar sugestão: {e}", exc_info=True)
        raise e
    finally:
        if conn:
            conn.close()

def buscar_produto_mestre_por_nome(nome_produto):
    
    """Busca um produto mestre pelo seu nome exato e retorna o ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT ProdutoID FROM ProdutosEstoque WHERE NomeProduto = ?"
            cursor.execute(sql, nome_produto)
            resultado = cursor.fetchone()
            return resultado[0] if resultado else None # Retorna o ID ou None
        except Exception as e:
            logger.error(f"ERRO ao buscar produto mestre por nome ({nome_produto}): {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()
    return None

def verificar_nota_fiscal_existente(numero_nf, fornecedor_id):
    """Verifica se uma Nota Fiscal com o mesmo número e fornecedor já foi registrada."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT COUNT(1) FROM NotasFiscaisEntrada WHERE NumeroNF = ? AND FornecedorID = ?"
            cursor.execute(sql, numero_nf, fornecedor_id)
            return cursor.fetchone()[0] > 0
        except Exception as e:
            logger.error(f"ERRO ao verificar duplicidade de NF: {e}", exc_info=True)
            return True # Assume que existe para evitar duplicidade em caso de falha
        finally:
            if conn:
                conn.close()
    return True # Assume que existe para evitar duplicidade se a conexão falhar

def buscar_historico_compras_produto(produto_id_mestre):
    """
    Busca o histórico de todas as compras (itens de NF) para um 
    produto mestre específico, para a tela de drill-down.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    NF.DataEmissao,
                    NF.NumeroNF,
                    F.NomeFantasia,
                    INI.Quantidade,
                    INI.PrecoCustoUnitario
                FROM ItensNotaFiscalEntrada INI
                JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
                JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
                JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
                WHERE PF.ProdutoID = ?
                ORDER BY NF.DataEmissao DESC
            """
            cursor.execute(sql, produto_id_mestre)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao buscar histórico de compras para ProdutoID {produto_id_mestre}: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
    return []

def buscar_configuracoes_escala():
    """Busca o único registro de configurações de escala, incluindo Jornada Padrão."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Req 1: Adicionado DuracaoJornadaPadrao
            sql = "SELECT TOP 1 MaxHorasSemPausa, DuracaoIntervalo, DuracaoJornadaPadrao FROM ConfiguracoesEscala ORDER BY ConfigID ASC"
            cursor.execute(sql)
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Erro ao buscar configurações de escala: {e}")
            return None
        finally:
            conn.close()
    return None

def listar_configuracoes_pico_diario():
    """Lista as configurações de horário de pico para todos os 7 dias da semana."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "SELECT DiaSemanaID, NomeDia, HoraBloqueioInicio, HoraBloqueioFim FROM PicoDiario ORDER BY DiaSemanaID"
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao listar configurações de pico diário: {e}")
            return []
        finally:
            conn.close()
    return []

def atualizar_pico_diario(dia_id, h_ini, h_fim):
    """Atualiza o horário de pico para um dia da semana específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Se h_ini e h_fim forem vazios (None), o UPDATE usa NULL no banco.
            sql = "UPDATE PicoDiario SET HoraBloqueioInicio = ?, HoraBloqueioFim = ? WHERE DiaSemanaID = ?"
            cursor.execute(sql, h_ini, h_fim, dia_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar pico diário para DiaID {dia_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def garantir_registro_configuracao_global():
    """Garante que haja um registro na tabela ConfiguracoesEscala (ID=1)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Verifica se o registro padrão existe. Se não, insere.
            sql = """
                IF NOT EXISTS (SELECT 1 FROM ConfiguracoesEscala)
                BEGIN
                    INSERT INTO ConfiguracoesEscala (MaxHorasSemPausa, DuracaoIntervalo)
                    VALUES (5, 1);
                END
            """
            cursor.execute(sql)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao garantir registro global de configuração: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def atualizar_configuracoes_escala(h_ini, h_fim, max_horas, duracao_int, jornada_padrao=8):
    """Atualiza as configurações de escala no banco (Incluindo Jornada Padrão)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE ConfiguracoesEscala SET 
                    MaxHorasSemPausa = ?, 
                    DuracaoIntervalo = ?,
                    DuracaoJornadaPadrao = ?,
                    DataAtualizacao = GETDATE()
            """
            # h_ini e h_fim ignorados (legado), jornada_padrao adicionado
            cursor.execute(sql, max_horas, duracao_int, jornada_padrao)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar configurações de escala: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def criar_posicao_loja(nome, x, y, setor=None):
    """Cria um ponto clicável no mapa da loja, com compatibilidade para chamadas antigas."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "INSERT INTO PosicoesLoja (NomePosicao, CoordX, CoordY, Setor, Ativo) VALUES (?, ?, ?, ?, 1)"
            cursor.execute(sql, nome, x, y, setor)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao criar posição: {e}")
            return False
        finally:
            conn.close()
    return False

def atualizar_dados_posicao(posicao_id, novo_nome, novo_setor):
    """Atualiza nome e setor de uma posição existente."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE PosicoesLoja SET NomePosicao = ?, Setor = ? WHERE PosicaoID = ?"
            cursor.execute(sql, novo_nome, novo_setor, posicao_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar posição: {e}")
            return False
        finally:
            conn.close()
    return False

def listar_posicoes_loja():
    """Lista todas as posições cadastradas, incluindo a nova coluna Setor."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Retorna explicitamente: PosicaoID, NomePosicao, CoordX, CoordY, Ativo, Setor
            cursor.execute("SELECT PosicaoID, NomePosicao, CoordX, CoordY, Ativo, Setor FROM PosicoesLoja WHERE Ativo = 1")
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def excluir_posicao_loja(posicao_id):
    """Desativa uma posição no mapa."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE PosicoesLoja SET Ativo = 0 WHERE PosicaoID = ?", posicao_id)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def salvar_escala_dia(data, posicao_id, func_id, free_id, h_ent, h_sai, h_int_ini, h_int_fim, foco):
    """
    (VERSÃO V2 - MULTI-TURNO)
    Salva escala permitindo várias pessoas na mesma posição, desde que horários não batam.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # 1. Verifica se existe conflito de horário para esta posição nesta data
            # Lógica de Overlap: (InicioA < FimB) e (FimA > InicioB)
            # Excluímos da checagem se for o mesmo funcionário/freelancer tentando editar o próprio turno (opcional, aqui simplificado)
            
            sql_conflito = """
                SELECT EscalaID FROM EscalaDiaria 
                WHERE DataEscala = ? AND PosicaoID = ?
                AND (
                    (CAST(? AS TIME) < HorarioSaida) AND (CAST(? AS TIME) > HorarioEntrada)
                )
            """
            # Se h_ent ou h_sai forem None (limpeza), não checa conflito
            conflito_id = None
            if h_ent and h_sai:
                cursor.execute(sql_conflito, data, posicao_id, h_ent, h_sai)
                res = cursor.fetchone()
                if res: conflito_id = res[0]

            if conflito_id:
                # Se conflita, ATUALIZA o registro existente (Assume edição do turno)
                sql = """
                    UPDATE EscalaDiaria SET 
                        FuncionarioID = ?, FreelancerID = ?, 
                        HorarioEntrada = ?, HorarioSaida = ?, 
                        InicioIntervalo = ?, FimIntervalo = ?, FocoDoDia = ?
                    WHERE EscalaID = ?
                """
                cursor.execute(sql, func_id, free_id, h_ent, h_sai, h_int_ini, h_int_fim, foco, conflito_id)
            else:
                # Se não conflita (horário livre), INSERE novo turno
                sql = """
                    INSERT INTO EscalaDiaria 
                    (DataEscala, PosicaoID, FuncionarioID, FreelancerID, HorarioEntrada, HorarioSaida, InicioIntervalo, FimIntervalo, FocoDoDia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                cursor.execute(sql, data, posicao_id, func_id, free_id, h_ent, h_sai, h_int_ini, h_int_fim, foco)
            
            conn.commit()
            return True
        except Exception as e:
            logging.error(f"Erro ao salvar escala multi-turno: {e}")
            return False
        finally:
            conn.close()
    return False

def buscar_escala_do_dia(data_str):
    """
    (VERSÃO V2 - MULTI-TURNO)
    Retorna um dicionário onde a CHAVE é o PosicaoID e o VALOR é uma LISTA de registros.
    """
    conn = get_db_connection()
    escala_map = {}
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    E.*, 
                    ISNULL(F.NomeCompleto, FR.Nome) as NomePessoa,
                    ISNULL(FR.Telefone, F.TelefoneWhatsApp) as TelefonePessoa
                FROM EscalaDiaria E
                LEFT JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID
                LEFT JOIN Freelancers FR ON E.FreelancerID = FR.FreelancerID
                WHERE E.DataEscala = ?
                ORDER BY E.HorarioEntrada ASC
            """
            cursor.execute(sql, data_str)
            resultados = cursor.fetchall()
            for row in resultados:
                if row.PosicaoID not in escala_map:
                    escala_map[row.PosicaoID] = []
                escala_map[row.PosicaoID].append(row)
            return escala_map
        finally:
            conn.close()
    return {}

def listar_freelancers():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Freelancers ORDER BY Nome")
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def criar_freelancer(nome, telefone):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Freelancers (Nome, Telefone) VALUES (?, ?)", nome, telefone)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def buscar_funcionarios_com_posicao_padrao(posicao_id):
    """Busca funcionário que tem esta posição como padrão (para auto-preenchimento)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Retorna o funcionário apenas se ele NÃO estiver de folga no dia (Lógica tratada no Python ou aqui)
            # Por enquanto, trazemos quem é o dono da posição
            sql = "SELECT FuncionarioID, NomeCompleto, DiaDeFolga FROM Funcionarios WHERE PosicaoPadraoID = ?"
            cursor.execute(sql, posicao_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None

def definir_posicao_padrao_funcionario(funcionario_id, posicao_id):
    """Define uma posição fixa para o funcionário e remove de outros que possam ter a mesma."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Limpa quem quer que tivesse essa posição padrão antes
            cursor.execute("UPDATE Funcionarios SET PosicaoPadraoID = NULL WHERE PosicaoPadraoID = ?", posicao_id)
            # 2. Define para o novo funcionário
            cursor.execute("UPDATE Funcionarios SET PosicaoPadraoID = ? WHERE FuncionarioID = ?", posicao_id, funcionario_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao definir posição padrão: {e}")
            return False
        finally:
            conn.close()
    return False

def gerar_relatorio_escala_texto(data_str):
    """Gera um texto formatado com a escala do dia para envio no Telegram."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Busca dados ordenados por Setor e Nome da Posição
            sql = """
                SELECT 
                    PL.Setor,
                    PL.NomePosicao,
                    ISNULL(F.NomeCompleto, FR.Nome) as NomePessoa,
                    ED.HorarioEntrada,
                    ED.HorarioSaida,
                    ED.InicioIntervalo,
                    ED.FimIntervalo
                FROM EscalaDiaria ED
                JOIN PosicoesLoja PL ON ED.PosicaoID = PL.PosicaoID
                LEFT JOIN Funcionarios F ON ED.FuncionarioID = F.FuncionarioID
                LEFT JOIN Freelancers FR ON ED.FreelancerID = FR.FreelancerID
                WHERE ED.DataEscala = ? AND (ED.FuncionarioID IS NOT NULL OR ED.FreelancerID IS NOT NULL)
                ORDER BY CASE 
                    WHEN PL.Setor = 'Frente Loja' THEN 1 
                    WHEN PL.Setor = 'Caixa' THEN 2
                    WHEN PL.Setor = 'Salão' THEN 3
                    WHEN PL.Setor = 'Buffet' THEN 4
                    WHEN PL.Setor = 'Cozinha' THEN 5
                    ELSE 99 END, PL.NomePosicao
            """
            cursor.execute(sql, data_str)
            resultados = cursor.fetchall()

            if not resultados:
                return "Nenhuma escala definida para este dia."

            texto = f"📅 **ESCALA DE TRABALHO - {datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')}**\n"
            setor_atual = ""

            for row in resultados:
                setor, pos, nome, ent, sai, ini, fim = row
                setor = setor if setor else "Geral"

                if setor != setor_atual:
                    texto += f"\n🔹 **{setor.upper()}**\n"
                    setor_atual = setor

                horario = ""
                if ent and sai:
                    horario = f"({ent.strftime('%H:%M')} - {sai.strftime('%H:%M')})"

                intervalo = ""
                if ini and fim:
                    intervalo = f"\n   ☕ Intervalo: {ini.strftime('%H:%M')} às {fim.strftime('%H:%M')}"

                texto += f"▪️ {pos}: <b>{nome}</b> {horario}{intervalo}\n"

            return texto
        except Exception as e:
            logger.error(f"Erro ao gerar relatório texto: {e}")
            return "Erro ao gerar relatório."
        finally:
            conn.close()
    return "Erro de conexão."

def buscar_horarios_ocupacao_hoje(data_str, dia_semana_int):
    """
    Busca horários da escala manual filtrando por posições ativas.
    Retorna também o SETOR para permitir filtros no gráfico.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # CORREÇÃO: Adicionado PL.Setor na seleção
            sql = """
                SELECT 
                    ED.HorarioEntrada AS Entrada, 
                    ED.HorarioSaida AS Saida, 
                    ED.InicioIntervalo, 
                    ED.FimIntervalo,
                    PL.Setor -- Nova coluna
                FROM EscalaDiaria ED
                INNER JOIN PosicoesLoja PL ON ED.PosicaoID = PL.PosicaoID
                WHERE ED.DataEscala = ?
                  AND PL.Ativo = 1
            """
            cursor.execute(sql, data_str)
            return cursor.fetchall()
        except Exception as e:
            logging.error(f"Erro ao buscar horários de ocupação: {e}")
            return []
        finally:
            conn.close()
    return []

def buscar_ultimo_foco_posicao(pos_id):
    """
    Busca o último 'Foco do Dia' registrado para esta posição em escalas passadas.
    Isso permite o pré-preenchimento inteligente.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Pega o último foco não vazio ordenado pela data mais recente
            sql = """
                SELECT TOP 1 FocoDoDia 
                FROM EscalaDiaria 
                WHERE PosicaoID = ? AND FocoDoDia IS NOT NULL AND FocoDoDia <> '' 
                ORDER BY DataEscala DESC
            """
            cursor.execute(sql, pos_id)
            res = cursor.fetchone()
            return res[0] if res else None
        except Exception as e:
            logger.error(f"Erro ao buscar último foco: {e}")
            return None
        finally:
            conn.close()
    return None

def atualizar_freelancer(freelancer_id, nome, telefone):
    """Atualiza os dados de um freelancer existente."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE Freelancers SET Nome = ?, Telefone = ? WHERE FreelancerID = ?"
            cursor.execute(sql, nome, telefone, freelancer_id)
            conn.commit()
            return True
        except Exception as e:
            logging.error(f"Erro ao atualizar freelancer: {e}")
            return False
        finally:
            conn.close()
    return False

def excluir_freelancer(freelancer_id):
    """Exclui um freelancer e limpa suas referências na escala."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Limpa referências na escala (seta para NULL)
            cursor.execute("UPDATE EscalaDiaria SET FreelancerID = NULL WHERE FreelancerID = ?", freelancer_id)
            # 2. Exclui o freelancer
            cursor.execute("DELETE FROM Freelancers WHERE FreelancerID = ?", freelancer_id)
            conn.commit()
            return True
        except Exception as e:
            logging.error(f"Erro ao excluir freelancer: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def resetar_dados_estoque_completo():
    """
    AÇÃO DESTRUTIVA: Apaga TODO o histórico de estoque, vínculos e produtos.
    Mantém apenas os Fornecedores e os Funcionários.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM ItensNotaFiscalEntrada")
            cursor.execute("DBCC CHECKIDENT ('ItensNotaFiscalEntrada', RESEED, 0)")
            cursor.execute("DELETE FROM NotasFiscaisEntrada")
            cursor.execute("DBCC CHECKIDENT ('NotasFiscaisEntrada', RESEED, 0)")
            cursor.execute("DELETE FROM ItensContagemEstoque")
            cursor.execute("DBCC CHECKIDENT ('ItensContagemEstoque', RESEED, 0)")
            cursor.execute("DELETE FROM ContagensEstoque")
            cursor.execute("DBCC CHECKIDENT ('ContagensEstoque', RESEED, 0)")
            cursor.execute("DELETE FROM ProdutosFornecedor")
            cursor.execute("DBCC CHECKIDENT ('ProdutosFornecedor', RESEED, 0)")
            cursor.execute("DELETE FROM ProdutosEstoque")
            cursor.execute("DBCC CHECKIDENT ('ProdutosEstoque', RESEED, 0)")
            conn.commit()
            logger.info("RESET COMPLETO do módulo de estoque executado com sucesso.")
            return True
        except Exception as e:
            logger.error(f"ERRO CRÍTICO ao resetar estoque: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

# ===================================================================
# == MÓDULO DE GERENCIAMENTO DE VÍNCULOS (DE/PARA) ==================
# ===================================================================

def listar_todos_vinculos_detalhado():
    """
    Lista todos os vínculos DE/PARA cadastrados para edição.
    Usa LEFT JOIN para mostrar vínculos órfãos (onde o produto ou fornecedor foi deletado).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # ISNULL substitui valores vazios por texto de alerta
            sql = """
                SELECT 
                    PF.ProdutoFornecedorID,
                    ISNULL(F.NomeFantasia, 'FORNECEDOR DELETADO'),
                    PF.DescricaoXML,
                    ISNULL(P.NomeProduto, 'PRODUTO DELETADO (ÓRFÃO)'),
                    PF.FatorConversao
                FROM ProdutosFornecedor PF
                LEFT JOIN Fornecedores F ON PF.FornecedorID = F.FornecedorID
                LEFT JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
                ORDER BY F.NomeFantasia, PF.DescricaoXML
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao listar vínculos detalhados: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []

def atualizar_vinculo_existente(vinculo_id, novo_produto_id, novo_fator):
    """Atualiza o Produto Mestre e o Fator de um vínculo existente."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE ProdutosFornecedor 
                SET ProdutoID = ?, FatorConversao = ? 
                WHERE ProdutoFornecedorID = ?
            """
            cursor.execute(sql, novo_produto_id, novo_fator, vinculo_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar vínculo ID {vinculo_id}: {e}")
            return False
        finally:
            conn.close()
    return False

def excluir_vinculo_existente(vinculo_id):
    """Exclui um vínculo DE/PARA."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM ProdutosFornecedor WHERE ProdutoFornecedorID = ?"
            cursor.execute(sql, vinculo_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao excluir vínculo ID {vinculo_id}: {e}")
            return False
        finally:
            conn.close()
    return False

def relatorio_resgates_consolidado_mes():
    """
    Retorna o total de pontos gastos por funcionário em resgates aprovados no mês corrente.
    Colunas: NomeCompleto, QtdItens, TotalPontos
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    F.NomeCompleto,
                    COUNT(R.ResgateID) as QtdItens,
                    SUM(R.PontosGastos) as TotalPontos
                FROM Resgates R
                JOIN Funcionarios F ON R.FuncionarioID = F.FuncionarioID
                WHERE R.Status = 'Aprovado'
                  AND MONTH(R.DataAprovacao) = MONTH(GETDATE())
                  AND YEAR(R.DataAprovacao) = YEAR(GETDATE())
                GROUP BY F.NomeCompleto
                ORDER BY TotalPontos DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao gerar relatório de resgates do mês: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []

# ===================================================================
# == FUNÇÕES PARA O DASHBOARD OPERACIONAL ===========================
# ===================================================================

def listar_cronograma_agendado_grupos():
    """Retorna todas as tarefas atribuídas a GRUPOS e seus horários."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    G.NomeGrupo,
                    T.Titulo,
                    TA.TipoFrequencia,
                    ISNULL(CONVERT(VARCHAR(5), TA.HorarioDisparo, 108), 'Auto') as Horario
                FROM TarefasAtribuidas TA
                JOIN Grupos G ON TA.GrupoID = G.GrupoID
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE TA.DataFimVigencia IS NULL
                ORDER BY TA.HorarioDisparo, G.NomeGrupo
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def listar_tarefas_sem_atribuicao_ativa():
    """Retorna tarefas do catálogo que NÃO estão atribuídas a ninguém."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT T.TarefaID, T.Titulo, T.Pontos, ISNULL(T.Setor, 'Geral')
                FROM Tarefas T
                WHERE NOT EXISTS (
                    SELECT 1 FROM TarefasAtribuidas TA
                    WHERE TA.TarefaID = T.TarefaID
                    AND TA.DataFimVigencia IS NULL
                )
                ORDER BY T.Setor, T.Titulo
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def listar_pendencias_gerais_hoje():
    """
    Retorna quem tinha que entregar algo HOJE e não entregou.
    Filtra apenas tarefas individuais agendadas para a data atual.
    AGORA CONSIDERA O PERÍODO DE AFASTAMENTO/FÉRIAS.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    F.NomeCompleto,
                    T.Titulo,
                    TA.TipoFrequencia
                FROM TarefasAtribuidas TA
                JOIN Funcionarios F ON TA.FuncionarioID = F.FuncionarioID
                JOIN Tarefas T ON TA.TarefaID = T.TarefaID
                WHERE 
                    TA.DataFimVigencia IS NULL
                    AND TA.FuncionarioID IS NOT NULL
                    -- Regras de Agendamento
                    AND (
                        TA.TipoFrequencia = 'Diaria'
                        OR (TA.TipoFrequencia = 'Semanal' AND CAST(TA.ValorFrequencia AS INT) = ((DATEPART(dw, GETDATE()) + @@DATEFIRST - 1) % 7) + 1)
                        OR (TA.TipoFrequencia = 'Mensal' AND CAST(TA.ValorFrequencia AS INT) = DATEPART(day, GETDATE()))
                        OR (TA.TipoFrequencia = 'Unica' AND CONVERT(date, TA.DataInicioVigencia) = CONVERT(date, GETDATE()))
                    )
                    -- Ignora quem está de folga semanal hoje
                    AND (F.DiaDeFolga IS NULL OR F.DiaDeFolga = 0 OR F.DiaDeFolga != ((DATEPART(dw, GETDATE()) + @@DATEFIRST - 1) % 7) + 1)
                    
                    -- [CORREÇÃO] Ignora quem está em Férias/Afastamento hoje
                    AND (
                        F.DataInicioAfastamento IS NULL 
                        OR CONVERT(date, GETDATE()) < F.DataInicioAfastamento 
                        OR CONVERT(date, GETDATE()) > F.DataFimAfastamento
                    )

                    -- Filtra quem NÃO entregou (Pendência)
                    AND NOT EXISTS (
                        SELECT 1 FROM Entregas E
                        WHERE E.AtribuicaoID = TA.AtribuicaoID 
                        AND CONVERT(date, E.DataEnvio) = CONVERT(date, GETDATE())
                        AND E.StatusValidacao != 'Recusada'
                    )
                ORDER BY F.NomeCompleto
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def listar_funcionarios_por_tarefa(tarefa_id):
    """
    Retorna duas listas: 
    1. Funcionários que JÁ possuem a tarefa ativa (Atribuídos).
    2. Funcionários que NÃO possuem a tarefa ativa (Disponíveis).
    Usado para filtrar a lista de seleção no Desktop.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # 1. Quem já tem a tarefa ativa
            sql_assigned = """
                SELECT F.FuncionarioID, F.NomeCompleto
                FROM Funcionarios F
                JOIN TarefasAtribuidas TA ON F.FuncionarioID = TA.FuncionarioID
                WHERE TA.TarefaID = ? AND TA.DataFimVigencia IS NULL
                ORDER BY F.NomeCompleto
            """
            cursor.execute(sql_assigned, tarefa_id)
            atribuidos = cursor.fetchall()

            # 2. Quem NÃO tem a tarefa ativa (Disponíveis para seleção)
            sql_available = """
                SELECT F.FuncionarioID, F.NomeCompleto
                FROM Funcionarios F
                WHERE NOT EXISTS (
                    SELECT 1 FROM TarefasAtribuidas TA
                    WHERE TA.FuncionarioID = F.FuncionarioID
                    AND TA.TarefaID = ?
                    AND TA.DataFimVigencia IS NULL
                )
                ORDER BY F.NomeCompleto
            """
            cursor.execute(sql_available, tarefa_id)
            disponiveis = cursor.fetchall()

            return atribuidos, disponiveis
        except Exception as e:
            logger.error(f"Erro em listar_funcionarios_por_tarefa: {e}", exc_info=True)
            return [], []
        finally:
            conn.close()
    return [],

def salvar_escala_dia_v3(escala_id, data, pos_id, func_id, free_id, h_ent, h_sai, h_int_ini, h_int_fim, foco):
    """
    (VERSÃO V3 - CRUD EXPLÍCITO)
    Se escala_id for fornecido, faz UPDATE. Se não, faz INSERT.
    Valida conflitos de horário na mesma posição antes de salvar.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Validação de Conflito (Ignora o próprio ID se for edição)
            sql_check = """
                SELECT EscalaID FROM EscalaDiaria 
                WHERE DataEscala = ? AND PosicaoID = ? 
                AND EscalaID != ? -- Ignora a si mesmo
                AND (
                    (CAST(? AS TIME) < HorarioSaida) AND (CAST(? AS TIME) > HorarioEntrada)
                )
            """
            # Trata escala_id nulo para a query
            id_check = escala_id if escala_id else -1
            cursor.execute(sql_check, data, pos_id, id_check, h_ent, h_sai)
            
            if cursor.fetchone():
                return False # Conflito detectado!

            if escala_id:
                # UPDATE
                sql = """
                    UPDATE EscalaDiaria SET 
                        FuncionarioID = ?, FreelancerID = ?, 
                        HorarioEntrada = ?, HorarioSaida = ?, 
                        InicioIntervalo = ?, FimIntervalo = ?, FocoDoDia = ?
                    WHERE EscalaID = ?
                """
                cursor.execute(sql, func_id, free_id, h_ent, h_sai, h_int_ini, h_int_fim, foco, escala_id)
            else:
                # INSERT
                sql = """
                    INSERT INTO EscalaDiaria 
                    (DataEscala, PosicaoID, FuncionarioID, FreelancerID, HorarioEntrada, HorarioSaida, InicioIntervalo, FimIntervalo, FocoDoDia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                cursor.execute(sql, data, pos_id, func_id, free_id, h_ent, h_sai, h_int_ini, h_int_fim, foco)
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro salvar v3: {e}")
            return False
        finally:
            conn.close()
    return False

def salvar_escalas_em_lote(data, lista_sugestoes):
    """
    Salva múltiplos intervalos de uma vez de forma atômica (Transação Única).
    lista_sugestoes: [(pos_id, ini, fim, dados_antigos), ...]
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # SQL focado apenas na atualização de intervalos sugeridos pela calculadora
            sql = """
                UPDATE EscalaDiaria 
                SET InicioIntervalo = ?, FimIntervalo = ? 
                WHERE DataEscala = ? AND PosicaoID = ?
            """
            for item in lista_sugestoes:
                # Executa cada update sem commitar individualmente
                cursor.execute(sql, item['ini'], item['fim'], data, item['pos_id'])

            # Comita todos os registros de uma só vez
            conn.commit()
            logger.info(f"Lote de {len(lista_sugestoes)} intervalos salvos com sucesso.")
            return True
        except Exception as e:
            conn.rollback() # Reverte TUDO se houver falha em qualquer item
            logger.error(f"ERRO ATÔMICO no lote de escalas: {e}")
            return False
        finally:
            conn.close()
    return False

def buscar_escala_tempo_real(data_str, hora_str):
    """
    (VERSÃO V4 - DEBUG + SQL ROBUSTO)
    Busca quem está trabalhando AGORA com lógica explícita para turnos noturnos.
    """
    conn = get_db_connection()
    escala_map = {}
    
    # Logs para ajudar a encontrar o erro
    print(f"--> [DB] Consultando Tempo Real. Data: {data_str} | Hora: {hora_str}")
    
    if conn:
        try:
            cursor = conn.cursor()
            
            # Data de ontem para buscar turnos que começaram ontem e terminam hoje
            data_ontem = (datetime.strptime(data_str, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')

            # SQL Explicado:
            # PARTE A: Escala de HOJE
            #   1. Turno Normal (Inicio < Fim): Hora deve estar entre eles.
            #   2. Turno Noturno (Inicio > Fim): Hora deve ser MAIOR que inicio (até 23:59) OU MENOR que fim (00:00 em diante).
            
            # PARTE B: Escala de ONTEM
            #   1. Turno Noturno de Ontem: Hora deve ser MENOR que o fim (madrugada de hoje).

            sql = """
                SELECT 
                    E.*, 
                    ISNULL(F.NomeCompleto, FR.Nome) as NomePessoa
                FROM EscalaDiaria E
                LEFT JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID
                LEFT JOIN Freelancers FR ON E.FreelancerID = FR.FreelancerID
                WHERE 
                    -- CENÁRIO 1: O registro é de HOJE
                    (
                        E.DataEscala = ? 
                        AND (
                            -- Turno Simples (ex: 08:00 as 18:00)
                            (E.HorarioEntrada <= E.HorarioSaida 
                             AND CAST(? AS TIME) >= E.HorarioEntrada 
                             AND CAST(? AS TIME) <= E.HorarioSaida)
                            OR
                            -- Turno Virada (ex: 15:00 as 02:00)
                            (E.HorarioEntrada > E.HorarioSaida 
                             AND (
                                CAST(? AS TIME) >= E.HorarioEntrada -- Parte da noite (ex: 23:00)
                                OR 
                                CAST(? AS TIME) <= E.HorarioSaida   -- Parte da manhã (ex: 01:00)
                             )
                            )
                        )
                    )
                    OR
                    -- CENÁRIO 2: O registro é de ONTEM (mas invade hoje)
                    (
                        E.DataEscala = ?
                        AND E.HorarioEntrada > E.HorarioSaida -- Tem que ser turno de virada
                        AND CAST(? AS TIME) <= E.HorarioSaida -- Hora atual deve ser antes do fim
                    )
            """
            
            # Parâmetros na ordem exata dos ?
            params = (
                data_str,   # Data Hoje
                hora_str,   # Hora (Turno Simples - Inicio)
                hora_str,   # Hora (Turno Simples - Fim)
                hora_str,   # Hora (Turno Virada - Noite)
                hora_str,   # Hora (Turno Virada - Manhã) <-- ADICIONADO QUE FALTAVA
                data_ontem, # Data Ontem
                hora_str    # Hora (Turno Ontem - Fim)
            )
            
            cursor.execute(sql, params)
            
            resultados = cursor.fetchall()
            print(f"--> [DB] Registros encontrados: {len(resultados)}")
            
            for row in resultados:
                escala_map[row.PosicaoID] = row 
                
            return escala_map
        except Exception as e:
            logger.error(f"Erro ao buscar escala tempo real (V4): {e}")
            return {}
        finally:
            conn.close()
    return {}

def excluir_turno_escala(escala_id):
    """Deleta uma escalação específica do banco de dados pelo ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "DELETE FROM EscalaDiaria WHERE EscalaID = ?"
            cursor.execute(sql, escala_id)
            conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao excluir escala: {e}")
            return False
        finally:
            conn.close()
    return False

def listar_escala_detalhada_ordenada(data_str):
    """
    Retorna a escala do dia ordenada por Setor (Alfabetico) e depois por Horário de Entrada.
    Usado para a tabela visual e o gerenciador de intervalos.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Log de Debug para ver o que está chegando
            # print(f"--> [DB DEBUG] Buscando escala ordenada para data: '{data_str}'")

            sql = """
                SELECT 
                    E.EscalaID,
                    E.PosicaoID,
                    ISNULL(PL.Setor, 'Geral') as Setor,
                    PL.NomePosicao,
                    ISNULL(F.NomeCompleto, FR.Nome) as NomePessoa,
                    E.HorarioEntrada,
                    E.HorarioSaida,
                    E.InicioIntervalo,
                    E.FimIntervalo,
                    E.FuncionarioID,
                    E.FreelancerID,
                    E.FocoDoDia
                FROM EscalaDiaria E
                JOIN PosicoesLoja PL ON E.PosicaoID = PL.PosicaoID
                LEFT JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID
                LEFT JOIN Freelancers FR ON E.FreelancerID = FR.FreelancerID
                WHERE E.DataEscala = ?
                    AND PL.Ativo = 1
                ORDER BY 
                    CASE 
                        WHEN PL.Setor = 'Frente Loja' THEN 1 
                        WHEN PL.Setor = 'Caixa' THEN 2
                        WHEN PL.Setor = 'Salão' THEN 3
                        WHEN PL.Setor = 'Buffet' THEN 4
                        WHEN PL.Setor = 'Cozinha' THEN 5
                        ELSE 99 
                    END,
                    PL.Setor, 
                    E.HorarioEntrada
            """
            cursor.execute(sql, data_str)
            resultados = cursor.fetchall()

            # print(f"--> [DB DEBUG] Encontrados {len(resultados)} registros.")
            return resultados
        except Exception as e:
            logging.error(f"Erro na query listar_escala_detalhada_ordenada: {e}")
            return []
        finally:
            conn.close()
    return []

# ===================================================================
# == MÓDULO DE SOLICITAÇÕES (COMPRAS E MANUTENÇÃO) ==================
# ===================================================================

def criar_solicitacao_interna(func_id, tipo, categoria, descricao, qtd=None, path_foto=None):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO SolicitacoesInternas 
                (FuncionarioID, Tipo, Categoria, Descricao, Quantidade, CaminhoFoto, Status)
                VALUES (?, ?, ?, ?, ?, ?, 'Pendente')
            """
            cursor.execute(sql, func_id, tipo, categoria, descricao, qtd, path_foto)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao criar solicitação: {e}")
            return False
        finally:
            conn.close()
    return False

def listar_solicitacoes_pendentes():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT S.SolicitacaoID, F.NomeCompleto, S.Tipo, S.Categoria, S.Descricao, S.Quantidade, S.CaminhoFoto, S.DataSolicitacao
                FROM SolicitacoesInternas S
                JOIN Funcionarios F ON S.FuncionarioID = F.FuncionarioID
                WHERE S.Status = 'Pendente'
                ORDER BY S.DataSolicitacao ASC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def atualizar_status_solicitacao(solicitacao_id, novo_status, motivo=None):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE SolicitacoesInternas SET Status = ?, MotivoRecusa = ?, DataConclusao = GETDATE() WHERE SolicitacaoID = ?"
            cursor.execute(sql, novo_status, motivo, solicitacao_id)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

# ===================================================================
# == NOVAS FUNÇÕES PARA AUTOMAÇÃO DE WHATSAPP (AGENDAMENTOS) ========
# ===================================================================

def buscar_agendamentos_pendentes_confirmacao(data_amanha_str):
    """
    Busca agendamentos para AMANHÃ que ainda NÃO receberam mensagem de confirmação.
    Data deve vir no formato 'YYYY-MM-DD'.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    AgendamentoID, NomeCliente, TelefoneCliente, 
                    TipoEvento, DataEvento, Observacoes
                FROM Agendamentos
                WHERE 
                    -- Filtra pela data (ignorando hora)
                    CONVERT(DATE, DataEvento) = ? 
                    -- Apenas se tiver telefone
                    AND TelefoneCliente IS NOT NULL AND TelefoneCliente != ''
                    -- Apenas se ainda não enviou
                    AND (MsgConfirmacaoEnviada IS NULL OR MsgConfirmacaoEnviada = 0)
                    -- Opcional: Apenas agendamentos confirmados (não cancelados)
                    AND StatusAgendamento != 'Cancelado'
            """
            cursor.execute(sql, data_amanha_str)
            cols = [column[0] for column in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao buscar pendências de confirmação: {e}")
            return []
        finally:
            conn.close()
    return []

def buscar_agendamentos_pendentes_posvenda(data_ontem_str):
    """
    Busca agendamentos de ONTEM que ainda NÃO receberam mensagem de pós-venda.
    Data deve vir no formato 'YYYY-MM-DD'.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    AgendamentoID, NomeCliente, TelefoneCliente, 
                    TipoEvento, DataEvento
                FROM Agendamentos
                WHERE 
                    CONVERT(DATE, DataEvento) = ? 
                    AND TelefoneCliente IS NOT NULL AND TelefoneCliente != ''
                    AND (MsgPosVendaEnviada IS NULL OR MsgPosVendaEnviada = 0)
                    AND StatusAgendamento != 'Cancelado'
            """
            cursor.execute(sql, data_ontem_str)
            cols = [column[0] for column in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao buscar pendências de pós-venda: {e}")
            return []
        finally:
            conn.close()
    return []

def marcar_flag_agendamento(agendamento_id, tipo_flag):
    """
    Marca uma mensagem como enviada.
    tipo_flag deve ser: 'criacao', 'confirmacao' ou 'posvenda'.
    """
    mapa_colunas = {
        'criacao': 'MsgCriacaoEnviada',
        'confirmacao': 'MsgConfirmacaoEnviada',
        'posvenda': 'MsgPosVendaEnviada'
    }
    
    coluna = mapa_colunas.get(tipo_flag)
    if not coluna:
        logger.error(f"Tipo de flag inválido: {tipo_flag}")
        return False

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = f"UPDATE Agendamentos SET {coluna} = 1 WHERE AgendamentoID = ?"
            cursor.execute(sql, agendamento_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao marcar flag {coluna} para ID {agendamento_id}: {e}")
            return False
        finally:
            conn.close()
    return False

# --- GESTÃO DE ACESSO WEB (MIGRAÇÃO) ---

def inicializar_tabela_usuarios():
    """Cria a tabela de usuários administrativos se não existir e cria o admin padrão."""
    conn = get_db_connection()
    if not conn: return
    
    try:
        cursor = conn.cursor()
        # Cria a tabela
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='UsuariosAdmin' AND xtype='U')
            CREATE TABLE UsuariosAdmin (
                UsuarioID INT IDENTITY(1,1) PRIMARY KEY,
                Login VARCHAR(50) UNIQUE NOT NULL,
                SenhaHash VARCHAR(64) NOT NULL, -- SHA256
                NomeExibicao VARCHAR(100),
                NivelAcesso INT DEFAULT 1 -- 1=Admin, 2=Gerente
            )
        """)
        
        # Verifica se existe algum usuário
        cursor.execute("SELECT COUNT(*) FROM UsuariosAdmin")
        count = cursor.fetchone()[0]
        
        # Se não existir ninguém, cria o Admin padrão
        if count == 0:
            # Senha padrão: "admin123" (SHA256)
            senha_padrao = hashlib.sha256("admin123".encode()).hexdigest()
            cursor.execute("""
                INSERT INTO UsuariosAdmin (Login, SenhaHash, NomeExibicao, NivelAcesso)
                VALUES (?, ?, ?, ?)
            """, ('admin', senha_padrao, 'Administrador Master', 1))
            print("--> [DB AUTH] Usuário 'admin' criado com senha padrão 'admin123'.")
        
        conn.commit()
    except Exception as e:
        logger.error(f"Erro ao inicializar tabela usuários: {e}")
    finally:
        conn.close()

def verificar_credenciais(login, senha_texto):
    """Verifica se usuario e senha conferem. Retorna dados do usuario ou None."""
    conn = get_db_connection()
    if not conn: return None
    
    try:
        senha_hash = hashlib.sha256(senha_texto.encode()).hexdigest()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT UsuarioID, NomeExibicao, NivelAcesso 
            FROM UsuariosAdmin 
            WHERE Login = ? AND SenhaHash = ?
        """, (login, senha_hash))
        
        row = cursor.fetchone()
        if row:
            return {"id": row[0], "nome": row[1], "nivel": row[2]}
        return None
    except Exception as e:
        logger.error(f"Erro ao verificar login: {e}")
        return None
    finally:
        conn.close()

# ==============================================================================
# == FUNÇÕES NOVAS PARA O ADMIN WEB (MIGRAÇÃO) ==
# ==============================================================================

def buscar_funcionarios_ativos_simples():
    """Retorna lista simplificada de funcionários ativos para o sidebar da Web."""
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        # Pega ID, Nome e Cargo (ajuste os nomes das colunas se seu banco for diferente)
        cursor.execute("""
            SELECT FuncionarioID, NomeCompleto, Cargo 
            FROM Funcionarios 
            WHERE Ativo = 1 
            ORDER BY NomeCompleto ASC
        """)
        return [{"id": row[0], "nome": row[1], "cargo": row[2]} for row in cursor.fetchall()]
    except Exception as e:
        print(f"Erro ao buscar funcionarios simples: {e}")
        return []
    finally:
        conn.close()

def atualizar_item_escala_web(escala_id, entrada, saida, int_ini, int_fim):
    """Atualiza horários de um card específico."""
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        # Tratamento para salvar NULL se vier vazio
        entrada = entrada if entrada else None
        saida = saida if saida else None
        int_ini = int_ini if int_ini else None
        int_fim = int_fim if int_fim else None

        cursor.execute("""
            UPDATE EscalaDiaria
            SET HorarioEntrada = ?, HorarioSaida = ?, IntervaloInicio = ?, IntervaloFim = ?
            WHERE EscalaID = ?
        """, (entrada, saida, int_ini, int_fim, escala_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao atualizar item web: {e}")
        return False
    finally:
        conn.close()

def adicionar_funcionario_escala_web(funcionario_id, data_iso, setor):
    """Adiciona funcionário na escala (Drag & Drop)."""
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        # Evita duplicidade no mesmo dia
        cursor.execute("SELECT Count(*) FROM EscalaDiaria WHERE FuncionarioID = ? AND DataEscala = ?", (funcionario_id, data_iso))
        if cursor.fetchone()[0] > 0:
            return False 

        cursor.execute("""
            INSERT INTO EscalaDiaria (FuncionarioID, DataEscala, Setor, HorarioEntrada, HorarioSaida)
            VALUES (?, ?, ?, '08:00', '17:00')
        """, (funcionario_id, data_iso, setor))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao adicionar na escala web: {e}")
        return False
    finally:
        conn.close()

def remover_item_escala_web(escala_id):
    """Remove funcionário da escala."""
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM EscalaDiaria WHERE EscalaID = ?", (escala_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Erro ao remover item web: {e}")
        return False
    finally:
        conn.close()

def buscar_produto_por_ean(ean):
    """
    Busca um produto mestre através do código de barras (EAN) cadastrado nos vínculos.
    Retorna: (ProdutoID, NomeProduto, Unidade, FatorConversao)
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Faz o JOIN para pegar o Nome do Mestre baseado no EAN do Fornecedor
            sql = """
                SELECT 
                    PE.ProdutoID, 
                    PE.NomeProduto, 
                    PE.UnidadeMedida,
                    PF.FatorConversao
                FROM ProdutosFornecedor PF
                JOIN ProdutosEstoque PE ON PF.ProdutoID = PE.ProdutoID
                WHERE PF.EAN = ?
            """
            cursor.execute(sql, ean)
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Erro ao buscar EAN {ean}: {e}")
            return None
        finally:
            conn.close()
    return None

def buscar_produtos_mobile_por_nome(termo):
    """Busca produtos por nome/descrição para a interface mobile."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Busca tanto no nome do fornecedor quanto no nome do mestre
            sql = """
                SELECT TOP 20
                    PF.ProdutoFornecedorID,
                    ISNULL(P.NomeProduto, 'SEM MESTRE') as NomeMestre,
                    PF.DescricaoXML,
                    F.NomeFantasia,
                    PF.FatorConversao,
                    PF.EAN
                FROM ProdutosFornecedor PF
                LEFT JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
                LEFT JOIN Fornecedores F ON PF.FornecedorID = F.FornecedorID
                WHERE P.NomeProduto LIKE ? OR PF.DescricaoXML LIKE ?
                ORDER BY P.NomeProduto
            """
            busca = f"%{termo}%"
            cursor.execute(sql, busca, busca)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def criar_unidade_a_partir_de_caixa(id_origem, novo_ean, qtd_na_caixa):
    """
    Cria um novo vínculo de UNIDADE (Fator 1) copiando dados exatos da caixa.
    Registra custo fracionado na última nota (com qtd 0) para exibição em auditoria.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # 1. Pega os dados do cadastro da CAIXA (Origem)
            sql_origem = """
                SELECT 
                    PF.ProdutoID, PF.FornecedorID, PF.NCM, PF.DescricaoXML,
                    (SELECT TOP 1 PrecoCustoUnitario FROM ItensNotaFiscalEntrada 
                     WHERE ProdutoFornecedorID = PF.ProdutoFornecedorID 
                     ORDER BY NotaID DESC) as UltimoCusto,
                    (SELECT TOP 1 NotaID FROM ItensNotaFiscalEntrada 
                     WHERE ProdutoFornecedorID = PF.ProdutoFornecedorID 
                     ORDER BY NotaID DESC) as UltimaNotaID
                FROM ProdutosFornecedor PF
                WHERE PF.ProdutoFornecedorID = ?
            """
            cursor.execute(sql_origem, id_origem)
            dados_caixa = cursor.fetchone()

            if not dados_caixa:
                return False, "Cadastro origem não encontrado."

            prod_id, forn_id, ncm, desc_xml, custo_caixa, ultima_nota_id = dados_caixa
            if custo_caixa is None: custo_caixa = 0.0

            # 2. Calcula novo custo unitário fracionado
            try:
                novo_custo = float(custo_caixa) / float(qtd_na_caixa)
            except ZeroDivisionError:
                novo_custo = 0.0

            # 3. Insere o novo vínculo copiando a Descrição Exata e pega o ID gerado
            sql_insert = """
                INSERT INTO ProdutosFornecedor 
                (ProdutoID, FornecedorID, EAN, NCM, FatorConversao, DescricaoXML)
                OUTPUT INSERTED.ProdutoFornecedorID
                VALUES (?, ?, ?, ?, 1, ?)
            """
            cursor.execute(sql_insert, prod_id, forn_id, novo_ean, ncm, desc_xml)
            novo_vinculo_id = cursor.fetchone()[0]

            # 4. Associa o novo custo à última nota fiscal (Qtd 0 para não alterar finanças)
            if ultima_nota_id and novo_vinculo_id:
                sql_insert_custo = """
                    INSERT INTO ItensNotaFiscalEntrada 
                    (NotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario)
                    VALUES (?, ?, 0, ?)
                """
                cursor.execute(sql_insert_custo, ultima_nota_id, novo_vinculo_id, novo_custo)

            conn.commit()
            return True, "Cadastro de unidade criado com sucesso!"
        except Exception as e:
            logger.error(f"Erro ao criar unidade derivada: {e}")
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()
    return False, "Erro de conexão."

def listar_auditoria_produtos():
    """
    Lista detalhada para auditoria incluindo o ÚLTIMO CUSTO PAGO.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # A subquery busca o preço unitário do item da nota fiscal mais recente
            sql = """
                SELECT 
                    PF.ProdutoFornecedorID,
                    ISNULL(P.NomeProduto, 'SEM VÍNCULO') as NomeMestre,
                    PF.DescricaoXML,
                    PF.EAN,
                    PF.NCM,
                    F.NomeFantasia as Fornecedor,
                    PF.FatorConversao,
                    ISNULL((
                        SELECT TOP 1 I.PrecoCustoUnitario 
                        FROM ItensNotaFiscalEntrada I
                        JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                        WHERE I.ProdutoFornecedorID = PF.ProdutoFornecedorID
                        ORDER BY N.DataEmissao DESC, N.NotaID DESC
                    ), 0) as UltimoCusto
                FROM ProdutosFornecedor PF
                LEFT JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
                LEFT JOIN Fornecedores F ON PF.FornecedorID = F.FornecedorID
                ORDER BY P.NomeProduto
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def atualizar_dados_auditoria(vinculo_id, novo_ean, novo_ncm, novo_fator, novo_custo=None):
    """
    Atualiza EAN, NCM, Fator e, opcionalmente, o Custo da última compra.
    (VERSÃO CORRIGIDA: Usa ItemNotaID)
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # 1. Atualiza dados cadastrais (Vínculo)
            sql_update_vinculo = """
                UPDATE ProdutosFornecedor 
                SET EAN = ?, NCM = ?, FatorConversao = ?
                WHERE ProdutoFornecedorID = ?
            """
            cursor.execute(sql_update_vinculo, novo_ean, novo_ncm, novo_fator, vinculo_id)

            # 2. Atualiza o custo (Se fornecido) na ÚLTIMA entrada deste produto
            if novo_custo is not None:
                # Busca o ID do item da última nota para esse produto
                # CORREÇÃO AQUI: Usando ItemNotaID
                sql_busca_ultimo_item = """
                    SELECT TOP 1 I.ItemNotaID 
                    FROM ItensNotaFiscalEntrada I
                    JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                    WHERE I.ProdutoFornecedorID = ?
                    ORDER BY N.DataEmissao DESC, N.NotaID DESC
                """
                cursor.execute(sql_busca_ultimo_item, vinculo_id)
                resultado = cursor.fetchone()
                
                if resultado:
                    item_nota_id = resultado[0]
                    # CORREÇÃO AQUI: Usando ItemNotaID na cláusula WHERE
                    sql_update_custo = "UPDATE ItensNotaFiscalEntrada SET PrecoCustoUnitario = ? WHERE ItemNotaID = ?"
                    cursor.execute(sql_update_custo, novo_custo, item_nota_id)

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar auditoria: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def descobrir_produto_mestre_por_ean(ean):
    """
    Verifica se este EAN já está vinculado a algum Produto Mestre,
    mesmo que seja de outro fornecedor. Retorna o Nome e ID do Mestre.
    """
    if not ean or ean in ['SEM GTIN', 'SEM EAN', '']:
        return None

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT TOP 1 P.NomeProduto, P.ProdutoID
                FROM ProdutosFornecedor PF
                JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
                WHERE PF.EAN = ?
            """
            cursor.execute(sql, ean)
            return cursor.fetchone()
        finally:
            conn.close()
    return None
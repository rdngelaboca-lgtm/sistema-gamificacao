# ==============================================================================
# database.py - Camada de acesso ao SQL Server do Sistema de Gamificação
# ------------------------------------------------------------------------------
# VERSÃO DEPURADA
# Todas as funções mantêm o MESMO NOME e os MESMOS PARÂMETROS de antes, então
# main.py, telegram_bot.py, agendador.py e os demais continuam funcionando.
# Procure por "[DEPURAÇÃO]" para ver cada ponto corrigido e o motivo.
# ==============================================================================

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
        # [DEPURAÇÃO] Antes usava 'logger' aqui, mas ele ainda não existia nesta linha
        # (NameError) e 'file=' não é um parâmetro do logger. print() é o correto.
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
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
import html      # [DEPURAÇÃO] Para proteger nomes em mensagens HTML do Telegram
import locale    # [DEPURAÇÃO] Movido para o topo (estava no meio do arquivo)
import config
import notificador_telegram
import random
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
        # [DEPURAÇÃO] timeout=10: se o SQL Server estiver desligado, desiste em 10 s
        # em vez de deixar o bot/tela "congelado" esperando indefinidamente.
        conn = pyodbc.connect(CONNECTION_STRING, timeout=10)
        return conn
    except pyodbc.Error as ex:
        logger.critical(f"FALHA CRÍTICA na conexão com o banco de dados: {ex}", exc_info=True)
        return None


# ------------------------------------------------------------------------------
# [DEPURAÇÃO] DIA DA SEMANA PADRONIZADO (1=Domingo ... 7=Sábado)
# O sistema inteiro usa 1=Dom ... 7=Sáb. O comando DATEPART(weekday) do SQL Server
# muda de resultado conforme o idioma do login (@@DATEFIRST). Algumas consultas
# já usavam a fórmula segura e outras não, então tarefas semanais e folgas
# podiam cair no dia errado. Agora TODAS usam a mesma fórmula abaixo.
# ------------------------------------------------------------------------------
def _sql_dia_semana(expressao_data="GETDATE()"):
    """Devolve um trecho SQL que calcula o dia da semana (1=Dom..7=Sáb) de forma segura."""
    return f"(((DATEPART(dw, {expressao_data}) + @@DATEFIRST - 1) % 7) + 1)"

SQL_DIA_SEMANA_HOJE = _sql_dia_semana("GETDATE()")


def _ids_tarefas_bonus():
    """IDs das tarefas de bônus (Leitura, Feedback, Metas), lidos do config.py."""
    ids = []
    for nome in ('TAREFA_ID_LEITURA', 'TAREFA_ID_FEEDBACK_DIARIO', 'TAREFA_ID_PONTOS_META'):
        valor = getattr(config, nome, None)
        if valor is not None:
            ids.append(valor)
    return ids


def _tarefa_id_meta():
    """[DEPURAÇÃO] O número 121 estava 'chumbado' em 3 funções. Agora vem do config.py."""
    return getattr(config, 'TAREFA_ID_PONTOS_META', 121)


def _para_int(valor, padrao=0):
    """Converte com segurança para int (aceita None, texto e Decimal)."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao

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


            # 2.2. Migração de ProdutosEstoque (Categoria)
            try:
                cursor.execute("SELECT TOP 1 Categoria FROM ProdutosEstoque")
            except Exception:
                logger.info("Coluna 'Categoria' não encontrada em ProdutosEstoque. Criando...")
                cursor.execute("ALTER TABLE ProdutosEstoque ADD Categoria VARCHAR(100) DEFAULT 'Geral'")
                conn.commit()
                logger.info("Migração concluída: Coluna 'Categoria' adicionada.")
        
            # 2.3. Migração de ContagensEstoque (NomeContagem)
            try:
                cursor.execute("SELECT TOP 1 NomeContagem FROM ContagensEstoque")
            except Exception:
                logger.info("Coluna 'NomeContagem' não encontrada. Criando...")
                cursor.execute("ALTER TABLE ContagensEstoque ADD NomeContagem VARCHAR(100) DEFAULT 'Geral'")
                conn.commit()
                logger.info("Migração concluída: Coluna 'NomeContagem' adicionada.")

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
                # 3.1. Cria a Tabela Global de Configurações (se não existir)
                # [DEPURAÇÃO] Antes tudo era UM único bloco SQL que criava a coluna
                # DuracaoJornadaPadrao e, no mesmo bloco, fazia UPDATE nela. O SQL Server
                # confere os nomes antes de executar, então o bloco inteiro falhava com
                # "Invalid column name". Agora cada passo é um comando separado.
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
                """)

                def _coluna_existe(tabela, coluna):
                    cursor.execute("SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID(?) AND name = ?", tabela, coluna)
                    return cursor.fetchone() is not None

                # Remove colunas antigas de bloqueio (se ainda existirem)
                for coluna_antiga in ('HoraBloqueioInicio', 'HoraBloqueioFim'):
                    if _coluna_existe('ConfiguracoesEscala', coluna_antiga):
                        cursor.execute(f"ALTER TABLE ConfiguracoesEscala DROP COLUMN {coluna_antiga}")

                # Migração Req 1: Duração da Jornada Padrão
                if not _coluna_existe('ConfiguracoesEscala', 'DuracaoJornadaPadrao'):
                    cursor.execute("ALTER TABLE ConfiguracoesEscala ADD DuracaoJornadaPadrao INT DEFAULT 8")
                    conn.commit()  # A coluna precisa existir antes do UPDATE abaixo
                cursor.execute("UPDATE ConfiguracoesEscala SET DuracaoJornadaPadrao = 8 WHERE DuracaoJornadaPadrao IS NULL")

                cursor.execute("""
                    IF NOT EXISTS (SELECT 1 FROM ConfiguracoesEscala)
                        INSERT INTO ConfiguracoesEscala (MaxHorasSemPausa, DuracaoIntervalo) VALUES (5, 1);
                """)

                # 3.2. Cria a Tabela de Bloqueio Diário
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'PicoDiario')
                    CREATE TABLE PicoDiario (
                        DiaSemanaID INT PRIMARY KEY, -- 1=Dom, 2=Seg, ..., 7=Sab
                        NomeDia VARCHAR(20) NOT NULL,
                        HoraBloqueioInicio TIME,
                        HoraBloqueioFim TIME
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

def atualizar_tarefa_do_agendamento(agendamento_id, dados_sync):
    """
    [DEPURAÇÃO - FUNÇÃO NOVA] O api_server.py chamava esta função, mas ela não existia
    (o erro era escondido por um try/except e só aparecia como aviso no log).
    Atualiza a data e a descrição da tarefa de gamificação ligada a um agendamento.
    dados_sync: {'data_agendamento': date, 'descricao_override': str}
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE TarefasAtribuidas
                SET DataAgendamento = ?, DescricaoOverride = ?
                WHERE AgendamentoID = ? AND DataFimVigencia IS NULL
            """
            cursor.execute(sql, dados_sync.get('data_agendamento'), dados_sync.get('descricao_override'), agendamento_id)
            alteradas = cursor.rowcount
            conn.commit()
            return alteradas > 0
        except Exception as e:
            logger.error(f"Erro ao sincronizar tarefa do AgendamentoID {agendamento_id}: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            conn.close()
    return False


def excluir_tarefa_do_agendamento(agendamento_id):
    """
    [DEPURAÇÃO - FUNÇÃO NOVA] Também era chamada pelo api_server.py sem existir.
    Encerra a tarefa ligada ao agendamento (preserva o histórico, igual a
    encerrar_atribuicao_tarefa) e desfaz o vínculo, para que o agendamento
    possa ser excluído sem erro de chave estrangeira.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE TarefasAtribuidas
                SET DataFimVigencia = ISNULL(DataFimVigencia, GETDATE()), AgendamentoID = NULL
                WHERE AgendamentoID = ?
            """
            cursor.execute(sql, agendamento_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao encerrar tarefa do AgendamentoID {agendamento_id}: {e}", exc_info=True)
            conn.rollback()
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
                return True
            logger.warning(f"registrar_tarefa_nao_aplicavel: AtribuicaoID {atribuicao_id} não encontrada.")
            return False
        except Exception as e:
            # [DEPURAÇÃO] Antes um erro aqui derrubava a conversa do bot sem log.
            logger.error(f"Erro ao registrar 'Não Aplicável' (AtribuicaoID {atribuicao_id}): {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

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

# [DEPURAÇÃO] Havia DUAS funções listar_funcionarios() idênticas neste arquivo.
# A cópia daqui foi removida; a única versão fica mais abaixo (com tratamento de erro).

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
    (VERSÃO 14)
    - Recorrentes (Diária/Semanal/Mensal): aparecem no dia certo e somem depois de entregues hoje.
    - Únicas: aparecem a partir da data agendada e continuam até serem entregues.
    [DEPURAÇÃO] O texto antigo dizia "estritamente hoje", mas o código acumula as Únicas
    atrasadas (comportamento intencional, marcado como CORREÇÃO). Só o texto foi ajustado.
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
                            -- [DEPURAÇÃO] Dia da semana padronizado (1=Dom) e TRY_CAST (não quebra com valor inválido)
                            OR (TA.TipoFrequencia = 'Semanal' AND TRY_CAST(TA.ValorFrequencia AS INT) = """ + SQL_DIA_SEMANA_HOJE + """)
                            OR (TA.TipoFrequencia = 'Mensal' AND TRY_CAST(TA.ValorFrequencia AS INT) = DATEPART(day, GETDATE()))

                            -- Únicas: aparecem a partir da data agendada (pendências antigas se acumulam)
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
            # [DEPURAÇÃO] Solicitações de compra/manutenção também apontam para o funcionário
            # (REFERENCES Funcionarios). Sem esta linha a exclusão falhava com erro de chave estrangeira.
            cursor.execute("DELETE FROM SolicitacoesInternas WHERE FuncionarioID = ?", funcionario_id)
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
        except Exception as e:
            # [DEPURAÇÃO] Antes o erro "vazava" para quem chamou. Agora retorna None,
            # como a própria documentação da função promete.
            logger.error(f"Erro ao atribuir TarefaID {tarefa_id} ao FuncionarioID {funcionario_id}: {e}", exc_info=True)
            conn.rollback()
            return None
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
        # [DEPURAÇÃO] "AND StatusValidacao = 'Pendente'": se dois gestores clicarem em
        # Aprovar ao mesmo tempo (ou o desktop e o Telegram), só o primeiro aprova.
        # Antes os pontos eram somados DUAS vezes.
        sql_update_entrega = """
            UPDATE Entregas
            SET StatusValidacao = 'Aprovada',
                PontosGanhos = ?,
                DataEnvio = GETDATE()
            WHERE EntregaID = ? AND StatusValidacao = 'Pendente'
        """

        cursor.execute(sql_update_entrega, pontos, entrega_id)
        if cursor.rowcount == 0:
            logger.warning(f"Entrega {entrega_id} não estava 'Pendente' (já validada?). Nada foi alterado.")
            conn.rollback()
            return []

        logger.debug(f"UPDATE Entregas executado para EntregaID {entrega_id}.")

        # 2. Adiciona os pontos ao saldo
        # [DEPURAÇÃO] Agora usa o MESMO cursor (mesma transação). Antes o saldo era gravado
        # por outra conexão: se a aprovação falhasse depois, os pontos ficavam no saldo mesmo assim.
        adicionar_pontos_ao_saldo(funcionario_id, pontos, cursor=cursor)
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
    """
    Recusa uma entrega PENDENTE. Retorna True se recusou.
    [DEPURAÇÃO] Antes era possível "recusar" uma entrega já APROVADA: o status mudava,
    mas os pontos continuavam no saldo (saldo e histórico ficavam diferentes).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE Entregas SET StatusValidacao = 'Recusada', MotivoRecusa = ?
                WHERE EntregaID = ? AND StatusValidacao = 'Pendente'
            """
            cursor.execute(sql, motivo, entrega_id)
            alteradas = cursor.rowcount
            conn.commit()
            if alteradas == 0:
                logger.warning(f"recusar_entrega: EntregaID {entrega_id} não estava 'Pendente'. Nada alterado.")
            return alteradas > 0
        except Exception as e:
            logger.error(f"Erro ao recusar EntregaID {entrega_id}: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

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
                    (TA.TipoFrequencia = 'Semanal' AND TRY_CAST(TA.ValorFrequencia AS INT) = """ + _sql_dia_semana("CAST(? AS DATE)") + """ AND CONVERT(date, TA.DataAtribuicao) <= ?) OR
                    (TA.TipoFrequencia = 'Mensal' AND TRY_CAST(TA.ValorFrequencia AS INT) = DATEPART(day, ?) AND CONVERT(date, TA.DataAtribuicao) <= ?)
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
                    AND (DiaDeFolga = 0 OR DiaDeFolga IS NULL OR DiaDeFolga != """ + SQL_DIA_SEMANA_HOJE + """)
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
                    AND (DiaDeFolga = 0 OR DiaDeFolga IS NULL OR DiaDeFolga != """ + SQL_DIA_SEMANA_HOJE + """)
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
            # [DEPURAÇÃO] Só marca se ainda estiver 'Pendente' e AVISA (True/False) se marcou.
            # Assim um clique duplo no botão "Ciente" não dá os pontos duas vezes.
            sql = """
                UPDATE DocumentosAssinaturas
                SET StatusAssinatura = 'Ciente', DataCiencia = GETDATE()
                WHERE AssinaturaID = ? AND StatusAssinatura = 'Pendente'
            """
            cursor.execute(sql, assinatura_id)
            marcou = cursor.rowcount > 0
            conn.commit()
            return marcou
        except Exception as e:
            logger.error(f"Erro ao marcar ciência da AssinaturaID {assinatura_id}: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def registrar_pontos_por_leitura(funcionario_id, pontos, titulo_documento):
    """
    (O "TRUQUE MÁGICO")
    Insere um registro na tabela Entregas para contabilizar os pontos no ranking.
    """
    conn = get_db_connection()
    # [DEPURAÇÃO] Antes o 38 estava fixo aqui; agora vem do config.py (TAREFA_ID_LEITURA).
    TAREFA_ID_LEITURA = getattr(config, 'TAREFA_ID_LEITURA', 38)

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
            # [DEPURAÇÃO] UPDLOCK/HOLDLOCK: dois cliques rápidos na nota não gravam 2 feedbacks
            # (e não dão os pontos de bônus duas vezes).
            sql_check = "SELECT 1 FROM Feedbacks WITH (UPDLOCK, HOLDLOCK) WHERE FuncionarioID = ? AND CONVERT(DATE, DataFeedback) = ?"
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

def listar_solicitacoes_feedback_pendentes():
    """
    Busca no banco todas as solicitações de FEEDBACK com status 'Pendente'.
    [DEPURAÇÃO] Esta função se chamava listar_solicitacoes_pendentes(), o MESMO nome da
    função de Compras/Manutenção mais abaixo. Em Python a segunda "apaga" a primeira,
    então esta nunca era usada. Ganhou um nome próprio; a de Compras/Manutenção
    (usada pelo gestao_estoque_main.py) continua com o nome original.
    """
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
        except Exception as e:
            # [DEPURAÇÃO] O bot espera None em caso de erro (e avisa o funcionário).
            logger.error(f"Erro ao registrar entrega preliminar (AtribuicaoID {atribuicao_id}): {e}", exc_info=True)
            conn.rollback()
            return None
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
        # [DEPURAÇÃO] Antes a conexão nunca era fechada (vazamento) e dava erro se o banco caísse.
        conn = get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM EscalaDiaria WHERE FreelancerID = ? AND DataEscala = ?", pessoa_id, data_verificacao)
            return "⚠️ Freelancer já alocado hoje!" if cursor.fetchone() else None
        except Exception as e:
            logger.error(f"Erro ao verificar disponibilidade do freelancer {pessoa_id}: {e}")
            return None
        finally:
            conn.close()

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
                dt_check = datetime.strptime(data_verificacao[:10], '%Y-%m-%d').date()
            elif isinstance(data_verificacao, datetime):
                dt_check = data_verificacao.date()
            else:
                dt_check = data_verificacao

            # [DEPURAÇÃO] O banco pode devolver datas como datetime ou texto;
            # comparar 'date' com 'datetime' gerava TypeError e a função "engolia" o erro.
            inicio_afast = _get_date_part(inicio_afast) if inicio_afast else None
            fim_afast = _get_date_part(fim_afast) if fim_afast else None

            # 1. Verifica Afastamento (Férias/Atestado)
            if inicio_afast and fim_afast:
                if inicio_afast <= dt_check <= fim_afast:
                    return "⚠️ Funcionário em Férias/Afastamento!"

            # 2. Verifica Folga Semanal Fixa
            # Python weekday: 0=Seg ... 6=Dom. SQL (nosso padrão): 1=Dom ... 7=Sab
            dia_semana_sql = (dt_check.weekday() + 1) % 7 + 1
            # [DEPURAÇÃO] DiaDeFolga pode vir como texto ('3') e 3 != '3' em Python.
            if dia_semana_sql == _para_int(dia_folga_semanal, -1):
                return "⚠️ Dia de Folga Fixa Semanal!"

            # 3. Verifica Domingo de Folga (6x1)
            dom_folga_mensal = _para_int(dom_folga_mensal, 0)
            if dia_semana_sql == 1 and dom_folga_mensal > 0:
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
    Retorna SEMPRE 3 valores: (sucesso, mensagem, resgate_id).

    [DEPURAÇÃO]
    - Antes, em "saldo insuficiente" e "produto indisponível" a função devolvia só
      2 valores. O bot faz 'sucesso, mensagem, resgate_id = ...' e QUEBRAVA
      (ValueError) exatamente quando o funcionário não tinha pontos.
    - O estoque (EstoqueDisponivel) era exibido mas nunca conferido nem descontado:
      dava para resgatar um item esgotado. Agora o estoque é reservado aqui e
      devolvido se o gestor recusar.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Pega os detalhes do produto e o saldo do funcionário (com trava de leitura)
            sql_check = """
                SELECT P.CustoEmPontos, P.Nome, P.EstoqueDisponivel, F.SaldoPontos
                FROM ProdutosLoja P WITH (UPDLOCK), Funcionarios F WITH (UPDLOCK)
                WHERE P.ProdutoID = ? AND F.FuncionarioID = ? AND P.Ativo = 1
            """
            cursor.execute(sql_check, produto_id, funcionario_id)
            resultado = cursor.fetchone()
            if not resultado:
                conn.rollback()
                return (False, "Produto não encontrado ou indisponível.", None)

            custo_produto, nome_produto, estoque, saldo_atual = resultado
            saldo_atual = saldo_atual or 0

            # 2. Verifica o estoque (None = ilimitado)
            if estoque is not None and estoque <= 0:
                conn.rollback()
                return (False, f"Que pena! O item '{nome_produto}' está sem estoque no momento.", None)

            # 3. Verifica se há saldo suficiente
            if saldo_atual < custo_produto:
                conn.rollback()
                return (False, f"Saldo insuficiente! Você tem {saldo_atual} pontos, mas o item '{nome_produto}' custa {custo_produto}.", None)

            # 4. Se chegou até aqui, pode resgatar!
            # Debita os pontos do saldo do funcionário
            sql_debitar = "UPDATE Funcionarios SET SaldoPontos = SaldoPontos - ? WHERE FuncionarioID = ?"
            cursor.execute(sql_debitar, custo_produto, funcionario_id)

            # Reserva 1 unidade do estoque (se o produto controla estoque)
            if estoque is not None:
                cursor.execute("UPDATE ProdutosLoja SET EstoqueDisponivel = EstoqueDisponivel - 1 WHERE ProdutoID = ?", produto_id)

            # Insere o registro de resgate como 'Pendente'
            sql_resgate = "INSERT INTO Resgates (FuncionarioID, ProdutoID, PontosGastos) VALUES (?, ?, ?); SELECT SCOPE_IDENTITY();"
            cursor.execute(sql_resgate, funcionario_id, produto_id, custo_produto)
            cursor.nextset()
            resgate_id = cursor.fetchone()[0]
            
            conn.commit()
            return (True, f"Resgate do item '{nome_produto}' solicitado com sucesso! Aguarde a aprovação do seu gestor.", resgate_id)
        except Exception as e:
            conn.rollback() # Segurança: Desfaz tudo em caso de erro
            logger.error(f"ERRO CRÍTICO em solicitar_resgate: {e}", exc_info=True)
            return (False, "Ocorreu um erro inesperado no servidor. Tente novamente mais tarde.", None)
        finally:
            conn.close()
    # [DEPURAÇÃO] Antes, sem conexão a função devolvia None e o bot quebrava.
    return (False, "Não foi possível conectar ao banco de dados. Tente novamente.", None)

_coluna_valor_resgate_ok = False


def _garantir_coluna_valor_resgate(cursor):
    """[RESGATES] Guarda o valor em R$ pedido no abate de comanda (antes só os pontos ficavam gravados)."""
    global _coluna_valor_resgate_ok
    if not _coluna_valor_resgate_ok:
        cursor.execute("IF COL_LENGTH('Resgates', 'ValorReais') IS NULL ALTER TABLE Resgates ADD ValorReais DECIMAL(10, 2) NULL")
        _coluna_valor_resgate_ok = True


def listar_resgates_pendentes():
    """Busca todos os resgates com status 'Pendente' para o gestor aprovar (com o valor em R$ e o saldo)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            try:
                _garantir_coluna_valor_resgate(cursor)
                conn.commit()
                coluna_valor = "R.ValorReais"
            except Exception as e:
                # [DEPURAÇÃO] sem permissão para criar a coluna: a aba continua abrindo (valor pelos pontos)
                conn.rollback()
                logger.error(f"Não foi possível criar a coluna Resgates.ValorReais: {e}")
                coluna_valor = "NULL"
            sql = f"""
                SELECT R.ResgateID, F.NomeCompleto, P.Nome, R.PontosGastos, R.DataSolicitacao,
                       {coluna_valor} AS ValorReais, F.SaldoPontos
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
    """
    Muda o status de um resgate PENDENTE para 'Aprovado'. Retorna True se aprovou.
    [DEPURAÇÃO] Antes aprovava até um resgate já RECUSADO (cujos pontos já tinham
    sido devolvidos): o funcionário ganhava o prêmio sem pagar.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE Resgates SET Status = 'Aprovado', GestorID_Aprovacao = ?, DataAprovacao = GETDATE()
                WHERE ResgateID = ? AND Status = 'Pendente'
            """
            cursor.execute(sql, gestor_id, resgate_id)
            aprovou = cursor.rowcount > 0
            conn.commit()
            if not aprovou:
                logger.warning(f"aprovar_resgate: ResgateID {resgate_id} não está 'Pendente'.")
            return aprovou
        except Exception as e:
            conn.rollback()
            logger.error(f"ERRO ao aprovar resgate {resgate_id}: {e}", exc_info=True)
            return False
        finally:
            conn.close()
    return False

def recusar_resgate(resgate_id, gestor_id):
    """
    Muda o status para 'Recusado' e DEVOLVE os pontos (e o estoque) ao funcionário.
    [DEPURAÇÃO] Antes não conferia o status: recusar duas vezes (ou recusar um já
    aprovado) devolvia os pontos de novo, criando pontos "do nada".
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Primeiro, busca quantos pontos foram gastos e para qual funcionário (só se Pendente)
            sql_find = """
                SELECT R.FuncionarioID, R.PontosGastos, R.ProdutoID, P.EstoqueDisponivel
                FROM Resgates R WITH (UPDLOCK)
                LEFT JOIN ProdutosLoja P ON R.ProdutoID = P.ProdutoID
                WHERE R.ResgateID = ? AND R.Status = 'Pendente'
            """
            cursor.execute(sql_find, resgate_id)
            resgate = cursor.fetchone()
            if not resgate:
                logger.warning(f"recusar_resgate: ResgateID {resgate_id} não encontrado ou não está 'Pendente'.")
                conn.rollback()
                return False

            funcionario_id, pontos_gastos, produto_id, estoque = resgate
            # Devolve os pontos
            sql_refund = "UPDATE Funcionarios SET SaldoPontos = SaldoPontos + ? WHERE FuncionarioID = ?"
            cursor.execute(sql_refund, pontos_gastos, funcionario_id)

            # Devolve a unidade reservada ao estoque (se o produto controla estoque)
            if estoque is not None:
                cursor.execute("UPDATE ProdutosLoja SET EstoqueDisponivel = EstoqueDisponivel + 1 WHERE ProdutoID = ?", produto_id)

            # Atualiza o status do resgate
            sql_update = "UPDATE Resgates SET Status = 'Recusado', GestorID_Aprovacao = ?, DataAprovacao = GETDATE() WHERE ResgateID = ?"
            cursor.execute(sql_update, gestor_id, resgate_id)
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"ERRO ao recusar resgate: {e}", exc_info=True)
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

def registrar_solicitacao_comanda(funcionario_id, valor_reais, pontos_necessarios):
    """Registra o abate de comanda como um resgate pendente na loja, criando um produto virtual se necessário."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # 1. Garante que existe um 'Produto Virtual' para a Comanda (Ativo=0 para não aparecer no menu)
            nome_produto = "Abate na Comanda"
            cursor.execute("SELECT ProdutoID FROM ProdutosLoja WHERE Nome = ?", nome_produto)
            res = cursor.fetchone()
            if res:
                produto_id = res[0]
            else:
                cursor.execute("INSERT INTO ProdutosLoja (Nome, Descricao, CustoEmPontos, EstoqueDisponivel, Ativo) VALUES (?, ?, 0, NULL, 0); SELECT SCOPE_IDENTITY();", nome_produto, "Abatimento dinâmico de valor na comanda.")
                cursor.nextset()
                produto_id = cursor.fetchone()[0]

            # 2. Debita os pontos (Reserva Provisória)
            # [DEPURAÇÃO] O saldo é conferido NO PRÓPRIO UPDATE. Antes, dois pedidos
            # simultâneos podiam deixar o saldo NEGATIVO.
            sql_debitar = """
                UPDATE Funcionarios SET SaldoPontos = SaldoPontos - ?
                WHERE FuncionarioID = ? AND SaldoPontos >= ?
            """
            cursor.execute(sql_debitar, pontos_necessarios, funcionario_id, pontos_necessarios)
            if cursor.rowcount == 0:
                conn.rollback()
                return (False, "Saldo insuficiente para este abate.", None)

            # 3. Insere em Resgates como Pendente (com o valor em R$ pedido)
            try:
                _garantir_coluna_valor_resgate(cursor)
                sql_resgate = ("INSERT INTO Resgates (FuncionarioID, ProdutoID, PontosGastos, Status, ValorReais) "
                               "VALUES (?, ?, ?, 'Pendente', ?); SELECT SCOPE_IDENTITY();")
                cursor.execute(sql_resgate, funcionario_id, produto_id, pontos_necessarios, Decimal(str(round(valor_reais, 2))))
            except pyodbc.Error as e:
                # [DEPURAÇÃO] sem a coluna nova o pedido NÃO pode falhar: grava como antes (só os pontos)
                logger.error(f"Resgate sem o valor em R$ (coluna ValorReais indisponível): {e}")
                sql_resgate = "INSERT INTO Resgates (FuncionarioID, ProdutoID, PontosGastos, Status) VALUES (?, ?, ?, 'Pendente'); SELECT SCOPE_IDENTITY();"
                cursor.execute(sql_resgate, funcionario_id, produto_id, pontos_necessarios)
            cursor.nextset()
            resgate_id = cursor.fetchone()[0]

            conn.commit()
            return (True, f"Solicitação de abate no valor de R$ {valor_reais:.2f} enviada para aprovação do gestor!", resgate_id)
        except Exception as e:
            conn.rollback()
            logger.error(f"ERRO em registrar_solicitacao_comanda: {e}")
            return (False, "Ocorreu um erro ao processar a solicitação.", None)
        finally:
            conn.close()
    return (False, "Erro de conexão.", None)

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
        
        # [DEPURAÇÃO] "Tarefa aprovada" agora conta só TAREFAS DE VERDADE.
        # Antes contava também: leitura de comunicado, feedback diário, prêmios de meta
        # e as marcações "Não aplicável" (0 pontos), que o sistema grava como 'Aprovada'.
        ids_bonus = _ids_tarefas_bonus()
        filtro_bonus = ""
        params_bonus = []
        if ids_bonus:
            filtro_bonus = f" AND TarefaID NOT IN ({','.join('?' * len(ids_bonus))})"
            params_bonus = list(ids_bonus)
        filtro_tarefa_real = (
            " AND StatusValidacao = 'Aprovada'"
            " AND ISNULL(MotivoRecusa, '') NOT LIKE 'Não aplicável:%'"
            + filtro_bonus
        )

        # Total de tarefas aprovadas (usado por 'total_tarefas_aprovadas')
        sql_total_aprovadas = "SELECT COUNT(*) FROM Entregas WHERE FuncionarioID = ?" + filtro_tarefa_real
        cursor.execute(sql_total_aprovadas, [funcionario_id] + params_bonus)
        total_tarefas_aprovadas = cursor.fetchone()[0] or 0

        # Quantidade de tarefas aprovadas nos últimos 7 dias (usado por 'tarefas_aprovadas_periodo')
        # [DEPURAÇÃO] Antes contava DIAS diferentes (no máx. 10), não TAREFAS.
        sql_qtd_7_dias = ("SELECT COUNT(*) FROM Entregas WHERE FuncionarioID = ?" + filtro_tarefa_real +
                          " AND CONVERT(DATE, DataEnvio) >= DATEADD(day, -7, CONVERT(DATE, GETDATE()))")
        cursor.execute(sql_qtd_7_dias, [funcionario_id] + params_bonus)
        tarefas_ultimos_7_dias = cursor.fetchone()[0] or 0

        # Datas (sem repetir) das tarefas aprovadas, para 'sequencia_dias_tarefas'
        # [DEPURAÇÃO] Antes buscava só 10 datas: sequências maiores que 10 dias nunca eram alcançadas.
        sql_datas_aprovadas = ("SELECT DISTINCT TOP 400 CONVERT(DATE, DataEnvio) as Data FROM Entregas "
                               "WHERE FuncionarioID = ?" + filtro_tarefa_real + " ORDER BY Data DESC")
        cursor.execute(sql_datas_aprovadas, [funcionario_id] + params_bonus)
        datas_tarefas_aprovadas = [_get_date_part(row.Data) for row in cursor.fetchall()]

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
        # [DEPURAÇÃO] CONVERT(DATE...) + DISTINCT: se DataFeedback tiver hora, o mesmo dia
        # aparecia duas vezes e "quebrava" a sequência. TOP 400 permite sequências longas.
        sql_datas_feedback = """
            SELECT DISTINCT TOP 400 CONVERT(DATE, DataFeedback) as Data
            FROM Feedbacks
            WHERE FuncionarioID = ?
            ORDER BY Data DESC
        """
        cursor.execute(sql_datas_feedback, funcionario_id)
        datas_feedback = [_get_date_part(row.Data) for row in cursor.fetchall()]

        def _tem_sequencia(datas_desc, dias_necessarios):
            """True se as datas mais recentes formam 'dias_necessarios' dias seguidos."""
            if dias_necessarios <= 0:
                return False
            if len(datas_desc) < dias_necessarios:
                return False
            for i in range(dias_necessarios - 1):
                if (datas_desc[i] - datas_desc[i + 1]).days != 1:
                    return False
            return True

        # --- LOOP DE VERIFICAÇÃO ---
        for conquista in conquistas_a_verificar:
            atingiu_criterio = False
            # [DEPURAÇÃO] CriterioValor pode vir como texto/Decimal do banco. Antes,
            # range(texto) dava erro e NENHUMA conquista era concedida para ninguém.
            valor_criterio = _para_int(conquista.CriterioValor, -1)
            if valor_criterio < 0:
                logger.warning(f"Conquista ID {conquista.ConquistaID}: CriterioValor inválido ({conquista.CriterioValor}). Ignorada.")
                continue

            # --- CRITÉRIO 1: Total de Tarefas Aprovadas ---
            if conquista.CriterioTipo == 'total_tarefas_aprovadas':
                atingiu_criterio = total_tarefas_aprovadas >= valor_criterio

            # --- CRITÉRIO 2: Tarefas aprovadas nos últimos 7 dias ---
            elif conquista.CriterioTipo == 'tarefas_aprovadas_periodo':
                atingiu_criterio = tarefas_ultimos_7_dias >= valor_criterio

            # --- CRITÉRIO 3: Sequência de Dias com Tarefas ---
            elif conquista.CriterioTipo == 'sequencia_dias_tarefas':
                atingiu_criterio = _tem_sequencia(datas_tarefas_aprovadas, valor_criterio)

            # --- CRITÉRIO 4: Tarefas de Grupo Competitivo Aceitas ---
            elif conquista.CriterioTipo == 'tarefas_grupo_competitivo_aceitas':
                atingiu_criterio = total_grupo_competitivo_aprovadas >= valor_criterio

            # --- CRITÉRIO 5: Total de Comunicados Cientes ---
            elif conquista.CriterioTipo == 'total_comunicados_cientes':
                atingiu_criterio = total_comunicados_cientes >= valor_criterio

            # --- CRITÉRIO 6: Sequência de Dias com Feedback ---
            elif conquista.CriterioTipo == 'sequencia_feedback_diario':
                atingiu_criterio = _tem_sequencia(datas_feedback, valor_criterio)

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
                    # [DEPURAÇÃO] PontosBonus vazio (NULL) dava erro de comparação com None.
                    if (conquista.PontosBonus or 0) > 0:

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
                    OR (TA.TipoFrequencia = 'Semanal' AND TRY_CAST(TA.ValorFrequencia AS INT) = """ + SQL_DIA_SEMANA_HOJE + """)
                    OR (TA.TipoFrequencia = 'Mensal' AND TRY_CAST(TA.ValorFrequencia AS INT) = DATEPART(day, GETDATE()))
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

def _reverter_pontos_meta_diaria(apuracao_id, pontos_a_remover, meta_principal_id, cursor=None):
    """
    Função auxiliar interna para reverter pontos de meta diária.
    Remove o valor do saldo e exclui o registro de 'Entregas'.

    [DEPURAÇÃO]
    - Antes tirava os pontos de TODOS os funcionários que estão HOJE no setor, mesmo
      quem entrou depois e nunca recebeu o prêmio (saldo ficava errado/negativo).
      Agora tira exatamente de quem recebeu, olhando os registros do prêmio.
      (Se não houver registros vinculados, usa o método antigo por setor.)
    - Aceita 'cursor' para fazer parte da mesma transação de quem chamou.
    """
    conn = None
    usa_transacao_propria = cursor is None
    if usa_transacao_propria:
        conn = get_db_connection()
        if not conn:
            return False
        cursor = conn.cursor()

    try:
        tarefa_meta = _tarefa_id_meta()

        # 0. Método preciso: quem realmente recebeu pontos desta apuração?
        cursor.execute("""
            SELECT FuncionarioID, SUM(ISNULL(PontosGanhos, 0)) AS Total
            FROM Entregas
            WHERE TarefaID = ? AND AtribuicaoID = ?
            GROUP BY FuncionarioID
        """, tarefa_meta, apuracao_id)
        premiados = cursor.fetchall()

        if premiados:
            for premiado in premiados:
                adicionar_pontos_ao_saldo(premiado.FuncionarioID, -(premiado.Total or 0), cursor=cursor)
            cursor.execute("DELETE FROM Entregas WHERE TarefaID = ? AND AtribuicaoID = ?", tarefa_meta, apuracao_id)
            logger.info(f"Clawback: {len(premiados)} prêmio(s) da ApuracaoID {apuracao_id} revertido(s).")
            if usa_transacao_propria:
                conn.commit()
            return True

        # 1. (Método antigo) Buscar o setor alvo da meta principal associada
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
        params_del = [tarefa_meta, apuracao_id] + ids_funcionarios
        cursor.execute(sql_del_entregas, params_del)
        logger.info(f"Clawback: Registros de 'Entregas' (TarefaID {tarefa_meta}) vinculados ao ApuracaoID {apuracao_id} para o setor '{setor_alvo}' excluídos.")
        if usa_transacao_propria:
            conn.commit()
        return True

    except Exception as e:
        logger.error(f"ERRO CRÍTICO no clawback de pontos (ApuracaoID: {apuracao_id}): {e}", exc_info=True)
        if usa_transacao_propria:
            conn.rollback()
            return False
        raise  # Transação de quem chamou: avisa para ele desfazer tudo
    finally:
        if usa_transacao_propria and conn:
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
            # [DEPURAÇÃO] A reversão agora roda na MESMA transação da exclusão:
            # ou tudo acontece, ou nada acontece.
            if pontos_gerados > 0:
                logger.warning(f"Excluindo ApuracaoID {apuracao_id} que gerou {pontos_gerados} pontos. Iniciando Clawback...")
                if not _reverter_pontos_meta_diaria(apuracao_id, pontos_gerados, meta_principal_id, cursor=cursor):
                    # Se a reversão falhar, abortamos a exclusão
                    logger.error("Falha no Clawback. A exclusão da apuração foi ABORTADA.")
                    conn.rollback()
                    return False

            # 3. Excluir o registro de apuração
            sql_delete = "DELETE FROM MetasDiariasApuracoes WHERE ApuracaoID = ?"
            cursor.execute(sql_delete, apuracao_id)
            excluidas = cursor.rowcount  # [DEPURAÇÃO] Lido ANTES do commit (depois ele não é confiável)

            conn.commit()
            logger.info(f"ApuracaoID {apuracao_id} (Data: {data_apuracao}) excluída com sucesso.")
            return excluidas > 0

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
    # [DEPURAÇÃO] O ID vem do config.py (TAREFA_ID_PONTOS_META) em vez de 121 fixo.
    TAREFA_ID_META = _tarefa_id_meta()

    if not lista_funcionarios:
        return False
    conn = get_db_connection()
    if not conn:
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
            # [DEPURAÇÃO] Mesma transação (cursor=cursor): se algo falhar, nada fica pela metade.
            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_ganhos, cursor=cursor)

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
            # [DEPURAÇÃO] Dia da semana padronizado (1=Dom..7=Sáb), independente do idioma do SQL Server
            sql = """
                SELECT * FROM MetasDiariasModelos
                WHERE DiaSemanaID = """ + _sql_dia_semana("CAST(? AS DATE)") + """
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
    TAREFA_ID_META = _tarefa_id_meta()

    if not conn: return [] # Retorna lista vazia em caso de erro

    # [DEPURAÇÃO] O código abaixo usava a variável 'pontos_premio_diario', que NÃO
    # existe nesta função (NameError). A função SEMPRE falhava e ninguém era premiado.
    pontos_premio_diario = pontos_ganhos

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
        logger.info(f"Meta diária: premiando {len(funcionarios_do_setor)} funcionário(s) do setor '{setor}'.")

        # [DEPURAÇÃO] AtribuicaoID = apuracao_id vincula o prêmio à apuração,
        # permitindo estornar exatamente estes pontos se o lançamento for excluído.
        sql_entrega = """
            INSERT INTO Entregas (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa, AtribuicaoID)
            VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?, ?)
        """

        for funcionario in funcionarios_do_setor:
            # 1. Insere o registro de Entrega/Bônus (usa o cursor principal)
            cursor.execute(sql_entrega, TAREFA_ID_META, funcionario.FuncionarioID, pontos_premio_diario, motivo, apuracao_id)
            
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
        # Etapa 0: "Reserva" a meta, marcando como concluída DENTRO desta transação.
        # [DEPURAÇÃO] Antes a meta era marcada por OUTRA conexão (já gravada), antes de
        # terminar a distribuição. Se algo falhasse, a meta ficava "Concluida" sem ninguém
        # ser premiado. E dois cliques seguidos premiavam duas vezes. Agora só premia
        # quem conseguir mudar o status de 'Ativa' para 'Concluida'.
        cursor.execute("UPDATE MetasPrincipais SET Status = 'Concluida' WHERE MetaPrincipalID = ? AND Status = 'Ativa'", meta_id)
        if cursor.rowcount == 0:
            logger.warning(f"distribuir_premio_meta_principal: MetaID {meta_id} não está 'Ativa' (já premiada?).")
            conn.rollback()
            return []

        # Etapa 1: Buscar os detalhes da meta
        cursor.execute("SELECT PontosPremio, SetorAlvo FROM MetasPrincipais WHERE MetaPrincipalID = ?", meta_id)
        meta_detalhes = cursor.fetchone()
        if not meta_detalhes:
            conn.rollback()
            return []

        pontos_premio, setor_alvo = meta_detalhes

        # Etapa 2: Usar a função que já temos para buscar os funcionários
        funcionarios_do_setor = listar_funcionarios_por_setor(setor_alvo)
        if not funcionarios_do_setor:
            conn.rollback()  # Mantém a meta 'Ativa' para tentar de novo
            return []

        # Etapa 3: Distribuir os pontos (reutilizando a lógica da meta diária)
        TAREFA_ID_META = _tarefa_id_meta()
        sql_entrega = "INSERT INTO Entregas (TarefaID, FuncionarioID, StatusValidacao, PontosGanhos, DataEnvio, MotivoRecusa) VALUES (?, ?, 'Aprovada', ?, GETDATE(), ?)"
        motivo = f"Prêmio por atingir a META MENSAL do setor '{setor_alvo}'!"

        for funcionario in funcionarios_do_setor:
            cursor.execute(sql_entrega, TAREFA_ID_META, funcionario.FuncionarioID, pontos_premio, motivo)
            adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_premio, cursor=cursor)

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
# [DEPURAÇÃO] Aqui existia uma SEGUNDA função excluir_apuracao_diaria(), simples,
# que "apagava" a versão completa lá de cima (Python usa sempre a última definida).
# Resultado: ao excluir um lançamento pelo main.py, os pontos da meta NUNCA eram
# estornados. A cópia foi removida e agora vale a versão com estorno (clawback).

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
                    (SELECT ValorMeta FROM MetasDiariasModelos WHERE DiaSemanaID = """ + SQL_DIA_SEMANA_HOJE + """) as MetaDoDia,
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
            sql_find = "SELECT FuncionarioID, PontosGanhos, StatusValidacao FROM Entregas WHERE EntregaID = ?"
            cursor.execute(sql_find, entrega_id)
            entrega_dados = cursor.fetchone()

            if not entrega_dados:
                logger.warning(f"Tentativa de excluir EntregaID {entrega_id} que não foi encontrada.")
                return False # Entrega não existe

            funcionario_id, pontos_a_remover, status_entrega = entrega_dados
            # [DEPURAÇÃO] Só entregas APROVADAS colocaram pontos no saldo. Antes, excluir uma
            # entrega Pendente/Recusada que tinha PontosGanhos preenchido tirava pontos indevidamente.
            pontos_a_remover = (pontos_a_remover or 0) if status_entrega == 'Aprovada' else 0

            # 2. Excluir a entrega
            sql_delete = "DELETE FROM Entregas WHERE EntregaID = ?"
            cursor.execute(sql_delete, entrega_id)
            rows_affected = cursor.rowcount # Verifica se realmente excluiu algo

            # 3. Subtrair os pontos do saldo (APENAS se a exclusão foi bem-sucedida E havia pontos a remover)
            if rows_affected > 0 and pontos_a_remover != 0:
                 # [DEPURAÇÃO] cursor=cursor: o estorno faz parte da MESMA transação da exclusão.
                 # Antes era gravado por outra conexão; se a exclusão falhasse, o saldo já tinha caído.
                 adicionar_pontos_ao_saldo(funcionario_id, -pontos_a_remover, cursor=cursor)
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
            cursor.execute("SELECT FuncionarioID, PontosGanhos, StatusValidacao FROM Entregas WHERE EntregaID = ?", entrega_id)
            res = cursor.fetchone()
            if not res: return False
            funcionario_id, pontos_antigos, status_entrega = res
            pontos_antigos = pontos_antigos or 0 # Garante que não seja None

            # Atualiza os pontos na entrega
            sql_update = "UPDATE Entregas SET PontosGanhos = ? WHERE EntregaID = ?"
            cursor.execute(sql_update, novos_pontos, entrega_id)

            # Recalcula o saldo do funcionário (remove o antigo, adiciona o novo)
            # [DEPURAÇÃO] Só mexe no saldo se a entrega estiver APROVADA (as outras não
            # somaram pontos) e na MESMA transação (cursor=cursor).
            if status_entrega == 'Aprovada':
                diferenca = novos_pontos - pontos_antigos
                if diferenca:
                    adicionar_pontos_ao_saldo(funcionario_id, diferenca, cursor=cursor)

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
    Verifica se a meta diária foi atingida e premia a equipe DO SETOR CORRETO.
    Se um lançamento for corrigido para baixo, estorna o prêmio (clawback).

    [DEPURAÇÃO] Versão reescrita:
    - Antes, dois lançamentos quase simultâneos (desktop + Telegram) podiam premiar
      DUAS vezes. Agora a apuração é "reservada" com um UPDATE condicional: só quem
      conseguir marcar primeiro distribui os pontos.
    - O saldo era gravado por outra conexão, fora da transação. Se a gravação do
      histórico falhasse, o funcionário ficava com pontos sem registro. Agora é tudo
      uma única transação.
    - As mensagens do Telegram eram enviadas ANTES do commit (a pessoa podia ser
      parabenizada e o banco desfazer tudo). Agora são enviadas só depois.
    - O estorno e a zeragem da apuração também acontecem juntos.
    """
    try:
        modelo_meta_diaria = buscar_modelo_meta_para_data(data_apuracao_str)
        try:
            valor_dia_num = float(valor_dia or 0)
        except (TypeError, ValueError):
            valor_dia_num = 0.0

        meta_foi_batida = bool(
            modelo_meta_diaria
            and modelo_meta_diaria.ValorMeta is not None
            and (modelo_meta_diaria.PontosPremio or 0) > 0
            and valor_dia_num >= float(modelo_meta_diaria.ValorMeta)
        )

        conn = get_db_connection()
        if not conn:
            logger.error("verificar_e_premiar_meta_diaria: sem conexão com o banco.")
            return

        premiados_para_notificar = []
        pontos_premio_diario = 0
        try:
            cursor = conn.cursor()

            # Situação atual da apuração (com trava de leitura)
            cursor.execute(
                "SELECT ISNULL(PontosMetaDiariaGanhos, 0) FROM MetasDiariasApuracoes WITH (UPDLOCK) WHERE ApuracaoID = ?",
                apuracao_id
            )
            linha = cursor.fetchone()
            if not linha:
                logger.error(f"verificar_e_premiar_meta_diaria: ApuracaoID {apuracao_id} não encontrada.")
                conn.rollback()
                return
            pontos_ja_premiados = linha[0] or 0
            ja_premiada = pontos_ja_premiados > 0

            if meta_foi_batida and not ja_premiada:
                # Cenário 1: Meta batida, ainda não premiada
                cursor.execute("SELECT SetorAlvo FROM MetasPrincipais WHERE MetaPrincipalID = ?", meta_principal_id)
                meta_principal = cursor.fetchone()
                if not meta_principal or not meta_principal.SetorAlvo:
                    logger.warning("Meta diária atingida, mas falha ao identificar SetorAlvo.")
                    conn.rollback()
                    return

                setor_alvo_diario = meta_principal.SetorAlvo
                pontos_premio_diario = modelo_meta_diaria.PontosPremio

                # "Reserva" a premiação: só um processo consegue mudar de 0 para N
                cursor.execute("""
                    UPDATE MetasDiariasApuracoes SET PontosMetaDiariaGanhos = ?
                    WHERE ApuracaoID = ? AND ISNULL(PontosMetaDiariaGanhos, 0) = 0
                """, pontos_premio_diario, apuracao_id)
                if cursor.rowcount == 0:
                    logger.info(f"ApuracaoID {apuracao_id} já foi premiada por outro processo. Nada a fazer.")
                    conn.rollback()
                    return

                funcionarios_do_setor = listar_funcionarios_por_setor(setor_alvo_diario)
                logger.info(f"Meta diária ATINGIDA (ApuracaoID {apuracao_id}): {valor_dia_num} >= {modelo_meta_diaria.ValorMeta}. "
                            f"Distribuindo {pontos_premio_diario} pts para {len(funcionarios_do_setor)} funcionário(s) do setor '{setor_alvo_diario}'.")

                motivo_log = f"Meta Diária Atingida ({data_apuracao_str}) - Setor: {setor_alvo_diario}"
                for funcionario in funcionarios_do_setor:
                    adicionar_pontos_ao_saldo(funcionario.FuncionarioID, pontos_premio_diario, cursor=cursor)
                    registrar_pontos_de_bonus(
                        funcionario.FuncionarioID,
                        pontos_premio_diario,
                        motivo_log,
                        _tarefa_id_meta(),
                        vinculo_id=apuracao_id,
                        cursor=cursor
                    )
                    premiados_para_notificar.append(funcionario)

                conn.commit()

            elif not meta_foi_batida and ja_premiada:
                # Cenário 2: Clawback (Reversão) - o valor foi corrigido para baixo
                logger.warning(f"Meta diária NÃO ATINGIDA (ApuracaoID: {apuracao_id}). REVERTENDO {pontos_ja_premiados} pontos...")
                if _reverter_pontos_meta_diaria(apuracao_id, pontos_ja_premiados, meta_principal_id, cursor=cursor):
                    cursor.execute("UPDATE MetasDiariasApuracoes SET PontosMetaDiariaGanhos = 0 WHERE ApuracaoID = ?", apuracao_id)
                    conn.commit()
                    logger.info("Clawback concluído com sucesso.")
                else:
                    conn.rollback()
                    logger.error("Clawback falhou. Nenhuma alteração foi feita.")
            else:
                conn.rollback()  # Nada a mudar

        except Exception as e_proc:
            logger.error(f"Erro durante a premiação/estorno da meta diária (ApuracaoID {apuracao_id}): {e_proc}", exc_info=True)
            conn.rollback()
            premiados_para_notificar = []
        finally:
            conn.close()

        # Notificações SÓ depois que o banco confirmou tudo
        mensagens = getattr(config, 'MENSAGENS_META_DIARIA_CUMPRIDA', None) or ["🎉 Meta diária batida! Você ganhou {pontos} pontos!"]
        for funcionario in premiados_para_notificar:
            if getattr(funcionario, 'ChatIDTelegram', None):
                try:
                    mensagem_telegram = random.choice(mensagens).format(pontos=pontos_premio_diario)
                    notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem_telegram)
                except Exception as e_msg:
                    logger.error(f"Prêmio gravado, mas falhou ao avisar {getattr(funcionario, 'NomeCompleto', '?')}: {e_msg}")

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
# [DEPURAÇÃO] Esta linha aparecia duas vezes seguidas (abria 2 conexões à toa).

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

COLUNAS_ONBOARDING_PERMITIDAS = {
    'Escolaridade', 'EstadoCivil', 'DataCasamento', 'NomeConjugue', 'CPFConjugue',
    'QtdFilhos', 'DadosFilhos', 'RG_FileID', 'CPF_FileID', 'CTPS_FileID', 'TituloEleitor_FileID',
}

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
                # [DEPURAÇÃO] O nome da coluna entra direto no SQL. Só aceitamos colunas
                # conhecidas, para um erro de digitação (ou texto malicioso) nunca virar SQL.
                if campo not in COLUNAS_ONBOARDING_PERMITIDAS:
                    logger.error(f"atualizar_onboarding_etapa: coluna não permitida '{campo}'.")
                    return False
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
                # [DEPURAÇÃO] O notificador envia em modo HTML: os ** apareciam literalmente
                # na mensagem. Agora usa <b> e protege o nome (html.escape).
                mensagem_gestor = (
                    f"🟢 <b>NOVO ONBOARDING DE DOCUMENTOS CONCLUÍDO!</b> 🟢\n\n"
                    f"O funcionário <b>{html.escape(str(funcionario.NomeCompleto))}</b> finalizou o envio de todos os documentos e informações de registro.\n"
                    f"➡️ <b>Ação:</b> O funcionário foi liberado para fazer o exame admissional. Por favor, libere o acesso total após a aprovação no painel RH."
                )
                try:
                    notificador_telegram.enviar_mensagem(config.GESTOR_GROUP_CHAT_ID, mensagem_gestor)
                except Exception as e_notif:
                    # O cadastro JÁ foi concluído; falha no aviso não deve desfazer nada
                    logger.error(f"Onboarding concluído, mas falhou ao avisar o gestor: {e_notif}")

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
            ontem = (datetime.now() - timedelta(days=1)).date()
            data_ontem = ontem.strftime('%Y-%m-%d')

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

            # 3. [DEPURAÇÃO] Não exige feedback de um dia em que a pessoa NÃO trabalhou.
            # Antes, quem tinha folga na quarta ficava BLOQUEADO no bot na quinta; o mesmo
            # acontecia com quem voltava de férias/atestado.
            if verificar_status_disponibilidade(funcionario_id, ontem):
                return True  # Ontem foi folga, domingo de folga ou afastamento

            # 4. [DEPURAÇÃO] Funcionário recém-admitido (exame aprovado hoje ou ontem)
            # não tinha como ter dado feedback de ontem.
            try:
                cursor.execute("SELECT DataAdmissional FROM OnboardingStatus WHERE FuncionarioID = ?", funcionario_id)
                linha = cursor.fetchone()
                if linha and linha[0] and _get_date_part(linha[0]) >= ontem:
                    return True
            except Exception:
                pass  # Tabela/coluna ausente: segue a regra normal

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
def verificar_migracao_categorias_estoque():
    """Cria a tabela de Categorias e insere as categorias padrão se estiver vazia."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Cria a tabela se não existir
            sql_create = """
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CategoriasProduto')
                CREATE TABLE CategoriasProduto (
                    CategoriaID INT PRIMARY KEY IDENTITY(1,1),
                    NomeCategoria VARCHAR(100) UNIQUE NOT NULL
                )
            """
            cursor.execute(sql_create)
            
            # 2. Verifica se está vazia
            cursor.execute("SELECT COUNT(*) FROM CategoriasProduto")
            if cursor.fetchone()[0] == 0:
                logger.info("Tabela CategoriasProduto vazia. Inserindo categorias padrão...")
                categorias_padrao = ["Geral", "Sorvetes", "Brinquedos", "Embalagens", "Material de Limpeza", "Material de Escritório", "Mercado", "Distribuidoras", "Bebidas", "Insumos Produção", "Outros"]
                for cat in categorias_padrao:
                    cursor.execute("INSERT INTO CategoriasProduto (NomeCategoria) VALUES (?)", cat)
            
            conn.commit()
        except Exception as e:
            logger.error(f"Erro na migração de Categorias de Estoque: {e}")
        finally:
            conn.close()

# Executa imediatamente ao iniciar o módulo
verificar_migracao_categorias_estoque()

def listar_categorias_produto():
    """Retorna a lista de nomes de categorias em ordem alfabética."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT NomeCategoria FROM CategoriasProduto ORDER BY NomeCategoria")
            # Retorna uma lista simples de strings, ex: ['Bebidas', 'Brinquedos', ...]
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()
    return []

def criar_categoria_produto(nome_categoria):
    """Cria uma nova categoria no banco."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO CategoriasProduto (NomeCategoria) VALUES (?)", nome_categoria)
            conn.commit()
            return True, "Categoria criada com sucesso."
        except Exception as e:
            conn.rollback()
            # Erro 2627/2601 é violação de UNIQUE (nome repetido)
            if 'UNIQUE' in str(e).upper() or 'DUPLICATE' in str(e).upper():
                return False, "Já existe uma categoria com este exato nome."
            return False, f"Erro de banco de dados: {e}"
        finally:
            conn.close()
    return False, "Falha de conexão."

def atualizar_categoria_produto(nome_antigo, novo_nome):
    """
    Atualiza o nome da categoria na tabela de categorias e, 
    CRITICAMENTE, atualiza todos os produtos que usavam o nome antigo em cascata.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Atualiza na tabela de categorias
            cursor.execute("UPDATE CategoriasProduto SET NomeCategoria = ? WHERE NomeCategoria = ?", novo_nome, nome_antigo)
            
            # 2. Atualiza em cascata nos Produtos Mestre (pois a coluna Categoria lá é VARCHAR)
            cursor.execute("UPDATE ProdutosEstoque SET Categoria = ? WHERE Categoria = ?", novo_nome, nome_antigo)
            
            conn.commit()
            return True, "Categoria atualizada em todo o sistema."
        except Exception as e:
            conn.rollback()
            if 'UNIQUE' in str(e).upper():
                 return False, "Já existe outra categoria com este novo nome."
            return False, str(e)
        finally:
            conn.close()
    return False, "Falha de conexão."

def excluir_categoria_produto(nome_categoria):
    """
    Exclui uma categoria, MAS SÓ SE não houver nenhum produto usando ela.
    Não queremos produtos "órfãos" sem categoria no sistema.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Verifica se tem produto usando
            cursor.execute("SELECT COUNT(*) FROM ProdutosEstoque WHERE Categoria = ?", nome_categoria)
            qtd_uso = cursor.fetchone()[0]
            
            if qtd_uso > 0:
                return False, f"Não é possível excluir. Existem {qtd_uso} produto(s) usando esta categoria. Mude a categoria deles primeiro."
                
            # 2. Se não tem uso, pode apagar
            cursor.execute("DELETE FROM CategoriasProduto WHERE NomeCategoria = ?", nome_categoria)
            conn.commit()
            return True, "Categoria excluída com sucesso."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()
    return False, "Falha de conexão."

def criar_produto_estoque(nome, unidade, estoque_min, categoria='Geral'):
    """Insere um novo produto mestre na tabela ProdutosEstoque.
    RETORNA O ID do novo produto criado."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                INSERT INTO ProdutosEstoque (NomeProduto, UnidadeMedida, EstoqueMinimo, Categoria)
                VALUES (?, ?, ?, ?);
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql, nome, unidade, estoque_min, categoria)
            cursor.nextset()
            novo_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Novo produto mestre criado (ID: {novo_id}): {nome} - Categoria: {categoria}")
            return novo_id
        except Exception as e:
            logger.error(f"ERRO ao criar produto mestre: {e}", exc_info=True)
            if conn: conn.rollback()
            raise e 
        finally:
            if conn:
                conn.close()
    return None

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

def atualizar_produto_estoque(produto_id, nome, unidade, estoque_min, categoria='Geral'):
    """Atualiza um produto mestre existente na tabela ProdutosEstoque."""
    conn = get_db_connection()
    if not conn:  # [DEPURAÇÃO 2] antes devolvia None e a tela dizia "sucesso"
        raise Exception("Falha de conexão com o banco de dados.")
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE ProdutosEstoque
                SET NomeProduto = ?, UnidadeMedida = ?, EstoqueMinimo = ?, Categoria = ?
                WHERE ProdutoID = ?
            """
            cursor.execute(sql, nome, unidade, estoque_min, categoria, produto_id)
            conn.commit()
            logger.info(f"Produto mestre ID {produto_id} ({nome}) atualizado.")
        except Exception as e:
            logger.error(f"ERRO ao atualizar produto mestre ID {produto_id}: {e}", exc_info=True)
            raise e
        finally:
            if conn:
                conn.close()

class ProdutoComHistorico(ValueError):
    """O produto tem compras ou contagens: não pode ser apagado (a mensagem explica o que fazer)."""


def excluir_produto_estoque(produto_id):
    """
    Exclui um produto mestre da tabela ProdutosEstoque.
    [AUDITORIA ESTOQUE] Antes só apagava a linha do produto. Os vínculos com fornecedores
    ficavam "órfãos" (a próxima nota daquele item entrava num produto que não existe mais)
    e as rotinas/códigos do App de Compras apontavam para o nada.
    Agora:
      - produto com COMPRAS por nota ou que aparece em CONTAGENS não é apagado
        (levanta ProdutoComHistorico com a explicação; use "Juntar produtos");
      - sem histórico: apaga junto os vínculos, o custo manual (nota interna de quantidade 0)
        e as referências do App de Compras, tudo numa transação.
    """
    conn = get_db_connection()
    if not conn:  # [DEPURAÇÃO 2] antes devolvia None e a tela dizia "sucesso"
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM ItensNotaFiscalEntrada INI
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            WHERE PF.ProdutoID = ? AND INI.Quantidade > 0
        """, produto_id)
        compras = int(cursor.fetchone()[0] or 0)
        cursor.execute("SELECT COUNT(DISTINCT ContagemID) FROM ItensContagemEstoque WHERE ProdutoID = ?", produto_id)
        contagens = int(cursor.fetchone()[0] or 0)
        if compras or contagens:
            partes = [t for t in (f"{compras} compra(s) por nota fiscal" if compras else "",
                                  f"aparece em {contagens} contagem(ns)" if contagens else "") if t]
            raise ProdutoComHistorico(
                f"Este produto tem histórico: {' e '.join(partes)}.\n\n"
                "Apagar faria essas compras e contagens perderem o produto (o valor do estoque e a "
                "sugestão de compra ficariam errados).\n\n"
                "Se ele é um produto REPETIDO, selecione os dois no Catálogo (Ctrl + clique) e use "
                "'🔗 Juntar produtos duplicados'.")
        cursor.execute("SELECT ProdutoFornecedorID FROM ProdutosFornecedor WHERE ProdutoID = ?", produto_id)
        vinculos = [r[0] for r in cursor.fetchall()]
        if vinculos:
            marcas = ", ".join("?" for _ in vinculos)
            # custo manual: notas internas de quantidade 0 deste produto
            cursor.execute(f"SELECT DISTINCT NotaID FROM ItensNotaFiscalEntrada WHERE ProdutoFornecedorID IN ({marcas})", *vinculos)
            notas = [r[0] for r in cursor.fetchall()]
            cursor.execute(f"DELETE FROM ItensNotaFiscalEntrada WHERE ProdutoFornecedorID IN ({marcas})", *vinculos)
            for nota_id in notas:
                cursor.execute("SELECT COUNT(*) FROM ItensNotaFiscalEntrada WHERE NotaID = ?", nota_id)
                if not int(cursor.fetchone()[0] or 0):
                    cursor.execute("DELETE FROM NotasFiscaisEntrada WHERE NotaID = ? AND FornecedorID IN "
                                   "(SELECT FornecedorID FROM Fornecedores WHERE CNPJ = ?)", nota_id, CNPJ_FORNECEDOR_INTERNO)
            cursor.execute(f"DELETE FROM ProdutosFornecedor WHERE ProdutoFornecedorID IN ({marcas})", *vinculos)
        _trocar_produto_no_app_compras(cursor, [produto_id], None)
        cursor.execute("DELETE FROM ProdutosEstoque WHERE ProdutoID = ?", produto_id)
        conn.commit()
        logger.info(f"Produto mestre ID {produto_id} excluído ({len(vinculos)} vínculo(s) sem compras apagado(s)).")
    except ProdutoComHistorico:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"ERRO ao excluir produto mestre ID {produto_id}: {e}", exc_info=True)
        raise e # Lança o erro (provavelmente por restrição de chave estrangeira)
    finally:
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
    if not conn:  # [DEPURAÇÃO 2] antes devolvia None e a tela dizia "sucesso"
        raise Exception("Falha de conexão com o banco de dados.")
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
    if not conn:  # [DEPURAÇÃO 2] antes devolvia None e a tela dizia "sucesso"
        raise Exception("Falha de conexão com o banco de dados.")
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

def _ean_valido(ean):
    """EAN de verdade (8 a 14 dígitos). 'SEM GTIN', vazio, '0' etc. não servem para reconhecer produto."""
    digitos = ''.join(ch for ch in str(ean or '') if ch.isdigit())
    return digitos if 8 <= len(digitos) <= 14 and set(digitos) != {'0'} else None


def _codigo_valido(codigo):
    """Código do produto no fornecedor (cProd). Ignora vazios e códigos genéricos como '0'."""
    c = str(codigo or '').strip()
    return c if c and c.strip('0') else None


def buscar_vinculo_inteligente(fornecedor_id, descricao_xml, cprod=None, ean=None):
    """
    [MELHORIA] Reconhece o item da nota mesmo quando o fornecedor MUDA a descrição
    (ex: lote/validade no fim do nome). Antes o sistema só reconhecia pela descrição
    EXATA, e cada variação virava um "produto novo" para vincular de novo (vínculos
    duplicados). Ordem de busca, sempre dentro do MESMO fornecedor:
      1) descrição exata;  2) código do produto no fornecedor (cProd);  3) EAN.
    Só aceita 2) e 3) se todos os vínculos encontrados apontarem para o MESMO produto
    e com o MESMO fator (senão é ambíguo e o item vai para "pendentes", como antes).
    Devolve {'ProdutoFornecedorID', 'ProdutoID', 'Fator', 'Como'} ou None.
    """
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ProdutoFornecedorID, ProdutoID, FatorConversao FROM ProdutosFornecedor "
                       "WHERE FornecedorID = ? AND DescricaoXML = ?", fornecedor_id, descricao_xml)
        linha = cursor.fetchone()
        if linha:
            return {'ProdutoFornecedorID': linha[0], 'ProdutoID': linha[1], 'Fator': linha[2], 'Como': 'descricao'}

        tentativas = []
        codigo = _codigo_valido(cprod)
        if codigo:
            tentativas.append(('codigo', "CodigoFornecedor = ?", codigo))
        ean_ok = _ean_valido(ean)
        if ean_ok:
            tentativas.append(('ean', "EAN = ?", ean_ok))
        for como, condicao, valor in tentativas:
            cursor.execute(f"SELECT ProdutoFornecedorID, ProdutoID, FatorConversao FROM ProdutosFornecedor "
                           f"WHERE FornecedorID = ? AND ProdutoID IS NOT NULL AND {condicao}", fornecedor_id, valor)
            achados = cursor.fetchall()
            if not achados:
                continue
            produtos = {a[1] for a in achados}
            fatores = {_dec(a[2]) if a[2] is not None else Decimal('1') for a in achados}
            if len(produtos) == 1 and len(fatores) == 1:
                mais_novo = max(achados, key=lambda a: a[0])
                return {'ProdutoFornecedorID': mais_novo[0], 'ProdutoID': mais_novo[1], 'Fator': mais_novo[2], 'Como': como}
            logger.info(f"Item '{descricao_xml}': {como} '{valor}' aponta para produtos/fatores diferentes - fica pendente.")
        return None
    except Exception as e:
        logger.error(f"Erro no reconhecimento inteligente de '{descricao_xml}': {e}", exc_info=True)
        return None
    finally:
        conn.close()


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

_colunas_estoque_ok = False


def _garantir_colunas_estoque():
    """
    [DEPURAÇÃO 2] Acrescenta (uma vez, com COMMIT) duas colunas:
      - ItensNotaFiscalEntrada.FatorConversaoUsado: o Qtd/Cx usado NA IMPORTAÇÃO daquele item.
        Antes só existia o Qtd/Cx atual do vínculo: depois de juntar vínculos ou de trocar o
        Qtd/Cx "só para as próximas notas", recalcular as compras multiplicava itens que já
        estavam certos (ex: 120 UN viravam 1.440). Os itens antigos recebem o Qtd/Cx atual.
      - NotasFiscaisEntrada.ValorForaDoEstoque: valor dos itens da nota que NÃO entraram
        como compra paga (bonificação, comodato/remessa ignorados). Sem isso o "Ajustar
        notas antigas" achava que esse valor era ST/frete e o somava ao custo.
    """
    global _colunas_estoque_ok
    if _colunas_estoque_ok:
        return
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM ItensNotaFiscalEntrada WHERE 1 = 0")
        if 'fatorconversaousado' not in {d[0].lower() for d in (cur.description or [])}:
            cur.execute("ALTER TABLE ItensNotaFiscalEntrada ADD FatorConversaoUsado DECIMAL(18, 4) NULL")
            conn.commit()
            cur.execute("""
                UPDATE ItensNotaFiscalEntrada SET FatorConversaoUsado = (
                    SELECT PF.FatorConversao FROM ProdutosFornecedor PF
                    WHERE PF.ProdutoFornecedorID = ItensNotaFiscalEntrada.ProdutoFornecedorID)
                WHERE FatorConversaoUsado IS NULL
            """)
            logger.info("Coluna FatorConversaoUsado criada e preenchida com o Qtd/Cx atual dos vínculos.")
        cur.execute("SELECT * FROM NotasFiscaisEntrada WHERE 1 = 0")
        colunas_nf = {d[0].lower() for d in (cur.description or [])}
        if 'valorforadoestoque' not in colunas_nf:
            cur.execute("ALTER TABLE NotasFiscaisEntrada ADD ValorForaDoEstoque DECIMAL(18, 2) NULL")
        # [AUDITORIA ESTOQUE] série e chave de acesso: a mesma loja pode ter o MESMO número de nota
        # em séries diferentes (ex: cada caixa de supermercado tem a sua série)
        if 'serie' not in colunas_nf:
            cur.execute("ALTER TABLE NotasFiscaisEntrada ADD Serie VARCHAR(5) NULL")
        if 'chaveacesso' not in colunas_nf:
            cur.execute("ALTER TABLE NotasFiscaisEntrada ADD ChaveAcesso VARCHAR(44) NULL")
        # [NCM] o NCM (classificação fiscal) passa a ficar também no PRODUTO do estoque
        cur.execute("SELECT * FROM ProdutosEstoque WHERE 1 = 0")
        if 'ncm' not in {d[0].lower() for d in (cur.description or [])}:
            cur.execute("ALTER TABLE ProdutosEstoque ADD NCM VARCHAR(10) NULL")
            conn.commit()
            _preencher_ncm_dos_produtos(cur)
        conn.commit()
        _colunas_estoque_ok = True
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao criar colunas novas do estoque: {e}", exc_info=True)
        raise
    finally:
        conn.close()


def ncm_valido(ncm):
    """NCM com 8 números (o '00000000' de produto fantasma não conta). Senão None."""
    d = ''.join(ch for ch in str(ncm or '') if ch.isdigit())
    return d if len(d) == 8 and d != '00000000' else None


def _preencher_ncm_dos_produtos(cur):
    """[NCM] Uma vez: produto sem NCM recebe o NCM mais usado nos vínculos dele (vindo dos XMLs)."""
    cur.execute("SELECT ProdutoID, NCM FROM ProdutosFornecedor WHERE ProdutoID IS NOT NULL")
    contagem = {}
    for pid, ncm in cur.fetchall():
        ncm = ncm_valido(ncm)
        if ncm:
            contagem.setdefault(pid, {}).setdefault(ncm, 0)
            contagem[pid][ncm] += 1
    for pid, por_ncm in contagem.items():
        melhor = max(por_ncm.items(), key=lambda x: x[1])[0]
        cur.execute("UPDATE ProdutosEstoque SET NCM = ? WHERE ProdutoID = ? AND (NCM IS NULL OR NCM = '')", melhor, pid)
    logger.info(f"NCM preenchido em {len(contagem)} produto(s) a partir dos vínculos.")


def _guardar_ncm_dos_itens(cursor, itens):
    """[NCM] Ao salvar uma nota: o vínculo fica com o NCM do XML e o produto, se ainda não tinha, também."""
    for item in itens:
        ncm = ncm_valido(item.get('NCM'))
        if not ncm or not item.get('ProdutoFornecedorID'):
            continue
        cursor.execute("UPDATE ProdutosFornecedor SET NCM = ? WHERE ProdutoFornecedorID = ?", ncm, item['ProdutoFornecedorID'])
        cursor.execute("""UPDATE ProdutosEstoque SET NCM = ? WHERE (NCM IS NULL OR NCM = '') AND ProdutoID =
                          (SELECT ProdutoID FROM ProdutosFornecedor WHERE ProdutoFornecedorID = ?)""",
                       ncm, item['ProdutoFornecedorID'])


def _serie_normalizada(serie):
    """'001' -> '1' (a série vem com zeros na chave e sem zeros no XML). Vazio -> None."""
    texto = str(serie or '').strip()
    if not texto:
        return None
    return str(int(texto)) if texto.isdigit() else texto.upper()


def _chave_normalizada(chave):
    """Chave de acesso com 44 números (ou None)."""
    digitos = ''.join(ch for ch in str(chave or '') if ch.isdigit())
    return digitos if len(digitos) == 44 else None


def _nota_ja_salva(cursor, numero_nf, fornecedor_id, serie=None, chave=None):
    """
    [AUDITORIA ESTOQUE] NotaID da nota já salva, ou None. Antes a nota era reconhecida só pelo
    NÚMERO + fornecedor: a nota nº 559129 da série 7 era tratada como a nº 559129 da série 2 e
    nunca entrava no estoque ("já importada"), e o recálculo de custos podia usar o XML de uma
    nota na outra. Agora, quando as duas notas têm série/chave, elas precisam bater.
    Notas antigas (salvas sem série) continuam valendo como "já importada" (por segurança).
    """
    serie, chave = _serie_normalizada(serie), _chave_normalizada(chave)
    try:
        _garantir_colunas_estoque()
    except Exception as e:
        logger.warning(f"Colunas de série/chave indisponíveis, comparando só o número da nota: {e}")
        cursor.execute("SELECT NotaID FROM NotasFiscaisEntrada WHERE NumeroNF = ? AND FornecedorID = ?",
                       str(numero_nf), fornecedor_id)
        linha = cursor.fetchone()
        return linha[0] if linha else None
    if chave:
        cursor.execute("SELECT NotaID FROM NotasFiscaisEntrada WHERE ChaveAcesso = ?", chave)
        linha = cursor.fetchone()
        if linha:
            return linha[0]
    cursor.execute("SELECT NotaID, Serie, ChaveAcesso FROM NotasFiscaisEntrada WHERE NumeroNF = ? AND FornecedorID = ?",
                   str(numero_nf), fornecedor_id)
    for nota_id, serie_db, chave_db in cursor.fetchall():
        chave_db = _chave_normalizada(chave_db)
        if chave and chave_db and chave_db != chave:
            continue                      # chaves diferentes: são notas diferentes
        serie_db = _serie_normalizada(serie_db)
        if serie and serie_db and serie_db != serie:
            continue                      # séries diferentes: são notas diferentes
        return nota_id
    return None


def _fator_item(fator_usado, fator_vinculo):
    """Qtd/Cx de um item de nota: o usado na importação; se não houver, o atual do vínculo."""
    for f in (fator_usado, fator_vinculo):
        if f is not None and _dec(f) > 0:
            return _dec(f)
    return Decimal('1')


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
    serie = _serie_normalizada(dados_nf_cabecalho.get('Serie'))
    chave = _chave_normalizada(dados_nf_cabecalho.get('ChaveAcesso'))
    try:
        _garantir_colunas_estoque()
    except Exception as e:
        conn.close()
        return False, f"Não foi possível preparar o banco: {e}"

    try:
        cursor = conn.cursor()
        # [AUDITORIA ESTOQUE] confere número + série + chave (antes: só número + fornecedor)
        if _nota_ja_salva(cursor, numero_nf, fornecedor_id, serie, chave):
            return False, f"Nota Fiscal {numero_nf} já foi importada anteriormente para este fornecedor."

        # 1. Inserir o Cabeçalho da NF
        sql_nf = """
            INSERT INTO NotasFiscaisEntrada (NumeroNF, FornecedorID, DataEmissao, ValorTotalNF, ValorForaDoEstoque,
                                             Serie, ChaveAcesso)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            SELECT SCOPE_IDENTITY();
        """
        cursor.execute(sql_nf, 
                    dados_nf_cabecalho['NumeroNF'], 
                    dados_nf_cabecalho['FornecedorID'], 
                    dados_nf_cabecalho['DataEmissao'], 
                    dados_nf_cabecalho['ValorTotalNF'],
                    dados_nf_cabecalho.get('ValorForaDoEstoque') or Decimal('0'),
                    serie, chave)

        cursor.nextset()
        nova_nota_id = cursor.fetchone()[0]
        
        if not nova_nota_id:
            raise Exception("Falha ao obter o ID da nova Nota Fiscal.")
            
        # 2. Inserir os Itens da NF
        sql_item = """
            INSERT INTO ItensNotaFiscalEntrada (NotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario, FatorConversaoUsado)
            VALUES (?, ?, ?, ?, ?)
        """
        # Prepara os dados para executemany (mais rápido)
        itens_para_inserir = [
            (nova_nota_id, item['ProdutoFornecedorID'], item['Quantidade'], item['PrecoCustoUnitario'],
             item.get('FatorUsado'))
            for item in lista_itens_nf
        ]
        
        cursor.executemany(sql_item, itens_para_inserir)
        _guardar_ncm_dos_itens(cursor, lista_itens_nf)   # [NCM]

        # 3. Se tudo deu certo, commita a transação
        conn.commit()
        dados_nf_cabecalho['NotaID'] = int(nova_nota_id)   # [ALERTA PREÇO] quem salvou sabe qual nota conferir
        logger.info(f"Nota Fiscal {dados_nf_cabecalho['NumeroNF']} (ID: {nova_nota_id}) e seus {len(itens_para_inserir)} itens foram salvos com sucesso.")
        return True, f"Nota Fiscal {dados_nf_cabecalho['NumeroNF']} salva com sucesso."

    except Exception as e:
        if conn: conn.rollback() # Desfaz tudo em caso de erro
        logger.error(f"ERRO CRÍTICO ao salvar NF completa (NF: {dados_nf_cabecalho.get('NumeroNF', 'N/A')}): {e}", exc_info=True)
        return False, f"Erro ao salvar NF: {e}"
    finally:
        if conn:
            conn.close()


# ==============================================================================
# == [ALERTA PREÇO] Aumento de preço em relação à compra anterior ==============
# ==============================================================================
LIMITE_AUMENTO_PRECO_PCT = Decimal('10')   # avisa a partir de 10% de aumento


def aumentos_de_preco(nota_ids=None, desde_nota_id=None, desde_data=None, limite_pct=None):
    """
    Compras cujo custo (por unidade do ESTOQUE, já convertido pelo fator) subiu em relação
    à compra PAGA anterior do mesmo produto (de qualquer fornecedor).
    Filtra as compras conferidas por: nota_ids (lista), desde_nota_id (NotaID maior que) ou
    desde_data (emitidas a partir de). Bonificação (custo 0) e o fornecedor interno
    (custo manual) ficam de fora. Um produto aparece uma vez por nota.
    Devolve uma lista de dicts, do maior aumento para o menor.
    """
    limite = Decimal(str(limite_pct)) if limite_pct is not None else LIMITE_AUMENTO_PRECO_PCT
    desde_data = _como_data(desde_data)
    nota_ids = {int(n) for n in nota_ids} if nota_ids is not None else None
    if nota_ids is not None and not nota_ids:
        return []
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT PF.ProdutoID, P.NomeProduto, P.UnidadeMedida, NF.DataEmissao, NF.NotaID, INI.ItemNotaID,
                   INI.PrecoCustoUnitario, F.NomeFantasia, NF.NumeroNF, F.CNPJ, INI.Quantidade
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
            JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        """)
        linhas = cursor.fetchall()
    finally:
        conn.close()

    por_produto = {}
    for pid, nome, un, dt, nota_id, item_id, custo, forn, num_nf, cnpj, qtd in linhas:
        custo = _dec(custo)
        if (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO or custo <= 0 or _dec(qtd) <= 0:
            continue
        por_produto.setdefault(pid, []).append({
            'data': _como_data(dt), 'nota_id': int(nota_id), 'item_id': int(item_id or 0), 'custo': custo,
            'fornecedor': forn or '', 'numero_nf': str(num_nf or ''), 'nome': nome or f'Produto {pid}',
            'unidade': (un or 'UN').strip() or 'UN'})

    def alvo(c):
        if nota_ids is not None and c['nota_id'] not in nota_ids:
            return False
        if desde_nota_id is not None and c['nota_id'] <= int(desde_nota_id):
            return False
        if desde_data and (not c['data'] or c['data'] < desde_data):
            return False
        return True

    achados = {}
    for pid, compras in por_produto.items():
        compras.sort(key=lambda c: (c['data'] or date.min, c['nota_id'], c['item_id']))
        for k, c in enumerate(compras):
            if not alvo(c):
                continue
            anterior = next((a for a in reversed(compras[:k]) if a['nota_id'] != c['nota_id']), None)
            if not anterior:
                continue
            pct = (c['custo'] / anterior['custo'] - 1) * 100
            if pct < limite:
                continue
            chave = (c['nota_id'], pid)
            if chave in achados and achados[chave]['pct'] >= pct:
                continue
            achados[chave] = {
                'produto_id': pid, 'produto': c['nome'], 'unidade': c['unidade'],
                'custo': c['custo'], 'data': c['data'], 'fornecedor': c['fornecedor'],
                'nota_id': c['nota_id'], 'numero_nf': c['numero_nf'],
                'custo_anterior': anterior['custo'], 'data_anterior': anterior['data'],
                'fornecedor_anterior': anterior['fornecedor'], 'pct': pct.quantize(Decimal('0.1'))}
    return sorted(achados.values(), key=lambda a: (-a['pct'], a['produto']))


def chaves_ja_importadas(chaves):
    """[XML SEFAZ] Quais destas chaves de acesso já viraram nota de entrada no estoque."""
    chaves = [c for c in {str(c) for c in chaves} if len(c) == 44 and c.isdigit()]
    if not chaves:
        return set()
    _garantir_colunas_estoque()
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        achadas = set()
        for i in range(0, len(chaves), 500):
            parte = chaves[i:i + 500]
            cursor.execute(f"SELECT ChaveAcesso FROM NotasFiscaisEntrada WHERE ChaveAcesso IN ({','.join('?' * len(parte))})", parte)
            achadas |= {r[0] for r in cursor.fetchall()}
        return achadas
    finally:
        conn.close()


def notas_ja_lancadas(notas):
    """
    [XML SEFAZ] Quais destas notas já estão no estoque. notas = [(chave, cnpj, numero, serie)].
    Confere pela chave e também pelo CNPJ (só os números) + número da nota (sem zeros à esquerda),
    para achar as notas lançadas ANTES (sem chave gravada), mesmo se o fornecedor estiver
    cadastrado duas vezes ou com o CNPJ escrito com pontos. Série diferente = nota diferente.
    Devolve o conjunto das CHAVES já lançadas.
    """
    def so_digitos(t):
        return ''.join(ch for ch in str(t or '') if ch.isdigit())

    def numero(t):
        d = so_digitos(t)
        return str(int(d)) if d else str(t or '').strip()

    if not notas:
        return set()
    try:
        _garantir_colunas_estoque()
        com_serie = True
    except Exception:
        com_serie = False
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        if com_serie:
            cursor.execute("""SELECT NF.NumeroNF, NF.Serie, NF.ChaveAcesso, F.CNPJ FROM NotasFiscaisEntrada NF
                              LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID""")
            linhas = cursor.fetchall()
        else:
            cursor.execute("""SELECT NF.NumeroNF, NULL, NULL, F.CNPJ FROM NotasFiscaisEntrada NF
                              LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID""")
            linhas = cursor.fetchall()
    finally:
        conn.close()
    por_chave = set()
    por_numero = {}
    for num, serie, chave, cnpj in linhas:
        ch = _chave_normalizada(chave)
        if ch:
            por_chave.add(ch)
        por_numero.setdefault((so_digitos(cnpj), numero(num)), []).append((_serie_normalizada(serie), ch))
    lancadas = set()
    for chave, cnpj, num, serie in notas:
        ch, serie = _chave_normalizada(chave), _serie_normalizada(serie)
        if ch and ch in por_chave:
            lancadas.add(chave)
            continue
        for serie_db, chave_db in por_numero.get((so_digitos(cnpj), numero(num)), []):
            if ch and chave_db and chave_db != ch:
                continue
            if serie and serie_db and serie_db != serie:
                continue
            lancadas.add(chave)
            break
    return lancadas


def texto_aumento_preco(a):
    """'Leite condensado subiu 18% (R$ 5,00 → R$ 5,90/UN; antes em 12/09, Atacadão)'."""
    def reais(v):
        return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    antes = a['data_anterior'].strftime('%d/%m') if a.get('data_anterior') else '?'
    pct = f"{a['pct']:.0f}" if a['pct'] >= 10 else f"{a['pct']:.1f}".replace('.', ',')
    return (f"{a['produto']} subiu {pct}% ({reais(a['custo_anterior'])} → {reais(a['custo'])}/{a['unidade']}; "
            f"antes em {antes}, {a['fornecedor_anterior']})")


# ==============================================================================
# == [GRÁFICO PRODUTO] Linha do tempo de um produto ============================
# ==============================================================================
def _somar_por_mes(inicio, fim, quantidade, por_mes):
    """Reparte 'quantidade' (gasta entre inicio e fim) pelos meses, proporcional aos dias."""
    dias = (fim - inicio).days
    if dias <= 0:
        return
    por_dia = quantidade / dias
    d = inicio
    while d < fim:
        prox_mes = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        ate = min(prox_mes, fim)
        chave = (d.year, d.month)
        por_mes[chave] = por_mes.get(chave, Decimal('0')) + por_dia * (ate - d).days
        d = ate


def historico_grafico_produto(produto_id, meses=12, hoje=None):
    """
    Dados para o gráfico de um produto nos últimos 'meses':
      compras:   [{'data', 'custo' (por unidade do estoque), 'qtd', 'fornecedor', 'bonificacao'}]
      contagens: [{'data', 'qtd'}]   (contagens do mesmo dia somadas)
      meses:     [{'mes': date(ano, mes, 1), 'comprado', 'consumido' (None = sem contagens para calcular)}]
    O consumo vem das contagens: contado antes + comprado no meio − contado depois,
    repartido pelos dias entre as duas contagens.
    """
    hoje = _como_data(hoje) or date.today()
    inicio = (hoje.replace(day=1) - timedelta(days=31 * (int(meses) - 1))).replace(day=1)
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT NomeProduto, UnidadeMedida, EstoqueMinimo FROM ProdutosEstoque WHERE ProdutoID = ?", (int(produto_id),))
        p = cur.fetchone()
        if not p:
            raise ValueError("Produto não encontrado.")
        cur.execute("""
            SELECT NF.DataEmissao, INI.Quantidade, INI.PrecoCustoUnitario, F.NomeFantasia, F.CNPJ
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
            WHERE PF.ProdutoID = ?
        """, (int(produto_id),))
        compras_todas = []
        for dt, qtd, custo, forn, cnpj in cur.fetchall():
            dt, qtd = _como_data(dt), _dec(qtd)
            if not dt or qtd <= 0 or (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO:
                continue
            compras_todas.append({'data': dt, 'qtd': qtd, 'custo': _dec(custo), 'fornecedor': forn or 'Sem nome',
                                  'bonificacao': _dec(custo) <= 0})
        cur.execute("""SELECT C.DataContagem, I.QuantidadeContada FROM ItensContagemEstoque I
                       JOIN ContagensEstoque C ON I.ContagemID = C.ContagemID WHERE I.ProdutoID = ?""", (int(produto_id),))
        por_dia = {}
        for dt, qtd in cur.fetchall():
            dt = _como_data(dt)
            if dt:
                por_dia[dt] = por_dia.get(dt, Decimal('0')) + _dec(qtd)
    finally:
        conn.close()

    compras_todas.sort(key=lambda c: c['data'])
    contagens = [{'data': d, 'qtd': q} for d, q in sorted(por_dia.items())]

    comprado, consumido = {}, {}
    for c in compras_todas:
        if c['data'] >= inicio:
            chave = (c['data'].year, c['data'].month)
            comprado[chave] = comprado.get(chave, Decimal('0')) + c['qtd']
    for a, b in zip(contagens, contagens[1:]):
        if b['data'] < inicio:
            continue
        entrou = sum((c['qtd'] for c in compras_todas if a['data'] < c['data'] <= b['data']), Decimal('0'))
        gasto = a['qtd'] + entrou - b['qtd']
        if gasto >= 0:            # conta que não fecha (nota faltando, contagem errada) fica de fora
            _somar_por_mes(max(a['data'], inicio), b['data'], gasto * Decimal((b['data'] - max(a['data'], inicio)).days)
                           / Decimal((b['data'] - a['data']).days), consumido)

    lista_meses, d = [], inicio
    while d <= hoje:
        chave = (d.year, d.month)
        lista_meses.append({'mes': d, 'comprado': comprado.get(chave, Decimal('0')), 'consumido': consumido.get(chave)})
        d = (d + timedelta(days=32)).replace(day=1)
    return {'produto_id': int(produto_id), 'produto': p[0], 'unidade': (p[1] or 'UN').strip() or 'UN',
            'estoque_minimo': _dec(p[2]), 'inicio': inicio,
            'compras': [c for c in compras_todas if c['data'] >= inicio],
            'contagens': [c for c in contagens if c['data'] >= inicio], 'meses': lista_meses}


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
            

def verificar_migracao_itens_avulsos():
    """Garante que a tabela suporte itens órfãos (sem ProdutoID)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT NomeAvulso FROM ItensContagemEstoque WHERE 1=0")
            except Exception:
                logger.info("Executando migração para suportar Itens Avulsos na contagem...")
                cursor.execute("ALTER TABLE ItensContagemEstoque ALTER COLUMN ProdutoID INT NULL")
                cursor.execute("ALTER TABLE ItensContagemEstoque ADD NomeAvulso VARCHAR(255) NULL")
                cursor.execute("ALTER TABLE ItensContagemEstoque ADD EANAvulso VARCHAR(50) NULL")
                conn.commit()
                logger.info("Migração de Itens Avulsos concluída com sucesso.")
        except Exception as e:
            logger.error(f"Erro na migração de avulsos: {e}")
        finally:
            conn.close()

verificar_migracao_itens_avulsos()

def salvar_contagem_estoque(data_contagem, funcionario_id, lista_itens_contados, nome_contagem="Geral"):
    """Salva uma nova contagem de estoque com suporte a itens avulsos."""
    conn = get_db_connection()
    if not conn: return False, "Falha de conexão com o banco."
    try:
        cursor = conn.cursor()
        sql_contagem = """
            INSERT INTO ContagensEstoque (DataContagem, FuncionarioID, NomeContagem)
            OUTPUT INSERTED.ContagemID VALUES (?, ?, ?)
        """
        cursor.execute(sql_contagem, data_contagem, funcionario_id, nome_contagem)
        nova_contagem_id = cursor.fetchone()[0]
        
        # INSERÇÃO HÍBRIDA: Aceita ProdutoID ou NomeAvulso
        sql_item = """
            INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada, NomeAvulso, EANAvulso)
            VALUES (?, ?, ?, ?, ?)
        """
        itens_para_inserir = [
            (
                nova_contagem_id, 
                item.get('ProdutoID'), 
                item.get('QuantidadeContada', 0),
                item.get('NomeAvulso'),
                item.get('EANAvulso')
            ) for item in lista_itens_contados
        ]
        
        cursor.executemany(sql_item, itens_para_inserir)
        conn.commit()
        return True, f"Contagem salva com sucesso ({len(itens_para_inserir)} itens)."
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"ERRO CRÍTICO ao salvar contagem de estoque: {e}", exc_info=True)
        return False, f"Erro ao salvar contagem: {e}"
    finally:
        if conn: conn.close()

def listar_contagens_cabecalho():
    """Lista os cabeçalhos das contagens de estoque já realizadas."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT C.ContagemID, C.DataContagem, ISNULL(F.NomeCompleto, '(sem responsável)') AS NomeCompleto, C.NomeContagem
                FROM ContagensEstoque C
                LEFT JOIN Funcionarios F ON C.FuncionarioID = F.FuncionarioID
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
    """Busca itens, mesclando os oficiais com os avulsos (LEFT JOIN)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    ISNULL(P.NomeProduto, IC.NomeAvulso + ' [AVULSO]') as NomeProduto, 
                    IC.QuantidadeContada, 
                    ISNULL(P.UnidadeMedida, 'UN') as UnidadeMedida,
                    IC.ProdutoID,
                    IC.NomeAvulso,
                    IC.EANAvulso
                FROM ItensContagemEstoque IC
                LEFT JOIN ProdutosEstoque P ON IC.ProdutoID = P.ProdutoID
                WHERE IC.ContagemID = ?
                ORDER BY NomeProduto
            """
            cursor.execute(sql, contagem_id)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"ERRO ao buscar itens da contagem ID {contagem_id}: {e}", exc_info=True)
            return []
        finally:
            if conn: conn.close()
    return []

def consolidar_contagens(ids_contagens, data_contagem, funcionario_id, nome_contagem):
    """
    [DEPURAÇÃO 2] Junta várias contagens numa só (somando produtos iguais e avulsos iguais)
    e apaga as originais — TUDO numa transação. Antes eram passos separados: uma falha no
    meio deixava a consolidada E as originais (estoque em dobro). Mantém o EAN dos avulsos.
    Recusa contagens com valor FECHADO. Devolve (sucesso, mensagem, novo_id).
    """
    ids = [int(i) for i in ids_contagens]
    if len(ids) < 2:
        return False, "Selecione pelo menos duas contagens.", None
    try:
        fechadas = set(listar_valores_estoque_fechados(levantar_erro=True))
    except Exception as e:
        return False, f"Não foi possível consultar o banco: {e}", None
    if fechadas & set(ids):
        return False, "Há contagem com o valor do estoque FECHADO na seleção (reabra antes).", None
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados.", None
    try:
        cursor = conn.cursor()
        marcas = ", ".join("?" for _ in ids)
        cursor.execute(f"SELECT ProdutoID, NomeAvulso, EANAvulso, QuantidadeContada FROM ItensContagemEstoque "
                       f"WHERE ContagemID IN ({marcas})", *ids)
        agrupado = {}
        for pid, avulso, ean, qtd in cursor.fetchall():
            chave = ('P', pid) if pid is not None else ('A', (avulso or '').strip().upper())
            atual = agrupado.setdefault(chave, {'ProdutoID': pid, 'NomeAvulso': avulso, 'EANAvulso': ean, 'Qtd': Decimal('0')})
            atual['Qtd'] += _dec(qtd)
            if not atual['EANAvulso'] and ean:
                atual['EANAvulso'] = ean
        cursor.execute("INSERT INTO ContagensEstoque (DataContagem, FuncionarioID, NomeContagem) "
                       "OUTPUT INSERTED.ContagemID VALUES (?, ?, ?)", data_contagem, funcionario_id, nome_contagem)
        novo_id = cursor.fetchone()[0]
        for it in agrupado.values():
            cursor.execute("INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada, NomeAvulso, EANAvulso) "
                           "VALUES (?, ?, ?, ?, ?)", novo_id, it['ProdutoID'], it['Qtd'],
                           it['NomeAvulso'] if it['ProdutoID'] is None else None,
                           it['EANAvulso'] if it['ProdutoID'] is None else None)
        cursor.execute(f"DELETE FROM ItensContagemEstoque WHERE ContagemID IN ({marcas})", *ids)
        cursor.execute(f"DELETE FROM ContagensEstoque WHERE ContagemID IN ({marcas})", *ids)
        conn.commit()
        logger.info(f"Contagens {ids} consolidadas na contagem {novo_id} ({len(agrupado)} itens).")
        return True, f"{len(ids)} contagens consolidadas ({len(agrupado)} itens).", novo_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao consolidar contagens {ids}: {e}", exc_info=True)
        return False, f"Erro ao consolidar (nada foi alterado): {e}", None
    finally:
        conn.close()


def excluir_contagem_estoque(contagem_id):
    """Exclui uma Contagem de Estoque e seus itens."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # [MELHORIA] Apaga também o "valor fechado" desta contagem (se existir)
            _garantir_tabelas_valor_estoque(cursor)
            cursor.execute("DELETE FROM ValorEstoqueFechamentoItens WHERE ContagemID = ?", contagem_id)
            cursor.execute("DELETE FROM ValorEstoqueFechamento WHERE ContagemID = ?", contagem_id)
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

def listar_itens_avulsos_pendentes():
    """Busca todos os itens contados que ainda não têm Produto Mestre associado."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT IC.ContagemID, C.DataContagem, IC.NomeAvulso, IC.QuantidadeContada, IC.EANAvulso
                FROM ItensContagemEstoque IC
                JOIN ContagensEstoque C ON IC.ContagemID = C.ContagemID
                WHERE IC.ProdutoID IS NULL
                ORDER BY C.DataContagem DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()
    return []

def vincular_item_avulso_contagem(contagem_id, nome_avulso, produto_id_mestre):
    """
    Resolve um item avulso na contagem. Se o mestre já estiver na mesma contagem,
    soma as quantidades. Se não, apenas substitui o ID.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT QuantidadeContada FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?", contagem_id, produto_id_mestre)
            existente = cursor.fetchone()
            
            cursor.execute("SELECT QuantidadeContada FROM ItensContagemEstoque WHERE ContagemID = ? AND NomeAvulso = ?", contagem_id, nome_avulso)
            avulso = cursor.fetchone()
            qtd_avulso = avulso.QuantidadeContada if avulso else 0
            
            if existente:
                cursor.execute("UPDATE ItensContagemEstoque SET QuantidadeContada = QuantidadeContada + ? WHERE ContagemID = ? AND ProdutoID = ?", qtd_avulso, contagem_id, produto_id_mestre)
                cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND NomeAvulso = ?", contagem_id, nome_avulso)
            else:
                cursor.execute("UPDATE ItensContagemEstoque SET ProdutoID = ?, NomeAvulso = NULL, EANAvulso = NULL WHERE ContagemID = ? AND NomeAvulso = ?", produto_id_mestre, contagem_id, nome_avulso)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao vincular avulso: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def _resolver_avulso_na_contagem(cursor, contagem_id, nome_avulso, produto_id, qtd):
    """
    [AUDITORIA ESTOQUE] Troca o item avulso da contagem pelo produto, deixando UMA linha só.
    Antes: se o avulso estava em 2 linhas (ex: bipado 2x no celular), as DUAS recebiam o
    produto com a quantidade digitada (o estoque dobrava); e se o produto já estava em 2
    linhas, a quantidade era somada nas duas.
    Resultado: produto = (o que já havia do produto nesta contagem) + qtd.
    """
    cursor.execute("SELECT QuantidadeContada FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?",
                   contagem_id, produto_id)
    ja_tinha = sum((_dec(r[0]) for r in cursor.fetchall()), Decimal('0'))
    cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?", contagem_id, produto_id)
    cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID IS NULL AND NomeAvulso = ?",
                   contagem_id, nome_avulso)
    cursor.execute("INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada, NomeAvulso, EANAvulso) "
                   "VALUES (?, ?, ?, NULL, NULL)", contagem_id, produto_id, ja_tinha + _dec(qtd))


def contagens_do_dia_por_produto(data_contagem, produto_ids, ignorar_ids=()):
    """
    [AUDITORIA ESTOQUE] Produtos que JÁ foram contados nesta data em outras contagens:
    {ProdutoID: {'qtd': Decimal, 'contagens': ['ID 12 - App compras: Sorvetes', ...]}}.
    A Sugestão de Compra SOMA as contagens do mesmo dia (contar por área: freezer + depósito);
    uma RECONTAGEM salva como contagem nova deixaria o estoque em dobro.
    """
    ids = [int(p) for p in produto_ids if p is not None]
    data = _como_data(data_contagem)
    if not ids or not data:
        return {}
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ContagemID, DataContagem, NomeContagem FROM ContagensEstoque")
        ignorar = {int(i) for i in ignorar_ids}
        do_dia = {cid: (nome or 'Geral') for cid, dt, nome in cursor.fetchall()
                  if _como_data(dt) == data and cid not in ignorar}
        if not do_dia:
            return {}
        resultado = {}
        marcas_c = ", ".join("?" for _ in do_dia)
        for inicio in range(0, len(ids), 500):          # limite de parâmetros do SQL Server
            parte = ids[inicio:inicio + 500]
            marcas_p = ", ".join("?" for _ in parte)
            cursor.execute(f"SELECT ContagemID, ProdutoID, QuantidadeContada FROM ItensContagemEstoque "
                           f"WHERE ContagemID IN ({marcas_c}) AND ProdutoID IN ({marcas_p})", *list(do_dia), *parte)
            for cid, pid, qtd in cursor.fetchall():
                r = resultado.setdefault(pid, {'qtd': Decimal('0'), 'contagens': []})
                r['qtd'] += _dec(qtd)
                rotulo = f"ID {cid} - {do_dia[cid]}"
                if rotulo not in r['contagens']:
                    r['contagens'].append(rotulo)
        return resultado
    finally:
        conn.close()


def vincular_item_avulso_inteligente(contagem_id, nome_avulso, produto_id_mestre, nova_qtd, ean, salvar_permanente):
    """
    Substitui o avulso na contagem aplicando a quantidade corrigida.
    Se 'salvar_permanente' for True, herda os dados do fornecedor do Mestre
    e cria um vínculo definitivo para este novo EAN.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # 1. TRATA A CONTAGEM FÍSICA (Aplica a quantidade ajustada pelo gestor)
            _resolver_avulso_na_contagem(cursor, contagem_id, nome_avulso, produto_id_mestre, nova_qtd)

            # 2. AUTO-APRENDIZAGEM DO SISTEMA (Grava o EAN para o futuro)
            if salvar_permanente and ean and ean != "Sem EAN":
                # Checa se o EAN já não foi cadastrado em paralelo
                cursor.execute("SELECT 1 FROM ProdutosFornecedor WHERE EAN = ?", ean)
                if not cursor.fetchone():
                    # Herança Inteligente: Pega o vínculo mais recente deste Produto Mestre
                    # para herdar o FornecedorID e o NCM e não deixar o banco sujo.
                    cursor.execute("SELECT TOP 1 FornecedorID, NCM, DescricaoXML FROM ProdutosFornecedor WHERE ProdutoID = ? ORDER BY ProdutoFornecedorID DESC", produto_id_mestre)
                    ref = cursor.fetchone()

                    if ref:
                        forn_id, ncm, desc_xml = ref
                        nova_desc = f"{desc_xml} (EAN APRENDIDO)"
                        # Insere com fator 1 (assumindo que bipou uma unidade)
                        cursor.execute("""
                            INSERT INTO ProdutosFornecedor (ProdutoID, FornecedorID, DescricaoXML, EAN, NCM, FatorConversao)
                            VALUES (?, ?, ?, ?, ?, 1.0)
                        """, produto_id_mestre, forn_id, nova_desc, ean, ncm)
                        logger.info(f"EAN {ean} aprendido automaticamente e vinculado ao Mestre ID {produto_id_mestre}.")

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro no vínculo inteligente: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def resolver_avulso_fracionando_caixa(contagem_id, nome_avulso, id_vinculo_caixa, novo_ean, qtd_na_caixa, qtd_contada):
    """
    Desktop: transforma o produto da caixa em UNIDADE (ver desmembrar_caixa) e resolve o
    item avulso da contagem — [DEPURAÇÃO 2] agora TUDO numa transação só (antes eram duas:
    se a 2ª falhasse, o histórico já tinha sido reescrito e uma nova tentativa duplicava o vínculo).
    """
    return desmembrar_caixa(id_vinculo_caixa, novo_ean, qtd_na_caixa, contagem_id, nome_avulso, qtd_contada)

def atualizar_qtd_item_contagem(contagem_id, produto_id, nome_avulso, nova_qtd):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # [DEPURAÇÃO 2] Se o mesmo produto/avulso estiver em 2 linhas da contagem (ex: lançado
            # pelo celular duas vezes), antes AS DUAS recebiam a nova quantidade e o total dobrava.
            # Agora as linhas viram UMA só, com a quantidade informada.
            if produto_id:
                cursor.execute("SELECT COUNT(*) FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?", contagem_id, produto_id)
                if int(cursor.fetchone()[0] or 0) > 1:
                    cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?", contagem_id, produto_id)
                    cursor.execute("INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada) VALUES (?, ?, ?)",
                                   contagem_id, produto_id, nova_qtd)
                else:
                    cursor.execute("UPDATE ItensContagemEstoque SET QuantidadeContada = ? WHERE ContagemID = ? AND ProdutoID = ?", nova_qtd, contagem_id, produto_id)
            else:
                cursor.execute("SELECT EANAvulso FROM ItensContagemEstoque WHERE ContagemID = ? AND NomeAvulso = ?", contagem_id, nome_avulso)
                linhas = cursor.fetchall()
                if len(linhas) > 1:
                    ean = next((l[0] for l in linhas if l[0]), None)
                    cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND NomeAvulso = ?", contagem_id, nome_avulso)
                    cursor.execute("INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada, NomeAvulso, EANAvulso) "
                                   "VALUES (?, NULL, ?, ?, ?)", contagem_id, nova_qtd, nome_avulso, ean)
                else:
                    cursor.execute("UPDATE ItensContagemEstoque SET QuantidadeContada = ? WHERE ContagemID = ? AND NomeAvulso = ?", nova_qtd, contagem_id, nome_avulso)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar qtd na contagem: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

def remover_item_contagem(contagem_id, produto_id, nome_avulso):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            if produto_id:
                cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?", contagem_id, produto_id)
            else:
                cursor.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND NomeAvulso = ?", contagem_id, nome_avulso)
            conn.commit()
            return True
        finally:
            conn.close()
    return False

def adicionar_item_contagem_existente(contagem_id, produto_id, qtd):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID = ?", contagem_id, produto_id)
            if cursor.fetchone():
                cursor.execute("UPDATE ItensContagemEstoque SET QuantidadeContada = QuantidadeContada + ? WHERE ContagemID = ? AND ProdutoID = ?", qtd, contagem_id, produto_id)
            else:
                cursor.execute("INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada) VALUES (?, ?, ?)", contagem_id, produto_id, qtd)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao adicionar na contagem existente: {e}")
            return False
        finally:
            conn.close()
    return False


# ===================================================================
# == [MELHORIA] VALOR DO ESTOQUE (custo médio ponderado + fechamento)
# ===================================================================
# Como o valor de cada produto é calculado (opção "B" escolhida pelo gestor):
#   1) Custo médio PONDERADO das compras dos últimos 90 dias ATÉ a data da contagem
#      (cada compra pesa pela quantidade; compras depois da contagem NÃO entram);
#   2) sem compras nesses 90 dias -> custo da última compra anterior à contagem;
#   3) nunca comprado por nota -> custo digitado à mão no Catálogo ("custo manual");
#   4) nada disso -> R$ 0,00 (e aparece um aviso "Sem custo").
# As "notas fantasmas" do custo manual (quantidade 0) NÃO entram na média.
# Ao "Fechar valor", o custo de cada item fica GRAVADO e o total nunca mais muda,
# mesmo que cheguem notas novas (dá para reabrir se precisar corrigir).
CNPJ_FORNECEDOR_INTERNO = "00000000000000"
JANELA_CUSTO_MEDIO_DIAS = 90
DIAS_VERIFICACAO_SUSPEITO = 365
FATOR_CUSTO_SUSPEITO = Decimal('3')   # maior custo >= 3x o menor -> provável fator errado
_tabelas_valor_ok = False


def _como_data(valor):
    """Aceita date, datetime ou texto 'AAAA-MM-DD' e devolve date (ou None)."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _dec(valor):
    try:
        return Decimal(str(valor)) if valor is not None else Decimal('0')
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _br(valor, casas=None):
    """Número no jeito brasileiro: 1234.5 -> '1.234,50' (casas=2) ou '1234,5' (casas=None)."""
    v = _dec(valor)
    if casas is None:
        texto = f"{v:f}"
        texto = texto.rstrip('0').rstrip('.') if '.' in texto else texto
        return texto.replace('.', ',')
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _garantir_tabelas_valor_estoque(cursor=None):
    """
    Cria (uma vez) as tabelas onde o valor fechado de cada contagem fica guardado.
    [CORREÇÃO] A 1ª versão criava as tabelas na mesma conexão da consulta e NÃO fazia
    commit: ao fechar a conexão, o SQL Server desfazia a criação ("Nome de objeto
    'ValorEstoqueFechamento' inválido"). Agora usa uma conexão própria, faz COMMIT e só
    marca como "pronto" depois que a criação foi realmente gravada.
    (O parâmetro 'cursor' é ignorado; ficou só para não mudar quem chama.)
    """
    global _tabelas_valor_ok
    if _tabelas_valor_ok:
        return
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ValorEstoqueFechamento')
            CREATE TABLE ValorEstoqueFechamento (
                ContagemID INT PRIMARY KEY,
                DataFechamento DATETIME NOT NULL DEFAULT GETDATE(),
                ValorTotal DECIMAL(18, 2) NOT NULL,
                Metodo NVARCHAR(200) NULL,
                QtdAvisos INT NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ValorEstoqueFechamentoItens')
            CREATE TABLE ValorEstoqueFechamentoItens (
                ItemID INT IDENTITY(1,1) PRIMARY KEY,
                ContagemID INT NOT NULL,
                ProdutoID INT NULL,
                NomeProduto NVARCHAR(255) NOT NULL,
                Categoria NVARCHAR(100) NULL,
                Unidade NVARCHAR(20) NULL,
                Quantidade DECIMAL(18, 3) NOT NULL,
                CustoUnitario DECIMAL(18, 4) NOT NULL,
                ValorTotal DECIMAL(18, 2) NOT NULL,
                OrigemCusto NVARCHAR(200) NULL
            )
        """)
        conn.commit()
        _tabelas_valor_ok = True
        logger.info("Tabelas ValorEstoqueFechamento / ValorEstoqueFechamentoItens verificadas/criadas.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Não foi possível criar as tabelas do Valor do Estoque: {e}", exc_info=True)
        raise
    finally:
        conn.close()


def _custos_por_produto(cursor, data_contagem):
    """
    Calcula o custo de cada produto NA DATA da contagem.
    Devolve {ProdutoID: {'custo', 'origem', 'suspeito': (menor, maior) ou None}}.
    """
    # Compras REAIS até a data da contagem (sem notas fantasmas de quantidade 0)
    cursor.execute("""
        SELECT PF.ProdutoID, NF.DataEmissao, NF.NotaID, INI.ItemNotaID,
               INI.Quantidade, INI.PrecoCustoUnitario, F.CNPJ
        FROM ItensNotaFiscalEntrada INI
        JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
        JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
        JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        WHERE PF.ProdutoID IS NOT NULL AND NF.DataEmissao < ?
    """, data_contagem + timedelta(days=1))  # "< dia seguinte": inclui notas do próprio dia, mesmo com hora
    compras = {}
    for pid, dt, nota_id, item_id, qtd, custo, cnpj in cursor.fetchall():
        if (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO or _dec(qtd) <= 0:
            continue
        compras.setdefault(pid, []).append((_como_data(dt), nota_id or 0, item_id or 0, _dec(qtd), _dec(custo)))

    # Custo manual (notas fantasmas): vale só para quem NUNCA foi comprado por nota
    cursor.execute("""
        SELECT PF.ProdutoID, NF.DataEmissao, NF.NotaID, INI.ItemNotaID, INI.PrecoCustoUnitario
        FROM ItensNotaFiscalEntrada INI
        JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
        JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
        JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        WHERE PF.ProdutoID IS NOT NULL AND F.CNPJ = ?
    """, CNPJ_FORNECEDOR_INTERNO)
    manuais = {}
    for pid, dt, nota_id, item_id, custo in cursor.fetchall():
        chave = (_como_data(dt) or date.min, nota_id or 0, item_id or 0)
        if pid not in manuais or chave > manuais[pid][0]:
            manuais[pid] = (chave, _dec(custo))

    inicio_janela = data_contagem - timedelta(days=JANELA_CUSTO_MEDIO_DIAS)
    inicio_suspeito = data_contagem - timedelta(days=DIAS_VERIFICACAO_SUSPEITO)
    resultado = {}
    for pid in set(compras) | set(manuais):
        lista = compras.get(pid, [])
        na_janela = [c for c in lista if c[0] and c[0] > inicio_janela]
        suspeito = None
        custos_validos = [c[4] for c in lista if c[0] and c[0] > inicio_suspeito and c[4] > 0]
        if len(custos_validos) >= 2 and min(custos_validos) > 0 and max(custos_validos) >= min(custos_validos) * FATOR_CUSTO_SUSPEITO:
            suspeito = (min(custos_validos), max(custos_validos))

        # [AUDITORIA ESTOQUE] Bonificação entra com custo ZERO. Antes, se a ÚLTIMA entrada (ou todas as
        # entradas dos 90 dias) fosse bonificação, o produto valia R$ 0,00 no estoque, mesmo tendo
        # compras PAGAS antes. Agora, nesses casos, vale o custo da última compra paga.
        pagas = [c for c in lista if c[4] > 0]
        valor_janela = sum(c[3] * c[4] for c in na_janela)
        if na_janela and valor_janela > 0:
            qtd_total = sum(c[3] for c in na_janela)
            custo = valor_janela / qtd_total
            origem = f"Média ponderada de {len(na_janela)} compra(s) em {JANELA_CUSTO_MEDIO_DIAS} dias"
        elif lista:
            def ordem(c):
                return (c[0] or date.min, c[1], c[2])
            mais_recente = max(lista, key=ordem)
            ultima = max(pagas, key=ordem) if pagas else mais_recente
            custo = ultima[4]
            data_txt = ultima[0].strftime('%d/%m/%Y') if ultima[0] else '?'
            if na_janela and pagas:
                origem = f"Última compra paga ({data_txt}) — nos {JANELA_CUSTO_MEDIO_DIAS} dias só houve bonificação"
            elif ultima is not mais_recente:
                origem = f"Última compra paga ({data_txt}) — a mais recente foi bonificação"
            else:
                origem = f"Última compra ({data_txt})"
        else:
            custo = manuais[pid][1]
            origem = "Custo manual (Catálogo)"
        # [DEPURAÇÃO 2] Produto que só entrou por BONIFICAÇÃO (custo 0): antes ficava valendo
        # R$ 0 mesmo depois de informar o custo manual no Catálogo.
        if custo <= 0 and pid in manuais and manuais[pid][1] > 0:
            custo = manuais[pid][1]
            origem = "Custo manual (só recebido em bonificação)"
        resultado[pid] = {'custo': custo, 'origem': origem, 'suspeito': suspeito}
    return resultado, compras


def calcular_valor_estoque(contagem_id):
    """
    Calcula o VALOR DO ESTOQUE de uma contagem (quantidade x custo médio ponderado).
    Se a contagem já teve o valor FECHADO, devolve os valores gravados (não mudam mais).
    Devolve um dicionário:
      {'contagem': {...}, 'itens': [...], 'total', 'por_categoria': {cat: valor},
       'avisos': {'nao_contados', 'avulsos', 'sem_custo', 'custo_suspeito'},
       'fechado': None ou {'data', 'total'}}
    """
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        _garantir_tabelas_valor_estoque(cursor)

        cursor.execute("SELECT ContagemID, DataContagem, NomeContagem FROM ContagensEstoque WHERE ContagemID = ?", contagem_id)
        cab = cursor.fetchone()
        if not cab:
            raise Exception(f"Contagem {contagem_id} não encontrada.")
        data_contagem = _como_data(cab[1])
        if data_contagem is None:
            raise Exception(f"A contagem {contagem_id} está sem data válida.")
        info = {'id': cab[0], 'data': data_contagem, 'nome': cab[2] or 'Geral'}
        vazio = {'nao_contados': [], 'avulsos': [], 'sem_custo': [], 'custo_suspeito': []}

        # ---------- Já fechada? Devolve o que foi gravado ----------
        cursor.execute("SELECT DataFechamento, ValorTotal FROM ValorEstoqueFechamento WHERE ContagemID = ?", contagem_id)
        fech = cursor.fetchone()
        if fech:
            cursor.execute("""
                SELECT ProdutoID, NomeProduto, Categoria, Unidade, Quantidade, CustoUnitario, ValorTotal, OrigemCusto
                FROM ValorEstoqueFechamentoItens WHERE ContagemID = ? ORDER BY Categoria, NomeProduto
            """, contagem_id)
            itens = [{'ProdutoID': r[0], 'NomeProduto': r[1], 'Categoria': r[2] or 'Geral', 'Unidade': r[3] or 'UN',
                      'Quantidade': _dec(r[4]), 'CustoUnitario': _dec(r[5]), 'ValorTotal': _dec(r[6]),
                      'OrigemCusto': r[7] or ''} for r in cursor.fetchall()]
            por_cat = {}
            for it in itens:
                por_cat[it['Categoria']] = por_cat.get(it['Categoria'], Decimal('0')) + it['ValorTotal']
            return {'contagem': info, 'itens': itens, 'total': _dec(fech[1]), 'por_categoria': dict(sorted(por_cat.items())),
                    'avisos': vazio, 'fechado': {'data': fech[0], 'total': _dec(fech[1])}}

        # ---------- Catálogo ----------
        cursor.execute("SELECT ProdutoID, NomeProduto, UnidadeMedida, Categoria FROM ProdutosEstoque")
        catalogo = {r[0]: {'nome': r[1], 'un': r[2] or 'UN', 'cat': r[3] or 'Geral'} for r in cursor.fetchall()}

        # ---------- Itens contados (somando repetidos) e avulsos ----------
        cursor.execute("SELECT ProdutoID, QuantidadeContada, NomeAvulso FROM ItensContagemEstoque WHERE ContagemID = ?", contagem_id)
        contados, avulsos = {}, []
        for pid, qtd, nome_avulso in cursor.fetchall():
            if pid is None:
                avulsos.append({'NomeProduto': nome_avulso or '(sem nome)', 'Quantidade': _dec(qtd)})
            else:
                contados[pid] = contados.get(pid, Decimal('0')) + _dec(qtd)

        custos, compras = _custos_por_produto(cursor, data_contagem)

        itens, sem_custo, suspeitos = [], [], []
        for pid, qtd in contados.items():
            prod = catalogo.get(pid, {'nome': f'Produto {pid} (excluído do catálogo)', 'un': 'UN', 'cat': 'Geral'})
            c = custos.get(pid, {'custo': Decimal('0'), 'origem': 'SEM CUSTO', 'suspeito': None})
            custo = c['custo'].quantize(Decimal('0.0001'))
            valor = (qtd * custo).quantize(Decimal('0.01'))
            item = {'ProdutoID': pid, 'NomeProduto': prod['nome'], 'Categoria': prod['cat'], 'Unidade': prod['un'],
                    'Quantidade': qtd, 'CustoUnitario': custo, 'ValorTotal': valor, 'OrigemCusto': c['origem']}
            itens.append(item)
            if qtd > 0 and custo <= 0:
                sem_custo.append(item)
            if c['suspeito'] and qtd > 0:
                menor, maior = c['suspeito']
                suspeitos.append(dict(item, Detalhe=f"compras entre R$ {_br(menor, 2)} e R$ {_br(maior, 2)} por {prod['un']} — confira o fator da caixa"))
        itens.sort(key=lambda i: (i['Categoria'], i['NomeProduto']))

        # ---------- Não contados ----------
        cursor.execute("SELECT ContagemID, DataContagem FROM ContagensEstoque")
        anteriores = [(_como_data(d), cid) for cid, d in cursor.fetchall() if _como_data(d) and _como_data(d) < data_contagem]
        nao_contados = {}
        desde = data_contagem - timedelta(days=60)
        if anteriores:
            data_ant, id_ant = max(anteriores)
            desde = data_ant
            cursor.execute("SELECT ProdutoID, QuantidadeContada FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID IS NOT NULL", id_ant)
            qtd_ant = {}
            for pid, qtd in cursor.fetchall():
                qtd_ant[pid] = qtd_ant.get(pid, Decimal('0')) + _dec(qtd)
            for pid, qtd in qtd_ant.items():
                if qtd > 0 and pid not in contados and pid in catalogo:
                    nao_contados[pid] = f"tinha {_br(qtd)} {catalogo[pid]['un']} na contagem de {data_ant:%d/%m/%Y}"
        for pid, lista in compras.items():
            if pid in contados or pid not in catalogo:
                continue
            qtd_comprada = sum(c[3] for c in lista if c[0] and c[0] > desde)
            if qtd_comprada > 0:
                texto = f"comprado {_br(qtd_comprada)} {catalogo[pid]['un']} desde {desde:%d/%m/%Y}"
                nao_contados[pid] = f"{nao_contados[pid]}; {texto}" if pid in nao_contados else texto
        lista_nao_contados = sorted(
            [{'ProdutoID': pid, 'NomeProduto': catalogo[pid]['nome'], 'Unidade': catalogo[pid]['un'], 'Detalhe': motivo}
             for pid, motivo in nao_contados.items()], key=lambda i: i['NomeProduto'])

        total = sum((i['ValorTotal'] for i in itens), Decimal('0'))
        por_cat = {}
        for it in itens:
            por_cat[it['Categoria']] = por_cat.get(it['Categoria'], Decimal('0')) + it['ValorTotal']
        return {'contagem': info, 'itens': itens, 'total': total, 'por_categoria': dict(sorted(por_cat.items())),
                'avisos': {'nao_contados': lista_nao_contados, 'avulsos': avulsos,
                           'sem_custo': sem_custo, 'custo_suspeito': suspeitos},
                'fechado': None}
    finally:
        conn.close()


def fechar_valor_estoque(contagem_id):
    """Grava (congela) o valor atual da contagem. Devolve (sucesso, mensagem, total)."""
    try:
        dados = calcular_valor_estoque(contagem_id)
    except Exception as e:
        logger.error(f"Erro ao calcular valor para fechamento (contagem {contagem_id}): {e}", exc_info=True)
        return False, f"Erro ao calcular: {e}", None
    if dados['fechado']:
        return False, "Esta contagem já está com o valor fechado.", dados['total']
    qtd_avisos = sum(len(v) for v in dados['avisos'].values())
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados.", None
    try:
        cursor = conn.cursor()
        _garantir_tabelas_valor_estoque(cursor)
        cursor.execute("INSERT INTO ValorEstoqueFechamento (ContagemID, DataFechamento, ValorTotal, Metodo, QtdAvisos) VALUES (?, ?, ?, ?, ?)",
                       contagem_id, datetime.now(), dados['total'],
                       f"Custo médio ponderado ({JANELA_CUSTO_MEDIO_DIAS} dias)", qtd_avisos)
        linhas = [(contagem_id, i['ProdutoID'], i['NomeProduto'], i['Categoria'], i['Unidade'], i['Quantidade'],
                   i['CustoUnitario'], i['ValorTotal'], i['OrigemCusto']) for i in dados['itens']]
        if linhas:
            cursor.executemany("""
                INSERT INTO ValorEstoqueFechamentoItens
                (ContagemID, ProdutoID, NomeProduto, Categoria, Unidade, Quantidade, CustoUnitario, ValorTotal, OrigemCusto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, linhas)
        conn.commit()
        logger.info(f"Valor do estoque da contagem {contagem_id} FECHADO em R$ {dados['total']:.2f} ({qtd_avisos} aviso(s)).")
        return True, "Valor fechado com sucesso.", dados['total']
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao fechar valor do estoque (contagem {contagem_id}): {e}", exc_info=True)
        return False, f"Erro ao gravar o fechamento: {e}", None
    finally:
        conn.close()


def reabrir_valor_estoque(contagem_id):
    """Apaga o valor gravado (a contagem volta a ser calculada com os custos atuais)."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        _garantir_tabelas_valor_estoque(cursor)
        cursor.execute("DELETE FROM ValorEstoqueFechamentoItens WHERE ContagemID = ?", contagem_id)
        cursor.execute("DELETE FROM ValorEstoqueFechamento WHERE ContagemID = ?", contagem_id)
        conn.commit()
        logger.info(f"Valor do estoque da contagem {contagem_id} REABERTO.")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao reabrir valor do estoque (contagem {contagem_id}): {e}", exc_info=True)
        return False
    finally:
        conn.close()


def listar_valores_estoque_fechados(levantar_erro=False):
    """
    Devolve {ContagemID: (ValorTotal, DataFechamento)} das contagens com valor fechado.
    levantar_erro=True: se o banco falhar, levanta erro (quem protege a contagem não pode
    concluir "não está fechada" só porque a consulta falhou).
    """
    conn = get_db_connection()
    if not conn:
        if levantar_erro:
            raise Exception("Falha de conexão com o banco de dados.")
        return {}
    try:
        cursor = conn.cursor()
        _garantir_tabelas_valor_estoque(cursor)
        cursor.execute("SELECT ContagemID, ValorTotal, DataFechamento FROM ValorEstoqueFechamento")
        return {r[0]: (_dec(r[1]), r[2]) for r in cursor.fetchall()}
    except Exception as e:
        logger.error(f"Erro ao listar valores de estoque fechados: {e}", exc_info=True)
        if levantar_erro:
            raise
        return {}
    finally:
        conn.close()


def contagem_esta_fechada(contagem_id):
    """True se a contagem já tem o valor do estoque fechado (gravado)."""
    return int(contagem_id) in listar_valores_estoque_fechados()

def gerar_relatorio_valoracao_contagem(contagem_id):
    """
    Gera o relatório financeiro de uma contagem para cálculo de CMV.
    Calcula o Preço de Custo usando a MÉDIA das últimas 3 compras de cada produto.
    Ignora itens avulsos (sem ProdutoID).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    ISNULL(PE.Categoria, 'Geral') as Categoria,
                    PE.NomeProduto,
                    IC.QuantidadeContada,
                    ISNULL((
                        SELECT AVG(Sub.PrecoCustoUnitario)
                        FROM (
                            SELECT TOP 3 I.PrecoCustoUnitario 
                            FROM ItensNotaFiscalEntrada I
                            JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                            JOIN ProdutosFornecedor PF ON I.ProdutoFornecedorID = PF.ProdutoFornecedorID
                            WHERE PF.ProdutoID = PE.ProdutoID
                            ORDER BY N.DataEmissao DESC, N.NotaID DESC
                        ) AS Sub
                    ), 0) as CustoMedio
                FROM ItensContagemEstoque IC
                JOIN ProdutosEstoque PE ON IC.ProdutoID = PE.ProdutoID
                WHERE IC.ContagemID = ?
                ORDER BY ISNULL(PE.Categoria, 'Geral'), PE.NomeProduto
            """
            cursor.execute(sql, contagem_id)
            cols = [column[0] for column in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao gerar relatório CMV para Contagem ID {contagem_id}: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []


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
            if contagem_id_inicio == contagem_id_fim:
                raise Exception("A Contagem Inicial e a Contagem Final não podem ser a mesma. Selecione períodos distintos.")

            if (data_final - data_inicial_fixa).days < 0:
                raise Exception("A Data da Contagem Final deve ser posterior à Contagem Inicial.")
        # 3. Busca os ITENS da Contagem FINAL (Estoque Atual Real)
        # CORREÇÃO: Partir de ProdutosEstoque com LEFT JOIN e consolidar quantidades (SUM/GROUP BY) 
        # para evitar duplicidade de ProdutoID na interface do Tkinter (TclError).
        sql_itens_fim = """
            SELECT 
                PE.ProdutoID, 
                PE.NomeProduto, 
                ISNULL(PE.UnidadeMedida, 'UN') as UnidadeMedida, 
                ISNULL(PE.EstoqueMinimo, 0) as EstoqueMinimo, 
                ISNULL(SUM(IC.QuantidadeContada), 0) as QuantidadeContada,
                ISNULL(PE.Categoria, 'Geral') as Categoria
            FROM ProdutosEstoque PE
            LEFT JOIN ItensContagemEstoque IC 
                ON PE.ProdutoID = IC.ProdutoID AND IC.ContagemID = ?
            GROUP BY 
                PE.ProdutoID, 
                PE.NomeProduto, 
                PE.UnidadeMedida, 
                PE.EstoqueMinimo,
                PE.Categoria
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
                    primeira_data_banco = res_data.PrimeiraData
                    # Tratamento de segurança para string vs date (caso o driver ODBC retorne string)
                    if isinstance(primeira_data_banco, str):
                        primeira_data_banco = datetime.strptime(primeira_data_banco[:10], '%Y-%m-%d').date()

                    # Recua 1 dia para que a condição "> data_inicio" do SQL englobe a primeira nota fiscal!
                    data_ini_calc = primeira_data_banco - timedelta(days=1)
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

            # Validação de Datas (CORREÇÃO: Normalização segura para evitar TypeError entre date e datetime)
            def extrair_data_segura(dt_obj):
                return dt_obj.date() if hasattr(dt_obj, 'date') else dt_obj
            
            dt_final_norm = extrair_data_segura(data_final)
            dt_ini_norm = extrair_data_segura(data_ini_calc)

            dias_periodo = (dt_final_norm - dt_ini_norm).days
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
                "DiasPeriodo": dias_periodo,
                "Categoria": item.Categoria
            })
        return relatorio_final

    except Exception as e:
        logger.error(f"ERRO CRÍTICO ao gerar sugestão: {e}", exc_info=True)
        raise e
    finally:
        if conn:
            conn.close()

# ==============================================================================
# == [MELHORIA SUGESTÃO] NOVO CÁLCULO DA SUGESTÃO DE COMPRAS ==================
# ==============================================================================
# Regras (todas explicadas na tela em "🧮 Como calculei"):
#  1. Cada produto usa a SUA última contagem até o Ponto B. Contagem parcial não zera
#     quem não foi contado: vale a contagem anterior daquele produto.
#  2. Contagens do MESMO DIA são somadas (ex: "freezer" + "estoque seco" no mesmo dia).
#  3. Consumo = estoque na contagem inicial + compras entre as contagens - estoque na
#     contagem final, dividido pelos dias entre as duas contagens DO PRODUTO.
#     Ponto A automático = contagem do produto mais perto de N dias antes (padrão 90).
#  4. Produto com 1 contagem só: consumo aproximado pelas compras dos últimos N dias (≈).
#  5. Consumo negativo (saiu menos do que entrou + sobrou) NÃO vira zero escondido:
#     o produto é marcado "⚠️ Conferir" (contagem errada, nota não importada ou vínculo).
#  6. Estoque de hoje = última contagem + compras depois dela - consumo estimado dos dias
#     que passaram. Compras com data no dia da contagem já estão DENTRO da contagem.
#  7. Fornecedores: o da ÚLTIMA compra e o MAIS BARATO dos últimos 12 meses (por unidade
#     do estoque), com o Qtd/Cx do vínculo para pedir em caixas.
SUGESTAO_JANELA_PADRAO = 90       # dias de consumo analisados no modo automático
SUGESTAO_DIAS_MINIMOS = 7         # intervalo mínimo entre 2 contagens para medir consumo


def calcular_sugestao_compra(contagem_id_fim, contagem_id_inicio=None, janela_dias=SUGESTAO_JANELA_PADRAO, hoje=None):
    """
    [MELHORIA SUGESTÃO] Calcula, para TODOS os produtos, o estoque de hoje, o consumo
    por dia e os fornecedores (último e mais barato). Não decide quanto comprar: isso é
    feito na tela, porque depende dos dias a cobrir e do prazo de entrega.
      contagem_id_inicio: None = automático (últimos `janela_dias` dias)
                          -1   = todo o histórico de contagens
                          -2   = desde a PRIMEIRA COMPRA (estoque zero antes da 1ª nota do produto;
                                 se houver contagem ANTES da 1ª nota, começa por ela)
                          ID   = a partir daquela contagem (Ponto A fixo)
    Devolve {'itens': [...], 'DataB', 'DataReferencia', 'Modo', 'JanelaDias'}.
    Levanta Exception com mensagem clara se o Ponto B não existir.
    """
    hoje = _como_data(hoje) or date.today()
    janela_dias = max(int(janela_dias or SUGESTAO_JANELA_PADRAO), SUGESTAO_DIAS_MINIMOS)
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ContagemID, DataContagem FROM ContagensEstoque")
        datas_contagens = {cid: _como_data(dt) for cid, dt in cursor.fetchall()}
        if contagem_id_fim not in datas_contagens or not datas_contagens[contagem_id_fim]:
            raise Exception(f"Contagem Final (Ponto B) ID {contagem_id_fim} não encontrada.")
        data_b = datas_contagens[contagem_id_fim]
        modo = ('auto' if contagem_id_inicio is None else 'historico' if contagem_id_inicio == -1
                else 'primeira_compra' if contagem_id_inicio == -2 else 'fixo')
        data_a = None
        if modo == 'fixo':
            if contagem_id_inicio not in datas_contagens:
                raise Exception(f"Contagem Inicial (Ponto A) ID {contagem_id_inicio} não encontrada.")
            if contagem_id_inicio == contagem_id_fim:
                raise Exception("A Contagem Inicial e a Final não podem ser a mesma. Escolha contagens diferentes "
                                "ou use o modo automático.")
            data_a = datas_contagens[contagem_id_inicio]
            if data_a > data_b:
                raise Exception("A Contagem Inicial (Ponto A) precisa ser ANTERIOR à Contagem Final (Ponto B).")
        # Se o Ponto B é a contagem mais recente, a posição é projetada para HOJE
        # (entram as notas importadas depois da contagem). Se é uma contagem antiga,
        # a análise fica na data dela (para comparar com o passado).
        ultima_geral = max((d for d in datas_contagens.values() if d), default=data_b)
        data_ref = max(hoje, data_b) if data_b >= ultima_geral else data_b

        cursor.execute("SELECT ProdutoID, NomeProduto, UnidadeMedida, EstoqueMinimo, Categoria FROM ProdutosEstoque")
        produtos = cursor.fetchall()

        # Contagens por produto (somando as do mesmo dia), só até a data do Ponto B
        cursor.execute("SELECT ContagemID, ProdutoID, QuantidadeContada FROM ItensContagemEstoque WHERE ProdutoID IS NOT NULL")
        contagens = {}   # pid -> {data: [qtd_total, nº de contagens]}
        for cid, pid, qtd in cursor.fetchall():
            dt = datas_contagens.get(cid)
            if not dt or dt > data_b:
                continue
            dia = contagens.setdefault(pid, {}).setdefault(dt, [Decimal('0'), set()])
            dia[0] += _dec(qtd)
            dia[1].add(cid)

        # Compras reais (quantidade > 0) com fornecedor e fator do vínculo
        cursor.execute("""
            SELECT PF.ProdutoID, NF.DataEmissao, INI.ItemNotaID, INI.Quantidade, INI.PrecoCustoUnitario,
                   PF.FatorConversao, F.FornecedorID, F.NomeFantasia, F.CNPJ, PF.DescricaoXML
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
            WHERE INI.Quantidade > 0
        """)
        compras = {}     # pid -> [(data, item_id, qtd, custo, fator, forn_id, forn_nome, desc)]
        for pid, dt, item_id, qtd, custo, fator, forn_id, forn_nome, cnpj, desc in cursor.fetchall():
            dt = _como_data(dt)
            if not dt or pid is None or (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO:
                continue
            f = _dec(fator) if fator is not None and _dec(fator) > 0 else Decimal('1')
            compras.setdefault(pid, []).append((dt, item_id or 0, _dec(qtd), _dec(custo), f, forn_id,
                                                forn_nome or 'Fornecedor sem nome', desc or ''))
        for lista in compras.values():
            lista.sort(key=lambda c: (c[0], c[1]))

        def soma_compras(lista, depois_de, ate):
            """Compras com data > depois_de e <= ate (None = sem limite)."""
            return sum((c[2] for c in lista if (depois_de is None or c[0] > depois_de) and c[0] <= ate), Decimal('0'))

        def info_fornecedor(c):
            return {'FornecedorID': c[5], 'Fornecedor': c[6], 'Fator': c[4], 'CustoUnid': c[3],
                    'Descricao': c[7], 'Data': c[0]}

        itens = []
        for pid, nome, un, minimo, categoria in produtos:
            lista_c = compras.get(pid, [])
            dias_contados = sorted(contagens.get(pid, {}).items())          # [(data, [qtd, {ids}])]
            ate_ref = [c for c in lista_c if c[0] <= data_ref]
            pagas = [c for c in ate_ref if c[3] > 0]          # bonificação (custo 0) não serve de preço
            ultimo = info_fornecedor((pagas or ate_ref)[-1]) if ate_ref else None
            ano = [c for c in ate_ref if c[0] > data_ref - timedelta(days=365) and c[3] > 0]
            barato = info_fornecedor(min(ano, key=lambda c: (c[3], -c[0].toordinal()))) if ano else None
            # [DEPURAÇÃO 2] última compra de CADA fornecedor (para o pedido do fornecedor filtrado)
            por_fornecedor = {}
            for c in (pagas or ate_ref):
                por_fornecedor[c[5]] = info_fornecedor(c)
            compras_janela = soma_compras(lista_c, data_ref - timedelta(days=janela_dias), data_ref)
            item = {
                'ProdutoID': pid, 'NomeProduto': nome or f'Produto {pid}', 'Unidade': (un or 'UN').strip() or 'UN',
                'Categoria': categoria or 'Geral', 'EstoqueMinimo': _dec(minimo),
                'Contado': bool(dias_contados), 'DataUltimaContagem': None, 'QtdUltimaContagem': None,
                'ContagensNoDia': 0, 'DataInicio': None, 'QtdInicio': None, 'ComprasPeriodo': Decimal('0'),
                'DiasPeriodo': 0, 'Consumo': None, 'UsoMedioDiario': Decimal('0'), 'MetodoConsumo': 'sem_dados',
                'ConsumoNegativo': False, 'ComprasDepois': Decimal('0'), 'DiasDesdeContagem': 0,
                'InicioPrimeiraCompra': False,
                'EstoqueHoje': None, 'ContadoNoPontoB': False, 'ComprasJanela': compras_janela,
                'UltimaCompra': ate_ref[-1][0] if ate_ref else None,
                'FornecedorUltimo': ultimo, 'FornecedorBarato': barato, 'PorFornecedor': por_fornecedor,
            }
            if dias_contados:
                d_l, (q_l, ids_l) = dias_contados[-1]
                item.update({'DataUltimaContagem': d_l, 'QtdUltimaContagem': q_l, 'ContagensNoDia': len(ids_l),
                             'ContadoNoPontoB': d_l == data_b})
                candidatos = [(d, v[0]) for d, v in dias_contados if d <= d_l - timedelta(days=SUGESTAO_DIAS_MINIMOS)]
                inicio = None
                primeira = lista_c[0][0] if lista_c else None
                if modo == 'primeira_compra' and primeira and primeira <= d_l:
                    # Estoque ZERO no dia anterior à 1ª nota. Se o produto foi contado ANTES
                    # dessa nota, a contagem é mais confiável que o "zero" e vira o início.
                    contados_antes = [c for c in candidatos if c[0] < primeira]
                    if contados_antes:
                        inicio = contados_antes[0]
                    elif (d_l - primeira).days >= 0:
                        inicio = (primeira - timedelta(days=1), Decimal('0'))
                        item['InicioPrimeiraCompra'] = True
                elif candidatos:
                    if modo == 'historico':
                        inicio = candidatos[0]
                    elif modo == 'fixo':
                        antes = [c for c in candidatos if c[0] <= data_a]
                        inicio = antes[-1] if antes else candidatos[0]
                    else:
                        # automático: a contagem do produto mais PERTO de N dias atrás
                        alvo = d_l - timedelta(days=janela_dias)
                        inicio = min(candidatos, key=lambda c: (abs((c[0] - alvo).days), c[0]))
                if inicio:
                    d_s, q_s = inicio
                    entrou = soma_compras(lista_c, d_s, d_l)
                    consumo = q_s + entrou - q_l
                    dias = (d_l - d_s).days
                    item.update({'DataInicio': d_s, 'QtdInicio': q_s, 'ComprasPeriodo': entrou, 'DiasPeriodo': dias,
                                 'Consumo': consumo, 'MetodoConsumo': 'contagens'})
                    if consumo < 0:
                        item['ConsumoNegativo'] = True
                    else:
                        item['UsoMedioDiario'] = consumo / dias
                elif compras_janela > 0:
                    # Só uma contagem: aproxima o consumo pelo que foi comprado na janela
                    item.update({'MetodoConsumo': 'compras', 'DiasPeriodo': janela_dias,
                                 'ComprasPeriodo': compras_janela, 'Consumo': compras_janela,
                                 'UsoMedioDiario': compras_janela / janela_dias})
                depois = soma_compras(lista_c, d_l, data_ref)
                dias_desde = (data_ref - d_l).days
                estimado = q_l + depois - item['UsoMedioDiario'] * dias_desde
                item.update({'ComprasDepois': depois, 'DiasDesdeContagem': dias_desde,
                             'EstoqueHoje': max(estimado, Decimal('0'))})
            itens.append(item)
        return {'itens': itens, 'DataB': data_b, 'DataReferencia': data_ref, 'Modo': modo,
                'DataA': data_a, 'JanelaDias': janela_dias}
    except Exception as e:
        logger.error(f"Erro ao calcular a sugestão de compra: {e}", exc_info=True)
        raise
    finally:
        conn.close()


def embalagens_por_produto():
    """
    [MELHORIA CONTAGEM] Embalagens (caixas) conhecidas de cada produto, tiradas do Qtd/Cx
    dos vínculos com fornecedores: {ProdutoID: [{'Fator', 'Fornecedores', 'Compras', 'Ultima'}]}
    Só fatores maiores que 1. A mais usada recentemente vem primeiro.
    """
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT PF.ProdutoID, PF.FatorConversao, F.NomeFantasia, F.CNPJ, INI.ItemNotaID, NF.DataEmissao
            FROM ProdutosFornecedor PF
            LEFT JOIN Fornecedores F ON PF.FornecedorID = F.FornecedorID
            LEFT JOIN ItensNotaFiscalEntrada INI ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID AND INI.Quantidade > 0
            LEFT JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            WHERE PF.ProdutoID IS NOT NULL AND PF.FatorConversao > 1
        """)
        grupos = {}
        for pid, fator, forn, cnpj, item_id, dt in cursor.fetchall():
            if (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO:
                continue
            f = _dec(fator).normalize()
            g = grupos.setdefault((pid, f), {'Fator': f, 'Fornecedores': set(), 'Compras': 0, 'Ultima': date.min})
            if forn:
                g['Fornecedores'].add(forn)
            if item_id is not None:
                g['Compras'] += 1
                g['Ultima'] = max(g['Ultima'], _como_data(dt) or date.min)
        resultado = {}
        for (pid, _), g in grupos.items():
            g['Fornecedores'] = sorted(g['Fornecedores'])
            resultado.setdefault(pid, []).append(g)
        for lista in resultado.values():
            lista.sort(key=lambda g: (g['Ultima'], g['Compras']), reverse=True)
        return resultado
    except Exception as e:
        logger.error(f"Erro ao listar embalagens por produto: {e}", exc_info=True)
        return {}
    finally:
        conn.close()


def ultimas_contagens_por_produto():
    """
    [MELHORIA CONTAGEM] Última quantidade contada de cada produto (somando as contagens do
    mesmo dia): {ProdutoID: (quantidade, data)}. Usada para avisar "contou em caixa?".
    """
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT C.DataContagem, I.ProdutoID, I.QuantidadeContada
            FROM ItensContagemEstoque I JOIN ContagensEstoque C ON I.ContagemID = C.ContagemID
            WHERE I.ProdutoID IS NOT NULL
        """)
        por_dia = {}
        for dt, pid, qtd in cursor.fetchall():
            d = _como_data(dt)
            if d:
                chave = (pid, d)
                por_dia[chave] = por_dia.get(chave, Decimal('0')) + _dec(qtd)
        resultado = {}
        for (pid, d), qtd in por_dia.items():
            if pid not in resultado or d > resultado[pid][1]:
                resultado[pid] = (qtd, d)
        return resultado
    except Exception as e:
        logger.error(f"Erro ao buscar últimas contagens: {e}", exc_info=True)
        return {}
    finally:
        conn.close()


def ultimo_custo_real_produto(produto_id):
    """
    [DEPURAÇÃO 2] Custo por unidade da última compra PAGA do produto (sem bonificação de
    custo 0 e sem o custo manual). Usado para conferir o Qtd/Cx na hora de vincular.
    """
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT INI.PrecoCustoUnitario, NF.DataEmissao, INI.ItemNotaID, F.CNPJ
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
            WHERE PF.ProdutoID = ? AND INI.Quantidade > 0 AND INI.PrecoCustoUnitario > 0
        """, produto_id)
        linhas = [r for r in cursor.fetchall() if (r[3] or '').strip() != CNPJ_FORNECEDOR_INTERNO]
        if not linhas:
            return None
        ultima = max(linhas, key=lambda r: (_como_data(r[1]) or date.min, r[2] or 0))
        return _dec(ultima[0])
    except Exception as e:
        logger.error(f"Erro ao buscar o último custo real do produto {produto_id}: {e}", exc_info=True)
        return None
    finally:
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

def verificar_nota_fiscal_existente(numero_nf, fornecedor_id, serie=None, chave=None):
    """Verifica se a Nota Fiscal (número + fornecedor + série/chave, quando houver) já foi registrada."""
    conn = get_db_connection()
    if conn:
        try:
            return _nota_ja_salva(conn.cursor(), numero_nf, fornecedor_id, serie, chave) is not None
        except Exception as e:
            logger.error(f"ERRO ao verificar duplicidade de NF: {e}", exc_info=True)
            return True # Assume que existe para evitar duplicidade em caso de falha
        finally:
            if conn:
                conn.close()
    return True # Assume que existe para evitar duplicidade se a conexão falhar

def buscar_historico_compras_produto(produto_id_mestre):
    """Busca o histórico de compras, AGORA TRAZENDO O ItemNotaID para edição."""
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
                    INI.PrecoCustoUnitario,
                    INI.ItemNotaID -- <--- CAMPO CRUCIAL ADICIONADO
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
            logger.error(f"ERRO ao buscar histórico de compras: {e}", exc_info=True)
            return []
        finally:
            if conn: conn.close()
    return []

def atualizar_item_historico_compra(item_nota_id, nova_qtd, novo_custo):
    """Atualiza a quantidade e o custo de uma entrada de nota fiscal do passado."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                UPDATE ItensNotaFiscalEntrada 
                SET Quantidade = ?, PrecoCustoUnitario = ? 
                WHERE ItemNotaID = ?
            """
            cursor.execute(sql, nova_qtd, novo_custo, item_nota_id)
            if getattr(cursor, 'rowcount', 1) == 0:   # [DEPURAÇÃO 2] item não existe mais
                conn.rollback()
                return False
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar histórico de compra ID {item_nota_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    return False

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

def gerar_ranking_sabores_buffet(dias_analise=90, lista_ids_permitidos=None):
    """
    Analisa o histórico para determinar a velocidade de compra (UMD).
    Agora filtra EXATAMENTE pelos IDs selecionados manualmente pelo gestor.
    """
    if not lista_ids_permitidos:
        return [] # Se não selecionou nenhum, retorna vazio logo de cara

    conn = get_db_connection()
    if not conn: return []
    
    try:
        cursor = conn.cursor()
        
        # Cria a string de interrogações dinâmica baseada na quantidade de produtos selecionados: "?, ?, ?"
        placeholders = ','.join('?' * len(lista_ids_permitidos))
        
        sql = f"""
            SELECT 
                PE.ProdutoID,
                PE.NomeProduto,
                ISNULL(SUM(INI.Quantidade), 0) as TotalComprado,
                ISNULL(SUM(INI.Quantidade) / CAST(? AS DECIMAL(10,4)), 0) as UMD
            FROM ProdutosEstoque PE
            JOIN ProdutosFornecedor PF ON PE.ProdutoID = PF.ProdutoID
            JOIN ItensNotaFiscalEntrada INI ON PF.ProdutoFornecedorID = INI.ProdutoFornecedorID
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            WHERE PE.ProdutoID IN ({placeholders})
              AND NF.DataEmissao >= DATEADD(day, -?, GETDATE())
            GROUP BY PE.ProdutoID, PE.NomeProduto
            ORDER BY UMD DESC
        """
        
        # Os parâmetros agora são: [dias_divisao] + [id1, id2, id3...] + [dias_filtro_data]
        params = [dias_analise] + lista_ids_permitidos + [dias_analise]
        
        cursor.execute(sql, params)
        cols = [column[0] for column in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
        
    except Exception as e:
        logger.error(f"Erro ao gerar ranking do buffet: {e}", exc_info=True)
        return []
        
    finally:
        if conn: conn.close()
        
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

            # [DEPURAÇÃO] O texto misturava **negrito Markdown** com <b>HTML</b>. Como o
            # notificador envia em HTML, os ** apareciam na mensagem do grupo. Agora é
            # tudo HTML, e nomes/posições são protegidos com html.escape (um '&' ou '<'
            # num nome fazia o Telegram recusar a mensagem inteira).
            data_br = datetime.strptime(str(data_str)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
            texto = f"📅 <b>ESCALA DE TRABALHO - {data_br}</b>\n"
            setor_atual = ""

            for row in resultados:
                setor, pos, nome, ent, sai, ini, fim = row
                setor = setor if setor else "Geral"
                pos = html.escape(str(pos or ''))
                nome = html.escape(str(nome or ''))

                if setor != setor_atual:
                    texto += f"\n🔹 <b>{html.escape(setor.upper())}</b>\n"
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
            # [DEPURAÇÃO 2] Os "valores fechados" das contagens também saem. Antes ficavam no
            # banco e a 1ª contagem nova (ID 1 de novo) aparecia FECHADA com o valor antigo.
            _garantir_tabelas_valor_estoque()
            cursor.execute("DELETE FROM ValorEstoqueFechamentoItens")
            cursor.execute("DELETE FROM ValorEstoqueFechamento")
            for tabela in ('ItensNotaFiscalEntrada', 'NotasFiscaisEntrada', 'ItensContagemEstoque',
                           'ContagensEstoque', 'ProdutosFornecedor', 'ProdutosEstoque'):
                cursor.execute(f"SELECT COUNT(*) FROM {tabela}")
                tinha_linhas = int(cursor.fetchone()[0] or 0) > 0
                cursor.execute(f"DELETE FROM {tabela}")
                # [DEPURAÇÃO 2] Só reinicia a numeração de quem tinha linhas. Numa tabela que
                # nunca foi usada o SQL Server daria o ID 0 ao próximo registro (e "0" é tratado
                # como "sem ID" em vários lugares).
                if tinha_linhas:
                    cursor.execute(f"DBCC CHECKIDENT ('{tabela}', RESEED, 0)")
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

TABELAS_BACKUP_ESTOQUE = ('ProdutosEstoque', 'Fornecedores', 'ProdutosFornecedor', 'NotasFiscaisEntrada',
                          'ItensNotaFiscalEntrada', 'ContagensEstoque', 'ItensContagemEstoque',
                          'ValorEstoqueFechamento', 'ValorEstoqueFechamentoItens')


def exportar_tabelas_estoque():
    """
    [DEPURAÇÃO 2] Lê TODAS as tabelas do estoque como estão no banco (para o backup antes do
    reset): {tabela: (colunas, linhas)}. Qualquer falha LEVANTA ERRO — um backup pela metade
    não pode ser tratado como backup.
    """
    _garantir_tabelas_valor_estoque()
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cursor = conn.cursor()
        resultado = {}
        for tabela in TABELAS_BACKUP_ESTOQUE:
            cursor.execute(f"SELECT * FROM {tabela}")
            colunas = [d[0] for d in cursor.description]
            resultado[tabela] = (colunas, [tuple(r) for r in cursor.fetchall()])
        return resultado
    finally:
        conn.close()


# ===================================================================
# == MÓDULO DE GERENCIAMENTO DE VÍNCULOS (DE/PARA) ==================
# ===================================================================

def buscar_ids_produtos_por_fornecedor(fornecedor_id):
    """Busca a lista de Produtos Mestre que já foram comprados deste fornecedor."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT ProdutoID FROM ProdutosFornecedor WHERE FornecedorID = ? AND ProdutoID IS NOT NULL", fornecedor_id)
            return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Erro ao buscar produtos por fornecedor: {e}")
            return set()
        finally:
            conn.close()
    return set()

def buscar_vinculos_por_produto_mestre(produto_id):
    """Busca todos os vínculos DE/PARA associados a um Produto Mestre específico."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # ADICIONADO: PF.ProdutoFornecedorID no início do SELECT
            sql = """
                SELECT PF.ProdutoFornecedorID, F.NomeFantasia, PF.DescricaoXML, PF.FatorConversao, PF.EAN
                FROM ProdutosFornecedor PF
                JOIN Fornecedores F ON PF.FornecedorID = F.FornecedorID
                WHERE PF.ProdutoID = ?
                ORDER BY F.NomeFantasia
            """
            cursor.execute(sql, produto_id)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao buscar vínculos por mestre (ID: {produto_id}): {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []


def atualizar_vinculo_simples(vinculo_id, novo_fator, novo_ean, novo_mestre_id):
    """Atualiza o Fator, EAN e permite trocar o Produto Mestre do vínculo."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE ProdutosFornecedor SET FatorConversao = ?, EAN = ?, ProdutoID = ? WHERE ProdutoFornecedorID = ?"
            cursor.execute(sql, novo_fator, novo_ean, novo_mestre_id, vinculo_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar vinculo simples (ID {vinculo_id}): {e}", exc_info=True)
            return False
        finally:
            conn.close()
    return False


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

def atualizar_vinculo_existente(vinculo_id, novo_produto_id, novo_fator, recalcular_compras=False, novo_ean=None, novo_ncm=None):
    """
    Atualiza o Produto Mestre e o Fator de um vínculo existente.
    [MELHORIA] recalcular_compras=True: corrige também as compras JÁ IMPORTADAS por
    este vínculo. Antes, trocar o fator só valia para as próximas notas e o histórico
    continuava errado (ex: 1 UN a R$ 72 em vez de 12 UN a R$ 6). O valor total de cada
    compra não muda: Quantidade x (novo/antigo) e Custo x (antigo/novo).
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            if recalcular_compras:
                # [DEPURAÇÃO 2] Cada item é convertido a partir do Qtd/Cx com que FOI importado
                # (antes usava o Qtd/Cx atual do vínculo para todos: itens vindos de um vínculo
                # juntado, ou já corrigidos antes, eram multiplicados de novo).
                _garantir_colunas_estoque()
                cursor.execute("SELECT FatorConversao FROM ProdutosFornecedor WHERE ProdutoFornecedorID = ?", vinculo_id)
                linha = cursor.fetchone()
                fator_vinculo = _fator_item(None, linha[0] if linha else None)
                fator_novo = _dec(novo_fator)
                if fator_novo > 0:
                    cursor.execute("SELECT ItemNotaID, Quantidade, PrecoCustoUnitario, FatorConversaoUsado FROM ItensNotaFiscalEntrada "
                                   "WHERE ProdutoFornecedorID = ? AND Quantidade > 0", vinculo_id)
                    alterados = 0
                    for item_id, qtd, custo, usado in cursor.fetchall():
                        fator_antigo = _fator_item(usado, fator_vinculo)
                        if fator_antigo == fator_novo:
                            continue
                        nova_qtd = (_dec(qtd) * fator_novo / fator_antigo).quantize(Decimal('0.001'))
                        novo_custo = (_dec(custo) * fator_antigo / fator_novo).quantize(Decimal('0.0001'))
                        cursor.execute("UPDATE ItensNotaFiscalEntrada SET Quantidade = ?, PrecoCustoUnitario = ?, "
                                       "FatorConversaoUsado = ? WHERE ItemNotaID = ?", nova_qtd, novo_custo, fator_novo, item_id)
                        alterados += 1
                    logger.info(f"Vínculo {vinculo_id}: {alterados} compra(s) recalculada(s) para o Qtd/Cx {fator_novo}.")
            sql = """
                UPDATE ProdutosFornecedor 
                SET ProdutoID = ?, FatorConversao = ? 
                WHERE ProdutoFornecedorID = ?
            """
            cursor.execute(sql, novo_produto_id, novo_fator, vinculo_id)
            # [MELHORIA] EAN e NCM também podem ser editados aqui (None = não mexe)
            if novo_ean is not None:
                cursor.execute("UPDATE ProdutosFornecedor SET EAN = ? WHERE ProdutoFornecedorID = ?", novo_ean, vinculo_id)
            if novo_ncm is not None:
                cursor.execute("UPDATE ProdutosFornecedor SET NCM = ? WHERE ProdutoFornecedorID = ?", novo_ncm, vinculo_id)
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Erro ao atualizar vínculo ID {vinculo_id}: {e}", exc_info=True)
            return False
        finally:
            conn.close()
    return False


def listar_vinculos_com_resumo():
    """
    [MELHORIA] Lista os vínculos com o resumo das compras de cada um, para a tela de
    vínculos: quantas compras, data e custo por unidade da ÚLTIMA compra, custo da
    embalagem (custo x fator) e se o vínculo parece ter o fator errado.
    Devolve uma lista de dicionários.
    """
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT PF.ProdutoFornecedorID, F.NomeFantasia, PF.DescricaoXML, PF.ProdutoID, P.NomeProduto,
                   PF.FatorConversao, PF.EAN, F.CNPJ, PF.NCM, PF.CodigoFornecedor, PF.FornecedorID
            FROM ProdutosFornecedor PF
            LEFT JOIN Fornecedores F ON PF.FornecedorID = F.FornecedorID
            LEFT JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
        """)
        vinculos = cursor.fetchall()
        cursor.execute("""
            SELECT INI.ProdutoFornecedorID, NF.DataEmissao, NF.NotaID, INI.ItemNotaID, INI.Quantidade, INI.PrecoCustoUnitario,
                   NF.ValorTotalNF
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            WHERE INI.Quantidade > 0
        """)
        compras = {}
        custo_errado = set()   # [MELHORIA] vínculos com alguma compra que custa mais que a NOTA INTEIRA
        for pf, dt, nota_id, item_id, qtd, custo, total_nf in cursor.fetchall():
            compras.setdefault(pf, []).append((_como_data(dt) or date.min, nota_id or 0, item_id or 0, _dec(qtd), _dec(custo)))
            if _item_maior_que_nota(_dec(qtd) * _dec(custo), total_nf):
                custo_errado.add(pf)

        resultado = []
        for pf, forn, desc, pid, nome_mestre, fator, ean, cnpj, ncm, codigo, forn_id in vinculos:
            fator = _dec(fator) if fator is not None and _dec(fator) > 0 else Decimal('1')
            lista = sorted(compras.get(pf, []))
            ultima = lista[-1] if lista else None
            custos = [c[4] for c in lista if c[4] > 0]
            resultado.append({
                'ID': pf, 'Fornecedor': forn or 'FORNECEDOR DELETADO', 'DescricaoXML': desc or 'Sem Descrição',
                'ProdutoID': pid, 'NomeMestre': nome_mestre or ('PRODUTO DELETADO (ÓRFÃO)' if pid else 'SEM PRODUTO'),
                'Fator': fator, 'EAN': ean or '', 'Interno': (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO,
                'NCM': ncm or '', 'Codigo': codigo or '', 'FornecedorID': forn_id,
                'Orfao': bool(pid) and not nome_mestre, 'SemProduto': not pid,
                'QtdCompras': len(lista),
                'UltimaData': ultima[0] if ultima and ultima[0] != date.min else None,
                'UltimaQtd': ultima[3] if ultima else None,          # já na unidade do estoque
                'UltimoCustoUnid': ultima[4] if ultima else None,    # por unidade do estoque
                'VariacaoPropria': bool(len(custos) >= 2 and max(custos) >= min(custos) * FATOR_CUSTO_SUSPEITO),
                'CustoErrado': pf in custo_errado,
            })

        # Suspeito: custo por unidade muito diferente do custo "típico" do mesmo produto.
        # O típico é a MEDIANA PONDERADA PELA QUANTIDADE de todas as compras do produto:
        # um vínculo com fator errado costuma ter poucas unidades (ex: 1 "UN" a R$ 72) e
        # por isso não "puxa" a referência para o lado errado.
        compras_por_produto = {}
        for v in resultado:
            if v['ProdutoID'] and not v['Interno']:
                for c in compras.get(v['ID'], []):
                    if c[4] > 0:
                        compras_por_produto.setdefault(v['ProdutoID'], []).append((c[4], c[3]))
        referencia = {}
        for pid, lista in compras_por_produto.items():
            lista.sort()
            metade = sum(q for _, q in lista) / 2
            acumulado = Decimal('0')
            for custo, qtd in lista:
                acumulado += qtd
                if acumulado >= metade:
                    referencia[pid] = custo
                    break
        for v in resultado:
            v['Suspeito'] = v['VariacaoPropria']
            ref = referencia.get(v['ProdutoID'])
            if ref and ref > 0 and v['UltimoCustoUnid'] and v['UltimoCustoUnid'] > 0 and not v['Interno']:
                if v['UltimoCustoUnid'] >= ref * FATOR_CUSTO_SUSPEITO or v['UltimoCustoUnid'] * FATOR_CUSTO_SUSPEITO <= ref:
                    v['Suspeito'] = True
            v['CustoReferencia'] = ref

        # [MELHORIA] Grupos de duplicados (mesmo fornecedor + mesmo produto + mesmo código ou EAN)
        grupos = _agrupar_duplicados(resultado)
        for n, grupo in enumerate(grupos, start=1):
            for v in grupo:
                v['Grupo'] = n
        for v in resultado:
            v.setdefault('Grupo', None)
            v['Duplicado'] = v['Grupo'] is not None
            v['SemEAN'] = not v['Interno'] and not _ean_valido(v['EAN'])
            v['SemCompras'] = v['QtdCompras'] == 0 and not v['Interno']
        resultado.sort(key=lambda v: (str(v['Fornecedor']), str(v['DescricaoXML'])))
        return resultado
    except Exception as e:
        logger.error(f"Erro ao listar vínculos com resumo: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def _item_maior_que_nota(total_item, total_nota):
    """
    [MELHORIA] True quando UM item custa mais que a NOTA INTEIRA (impossível: é erro de
    digitação/importação, ex: R$ 840.000,00 no lugar de R$ 84,00). Só confere quando o
    total da nota foi gravado (> 0). Tolerância de 5% + R$ 1 para arredondamentos.
    """
    total_nota = _dec(total_nota) if total_nota is not None else Decimal('0')
    return total_nota > 0 and _dec(total_item) > total_nota * Decimal('1.05') + Decimal('1')


def listar_compras_do_vinculo(vinculo_id):
    """
    [MELHORIA] Todas as compras (itens de nota) de um vínculo, da mais nova para a mais
    antiga, com o que é preciso para conferir e corrigir o custo:
    [{'ItemNotaID','NotaID','NF','Data','Quantidade','Custo','TotalItem','TotalNota',
      'SomaOutrosItens','MaiorQueNota'}]
    """
    try:
        _garantir_colunas_estoque()
    except Exception:
        return []
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT INI.ItemNotaID, NF.NotaID, NF.NumeroNF, NF.DataEmissao, INI.Quantidade, INI.PrecoCustoUnitario,
                   NF.ValorTotalNF, INI.FatorConversaoUsado, PF.FatorConversao
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            LEFT JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            WHERE INI.ProdutoFornecedorID = ?
        """, vinculo_id)
        linhas = cursor.fetchall()
        resultado = []
        for item_id, nota_id, nf, dt, qtd, custo, total_nf, usado, fator_vinc in linhas:
            cursor.execute("SELECT Quantidade, PrecoCustoUnitario FROM ItensNotaFiscalEntrada "
                           "WHERE NotaID = ? AND ItemNotaID <> ?", nota_id, item_id)
            outros = sum((_dec(q) * _dec(c) for q, c in cursor.fetchall()), Decimal('0'))
            q, c = _dec(qtd), _dec(custo)
            total_nota = _dec(total_nf) if total_nf is not None else Decimal('0')
            resultado.append({'ItemNotaID': item_id, 'NotaID': nota_id, 'NF': nf, 'Data': _como_data(dt),
                              'Quantidade': q, 'Custo': c, 'TotalItem': q * c, 'TotalNota': total_nota,
                              'SomaOutrosItens': outros, 'MaiorQueNota': _item_maior_que_nota(q * c, total_nota),
                              'Fator': _fator_item(usado, fator_vinc)})
        resultado.sort(key=lambda r: (r['Data'] or date.min, r['ItemNotaID'] or 0), reverse=True)
        return resultado
    except Exception as e:
        logger.error(f"Erro ao listar compras do vínculo {vinculo_id}: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def _agrupar_duplicados(vinculos):
    """
    Junta em grupos os vínculos que são o MESMO item: mesmo fornecedor, mesmo Produto
    Mestre e que compartilham o código do fornecedor ou o EAN. Devolve lista de grupos
    (cada grupo = lista de dicionários, com 2 ou mais vínculos).
    """
    pai = {}

    def achar(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    chaves = {}
    for v in vinculos:
        if v.get('Interno') or not v.get('ProdutoID'):
            continue
        pai[v['ID']] = v['ID']
        base = (v.get('FornecedorID'), v['ProdutoID'])
        for chave in ((('COD',) + base + (_codigo_valido(v.get('Codigo')),)) if _codigo_valido(v.get('Codigo')) else None,
                      (('EAN',) + base + (_ean_valido(v.get('EAN')),)) if _ean_valido(v.get('EAN')) else None):
            if chave is None:
                continue
            if chave in chaves:
                pai[achar(v['ID'])] = achar(chaves[chave])
            else:
                chaves[chave] = v['ID']
    por_raiz = {}
    por_id = {v['ID']: v for v in vinculos}
    for vid in pai:
        por_raiz.setdefault(achar(vid), []).append(por_id[vid])
    return [sorted(g, key=lambda v: v['ID']) for g in por_raiz.values() if len(g) >= 2]


def listar_grupos_duplicados():
    """[MELHORIA] Grupos de vínculos duplicados, com o vínculo sugerido para MANTER em cada um."""
    grupos = {}
    for v in listar_vinculos_com_resumo():
        if v.get('Grupo'):
            grupos.setdefault(v['Grupo'], []).append(v)
    resultado = []
    for n, lista in sorted(grupos.items()):
        # Sugere manter o que tem a compra mais recente (e, empatando, mais compras)
        manter = max(lista, key=lambda v: (v['UltimaData'] or date.min, v['QtdCompras'], v['ID']))
        resultado.append({'Grupo': n, 'Vinculos': lista, 'ManterID': manter['ID'],
                          'FatoresIguais': len({v['Fator'] for v in lista}) == 1,
                          'Fornecedor': lista[0]['Fornecedor'], 'NomeMestre': lista[0]['NomeMestre']})
    return resultado


def juntar_vinculos(manter_id, remover_ids):
    """
    [MELHORIA] Junta vínculos duplicados num só: as compras dos removidos passam a
    apontar para o vínculo mantido e os removidos são apagados. As quantidades e custos
    já gravados NÃO mudam (já estão na unidade do estoque). Exige mesmo fornecedor e
    mesmo Produto Mestre. Devolve (sucesso, mensagem).
    """
    remover_ids = [r for r in remover_ids if str(r) != str(manter_id)]
    if not remover_ids:
        return False, "Nada para juntar."
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        todos = [manter_id] + list(remover_ids)
        marcas = ", ".join("?" for _ in todos)
        cursor.execute(f"SELECT ProdutoFornecedorID, FornecedorID, ProdutoID, EAN, CodigoFornecedor, NCM "
                       f"FROM ProdutosFornecedor WHERE ProdutoFornecedorID IN ({marcas})", *todos)
        linhas = {str(r[0]): r for r in cursor.fetchall()}
        if str(manter_id) not in linhas or any(str(r) not in linhas for r in remover_ids):
            return False, "Algum vínculo não foi encontrado (a lista pode estar desatualizada)."
        if len({(linhas[str(i)][1], linhas[str(i)][2]) for i in todos}) != 1:
            return False, "Só é possível juntar vínculos do MESMO fornecedor e do MESMO produto."
        manter = linhas[str(manter_id)]
        # Aproveita EAN / código / NCM dos removidos se o mantido não tiver
        for campo, idx in (('EAN', 3), ('CodigoFornecedor', 4), ('NCM', 5)):
            valor_mantido = manter[idx]
            if (campo == 'EAN' and not _ean_valido(valor_mantido)) or (campo != 'EAN' and not str(valor_mantido or '').strip()):
                for r in remover_ids:
                    candidato = linhas[str(r)][idx]
                    if (campo == 'EAN' and _ean_valido(candidato)) or (campo != 'EAN' and str(candidato or '').strip()):
                        cursor.execute(f"UPDATE ProdutosFornecedor SET {campo} = ? WHERE ProdutoFornecedorID = ?", candidato, manter_id)
                        break
        marcas_r = ", ".join("?" for _ in remover_ids)
        # [DEPURAÇÃO 2] os itens levam junto o Qtd/Cx com que foram importados
        _garantir_colunas_estoque()
        cursor.execute(f"""UPDATE ItensNotaFiscalEntrada SET FatorConversaoUsado = (
                              SELECT PF.FatorConversao FROM ProdutosFornecedor PF
                              WHERE PF.ProdutoFornecedorID = ItensNotaFiscalEntrada.ProdutoFornecedorID)
                          WHERE FatorConversaoUsado IS NULL AND ProdutoFornecedorID IN ({marcas_r})""", *remover_ids)
        cursor.execute(f"UPDATE ItensNotaFiscalEntrada SET ProdutoFornecedorID = ? WHERE ProdutoFornecedorID IN ({marcas_r})",
                       manter_id, *remover_ids)
        cursor.execute(f"DELETE FROM ProdutosFornecedor WHERE ProdutoFornecedorID IN ({marcas_r})", *remover_ids)
        conn.commit()
        logger.info(f"Vínculos {remover_ids} juntados no vínculo {manter_id}.")
        return True, f"{len(remover_ids)} vínculo(s) juntado(s) no ID {manter_id}."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao juntar vínculos {remover_ids} em {manter_id}: {e}", exc_info=True)
        return False, f"Erro ao juntar: {e}"
    finally:
        conn.close()


# ===================================================================
# == [MELHORIA] CONSULTAS: histórico de preços e notas fiscais ======
# ===================================================================
def historico_compras_detalhado(produto_id):
    """
    Todas as compras REAIS de um Produto Mestre (sem as notas fantasmas do custo manual),
    da mais nova para a mais antiga. Quantidade e custo já na unidade do estoque;
    'Fator' permite mostrar também como veio na nota (embalagens e custo da embalagem).
    """
    try:
        _garantir_colunas_estoque()
    except Exception:
        return []
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT NF.NotaID, NF.NumeroNF, NF.DataEmissao, F.FornecedorID, F.NomeFantasia, F.CNPJ,
                   PF.DescricaoXML, COALESCE(INI.FatorConversaoUsado, PF.FatorConversao), INI.Quantidade,
                   INI.PrecoCustoUnitario, INI.ItemNotaID
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
            WHERE PF.ProdutoID = ? AND INI.Quantidade > 0
        """, produto_id)
        resultado = []
        for nota_id, numero, dt, forn_id, forn, cnpj, desc, fator, qtd, custo, item_id in cursor.fetchall():
            if (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO:
                continue
            fator = _dec(fator) if fator is not None and _dec(fator) > 0 else Decimal('1')
            q, c = _dec(qtd), _dec(custo)
            resultado.append({'NotaID': nota_id, 'NumeroNF': numero, 'Data': _como_data(dt), 'FornecedorID': forn_id,
                              'Fornecedor': forn or '?', 'DescricaoXML': desc or '', 'Fator': fator,
                              'Quantidade': q, 'CustoUnitario': c, 'Total': q * c,
                              'Embalagens': q / fator, 'CustoEmbalagem': c * fator, 'ItemNotaID': item_id})
        resultado.sort(key=lambda r: (r['Data'] or date.min, r['NotaID'], r['ItemNotaID'] or 0), reverse=True)
        return resultado
    except Exception as e:
        logger.error(f"Erro ao buscar histórico detalhado do produto {produto_id}: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def resumo_precos_por_fornecedor(historico, desde=None):
    """
    Resume um histórico (de historico_compras_detalhado) por fornecedor, do MAIS BARATO
    para o mais caro (pelo custo médio ponderado por unidade do estoque).
    Bonificações (custo zero) contam na quantidade mas não entram no "menor preço".
    """
    grupos = {}
    for r in historico:
        if desde and r['Data'] and r['Data'] < desde:
            continue
        grupos.setdefault((r['FornecedorID'], r['Fornecedor']), []).append(r)
    resumo = []
    for (forn_id, forn), lista in grupos.items():
        qtd = sum((r['Quantidade'] for r in lista), Decimal('0'))
        valor = sum((r['Total'] for r in lista), Decimal('0'))
        pagos = [r['CustoUnitario'] for r in lista if r['CustoUnitario'] > 0]
        ultima = max(lista, key=lambda r: (r['Data'] or date.min, r['NotaID']))
        resumo.append({'FornecedorID': forn_id, 'Fornecedor': forn, 'Compras': len(lista), 'Quantidade': qtd,
                       'CustoMedio': (valor / qtd) if qtd > 0 else Decimal('0'),
                       'Menor': min(pagos) if pagos else Decimal('0'), 'Maior': max(pagos) if pagos else Decimal('0'),
                       'Ultimo': ultima['CustoUnitario'], 'UltimaData': ultima['Data']})
    resumo.sort(key=lambda r: (r['CustoMedio'] <= 0, r['CustoMedio']))
    return resumo


def listar_notas_para_consulta():
    """
    Notas fiscais importadas (sem as notas fantasmas do custo manual), com a quantidade
    de itens, o total dos itens e um texto com os itens (para a busca "que nota tinha X?").
    """
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT NF.NotaID, NF.NumeroNF, NF.DataEmissao, NF.ValorTotalNF, F.NomeFantasia, F.CNPJ
            FROM NotasFiscaisEntrada NF
            LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        """)
        notas = {}
        for nota_id, numero, dt, valor, forn, cnpj in cursor.fetchall():
            if (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO:
                continue
            notas[nota_id] = {'NotaID': nota_id, 'NumeroNF': numero or '', 'Data': _como_data(dt),
                              'ValorNF': _dec(valor), 'Fornecedor': forn or '?', 'CNPJ': cnpj or '',
                              'Itens': 0, 'TotalItens': Decimal('0'), 'TextoItens': ''}
        cursor.execute("""
            SELECT INI.NotaID, INI.Quantidade, INI.PrecoCustoUnitario, PF.DescricaoXML, P.NomeProduto
            FROM ItensNotaFiscalEntrada INI
            LEFT JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            LEFT JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
        """)
        textos = {}
        for nota_id, qtd, custo, desc, nome in cursor.fetchall():
            n = notas.get(nota_id)
            if not n:
                continue
            n['Itens'] += 1
            n['TotalItens'] += _dec(qtd) * _dec(custo)
            textos.setdefault(nota_id, []).append(f"{desc or ''} {nome or ''}")
        for nota_id, partes in textos.items():
            notas[nota_id]['TextoItens'] = " | ".join(partes)
        return sorted(notas.values(), key=lambda n: (n['Data'] or date.min, n['NotaID']), reverse=True)
    except Exception as e:
        logger.error(f"Erro ao listar notas para consulta: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def itens_da_nota(nota_id):
    """Itens de uma nota fiscal: produto do estoque, descrição na nota, quantidades e custos."""
    try:
        _garantir_colunas_estoque()
    except Exception:
        return []
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT INI.ItemNotaID, PF.DescricaoXML, P.ProdutoID, P.NomeProduto, P.UnidadeMedida,
                   COALESCE(INI.FatorConversaoUsado, PF.FatorConversao), INI.Quantidade, INI.PrecoCustoUnitario
            FROM ItensNotaFiscalEntrada INI
            LEFT JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            LEFT JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
            WHERE INI.NotaID = ?
        """, nota_id)
        itens = []
        for item_id, desc, pid, nome, un, fator, qtd, custo in cursor.fetchall():
            fator = _dec(fator) if fator is not None and _dec(fator) > 0 else Decimal('1')
            q, c = _dec(qtd), _dec(custo)
            itens.append({'ItemNotaID': item_id, 'DescricaoXML': desc or '(vínculo excluído)', 'ProdutoID': pid,
                          'NomeProduto': nome or '(sem produto)', 'Unidade': un or 'UN', 'Fator': fator,
                          'Quantidade': q, 'CustoUnitario': c, 'Total': q * c,
                          'Embalagens': q / fator, 'CustoEmbalagem': c * fator})
        itens.sort(key=lambda i: i['ItemNotaID'] or 0)
        return itens
    except Exception as e:
        logger.error(f"Erro ao buscar itens da nota {nota_id}: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def buscar_nota_importada(numero_nf, fornecedor_id, serie=None, chave=None):
    """[MELHORIA ST] NotaID de uma nota já salva (mesmo número e fornecedor; mesma série/chave quando houver), ou None."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        return _nota_ja_salva(conn.cursor(), numero_nf, fornecedor_id, serie, chave)
    except Exception as e:
        logger.error(f"Erro ao buscar nota {numero_nf} do fornecedor {fornecedor_id}: {e}", exc_info=True)
        return None
    finally:
        conn.close()


def itens_nota_para_recalculo(nota_id):
    """[MELHORIA ST] Itens gravados de uma nota: [{'ItemNotaID','ProdutoFornecedorID','Quantidade','Custo'}]."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ItemNotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario "
                       "FROM ItensNotaFiscalEntrada WHERE NotaID = ?", nota_id)
        return [{'ItemNotaID': r[0], 'ProdutoFornecedorID': r[1], 'Quantidade': _dec(r[2]), 'Custo': _dec(r[3])}
                for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Erro ao ler itens da nota {nota_id} para recálculo: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def atualizar_custos_itens(alteracoes):
    """
    [MELHORIA ST] Grava novos custos unitários: alteracoes = [(ItemNotaID, novo_custo), ...].
    Tudo numa transação só (ou grava tudo, ou nada). Quantidades não mudam.
    """
    if not alteracoes:
        return True, "Nada para alterar."
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        for item_id, custo in alteracoes:
            cursor.execute("UPDATE ItensNotaFiscalEntrada SET PrecoCustoUnitario = ? WHERE ItemNotaID = ?",
                           _dec(custo).quantize(Decimal('0.0001')), item_id)
        conn.commit()
        logger.info(f"Custos recalculados em {len(alteracoes)} item(ns) de notas fiscais.")
        return True, f"{len(alteracoes)} item(ns) atualizado(s)."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao atualizar custos dos itens: {e}", exc_info=True)
        return False, f"Erro ao gravar: {e}"
    finally:
        conn.close()


def listar_notas_com_diferenca(diferenca_minima=Decimal('0.05')):
    """
    [MELHORIA ST - sem XML] Notas em que o VALOR TOTAL DA NOTA (gravado na importação) é
    MAIOR que a soma dos itens gravados (quantidade x custo). A diferença costuma ser ST,
    frete etc. que estavam só no total da nota e ficaram fora do custo — mas também pode ser
    item de comodato ignorado ou item que não foi salvo (por isso o usuário escolhe as notas).
    """
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        _garantir_colunas_estoque()
        cursor.execute("""
            SELECT NF.NotaID, NF.NumeroNF, NF.DataEmissao, NF.ValorTotalNF, F.FornecedorID, F.NomeFantasia, F.CNPJ,
                   NF.ValorForaDoEstoque
            FROM NotasFiscaisEntrada NF
            LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        """)
        notas = {}
        for nota_id, numero, dt, valor, forn_id, forn, cnpj, fora in cursor.fetchall():
            if (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO:
                continue
            # [DEPURAÇÃO 2] tira do total da nota o que não é compra paga (bonificação, comodato)
            notas[nota_id] = {'NotaID': nota_id, 'NumeroNF': numero or '', 'Data': _como_data(dt),
                              'ValorNF': _dec(valor) - _dec(fora or 0), 'ValorFora': _dec(fora or 0),
                              'ImportadaAntes': fora is None,
                              'FornecedorID': forn_id, 'Fornecedor': forn or '?', 'SomaItens': Decimal('0'), 'Itens': 0,
                              'ItensCustoZero': 0}
        cursor.execute("SELECT NotaID, Quantidade, PrecoCustoUnitario FROM ItensNotaFiscalEntrada WHERE Quantidade > 0")
        for nota_id, qtd, custo in cursor.fetchall():
            n = notas.get(nota_id)
            if n:
                n['SomaItens'] += _dec(qtd) * _dec(custo)
                n['Itens'] += 1
                if _dec(custo) <= 0:
                    n['ItensCustoZero'] += 1
        resultado = []
        for n in notas.values():
            n['Diferenca'] = n['ValorNF'] - n['SomaItens']
            if n['Itens'] and n['SomaItens'] > 0 and n['Diferenca'] >= diferenca_minima:
                n['Percentual'] = n['Diferenca'] / n['SomaItens'] * 100
                resultado.append(n)
        return sorted(resultado, key=lambda n: (n['Data'] or date.min, n['NotaID']), reverse=True)
    except Exception as e:
        logger.error(f"Erro ao listar notas com diferença: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def _itens_rateio(cursor, nota_id):
    _garantir_colunas_estoque()
    cursor.execute("SELECT NF.ValorTotalNF, NF.ValorForaDoEstoque FROM NotasFiscaisEntrada NF WHERE NF.NotaID = ?", nota_id)
    linha = cursor.fetchone()
    # [DEPURAÇÃO 2] o que não é compra paga (bonificação, comodato) não entra no rateio
    valor_nf = (_dec(linha[0]) - _dec(linha[1] or 0)) if linha else Decimal('0')
    cursor.execute("""
        SELECT INI.ItemNotaID, INI.Quantidade, INI.PrecoCustoUnitario, PF.DescricaoXML, P.NomeProduto
        FROM ItensNotaFiscalEntrada INI
        LEFT JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
        LEFT JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
        WHERE INI.NotaID = ? AND INI.Quantidade > 0
    """, nota_id)
    itens = [{'ItemNotaID': r[0], 'Quantidade': _dec(r[1]), 'CustoAtual': _dec(r[2]),
              'Descricao': r[3] or '', 'Produto': r[4] or ''} for r in cursor.fetchall()]
    soma = sum((i['Quantidade'] * i['CustoAtual'] for i in itens), Decimal('0'))
    diferenca = valor_nf - soma
    # Cada item recebe a diferença proporcional ao seu valor: custo x (valor da nota / soma dos itens).
    # Bonificação (custo zero) continua zero.
    fator = (valor_nf / soma) if soma > 0 and diferenca > 0 else Decimal('1')
    for i in itens:
        i['CustoNovo'] = (i['CustoAtual'] * fator).quantize(Decimal('0.0001'))
    return valor_nf, soma, diferenca, itens


def previa_rateio_nota(nota_id):
    """[MELHORIA ST - sem XML] Como os itens da nota ficariam depois do rateio (não grava nada)."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        return _itens_rateio(conn.cursor(), nota_id)[3]
    except Exception as e:
        logger.error(f"Erro na prévia de rateio da nota {nota_id}: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def ratear_diferenca_nas_notas(nota_ids):
    """
    [MELHORIA ST - sem XML] Reparte, nos itens de cada nota escolhida, a diferença entre o
    valor total da nota e a soma dos itens (proporcional ao valor de cada item).
    Só o CUSTO muda (quantidades iguais). Fazer de novo não muda nada: depois do ajuste a
    soma dos itens já bate com o valor da nota. Devolve (sucesso, mensagem).
    """
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        notas_ok, itens_ok, total = 0, 0, Decimal('0')
        for nota_id in nota_ids:
            valor_nf, soma, diferenca, itens = _itens_rateio(cursor, nota_id)
            if diferenca < Decimal('0.01') or soma <= 0:
                continue
            for i in itens:
                if i['CustoNovo'] != i['CustoAtual']:
                    cursor.execute("UPDATE ItensNotaFiscalEntrada SET PrecoCustoUnitario = ? WHERE ItemNotaID = ?",
                                   i['CustoNovo'], i['ItemNotaID'])
                    itens_ok += 1
            notas_ok += 1
            total += diferenca
        conn.commit()
        logger.info(f"Rateio pelo valor da nota: {notas_ok} nota(s), {itens_ok} item(ns), R$ {total:.2f} incluídos no custo.")
        return True, f"{notas_ok} nota(s) ajustada(s), {itens_ok} item(ns), R$ {_br(total, 2)} incluídos no custo."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro no rateio pelo valor da nota: {e}", exc_info=True)
        return False, f"Erro ao gravar: {e}"
    finally:
        conn.close()


# ===================================================================
# == [MELHORIA] CATÁLOGO MESTRE: resumo, edição em massa, duplicados
# ===================================================================
def resumo_catalogo():
    """
    Uma linha de resumo por produto (para as colunas do Catálogo):
    custo atual (mesma regra do Valor do Estoque, na data de HOJE), se tem compra por nota,
    última compra (data e fornecedor), fornecedor mais barato (12 meses), custo manual e a
    quantidade na última contagem em que o produto apareceu.
    """
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cursor = conn.cursor()
        hoje = date.today()
        custos, _ = _custos_por_produto(cursor, hoje)
        cursor.execute("""
            SELECT PF.ProdutoID, NF.DataEmissao, NF.NotaID, INI.Quantidade, INI.PrecoCustoUnitario, F.NomeFantasia, F.CNPJ
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
            JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
            WHERE PF.ProdutoID IS NOT NULL AND INI.Quantidade > 0
        """)
        compras = {}
        for pid, dt, nota_id, qtd, custo, forn, cnpj in cursor.fetchall():
            if (cnpj or '').strip() == CNPJ_FORNECEDOR_INTERNO:
                continue
            compras.setdefault(pid, []).append((_como_data(dt) or date.min, nota_id or 0, _dec(qtd), _dec(custo), forn or '?'))
        cursor.execute("""
            SELECT IC.ProdutoID, C.DataContagem, C.ContagemID, IC.QuantidadeContada
            FROM ItensContagemEstoque IC JOIN ContagensEstoque C ON IC.ContagemID = C.ContagemID
            WHERE IC.ProdutoID IS NOT NULL
        """)
        contagens = {}
        for pid, dt, cid, qtd in cursor.fetchall():
            chave = (_como_data(dt) or date.min, cid)
            atual = contagens.get(pid)
            if not atual or chave > atual[0]:
                contagens[pid] = (chave, _dec(qtd))
            elif chave == atual[0]:
                contagens[pid] = (chave, atual[1] + _dec(qtd))   # mesmo produto 2x na mesma contagem
        resultado = {}
        um_ano = hoje - timedelta(days=365)
        for pid in set(custos) | set(compras) | set(contagens):
            lista = compras.get(pid, [])
            ultima = max(lista) if lista else None
            por_forn = {}
            for dt, _, q, c, forn in lista:
                if dt >= um_ano and c > 0:
                    soma = por_forn.setdefault(forn, [Decimal('0'), Decimal('0')])
                    soma[0] += q * c; soma[1] += q
            barato = min(((v[0] / v[1], f) for f, v in por_forn.items() if v[1] > 0), default=None)
            info = custos.get(pid, {})
            cont = contagens.get(pid)
            resultado[pid] = {
                'TemNota': bool(lista), 'CustoAtual': info.get('custo'), 'OrigemCusto': info.get('origem', 'SEM CUSTO'),
                'UltimaCompra': ultima[0] if ultima and ultima[0] != date.min else None,
                'FornecedorUltimo': ultima[4] if ultima else None,
                'MaisBaratoFornecedor': barato[1] if barato else None, 'MaisBaratoCusto': barato[0] if barato else None,
                'QtdFornecedores': len(por_forn),
                'UltContagemData': cont[0][0] if cont and cont[0][0] != date.min else None,
                'UltContagemQtd': cont[1] if cont else None,
            }
        return resultado
    except Exception as e:
        logger.error(f"Erro ao montar o resumo do catálogo: {e}", exc_info=True)
        return {}
    finally:
        conn.close()


def atualizar_produtos_em_massa(ids, categoria=None, unidade=None, estoque_min=None):
    """Muda categoria / unidade / estoque mínimo de VÁRIOS produtos de uma vez (None = não muda)."""
    campos, valores = [], []
    if categoria is not None:
        campos.append("Categoria = ?"); valores.append(categoria)
    if unidade is not None:
        campos.append("UnidadeMedida = ?"); valores.append(unidade)
    if estoque_min is not None:
        campos.append("EstoqueMinimo = ?"); valores.append(_dec(estoque_min))
    if not campos or not ids:
        return False, "Nada para alterar."
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        for pid in ids:
            cursor.execute(f"UPDATE ProdutosEstoque SET {', '.join(campos)} WHERE ProdutoID = ?", *valores, pid)
        conn.commit()
        logger.info(f"Edição em massa: {len(ids)} produto(s) -> {', '.join(campos)}")
        return True, f"{len(ids)} produto(s) atualizado(s)."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro na edição em massa: {e}", exc_info=True)
        return False, f"Erro ao gravar: {e}"
    finally:
        conn.close()


def renomear_produtos(novos_nomes):
    """
    Renomeia produtos: novos_nomes = [(ProdutoID, 'Nome novo'), ...]. Um nome que já existe
    em outro produto é recusado (evita dois produtos com o mesmo nome).
    Devolve (quantidade_renomeada, [erros]).
    """
    conn = get_db_connection()
    if not conn:
        return 0, ["Falha de conexão com o banco de dados."]
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ProdutoID, NomeProduto FROM ProdutosEstoque")
        nomes = {r[0]: (r[1] or '') for r in cursor.fetchall()}
        ok, erros = 0, []
        for pid, novo in novos_nomes:
            novo = ' '.join(str(novo or '').split())
            if not novo:
                erros.append(f"ID {pid}: nome vazio"); continue
            conflito = next((outro for outro, n in nomes.items() if outro != pid and n.strip().lower() == novo.lower()), None)
            if conflito:
                erros.append(f"ID {pid}: '{novo}' já é o nome do produto ID {conflito} (talvez sejam duplicados: use 'Juntar')")
                continue
            cursor.execute("UPDATE ProdutosEstoque SET NomeProduto = ? WHERE ProdutoID = ?", novo, pid)
            nomes[pid] = novo
            ok += 1
        conn.commit()
        return ok, erros
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao renomear produtos: {e}", exc_info=True)
        return 0, [f"Erro ao gravar: {e}"]
    finally:
        conn.close()


def _nome_normalizado(nome):
    import unicodedata
    t = unicodedata.normalize('NFKD', str(nome or ''))
    t = ''.join(c for c in t if not unicodedata.combining(c)).lower()
    return ''.join(c for c in t if c.isalnum())


def listar_produtos_duplicados():
    """
    Grupos de produtos do Catálogo que parecem ser o MESMO produto:
      - mesmo nome (ignorando acentos, maiúsculas, espaços e pontuação); ou
      - o mesmo EAN ligado a produtos diferentes.
    Devolve [{'Grupo', 'Motivo', 'Produtos': [{ProdutoID, NomeProduto, UnidadeMedida, Categoria, Compras, Vinculos}], 'ManterID'}]
    """
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ProdutoID, NomeProduto, UnidadeMedida, Categoria FROM ProdutosEstoque")
        produtos = {r[0]: {'ProdutoID': r[0], 'NomeProduto': r[1] or '', 'UnidadeMedida': r[2] or 'UN',
                           'Categoria': r[3] or 'Geral', 'Compras': 0, 'Vinculos': 0} for r in cursor.fetchall()}
        cursor.execute("SELECT ProdutoFornecedorID, ProdutoID, EAN FROM ProdutosFornecedor WHERE ProdutoID IS NOT NULL")
        por_ean = {}
        for pf, pid, ean in cursor.fetchall():
            if pid in produtos:
                produtos[pid]['Vinculos'] += 1
                e = _ean_valido(ean)
                if e:
                    por_ean.setdefault(e, set()).add(pid)
        cursor.execute("""SELECT PF.ProdutoID, COUNT(*) FROM ItensNotaFiscalEntrada INI
                          JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
                          WHERE INI.Quantidade > 0 GROUP BY PF.ProdutoID""")
        for pid, n in cursor.fetchall():
            if pid in produtos:
                produtos[pid]['Compras'] = n

        # Junta (union-find) por nome normalizado e por EAN compartilhado
        pai = {pid: pid for pid in produtos}
        motivo = {}

        def achar(x):
            while pai[x] != x:
                pai[x] = pai[pai[x]]; x = pai[x]
            return x

        def unir(a, b, por):
            ra, rb = achar(a), achar(b)
            if ra != rb:
                pai[rb] = ra
            motivo.setdefault(a, set()).add(por)

        por_nome = {}
        for pid, p in produtos.items():
            chave = _nome_normalizado(p['NomeProduto'])
            if chave:
                por_nome.setdefault(chave, []).append(pid)
        for ids in por_nome.values():
            for outro in ids[1:]:
                unir(ids[0], outro, 'mesmo nome')
        for ean, ids in por_ean.items():
            ids = sorted(ids)
            for outro in ids[1:]:
                unir(ids[0], outro, f'mesmo EAN {ean}')
        grupos = {}
        for pid in produtos:
            grupos.setdefault(achar(pid), []).append(produtos[pid])
        resultado = []
        for raiz, lista in grupos.items():
            if len(lista) < 2:
                continue
            motivos = set()
            for p in lista:
                motivos |= motivo.get(p['ProdutoID'], set())
            lista.sort(key=lambda p: p['ProdutoID'])
            manter = max(lista, key=lambda p: (p['Compras'], p['Vinculos'], -p['ProdutoID']))
            resultado.append({'Motivo': ', '.join(sorted(motivos)), 'Produtos': lista, 'ManterID': manter['ProdutoID']})
        resultado.sort(key=lambda g: g['Produtos'][0]['NomeProduto'])
        for n, g in enumerate(resultado, start=1):
            g['Grupo'] = n
        return resultado
    except Exception as e:
        logger.error(f"Erro ao procurar produtos duplicados: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def _tabela_existe(cursor, nome):
    cursor.execute("SELECT COUNT(*) FROM sys.tables WHERE name = ?", nome)
    return int(cursor.fetchone()[0] or 0) > 0


def _trocar_produto_no_app_compras(cursor, remover_ids, manter_id=None):
    """
    Rotinas (CompraRotinaItens) e códigos de barras (CompraCodigos) do App de Compras:
    manter_id = produto que fica no lugar (juntar); None = só apaga as referências (excluir).
    """
    if _tabela_existe(cursor, 'CompraRotinaItens'):
        for rid in remover_ids:
            if manter_id is None:
                cursor.execute("DELETE FROM CompraRotinaItens WHERE ProdutoID = ?", rid)
                continue
            cursor.execute("SELECT RotinaID FROM CompraRotinaItens WHERE ProdutoID = ?", rid)
            for (rotina_id,) in cursor.fetchall():
                cursor.execute("SELECT COUNT(*) FROM CompraRotinaItens WHERE RotinaID = ? AND ProdutoID = ?", rotina_id, manter_id)
                if int(cursor.fetchone()[0] or 0):
                    cursor.execute("DELETE FROM CompraRotinaItens WHERE RotinaID = ? AND ProdutoID = ?", rotina_id, rid)
                else:
                    cursor.execute("UPDATE CompraRotinaItens SET ProdutoID = ? WHERE RotinaID = ? AND ProdutoID = ?",
                                   manter_id, rotina_id, rid)
    if _tabela_existe(cursor, 'CompraCodigos'):
        for rid in remover_ids:
            if manter_id is None:
                cursor.execute("DELETE FROM CompraCodigos WHERE ProdutoID = ?", rid)
            else:
                cursor.execute("UPDATE CompraCodigos SET ProdutoID = ? WHERE ProdutoID = ?", manter_id, rid)


def juntar_produtos(manter_id, remover_ids):
    """
    Junta produtos duplicados do Catálogo num só:
      - os vínculos (fornecedores/XML) dos removidos passam para o mantido (as compras vão junto);
      - nas contagens, a quantidade do removido é SOMADA à do mantido (ou passa para ele);
      - os produtos removidos são apagados.
    Valores de estoque já FECHADOS não mudam. Devolve (sucesso, mensagem).
    """
    remover_ids = [int(r) for r in remover_ids if int(r) != int(manter_id)]
    if not remover_ids:
        return False, "Nada para juntar."
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ProdutoID FROM ProdutosEstoque WHERE ProdutoID = ?", manter_id)
        if not cursor.fetchone():
            return False, "O produto a manter não existe mais."
        todos = [int(manter_id)] + remover_ids
        marcas = ", ".join("?" for _ in todos)
        for rid in remover_ids:
            cursor.execute("UPDATE ProdutosFornecedor SET ProdutoID = ? WHERE ProdutoID = ?", manter_id, rid)
        # [AUDITORIA ESTOQUE] Contagens: soma TUDO o que havia dos produtos juntados em cada contagem
        # numa linha só. Antes, com o mesmo produto em 2 linhas de uma contagem, a soma saía errada
        # (uma das quantidades entrava 3 vezes).
        cursor.execute(f"SELECT ContagemID, ProdutoID, QuantidadeContada FROM ItensContagemEstoque "
                       f"WHERE ProdutoID IN ({marcas})", *todos)
        por_contagem = {}
        for cid, pid, qtd in cursor.fetchall():
            info = por_contagem.setdefault(cid, {'total': Decimal('0'), 'juntar': False})
            info['total'] += _dec(qtd)
            info['juntar'] = info['juntar'] or int(pid) != int(manter_id)
        for cid, info in por_contagem.items():
            if not info['juntar']:
                continue
            cursor.execute(f"DELETE FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID IN ({marcas})", cid, *todos)
            cursor.execute("INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada, NomeAvulso, EANAvulso) "
                           "VALUES (?, ?, ?, NULL, NULL)", cid, manter_id, info['total'])
        # [AUDITORIA ESTOQUE] App de Compras: rotinas e códigos de barras apontavam para o produto
        # apagado (o item sumia da contagem do app e o código de barras parava de funcionar).
        _trocar_produto_no_app_compras(cursor, remover_ids, manter_id)
        for rid in remover_ids:
            cursor.execute("DELETE FROM ProdutosEstoque WHERE ProdutoID = ?", rid)
        conn.commit()
        logger.info(f"Produtos {remover_ids} juntados no produto {manter_id}.")
        return True, f"{len(remover_ids)} produto(s) juntado(s) no ID {manter_id}."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao juntar produtos {remover_ids} em {manter_id}: {e}", exc_info=True)
        return False, f"Erro ao juntar: {e}"
    finally:
        conn.close()


def previa_recalculo_vinculo(vinculo_id, novo_fator):
    """
    [MELHORIA] Mostra como ficariam as compras já importadas se o fator mudar.
    Devolve (fator_antigo, [ {NF, Data, QtdAtual, CustoAtual, QtdNova, CustoNovo} ]).
    """
    try:
        _garantir_colunas_estoque()
    except Exception:
        return Decimal('1'), []
    conn = get_db_connection()
    if not conn:
        return Decimal('1'), []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT FatorConversao FROM ProdutosFornecedor WHERE ProdutoFornecedorID = ?", vinculo_id)
        linha = cursor.fetchone()
        fator_vinculo = _fator_item(None, linha[0] if linha else None)
        fator_novo = _dec(novo_fator)
        cursor.execute("""
            SELECT NF.NumeroNF, NF.DataEmissao, INI.Quantidade, INI.PrecoCustoUnitario, INI.FatorConversaoUsado
            FROM ItensNotaFiscalEntrada INI
            JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
            WHERE INI.ProdutoFornecedorID = ? AND INI.Quantidade > 0
            ORDER BY NF.DataEmissao DESC
        """, vinculo_id)
        itens = []
        for nf, dt, qtd, custo, usado in cursor.fetchall():
            q, c = _dec(qtd), _dec(custo)
            antigo = _fator_item(usado, fator_vinculo)
            if fator_novo <= 0 or antigo == fator_novo:
                continue      # [DEPURAÇÃO 2] este item já está no Qtd/Cx novo: não muda
            itens.append({'NF': nf, 'Data': _como_data(dt), 'QtdAtual': q, 'CustoAtual': c, 'FatorAntigo': antigo,
                          'QtdNova': q * fator_novo / antigo, 'CustoNovo': c * antigo / fator_novo})
        return fator_vinculo, itens
    except Exception as e:
        logger.error(f"Erro na prévia de recálculo do vínculo {vinculo_id}: {e}", exc_info=True)
        return Decimal('1'), []
    finally:
        conn.close()

def vinculo_tem_itens(vinculo_id):
    """Quantos itens de nota (inclusive o custo manual, de quantidade 0) usam o vínculo."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ItensNotaFiscalEntrada WHERE ProdutoFornecedorID = ?", vinculo_id)
        return int(cursor.fetchone()[0] or 0)
    finally:
        conn.close()


def excluir_vinculo_existente(vinculo_id):
    """Exclui um vínculo DE/PARA (recusa se algum item de nota ainda usa o vínculo)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # [DEPURAÇÃO 2] Itens de nota apontando para um vínculo apagado somem do estoque
            # (inclusive o custo manual do Catálogo, que é uma "nota" de quantidade 0).
            cursor.execute("SELECT COUNT(*) FROM ItensNotaFiscalEntrada WHERE ProdutoFornecedorID = ?", vinculo_id)
            if int(cursor.fetchone()[0] or 0) > 0:
                logger.warning(f"Exclusão do vínculo {vinculo_id} recusada: ainda há itens de nota usando-o.")
                return False
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
    # [DEPURAÇÃO] Era 'return [],' (vírgula sobrando = UMA lista só). O main.py faz
    # '_, disponiveis = ...' e quebrava quando o banco estava fora do ar.
    return [], []

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

# ==============================================================================
# == [MELHORIA ESCALA] PAGAMENTO DE FREELANCERS ================================
# ==============================================================================
# Regras da loja (todas editáveis em "⚙️ Valores"):
#   Diária LONGA = 8h20 na loja (7h20 de trabalho + 1h de intervalo remunerado)
#       seg a sáb R$ 100,00  ·  domingo/feriado R$ 130,00
#   Diária CURTA = 6h00 na loja (com 15 min de descanso)
#       seg a sáb R$ 80,00   ·  domingo/feriado R$ 100,00
#   Hora extra: seg a sáb R$ 12,00/h · domingo/feriado R$ 16,25/h (130 ÷ 8),
#       contada em BLOCOS de 20 min completos (19 min a mais não contam).
#   Tipo da diária: vem da ESCALA planejada (até 7h = curta; mais = longa),
#       e pode ser trocado na correção do turno.
#   Saiu mais cedo: paga só o tempo trabalhado (proporcional ao minuto).
#   O intervalo é remunerado: conta-se só entrada -> saída.
#   Ao marcar como PAGO os valores ficam "congelados".
_tabelas_pagamento_ok = False
_CENTAVO = Decimal('0.01')

CONFIG_PAGAMENTO_PADRAO = {
    'DiariaLongaSemana': Decimal('100'), 'DiariaCurtaSemana': Decimal('80'),
    'DiariaLongaDomingo': Decimal('130'), 'DiariaCurtaDomingo': Decimal('100'),
    'MinutosLonga': 500, 'MinutosCurta': 360,
    'HoraExtraSemana': Decimal('12'), 'HoraExtraDomingo': Decimal('16.25'),
    'BlocoExtraMinutos': 20, 'LimiteCurtaMinutos': 420,
}
_CHAVES_INTEIRAS = ('MinutosLonga', 'MinutosCurta', 'BlocoExtraMinutos', 'LimiteCurtaMinutos')


def _garantir_tabelas_pagamento_freelancer():
    """Cria (uma vez, com COMMIT) as tabelas de valores, feriados e pagamentos."""
    global _tabelas_pagamento_ok
    if _tabelas_pagamento_ok:
        return
    conn = get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ParametrosPagamentoFreelancer')
            CREATE TABLE ParametrosPagamentoFreelancer (
                Chave NVARCHAR(50) PRIMARY KEY,
                Valor DECIMAL(12, 4) NOT NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FeriadosLoja')
            CREATE TABLE FeriadosLoja (
                DataFeriado DATE PRIMARY KEY,
                Nome NVARCHAR(100) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'PagamentosFreelancer')
            CREATE TABLE PagamentosFreelancer (
                PagamentoID INT IDENTITY(1,1) PRIMARY KEY,
                EscalaID INT NULL,
                DataEscala DATE NOT NULL,
                FreelancerID INT NULL,
                NomeFreelancer NVARCHAR(150) NULL,
                NomePosicao NVARCHAR(100) NULL,
                EntradaEscala VARCHAR(5) NULL,
                SaidaEscala VARCHAR(5) NULL,
                EntradaReal VARCHAR(5) NULL,
                SaidaReal VARCHAR(5) NULL,
                TipoDiaria NVARCHAR(10) NULL,
                TipoDia NVARCHAR(10) NULL,
                Horas DECIMAL(6, 2) NULL,
                HorasExtras DECIMAL(6, 2) NULL,
                ValorDiaria DECIMAL(10, 2) NULL,
                ValorHoraExtra DECIMAL(10, 2) NULL,
                ValorExtras DECIMAL(10, 2) NULL,
                Ajuste DECIMAL(10, 2) NOT NULL DEFAULT 0,
                ValorTotal DECIMAL(10, 2) NULL,
                Pago BIT NOT NULL DEFAULT 0,
                DataPagamento DATE NULL,
                FormaPagamento NVARCHAR(30) NULL,
                Observacao NVARCHAR(300) NULL,
                AtualizadoEm DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)
        # Quem já abriu a versão anterior tem a tabela sem estas 2 colunas: acrescenta.
        cur.execute("SELECT * FROM PagamentosFreelancer WHERE 1 = 0")
        existentes = {d[0].lower() for d in (cur.description or [])}
        for coluna in ('TipoDiaria', 'TipoDia'):
            if coluna.lower() not in existentes:
                cur.execute(f"ALTER TABLE PagamentosFreelancer ADD {coluna} NVARCHAR(10) NULL")
        # [DIÁRIA NA ESCALA] O gestor escolhe CURTA ou LONGA ao escalar o freelancer
        # (NULL = automático pela duração, como nos turnos antigos).
        cur.execute("IF COL_LENGTH('EscalaDiaria', 'TipoDiaria') IS NULL "
                    "ALTER TABLE EscalaDiaria ADD TipoDiaria NVARCHAR(10) NULL")
        conn.commit()
        _tabelas_pagamento_ok = True
        logger.info("Tabelas de pagamento de freelancers verificadas/criadas.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao criar as tabelas de pagamento de freelancers: {e}", exc_info=True)
        raise
    finally:
        conn.close()


def buscar_config_pagamento_freelancer():
    """Valores atuais (os padrões da loja, se nunca foram alterados)."""
    _garantir_tabelas_pagamento_freelancer()
    cfg = dict(CONFIG_PAGAMENTO_PADRAO)
    conn = get_db_connection()
    if not conn:
        return cfg
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Chave, Valor FROM ParametrosPagamentoFreelancer")
        for chave, valor in cursor.fetchall():
            if chave in cfg:
                cfg[chave] = int(_dec(valor)) if chave in _CHAVES_INTEIRAS else _dec(valor).quantize(_CENTAVO)
        return cfg
    finally:
        conn.close()


def salvar_config_pagamento_freelancer(novos):
    """Grava os valores (vale para os turnos AINDA NÃO PAGOS). Devolve (ok, mensagem)."""
    cfg = dict(CONFIG_PAGAMENTO_PADRAO)
    for chave in cfg:
        if chave in novos and novos[chave] is not None:
            cfg[chave] = int(novos[chave]) if chave in _CHAVES_INTEIRAS else _dec(novos[chave]).quantize(_CENTAVO)
    if any(_dec(v) < 0 for v in cfg.values()):
        return False, "Os valores não podem ser negativos."
    if not (0 < cfg['MinutosCurta'] < cfg['MinutosLonga'] <= 24 * 60):
        return False, "O tempo da diária curta precisa ser menor que o da longa (e a longa até 24h)."
    if not (cfg['MinutosCurta'] <= cfg['LimiteCurtaMinutos'] < cfg['MinutosLonga']):
        return False, "O limite 'até X horas na escala = curta' precisa ficar entre a curta e a longa."
    if not (1 <= cfg['BlocoExtraMinutos'] <= 120):
        return False, "O bloco da hora extra precisa ter entre 1 e 120 minutos."
    _garantir_tabelas_pagamento_freelancer()
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ParametrosPagamentoFreelancer")
        for chave, valor in cfg.items():
            cursor.execute("INSERT INTO ParametrosPagamentoFreelancer (Chave, Valor) VALUES (?, ?)", chave, _dec(valor))
        conn.commit()
        return True, "Valores salvos."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao salvar valores de pagamento: {e}", exc_info=True)
        return False, f"Erro ao salvar: {e}"
    finally:
        conn.close()


# ---------------------------- FERIADOS ----------------------------
def _pascoa(ano):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano):
    """Feriados nacionais (lei federal) do ano: [(data, nome)]. Municipais/estaduais: cadastre à mão."""
    pascoa = _pascoa(ano)
    lista = [(date(ano, 1, 1), "Confraternização Universal"), (pascoa - timedelta(days=2), "Sexta-feira Santa"),
             (date(ano, 4, 21), "Tiradentes"), (date(ano, 5, 1), "Dia do Trabalho"),
             (date(ano, 9, 7), "Independência do Brasil"), (date(ano, 10, 12), "Nossa Senhora Aparecida"),
             (date(ano, 11, 2), "Finados"), (date(ano, 11, 15), "Proclamação da República"),
             (date(ano, 12, 25), "Natal")]
    if ano >= 2024:
        lista.append((date(ano, 11, 20), "Dia Nacional de Zumbi e da Consciência Negra"))
    return sorted(lista)


def listar_feriados(ano=None):
    """[(data, nome)] cadastrados (de um ano ou todos)."""
    _garantir_tabelas_pagamento_freelancer()
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        if ano:
            cursor.execute("SELECT DataFeriado, Nome FROM FeriadosLoja WHERE DataFeriado >= ? AND DataFeriado <= ?",
                           f"{int(ano)}-01-01", f"{int(ano)}-12-31")
        else:
            cursor.execute("SELECT DataFeriado, Nome FROM FeriadosLoja")
        return sorted((_como_data(d), n or '') for d, n in cursor.fetchall())
    finally:
        conn.close()


def salvar_feriados(lista):
    """Cadastra (ou renomeia) feriados: lista de (data, nome). Devolve (ok, mensagem)."""
    _garantir_tabelas_pagamento_freelancer()
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        novos = 0
        for dt, nome in lista:
            dt = _como_data(dt)
            if not dt:
                continue
            cursor.execute("SELECT 1 FROM FeriadosLoja WHERE DataFeriado = ?", dt)
            if cursor.fetchone():
                cursor.execute("UPDATE FeriadosLoja SET Nome = ? WHERE DataFeriado = ?", (nome or '')[:100], dt)
            else:
                cursor.execute("INSERT INTO FeriadosLoja (DataFeriado, Nome) VALUES (?, ?)", dt, (nome or '')[:100])
                novos += 1
        conn.commit()
        return True, f"{novos} feriado(s) novo(s) cadastrado(s)."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao salvar feriados: {e}", exc_info=True)
        return False, f"Erro ao salvar: {e}"
    finally:
        conn.close()


def excluir_feriado(data_feriado):
    _garantir_tabelas_pagamento_freelancer()
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM FeriadosLoja WHERE DataFeriado = ?", _como_data(data_feriado))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao excluir feriado: {e}", exc_info=True)
        return False
    finally:
        conn.close()


def nome_feriado(data_escala):
    """Nome do feriado da data (ou None)."""
    d = _como_data(data_escala)
    return next((n or 'Feriado' for dt, n in listar_feriados(d.year) if dt == d), None) if d else None


# ---------------------------- CÁLCULO ----------------------------
def _hhmm(valor):
    """time / datetime / timedelta / 'HH:MM[:SS]' -> 'HH:MM' (ou None)."""
    if valor is None or valor == '':
        return None
    if isinstance(valor, timedelta):
        minutos = int(valor.total_seconds() // 60) % (24 * 60)
        return f"{minutos // 60:02d}:{minutos % 60:02d}"
    if hasattr(valor, 'strftime'):
        return valor.strftime('%H:%M')
    texto = str(valor).strip()
    if len(texto) >= 16 and texto[10] in ' T':      # '1900-01-01 08:00:00'
        texto = texto[11:]
    partes = texto.split(':')
    try:
        h, m = int(partes[0]), int(partes[1])
    except (ValueError, IndexError):
        return None
    return f"{h:02d}:{m:02d}" if 0 <= h < 24 and 0 <= m < 60 else None


def _minutos_turno(entrada, saida):
    ent, sai = _hhmm(entrada), _hhmm(saida)
    if not ent or not sai:
        return None
    minutos = (int(sai[:2]) * 60 + int(sai[3:])) - (int(ent[:2]) * 60 + int(ent[3:]))
    return minutos + 24 * 60 if minutos <= 0 else minutos      # passou da meia-noite


def calcular_pagamento_turno(entrada, saida, config_pag, ajuste=0, data_escala=None, tipo=None,
                             entrada_escala=None, saida_escala=None, feriado=None):
    """
    Calcula o pagamento de UM turno de freelancer.
      entrada/saida: horário usado no pagamento (o real, se corrigido; senão o da escala)
      entrada_escala/saida_escala: horário PLANEJADO (decide se a diária é longa ou curta)
      tipo: 'longa' / 'curta' para forçar; None = automático pela escala
      feriado: nome do feriado (ou None). Domingo e feriado usam os valores de domingo.
    Devolve dicionário (Decimals) ou None se faltar horário.
    """
    minutos = _minutos_turno(entrada, saida)
    if minutos is None:
        return None
    cfg = dict(CONFIG_PAGAMENTO_PADRAO, **(config_pag or {}))
    d = _como_data(data_escala)
    if feriado:
        dia = 'Feriado'
    elif d and d.weekday() == 6:
        dia = 'Domingo'
    else:
        dia = 'Semana'
    planejado = _minutos_turno(entrada_escala, saida_escala) or minutos
    if tipo not in ('longa', 'curta'):
        tipo = 'curta' if planejado <= int(cfg['LimiteCurtaMinutos']) else 'longa'
    sufixo = 'Semana' if dia == 'Semana' else 'Domingo'
    diaria = _dec(cfg[f"Diaria{tipo.capitalize()}{sufixo}"]).quantize(_CENTAVO)
    limite = int(cfg['MinutosLonga'] if tipo == 'longa' else cfg['MinutosCurta'])
    valor_hora_extra = _dec(cfg[f"HoraExtra{sufixo}"])
    bloco = max(int(cfg['BlocoExtraMinutos']), 1)
    proporcional = minutos < limite
    if proporcional:
        base = (diaria * minutos / limite).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
        extras_brutos = extras = 0
    else:
        base = diaria
        extras_brutos = minutos - limite
        extras = (extras_brutos // bloco) * bloco               # só blocos COMPLETOS
    valor_extras = (Decimal(extras) / 60 * valor_hora_extra).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
    ajuste = _dec(ajuste).quantize(_CENTAVO)
    return {'Minutos': minutos, 'Horas': (Decimal(minutos) / 60).quantize(_CENTAVO),
            'Tipo': tipo, 'Dia': dia, 'Feriado': feriado, 'MinutosDiaria': limite, 'DiariaCheia': diaria,
            'Proporcional': proporcional, 'ValorDiaria': base,
            'MinutosExtrasBrutos': extras_brutos, 'MinutosExtras': extras,
            'HorasExtras': (Decimal(extras) / 60).quantize(_CENTAVO), 'ValorHoraExtra': valor_hora_extra,
            'BlocoMinutos': bloco, 'ValorExtras': valor_extras, 'Ajuste': ajuste,
            'Total': base + valor_extras + ajuste}


def _linhas_pagamento_salvas(cursor, data_ini=None, data_fim=None):
    nomes = ['PagamentoID', 'EscalaID', 'DataEscala', 'FreelancerID', 'NomeFreelancer', 'NomePosicao', 'EntradaEscala',
             'SaidaEscala', 'EntradaReal', 'SaidaReal', 'TipoDiaria', 'TipoDia', 'Horas', 'HorasExtras', 'ValorDiaria',
             'ValorHoraExtra', 'ValorExtras', 'Ajuste', 'ValorTotal', 'Pago', 'DataPagamento', 'FormaPagamento', 'Observacao']
    sql = f"SELECT {', '.join(nomes)} FROM PagamentosFreelancer"
    params = []
    if data_ini and data_fim:
        sql += " WHERE DataEscala >= ? AND DataEscala <= ?"
        params = [str(data_ini), str(data_fim)]
    cursor.execute(sql, *params)
    return [dict(zip(nomes, r)) for r in cursor.fetchall()]


def _feriados_periodo(data_ini, data_fim):
    anos = range(data_ini.year, data_fim.year + 1)
    return {d: n for ano in anos for d, n in listar_feriados(ano)}


def listar_pagamentos_freelancers(data_ini, data_fim, freelancer_id=None, status='todos'):
    """
    [MELHORIA ESCALA] Um item por TURNO de freelancer no período, com o valor a pagar.
      - Pendente: calculado AGORA (valores atuais, horário real e tipo de diária corrigidos).
      - Pago: valores congelados no dia do pagamento (aparece mesmo se o turno foi excluído).
    status: 'todos' | 'pendentes' | 'pagos'. Ordenado por data e nome.
    """
    _garantir_tabelas_pagamento_freelancer()
    data_ini, data_fim = _como_data(data_ini), _como_data(data_fim)
    cfg = buscar_config_pagamento_freelancer()
    feriados = _feriados_periodo(data_ini, data_fim)
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT E.EscalaID, E.DataEscala, E.FreelancerID, FR.Nome, PL.NomePosicao, E.HorarioEntrada, E.HorarioSaida,
                   E.TipoDiaria
            FROM EscalaDiaria E
            JOIN Freelancers FR ON E.FreelancerID = FR.FreelancerID
            LEFT JOIN PosicoesLoja PL ON E.PosicaoID = PL.PosicaoID
            WHERE E.FreelancerID IS NOT NULL AND E.DataEscala >= ? AND E.DataEscala <= ?
        """, str(data_ini), str(data_fim))
        turnos = {r[0]: r for r in cursor.fetchall()}
        salvos = _linhas_pagamento_salvas(cursor, data_ini, data_fim)
        por_escala = {s['EscalaID']: s for s in salvos if s['EscalaID'] is not None}

        itens = []
        for escala_id, (eid, dt, fid, nome, posicao, ent, sai, tipo_escala) in turnos.items():
            s = por_escala.get(escala_id) or {}
            if s.get('Pago'):
                continue                       # entra abaixo, pelos valores congelados
            d = _como_data(dt)
            ent_real, sai_real = s.get('EntradaReal'), s.get('SaidaReal')
            ajuste = _dec(s.get('Ajuste') or 0)
            tipo_forcado = s.get('TipoDiaria') if s.get('TipoDiaria') in ('longa', 'curta') else None
            tipo_escala = tipo_escala if tipo_escala in ('longa', 'curta') else None
            calc = calcular_pagamento_turno(ent_real or ent, sai_real or sai, cfg, ajuste, d, tipo_forcado or tipo_escala,
                                            ent, sai, feriados.get(d))
            itens.append({
                'PagamentoID': s.get('PagamentoID'), 'EscalaID': escala_id, 'Data': d,
                'FreelancerID': fid, 'Nome': nome or '?', 'Posicao': posicao or '', 'EntradaEscala': _hhmm(ent),
                'SaidaEscala': _hhmm(sai), 'EntradaReal': _hhmm(ent_real), 'SaidaReal': _hhmm(sai_real),
                'Corrigido': bool(ent_real or sai_real), 'TipoForcado': tipo_forcado, 'TipoEscala': tipo_escala,
                'Calculo': calc, 'Ajuste': ajuste,
                'Total': calc['Total'] if calc else ajuste, 'Pago': False, 'DataPagamento': None,
                'FormaPagamento': None, 'Observacao': s.get('Observacao') or '', 'TurnoExcluido': False,
                'SemHorario': calc is None, 'Feriado': feriados.get(d)})
        for s in salvos:
            if not s['Pago']:
                continue
            d = _como_data(s['DataEscala'])
            calc = {'Horas': _dec(s['Horas']), 'HorasExtras': _dec(s['HorasExtras']), 'Tipo': s['TipoDiaria'] or '',
                    'Dia': s['TipoDia'] or '', 'ValorDiaria': _dec(s['ValorDiaria']), 'ValorExtras': _dec(s['ValorExtras']),
                    'ValorHoraExtra': _dec(s['ValorHoraExtra']), 'Ajuste': _dec(s['Ajuste']), 'Total': _dec(s['ValorTotal']),
                    'Minutos': int((_dec(s['Horas']) * 60).to_integral_value()),
                    'MinutosExtras': int((_dec(s['HorasExtras']) * 60).to_integral_value()), 'Proporcional': False}
            itens.append({
                'PagamentoID': s['PagamentoID'], 'EscalaID': s['EscalaID'], 'Data': d,
                'FreelancerID': s['FreelancerID'], 'Nome': s['NomeFreelancer'] or '?', 'Posicao': s['NomePosicao'] or '',
                'EntradaEscala': s['EntradaEscala'], 'SaidaEscala': s['SaidaEscala'], 'EntradaReal': s['EntradaReal'],
                'SaidaReal': s['SaidaReal'], 'Corrigido': bool(s['EntradaReal'] or s['SaidaReal']),
                'TipoForcado': None, 'Calculo': calc,
                'Ajuste': _dec(s['Ajuste']), 'Total': _dec(s['ValorTotal']), 'Pago': True,
                'DataPagamento': _como_data(s['DataPagamento']), 'FormaPagamento': s['FormaPagamento'] or '',
                'Observacao': s['Observacao'] or '', 'TurnoExcluido': s['EscalaID'] not in turnos, 'SemHorario': False,
                'Feriado': feriados.get(d)})
        if freelancer_id is not None:
            itens = [i for i in itens if i['FreelancerID'] == freelancer_id]
        if status == 'pendentes':
            itens = [i for i in itens if not i['Pago']]
        elif status == 'pagos':
            itens = [i for i in itens if i['Pago']]
        itens.sort(key=lambda i: (i['Data'] or date.min, str(i['Nome']).lower(), i['EntradaEscala'] or ''))
        return itens
    except Exception as e:
        logger.error(f"Erro ao listar pagamentos de freelancers: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def tipo_diaria_da_escala(cursor, escala_id):
    """'curta' / 'longa' escolhido na escala para o turno (None = automático)."""
    cursor.execute("SELECT TipoDiaria FROM EscalaDiaria WHERE EscalaID = ?", escala_id)
    r = cursor.fetchone()
    return r[0] if r and r[0] in ('longa', 'curta') else None


def definir_tipo_diaria_escala(escala_id, tipo):
    """
    [DIÁRIA NA ESCALA] Grava a diária escolhida pelo gestor no turno ('curta' / 'longa' / None).
    Turno já PAGO não muda (o valor pago fica congelado). Devolve (ok, mensagem).
    """
    _garantir_tabelas_pagamento_freelancer()
    tipo = tipo if tipo in ('longa', 'curta') else None
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM PagamentosFreelancer WHERE EscalaID = ? AND Pago = 1", escala_id)
        if cursor.fetchone():
            return False, "Turno já pago: a diária não foi alterada."
        cursor.execute("UPDATE EscalaDiaria SET TipoDiaria = ? WHERE EscalaID = ?", tipo, escala_id)
        conn.commit()
        return True, "Diária gravada."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao gravar a diária do turno {escala_id}: {e}", exc_info=True)
        return False, f"Erro ao gravar a diária: {e}"
    finally:
        conn.close()


def _turno_freelancer(cursor, escala_id):
    cursor.execute("""
        SELECT E.EscalaID, E.DataEscala, E.FreelancerID, FR.Nome, PL.NomePosicao, E.HorarioEntrada, E.HorarioSaida
        FROM EscalaDiaria E
        JOIN Freelancers FR ON E.FreelancerID = FR.FreelancerID
        LEFT JOIN PosicoesLoja PL ON E.PosicaoID = PL.PosicaoID
        WHERE E.EscalaID = ?
    """, escala_id)
    return cursor.fetchone()


def salvar_correcao_pagamento(escala_id, entrada_real=None, saida_real=None, ajuste=0, observacao='', tipo_diaria=None):
    """
    Guarda, para um turno AINDA NÃO PAGO: o horário REAL (se diferente da escala), o tipo
    de diária ('longa'/'curta'; None = automático), um ajuste em R$ (+ bônus / - desconto)
    e uma observação. Devolve (ok, mensagem).
    """
    _garantir_tabelas_pagamento_freelancer()
    ent, sai = _hhmm(entrada_real), _hhmm(saida_real)
    if bool(ent) != bool(sai):
        return False, "Preencha a entrada E a saída reais (ou deixe as duas vazias para usar a escala)."
    tipo_diaria = tipo_diaria if tipo_diaria in ('longa', 'curta') else None
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        turno = _turno_freelancer(cursor, escala_id)
        if not turno:
            return False, "Turno de freelancer não encontrado (foi excluído da escala?)."
        cursor.execute("SELECT PagamentoID, Pago FROM PagamentosFreelancer WHERE EscalaID = ?", escala_id)
        existente = cursor.fetchone()
        if existente and existente[1]:
            return False, "Este turno já está PAGO. Desfaça o pagamento antes de corrigir."
        obs = (observacao or '').strip()[:300] or None
        if existente:
            cursor.execute("UPDATE PagamentosFreelancer SET EntradaReal = ?, SaidaReal = ?, Ajuste = ?, Observacao = ?, "
                           "TipoDiaria = ?, AtualizadoEm = GETDATE() WHERE PagamentoID = ?",
                           ent, sai, _dec(ajuste), obs, tipo_diaria, existente[0])
        else:
            cursor.execute("INSERT INTO PagamentosFreelancer (EscalaID, DataEscala, FreelancerID, NomeFreelancer, NomePosicao, "
                           "EntradaReal, SaidaReal, Ajuste, Observacao, TipoDiaria, Pago) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                           escala_id, _como_data(turno[1]), turno[2], turno[3], turno[4], ent, sai, _dec(ajuste), obs, tipo_diaria)
        conn.commit()
        return True, "Correção salva."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao salvar correção de pagamento: {e}", exc_info=True)
        return False, f"Erro ao salvar: {e}"
    finally:
        conn.close()


def marcar_pagamentos_pagos(escala_ids, data_pagamento=None, forma_pagamento=''):
    """
    Marca os turnos como PAGOS, congelando os valores calculados agora.
    Tudo numa transação (ou paga todos, ou nenhum). Devolve (ok, mensagem, total_pago).
    """
    _garantir_tabelas_pagamento_freelancer()
    if not escala_ids:
        return False, "Nenhum turno selecionado.", Decimal('0')
    cfg = buscar_config_pagamento_freelancer()
    data_pagamento = _como_data(data_pagamento) or date.today()
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados.", Decimal('0')
    try:
        cursor = conn.cursor()
        total = Decimal('0')
        for escala_id in escala_ids:
            turno = _turno_freelancer(cursor, escala_id)
            if not turno:
                raise ValueError(f"Turno {escala_id} não encontrado (foi excluído da escala?).")
            eid, dt, fid, nome, posicao, ent, sai = turno
            d = _como_data(dt)
            cursor.execute("SELECT PagamentoID, Pago, EntradaReal, SaidaReal, Ajuste, TipoDiaria FROM PagamentosFreelancer "
                           "WHERE EscalaID = ?", escala_id)
            s = cursor.fetchone()
            if s and s[1]:
                raise ValueError(f"O turno de {nome} em {d.strftime('%d/%m/%Y')} já está pago.")
            ent_real, sai_real, ajuste, tipo = (s[2], s[3], _dec(s[4]), s[5]) if s else (None, None, Decimal('0'), None)
            if tipo not in ('longa', 'curta'):
                tipo = tipo_diaria_da_escala(cursor, escala_id)
            calc = calcular_pagamento_turno(ent_real or ent, sai_real or sai, cfg, ajuste, d, tipo, ent, sai, nome_feriado(d))
            if not calc:
                raise ValueError(f"O turno de {nome} em {d.strftime('%d/%m/%Y')} está sem horário de entrada/saída.")
            valores = (_hhmm(ent), _hhmm(sai), calc['Tipo'], calc['Dia'], calc['Horas'], calc['HorasExtras'],
                       calc['ValorDiaria'], calc['ValorHoraExtra'].quantize(_CENTAVO), calc['ValorExtras'], calc['Total'],
                       data_pagamento, (forma_pagamento or '')[:30] or None)
            if s:
                cursor.execute("UPDATE PagamentosFreelancer SET EntradaEscala = ?, SaidaEscala = ?, TipoDiaria = ?, TipoDia = ?, "
                               "Horas = ?, HorasExtras = ?, ValorDiaria = ?, ValorHoraExtra = ?, ValorExtras = ?, ValorTotal = ?, "
                               "Pago = 1, DataPagamento = ?, FormaPagamento = ?, NomeFreelancer = ?, NomePosicao = ?, "
                               "AtualizadoEm = GETDATE() WHERE PagamentoID = ?", *valores, nome, posicao, s[0])
            else:
                cursor.execute("INSERT INTO PagamentosFreelancer (EntradaEscala, SaidaEscala, TipoDiaria, TipoDia, Horas, "
                               "HorasExtras, ValorDiaria, ValorHoraExtra, ValorExtras, ValorTotal, DataPagamento, FormaPagamento, "
                               "Pago, EscalaID, DataEscala, FreelancerID, NomeFreelancer, NomePosicao, Ajuste) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 0)",
                               *valores, escala_id, d, fid, nome, posicao)
            total += calc['Total']
        conn.commit()
        logger.info(f"{len(escala_ids)} turno(s) de freelancer marcados como pagos ({_br(total)}).")
        return True, f"{len(escala_ids)} turno(s) marcados como pagos.", total
    except ValueError as e:
        conn.rollback()
        return False, str(e), Decimal('0')
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao marcar pagamentos: {e}", exc_info=True)
        return False, f"Erro ao gravar: {e}", Decimal('0')
    finally:
        conn.close()


def desfazer_pagamentos(pagamento_ids):
    """Volta os pagamentos para PENDENTE (mantém o horário real e o ajuste). Devolve (ok, mensagem)."""
    _garantir_tabelas_pagamento_freelancer()
    if not pagamento_ids:
        return False, "Nenhum pagamento selecionado."
    conn = get_db_connection()
    if not conn:
        return False, "Falha de conexão com o banco de dados."
    try:
        cursor = conn.cursor()
        for pid in pagamento_ids:
            cursor.execute("UPDATE PagamentosFreelancer SET Pago = 0, DataPagamento = NULL, FormaPagamento = NULL, "
                           "AtualizadoEm = GETDATE() WHERE PagamentoID = ?", pid)
        # Pagamento de turno que já foi EXCLUÍDO da escala não tem mais o que pagar: some.
        cursor.execute("DELETE FROM PagamentosFreelancer WHERE Pago = 0 AND (EscalaID IS NULL OR EscalaID NOT IN "
                       "(SELECT EscalaID FROM EscalaDiaria))")
        conn.commit()
        return True, f"{len(pagamento_ids)} pagamento(s) desfeito(s)."
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao desfazer pagamentos: {e}", exc_info=True)
        return False, f"Erro ao gravar: {e}"
    finally:
        conn.close()


def turnos_pagos(escala_ids=None, data_escala=None):
    """EscalaIDs que já estão PAGOS (de uma lista de turnos ou de um dia inteiro)."""
    try:
        _garantir_tabelas_pagamento_freelancer()
    except Exception:
        return set()
    conn = get_db_connection()
    if not conn:
        return set()
    try:
        cursor = conn.cursor()
        if data_escala is not None:
            cursor.execute("SELECT EscalaID FROM PagamentosFreelancer WHERE Pago = 1 AND DataEscala = ?", str(_como_data(data_escala)))
        else:
            cursor.execute("SELECT EscalaID FROM PagamentosFreelancer WHERE Pago = 1")
        pagos = {r[0] for r in cursor.fetchall() if r[0] is not None}
        return pagos if escala_ids is None else {e for e in pagos if e in {int(x) for x in escala_ids}}
    except Exception as e:
        logger.error(f"Erro ao consultar turnos pagos: {e}", exc_info=True)
        return set()
    finally:
        conn.close()


def total_pendente_por_freelancer(ate=None):
    """{FreelancerID: (qtd_turnos, total)} do que ainda falta pagar até a data (padrão: hoje)."""
    ate = _como_data(ate) or date.today()
    resumo = {}
    for i in listar_pagamentos_freelancers(date(2000, 1, 1), ate, status='pendentes'):
        qtd, total = resumo.get(i['FreelancerID'], (0, Decimal('0')))
        resumo[i['FreelancerID']] = (qtd + 1, total + i['Total'])
    return resumo


def copiar_escala_dia(data_origem, data_destino):
    """
    Copia todos os turnos de um dia específico para outro dia.
    Substitui a escala do dia de destino caso ela já exista.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # 1. Verifica se existe algo para copiar
            cursor.execute("SELECT COUNT(*) FROM EscalaDiaria WHERE DataEscala = ?", data_origem)
            if cursor.fetchone()[0] == 0:
                return False, "Nenhuma escala encontrada na data de origem selecionada."

            # [MELHORIA ESCALA] Não apaga um dia que já tem freelancer PAGO (o turno copiado
            # apareceria de novo como "a pagar" e o freelancer poderia receber 2 vezes).
            if turnos_pagos(data_escala=data_destino):
                return False, ("Este dia já tem turno de freelancer PAGO. Copiar apagaria a escala dele.\n\n"
                               "Desfaça o pagamento em '💰 Pagamentos' ou ajuste a escala à mão.")

            # 2. Limpa o dia de destino para não encavalar turnos
            cursor.execute("DELETE FROM EscalaDiaria WHERE DataEscala = ?", data_destino)

            # 3. Copia tudo em uma única transação usando SELECT INSERT
            # [DIÁRIA NA ESCALA] a diária escolhida (curta/longa) vai junto na cópia
            sql_copy = """
                INSERT INTO EscalaDiaria 
                (DataEscala, PosicaoID, FuncionarioID, FreelancerID, HorarioEntrada, HorarioSaida, InicioIntervalo, FimIntervalo, FocoDoDia, TipoDiaria)
                SELECT ?, PosicaoID, FuncionarioID, FreelancerID, HorarioEntrada, HorarioSaida, InicioIntervalo, FimIntervalo, FocoDoDia, TipoDiaria
                FROM EscalaDiaria 
                WHERE DataEscala = ?
            """
            cursor.execute(sql_copy, data_destino, data_origem)
            conn.commit()
            return True, "Escala copiada com sucesso!"
        except Exception as e:
            logger.error(f"Erro ao copiar escala de {data_origem} para {data_destino}: {e}", exc_info=True)
            conn.rollback()
            return False, f"Erro interno no banco de dados: {e}"
        finally:
            conn.close()
    return False, "Erro de conexão com o banco de dados."

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

def atualizar_status_solicitacao(solicitacao_id, novo_status, motivo=None, status_esperado=None):
    """
    status_esperado: se informado (ex: 'Pendente'), só muda se a solicitação ainda estiver
    nesse status. Devolve False se outra pessoa (ou o bot) já tinha decidido antes.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE SolicitacoesInternas SET Status = ?, MotivoRecusa = ?, DataConclusao = GETDATE() WHERE SolicitacaoID = ?"
            params = [novo_status, motivo, solicitacao_id]
            if status_esperado:
                sql += " AND Status = ?"
                params.append(status_esperado)
            cursor.execute(sql, *params)
            if status_esperado and getattr(cursor, 'rowcount', 1) == 0:
                conn.rollback()
                return False
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
        # [DEPURAÇÃO] A tabela Funcionarios não tem coluna 'Ativo' (o sistema exclui o
        # funcionário em vez de desativar), então a consulta sempre falhava e a lista
        # voltava vazia. Se um dia a coluna existir, ela é usada; senão, lista todos.
        cursor.execute("SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('Funcionarios') AND name = 'Ativo'")
        filtro_ativo = "WHERE Ativo = 1" if cursor.fetchone() else ""
        cursor.execute(f"""
            SELECT FuncionarioID, NomeCompleto, Cargo
            FROM Funcionarios
            {filtro_ativo}
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

        # [DEPURAÇÃO] As colunas se chamam InicioIntervalo/FimIntervalo (como no resto
        # do arquivo). Com IntervaloInicio/IntervaloFim o UPDATE sempre falhava.
        cursor.execute("""
            UPDATE EscalaDiaria
            SET HorarioEntrada = ?, HorarioSaida = ?, InicioIntervalo = ?, FimIntervalo = ?
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

        # [DEPURAÇÃO] EscalaDiaria não tem coluna 'Setor': ela guarda a POSIÇÃO (PosicaoID),
        # e o setor fica em PosicoesLoja. Agora escolhemos uma posição ativa daquele setor.
        cursor.execute("SELECT TOP 1 PosicaoID FROM PosicoesLoja WHERE Setor = ? AND Ativo = 1 ORDER BY PosicaoID", (setor,))
        posicao = cursor.fetchone()
        if not posicao:
            logger.warning(f"adicionar_funcionario_escala_web: nenhuma posição ativa no setor '{setor}'.")
            return False
        cursor.execute("""
            INSERT INTO EscalaDiaria (FuncionarioID, DataEscala, PosicaoID, HorarioEntrada, HorarioSaida)
            VALUES (?, ?, ?, '08:00', '17:00')
        """, (funcionario_id, data_iso, posicao[0]))
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
    Busca um produto mestre através do código de barras (EAN).
    AGORA RETORNA TAMBÉM O ÚLTIMO CUSTO PAGO.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # CORREÇÃO LÓGICA: O sub-select agora faz JOIN com ProdutosFornecedor (PF_SUB) 
            # para buscar o histórico de custo atrelado ao Produto Mestre (PE.ProdutoID), 
            # garantindo que novos códigos de barras herdem o custo fracionado da caixa mãe.
            sql = """
                SELECT 
                    PE.ProdutoID, 
                    PE.NomeProduto, 
                    PE.UnidadeMedida,
                    PF.FatorConversao,
                    ISNULL((
                        SELECT TOP 1 I.PrecoCustoUnitario 
                        FROM ItensNotaFiscalEntrada I
                        JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                        JOIN ProdutosFornecedor PF_SUB ON I.ProdutoFornecedorID = PF_SUB.ProdutoFornecedorID
                        WHERE PF_SUB.ProdutoID = PE.ProdutoID
                        ORDER BY N.DataEmissao DESC, N.NotaID DESC
                    ), 0) as UltimoCusto
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
    """Busca produtos por nome/descrição para a interface mobile. AGORA INCLUI CUSTO."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT TOP 20
                    PF.ProdutoFornecedorID,
                    ISNULL(P.NomeProduto, 'SEM MESTRE') as NomeMestre,
                    PF.DescricaoXML,
                    F.NomeFantasia,
                    PF.FatorConversao,
                    PF.EAN,
                    ISNULL((
                        SELECT TOP 1 I.PrecoCustoUnitario 
                        FROM ItensNotaFiscalEntrada I
                        JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                        WHERE I.ProdutoFornecedorID = PF.ProdutoFornecedorID
                        ORDER BY N.DataEmissao DESC, N.NotaID DESC
                    ), 0) as UltimoCusto,
                    P.ProdutoID,
                    P.UnidadeMedida
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

def previa_desmembrar_caixa(id_origem, qtd_na_caixa):
    """
    [DEPURAÇÃO 2] O que o "desmembrar caixa" vai mudar, para o gestor confirmar antes:
    {'Produto', 'Unidade', 'FatorAtual', 'Multiplicador', 'Vinculos', 'Compras', 'Contagens', 'Fechadas'}
    """
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT PF.ProdutoID, PF.FatorConversao, P.NomeProduto, P.UnidadeMedida FROM ProdutosFornecedor PF "
                       "JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID WHERE PF.ProdutoFornecedorID = ?", id_origem)
        r = cursor.fetchone()
        if not r:
            return None
        pid, fator, nome, un = r
        fator = _fator_item(None, fator)
        mult = _dec(qtd_na_caixa) / fator
        cursor.execute("SELECT COUNT(*) FROM ProdutosFornecedor WHERE ProdutoID = ?", pid)
        vinculos = int(cursor.fetchone()[0] or 0)
        cursor.execute("SELECT COUNT(*) FROM ItensNotaFiscalEntrada INI JOIN ProdutosFornecedor PF "
                       "ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID WHERE PF.ProdutoID = ? AND INI.Quantidade > 0", pid)
        compras = int(cursor.fetchone()[0] or 0)
        cursor.execute("SELECT DISTINCT ContagemID FROM ItensContagemEstoque WHERE ProdutoID = ?", pid)
        contagens = [x[0] for x in cursor.fetchall()]
        fechadas = [c for c in contagens if c in listar_valores_estoque_fechados()]
        return {'ProdutoID': pid, 'Produto': nome, 'Unidade': un or 'UN', 'FatorAtual': fator, 'Multiplicador': mult,
                'Vinculos': vinculos, 'Compras': compras, 'Contagens': len(contagens), 'Fechadas': len(fechadas)}
    finally:
        conn.close()


def desmembrar_caixa(id_origem, novo_ean, qtd_na_caixa, contagem_id=None, nome_avulso=None, qtd_contada=None):
    """
    (MÁQUINA DO TEMPO) O produto passa a ser controlado em UNIDADES em vez de caixas:
      - o Qtd/Cx de TODOS os vínculos do produto é multiplicado (a caixa de 72 vira fator 72);
      - TODAS as compras do produto viram unidades (quantidade x M, custo ÷ M);
      - TODAS as contagens do produto viram unidades (quantidade x M) — [DEPURAÇÃO 2] antes só
        as compras de UM vínculo mudavam: as contagens antigas (em caixas) passavam a valer
        unidades e o consumo/valor ficavam 72x menores;
      - cria o vínculo da UNIDADE para o EAN bipado (se ainda não existir);
      - se vier de uma contagem, resolve o item avulso.
    M = unidades na caixa ÷ Qtd/Cx atual (se já estava em unidades, M = 1 e nada muda).
    Contagens com valor FECHADO não mudam (o valor fechado é um retrato). Tudo numa transação.
    Devolve (sucesso, mensagem).
    """
    try:
        qtd_caixa = _dec(qtd_na_caixa)
    except Exception:
        return False, "Quantidade inválida."
    if qtd_caixa <= 0:
        return False, "Quantidade inválida."
    try:
        _garantir_colunas_estoque()
        fechadas = set(listar_valores_estoque_fechados(levantar_erro=True))
    except Exception as e:
        return False, f"Não foi possível consultar o banco: {e}"
    conn = get_db_connection()
    if not conn:
        return False, "Erro de conexão."
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT PF.ProdutoID, PF.FornecedorID, PF.NCM, PF.DescricaoXML, PF.FatorConversao, P.NomeProduto
            FROM ProdutosFornecedor PF
            JOIN ProdutosEstoque P ON PF.ProdutoID = P.ProdutoID
            WHERE PF.ProdutoFornecedorID = ?
        """, id_origem)
        dados_caixa = cursor.fetchone()
        if not dados_caixa:
            return False, "Cadastro origem não encontrado."
        prod_id, forn_id, ncm, desc_xml, fator_atual, nome_mestre_atual = dados_caixa
        fator_atual = _fator_item(None, fator_atual)
        mult = qtd_caixa / fator_atual

        if mult != 1:
            nome = nome_mestre_atual or ''
            if "(UNIDADE)" not in nome.upper() and "(UN)" not in nome.upper():
                cursor.execute("UPDATE ProdutosEstoque SET NomeProduto = ?, UnidadeMedida = 'UN' WHERE ProdutoID = ?",
                               f"{nome} (UNIDADE)", prod_id)
            else:
                cursor.execute("UPDATE ProdutosEstoque SET UnidadeMedida = 'UN' WHERE ProdutoID = ?", prod_id)
            cursor.execute("SELECT ProdutoFornecedorID, FatorConversao, FornecedorID FROM ProdutosFornecedor WHERE ProdutoID = ?", prod_id)
            vinculos = cursor.fetchall()
            internos = set()
            if vinculos:
                marcas = ", ".join("?" for _ in vinculos)
                cursor.execute(f"SELECT FornecedorID FROM Fornecedores WHERE CNPJ = ? AND FornecedorID IN ({marcas})",
                               CNPJ_FORNECEDOR_INTERNO, *[v[2] for v in vinculos])
                internos = {r[0] for r in cursor.fetchall()}
            for vid, fator_v, forn_v in vinculos:
                # compras: quantidade x M, custo / M (o valor de cada compra não muda)
                cursor.execute("""
                    UPDATE ItensNotaFiscalEntrada
                    SET Quantidade = Quantidade * ?, PrecoCustoUnitario = PrecoCustoUnitario / ?,
                        FatorConversaoUsado = COALESCE(FatorConversaoUsado, ?) * ?
                    WHERE ProdutoFornecedorID = ?
                """, mult, mult, _fator_item(None, fator_v), mult, vid)
                if forn_v not in internos:      # o vínculo do custo manual não tem "caixa"
                    cursor.execute("UPDATE ProdutosFornecedor SET FatorConversao = ? WHERE ProdutoFornecedorID = ?",
                                   _fator_item(None, fator_v) * mult, vid)
            cursor.execute("SELECT DISTINCT ContagemID FROM ItensContagemEstoque WHERE ProdutoID = ?", prod_id)
            for (cid,) in cursor.fetchall():
                if cid in fechadas:
                    continue
                cursor.execute("UPDATE ItensContagemEstoque SET QuantidadeContada = QuantidadeContada * ? "
                               "WHERE ContagemID = ? AND ProdutoID = ?", mult, cid, prod_id)
            logger.info(f"MÁQUINA DO TEMPO: produto {prod_id} convertido para unidades (x{mult}).")

        # vínculo da UNIDADE para o EAN bipado (não duplica se já existir)
        if novo_ean and novo_ean != "Sem EAN":
            cursor.execute("SELECT 1 FROM ProdutosFornecedor WHERE ProdutoID = ? AND EAN = ?", prod_id, novo_ean)
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO ProdutosFornecedor (ProdutoID, FornecedorID, EAN, NCM, FatorConversao, DescricaoXML)
                    VALUES (?, ?, ?, ?, 1.0, ?)
                """, prod_id, forn_id, novo_ean, ncm, f"{desc_xml} (VINCULO UNIDADE)")

        # resolve o item avulso da contagem (mesma transação)
        if contagem_id is not None and nome_avulso is not None:
            _resolver_avulso_na_contagem(cursor, contagem_id, nome_avulso, prod_id, _dec(qtd_contada or 0))
        conn.commit()
        if contagem_id is not None:
            return True, "Caixa desmembrada, EAN aprendido e contagem atualizada!"
        return True, "Desmembramento inteligente e ajuste histórico concluídos!"
    except Exception as e:
        logger.error(f"Erro ao desmembrar caixa: {e}", exc_info=True)
        conn.rollback()
        return False, f"Erro ao desmembrar (nada foi alterado): {e}"
    finally:
        conn.close()


def criar_unidade_a_partir_de_caixa(id_origem, novo_ean, qtd_na_caixa):
    """Compatibilidade (app do celular): mesmo que desmembrar_caixa, sem contagem."""
    return desmembrar_caixa(id_origem, novo_ean, qtd_na_caixa)

def excluir_vinculo_auditoria(vinculo_id):
    """Exclui um cadastro (vínculo) da tabela ProdutosFornecedor."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ItensNotaFiscalEntrada WHERE ProdutoFornecedorID = ?", vinculo_id)
            if int(cursor.fetchone()[0] or 0) > 0:   # [DEPURAÇÃO 2]
                return False, "Este vínculo tem compras registradas e não pode ser excluído."

            sql = "DELETE FROM ProdutosFornecedor WHERE ProdutoFornecedorID = ?"
            cursor.execute(sql, vinculo_id)
            conn.commit()
            return True, "Cadastro excluído com sucesso!"
        except Exception as e:
            logger.error(f"Erro ao excluir vínculo {vinculo_id}: {e}")
            conn.rollback()
            # O erro 547 do SQL Server é violação de Foreign Key
            return False, "Não é possível excluir: Este cadastro já possui histórico de notas fiscais vinculadas."
        finally:
            conn.close()
    return False, "Erro de conexão com o banco de dados."

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

# ===================================================================
# == INÍCIO DO MÓDULO DE AUDITORIA DE CÓDIGOS DE BARRAS (MOBILE) ====
# ===================================================================

def buscar_itens_sem_ean():
    """
    Busca os itens vinculados que não possuem código de barras válido.
    Ignora itens que o usuário marcou para não rastrear ('IGNORADO').
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT 
                    PF.ProdutoFornecedorID,
                    PF.DescricaoXML,
                    F.NomeFantasia,
                    ISNULL((
                        SELECT TOP 1 I.Quantidade 
                        FROM ItensNotaFiscalEntrada I
                        JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                        WHERE I.ProdutoFornecedorID = PF.ProdutoFornecedorID
                        ORDER BY N.DataEmissao DESC, N.NotaID DESC
                    ), 0) as UltimaQtd,
                    ISNULL((
                        SELECT TOP 1 I.PrecoCustoUnitario 
                        FROM ItensNotaFiscalEntrada I
                        JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                        WHERE I.ProdutoFornecedorID = PF.ProdutoFornecedorID
                        ORDER BY N.DataEmissao DESC, N.NotaID DESC
                    ), 0) as UltimoCusto
                FROM ProdutosFornecedor PF
                JOIN Fornecedores F ON PF.FornecedorID = F.FornecedorID
                WHERE PF.EAN IS NULL 
                   OR PF.EAN = '' 
                   OR PF.EAN = 'SEM GTIN'
            """
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao buscar itens sem EAN: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    return []

def atualizar_ean_vinculo(vinculo_id, novo_ean):
    """Atualiza o código de barras de um vínculo específico. Permite salvar 'IGNORADO'."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = "UPDATE ProdutosFornecedor SET EAN = ? WHERE ProdutoFornecedorID = ?"
            cursor.execute(sql, novo_ean, vinculo_id)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar EAN do vínculo ID {vinculo_id}: {e}", exc_info=True)
            if conn: conn.rollback()
            return False
        finally:
            conn.close()
    return False

def registrar_debito_pontos(funcionario_id, pontos_a_debitar, descricao):
    """
    [NOVO] Debita pontos do saldo do funcionário e registra a transação no extrato.
    Usado para a funcionalidade de Abater Saldo em Comanda.
    """
    conn = get_db_connection()
    if not conn: return False

    try:
        cursor = conn.cursor()
        # [DEPURAÇÃO] Antes: lia o saldo, calculava no Python e gravava o valor final.
        # Se outro processo mexesse no saldo no meio do caminho, a alteração dele se
        # perdia. Agora a conta e a conferência são feitas pelo próprio banco, de uma vez.
        cursor.execute("""
            UPDATE Funcionarios SET SaldoPontos = SaldoPontos - ?
            WHERE FuncionarioID = ? AND ISNULL(SaldoPontos, 0) >= ?
        """, pontos_a_debitar, funcionario_id, pontos_a_debitar)
        if cursor.rowcount == 0:
            conn.rollback()
            return False  # Saldo insuficiente (ou funcionário inexistente)

        # O INSERT em ExtratoPontos foi removido pois a tabela não existe no schema atual.
        # A auditoria já é feita automaticamente via mensagem para o grupo de Gestores.

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Erro ao debitar pontos do FuncionarioID {funcionario_id}: {e}", exc_info=True)
        if conn: conn.rollback()
        return False
    finally:
        if conn: conn.close()

def criar_produto_manual_com_custo(nome, unidade, estoque_min, categoria, custo_inicial):
    """
    (NOVA FUNÇÃO) Cria um produto e, se tiver custo, gera um 'Vínculo Fantasma' 
    e uma 'Nota Fiscal Fantasma' para que o sistema consiga ler o custo no celular.
    """
    conn = get_db_connection()
    if not conn: return None
    
    try:
        cursor = conn.cursor()
        # 1. Cria o Produto Mestre no Catálogo normalmente
        sql_mestre = """
            INSERT INTO ProdutosEstoque (NomeProduto, UnidadeMedida, EstoqueMinimo, Categoria)
            VALUES (?, ?, ?, ?);
            SELECT SCOPE_IDENTITY();
        """
        cursor.execute(sql_mestre, nome, unidade, estoque_min, categoria)
        cursor.nextset() # Avança para ler o ID criado
        produto_id = cursor.fetchone()[0]

        # 2. Se o gerente digitou um custo maior que zero, criamos a "Magia"
        if custo_inicial > 0:
            cnpj_interno = "00000000000000" # CNPJ Falso seguro
            
            # Checa se o fornecedor fantasma já existe
            cursor.execute("SELECT FornecedorID FROM Fornecedores WHERE CNPJ = ?", cnpj_interno)
            res_forn = cursor.fetchone()
            
            if res_forn:
                forn_id = res_forn[0]
            else:
                # Se não existe, cria o Fornecedor Fantasma
                cursor.execute("INSERT INTO Fornecedores (CNPJ, NomeFantasia) VALUES (?, ?); SELECT SCOPE_IDENTITY();", cnpj_interno, "PRODUÇÃO INTERNA / AVULSO")
                cursor.nextset()
                forn_id = cursor.fetchone()[0]

            # 3. Cria o Vínculo Fantasma (DE/PARA)
            desc_fantasma = f"{nome} (CADASTRO MANUAL)"
            sql_vinculo = """
                INSERT INTO ProdutosFornecedor (ProdutoID, FornecedorID, DescricaoXML, EAN, NCM, FatorConversao) 
                VALUES (?, ?, ?, 'SEM EAN', '00000000', 1.0); 
                SELECT SCOPE_IDENTITY();
            """
            cursor.execute(sql_vinculo, produto_id, forn_id, desc_fantasma)
            cursor.nextset()
            vinculo_id = cursor.fetchone()[0]

            # 4. Cria a Nota Fiscal Fantasma (Com valor 0 e Data de Hoje)
            numero_nf = f"MANUAL-{produto_id}" # Ex: MANUAL-45
            cursor.execute("INSERT INTO NotasFiscaisEntrada (NumeroNF, FornecedorID, DataEmissao, ValorTotalNF) VALUES (?, ?, GETDATE(), 0); SELECT SCOPE_IDENTITY();", numero_nf, forn_id)
            cursor.nextset()
            nota_id = cursor.fetchone()[0]

            # 5. Coloca o Item dentro da Nota Fantasma com o PREÇO DE CUSTO!
            # Quantidade 0 para não inflar o estoque falsamente.
            cursor.execute("INSERT INTO ItensNotaFiscalEntrada (NotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario) VALUES (?, ?, 0, ?)", nota_id, vinculo_id, custo_inicial)

        # Salva tudo de uma vez (Transação segura)
        conn.commit()
        return produto_id
        
    except Exception as e:
        conn.rollback() # Desfaz tudo se der erro!
        logger.error(f"Erro ao criar produto manual com custo: {e}", exc_info=True)
        return None
    finally:
        conn.close()

def buscar_ultimo_custo_por_produto(produto_id):
    """
    (NOVA FUNÇÃO) Busca o último preço de custo registrado para um Produto Mestre.
    Ele olha no histórico de todas as notas fiscais vinculadas a este produto
    e pega a mais recente.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            sql = """
                SELECT TOP 1 I.PrecoCustoUnitario 
                FROM ItensNotaFiscalEntrada I
                JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                JOIN ProdutosFornecedor PF ON I.ProdutoFornecedorID = PF.ProdutoFornecedorID
                WHERE PF.ProdutoID = ?
                ORDER BY N.DataEmissao DESC, N.NotaID DESC
            """
            cursor.execute(sql, produto_id)
            resultado = cursor.fetchone()
            
            # Se achou um valor, retorna. Se não achou (ou se o produto for novo sem nota), retorna 0.00
            return resultado[0] if resultado else 0.00
            
        except Exception as e:
            logger.error(f"Erro ao buscar último custo do produto {produto_id}: {e}", exc_info=True)
            return 0.00
        finally:
            conn.close()
    return 0.00

def atualizar_custo_manual_produto(produto_id, novo_custo):
    """
    (NOVA FUNÇÃO) Permite adicionar ou atualizar o preço de custo de um
    produto que JÁ ESTAVA CADASTRADO no sistema antes da atualização.
    """
    conn = get_db_connection()
    if not conn: return False

    try:
        cursor = conn.cursor()
        cnpj_interno = "00000000000000"

        # 1. Procura ou Cria o Fornecedor Fantasma
        cursor.execute("SELECT FornecedorID FROM Fornecedores WHERE CNPJ = ?", cnpj_interno)
        res_forn = cursor.fetchone()
        if not res_forn:
            cursor.execute("INSERT INTO Fornecedores (CNPJ, NomeFantasia) VALUES (?, ?); SELECT SCOPE_IDENTITY();", cnpj_interno, "PRODUÇÃO INTERNA / AVULSO")
            cursor.nextset()
            forn_id = cursor.fetchone()[0]
        else:
            forn_id = res_forn[0]

        # 2. Procura se este produto já foi vinculado ao Fornecedor Fantasma antes
        cursor.execute("SELECT ProdutoFornecedorID FROM ProdutosFornecedor WHERE ProdutoID = ? AND FornecedorID = ?", produto_id, forn_id)
        res_vinculo = cursor.fetchone()

        if res_vinculo:
            vinculo_id = res_vinculo[0]
            # 3. Se tem vínculo, acha o ID do item na Nota Fantasma para atualizar o preço
            cursor.execute("""
                SELECT TOP 1 I.ItemNotaID
                FROM ItensNotaFiscalEntrada I
                JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                WHERE I.ProdutoFornecedorID = ? AND N.FornecedorID = ?
                ORDER BY N.DataEmissao DESC, N.NotaID DESC
            """, vinculo_id, forn_id)
            res_item = cursor.fetchone()

            if res_item:
                # Achamos a nota! Atualiza o preço nela.
                cursor.execute("UPDATE ItensNotaFiscalEntrada SET PrecoCustoUnitario = ? WHERE ItemNotaID = ?", novo_custo, res_item[0])
            else:
                # Caso raro: tem o vínculo, mas deletaram a nota. Vamos recriar.
                num_nf = f"MANUAL-UPD-{produto_id}"
                cursor.execute("INSERT INTO NotasFiscaisEntrada (NumeroNF, FornecedorID, DataEmissao, ValorTotalNF) VALUES (?, ?, GETDATE(), 0); SELECT SCOPE_IDENTITY();", num_nf, forn_id)
                cursor.nextset()
                nota_id = cursor.fetchone()[0]
                cursor.execute("INSERT INTO ItensNotaFiscalEntrada (NotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario) VALUES (?, ?, 0, ?)", nota_id, vinculo_id, novo_custo)
        else:
            # 4. O Produto antigo NÃO tinha vínculo fantasma. Vamos criar tudo do zero!
            # ---> A CORREÇÃO ESTÁ AQUI: Incluímos o ID do produto no nome para garantir que NUNCA seja duplicado! <---
            desc_fantasma = f"(CUSTO ATUALIZADO MANUAL - ID {produto_id})"
            
            cursor.execute("INSERT INTO ProdutosFornecedor (ProdutoID, FornecedorID, DescricaoXML, EAN, NCM, FatorConversao) VALUES (?, ?, ?, 'SEM EAN', '00000000', 1.0); SELECT SCOPE_IDENTITY();", produto_id, forn_id, desc_fantasma)
            cursor.nextset()
            vinculo_id = cursor.fetchone()[0]

            num_nf = f"MANUAL-UPD-{produto_id}"
            cursor.execute("INSERT INTO NotasFiscaisEntrada (NumeroNF, FornecedorID, DataEmissao, ValorTotalNF) VALUES (?, ?, GETDATE(), 0); SELECT SCOPE_IDENTITY();", num_nf, forn_id)
            cursor.nextset()
            nota_id = cursor.fetchone()[0]
            cursor.execute("INSERT INTO ItensNotaFiscalEntrada (NotaID, ProdutoFornecedorID, Quantidade, PrecoCustoUnitario) VALUES (?, ?, 0, ?)", nota_id, vinculo_id, novo_custo)

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Erro ao atualizar custo manual: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        conn.close()

def buscar_produtos_para_folha_contagem():
    """
    Busca todos os produtos cadastrados com seus respectivos últimos custos tributados,
    ordenados por Categoria e Nome Alfabético para a folha de checagem manual.
    """
    conn = get_db_connection()
    if not conn: return []
    
    try:
        cursor = conn.cursor()
        # Query que traz os dados básicos do mestre e faz uma subquery para buscar
        # o valor unitário da última Nota Fiscal de Entrada que deu entrada no sistema.
        sql = """
            SELECT
                ISNULL(PE.Categoria, 'Geral') as Categoria,
                PE.ProdutoID,
                PE.NomeProduto,
                PE.UnidadeMedida,
                ISNULL((
                    SELECT TOP 1 I.PrecoCustoUnitario
                    FROM ItensNotaFiscalEntrada I
                    JOIN NotasFiscaisEntrada N ON I.NotaID = N.NotaID
                    JOIN ProdutosFornecedor PF ON I.ProdutoFornecedorID = PF.ProdutoFornecedorID
                    WHERE PF.ProdutoID = PE.ProdutoID
                    ORDER BY N.DataEmissao DESC, N.NotaID DESC
                ), 0) as UltimoCusto
            FROM ProdutosEstoque PE
            ORDER BY Categoria ASC, NomeProduto ASC
        """
        cursor.execute(sql)
        cols = [column[0] for column in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
        
    except Exception as e:
        logger.error(f"Erro ao buscar produtos para folha de contagem: {e}", exc_info=True)
        return []
        
    finally:
        if conn: conn.close()

# ===================================================================
# == TESTE MANUAL DO MÓDULO (só roda com: python database.py) =======
# ===================================================================
# [DEPURAÇÃO] Este bloco estava no MEIO do arquivo: ao rodar 'python database.py'
# ele executava antes de metade das funções existir. Foi movido para o final.
# ATENÇÃO: ele cria um comunicado de teste DE VERDADE no banco.
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
        raise SystemExit(1)
    print(f"\n[TESTE 2] Registrando pendência do Doc ID {id_doc} para o Funcionário ID {FUNCIONARIO_ID_TESTE}...")
    id_assinatura = registrar_pendencia_assinatura(id_doc, FUNCIONARIO_ID_TESTE)
    if id_assinatura:
        print(f"--> SUCESSO! Pendência registrada com AssinaturaID: {id_assinatura}")
    else:
        print("--> FALHA! Não foi possível registrar a pendência.")
        raise SystemExit(1)

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

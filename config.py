# config.py - Arquivo Central de Configurações
# Este é o "painel de controle" do seu sistema. Todas as senhas, tokens e IDs importantes ficam aqui.

# --- CONFIGURAÇÕES DO TELEGRAM ---
# Token secreto do seu bot, obtido com o @BotFather no Telegram.
TELEGRAM_TOKEN = '8286167530:AAHsQlEHQwNB1O7SdyAqLk-rEhSXFdf___M'

# ID do chat de grupo para onde as notificações de gestão (validações, etc.) são enviadas.
GESTOR_GROUP_CHAT_ID = -1002979750507

# ID do chat de grupo para onde os lembretes de agendamentos são enviados.
AGENDAMENTOS_GROUP_CHAT_ID = -4839358986

# ID do chat de grupo para onde as tarefas de funcionários de folga são oferecidas.
ATENDIMENTO_GROUP_CHAT_ID = -1003142022069
COZINHA_GROUP_CHAT_ID = -4902264106

# --- CONFIGURAÇÕES DO BANCO DE DADOS ---
# Endereço do seu servidor SQL Server.
DB_SERVER = '192.168.2.23'
# Nome do banco de dados que estamos usando.
DB_DATABASE = 'gamificacao_db'
# Usuário de acesso ao banco.
DB_UID = 'sa'
# Senha de acesso ao banco. MANTENHA ESTE ARQUIVO SEGURO!
DB_PWD = 'Gamificacao#2025'

# --- CONFIGURAÇÕES DA API E ARQUIVOS ---
# URL base para a API. Essencial para o ngrok e para o deploy final.
API_BASE_URL = "http://192.168.2.23:5000" # Lembre-se de atualizar se o ngrok mudar!

# Nome da pasta onde os documentos de RH (holerites, etc.) serão salvos no servidor.
PASTA_DOCUMENTOS_RH = "documentos_rh_seguros"

# --- CONFIGURAÇÕES DE REGRAS DE NEGÓCIO (GAMIFICAÇÃO) ---
# Taxa para converter o saldo de pontos em valor monetário na loja.
TAXA_CONVERSAO_PONTO_REAL = 0.02 # Ex: 1 ponto = R$ 0.02

# ID do funcionário responsável por receber as tarefas geradas a partir de novos agendamentos.
RESPONSAVEL_AGENDAMENTOS_ID = 2

# ID da tarefa "modelo" usada para criar as tarefas de agendamento (Ex: "Preparar Agendamento").
TAREFA_MODELO_AGENDAMENTO_ID = 92

# ID da tarefa "modelo" usada para registrar os pontos ganhos pela leitura de comunicados.
TAREFA_ID_LEITURA = 38

# ID da tarefa "modelo" usada para registrar os pontos de feedback diário.
TAREFA_ID_FEEDBACK_DIARIO = 5
# Pontos de bônus concedidos ao dar o feedback diário.
PONTOS_BONUS_FEEDBACK_DIARIO = 5

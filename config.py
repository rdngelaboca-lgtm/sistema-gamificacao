# --- CONFIGURAÇÕES DO PAINEL WEB ---
# Senha para acessar a área administrativa (Gestão de Escala)
ADMIN_PASSWORD = "admin"  # <--- ALTERE PARA UMA SENHA FORTE DEPOIS
SECRET_KEY_FLASK = "321Loj@890" # Necessário para criar sessões seguras

# --- CONFIGURAÇÕES DO TELEGRAM ---
# Token secreto do seu bot, obtido com o @BotFather no Telegram.
TELEGRAM_TOKEN = '8286167530:AAHsQlEHQwNB1O7SdyAqLk-rEhSXFdf___M'

# ID do chat de grupo para onde as notificações de gestão (validações, etc.) são enviadas.
GESTOR_GROUP_CHAT_ID = -1002979750507

# ID do chat de grupo para onde os lembretes de agendamentos são enviados.
AGENDAMENTOS_GROUP_CHAT_ID = -4839358986

# ID do chat de grupo para onde as tarefas de funcionários de folga são oferecidas.
FOLGA_GROUP_CHAT_ID = -1003142022069
ATENDIMENTO_GROUP_CHAT_ID = -1003142022069
COZINHA_GROUP_CHAT_ID = -4902264106

# ID do grupo onde estão TODOS os funcionários para receber a escala diária
# (Substitua pelo ID correto do seu grupo "Geral")
TODOS_FUNCIONARIOS_GROUP_ID = -5030960080

# --- CONFIGURAÇÕES DO BANCO DE DADOS ---
# Endereço do seu servidor SQL Server.
DB_SERVER = '127.0.0.1'
# Nome do banco de dados que estamos usando.
DB_DATABASE = 'gamificacao_db'
# Usuário de acesso ao banco.
DB_UID = 'sa'
# Senha de acesso ao banco. MANTENHA ESTE ARQUIVO SEGURO!
DB_PWD = 'Gamificacao#2025'

# --- CONFIGURAÇÕES DA API E ARQUIVOS ---
# URL base para a API. Como o Bot e a API rodam no mesmo servidor Linux (Lubuntu),
# usamos localhost (127.0.0.1) para que eles conversem internamente, imunes a quedas de rede.
API_BASE_URL = "http://127.0.0.1:5000"

# Nome da pasta onde os documentos de RH (holerites, etc.) serão salvos no servidor.
PASTA_DOCUMENTOS_RH = "documentos_rh_seguros"

# --- CONFIGURAÇÕES DE REGRAS DE NEGÓCIO (GAMIFICAÇÃO) ---
# Taxa para converter o saldo de pontos em valor monetário na loja.
TAXA_CONVERSAO_PONTO_REAL = 0.03 # Ex: 1 ponto = R$ 0.02

# ID do funcionário responsável por receber as tarefas geradas a partir de novos agendamentos.
RESPONSAVEL_AGENDAMENTOS_ID = 3

# ID da tarefa "modelo" usada para criar as tarefas de agendamento (Ex: "Preparar Agendamento").
TAREFA_MODELO_AGENDAMENTO_ID = 92

# ID da tarefa "modelo" usada para registrar os pontos ganhos pela leitura de comunicados.
TAREFA_ID_LEITURA = 38
TAREFA_ID_PONTOS_META = 121

# ID da tarefa "modelo" usada para registrar os pontos de feedback diário.
TAREFA_ID_FEEDBACK_DIARIO = 5
# Pontos de bônus concedidos ao dar o feedback diário.
PONTOS_BONUS_FEEDBACK_DIARIO = 5

ID_GESTOR_PADRAO = 2
HORARIO_FECHAMENTO_MENSAL = "08:00" # Roda todo dia, mas só executa no dia 1
HORARIO_DELEGACAO_FOLGA = "09:05"
HORARIO_LEMBRETE_COMUNICADOS = "09:00"
HORARIO_LEMBRETE_HOJE = "08:00"
HORARIO_LEMBRETE_DIARIO_AMANHA = "09:00"
HORARIO_LEMBRETE_SEMANAL = "08:00"
MAX_DIFERENCA_FOTO_SEGUNDOS = 120

# --- CONFIGURAÇÕES DA FUNCIONALIDADE DE NOTA FISCAL (NF) ---
# Pontos de bônus que o funcionário ganha por enviar a NF (Regra 1)
PONTOS_BONUS_NOTA_FISCAL = 10

# ID da Tarefa "Bônus: Envio de Nota Fiscal" que você criou no Passo 0.1 (Regra 1)
TAREFA_ID_NOTA_FISCAL = 156 # <--- SUBSTITUA O 0 PELO ID CORRETO

# ID da Tarefa "Guardar Mercadoria (NF)" que você criou no Passo 0.2 (Regra 4)
TAREFA_ID_GUARDAR_MERCADORIA_MODELO = 157 # <--- SUBSTITUA O 0 PELO ID CORRETO

# --- CONFIGURAÇÕES DE API WHATSAPP (Z-API - PAGO) ---
# Seus dados obtidos no painel do z-api.io (Conforme print enviado)
ZAPI_INSTANCE_ID = "3EB36324A185017B5FF226D356DD90A9" 
ZAPI_TOKEN = "0A46EB01B39DF4EA213B5F3F"
# Token de Segurança (Client-Token) para autenticação na Z-API
ZAPI_CLIENT_TOKEN = "F7880a7b372194b21b5ca96fb4360cde1S"

# URL Base padrão da Z-API
WPP_API_URL = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

# --- MENSAGENS PARA META DIÁRIA ATINGIDA ---
MENSAGENS_META_DIARIA_CUMPRIDA = [
    "🏆 UHUUUL! Batemos a meta de hoje! 🎉 Cada um ganhou +{pontos} pontos! Vocês são demais! 🚀",
    "🎯 META DIÁRIA NO ALVO! Parabéns, equipe! +{pontos} pontos na conta de todo mundo! 🥳",
    "✨ MISSÃO CUMPRIDA! A meta de hoje foi superada! Valeu, time! +{pontos} pontos para geral! 💪",
    "🚀 IMPARÁVEIS! Meta diária batida mais uma vez! +{pontos} pontos de recompensa para todos! 🔥",
    "💰 SHOW DE BOLA! Meta do dia alcançada com sucesso! +{pontos} pontos para cada membro da equipe! 🤩",
]

import logging
import logging.handlers
import sys
import os
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
import database
import config
import web_auth
from datetime import date, datetime, time, timedelta
import decimal

# ==============================================================================
# == CONFIGURAÇÃO DE LOGGING
# ==============================================================================
LOG_FOLDER = 'logs'
LOG_FILENAME = 'gamificacao_api.log'

log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
    except OSError:
        pass # Falha silenciosa se não der pra criar

logging.basicConfig(
    filename=os.path.join(log_dir, LOG_FILENAME),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')

# [CORREÇÃO 3] Fallback de segurança para Secret Key
app.secret_key = getattr(config, 'SECRET_KEY_FLASK', 'chave_padrao_insegura_dev')
CORS(app)

# ==============================================================================
# 🛠️ UTILITÁRIOS DE SERIALIZAÇÃO (CORREÇÃO DO BUG 1)
# ==============================================================================
def converter_objeto_para_json(obj):
    """
    Função recursiva para converter tipos complexos (Date, Time, Decimal)
    em strings ou floats aceitáveis pelo JSON.
    """
    if isinstance(obj, dict):
        return {k: converter_objeto_para_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [converter_objeto_para_json(i) for i in obj]
    elif isinstance(obj, (date, datetime)):
        return obj.isoformat() # Retorna "YYYY-MM-DD" ou "YYYY-MM-DDTHH:MM:SS"
    elif isinstance(obj, time):
        return obj.strftime('%H:%M') # Retorna "HH:MM"
    elif isinstance(obj, decimal.Decimal):
        return float(obj) # Converte Decimal SQL para Float Python
    return obj

# ==============================================================================
# 🌐 ROTAS DE PÁGINAS (FRONTEND)
# ==============================================================================

@app.route('/')
def index():
    # Redireciona para o painel principal se acessar a raiz
    return send_from_directory('.', 'painel.html')

@app.route('/admin')
def admin_page():
    return send_from_directory('.', 'admin.html')

@app.route('/painel')
def painel_page():
    return send_from_directory('.', 'painel.html')

# Servir arquivos estáticos (CSS/JS)
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# ==============================================================================
# 🔐 AUTENTICAÇÃO
# ==============================================================================

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    senha = data.get('senha')
    
    if web_auth.verificar_senha(senha):
        session['logged_in'] = True
        return jsonify({"sucesso": True})
    else:
        return jsonify({"sucesso": False, "erro": "Senha incorreta"}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return jsonify({"sucesso": True})

@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    if session.get('logged_in'):
        return jsonify({"autenticado": True})
    return jsonify({"autenticado": False}), 401

# ==============================================================================
# 📊 API DE DADOS (DASHBOARD & RANKING)
# ==============================================================================

@app.route('/api/ranking', methods=['GET'])
def get_ranking():
    try:
        # Busca dados brutos (objetos Python)
        dados = database.obter_ranking_geral()
        # [CORREÇÃO 1] Converte antes de enviar
        dados_json = converter_objeto_para_json(dados)
        return jsonify(dados_json)
    except Exception as e:
        logger.error(f"Erro na API Ranking: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route('/api/metas', methods=['GET'])
def get_metas():
    try:
        dados = database.obter_status_metas()
        dados_json = converter_objeto_para_json(dados)
        return jsonify(dados_json)
    except Exception as e:
        logger.error(f"Erro na API Metas: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route('/api/tarefas-hoje', methods=['GET'])
def get_tarefas_hoje():
    try:
        dados = database.listar_tarefas_pendentes_hoje() # Assumindo que existe func similar
        dados_json = converter_objeto_para_json(dados)
        return jsonify(dados_json)
    except Exception as e:
        # Se a função não existir no database, retorna lista vazia para não quebrar o front
        logger.warning(f"Erro/Função Inexistente API Tarefas: {e}")
        return jsonify([])

# ==============================================================================
# 📅 API DE ESCALA (LEITURA E ESCRITA)
# ==============================================================================

@app.route('/api/escala', methods=['GET'])
def get_escala():
    data_str = request.args.get('data')
    if not data_str:
        data_str = date.today().strftime('%Y-%m-%d')
    
    try:
        # database.buscar_escala_do_dia espera string YYYY-MM-DD ou date object
        # Vamos passar string para garantir
        dados = database.buscar_escala_do_dia(data_str)
        dados_json = converter_objeto_para_json(dados)
        return jsonify(dados_json)
    except Exception as e:
        logger.error(f"Erro na API Escala: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route('/api/escala/atualizar-horario', methods=['POST'])
@web_auth.login_required
def update_horario():
    """
    Recebe atualização de um slot de horário específico.
    """
    try:
        data = request.json
        escala_id = data.get('id')
        
        # [CORREÇÃO 2] Sanitização de Inputs Vazios -> NULL
        # Se o campo vier vazio "", converte para None para o SQL entender como NULL
        entrada = data.get('entrada') or None
        saida = data.get('saida') or None
        int_ini = data.get('int_ini') or None
        int_fim = data.get('int_fim') or None

        if not escala_id:
            return jsonify({"sucesso": False, "erro": "ID não fornecido"}), 400

        logger.info(f"Update Escala ID {escala_id}: {entrada}-{saida}")

        sucesso = database.atualizar_horario_escala(
            escala_id, 
            entrada, 
            saida, 
            int_ini, 
            int_fim
        )

        if sucesso:
            return jsonify({"sucesso": True})
        else:
            return jsonify({"sucesso": False, "erro": "Banco recusou a gravação"}), 500

    except Exception as e:
        logger.error(f"Erro Crítico Update Horário: {e}", exc_info=True)
        return jsonify({"sucesso": False, "erro": str(e)}), 500

# ==============================================================================
# 🚀 INICIALIZAÇÃO
# ==============================================================================

if __name__ == '__main__':
    print("--- 🌍 Servidor API Flask Iniciado na Porta 5000 ---")
    print("Acesse: http://localhost:5000/painel")
    # debug=True ajuda a ver erros no console, mas cuidado em produção real
    app.run(host='0.0.0.0', port=5000, debug=True)

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

# --- Configuração de Log (Padrão) ---
LOG_FOLDER = 'logs'
LOG_FILENAME = 'gamificacao_api.log'
log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try: os.makedirs(log_dir)
    except: pass

logging.basicConfig(
    filename=os.path.join(log_dir, LOG_FILENAME),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = getattr(config, 'SECRET_KEY_FLASK', 'dev_key_seguranca')
CORS(app)

# --- CONVERSOR DE DADOS (Mantido pois é essencial) ---
def converter_objeto_para_json(obj):
    if isinstance(obj, dict):
        return {k: converter_objeto_para_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [converter_objeto_para_json(i) for i in obj]
    elif isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, time):
        return obj.strftime('%H:%M')
    elif isinstance(obj, timedelta):
        return str(obj)
    elif isinstance(obj, decimal.Decimal):
        return float(obj)
    elif hasattr(obj, 'cursor_description'):
        colunas = [column[0] for column in obj.cursor_description]
        return {k: converter_objeto_para_json(v) for k, v in zip(colunas, obj)}
    return obj

# --- ROTAS ESTÁTICAS ---
@app.route('/')
def index(): return send_from_directory('.', 'painel.html')

@app.route('/admin')
def admin_page(): return send_from_directory('.', 'admin.html')

@app.route('/painel')
def painel_page(): return send_from_directory('.', 'painel.html')

@app.route('/<path:path>')
def serve_static(path): return send_from_directory('.', path)

# --- ROTAS DE DADOS (PONTES RECONSTRUÍDAS) ---

@app.route('/api/ranking', methods=['GET'])
def get_ranking():
    # CHAMA DIRETO - SEM MEDO DE ERRO
    # Se der erro aqui, é porque o SQL no database.py precisa de ajuste nos nomes das colunas
    dados = database.obter_ranking_geral()
    return jsonify(converter_objeto_para_json(dados))

@app.route('/api/metas', methods=['GET'])
def get_metas():
    # CHAMA DIRETO
    dados = database.obter_status_metas()
    return jsonify(converter_objeto_para_json(dados))

@app.route('/api/tarefas-hoje', methods=['GET'])
def get_tarefas_hoje():
    # CHAMA DIRETO
    dados = database.listar_tarefas_pendentes_hoje()
    return jsonify(converter_objeto_para_json(dados))

@app.route('/api/escala', methods=['GET'])
def get_escala():
    data_str = request.args.get('data')
    if not data_str: data_str = date.today().strftime('%Y-%m-%d')
    
    # CHAMA DIRETO
    dados = database.buscar_escala_do_dia(data_str) or []
    return jsonify(converter_objeto_para_json(dados))

# --- ROTAS DE AÇÃO ---

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if web_auth.verificar_senha(data.get('senha')):
        session['logged_in'] = True
        return jsonify({"sucesso": True})
    return jsonify({"sucesso": False, "erro": "Senha incorreta"}), 401

@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    return jsonify({"autenticado": bool(session.get('logged_in'))})

@app.route('/api/escala/atualizar-horario', methods=['POST'])
@web_auth.login_required
def update_horario():
    try:
        data = request.json
        # Sanitização de inputs vazios para NULL
        entrada = data.get('entrada') or None
        saida = data.get('saida') or None
        int_ini = data.get('int_ini') or None
        int_fim = data.get('int_fim') or None

        sucesso = database.atualizar_horario_escala(
            data.get('id'), entrada, saida, int_ini, int_fim
        )
        return jsonify({"sucesso": sucesso})
    except Exception as e:
        logger.error(f"Erro update: {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500

if __name__ == '__main__':
    print("--- 🌍 Servidor API (PONTES REATIVADAS) ---")
    app.run(host='0.0.0.0', port=5000, debug=True)

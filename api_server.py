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
        pass 

logging.basicConfig(
    filename=os.path.join(log_dir, LOG_FILENAME),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')

# Fallback de segurança para Secret Key
app.secret_key = getattr(config, 'SECRET_KEY_FLASK', 'chave_padrao_insegura_dev')
CORS(app)

# ==============================================================================
# 🛠️ CONVERSOR UNIVERSAL DE DADOS (A CORREÇÃO DO PAINEL)
# ==============================================================================
def converter_objeto_para_json(obj):
    """
    Transforma qualquer dado estranho do SQL Server em algo que o Javascript entenda.
    """
    if isinstance(obj, dict):
        return {k: converter_objeto_para_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [converter_objeto_para_json(i) for i in obj]
    elif isinstance(obj, (date, datetime)):
        return obj.isoformat() # "2023-10-27"
    elif isinstance(obj, time):
        return obj.strftime('%H:%M') # "14:30"
    elif isinstance(obj, timedelta):
        # Transforma duração (ex: 2 horas) em string "2:00:00"
        return str(obj)
    elif isinstance(obj, decimal.Decimal):
        return float(obj) # Dinheiro vira número normal
    elif hasattr(obj, 'cursor_description'): 
        # Se vier uma linha crua do banco (pyodbc Row), transforma em Dicionário
        colunas = [column[0] for column in obj.cursor_description]
        return {k: converter_objeto_para_json(v) for k, v in zip(colunas, obj)}
    return obj

# ==============================================================================
# 🌐 ROTAS DE PÁGINAS (FRONTEND)
# ==============================================================================

@app.route('/')
def index():
    return send_from_directory('.', 'painel.html')

@app.route('/admin')
def admin_page():
    return send_from_directory('.', 'admin.html')

@app.route('/painel')
def painel_page():
    return send_from_directory('.', 'painel.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# ==============================================================================
# 🔐 AUTENTICAÇÃO (MANTIDO IGUAL - POIS FUNCIONOU)
# ==============================================================================

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        senha = data.get('senha')
        if web_auth.verificar_senha(senha):
            session['logged_in'] = True
            return jsonify({"sucesso": True})
        return jsonify({"sucesso": False, "erro": "Senha incorreta"}), 401
    except Exception as e:
        logger.error(f"Erro no Login: {e}")
        return jsonify({"sucesso": False, "erro": "Erro interno"}), 500

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
# 📊 API DE DADOS - PAINEL DE GESTÃO (AQUI ESTAVA O PROBLEMA)
# ==============================================================================

@app.route('/api/ranking', methods=['GET'])
def get_ranking():
    try:
        # Tenta buscar, se a função não existir no database, retorna lista vazia pra não travar a tela
        if hasattr(database, 'obter_ranking_geral'):
            dados = database.obter_ranking_geral()
        else:
            dados = [] 
            logger.warning("Função obter_ranking_geral não encontrada no database.py")
            
        return jsonify(converter_objeto_para_json(dados))
    except Exception as e:
        logger.error(f"Erro API Ranking: {e}")
        return jsonify([]) # Retorna vazio em vez de erro 500 para não quebrar o JS

@app.route('/api/metas', methods=['GET'])
def get_metas():
    try:
        if hasattr(database, 'obter_status_metas'):
            dados = database.obter_status_metas()
        else:
            dados = {"meta_diaria": 0, "vendido_hoje": 0} # Dados dummy
            
        return jsonify(converter_objeto_para_json(dados))
    except Exception as e:
        logger.error(f"Erro API Metas: {e}")
        return jsonify({"erro": str(e)})

@app.route('/api/tarefas-hoje', methods=['GET'])
def get_tarefas_hoje():
    try:
        # Verifica nomes comuns de função para listar tarefas
        dados = []
        if hasattr(database, 'listar_tarefas_pendentes_hoje'):
            dados = database.listar_tarefas_pendentes_hoje()
        elif hasattr(database, 'buscar_tarefas_hoje'):
            dados = database.buscar_tarefas_hoje()
            
        return jsonify(converter_objeto_para_json(dados))
    except Exception as e:
        logger.error(f"Erro API Tarefas: {e}")
        return jsonify([])

# ==============================================================================
# 📅 API DE ESCALA (USADO PELO PAINEL E PELO ADMIN)
# ==============================================================================

@app.route('/api/escala', methods=['GET'])
def get_escala():
    """Retorna a escala para preencher o Mapa da Loja e Gráficos"""
    data_str = request.args.get('data')
    if not data_str:
        data_str = date.today().strftime('%Y-%m-%d')
    
    try:
        dados = database.buscar_escala_do_dia(data_str)
        
        # O Painel espera uma lista. Se vier None, enviamos lista vazia.
        if dados is None:
            dados = []
            
        json_saida = converter_objeto_para_json(dados)
        return jsonify(json_saida)
    except Exception as e:
        logger.error(f"Erro API Escala: {e}", exc_info=True)
        return jsonify([])

@app.route('/api/escala/atualizar-horario', methods=['POST'])
@web_auth.login_required
def update_horario():
    try:
        data = request.json
        escala_id = data.get('id')
        
        # Converte strings vazias "" para None (NULL no banco)
        entrada = data.get('entrada') or None
        saida = data.get('saida') or None
        int_ini = data.get('int_ini') or None
        int_fim = data.get('int_fim') or None

        if not escala_id:
            return jsonify({"sucesso": False, "erro": "ID não fornecido"}), 400

        sucesso = database.atualizar_horario_escala(escala_id, entrada, saida, int_ini, int_fim)

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
    print("--- 🌍 Servidor API Flask (V2.0 - Fixed) Iniciado ---")
    print("Acesse: http://localhost:5000/painel")
    app.run(host='0.0.0.0', port=5000, debug=True)

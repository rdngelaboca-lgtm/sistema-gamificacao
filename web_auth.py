# web_auth.py
from functools import wraps
from flask import session, jsonify, request
import config

def login_required(f):
    """
    Decora uma rota Flask para exigir login.
    Se não estiver logado, retorna erro 401 ou redireciona.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verifica se a flag 'logged_in' está na sessão do navegador
        if not session.get('logged_in'):
            return jsonify({"erro": "Acesso negado. Faça login."}), 401
        return f(*args, **kwargs)
    return decorated_function

def verificar_senha(senha_recebida):
    """Compara a senha enviada com a do config.py"""
    return senha_recebida == config.ADMIN_PASSWORD
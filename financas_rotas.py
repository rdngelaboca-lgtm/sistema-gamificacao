# ==============================================================================
# financas_rotas.py - ENDEREÇOS (ROTAS) DO APP DE FINANÇAS DA FAMÍLIA
# ------------------------------------------------------------------------------
# Endereço: http://IP-DO-COMPUTADOR:5000/financas  (rede da loja)
#       ou: https://SEU-ENDERECO-DO-TUNEL/financas  (internet)
# Login: escolhe o nome e digita o PIN (cadastre com cadastrar_pin_financas.py).
# Toda a lógica fica no financas_database.py. Este arquivo é ligado ao servidor
# (api_server.py) com app.register_blueprint(financas_rotas.bp).
#
# O login do app de finanças é SEPARADO do app de compras e do painel: entrar em
# um não dá acesso ao outro.
# ==============================================================================

import logging
import os
import time
from functools import wraps

from flask import Blueprint, jsonify, make_response, render_template, request, send_from_directory, session

import financas_database as fd

logger = logging.getLogger(__name__)

bp = Blueprint('financas', __name__)
PASTA_ARQUIVOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'financas')
CHAVE_SESSAO = 'financas_usuario'

# Freio contra quem tenta adivinhar PIN: no máximo 20 erros por IP a cada 15 minutos
_erros_por_ip = {}
LIMITE_ERROS_POR_IP = 20
JANELA_ERROS_SEGUNDOS = 15 * 60


def _ip():
    return (request.headers.get('Cf-Connecting-Ip') or request.remote_addr or '?').strip()


def _ip_bloqueado(ip):
    agora = time.time()
    recentes = [t for t in _erros_por_ip.get(ip, []) if agora - t < JANELA_ERROS_SEGUNDOS]
    _erros_por_ip[ip] = recentes
    return len(recentes) >= LIMITE_ERROS_POR_IP


def _json():
    dados = request.get_json(silent=True)
    return dados if isinstance(dados, dict) else {}


def _responder(funcao, *args, status_ok=200, **kwargs):
    """Executa uma função do financas_database e devolve JSON (erro amigável se falhar)."""
    try:
        return jsonify(funcao(*args, **kwargs)), status_ok
    except fd.ErroFinancas as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        logger.exception(f"Erro no app de finanças ({request.path}): {e}")
        return jsonify({"erro": "Erro no servidor. Tente de novo."}), 500


def login_financas(f):
    """Protege as rotas: precisa ter entrado com o PIN."""
    @wraps(f)
    def interno(*args, **kwargs):
        usuario = session.get(CHAVE_SESSAO)
        if not usuario:
            return jsonify({"erro": "Entre com seu PIN.", "login": True}), 401
        try:
            ativo = fd.usuario_ativo(usuario['id'])
        except Exception as e:
            logger.error(f"Finanças: falha ao conferir usuário: {e}")
            return jsonify({"erro": "Sem acesso ao banco de dados."}), 503
        if not ativo:
            session.pop(CHAVE_SESSAO, None)
            return jsonify({"erro": "Seu acesso foi desativado.", "login": True}), 401
        return f(usuario, *args, **kwargs)
    return interno


# ---------------------------- página e arquivos do app ----------------------------

@bp.route('/financas')
@bp.route('/financas/')
def pagina():
    resposta = make_response(render_template('financas_app.html'))
    resposta.headers['Cache-Control'] = 'no-cache'
    return resposta


@bp.route('/financas/sw.js')
def service_worker():
    resposta = send_from_directory(PASTA_ARQUIVOS, 'sw.js', mimetype='application/javascript')
    resposta.headers['Cache-Control'] = 'no-cache'
    resposta.headers['Service-Worker-Allowed'] = '/financas/'
    return resposta


@bp.route('/financas/manifest.webmanifest')
def manifest():
    return send_from_directory(PASTA_ARQUIVOS, 'manifest.webmanifest', mimetype='application/manifest+json')


@bp.route('/financas/arquivos/<path:nome>')
def arquivos(nome):
    return send_from_directory(PASTA_ARQUIVOS, nome)


# ---------------------------- login com PIN ----------------------------

@bp.route('/api/financas/usuarios', methods=['GET'])
def api_usuarios():
    return _responder(fd.listar_usuarios)


@bp.route('/api/financas/login', methods=['POST'])
def api_login():
    ip = _ip()
    if _ip_bloqueado(ip):
        return jsonify({"erro": "Muitas tentativas erradas deste aparelho. Espere 15 minutos."}), 429
    dados = _json()
    try:
        usuario = fd.verificar_pin(dados.get('usuario_id'), dados.get('pin'))
    except fd.ErroFinancas as e:
        _erros_por_ip.setdefault(ip, []).append(time.time())
        logger.warning(f"Finanças: login recusado (usuário {dados.get('usuario_id')}, IP {ip}): {e}")
        return jsonify({"erro": str(e)}), 401
    except Exception as e:
        logger.exception(f"Finanças: erro no login: {e}")
        return jsonify({"erro": "Sem acesso ao banco de dados."}), 503
    session[CHAVE_SESSAO] = usuario
    session.permanent = True
    logger.info(f"Finanças: login de {usuario['nome']} (IP {ip})")
    return jsonify({"usuario": usuario})


@bp.route('/api/financas/logout', methods=['POST'])
def api_logout():
    session.pop(CHAVE_SESSAO, None)
    return jsonify({"ok": True})


@bp.route('/api/financas/inicio', methods=['GET'])
@login_financas
def api_inicio(usuario):
    """Quem está logado + contas, categorias e pessoas (o app guarda isso para montar as telas)."""
    return _responder(lambda: dict(fd.dados_iniciais(), usuario=usuario))


# ---------------------------- contas e categorias ----------------------------

@bp.route('/api/financas/contas', methods=['POST'])
@login_financas
def api_salvar_conta(usuario):
    return _responder(fd.salvar_conta, _json())


@bp.route('/api/financas/contas/<int:conta_id>', methods=['DELETE'])
@login_financas
def api_apagar_conta(usuario, conta_id):
    return _responder(fd.apagar_conta, conta_id)


@bp.route('/api/financas/categorias', methods=['POST'])
@login_financas
def api_salvar_categoria(usuario):
    return _responder(fd.salvar_categoria, _json())


@bp.route('/api/financas/categorias/<int:cat_id>', methods=['DELETE'])
@login_financas
def api_apagar_categoria(usuario, cat_id):
    return _responder(fd.apagar_categoria, cat_id)


@bp.route('/api/financas/sugerir-categoria', methods=['GET'])
@login_financas
def api_sugerir_categoria(usuario):
    return _responder(fd.sugerir_categoria, request.args.get('descricao', ''), request.args.get('tipo', 'despesa'))


# ---------------------------- lançamentos e resumo ----------------------------

@bp.route('/api/financas/resumo', methods=['GET'])
@login_financas
def api_resumo(usuario):
    return _responder(fd.resumo_mes, request.args.get('mes'), request.args.get('pessoa') or None)


@bp.route('/api/financas/lancamentos', methods=['GET'])
@login_financas
def api_lancamentos(usuario):
    a = request.args
    return _responder(fd.listar_lancamentos, a.get('mes'), a.get('conta') or None, a.get('categoria') or None,
                      a.get('pessoa') or None, a.get('q') or None, a.get('tipo') or None)


@bp.route('/api/financas/lancamentos', methods=['POST'])
@login_financas
def api_criar_lancamento(usuario):
    return _responder(fd.criar_lancamento, _json(), usuario, status_ok=201)


@bp.route('/api/financas/lancamentos/<int:lanc_id>', methods=['PUT'])
@login_financas
def api_alterar_lancamento(usuario, lanc_id):
    dados = _json()
    return _responder(fd.alterar_lancamento, lanc_id, dados, usuario, bool(dados.get('todas_parcelas')))


@bp.route('/api/financas/lancamentos/<int:lanc_id>', methods=['DELETE'])
@login_financas
def api_apagar_lancamento(usuario, lanc_id):
    return _responder(fd.apagar_lancamento, lanc_id, request.args.get('todas') == '1')


# ---------------------------- cupom fiscal ----------------------------

@bp.route('/api/financas/cupons', methods=['GET'])
@login_financas
def api_cupons(usuario):
    return _responder(fd.listar_cupons)


@bp.route('/api/financas/cupons', methods=['POST'])
@login_financas
def api_ler_cupom(usuario):
    """Recebe o texto do QR Code ('texto') ou a foto dele ('foto', quando o celular não lê sozinho)."""
    dados = _json()
    def ler():
        texto = dados.get('texto')
        if not texto and dados.get('foto'):
            texto = fd.ler_qr_da_foto(dados['foto'])
        if not texto:
            raise fd.ErroFinancas("Leia o QR Code ou cole o link dele.")
        return fd.registrar_cupom(texto, usuario)
    return _responder(ler, status_ok=201)


@bp.route('/api/financas/cupons/<int:cupom_id>', methods=['GET'])
@login_financas
def api_cupom(usuario, cupom_id):
    return _responder(fd.obter_cupom, cupom_id)


@bp.route('/api/financas/cupons/<int:cupom_id>', methods=['DELETE'])
@login_financas
def api_apagar_cupom(usuario, cupom_id):
    return _responder(fd.apagar_cupom, cupom_id)


@bp.route('/api/financas/cupons/<int:cupom_id>/tentar', methods=['POST'])
@login_financas
def api_tentar_cupom(usuario, cupom_id):
    return _responder(fd.tentar_cupom_de_novo, cupom_id)


@bp.route('/api/financas/cupons/<int:cupom_id>/itens/<int:seq>', methods=['PATCH'])
@login_financas
def api_categoria_item(usuario, cupom_id, seq):
    dados = _json()
    return _responder(fd.mudar_categoria_item, cupom_id, seq, dados.get('categoria_id'), dados.get('iguais', True))


@bp.route('/api/financas/cupons/<int:cupom_id>/categoria', methods=['PATCH'])
@login_financas
def api_categoria_geral(usuario, cupom_id):
    return _responder(fd.mudar_categoria_geral, cupom_id, _json().get('categoria_id'))


@bp.route('/api/financas/cupons/<int:cupom_id>/lancar', methods=['POST'])
@login_financas
def api_lancar_cupom(usuario, cupom_id):
    return _responder(fd.lancar_cupom, cupom_id, _json(), usuario)

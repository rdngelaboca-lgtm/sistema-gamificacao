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
        logger.info(f"Pasta de logs criada em: {log_dir}") # Print inicial para confirmar criação
    except OSError as e:
        logger.exception(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
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

from flask import Flask, request, jsonify
from flask_cors import CORS
import database 
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from flask import send_from_directory
import notificador_telegram 
import config
import hashlib
import re

app = Flask(__name__)
CORS(app)

# --- LÓGICA DE CRIAÇÃO DA PASTA ---
# Pega o caminho do diretório onde o script está rodando
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Cria o caminho completo para a pasta de documentos
PASTA_DOCUMENTOS_SEGUROS = os.path.join(BASE_DIR, config.PASTA_DOCUMENTOS_RH)

# Cria a pasta se ela não existir
if not os.path.exists(PASTA_DOCUMENTOS_SEGUROS):
    os.makedirs(PASTA_DOCUMENTOS_SEGUROS)
    logger.info(f"--> PASTA CRIADA EM: {PASTA_DOCUMENTOS_SEGUROS}")

def formatar_data_pt_br(dt_obj, formato_str):
    """Uma função 'tradutora' para garantir que as datas saiam em português."""
    dias = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
    meses = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]
    
    # Formata a data e depois substitui os nomes em inglês pelos em português
    data_formatada = dt_obj.strftime(formato_str)
    data_formatada = data_formatada.replace(dt_obj.strftime('%A'), dias[dt_obj.weekday()])
    data_formatada = data_formatada.replace(dt_obj.strftime('%B'), meses[dt_obj.month - 1])
    return data_formatada

def criar_link_whatsapp(telefone):
    """Limpa o número de telefone e cria um link 'wa.me'."""
    if not telefone or not telefone.strip():
        return None, None
    
    # Remove todos os caracteres que não são números
    numeros = re.sub(r'\D', '', telefone)
    
    # Se não tiver um código de país (assumimos Brasil '55')
    if len(numeros) <= 11:
        numeros = "55" + numeros
        
    link = f"https://wa.me/{numeros}"
    return telefone, link



@app.route('/teste', methods=['GET'])
def rota_de_teste():
    """
    Um endpoint simples para verificar se o servidor está no ar e respondendo.
    """
    logger.info("Rota /teste foi chamada.")
    return jsonify(
        {
            "status": "sucesso",
            "mensagem": "O servidor da API está funcionando corretamente!"
        }
    ), 200 # 200 é o código HTTP para "OK"

@app.route('/api/agendamentos', methods=['GET'])
def rota_listar_agendamentos():
    """Endpoint para listar todos os agendamentos."""
    try:
        agendamentos_db = database.listar_agendamentos()
        
        lista_de_agendamentos = []
        for ag in agendamentos_db:
            lista_de_agendamentos.append({
                "agendamento_id": ag.AgendamentoID,
                "nome_cliente": ag.NomeCliente,
                "cpf_cliente": ag.CPFCliente,
                "telefone_cliente": ag.TelefoneCliente,
                "tipo_evento": ag.TipoEvento,
                "data_evento": ag.DataEvento.strftime('%d/%m/%Y %H:%M'), # Formata a data
                "status_agendamento": ag.StatusAgendamento,
                "status_pagamento": ag.StatusPagamento,
                "nome_funcionario": ag.NomeFuncionario
            })
            
        return jsonify(lista_de_agendamentos), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500


# Em api_server.py, SUBSTITUA a função rota_criar_agendamento inteira por esta:

@app.route('/agendamentos/novo', methods=['POST'])
def rota_criar_agendamento():
    """Endpoint para criar um novo agendamento."""
    dados = request.get_json()

    campos_obrigatorios = ['nome_cliente', 'tipo_evento', 'data_evento', 'funcionario_id']
    if not all(campo in dados for campo in campos_obrigatorios):
        return jsonify({"status": "erro", "mensagem": "Campos obrigatórios ausentes"}), 400

    try:
        data_evento_str = dados['data_evento']
        dados['data_evento'] = datetime.strptime(data_evento_str, '%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return jsonify({"status": "erro", "mensagem": "Formato de data_evento inválido. Use 'AAAA-MM-DD HH:MM'."}), 400

    sucesso, resultado = database.criar_agendamento(dados)

    if sucesso:
        novo_agendamento_id = resultado 

        # --- LÓGICA DE GAMIFICAÇÃO ---
        try:
            descricao_tarefa = (
                f"Cliente: {dados['nome_cliente']}\n"
                f"Evento: {dados['tipo_evento']}\n"
                f"Data/Hora: {dados['data_evento'].strftime('%d/%m/%Y %H:%M')}\n"
                f"Telefone: {dados.get('telefone_cliente', 'N/A')}\n"
                f"Observações: {dados.get('observacoes', 'Nenhuma')}"
            )
            
            database.atribuir_tarefa(
                tarefa_id=config.TAREFA_MODELO_AGENDAMENTO_ID,
                funcionario_id=config.RESPONSAVEL_AGENDAMENTOS_ID,
                tipo_frequencia='Unica', valor_frequencia=None,
                descricao_override=descricao_tarefa,
                data_agendamento=dados['data_evento'].date(),
                agendamento_id=novo_agendamento_id
            )
            logger.info(f"Tarefa de gamificação criada e vinculada ao Agendamento ID {novo_agendamento_id}")
        except Exception as e:
            logger.warning(f"!!! ATENÇÃO: Agendamento criado, mas falha ao criar a tarefa de gamificação: {e}")
        
        # --- BLOCO DE NOTIFICAÇÃO QUE ESTAVA FALTANDO ---
        try:
            data_formatada = dados['data_evento'].strftime('%d/%m/%Y às %H:%M')
            
            mensagem_alerta = (
                f"✅ **Novo Agendamento Recebido!** ✅\n\n"
                f"**Cliente:** {dados['nome_cliente']}\n"
                f"**Evento:** {dados['tipo_evento']}\n"
                f"**Quando:** {data_formatada}\n"
            )
            observacoes = dados.get('observacoes')
            if observacoes and observacoes.strip():
                mensagem_alerta += f"**Obs:** {observacoes.strip()}"
            
            notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem_alerta)
        except Exception as e:
            logger.warning(f"!!! ATENÇÃO: Agendamento criado, mas falha ao enviar notificação no Telegram: {e}")
        # --- FIM DO BLOCO DE NOTIFICAÇÃO ---

        return jsonify({"status": "sucesso", "mensagem": "Agendamento criado e equipe notificada!"}), 201
    else:
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500    

@app.route('/documentos/upload', methods=['POST'])
def rota_upload_documento():
    """
    Endpoint para fazer o upload de um documento pessoal (holerite, etc.)
    e salvar o registro no banco de dados.
    """
    try:
        if 'file' not in request.files:
            return jsonify({"status": "erro", "mensagem": "Nenhum arquivo enviado."}), 400

        arquivo = request.files['file']
        dados_form = request.form

        if arquivo.filename == '':
            return jsonify({"status": "erro", "mensagem": "Nenhum arquivo selecionado."}), 400

        funcionario_id = dados_form.get('funcionario_id')
        tipo_documento = dados_form.get('tipo_documento')
        mes_ano_str = dados_form.get('mes_ano') # Formato 'YYYY-MM-DD'

        if not all([funcionario_id, tipo_documento, mes_ano_str]):
            return jsonify({"status": "erro", "mensagem": "Dados do formulário incompletos."}), 400

        nome_arquivo_seguro = secure_filename(f"{tipo_documento.lower()}_{funcionario_id}_{mes_ano_str}.pdf")
        caminho_para_salvar = os.path.join(PASTA_DOCUMENTOS_SEGUROS, nome_arquivo_seguro)

        arquivo.save(caminho_para_salvar)
        logger.info(f">>> Arquivo '{nome_arquivo_seguro}' salvo com sucesso em '{PASTA_DOCUMENTOS_SEGUROS}'")

        documento_id = database.salvar_documento_pessoal(
            funcionario_id=funcionario_id,
            tipo_documento=tipo_documento,
            mes_ano=mes_ano_str,
            caminho_arquivo=caminho_para_salvar
        )

        if not documento_id:
            os.remove(caminho_para_salvar)
            return jsonify({"status": "erro", "mensagem": "Falha ao registrar o documento no banco de dados."}), 500
        
        database.criar_pendencia_ciencia_documento_pessoal(documento_id, funcionario_id)

        return jsonify({"status": "sucesso", "mensagem": "Documento enviado e registrado com sucesso!"}), 201

    except Exception as e:
        logger.error(f"Erro crítico em /documentos/upload: {e}", exc_info=True)
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
@app.route('/documentos/download/<int:documento_id>', methods=['GET'])
def rota_download_documento(documento_id):
    """
    Endpoint seguro para baixar um documento pessoal a partir do seu ID.
    """
    try:
        caminho_completo = database.buscar_caminho_documento(documento_id)

        if not caminho_completo or not os.path.exists(caminho_completo):
            return jsonify({"status": "erro", "mensagem": "Documento não encontrado."}), 404

        diretorio, nome_arquivo = os.path.split(caminho_completo)

        logger.info(f">>> Enviando o arquivo '{nome_arquivo}' do diretório '{diretorio}'")
        return send_from_directory(diretorio, nome_arquivo, as_attachment=True)

    except Exception as e:
        logger.exception(f"!!! ERRO CRÍTICO em /documentos/download: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    

@app.route('/agendamentos/<int:agendamento_id>', methods=['PUT'])
def rota_atualizar_agendamento(agendamento_id):
    """Endpoint para atualizar um agendamento existente."""
    dados = request.get_json()
    if not dados:
        return jsonify({"status": "erro", "mensagem": "Dados não enviados."}), 400

    # --- ADICIONANDO A MESMA CORREÇÃO AQUI ---
    if 'data_evento' in dados:
        try:
            data_evento_str = dados['data_evento']
            dados['data_evento'] = datetime.strptime(data_evento_str, '%Y-%m-%d %H:%M')
        except (ValueError, TypeError):
            return jsonify({"status": "erro", "mensagem": "Formato de data_evento inválido para atualização."}), 400
    # ---------------------------------------

    sucesso = database.atualizar_agendamento(agendamento_id, dados)
    if sucesso:
        # --- LÓGICA DE SINCRONIZAÇÃO NA ATUALIZAÇÃO ---
        try:
            nova_descricao = (
                f"Cliente: {dados['nome_cliente']}\n"
                f"Evento: {dados['tipo_evento']}\n"
                f"Data/Hora: {dados['data_evento'].strftime('%d/%m/%Y %H:%M')}\n"
                f"Telefone: {dados.get('telefone_cliente', 'N/A')}\n"
                f"Observações: {dados.get('observacoes', 'Nenhuma')}"
            )
            dados_sync = {
                "data_agendamento": dados['data_evento'].date(),
                "descricao_override": nova_descricao
            }
            database.atualizar_tarefa_do_agendamento(agendamento_id, dados_sync)
            logger.info(f"Tarefa de gamificação do Agendamento ID {agendamento_id} foi sincronizada.")
        except Exception as e:
            logger.warning(f"!!! ATENÇÃO: Agendamento atualizado, mas falha ao sincronizar a tarefa: {e}")

        return jsonify({"status": "sucesso", "mensagem": "Agendamento atualizado com sucesso!"}), 200
    else:
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500


@app.route('/agendamentos/<int:agendamento_id>', methods=['DELETE'])
def rota_excluir_agendamento(agendamento_id):
    try:
        # --- LÓGICA DE SINCRONIZAÇÃO NA EXCLUSÃO ---
        database.excluir_tarefa_do_agendamento(agendamento_id)
        logger.info(f"Tarefa de gamificação do Agendamento ID {agendamento_id} foi excluída.")
    except Exception as e:
        logger.warning(f"!!! ATENÇÃO: Falha ao excluir a tarefa de gamificação vinculada: {e}")
        
    sucesso = database.excluir_agendamento(agendamento_id)
    if sucesso:
        return '', 204
    else:
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
@app.route('/agendamentos/<int:agendamento_id>/pagamento', methods=['PATCH'])
def rota_patch_pagamento(agendamento_id):
    """Endpoint para atualizar SOMENTE o status do pagamento."""
    dados = request.get_json()
    novo_status = dados.get('status')
    if not novo_status or novo_status not in ['Pago', 'Pendente']:
        return jsonify({"status": "erro", "mensagem": "Status de pagamento inválido."}), 400

    sucesso = database.atualizar_status_pagamento(agendamento_id, novo_status)
    if sucesso:
        return jsonify({"status": "sucesso", "mensagem": f"Status de pagamento atualizado para '{novo_status}'."}), 200
    else:
        return jsonify({"status": "erro", "mensagem": "Falha ao atualizar o status de pagamento."}), 500
    
@app.route('/agendamentos/<int:agendamento_id>', methods=['GET'])
def rota_buscar_agendamento(agendamento_id):
    """Endpoint para buscar os detalhes de um único agendamento."""
    agendamento = database.buscar_agendamento_por_id(agendamento_id)
    if agendamento:
        # Converte o objeto do banco em um dicionário JSON amigável
        ag_dict = {
            "agendamento_id": agendamento.AgendamentoID, "nome_cliente": agendamento.NomeCliente,
            "cpf_cliente": agendamento.CPFCliente, "telefone_cliente": agendamento.TelefoneCliente,
            "tipo_evento": agendamento.TipoEvento, "data_evento": agendamento.DataEvento.strftime('%d/%m/%Y %H:%M'),
            "status_agendamento": agendamento.StatusAgendamento, "status_pagamento": agendamento.StatusPagamento,
            "observacoes": agendamento.Observacoes, "funcionario_id": agendamento.FuncionarioID
        }
        return jsonify(ag_dict), 200
    else:
        return jsonify({"status": "erro", "mensagem": "Agendamento não encontrado."}), 404
    
@app.route('/agendamentos/enviar-lembrete-geral', methods=['POST'])
def rota_enviar_lembrete_geral():
    """
    Busca todos os agendamentos futuros e envia um resumo completo para o Telegram.
    """
    try:
        agendamentos_db = database.listar_agendamentos()
        
        agendamentos_futuros = sorted(
            [ag for ag in agendamentos_db if ag.DataEvento > datetime.now()],
            key=lambda ag: ag.DataEvento
        )

        if not agendamentos_futuros:
            mensagem = "✅ Nenhum agendamento futuro encontrado no sistema."
        else:
            mensagem = "🗓️ **Resumo de Todos os Agendamentos Futuros** 🗓️\n"
            data_atual = None
            for i, ag in enumerate(agendamentos_futuros):
                if ag.DataEvento.date() != data_atual:
                    data_atual = ag.DataEvento.date()
                    data_formatada = formatar_data_pt_br(data_atual, '%A, %d de %B de %Y')
                    mensagem += f"\n{'=' * 40}\n**{data_formatada}**\n{'=' * 40}\n"
                
                hora_formatada = ag.DataEvento.strftime('%H:%M')
                mensagem += f"\n🔹 **{ag.TipoEvento}**\n"
                mensagem += f"  - ⏰ **{hora_formatada}**\n"
                mensagem += f"  - 👤 **Cliente:** {ag.NomeCliente}\n"
                
                # --- NOVAS INFORMAÇÕES AQUI ---
                telefone_limpo, link_wpp = criar_link_whatsapp(ag.TelefoneCliente)
                if telefone_limpo:
                    mensagem += f"  - 📞 **Telefone:** [{telefone_limpo}]({link_wpp})\n"
                
                if ag.CPFCliente and ag.CPFCliente.strip():
                    mensagem += f"  - 📄 **CPF:** {ag.CPFCliente.strip()}\n"

                status_pag = "PAGO" if ag.StatusPagamento == "Pago" else "RECEBER (Pendente)"
                mensagem += f"  - 💰 **Pagamento:** **{status_pag}**\n"
                # --- FIM DAS NOVAS INFORMAÇÕES ---

                if ag.Observacoes and ag.Observacoes.strip():
                    mensagem += "  - 📝 **Observações:**\n"
                    for linha in ag.Observacoes.strip().splitlines():
                        mensagem += f"    > _{linha.strip()}_\n"
                
                if (i + 1) < len(agendamentos_futuros) and agendamentos_futuros[i+1].DataEvento.date() == data_atual:
                    mensagem += "\n`- - - - - - - - - - - - - - - - -`\n"

        notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
        return jsonify({"status": "sucesso", "mensagem": "Lembrete geral enviado com sucesso!"}), 200

    except Exception as e:
        logger.exception(f"!!! ERRO em /enviar-lembrete-geral: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500    

@app.route('/login', methods=['POST'])
def rota_login():
    """Endpoint para autenticar um funcionário."""
    dados = request.get_json()
    if not dados or 'id' not in dados or 'senha' not in dados:
        return jsonify({"status": "erro", "mensagem": "ID e senha são obrigatórios."}), 400

    funcionario_id = dados['id']
    senha_digitada = dados['senha']

    try:
        dados_funcionario_db = database.autenticar_funcionario(int(funcionario_id))

        if dados_funcionario_db and dados_funcionario_db.SenhaHash:
            senha_hash_digitada = hashlib.sha256(senha_digitada.encode('utf-8')).hexdigest()

            if senha_hash_digitada == dados_funcionario_db.SenhaHash:
                # Login bem-sucedido! Retorna os dados do funcionário.
                return jsonify({
                    "status": "sucesso",
                    "mensagem": f"Acesso liberado para {dados_funcionario_db.NomeCompleto}!",
                    "funcionario": {
                        "id": dados_funcionario_db.FuncionarioID,
                        "nome": dados_funcionario_db.NomeCompleto
                    }
                }), 200
            else:
                return jsonify({"status": "erro", "mensagem": "Senha incorreta."}), 401 # 401 Unauthorized
        elif dados_funcionario_db:
            return jsonify({"status": "erro", "mensagem": "Usuário sem senha cadastrada."}), 401
        else:
            return jsonify({"status": "erro", "mensagem": "ID de funcionário não encontrado."}), 404 # 404 Not Found

    except Exception as e:
        logger.exception(f"!!! ERRO em /login: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
# Em api_server.py, adicione esta nova rota

@app.route('/api/painel/tarefas', methods=['GET'])
def rota_painel_tarefas():
    try:
        dados_painel = database.buscar_dados_para_painel_kanban()
        return jsonify(dados_painel), 200
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/painel/tarefas: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500

    

# Em api_server.py, substitua a função inteira pela versão corrigida e simplificada

@app.route('/api/ranking/diario', methods=['GET'])
def rota_ranking_diario():
    try:
        ranking_do_dia = database.buscar_ranking_do_dia()
        return jsonify(ranking_do_dia), 200
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/ranking/diario: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
# Em api_server.py, adicione esta nova rota

@app.route('/api/feed', methods=['GET'])
def rota_feed():
    """
    Endpoint que fornece os últimos eventos para o feed de atividades.
    """
    try:
        feed_data = database.buscar_feed_de_atividades(limite=7) # Podemos pegar 7, por exemplo
        return jsonify(feed_data), 200
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/feed: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
# Adicione esta nova rota ao final de api_server.py
@app.route('/api/meta_principal_do_dia', methods=['GET'])
def rota_meta_principal_do_dia():
    """Endpoint para o painel web buscar a meta principal ativa e seu progresso."""
    try:
        dados_meta = database.buscar_meta_principal_do_dia()
        if dados_meta:
            return jsonify(dados_meta), 200
        else:
            # Se não houver meta ativa, retorna um objeto vazio para não quebrar o painel
            return jsonify({}), 200 
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/meta_principal_do_dia: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
# Em api_server.py, adicione esta nova rota ao final

@app.route('/api/meta_diaria_do_dia', methods=['GET'])
def rota_meta_diaria_do_dia():
    """Endpoint para o painel web buscar a meta diária e seu progresso."""
    try:
        dados_meta_diaria = database.buscar_dados_meta_diaria_hoje()
        if dados_meta_diaria:
            return jsonify(dados_meta_diaria), 200
        else:
            return jsonify({}), 200 # Retorna objeto vazio se não houver meta para o dia
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/meta_diaria_do_dia: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
@app.route('/api/agendamentos/proximos', methods=['GET'])
def rota_proximos_agendamentos():
    """Endpoint para buscar apenas os próximos agendamentos para o painel."""
    try:
        # Chama a nova função do banco
        proximos = database.buscar_proximos_agendamentos(limite=5)
        # A função do banco já retorna a lista de dicionários formatada
        return jsonify(proximos), 200
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/agendamentos/proximos: {e}")
        return jsonify({"status": "erro", "mensagem": "Erro ao buscar próximos agendamentos."}), 500
    
# Em api_server.py, adicione esta nova rota
@app.route('/api/historico_lucro', methods=['GET'])
def rota_historico_lucro():
    """Endpoint para fornecer o histórico de lucro dos últimos 3 meses."""
    try:
        historico = database.buscar_historico_lucro_ultimos_meses(num_meses=3)
        return jsonify(historico), 200
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/historico_lucro: {e}")
        return jsonify({"status": "erro", "mensagem": "Erro ao buscar histórico de lucro."}), 500 
    
if __name__ == '__main__':
    # O debug=False é essencial para rodar como serviço
    app.run(host='0.0.0.0', port=5000, debug=False)

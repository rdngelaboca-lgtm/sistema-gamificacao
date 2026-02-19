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

from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
import database 
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from flask import send_from_directory
import notificador_telegram 
import config
import hashlib
import re
import notificador_whatsapp 

app = Flask(__name__)
# Configuração de Segurança de Sessão
app.secret_key = config.SECRET_KEY_FLASK 
# Se der erro de chave não encontrada, use temporariamente: app.secret_key = "chave_provisoria_segura"
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

# --- FUNÇÕES AUXILIARES DE CORREÇÃO ---

def _executar_sql_auxiliar(sql, params):
    """Executa SQLs que faltam no database.py sem alterar o arquivo original."""
    conn = database.get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro em SQL auxiliar: {e}")
            return False
        finally:
            conn.close()
    return False

def _parse_horario_seguro(valor):
    """Converte timedelta, datetime ou string para 'HH:MM'."""
    if valor is None: return None
    if isinstance(valor, timedelta):
        total_seconds = int(valor.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
    if hasattr(valor, 'strftime'): 
        return valor.strftime('%H:%M')
    return str(valor)[:5]

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
                "nome_funcionario": ag.NomeFuncionario,
                "observacoes": ag.Observacoes
            })
            
        return jsonify(lista_de_agendamentos), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500


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

        # --- 1. LÓGICA DE GAMIFICAÇÃO (MANTIDA) ---
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
            logger.info(f"Tarefa de gamificação criada para Agendamento ID {novo_agendamento_id}")
        except Exception as e:
            logger.warning(f"!!! Falha na gamificação: {e}")
        
        # --- 2. NOTIFICAÇÃO TELEGRAM GRUPO (MANTIDA) ---
        try:
            data_formatada = dados['data_evento'].strftime('%d/%m/%Y às %H:%M')
            mensagem_alerta = (
                f"✅ **Novo Agendamento Recebido!** ✅\n\n"
                f"**Cliente:** {dados['nome_cliente']}\n"
                f"**Evento:** {dados['tipo_evento']}\n"
                f"**Quando:** {data_formatada}\n"
            )
            if dados.get('observacoes'):
                mensagem_alerta += f"**Obs:** {dados['observacoes']}"
            
            notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem_alerta)
        except Exception as e:
            logger.warning(f"!!! Falha no Telegram: {e}")

        # --- 3. NOVA AUTOMAÇÃO WHATSAPP (CLIENTE) ---
        telefone_cliente = dados.get('telefone_cliente')
        if telefone_cliente:
            try:
                # Prepara os dados
                nome_cliente = dados['nome_cliente'].split()[0]
                hora_evento = dados['data_evento'].strftime('%H:%M')
                data_evento = dados['data_evento'].strftime('%d/%m/%Y')
                tipo_evento = dados['tipo_evento']

                msg_zap = (
                    f"Olá, *{nome_cliente}*! Tudo bem? 👋\n\n"
                    f"Seu agendamento de *{tipo_evento}* foi confirmado com sucesso!\n"
                    f"🗓️ Data: *{data_evento}*\n"
                    f"⏰ Horário: *{hora_evento}*\n\n"
                    f"Agradecemos a preferência! 🍦"
                )

                # Envia imediatamente
                ok, resp = notificador_whatsapp.enviar_mensagem_whatsapp(telefone_cliente, msg_zap)
                
                if ok:
                    # Marca no banco que já enviou a mensagem de criação
                    database.marcar_flag_agendamento(novo_agendamento_id, 'criacao')
                    logger.info(f"--> WhatsApp de confirmação enviado para {nome_cliente}.")
                else:
                    logger.error(f"--> Falha ao enviar WhatsApp para {nome_cliente}: {resp}")

            except Exception as e:
                logger.error(f"--> Erro crítico na automação WhatsApp: {e}")
        # ---------------------------------------------

        return jsonify({"status": "sucesso", "mensagem": "Agendamento criado e notificações enviadas!"}), 201
    else:
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor."}), 500

@app.route('/documentos/upload', methods=['POST'])
def rota_upload_documento():
    """
    Endpoint para fazer o upload de um documento pessoal (holerite, etc.)
    e salvar o registro no banco de dados.
    (VERSÃO CORRIGIDA PARA ACEITAR PDF, JPG e PNG)
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

        # --- CORREÇÃO APLICADA AQUI ---
        # 1. Pegamos a extensão do arquivo original enviado
        nome_original = arquivo.filename
        extensao = os.path.splitext(nome_original)[1].lower() # ex: '.jpg', '.pdf', '.png'

        # 2. Validamos por segurança (adicionado .png)
        if extensao not in ['.pdf', '.jpg', '.jpeg', '.png']: # <-- ADICIONADO .png
            return jsonify({"status": "erro", "mensagem": "Tipo de arquivo não suportado pelo servidor."}), 400

        # 3. Usamos a extensão dinâmica no nome do arquivo
        nome_arquivo_seguro = secure_filename(f"{tipo_documento.lower()}_{funcionario_id}_{mes_ano_str}{extensao}")
        # --- FIM DA CORREÇÃO ---
        
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
    
@app.route('/documentos/excluir/<int:documento_id>', methods=['DELETE'])
def rota_excluir_documento_fisico(documento_id):
    """
    Endpoint para excluir o arquivo físico e o registro do banco.
    """
    try:
        # 1. Busca o caminho antes de excluir do banco
        caminho_completo = database.buscar_caminho_documento(documento_id)
        
        # 2. Exclui do banco (Cascata)
        sucesso_db, _ = database.excluir_documento_pessoal_completo(documento_id)
        
        if not sucesso_db:
            return jsonify({"status": "erro", "mensagem": "Falha ao excluir registro do banco."}), 500

        # 3. Exclui o arquivo físico
        if caminho_completo and os.path.exists(caminho_completo):
            try:
                os.remove(caminho_completo)
                logger.info(f"Arquivo físico excluído: {caminho_completo}")
            except OSError as e:
                logger.error(f"Erro ao excluir arquivo físico: {e}")
                # Não retorna erro 500 pois o registro já saiu do banco
                return jsonify({"status": "alerta", "mensagem": "Registro excluído, mas erro ao apagar arquivo físico."}), 200

        return jsonify({"status": "sucesso", "mensagem": "Documento excluído com sucesso."}), 200

    except Exception as e:
        logger.error(f"Erro crítico em /documentos/excluir: {e}", exc_info=True)
        return jsonify({"status": "erro", "mensagem": "Erro interno no servidor."}), 500

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
        feed_data = database.buscar_feed_de_atividades(limite=15) # Podemos pegar 7, por exemplo
        return jsonify(feed_data), 200
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/feed: {e}")
        return jsonify({"status": "erro", "mensagem": "Ocorreu um erro interno no servidor. Tente novamente mais tarde ou contate o suporte."}), 500
    
@app.route('/imagens/entregas/<path:filename>')
def servir_imagem_entrega(filename):
    """
    Rota para servir as imagens de evidência salvas na pasta 'entregas'.
    """
    pasta_entregas = os.path.join(BASE_DIR, 'entregas') # Assume que a pasta 'entregas' está na raiz do projeto
    return send_from_directory(pasta_entregas, filename)

    
# Adicione esta nova rota ao final de api_server.py
@app.route('/api/meta_principal_do_dia', methods=['GET'])
def rota_meta_principal_do_dia():
    """Endpoint para o painel web buscar a meta principal ativa e seu progresso."""
    try:
        dados_meta = database.buscar_meta_principal_do_dia()
        if dados_meta:
            return jsonify(dados_meta), 200
        else:
            # [CORREÇÃO] Retorna estrutura zerada para evitar erro de "undefined" no JS do painel
            return jsonify({
            "nome_meta": "Sem Meta Ativa",
            "valor_meta": 0.0,
            "valor_atingido": 0.0
        }), 200 
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
    
@app.route('/api/resgates/recentes', methods=['GET'])
def rota_resgates_recentes():
    """Endpoint para fornecer os últimos resgates aprovados para o painel."""
    try:
        resgates = database.buscar_resgates_recentes(limite=15) # Busca os últimos 5
        return jsonify(resgates), 200
    except Exception as e:
        logger.exception(f"!!! ERRO no endpoint /api/resgates/recentes: {e}")
        return jsonify({"status": "erro", "mensagem": "Erro ao buscar resgates recentes."}), 500   

@app.route('/api/escala/hoje', methods=['GET'])
def rota_escala_hoje():
    """
    (VERSÃO SIMPLIFICADA) Retorna APENAS as posições que têm alguém trabalhando AGORA.
    Usa o horário local do servidor, sem conversão de fuso forçada.
    """
    try:
        # Pega data e hora do sistema operacional (Lubuntu)
        agora_dt = datetime.now()
        hoje_str = agora_dt.strftime('%Y-%m-%d')
        agora_str = agora_dt.strftime('%H:%M:%S')
        
        # Log para debug (verifique no terminal se a hora bate com a real)
        # logger.info(f"API Escala Tempo Real -> Data: {hoje_str} | Hora: {agora_str}")

        # Busca quem está escalado EXATAMENTE neste minuto
        escala_do_momento = database.buscar_escala_tempo_real(hoje_str, agora_str)
        posicoes = database.listar_posicoes_loja()

        dados_mapa = []
        for pos in posicoes:
            pos_id, nome, x, y, ativo, setor = pos

            # Só processamos se houver alguém na escala DO MOMENTO
            if pos_id in escala_do_momento:
                dados = escala_do_momento[pos_id]
                
                if not dados.NomePessoa: continue

                nome_pessoa = dados.NomePessoa
                cor = "#00C851" # Verde (Padrão: Trabalhando)
                
                # Formatação segura de hora
                fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5]
                
                entrada = fmt(dados.HorarioEntrada) if dados.HorarioEntrada else "--"
                saida = fmt(dados.HorarioSaida) if dados.HorarioSaida else "--"
                detalhes = f"Até {saida}" 

                # Checagem visual de intervalo
                if dados.InicioIntervalo and dados.FimIntervalo:
                    try:
                        # Converte para objeto time para comparar
                        # Truque: converte a string HH:MM:SS para time
                        agora_time = agora_dt.time()
                        
                        def to_time(val):
                            if isinstance(val, timedelta): return (datetime.min + val).time()
                            if hasattr(val, 'time'): return val.time()
                            if hasattr(val, 'strftime'): return val.time()
                            # Se for string, tenta parsear
                            if isinstance(val, str):
                                try: return datetime.strptime(val[:5], '%H:%M').time()
                                except: return None
                            return None

                        ini_t = to_time(dados.InicioIntervalo)
                        fim_t = to_time(dados.FimIntervalo)

                        if ini_t and fim_t:
                            # Se agora estiver dentro do intervalo
                            if ini_t <= agora_time <= fim_t:
                                detalhes = "EM INTERVALO ☕"
                                cor = "#FFBB33" # Amarelo
                            else:
                                detalhes += f" (☕ {fmt(dados.InicioIntervalo)})"
                    except Exception as e_int:
                        # Em caso de erro no cálculo de hora, segue normal
                        detalhes += " (Intervalo)"

                # Adiciona à lista final
                dados_mapa.append({
                    "id": pos_id,
                    "nome_posicao": nome,
                    "x": x,
                    "y": y,
                    "ocupante": nome_pessoa,
                    "cor": cor,
                    "detalhes": detalhes,
                    "setor": setor
                })

        return jsonify(dados_mapa), 200
    except Exception as e:
        logger.error(f"Erro na rota /api/escala/hoje: {e}", exc_info=True)
        return jsonify([]), 500
        
@app.route('/api/escala/ocupacao', methods=['GET'])
def rota_escala_ocupacao():
    """
    Retorna os DADOS BRUTOS de horários para o frontend calcular o gráfico.
    Isso permite filtrar por setor dinamicamente no Javascript.
    """
    try:
        hoje_str = datetime.now().strftime('%Y-%m-%d')
        # Reutiliza a função do banco que já traz (Entrada, Saida, IntIni, IntFim, Setor)
        horarios = database.buscar_horarios_ocupacao_hoje(hoje_str, 0)

        dados_formatados = []

        def formatar_hora(val):
            if val is None: return None
            # Se for datetime/time, converte para string "HH:MM"
            if hasattr(val, 'strftime'): return val.strftime('%H:%M')
            return str(val)

        for row in horarios:
            # row = (Entrada, Saida, InicioIntervalo, FimIntervalo, Setor)
            dados_formatados.append({
                "entrada": formatar_hora(row[0]),
                "saida": formatar_hora(row[1]),
                "int_ini": formatar_hora(row[2]),
                "int_fim": formatar_hora(row[3]),
                "setor": row[4]
            })

        return jsonify(dados_formatados), 200

    except Exception as e:
        logger.error(f"Erro na rota ocupacao: {e}", exc_info=True)
        return jsonify([]), 500
    
@app.route('/webhook/whatsapp', methods=['POST'])
def webhook_whatsapp():
    """
    Recebe notificações de mensagens recebidas via API do WhatsApp.
    Aqui você implementará a lógica para processar o 'Confirmado' do freelancer.
    """
    try:
        dados = request.get_json()

        # Log genérico para depuração (ver o que a API manda)
        # logger.info(f"Webhook WPP Recebido: {dados}")

        # Exemplo de lógica futura (Depende do formato da sua API):
        # 1. Extrair telefone do remetente
        # 2. Extrair texto da mensagem
        # 3. Se texto == "CONFIRMO":
        #    Buscar na tabela EscalaDiaria quem tem esse telefone na data de hoje/amanhã
        #    e atualizar status visual (cor verde, etc).

        return jsonify({"status": "recebido"}), 200
    except Exception as e:
        logger.error(f"Erro no Webhook WPP: {e}")
        return jsonify({"status": "erro"}), 500
    
@app.route('/api/escala/tabela', methods=['GET'])
def rota_escala_tabela():
    """
    Retorna a escala agrupada por SETORES.
    Versão ultra-defensiva para não derrubar o servidor.
    """
    try:
        data_url = request.args.get('data')
        
        # Fallback seguro de data
        if data_url:
            hoje_str = data_url
        else:
            hoje_str = datetime.now().strftime('%Y-%m-%d')

        # Busca dados (agora sabemos que database.py trata exceções)
        dados_brutos = database.listar_escala_detalhada_ordenada(hoje_str)
        
        # Se vier vazio ou None, retorna JSON vazio válido
        if not dados_brutos:
            return jsonify({}), 200
        
        # Processamento
        escala_agrupada = {}
        
        # Helpers internos seguros
        def safe_fmt(val): return str(val)[:5] if val else "--:--"

        for row in dados_brutos:
            try:
                # Acesso posicional seguro (0 a 11)
                if len(row) < 9: continue # Pula linhas malformadas
                
                setor = row[2] if row[2] else "Geral"
                
                func_obj = {
                    "nome": row[4] or "Sem Nome",
                    "posicao": row[3] or "Posição",
                    "entrada": safe_fmt(row[5]),
                    "saida": safe_fmt(row[6]),
                    "int_ini": safe_fmt(row[7]),
                    "int_fim": safe_fmt(row[8]),
                    "status": "normal" # Simplificado para evitar erro de lógica de tempo
                }

                if setor not in escala_agrupada:
                    escala_agrupada[setor] = []
                escala_agrupada[setor].append(func_obj)
            except Exception as e_row:
                logger.error(f"Erro processando linha escala: {e_row}")
                continue

        return jsonify(escala_agrupada), 200

    except Exception as e:
        logger.error(f"Erro Rota Tabela: {e}")
        # Retorna JSON vazio em vez de erro 500 para o front não travar
        return jsonify({}), 200


# --- SISTEMA DE AUTENTICAÇÃO ---

def login_required(f):
    """Protege rotas que exigem login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            return redirect(url_for('page_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login')
def page_login():
    """Renderiza a página de login."""
    # Se já estiver logado, manda pro painel (ou futura home admin)
    if 'usuario_id' in session:
        return redirect(url_for('index')) 
    return render_template('login.html')

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Recebe dados do formulário e valida no banco."""
    dados = request.json
    usuario = dados.get('usuario')
    senha = dados.get('senha')
    
    user_data = database.verificar_credenciais(usuario, senha)
    
    if user_data:
        session['usuario_id'] = user_data['id']
        session['usuario_nome'] = user_data['nome']
        session['nivel'] = user_data['nivel']
        return jsonify({"sucesso": True, "nome": user_data['nome']})
    else:
        return jsonify({"sucesso": False, "erro": "Usuário ou senha incorretos."}), 401

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({"sucesso": True})

@app.route('/api/auth/check')
def api_check_auth():
    """Verifica se o usuário está logado (para o frontend saber)."""
    if 'usuario_id' in session:
        return jsonify({"logado": True, "nome": session['usuario_nome']})
    return jsonify({"logado": False})

# --- ADICIONE ESTE BLOCO QUE ESTÁ FALTANDO ---

@app.route('/')
def index():
    """Rota da Página Principal (Painel da TV)."""
    return render_template('painel.html')

# ---------------------------------------------

# --- ROTAS PARA CONTAGEM MOBILE ---

@app.route('/mobile/contagem')
def page_contagem_mobile():
    """Renderiza a página HTML de contagem."""
    return render_template('mobile_contagem.html')

@app.route('/api/produto/ean/<codigo>', methods=['GET'])
def rota_buscar_ean(codigo):
    """Busca dados do produto ao bipar."""
    res = database.buscar_produto_por_ean(codigo)
    if res:
        return jsonify({
            "encontrado": True,
            "id": res[0],
            "nome": res[1],
            "unidade": res[2],
            "fator": float(res[3]) if res[3] else 1.0
        })
    else:
        return jsonify({"encontrado": False}), 404
    
@app.route('/api/produto/buscar/<termo>', methods=['GET'])
def rota_buscar_por_nome(termo):
    """Busca produtos por nome para o mobile."""
    resultados = database.buscar_produtos_mobile_por_nome(termo)
    lista = []
    for row in resultados:
        lista.append({
            "id_vinculo": row[0],
            "nome_mestre": row[1],
            "desc_xml": row[2],
            "fornecedor": row[3],
            "fator": float(row[4]) if row[4] else 1.0,
            "ean_existente": row[5]
        })
    return jsonify(lista)

@app.route('/api/produto/criar-unidade', methods=['POST'])
def rota_criar_unidade():
    """Cria cadastro de unidade a partir de uma caixa."""
    dados = request.json
    id_origem = dados.get('id_origem') # ID da Caixa
    novo_ean = dados.get('novo_ean')   # EAN da Unidade (que falhou ao bipar)
    qtd_caixa = dados.get('qtd_caixa') # Quantas unidades vem na caixa

    if not all([id_origem, novo_ean, qtd_caixa]):
        return jsonify({"sucesso": False, "erro": "Dados incompletos"}), 400

    sucesso, msg = database.criar_unidade_a_partir_de_caixa(id_origem, novo_ean, float(qtd_caixa))

    if sucesso:
        # Já retorna os dados do novo produto para adicionar na contagem imediatamente
        # Busca o produto recém criado para garantir
        res = database.buscar_produto_por_ean(novo_ean)
        if res:
            return jsonify({
                "sucesso": True,
                "msg": msg,
                "produto": {
                    "id": res[0], "nome": res[1], "unidade": res[2], "fator": 1.0
                }
            })

    return jsonify({"sucesso": False, "erro": msg}), 500

@app.route('/api/contagem/salvar-mobile', methods=['POST'])
def rota_salvar_contagem_mobile():
    """Recebe o JSON do celular e salva no banco."""
    dados = request.json
    # dados = { 'funcionario_id': 2, 'itens': [ {'ProdutoID': 1, 'QuantidadeContada': 10}, ... ] }

    data_hoje = datetime.now().strftime('%Y-%m-%d')
    funcionario_id = dados.get('funcionario_id', 2) # Default Gestor se não vier
    itens = dados.get('itens', [])

    if not itens:
        return jsonify({"sucesso": False, "erro": "Lista vazia"}), 400

    sucesso, msg = database.salvar_contagem_estoque(data_hoje, funcionario_id, itens)

    if sucesso:
        return jsonify({"sucesso": True, "msg": msg})
    else:
        return jsonify({"sucesso": False, "erro": msg}), 500

if __name__ == "__main__":
    # O '0.0.0.0' é o segredo. Ele libera o acesso para a rede inteira.
    logger.info("Iniciando servidor API acessível na rede...")
    app.run(host='0.0.0.0', port=5000, debug=True)

from flask import Flask, request, jsonify
import database 
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from flask import send_from_directory

app = Flask(__name__)

PASTA_DOCUMENTOS_SEGUROS = "/home/rodrigoaraujo/documentos_rh"

@app.route('/teste', methods=['GET'])
def rota_de_teste():
    """
    Um endpoint simples para verificar se o servidor está no ar e respondendo.
    """
    print(">>> Rota /teste foi chamada com sucesso!")
    return jsonify(
        {
            "status": "sucesso",
            "mensagem": "O servidor da API está funcionando corretamente!"
        }
    ), 200 # 200 é o código HTTP para "OK"

@app.route('/agendamentos', methods=['GET'])
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
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/agendamentos/novo', methods=['POST'])
def rota_criar_agendamento():
    """Endpoint para criar um novo agendamento."""
    dados = request.get_json()

    campos_obrigatorios = ['nome_cliente', 'tipo_evento', 'data_evento', 'funcionario_id']
    if not all(campo in dados for campo in campos_obrigatorios):
        return jsonify({"status": "erro", "mensagem": "Campos obrigatórios ausentes"}), 400

    # --- A MÁGICA DA CORREÇÃO ACONTECE AQUI ---
    try:
        # 1. Pegamos a string que veio do cliente (Ex: '2025-11-29 14:00')
        data_evento_str = dados['data_evento']
        # 2. Convertemos ela de volta para um objeto datetime do Python
        dados['data_evento'] = datetime.strptime(data_evento_str, '%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        # Se o formato for inválido ou o campo não existir, retornamos um erro claro.
        return jsonify({"status": "erro", "mensagem": "Formato de data_evento inválido. Use 'AAAA-MM-DD HH:MM'."}), 400
    # ---------------------------------------------

    sucesso, erro_db = database.criar_agendamento(dados) # <-- AGORA passamos o objeto datetime!

    if sucesso:
        return jsonify({"status": "sucesso", "mensagem": "Agendamento criado com sucesso!"}), 201
    else:
        return jsonify({"status": "erro", "mensagem": f"Erro no banco de dados: {erro_db}"}), 500
    

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
        print(f">>> Arquivo '{nome_arquivo_seguro}' salvo com sucesso em '{PASTA_DOCUMENTOS_SEGUROS}'")

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
        print(f"!!! ERRO CRÍTICO em /documentos/upload: {e}")
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {e}"}), 500
    
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

        print(f">>> Enviando o arquivo '{nome_arquivo}' do diretório '{diretorio}'")
        return send_from_directory(diretorio, nome_arquivo, as_attachment=True)

    except Exception as e:
        print(f"!!! ERRO CRÍTICO em /documentos/download: {e}")
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {e}"}), 500
    

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
        return jsonify({"status": "sucesso", "mensagem": "Agendamento atualizado com sucesso!"}), 200
    else:
        return jsonify({"status": "erro", "mensagem": "Falha ao atualizar o agendamento."}), 500

@app.route('/agendamentos/<int:agendamento_id>', methods=['DELETE'])
def rota_excluir_agendamento(agendamento_id):
    """Endpoint para excluir um agendamento."""
    sucesso = database.excluir_agendamento(agendamento_id)
    if sucesso:
        return '', 204
    else:
        return jsonify({"status": "erro", "mensagem": "Falha ao excluir o agendamento."}), 500

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
            "tipo_evento": agendamento.TipoEvento, "data_evento": agendamento.DataEvento.strftime('%Y-%m-%d %H:%M'),
            "status_agendamento": agendamento.StatusAgendamento, "status_pagamento": agendamento.StatusPagamento,
            "observacoes": agendamento.Observacoes, "funcionario_id": agendamento.FuncionarioID
        }
        return jsonify(ag_dict), 200
    else:
        return jsonify({"status": "erro", "mensagem": "Agendamento não encontrado."}), 404

if __name__ == '__main__':
    print(">>> Iniciando o Servidor da API...")
    app.run(host='0.0.0.0', port=5000, debug=True)

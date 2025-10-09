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
        return jsonify({"status": "erro", "mensagem": "Campos obrigatórios ausentes"}), 400 # 400 = Bad Request

    sucesso = database.criar_agendamento(dados)

    if sucesso:
        return jsonify({"status": "sucesso", "mensagem": "Agendamento criado com sucesso!"}), 201 # 201 = Created
    else:
        return jsonify({"status": "erro", "mensagem": "Falha ao salvar o agendamento no banco de dados."}), 500
    

@app.route('/documentos/upload', methods=['POST'])
def rota_upload_documento():
    """
    Endpoint para fazer o upload de um documento pessoal (holerite, etc.)
    e salvar o registro no banco de dados.
    """
    try:
        # 1. Verifica se os dados do formulário e o arquivo foram enviados
        if 'file' not in request.files:
            return jsonify({"status": "erro", "mensagem": "Nenhum arquivo enviado."}), 400

        arquivo = request.files['file']
        dados_form = request.form

        if arquivo.filename == '':
            return jsonify({"status": "erro", "mensagem": "Nenhum arquivo selecionado."}), 400

        # 2. Pega os dados que vieram junto com o arquivo
        funcionario_id = dados_form.get('funcionario_id')
        tipo_documento = dados_form.get('tipo_documento')
        mes_ano_str = dados_form.get('mes_ano') # Formato 'YYYY-MM-DD'

        # Validação dos dados
        if not all([funcionario_id, tipo_documento, mes_ano_str]):
            return jsonify({"status": "erro", "mensagem": "Dados do formulário incompletos."}), 400

        # 3. Monta um nome de arquivo seguro e o caminho para salvar
        nome_arquivo_seguro = secure_filename(f"{tipo_documento.lower()}_{funcionario_id}_{mes_ano_str}.pdf")
        caminho_para_salvar = os.path.join(PASTA_DOCUMENTOS_SEGUROS, nome_arquivo_seguro)

        # 4. Salva o arquivo no servidor
        arquivo.save(caminho_para_salvar)
        print(f">>> Arquivo '{nome_arquivo_seguro}' salvo com sucesso em '{PASTA_DOCUMENTOS_SEGUROS}'")

        # 5. Registra no banco de dados
        documento_id = database.salvar_documento_pessoal(
            funcionario_id=funcionario_id,
            tipo_documento=tipo_documento,
            mes_ano=mes_ano_str,
            caminho_arquivo=caminho_para_salvar
        )

        if not documento_id:
            # Se falhar ao salvar no BD, deleta o arquivo que foi salvo para não deixar lixo
            os.remove(caminho_para_salvar)
            return jsonify({"status": "erro", "mensagem": "Falha ao registrar o documento no banco de dados."}), 500
        
        # 6. Cria a pendência de ciência para o funcionário
        database.criar_pendencia_ciencia_documento_pessoal(documento_id, funcionario_id)

        return jsonify({"status": "sucesso", "mensagem": "Documento enviado e registrado com sucesso!"}), 201

    except Exception as e:
        print(f"!!! ERRO CRÍTICO em /documentos/upload: {e}")
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {e}"}), 500
    

# Em api_server.py, adicione esta nova rota

@app.route('/documentos/download/<int:documento_id>', methods=['GET'])
def rota_download_documento(documento_id):
    """
    Endpoint seguro para baixar um documento pessoal a partir do seu ID.
    """
    try:
        # 1. Busca o caminho completo do arquivo no banco de dados
        caminho_completo = database.buscar_caminho_documento(documento_id)

        if not caminho_completo or not os.path.exists(caminho_completo):
            return jsonify({"status": "erro", "mensagem": "Documento não encontrado."}), 404

        # 2. Separa o diretório do nome do arquivo
        diretorio, nome_arquivo = os.path.split(caminho_completo)

        # 3. Usa a função segura do Flask para enviar o arquivo
        print(f">>> Enviando o arquivo '{nome_arquivo}' do diretório '{diretorio}'")
        return send_from_directory(diretorio, nome_arquivo, as_attachment=True)

    except Exception as e:
        print(f"!!! ERRO CRÍTICO em /documentos/download: {e}")
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {e}"}), 500



if __name__ == '__main__':
    print(">>> Iniciando o Servidor da API...")
    app.run(host='0.0.0.0', port=5000, debug=True)

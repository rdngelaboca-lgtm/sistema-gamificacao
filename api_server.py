from flask import Flask, request, jsonify
import database 
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from flask import send_from_directory
import notificador_telegram 
import config
import hashlib

app = Flask(__name__)

PASTA_DOCUMENTOS_SEGUROS = "/home/rodrigoaraujo/documentos_rh"

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

    try:
        data_evento_str = dados['data_evento']
        dados['data_evento'] = datetime.strptime(data_evento_str, '%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return jsonify({"status": "erro", "mensagem": "Formato de data_evento inválido. Use 'AAAA-MM-DD HH:MM'."}), 400

    sucesso, erro_db = database.criar_agendamento(dados)

    if sucesso:
        # --- ALERTA DE NOVO AGENDAMENTO ---
        try:
            # Formatamos a data para o formato brasileiro para a notificação
            data_formatada = dados['data_evento'].strftime('%d/%m/%Y às %H:%M')
            
            mensagem_alerta = (
                f"✅ **Novo Agendamento Recebido!** ✅\n\n"
                f"**Cliente:** {dados['nome_cliente']}\n"
                f"**Evento:** {dados['tipo_evento']}\n"
                f"**Quando:** {data_formatada}\n"
            )

            # --- AQUI ESTÁ A MUDANÇA ---
            # Adiciona a observação apenas se ela não estiver vazia
            observacoes = dados.get('observacoes')
            if observacoes and observacoes.strip():
                mensagem_alerta += f"**Obs:** {observacoes.strip()}"
        # ---------------------------
            notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem_alerta)
        except Exception as e:
            # Se a notificação falhar, o agendamento ainda foi criado.
            # Apenas registramos o erro no console do servidor.
            print(f"!!! ATENÇÃO: Agendamento criado, mas falha ao enviar notificação no Telegram: {e}")
        # -----------------------------------

        return jsonify({"status": "sucesso", "mensagem": "Agendamento criado e equipe notificada!"}), 201
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
            "tipo_evento": agendamento.TipoEvento, "data_evento": agendamento.DataEvento.strftime('%d/%m/%Y %H:%M'),
            "status_agendamento": agendamento.StatusAgendamento, "status_pagamento": agendamento.StatusPagamento,
            "observacoes": agendamento.Observacoes, "funcionario_id": agendamento.FuncionarioID
        }
        return jsonify(ag_dict), 200
    else:
        return jsonify({"status": "erro", "mensagem": "Agendamento não encontrado."}), 404
    

# Em api_server.py, substitua a função inteira

@app.route('/agendamentos/enviar-lembrete-geral', methods=['POST'])
def rota_enviar_lembrete_geral():
    """
    Busca todos os agendamentos futuros, agrupa por dia, formata em um layout limpo e envia para o Telegram.
    """
    try:
        agendamentos_db = database.listar_agendamentos()
        
        agendamentos_futuros = [
            ag for ag in agendamentos_db 
            if ag.DataEvento > datetime.now()
        ]

        if not agendamentos_futuros:
            mensagem = "✅ Nenhum agendamento futuro encontrado no sistema."
        else:
            mensagem = "🗓️ **Resumo de Todos os Agendamentos Futuros** 🗓️\n"
            data_atual = None
            for ag in agendamentos_futuros:
                if ag.DataEvento.date() != data_atual:
                    data_atual = ag.DataEvento.date()
                    # Usa nossa nova função tradutora
                    data_formatada = formatar_data_pt_br(data_atual, '%A, %d de %B de %Y')
                    mensagem += f"\n- - - - - - - - - - - - - - - - - - - -\n**{data_formatada}**\n- - - - - - - - - - - - - - - - - - - -\n"
                
                hora_formatada = ag.DataEvento.strftime('%H:%M')
                mensagem += f"\n🔹 **{ag.TipoEvento}**\n"
                mensagem += f"  - ⏰ **{hora_formatada}**\n"
                mensagem += f"  - 👤 **Cliente:** {ag.NomeCliente}\n"
                
                if ag.Observacoes and ag.Observacoes.strip():
                    mensagem += "  - 📝 **Observações:**\n"
                    # Lógica para formatar múltiplas linhas de observação
                    for linha in ag.Observacoes.strip().splitlines():
                        mensagem += f"    > _{linha.strip()}_\n"

        notificador_telegram.enviar_mensagem(config.AGENDAMENTOS_GROUP_CHAT_ID, mensagem)
        return jsonify({"status": "sucesso", "mensagem": "Lembrete geral enviado com sucesso!"}), 200

    except Exception as e:
        print(f"!!! ERRO em /enviar-lembrete-geral: {e}")
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {e}"}), 500
    

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
        print(f"!!! ERRO em /login: {e}")
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {e}"}), 500

if __name__ == '__main__':
    print(">>> Iniciando o Servidor da API...")
    app.run(host='0.0.0.0', port=5000, debug=True)

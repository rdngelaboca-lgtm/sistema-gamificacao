# api_server.py (Nosso novo "Garçom" / Servidor Central)

from flask import Flask, request, jsonify
import database # Reutilizaremos nosso cérebro de banco de dados!

# 1. Cria a aplicação Flask
app = Flask(__name__)

# 2. Rota de Teste (Endpoint)
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
        
        # Precisamos converter o resultado do banco para um formato que o JSON entende
        # (especialmente para converter a data e hora)
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
    # Pega os dados que o programa cliente enviou no formato JSON
    dados = request.get_json()

    # Validação simples para garantir que os campos essenciais foram enviados
    campos_obrigatorios = ['nome_cliente', 'tipo_evento', 'data_evento', 'funcionario_id']
    if not all(campo in dados for campo in campos_obrigatorios):
        return jsonify({"status": "erro", "mensagem": "Campos obrigatórios ausentes"}), 400 # 400 = Bad Request

    # Chama a função do database para salvar
    sucesso = database.criar_agendamento(dados)

    if sucesso:
        return jsonify({"status": "sucesso", "mensagem": "Agendamento criado com sucesso!"}), 201 # 201 = Created
    else:
        return jsonify({"status": "erro", "mensagem": "Falha ao salvar o agendamento no banco de dados."}), 500



# --- FUTURAMENTE, NOSSAS ROTAS DE AGENDAMENTO VIRÃO AQUI ---
# @app.route('/agendamentos', methods=['GET'])
# def listar_agendamentos():
#     # ...
#
# @app.route('/agendamentos/novo', methods=['POST'])
# def criar_agendamento():
#     # ...


# 3. Bloco para iniciar o servidor
if __name__ == '__main__':
    # O host='0.0.0.0' é CRUCIAL! Ele diz ao servidor para "ouvir"
    # por pedidos de qualquer computador na rede, não apenas do localhost.
    print(">>> Iniciando o Servidor da API...")
    app.run(host='0.0.0.0', port=5000, debug=True)
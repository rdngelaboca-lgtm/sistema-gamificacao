# teste_tarefas.py
import database
import pyodbc

# IMPORTANTE: Altere este número para o ID de um funcionário que DEVERIA ter tarefas hoje.
# Pelo print do ranking, o ID do "Rodrigo Araujo" parece ser 7. Vamos usar esse como exemplo.
# Se for outro, por favor, altere aqui.
FUNCIONARIO_ID_PARA_TESTAR = 7

print(f"--- INICIANDO TESTE PARA O FUNCIONÁRIO ID: {FUNCIONARIO_ID_PARA_TESTAR} ---")

try:
    # Vamos chamar a função diretamente
    tarefas_encontradas = database.listar_tarefas_do_dia_por_funcionario(FUNCIONARIO_ID_PARA_TESTAR)

    # Vamos verificar o resultado
    if tarefas_encontradas:
        print("\n✅ SUCESSO! Tarefas encontradas:")
        for tarefa in tarefas_encontradas:
            print(f"  - ID Atribuição: {tarefa.AtribuicaoID}, Título: {tarefa.Titulo}")
    else:
        print("\n❌ FALHA! Nenhuma tarefa foi encontrada pela função.")

except pyodbc.Error as e:
    print("\n💥 ERRO DE BANCO DE DADOS DETECTADO! 💥")
    print("O problema está na consulta SQL. A mensagem de erro é:")
    print(e)
except Exception as e:
    print("\n💥 ERRO INESPERADO NO PYTHON! 💥")
    print("A mensagem de erro é:")
    print(e)

print("\n--- TESTE FINALIZADO ---")

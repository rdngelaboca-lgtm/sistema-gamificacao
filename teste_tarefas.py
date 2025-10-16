# teste_folga.py
import agendador
from datetime import datetime

print("=============================================")
print(f"INICIANDO TESTE MANUAL DE DELEGAÇÃO DE FOLGAS")
print(f"Horário do teste: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
print("=============================================\n")

# Esta é a linha que força a execução da função que queremos testar
agendador.verificar_e_delegar_tarefas_de_folga()

print("\n=============================================")
print("TESTE MANUAL FINALIZADO.")
print("=============================================")

import database
import logging

# Configuração básica de log para ver no terminal
logging.basicConfig(level=logging.INFO, format='%(message)s')

def diagnosticar_cozinha():
    print("\n=== 🕵️ INICIANDO DIAGNÓSTICO DA COZINHA ===")
    
    conn = database.get_db_connection()
    if not conn:
        print("❌ Erro ao conectar no banco.")
        return

    try:
        cursor = conn.cursor()
        
        # 1. Verificar se o Grupo Cozinha existe e tem Chat ID
        print("\n[1] Verificando Cadastro do Grupo 'Cozinha'...")
        cursor.execute("SELECT GrupoID, NomeGrupo, ChatIDTelegram FROM Grupos WHERE NomeGrupo LIKE '%Cozinha%'")
        grupos = cursor.fetchall()
        
        if not grupos:
            print("❌ ALERTA: Nenhum grupo com nome 'Cozinha' encontrado na tabela Grupos!")
        else:
            for g in grupos:
                print(f"   ✅ Encontrado: ID={g.GrupoID} | Nome='{g.NomeGrupo}' | Chat ID='{g.ChatIDTelegram}'")
                if not g.ChatIDTelegram:
                    print("      ⚠️ PERIGO: Este grupo não tem Chat ID cadastrado! O bot não consegue enviar mensagens.")

        # 2. Verificar as Tarefas que aparecem no Painel
        print("\n[2] Verificando as Tarefas de Grupo Ativas...")
        sql_tarefas = """
            SELECT 
                T.Titulo, 
                TA.TipoFrequencia, 
                TA.HorarioDisparo, 
                G.NomeGrupo,
                TA.ValorFrequencia,
                TA.AtribuicaoID
            FROM TarefasAtribuidas TA
            JOIN Tarefas T ON TA.TarefaID = T.TarefaID
            JOIN Grupos G ON TA.GrupoID = G.GrupoID
            WHERE TA.DataFimVigencia IS NULL
              AND G.NomeGrupo LIKE '%Cozinha%'
        """
        cursor.execute(sql_tarefas)
        tarefas = cursor.fetchall()
        
        if not tarefas:
            print("❌ Nenhuma tarefa ativa encontrada para o grupo Cozinha.")
        else:
            print(f"   Foram encontradas {len(tarefas)} tarefas ativas:")
            for t in tarefas:
                horario = t.HorarioDisparo.strftime('%H:%M') if t.HorarioDisparo else "SEM HORARIO"
                freq = f"{t.TipoFrequencia}"
                if t.TipoFrequencia == 'GrupoSemanal':
                    dias = {1:'Dom', 2:'Seg', 3:'Ter', 4:'Qua', 5:'Qui', 6:'Sex', 7:'Sab'}
                    dia_sem = dias.get(int(t.ValorFrequencia or 0), 'Erro')
                    freq += f" ({dia_sem})"
                
                print(f"   👉 ID {t.AtribuicaoID}: '{t.Titulo}'")
                print(f"      ⏰ Dispara às: {horario} | Frequência: {freq}")
                print(f"      📦 Grupo Alvo: {t.NomeGrupo}")
                print("      ------------------------------------------------")

    except Exception as e:
        print(f"❌ Erro durante o diagnóstico: {e}")
    finally:
        conn.close()
        print("\n=== FIM DO DIAGNÓSTICO ===")

if __name__ == "__main__":
    diagnosticar_cozinha()

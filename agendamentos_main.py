# agendamentos_main.py (A nova ferramenta do Atendimento)

from tkcalendar import DateEntry
import tkinter as tk
from tkinter import ttk, messagebox
import requests # A biblioteca para fazer os "pedidos" para o nosso "garçom" (a API)
import json
from datetime import datetime

# --- CONFIGURAÇÃO ---
# Endereço da nossa API. Lembre-se de usar o IP do servidor!
API_BASE_URL = "http://192.168.2.23:5000"


class AppAgendamentos:
    def __init__(self, root):
        self.root = root
        self.root.title("Gela Boca - Controle de Agendamentos")
        self.root.geometry("1000x600")

        # --- LAYOUT PRINCIPAL ---
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=2) # Coluna da lista
        main_frame.columnconfigure(1, weight=1) # Coluna do formulário
        main_frame.rowconfigure(0, weight=1)

        # --- PAINEL ESQUERDO: LISTA DE AGENDAMENTOS ---
        frame_lista = ttk.LabelFrame(main_frame, text="Agendamentos Futuros", padding="10")
        frame_lista.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame_lista.rowconfigure(0, weight=1)
        frame_lista.columnconfigure(0, weight=1)

        
        cols = ('ID', 'Cliente', 'Tipo', 'Data/Hora', 'Status Pagamento')
        self.tree_agendamentos = ttk.Treeview(frame_lista, columns=cols, show='headings')
        for col in cols:
            self.tree_agendamentos.heading(col, text=col)
        self.tree_agendamentos.column('ID', width=40, anchor='center')
        self.tree_agendamentos.column('Cliente', width=200)
        self.tree_agendamentos.column('Tipo', width=150)
        self.tree_agendamentos.column('Data/Hora', width=120, anchor='center')
        self.tree_agendamentos.column('Status Pagamento', width=100, anchor='center')
        self.tree_agendamentos.pack(fill=tk.BOTH, expand=True)

        frame_botoes_acao = ttk.Frame(frame_lista)
        frame_botoes_acao.pack(fill=tk.X, pady=(10,0))

        ttk.Button(frame_botoes_acao, text="Editar Selecionado", command=self.abrir_janela_edicao).pack(side=tk.LEFT, padx=(0,5))
        ttk.Button(frame_botoes_acao, text="Excluir Selecionado", command=self.excluir_agendamento_selecionado).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_botoes_acao, text="Alterar Status Pag.", command=self.alterar_status_pagamento).pack(side=tk.LEFT, padx=5)

        self.tree_agendamentos.column('ID', width=40, anchor='center')
        self.tree_agendamentos.column('Cliente', width=200)
        self.tree_agendamentos.column('Tipo', width=150)
        self.tree_agendamentos.column('Data/Hora', width=120, anchor='center')
        self.tree_agendamentos.column('Status Pagamento', width=100, anchor='center')
        
        # TODO: Adicionar a função para carregar os dados da API
        self.carregar_agendamentos()

        # --- PAINEL DIREITO: FORMULÁRIO DE NOVO AGENDAMENTO ---
        frame_form = ttk.LabelFrame(main_frame, text="Novo Agendamento", padding="10")
        frame_form.grid(row=0, column=1, sticky="nsew")

        # Labels e Entradas do Formulário
        ttk.Label(frame_form, text="Nome do Cliente:").pack(anchor="w")
        self.entry_nome = ttk.Entry(frame_form)
        self.entry_nome.pack(fill="x", pady=(0, 5))
        
        ttk.Label(frame_form, text="CPF:").pack(anchor="w")
        self.entry_cpf = ttk.Entry(frame_form)
        self.entry_cpf.pack(fill="x", pady=(0, 5))

        ttk.Label(frame_form, text="Telefone:").pack(anchor="w")
        self.entry_telefone = ttk.Entry(frame_form)
        self.entry_telefone.pack(fill="x", pady=(0, 5))

        ttk.Label(frame_form, text="Tipo de Evento:").pack(anchor="w")
        self.combo_tipo_evento = ttk.Combobox(frame_form, values=['Carrinho de Sorvete', 'Festa de Aniversario'])
        self.combo_tipo_evento.pack(fill="x", pady=(0, 5))

        # Crie um frame para alinhar a Data e a Hora lado a lado
        frame_data_hora = ttk.Frame(frame_form)
        frame_data_hora.pack(fill="x", pady=(0, 5))

        # Campo de DATA (com calendário)
        ttk.Label(frame_data_hora, text="Data:").pack(side="left")
        self.entry_data = DateEntry(
            frame_data_hora,
            width=12,
            background='darkblue',
            foreground='white',
            borderwidth=2,
            date_pattern='dd/mm/yyyy' # Formato da data
        )
        self.entry_data.pack(side="left", padx=(5, 10))

        # Campo de HORA (manteremos um Entry simples por enquanto)
        ttk.Label(frame_data_hora, text="Hora (HH:MM):").pack(side="left")
        self.entry_hora = ttk.Entry(frame_data_hora, width=8)
        self.entry_hora.pack(side="left", padx=5)
        self.entry_hora.insert(0, "14:00") # Hora padrão

        ttk.Label(frame_form, text="Observações:").pack(anchor="w")
        self.txt_observacoes = tk.Text(frame_form, height=4)
        self.txt_observacoes.pack(fill="x", pady=(0, 10))

        # TODO: Precisaremos saber qual funcionário está logado. Por agora, vamos fixar um ID.
        self.id_funcionario_logado = 2 # IMPORTANTE: Altere para um ID que exista na sua tabela Funcionarios

        btn_salvar = ttk.Button(frame_form, text="Salvar Agendamento", command=self.salvar_agendamento)
        btn_salvar.pack(fill="x", ipady=5)

    def excluir_agendamento_selecionado(self):
        """Exclui o agendamento selecionado na lista."""
        selecionado = self.tree_agendamentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um agendamento na lista para excluir.")
            return

        dados_ag = self.tree_agendamentos.item(selecionado, 'values')
        agendamento_id = dados_ag[0]
        nome_cliente = dados_ag[1]

        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o agendamento de '{nome_cliente}'?"):
            try:
                response = requests.delete(f"{API_BASE_URL}/agendamentos/{agendamento_id}")
                if response.status_code == 204: # No Content (sucesso)
                    messagebox.showinfo("Sucesso", "Agendamento excluído com sucesso!")
                    self.carregar_agendamentos()
                else:
                    erro = response.json().get('mensagem', 'Erro desconhecido')
                    messagebox.showerror("Erro da API", f"Falha ao excluir: {erro}")
            except requests.exceptions.RequestException as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}")

    def alterar_status_pagamento(self):
        """Altera o status de pagamento do agendamento selecionado."""
        selecionado = self.tree_agendamentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um agendamento na lista.")
            return

        dados_ag = self.tree_agendamentos.item(selecionado, 'values')
        agendamento_id = dados_ag[0]
        status_atual = dados_ag[4]

        novo_status = "Pago" if status_atual == "Pendente" else "Pendente"
        
        payload = {"status": novo_status}
        
        try:
            response = requests.patch(f"{API_BASE_URL}/agendamentos/{agendamento_id}/pagamento", json=payload)
            if response.status_code == 200:
                messagebox.showinfo("Sucesso", f"Status do pagamento alterado para '{novo_status}'.")
                self.carregar_agendamentos()
            else:
                erro = response.json().get('mensagem', 'Erro desconhecido')
                messagebox.showerror("Erro da API", f"Falha ao alterar status: {erro}")
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}")


    def carregar_agendamentos(self):
        """Busca a lista de agendamentos na API e preenche a tabela."""
        for i in self.tree_agendamentos.get_children():
            self.tree_agendamentos.delete(i)
            
        try:
            response = requests.get(f"{API_BASE_URL}/agendamentos")
            # Verifica se a resposta da API foi bem-sucedida (código 200)
            if response.status_code == 200:
                agendamentos = response.json()
                for ag in agendamentos:
                    self.tree_agendamentos.insert(
                        "", "end",
                        values=(
                            ag['agendamento_id'], ag['nome_cliente'], ag['tipo_evento'],
                            ag['data_evento'], ag['status_pagamento']
                        )
                    )
            else:
                messagebox.showerror("Erro de API", f"Não foi possível buscar os agendamentos.\nStatus: {response.status_code}")
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API.\nVerifique se o servidor está no ar.\n\n{e}")

    # Em agendamentos_main.py, adicione esta função à classe

    def abrir_janela_edicao(self):
        """Abre um pop-up completo para editar um agendamento selecionado."""
        selecionado = self.tree_agendamentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um agendamento na lista para editar.")
            return

        agendamento_id = self.tree_agendamentos.item(selecionado, 'values')[0]

        # 1. Busca os dados completos na API
        try:
            response = requests.get(f"{API_BASE_URL}/agendamentos/{agendamento_id}")
            if response.status_code != 200:
                messagebox.showerror("Erro", "Não foi possível buscar os detalhes do agendamento.")
                return
            dados_completos = response.json()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}")
            return

        # --- Criação da Janela Pop-up ---
        popup = Toplevel(self.root)
        popup.title("Editar Agendamento")
        popup.geometry("450x450")
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        # --- Widgets do Formulário (agora completos e preenchidos) ---
        ttk.Label(frame, text="Nome do Cliente:").pack(anchor="w")
        edit_entry_nome = ttk.Entry(frame); edit_entry_nome.pack(fill="x", pady=(0, 5))
        edit_entry_nome.insert(0, dados_completos.get('nome_cliente', ''))

        ttk.Label(frame, text="CPF:").pack(anchor="w")
        edit_entry_cpf = ttk.Entry(frame); edit_entry_cpf.pack(fill="x", pady=(0, 5))
        edit_entry_cpf.insert(0, dados_completos.get('cpf_cliente', ''))

        ttk.Label(frame, text="Telefone:").pack(anchor="w")
        edit_entry_telefone = ttk.Entry(frame); edit_entry_telefone.pack(fill="x", pady=(0, 5))
        edit_entry_telefone.insert(0, dados_completos.get('telefone_cliente', ''))

        ttk.Label(frame, text="Tipo de Evento:").pack(anchor="w")
        edit_combo_tipo = ttk.Combobox(frame, values=['Carrinho de Sorvete', 'Festa de Aniversario'])
        edit_combo_tipo.pack(fill="x", pady=(0, 5))
        edit_combo_tipo.set(dados_completos.get('tipo_evento', ''))

        # (Data/Hora - simplificado para manter data/hora originais na edição por enquanto)
        ttk.Label(frame, text=f"Data/Hora: {dados_completos['data_evento']}").pack(anchor="w")

        ttk.Label(frame, text="Observações:").pack(anchor="w")
        edit_txt_obs = tk.Text(frame, height=3); edit_txt_obs.pack(fill="x", pady=(0, 5))
        edit_txt_obs.insert("1.0", dados_completos.get('observacoes', ''))

        ttk.Label(frame, text="Status Pagamento:").pack(anchor="w")
        edit_combo_pagamento = ttk.Combobox(frame, values=['Pendente', 'Pago'])
        edit_combo_pagamento.pack(fill="x", pady=(0, 5))
        edit_combo_pagamento.set(dados_completos.get('status_pagamento', 'Pendente'))

        # --- Lógica de Salvamento da Edição ---
        def salvar_edicao():
            # Coleta todos os dados, garantindo que não se percam
            payload_editado = {
                "nome_cliente": edit_entry_nome.get(),
                "cpf_cliente": edit_entry_cpf.get(),
                "telefone_cliente": edit_entry_telefone.get(),
                "tipo_evento": edit_combo_tipo.get(),
                "status_pagamento": edit_combo_pagamento.get(),
                "observacoes": edit_txt_obs.get("1.0", tk.END).strip(),
                # Dados que não estamos editando na tela, mas precisamos reenviar
                "data_evento": datetime.strptime(dados_completos['data_evento'], '%d/%m/%Y %H:%M').strftime('%Y-%m-%d %H:%M'),
                "funcionario_id": dados_completos['funcionario_id'],
                "status_agendamento": dados_completos['status_agendamento']
            }

            try:
                response = requests.put(f"{API_BASE_URL}/agendamentos/{agendamento_id}", json=payload_editado)
                if response.status_code == 200:
                    messagebox.showinfo("Sucesso", "Agendamento atualizado!", parent=popup)
                    popup.destroy()
                    self.carregar_agendamentos()
                else:
                    messagebox.showerror("Erro da API", f"Falha ao atualizar: {response.json().get('mensagem', 'Erro')}", parent=popup)
            except requests.exceptions.RequestException as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}", parent=popup)

        ttk.Button(frame, text="Salvar Alterações", command=salvar_edicao).pack(pady=20, fill="x")

def buscar_agendamento_por_id(agendamento_id):
    """Busca todos os detalhes de um único agendamento pelo seu ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Reutilizamos a query de listar, mas filtrando por ID
            sql = """
                SELECT A.*, F.NomeCompleto AS NomeFuncionario
                FROM Agendamentos A JOIN Funcionarios F ON A.FuncionarioID = F.FuncionarioID
                WHERE A.AgendamentoID = ?
            """
            cursor.execute(sql, agendamento_id)
            return cursor.fetchone()
        finally:
            conn.close()
    return None




if __name__ == "__main__":
    root = tk.Tk()
    app = AppAgendamentos(root)
    root.mainloop()

# agendamentos_main.py (A nova ferramenta do Atendimento)

from tkcalendar import DateEntry
import tkinter as tk
from tkinter import ttk, messagebox
import requests # A biblioteca para fazer os "pedidos" para o nosso "garçom" (a API)
import json
from datetime import datetime

# --- CONFIGURAÇÃO ---
# Endereço da nossa API. Lembre-se de usar o IP do servidor!
API_BASE_URL = "http://192.168.2.62:5000"


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
        self.tree_agendamentos.pack(fill=tk.BOTH, expand=True)
        
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

    # Em agendamentos_main.py, adicione estas duas funções dentro da classe AppAgendamentos

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

    def salvar_agendamento(self):
        """Coleta os dados do formulário, envia para a API e salva o agendamento."""
        # 1. Coletar os dados da interface
        nome = self.entry_nome.get()
        cpf = self.entry_cpf.get()
        telefone = self.entry_telefone.get()
        tipo_evento = self.combo_tipo_evento.get()
        data_selecionada = self.entry_data.get_date() # Pega a data do calendário
        hora_digitada = self.entry_hora.get()
        obs = self.txt_observacoes.get("1.0", tk.END).strip()

        # 2. Validar os dados
        if not all([nome, tipo_evento, hora_digitada]):
            messagebox.showwarning("Campos Obrigatórios", "Nome do Cliente, Tipo e Hora são obrigatórios.")
            return

        try:
            # Junta a data do calendário com a hora digitada
            data_hora_evento = datetime.combine(data_selecionada, datetime.strptime(hora_digitada, "%H:%M").time())
            # Converte para o formato que a API e o banco esperam (AAAA-MM-DD HH:MM)
            data_evento_str = data_hora_evento.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            messagebox.showerror("Erro de Formato", "A hora deve estar no formato HH:MM (ex: 14:30).")
            return

        # 3. Montar o "pacote" de dados (payload) em formato de dicionário
        payload = {
            "nome_cliente": nome,
            "cpf_cliente": cpf,
            "telefone_cliente": telefone,
            "tipo_evento": tipo_evento,
            "data_evento": data_evento_str,
            "observacoes": obs,
            "funcionario_id": self.id_funcionario_logado # O ID fixo que definimos
        }

        # 4. Enviar os dados para a API
        try:
            response = requests.post(f"{API_BASE_URL}/agendamentos/novo", json=payload)

            if response.status_code == 201: # 201 = Created (Criado com Sucesso)
                messagebox.showinfo("Sucesso", "Agendamento salvo com sucesso!")
                self.limpar_formulario()
                self.carregar_agendamentos() # Atualiza a lista na tela
            else:
                # Mostra a mensagem de erro que a API enviou
                erro_api = response.json().get('mensagem', 'Erro desconhecido.')
                messagebox.showerror("Erro da API", f"Não foi possível salvar.\nErro: {erro_api}")
                
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API para salvar.\n\n{e}")

    def limpar_formulario(self):
        """Limpa todos os campos do formulário após o salvamento."""
        self.entry_nome.delete(0, tk.END)
        self.entry_cpf.delete(0, tk.END)
        self.entry_telefone.delete(0, tk.END)
        self.combo_tipo_evento.set('')
        self.entry_hora.delete(0, tk.END); self.entry_hora.insert(0, "14:00")
        self.txt_observacoes.delete("1.0", tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    app = AppAgendamentos(root)
    root.mainloop()
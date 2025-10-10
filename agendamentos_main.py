### ARQUIVO COMPLETO E ATUALIZADO: agendamentos_main.py (COM TELA DE LOGIN) ###

from tkcalendar import DateEntry
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel
import requests
from datetime import datetime
import database

# --- CONFIGURAÇÃO ---
API_BASE_URL = "https://09396f7674d5.ngrok-free.app" 

# Em agendamentos_main.py, substitua a classe LoginWindow por esta
import hashlib # Adicione esta importação no topo do arquivo

# Em agendamentos_main.py, substitua a classe LoginWindow inteira por esta
# Note que não precisamos mais de 'import hashlib' aqui!

class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("Gela Boca - Acesso ao Sistema")
        self.root.geometry("350x280")
        self.root.resizable(False, False)
        self.root.eval('tk::PlaceWindow . center')

        frame = ttk.Frame(root, padding="20")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="ID do Funcionário:", font=("Arial", 12)).pack(pady=(0, 5))
        self.entry_id = ttk.Entry(frame, font=("Arial", 12), justify="center")
        self.entry_id.pack(fill="x", ipady=5)
        self.entry_id.focus()

        ttk.Label(frame, text="Senha:", font=("Arial", 12)).pack(pady=(10, 5))
        self.entry_senha = ttk.Entry(frame, font=("Arial", 12), justify="center", show="*")
        self.entry_senha.pack(fill="x", ipady=5)
        
        self.entry_id.bind("<Return>", lambda e: self.entry_senha.focus())
        self.entry_senha.bind("<Return>", self.fazer_login)

        btn_login = ttk.Button(frame, text="Entrar", command=self.fazer_login)
        btn_login.pack(pady=20, fill="x", ipady=8)

        self.funcionario_logado = None

    def fazer_login(self, event=None):
        funcionario_id = self.entry_id.get()
        senha = self.entry_senha.get()

        if not funcionario_id.isdigit() or not senha:
            messagebox.showerror("Erro", "ID e Senha são obrigatórios.")
            return

        # --- LÓGICA ATUALIZADA: AGORA USAMOS A API! ---
        try:
            payload = {"id": int(funcionario_id), "senha": senha}
            # Usa a mesma API_BASE_URL (a URL do ngrok) que o resto do programa
            response = requests.post(f"{API_BASE_URL}/login", json=payload)

            if response.status_code == 200:
                dados_resposta = response.json()
                messagebox.showinfo("Bem-vindo(a)!", dados_resposta['mensagem'])
                
                # Armazena os dados do funcionário que a API retornou
                self.funcionario_logado = type('Funcionario', (), dados_resposta['funcionario'])
                # Renomeia os atributos para corresponder ao que o resto do código espera
                self.funcionario_logado.FuncionarioID = self.funcionario_logado.id
                self.funcionario_logado.NomeCompleto = self.funcionario_logado.nome

                self.root.destroy()
            else:
                # Mostra a mensagem de erro que a API enviou (Senha incorreta, ID não encontrado, etc.)
                messagebox.showerror("Acesso Negado", response.json().get('mensagem', 'Erro desconhecido.'))

        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar ao servidor de login.\nVerifique se a API e o ngrok estão no ar.\n\n{e}")
        except Exception as e:
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado: {e}")

# A classe principal continua a mesma, com uma pequena alteração no __init__
class AppAgendamentos:
    def __init__(self, root, funcionario_logado):
        self.root = root
        self.funcionario_logado = funcionario_logado
        self.id_funcionario_logado = self.funcionario_logado.FuncionarioID

        # Adiciona o nome do funcionário logado no título da janela
        self.root.title(f"Gela Boca - Controle de Agendamentos (Logado como: {self.funcionario_logado.NomeCompleto})")
        self.root.geometry("1000x600")

        # O restante do código da classe AppAgendamentos (interface, funções, etc.)
        # continua exatamente o mesmo de antes. Cole todo o resto dela aqui,
        # desde "main_frame = ttk.Frame(root, padding="10")" até o final da classe.
        # ... (COLE O RESTO DA CLASSE AppAgendamentos AQUI) ...
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=2)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)
        frame_lista = ttk.LabelFrame(main_frame, text="Agendamentos Futuros", padding="10")
        frame_lista.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame_lista.rowconfigure(0, weight=1)
        frame_lista.columnconfigure(0, weight=1)
        cols = ('ID', 'Cliente', 'Tipo', 'Data/Hora', 'Status Pagamento')
        self.tree_agendamentos = ttk.Treeview(frame_lista, columns=cols, show='headings')
        for col in cols: self.tree_agendamentos.heading(col, text=col)
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
        ttk.Button(frame_botoes_acao, text="📢 Enviar Lembrete Geral", command=self.enviar_lembrete_geral).pack(side=tk.RIGHT, padx=5)
        frame_form = ttk.LabelFrame(main_frame, text="Novo Agendamento", padding="10")
        frame_form.grid(row=0, column=1, sticky="nsew")
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
        self.combo_tipo_evento = ttk.Combobox(frame_form, values=['Carrinho de Sorvete', 'Festa de Aniversario', 'Reserva de Tortas de Sorvete'])
        self.combo_tipo_evento.pack(fill="x", pady=(0, 5))
        frame_data_hora = ttk.Frame(frame_form)
        frame_data_hora.pack(fill="x", pady=(0, 5))
        ttk.Label(frame_data_hora, text="Data:").pack(side="left")
        self.entry_data = DateEntry(frame_data_hora, width=12, date_pattern='dd/mm/yyyy')
        self.entry_data.pack(side="left", padx=(5, 10))
        ttk.Label(frame_data_hora, text="Hora (HH:MM):").pack(side="left")
        self.entry_hora = ttk.Entry(frame_data_hora, width=8)
        self.entry_hora.pack(side="left", padx=5)
        self.entry_hora.insert(0, "14:00")
        ttk.Label(frame_form, text="Observações:").pack(anchor="w")
        self.txt_observacoes = tk.Text(frame_form, height=4)
        self.txt_observacoes.pack(fill="x", pady=(0, 10))
        btn_salvar = ttk.Button(frame_form, text="Salvar Agendamento", command=self.salvar_agendamento)
        btn_salvar.pack(fill="x", ipady=5)
        self.carregar_agendamentos()
    def carregar_agendamentos(self):
        for i in self.tree_agendamentos.get_children(): self.tree_agendamentos.delete(i)
        try:
            response = requests.get(f"{API_BASE_URL}/agendamentos")
            if response.status_code == 200:
                agendamentos = response.json()
                for ag in agendamentos:
                    self.tree_agendamentos.insert("", "end", values=(ag['agendamento_id'], ag['nome_cliente'], ag['tipo_evento'], ag['data_evento'], ag['status_pagamento']))
            else:
                messagebox.showerror("Erro de API", f"Não foi possível buscar os agendamentos.\nStatus: {response.status_code}")
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API.\nVerifique se o servidor está no ar.\n\n{e}")
    def salvar_agendamento(self):
        nome = self.entry_nome.get()
        cpf = self.entry_cpf.get()
        telefone = self.entry_telefone.get()
        tipo_evento = self.combo_tipo_evento.get()
        data_selecionada = self.entry_data.get_date()
        hora_digitada = self.entry_hora.get()
        obs = self.txt_observacoes.get("1.0", tk.END).strip()
        if not all([nome, tipo_evento, hora_digitada]):
            messagebox.showwarning("Campos Obrigatórios", "Nome do Cliente, Tipo e Hora são obrigatórios.")
            return
        try:
            data_hora_evento = datetime.combine(data_selecionada, datetime.strptime(hora_digitada, "%H:%M").time())
            data_evento_str = data_hora_evento.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            messagebox.showerror("Erro de Formato", "A hora deve estar no formato HH:MM (ex: 14:30).")
            return
        payload = {
            "nome_cliente": nome, "cpf_cliente": cpf, "telefone_cliente": telefone,
            "tipo_evento": tipo_evento, "data_evento": data_evento_str, "observacoes": obs,
            "funcionario_id": self.id_funcionario_logado
        }
        print(f"\n--- DEBUG ENVIANDO ---\n{payload}\n--- FIM DEBUG ---\n")
        try:
            response = requests.post(f"{API_BASE_URL}/agendamentos/novo", json=payload)
            if response.status_code == 201:
                messagebox.showinfo("Sucesso", "Agendamento salvo com sucesso!")
                self.limpar_formulario()
                self.carregar_agendamentos()
            else:
                erro_api = response.json().get('mensagem', 'Erro desconhecido.')
                messagebox.showerror("Erro da API", f"Não foi possível salvar.\nErro: {erro_api}")
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API para salvar.\n\n{e}")
    def limpar_formulario(self):
        self.entry_nome.delete(0, tk.END)
        self.entry_cpf.delete(0, tk.END)
        self.entry_telefone.delete(0, tk.END)
        self.combo_tipo_evento.set('')
        self.entry_hora.delete(0, tk.END); self.entry_hora.insert(0, "14:00")
        self.txt_observacoes.delete("1.0", tk.END)
    def excluir_agendamento_selecionado(self):
        selecionado = self.tree_agendamentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um agendamento na lista para excluir.")
            return
        dados_ag = self.tree_agendamentos.item(selecionado, 'values')
        agendamento_id, nome_cliente = dados_ag[0], dados_ag[1]
        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o agendamento de '{nome_cliente}'?"):
            try:
                response = requests.delete(f"{API_BASE_URL}/agendamentos/{agendamento_id}")
                if response.status_code == 204:
                    messagebox.showinfo("Sucesso", "Agendamento excluído com sucesso!")
                    self.carregar_agendamentos()
                else:
                    erro = response.json().get('mensagem', 'Erro desconhecido')
                    messagebox.showerror("Erro da API", f"Falha ao excluir: {erro}")
            except requests.exceptions.RequestException as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}")
    def alterar_status_pagamento(self):
        selecionado = self.tree_agendamentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um agendamento na lista.")
            return
        dados_ag = self.tree_agendamentos.item(selecionado, 'values')
        agendamento_id, status_atual = dados_ag[0], dados_ag[4]
        novo_status = "Pago" if status_atual == "Pendente" else "Pendente"
        try:
            response = requests.patch(f"{API_BASE_URL}/agendamentos/{agendamento_id}/pagamento", json={"status": novo_status})
            if response.status_code == 200:
                messagebox.showinfo("Sucesso", f"Status do pagamento alterado para '{novo_status}'.")
                self.carregar_agendamentos()
            else:
                erro = response.json().get('mensagem', 'Erro desconhecido')
                messagebox.showerror("Erro da API", f"Falha ao alterar status: {erro}")
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}")

    # Em agendamentos_main.py, substitua a função abrir_janela_edicao inteira por esta:

    def abrir_janela_edicao(self):
        selecionado = self.tree_agendamentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um agendamento na lista para editar.")
            return
        agendamento_id = self.tree_agendamentos.item(selecionado, 'values')[0]
        
        try:
            response = requests.get(f"{API_BASE_URL}/agendamentos/{agendamento_id}")
            if response.status_code != 200:
                messagebox.showerror("Erro", "Não foi possível buscar os detalhes do agendamento.")
                return
            dados_completos = response.json()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}")
            return
        
        popup = Toplevel(self.root)
        popup.title("Editar Agendamento")
        popup.geometry("450x550") # Aumentei a altura para caber tudo confortavelmente
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        # --- Campos de texto normais (sem alteração) ---
        ttk.Label(frame, text="Nome do Cliente:").pack(anchor="w")
        edit_entry_nome = ttk.Entry(frame); edit_entry_nome.pack(fill="x", pady=(0, 5))
        edit_entry_nome.insert(0, dados_completos.get('nome_cliente', ''))

        ttk.Label(frame, text="CPF:").pack(anchor="w")
        edit_entry_cpf = ttk.Entry(frame); edit_entry_cpf.pack(fill="x", pady=(0, 5))
        edit_entry_cpf.insert(0, dados_completos.get('cpf_cliente', '') or '')

        ttk.Label(frame, text="Telefone:").pack(anchor="w")
        edit_entry_telefone = ttk.Entry(frame); edit_entry_telefone.pack(fill="x", pady=(0, 5))
        edit_entry_telefone.insert(0, dados_completos.get('telefone_cliente', '') or '')

        ttk.Label(frame, text="Tipo de Evento:").pack(anchor="w")
        edit_combo_tipo = ttk.Combobox(frame, values=['Carrinho de Sorvete', 'Festa de Aniversario'])
        edit_combo_tipo.pack(fill="x", pady=(0, 5))
        edit_combo_tipo.set(dados_completos.get('tipo_evento', ''))

        # --- NOVA PARTE: Campos de Data e Hora editáveis ---
        frame_data_hora = ttk.Frame(frame)
        frame_data_hora.pack(fill="x", pady=(5, 5))

        ttk.Label(frame_data_hora, text="Data:").pack(side="left")
        edit_entry_data = DateEntry(frame_data_hora, width=12, date_pattern='dd/mm/yyyy')
        edit_entry_data.pack(side="left", padx=(5, 10))

        ttk.Label(frame_data_hora, text="Hora (HH:MM):").pack(side="left")
        edit_entry_hora = ttk.Entry(frame_data_hora, width=8)
        edit_entry_hora.pack(side="left", padx=5)

        # --- LÓGICA ATUALIZADA: Preenchendo os campos com os dados existentes ---
        # A API retorna a data no formato 'dd/mm/yyyy HH:MM', então usamos esse formato para ler.
        data_evento_obj = datetime.strptime(dados_completos['data_evento'], '%d/%m/%Y %H:%M')
        edit_entry_data.set_date(data_evento_obj.date())
        edit_entry_hora.insert(0, data_evento_obj.strftime('%H:%M'))

        # --- Resto dos campos (sem alteração) ---
        ttk.Label(frame, text="Observações:").pack(anchor="w")
        edit_txt_obs = tk.Text(frame, height=3); edit_txt_obs.pack(fill="x", pady=(0, 5))
        edit_txt_obs.insert("1.0", dados_completos.get('observacoes', '') or '')

        ttk.Label(frame, text="Status Pagamento:").pack(anchor="w")
        edit_combo_pagamento = ttk.Combobox(frame, values=['Pendente', 'Pago'])
        edit_combo_pagamento.pack(fill="x", pady=(0, 5))
        edit_combo_pagamento.set(dados_completos.get('status_pagamento', 'Pendente'))
    
        # --- LÓGICA ATUALIZADA: Função interna de salvar ---
        def salvar_edicao():
            # 1. Lê os novos valores da data e da hora dos campos editáveis
            try:
                nova_data = edit_entry_data.get_date()
                nova_hora_str = edit_entry_hora.get()
                nova_data_hora_obj = datetime.combine(nova_data, datetime.strptime(nova_hora_str, "%H:%M").time())
                # Formata para o padrão AAAA-MM-DD que a API espera
                nova_data_hora_str_payload = nova_data_hora_obj.strftime('%Y-%m-%d %H:%M') 
            except ValueError:
                messagebox.showerror("Erro de Formato", "A hora deve estar no formato HH:MM (ex: 14:30).", parent=popup)
                return

            # 2. Monta o payload COMPLETO para enviar à API
            payload_editado = {
                "nome_cliente": edit_entry_nome.get(),
                "cpf_cliente": edit_entry_cpf.get(),
                "telefone_cliente": edit_entry_telefone.get(),
                "tipo_evento": edit_combo_tipo.get(),
                "status_pagamento": edit_combo_pagamento.get(),
                "observacoes": edit_txt_obs.get("1.0", tk.END).strip(),
                "data_evento": nova_data_hora_str_payload, # <-- Usa a nova data/hora lida dos campos
                # Mantém os dados que não são editáveis na tela
                "funcionario_id": dados_completos['funcionario_id'],
                "status_agendamento": dados_completos['status_agendamento']
            }
            
            # 3. Envia os dados para a API (sem alteração aqui)
            try:
                response = requests.put(f"{API_BASE_URL}/agendamentos/{agendamento_id}", json=payload_editado)
                if response.status_code == 200:
                    messagebox.showinfo("Sucesso", "Agendamento atualizado!", parent=popup)
                    popup.destroy()
                    self.carregar_agendamentos()
                else:
                    erro_msg = response.json().get('mensagem', 'Erro desconhecido')
                    messagebox.showerror("Erro da API", f"Falha ao atualizar: {erro_msg}", parent=popup)
            except requests.exceptions.RequestException as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}", parent=popup)
                
        ttk.Button(frame, text="Salvar Alterações", command=salvar_edicao).pack(pady=20, fill="x")

    def enviar_lembrete_geral(self):
        confirmado = messagebox.askyesno("Confirmar Envio", "Deseja enviar um resumo de TODOS os agendamentos futuros para o grupo do Telegram agora?")
        if confirmado:
            try:
                response = requests.post(f"{API_BASE_URL}/agendamentos/enviar-lembrete-geral")
                if response.status_code == 200:
                    messagebox.showinfo("Sucesso", "Resumo de agendamentos enviado para o grupo!")
                else:
                    messagebox.showerror("Erro da API", f"Falha ao enviar o lembrete: {response.json().get('mensagem')}")
            except requests.exceptions.RequestException as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}") 

if __name__ == "__main__":
    # --- FLUXO DE INICIALIZAÇÃO ---
    # 1. Cria a janela de login
    login_root = tk.Tk()
    app_login = LoginWindow(login_root)
    login_root.mainloop() # O programa pausa aqui até a janela de login ser fechada

    # 2. Se o login foi bem-sucedido, 'app_login.funcionario_logado' terá os dados.
    if app_login.funcionario_logado:
        # 3. Cria a janela principal da aplicação, passando os dados do funcionário.
        main_app_root = tk.Tk()
        app_principal = AppAgendamentos(main_app_root, app_login.funcionario_logado)
        main_app_root.mainloop()

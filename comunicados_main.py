### ARQUIVO CORRIGIDO: comunicados_main.py ###
# Arquivo: comunicados_main.py (Versão Corrigida e Funcional)

import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, Listbox, Checkbutton, Text, Entry, Scrollbar, Frame, Label, Button
from datetime import datetime
import database
import notificador_telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import time
import os

# Garanta que todos os imports necessários estejam no topo
import comunicado_generator
import file_utils
import recibo_generator

class AppComunicados:
    def __init__(self, root):
        self.root = root
        self.root.title("Módulo de Comunicados e Ciência")
        self.root.geometry("900x600")
        self.root.minsize(700, 400)

        self.root.grid_rowconfigure(2, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.dados_funcionarios = {}
        self.popup_criacao = None

        self.criar_widgets_principais()
        self.atualizar_lista_comunicados()

    def criar_widgets_principais(self):
        """ Cria os widgets da tela principal (lista de comunicados e botões) """
        frame_botoes = ttk.Frame(self.root, padding="10")
        frame_botoes.grid(row=0, column=0, sticky="ew")

        btn_novo = ttk.Button(frame_botoes, text="Criar Novo Comunicado", command=self.abrir_janela_criacao)
        btn_novo.pack(side="left")

        btn_atualizar = ttk.Button(frame_botoes, text="Atualizar Lista", command=self.atualizar_lista_comunicados)
        btn_atualizar.pack(side="left", padx=10)

        btn_detalhes = ttk.Button(frame_botoes, text="Ver Detalhes do Selecionado", command=self.abrir_janela_detalhes)
        btn_detalhes.pack(side="left", padx=10)

        btn_excluir = ttk.Button(frame_botoes, text="Excluir Comunicado", command=self.excluir_comunicado_selecionado)
        btn_excluir.pack(side="left", padx=10)

        frame_filtro = ttk.Frame(self.root, padding="10")
        frame_filtro.grid(row=1, column=0, sticky="ew")

        lbl_filtro = ttk.Label(frame_filtro, text="Filtrar por Título:")
        lbl_filtro.pack(side="left")

        self.entry_filtro = ttk.Entry(frame_filtro, width=40)
        self.entry_filtro.pack(side="left", padx=5, fill="x", expand=True)

        btn_buscar = ttk.Button(frame_filtro, text="Buscar", command=self.filtrar_lista_comunicados)
        btn_buscar.pack(side="left", padx=(0, 5))

        btn_limpar = ttk.Button(frame_filtro, text="Limpar", command=self.limpar_filtro)
        btn_limpar.pack(side="left")

        frame_lista = ttk.Frame(self.root, padding="10")
        frame_lista.grid(row=2, column=0, sticky="nsew")
        frame_lista.grid_rowconfigure(0, weight=1)
        frame_lista.grid_columnconfigure(0, weight=1)

        cols = ('ID', 'Título', 'Data de Criação', 'Status')
        self.tree_comunicados = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')

        self.tree_comunicados.heading('ID', text='ID')
        self.tree_comunicados.column('ID', width=50, anchor='center')
        self.tree_comunicados.heading('Título', text='Título')
        self.tree_comunicados.column('Título', width=350)
        self.tree_comunicados.heading('Data de Criação', text='Enviado em')
        self.tree_comunicados.column('Data de Criação', width=150, anchor='center')
        self.tree_comunicados.heading('Status', text='Status')
        self.tree_comunicados.column('Status', width=120, anchor='center')

        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.tree_comunicados.yview)
        self.tree_comunicados.configure(yscrollcommand=scrollbar.set)

        self.tree_comunicados.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def atualizar_lista_comunicados(self, filtro=None):
        for i in self.tree_comunicados.get_children():
            self.tree_comunicados.delete(i)
        comunicados = database.listar_comunicados_com_status(filtro_titulo=filtro)
        for doc in comunicados:
            status = f"{doc.TotalCientes} / {doc.TotalEnviado} Cientes"
            data_formatada = doc.DataCriacao.strftime("%d/%m/%Y %H:%M")
            self.tree_comunicados.insert("", "end", values=(doc.DocumentoID, doc.Titulo, data_formatada, status))

    def abrir_janela_criacao(self):
        if self.popup_criacao is not None and self.popup_criacao.winfo_exists():
            self.popup_criacao.focus()
            return
        self.popup_criacao = Toplevel(self.root)
        self.popup_criacao.title("Novo Comunicado")
        self.popup_criacao.geometry("800x600")
        self.popup_criacao.transient(self.root)
        Label(self.popup_criacao, text="Título:", font=("Arial", 10, "bold")).pack(padx=10, pady=(10,0), anchor='w')
        entry_titulo = Entry(self.popup_criacao, font=("Arial", 10))
        entry_titulo.pack(padx=10, fill='x')
        Label(self.popup_criacao, text="Conteúdo:", font=("Arial", 10, "bold")).pack(padx=10, pady=(10,0), anchor='w')
        text_conteudo = Text(self.popup_criacao, height=10, font=("Arial", 10))
        text_conteudo.pack(padx=10, fill='both', expand=True)
        frame_pontos = Frame(self.popup_criacao)
        frame_pontos.pack(padx=10, pady=5, fill='x')
        var_premiar = tk.BooleanVar()
        check_premiar = Checkbutton(frame_pontos, text="Premiar com pontos pela ciência?", variable=var_premiar)
        check_premiar.pack(side="left")
        entry_pontos = Entry(frame_pontos, width=5)
        entry_pontos.pack(side="left", padx=5)
        entry_pontos.insert(0, "10")
        Label(self.popup_criacao, text="Enviar para:", font=("Arial", 10, "bold")).pack(padx=10, pady=(10,0), anchor='w')
        frame_funcionarios = Frame(self.popup_criacao)
        frame_funcionarios.pack(padx=10, pady=5, fill='both', expand=True)
        listbox_funcionarios = Listbox(frame_funcionarios, selectmode=tk.EXTENDED)
        scrollbar_func = Scrollbar(frame_funcionarios, orient="vertical", command=listbox_funcionarios.yview)
        listbox_funcionarios.configure(yscrollcommand=scrollbar_func.set)
        listbox_funcionarios.pack(side="left", fill="both", expand=True)
        scrollbar_func.pack(side="left", fill="y")
        self.dados_funcionarios.clear()
        funcionarios = database.listar_funcionarios()
        for func in funcionarios:
            display_text = f"{func.NomeCompleto} (ID: {func.FuncionarioID})"
            listbox_funcionarios.insert(tk.END, display_text)
            self.dados_funcionarios[display_text] = func
        btn_enviar = Button(self.popup_criacao, text="ENVIAR COMUNICADO", bg="green", fg="white", font=("Arial", 12, "bold"),
                            command=lambda: self.enviar_comunicado(
                                entry_titulo.get(), text_conteudo.get("1.0", tk.END),
                                var_premiar.get(), entry_pontos.get(),
                                listbox_funcionarios.curselection(), listbox_funcionarios
                            ))
        btn_enviar.pack(pady=10, padx=10, fill='x', ipady=5)

    def enviar_comunicado(self, titulo, conteudo, premiar, pontos_str, indices_selecionados, listbox):
        if not titulo or not conteudo.strip():
            messagebox.showerror("Erro", "Título e Conteúdo são obrigatórios.", parent=self.popup_criacao)
            return
        if not indices_selecionados:
            messagebox.showerror("Erro", "Selecione pelo menos um funcionário.", parent=self.popup_criacao)
            return
        pontos = 0
        if premiar:
            try:
                pontos = int(pontos_str)
                if pontos <= 0: raise ValueError
            except ValueError:
                messagebox.showerror("Erro", "A pontuação deve ser um número inteiro positivo.", parent=self.popup_criacao)
                return
        try:
            GESTOR_ID = 2 
            documento_id = database.criar_documento(titulo, conteudo.strip(), GESTOR_ID, pontos)
            if not documento_id:
                messagebox.showerror("Erro de Banco de Dados", "Não foi possível criar o registro do documento.", parent=self.popup_criacao)
                return

            destinatarios = [listbox.get(i) for i in indices_selecionados]
            enviados_com_sucesso = 0

            for display_text in destinatarios:
                funcionario = self.dados_funcionarios[display_text]
                assinatura_id = database.registrar_pendencia_assinatura(documento_id, funcionario.FuncionarioID)
                
                if assinatura_id:
                    texto_telegram = (
                        f"🚨 **NOVO COMUNICADO IMPORTANTE** 🚨\n\n"
                        f"**Título:** {titulo}\n\n"
                        f"**Conteúdo:**\n{conteudo.strip()}\n\n"
                        f"Sua confirmação de leitura é obrigatória e será registrada."
                    )
                    keyboard = [[InlineKeyboardButton("✅ Li e estou ciente", callback_data=f"doc_ciente_{assinatura_id}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    notificador_telegram.enviar_mensagem_com_botao(
                        funcionario.ChatIDTelegram, 
                        texto_telegram, 
                        reply_markup
                    )
                    enviados_com_sucesso += 1
                    time.sleep(0.1) 
            
            messagebox.showinfo("Sucesso", f"{enviados_com_sucesso} de {len(destinatarios)} comunicados foram enviados.", parent=self.popup_criacao)
            self.popup_criacao.destroy()
            self.atualizar_lista_comunicados()
        except Exception as e:
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro: {e}", parent=self.popup_criacao)
        
    # --- AQUI ESTÁ A CORREÇÃO: As funções abaixo agora estão no nível correto da classe ---

    def abrir_janela_detalhes(self):
        selecionado = self.tree_comunicados.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um comunicado na lista para ver os detalhes.")
            return
        dados_comunicado = self.tree_comunicados.item(selecionado, 'values')
        documento_id = dados_comunicado[0]
        detalhes_doc = database.buscar_detalhes_completos_documento(documento_id)
        if not detalhes_doc:
            messagebox.showerror("Erro", "Não foi possível encontrar os detalhes deste comunicado.")
            return
        titulo_comunicado = detalhes_doc.Titulo
        conteudo_comunicado = detalhes_doc.Conteudo
        popup_detalhes = Toplevel(self.root)
        popup_detalhes.title(f"Detalhes: {titulo_comunicado}")
        popup_detalhes.geometry("700x550")
        popup_detalhes.transient(self.root)
        frame_conteudo = ttk.LabelFrame(popup_detalhes, text="Conteúdo do Comunicado", padding="10")
        frame_conteudo.pack(padx=10, pady=10, fill="x")
        text_widget = Text(frame_conteudo, height=8, wrap="word", font=("Arial", 10))
        text_widget.insert("1.0", conteudo_comunicado)
        text_widget.config(state="disabled")
        scrollbar_conteudo = ttk.Scrollbar(frame_conteudo, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar_conteudo.set)
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar_conteudo.pack(side="left", fill="y")
        frame_detalhes = ttk.LabelFrame(popup_detalhes, text="Status de Ciência dos Funcionários", padding="10")
        frame_detalhes.pack(padx=10, pady=(0, 5), fill="both", expand=True)
        cols_detalhes = ('ID Assinatura', 'Funcionário', 'Status', 'Data da Ciência')
        tree_detalhes = ttk.Treeview(frame_detalhes, columns=cols_detalhes, show='headings')
        tree_detalhes.heading('ID Assinatura', text='ID')
        tree_detalhes.column('ID Assinatura', width=40, anchor='center')
        tree_detalhes.heading('Funcionário', text='Funcionário')
        tree_detalhes.column('Funcionário', width=250)
        tree_detalhes.heading('Status', text='Status')
        tree_detalhes.column('Status', width=100, anchor='center')
        tree_detalhes.heading('Data da Ciência', text='Data da Ciência')
        tree_detalhes.column('Data da Ciência', width=150, anchor='center')
        scrollbar_dest = ttk.Scrollbar(frame_detalhes, orient="vertical", command=tree_detalhes.yview)
        tree_detalhes.configure(yscrollcommand=scrollbar_dest.set)
        tree_detalhes.pack(side="left", fill="both", expand=True)
        scrollbar_dest.pack(side="left", fill="y")
        destinatarios = database.listar_destinatarios_de_documento(documento_id)
        for dest in destinatarios:
            data_ciencia_formatada = dest.DataCiencia.strftime("%d/%m/%Y %H:%M:%S") if dest.DataCiencia else "---"
            tree_detalhes.insert("", "end", values=(dest.AssinaturaID, dest.NomeCompleto, dest.StatusAssinatura, data_ciencia_formatada))
        btn_gerar_recibo = ttk.Button(popup_detalhes, text="Gerar Recibo PDF para Selecionado", command=lambda: self.gerar_recibo_para_selecionado(tree_detalhes, popup_detalhes))
        btn_gerar_recibo.pack(pady=(5,10), side="left", padx=10)
        btn_adicionar_func = ttk.Button(popup_detalhes, text="Adicionar Funcionário(s)", command=lambda: self.abrir_janela_adicionar_funcionario(documento_id, popup_detalhes))
        btn_adicionar_func.pack(pady=(5,10), side="left", padx=10)

    def excluir_comunicado_selecionado(self):
        selecionado = self.tree_comunicados.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um comunicado na lista para excluir.")
            return
        dados_comunicado = self.tree_comunicados.item(selecionado, 'values')
        documento_id = dados_comunicado[0]
        titulo_comunicado = dados_comunicado[1]
        confirmado = messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir permanentemente o comunicado:\n\n'{titulo_comunicado}'\n\nEsta ação não pode ser desfeita.", icon='warning')
        if confirmado:
            database.excluir_documento(documento_id)
            messagebox.showinfo("Sucesso", "O comunicado foi excluído com sucesso.")
            self.atualizar_lista_comunicados()

    def gerar_recibo_para_selecionado(self, tree_detalhes, popup_pai):
        selecionado = tree_detalhes.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista para gerar o recibo.", parent=popup_pai)
            return
        dados_assinatura = tree_detalhes.item(selecionado, 'values')
        assinatura_id = dados_assinatura[0]
        status = dados_assinatura[2]
        if status != 'Ciente':
            messagebox.showerror("Erro", "Só é possível gerar recibos para funcionários que já confirmaram a ciência.", parent=popup_pai)
            return
        try:
            dados_recibo = database.buscar_dados_completos_para_recibo(assinatura_id)
            if dados_recibo:
                path_do_pdf = recibo_generator.gerar_recibo_pdf(
                    assinatura_id=assinatura_id, nome_funcionario=dados_recibo.NomeCompleto,
                    titulo_doc=dados_recibo.Titulo, conteudo_doc=dados_recibo.Conteudo,
                    data_ciencia=dados_recibo.DataCiencia
                )
                file_utils.abrir_arquivo(path_do_pdf)
                messagebox.showinfo("Sucesso", f"Recibo em PDF gerado e aberto com sucesso!\n\nSalvo em: {os.path.abspath(path_do_pdf)}", parent=popup_pai)
            else:
                messagebox.showerror("Erro de Dados", "Não foi possível encontrar os dados completos para gerar este recibo.", parent=popup_pai)
        except Exception as e:
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao gerar o PDF: {e}", parent=popup_pai)

    def abrir_janela_adicionar_funcionario(self, documento_id, popup_pai):
        popup_adicionar = Toplevel(popup_pai)
        popup_adicionar.title("Adicionar Destinatários")
        popup_adicionar.geometry("400x500")
        popup_adicionar.transient(popup_pai)
        funcionarios_disponiveis = database.listar_funcionarios_nao_destinatarios(documento_id)
        if not funcionarios_disponiveis:
            messagebox.showinfo("Informação", "Todos os funcionários já receberam este comunicado.", parent=popup_adicionar)
            popup_adicionar.destroy()
            return
        Label(popup_adicionar, text="Selecione os funcionários para incluir:").pack(padx=10, pady=10)
        frame_lista = Frame(popup_adicionar)
        frame_lista.pack(padx=10, pady=5, fill="both", expand=True)
        listbox_novos = Listbox(frame_lista, selectmode=tk.EXTENDED)
        scrollbar = Scrollbar(frame_lista, orient="vertical", command=listbox_novos.yview)
        listbox_novos.configure(yscrollcommand=scrollbar.set)
        listbox_novos.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")
        dados_disponiveis = {}
        for func in funcionarios_disponiveis:
            display_text = f"{func.NomeCompleto} (ID: {func.FuncionarioID})"
            listbox_novos.insert(tk.END, display_text)
            dados_disponiveis[display_text] = func
        btn_confirmar = Button(popup_adicionar, text="Confirmar e Enviar Notificação", bg="green", fg="white",
                            command=lambda: self.confirmar_e_enviar_para_novos(
                                documento_id, listbox_novos, dados_disponiveis, popup_adicionar
                            ))
        btn_confirmar.pack(pady=10, padx=10, fill='x', ipady=5)

    def confirmar_e_enviar_para_novos(self, documento_id, listbox, dados_funcionarios, popup):
        indices_selecionados = listbox.curselection()
        if not indices_selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos um funcionário.", parent=popup)
            return
        detalhes_doc = database.buscar_detalhes_completos_documento(documento_id)
        if not detalhes_doc:
            messagebox.showerror("Erro Crítico", "Não foi possível encontrar os dados do comunicado original.", parent=popup)
            return
        enviados_com_sucesso = 0
        for i in indices_selecionados:
            display_text = listbox.get(i)
            funcionario = dados_funcionarios[display_text]
            assinatura_id = database.registrar_pendencia_assinatura(documento_id, funcionario.FuncionarioID)
            if assinatura_id:
                texto_telegram = (f"🚨 **NOVO COMUNICADO IMPORTANTE** 🚨\n\n"
                                f"**Título:** {detalhes_doc.Titulo}\n\n"
                                f"**Conteúdo:**\n{detalhes_doc.Conteudo}\n\n"
                                f"Sua confirmação de leitura é obrigatória e será registrada.")
                keyboard = [[InlineKeyboardButton("✅ Li e estou ciente", callback_data=f"doc_ciente_{assinatura_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                notificador_telegram.enviar_mensagem_com_botao(funcionario.ChatIDTelegram, texto_telegram, reply_markup)
                enviados_com_sucesso += 1
                time.sleep(0.1)
        messagebox.showinfo("Sucesso", f"{enviados_com_sucesso} funcionário(s) foram notificados com sucesso!", parent=popup)
        popup.destroy()

    def filtrar_lista_comunicados(self):
        termo_busca = self.entry_filtro.get()
        self.atualizar_lista_comunicados(filtro=termo_busca)

    def limpar_filtro(self):
        self.entry_filtro.delete(0, "end")
        self.atualizar_lista_comunicados()
        
if __name__ == "__main__":
    root = tk.Tk()
    app = AppComunicados(root)
    root.mainloop()
# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING (Igual ao anterior) ================
# ==============================================================================
import logging
import logging.handlers
import sys
import os

LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs'
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        print(f"Pasta de logs criada em: {log_dir}")
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        log_dir = os.path.dirname(__file__)

log_filepath = os.path.join(log_dir, LOG_FILENAME)
file_handler = logging.handlers.RotatingFileHandler(
    log_filepath, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
)
file_handler.setLevel(LOG_LEVEL)
file_formatter = logging.Formatter(LOG_FORMAT)
file_handler.setFormatter(file_formatter)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL)
console_formatter = logging.Formatter(LOG_FORMAT)
console_handler.setFormatter(console_formatter)
logging.getLogger('').handlers = []
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[file_handler, console_handler])
logger = logging.getLogger(__name__)
logger.info(f"*** Logging configurado para o módulo: {__name__} ***")
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================

import tkinter as tk
from tkinter import ttk, messagebox
import database # Importa nosso arquivo de banco de dados

class AppGestaoEstoque:
    def __init__(self, root):
        self.root = root
        self.root.title("Módulo de Gestão de Estoque")
        self.root.geometry("1000x600") # Aumentei a largura
        
        # --- NOVO: Notebook (Abas) ---
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        # --- Frames para cada Aba ---
        self.frame_produtos = ttk.Frame(self.notebook, padding="10")
        self.frame_fornecedores = ttk.Frame(self.notebook, padding="10")
        # (Futuramente adicionaremos a frame_xml aqui)

        self.notebook.add(self.frame_produtos, text='1. Catálogo Mestre (Produtos)')
        self.notebook.add(self.frame_fornecedores, text='2. Fornecedores')

        # --- Variáveis de rastreio ---
        self.produto_selecionado_id = None
        self.fornecedor_selecionado_id = None # NOVO

        # --- Chama as funções para construir cada aba ---
        self.criar_aba_catalogo_produtos()
        self.criar_aba_fornecedores() # NOVO

    # ===================================================================
    # == ABA 1: CATÁLOGO MESTRE DE PRODUTOS =============================
    # (Este é o código que já tínhamos, agora dentro de uma função)
    # ===================================================================
    def criar_aba_catalogo_produtos(self):
        main_frame = ttk.Frame(self.frame_produtos)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Frame do Formulário (Esquerda) ---
        form_frame = ttk.LabelFrame(main_frame, text="Cadastrar/Editar Produto Mestre", padding="10")
        form_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        ttk.Label(form_frame, text="Nome do Produto:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_prod_nome = ttk.Entry(form_frame, width=40)
        self.entry_prod_nome.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Label(form_frame, text="Unidade (Ex: UN, KG, L):").grid(row=2, column=0, sticky="w", pady=2)
        self.entry_prod_unidade = ttk.Entry(form_frame, width=15)
        self.entry_prod_unidade.grid(row=3, column=0, sticky="w", pady=(0, 10))

        ttk.Label(form_frame, text="Estoque Mínimo:").grid(row=2, column=1, sticky="w", pady=2)
        self.entry_prod_estoque_min = ttk.Entry(form_frame, width=15)
        self.entry_prod_estoque_min.grid(row=3, column=1, sticky="w", pady=(0, 10))
        self.entry_prod_estoque_min.insert(0, "0.0")

        btn_frame = ttk.Frame(form_frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)

        self.btn_prod_salvar = ttk.Button(btn_frame, text="Salvar Novo", command=self.salvar_produto)
        self.btn_prod_salvar.pack(side=tk.LEFT, padx=5)

        self.btn_prod_limpar = ttk.Button(btn_frame, text="Limpar", command=self.limpar_formulario_produto)
        self.btn_prod_limpar.pack(side=tk.LEFT, padx=5)

        # --- Frame da Lista (Direita) ---
        lista_frame = ttk.LabelFrame(main_frame, text="Catálogo Mestre de Produtos", padding="10")
        lista_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        lista_frame.rowconfigure(0, weight=1)
        lista_frame.columnconfigure(0, weight=1)

        cols = ('ID', 'Nome', 'Unidade', 'Estoque Mínimo')
        self.tree_produtos = ttk.Treeview(lista_frame, columns=cols, show='headings', selectmode='browse')
        
        self.tree_produtos.heading('ID', text='ID'); self.tree_produtos.column('ID', width=40, anchor='center')
        self.tree_produtos.heading('Nome', text='Nome'); self.tree_produtos.column('Nome', width=250)
        self.tree_produtos.heading('Unidade', text='UN'); self.tree_produtos.column('Unidade', width=50, anchor='center')
        self.tree_produtos.heading('Estoque Mínimo', text='Est. Mínimo'); self.tree_produtos.column('Estoque Mínimo', width=80, anchor='e')
        
        scrollbar = ttk.Scrollbar(lista_frame, orient="vertical", command=self.tree_produtos.yview)
        self.tree_produtos.configure(yscrollcommand=scrollbar.set)
        
        self.tree_produtos.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.tree_produtos.bind('<<TreeviewSelect>>', self.selecionar_produto_para_edicao)

        lista_btn_frame = ttk.Frame(lista_frame)
        lista_btn_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0))

        btn_excluir = ttk.Button(lista_btn_frame, text="Excluir Selecionado", command=self.excluir_produto_selecionado)
        btn_excluir.pack(side=tk.LEFT)

        self.atualizar_lista_produtos()

    def limpar_formulario_produto(self):
        self.entry_prod_nome.delete(0, tk.END)
        self.entry_prod_unidade.delete(0, tk.END)
        self.entry_prod_estoque_min.delete(0, tk.END); self.entry_prod_estoque_min.insert(0, "0.0")
        self.produto_selecionado_id = None
        self.btn_prod_salvar.config(text="Salvar Novo")
        self.entry_prod_nome.focus()
        if self.tree_produtos.selection():
            self.tree_produtos.selection_remove(self.tree_produtos.selection()[0])

    def salvar_produto(self):
        nome = self.entry_prod_nome.get()
        unidade = self.entry_prod_unidade.get().upper()
        estoque_min_str = self.entry_prod_estoque_min.get().replace(",", ".")
        if not nome or not unidade:
            messagebox.showerror("Erro", "Nome e Unidade são obrigatórios.", parent=self.root)
            return
        try:
            estoque_min = float(estoque_min_str)
        except ValueError:
            messagebox.showerror("Erro", "Estoque Mínimo deve ser um número.", parent=self.root)
            return
        try:
            if self.produto_selecionado_id:
                database.atualizar_produto_estoque(self.produto_selecionado_id, nome, unidade, estoque_min)
                messagebox.showinfo("Sucesso", "Produto atualizado com sucesso!", parent=self.root)
            else:
                database.criar_produto_estoque(nome, unidade, estoque_min)
                messagebox.showinfo("Sucesso", "Produto criado com sucesso!", parent=self.root)
            self.limpar_formulario_produto()
            self.atualizar_lista_produtos()
        except Exception as e:
            logger.error(f"Erro ao salvar produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível salvar o produto.\nErro: {e}", parent=self.root)

    def atualizar_lista_produtos(self):
        for i in self.tree_produtos.get_children():
            self.tree_produtos.delete(i)
        try:
            produtos = database.listar_produtos_estoque()
            for p in produtos:
                self.tree_produtos.insert("", "end", values=(p.ProdutoID, p.NomeProduto, p.UnidadeMedida, f"{p.EstoqueMinimo:.3f}"))
        except Exception as e:
            logger.error(f"Erro ao atualizar lista de produtos: {e}", exc_info=True)

    def selecionar_produto_para_edicao(self, event=None):
        selecionado = self.tree_produtos.focus()
        if not selecionado: return
        dados = self.tree_produtos.item(selecionado, 'values')
        produto_id, nome, unidade, estoque_min = dados
        self.limpar_formulario_produto()
        self.produto_selecionado_id = int(produto_id)
        self.entry_prod_nome.insert(0, nome)
        self.entry_prod_unidade.insert(0, unidade)
        self.entry_prod_estoque_min.delete(0, tk.END); self.entry_prod_estoque_min.insert(0, estoque_min)
        self.btn_prod_salvar.config(text="Atualizar Produto")

    def excluir_produto_selecionado(self):
        if not self.produto_selecionado_id:
            messagebox.showwarning("Aviso", "Selecione um produto da lista para excluir.", parent=self.root)
            return
        nome_produto = self.entry_prod_nome.get()
        if not messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o produto:\n\n'{nome_produto}'?", icon='warning', parent=self.root):
            return
        try:
            database.excluir_produto_estoque(self.produto_selecionado_id)
            messagebox.showinfo("Sucesso", "Produto excluído com sucesso!", parent=self.root)
            self.limpar_formulario_produto()
            self.atualizar_lista_produtos()
        except Exception as e:
            logger.error(f"Erro ao excluir produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", "Não foi possível excluir o produto.\nVerifique se ele já está vinculado a notas fiscais ou contagens.", parent=self.root)

    # ===================================================================
    # == ABA 2: CADASTRO DE FORNECEDORES (NOVO) =========================
    # ===================================================================
    def criar_aba_fornecedores(self):
        main_frame = ttk.Frame(self.frame_fornecedores)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Frame do Formulário (Esquerda) ---
        form_frame = ttk.LabelFrame(main_frame, text="Cadastrar/Editar Fornecedor", padding="10")
        form_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        ttk.Label(form_frame, text="Nome Fantasia:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_forn_nome = ttk.Entry(form_frame, width=40)
        self.entry_forn_nome.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Label(form_frame, text="CNPJ (apenas números):").grid(row=2, column=0, sticky="w", pady=2)
        self.entry_forn_cnpj = ttk.Entry(form_frame, width=40)
        self.entry_forn_cnpj.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 10))

        btn_frame = ttk.Frame(form_frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)

        self.btn_forn_salvar = ttk.Button(btn_frame, text="Salvar Novo", command=self.salvar_fornecedor)
        self.btn_forn_salvar.pack(side=tk.LEFT, padx=5)

        self.btn_forn_limpar = ttk.Button(btn_frame, text="Limpar", command=self.limpar_formulario_fornecedor)
        self.btn_forn_limpar.pack(side=tk.LEFT, padx=5)

        # --- Frame da Lista (Direita) ---
        lista_frame = ttk.LabelFrame(main_frame, text="Fornecedores Cadastrados", padding="10")
        lista_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        lista_frame.rowconfigure(0, weight=1)
        lista_frame.columnconfigure(0, weight=1)

        cols_forn = ('ID', 'Nome Fantasia', 'CNPJ')
        self.tree_fornecedores = ttk.Treeview(lista_frame, columns=cols_forn, show='headings', selectmode='browse')
        
        self.tree_fornecedores.heading('ID', text='ID'); self.tree_fornecedores.column('ID', width=40, anchor='center')
        self.tree_fornecedores.heading('Nome Fantasia', text='Nome'); self.tree_fornecedores.column('Nome Fantasia', width=250)
        self.tree_fornecedores.heading('CNPJ', text='CNPJ'); self.tree_fornecedores.column('CNPJ', width=150, anchor='center')
        
        scrollbar_forn = ttk.Scrollbar(lista_frame, orient="vertical", command=self.tree_fornecedores.yview)
        self.tree_fornecedores.configure(yscrollcommand=scrollbar_forn.set)
        
        self.tree_fornecedores.grid(row=0, column=0, sticky="nsew")
        scrollbar_forn.grid(row=0, column=1, sticky="ns")
        
        self.tree_fornecedores.bind('<<TreeviewSelect>>', self.selecionar_fornecedor_para_edicao)

        lista_btn_frame_forn = ttk.Frame(lista_frame)
        lista_btn_frame_forn.grid(row=1, column=0, columnspan=2, pady=(10, 0))

        btn_excluir_forn = ttk.Button(lista_btn_frame_forn, text="Excluir Selecionado", command=self.excluir_fornecedor_selecionado)
        btn_excluir_forn.pack(side=tk.LEFT)

        self.atualizar_lista_fornecedores()

    def limpar_formulario_fornecedor(self):
        self.entry_forn_nome.delete(0, tk.END)
        self.entry_forn_cnpj.delete(0, tk.END)
        self.fornecedor_selecionado_id = None
        self.btn_forn_salvar.config(text="Salvar Novo")
        self.entry_forn_nome.focus()
        if self.tree_fornecedores.selection():
            self.tree_fornecedores.selection_remove(self.tree_fornecedores.selection()[0])

    def salvar_fornecedor(self):
        nome = self.entry_forn_nome.get()
        cnpj = self.entry_forn_cnpj.get()

        if not nome or not cnpj:
            messagebox.showerror("Erro", "Nome Fantasia e CNPJ são obrigatórios.", parent=self.root)
            return
        
        try:
            if self.fornecedor_selecionado_id:
                database.atualizar_fornecedor(self.fornecedor_selecionado_id, cnpj, nome)
                messagebox.showinfo("Sucesso", "Fornecedor atualizado com sucesso!", parent=self.root)
            else:
                database.criar_fornecedor(cnpj, nome)
                messagebox.showinfo("Sucesso", "Fornecedor criado com sucesso!", parent=self.root)
            
            self.limpar_formulario_fornecedor()
            self.atualizar_lista_fornecedores()

        except Exception as e:
            logger.error(f"Erro ao salvar fornecedor: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível salvar o fornecedor.\nVerifique se o CNPJ já não está cadastrado.\nErro: {e}", parent=self.root)

    def atualizar_lista_fornecedores(self):
        for i in self.tree_fornecedores.get_children():
            self.tree_fornecedores.delete(i)
        try:
            fornecedores = database.listar_fornecedores()
            for f in fornecedores:
                self.tree_fornecedores.insert("", "end", values=(f.FornecedorID, f.NomeFantasia, f.CNPJ))
        except Exception as e:
            logger.error(f"Erro ao atualizar lista de fornecedores: {e}", exc_info=True)

    def selecionar_fornecedor_para_edicao(self, event=None):
        selecionado = self.tree_fornecedores.focus()
        if not selecionado: return
        dados = self.tree_fornecedores.item(selecionado, 'values')
        fornecedor_id, nome, cnpj = dados
        self.limpar_formulario_fornecedor()
        self.fornecedor_selecionado_id = int(fornecedor_id)
        self.entry_forn_nome.insert(0, nome)
        self.entry_forn_cnpj.insert(0, cnpj)
        self.btn_forn_salvar.config(text="Atualizar Fornecedor")

    def excluir_fornecedor_selecionado(self):
        if not self.fornecedor_selecionado_id:
            messagebox.showwarning("Aviso", "Selecione um fornecedor da lista para excluir.", parent=self.root)
            return
        
        nome_fornecedor = self.entry_forn_nome.get()
        if not messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o fornecedor:\n\n'{nome_fornecedor}'?", icon='warning', parent=self.root):
            return
        
        try:
            database.excluir_fornecedor(self.fornecedor_selecionado_id)
            messagebox.showinfo("Sucesso", "Fornecedor excluído com sucesso!", parent=self.root)
            self.limpar_formulario_fornecedor()
            self.atualizar_lista_fornecedores()
        except Exception as e:
            logger.error(f"Erro ao excluir fornecedor: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", "Não foi possível excluir o fornecedor.\nVerifique se ele já está vinculado a notas fiscais.", parent=self.root)


# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoEstoque(root)
    root.mainloop()

# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING (Igual ao anterior) ================
# ==============================================================================
import logging
import logging.handlers
import sys
import file_utils
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
from tkinter import ttk, messagebox, filedialog, simpledialog, Toplevel
import database # Importa nosso arquivo de banco de dados
from lxml import etree as ET 
from datetime import datetime
from tkcalendar import DateEntry 
from decimal import Decimal, InvalidOperation # <-- Adicionado InvalidOperation

class AppGestaoEstoque:
    def __init__(self, root):
        self.root = root
        self.root.title("Módulo de Gestão de Estoque")
        self.root.geometry("1200x700") 
        
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        self.frame_produtos = ttk.Frame(self.notebook, padding="10")
        self.frame_fornecedores = ttk.Frame(self.notebook, padding="10")
        self.frame_importacao = ttk.Frame(self.notebook, padding="10") 
        self.frame_contagem = ttk.Frame(self.notebook, padding="10")
        self.frame_sugestao = ttk.Frame(self.notebook, padding="10") 
        self.frame_admin = ttk.Frame(self.notebook, padding="10") # Nova Aba Admin

        self.notebook.add(self.frame_produtos, text='1. Catálogo Mestre')
        self.notebook.add(self.frame_fornecedores, text='2. Fornecedores')
        self.notebook.add(self.frame_importacao, text='3. Importar XMLs (DE/PARA)')
        self.notebook.add(self.frame_contagem, text='4. Lançar Contagem Física')
        self.notebook.add(self.frame_sugestao, text='5. Sugestão de Compra') 
        self.notebook.add(self.frame_admin, text='6. Administração / Reset')
        self.frame_solicitacoes = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.frame_solicitacoes, text='7. Solicitações (Líderes)')
        self.criar_aba_solicitacoes()

        self.produto_selecionado_id = None
        self.fornecedor_selecionado_id = None
        
        self.itens_xml_nao_vinculados = []
        self.dados_notas_processadas = []
        self.mapa_produtos_mestre = {}
        self.lista_mestre_produtos_nomes = [] 

        self.mapa_produtos_mestre_contagem = {}
        self.lista_itens_para_salvar_contagem = []
        self.lista_mestre_contagem_nomes = []
        
        self.cache_relatorio_posicao = {}
        self.mapa_contagens_historico = {} 

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.criar_aba_catalogo_produtos()
        self.criar_aba_fornecedores()
        self.criar_aba_importacao_xml() 
        self.criar_aba_contagem_estoque()
        self.criar_aba_sugestao_compra() 
        self.criar_aba_administracao()
        
        # Carregamento inicial
        self.atualizar_lista_produtos() 
        self.atualizar_lista_fornecedores() 
        self.popular_combobox_produtos_mestre() 
        self.atualizar_lista_contagens_historico() 
        self.popular_combos_contagem_sugestao() # <-- CORREÇÃO: Inicializa os combos da aba 5

    def on_tab_changed(self, event):
        """Atualiza os dados das abas quando elas são selecionadas."""
        tab_selecionada = self.notebook.tab(self.notebook.select(), "text")
        
        if tab_selecionada == '5. Sugestão de Compra':
            self.popular_combos_contagem_sugestao()
        elif tab_selecionada == '4. Lançar Contagem Física':
            self.atualizar_lista_contagens_historico()
        elif tab_selecionada == '1. Catálogo Mestre':
            self.atualizar_lista_produtos()
        elif tab_selecionada == '2. Fornecedores':
            self.atualizar_lista_fornecedores()
        elif tab_selecionada == '6. Administração / Reset':
            self.atualizar_lista_nfs_admin()
            self.atualizar_lista_contagens_admin()
        elif tab_selecionada == '7. Aprovar Compras/Manutenção':
            self.carregar_solicitacoes()

    # ===================================================================
    # == ABA 1: CATÁLOGO MESTRE (Sem alterações) ========================
    # ===================================================================
    def criar_aba_catalogo_produtos(self):
        main_frame = ttk.Frame(self.frame_produtos)
        main_frame.pack(fill=tk.BOTH, expand=True)
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
            estoque_min = Decimal(estoque_min_str)
        except InvalidOperation: # <-- CORREÇÃO: Exceção específica
            messagebox.showerror("Erro", "Estoque Mínimo deve ser um número.", parent=self.root)
            return
        try:
            if self.produto_selecionado_id:
                database.atualizar_produto_estoque(self.produto_selecionado_id, nome, unidade, estoque_min)
                messagebox.showinfo("Sucesso", "Produto atualizado com sucesso!", parent=self.root)
            else:
                novo_id = database.criar_produto_estoque(nome, unidade, estoque_min) 
                if not novo_id: raise Exception("Falha ao criar produto, não retornou ID.")
                messagebox.showinfo("Sucesso", "Produto criado com sucesso!", parent=self.root)
            self.limpar_formulario_produto()
            self.atualizar_lista_produtos()
            self.popular_combobox_produtos_mestre()
        except Exception as e:
            logger.error(f"Erro ao salvar produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível salvar o produto.\nErro: {e}", parent=self.root)

    def atualizar_lista_produtos(self):
        for i in self.tree_produtos.get_children():
            self.tree_produtos.delete(i)
        try:
            produtos = database.listar_produtos_estoque()
            self.mapa_produtos_mestre_contagem.clear()
            for p in produtos:
                self.tree_produtos.insert("", "end", values=(p.ProdutoID, p.NomeProduto, p.UnidadeMedida, f"{p.EstoqueMinimo:.3f}"))
                self.mapa_produtos_mestre_contagem[p.NomeProduto] = {'id': p.ProdutoID, 'un': p.UnidadeMedida}
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
            self.popular_combobox_produtos_mestre()
        except Exception as e:
            logger.error(f"Erro ao excluir produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", "Não foi possível excluir o produto.\nVerifique se ele já está vinculado a notas fiscais ou contagens.", parent=self.root)

    # ===================================================================
    # == ABA 2: FORNECEDORES (Sem alterações) ===========================
    # ===================================================================
    def criar_aba_fornecedores(self):
        # ... (código idêntico ao anterior) ...
        main_frame = ttk.Frame(self.frame_fornecedores)
        main_frame.pack(fill=tk.BOTH, expand=True)
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

    def limpar_formulario_fornecedor(self):
        # ... (código idêntico ao anterior) ...
        self.entry_forn_nome.delete(0, tk.END)
        self.entry_forn_cnpj.delete(0, tk.END)
        self.fornecedor_selecionado_id = None
        self.btn_forn_salvar.config(text="Salvar Novo")
        self.entry_forn_nome.focus()
        if self.tree_fornecedores.selection():
            self.tree_fornecedores.selection_remove(self.tree_fornecedores.selection()[0])

    def salvar_fornecedor(self):
        # ... (código idêntico ao anterior) ...
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
        # ... (código idêntico ao anterior) ...
        for i in self.tree_fornecedores.get_children():
            self.tree_fornecedores.delete(i)
        try:
            fornecedores = database.listar_fornecedores()
            for f in fornecedores:
                self.tree_fornecedores.insert("", "end", values=(f.FornecedorID, f.NomeFantasia, f.CNPJ))
        except Exception as e:
            logger.error(f"Erro ao atualizar lista de fornecedores: {e}", exc_info=True)

    def selecionar_fornecedor_para_edicao(self, event=None):
        # ... (código idêntico ao anterior) ...
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
        # ... (código idêntico ao anterior) ...
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

    # ===================================================================
    # == ABA 3: IMPORTAÇÃO XML (ATUALIZADA com Filtro) ==================
    # ===================================================================
    def criar_aba_importacao_xml(self):
        main_frame = ttk.Frame(self.frame_importacao)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1) 
        main_frame.rowconfigure(3, weight=1) 
        frame_botoes = ttk.Frame(main_frame)
        frame_botoes.grid(row=0, column=0, sticky="ew", pady=5)
        btn_selecionar_pasta = ttk.Button(frame_botoes, text="1. Selecionar Pasta com XMLs de Compra", command=self.abrir_seletor_pasta_xml)
        btn_selecionar_pasta.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10)
        frame_vincular = ttk.LabelFrame(main_frame, text="2. Itens Pendentes de Vinculação (DE/PARA)", padding="10")
        frame_vincular.grid(row=1, column=0, sticky="nsew", pady=5)
        frame_vincular.rowconfigure(0, weight=1)
        frame_vincular.columnconfigure(0, weight=1)
        # --- COLUNAS ATUALIZADAS (Removido NCM, Adicionado Qtd/Custo) ---
        cols_vinc = ('Fornecedor', 'Produto no XML', 'EAN', 'Qtd na Nota', 'Custo Unit.', 'Custo Total')
        self.tree_vincular = ttk.Treeview(frame_vincular, columns=cols_vinc, show='headings', selectmode='browse')

        self.tree_vincular.heading('Fornecedor', text='Fornecedor'); self.tree_vincular.column('Fornecedor', width=150)
        self.tree_vincular.heading('Produto no XML', text='Produto no XML'); self.tree_vincular.column('Produto no XML', width=250)
        self.tree_vincular.heading('EAN', text='EAN'); self.tree_vincular.column('EAN', width=100, anchor='center')
        self.tree_vincular.heading('Qtd na Nota', text='Qtd Nota'); self.tree_vincular.column('Qtd na Nota', width=60, anchor='center')
        self.tree_vincular.heading('Custo Unit.', text='Custo Unit.'); self.tree_vincular.column('Custo Unit.', width=80, anchor='e')
        self.tree_vincular.heading('Custo Total', text='Custo Total'); self.tree_vincular.column('Custo Total', width=80, anchor='e')
        self.tree_vincular.grid(row=0, column=0, sticky="nsew")
        self.tree_vincular.bind("<<TreeviewSelect>>", self.sugerir_mestre_por_ean)
        frame_ferramenta = ttk.Frame(main_frame)
        frame_ferramenta.grid(row=2, column=0, sticky="ew", pady=10)
        frame_ferramenta.columnconfigure(1, weight=1)
        ttk.Label(frame_ferramenta, text="Filtrar Lista:").grid(row=0, column=0, sticky="w", padx=(0,5))
        self.entry_filtro_importacao = ttk.Entry(frame_ferramenta, width=25)
        self.entry_filtro_importacao.grid(row=0, column=1, sticky="ew", padx=(0,10))
        self.entry_filtro_importacao.bind("<KeyRelease>", self.filtrar_combo_importacao)
        ttk.Label(frame_ferramenta, text="Vincular ao Mestre:").grid(row=0, column=2, sticky="w", padx=(10,5))
        self.combo_produtos_mestre = ttk.Combobox(frame_ferramenta, state="readonly", width=35)
        self.combo_produtos_mestre.grid(row=0, column=3, sticky="ew", padx=(0,5))
       # --- NOVO CAMPO: FATOR DE CONVERSÃO ---
        ttk.Label(frame_ferramenta, text="Itens p/ Cx:").grid(row=0, column=4, sticky="w")
        self.entry_fator_conversao = ttk.Entry(frame_ferramenta, width=5)
        self.entry_fator_conversao.insert(0, "1") # Padrão é 1 para 1
        self.entry_fator_conversao.grid(row=0, column=5, sticky="w", padx=(0,10))
        btn_vincular = ttk.Button(frame_ferramenta, text="Vincular", command=self.vincular_produto_selecionado)
        btn_vincular.grid(row=0, column=6, sticky="w", padx=5)
        btn_criar_vincular = ttk.Button(frame_ferramenta, text="Criar Mestre e Vincular", command=self.criar_mestre_e_vincular)
        btn_criar_vincular.grid(row=0, column=7, sticky="w", padx=5)
        frame_prontos = ttk.LabelFrame(main_frame, text="3. Itens Prontos para Salvar (Já Vinculados)", padding="10")
        frame_prontos.grid(row=3, column=0, sticky="nsew", pady=5)
        frame_prontos.rowconfigure(0, weight=1)
        frame_prontos.columnconfigure(0, weight=1)
        cols_prontos = ('NF', 'Fornecedor', 'Produto Mestre', 'Qtd', 'Custo Unit.', 'Custo Total')
        self.tree_prontos = ttk.Treeview(frame_prontos, columns=cols_prontos, show='headings', selectmode='none')
        for col in cols_prontos: self.tree_prontos.heading(col, text=col)
        self.tree_prontos.column('NF', width=80, anchor='center')
        self.tree_prontos.column('Fornecedor', width=150)
        self.tree_prontos.column('Produto Mestre', width=200)
        self.tree_prontos.column('Qtd', width=60, anchor='e')
        self.tree_prontos.column('Custo Unit.', width=80, anchor='e')
        self.tree_prontos.column('Custo Total', width=80, anchor='e')
        self.tree_prontos.grid(row=0, column=0, sticky="nsew")
        btn_salvar_tudo = ttk.Button(main_frame, text="4. Salvar Todas as Notas Processadas no Banco", command=self.salvar_notas_processadas)
        btn_salvar_tudo.grid(row=4, column=0, sticky="ew", pady=10, ipady=10)
        # Botão de Gerenciamento de Vínculos (Correção)
        btn_gerir_vinculos = ttk.Button(main_frame, text="🛠️ Gerenciar / Corrigir Vínculos Salvos", command=self.abrir_gestor_vinculos)
        btn_gerir_vinculos.grid(row=5, column=0, sticky="ew", pady=(0, 10))

    def sugerir_mestre_por_ean(self, event):
        """
        Ao clicar num item pendente, verifica se o EAN já existe no sistema.
        Se existir, seleciona automaticamente o Produto Mestre no Combobox.
        """
        selecionado = self.tree_vincular.focus()
        if not selecionado: return

        # Pega os dados da linha clicada
        # Ordem das colunas: Fornecedor, ProdutoXML, EAN, Qtd, Custo...
        valores = self.tree_vincular.item(selecionado, 'values')
        ean_clicado = valores[2] # O EAN é a terceira coluna (índice 2)

        # 1. Tenta descobrir quem é esse EAN
        sugestao = database.descobrir_produto_mestre_por_ean(ean_clicado)

        if sugestao:
            nome_mestre, id_mestre = sugestao
            # Formata como aparece no Combobox: "Nome (ID: 123)"
            texto_combo = f"{nome_mestre} (ID: {id_mestre})"

            # Verifica se essa opção existe na lista atual do combo
            if texto_combo in self.lista_mestre_produtos_nomes:
                self.combo_produtos_mestre.set(texto_combo)
                # Feedback visual sutil (Opcional: piscar o campo ou focar)
                print(f"Sugestão Automática: {texto_combo}")
            else:
                self.combo_produtos_mestre.set('')
        else:
            # Se não achou nada, limpa para não confundir
            self.combo_produtos_mestre.set('')

    def popular_combobox_produtos_mestre(self):
        # ... (código idêntico ao anterior) ...
        try:
            produtos = database.listar_produtos_estoque()
            self.mapa_produtos_mestre.clear()
            self.lista_mestre_produtos_nomes.clear() 
            nomes_produtos_mestre = []
            for p in produtos:
                nome_display = f"{p.NomeProduto} (ID: {p.ProdutoID})"
                nomes_produtos_mestre.append(nome_display)
                self.mapa_produtos_mestre[nome_display] = p.ProdutoID
            self.lista_mestre_produtos_nomes = sorted(nomes_produtos_mestre) 
            self.combo_produtos_mestre['values'] = self.lista_mestre_produtos_nomes
            self.lista_mestre_contagem_nomes = sorted(list(self.mapa_produtos_mestre_contagem.keys()))
            if hasattr(self, 'combo_contagem_produtos'):
                self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes
        except Exception as e:
            logger.error(f"Erro ao carregar produtos mestre no combobox: {e}", exc_info=True)

    def filtrar_combo_importacao(self, event=None):
        # ... (código idêntico ao anterior) ...
        texto = self.entry_filtro_importacao.get().lower()
        if not texto:
            self.combo_produtos_mestre['values'] = self.lista_mestre_produtos_nomes
            self.combo_produtos_mestre.set('')
        else:
            filtrados = [nome for nome in self.lista_mestre_produtos_nomes if texto in nome.lower()]
            self.combo_produtos_mestre['values'] = filtrados
            if filtrados:
                self.combo_produtos_mestre.set(filtrados[0])
            else:
                self.combo_produtos_mestre.set('')

    def abrir_seletor_pasta_xml(self):
        # ... (código idêntico ao anterior) ...
        pasta_selecionada = filedialog.askdirectory(title="Selecione a pasta contendo os XMLs")
        if not pasta_selecionada:
            return
        for i in self.tree_vincular.get_children(): self.tree_vincular.delete(i)
        for i in self.tree_prontos.get_children(): self.tree_prontos.delete(i)
        self.itens_xml_nao_vinculados.clear()
        self.dados_notas_processadas.clear()
        try:
            self.processar_arquivos_xml(pasta_selecionada)
        except Exception as e:
            logger.error(f"Erro GERAL ao processar pasta XML: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico no Processamento", f"Ocorreu um erro ao ler os arquivos:\n{e}", parent=self.root)

    def ler_xml_nota_fiscal(self, caminho_arquivo_xml):
        try:
            parser = ET.XMLParser(remove_blank_text=True)
            tree = ET.parse(caminho_arquivo_xml, parser)
            root = tree.getroot()

            # [CORREÇÃO] Remove namespaces para facilitar a busca das tags e evitar erros de versão
            for elem in root.getiterator():
                if not hasattr(elem.tag, 'find'): continue
                i = elem.tag.find('}')
                if i >= 0:
                    elem.tag = elem.tag[i+1:]

            # Busca direta sem namespace (mais robusto)
            ide = root.find('.//ide')
            emit = root.find('.//emit')
            total = root.find('.//total/ICMSTot')

            if ide is None or emit is None or total is None:
                raise Exception("Estrutura do XML inválida (tags essenciais não encontradas após limpeza).")

            dados_nf = {
                'NumeroNF': ide.findtext('nNF', default=''),
                # Alguns XMLs usam dhEmi, outros dEmi. Tenta ambos.
                'DataEmissao': (ide.findtext('dhEmi') or ide.findtext('dEmi') or datetime.now().strftime('%Y-%m-%dT')).split('T')[0],
                'ValorTotalNF': Decimal(total.findtext('vNF', default='0.0')),
                'FornecedorCNPJ': emit.findtext('CNPJ', default=''),
                'FornecedorNome': emit.findtext('xNome', default='')
            }

            itens = []
            detalhes = root.findall('.//det')
            for det in detalhes:
                prod = det.find('prod')
                if prod is None: continue

                itens.append({
                    'cProd': prod.findtext('cProd', default=''),
                    'cEAN': prod.findtext('cEAN', default=''),
                    'DescricaoXML': prod.findtext('xProd', default=''),
                    'NCM': prod.findtext('NCM', default=''),
                    'Quantidade': Decimal(prod.findtext('qCom', default='0.0')),
                    'PrecoCustoUnitario': Decimal(prod.findtext('vUnCom', default='0.0'))
                })

            return dados_nf, itens

        except Exception as e:
            logger.error(f"Erro ao ler o arquivo XML '{caminho_arquivo_xml}': {e}", exc_info=True)
            raise Exception(f"Falha estrutural no XML: {e}")

    def processar_arquivos_xml(self, pasta_selecionada):
        # ... (código idêntico ao anterior, agora com pop-up de erro) ...
        extensoes_permitidas = ('.xml', '.txt')
        arquivos_xml = [os.path.join(pasta_selecionada, f) for f in os.listdir(pasta_selecionada) if f.lower().endswith(extensoes_permitidas)]
        notas_processadas_nesta_sessao = {}
        arquivos_com_falha = 0
        for caminho_xml in arquivos_xml:
            try:
                cabecalho_nf, itens_nf = self.ler_xml_nota_fiscal(caminho_xml)
                cnpj = cabecalho_nf['FornecedorCNPJ']
                nome_fornecedor = cabecalho_nf['FornecedorNome']
                num_nf = cabecalho_nf['NumeroNF']
                if not cnpj or not itens_nf:
                    raise Exception("Arquivo XML não contém CNPJ ou lista de itens.")
                fornecedor_id = database.buscar_fornecedor_por_cnpj(cnpj)
                if not fornecedor_id:
                    database.criar_fornecedor(cnpj, nome_fornecedor)
                    fornecedor_id = database.buscar_fornecedor_por_cnpj(cnpj)
                    self.atualizar_lista_fornecedores()
                cabecalho_nf['FornecedorID'] = fornecedor_id
                if num_nf not in notas_processadas_nesta_sessao:
                     notas_processadas_nesta_sessao[num_nf] = {
                        'cabecalho': cabecalho_nf,
                        'itens_vinculados': []
                    }
                for item in itens_nf:
                    desc_xml = item['DescricaoXML']
                    vinculo_existente = database.buscar_vinculo_produto_fornecedor(fornecedor_id, desc_xml)

                    if vinculo_existente:
                        # Desempacota os 3 valores. Se fator vier None do banco, trata aqui.
                        produto_fornecedor_id, produto_mestre_id, fator_db = vinculo_existente

                        # Tratamento defensivo: se for None ou <= 0, assume 1.0
                        if fator_db is None or fator_db <= 0:
                            fator = Decimal('1.0')
                        else:
                            fator = Decimal(str(fator_db))

                        # --- A MÁGICA DA CONVERSÃO ---
                        qtd_xml = item['Quantidade'] # Ex: 1 (caixa)
                        custo_xml = item['PrecoCustoUnitario'] # Ex: 60.00 (caixa)

                        qtd_real = qtd_xml * fator # Ex: 1 * 6 = 6 Unidades
                        custo_real = custo_xml / fator # Ex: 60 / 6 = 10.00 Unidade

                        item_pronto = item.copy()
                        item_pronto['ProdutoFornecedorID'] = produto_fornecedor_id
                        # Atualiza para os valores convertidos antes de salvar
                        item_pronto['Quantidade'] = qtd_real 
                        item_pronto['PrecoCustoUnitario'] = custo_real

                        notas_processadas_nesta_sessao[num_nf]['itens_vinculados'].append(item_pronto)
                        
                        # Busca nome para exibição
                        nome_mestre = next((k for k, v in self.mapa_produtos_mestre.items() if v == produto_mestre_id), "Desconhecido")
                        
                        # Custo total não muda (R$ 60 continua R$ 60)
                        custo_total_nota = qtd_real * custo_real 
                        
                        # Exibe na tela informando a conversão se houver
                        txt_qtd = f"{qtd_real:.2f}"
                        if fator > 1:
                            txt_qtd += f" (Conv. x{int(fator)})"

                        self.tree_prontos.insert("", "end", values=(
                            num_nf, nome_fornecedor, nome_mestre, 
                            txt_qtd, f"{custo_real:.4f}", f"{custo_total_nota:.2f}"
                        ))

                    else:
                        item_pendente = {
                            'FornecedorID': fornecedor_id,
                            'FornecedorNome': nome_fornecedor,
                            'DescricaoXML': desc_xml,
                            'cProd': item['cProd'],
                            'cEAN': item['cEAN'],
                            'NCM': item['NCM']
                        }

                        if not any(p['DescricaoXML'] == desc_xml and p['FornecedorID'] == fornecedor_id for p in self.itens_xml_nao_vinculados):
                            self.itens_xml_nao_vinculados.append(item_pendente)

                            # --- PREENCHIMENTO ATUALIZADO ---
                            qtd_xml = float(item['Quantidade'])
                            custo_unit = float(item['PrecoCustoUnitario'])
                            custo_total = qtd_xml * custo_unit

                            # CORREÇÃO: Remoção do parâmetro 'iid' para evitar TclError (colisão de IDs) ao importar XMLs sequenciais
                            self.tree_vincular.insert("", "end", values=(
                                nome_fornecedor, 
                                desc_xml, 
                                item['cEAN'], 
                                f"{qtd_xml:.2f}".rstrip('0').rstrip('.'), # Qtd formatada
                                f"R$ {custo_unit:.2f}", 
                                f"R$ {custo_total:.2f}"
                            ))

            except Exception as e:
                arquivos_com_falha += 1
                logger.error(f"Falha ao processar o arquivo {caminho_xml}: {e}", exc_info=True)
                messagebox.showwarning("Aviso de Arquivo", 
                                       f"Não foi possível processar o arquivo:\n\n{os.path.basename(caminho_xml)}\n\n"
                                       f"Motivo: {e}\n\nVerifique se o arquivo não está corrompido ou se é uma NF-e de Produto válida.",
                                       parent=self.root)
        self.dados_notas_processadas = list(notas_processadas_nesta_sessao.values())
        messagebox.showinfo("Processamento Concluído", 
                            f"Leitura de XMLs concluída.\n\n"
                            f"- {len(self.itens_xml_nao_vinculados)} itens precisam de vinculação (Passo 2).\n"
                            f"- {len(self.dados_notas_processadas)} NFs foram processadas com sucesso e estão prontas para salvar (Passo 3).\n"
                            f"- {arquivos_com_falha} arquivos falharam ao ler (verifique os pop-ups de aviso).",
                            parent=self.root)

    def vincular_produto_selecionado(self):
        # ... (código idêntico ao anterior) ...
        selecionado_tree = self.tree_vincular.focus()
        produto_mestre_selecionado = self.combo_produtos_mestre.get()
        if not selecionado_tree:
            messagebox.showwarning("Aviso", "Selecione um item pendente na lista 'Itens Pendentes' (Passo 2).", parent=self.root)
            return
        if not produto_mestre_selecionado:
            messagebox.showwarning("Aviso", "Selecione um 'Produto Mestre' no menu dropdown para vincular.", parent=self.root)
            return
        # [CORREÇÃO] Busca segura pelo conteúdo visual para evitar erro de índice
        valores_visuais = self.tree_vincular.item(selecionado_tree, 'values')
        # valores = ('Fornecedor', 'Produto no XML', ...)

        # Busca na lista interna o item que corresponde ao fornecedor e descrição visual
        item_pendente = next((i for i in self.itens_xml_nao_vinculados 
                            if i['DescricaoXML'] == valores_visuais[1] 
                            and i['FornecedorNome'] == valores_visuais[0]), None)

        if not item_pendente:
            messagebox.showerror("Erro de Sincronia", "O item selecionado não foi encontrado na memória. Tente recarregar a pasta.", parent=self.root)
            return

        produto_mestre_id = self.mapa_produtos_mestre[produto_mestre_selecionado]
        

        # Pega o fator digitado
        str_fator = self.entry_fator_conversao.get().replace(',', '.')
        try:
            # [CORREÇÃO] Uso de Decimal para precisão consistente e evitar erro de tipo
            fator = Decimal(str_fator)
            if fator <= 0: raise ValueError
        except:
            messagebox.showerror("Erro", "O Fator de Conversão deve ser um número válido maior que 0 (Use ponto para decimais).", parent=self.root)
            return

        try:
            database.criar_vinculo_produto_fornecedor(
                produto_id_mestre=produto_mestre_id,
                fornecedor_id=item_pendente['FornecedorID'],
                descricao_xml=item_pendente['DescricaoXML'],
                cProd=item_pendente['cProd'],
                cEAN=item_pendente['cEAN'],
                NCM=item_pendente['NCM'],
                fator_conversao=fator # <-- Passa o fator
            )

            # Remove o objeto específico da lista e da árvore
            self.itens_xml_nao_vinculados.remove(item_pendente)
            self.tree_vincular.delete(selecionado_tree)
            messagebox.showinfo("Sucesso", 
                                "Vínculo criado!\n\nPor favor, re-importe a pasta de XMLs para processar este item.",
                                parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao criar vínculo: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível criar o vínculo.\n{e}", parent=self.root)

    def salvar_notas_processadas(self):
        if not self.dados_notas_processadas:
            messagebox.showwarning("Aviso", "Nenhuma nota fiscal foi processada ou não há itens vinculados para salvar.", parent=self.root)
            return
        if any(self.itens_xml_nao_vinculados):
             if not messagebox.askyesno("Aviso", "Você ainda possui itens pendentes de vinculação (na lista do Passo 2).\n\nDeseja salvar assim mesmo? (Apenas os itens já vinculados serão salvos)", parent=self.root):
                return
        
        sucessos = 0
        falhas = 0
        
        # Lista auxiliar para manter apenas o que falhou
        notas_remanescentes = []

        for nf in self.dados_notas_processadas:
            cabecalho = nf['cabecalho']
            itens_para_salvar = nf['itens_vinculados']
            
            if not itens_para_salvar:
                logger.warning(f"Pulando NF {cabecalho['NumeroNF']} pois não possui itens vinculados prontos para salvar.")
                # Se não tem itens vinculados, mantemos na lista para o usuário vincular
                notas_remanescentes.append(nf)
                continue
            
            try:
                sucesso_db, msg_db = database.salvar_nota_fiscal_completa(cabecalho, itens_para_salvar)
                if sucesso_db:
                    sucessos += 1
                    # Se salvou com sucesso, NÃO adicionamos à lista remanescente (removemos da memória)
                else:
                    falhas += 1
                    notas_remanescentes.append(nf) # Mantém na memória para tentar de novo
                    
                    logger.error(f"Falha ao salvar NF {cabecalho['NumeroNF']} no banco: {msg_db}")
                    if "já foi importada" in msg_db:
                        messagebox.showwarning("Aviso de Duplicidade", f"Nota Fiscal {cabecalho['NumeroNF']} não foi salva: já existe no sistema.", parent=self.root)
            except Exception as e:
                falhas += 1
                notas_remanescentes.append(nf)
                logger.error(f"Erro crítico ao tentar salvar NF {cabecalho['NumeroNF']}: {e}", exc_info=True)
        
        # Atualiza a memória principal com apenas o que sobrou
        self.dados_notas_processadas = notas_remanescentes

        messagebox.showinfo("Processamento Concluído", 
                    f"Processo de salvamento finalizado.\n\n"
                    f"Notas Salvas com Sucesso: {sucessos}\n"
                    f"Notas que Falharam ou Pendentes: {len(self.dados_notas_processadas)}",
                    parent=self.root)

        # Atualiza a interface visual
        for i in self.tree_prontos.get_children(): 
            self.tree_prontos.delete(i)
            
        # Recarrega na visualização APENAS o que sobrou na memória
        for nf in self.dados_notas_processadas:
            cabecalho = nf['cabecalho']
            for item in nf['itens_vinculados']:
                # Recalcula visualmente para exibir de novo
                nome_mestre = next((k for k, v in self.mapa_produtos_mestre.items() if v == item['ProdutoFornecedorID']), "Item Processado")
                # Nota: A lógica de exibição original usa IDs, simplificamos aqui para reexibir
                # Para uma recarga visual perfeita, idealmente reprocessamos, mas aqui limpamos o que já foi.
                pass
        
        # Se tudo foi salvo e não há pendentes de vínculo, limpa tudo
        if len(self.dados_notas_processadas) == 0 and len(self.itens_xml_nao_vinculados) == 0:
             messagebox.showinfo("Limpeza", "Todas as notas e itens foram processados com sucesso! Tela limpa.", parent=self.root)

    def criar_mestre_e_vincular(self):
        # ... (código idêntico ao anterior) ...
        selecionado_tree = self.tree_vincular.focus()
        if not selecionado_tree:
            messagebox.showwarning("Aviso", "Selecione um item pendente na lista 'Itens Pendentes' (Passo 2).", parent=self.root)
            return

        # [CORREÇÃO] Busca segura pelo conteúdo visual
        valores_visuais = self.tree_vincular.item(selecionado_tree, 'values')
        item_pendente = next((i for i in self.itens_xml_nao_vinculados 
                            if i['DescricaoXML'] == valores_visuais[1] 
                            and i['FornecedorNome'] == valores_visuais[0]), None)

        if not item_pendente:
            messagebox.showerror("Erro de Sincronia", "O item selecionado não foi encontrado na memória.", parent=self.root)
            return

        nome_novo_produto = item_pendente['DescricaoXML']
        try:
            produto_id_mestre = database.buscar_produto_mestre_por_nome(nome_novo_produto)
            produto_foi_criado = False
            if not produto_id_mestre:
                if not messagebox.askyesno("Confirmar Auto-Criação",
                                          f"O produto mestre '{nome_novo_produto}' não existe no Catálogo (Aba 1).\n\n"
                                          f"Deseja criá-lo automaticamente agora?\n"
                                          f"(Unidade: 'UN', Est. Mínimo: 0.0)",
                                          parent=self.root):
                    return
                produto_id_mestre = database.criar_produto_estoque(
                    nome=nome_novo_produto,
                    unidade="UN", 
                    estoque_min=Decimal('0.0')
                )
                if not produto_id_mestre:
                    raise Exception("Falha ao criar o produto mestre, não retornou ID.")
                produto_foi_criado = True

            # Pega o fator digitado na tela principal também
            str_fator = self.entry_fator_conversao.get().replace(',', '.')
            try:
                # [CORREÇÃO] Uso de Decimal para evitar incompatibilidade
                fator = Decimal(str_fator)
                if fator <= 0: fator = Decimal('1.0')
            except:
                fator = Decimal('1.0')

            database.criar_vinculo_produto_fornecedor(
                produto_id_mestre=produto_id_mestre,
                fornecedor_id=item_pendente['FornecedorID'],
                descricao_xml=item_pendente['DescricaoXML'],
                cProd=item_pendente['cProd'],
                cEAN=item_pendente['cEAN'],
                NCM=item_pendente['NCM'],
                fator_conversao=fator
            )

            # Remove o objeto específico da lista e da árvore
            self.itens_xml_nao_vinculados.remove(item_pendente)
            self.tree_vincular.delete(selecionado_tree)
            if produto_foi_criado:
                self.atualizar_lista_produtos()
                self.popular_combobox_produtos_mestre()
            messagebox.showinfo("Sucesso", 
                                f"Produto vinculado com sucesso!\n\n"
                                "Por favor, re-importe a pasta de XMLs para que este item apareça na lista 'Prontos para Salvar'.",
                                parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao auto-criar e vincular: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Não foi possível criar e vincular o produto.\nVerifique se o nome já existe no Catálogo Mestre com alguma variação.\n\nErro: {e}", parent=self.root)

    # ===================================================================
    # == ABA 4: LANÇAR CONTAGEM FÍSICA (Com Filtro) =====================
    # ===================================================================
    def criar_aba_contagem_estoque(self):
        # ... (código idêntico ao anterior) ...
        main_frame = ttk.Frame(self.frame_contagem)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1) 
        frame_lancamento = ttk.LabelFrame(main_frame, text="1. Lançar Itens Contados", padding="10")
        frame_lancamento.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        frame_lancamento.columnconfigure(0, weight=1)
        ttk.Label(frame_lancamento, text="Filtrar Produto:").grid(row=0, column=0, sticky="w")
        self.entry_filtro_contagem = ttk.Entry(frame_lancamento)
        self.entry_filtro_contagem.grid(row=1, column=0, sticky="ew", padx=(0, 5))
        self.entry_filtro_contagem.bind("<KeyRelease>", self.filtrar_combo_contagem)
        ttk.Label(frame_lancamento, text="Produto do Catálogo Mestre:").grid(row=2, column=0, sticky="w", pady=(5,0))
        self.combo_contagem_produtos = ttk.Combobox(frame_lancamento, state="readonly")
        self.combo_contagem_produtos.grid(row=3, column=0, sticky="ew", padx=(0, 5))
        self.combo_contagem_produtos.bind("<<ComboboxSelected>>", self.atualizar_label_unidade_contagem)
        ttk.Label(frame_lancamento, text="Quantidade:").grid(row=2, column=1, sticky="w", pady=(5,0))
        self.entry_contagem_qtd = ttk.Entry(frame_lancamento, width=10)
        self.entry_contagem_qtd.grid(row=3, column=1, sticky="w", padx=5)
        self.lbl_contagem_unidade = ttk.Label(frame_lancamento, text="UN", font=("Arial", 10, "italic"))
        self.lbl_contagem_unidade.grid(row=3, column=2, sticky="w", padx=5)
        btn_adicionar_item = ttk.Button(frame_lancamento, text="Adicionar à Lista", command=self.adicionar_item_contagem)
        btn_adicionar_item.grid(row=3, column=3, sticky="w", padx=10)
        frame_lista_lancar = ttk.LabelFrame(main_frame, text="2. Itens nesta Contagem", padding="10")
        frame_lista_lancar.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=10)
        frame_lista_lancar.rowconfigure(0, weight=1)
        frame_lista_lancar.columnconfigure(0, weight=1)
        cols_cont = ('Produto Mestre', 'Qtd Contada', 'UN')
        self.tree_contagem_atual = ttk.Treeview(frame_lista_lancar, columns=cols_cont, show='headings', selectmode='browse')
        self.tree_contagem_atual.heading('Produto Mestre', text='Produto'); self.tree_contagem_atual.column('Produto Mestre', width=200)
        self.tree_contagem_atual.heading('Qtd Contada', text='Qtd'); self.tree_contagem_atual.column('Qtd Contada', width=60, anchor='e')
        self.tree_contagem_atual.heading('UN', text='UN'); self.tree_contagem_atual.column('UN', width=40, anchor='center')
        self.tree_contagem_atual.grid(row=0, column=0, sticky="nsew")
        btn_remover_item = ttk.Button(frame_lista_lancar, text="Remover Item Selecionado da Lista", command=self.remover_item_contagem)
        btn_remover_item.grid(row=1, column=0, sticky="w", pady=(10, 0))
        frame_salvar = ttk.Frame(main_frame)
        frame_salvar.grid(row=2, column=0, sticky="nsew", padx=(0, 5))
        frame_salvar.columnconfigure(1, weight=1)
        ttk.Label(frame_salvar, text="Data da Contagem:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.date_contagem = DateEntry(frame_salvar, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_contagem.grid(row=0, column=1, sticky="w")
        self.id_funcionario_contagem = 2
        btn_salvar_contagem = ttk.Button(frame_salvar, text="Salvar Contagem Completa", command=self.salvar_contagem_completa)
        btn_salvar_contagem.grid(row=0, column=2, sticky="e", padx=20, ipady=5)
        frame_historico = ttk.LabelFrame(main_frame, text="Histórico de Contagens Realizadas", padding="10")
        frame_historico.grid(row=0, column=1, rowspan=3, sticky="nsew", pady=5)
        frame_historico.rowconfigure(0, weight=1)
        frame_historico.rowconfigure(1, weight=1)
        frame_historico.columnconfigure(0, weight=1)
        cols_hist = ('ID', 'Data Contagem', 'Responsável')
        self.tree_hist_contagens = ttk.Treeview(frame_historico, columns=cols_hist, show='headings', selectmode='browse', height=5)
        self.tree_hist_contagens.heading('ID', text='ID'); self.tree_hist_contagens.column('ID', width=40, anchor='center')
        self.tree_hist_contagens.heading('Data Contagem', text='Data'); self.tree_hist_contagens.column('Data Contagem', width=100, anchor='center')
        self.tree_hist_contagens.heading('Responsável', text='Responsável'); self.tree_hist_contagens.column('Responsável', width=150)
        self.tree_hist_contagens.grid(row=0, column=0, sticky="nsew")
        self.tree_hist_contagens.bind("<<TreeviewSelect>>", self.carregar_itens_contagem_historico)
        cols_hist_itens = ('Produto', 'Qtd Contada', 'UN')
        self.tree_hist_itens = ttk.Treeview(frame_historico, columns=cols_hist_itens, show='headings')
        self.tree_hist_itens.heading('Produto', text='Produto'); self.tree_hist_itens.column('Produto', width=200)
        self.tree_hist_itens.heading('Qtd Contada', text='Qtd'); self.tree_hist_itens.column('Qtd Contada', width=60, anchor='e')
        self.tree_hist_itens.heading('UN', text='UN'); self.tree_hist_itens.column('UN', width=40, anchor='center')
        self.tree_hist_itens.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def filtrar_combo_contagem(self, event=None):
        # ... (código idêntico ao anterior) ...
        texto = self.entry_filtro_contagem.get().lower()
        if not texto:
            self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes
            self.combo_contagem_produtos.set('')
            self.lbl_contagem_unidade.config(text="UN")
        else:
            filtrados = [nome for nome in self.lista_mestre_contagem_nomes if texto in nome.lower()]
            self.combo_contagem_produtos['values'] = filtrados
            if filtrados:
                self.combo_contagem_produtos.set(filtrados[0])
                self.atualizar_label_unidade_contagem() # [CORREÇÃO] Atualiza a unidade visualmente
                self.atualizar_label_unidade_contagem()
            else:
                self.combo_contagem_produtos.set('')
                self.lbl_contagem_unidade.config(text="UN")

    def atualizar_label_unidade_contagem(self, event=None):
        # ... (código idêntico ao anterior) ...
        produto_selecionado = self.combo_contagem_produtos.get()
        if produto_selecionado and produto_selecionado in self.mapa_produtos_mestre_contagem:
            unidade = self.mapa_produtos_mestre_contagem[produto_selecionado]['un']
            self.lbl_contagem_unidade.config(text=unidade)
        else:
            self.lbl_contagem_unidade.config(text="UN")

    def adicionar_item_contagem(self):
        # ... (código idêntico ao anterior) ...
        produto_nome = self.combo_contagem_produtos.get()
        qtd_str = self.entry_contagem_qtd.get().replace(",", ".")
        if not produto_nome or not qtd_str:
            messagebox.showwarning("Aviso", "Selecione um produto e digite a quantidade.", parent=self.root)
            return
        try:
            quantidade = Decimal(qtd_str)
        except InvalidOperation: # <-- CORREÇÃO: Exceção específica
            messagebox.showerror("Erro", "Quantidade deve ser um número.", parent=self.root)
            # Limpa o campo para evitar reenvio de dados inválidos e foca
            self.entry_contagem_qtd.delete(0, tk.END)
            self.entry_contagem_qtd.focus()
            return
        dados_produto = self.mapa_produtos_mestre_contagem[produto_nome]
        produto_id = dados_produto['id']
        unidade = dados_produto['un']
        for item in self.lista_itens_para_salvar_contagem:
            if item['ProdutoID'] == produto_id:
                messagebox.showwarning("Aviso", "Este produto já está na lista. Remova-o se quiser alterar a quantidade.", parent=self.root)
                return
        self.lista_itens_para_salvar_contagem.append({
            'ProdutoID': produto_id,
            'NomeProduto': produto_nome,
            'QuantidadeContada': quantidade,
            'Unidade': unidade
        })
        self.tree_contagem_atual.insert("", "end", values=(produto_nome, f"{quantidade:.3f}", unidade))
        self.combo_contagem_produtos.set('')
        self.entry_contagem_qtd.delete(0, tk.END)
        self.lbl_contagem_unidade.config(text="UN")
        self.entry_filtro_contagem.delete(0, tk.END) 
        self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes 
        self.entry_filtro_contagem.focus()
        
    def remover_item_contagem(self):
        # ... (código idêntico ao anterior) ...
        selecionado = self.tree_contagem_atual.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um item da lista 'Itens nesta Contagem' para remover.", parent=self.root)
            return
        dados = self.tree_contagem_atual.item(selecionado, 'values')
        nome_produto = dados[0]
        self.lista_itens_para_salvar_contagem = [
            item for item in self.lista_itens_para_salvar_contagem 
            if item['NomeProduto'] != nome_produto
        ]
        self.tree_contagem_atual.delete(selecionado)

    def salvar_contagem_completa(self):
        # ... (código idêntico ao anterior) ...
        if not self.lista_itens_para_salvar_contagem:
            messagebox.showwarning("Aviso", "Adicione pelo menos um item à lista de contagem antes de salvar.", parent=self.root)
            return
        data_contagem = self.date_contagem.get_date().strftime('%Y-%m-%d')
        funcionario_id = self.id_funcionario_contagem 
        try:
            sucesso, msg = database.salvar_contagem_estoque(
                data_contagem,
                funcionario_id,
                self.lista_itens_para_salvar_contagem
            )
            if sucesso:
                messagebox.showinfo("Sucesso", msg, parent=self.root)
                for i in self.tree_contagem_atual.get_children(): self.tree_contagem_atual.delete(i)
                self.lista_itens_para_salvar_contagem.clear()
                self.atualizar_lista_contagens_historico()
            else:
                messagebox.showerror("Erro de Banco", msg, parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao salvar contagem completa: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado: {e}", parent=self.root)

    def atualizar_lista_contagens_historico(self):
        # ... (código idêntico ao anterior) ...
        for i in self.tree_hist_contagens.get_children():
            self.tree_hist_contagens.delete(i)
        
        self.mapa_contagens_historico.clear()
        nomes_contagens = []
        
        try:
            contagens = database.listar_contagens_cabecalho()
            for c in contagens:
                data_f = c.DataContagem.strftime('%d/%m/%Y')
                nome_display = f"ID: {c.ContagemID} - {data_f} ({c.NomeCompleto})"
                
                self.tree_hist_contagens.insert("", "end", values=(c.ContagemID, data_f, c.NomeCompleto))
                
                nomes_contagens.append(nome_display)
                self.mapa_contagens_historico[nome_display] = c.ContagemID
                
        except Exception as e:
            logger.error(f"Erro ao atualizar histórico de contagens: {e}", exc_info=True)

    def carregar_itens_contagem_historico(self, event=None):
        # ... (código idêntico ao anterior) ...
        for i in self.tree_hist_itens.get_children():
            self.tree_hist_itens.delete(i)
        selecionado = self.tree_hist_contagens.focus()
        if not selecionado:
            return
        contagem_id = self.tree_hist_contagens.item(selecionado, 'values')[0]
        try:
            itens = database.buscar_itens_contagem(contagem_id)
            for item in itens:
                self.tree_hist_itens.insert("", "end", values=(item.NomeProduto, f"{item.QuantidadeContada:.3f}", item.UnidadeMedida))
        except Exception as e:
            logger.error(f"Erro ao carregar itens do histórico (ContagemID {contagem_id}): {e}", exc_info=True)

    # ===================================================================
    # == ABA 5: SUGESTÃO DE COMPRA (ATUALIZADA) =========================
    # ===================================================================
    def criar_aba_sugestao_compra(self):
        main_frame = ttk.Frame(self.frame_sugestao)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(1, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # --- Frame 1: Filtros (REESCRITO) ---
        frame_filtros = ttk.LabelFrame(main_frame, text="Parâmetros da Sugestão (Baseado em Período de Contagem)", padding="10")
        frame_filtros.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame_filtros.columnconfigure(1, weight=1)
        frame_filtros.columnconfigure(3, weight=1)

        ttk.Label(frame_filtros, text="Contagem Inicial (Ponto A):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.combo_contagem_inicio = ttk.Combobox(frame_filtros, state="readonly", width=40)
        self.combo_contagem_inicio.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        ttk.Label(frame_filtros, text="Contagem Final (Ponto B):").grid(row=0, column=2, sticky="w", padx=10, pady=5)
        self.combo_contagem_fim = ttk.Combobox(frame_filtros, state="readonly", width=40)
        self.combo_contagem_fim.grid(row=0, column=3, sticky="ew", padx=5, pady=5)

        ttk.Label(frame_filtros, text="Cobrir próximos:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        
        # --- CORREÇÃO DO BUG .pack() ---
        # Criamos um sub-frame para o spinbox e o label "meses."
        frame_spin = ttk.Frame(frame_filtros)
        frame_spin.grid(row=1, column=1, sticky="w") # .grid() para o sub-frame
        
        self.spin_meses_cobertura = ttk.Spinbox(frame_spin, from_=1, to=12, width=5)
        self.spin_meses_cobertura.set("1") 
        self.spin_meses_cobertura.pack(side=tk.LEFT, padx=5) # .pack() dentro do sub-frame
        
        ttk.Label(frame_spin, text="meses.").pack(side=tk.LEFT) # .pack() dentro do sub-frame
        # --- FIM DA CORREÇÃO ---
        
        btn_gerar_sugestao = ttk.Button(frame_filtros, text="Gerar Sugestão de Compra", command=self.gerar_sugestao_compra)
        btn_gerar_sugestao.grid(row=1, column=2, columnspan=2, sticky="e", padx=5, pady=5, ipady=5)
        # --- FIM DO FRAME DE FILTROS ---

        # --- Frame 2: Tabela de Sugestões (Mesma de antes, mas o bind foi movido) ---
        frame_resultado = ttk.LabelFrame(main_frame, text="Relatório de Posição de Estoque e Sugestão (Duplo-clique para ver histórico de compras)", padding="10")
        frame_resultado.grid(row=1, column=0, sticky="nsew")
        frame_resultado.rowconfigure(0, weight=1)
        frame_resultado.columnconfigure(0, weight=1)
        
    # [ATUALIZAÇÃO] Adicionada coluna 'Duração (Meses)'
        cols = ('Produto', 'UN', 'Estoque Atual', 'Total Comprado', 'Consumo Médio/Mês', 'Consumo Médio/Dia', 'Duração (Meses)', 'Sugestão Compra', 'Status')
        self.tree_sugestao = ttk.Treeview(frame_resultado, columns=cols, show='headings')
        for col in cols: self.tree_sugestao.heading(col, text=col)

        self.tree_sugestao.column('Produto', width=250)
        self.tree_sugestao.column('UN', width=40, anchor='center')
        self.tree_sugestao.column('Estoque Atual', width=90, anchor='e')
        self.tree_sugestao.column('Total Comprado', width=90, anchor='e')
        self.tree_sugestao.column('Consumo Médio/Mês', width=110, anchor='e')
        self.tree_sugestao.column('Consumo Médio/Dia', width=110, anchor='e')
        self.tree_sugestao.column('Duração (Meses)', width=100, anchor='center') # Nova Coluna
        self.tree_sugestao.column('Sugestão Compra', width=110, anchor='e')
        self.tree_sugestao.column('Status', width=100)

        scrollbar = ttk.Scrollbar(frame_resultado, orient="vertical", command=self.tree_sugestao.yview)
        self.tree_sugestao.configure(yscrollcommand=scrollbar.set)
        
        self.tree_sugestao.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.tree_sugestao.bind("<Double-1>", self.abrir_popup_historico_compras)

    # --- FUNÇÃO ATUALIZADA (v3 - Lógica por Período) ---
    def gerar_sugestao_compra(self):
        """Busca o relatório do banco baseado no período selecionado e calcula a sugestão."""
        try:
            # Validação robusta do Spinbox (evita erro se estiver vazio)
            valor_spin = self.spin_meses_cobertura.get().strip()
            # CORREÇÃO: Garante que, se o valor for vazio, ele seja tratado como 1
            if not valor_spin.isdigit(): # Verifica se é vazio ou não numérico
                meses_cobertura = 1
                self.spin_meses_cobertura.set("1")
            else:
                meses_cobertura = int(valor_spin)

            # Converte para Decimal para garantir precisão no cálculo com UMD
            dias_cobertura = Decimal(meses_cobertura * 30)

            str_contagem_inicio = self.combo_contagem_inicio.get()
            str_contagem_fim = self.combo_contagem_fim.get()
            
            if not str_contagem_inicio or not str_contagem_fim:
                messagebox.showwarning("Aviso", "Selecione uma Contagem Inicial (Ponto A) e uma Contagem Final (Ponto B).", parent=self.root)
                return

            contagem_id_inicio = self.mapa_contagens_historico[str_contagem_inicio]
            contagem_id_fim = self.mapa_contagens_historico[str_contagem_fim]

        except (ValueError, KeyError) as e:
            messagebox.showerror("Erro de Seleção", f"Parâmetros inválidos. Verifique suas seleções.\n{e}", parent=self.root)
            return

        for i in self.tree_sugestao.get_children():
            self.tree_sugestao.delete(i)
            
        try:
            # Chama a função corrigida do database, que já retorna Decimals prontos
            relatorio_posicao = database.gerar_sugestao_por_periodo(contagem_id_inicio, contagem_id_fim)
            self.cache_relatorio_posicao.clear()

            if not relatorio_posicao:
                messagebox.showinfo("Aviso", "Nenhum produto encontrado ou erro de processamento.", parent=self.root)
                return

            for item in relatorio_posicao:
                # Armazena no cache para o recurso de duplo-clique (histórico)
                self.cache_relatorio_posicao[item['ProdutoID']] = item

                # Extração direta dos dados já calculados no database.py
                nome = item['NomeProduto']
                un = item['Unidade']
                atual = item['EstoqueAtual']       # Já é Decimal
                umd = item['UsoMedioDiario']       # Já é Decimal
                minimo = item['EstoqueMinimo']     # Já é Decimal
                total_comprado = item['TotalComprado']
                status = item['Status']

                # Cálculo de apresentação: Consumo Mensal
                consumo_mes = umd * 30

                # Cálculo da Sugestão de Compra
                # Estoque Ideal = (Consumo Diário * Dias a Cobrir) + Estoque de Segurança
                estoque_ideal = (umd * dias_cobertura) + minimo
                sugestao_calc = estoque_ideal - atual

                # A sugestão não pode ser negativa
                sugestao_compra = max(sugestao_calc, Decimal('0.0'))

                # --- CÁLCULO DA DURAÇÃO DE ESTOQUE (Visual) ---
                if consumo_mes > 0:
                    duracao_val = atual / consumo_mes
                    if duracao_val > 120: 
                        duracao_f = "> 120 meses"
                    else:
                        duracao_f = f"{duracao_val:.1f} meses"
                else:
                    if atual > 0:
                        duracao_f = "Sem Giro" # Tem estoque mas não vendeu no período
                    else:
                        duracao_f = "---" # Zerado e sem venda

                # Formatação para string (3 casas decimais)
                atual_f = f"{atual:.3f}"
                total_comprado_f = f"{total_comprado:.3f}"
                consumo_mes_f = f"{consumo_mes:.3f}"
                umd_f = f"{umd:.3f}"
                sugestao_f = f"{sugestao_compra:.3f}"

                # Insere na Treeview
                self.tree_sugestao.insert("", "end", values=(
                    nome, un, atual_f, total_comprado_f, consumo_mes_f, umd_f, duracao_f, sugestao_f, status
                ), iid=item['ProdutoID'])

        except Exception as e:
            logger.error(f"Erro ao gerar sugestão de compra (Frontend): {e}", exc_info=True)
            messagebox.showerror("Erro de Processamento", f"Falha ao exibir relatório:\n{e}", parent=self.root)

    def popular_combos_contagem_sugestao(self):
        """Atualiza os combos da Aba 5 com os dados mais recentes da Aba 4."""
        try:
            contagens = database.listar_contagens_cabecalho()
            self.mapa_contagens_historico.clear()

            # Limpa os combos preventivamente
            self.combo_contagem_inicio.set('')
            self.combo_contagem_fim.set('')
            self.combo_contagem_inicio['values'] = []
            self.combo_contagem_fim['values'] = []

            # --- NOVA OPÇÃO ESPECIAL ---
            opcao_primeira_compra = "⏮️ DESDE A PRIMEIRA COMPRA (Histórico Completo)"
            self.mapa_contagens_historico[opcao_primeira_compra] = -1 # Código especial -1
            
            nomes_contagens = []
            
            # Adiciona as contagens físicas reais
            for c in contagens:
                data_f = c.DataContagem.strftime('%d/%m/%Y')
                nome_display = f"ID: {c.ContagemID} - {data_f} ({c.NomeCompleto})"
                nomes_contagens.append(nome_display)
                self.mapa_contagens_historico[nome_display] = c.ContagemID

            # Configura Combo Final (Apenas contagens reais, pois "Hoje" é sempre uma contagem física)
            self.combo_contagem_fim['values'] = nomes_contagens
            
            # Configura Combo Inicial (Contagens Reais + Opção Especial no topo)
            self.combo_contagem_inicio['values'] = [opcao_primeira_compra] + nomes_contagens

            # Lógica inteligente de seleção padrão
            if nomes_contagens:
                self.combo_contagem_fim.set(nomes_contagens[0])   # A mais recente (Ponto B)
                # Por padrão, sugere a opção especial se houver poucas contagens
                self.combo_contagem_inicio.set(opcao_primeira_compra)

        except Exception as e:
            logger.error(f"Erro ao popular combos de contagem (Aba 5): {e}", exc_info=True)

    def abrir_popup_historico_compras(self, event):
        selecionado = self.tree_sugestao.focus()
        if not selecionado:
            return

        try:
            # O IID foi definido como ProdutoID na inserção, mas protegemos a conversão
            produto_id = int(selecionado)
        except ValueError:
            # Se clicou em algo que não tem ID numérico
            return

        dados_produto = self.cache_relatorio_posicao.get(produto_id)

        # Proteção contra Cache Desatualizado
        if not dados_produto:
            messagebox.showwarning("Dados Desatualizados", "As informações deste produto não estão mais na memória.\nPor favor, clique em 'Gerar Sugestão' novamente.", parent=self.root)
            return

        nome_produto = dados_produto['NomeProduto']
        popup = Toplevel(self.root)
        popup.title(f"Histórico de Compras - {nome_produto}")
        popup.geometry("800x500")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        cols_hist = ('Data Compra', 'NF', 'Fornecedor', 'Qtd', 'Custo Unit.')
        tree_hist = ttk.Treeview(frame, columns=cols_hist, show='headings')

        for col in cols_hist: 
            tree_hist.heading(col, text=col)

        tree_hist.column('Data Compra', width=100, anchor='center')
        tree_hist.column('NF', width=80, anchor='center')
        tree_hist.column('Fornecedor', width=250)
        tree_hist.column('Qtd', width=80, anchor='e')
        tree_hist.column('Custo Unit.', width=100, anchor='e')

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree_hist.yview)
        tree_hist.configure(yscrollcommand=scrollbar.set)
        tree_hist.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        try:
            historico = database.buscar_historico_compras_produto(produto_id)
            if not historico:
                tree_hist.insert("", "end", values=("Nenhuma compra encontrada.", "", "", "", ""))

            for compra in historico:
                # --- CORREÇÃO DE FORMATAÇÃO DE DATA ---
                raw_date = compra.DataEmissao
                data_f = "--/--/----"

                if raw_date:
                    if hasattr(raw_date, 'strftime'):
                        data_f = raw_date.strftime('%d/%m/%Y')
                    else:
                        # Tenta converter string YYYY-MM-DD para BR
                        try:
                            # Pega os primeiros 10 chars (caso venha com hora)
                            data_str = str(raw_date)[:10] 
                            dt_obj = datetime.strptime(data_str, '%Y-%m-%d')
                            data_f = dt_obj.strftime('%d/%m/%Y')
                        except:
                            data_f = str(raw_date) # Fallback: mostra como veio

                qtd_f = f"{compra.Quantidade:.3f}"
                custo_f = f"R$ {compra.PrecoCustoUnitario:.4f}"

                tree_hist.insert("", "end", values=(
                    data_f, compra.NumeroNF, compra.NomeFantasia, qtd_f, custo_f
                ))

        except Exception as e:
            messagebox.showerror("Erro de Banco", f"Não foi possível buscar o histórico: {e}", parent=popup)

    # ===================================================================
    # == ABA 7: SOLICITAÇÕES (Transplantada do main.py) =================
    # ===================================================================
    def criar_aba_solicitacoes(self):
        main_frame = ttk.Frame(self.frame_solicitacoes)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- ESQUERDA: LISTA ---
        frame_lista = ttk.LabelFrame(main_frame, text="Solicitações Pendentes", padding="10")
        frame_lista.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))
        
        cols = ('ID', 'Solicitante', 'Tipo', 'Categoria', 'Data')
        self.tree_solicitacoes = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')
        self.tree_solicitacoes.heading('ID', text='ID'); self.tree_solicitacoes.column('ID', width=40)
        self.tree_solicitacoes.heading('Solicitante', text='Solicitante'); self.tree_solicitacoes.column('Solicitante', width=150)
        self.tree_solicitacoes.heading('Tipo', text='Tipo'); self.tree_solicitacoes.column('Tipo', width=80)
        self.tree_solicitacoes.heading('Categoria', text='Categoria'); self.tree_solicitacoes.column('Categoria', width=100)
        self.tree_solicitacoes.heading('Data', text='Data'); self.tree_solicitacoes.column('Data', width=120)
        
        self.tree_solicitacoes.pack(fill=tk.BOTH, expand=True)
        self.tree_solicitacoes.bind('<<TreeviewSelect>>', self.on_solicitacao_selecionada)
        
        ttk.Button(frame_lista, text="🔄 Atualizar Lista", command=self.carregar_solicitacoes).pack(pady=5)
        
        # --- DIREITA: DETALHES ---
        frame_detalhes = ttk.LabelFrame(main_frame, text="Detalhes & Ação", padding="10")
        frame_detalhes.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.lbl_solic_detalhes = tk.Text(frame_detalhes, height=15, width=40, wrap=tk.WORD, state='disabled', font=("Arial", 10))
        self.lbl_solic_detalhes.pack(fill=tk.X, pady=5)
        
        self.btn_ver_foto_solic = ttk.Button(frame_detalhes, text="📸 Ver Foto (Manutenção)", state='disabled', command=self.ver_foto_solicitacao)
        self.btn_ver_foto_solic.pack(pady=5, fill=tk.X)
        
        frame_botoes = ttk.Frame(frame_detalhes)
        frame_botoes.pack(pady=20, fill=tk.X)
        
        ttk.Button(frame_botoes, text="✅ Aprovar", command=self.aprovar_solicitacao).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        ttk.Button(frame_botoes, text="❌ Recusar", command=self.recusar_solicitacao).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        self.solicitacao_atual_foto = None
        self.solicitacao_atual_id = None
        self.cache_solicitacoes = {}

    def carregar_solicitacoes(self):
        for i in self.tree_solicitacoes.get_children(): self.tree_solicitacoes.delete(i)
        
        dados = database.listar_solicitacoes_pendentes()
        # Colunas SQL: 0:ID, 1:Nome, 2:Tipo, 3:Cat, 4:Desc, 5:Qtd, 6:Foto, 7:Data
        self.cache_solicitacoes = {row[0]: row for row in dados}
        
        for row in dados:
            data_fmt = row[7].strftime('%d/%m %H:%M') if row[7] else ""
            self.tree_solicitacoes.insert("", "end", values=(row[0], row[1], row[2], row[3], data_fmt))

    def on_solicitacao_selecionada(self, event):
        sel = self.tree_solicitacoes.focus()
        if not sel: return
        item = self.tree_solicitacoes.item(sel, 'values')
        s_id = int(item[0])
        self.solicitacao_atual_id = s_id
        
        dados = self.cache_solicitacoes.get(s_id)
        if not dados: return
        
        texto = f"Solicitante: {dados[1]}\n"
        texto += f"Tipo: {dados[2]} - {dados[3]}\n"
        texto += f"Data: {dados[7].strftime('%d/%m/%Y %H:%M')}\n\n"
        texto += f"DESCRIÇÃO:\n{dados[4]}\n"
        if dados[5]: texto += f"\nQuantidade: {dados[5]}"
        
        self.lbl_solic_detalhes.config(state='normal')
        self.lbl_solic_detalhes.delete("1.0", tk.END)
        self.lbl_solic_detalhes.insert("1.0", texto)
        self.lbl_solic_detalhes.config(state='disabled')
        
        if dados[2] == 'Manutencao' and dados[6]:
            self.solicitacao_atual_foto = dados[6]
            self.btn_ver_foto_solic.config(state='normal')
        else:
            self.solicitacao_atual_foto = None
            self.btn_ver_foto_solic.config(state='disabled')

    def ver_foto_solicitacao(self):
        if self.solicitacao_atual_foto and os.path.exists(self.solicitacao_atual_foto):
            file_utils.abrir_arquivo(self.solicitacao_atual_foto)
        else:
            messagebox.showerror("Erro", "Arquivo de foto não encontrado no disco.")

    def aprovar_solicitacao(self):
        if not self.solicitacao_atual_id: return
        if database.atualizar_status_solicitacao(self.solicitacao_atual_id, 'Aprovado'):
            messagebox.showinfo("Sucesso", "Solicitação Aprovada!")
            self.carregar_solicitacoes()
            self.lbl_solic_detalhes.config(state='normal'); self.lbl_solic_detalhes.delete("1.0", tk.END); self.lbl_solic_detalhes.config(state='disabled')
            self.solicitacao_atual_id = None

    def recusar_solicitacao(self):
        if not self.solicitacao_atual_id: return
        motivo = simpledialog.askstring("Recusa", "Motivo da recusa:", parent=self.root)
        if motivo:
            if database.atualizar_status_solicitacao(self.solicitacao_atual_id, 'Recusado', motivo):
                messagebox.showinfo("Sucesso", "Solicitação Recusada.")
                self.carregar_solicitacoes()
                self.solicitacao_atual_id = None

# ===================================================================
    # == ABA 6: ADMINISTRAÇÃO / RESET ===================================
    # ===================================================================
    def criar_aba_administracao(self):
        main_frame = ttk.Frame(self.frame_admin)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Título ---
        ttk.Label(main_frame, text="⚠️ Área de Gestão de Dados - Ações Destrutivas", font=("Arial", 12, "bold"), foreground="red").pack(pady=10)

        # --- Painel Dividido ---
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # --- Esquerda: Gestão de Notas Fiscais ---
        frame_nfs = ttk.LabelFrame(paned, text="Gerenciar Notas Fiscais Importadas", padding="10")
        paned.add(frame_nfs, weight=1)

        cols_nf = ('ID', 'Número', 'Fornecedor', 'Data', 'Valor', 'Itens')
        self.tree_admin_nfs = ttk.Treeview(frame_nfs, columns=cols_nf, show='headings', selectmode='extended')
        self.tree_admin_nfs.heading('ID', text='ID'); self.tree_admin_nfs.column('ID', width=30, anchor='center')
        self.tree_admin_nfs.heading('Número', text='Número'); self.tree_admin_nfs.column('Número', width=80)
        self.tree_admin_nfs.heading('Fornecedor', text='Fornecedor'); self.tree_admin_nfs.column('Fornecedor', width=120)
        self.tree_admin_nfs.heading('Data', text='Data'); self.tree_admin_nfs.column('Data', width=80, anchor='center')
        self.tree_admin_nfs.heading('Valor', text='Valor (R$)'); self.tree_admin_nfs.column('Valor', width=80, anchor='e')
        self.tree_admin_nfs.heading('Itens', text='Qtd. Itens'); self.tree_admin_nfs.column('Itens', width=60, anchor='center')
        
        sb_nf = ttk.Scrollbar(frame_nfs, orient="vertical", command=self.tree_admin_nfs.yview)
        self.tree_admin_nfs.configure(yscrollcommand=sb_nf.set)
        self.tree_admin_nfs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_nf.pack(side=tk.RIGHT, fill=tk.Y)

        btn_del_nf = ttk.Button(frame_nfs, text="🗑️ Excluir Nota(s) Selecionada(s)", command=self.excluir_nfs_selecionadas)
        btn_del_nf.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        # --- Botão de Auditoria ---
        frame_auditoria = ttk.LabelFrame(main_frame, text="Revisão de Cadastros", padding="10")
        frame_auditoria.pack(fill=tk.X, pady=10, padx=10)
        
        btn_auditoria = ttk.Button(frame_auditoria, text="🔍 Abrir Auditoria Completa de Produtos (EAN, NCM, Fator)", 
                                   command=self.abrir_tela_auditoria)
        btn_auditoria.pack(fill=tk.X, ipady=5)

        # --- Direita: Gestão de Contagens ---
        frame_cont = ttk.LabelFrame(paned, text="Gerenciar Contagens de Estoque", padding="10")
        paned.add(frame_cont, weight=1)

        cols_cont = ('ID', 'Data', 'Responsável')
        self.tree_admin_cont = ttk.Treeview(frame_cont, columns=cols_cont, show='headings', selectmode='extended')
        self.tree_admin_cont.heading('ID', text='ID'); self.tree_admin_cont.column('ID', width=40, anchor='center')
        self.tree_admin_cont.heading('Data', text='Data'); self.tree_admin_cont.column('Data', width=100, anchor='center')
        self.tree_admin_cont.heading('Responsável', text='Responsável'); self.tree_admin_cont.column('Responsável', width=150)

        sb_cont = ttk.Scrollbar(frame_cont, orient="vertical", command=self.tree_admin_cont.yview)
        self.tree_admin_cont.configure(yscrollcommand=sb_cont.set)
        self.tree_admin_cont.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_cont.pack(side=tk.RIGHT, fill=tk.Y)

        btn_del_cont = ttk.Button(frame_cont, text="🗑️ Excluir Contagem(s) Selecionada(s)", command=self.excluir_contagens_selecionadas)
        btn_del_cont.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        # --- Área de Perigo (Reset Total) ---
        frame_perigo = ttk.LabelFrame(main_frame, text="ZONA DE PERIGO", padding="10")
        frame_perigo.pack(fill=tk.X, pady=20, padx=10)

        lbl_aviso = ttk.Label(frame_perigo, text="Atenção: O botão abaixo apagará TODOS os Produtos, Vínculos, Notas Fiscais e Contagens.\nUse apenas se quiser recomeçar o estoque do zero. Os Fornecedores serão mantidos.", foreground="red", justify=tk.CENTER)
        lbl_aviso.pack(pady=5)

        style = ttk.Style()
        style.configure("Danger.TButton", foreground="red", font=("Arial", 10, "bold"))

        btn_reset_total = ttk.Button(frame_perigo, text="☢️ APAGAR TUDO E RECOMEÇAR ESTOQUE ☢️", style="Danger.TButton", command=self.resetar_sistema_estoque)
        btn_reset_total.pack(ipadx=10, ipady=10)

    def atualizar_lista_nfs_admin(self):
        for i in self.tree_admin_nfs.get_children(): self.tree_admin_nfs.delete(i)
        try:
            nfs = database.listar_notas_fiscais_entrada_completa()
            for nf in nfs:
                # nf = (NotaID, NumeroNF, NomeFantasia, DataEmissao, ValorTotalNF, QtdItens)
                data_fmt = nf[3].strftime('%d/%m/%Y') if nf[3] else "--"
                valor_fmt = f"{float(nf[4]):.2f}"
                self.tree_admin_nfs.insert("", "end", values=(nf[0], nf[1], nf[2], data_fmt, valor_fmt, nf[5]))
        except Exception as e:
            print(f"Erro lista admin NF: {e}")

    def atualizar_lista_contagens_admin(self):
        for i in self.tree_admin_cont.get_children(): self.tree_admin_cont.delete(i)
        try:
            contagens = database.listar_contagens_cabecalho()
            for c in contagens:
                data_fmt = c.DataContagem.strftime('%d/%m/%Y')
                self.tree_admin_cont.insert("", "end", values=(c.ContagemID, data_fmt, c.NomeCompleto))
        except Exception as e:
            print(f"Erro lista admin Contagem: {e}")

    def excluir_nfs_selecionadas(self):
        selecionados = self.tree_admin_nfs.selection()
        if not selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma Nota Fiscal para excluir.")
            return
        
        if not messagebox.askyesno("Confirmar Exclusão", f"Você selecionou {len(selecionados)} notas fiscais.\n\nEsta ação apagará o registro da nota e todo o histórico de entrada de estoque associado a ela.\n\nDeseja continuar?", icon='warning'):
            return

        sucessos = 0
        for item in selecionados:
            dados = self.tree_admin_nfs.item(item, 'values')
            nota_id = dados[0]
            if database.excluir_nota_fiscal_entrada(nota_id):
                sucessos += 1
        
        messagebox.showinfo("Resultado", f"{sucessos} nota(s) excluída(s) com sucesso.")
        self.atualizar_lista_nfs_admin()

    def excluir_contagens_selecionadas(self):
        selecionados = self.tree_admin_cont.selection()
        if not selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma Contagem para excluir.")
            return
        
        if not messagebox.askyesno("Confirmar Exclusão", f"Você selecionou {len(selecionados)} contagens.\n\nEsta ação apagará o registro histórico dessa contagem de estoque.\n\nDeseja continuar?", icon='warning'):
            return

        sucessos = 0
        for item in selecionados:
            dados = self.tree_admin_cont.item(item, 'values')
            cont_id = dados[0]
            if database.excluir_contagem_estoque(cont_id):
                sucessos += 1
        
        messagebox.showinfo("Resultado", f"{sucessos} contagem(ns) excluída(s) com sucesso.")
        self.atualizar_lista_contagens_admin()

    def resetar_sistema_estoque(self):
            """Executa o reset completo após dupla confirmação."""
            # Confirmação 1
            if not messagebox.askyesno("PERIGO - Reset Total", 
                                    "Tem certeza absoluta que deseja APAGAR TODO O ESTOQUE?\n\n"
                                    "Isso excluirá:\n"
                                    "- Todos os Produtos Mestre\n"
                                    "- Todos os Vínculos criados\n"
                                    "- Todo o histórico de Notas Fiscais\n"
                                    "- Todo o histórico de Contagens\n\n"
                                    "Essa ação NÃO PODE ser desfeita.", 
                                    icon='warning', default='no', parent=self.root):
                return

            # Confirmação 2 (Segurança extra)
            codigo_seguranca = simpledialog.askstring("Confirmação Final", "Para confirmar, digite 'DELETAR' (em maiúsculo) abaixo:", parent=self.root)
            
            if codigo_seguranca == "DELETAR":
                # Chama a função do banco de dados
                sucesso = database.resetar_dados_estoque_completo()
                
                if sucesso:
                    messagebox.showinfo("Sistema Resetado", "O banco de dados de estoque foi limpo com sucesso.\n\nVocê pode começar a cadastrar e vincular novamente.", parent=self.root)
                    
                    # Atualiza todas as listas para refletir o vazio
                    self.atualizar_lista_produtos()
                    self.atualizar_lista_fornecedores() 
                    self.popular_combobox_produtos_mestre()
                    self.atualizar_lista_contagens_historico()
                    self.popular_combos_contagem_sugestao()
                    self.atualizar_lista_nfs_admin()
                    self.atualizar_lista_contagens_admin()
                    
                    # Limpa as árvores de importação
                    for i in self.tree_vincular.get_children(): self.tree_vincular.delete(i)
                    for i in self.tree_prontos.get_children(): self.tree_prontos.delete(i)
                    self.itens_xml_nao_vinculados.clear()
                    self.dados_notas_processadas.clear()
                    
                else:
                    messagebox.showerror("Erro", "Falha ao resetar o banco. Verifique os logs.", parent=self.root)
            else:
                messagebox.showinfo("Cancelado", "Ação cancelada. O código de confirmação estava incorreto.", parent=self.root)

    def abrir_gestor_vinculos(self):
        """Abre uma janela para editar/excluir vínculos DE/PARA existentes."""
        popup = Toplevel(self.root)
        popup.title("Gerenciador de Vínculos de Produtos")
        popup.geometry("900x600")
        popup.transient(self.root)

        # --- Filtro ---
        frame_topo = ttk.Frame(popup, padding="10")
        frame_topo.pack(fill=tk.X)
        ttk.Label(frame_topo, text="Filtrar (XML ou Mestre):").pack(side=tk.LEFT)
        entry_filtro = ttk.Entry(frame_topo, width=30)
        entry_filtro.pack(side=tk.LEFT, padx=5)

        # --- Lista ---
        frame_lista = ttk.Frame(popup, padding="10")
        frame_lista.pack(fill=tk.BOTH, expand=True)

        cols = ('ID', 'Fornecedor', 'Descrição no XML', 'Produto Mestre Atual', 'Fator (Cx)')
        tree_vinculos = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')

        tree_vinculos.heading('ID', text='ID'); tree_vinculos.column('ID', width=40)
        tree_vinculos.heading('Fornecedor', text='Fornecedor'); tree_vinculos.column('Fornecedor', width=200)
        tree_vinculos.heading('Descrição no XML', text='Descrição no XML'); tree_vinculos.column('Descrição no XML', width=250)
        tree_vinculos.heading('Produto Mestre Atual', text='Produto Mestre (Seu Estoque)'); tree_vinculos.column('Produto Mestre Atual', width=250)
        tree_vinculos.heading('Fator (Cx)', text='Qtd/Cx'); tree_vinculos.column('Fator (Cx)', width=60, anchor='center')

        sb = ttk.Scrollbar(frame_lista, orient="vertical", command=tree_vinculos.yview)
        tree_vinculos.configure(yscrollcommand=sb.set)
        tree_vinculos.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def carregar_lista(filtro=""):
            for i in tree_vinculos.get_children(): tree_vinculos.delete(i)
            
            try:
                dados = database.listar_todos_vinculos_detalhado()
                if not dados:
                    # Se não houver dados, não faz nada (lista fica vazia mas sem erro)
                    print("Nenhum vínculo encontrado no banco.")
                    return

                for item in dados:
                    # item = (ID, Fornecedor, DescXML, NomeMestre, Fator)
                    
                    # Proteção para campos nulos
                    desc_xml = item[2] if item[2] else "Sem Descrição"
                    nome_mestre = item[3] if item[3] else "Sem Nome"
                    
                    texto_busca = f"{desc_xml} {nome_mestre}".lower()
                    
                    if not filtro or filtro.lower() in texto_busca:
                        # Tratamento seguro para o fator
                        fator_val = item[4] if item[4] is not None else 1.0
                        fator_fmt = f"{fator_val:.2f}".replace('.', ',')
                        
                        tree_vinculos.insert("", "end", values=(item[0], item[1], desc_xml, nome_mestre, fator_fmt))
            except Exception as e:
                messagebox.showerror("Erro de Carregamento", f"Falha ao ler os vínculos: {e}", parent=popup)

        entry_filtro.bind("<KeyRelease>", lambda e: carregar_lista(entry_filtro.get()))

        # --- Área de Edição ---
        frame_edit = ttk.LabelFrame(popup, text="Editar Vínculo Selecionado", padding="10")
        frame_edit.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(frame_edit, text="Alterar Produto Mestre para:").grid(row=0, column=0, sticky="w")
        combo_mestre_edit = ttk.Combobox(frame_edit, values=self.lista_mestre_produtos_nomes, width=40, state="readonly")
        combo_mestre_edit.grid(row=1, column=0, sticky="ew", padx=(0,10))

        ttk.Label(frame_edit, text="Alterar Qtd por Caixa (Fator):").grid(row=0, column=1, sticky="w")
        entry_fator_edit = ttk.Entry(frame_edit, width=10)
        entry_fator_edit.grid(row=1, column=1, sticky="w")

        def preencher_edicao(event):
            selecionado = tree_vinculos.focus()
            if not selecionado: return
            vals = tree_vinculos.item(selecionado, 'values')
            # vals = (ID, Fornecedor, DescXML, NomeMestre, Fator)

            # Tenta selecionar o mestre atual no combo
            nome_mestre_atual = vals[3]
            # Busca na lista do combo algo que contenha o nome
            for item in self.lista_mestre_produtos_nomes:
                if nome_mestre_atual in item: 
                    combo_mestre_edit.set(item)
                    break

            entry_fator_edit.delete(0, tk.END)
            entry_fator_edit.insert(0, vals[4])

        tree_vinculos.bind("<<TreeviewSelect>>", preencher_edicao)

        def salvar_alteracao():
            selecionado = tree_vinculos.focus()
            if not selecionado: return
            vinculo_id = tree_vinculos.item(selecionado, 'values')[0]

            novo_mestre_nome = combo_mestre_edit.get()
            if not novo_mestre_nome:
                messagebox.showerror("Erro", "Selecione um produto mestre.", parent=popup)
                return

            novo_mestre_id = self.mapa_produtos_mestre.get(novo_mestre_nome)

            try:
                novo_fator = Decimal(entry_fator_edit.get().replace(',', '.'))
                if novo_fator <= 0: raise ValueError
            except:
                messagebox.showerror("Erro", "Fator inválido. Use um número maior que 0.", parent=popup)
                return

            if database.atualizar_vinculo_existente(vinculo_id, novo_mestre_id, novo_fator):
                messagebox.showinfo("Sucesso", "Vínculo atualizado!", parent=popup)
                carregar_lista(entry_filtro.get())
            else:
                messagebox.showerror("Erro", "Falha ao atualizar.", parent=popup)

        def excluir_vinculo():
            selecionado = tree_vinculos.focus()
            if not selecionado: return
            vinculo_id = tree_vinculos.item(selecionado, 'values')[0]
            desc = tree_vinculos.item(selecionado, 'values')[2]

            if messagebox.askyesno("Excluir", f"Deseja excluir o vínculo para '{desc}'?\n\nNa próxima importação, o sistema pedirá para vincular novamente.", parent=popup):
                if database.excluir_vinculo_existente(vinculo_id):
                    messagebox.showinfo("Sucesso", "Vínculo excluído.", parent=popup)
                    carregar_lista(entry_filtro.get())
                else:
                    messagebox.showerror("Erro", "Falha ao excluir.", parent=popup)

        btn_salvar = ttk.Button(frame_edit, text="💾 Salvar Alterações", command=salvar_alteracao)
        btn_salvar.grid(row=1, column=2, padx=10)

        btn_excluir = ttk.Button(frame_edit, text="🗑️ Excluir Vínculo", command=excluir_vinculo)
        btn_excluir.grid(row=1, column=3, padx=10)

        carregar_lista()

    def abrir_tela_auditoria(self):
        """
        Abre a tela de Auditoria Geral para revisão de cadastros, fatores e custos.
        """
        popup = Toplevel(self.root)
        popup.title("Auditoria de Cadastro e Custos de Produtos")
        popup.geometry("1100x600")
        popup.transient(self.root)

        # --- Área de Filtro ---
        frame_topo = ttk.Frame(popup, padding="10")
        frame_topo.pack(fill=tk.X)
        
        ttk.Label(frame_topo, text="Filtrar por Nome/Código:").pack(side=tk.LEFT)
        entry_filtro = ttk.Entry(frame_topo, width=40)
        entry_filtro.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(frame_topo, text="(Dica: Dê duplo clique na linha para editar)", font=("Arial", 9, "italic"), foreground="gray").pack(side=tk.LEFT, padx=15)

        # --- Configuração da Tabela ---
        # Colunas atualizadas para incluir o Custo
        cols = ('ID', 'Produto Mestre', 'Descrição XML', 'Fornecedor', 'EAN', 'NCM', 'Fator', 'Último Custo')
        tree = ttk.Treeview(popup, columns=cols, show='headings', selectmode='browse')
        
        # Cabeçalhos
        for col in cols: tree.heading(col, text=col)
        
        # Larguras das Colunas
        tree.column('ID', width=40, anchor='center')
        tree.column('Produto Mestre', width=200)
        tree.column('Descrição XML', width=250)
        tree.column('Fornecedor', width=150)
        tree.column('EAN', width=100, anchor='center')
        tree.column('NCM', width=80, anchor='center')
        tree.column('Fator', width=60, anchor='center')
        tree.column('Último Custo', width=100, anchor='e') # Alinhado à direita
        
        # Barra de Rolagem
        scrollbar = ttk.Scrollbar(popup, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Variável para cache dos dados (para filtro rápido)
        dados_completo = []

        # --- Função Interna: Carregar Dados ---
        def carregar(filtro=""):
            for i in tree.get_children(): tree.delete(i)
            
            # Chama o banco apenas se a lista estiver vazia (primeira carga) ou se for recarga forçada
            # Mas aqui simplificamos chamando sempre que não for filtro local
            dados = database.listar_auditoria_produtos()
            dados_completo[:] = dados 
            
            for row in dados:
                # row: 0:ID, 1:Mestre, 2:XML, 3:EAN, 4:NCM, 5:Forn, 6:Fator, 7:Custo
                # Monta string de busca
                texto_busca = f"{row[1]} {row[2]} {row[3]} {row[5]}".lower()
                
                if not filtro or filtro.lower() in texto_busca:
                    # Formata o custo para R$
                    custo_val = row[7] if row[7] is not None else 0.0
                    custo_fmt = f"R$ {float(custo_val):.2f}".replace('.', ',')
                    
                    # Formata o Fator
                    fator_val = row[6] if row[6] is not None else 1.0
                    fator_fmt = f"{float(fator_val):.4f}".rstrip('0').rstrip('.')

                    tree.insert("", "end", values=(
                        row[0], # ID Vinculo
                        row[1], # Mestre
                        row[2], # XML
                        row[5], # Fornecedor
                        row[3], # EAN
                        row[4], # NCM
                        fator_fmt, # Fator
                        custo_fmt  # Custo Formatado
                    ))

        # Bind do Filtro
        entry_filtro.bind("<KeyRelease>", lambda e: carregar(entry_filtro.get()))

        # --- Função Interna: Editar Item (Duplo Clique) ---
        def editar_selecionado(event):
            sel = tree.focus()
            if not sel: return
            vals = tree.item(sel, 'values')
            vinculo_id = vals[0]
            nome_produto = vals[1]

            # Janela de Edição Rápida
            edit_win = Toplevel(popup)
            edit_win.title(f"Editando: {nome_produto}")
            edit_win.geometry("450x520")
            edit_win.transient(popup) # Fica na frente da auditoria
            
            frame = ttk.Frame(edit_win, padding="20")
            frame.pack(fill="both", expand=True)

            # Campos de Edição
            ttk.Label(frame, text="EAN (Código de Barras):").pack(anchor="w")
            ent_ean = ttk.Entry(frame); ent_ean.pack(fill="x", pady=5)
            # Remove 'None' se vier do banco
            ean_val = vals[4] if vals[4] != 'None' else ''
            ent_ean.insert(0, ean_val)

            ttk.Label(frame, text="NCM (Classificação Fiscal):").pack(anchor="w")
            ent_ncm = ttk.Entry(frame); ent_ncm.pack(fill="x", pady=5)
            ncm_val = vals[5] if vals[5] != 'None' else ''
            ent_ncm.insert(0, ncm_val)

            ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=15)

            ttk.Label(frame, text="Fator de Conversão (Itens p/ Cx):", font=("Arial", 9, "bold")).pack(anchor="w")
            ttk.Label(frame, text="Ex: Se compra caixa com 12, coloque 12.", font=("Arial", 8), foreground="gray").pack(anchor="w")
            ent_fator = ttk.Entry(frame); ent_fator.pack(fill="x", pady=5)
            ent_fator.insert(0, vals[6])

            ttk.Label(frame, text="Último Preço de Custo (Unitário no XML):", font=("Arial", 9, "bold")).pack(anchor="w", pady=(10, 0))
            ttk.Label(frame, text="* Alterar aqui corrige o histórico da última nota.", font=("Arial", 8), foreground="red").pack(anchor="w")
            
            ent_custo = ttk.Entry(frame)
            ent_custo.pack(fill="x", pady=5)
            # Limpa formatação R$ para edição
            custo_limpo = vals[7].replace("R$ ", "").strip()
            ent_custo.insert(0, custo_limpo)

            def salvar():
                try:
                    # Tratamento de vírgula para ponto
                    fator = float(ent_fator.get().replace(',', '.'))
                    custo = float(ent_custo.get().replace(',', '.'))
                    
                    if fator <= 0:
                        messagebox.showerror("Erro", "O Fator deve ser maior que 0.")
                        return

                    # Chama o banco
                    sucesso = database.atualizar_dados_auditoria(
                        vinculo_id, 
                        ent_ean.get(), 
                        ent_ncm.get(), 
                        fator,
                        custo
                    )

                    if sucesso:
                        messagebox.showinfo("Sucesso", "Cadastro atualizado!", parent=edit_win)
                        edit_win.destroy()
                        # Recarrega a lista mantendo o filtro atual
                        carregar(entry_filtro.get())
                    else:
                        messagebox.showerror("Erro", "Falha ao salvar no banco de dados.", parent=edit_win)

                except ValueError:
                    messagebox.showerror("Erro de Formato", "Fator e Custo devem ser números válidos.", parent=edit_win)

            # Botão Salvar
            btn_salvar = ttk.Button(frame, text="💾 Salvar Alterações", command=salvar)
            btn_salvar.pack(pady=20, fill="x", ipady=5)

            def excluir():
                # Pede confirmação antes de deletar
                if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja EXCLUIR definitivamente o cadastro ID {vinculo_id}?\n\nIsso não pode ser desfeito.", parent=edit_win):
                    sucesso, msg = database.excluir_vinculo_auditoria(vinculo_id)
                    if sucesso:
                        messagebox.showinfo("Sucesso", msg, parent=edit_win)
                        edit_win.destroy()
                        carregar(entry_filtro.get()) # Recarrega a lista
                    else:
                        messagebox.showerror("Ação Bloqueada", msg, parent=edit_win)

            # Botão Excluir
            btn_excluir = ttk.Button(frame, text="🗑️ Excluir Cadastro", command=excluir)
            btn_excluir.pack(pady=(0, 10), fill="x", ipady=5)

        # Bind do Duplo Clique
        tree.bind("<Double-1>", editar_selecionado)
        
        # Carga Inicial
        carregar()    

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoEstoque(root)
    root.mainloop()

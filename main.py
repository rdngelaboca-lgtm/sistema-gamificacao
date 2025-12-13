# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING ===================================
# ==============================================================================
import logging
import logging.handlers
import sys
import os # Necessário para criar a pasta de logs

# --- Configurações ---
LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs' # Nome da pasta onde os logs serão salvos
LOG_LEVEL = logging.INFO # Nível mínimo para registrar (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024 # Tamanho máximo de cada arquivo de log (10 MB)
LOG_BACKUP_COUNT = 5 # Quantos arquivos de log antigos manter

# --- Cria a pasta de logs se não existir ---
log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        print(f"Pasta de logs criada em: {log_dir}") # Print inicial para confirmar criação
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        # Se não conseguir criar a pasta, tenta logar no diretório atual
        log_dir = os.path.dirname(__file__)

log_filepath = os.path.join(log_dir, LOG_FILENAME)

# --- Configuração do Handler de Arquivo Rotativo ---
# Rotaciona o log quando atinge LOG_MAX_BYTES, mantendo LOG_BACKUP_COUNT arquivos antigos
file_handler = logging.handlers.RotatingFileHandler(
    log_filepath, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
)
file_handler.setLevel(LOG_LEVEL)
file_formatter = logging.Formatter(LOG_FORMAT)
file_handler.setFormatter(file_formatter)

# --- Configuração do Handler do Console ---
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL) # Pode ser diferente do arquivo se quiser (ex: logging.DEBUG)
console_formatter = logging.Formatter(LOG_FORMAT)
console_handler.setFormatter(console_formatter)

# --- Configuração do Logger Raiz ---
# Limpa handlers existentes para evitar duplicação em recargas
logging.getLogger('').handlers = []
# Adiciona os novos handlers
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[file_handler, console_handler])

# Obtém um logger específico para este módulo
logger = logging.getLogger(__name__)

logger.info(f"*** Logging configurado para o módulo: {__name__} ***")
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================


import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
import database
import notificador_telegram
from PIL import Image, ImageTk
import os
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta
from tkcalendar import DateEntry
import config
import file_utils
import urllib.parse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import adicionar_pontos_ao_saldo
import threading


class App:
    def __init__(self, root):
        
        self.root = root
        self.root.title("Sistema de Gamificação - Gerenciador")
        self.root.geometry("1200x800")

        self.dados_entregas, self.dados_funcionarios, self.dados_tarefas = {}, {}, {}
        self.dados_funcionarios_relatorio = {}
        self.tarefa_selecionada_para_edicao = None

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        self.frame_dashboard = ttk.Frame(self.notebook)
        self.frame_funcionarios = ttk.Frame(self.notebook)
        self.frame_grupos = ttk.Frame(self.notebook)
        self.frame_tarefas = ttk.Frame(self.notebook)
        self.frame_atribuicoes = ttk.Frame(self.notebook)
        self.frame_validacao = ttk.Frame(self.notebook)
        self.frame_ranking = ttk.Frame(self.notebook)
        self.frame_relatorios = ttk.Frame(self.notebook)
        self.frame_feedbacks = ttk.Frame(self.notebook)
        self.frame_agenda = ttk.Frame(self.notebook)
        self.frame_loja = ttk.Frame(self.notebook)
        self.frame_metas = ttk.Frame(self.notebook, padding="10")
        self.frame_conquistas = ttk.Frame(self.notebook, padding="10")
        self.frame_consulta_nf = ttk.Frame(self.notebook, padding="10")

        self.notebook.add(self.frame_dashboard, text='Dashboard')
        self.notebook.add(self.frame_funcionarios, text='Gerenciar Funcionários')
        self.notebook.add(self.frame_grupos, text='Gerenciar Grupos')
        self.notebook.add(self.frame_tarefas, text='Catálogo de Tarefas')
        self.notebook.add(self.frame_atribuicoes, text='Atribuir Tarefas')
        self.notebook.add(self.frame_validacao, text='Validar Entregas')
        self.notebook.add(self.frame_ranking, text='Ranking')
        self.notebook.add(self.frame_relatorios, text='Relatórios')
        self.notebook.add(self.frame_feedbacks, text='Feedbacks')
        self.notebook.add(self.frame_agenda, text='Agenda Semanal')
        self.notebook.add(self.frame_loja, text='Loja e Resgates')
        self.notebook.add(self.frame_metas, text='Gestão de Metas')
        self.notebook.add(self.frame_conquistas, text='Gerenciar Conquistas')
        self.notebook.add(self.frame_consulta_nf, text='Consultar NFs')

        self.criar_aba_dashboard()
        self.criar_aba_funcionarios()
        self.criar_aba_grupos()
        self.criar_aba_tarefas()
        self.criar_aba_atribuicoes()
        self.criar_aba_validacao()
        self.criar_aba_ranking()
        self.criar_aba_relatorios()
        self.criar_aba_feedbacks()
        self.criar_aba_agenda()
        self.criar_aba_loja()
        self.criar_aba_metas()
        self.criar_aba_conquistas()
        self.criar_aba_consulta_nf()

    # Em main.py, DENTRO da classe App, adicione esta função completa:
    def criar_aba_conquistas(self):
        """Cria a interface para gerenciar os modelos de conquistas."""
        main_frame = ttk.Frame(self.frame_conquistas)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1) # Coluna do formulário cresce mais
        main_frame.rowconfigure(0, weight=1)    # Linha principal cresce

        # --- PAINEL ESQUERDO: LISTA DE CONQUISTAS ---
        frame_lista = ttk.LabelFrame(main_frame, text="Modelos de Conquistas", padding="10")
        frame_lista.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame_lista.rowconfigure(0, weight=1)
        frame_lista.columnconfigure(0, weight=1)

        cols = ('ID', 'Ícone', 'Nome')
        self.tree_conquistas = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')
        self.tree_conquistas.heading('ID', text='ID'); self.tree_conquistas.column('ID', width=40, anchor='center')
        self.tree_conquistas.heading('Ícone', text='Ícone'); self.tree_conquistas.column('Ícone', width=40, anchor='center')
        self.tree_conquistas.heading('Nome', text='Nome da Conquista'); self.tree_conquistas.column('Nome', width=250)
        self.tree_conquistas.grid(row=0, column=0, sticky="nsew")
        self.tree_conquistas.bind('<<TreeviewSelect>>', self.selecionar_conquista_para_edicao)

        scrollbar_lista = ttk.Scrollbar(frame_lista, orient="vertical", command=self.tree_conquistas.yview)
        self.tree_conquistas.configure(yscrollcommand=scrollbar_lista.set)
        scrollbar_lista.grid(row=0, column=1, sticky="ns")

        # --- PAINEL DIREITO: FORMULÁRIO ---
        frame_formulario = ttk.LabelFrame(main_frame, text="Criar ou Editar Conquista", padding="15")
        frame_formulario.grid(row=0, column=1, sticky="nsew")
        frame_formulario.columnconfigure(1, weight=1) # Coluna dos inputs cresce

        ttk.Label(frame_formulario, text="Nome:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.entry_conquista_nome = ttk.Entry(frame_formulario, width=40)
        self.entry_conquista_nome.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=3)

        ttk.Label(frame_formulario, text="Ícone (Emoji):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        self.entry_conquista_icone = ttk.Entry(frame_formulario, width=10)
        self.entry_conquista_icone.grid(row=1, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(frame_formulario, text="Descrição:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=3)
        self.text_conquista_descricao = tk.Text(frame_formulario, height=3, width=40)
        self.text_conquista_descricao.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=3)

        ttk.Label(frame_formulario, text="Tipo de Critério:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=3)
        # [CORREÇÃO] Expondo todos os critérios suportados pelo database.py
        self.combo_conquista_criterio_tipo = ttk.Combobox(frame_formulario,
                                                        values=[
                                                            'total_tarefas_aprovadas',
                                                            'tarefas_aprovadas_periodo',
                                                            'sequencia_dias_tarefas',
                                                            'tarefas_grupo_competitivo_aceitas',
                                                            'total_comunicados_cientes',
                                                            'sequencia_feedback_diario'
                                                        ],
                                                        state="readonly")
        self.combo_conquista_criterio_tipo.grid(row=3, column=1, sticky=tk.EW, padx=5, pady=3)
        self.combo_conquista_criterio_tipo.set('total_tarefas_aprovadas') # Padrão

        ttk.Label(frame_formulario, text="Valor do Critério:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=3)
        self.entry_conquista_criterio_valor = ttk.Entry(frame_formulario, width=10)
        self.entry_conquista_criterio_valor.grid(row=4, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(frame_formulario, text="Pontos Bônus:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=3)
        self.entry_conquista_pontos_bonus = ttk.Entry(frame_formulario, width=10)
        self.entry_conquista_pontos_bonus.grid(row=5, column=1, sticky=tk.W, padx=5, pady=3)
        self.entry_conquista_pontos_bonus.insert(0, "0") # Padrão é 0

        # Frame para os botões do formulário
        frame_botoes_form = ttk.Frame(frame_formulario)
        frame_botoes_form.grid(row=6, column=1, sticky=tk.E, pady=20, padx=5)

        self.btn_salvar_conquista = ttk.Button(frame_botoes_form, text="Criar Conquista", command=self.salvar_conquista)
        self.btn_salvar_conquista.pack(side=tk.LEFT)

        self.btn_limpar_form_conquista = ttk.Button(frame_botoes_form, text="Limpar", command=self.limpar_formulario_conquista)
        self.btn_limpar_form_conquista.pack(side=tk.LEFT, padx=10)

        # Botão Excluir (fora do frame do formulário, embaixo da lista)
        self.btn_excluir_conquista = ttk.Button(frame_lista, text="Excluir Conquista Selecionada", command=self.excluir_conquista_selecionada)
        self.btn_excluir_conquista.grid(row=1, column=0, pady=10)

        self.conquista_selecionada_para_edicao = None # Guarda o ID da conquista selecionada
        self.atualizar_lista_conquistas() # Carrega a lista ao iniciar

    # Em main.py, DENTRO da classe App, adicione estas funções:

    def atualizar_lista_conquistas(self):
        """Limpa a Treeview e recarrega os modelos de conquistas do banco."""
        try: # <--- ADICIONADO TRY
            for i in self.tree_conquistas.get_children():
                self.tree_conquistas.delete(i)
            conquistas = database.listar_modelos_conquistas() # Pode falhar
            for conq in conquistas:
                self.tree_conquistas.insert("", "end", values=(conq.ConquistaID, conq.Icone, conq.Nome))
            self.limpar_formulario_conquista()
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao atualizar lista de conquistas: {e}") # Loga o erro completo
            messagebox.showerror("Erro de Banco", f"Não foi possível carregar os modelos de conquistas:\n{e}", parent=self.root) # Informa o usuário

    def selecionar_conquista_para_edicao(self, event):
        """Preenche o formulário com os dados da conquista selecionada na lista."""
        try: # <--- ADICIONADO TRY
            selecionado = self.tree_conquistas.focus()
            if not selecionado: return
            dados = self.tree_conquistas.item(selecionado, 'values')
            conquista_id = dados[0]
            conquistas_completas = database.listar_modelos_conquistas() # Pode falhar
            conquista_completa = next((c for c in conquistas_completas if c.ConquistaID == int(conquista_id)), None) # int() pode falhar

            if conquista_completa:
                self.limpar_formulario_conquista()
                self.conquista_selecionada_para_edicao = conquista_id
                self.entry_conquista_nome.insert(0, conquista_completa.Nome)
                self.entry_conquista_icone.insert(0, conquista_completa.Icone)
                self.text_conquista_descricao.insert("1.0", conquista_completa.Descricao)
                self.combo_conquista_criterio_tipo.set(conquista_completa.CriterioTipo)
                self.entry_conquista_criterio_valor.insert(0, conquista_completa.CriterioValor)
                self.entry_conquista_pontos_bonus.insert(0, conquista_completa.PontosBonus)
                self.btn_salvar_conquista.config(text="Salvar Alterações")
        except ValueError as e: # <--- ADICIONADO EXCEPT ESPECÍFICO
             logger.error(f"Erro de formato ao selecionar conquista: {e}")
             messagebox.showerror("Erro de Formato", f"O ID da conquista '{conquista_id}' não é válido.", parent=self.root)
        except Exception as e: # <--- ADICIONADO EXCEPT GENÉRICO
            logger.exception(f"Erro ao selecionar conquista para edição: {e}")
            messagebox.showerror("Erro", f"Não foi possível carregar os detalhes da conquista:\n{e}", parent=self.root)

    def limpar_formulario_conquista(self):
        """Limpa todos os campos do formulário e reseta o estado de edição."""
        self.entry_conquista_nome.delete(0, tk.END)
        self.entry_conquista_icone.delete(0, tk.END)
        self.text_conquista_descricao.delete("1.0", tk.END)
        self.combo_conquista_criterio_tipo.set('total_tarefas_aprovadas') # Volta ao padrão
        self.entry_conquista_criterio_valor.delete(0, tk.END)
        self.entry_conquista_pontos_bonus.delete(0, tk.END); self.entry_conquista_pontos_bonus.insert(0, "0") # Volta a 0

        self.conquista_selecionada_para_edicao = None # Reseta o ID de edição
        self.btn_salvar_conquista.config(text="Criar Conquista") # Volta o texto do botão
        self.tree_conquistas.selection_remove(self.tree_conquistas.selection()) # Remove seleção da lista

    def salvar_conquista(self):
        """Coleta dados do formulário, valida e chama a função apropriada do banco."""
        # Validações básicas (fora do try)
        nome = self.entry_conquista_nome.get()
        icone = self.entry_conquista_icone.get()
        descricao = self.text_conquista_descricao.get("1.0", tk.END).strip()
        criterio_tipo = self.combo_conquista_criterio_tipo.get()
        criterio_valor_str = self.entry_conquista_criterio_valor.get()
        pontos_bonus_str = self.entry_conquista_pontos_bonus.get()

        if not all([nome, icone, descricao, criterio_tipo, criterio_valor_str, pontos_bonus_str]):
            messagebox.showerror("Erro", "Todos os campos são obrigatórios.", parent=self.root) # Adicionado parent
            return

        try: # <--- ADICIONADO TRY (para conversão e banco)
            # Conversões que podem falhar
            criterio_valor = int(criterio_valor_str)
            pontos_bonus = int(pontos_bonus_str)
            if criterio_valor <= 0 or pontos_bonus < 0: raise ValueError("Valor inválido")

            # Chamadas de banco que podem falhar
            if self.conquista_selecionada_para_edicao:
                sucesso = database.atualizar_conquista(
                    self.conquista_selecionada_para_edicao, nome, descricao, icone,
                    criterio_tipo, criterio_valor, pontos_bonus
                )
                if sucesso: messagebox.showinfo("Sucesso", "Conquista atualizada!", parent=self.root) # Adicionado parent
                else: messagebox.showerror("Erro", "Falha ao atualizar a conquista no banco.", parent=self.root) # Adicionado parent
            else:
                sucesso = database.criar_conquista(
                    nome, descricao, icone, criterio_tipo, criterio_valor, pontos_bonus
                )
                if sucesso: messagebox.showinfo("Sucesso", "Conquista criada!", parent=self.root) # Adicionado parent
                else: messagebox.showerror("Erro", "Falha ao criar a conquista no banco.", parent=self.root) # Adicionado parent

            if sucesso:
                self.atualizar_lista_conquistas()

        except ValueError: # <--- ADICIONADO EXCEPT ESPECÍFICO
            logger.error(f"Erro de formato em salvar_conquista: Valor Critério='{criterio_valor_str}', Pontos Bônus='{pontos_bonus_str}'")
            messagebox.showerror("Erro de Formato", "Valor do Critério e Pontos Bônus devem ser números inteiros (Critério > 0, Bônus >= 0).", parent=self.root) # Adicionado parent
        except Exception as e: # <--- ADICIONADO EXCEPT GENÉRICO
            logger.exception(f"Erro inesperado em salvar_conquista: {e}")
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao salvar a conquista:\n{e}", parent=self.root) # Adicionado parent

    def excluir_conquista_selecionada(self):
        """Exclui a conquista selecionada após confirmação."""
        if not self.conquista_selecionada_para_edicao:
             messagebox.showwarning("Aviso", "Selecione uma conquista da lista para excluir.", parent=self.root) # Adicionado parent
             return

        conquista_id = self.conquista_selecionada_para_edicao
        nome_conquista = self.entry_conquista_nome.get()

        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir a conquista '{nome_conquista}'?\n\nIsso também removerá a conquista de todos os funcionários que a ganharam.", parent=self.root): # Adicionado parent
            try: # <--- ADICIONADO TRY
                sucesso = database.excluir_conquista(conquista_id) # Pode falhar
                if sucesso:
                    messagebox.showinfo("Sucesso", "Conquista excluída.", parent=self.root) # Adicionado parent
                    self.atualizar_lista_conquistas()
                else:
                    messagebox.showerror("Erro", "Falha ao excluir a conquista do banco.", parent=self.root) # Adicionado parent
            except Exception as e: # <--- ADICIONADO EXCEPT
                logger.exception(f"Erro inesperado em excluir_conquista_selecionada: {e}")
                messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao excluir a conquista:\n{e}", parent=self.root) # Adicionado parent


        # --- INÍCIO: Funções da Aba "Consultar NFs" ---

    def criar_aba_consulta_nf(self):
        """Cria a interface para consultar o histórico de Notas Fiscais."""
        main_frame = ttk.Frame(self.frame_consulta_nf)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1) # Linha da Treeview expande

        # --- Frame de Filtros ---
        frame_filtros = ttk.LabelFrame(main_frame, text="Filtros de Busca", padding="10")
        frame_filtros.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(frame_filtros, text="De:").grid(row=0, column=0, padx=(0, 5), pady=5)
        self.nf_date_inicio = DateEntry(frame_filtros, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.nf_date_inicio.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame_filtros, text="Até:").grid(row=0, column=2, padx=(10, 5), pady=5)
        self.nf_date_fim = DateEntry(frame_filtros, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.nf_date_fim.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(frame_filtros, text="Funcionário:").grid(row=0, column=4, padx=(10, 5), pady=5)
        self.nf_combo_funcionarios = ttk.Combobox(frame_filtros, state="readonly", width=30)
        self.nf_combo_funcionarios.grid(row=0, column=5, padx=5, pady=5)

        ttk.Label(frame_filtros, text="Status:").grid(row=0, column=6, padx=(10, 5), pady=5)
        self.nf_combo_status = ttk.Combobox(frame_filtros, state="readonly", values=["Todos", "Pendente", "Processada"])
        self.nf_combo_status.grid(row=0, column=7, padx=5, pady=5)
        self.nf_combo_status.set("Todos")

        btn_buscar = ttk.Button(frame_filtros, text="Buscar", command=self.buscar_historico_nfs)
        btn_buscar.grid(row=0, column=8, padx=(10, 5), pady=5)
        btn_limpar = ttk.Button(frame_filtros, text="Limpar", command=self.limpar_filtros_nf)
        btn_limpar.grid(row=0, column=9, padx=5, pady=5)

        # --- Frame da Lista (Treeview) ---
        frame_lista = ttk.LabelFrame(main_frame, text="Histórico de Notas Fiscais Recebidas", padding="10")
        frame_lista.grid(row=1, column=0, sticky="nsew")
        frame_lista.rowconfigure(0, weight=1)
        frame_lista.columnconfigure(0, weight=1)

        cols_nf = ('ID', 'Data/Hora', 'Funcionário', 'Status', 'Caminho')
        self.tree_consulta_nf = ttk.Treeview(frame_lista, columns=cols_nf, show='headings', selectmode='browse')
        self.tree_consulta_nf.heading('ID', text='ID'); self.tree_consulta_nf.column('ID', width=50, anchor='center')
        self.tree_consulta_nf.heading('Data/Hora', text='Data/Hora'); self.tree_consulta_nf.column('Data/Hora', width=150, anchor='center')
        self.tree_consulta_nf.heading('Funcionário', text='Funcionário'); self.tree_consulta_nf.column('Funcionário', width=250)
        self.tree_consulta_nf.heading('Status', text='Status'); self.tree_consulta_nf.column('Status', width=100, anchor='center')
        self.tree_consulta_nf.heading('Caminho', text='Caminho'); self.tree_consulta_nf.column('Caminho', width=0, stretch=tk.NO) # Oculta

        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.tree_consulta_nf.yview)
        self.tree_consulta_nf.configure(yscrollcommand=scrollbar.set)
        self.tree_consulta_nf.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # --- Frame de Ações ---
        frame_acoes = ttk.Frame(frame_lista)
        frame_acoes.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        btn_ver_foto = ttk.Button(frame_acoes, text="Ver Foto da NF Selecionada", command=self.ver_foto_nf_selecionada)
        btn_ver_foto.pack(side=tk.LEFT)
        btn_recriar_botoes = ttk.Button(frame_acoes, text="Recriar Ações no Telegram", command=self.recriar_botoes_nf_telegram)
        btn_recriar_botoes.pack(side=tk.LEFT, padx=10)

        # Carrega os dados iniciais
        self.carregar_filtros_nf()
        self.buscar_historico_nfs()

    def carregar_filtros_nf(self):
        """Carrega a lista de funcionários para o combobox de filtro de NFs."""
        # Reutiliza o dicionário já carregado pela aba de relatórios
        if not hasattr(self, 'dados_funcionarios_relatorio') or not self.dados_funcionarios_relatorio:
            funcionarios = database.listar_funcionarios()
            self.dados_funcionarios_relatorio = {f"{f.NomeCompleto} (ID: {f.FuncionarioID})": f.FuncionarioID for f in funcionarios}

        nomes_para_combobox = ["Todos"] + list(self.dados_funcionarios_relatorio.keys())
        self.nf_combo_funcionarios['values'] = nomes_para_combobox
        self.nf_combo_funcionarios.set("Todos")
        # Define datas padrão (últimos 30 dias)
        self.nf_date_fim.set_date(datetime.now())
        self.nf_date_inicio.set_date(datetime.now() - timedelta(days=30))

    def limpar_filtros_nf(self):
        """Limpa os filtros da aba de NFs e busca todos os registros."""
        self.nf_combo_funcionarios.set("Todos")
        self.nf_combo_status.set("Todos")
        self.nf_date_fim.set_date(datetime.now())
        self.nf_date_inicio.set_date(datetime.now() - timedelta(days=30))
        self.buscar_historico_nfs()

    def buscar_historico_nfs(self):
        """Executa a busca no banco com base nos filtros e preenche a treeview."""
        for i in self.tree_consulta_nf.get_children():
            self.tree_consulta_nf.delete(i)

        data_inicio = self.nf_date_inicio.get_date()
        data_fim = self.nf_date_fim.get_date()

        nome_selecionado = self.nf_combo_funcionarios.get()
        func_id = self.dados_funcionarios_relatorio.get(nome_selecionado) if nome_selecionado != "Todos" else None

        status = self.nf_combo_status.get()

        historico = database.buscar_notas_fiscais_historico(data_inicio, data_fim, func_id, status)

        for item in historico:
            data_f = item.DataRecebimento.strftime("%d/%m/%Y %H:%M")
            self.tree_consulta_nf.insert("", "end", values=(
                item.NotaFiscalID, data_f, item.NomeCompleto, item.Status, item.PathFoto or ""
            ))

    def ver_foto_nf_selecionada(self):
        """Abre o arquivo de foto da NF selecionada."""
        selecionado = self.tree_consulta_nf.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione uma NF na lista para ver a foto.")
            return

        dados = self.tree_consulta_nf.item(selecionado, 'values')
        path_foto = dados[4] # Coluna 'Caminho'

        if not path_foto:
            messagebox.showerror("Erro", "O download desta foto ainda não foi processado pelo servidor (PathFoto está NULO).")
            return

        if not os.path.exists(path_foto):
            messagebox.showerror("Erro de Arquivo", f"O arquivo da foto não foi encontrado no servidor no caminho:\n{path_foto}")
            return

        try:
            file_utils.abrir_arquivo(path_foto)
        except Exception as e:
            messagebox.showerror("Erro ao Abrir", f"Não foi possível abrir o arquivo de imagem:\n{e}")

    def recriar_botoes_nf_telegram(self):
        """
        Busca os dados da NF selecionada e re-envia a foto e os botões
        para o grupo de gestores, caso a mensagem original tenha sido perdida.
        """
        selecionado = self.tree_consulta_nf.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione uma NF na lista para recriar as ações.")
            return

        nota_fiscal_id = self.tree_consulta_nf.item(selecionado, 'values')[0]

        if not messagebox.askyesno("Confirmar", f"Deseja reenviar a foto e os botões de ação para a NF ID: {nota_fiscal_id} no grupo de Gestores?"):
            return

        try:
            dados_nf = database.buscar_nota_fiscal(nota_fiscal_id)
            if not dados_nf:
                messagebox.showerror("Erro", "Não foi possível encontrar os dados desta NF no banco.")
                return

            # Prepara a mesma mensagem do bot
            legenda_gestor = (
                f"🧾 **Nota Fiscal (Reenviada)** 🧾\n\n"
                f"👤 **Enviada por:** {dados_nf.NomeFuncionario}\n"
                f"🗓️ **Data Original:** {dados_nf.DataRecebimento.strftime('%d/%m/%Y %H:%M')}\n"
                f"🆔 **NF ID:** {dados_nf.NotaFiscalID}\n\n"
                "Ações Rápidas:"
            )

            keyboard = [
                [InlineKeyboardButton("📲 Encaminhar p/ Financeiro", callback_data=f"nf_prep_fwd_{nota_fiscal_id}")],
                [InlineKeyboardButton("📦 Criar Tarefa 'Guardar'", callback_data=f"nf_create_task_{nota_fiscal_id}")],
                [InlineKeyboardButton("👍 Arquivar (Nenhuma Ação)", callback_data=f"nf_ignore_{nota_fiscal_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Usa o notificador_telegram (HTTP) para enviar
            # Usamos o FileID se a foto ainda não foi baixada, ou o PathFoto se já foi.
            foto_para_enviar = dados_nf.PathFoto if dados_nf.PathFoto else dados_nf.FileIDTelegram

            if not foto_para_enviar:
                messagebox.showerror("Erro", "Esta NF não possui FileID nem PathFoto. Não é possível reenviar.")
                return

            notificador_telegram.enviar_foto_com_botoes(
                config.GESTOR_GROUP_CHAT_ID,
                foto_para_enviar,
                legenda_gestor,
                reply_markup,
                parse_mode='HTML'
            )
            messagebox.showinfo("Sucesso", "A Nota Fiscal e os botões de ação foram reenviados para o grupo de Gestores.")

        except Exception as e:
            logger.error(f"Erro ao recriar botões de NF: {e}", exc_info=True)
            messagebox.showerror("Erro Inesperado", f"Não foi possível reenviar as ações:\n{e}")

    # --- FIM: Funções da Aba "Consultar NFs" ---



    def popular_combobox_filtro_setor(self):
        """Busca os setores únicos e popula o combobox de filtro."""
        try: # <--- ADICIONADO TRY
            setores = database.listar_setores_unicos() # Pode falhar
            self.combo_filtro_setor['values'] = setores + ["Outras Tarefas"]
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao popular combobox de setores (filtro): {e}")
            messagebox.showerror("Erro de Banco", f"Não foi possível carregar a lista de setores:\n{e}", parent=self.root)

    def limpar_filtro_tarefas(self):
        """Limpa o filtro de setor e de título, e recarrega todas as tarefas."""
        self.combo_filtro_setor.set('')
        self.entry_filtro_atr_tarefas.delete(0, tk.END)
        self.atualizar_lista_tarefas_atribuicao() # Chama a função principal sem filtro

    def filtrar_tarefas_por_setor(self, event=None):
        # [CORREÇÃO] Limpa o campo de busca textual para evitar ambiguidade visual
        self.entry_filtro_atr_tarefas.delete(0, tk.END)
        """Pega o setor selecionado e chama a função de atualização com o filtro."""
        setor_selecionado = self.combo_filtro_setor.get()
        if setor_selecionado:
            self.atualizar_lista_tarefas_atribuicao(filtro_setor=setor_selecionado)

    def criar_aba_dashboard(self):
        """Constrói o Dashboard Operacional (Sem gráfico, com filtros)."""
        # --- Título e Botão de Atualização Geral ---
        frame_topo = ttk.Frame(self.frame_dashboard)
        frame_topo.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(frame_topo, text="Dashboard & Controle Operacional", font=("Arial", 16, "bold")).pack(side=tk.LEFT)
        ttk.Button(frame_topo, text="🔄 Atualizar Tudo", command=self.atualizar_dashboard_completo).pack(side=tk.RIGHT)

        # --- Área Principal: Painéis Operacionais (3 Colunas) ---
        # Agora expande para ocupar a tela toda, já que o gráfico saiu
        frame_operacional = ttk.Frame(self.frame_dashboard)
        frame_operacional.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # === COLUNA 1: Agendamentos de Grupo (COM FILTROS) ===
        frame_col1 = ttk.Frame(frame_operacional)
        frame_col1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        frame_grupos = ttk.LabelFrame(frame_col1, text="📅 Agendamentos de Grupo", padding="5")
        frame_grupos.pack(fill=tk.BOTH, expand=True)

        # Filtros de Grupo
        frame_filtros_grupo = ttk.Frame(frame_grupos)
        frame_filtros_grupo.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(frame_filtros_grupo, text="Filtrar Grupo:").pack(side=tk.LEFT)
        self.entry_filtro_grupo_nome = ttk.Entry(frame_filtros_grupo, width=15)
        self.entry_filtro_grupo_nome.pack(side=tk.LEFT, padx=5)
        # Bind para atualizar ao digitar (Enter ou KeyRelease)
        self.entry_filtro_grupo_nome.bind("<KeyRelease>", lambda e: self.atualizar_dashboard_completo())

        cols_g = ('Grupo', 'Tarefa', 'Horário')
        self.tree_audit_grupos = ttk.Treeview(frame_grupos, columns=cols_g, show='headings')
        self.tree_audit_grupos.heading('Grupo', text='Grupo'); self.tree_audit_grupos.column('Grupo', width=100)
        self.tree_audit_grupos.heading('Tarefa', text='Tarefa'); self.tree_audit_grupos.column('Tarefa', width=150)
        self.tree_audit_grupos.heading('Horário', text='Hora'); self.tree_audit_grupos.column('Horário', width=60, anchor='center')
        self.tree_audit_grupos.pack(fill=tk.BOTH, expand=True)

        # === COLUNA 2: Tarefas Órfãs ===
        frame_orfas = ttk.LabelFrame(frame_operacional, text="⚠️ Tarefas Sem Dono (Órfãs)", padding="5")
        frame_orfas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

        cols_o = ('Setor', 'Tarefa', 'Pts')
        self.tree_audit_orfas = ttk.Treeview(frame_orfas, columns=cols_o, show='headings')
        self.tree_audit_orfas.heading('Setor', text='Setor'); self.tree_audit_orfas.column('Setor', width=80)
        self.tree_audit_orfas.heading('Tarefa', text='Tarefa'); self.tree_audit_orfas.column('Tarefa', width=150)
        self.tree_audit_orfas.heading('Pts', text='Pts'); self.tree_audit_orfas.column('Pts', width=40, anchor='center')
        self.tree_audit_orfas.pack(fill=tk.BOTH, expand=True)

        # === COLUNA 3: Pendências de Hoje ===
        frame_pendencias = ttk.LabelFrame(frame_operacional, text="🚨 Pendências de HOJE", padding="5")
        frame_pendencias.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        cols_p = ('Func.', 'Tarefa', 'Tipo')
        self.tree_audit_pendencias = ttk.Treeview(frame_pendencias, columns=cols_p, show='headings')
        self.tree_audit_pendencias.heading('Func.', text='Nome'); self.tree_audit_pendencias.column('Func.', width=100)
        self.tree_audit_pendencias.heading('Tarefa', text='Tarefa Pendente'); self.tree_audit_pendencias.column('Tarefa', width=150)
        self.tree_audit_pendencias.heading('Tipo', text='Tipo'); self.tree_audit_pendencias.column('Tipo', width=60, anchor='center')
        self.tree_audit_pendencias.pack(fill=tk.BOTH, expand=True)

        # Inicializa os dados
        self.atualizar_dashboard_completo()

    def atualizar_dashboard_completo(self):
        """Atualiza as 3 tabelas operacionais. (Gráfico Removido)."""

        # 1. Limpar as tabelas
        for i in self.tree_audit_grupos.get_children(): self.tree_audit_grupos.delete(i)
        for i in self.tree_audit_orfas.get_children(): self.tree_audit_orfas.delete(i)
        for i in self.tree_audit_pendencias.get_children(): self.tree_audit_pendencias.delete(i)

        try:
            # 2. Carregar Grupos (COM FILTRO)
            dados_grupos = database.listar_cronograma_agendado_grupos()

            # Captura o texto do filtro (se o widget já existir)
            filtro_texto = ""
            if hasattr(self, 'entry_filtro_grupo_nome'):
                filtro_texto = self.entry_filtro_grupo_nome.get().lower()

            for row in dados_grupos:
                # row = (NomeGrupo, Titulo, TipoFreq, Horario)
                nome_grupo = row[0]
                nome_tarefa = row[1]

                # Aplica o filtro: Se tiver texto, verifica se está no nome do grupo ou da tarefa
                if filtro_texto:
                    if (filtro_texto not in nome_grupo.lower()) and (filtro_texto not in nome_tarefa.lower()):
                        continue # Pula este registro

                self.tree_audit_grupos.insert("", "end", values=(nome_grupo, nome_tarefa, row[3]))

            # 3. Carregar Órfãs
            dados_orfas = database.listar_tarefas_sem_atribuicao_ativa()
            for row in dados_orfas:
                # row = (ID, Titulo, Pontos, Setor)
                self.tree_audit_orfas.insert("", "end", values=(row[3] or "Geral", row[1], row[2]))

            # 4. Carregar Pendências do Dia (Agora com a query corrigida no database)
            dados_pendencias = database.listar_pendencias_gerais_hoje()
            for row in dados_pendencias:
                # row = (NomeFuncionario, TituloTarefa, TipoFreq)
                self.tree_audit_pendencias.insert("", "end", values=(row[0], row[1], row[2]))

        except Exception as e:
            logger.error(f"Erro ao atualizar dashboard operacional: {e}")

    def atualizar_combobox_setores(self):
        """Busca os setores únicos do banco e atualiza a lista do combobox."""
        setores = database.listar_setores_unicos()
        self.combo_setor_tarefa['values'] = setores

    def criar_aba_agenda(self):
        """Cria a interface da aba de Agenda Semanal."""
        main_frame = ttk.Frame(self.frame_agenda, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        frame_filtro = ttk.Frame(main_frame, padding="10")
        frame_filtro.pack(fill=tk.X)
        
        ttk.Label(frame_filtro, text="Selecione o Funcionário:", font=("Arial", 12)).pack(side=tk.LEFT)
        
        self.combo_funcionarios_agenda = ttk.Combobox(frame_filtro, state="readonly", width=40, font=("Arial", 10))
        self.combo_funcionarios_agenda.pack(side=tk.LEFT, padx=10)
        self.combo_funcionarios_agenda.bind("<<ComboboxSelected>>", self.exibir_agenda_funcionario)
        
        frame_tabela = ttk.Frame(main_frame, padding="10")
        frame_tabela.pack(fill=tk.BOTH, expand=True)
        
        dias_semana = ('Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo')
        self.tree_agenda = ttk.Treeview(frame_tabela, columns=dias_semana, show='headings')
        
        for dia in dias_semana:
            self.tree_agenda.heading(dia, text=dia)
            self.tree_agenda.column(dia, width=150)

        self.tree_agenda.column("#0", width=0, stretch=tk.NO)
        
        self.tree_agenda.pack(fill=tk.BOTH, expand=True)

        self.carregar_funcionarios_agenda()

    def criar_aba_loja(self):
        main_frame = ttk.Frame(self.frame_loja, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1) 
        main_frame.columnconfigure(1, weight=1)

        frame_produtos = ttk.LabelFrame(main_frame, text="Gerenciar Produtos da Loja", padding="10")
        frame_produtos.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        frame_produtos.rowconfigure(0, weight=1)
        frame_produtos.columnconfigure(0, weight=1)

        cols_prod = ('ID', 'Nome', 'Custo', 'Estoque', 'Status')
        self.tree_produtos_loja = ttk.Treeview(frame_produtos, columns=cols_prod, show='headings', selectmode='browse')
        self.tree_produtos_loja.heading('ID', text='ID'); self.tree_produtos_loja.column('ID', width=30)
        self.tree_produtos_loja.heading('Nome', text='Nome'); self.tree_produtos_loja.column('Nome', width=200)
        self.tree_produtos_loja.heading('Custo', text='Custo (pts)'); self.tree_produtos_loja.column('Custo', width=80, anchor='center')
        self.tree_produtos_loja.heading('Estoque', text='Estoque'); self.tree_produtos_loja.column('Estoque', width=60, anchor='center')
        self.tree_produtos_loja.heading('Status', text='Status'); self.tree_produtos_loja.column('Status', width=60, anchor='center')
        self.tree_produtos_loja.grid(row=0, column=0, sticky="nsew")

        frame_botoes_prod = ttk.Frame(frame_produtos)
        frame_botoes_prod.grid(row=1, column=0, pady=10)
        ttk.Button(frame_botoes_prod, text="Criar Novo", command=self.abrir_janela_produto).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_botoes_prod, text="Editar", command=lambda: self.abrir_janela_produto(editar=True)).pack(side=tk.LEFT, padx=5)

        frame_resgates = ttk.LabelFrame(main_frame, text="Aprovar Resgates Pendentes", padding="10")
        frame_resgates.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        frame_resgates.rowconfigure(0, weight=1)
        frame_resgates.columnconfigure(0, weight=1)

        cols_resg = ('ID', 'Funcionário', 'Produto', 'Data')
        self.tree_resgates_pendentes = ttk.Treeview(frame_resgates, columns=cols_resg, show='headings', selectmode='browse')
        self.tree_resgates_pendentes.heading('ID', text='ID'); self.tree_resgates_pendentes.column('ID', width=30)
        self.tree_resgates_pendentes.heading('Funcionário', text='Funcionário'); self.tree_resgates_pendentes.column('Funcionário', width=150)
        self.tree_resgates_pendentes.heading('Produto', text='Produto'); self.tree_resgates_pendentes.column('Produto', width=150)
        self.tree_resgates_pendentes.heading('Data', text='Data'); self.tree_resgates_pendentes.column('Data', width=120, anchor='center')
        self.tree_resgates_pendentes.grid(row=0, column=0, sticky="nsew")

        frame_botoes_resg = ttk.Frame(frame_resgates)
        frame_botoes_resg.grid(row=1, column=0, pady=10)
        ttk.Button(frame_botoes_resg, text="Aprovar Resgate", command=self.aprovar_resgate_selecionado).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_botoes_resg, text="Recusar Resgate", command=self.recusar_resgate_selecionado).pack(side=tk.LEFT, padx=5)

    def carregar_funcionarios_agenda(self):
        """Carrega a lista de funcionários para o combobox da aba Agenda."""
        funcionarios = database.listar_funcionarios()
        self.dados_funcionarios_agenda = {f"{f.NomeCompleto} (ID: {f.FuncionarioID})": f.FuncionarioID for f in funcionarios}
        self.combo_funcionarios_agenda['values'] = list(self.dados_funcionarios_agenda.keys())

    def exibir_agenda_funcionario(self, event=None):
        """Busca as tarefas do funcionário selecionado e as exibe na agenda semanal."""
        for i in self.tree_agenda.get_children():
            self.tree_agenda.delete(i)

        nome_selecionado = self.combo_funcionarios_agenda.get()
        if not nome_selecionado:
            return

        funcionario_id = self.dados_funcionarios_agenda[nome_selecionado]
        tarefas = database.listar_agenda_semanal_por_funcionario(funcionario_id)
        
        agenda_semanal = {
            '2': [], '3': [], '4': [], '5': [], '6': [], '7': [], '1': []
        }
        tarefas_diarias = []

        for tarefa in tarefas:
            if tarefa.TipoFrequencia == 'Diaria':
                tarefas_diarias.append(tarefa.Titulo)
            elif tarefa.TipoFrequencia == 'Semanal':
                agenda_semanal[str(tarefa.ValorFrequencia)].append(tarefa.Titulo)
        
        for dia in agenda_semanal:
            agenda_semanal[dia].extend(tarefas_diarias)

        max_linhas = 0
        for tarefas_do_dia in agenda_semanal.values():
            if len(tarefas_do_dia) > max_linhas:
                max_linhas = len(tarefas_do_dia)
                
        if max_linhas == 0 and not tarefas_diarias:
            return

        for i in range(max_linhas):
            linha = (
                agenda_semanal['2'][i] if i < len(agenda_semanal['2']) else "",
                agenda_semanal['3'][i] if i < len(agenda_semanal['3']) else "",
                agenda_semanal['4'][i] if i < len(agenda_semanal['4']) else "",
                agenda_semanal['5'][i] if i < len(agenda_semanal['5']) else "",
                agenda_semanal['6'][i] if i < len(agenda_semanal['6']) else "",
                agenda_semanal['7'][i] if i < len(agenda_semanal['7']) else "",
                agenda_semanal['1'][i] if i < len(agenda_semanal['1']) else "",
            )
            self.tree_agenda.insert("", "end", values=linha)

    def desenhar_grafico_ranking(self):
        try: # <--- ADICIONADO TRY
            self.ax_ranking.clear()
            ranking_data = database.calcular_ranking_desempenho()[:5] # Pode falhar

            if not ranking_data:
                self.ax_ranking.text(0.5, 0.5, "Sem dados para exibir.", ha='center', va='center')
                self.canvas_grafico.draw()
                return

            ranking_data.reverse() 
            nomes = [row['NomeCompleto'] for row in ranking_data]
            percentuais = [row['Desempenho'] for row in ranking_data]
            
            self.ax_ranking.barh(nomes, percentuais, color='skyblue', height=0.6)
            
            for index, value in enumerate(percentuais):
                self.ax_ranking.text(value + 0.5, index, f' {value}%', va='center')
                
            self.ax_ranking.set_title('Top 5 Funcionários por Desempenho (%)')
            self.ax_ranking.set_xlabel('Percentual de Desempenho')
            self.ax_ranking.set_xlim(0, 110)
            self.ax_ranking.spines['top'].set_visible(False)
            self.ax_ranking.spines['right'].set_visible(False)
            
            self.canvas_grafico.figure.tight_layout()
            
            self.canvas_grafico.draw()
        
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao desenhar gráfico de ranking: {e}")
            messagebox.showerror("Erro Gráfico", f"Não foi possível gerar o gráfico de ranking:\n{e}", parent=self.root)
            # Limpa o eixo em caso de erro para não mostrar gráfico antigo
            if hasattr(self, 'ax_ranking'):
                self.ax_ranking.clear()
                self.ax_ranking.text(0.5, 0.5, "Erro ao carregar dados.", ha='center', va='center', color='red')
            if hasattr(self, 'canvas_grafico'):
                self.canvas_grafico.draw()

    def on_funcionario_selecionado(self, event):
        """Chamada quando um funcionário é selecionado na lista."""
        try: # <--- ADICIONADO TRY
            for i in self.tree_tarefas_funcionario.get_children():
                self.tree_tarefas_funcionario.delete(i)

            indices = self.lista_funcionarios.curselection()
            if not indices: return

            texto_selecionado = self.lista_funcionarios.get(indices[0])
            funcionario_selecionado = self.dados_funcionarios[texto_selecionado] # Pode dar KeyError se dados_funcionarios estiver vazio
            funcionario_id = funcionario_selecionado.FuncionarioID

            tarefas_ativas = database.listar_atribuicoes_ativas_por_funcionario(funcionario_id) # Pode falhar
            for tarefa in tarefas_ativas:
                self.tree_tarefas_funcionario.insert("", "end", values=tuple(tarefa))
            # [CORREÇÃO] Removida a mudança forçada de aba para não interromper o fluxo do gestor
            # self.notebook_funcionarios.select(self.notebook_funcionarios.tabs()[1])
        except KeyError as e: # <--- ADICIONADO EXCEPT ESPECÍFICO
             logger.error(f"Erro ao buscar dados do funcionário selecionado: {e}")
             messagebox.showerror("Erro Interno", f"Não foi possível encontrar os dados do funcionário selecionado na memória:\n{e}", parent=self.root)
        except Exception as e: # <--- ADICIONADO EXCEPT GENÉRICO
            logger.exception(f"Erro em on_funcionario_selecionado: {e}")
            messagebox.showerror("Erro", f"Não foi possível carregar as tarefas ativas do funcionário:\n{e}", parent=self.root)

    def criar_aba_funcionarios(self):
        main_frame = ttk.Frame(self.frame_funcionarios, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # --- PAINEL ESQUERDO: LISTA DE FUNCIONÁRIOS ---
        frame_esquerda = ttk.Frame(main_frame, padding="10")
        frame_esquerda.grid(row=0, column=0, sticky="ns")
        ttk.Label(frame_esquerda, text="Funcionários Cadastrados", font=("Arial", 14)).pack(pady=5)
        
        self.lista_funcionarios = tk.Listbox(frame_esquerda, height=20, width=50, exportselection=False)
        self.lista_funcionarios.pack(fill=tk.BOTH, expand=True)
        self.lista_funcionarios.bind('<<ListboxSelect>>', self.on_funcionario_selecionado)

        # --- PAINEL DIREITO: ABAS DE DETALHES ---
        self.notebook_funcionarios = ttk.Notebook(main_frame)
        self.notebook_funcionarios.grid(row=0, column=1, sticky="nsew", padx=10)

        # Aba 1: Adicionar Novo
        frame_direita_add = ttk.Frame(self.notebook_funcionarios, padding="10")
        self.notebook_funcionarios.add(frame_direita_add, text='Adicionar Novo Funcionário')
        
        ttk.Label(frame_direita_add, text="Adicionar Novo Funcionário", font=("Arial", 14)).pack(pady=5)
        ttk.Label(frame_direita_add, text="Nome Completo:").pack(pady=(10, 2)); self.entry_nome = ttk.Entry(frame_direita_add, width=40); self.entry_nome.pack()
        ttk.Label(frame_direita_add, text="ID do Chat Telegram:").pack(pady=(10, 2)); self.entry_chat_id = ttk.Entry(frame_direita_add, width=40); self.entry_chat_id.pack()
        ttk.Label(frame_direita_add, text="Cargo:").pack(pady=(10, 2)); self.entry_cargo = ttk.Entry(frame_direita_add, width=40); self.entry_cargo.pack()
        
        # LINHAS QUE ESTAVAM FALTANDO:
        ttk.Label(frame_direita_add, text="Horário de Notificação (HH:MM):").pack(pady=(10, 2)); self.entry_horario = ttk.Entry(frame_direita_add, width=40); self.entry_horario.insert(0, "08:00"); self.entry_horario.pack()
        ttk.Label(frame_direita_add, text="Folga Semanal:").pack(pady=(10, 2))
        self.dias_semana_mapa = {
            'Sem Folga Definida': 0, 'Domingo': 1, 'Segunda-feira': 2, 'Terça-feira': 3, 
            'Quarta-feira': 4, 'Quinta-feira': 5, 'Sexta-feira': 6, 'Sábado': 7
        }
        self.combo_folga = ttk.Combobox(frame_direita_add, state="readonly", values=list(self.dias_semana_mapa.keys()))
        self.combo_folga.pack()
        self.combo_folga.set('Sem Folga Definida')
        
        btn_adicionar = ttk.Button(frame_direita_add, text="Adicionar Funcionário", command=self.adicionar_novo_funcionario); btn_adicionar.pack(pady=20, ipadx=10, ipady=5)

        # Aba 2: Tarefas Ativas do Selecionado
        frame_direita_tarefas = ttk.Frame(self.notebook_funcionarios, padding="10")
        self.notebook_funcionarios.add(frame_direita_tarefas, text='Tarefas Ativas')

        cols_tarefas = ('ID', 'Tarefa', 'Frequência')
        self.tree_tarefas_funcionario = ttk.Treeview(frame_direita_tarefas, columns=cols_tarefas, show='headings')
        self.tree_tarefas_funcionario.heading('ID', text='ID'); self.tree_tarefas_funcionario.column('ID', width=40)
        self.tree_tarefas_funcionario.heading('Tarefa', text='Tarefa'); self.tree_tarefas_funcionario.column('Tarefa', width=300)
        self.tree_tarefas_funcionario.heading('Frequência', text='Frequência'); self.tree_tarefas_funcionario.column('Frequência', width=150)
        self.tree_tarefas_funcionario.pack(fill=tk.BOTH, expand=True)

        # Aba 3: Ações para o funcionário selecionado
        frame_direita_acoes = ttk.Frame(self.notebook_funcionarios, padding="30")
        self.notebook_funcionarios.add(frame_direita_acoes, text='Ações')
        
        btn_editar_func = ttk.Button(frame_direita_acoes, text="Editar Cadastro do Funcionário", command=self.abrir_janela_edicao_funcionario); btn_editar_func.pack(pady=10, fill='x', ipady=5)
        btn_ver_historico = ttk.Button(frame_direita_acoes, text="Ver Histórico Completo", command=self.abrir_janela_historico); btn_ver_historico.pack(pady=10, fill='x', ipady=5)
        btn_ver_pendencias = ttk.Button(frame_direita_acoes, text="Ver Pendências de Hoje", command=self.abrir_janela_pendencias); btn_ver_pendencias.pack(pady=10, fill='x', ipady=5)
        btn_zerar_pontos = ttk.Button(frame_direita_acoes, text="Zerar Pontos do Mês", command=self.zerar_pontos_do_funcionario_selecionado); btn_zerar_pontos.pack(pady=10, fill='x', ipady=5)
        btn_excluir_func = ttk.Button(frame_direita_acoes, text="Excluir Funcionário", command=self.excluir_funcionario_selecionado, style="Danger.TButton"); btn_excluir_func.pack(pady=10, fill='x', ipady=5)
        
        style = ttk.Style()
        style.configure("Danger.TButton", foreground="red")
        
        self.atualizar_lista_funcionarios()
  
    def criar_aba_grupos(self):
        main_frame = ttk.Frame(self.frame_grupos, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1); main_frame.columnconfigure(1, weight=2)
        main_frame.rowconfigure(0, weight=1) # Diz para a Linha 0 (onde estão os painéis) crescer na vertical
        frame_grupos_lista = ttk.LabelFrame(main_frame, text="Grupos", padding="10")
        frame_grupos_lista.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame_grupos_lista.rowconfigure(0, weight=1); frame_grupos_lista.columnconfigure(0, weight=1)
        cols_grupos = ('ID', 'Nome', 'Chat ID'); self.tree_grupos = ttk.Treeview(frame_grupos_lista, columns=cols_grupos, show='headings', selectmode='browse')
        self.tree_grupos.heading('ID', text='ID'); self.tree_grupos.column('ID', width=40)
        self.tree_grupos.heading('Nome', text='Nome'); self.tree_grupos.heading('Chat ID', text='Chat ID')
        self.tree_grupos.grid(row=0, column=0, sticky="nsew")
        self.tree_grupos.bind('<<TreeviewSelect>>', self.popular_paineis_de_membros)
        frame_botoes_grupos = ttk.Frame(frame_grupos_lista); frame_botoes_grupos.grid(row=1, column=0, pady=10)
        ttk.Button(frame_botoes_grupos, text="Criar Novo Grupo", command=self.criar_novo_grupo).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_botoes_grupos, text="Editar Grupo", command=self.editar_grupo_selecionado).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_botoes_grupos, text="Excluir Grupo", command=self.excluir_grupo_selecionado).pack(side=tk.LEFT, padx=5)
        frame_membros = ttk.LabelFrame(main_frame, text="Gerenciar Membros do Grupo", padding="10")
        frame_membros.grid(row=0, column=1, sticky="nsew")
        frame_membros.columnconfigure(0, weight=2); frame_membros.columnconfigure(1, weight=1); frame_membros.columnconfigure(2, weight=2)
        frame_membros.rowconfigure(1, weight=1)
        ttk.Label(frame_membros, text="Funcionários Disponíveis").grid(row=0, column=0)
        self.tree_nao_membros = ttk.Treeview(frame_membros, columns=('ID', 'Nome'), show='headings', selectmode='extended')
        self.tree_nao_membros.heading('ID', text='ID'); self.tree_nao_membros.column('ID', width=40); self.tree_nao_membros.heading('Nome', text='Nome')
        self.tree_nao_membros.grid(row=1, column=0, sticky="nsew", padx=5)
        frame_botoes_membros = ttk.Frame(frame_membros); frame_botoes_membros.grid(row=1, column=1, padx=5)
        ttk.Button(frame_botoes_membros, text="Adicionar ->", command=self.adicionar_membros_ao_grupo).pack(pady=5)
        ttk.Button(frame_botoes_membros, text="<- Remover", command=self.remover_membros_do_grupo).pack(pady=5)
        ttk.Label(frame_membros, text="Membros Atuais").grid(row=0, column=2)
        self.tree_membros = ttk.Treeview(frame_membros, columns=('ID', 'Nome'), show='headings', selectmode='extended')
        self.tree_membros.heading('ID', text='ID'); self.tree_membros.column('ID', width=40); self.tree_membros.heading('Nome', text='Nome')
        self.tree_membros.grid(row=1, column=2, sticky="nsew", padx=5)
        self.atualizar_lista_grupos()

    def popular_paineis_de_membros(self, event):
        """Atualiza as listas de membros e não-membros de um grupo."""
        try: # <--- ADICIONADO TRY
            for i in self.tree_membros.get_children(): self.tree_membros.delete(i)
            for i in self.tree_nao_membros.get_children(): self.tree_nao_membros.delete(i)

            selecionado = self.tree_grupos.focus()
            if not selecionado: return
            dados_grupo = self.tree_grupos.item(selecionado, 'values')
            if not dados_grupo: return
            grupo_id = dados_grupo[0]

            membros, nao_membros = database.listar_membros_e_nao_membros(grupo_id) # Pode falhar

            for membro in membros: self.tree_membros.insert("", "end", values=(membro.FuncionarioID, membro.NomeCompleto))
            for nao_membro in nao_membros: self.tree_nao_membros.insert("", "end", values=(nao_membro.FuncionarioID, nao_membro.NomeCompleto))
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao popular painéis de membros para grupo ID {grupo_id if 'grupo_id' in locals() else 'N/A'}: {e}")
            messagebox.showerror("Erro de Banco", f"Não foi possível carregar os membros do grupo:\n{e}", parent=self.root)   

    def atualizar_lista_grupos(self):
        """Limpa e recarrega a lista de grupos do banco de dados."""
        try: # <--- ADICIONADO TRY
            for i in self.tree_grupos.get_children(): self.tree_grupos.delete(i)
            for grupo in database.listar_grupos(): # Pode falhar
                self.tree_grupos.insert("", "end", values=(grupo.GrupoID, grupo.NomeGrupo, grupo.ChatIDTelegram))
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao atualizar lista de grupos: {e}")
            messagebox.showerror("Erro de Banco", f"Não foi possível carregar a lista de grupos:\n{e}", parent=self.root)

    def criar_novo_grupo(self):
        """Abre pop-ups para pedir o nome e o chat_id e cria um novo grupo."""
        try: # <--- ADICIONADO TRY (para simpledialog e banco)
            nome = simpledialog.askstring("Novo Grupo", "Digite o nome do novo grupo:", parent=self.root) # Pode retornar None
            if nome:
                chat_id = simpledialog.askstring("Chat ID", f"Digite o Chat ID do Telegram para o grupo '{nome}':", parent=self.root) # Pode retornar None
                if chat_id:
                    database.criar_grupo(nome, chat_id) # Pode falhar
                    self.atualizar_lista_grupos()
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao criar novo grupo: {e}")
            messagebox.showerror("Erro", f"Não foi possível criar o grupo:\n{e}", parent=self.root)

    def editar_grupo_selecionado(self):
        """Pega o grupo selecionado e abre pop-ups para editar seus dados."""
        selecionado = self.tree_grupos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um grupo para editar.", parent=self.root) # Adicionado parent
            return

        try: # <--- ADICIONADO TRY (para simpledialog e banco)
            dados_grupo = self.tree_grupos.item(selecionado, 'values')
            grupo_id, nome_antigo, chat_id_antigo = dados_grupo

            novo_nome = simpledialog.askstring("Editar Grupo", "Digite o novo nome do grupo:", initialvalue=nome_antigo, parent=self.root) # Pode retornar None
            if novo_nome:
                novo_chat_id = simpledialog.askstring("Editar Chat ID", "Digite o novo Chat ID do Telegram:", initialvalue=chat_id_antigo, parent=self.root) # Pode retornar None
                if novo_chat_id:
                    database.atualizar_grupo(grupo_id, novo_nome, novo_chat_id) # Pode falhar
                    self.atualizar_lista_grupos()
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao editar grupo ID {grupo_id if 'grupo_id' in locals() else 'N/A'}: {e}")
            messagebox.showerror("Erro", f"Não foi possível editar o grupo:\n{e}", parent=self.root)

    def excluir_grupo_selecionado(self):
        """Exclui o grupo selecionado após uma confirmação."""
        selecionado = self.tree_grupos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um grupo para excluir.", parent=self.root) # Adicionado parent
            return

        dados_grupo = self.tree_grupos.item(selecionado, 'values')
        grupo_id, nome_grupo, _ = dados_grupo

        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o grupo '{nome_grupo}'?", parent=self.root): # Adicionado parent
            try: # <--- ADICIONADO TRY
                database.excluir_grupo(grupo_id) # Pode falhar
                self.atualizar_lista_grupos()
            except Exception as e: # <--- ADICIONADO EXCEPT
                logger.exception(f"Erro ao excluir grupo ID {grupo_id}: {e}")
                messagebox.showerror("Erro", f"Não foi possível excluir o grupo:\n{e}", parent=self.root)

    def adicionar_membros_ao_grupo(self):
        """Adiciona os funcionários selecionados da lista de 'disponíveis' ao grupo."""
        grupo_selecionado = self.tree_grupos.focus()
        if not grupo_selecionado:
            messagebox.showwarning("Aviso", "Selecione um grupo primeiro.", parent=self.root) # Adicionado parent
            return
        funcionarios_selecionados = self.tree_nao_membros.selection()
        if not funcionarios_selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos um funcionário da lista de 'Disponíveis'.", parent=self.root) # Adicionado parent
            return

        grupo_id = self.tree_grupos.item(grupo_selecionado, 'values')[0]
        try: # <--- ADICIONADO TRY (em volta do loop)
            erros = 0
            for item in funcionarios_selecionados:
                try: # Try interno para continuar mesmo se um falhar
                    funcionario_id = self.tree_nao_membros.item(item, 'values')[0]
                    database.adicionar_membro_ao_grupo(funcionario_id, grupo_id) # Pode falhar
                except Exception as e_inner:
                    erros += 1
                    logger.error(f"Erro ao adicionar membro {funcionario_id} ao grupo {grupo_id}: {e_inner}")

            self.popular_paineis_de_membros(None) # Atualiza as listas

            if erros > 0:
                 messagebox.showwarning("Atenção", f"{len(funcionarios_selecionados) - erros} membro(s) adicionado(s), mas {erros} falharam.", parent=self.root)
            # else: # Opcional: Mostrar sucesso se nenhum erro
            #    messagebox.showinfo("Sucesso", f"{len(funcionarios_selecionados)} membro(s) adicionado(s).", parent=self.root)

        except Exception as e: # <--- ADICIONADO EXCEPT (para erros inesperados no processo)
            logger.exception(f"Erro inesperado ao adicionar membros ao grupo ID {grupo_id}: {e}")
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao adicionar membros:\n{e}", parent=self.root) 
    
    def remover_membros_do_grupo(self):
        """Remove os funcionários selecionados da lista de 'membros' do grupo."""
        grupo_selecionado = self.tree_grupos.focus()
        if not grupo_selecionado:
            messagebox.showwarning("Aviso", "Selecione um grupo primeiro.", parent=self.root) # Adicionado parent
            return
        funcionarios_selecionados = self.tree_membros.selection()
        if not funcionarios_selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos um funcionário da lista de 'Membros Atuais'.", parent=self.root) # Adicionado parent
            return

        grupo_id = self.tree_grupos.item(grupo_selecionado, 'values')[0]
        try: # <--- ADICIONADO TRY (em volta do loop)
            erros = 0
            for item in funcionarios_selecionados:
                try: # Try interno
                    funcionario_id = self.tree_membros.item(item, 'values')[0]
                    database.remover_membro_do_grupo(funcionario_id, grupo_id) # Pode falhar
                except Exception as e_inner:
                    erros += 1
                    logger.error(f"Erro ao remover membro {funcionario_id} do grupo {grupo_id}: {e_inner}")

            self.popular_paineis_de_membros(None) # Atualiza as listas

            if erros > 0:
                 messagebox.showwarning("Atenção", f"{len(funcionarios_selecionados) - erros} membro(s) removido(s), mas {erros} falharam.", parent=self.root)

        except Exception as e: # <--- ADICIONADO EXCEPT (geral)
            logger.exception(f"Erro inesperado ao remover membros do grupo ID {grupo_id}: {e}")
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao remover membros:\n{e}", parent=self.root)        

    def atualizar_lista_tarefas_atribuicao(self, filtro_setor=None):
        """(VERSÃO FINAL) Carrega a lista de tarefas, agrupada por setor, aplicando um filtro opcional."""
        try: # <--- ADICIONADO TRY
            for i in self.tree_atr_tarefas.get_children(): self.tree_atr_tarefas.delete(i)
            setores_nodes = {}
            tarefas = database.listar_tarefas_para_atribuicao(filtro_setor) # Pode falhar
            for tarefa in tarefas:
                setor_nome = tarefa.Setor if tarefa.Setor else "Outras Tarefas"
                if setor_nome not in setores_nodes:
                    setor_node = self.tree_atr_tarefas.insert("", "end", text=setor_nome, open=True)
                    setores_nodes[setor_nome] = setor_node
                else: setor_node = setores_nodes[setor_nome]
                self.tree_atr_tarefas.insert(setor_node, "end", text=tarefa.Titulo, values=(tarefa.TarefaID, tarefa.Titulo))
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao atualizar lista de tarefas para atribuição: {e}")
            messagebox.showerror("Erro de Banco", f"Não foi possível carregar a lista de tarefas:\n{e}", parent=self.root)

    def filtrar_lista_tarefas_atribuicao(self):
        """
        (VERSÃO CORRIGIDA)
        Filtra a lista de tarefas, mas MANTÉM a estrutura de agrupamento por setor.
        """
        termo_busca = self.entry_filtro_atr_tarefas.get().lower()

        for i in self.tree_atr_tarefas.get_children():
            self.tree_atr_tarefas.delete(i)
        # [CORREÇÃO] Captura o setor selecionado para manter a consistência do filtro
        setor_selecionado = self.combo_filtro_setor.get()
        filtro_db = setor_selecionado if setor_selecionado else None

        setores_nodes = {}
        # Passa o filtro de setor para o banco junto com a busca textual local
        tarefas = database.listar_tarefas_para_atribuicao(filtro_setor=filtro_db)

        for tarefa in tarefas:
          
            if termo_busca not in tarefa.Titulo.lower():
                continue # Pula para a próxima tarefa

            setor_nome = tarefa.Setor if tarefa.Setor else "Outras Tarefas"

            if setor_nome not in setores_nodes:
                setor_node = self.tree_atr_tarefas.insert("", "end", text=setor_nome, open=True)
                setores_nodes[setor_nome] = setor_node
            else:
                setor_node = setores_nodes[setor_nome]

            self.tree_atr_tarefas.insert(setor_node, "end", text=tarefa.Titulo, values=(tarefa.TarefaID, tarefa.Titulo))

    def atualizar_painel_selecao(self, tarefa_id=None):
        """Atualiza a lista de alvos (funcionários ou grupos)."""
        try: # <--- ADICIONADO TRY
            for i in self.tree_atr_selecao.get_children(): self.tree_atr_selecao.delete(i)
            modo = self.modo_atribuicao.get()
            if modo == "Individual":
                if tarefa_id: _, disponiveis = database.listar_funcionarios_por_tarefa(tarefa_id) # Pode falhar
                else: disponiveis = database.listar_funcionarios() # Pode falhar
                alvos = disponiveis
                for alvo in alvos: self.tree_atr_selecao.insert("", "end", values=(alvo.FuncionarioID, alvo.NomeCompleto))
            elif modo == "Grupo":
                alvos = database.listar_grupos() # Pode falhar
                for alvo in alvos: self.tree_atr_selecao.insert("", "end", values=(alvo.GrupoID, alvo.NomeGrupo))
        except Exception as e: # <--- ADICIONADO EXCEPT
            logger.exception(f"Erro ao atualizar painel de seleção (alvos): {e}")
            messagebox.showerror("Erro de Banco", f"Não foi possível carregar a lista de alvos:\n{e}", parent=self.root)

    def atualizar_lista_atribuicoes_ativas(self):
        """Carrega/Atualiza a lista de tarefas que já foram atribuídas."""
        for i in self.tree_atribuicoes_ativas.get_children():
            self.tree_atribuicoes_ativas.delete(i)
        for atribuicao in database.listar_atribuicoes_ativas():
            self.tree_atribuicoes_ativas.insert("", "end", values=atribuicao)

    def desatribuir_tarefa_selecionada(self):
        """Encerra a validade de uma atribuição e atualiza AMBAS as listas na tela."""
        # Validações (fora do try)
        tarefa_selecionada_item = self.tree_atr_tarefas.focus()
        if not tarefa_selecionada_item: messagebox.showwarning("Aviso", "...", parent=self.root); return # Adicionado parent
        atribuicao_selecionada_item = self.tree_atribuicoes_ativas.focus()
        if not atribuicao_selecionada_item: messagebox.showwarning("Aviso", "...", parent=self.root); return # Adicionado parent
        atribuicao_id = self.tree_atribuicoes_ativas.item(atribuicao_selecionada_item, 'values')[0]
        tarefa_id_contexto = self.tree_atr_tarefas.item(tarefa_selecionada_item, 'values')[0]

        if messagebox.askyesno("Confirmar Encerramento", "...", parent=self.root): # Adicionado parent
            try: # <--- ADICIONADO TRY
                database.encerrar_atribuicao_tarefa(atribuicao_id) # Pode falhar
                self.atualizar_lista_atribuicoes_ativas() # Pode falhar
                self.atualizar_painel_selecao(tarefa_id=tarefa_id_contexto) # Pode falhar
                messagebox.showinfo("Sucesso", "Atribuição encerrada com sucesso.", parent=self.root) # Adicionado parent
            except Exception as e: # <--- ADICIONADO EXCEPT
                logger.exception(f"Erro ao desatribuir tarefa (AtribuicaoID {atribuicao_id}): {e}")
                messagebox.showerror("Erro", f"Não foi possível encerrar a atribuição:\n{e}", parent=self.root)


    # Em main.py, SUBSTITUA a função inteira abrir_popup_frequencia_universal por esta:

    def abrir_popup_frequencia_universal(self):
        """
        (VERSÃO REVISADA - BOTÕES CORRIGIDOS)
        Abre um pop-up inteligente para atribuição individual OU de grupo,
        com as opções de frequência corretas e os botões corretos para cada modo.
        """
        tarefa_selecionada_item = self.tree_atr_tarefas.focus()
        alvos_selecionados_items = self.tree_atr_selecao.selection()

        if not tarefa_selecionada_item or not alvos_selecionados_items:
            messagebox.showwarning("Aviso", "Selecione uma tarefa e pelo menos um alvo (funcionário ou grupo).")
            return

        values_tarefa = self.tree_atr_tarefas.item(tarefa_selecionada_item, 'values')
        if not values_tarefa or not values_tarefa[0]:
            messagebox.showwarning("Aviso", "Por favor, selecione uma TAREFA específica, não um setor.")
            return
        tarefa_id = values_tarefa[0]
        tarefa_titulo = values_tarefa[1]

        popup = tk.Toplevel(self.root)
        popup.title(f"Atribuir '{tarefa_titulo}'")
        frame = ttk.Frame(popup, padding="10"); frame.pack(fill="both", expand=True)
        modo = self.modo_atribuicao.get()

        # ===========================================================
        # == BLOCO PARA ATRIBUIÇÃO DE GRUPO =========================
        # ===========================================================
        if modo == "Grupo":
            popup.geometry("400x450")
            # --- Interface do Grupo (sem alterações) ---
            ttk.Label(frame, text="Selecione a Frequência de Oferta:", font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=(0,10))
            frequencia_grupo = tk.StringVar(value="Diaria")
            frame_radios = ttk.Frame(frame); frame_radios.pack(fill=tk.X)
            ttk.Radiobutton(frame_radios, text="Diária", variable=frequencia_grupo, value="Diaria").pack(side=tk.LEFT, padx=5)
            ttk.Radiobutton(frame_radios, text="Semanal", variable=frequencia_grupo, value="Semanal").pack(side=tk.LEFT, padx=5)
            ttk.Radiobutton(frame_radios, text="Mensal", variable=frequencia_grupo, value="Mensal").pack(side=tk.LEFT, padx=5)
            frame_semanal = ttk.Frame(frame, padding=(10, 5, 0, 0))
            ttk.Label(frame_semanal, text="Selecione os dias da semana:").pack(anchor=tk.W)
            frame_checks = ttk.Frame(frame_semanal); frame_checks.pack(fill=tk.X)
            dias_semana_vars_grupo = {"Dom": (tk.BooleanVar(), "1"), "Seg": (tk.BooleanVar(), "2"),"Ter": (tk.BooleanVar(), "3"), "Qua": (tk.BooleanVar(), "4"),"Qui": (tk.BooleanVar(), "5"), "Sex": (tk.BooleanVar(), "6"),"Sáb": (tk.BooleanVar(), "7")}
            for dia, (var, _) in dias_semana_vars_grupo.items(): ttk.Checkbutton(frame_checks, text=dia, variable=var).pack(side=tk.LEFT)
            frame_mensal = ttk.Frame(frame, padding=(10, 5, 0, 0))
            ttk.Label(frame_mensal, text="Digite o dia do mês (1-31):").pack(side=tk.LEFT)
            valor_mensal_grupo = tk.StringVar()
            entry_mensal = ttk.Entry(frame_mensal, textvariable=valor_mensal_grupo, width=5); entry_mensal.pack(side=tk.LEFT, padx=5)
            frame_horario = ttk.Frame(frame, padding=(0, 15, 0, 0)); frame_horario.pack(fill=tk.X)
            ttk.Label(frame_horario, text="Horário de Disparo (HH:MM):").pack(side=tk.LEFT)
            horario_var_grupo = tk.StringVar(value="19:00")
            ttk.Entry(frame_horario, textvariable=horario_var_grupo, width=10).pack(side=tk.LEFT, padx=5)
            
            # --- CORREÇÃO DE LÓGICA DE LAYOUT ---
            # 1. Definimos o botão, mas não o "empacotamos" (sem .pack())
            btn_confirmar_grupo = ttk.Button(frame, text="Confirmar Agendamento Recorrente")
            # --- FIM DA CORREÇÃO ---

            def atualizar_visibilidade_grupo(*args):
                freq = frequencia_grupo.get()
                if freq == "Semanal": frame_semanal.pack(fill=tk.X, pady=5); frame_mensal.pack_forget()
                elif freq == "Mensal": frame_mensal.pack(fill=tk.X, pady=5); frame_semanal.pack_forget()
                else: frame_semanal.pack_forget(); frame_mensal.pack_forget()
                
                # --- CORREÇÃO DE LÓGICA DE LAYOUT ---
                # 2. Empacotamos o botão *dentro* da função de atualização,
                #    garantindo que ele seja sempre o último widget a ser desenhado.
                btn_confirmar_grupo.pack(pady=20, ipady=5)
                # --- FIM DA CORREÇÃO ---
                
            frequencia_grupo.trace_add("write", atualizar_visibilidade_grupo)
            
            # --- Função de Confirmação do Grupo (sem alterações) ---
            def confirmar_atribuicao_grupo():
                # (Código interno desta função permanece o mesmo)
                horario = horario_var_grupo.get()
                tipo_freq_selecionada = frequencia_grupo.get()
                try: datetime.strptime(horario, '%H:%M')
                except ValueError: messagebox.showerror("Erro", "Formato de horário inválido. Use HH:MM.", parent=popup); return
                valores_frequencia = []
                tipo_freq_db = f"Grupo{tipo_freq_selecionada}"
                if tipo_freq_selecionada == "Semanal":
                    valores_frequencia = [val_db for _, (var, val_db) in dias_semana_vars_grupo.items() if var.get()]
                    if not valores_frequencia: messagebox.showerror("Erro", "Selecione pelo menos um dia da semana.", parent=popup); return
                elif tipo_freq_selecionada == "Mensal":
                    try: dia_mes = int(valor_mensal_grupo.get()); assert 1 <= dia_mes <= 31; valores_frequencia.append(str(dia_mes))
                    except (ValueError, AssertionError): messagebox.showerror("Erro", "O dia do mês deve ser um número entre 1 e 31.", parent=popup); return
                else: valores_frequencia.append(None)
                sucessos = falhas = 0
                for item_alvo in alvos_selecionados_items:
                    grupo_id = self.tree_atr_selecao.item(item_alvo, 'values')[0]
                    for valor in valores_frequencia:
                        if database.agendar_tarefa_recorrente_para_grupo(tarefa_id, grupo_id, tipo_freq_db, valor, horario): sucessos += 1
                        else: falhas += 1
                if falhas == 0: messagebox.showinfo("Sucesso", f"{sucessos} agendamento(s) de tarefa recorrente para grupo criado(s)!", parent=popup)
                else: messagebox.showwarning("Atenção", f"{sucessos} agendamentos criados, mas {falhas} falharam.", parent=popup)
                popup.destroy()
                self.atualizar_lista_atribuicoes_ativas()

            # --- CORREÇÃO DE LÓGICA DE LAYOUT ---
            # 3. Atribuímos o comando ao botão e chamamos a atualização pela primeira vez.
            btn_confirmar_grupo.config(command=confirmar_atribuicao_grupo)
            atualizar_visibilidade_grupo() # Desenha o layout inicial
            # --- FIM DA CORREÇÃO ---


        # ====================================================================
        # == ELSE: BLOCO PARA ATRIBUIÇÃO INDIVIDUAL ==========================
        # ====================================================================
        else: # modo == "Individual"
            popup.geometry("400x400")
            # --- Interface Individual (com checkbuttons semanais, sem alterações na UI) ---
            ttk.Label(frame, text="Selecione a Frequência:", font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=(0,10))
            frequencia_individual = tk.StringVar(value="Unica")
            frame_radios = ttk.Frame(frame); frame_radios.pack(fill=tk.X)
            ttk.Radiobutton(frame_radios, text="Única", variable=frequencia_individual, value="Unica").pack(side=tk.LEFT, padx=5)
            ttk.Radiobutton(frame_radios, text="Diária", variable=frequencia_individual, value="Diaria").pack(side=tk.LEFT, padx=5)
            ttk.Radiobutton(frame_radios, text="Semanal", variable=frequencia_individual, value="Semanal").pack(side=tk.LEFT, padx=5)
            ttk.Radiobutton(frame_radios, text="Mensal", variable=frequencia_individual, value="Mensal").pack(side=tk.LEFT, padx=5)
            frame_semanal_ind = ttk.Frame(frame, padding=(10, 5, 0, 0))
            ttk.Label(frame_semanal_ind, text="Selecione os dias da semana:").pack(anchor=tk.W)
            frame_checks_ind = ttk.Frame(frame_semanal_ind); frame_checks_ind.pack(fill=tk.X)
            dias_semana_vars_individual = {"Dom": (tk.BooleanVar(), "1"), "Seg": (tk.BooleanVar(), "2"),"Ter": (tk.BooleanVar(), "3"), "Qua": (tk.BooleanVar(), "4"),"Qui": (tk.BooleanVar(), "5"), "Sex": (tk.BooleanVar(), "6"),"Sáb": (tk.BooleanVar(), "7")}
            for dia, (var, _) in dias_semana_vars_individual.items(): ttk.Checkbutton(frame_checks_ind, text=dia, variable=var).pack(side=tk.LEFT)
            frame_mensal_ind = ttk.Frame(frame, padding=(10, 5, 0, 0))
            ttk.Label(frame_mensal_ind, text="Digite o dia do mês (1-31):").pack(side=tk.LEFT)
            valor_mensal_individual = tk.StringVar()
            entry_mensal_ind = ttk.Entry(frame_mensal_ind, textvariable=valor_mensal_individual, width=5); entry_mensal_ind.pack(side=tk.LEFT, padx=5)

            # --- CORREÇÃO DE LÓGICA DE LAYOUT (MESMA LÓGICA DO GRUPO) ---
            # 1. Definimos o botão, mas não o "empacotamos" (sem .pack())
            btn_confirmar_individual = ttk.Button(frame, text="Confirmar Atribuição")
            # --- FIM DA CORREÇÃO ---

            def atualizar_visibilidade_individual(*args):
                freq = frequencia_individual.get()
                if freq == "Semanal": frame_semanal_ind.pack(fill=tk.X, pady=5); frame_mensal_ind.pack_forget()
                elif freq == "Mensal": frame_mensal_ind.pack(fill=tk.X, pady=5); frame_semanal_ind.pack_forget()
                else: frame_semanal_ind.pack_forget(); frame_mensal_ind.pack_forget()
                
                # --- CORREÇÃO DE LÓGICA DE LAYOUT ---
                # 2. Empacotamos o botão *dentro* da função de atualização.
                btn_confirmar_individual.pack(pady=20, ipady=5)
                # --- FIM DA CORREÇÃO ---
            
            frequencia_individual.trace_add("write", atualizar_visibilidade_individual)
            
            # --- Função de Confirmação Individual (COM CORREÇÃO) ---
            def confirmar_atribuicao_individual():
                tipo_freq_selecionada = frequencia_individual.get()
                valores_freq = []
                # ... (lógica para obter valores_freq permanece a mesma) ...
                if tipo_freq_selecionada == "Semanal":
                    valores_freq = [val_db for _, (var, val_db) in dias_semana_vars_individual.items() if var.get()]
                    if not valores_freq: messagebox.showerror("Erro", "Selecione pelo menos um dia da semana.", parent=popup); return
                elif tipo_freq_selecionada == "Mensal":
                    try: dia_mes = int(valor_mensal_individual.get()); assert 1 <= dia_mes <= 31; valores_freq.append(str(dia_mes))
                    except (ValueError, AssertionError): messagebox.showerror("Erro", "O dia do mês deve ser um número entre 1 e 31.", parent=popup); return
                else: # Para Unica e Diaria
                    valores_freq.append(None) # Garante que o loop abaixo rode uma vez

                sucessos = falhas = ignorados = 0
                for item_alvo in alvos_selecionados_items:
                    funcionario_id = self.tree_atr_selecao.item(item_alvo, 'values')[0]

                    # [CORREÇÃO] Lógica refinada: Só bloqueia duplicidade se NÃO for tarefa Única.
                    # Tarefas Únicas podem ser atribuídas múltiplas vezes (ex: reforço esporádico),
                    # pois o histórico deve ser preservado.
                    if tipo_freq_selecionada != 'Unica':
                        if database.verificar_atribuicao_existente(tarefa_id, funcionario_id):
                            ignorados += 1
                            logger.warning(f"--> Atribuição Recorrente ignorada: Tarefa {tarefa_id} já ativa para Funcionario {funcionario_id}.")
                            continue

                    # Agora, itera pelos valores (dias da semana/mês ou None)
                    for valor in valores_freq:
                        # NÃO precisamos mais verificar aqui dentro
                        # if database.verificar_atribuicao_existente(tarefa_id, funcionario_id): # <-- LINHA REMOVIDA
                        #    ignorados += 1                                                     # <-- LINHA REMOVIDA
                        #    print(f"--> Atribuição ignorada: Tarefa {tarefa_id} já está ativa para Funcionário {funcionario_id}.") # <-- LINHA REMOVIDA
                        #    break # <-- LINHA REMOVIDA

                        # Tenta atribuir a tarefa para este valor específico
                        if database.atribuir_tarefa(tarefa_id, funcionario_id, tipo_freq_selecionada, valor):
                            sucessos += 1
                        else:
                            falhas += 1
                            # Se falhar aqui, pode ser um erro de banco, logar seria bom
                            logger.error(f"Falha ao chamar database.atribuir_tarefa para Func:{funcionario_id}, Tar:{tarefa_id}, Freq:{tipo_freq_selecionada}, Val:{valor}")

                # Lógica de mensagem final (ajustada para contar sucessos corretamente)
                msg_final = f"{sucessos} atribuição(ões) de frequência criada(s) com sucesso!" # Mensagem mais precisa
                if ignorados > 0:
                    msg_final += f"\n{ignorados} funcionário(s) foram ignorados pois já tinham esta tarefa ativa."
                if falhas > 0:
                    messagebox.showwarning("Atenção", f"{msg_final}\n{falhas} falharam ao salvar no banco.", parent=popup)
                else:
                    messagebox.showinfo("Sucesso", msg_final, parent=popup)

                popup.destroy()
                self.atualizar_lista_atribuicoes_ativas()
                self.atualizar_painel_selecao(tarefa_id=tarefa_id)

            # --- CORREÇÃO DE LÓGICA DE LAYOUT ---
            # 3. Atribuímos o comando ao botão e chamamos a atualização pela primeira vez.
            btn_confirmar_individual.config(command=confirmar_atribuicao_individual)
            atualizar_visibilidade_individual() # Desenha o layout inicial
            # --- FIM DA CORREÇÃO ---


    def criar_aba_tarefas(self):
        frame_formulario = ttk.LabelFrame(self.frame_tarefas, text="Criar ou Editar Modelo de Tarefa", padding="10"); frame_formulario.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(frame_formulario, text="Título:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2); self.entry_tarefa_titulo = ttk.Entry(frame_formulario, width=50); self.entry_tarefa_titulo.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=2)
        ttk.Label(frame_formulario, text="Descrição:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2); self.text_tarefa_descricao = tk.Text(frame_formulario, height=3, width=50); self.text_tarefa_descricao.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=2)
        ttk.Label(frame_formulario, text="Pontos:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2); self.entry_tarefa_pontos = ttk.Entry(frame_formulario, width=20); self.entry_tarefa_pontos.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        frame_botoes_form = ttk.Frame(frame_formulario); frame_botoes_form.grid(row=4, column=1, sticky=tk.E, pady=10)
        self.btn_salvar_tarefa = ttk.Button(frame_botoes_form, text="Criar Modelo de Tarefa", command=self.salvar_tarefa); self.btn_salvar_tarefa.pack(side=tk.LEFT)
        ttk.Label(frame_formulario, text="Setor:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.combo_setor_tarefa = ttk.Combobox(frame_formulario, width=47)
        self.combo_setor_tarefa.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        self.btn_limpar_form_tarefa = ttk.Button(frame_botoes_form, text="Limpar", command=self.limpar_formulario_tarefa); self.btn_limpar_form_tarefa.pack(side=tk.LEFT, padx=10)
        frame_formulario.columnconfigure(1, weight=1)
        frame_lista = ttk.LabelFrame(self.frame_tarefas, text="Catálogo de Modelos de Tarefa", padding="10"); frame_lista.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        cols = ('ID', 'Título', 'Pontos'); self.tree_tarefas = ttk.Treeview(frame_lista, columns=cols, show='headings')
        for col in cols: self.tree_tarefas.heading(col, text=col)
        self.tree_tarefas.column('ID', width=50); self.tree_tarefas.column('Título', width=400); self.tree_tarefas.column('Pontos', width=80); self.tree_tarefas.pack(fill=tk.BOTH, expand=True, pady=5)
        self.tree_tarefas.bind('<<TreeviewSelect>>', self.selecionar_tarefa_para_edicao)
        btn_excluir_tarefa = ttk.Button(frame_lista, text="Excluir Modelo Selecionado", command=self.excluir_tarefa_selecionada); btn_excluir_tarefa.pack(pady=10)
        self.atualizar_catalogo_tarefas()
        self.atualizar_combobox_setores()

    def criar_aba_atribuicoes(self):
        main_frame = ttk.Frame(self.frame_atribuicoes, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- CONFIGURAÇÃO DO GRID ---
        main_frame.columnconfigure(0, weight=3)
        main_frame.columnconfigure(1, weight=2)
        main_frame.columnconfigure(2, weight=3)
        # --- A CORREÇÃO ESTÁ AQUI ---
        main_frame.rowconfigure(0, weight=1) # <<< LINHA ADICIONADA: Permite que a linha 0 (dos painéis) cresça verticalmente

        # --- PAINEL 1: TAREFAS ---
        frame_tarefas = ttk.LabelFrame(main_frame, text="1. Selecione a Tarefa", padding="10")
        frame_tarefas.grid(row=0, column=0, sticky="nsew", padx=(0, 10), rowspan=2)
        # Configuração de grid para o frame interno
        frame_tarefas.rowconfigure(2, weight=1)
        frame_tarefas.columnconfigure(0, weight=1)

        # --- ADICIONE ESTE NOVO FRAME DE FILTRO DE SETOR ---
        frame_filtro_setor = ttk.Frame(frame_tarefas)
        frame_filtro_setor.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        frame_filtro_setor.columnconfigure(0, weight=1)
        
        self.combo_filtro_setor = ttk.Combobox(frame_filtro_setor, state="readonly")
        self.combo_filtro_setor.grid(row=0, column=0, sticky="ew")
        self.combo_filtro_setor.bind("<<ComboboxSelected>>", self.filtrar_tarefas_por_setor)
        
        btn_limpar_filtro = ttk.Button(frame_filtro_setor, text="Limpar Filtro", command=self.limpar_filtro_tarefas)
        btn_limpar_filtro.grid(row=0, column=1, padx=(5,0))

        # Novo Frame para o Filtro
        frame_filtro_tarefas = ttk.Frame(frame_tarefas)
        frame_filtro_tarefas.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        frame_filtro_tarefas.columnconfigure(0, weight=1)

        self.entry_filtro_atr_tarefas = ttk.Entry(frame_filtro_tarefas)
        self.entry_filtro_atr_tarefas.grid(row=0, column=0, sticky="ew")
        
        btn_filtrar = ttk.Button(frame_filtro_tarefas, text="Buscar", command=self.filtrar_lista_tarefas_atribuicao)
        btn_filtrar.grid(row=0, column=1, padx=(5, 0))

        # Lista de Tarefas (agora na linha 1)
        cols_tarefas = ('ID', 'Título')
        self.tree_atr_tarefas = ttk.Treeview(frame_tarefas, columns=cols_tarefas, show='tree headings', selectmode='browse')
        self.tree_atr_tarefas.heading('#0', text='Setor / Tarefa')
        self.tree_atr_tarefas.column('#0', width=300)
        self.tree_atr_tarefas.heading('ID', text='ID')
        self.tree_atr_tarefas.column('ID', width=40, stretch=tk.NO)
        self.tree_atr_tarefas.heading('Título', text='Título Completo')
        self.tree_atr_tarefas.column('Título', width=0, stretch=tk.NO)
        self.tree_atr_tarefas.grid(row=2, column=0, columnspan=2, sticky="nsew") # columnspan=2
        self.tree_atr_tarefas.bind('<<TreeviewSelect>>', self.on_tarefa_selecionada_para_atribuicao)

        # --- PAINEL 2: ALVOS ---
        frame_selecao = ttk.LabelFrame(main_frame, text="2. Selecione o Alvo", padding="10")
        frame_selecao.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.modo_atribuicao = tk.StringVar(value="Individual")
        ttk.Radiobutton(frame_selecao, text="Individual", variable=self.modo_atribuicao, value="Individual", command=self.atualizar_painel_selecao).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(frame_selecao, text="Para Grupo", variable=self.modo_atribuicao, value="Grupo", command=self.atualizar_painel_selecao).pack(side=tk.LEFT, padx=10)

        self.tree_atr_selecao = ttk.Treeview(frame_selecao, columns=('ID', 'Nome'), show='headings', selectmode='extended')
        self.tree_atr_selecao.heading('ID', text='ID')
        self.tree_atr_selecao.column('ID', width=40, stretch=tk.NO)
        self.tree_atr_selecao.heading('Nome', text='Nome')
        self.tree_atr_selecao.column('Nome', width=200)
        self.tree_atr_selecao.pack(fill=tk.BOTH, expand=True, pady=10)

        ttk.Button(main_frame, text="Atribuir Tarefa", command=self.abrir_popup_frequencia_universal).grid(row=1, column=1, sticky="ew", padx=(0, 10), ipady=5)

        # --- PAINEL 3: ATRIBUIÇÕES ATIVAS ---
        frame_ativas = ttk.LabelFrame(main_frame, text="Atribuições Ativas", padding="10")
        frame_ativas.grid(row=0, column=2, sticky="nsew", rowspan=2)
        self.tree_atribuicoes_ativas = ttk.Treeview(frame_ativas, columns=('ID', 'Alvo', 'Tarefa', 'Frequência'), show='headings')

        self.tree_atribuicoes_ativas.heading('ID', text='ID')
        self.tree_atribuicoes_ativas.column('ID', width=40, stretch=tk.NO)
        self.tree_atribuicoes_ativas.heading('Alvo', text='Alvo (Func/Grupo)')
        self.tree_atribuicoes_ativas.column('Alvo', width=150)
        self.tree_atribuicoes_ativas.heading('Tarefa', text='Tarefa')
        self.tree_atribuicoes_ativas.column('Tarefa', width=200)
        self.tree_atribuicoes_ativas.heading('Frequência', text='Frequência')
        self.tree_atribuicoes_ativas.column('Frequência', width=120)

        self.tree_atribuicoes_ativas.pack(fill=tk.BOTH, expand=True)

        ttk.Button(frame_ativas, text="Desatribuir Selecionada", command=self.desatribuir_tarefa_selecionada).pack(pady=10)

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change, add="+")
        self.atualizar_painel_selecao()
        self.popular_combobox_filtro_setor()

    def criar_aba_validacao(self):
        frame_lista = ttk.Frame(self.frame_validacao, padding="10"); frame_lista.pack(side=tk.LEFT, fill=tk.Y)
        frame_titulo_validacao = ttk.Frame(frame_lista); frame_titulo_validacao.pack(fill=tk.X)
        ttk.Label(frame_titulo_validacao, text="Entregas Pendentes", font=("Arial", 14)).pack(side=tk.LEFT)
        btn_atualizar_validacao = ttk.Button(frame_titulo_validacao, text="🔄", command=self.carregar_entregas_pendentes, width=3); btn_atualizar_validacao.pack(side=tk.RIGHT)
        self.lista_entregas = tk.Listbox(frame_lista, height=25, width=50); self.lista_entregas.pack(fill=tk.Y, pady=5); self.lista_entregas.bind('<<ListboxSelect>>', self.mostrar_detalhes_entrega)
        frame_detalhes = ttk.Frame(self.frame_validacao, padding="10"); frame_detalhes.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lbl_nome_funcionario = ttk.Label(frame_detalhes, text="Funcionário: ", font=("Arial", 12)); self.lbl_nome_funcionario.pack(anchor=tk.W)
        self.lbl_titulo_tarefa = ttk.Label(frame_detalhes, text="Tarefa: ", font=("Arial", 12)); self.lbl_titulo_tarefa.pack(anchor=tk.W)
        self.lbl_imagem = ttk.Label(frame_detalhes); self.lbl_imagem.pack(pady=10, fill=tk.BOTH, expand=True)
        frame_botoes = ttk.Frame(frame_detalhes); frame_botoes.pack(side=tk.BOTTOM, pady=10)
        btn_aprovar = ttk.Button(frame_botoes, text="Aprovar", command=self.aprovar_entrega_selecionada); btn_aprovar.pack(side=tk.LEFT, padx=10, ipadx=10, ipady=5)
        btn_recusar = ttk.Button(frame_botoes, text="Recusar", command=self.recusar_entrega_selecionada); btn_recusar.pack(side=tk.LEFT, padx=10, ipadx=10, ipady=5)
        self.carregar_entregas_pendentes()
        
    # Em main.py, SUBSTITUA a função criar_aba_ranking por esta:

    def criar_aba_ranking(self):
        ttk.Label(self.frame_ranking, text="Ranking de Desempenho Mensal", font=("Arial", 16)).pack(pady=10)

        # --- NOVO FRAME PARA FILTRO ---
        frame_filtro_ranking = ttk.Frame(self.frame_ranking, padding=(0, 0, 0, 10))
        frame_filtro_ranking.pack(fill=tk.X, padx=20)

        ttk.Label(frame_filtro_ranking, text="Visualizar Ranking:").pack(side=tk.LEFT, padx=(0, 5))
        self.combo_filtro_setor_ranking = ttk.Combobox(frame_filtro_ranking,
                                                    values=['Geral', 'Cozinha', 'Loja'],
                                                    state="readonly", width=15)
        self.combo_filtro_setor_ranking.pack(side=tk.LEFT)
        self.combo_filtro_setor_ranking.set('Geral') # Padrão
        # Chama atualizar_ranking sempre que o valor do combobox mudar
        self.combo_filtro_setor_ranking.bind("<<ComboboxSelected>>", self.atualizar_ranking)
        # --- FIM DO NOVO FRAME ---

        cols = ('Posição', 'Nome', 'Score Final', 'Desempenho %', 'Pontos Ganhos', 'Pontos Possíveis') # - Colunas originais mantidas
        self.tree_ranking = ttk.Treeview(self.frame_ranking, columns=cols, show='headings') #

        self.tree_ranking.heading('Posição', text='Pos.'); self.tree_ranking.column('Posição', width=40, anchor='center') #
        self.tree_ranking.heading('Nome', text='Funcionário'); self.tree_ranking.column('Nome', width=300) #
        self.tree_ranking.heading('Score Final', text='Score Final'); self.tree_ranking.column('Score Final', width=100, anchor='center') #
        self.tree_ranking.heading('Desempenho %', text='Confiabilidade (%)'); self.tree_ranking.column('Desempenho %', width=120, anchor='center') #
        self.tree_ranking.heading('Pontos Ganhos', text='Pontos (Esforço)'); self.tree_ranking.column('Pontos Ganhos', width=120, anchor='center') #
        self.tree_ranking.heading('Pontos Possíveis', text='Pontos Possíveis'); self.tree_ranking.column('Pontos Possíveis', width=120, anchor='center') #

        self.tree_ranking.pack(fill=tk.BOTH, expand=True, padx=20, pady=5) #
        btn_atualizar_ranking = ttk.Button(self.frame_ranking, text="Atualizar Ranking", command=self.atualizar_ranking) #
        btn_atualizar_ranking.pack(pady=10) #

        self.atualizar_ranking() # - Chama ao iniciar a aba


    def atualizar_ranking(self, event=None): # <<< CORREÇÃO: Adicionado event=None para suportar o bind do Combobox
        # Limpa a tabela antes de tentar buscar novos dados
        for i in self.tree_ranking.get_children(): self.tree_ranking.delete(i)

        try:
            # Captura o valor do filtro selecionado na interface
            setor_selecionado = self.combo_filtro_setor_ranking.get()

            # Converte o nome do combo para o parâmetro que o banco espera
            filtro_db = None
            if setor_selecionado == 'Cozinha':
                filtro_db = 'Cozinha'
            elif setor_selecionado == 'Loja':
                filtro_db = 'Loja'

            # Busca os dados filtrados
            ranking_data = database.calcular_ranking_desempenho(setor_filtro=filtro_db)

            if not ranking_data:
                self.tree_ranking.insert("", "end", values=("Sem dados para este filtro.", "", "", "", "", ""))
            else:
                for i, row in enumerate(ranking_data):
                    posicao = f"{i+1}º"
                    nome = row['NomeCompleto']
                    score_final = f"{row['ScoreHibrido']}"
                    desempenho = f"{row['Desempenho']}%"
                    ganhos = row['PontosGanhos']
                    possiveis = row['PontosPossiveis']
                    self.tree_ranking.insert("", "end", values=(posicao, nome, score_final, desempenho, ganhos, possiveis))
        except Exception as e:
            logger.exception(f"Erro ao atualizar o ranking na interface gráfica: {e}")
            self.tree_ranking.insert("", "end", values=("Erro ao carregar dados.", "", "", "", "", ""))
            messagebox.showerror("Erro de Ranking", f"Não foi possível carregar os dados do ranking:\n{e}", parent=self.root)

    def criar_aba_relatorios(self):
        frame_principal = ttk.Frame(self.frame_relatorios, padding="10")
        frame_principal.pack(fill=tk.BOTH, expand=True)
        frame_principal.columnconfigure(1, weight=1) # Coluna da direita (resultados) cresce
        frame_principal.rowconfigure(0, weight=1)    # A linha inteira cresce

        frame_selecao = ttk.LabelFrame(frame_principal, text="Tipos de Relatório", padding="10")
        frame_selecao.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        self.lista_relatorios = tk.Listbox(frame_selecao, exportselection=False)
        self.lista_relatorios.pack(fill=tk.Y, expand=True)

        self.lista_relatorios.insert(tk.END, "Pendências Recorrentes")
        self.lista_relatorios.insert(tk.END, "Análise de Tarefas")
        self.lista_relatorios.insert(tk.END, "Resgates do Mês (Consolidado)")
        self.lista_relatorios.bind('<<ListboxSelect>>', self.on_report_select)

        self.lista_relatorios.select_set(0)

        self.frame_conteudo_relatorio = ttk.Frame(frame_principal)
        self.frame_conteudo_relatorio.grid(row=0, column=1, sticky="nsew")

        self.on_report_select(None)

    def on_report_select(self, event):
        """
        Chamada sempre que um relatório é selecionado na lista.
        Ela limpa o painel da direita e constrói a interface para o relatório escolhido.
        """
        selecionado_indices = self.lista_relatorios.curselection()
        if not selecionado_indices:
            return 
        
        nome_relatorio = self.lista_relatorios.get(selecionado_indices[0])

        for widget in self.frame_conteudo_relatorio.winfo_children():
            widget.destroy()

        if nome_relatorio == "Pendências Recorrentes":
            self.construir_ui_relatorio_pendencias()
        elif nome_relatorio == "Análise de Tarefas":
            self.construir_ui_relatorio_analise_tarefas()
        elif nome_relatorio == "Resgates do Mês (Consolidado)":
            self.construir_ui_relatorio_resgates()

    def criar_aba_feedbacks(self):
        """Cria todos os widgets para a aba de visualização de feedbacks."""
        frame_principal = ttk.Frame(self.frame_feedbacks, padding="10")
        frame_principal.pack(fill="both", expand=True)
        ttk.Label(frame_principal, text="Análise de Feedbacks dos Colaboradores", font=("Arial", 16)).pack(pady=10)

        frame_filtros = ttk.LabelFrame(frame_principal, text="Filtros", padding="10")
        frame_filtros.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_filtros, text="Funcionário:").pack(side="left", padx=(0, 5))
        self.combo_funcionarios_feedback = ttk.Combobox(frame_filtros, state="readonly", width=30)
        self.combo_funcionarios_feedback.pack(side="left")

        ttk.Label(frame_filtros, text="De:").pack(side="left", padx=(20, 5))
        self.entry_data_inicio_feedback = ttk.Entry(frame_filtros, width=12)
        self.entry_data_inicio_feedback.pack(side="left")
        self.entry_data_inicio_feedback.insert(0, "AAAA-MM-DD")

        ttk.Label(frame_filtros, text="Até:").pack(side="left", padx=5)
        self.entry_data_fim_feedback = ttk.Entry(frame_filtros, width=12)
        self.entry_data_fim_feedback.pack(side="left")
        self.entry_data_fim_feedback.insert(0, "AAAA-MM-DD")

        btn_filtrar = ttk.Button(frame_filtros, text="Filtrar", command=self.atualizar_lista_feedbacks)
        btn_filtrar.pack(side="left", padx=20)
        btn_limpar = ttk.Button(frame_filtros, text="Limpar Filtros", command=self.limpar_filtros_feedback)
        btn_limpar.pack(side="left")

        frame_resultados = ttk.Frame(frame_principal)
        frame_resultados.pack(fill="x", padx=10, pady=10)
        self.lbl_media_feedback = ttk.Label(frame_resultados, text="Nota Média do Período: --", font=("Arial", 12, "bold"))
        self.lbl_media_feedback.pack(side="right")

        frame_lista = ttk.Frame(frame_principal)
        frame_lista.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ('ID', 'Funcionário', 'Data', 'Nota')
        self.tree_feedbacks = ttk.Treeview(frame_lista, columns=cols, show='headings')

        self.tree_feedbacks.heading('ID', text='ID')
        self.tree_feedbacks.column('ID', width=50, anchor='center')
        self.tree_feedbacks.heading('Funcionário', text='Funcionário')
        self.tree_feedbacks.column('Funcionário', width=300)
        self.tree_feedbacks.heading('Data', text='Data')
        self.tree_feedbacks.column('Data', width=150, anchor='center')
        self.tree_feedbacks.heading('Nota', text='Nota')
        self.tree_feedbacks.column('Nota', width=80, anchor='center')

        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.tree_feedbacks.yview)
        self.tree_feedbacks.configure(yscrollcommand=scrollbar.set)

        self.tree_feedbacks.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")

        self.carregar_funcionarios_feedback()
        self.atualizar_lista_feedbacks()
    

    def on_tab_change(self, event):
            """Chamada sempre que uma aba do notebook principal é alterada."""
            try:
                tab_text = event.widget.tab(event.widget.select(), "text")

                tab_map = {
                    "Gerenciar Grupos": self.atualizar_lista_grupos,
                    "Atribuir Tarefas": self.on_tab_atribuir_tarefas_selected,
                    "Dashboard": self.atualizar_dashboard_completo,
                    "Ranking": self.atualizar_ranking,
                    "Gerenciar Funcionários": self.atualizar_lista_funcionarios,
                    "Catálogo de Tarefas": self.atualizar_catalogo_tarefas,
                    "Loja e Resgates": self.carregar_dados_loja,
                    # "Gestão de Metas" é tratado abaixo
                    "Gerenciar Conquistas": self.atualizar_lista_conquistas,
                }

                if tab_text == "Gestão de Metas":
                    # A aba de Metas tem duas funções de carregamento
                    self.carregar_dados_metas()
                    self.atualizar_lista_lucros() 
                    return # Sai para não chamar a outra
                
                if tab_text == "Consultar NFs":
                    self.carregar_filtros_nf()
                    # self.buscar_historico_nfs() # Opcional: recarregar automaticamente ao clicar na aba
                    return

                if tab_text in tab_map:
                    # Se estiver, executa a função correspondente
                    tab_map[tab_text]()

            except tk.TclError:
                pass        
    
    def on_tab_atribuir_tarefas_selected(self):
        self.atualizar_lista_tarefas_atribuicao()
        self.atualizar_painel_selecao()
        self.atualizar_lista_atribuicoes_ativas()

    def carregar_dados_loja(self):
        for i in self.tree_produtos_loja.get_children(): self.tree_produtos_loja.delete(i)
        produtos = database.listar_produtos_loja(incluir_inativos=True)
        for p in produtos:
            estoque = p.EstoqueDisponivel if p.EstoqueDisponivel is not None else "Ilimitado"
            status = "Ativo" if p.Ativo else "Inativo"
            self.tree_produtos_loja.insert("", "end", values=(p.ProdutoID, p.Nome, p.CustoEmPontos, estoque, status))

        for i in self.tree_resgates_pendentes.get_children(): self.tree_resgates_pendentes.delete(i)
        resgates = database.listar_resgates_pendentes()
        for r in resgates:
            data_f = r.DataSolicitacao.strftime("%d/%m/%Y %H:%M")
            self.tree_resgates_pendentes.insert("", "end", values=(r.ResgateID, r.NomeCompleto, r.Nome, data_f))

    def aprovar_resgate_selecionado(self):
        selecionado = self.tree_resgates_pendentes.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um resgate pendente para aprovar.", parent=self.root)
            return

        dados_resgate = self.tree_resgates_pendentes.item(selecionado, 'values')
        resgate_id = dados_resgate[0]
        
        sucesso = database.aprovar_resgate(resgate_id, config.ID_GESTOR_PADRAO)
        
        if sucesso:
            dados_notificacao = database.buscar_dados_resgate_para_notificacao(resgate_id)
            if dados_notificacao:
                mensagem = (f"✅ **Seu resgate foi APROVADO!** ✅\n\n"
                            f"🎁 **Produto:** {dados_notificacao.Nome}\n\n"
                            "Procure seu gestor para combinar a retirada do seu prêmio. Parabéns!")
                notificador_telegram.enviar_mensagem(dados_notificacao.ChatIDTelegram, mensagem)
            
            messagebox.showinfo("Sucesso", "Resgate aprovado! O funcionário foi notificado.", parent=self.root)
            self.carregar_dados_loja()
        else:
            messagebox.showerror("Erro", "Não foi possível aprovar o resgate.", parent=self.root)

    def recusar_resgate_selecionado(self):
        selecionado = self.tree_resgates_pendentes.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um resgate para recusar.", parent=self.root)
            return

        motivo = simpledialog.askstring("Motivo da Recusa", "Por favor, digite o motivo da recusa (será enviado ao funcionário):", parent=self.root)
        if not motivo:
            messagebox.showinfo("Cancelado", "Ação cancelada.", parent=self.root)
            return

        dados_resgate = self.tree_resgates_pendentes.item(selecionado, 'values')
        resgate_id = dados_resgate[0]
        GESTOR_ID = 2 # Novamente, assumindo GESTOR_ID = 2
        
        sucesso = database.recusar_resgate(resgate_id, GESTOR_ID)
        
        if sucesso:
            dados_notificacao = database.buscar_dados_resgate_para_notificacao(resgate_id)
            if dados_notificacao:
                mensagem = (f"❌ **Seu resgate foi RECUSADO.** ❌\n\n"
                            f"🎁 **Produto:** {dados_notificacao.Nome}\n"
                            f"📝 **Motivo:** {motivo}\n\n"
                            "Os pontos foram estornados para o seu saldo. Fale com seu gestor para mais detalhes.")
                notificador_telegram.enviar_mensagem(dados_notificacao.ChatIDTelegram, mensagem)
            
            messagebox.showinfo("Sucesso", "Resgate recusado. Os pontos foram devolvidos e o funcionário notificado.", parent=self.root)
            self.carregar_dados_loja()
        else:
            messagebox.showerror("Erro", "Não foi possível recusar o resgate.", parent=self.root)

    def abrir_janela_produto(self, editar=False):
        dados_produto = None
        if editar:
            selecionado = self.tree_produtos_loja.focus()
            if not selecionado:
                messagebox.showwarning("Aviso", "Selecione um produto para editar.", parent=self.root)
                return
            produto_id = self.tree_produtos_loja.item(selecionado, 'values')[0]
            produtos = database.listar_produtos_loja(incluir_inativos=True)
            dados_produto = next((p for p in produtos if p.ProdutoID == int(produto_id)), None)

        popup = Toplevel(self.root)
        popup.title("Criar/Editar Produto da Loja")
        popup.geometry("400x350")
        
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Nome do Produto:").grid(row=0, column=0, sticky="w", pady=2)
        entry_nome = ttk.Entry(frame, width=40)
        entry_nome.grid(row=0, column=1, pady=2)

        ttk.Label(frame, text="Descrição:").grid(row=1, column=0, sticky="w", pady=2)
        entry_desc = ttk.Entry(frame, width=40)
        entry_desc.grid(row=1, column=1, pady=2)

        ttk.Label(frame, text="Custo em Pontos:").grid(row=2, column=0, sticky="w", pady=2)
        entry_custo = ttk.Entry(frame, width=20)
        entry_custo.grid(row=2, column=1, sticky="w", pady=2)

        ttk.Label(frame, text="Estoque (deixe em branco para infinito):").grid(row=3, column=0, sticky="w", pady=2)
        entry_estoque = ttk.Entry(frame, width=20)
        entry_estoque.grid(row=3, column=1, sticky="w", pady=2)

        var_ativo = tk.BooleanVar(value=True)
        check_ativo = ttk.Checkbutton(frame, text="Produto Ativo (visível na loja)", variable=var_ativo)
        check_ativo.grid(row=4, columnspan=2, pady=10)
        
        if editar and dados_produto:
            entry_nome.insert(0, dados_produto.Nome)
            entry_desc.insert(0, dados_produto.Descricao or "")
            entry_custo.insert(0, dados_produto.CustoEmPontos)
            entry_estoque.insert(0, dados_produto.EstoqueDisponivel or "")
            var_ativo.set(dados_produto.Ativo)

        def salvar():
            nome = entry_nome.get()
            desc = entry_desc.get()
            custo_str = entry_custo.get()
            estoque_str = entry_estoque.get()
            ativo = var_ativo.get()

            if not nome or not custo_str:
                messagebox.showerror("Erro", "Nome e Custo são obrigatórios.", parent=popup)
                return
            try:
                custo = int(custo_str)
                estoque = int(estoque_str) if estoque_str else None
                
                if editar:
                    database.atualizar_produto_loja(dados_produto.ProdutoID, nome, desc, custo, estoque, ativo)
                else:
                    database.criar_produto_loja(nome, desc, custo, estoque, ativo)
                
                self.carregar_dados_loja()
                popup.destroy()
            except ValueError:
                messagebox.showerror("Erro de Formato", "Custo e Estoque devem ser números.", parent=popup)

        btn_salvar = ttk.Button(frame, text="Salvar", command=salvar)
        btn_salvar.grid(row=5, columnspan=2, pady=20)

    def on_tarefa_selecionada_para_atribuicao(self, event):
        """
        (VERSÃO CORRIGIDA)
        Chamada sempre que um item é selecionado na árvore de tarefas.
        """
        for i in self.tree_atribuicoes_ativas.get_children():
            self.tree_atribuicoes_ativas.delete(i)

        selecionado = self.tree_atr_tarefas.focus()
        if not selecionado: # Se nada estiver selecionado, não faz nada
            return

        values = self.tree_atr_tarefas.item(selecionado, 'values')

        if not values or not values[0]:
            self.atualizar_painel_selecao() # Limpa o painel do meio
            return # Para a execução aqui
        tarefa_id_selecionada = values[0]
        tarefa_titulo_selecionado = values[1]

        if self.modo_atribuicao.get() == "Individual":
            self.atualizar_painel_selecao(tarefa_id=tarefa_id_selecionada)
        else:
            self.atualizar_painel_selecao()

        for atribuicao in database.listar_atribuicoes_ativas():
            if atribuicao[2] == tarefa_titulo_selecionado:
                self.tree_atribuicoes_ativas.insert("", "end", values=atribuicao)

    def adicionar_novo_funcionario(self):
        nome = self.entry_nome.get()
        chat_id = self.entry_chat_id.get()
        cargo = self.entry_cargo.get()
        horario = self.entry_horario.get()
        dia_folga_texto = self.combo_folga.get()

        dia_folga_valor = self.dias_semana_mapa.get(dia_folga_texto, 0)

        if not all([nome, chat_id, cargo, horario]): 

            messagebox.showerror("Erro", "Todos os campos, exceto a folga, são obrigatórios!")
            return
        
        # [CORREÇÃO] Validação de Chat ID numérico
        # Remove espaços e traços (para grupos) e verifica se o resto são dígitos.
        # Isso previne erros na API do Telegram que exige inteiros.
        if not chat_id.lstrip('-').isdigit():
            messagebox.showerror("Erro de Formato", "O Chat ID deve conter apenas números (ex: 123456789 ou -100...).")
            return

        # --- NOVA VALIDAÇÃO DE HORÁRIO ---
        try:
            datetime.strptime(horario, '%H:%M') # Tenta converter para validar o formato
        except ValueError:
            messagebox.showerror("Erro de Formato", "O Horário de Notificação deve estar no formato HH:MM (ex: 08:30).")
            return # Impede o salvamento se o formato for inválido
        # --- FIM DA VALIDAÇÃO ---
        # 1. Cria o funcionário (Insert padrão)
        database.adicionar_funcionario(nome, chat_id, cargo, horario, dia_folga_valor)
        # 2. Atualiza o Verificador de Segurança (Se fornecido)
        # Abordagem conservadora: Busca o ID recém-criado pelo ChatID (único) e faz update
        verificador = self.entry_verificador_novo.get() if hasattr(self, 'entry_verificador_novo') else None

        if verificador:
            if len(verificador) == 3 and verificador.isdigit():
                novo_func = database.buscar_funcionario_por_chat_id(chat_id)
                # [CORREÇÃO] Validação defensiva: só tenta atualizar se o funcionário foi realmente encontrado/criado
                if novo_func and hasattr(novo_func, 'FuncionarioID'):
                    database.atualizar_verificador_cpf(novo_func.FuncionarioID, verificador)
                else:
                    logger.error(f"Erro: Funcionário com ChatID {chat_id} não encontrado após tentativa de criação.")
                    messagebox.showwarning("Aviso", "Funcionário criado, mas houve erro ao vincular o Verificador CPF (Retorno Nulo). Tente editar depois.")
            else:
                messagebox.showwarning("Aviso", "Funcionário criado, mas o Verificador de CPF foi ignorado (deve ter 3 dígitos). Edite o cadastro depois.")
        messagebox.showinfo("Sucesso", f"Funcionário {nome} adicionado com sucesso!")
        # Limpeza dos campos
        self.entry_nome.delete(0, tk.END)
        self.entry_chat_id.delete(0, tk.END)
        self.entry_cargo.delete(0, tk.END)
        self.entry_horario.delete(0, tk.END); self.entry_horario.insert(0, "08:00")
        self.combo_folga.set('Sem Folga Definida')
        if hasattr(self, 'entry_verificador_novo'): self.entry_verificador_novo.delete(0, tk.END)        # --- Campo Novo: Verificador CPF ---
        ttk.Label(frame_direita_add, text="Verificador CPF (3 primeiros dígitos):").pack(pady=(10, 2))
        self.entry_verificador_novo = ttk.Entry(frame_direita_add, width=10)
        self.entry_verificador_novo.pack()
        # -----------------------------------
        
        self.atualizar_todas_as_listas()

    def abrir_janela_edicao_funcionario(self):
        indices = self.lista_funcionarios.curselection()
        if not indices:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário da lista para editar.")
            return
        
        texto_selecionado = self.lista_funcionarios.get(indices[0])
        funcionario_selecionado = self.dados_funcionarios[texto_selecionado]

        self.edit_window = tk.Toplevel(self.root)
        self.edit_window.title("Editar Funcionário")
        
        frame_edicao = ttk.Frame(self.edit_window, padding="20")
        frame_edicao.pack(fill="both", expand=True)

        ttk.Label(frame_edicao, text="Nome Completo:").grid(row=0, column=0, sticky="w", pady=5)
        edit_entry_nome = ttk.Entry(frame_edicao, width=40)
        edit_entry_nome.grid(row=0, column=1, pady=5)
        edit_entry_nome.insert(0, funcionario_selecionado.NomeCompleto)

        ttk.Label(frame_edicao, text="ID do Chat Telegram:").grid(row=1, column=0, sticky="w", pady=5)
        edit_entry_chat_id = ttk.Entry(frame_edicao, width=40)
        edit_entry_chat_id.grid(row=1, column=1, pady=5)
        edit_entry_chat_id.insert(0, funcionario_selecionado.ChatIDTelegram)

        ttk.Label(frame_edicao, text="Cargo:").grid(row=2, column=0, sticky="w", pady=5)
        edit_entry_cargo = ttk.Entry(frame_edicao, width=40)
        edit_entry_cargo.grid(row=2, column=1, pady=5)
        edit_entry_cargo.insert(0, funcionario_selecionado.Cargo)

        ttk.Label(frame_edicao, text="Horário de Notificação (HH:MM):").grid(row=3, column=0, sticky="w", pady=5)
        edit_entry_horario = ttk.Entry(frame_edicao, width=40)
        edit_entry_horario.grid(row=3, column=1, pady=5)
        horario = funcionario_selecionado.HorarioNotificacao if funcionario_selecionado.HorarioNotificacao else ""
        edit_entry_horario.insert(0, horario)
        ttk.Label(frame_edicao, text="Folga Semanal:").grid(row=4, column=0, sticky="w", pady=5)
        dias_semana_lista = list(self.dias_semana_mapa.keys())
        edit_combo_folga = ttk.Combobox(frame_edicao, state="readonly", values=dias_semana_lista)
        edit_combo_folga.grid(row=4, column=1, pady=5)

        ttk.Label(frame_edicao, text="Verificador de Segurança (3 dígitos CPF):").grid(row=5, column=0, sticky="w", pady=5)
        edit_entry_verificador = ttk.Entry(frame_edicao, width=10)
        edit_entry_verificador.grid(row=5, column=1, sticky="w", pady=5)
        verificador_atual = getattr(funcionario_selecionado, 'VerificadorCPF', '')
        edit_entry_verificador.insert(0, verificador_atual or "")

        folga_atual_num = getattr(funcionario_selecionado, 'DiaDeFolga', 0)
        folga_atual_texto = next((nome for nome, num in self.dias_semana_mapa.items() if num == folga_atual_num), 'Sem Folga Definida')
        edit_combo_folga.set(folga_atual_texto)

        btn_salvar = ttk.Button(frame_edicao, text="Salvar Alterações", 
                        command=lambda: self.salvar_edicao_funcionario(
                            funcionario_selecionado.FuncionarioID, 
                            edit_entry_nome.get(), 
                            edit_entry_chat_id.get(), 
                            edit_entry_cargo.get(), 
                            edit_entry_horario.get(),
                            edit_combo_folga.get(),
                            edit_entry_verificador.get() # Passa o novo valor
                        ))
        btn_salvar.grid(row=6, columnspan=2, pady=20)

    def salvar_edicao_funcionario(self, func_id, nome, chat_id, cargo, horario, dia_folga_texto, verificador_cpf): # 1. Novo parâmetro
        dia_folga_valor = self.dias_semana_mapa.get(dia_folga_texto, 0)
        
        if verificador_cpf and len(verificador_cpf) != 3:
            messagebox.showerror("Erro", "O Verificador de Segurança deve ter exatamente 3 dígitos.")
            return
                    # --- NOVA VALIDAÇÃO DE HORÁRIO ---
        try:
            # Adiciona um check extra para permitir horário vazio (se for o caso)
            if horario and horario.strip(): # Só valida se não estiver vazio
                datetime.strptime(horario, '%H:%M') # Tenta converter para validar o formato
            # Se estiver vazio, assume que é válido (ou ajuste a regra se horário for obrigatório)
        except ValueError:
            messagebox.showerror("Erro de Formato", "O Horário de Notificação deve estar no formato HH:MM (ex: 08:30) ou vazio.")
            # Garante que a janela de edição não seja fechada
            if hasattr(self, 'edit_window') and self.edit_window.winfo_exists():
                self.edit_window.focus_force() # Traz a janela de edição para frente
            return # Impede o salvamento se o formato for inválido
        # --- FIM DA VALIDAÇÃO ---

        # Se passou nas validações, continua com o salvamento
        # (A linha abaixo já existe, apenas continue a partir daqui)
        # database.atualizar_funcionario(func_id, nome, chat_id, cargo, horario, dia_folga_valor, verificador_cpf)

        database.atualizar_funcionario(func_id, nome, chat_id, cargo, horario, dia_folga_valor, verificador_cpf)
        
        messagebox.showinfo("Sucesso", "Funcionário atualizado com sucesso.")
        self.edit_window.destroy()
        self.atualizar_todas_as_listas()

    def excluir_funcionario_selecionado(self):
        indices = self.lista_funcionarios.curselection()
        if not indices:
            messagebox.showwarning("Aviso", "Selecione um funcionário para excluir.")
            return
            
        texto = self.lista_funcionarios.get(indices[0])
        funcionario = self.dados_funcionarios[texto]

        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir '{funcionario.NomeCompleto}'?\n\nTODAS as suas tarefas e entregas serão apagadas permanentemente."):
            database.excluir_funcionario(funcionario.FuncionarioID)
            messagebox.showinfo("Sucesso", "Funcionário excluído.")
            self.atualizar_todas_as_listas()

    def abrir_janela_historico(self):
        """
        Abre uma nova janela para mostrar o histórico completo de tarefas
        e entregas do funcionário selecionado.
        """
        indices = self.lista_funcionarios.curselection()
        if not indices:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário da lista para ver o histórico.")
            return

        texto_selecionado = self.lista_funcionarios.get(indices[0])
        funcionario = self.dados_funcionarios[texto_selecionado]
        funcionario_id = funcionario.FuncionarioID

        historico = database.obter_historico_funcionario(funcionario_id)

        popup_historico = Toplevel(self.root)
        popup_historico.title(f"Histórico de - {funcionario.NomeCompleto}")
        popup_historico.geometry("800x500")
        popup_historico.transient(self.root) # Faz a janela ficar sobre a principal.

        frame_lista = ttk.Frame(popup_historico, padding="10")
        frame_lista.pack(fill="both", expand=True)
        frame_lista.grid_rowconfigure(0, weight=1)
        frame_lista.grid_columnconfigure(0, weight=1)

        cols = ('Tarefa', 'Atribuído em', 'Enviado em', 'Status', 'Pontos', 'Observação')
        tree_historico = ttk.Treeview(frame_lista, columns=cols, show='headings')

        # Configura os cabeçalhos e tamanhos das colunas
        tree_historico.heading('Tarefa', text='Tarefa')
        tree_historico.heading('Atribuído em', text='Atribuído em')
        tree_historico.column('Atribuído em', width=120, anchor='center')
        tree_historico.heading('Enviado em', text='Enviado em')
        tree_historico.column('Enviado em', width=120, anchor='center')
        tree_historico.heading('Status', text='Status')
        tree_historico.column('Status', width=100, anchor='center')
        tree_historico.heading('Pontos', text='Pontos')
        tree_historico.column('Pontos', width=60, anchor='center')
        tree_historico.heading('Observação', text='Observação')
        tree_historico.column('Observação', width=200)

        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=tree_historico.yview)
        tree_historico.configure(yscrollcommand=scrollbar.set)
        
        tree_historico.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        if not historico:
            tree_historico.insert("", "end", values=("Nenhum histórico encontrado.", "", "", "", "", ""))
        else:
            for item in historico:
                data_atribuicao = item.DataAtribuicao.strftime("%d/%m/%Y") if item.DataAtribuicao else "---"
                data_envio = item.DataEnvio.strftime("%d/%m/%Y %H:%M") if item.DataEnvio else "---"
                pontos = item.PontosGanhos if item.PontosGanhos is not None else 0
                obs = item.MotivoRecusa if item.MotivoRecusa else ""
                
                tree_historico.insert("", "end", values=(item.Titulo, data_atribuicao, data_envio, item.Status, pontos, obs))


    def zerar_pontos_do_funcionario_selecionado(self):
        """
        (VERSÃO ATUALIZADA)
        Chama a função "bomba atômica" para limpar o histórico de entregas
        do funcionário selecionado DENTRO DO MÊS CORRENTE.
        """
        indices = self.lista_funcionarios.curselection()
        if not indices:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário da lista.")
            return

        texto_selecionado = self.lista_funcionarios.get(indices[0])
        funcionario = self.dados_funcionarios[texto_selecionado]

        confirmacao = messagebox.askyesno(
            "!! AÇÃO DESTRUTIVA !!",
            f"Você está prestes a APAGAR PERMANENTEMENTE todo o histórico de entregas de '{funcionario.NomeCompleto}' para o mês corrente.\n\n"
            f"Isso irá zerar seu desempenho no ranking atual.\n\n"
            f"Esta ação NÃO PODE SER DESFEITA.\n\n"
            f"Deseja continuar?",
            icon='warning'
        )

        if confirmacao:
            database.limpar_entregas_do_mes_por_funcionario(funcionario.FuncionarioID)
            messagebox.showinfo("Sucesso", f"O histórico de entregas de {funcionario.NomeCompleto} para este mês foi limpo com sucesso.")
            self.atualizar_todas_as_listas()                

    def abrir_janela_pendencias(self):
        """Abre uma janela para mostrar as tarefas pendentes de hoje do funcionário selecionado."""
        indices = self.lista_funcionarios.curselection()
        if not indices:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário da lista.")
            return

        texto_selecionado = self.lista_funcionarios.get(indices[0])
        funcionario = self.dados_funcionarios[texto_selecionado]

        tarefas_pendentes = database.listar_tarefas_do_dia_por_funcionario(funcionario.FuncionarioID)

        popup_pendencias = Toplevel(self.root)
        popup_pendencias.title(f"Pendências de Hoje - {funcionario.NomeCompleto}")
        popup_pendencias.geometry("600x400")
        popup_pendencias.transient(self.root)

        if not tarefas_pendentes:
            ttk.Label(popup_pendencias, text="Nenhuma tarefa pendente para hoje!", font=("Arial", 12)).pack(pady=20, padx=20)
            return

        frame_lista = ttk.Frame(popup_pendencias, padding="10")
        frame_lista.pack(fill="both", expand=True)
        
        cols = ('ID Atribuição', 'Tarefa', 'Pontos')
        tree_pendencias = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')

        tree_pendencias.heading('ID Atribuição', text='ID')
        tree_pendencias.column('ID Atribuição', width=60, anchor='center')
        tree_pendencias.heading('Tarefa', text='Tarefa Pendente')
        tree_pendencias.column('Tarefa', width=300)
        tree_pendencias.heading('Pontos', text='Pontos')
        tree_pendencias.column('Pontos', width=80, anchor='center')

        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=tree_pendencias.yview)
        tree_pendencias.configure(yscrollcommand=scrollbar.set)
        
        tree_pendencias.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")

        for tarefa in tarefas_pendentes: # <--- Linha com recuo CORRETO
            tree_pendencias.insert("", "end", values=(tarefa.AtribuicaoID, tarefa.Titulo, tarefa.Pontos))

    def salvar_tarefa(self):
        titulo = self.entry_tarefa_titulo.get()
        descricao = self.text_tarefa_descricao.get("1.0", tk.END).strip()
        pontos = self.entry_tarefa_pontos.get()
        setor = self.combo_setor_tarefa.get() # <<< CAPTURAMOS O VALOR DO SETOR

        if not all([titulo, descricao, pontos]):
            messagebox.showerror("Erro", "Título, Descrição e Pontos são obrigatórios!")
            return
        try:
            pontos_int = int(pontos)
            if self.tarefa_selecionada_para_edicao:
                tarefa_id = self.tarefa_selecionada_para_edicao.TarefaID
                database.atualizar_tarefa(tarefa_id, titulo, descricao, pontos_int, setor)
                messagebox.showinfo("Sucesso", "Modelo de tarefa atualizado!")
            else:
                database.criar_tarefa(titulo, descricao, pontos_int, setor)
                messagebox.showinfo("Sucesso", "Modelo de tarefa criado!")
            self.limpar_formulario_tarefa()
            self.atualizar_todas_as_listas()
        except ValueError:
            messagebox.showerror("Erro", "O campo 'Pontos' deve ser um número.")
        except Exception as e:
            messagebox.showerror("Erro no Banco de Dados", f"Ocorreu um erro: {e}")

    def limpar_formulario_tarefa(self):
        self.tarefa_selecionada_para_edicao = None; self.entry_tarefa_titulo.delete(0, tk.END)
        self.text_tarefa_descricao.delete("1.0", tk.END); self.entry_tarefa_pontos.delete(0, tk.END)
        self.combo_setor_tarefa.set('') # Limpa o valor selecionado
        self.atualizar_combobox_setores() # Atualiza a lista de sugestões
        self.btn_salvar_tarefa.config(text="Criar Modelo de Tarefa")

    def selecionar_tarefa_para_edicao(self, event):
        selecionado = self.tree_tarefas.focus()
        if not selecionado: return
        dados_tarefa = self.tree_tarefas.item(selecionado, 'values'); tarefa_id = dados_tarefa[0]
        tarefas_completas = database.listar_todas_as_tarefas(); tarefa_completa = next((t for t in tarefas_completas if t.TarefaID == int(tarefa_id)), None)
        if tarefa_completa:
            self.limpar_formulario_tarefa(); self.tarefa_selecionada_para_edicao = tarefa_completa
            self.entry_tarefa_titulo.insert(0, tarefa_completa.Titulo); self.text_tarefa_descricao.insert("1.0", tarefa_completa.Descricao)
            self.entry_tarefa_pontos.insert(0, tarefa_completa.Pontos)
            self.combo_setor_tarefa.set(tarefa_completa.Setor or '')
            self.btn_salvar_tarefa.config(text="Salvar Alterações")

    def excluir_tarefa_selecionada(self):
        selecionado = self.tree_tarefas.focus()
        if not selecionado: messagebox.showwarning("Aviso", "Selecione um modelo da lista para excluir."); return
        dados_tarefa = self.tree_tarefas.item(selecionado, 'values'); tarefa_id = dados_tarefa[0]; titulo_tarefa = dados_tarefa[1]
        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o modelo de tarefa '{titulo_tarefa}'?\n\nTODAS as suas atribuições e entregas relacionadas serão apagadas permanentemente."):
            database.excluir_tarefa(tarefa_id); messagebox.showinfo("Sucesso", "Modelo de tarefa excluído com sucesso.")
            self.limpar_formulario_tarefa(); self.atualizar_todas_as_listas()

    def aprovar_entrega_selecionada(self):
        indices = self.lista_entregas.curselection()
        if not indices: messagebox.showwarning("Aviso", "...", parent=self.root); return # Adicionado parent
        try: # <--- ADICIONADO TRY
            texto = self.lista_entregas.get(indices[0])
            entrega_id = int(texto.split(" | ")[0].split(": ")[1]) # int() pode falhar
            entrega_atual = self.dados_entregas[entrega_id] # Pode dar KeyError

            # Aprova e busca novas conquistas (pode falhar)
            novas_conquistas_ganhas = database.aprovar_entrega(entrega_atual.EntregaID, entrega_atual.FuncionarioID, entrega_atual.Pontos)

            texto_notificacao = f"🎉 Parabéns, <b>{entrega_atual.NomeCompleto}</b>! ... Você ganhou <b>{entrega_atual.Pontos}</b> pontos. ..."
            if novas_conquistas_ganhas:
                for conquista in novas_conquistas_ganhas:
                    # Apenas monta a string da notificação
                    texto_notificacao += (
                        f"\n\n✨ <b>NOVA CONQUISTA DESBLOQUEADA!</b> ✨\n"
                        f"{conquista.Icone} <b>{conquista.Nome}</b>\n"
                        f"<i>{conquista.Descricao}</i>\n"
                        f"Você ganhou um bônus de <b>{conquista.PontosBonus}</b> pontos!"
                    )

                    # --- CORREÇÃO: Lógica movida para DENTRO do loop ---
                    # Agora cada conquista soma seus pontos ao saldo individualmente.
                    if conquista.PontosBonus > 0:
                        database.adicionar_pontos_ao_saldo(entrega_atual.FuncionarioID, conquista.PontosBonus)
                    # ---------------------------------------------------

            # Executa notificação em thread para não travar a UI
            def enviar_notificacao_bg():
                try:
                    notificador_telegram.enviar_mensagem(entrega_atual.ChatIDTelegram, texto_notificacao)
                except Exception as e:
                    logger.error(f"Falha ao enviar notificação em background: {e}")

            threading.Thread(target=enviar_notificacao_bg, daemon=True).start()

            messagebox.showinfo("Sucesso", "Entrega aprovada e pontuação atribuída!", parent=self.root) # Adicionado parent
            self.atualizar_todas_as_listas() # Pode falhar
        except (ValueError, KeyError) as e_parse: # <--- ADICIONADO EXCEPT ESPECÍFICO
            logger.error(f"Erro ao processar seleção da entrega: {e_parse}")
            messagebox.showerror("Erro Interno", f"Não foi possível processar a entrega selecionada:\n{e_parse}", parent=self.root)
        except Exception as e: # <--- ADICIONADO EXCEPT GENÉRICO
            logger.exception(f"Erro ao aprovar entrega ID {entrega_id if 'entrega_id' in locals() else 'N/A'}: {e}")
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao aprovar a entrega:\n{e}", parent=self.root)
    
    def recusar_entrega_selecionada(self):
        indices = self.lista_entregas.curselection()
        if not indices: messagebox.showwarning("Aviso", "...", parent=self.root); return # Adicionado parent
        try: # <--- ADICIONADO TRY
            texto = self.lista_entregas.get(indices[0])
            entrega_id = int(texto.split(" | ")[0].split(": ")[1]) # int() pode falhar
            entrega_atual = self.dados_entregas[entrega_id] # Pode dar KeyError

            motivo = simpledialog.askstring("Motivo da Recusa", "...", parent=self.root) # Pode retornar None
            if motivo:
                database.recusar_entrega(entrega_atual.EntregaID, motivo) # Pode falhar
                texto_notificacao = f"⚠️ Atenção, <b>{entrega_atual.NomeCompleto}</b>! ... Motivo:</b> {motivo} ..."
                notificador_telegram.enviar_mensagem(entrega_atual.ChatIDTelegram, texto_notificacao) # Pode falhar
                messagebox.showinfo("Sucesso", "Entrega recusada e funcionário notificado.", parent=self.root) # Adicionado parent
                self.atualizar_todas_as_listas() # Pode falhar
            else:
                messagebox.showinfo("Cancelado", "Ação de recusa cancelada.", parent=self.root) # Adicionado parent
        except (ValueError, KeyError) as e_parse: # <--- ADICIONADO EXCEPT ESPECÍFICO
            logger.error(f"Erro ao processar seleção da entrega para recusa: {e_parse}")
            messagebox.showerror("Erro Interno", f"Não foi possível processar a entrega selecionada:\n{e_parse}", parent=self.root)
        except Exception as e: # <--- ADICIONADO EXCEPT GENÉRICO
            logger.exception(f"Erro ao recusar entrega ID {entrega_id if 'entrega_id' in locals() else 'N/A'}: {e}")
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao recusar a entrega:\n{e}", parent=self.root)

    
    def limpar_detalhes_validacao(self):
        self.lbl_nome_funcionario.config(text="Funcionário: "); self.lbl_titulo_tarefa.config(text="Tarefa: "); self.lbl_imagem.config(image='')
        
    # (Função duplicada removida. A versão correta com filtro já existe na linha ~1100 deste arquivo)

    def carregar_funcionarios_relatorio(self):
        funcionarios = database.listar_funcionarios(); self.dados_funcionarios_relatorio = {f"{f.NomeCompleto} (ID: {f.FuncionarioID})": f.FuncionarioID for f in funcionarios}
        self.combo_funcionarios_relatorio['values'] = list(self.dados_funcionarios_relatorio.keys())

    def construir_ui_relatorio_pendencias(self):
        """Cria os widgets para o relatório de pendências."""
        container = self.frame_conteudo_relatorio # Desenha dentro do frame da direita
        
        ttk.Label(container, text="Relatório de Pendências Recorrentes", font=("Arial", 16)).pack(pady=10)
        
        frame_filtros = ttk.Frame(container, padding="10")
        frame_filtros.pack(fill=tk.X)
        
        ttk.Label(frame_filtros, text="Funcionário:").pack(side=tk.LEFT, padx=5)
        self.combo_funcionarios_relatorio = ttk.Combobox(frame_filtros, state="readonly", width=40)
        self.combo_funcionarios_relatorio.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(frame_filtros, text="Data (AAAA-MM-DD):").pack(side=tk.LEFT, padx=5)
        self.entry_data_relatorio = ttk.Entry(frame_filtros)
        self.entry_data_relatorio.pack(side=tk.LEFT, padx=5)
        self.entry_data_relatorio.insert(0, datetime.now().strftime("%Y-%m-%d"))
        
        btn_gerar = ttk.Button(frame_filtros, text="Gerar Relatório", command=self.executar_relatorio_pendencias)
        btn_gerar.pack(side=tk.LEFT, padx=10)
        
        cols = ('Tarefa Pendente', 'Pontos Perdidos')
        self.tree_relatorio = ttk.Treeview(container, columns=cols, show='headings')
        for col in cols: self.tree_relatorio.heading(col, text=col)
        self.tree_relatorio.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.carregar_funcionarios_relatorio() # Carrega a lista de funcionários no combobox

    def executar_relatorio_pendencias(self):
        """Busca os dados e preenche a tabela do relatório de pendências."""
        for i in self.tree_relatorio.get_children(): self.tree_relatorio.delete(i)
        
        nome = self.combo_funcionarios_relatorio.get()
        data = self.entry_data_relatorio.get()
        
        if not nome or not data:
            messagebox.showerror("Erro", "Selecione um funcionário e uma data.")
            return
        try:
            datetime.strptime(data, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Erro de Formato", "A data deve estar no formato AAAA-MM-DD.")
            return
            
        funcionario_id = self.dados_funcionarios_relatorio[nome]
        pendencias = database.relatorio_pendencias(funcionario_id, data)
        
        if not pendencias:
            self.tree_relatorio.insert("", "end", values=("Nenhuma pendência encontrada!", "0"))
        else:
            for pendencia in pendencias:
                self.tree_relatorio.insert("", "end", values=(pendencia.Titulo, pendencia.Pontos))
    
    def atualizar_todas_as_listas(self):
        self.atualizar_lista_funcionarios()
        self.atualizar_catalogo_tarefas()
        self.carregar_entregas_pendentes()
        self.atualizar_ranking()
        if hasattr(self, 'canvas_grafico'): self.desenhar_grafico_ranking()
        if self.notebook.winfo_exists() and self.notebook.select():
            tab_text = self.notebook.tab(self.notebook.select(), "text")
            if tab_text == "Atribuir Tarefas": self.on_tab_atribuir_tarefas_selected()
            if tab_text == "Gerenciar Grupos": self.atualizar_lista_grupos()

    def atualizar_lista_funcionarios(self):
        self.lista_funcionarios.delete(0, tk.END); self.dados_funcionarios.clear()
        funcionarios = database.listar_funcionarios()
        
        # Mapeamento do SELECT (Ordem garantida no database.py: 0:ID, 1:Nome, 8:HorarioNotificacao)
        
        for func in funcionarios:
            # Acessamos por índice para garantir a compatibilidade com pyodbc.Row
            # func[8] é HorarioNotificacao
            horario_str = func[8].strftime('%H:%M') if func[8] else "N/D"
            texto = f"ID: {func[0]} | {func[1]} | Notificar às: {horario_str}"
            self.lista_funcionarios.insert(tk.END, texto); self.dados_funcionarios[texto] = func

    def atualizar_catalogo_tarefas(self):
        for i in self.tree_tarefas.get_children(): self.tree_tarefas.delete(i)
        for tarefa in database.listar_todas_as_tarefas():
            self.tree_tarefas.insert("", "end", values=(tarefa.TarefaID, tarefa.Titulo, tarefa.Pontos))

    def carregar_entregas_pendentes(self):
        self.lista_entregas.delete(0, tk.END); self.dados_entregas.clear()
        entregas = database.listar_entregas_pendentes()
        if entregas:
            for entrega in entregas:
                texto = f"ID: {entrega.EntregaID} | {entrega.NomeCompleto} - {entrega.Titulo}"
                self.lista_entregas.insert(tk.END, texto); self.dados_entregas[entrega.EntregaID] = entrega
    
    def mostrar_detalhes_entrega(self, event):
        try: 
            indices = self.lista_entregas.curselection()
            if not indices: return
            texto = self.lista_entregas.get(indices[0])

            # [CORREÇÃO] Parsing seguro do ID e acesso seguro ao dicionário
            try:
                entrega_id = int(texto.split(" | ")[0].split(": ")[1])
            except (IndexError, ValueError):
                return

            entrega_atual = self.dados_entregas.get(entrega_id)
            if not entrega_atual:
                self.lbl_imagem.config(image='', text="Dados desatualizados. Atualize a lista.")
                return

            self.lbl_nome_funcionario.config(text=f"Funcionário: {entrega_atual.NomeCompleto}")
            self.lbl_titulo_tarefa.config(text=f"Tarefa: {entrega_atual.Titulo} ({entrega_atual.Pontos} pts)")

            if entrega_atual.PathFotoEvidencia and os.path.exists(entrega_atual.PathFotoEvidencia):
                # [CORREÇÃO] Usa 'with' e 'copy' para liberar o arquivo imediatamente após carregar.
                # Isso evita o erro de "Arquivo em uso" no Windows ao tentar excluir a entrega.
                try:
                    with Image.open(entrega_atual.PathFotoEvidencia) as img_temp:
                        img_copy = img_temp.copy()

                    img_copy.thumbnail((500, 400))
                    self.photo_img = ImageTk.PhotoImage(img_copy)
                    self.lbl_imagem.config(image=self.photo_img)
                except Exception as e_img:
                    logger.error(f"Erro ao processar imagem: {e_img}")
                    self.lbl_imagem.config(image='', text="Erro ao carregar imagem.")

            else:
                self.lbl_imagem.config(image='', text="Foto ainda não processada pelo servidor ou não encontrada!")
        except (ValueError, KeyError) as e_parse: # <--- ADICIONADO EXCEPT ESPECÍFICO
            logger.error(f"Erro ao processar seleção da entrega para detalhes: {e_parse}")
            messagebox.showerror("Erro Interno", f"Não foi possível processar a entrega selecionada:\n{e_parse}", parent=self.root)
        except FileNotFoundError: # <--- ADICIONADO EXCEPT ESPECÍFICO
             logger.error(f"Arquivo de imagem não encontrado: {entrega_atual.PathFotoEvidencia if 'entrega_atual' in locals() else 'N/A'}")
             self.lbl_imagem.config(image='', text="Erro: Arquivo da imagem não encontrado no servidor!")
             messagebox.showerror("Erro de Arquivo", f"Não foi possível encontrar o arquivo da imagem:\n{entrega_atual.PathFotoEvidencia}", parent=self.root)
        except Exception as e: # <--- ADICIONADO EXCEPT GENÉRICO
            logger.exception(f"Erro ao mostrar detalhes da entrega ID {entrega_id if 'entrega_id' in locals() else 'N/A'}: {e}")
            self.lbl_imagem.config(image='', text=f"Erro ao carregar imagem: {e}")
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao carregar os detalhes ou a imagem:\n{e}", parent=self.root)
   
    def carregar_funcionarios_feedback(self):
        """Carrega a lista de funcionários para o combobox de filtro."""
        funcionarios = database.listar_funcionarios()
        self.dados_funcionarios_feedback = {f.NomeCompleto: f.FuncionarioID for f in funcionarios}
        nomes_para_combobox = ["Todos"] + list(self.dados_funcionarios_feedback.keys())
        self.combo_funcionarios_feedback['values'] = nomes_para_combobox
        self.combo_funcionarios_feedback.set("Todos")

    def limpar_filtros_feedback(self):
        """Limpa os campos de filtro e recarrega a lista completa."""
        self.combo_funcionarios_feedback.set("Todos")
        self.entry_data_inicio_feedback.delete(0, tk.END)
        self.entry_data_inicio_feedback.insert(0, "AAAA-MM-DD")
        self.entry_data_fim_feedback.delete(0, tk.END)
        self.entry_data_fim_feedback.insert(0, "AAAA-MM-DD")
        self.atualizar_lista_feedbacks()

    def atualizar_lista_feedbacks(self):
        """Busca os feedbacks no banco com base nos filtros e atualiza a lista e a média."""
        for i in self.tree_feedbacks.get_children():
            self.tree_feedbacks.delete(i)

        nome_selecionado = self.combo_funcionarios_feedback.get()
        func_id = self.dados_funcionarios_feedback.get(nome_selecionado) if nome_selecionado != "Todos" else None

        data_inicio = self.entry_data_inicio_feedback.get()
        if data_inicio == "AAAA-MM-DD": data_inicio = None

        data_fim = self.entry_data_fim_feedback.get()
        if data_fim == "AAAA-MM-DD": data_fim = None

        feedbacks = database.buscar_feedbacks(func_id, data_inicio, data_fim)

        total_notas = 0

        for fb in feedbacks:
            data_formatada = fb.DataFeedback.strftime("%d/%m/%Y")
            self.tree_feedbacks.insert("", "end", values=(fb.FeedbackID, fb.NomeCompleto, data_formatada, fb.NotaDia))
            total_notas += fb.NotaDia

        if feedbacks:
            media = total_notas / len(feedbacks)
            self.lbl_media_feedback.config(text=f"Nota Média do Período: {media:.2f}")
        else:
            self.lbl_media_feedback.config(text="Nota Média do Período: --")

    def executar_relatorio_analise_tarefas(self):
        """Busca os dados e preenche a tabela de análise de tarefas."""
        for i in self.tree_analise_tarefas.get_children():
            self.tree_analise_tarefas.delete(i)

        data_inicio = self.entry_data_inicio_analise.get()
        data_fim = self.entry_data_fim_analise.get()

        try:
            datetime.strptime(data_inicio, "%Y-%m-%d")
            datetime.strptime(data_fim, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Erro de Formato", "As datas devem estar no formato AAAA-MM-DD.")
            return # Para a execução se o formato estiver errado

        resultados = database.relatorio_analise_tarefas(data_inicio, data_fim)
        
        if not resultados:
            self.tree_analise_tarefas.insert("", "end", values=("Nenhum dado problemático encontrado no período!", "", "", ""))
        else:
            for res in resultados:
                self.tree_analise_tarefas.insert("", "end", values=tuple(res))

    def abrir_janela_justificativas(self):
        """Abre uma janela para mostrar os detalhes das justificativas 'Não Aplicável'."""
        selecionado = self.tree_analise_tarefas.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione uma tarefa na lista de resultados.")
            return

        dados_tarefa = self.tree_analise_tarefas.item(selecionado, 'values')
        titulo_tarefa = dados_tarefa[0]
        data_inicio = self.entry_data_inicio_analise.get()
        data_fim = self.entry_data_fim_analise.get()

        justificativas = database.buscar_justificativas_nao_aplicavel(titulo_tarefa, data_inicio, data_fim)

        popup = Toplevel(self.root)
        popup.title(f"Justificativas para '{titulo_tarefa}'")
        popup.geometry("600x400")
        popup.transient(self.root)

        if not justificativas:
            ttk.Label(popup, text="Nenhuma justificativa encontrada para esta tarefa no período.").pack(pady=20)
            return

        frame_lista = ttk.Frame(popup, padding="10")
        frame_lista.pack(fill="both", expand=True)
        
        cols = ('Data', 'Funcionário', 'Justificativa')
        tree_justificativas = ttk.Treeview(frame_lista, columns=cols, show='headings')
        
        tree_justificativas.heading('Data', text='Data'); tree_justificativas.column('Data', width=120)
        tree_justificativas.heading('Funcionário', text='Funcionário'); tree_justificativas.column('Funcionário', width=150)
        tree_justificativas.heading('Justificativa', text='Justificativa'); tree_justificativas.column('Justificativa', width=300)
        
        tree_justificativas.pack(fill="both", expand=True)

        for just in justificativas:
            motivo_limpo = just.MotivoRecusa.replace("Não aplicável: ", "", 1)
            data_formatada = just.DataEnvio.strftime('%d/%m/%Y %H:%M')
            tree_justificativas.insert("", "end", values=(data_formatada, just.NomeCompleto, motivo_limpo))

    def construir_ui_relatorio_resgates(self):
        """Constrói a interface para o relatório de gastos na loja."""
        container = self.frame_conteudo_relatorio

        # Título
        lbl_titulo = ttk.Label(container, text="Relatório de Resgates - Mês Atual", font=("Arial", 16))
        lbl_titulo.pack(pady=(10, 5))

        # Subtítulo explicativo
        mes_atual_str = datetime.now().strftime("%B/%Y")
        lbl_sub = ttk.Label(container, text=f"Total de pontos gastos por funcionário em {mes_atual_str}", foreground="gray")
        lbl_sub.pack(pady=(0, 15))

        # Botão de Atualizar
        btn_atualizar = ttk.Button(container, text="🔄 Atualizar Dados", command=self.executar_relatorio_resgates)
        btn_atualizar.pack(anchor='w', padx=10, pady=5)

        # Tabela (ATUALIZADA COM COLUNA R$)
        cols = ('Funcionário', 'Qtd. Itens', 'Total Gasto (Pontos)', 'Valor (R$)')
        self.tree_relatorio_resgates = ttk.Treeview(container, columns=cols, show='headings')

        self.tree_relatorio_resgates.heading('Funcionário', text='Funcionário')
        self.tree_relatorio_resgates.column('Funcionário', width=250)

        self.tree_relatorio_resgates.heading('Qtd. Itens', text='Qtd. Itens')
        self.tree_relatorio_resgates.column('Qtd. Itens', width=80, anchor='center')

        self.tree_relatorio_resgates.heading('Total Gasto (Pontos)', text='Total (Pontos)')
        self.tree_relatorio_resgates.column('Total Gasto (Pontos)', width=120, anchor='center')

        self.tree_relatorio_resgates.heading('Valor (R$)', text='Valor (R$)')
        self.tree_relatorio_resgates.column('Valor (R$)', width=120, anchor='e') # Alinhado à direita

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.tree_relatorio_resgates.yview)
        self.tree_relatorio_resgates.configure(yscrollcommand=scrollbar.set)

        self.tree_relatorio_resgates.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)

        # Carrega os dados automaticamente ao abrir
        self.executar_relatorio_resgates()

    def executar_relatorio_resgates(self):
        """Busca os dados no banco e preenche a tabela de resgates com cálculo em R$."""
        # Limpa a tabela
        for i in self.tree_relatorio_resgates.get_children():
            self.tree_relatorio_resgates.delete(i)

        # Busca dados
        resultados = database.relatorio_resgates_consolidado_mes()

        total_geral_pontos = 0
        total_geral_reais = 0.0
        taxa = config.TAXA_CONVERSAO_PONTO_REAL # Pega o 0.03 do config

        if not resultados:
            self.tree_relatorio_resgates.insert("", "end", values=("Nenhum resgate aprovado neste mês.", "", "", ""))
        else:
            for row in resultados:
                # row = (Nome, Qtd, TotalPontos)
                nome = row[0]
                qtd = row[1]
                pontos = row[2]

                # Cálculo do valor em reais
                valor_reais = pontos * taxa

                # Formatação bonita para moeda (R$ 1.234,56)
                valor_formatado = f"R$ {valor_reais:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                self.tree_relatorio_resgates.insert("", "end", values=(nome, qtd, pontos, valor_formatado))

                total_geral_pontos += pontos
                total_geral_reais += valor_reais

            # Adiciona uma linha final de totais
            self.tree_relatorio_resgates.insert("", "end", values=("", "", "", "")) # Linha vazia

            total_reais_fmt = f"R$ {total_geral_reais:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            self.tree_relatorio_resgates.insert("", "end", values=("TOTAL GERAL DO MÊS", "", f"{total_geral_pontos}", total_reais_fmt), tags=('total',))

            # Destaca a linha de total
            self.tree_relatorio_resgates.tag_configure('total', font=('Arial', 10, 'bold'), background='#e6e6e6')

    def construir_ui_relatorio_analise_tarefas(self):
        """Cria os widgets para o relatório de Análise de Tarefas."""
        container = self.frame_conteudo_relatorio

        ttk.Label(container, text="Relatório de Análise de Tarefas", font=("Arial", 16)).pack(pady=10)
        
        frame_filtros = ttk.Frame(container, padding="10")
        frame_filtros.pack(fill=tk.X)
        
        # Filtros de data
        ttk.Label(frame_filtros, text="De:").pack(side=tk.LEFT, padx=(0, 5))
        self.entry_data_inicio_analise = ttk.Entry(frame_filtros, width=12)
        self.entry_data_inicio_analise.pack(side=tk.LEFT)
        self.entry_data_inicio_analise.insert(0, (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))

        ttk.Label(frame_filtros, text="Até:").pack(side=tk.LEFT, padx=5)
        self.entry_data_fim_analise = ttk.Entry(frame_filtros, width=12)
        self.entry_data_fim_analise.pack(side=tk.LEFT)
        self.entry_data_fim_analise.insert(0, datetime.now().strftime("%Y-%m-%d"))

        btn_gerar = ttk.Button(frame_filtros, text="Gerar Análise", command=self.executar_relatorio_analise_tarefas)
        btn_gerar.pack(side=tk.LEFT, padx=10)

        btn_detalhes = ttk.Button(frame_filtros, text="Ver Justificativas da Tarefa Selecionada", command=self.abrir_janela_justificativas)
        btn_detalhes.pack(side=tk.LEFT, padx=10)

        # Tabela de resultados
        cols = ('Tarefa', 'Vezes Recusada', 'Vezes "Não Aplicável"', 'Total Problemático')
        self.tree_analise_tarefas = ttk.Treeview(container, columns=cols, show='headings')
        for col in cols:
            self.tree_analise_tarefas.heading(col, text=col)
            
        self.tree_analise_tarefas.column('Tarefa', width=300)
        self.tree_analise_tarefas.column('Vezes Recusada', anchor='center')
        self.tree_analise_tarefas.column('Vezes "Não Aplicável"', anchor='center')
        self.tree_analise_tarefas.column('Total Problemático', anchor='center')
        
        self.tree_analise_tarefas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def criar_aba_metas(self):
        """(VERSÃO V6) Cria a interface para Gestão de Metas, com histórico de lucro ao lado."""
        main_frame = ttk.Frame(self.frame_metas)
        main_frame.pack(fill=tk.BOTH, expand=True)
        # Layout: Venda (0), [Lançar Lucro + Histórico Lucro] (1), Ger. Metas (2), Detalhes Vendas (3)
        main_frame.rowconfigure(3, weight=1) # Linha 3 (Detalhes) que se expande
        main_frame.columnconfigure(0, weight=1)

        # --- Frame Lançamento Venda (Linha 0) ---
        frame_lancamento = ttk.LabelFrame(main_frame, text="Lançar Apuração Diária (Vendas R$)", padding="10")
        frame_lancamento.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame_lancamento.columnconfigure(1, weight=1)
        ttk.Label(frame_lancamento, text="Meta Principal Ativa:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.combo_metas_ativas = ttk.Combobox(frame_lancamento, state="readonly")
        self.combo_metas_ativas.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Label(frame_lancamento, text="Data da Apuração:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.date_apuracao = DateEntry(frame_lancamento, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_apuracao.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(frame_lancamento, text="Valor Vendido do Dia (R$):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.entry_valor_dia = ttk.Entry(frame_lancamento)
        self.entry_valor_dia.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        btn_lancar = ttk.Button(frame_lancamento, text="Lançar Apuração Diária", command=self.lancar_apuracao_diaria)
        btn_lancar.grid(row=3, column=1, padx=5, pady=10, sticky="e")

        # --- NOVO: Frame Intermediário para Lucro (Linha 1) ---
        frame_linha_lucro = ttk.Frame(main_frame)
        frame_linha_lucro.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        frame_linha_lucro.columnconfigure(0, weight=1) # Coluna do lançamento
        frame_linha_lucro.columnconfigure(1, weight=2) # Coluna do histórico (maior)
        # --- FIM NOVO ---

        # --- Frame Lançar Lucro Mensal (Linha 1, Coluna 0 do frame_linha_lucro) ---
        frame_lucro = ttk.LabelFrame(frame_linha_lucro, text="Lançar Lucro Mensal (%)", padding="10")
        frame_lucro.grid(row=0, column=0, sticky="nsew", padx=(0, 5)) # Adicionado padx
        # (Conteúdo interno do frame_lucro permanece o mesmo)
        frame_lucro.columnconfigure(1, weight=1)
        ttk.Label(frame_lucro, text="Ano:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.entry_lucro_ano = ttk.Entry(frame_lucro, width=6)
        self.entry_lucro_ano.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(frame_lucro, text="Mês:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        meses_nomes = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        self.combo_lucro_mes = ttk.Combobox(frame_lucro, values=meses_nomes, state="readonly", width=15)
        self.combo_lucro_mes.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(frame_lucro, text="Percentual (%):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.entry_lucro_percentual = ttk.Entry(frame_lucro, width=10)
        self.entry_lucro_percentual.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        btn_salvar_lucro = ttk.Button(frame_lucro, text="Salvar Lucro Mensal", command=self.salvar_lucro_interface)
        btn_salvar_lucro.grid(row=3, column=1, padx=5, pady=10, sticky="e")
        hoje = datetime.now()
        primeiro_dia_mes_atual = hoje.replace(day=1)
        ultimo_dia_mes_passado = primeiro_dia_mes_atual - timedelta(days=1)
        self.entry_lucro_ano.insert(0, str(ultimo_dia_mes_passado.year))
        self.combo_lucro_mes.current(ultimo_dia_mes_passado.month - 1)

        # --- Frame Histórico de Lucro (Linha 1, Coluna 1 do frame_linha_lucro) ---
        frame_historico_lucro = ttk.LabelFrame(frame_linha_lucro, text="Histórico de Lucro Lançado (Duplo-clique para editar)", padding="10")
        frame_historico_lucro.grid(row=0, column=1, sticky="nsew", padx=(5, 0)) # Adicionado padx
        frame_historico_lucro.columnconfigure(0, weight=1)
        frame_historico_lucro.rowconfigure(0, weight=1) # Permite que a Treeview cresça verticalmente se necessário
        cols_lucro = ('ID', 'Ano', 'Mês', 'Percentual')
        self.tree_lucros_lancados = ttk.Treeview(frame_historico_lucro, columns=cols_lucro, show='headings', selectmode='browse', height=5) # Ajuste a altura (height) conforme necessário
        self.tree_lucros_lancados.heading('ID', text='ID'); self.tree_lucros_lancados.column('ID', width=40, anchor="center")
        self.tree_lucros_lancados.heading('Ano', text='Ano'); self.tree_lucros_lancados.column('Ano', width=80, anchor="center")
        self.tree_lucros_lancados.heading('Mês', text='Mês'); self.tree_lucros_lancados.column('Mês', width=100, anchor="center")
        self.tree_lucros_lancados.heading('Percentual', text='Percentual (%)'); self.tree_lucros_lancados.column('Percentual', width=100, anchor="e")
        self.tree_lucros_lancados.grid(row=0, column=0, sticky="nsew") # Treeview cresce
        self.tree_lucros_lancados.bind("<Double-1>", self.abrir_janela_edicao_lucro)
        btn_excluir_lucro = ttk.Button(frame_historico_lucro, text="Excluir Lançamento Selecionado", command=self.excluir_lancamento_lucro_selecionado)
        btn_excluir_lucro.grid(row=1, column=0, sticky="e", pady=(5, 0)) # Botão abaixo da lista

        # --- Seção Gerenciar Metas Principais (agora na linha 2) ---
        frame_gerenciamento = ttk.LabelFrame(main_frame, text="Gerenciar Metas Principais (Clique para ver detalhes)", padding="10")
        frame_gerenciamento.grid(row=2, column=0, sticky="ew", pady=(10, 10)) # Mudou para row=2
        frame_gerenciamento.rowconfigure(0, weight=1)
        frame_gerenciamento.columnconfigure(0, weight=1)
        cols_principais = ('ID', 'Nome', 'Valor Total', 'Início', 'Fim', 'Status')
        self.tree_metas_principais = ttk.Treeview(frame_gerenciamento, columns=cols_principais, show='headings', selectmode='browse', height=5) # Definindo altura inicial        for col in cols_principais: self.tree_metas_principais.heading(col, text=col)
        self.tree_metas_principais.column('ID', width=40); self.tree_metas_principais.column('Nome', width=250)
        self.tree_metas_principais.column('Valor Total', width=120, anchor="e"); self.tree_metas_principais.column('Início', width=100, anchor="center")
        self.tree_metas_principais.column('Fim', width=100, anchor="center"); self.tree_metas_principais.column('Status', width=80, anchor="center")
        self.tree_metas_principais.pack(fill="x", expand=True, side="left")
        self.tree_metas_principais.bind('<<TreeviewSelect>>', self.on_meta_principal_selecionada)
        frame_botoes_gerenciamento = ttk.Frame(frame_gerenciamento)
        frame_botoes_gerenciamento.pack(side="left", fill="y", padx=10)
        ttk.Button(frame_botoes_gerenciamento, text="Criar Nova Meta Principal...", command=self.abrir_janela_criar_meta_principal).pack(pady=5)
        ttk.Button(frame_botoes_gerenciamento, text="Definir Metas Diárias...", command=self.abrir_janela_metas_diarias).pack(pady=5)

        # --- Frame Detalhes (agora na linha 3) ---
        frame_detalhes = ttk.LabelFrame(main_frame, text="Detalhes e Evolução da Meta de Vendas Selecionada", padding="10")
        frame_detalhes.grid(row=3, column=0, sticky="nsew") # Ocupa a linha 3 do main_frame

        # --- CORREÇÃO AQUI ---
        # Configura as linhas e colunas DENTRO do frame_detalhes
        frame_detalhes.rowconfigure(3, weight=1)    # Linha 0 (onde está a Treeview) pode expandir verticalmente
        frame_detalhes.rowconfigure(1, weight=0)    # Linha 1 (botão excluir) não expande
        frame_detalhes.columnconfigure(0, weight=3) # Coluna 0 (Treeview) expande mais horizontalmente
        frame_detalhes.columnconfigure(1, weight=1) # Coluna 1 (Resumo) expande menos
        # --- FIM DA CORREÇÃO ---

        cols_detalhes = ('Data do Lançamento', 'Valor Lançado (R$)')
        # Removemos o height=10 daqui
        self.tree_detalhes_apuracoes = ttk.Treeview(frame_detalhes, columns=cols_detalhes, show='headings', selectmode='browse') 
        self.tree_detalhes_apuracoes.heading('Data do Lançamento', text='Data do Lançamento')
        self.tree_detalhes_apuracoes.column('Data do Lançamento', anchor='center', width=150) # Ajuste a largura se necessário
        self.tree_detalhes_apuracoes.heading('Valor Lançado (R$)', text='Valor Lançado (R$)')
        self.tree_detalhes_apuracoes.column('Valor Lançado (R$)', anchor='e', width=150) # Ajuste a largura se necessário
        # A treeview agora ocupa a linha 0, coluna 0 e se expande (nsew)
        self.tree_detalhes_apuracoes.grid(row=0, column=0, sticky="nsew", pady=(0, 5)) 
        self.tree_detalhes_apuracoes.bind("<Double-1>", self.abrir_janela_edicao_apuracao)

        # Frame do botão excluir fica na linha 1, coluna 0
        frame_botoes_detalhes = ttk.Frame(frame_detalhes)
        frame_botoes_detalhes.grid(row=1, column=0, sticky="w", padx=0, pady=(0, 5)) # Ajustado padx e pady
        btn_excluir_apuracao = ttk.Button(frame_botoes_detalhes, text="Excluir Apuração Selecionada", command=self.excluir_apuracao_selecionada)
        btn_excluir_apuracao.pack() # Pack dentro do seu próprio frame

        # Frame de resumo ocupa a linha 0 e 1 (rowspan=2) na coluna 1
        frame_resumo = ttk.Frame(frame_detalhes, padding="20")
        frame_resumo.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(10, 0))
        self.lbl_total_atingido = ttk.Label(frame_resumo, text="Total Atingido: R$ 0,00", font=("Arial", 12, "bold"))
        self.lbl_total_atingido.pack(anchor="w", pady=5)
        self.lbl_progresso_percentual = ttk.Label(frame_resumo, text="Progresso: 0.00%", font=("Arial", 12))
        self.lbl_progresso_percentual.pack(anchor="w", pady=5)
        self.lbl_projecao_vendas = ttk.Label(frame_resumo, text="Projeção Final: R$ 0,00", font=("Arial", 12, "italic"))
        self.lbl_projecao_vendas.pack(anchor="w", pady=(15, 5))
        # Inicialização automática dos dados da aba
        self.carregar_dados_metas()
        self.atualizar_lista_lucros()

    def on_meta_principal_selecionada(self, event):
        """(VERSÃO V2 FINAL) Carrega o histórico, o resumo, a projeção E VERIFICA SE A META MENSAL FOI ATINGIDA."""
        for i in self.tree_detalhes_apuracoes.get_children(): self.tree_detalhes_apuracoes.delete(i)
        self.lbl_total_atingido.config(text="Total Atingido: R$ 0,00"); self.lbl_progresso_percentual.config(text="Progresso: 0.00%")
        self.lbl_projecao_vendas.config(text="Projeção Final: R$ 0,00")

        selecionados = self.tree_metas_principais.selection()
        if not selecionados: return
        item_selecionado = selecionados[0]

        dados_meta = self.tree_metas_principais.item(item_selecionado, 'values')
        if not dados_meta: return
            
        meta_id = int(dados_meta[0])
        valor_meta_total_str = dados_meta[2].replace("R$ ", "").replace(".", "").replace(",", ".")
        valor_meta_total = float(valor_meta_total_str)
        data_inicio_str, data_fim_str = dados_meta[3], dados_meta[4]
        status_meta = dados_meta[5]

        apuracoes = database.listar_apuracoes_por_meta_principal(meta_id)

        total_atingido = 0.0
        for apuracao in apuracoes:
            data_f = apuracao.DataApuracao.strftime('%d/%m/%Y'); valor_f = f"{apuracao.ValorDia:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            self.tree_detalhes_apuracoes.insert("", "end", values=(data_f, valor_f)); total_atingido += float(apuracao.ValorDia)

        percentual = (total_atingido / valor_meta_total) * 100 if valor_meta_total > 0 else 0
        total_atingido_f = f"R$ {total_atingido:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        self.lbl_total_atingido.config(text=f"Total Atingido: {total_atingido_f}"); self.lbl_progresso_percentual.config(text=f"Progresso: {percentual:.2f}%")

        if len(apuracoes) > 0:
            media_diaria = total_atingido / len(apuracoes)
            total_dias_meta = (datetime.strptime(data_fim_str, '%d/%m/%Y') - datetime.strptime(data_inicio_str, '%d/%m/%Y')).days + 1
            projecao = media_diaria * total_dias_meta
            projecao_f = f"R$ {projecao:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            self.lbl_projecao_vendas.config(text=f"Projeção Final: {projecao_f}")

        # [CORREÇÃO] Recarrega metas do banco para garantir status atualizado (Atomicidade)
        metas_banco = database.listar_metas_principais()
        meta_detalhes = next((m for m in metas_banco if m.MetaPrincipalID == meta_id), None)

        # Verifica o status REAL do banco, ignorando o cache visual da Treeview
        if meta_detalhes and total_atingido >= valor_meta_total and meta_detalhes.Status == 'Ativa':
            if meta_detalhes:
                confirmado = messagebox.askyesno(
                    "🎉 META MENSAL ATINGIDA! 🎉",
                    f"Parabéns! A meta '{meta_detalhes.NomeMeta}' foi alcançada!\n\n"
                    f"Deseja distribuir os {meta_detalhes.PontosPremio} pontos de prêmio para a equipe do setor '{meta_detalhes.SetorAlvo}' agora?"
                )
                if confirmado:
                    funcionarios_premiados = database.distribuir_premio_meta_principal(meta_id)
                    if funcionarios_premiados:
                        mensagem_telegram = (
                            f"🎉🎊 **META MENSAL ATINGIDA!** 🎊🎉\n\n"
                            f"Parabéns, equipe do setor '{meta_detalhes.SetorAlvo.upper()}'! Vocês alcançaram o grande objetivo do mês!\n\n"
                            f"Cada um recebeu um super bônus de **{meta_detalhes.PontosPremio} pontos**!\n\n"
                            "Vocês são incríveis! 🚀"
                        )
                        for funcionario in funcionarios_premiados:
                            notificador_telegram.enviar_mensagem(funcionario.ChatIDTelegram, mensagem_telegram)
                        
                        messagebox.showinfo("Sucesso", "Prêmio distribuído e equipe notificada com sucesso!")
                        self.carregar_dados_metas()

    def salvar_lucro_interface(self):
        """Lê os dados da interface e salva o lucro mensal no banco."""
        try:
            # [CORREÇÃO] Validação do índice do combobox para evitar mês 0
            idx_mes = self.combo_lucro_mes.current()
            if idx_mes == -1:
                raise ValueError("Selecione um mês válido na lista.")

            mes = int(idx_mes + 1)
            percentual_str = self.entry_lucro_percentual.get().replace(',', '.')
            percentual = float(percentual_str)

            if not (2020 <= ano <= 2100): # Validação simples do ano
                raise ValueError("Ano inválido.")
            if not (0 <= percentual <= 1000): # Validação do percentual (permite > 100 se necessário)
                raise ValueError("Percentual inválido.")

            if database.salvar_lucro_mensal(ano, mes, percentual):
                messagebox.showinfo("Sucesso", f"Percentual de lucro para {mes:02d}/{ano} salvo com sucesso!", parent=self.root)
                self.entry_lucro_percentual.delete(0, tk.END)
                self.atualizar_lista_lucros() # <-- ATUALIZA A LISTA
            else:
                messagebox.showerror("Erro de Banco", "Não foi possível salvar o percentual de lucro.", parent=self.root)

        except ValueError as e:
            messagebox.showerror("Erro de Formato", f"Verifique os valores digitados.\nAno, Mês e Percentual devem ser números válidos.\nDetalhe: {e}", parent=self.root)
        except Exception as e:
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro: {e}", parent=self.root)

    def abrir_janela_metas_diarias(self):
        """Abre um pop-up para o gestor definir as metas para cada dia da semana."""
        popup = Toplevel(self.root)
        popup.title("Definir Modelos de Metas Diárias")
        popup.geometry("550x350")
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Dê um duplo-clique em um dia para editar a meta.", font=("Arial", 9, "italic")).pack(pady=(0, 10))

        cols = ('Dia da Semana', 'Valor da Meta (R$)', 'Prêmio (Pontos)')
        tree = ttk.Treeview(frame, columns=cols, show='headings', selectmode='browse')
        for col in cols: tree.heading(col, text=col)
        tree.column('Valor da Meta (R$)', anchor='e')
        tree.column('Prêmio (Pontos)', anchor='center')
        tree.pack(fill="both", expand=True)

        def carregar_dados():
            for i in tree.get_children(): tree.delete(i)
            modelos = database.listar_modelos_metas_diarias()
            for modelo in modelos:
                valor_f = f"{modelo.ValorMeta:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                tree.insert("", "end", values=(modelo.NomeDia, valor_f, modelo.PontosPremio), iid=modelo.DiaSemanaID)

        def abrir_edicao(event):
            selecionado = tree.focus()
            if not selecionado: return
            self.abrir_janela_edicao_meta_diaria(popup, selecionado, carregar_dados)

        tree.bind("<Double-1>", abrir_edicao)
        carregar_dados()

    def abrir_janela_edicao_meta_diaria(self, parent, dia_semana_id, callback_refresh):
        """Abre a pequena janela para editar os valores de uma meta diária."""
        dados_modelo = next((m for m in database.listar_modelos_metas_diarias() if m.DiaSemanaID == int(dia_semana_id)), None)
        if not dados_modelo: return

        popup = Toplevel(parent)
        popup.title(f"Editar Meta de {dados_modelo.NomeDia}")
        popup.geometry("300x200")
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Valor da Meta (R$):").pack()
        entry_valor = ttk.Entry(frame); entry_valor.pack(pady=5)
        entry_valor.insert(0, f"{dados_modelo.ValorMeta:.2f}")

        ttk.Label(frame, text="Prêmio por Atingir (Pontos):").pack()
        entry_pontos = ttk.Entry(frame); entry_pontos.pack(pady=5)
        entry_pontos.insert(0, dados_modelo.PontosPremio)

        def salvar():
            try:
                valor = float(entry_valor.get().replace(",", "."))
                pontos = int(entry_pontos.get())
                if database.atualizar_modelo_meta_diaria(dia_semana_id, valor, pontos):
                    popup.destroy()
                    callback_refresh() # Chama a função para atualizar a lista
                else:
                    messagebox.showerror("Erro", "Falha ao salvar no banco de dados.", parent=popup)
            except ValueError:
                messagebox.showerror("Erro de Formato", "Os valores devem ser números.", parent=popup)

        ttk.Button(frame, text="Salvar", command=salvar).pack(pady=10)

    def abrir_janela_edicao_apuracao(self, event):
            """Abre um pop-up para editar o valor de um lançamento diário selecionado."""
            
            # 1. [CRÍTICO] Captura o contexto da Meta Principal ANTES de tudo.
            # Isso garante que a variável exista antes de definirmos a função interna.
            selecao_meta_principal = self.tree_metas_principais.selection()
            if not selecao_meta_principal:
                return
            # Pega o ID da meta (coluna 0) e guarda na variável
            meta_id_contexto = self.tree_metas_principais.item(selecao_meta_principal[0], 'values')[0]

            # 2. Valida a seleção da apuração
            selecionado = self.tree_detalhes_apuracoes.focus()
            if not selecionado:
                return

            dados_apuracao = self.tree_detalhes_apuracoes.item(selecionado, 'values')
            data_lancamento_str = dados_apuracao[0]
            valor_antigo_str = dados_apuracao[1].replace(".", "").replace(",", ".")

            # 3. Cria a Janela
            popup = Toplevel(self.root)
            popup.title(f"Editar Lançamento de {data_lancamento_str}")
            popup.geometry("350x200")
            popup.transient(self.root)
            frame = ttk.Frame(popup, padding="15")
            frame.pack(fill="both", expand=True)

            ttk.Label(frame, text=f"Data da Apuração: {data_lancamento_str}", font=("Arial", 10, "bold")).pack(pady=5)

            ttk.Label(frame, text="Novo Valor Lançado (R$):").pack(pady=5)
            entry_novo_valor = ttk.Entry(frame, justify="center")
            entry_novo_valor.pack(pady=5, ipady=4)
            entry_novo_valor.insert(0, valor_antigo_str)
            entry_novo_valor.focus()

            # 4. Função Interna (Closure)
            # Agora 'meta_id_contexto' JÁ EXISTE (foi criada no passo 1), então não dará erro.
            def salvar_edicao(meta_id_fixo=meta_id_contexto):
                nova_valor_str = entry_novo_valor.get().replace(",", ".")

                try:
                    novo_valor = float(nova_valor_str)
                    data_db_format = datetime.strptime(data_lancamento_str, '%d/%m/%Y').strftime('%Y-%m-%d')

                    # Usa o ID fixo que congelamos no argumento
                    id_funcionario_logado = 2 

                    sucesso, resultado = database.lancar_apuracao_diaria(meta_id_fixo, data_db_format, novo_valor, id_funcionario_logado)

                    if sucesso:
                        apuracao_id = resultado
                        messagebox.showinfo("Sucesso", "Apuração atualizada com sucesso!", parent=popup)
                        popup.destroy()
                        self.on_meta_principal_selecionada(None) 
                        
                        # [CORREÇÃO] Tratamento de erro dentro da thread para evitar falhas silenciosas
                        def tarefa_background():
                            try:
                                database.verificar_e_premiar_meta_diaria(apuracao_id, data_db_format, novo_valor, meta_id_fixo)
                            except Exception as e_bg:
                                logger.error(f"FALHA CRÍTICA na thread de premiação de meta (ApuracaoID {apuracao_id}): {e_bg}", exc_info=True)

                        threading.Thread(target=tarefa_background, daemon=True).start()
                    else:
                        messagebox.showerror("Erro", f"Não foi possível atualizar a apuração no banco.\nDetalhe: {resultado}", parent=popup)

                except ValueError:
                    messagebox.showerror("Erro de Formato", f"O valor '{nova_valor_str}' não é um número válido.", parent=popup)
                except Exception as e:
                    messagebox.showerror("Erro Inesperado", f"Ocorreu um erro: {e}", parent=popup)

            btn_salvar = ttk.Button(frame, text="Salvar Alterações", command=salvar_edicao)
            btn_salvar.pack(pady=15)
            entry_novo_valor.bind("<Return>", lambda e: salvar_edicao())

    def excluir_apuracao_selecionada(self):
        """Exclui o registro de apuração diária selecionado na lista de detalhes."""
        selecionado_apuracao = self.tree_detalhes_apuracoes.focus()
        selecionado_meta = self.tree_metas_principais.focus()

        if not selecionado_apuracao or not selecionado_meta:
            messagebox.showwarning("Aviso", "Por favor, selecione uma meta na lista de cima e uma apuração na lista de detalhes para excluir.")
            return
        dados_apuracao = self.tree_detalhes_apuracoes.item(selecionado_apuracao, 'values')
        meta_id = self.tree_metas_principais.item(selecionado_meta, 'values')[0]
        data_lancamento_str_br = dados_apuracao[0] # Formato: dd/mm/yyyy

        confirmado = messagebox.askyesno(
            "Confirmar Exclusão",
            f"Tem certeza que deseja excluir permanentemente o lançamento do dia {data_lancamento_str_br}?\n\nEsta ação não pode ser desfeita.",
            icon='warning'
        )

        if confirmado:
            try:
                data_db_format = datetime.strptime(data_lancamento_str_br, '%d/%m/%Y').strftime('%Y-%m-%d')

                sucesso = database.excluir_apuracao_diaria(meta_id, data_db_format)

                if sucesso:
                    messagebox.showinfo("Sucesso", "Lançamento excluído com sucesso!")
                    self.on_meta_principal_selecionada(None)
                else:
                    messagebox.showerror("Erro", "Não foi possível excluir o lançamento do banco de dados.")
            except Exception as e:
                messagebox.showerror("Erro Inesperado", f"Ocorreu um erro: {e}")


    def lancar_apuracao_diaria(self):
        """(VERSÃO V4) Lança a apuração e CHAMA A FUNÇÃO AUXILIAR para verificar/premiar."""
        print(">>> DEBUG: Função lancar_apuracao_diaria FOI CHAMADA!") # <-- Mantém o print de teste
        meta_selecionada_str = self.combo_metas_ativas.get()
        data_apuracao_obj = self.date_apuracao.get_date() # Pega o objeto date
        data_apuracao_str = data_apuracao_obj.strftime('%Y-%m-%d') # Formata para o banco
        valor_dia_str = self.entry_valor_dia.get().replace(',', '.')
        
        if not meta_selecionada_str or not valor_dia_str:
            messagebox.showwarning("Aviso", "Selecione uma meta e preencha o valor vendido no dia.")
            return
                
        try:
            meta_id = int(meta_selecionada_str.split('(ID: ')[1][:-1])
            valor_dia = float(valor_dia_str)
            # Use um ID de gestor fixo ou busque o do usuário logado se tiver sistema de login
            id_funcionario_logado = 2 # Exemplo: ID do gestor que está usando a interface
                
            # Salva/Atualiza no banco
            sucesso, resultado = database.lancar_apuracao_diaria(meta_id, data_apuracao_str, valor_dia, id_funcionario_logado) #
            print(f">>> DEBUG: Resultado do salvamento no DB - Sucesso: {sucesso}, Resultado: {resultado}") # <-- Mantém o print de teste
                
            if sucesso:
                apuracao_id = resultado # Captura o ID retornado pelo banco
                messagebox.showinfo("Sucesso", "Apuração diária lançada com sucesso!") #
                self.entry_valor_dia.delete(0, tk.END)
                self.on_meta_principal_selecionada(None) # Atualiza a lista de detalhes

                # [CORREÇÃO] Executa a verificação e envio de notificações em Thread separada
                # Isso evita que a interface do Tkinter congele enquanto o bot envia mensagens.
                def tarefa_background():
                    database.verificar_e_premiar_meta_diaria(apuracao_id, data_apuracao_str, valor_dia, meta_id)

                threading.Thread(target=tarefa_background, daemon=True).start()

            else:
                 print(f">>> DEBUG: Lançamento no DB falhou. Não vai verificar premiação.") # <-- Mantém o print de teste
                 messagebox.showerror("Erro", f"Não foi possível salvar a apuração no banco de dados.\nDetalhe: {resultado}") #
        except (ValueError, IndexError):
            messagebox.showerror("Erro de Formato", "Verifique o valor vendido e a seleção da meta.")
        except Exception as e:
             messagebox.showerror("Erro Inesperado", f"Ocorreu um erro: {e}")

# Em main.py, SUBSTITUA a função carregar_dados_metas por esta:

    def carregar_dados_metas(self):
        """Carrega as metas principais na lista e popula o combobox de metas ativas."""
        for i in self.tree_metas_principais.get_children():
            self.tree_metas_principais.delete(i)
        
        metas = database.listar_metas_principais()
        metas_ativas = []
        data_hoje = datetime.now().date() # Pega a data de HOJE

        for meta in metas:
            data_inicio_f = meta.DataInicio.strftime('%d/%m/%Y')
            data_fim_f = meta.DataFim.strftime('%d/%m/%Y')
            valor_total_f = f"R$ {meta.ValorMetaTotal:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            self.tree_metas_principais.insert("", "end", values=(
                meta.MetaPrincipalID, meta.NomeMeta, valor_total_f, data_inicio_f, data_fim_f, meta.Status
            ))
            
            # --- CORREÇÃO APLICADA AQUI ---
            # Verifica o Status E TAMBÉM o intervalo de datas
            # CORREÇÃO: Removemos .date() pois meta.DataInicio já é um objeto 'date'
            data_inicio_obj = meta.DataInicio
            data_fim_obj = meta.DataFim

            if meta.Status == 'Ativa' and (data_inicio_obj <= data_hoje <= data_fim_obj):
                metas_ativas.append(f"{meta.NomeMeta} (ID: {meta.MetaPrincipalID})")
            # --- FIM DA CORREÇÃO ---
                
        self.combo_metas_ativas['values'] = metas_ativas
        if metas_ativas:
            self.combo_metas_ativas.current(0)


    def abrir_janela_criar_meta_principal(self):
        """Abre um popup para o gestor cadastrar uma nova meta principal."""
        popup = Toplevel(self.root)
        popup.title("Criar Nova Meta Principal")
        popup.geometry("400x350")
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Nome da Meta:").pack(anchor='w')
        entry_nome = ttk.Entry(frame); entry_nome.pack(fill='x', pady=5)

        ttk.Label(frame, text="Setor Alvo:").pack(anchor='w')
        combo_setor = ttk.Combobox(frame, values=['Equipe', 'Caixa', 'Atendimento'])
        combo_setor.pack(fill='x', pady=5)

        ttk.Label(frame, text="Valor Total da Meta (R$):").pack(anchor='w')
        entry_valor = ttk.Entry(frame); entry_valor.pack(fill='x', pady=5)

        ttk.Label(frame, text="Pontos de Prêmio (se atingir):").pack(anchor='w')
        entry_pontos = ttk.Entry(frame); entry_pontos.pack(fill='x', pady=5)

        ttk.Label(frame, text="Período da Meta:").pack(anchor='w', pady=(10,0))
        frame_datas = ttk.Frame(frame)
        frame_datas.pack(fill='x')
        ttk.Label(frame_datas, text="De:").pack(side='left')
        date_inicio = DateEntry(frame_datas, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        date_inicio.pack(side='left', padx=5)
        ttk.Label(frame_datas, text="Até:").pack(side='left')
        date_fim = DateEntry(frame_datas, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        date_fim.pack(side='left', padx=5)

        def salvar_meta_principal():
            try:
                nome = entry_nome.get()
                setor = combo_setor.get()
                valor = float(entry_valor.get().replace(',', '.'))
                pontos = int(entry_pontos.get())
                inicio = date_inicio.get_date().strftime('%Y-%m-%d')
                fim = date_fim.get_date().strftime('%Y-%m-%d')

                if not all([nome, setor, valor, pontos, inicio, fim]):
                    messagebox.showerror("Erro", "Todos os campos são obrigatórios.", parent=popup)
                    return

                sucesso = database.criar_meta_principal(nome, "", valor, inicio, fim, pontos, setor)
                if sucesso:
                    messagebox.showinfo("Sucesso", "Meta principal criada com sucesso!", parent=popup)
                    self.carregar_dados_metas() # Atualiza a lista na tela principal
                    popup.destroy()
                else:
                    messagebox.showerror("Erro de Banco", "Não foi possível salvar a meta.", parent=popup)
            except ValueError:
                messagebox.showerror("Erro de Formato", "Valor da Meta e Pontos devem ser números.", parent=popup)

        ttk.Button(frame, text="Salvar Meta Principal", command=salvar_meta_principal).pack(pady=20)


        # --- NOVAS FUNÇÕES PARA GERENCIAR HISTÓRICO DE LUCRO ---
    # --- NOVAS FUNÇÕES PARA GERENCIAR HISTÓRICO DE LUCRO ---

    def atualizar_lista_lucros(self):
        """Carrega (ou recarrega) o histórico de lucros mensais na treeview."""
        try:
            for i in self.tree_lucros_lancados.get_children():
                self.tree_lucros_lancados.delete(i)

            lucros = database.listar_lucros_mensais()
            meses_nomes = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

            for lucro in lucros:
                lucro_id, ano, mes_num, percentual = lucro
                nome_mes = meses_nomes[mes_num] if 1 <= mes_num <= 12 else "Mês Inválido"
                percentual_f = f"{percentual:.2f} %"
                self.tree_lucros_lancados.insert("", "end", values=(lucro_id, ano, nome_mes, percentual_f))

        except Exception as e:
            logger.error(f"Erro ao atualizar lista de lucros: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível carregar o histórico de lucros:\n{e}", parent=self.root)

    def abrir_janela_edicao_lucro(self, event):
        """Chamada com duplo-clique para editar um lançamento de lucro."""
        selecionado = self.tree_lucros_lancados.focus()
        if not selecionado:
            return

        dados = self.tree_lucros_lancados.item(selecionado, 'values')
        try:
            lucro_id = int(dados[0])
            ano = dados[1]
            mes = dados[2]
            percentual_antigo_str = dados[3].replace(" %", "").replace(",", ".")

            novo_percentual_str = simpledialog.askstring(
                "Editar Percentual de Lucro",
                f"Digite o NOVO percentual de lucro para {mes} de {ano}:",
                initialvalue=percentual_antigo_str,
                parent=self.root
            )

            if novo_percentual_str is None:
                return # Usuário cancelou

            novo_percentual = float(novo_percentual_str.replace(",", "."))

            if database.atualizar_lucro_mensal(lucro_id, novo_percentual):
                messagebox.showinfo("Sucesso", "Percentual de lucro atualizado!", parent=self.root)
                self.atualizar_lista_lucros() # Recarrega a lista
            else:
                messagebox.showerror("Erro", "Não foi possível atualizar o registro no banco.", parent=self.root)

        except (ValueError, TypeError) as e:
            messagebox.showerror("Erro de Formato", f"Valor inválido: {novo_percentual_str}\nO percentual deve ser um número.", parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao editar lucro (ID: {lucro_id}): {e}", exc_info=True)
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro: {e}", parent=self.root)

    def excluir_lancamento_lucro_selecionado(self):
        """Exclui um lançamento de lucro selecionado na treeview."""
        selecionado = self.tree_lucros_lancados.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um lançamento da lista de histórico de lucro para excluir.", parent=self.root)
            return

        dados = self.tree_lucros_lancados.item(selecionado, 'values')
        try:
            lucro_id = int(dados[0])
            ano = dados[1]
            mes = dados[2]

            if not messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o lançamento de lucro de {mes} de {ano}?", parent=self.root):
                return

            if database.excluir_lucro_mensal(lucro_id):
                messagebox.showinfo("Sucesso", "Lançamento excluído com sucesso.", parent=self.root)
                self.atualizar_lista_lucros()
            else:
                messagebox.showerror("Erro", "Não foi possível excluir o registro do banco.", parent=self.root)

        except Exception as e:
            logger.error(f"Erro ao excluir lucro (ID: {lucro_id}): {e}", exc_info=True)
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao tentar excluir: {e}", parent=self.root)

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()

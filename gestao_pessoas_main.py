<<<<<<< HEAD
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
from tkinter import ttk, messagebox, Toplevel, Listbox, Checkbutton, Text, Entry, Scrollbar, Frame, Label, Button
from datetime import datetime
import database
import notificador_telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import time
import os
from tkinter import filedialog
from tkcalendar import DateEntry
import comunicado_generator
import file_utils
import recibo_generator
import config
import requests
import json
from PIL import Image, ImageTk
from fpdf import FPDF
import tempfile
import shutil

class AppGestaoPessoas:
    def __init__(self, root):
        self.root = root
        self.root.title("Módulo de Gestão de Pessoas (RH)")
        self.root.geometry("900x600")
        self.root.minsize(700, 400)
        
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        self.frame_comunicados = ttk.Frame(self.notebook, padding="10")
        self.frame_documentos = ttk.Frame(self.notebook, padding="10")
        # --- Variáveis de Login para Simulação de Acesso (Gestor ID 2) ---
        # Defina self.USUARIO_LOGADO_ID e self.nivel_usuario AQUI
        self.USUARIO_LOGADO_ID = 2 
        # Esta chamada requer que _buscar_nivel_acesso exista, o que faremos acima.
        # CORREÇÃO: Garante que o nível de usuário seja recuperado corretamente ou define um padrão para teste
        nivel_banco = self._buscar_nivel_acesso(self.USUARIO_LOGADO_ID)
        self.nivel_usuario = nivel_banco if nivel_banco else 'Gestor' # Fallback para 'Gestor' se não encontrar no banco para testes
        print(f"--> [DEBUG] Nível de Acesso do Usuário {self.USUARIO_LOGADO_ID}: {self.nivel_usuario}")
        self.frame_onboarding = ttk.Frame(self.notebook, padding="10") # <<< NOVA ABA

        self.notebook.add(self.frame_onboarding, text='📝 Onboarding/Admissional') # <<< NOVA ABA
        self.notebook.add(self.frame_comunicados, text='Comunicados')
        self.notebook.add(self.frame_documentos, text='Documentos Pessoais (RH)')
        
        self.dados_funcionarios = {}
        self.popup_criacao = None

        self.criar_aba_comunicados()
        self.criar_aba_documentos()
        self.criar_aba_onboarding() # <<< CHAMA A NOVA ABA
        
        self.atualizar_lista_comunicados()
        self.carregar_rh_funcionarios() # Carrega funcionários para a nova aba

    # --- ABA 1: COMUNICADOS ---
    def criar_aba_comunicados(self):
        self.frame_comunicados.grid_rowconfigure(2, weight=1)
        self.frame_comunicados.grid_columnconfigure(0, weight=1)
        # ... (código da interface da aba comunicados que já tínhamos)
        frame_botoes = ttk.Frame(self.frame_comunicados)
        frame_botoes.grid(row=0, column=0, sticky="ew")
        btn_novo = ttk.Button(frame_botoes, text="Criar Novo Comunicado", command=self.abrir_janela_criacao)
        btn_novo.pack(side="left")
        btn_atualizar = ttk.Button(frame_botoes, text="Atualizar Lista", command=self.atualizar_lista_comunicados)
        btn_atualizar.pack(side="left", padx=10)
        btn_detalhes = ttk.Button(frame_botoes, text="Ver Detalhes do Selecionado", command=self.abrir_janela_detalhes)
        btn_detalhes.pack(side="left", padx=10)
        btn_excluir = ttk.Button(frame_botoes, text="Excluir Comunicado", command=self.excluir_comunicado_selecionado)
        btn_excluir.pack(side="left", padx=10)
        frame_filtro = ttk.Frame(self.frame_comunicados)
        frame_filtro.grid(row=1, column=0, sticky="ew", pady=(5,0))
        lbl_filtro = ttk.Label(frame_filtro, text="Filtrar por Título:")
        lbl_filtro.pack(side="left")
        self.entry_filtro = ttk.Entry(frame_filtro, width=40)
        self.entry_filtro.pack(side="left", padx=5, fill="x", expand=True)
        btn_buscar = ttk.Button(frame_filtro, text="Buscar", command=self.filtrar_lista_comunicados)
        btn_buscar.pack(side="left", padx=(0, 5))
        btn_limpar = ttk.Button(frame_filtro, text="Limpar", command=self.limpar_filtro)
        btn_limpar.pack(side="left")
        frame_lista = ttk.Frame(self.frame_comunicados)
        frame_lista.grid(row=2, column=0, sticky="nsew", pady=(5,0))
        frame_lista.grid_rowconfigure(0, weight=1)
        frame_lista.grid_columnconfigure(0, weight=1)
        cols = ('ID', 'Título', 'Data de Criação', 'Status')
        self.tree_comunicados = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')
        self.tree_comunicados.heading('ID', text='ID'); self.tree_comunicados.column('ID', width=50, anchor='center')
        self.tree_comunicados.heading('Título', text='Título'); self.tree_comunicados.column('Título', width=350)
        self.tree_comunicados.heading('Data de Criação', text='Enviado em'); self.tree_comunicados.column('Data de Criação', width=150, anchor='center')
        self.tree_comunicados.heading('Status', text='Status'); self.tree_comunicados.column('Status', width=120, anchor='center')
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.tree_comunicados.yview)
        self.tree_comunicados.configure(yscrollcommand=scrollbar.set)
        self.tree_comunicados.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    # --- ABA 2: DOCUMENTOS PESSOAIS ---
    def criar_aba_documentos(self):
        main_frame = ttk.Frame(self.frame_documentos)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)
        frame_funcionarios = ttk.LabelFrame(main_frame, text="Selecionar Funcionário", padding="10")
        frame_funcionarios.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame_funcionarios.rowconfigure(0, weight=1)
        frame_funcionarios.columnconfigure(0, weight=1)
        cols_func = ('ID', 'Nome')
        self.tree_rh_funcionarios = ttk.Treeview(frame_funcionarios, columns=cols_func, show='headings', selectmode='browse')
        self.tree_rh_funcionarios.heading('ID', text='ID'); self.tree_rh_funcionarios.column('ID', width=40)
        self.tree_rh_funcionarios.heading('Nome', text='Nome')
        self.tree_rh_funcionarios.grid(row=0, column=0, sticky="nsew")
        self.tree_rh_funcionarios.bind('<<TreeviewSelect>>', self.on_rh_funcionario_selecionado)
        frame_docs = ttk.LabelFrame(main_frame, text="Documentos Enviados", padding="10")
        frame_docs.grid(row=0, column=1, sticky="nsew")
        frame_docs.rowconfigure(0, weight=1)
        frame_docs.columnconfigure(0, weight=1)
        cols_docs = ('ID Doc', 'Tipo', 'Referência', 'Data Upload', 'Status Ciência', 'Data da Ciência')
        self.tree_rh_documentos = ttk.Treeview(frame_docs, columns=cols_docs, show='headings', selectmode='browse')
        self.tree_rh_documentos.heading('ID Doc', text='ID'); self.tree_rh_documentos.column('ID Doc', width=40)
        self.tree_rh_documentos.heading('Tipo', text='Tipo de Documento'); self.tree_rh_documentos.column('Tipo', width=150)
        self.tree_rh_documentos.heading('Referência', text='Mês/Ano Ref.'); self.tree_rh_documentos.column('Referência', width=100, anchor='center')
        self.tree_rh_documentos.heading('Data Upload', text='Data de Upload'); self.tree_rh_documentos.column('Data Upload', width=150, anchor='center')
        self.tree_rh_documentos.heading('Status Ciência', text='Status')
        self.tree_rh_documentos.column('Status Ciência', width=100, anchor='center')
        self.tree_rh_documentos.heading('Data da Ciência', text='Data da Ciência')
        self.tree_rh_documentos.column('Data da Ciência', width=150, anchor='center')
        self.tree_rh_documentos.grid(row=0, column=0, sticky="nsew")
        frame_botoes_docs = ttk.Frame(frame_docs)
        frame_botoes_docs.grid(row=1, column=0, sticky="ew", pady=(10,0))
        
        btn_solicitar_onboarding = ttk.Button(frame_botoes_docs, text="🚀 Solicitar Documentos (Onboarding)", command=self.solicitar_onboarding_funcionario)
        btn_solicitar_onboarding.pack(side="left", padx=(0, 20))
        btn_add = ttk.Button(frame_botoes_docs, text="Adicionar Novo Documento...", command=self.abrir_janela_add_documento)
        btn_add.pack(side="left")
        
        # --- NOVOS BOTÕES ---
        btn_edit = ttk.Button(frame_botoes_docs, text="Editar Metadados", command=self.abrir_janela_edicao_documento)
        btn_edit.pack(side="left", padx=10)
        
        btn_del = ttk.Button(frame_botoes_docs, text="Excluir Documento", command=self.excluir_documento_selecionado)
        btn_del.pack(side="left", padx=10)
        # --- FIM NOVOS BOTÕES ---

        btn_vis = ttk.Button(frame_botoes_docs, text="Visualizar/Baixar Documento", command=self.visualizar_documento_selecionado)
        btn_vis.pack(side="right")


    def criar_aba_onboarding(self):
        """Cria a interface para gerenciar a aprovação do exame admissional."""
        # Acesso restrito apenas a Gestores e RH para evitar leaks de dados
        if self.nivel_usuario not in ('RH', 'Gestor'):
            ttk.Label(self.frame_onboarding, text="ACESSO NEGADO: Esta área é restrita ao RH/Gestão.", font=("Arial", 16, "bold"), foreground="red").pack(pady=50)
            return

        main_frame = ttk.Frame(self.frame_onboarding)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # Treeview de Funcionários Prontos
        cols = ('ID', 'Nome', 'Status Documentos', 'Status Admissional', 'Última Etapa', 'Data Admissional')
        self.tree_onboarding = ttk.Treeview(main_frame, columns=cols, show='headings', selectmode='browse')
        for col in cols: self.tree_onboarding.heading(col, text=col)

        self.tree_onboarding.column('ID', width=40)
        self.tree_onboarding.column('Status Documentos', width=120, anchor='center')
        self.tree_onboarding.column('Status Admissional', width=120, anchor='center')
        self.tree_onboarding.column('Data Admissional', width=120, anchor='center')

        self.tree_onboarding.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tree_onboarding.bind('<<TreeviewSelect>>', self.on_onboarding_selecionado)

        # Botões de Ação
        frame_botoes = ttk.Frame(main_frame)
        frame_botoes.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        
        ttk.Button(frame_botoes, text="🔄 Atualizar Lista", command=self.carregar_onboarding_lista).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="📂 Ver Documentos Enviados", command=self.abrir_janela_documentos_onboarding).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="📋 Ver Dados Cadastrais", command=self.ver_dados_cadastrais_selecionado).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="🗑️ Excluir Cadastro", command=self.excluir_candidato_onboarding).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="🔄 Reiniciar Processo", command=self.reiniciar_processo_onboarding).pack(side="left", padx=5)
        self.btn_aprovar_admissional = ttk.Button(frame_botoes, text="✅ Aprovar Exame Admissional", command=self.aprovar_exame_admissional_rh)
        self.btn_aprovar_admissional.pack(side="right", padx=5)

        self.carregar_onboarding_lista()

    def carregar_onboarding_lista(self):
        """Carrega a lista de funcionários com onboarding completo/pendente para a Treeview."""
        for i in self.tree_onboarding.get_children(): self.tree_onboarding.delete(i)
        
        funcionarios = database.buscar_onboarding_lista_rh()
        
        for f in funcionarios:
            data_admissional = f.DataAdmissional.strftime('%d/%m/%Y') if f.DataAdmissional else '---'
            
            self.tree_onboarding.insert("", "end", values=(
                f.FuncionarioID, f.NomeCompleto, f.StatusWorkflow, f.StatusAdmissional, f.UltimaEtapa, data_admissional
            ))

    def on_onboarding_selecionado(self, event):
        """Habilita/desabilita o botão de aprovação e armazena os dados de download."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado: return
        
        dados = self.tree_onboarding.item(selecionado, 'values')
        status_admissional = dados[3]
        
        if status_admissional == 'Pendente':
            self.btn_aprovar_admissional.config(state="normal")
        else:
            self.btn_aprovar_admissional.config(state="disabled")

    def aprovar_exame_admissional_rh(self):
        """Dispara a aprovação manual do exame admissional."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado: return
        
        dados = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id = dados[0]
        nome_funcionario = dados[1]

        if dados[3] != 'Pendente':
            messagebox.showwarning("Aviso", "O exame deste funcionário já foi aprovado.")
            return

        confirmado = messagebox.askyesno("Confirmar Aprovação", f"Tem certeza que deseja aprovar o exame admissional para {nome_funcionario}?\n\nIsso liberará o acesso TOTAL dele ao Bot Telegram.")

        if confirmado:
            hoje = datetime.now()
            if database.aprovar_exame_admissional(funcionario_id, hoje):
                
                # 1. Notificação de Liberação Total
                func_obj = database.buscar_funcionario_por_id(funcionario_id)
                if func_obj and func_obj.ChatIDTelegram:
                     notificador_telegram.enviar_mensagem(
                        func_obj.ChatIDTelegram,
                        "🎉 **PARABÉNS! SEU EXAME ADMISSIONAL FOI APROVADO!** 🎉\n\n"
                        "Seu acesso ao sistema de Gamificação está **TOTALMENTE LIBERADO**! "
                        "Você já pode usar todos os comandos (Tarefas, Ranking, Saldo). Bom trabalho! 🚀"
                    )

                # 2. Atualiza a lista na interface
                self.carregar_onboarding_lista()
                messagebox.showinfo("Sucesso", "Admissional Aprovado! Acesso liberado no sistema.")
            else:
                messagebox.showerror("Erro", "Falha ao atualizar o status no banco de dados.")

    def excluir_candidato_onboarding(self):
        """Exclui permanentemente o cadastro do candidato selecionado."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista para excluir.")
            return

        # Recupera dados da linha selecionada
        dados = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id = dados[0]
        nome = dados[1]

        # Confirmação de Segurança
        confirmacao = messagebox.askyesno(
            "Confirmar Exclusão",
            f"Tem certeza que deseja excluir o cadastro de '{nome}'?\n\n"
            "⚠️ ATENÇÃO: Esta ação apagará TODOS os dados, documentos e histórico deste funcionário permanentemente.\n"
            "Não será possível desfazer.",
            icon='warning',
            default='no',
            parent=self.root
        )

        if confirmacao:
            try:
                # Usa a função do database que já faz a limpeza em cascata
                database.excluir_funcionario(funcionario_id)
                messagebox.showinfo("Sucesso", "Cadastro excluído com sucesso!", parent=self.root)
                self.carregar_onboarding_lista() # Atualiza a lista
            except Exception as e:
                logger.error(f"Erro ao excluir candidato {funcionario_id}: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao excluir cadastro:\n{e}", parent=self.root)

    def abrir_janela_documentos_onboarding(self):
        """Abre uma janela para visualizar os File IDs dos documentos enviados."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um funcionário da lista.")
            return

        funcionario_id = self.tree_onboarding.item(selecionado, 'values')[0]
        nome_funcionario = self.tree_onboarding.item(selecionado, 'values')[1]
        
        file_ids = database.buscar_documentos_onboarding_para_download(funcionario_id)

        popup = Toplevel(self.root)
        popup.title(f"Documentos de Admissão - {nome_funcionario}")
        popup.geometry("600x400")
        popup.transient(self.root)

        # ... (Implementação do painel de download que utiliza a função buscar_documentos_onboarding_para_download) ...
        # (O painel de download em si é complexo, mas a função de banco está no lugar certo)
        
        # Simplificação: Apenas mostra os botões de download
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Documentos Enviados (Clique para Download):", font=("Arial", 12)).pack(anchor='w', pady=(0, 10))
        
        if not file_ids:
             ttk.Label(frame, text="Nenhum documento finalizado (Workflow incompleto).", foreground="gray").pack()
             return

        for doc_name, file_id in file_ids.items():
            if file_id:
                # O botão deve ter uma função que chama o notificador_telegram para baixar a foto/documento
                ttk.Button(frame, text=f"📥 Baixar {doc_name}", 
                           command=lambda fid=file_id, dn=doc_name: self.disparar_download_documento(fid, dn, popup)
                ).pack(fill='x', pady=5)
            else:
                 ttk.Label(frame, text=f"❌ {doc_name}: Não enviado ou File ID inválido.").pack(anchor='w', pady=2)

    def ver_dados_cadastrais_selecionado(self):
        """
        Exibe dados textuais E imagens dos documentos, com opção de gerar PDF profissional.
        """
        selecionado = self.tree_onboarding.focus()
        if not selecionado: return

        vals = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id, nome = vals[0], vals[1]

        status = database.buscar_onboarding_status(funcionario_id)
        if not status: 
            messagebox.showinfo("Aviso", "Sem dados de onboarding encontrados.", parent=self.root)
            return

        # --- 1. Preparação da Janela com Scroll (Necessário para muitas fotos) ---
        popup = Toplevel(self.root)
        popup.title(f"Prontuário Digital - {nome}")
        popup.geometry("650x800")

        # Container principal
        main_container = ttk.Frame(popup)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- 2. Preparação dos Dados ---
        # Dicionário para guardar caminhos locais das imagens baixadas (para o PDF)
        cache_imagens = {} 

        # Função interna para o botão de PDF
        def acao_gerar_pdf():
            self.gerar_pdf_prontuario(nome, status, cache_imagens)

        # Botão de Exportação no Topo
        frame_topo = ttk.Frame(scrollable_frame, padding="10")
        frame_topo.pack(fill="x")
        btn_pdf = ttk.Button(frame_topo, text="🖨️ Gerar PDF Completo (Dados + Fotos)", command=acao_gerar_pdf)
        btn_pdf.pack(fill="x", ipady=8)

        # --- 3. Exibição dos Dados (Texto) ---
        lbl_dados = tk.Label(scrollable_frame, text="DADOS CADASTRAIS", font=("Arial", 12, "bold"), bg="#e0e0e0", anchor="w", padx=5)
        lbl_dados.pack(fill="x", pady=(10, 5))

        texto_dados = f"Funcionário: {nome} (ID: {funcionario_id})\n"
        texto_dados += f"Escolaridade: {status.Escolaridade or '---'}\n"
        texto_dados += f"Estado Civil: {status.EstadoCivil or '---'}\n"

        if status.EstadoCivil and 'CASADO' in status.EstadoCivil.upper():
            texto_dados += f"Data Casamento: {status.DataCasamento or '---'}\n"
            texto_dados += f"Cônjuge: {status.NomeConjugue or '---'}\n"
            texto_dados += f"CPF Cônjuge: {status.CPFConjugue or '---'}\n"

        texto_dados += f"\nDEPENDENTES ({status.QtdFilhos or 0}):\n"
        if status.DadosFilhos:
            try:
                filhos = json.loads(status.DadosFilhos)
                for i, f in enumerate(filhos, 1):
                    texto_dados += f"- {f.get('Nome', '')} ({f.get('Nasc', '')}) CPF: {f.get('CPF', '')}\n"
            except: texto_dados += "(Erro na leitura dos dependentes)"
        else:
            texto_dados += "- Nenhum dependente declarado."

        tk.Label(scrollable_frame, text=texto_dados, justify="left", font=("Consolas", 10), bg="white", relief="solid", bd=1, padx=10, pady=10).pack(fill="x", padx=10)

        # --- 4. Exibição das Imagens (Visualização) ---
        lbl_docs = tk.Label(scrollable_frame, text="DOCUMENTOS DIGITALIZADOS", font=("Arial", 12, "bold"), bg="#e0e0e0", anchor="w", padx=5)
        lbl_docs.pack(fill="x", pady=(20, 5))

        docs_map = {
            "RG (Identidade)": status.RG_FileID,
            "CPF": status.CPF_FileID,
            "Carteira de Trabalho (CTPS)": status.CTPS_FileID,
            "Título de Eleitor": status.TituloEleitor_FileID
        }

        # Diretório temporário para cache de visualização
        temp_dir = os.path.join(os.getcwd(), "temp_view")
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)

        for titulo, file_id in docs_map.items():
            frame_doc = ttk.LabelFrame(scrollable_frame, text=titulo, padding="5")
            frame_doc.pack(fill="x", padx=10, pady=5)

            if file_id:
                # Baixa a imagem para exibir
                caminho_local = self._baixar_imagem_cache(file_id, temp_dir)

                if caminho_local:
                    cache_imagens[titulo] = caminho_local # Guarda referência para o PDF

                    try:
                        # Carrega e Redimensiona para o Painel (Thumbnail)
                        pil_img = Image.open(caminho_local)
                        # Redimensiona mantendo proporção (largura max 400px)
                        base_width = 400
                        w_percent = (base_width / float(pil_img.size[0]))
                        h_size = int((float(pil_img.size[1]) * float(w_percent)))
                        pil_img = pil_img.resize((base_width, h_size), Image.Resampling.LANCZOS)

                        tk_img = ImageTk.PhotoImage(pil_img)

                        lbl_img = tk.Label(frame_doc, image=tk_img)
                        lbl_img.image = tk_img # Mantém referência na memória para não sumir
                        lbl_img.pack()
                    except Exception:
                        tk.Label(frame_doc, text="[Arquivo PDF ou Formato não suportado para prévia]", fg="blue").pack()
                else:
                    tk.Label(frame_doc, text="Erro ao baixar arquivo do servidor.", fg="red").pack()
            else:
                tk.Label(frame_doc, text="Pendente / Não enviado", fg="gray").pack()

    def _baixar_imagem_cache(self, file_id, pasta_destino):
        """Baixa arquivo do Telegram para cache local."""
        try:
            token = config.TELEGRAM_TOKEN
            # 1. Pega o caminho
            url_info = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
            r = requests.get(url_info, timeout=5).json()
            if not r.get('ok'): return None

            file_path = r['result']['file_path']
            ext = os.path.splitext(file_path)[1]
            if not ext: ext = ".jpg"

            nome_arquivo = f"{file_id}{ext}"
            caminho_completo = os.path.join(pasta_destino, nome_arquivo)

            # Cache: Se já baixou, usa o local
            if os.path.exists(caminho_completo): return caminho_completo

            # 2. Baixa o conteúdo
            url_download = f"https://api.telegram.org/file/bot{token}/{file_path}"
            r_img = requests.get(url_download, timeout=20)

            if r_img.status_code == 200:
                with open(caminho_completo, 'wb') as f:
                    f.write(r_img.content)
                return caminho_completo
        except: return None
        return None

    def gerar_pdf_prontuario(self, nome_funcionario, status, cache_imagens):
        """Gera PDF profissional com dados e imagens anexadas."""
        try:
            dest = filedialog.asksaveasfilename(
                title="Salvar Prontuário PDF",
                defaultextension=".pdf",
                initialfile=f"Prontuario_{nome_funcionario.replace(' ', '_')}.pdf"
            )
            if not dest: return

            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # --- Cabeçalho ---
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Ficha de Registro de Colaborador", ln=True, align="C")
            pdf.set_font("Arial", "I", 10)
            pdf.cell(0, 10, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
            pdf.ln(10)

            # --- Tabela de Dados ---
            pdf.set_fill_color(240, 240, 240)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "1. DADOS PESSOAIS", ln=True, fill=True)
            pdf.ln(2)

            pdf.set_font("Arial", "", 11)
            pdf.multi_cell(0, 8, f"Nome: {nome_funcionario}\nEscolaridade: {status.Escolaridade}\nEstado Civil: {status.EstadoCivil}")

            if status.EstadoCivil and 'CASADO' in status.EstadoCivil.upper():
                pdf.multi_cell(0, 8, f"Cônjuge: {status.NomeConjugue}\nCPF Cônjuge: {status.CPFConjugue}")

            pdf.ln(5)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, f"2. DEPENDENTES ({status.QtdFilhos or 0})", ln=True, fill=True)

            if status.DadosFilhos:
                try:
                    filhos = json.loads(status.DadosFilhos)
                    pdf.set_font("Arial", "", 10)
                    for i, f in enumerate(filhos, 1):
                        pdf.cell(0, 8, f"{i}. {f.get('Nome','')} - CPF: {f.get('CPF','')}", ln=True)
                except: pass
            else:
                pdf.set_font("Arial", "I", 10)
                pdf.cell(0, 8, "Nenhum dependente declarado.", ln=True)

            # --- Imagens (Uma por página ou ajustada) ---
            pdf.add_page()
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "3. DOCUMENTOS DIGITALIZADOS", ln=True, fill=True)
            pdf.ln(5)

            for titulo, caminho_img in cache_imagens.items():
                if caminho_img and os.path.exists(caminho_img) and caminho_img.endswith(('.jpg', '.png', '.jpeg')):
                    pdf.set_font("Arial", "B", 11)
                    pdf.cell(0, 10, titulo, ln=True)

                    # Centraliza imagem na página A4 (largura aprox 190mm útil)
                    try:
                        pdf.image(caminho_img, w=170) 
                    except:
                        pdf.cell(0, 10, "[Erro ao renderizar imagem no PDF]", ln=True)

                    pdf.ln(10)
                elif caminho_img and ".pdf" in caminho_img:
                    pdf.set_font("Arial", "I", 10)
                    pdf.cell(0, 10, f"{titulo}: Arquivo PDF anexado original não pode ser mesclado aqui.", ln=True)

            pdf.output(dest)
            messagebox.showinfo("Sucesso", "Prontuário PDF gerado com sucesso!", parent=self.root)
            file_utils.abrir_arquivo(dest)

        except Exception as e:
            logger.error(f"Erro PDF: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Falha ao criar PDF: {e}", parent=self.root)

    def disparar_download_documento(self, file_id, doc_name, parent_popup):
        """Baixa o arquivo real da API do Telegram e salva onde o usuário escolher."""
        try:
            # 1. Define extensão provável
            ext = ".jpg" # Padrão fotos Telegram
            if "pdf" in doc_name.lower(): ext = ".pdf"

            # 2. Pede ao usuário onde salvar
            caminho_destino = filedialog.asksaveasfilename(
                title=f"Salvar {doc_name}",
                defaultextension=ext,
                initialfile=f"{doc_name}_{file_id[:5]}{ext}",
                parent=parent_popup
            )

            if not caminho_destino: return # Cancelado pelo usuário

            # 3. Obtém o caminho do arquivo na API Telegram
            token = config.TELEGRAM_TOKEN
            url_info = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"

            r_info = requests.get(url_info, timeout=10)
            if r_info.status_code != 200:
                messagebox.showerror("Erro API", "Falha ao localizar arquivo no Telegram.", parent=parent_popup)
                return

            file_path_remoto = r_info.json().get('result', {}).get('file_path')
            if not file_path_remoto:
                messagebox.showerror("Erro API", "Caminho remoto não encontrado.", parent=parent_popup)
                return

            # 4. Baixa o conteúdo binário
            url_download = f"https://api.telegram.org/file/bot{token}/{file_path_remoto}"
            r_content = requests.get(url_download, timeout=30)

            if r_content.status_code == 200:
                with open(caminho_destino, 'wb') as f:
                    f.write(r_content.content)

                messagebox.showinfo("Sucesso", f"Download concluído!\nSalvo em: {caminho_destino}", parent=parent_popup)
                file_utils.abrir_arquivo(caminho_destino)
            else:
                messagebox.showerror("Erro Download", f"Falha ao baixar bytes: {r_content.status_code}", parent=parent_popup)

        except Exception as e:
            logger.error(f"Erro no download manual: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Falha no download: {e}", parent=parent_popup)


    def visualizar_documento_selecionado(self):
        """Baixa o documento selecionado da API e o abre."""
        selecionado = self.tree_rh_documentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista da direita.")
            return
        dados_doc = self.tree_rh_documentos.item(selecionado, 'values')
        documento_id = dados_doc[0]
        # REMOVIDO: A linha que forçava .pdf foi substituída pela lógica abaixo

        url_download = f"{config.API_BASE_URL}/documentos/download/{documento_id}"

        try:
            print(f"--> Solicitando download do documento ID {documento_id}...")
            response = requests.get(url_download, stream=True)

            if response.status_code == 200:
                # --- CORREÇÃO DE PARSE DE HEADER ---
                import cgi
                nome_remoto = ""
                
                header_content = response.headers.get("Content-Disposition")
                if header_content:
                    try:
                        # Tenta usar cgi para parsear corretamente (lida com aspas, utf-8, etc)
                        _, params = cgi.parse_header(header_content)
                        if 'filename' in params:
                            nome_remoto = params['filename']
                        elif 'filename*' in params:
                            # Tratamento básico para filename* (UTF-8)
                            encoding, _, filename = params['filename*'].split("'", 2)
                            nome_remoto = urllib.parse.unquote(filename)
                    except Exception:
                        # Fallback para regex simples se cgi falhar
                        import re
                        fname = re.findall('filename="?([^"]+)"?', header_content)
                        if fname:
                            nome_remoto = fname[0]

                # Fallback final se o header falhar ou não existir
                if not nome_remoto:
                    ext = ".pdf" 
                    content_type = response.headers.get("Content-Type", "")
                    if "image/jpeg" in content_type: ext = ".jpg"
                    elif "image/png" in content_type: ext = ".png"
                    
                    # Nome seguro baseado nos dados da lista
                    safe_tipo = "".join(x for x in dados_doc[1] if x.isalnum())
                    nome_remoto = f"{safe_tipo}_{documento_id}{ext}"

                # Limpeza de caracteres inválidos no nome do arquivo (segurança extra)
                nome_remoto = os.path.basename(nome_remoto) 
                # -----------------------------------

                pasta_downloads = "downloads"
                if not os.path.exists(pasta_downloads):
                    os.makedirs(pasta_downloads)

                caminho_local = os.path.join(pasta_downloads, nome_remoto)
                # Salva o arquivo recebido no disco local
                with open(caminho_local, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                print(f"--> Download concluído! Arquivo salvo em: {caminho_local}")
                file_utils.abrir_arquivo(caminho_local)
            else:
                # --- CORREÇÃO: Tratamento seguro de resposta de erro ---
                try:
                    # Tenta ler como JSON se a API retornar estrutura padrão
                    erro_json = response.json()
                    msg_erro = erro_json.get('mensagem', 'Erro desconhecido no servidor.')
                except Exception:
                    # Se falhar (ex: erro 500 HTML ou Proxy), usa o texto cru limitado
                    texto_erro = response.text[:200] if response.text else "Sem conteúdo"
                    msg_erro = f"Erro HTTP {response.status_code}: {texto_erro}"

                messagebox.showerror("Erro da API", f"Não foi possível baixar o arquivo:\n{msg_erro}")

        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API para baixar o arquivo: {e}")

    def carregar_rh_funcionarios(self):
        for i in self.tree_rh_funcionarios.get_children(): self.tree_rh_funcionarios.delete(i)
        funcionarios = database.listar_funcionarios()
        for func in funcionarios: self.tree_rh_funcionarios.insert("", "end", values=(func.FuncionarioID, func.NomeCompleto))

    def on_rh_funcionario_selecionado(self, event):
        """Chamada quando um funcionário é selecionado. Carrega seus documentos e status de ciência."""
        for i in self.tree_rh_documentos.get_children():
            self.tree_rh_documentos.delete(i)

        selecionado = self.tree_rh_funcionarios.focus()
        if not selecionado:
            return

        funcionario_id = self.tree_rh_funcionarios.item(selecionado, 'values')[0]
        
        documentos = database.listar_documentos_por_funcionario(funcionario_id)
        for doc in documentos:
            # Formata as datas para exibição
            mes_ano_ref = doc.MesAno.strftime("%m/%Y")
            data_upload = doc.DataUpload.strftime("%d/%m/%Y %H:%M")
            status_ciencia = doc.Status or "N/A" # Pega o status
            data_ciencia = doc.DataCiencia.strftime("%d/%m/%Y %H:%M") if doc.DataCiencia else "---" # Pega a data da ciência

            # Insere todos os dados na tabela
            self.tree_rh_documentos.insert("", "end", values=(
                doc.DocumentoID, doc.TipoDocumento, mes_ano_ref, data_upload, status_ciencia, data_ciencia
            ))
    def excluir_documento_selecionado(self):
        """Chama a API para excluir o documento selecionado (banco + arquivo)."""
        selecionado = self.tree_rh_documentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista para excluir.")
            return

        dados_doc = self.tree_rh_documentos.item(selecionado, 'values')
        documento_id = dados_doc[0]
        tipo_doc = dados_doc[1]
        mes_ano_ref = dados_doc[2]

        confirmado = messagebox.askyesno(
            "Confirmar Exclusão", 
            f"Tem certeza que deseja excluir o documento:\n\nTipo: {tipo_doc}\nReferência: {mes_ano_ref}\n\n"
            f"Esta ação removerá o registro do banco e o arquivo físico no servidor. NÃO PODE SER DESFEITA.", 
            icon='warning'
        )

        if confirmado:
            try:
                # Chamada DELETE para a API
                url = f"{config.API_BASE_URL}/documentos/excluir/{documento_id}"
                response = requests.delete(url)

                if response.status_code == 200:
                    messagebox.showinfo("Sucesso", "Documento excluído com sucesso!")
                    self.on_rh_funcionario_selecionado(None) # Recarrega a lista
                else:
                    msg_erro = response.json().get('mensagem', 'Erro desconhecido')
                    messagebox.showerror("Erro da API", f"Falha ao excluir: {msg_erro}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Erro de conexão ao excluir documento: {e}", exc_info=True)
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar ao servidor: {e}")
                
    def _buscar_nivel_acesso(self, funcionario_id):
        """Busca o NivelAcesso de um funcionário pelo ID (função auxiliar)."""
        conn = database.get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                sql = "SELECT NivelAcesso FROM Funcionarios WHERE FuncionarioID = ?"
                cursor.execute(sql, funcionario_id)
                resultado = cursor.fetchone()
                return resultado[0] if resultado else 'Funcionario' # Retorna o primeiro campo
            except Exception as e:
                logger.error(f"Falha ao buscar NivelAcesso para ID {funcionario_id}: {e}")
                return 'Funcionario' # Default seguro
            finally:
                conn.close()
        return 'Funcionario'

    def abrir_janela_edicao_documento(self):
        """Abre a janela Toplevel para editar os metadados do documento selecionado."""
        selecionado = self.tree_rh_documentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista para editar.")
            return

        dados_doc = self.tree_rh_documentos.item(selecionado, 'values')
        documento_id = dados_doc[0]
        tipo_atual = dados_doc[1]
        mes_ano_ref_atual = dados_doc[2] # dd/mm/yyyy

        # Converte para objeto datetime para o DateEntry usar
        try:
            data_ref_obj = datetime.strptime(f"01/{mes_ano_ref_atual}", "%d/%m/%Y").date()
        except ValueError:
            data_ref_obj = datetime.now().date() # Fallback

        # --- Criação da Janela Pop-up ---
        popup = Toplevel(self.root)
        popup.title(f"Editar Documento ID: {documento_id}")
        popup.geometry("350x250")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        # --- Widgets do Formulário ---
        ttk.Label(frame, text="Tipo de Documento:").grid(row=0, column=0, sticky="w", pady=5)
        combo_tipo = ttk.Combobox(frame, values=['Holerite', 'Cartão Ponto', 'Comprovante de Consumo', 'Contrato', 'Atestado', 'Advertência', 'Outro'])
        combo_tipo.grid(row=0, column=1, sticky="ew", pady=5)
        combo_tipo.set(tipo_atual)

        ttk.Label(frame, text="Mês/Ano de Referência:").grid(row=1, column=0, sticky="w", pady=5)
        entry_data_ref = DateEntry(frame, date_pattern='dd/mm/yyyy', width=18)
        entry_data_ref.grid(row=1, column=1, sticky="w", pady=5)
        entry_data_ref.set_date(data_ref_obj)

        ttk.Label(frame, text=f"Arquivo atual: {dados_doc[3].split()[0]}").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 5))
        ttk.Label(frame, text="*Não é possível alterar o arquivo físico.", font=("Arial", 8, "italic")).grid(row=3, column=0, columnspan=2, sticky="w")


        def salvar_edicao():
            novo_tipo = combo_tipo.get()
            nova_data_ref_obj = entry_data_ref.get_date()
            nova_data_ref_db = nova_data_ref_obj.strftime('%Y-%m-%d') # Formato que o banco espera

            if not novo_tipo:
                messagebox.showerror("Erro", "O Tipo de Documento é obrigatório.", parent=popup)
                return

            try:
                sucesso = database.atualizar_documento_pessoal_metadados(documento_id, novo_tipo, nova_data_ref_db)

                if sucesso:
                    messagebox.showinfo("Sucesso", "Metadados do documento atualizados!", parent=popup)
                    popup.destroy()
                    self.on_rh_funcionario_selecionado(None) # Recarrega a lista
                else:
                    messagebox.showwarning("Aviso", "Nenhuma alteração detectada ou falha na atualização.")

            except Exception as e:
                messagebox.showerror("Erro", f"Ocorreu um erro ao salvar: {e}", parent=popup)

        # Botão de Envio
        btn_salvar = ttk.Button(frame, text="Salvar Metadados", command=salvar_edicao)
        btn_salvar.grid(row=4, column=0, columnspan=2, pady=20, ipady=5)

        frame.columnconfigure(1, weight=1)

    def abrir_janela_add_documento(self):
        """Abre a janela (Toplevel) para adicionar um novo documento pessoal."""
        selecionado = self.tree_rh_funcionarios.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário na lista da esquerda primeiro.")
            return
        
        dados_func = self.tree_rh_funcionarios.item(selecionado, 'values')
        funcionario_id = dados_func[0]
        nome_funcionario = dados_func[1]

        # --- Criação da Janela Pop-up ---
        popup = Toplevel(self.root)
        popup.title(f"Adicionar Documento para {nome_funcionario}")
        popup.geometry("450x300")
        popup.transient(self.root) # Mantém o pop-up na frente da janela principal

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        # --- Widgets do Formulário ---
        ttk.Label(frame, text="Tipo de Documento:").grid(row=0, column=0, sticky="w", pady=5)
        combo_tipo = ttk.Combobox(frame, values=['Holerite', 'Cartão Ponto', 'Comprovante de Consumo', 'Contrato', 'Atestado', 'Advertência', 'Outro'])
        combo_tipo.grid(row=0, column=1, sticky="ew", pady=5)
        combo_tipo.set('Holerite')

        ttk.Label(frame, text="Mês/Ano de Referência:").grid(row=1, column=0, sticky="w", pady=5)
        # Usaremos um DateEntry para facilitar a seleção
        from tkcalendar import DateEntry
        entry_data_ref = DateEntry(frame, date_pattern='dd/mm/yyyy', width=18)
        entry_data_ref.grid(row=1, column=1, sticky="w", pady=5)

        ttk.Label(frame, text="Arquivo (PDF, JPG, PNG):").grid(row=2, column=0, sticky="w", pady=5) # <-- Texto alterado
        frame_arquivo = ttk.Frame(frame)
        frame_arquivo.grid(row=2, column=1, sticky="ew", pady=5)
        
        lbl_caminho_pdf = ttk.Label(frame_arquivo, text="Nenhum arquivo selecionado.")
        lbl_caminho_pdf.pack(side="right", fill="x", expand=True)
        
        caminho_arquivo_selecionado = {"path": ""} # Usamos um dicionário para passar por referência

        # --- CORREÇÃO 1: Adicionado suporte a .png na seleção ---
        def selecionar_arquivo():
            filepath = filedialog.askopenfilename(
                title="Selecione o documento (PDF, JPG ou PNG)",
                filetypes=[
                    ("Documentos Suportados", "*.pdf *.jpg *.jpeg *.png"), # <-- ADICIONADO .png
                    ("Arquivos PDF", "*.pdf"),
                    ("Imagens JPG", "*.jpg *.jpeg"),
                    ("Imagens PNG", "*.png") # <-- ADICIONADA NOVA LINHA
                ]
            )
            if filepath:
                caminho_arquivo_selecionado["path"] = filepath
                lbl_caminho_pdf.config(text=os.path.basename(filepath))

        btn_selecionar = ttk.Button(frame_arquivo, text="Selecionar...", command=selecionar_arquivo) # <-- Usa a nova função
        btn_selecionar.pack(side="left")

        # --- Lógica de Envio ---
        def enviar_documento():
            # Coleta de dados
            tipo = combo_tipo.get()
            data_ref = entry_data_ref.get_date()
            caminho_arquivo = caminho_arquivo_selecionado["path"]

            if not all([tipo, data_ref, caminho_arquivo]):
                messagebox.showerror("Erro", "Todos os campos são obrigatórios.", parent=popup)
                return

            # --- CORREÇÃO 2: Adicionado suporte a .png no MIME type ---
            nome_arquivo = os.path.basename(caminho_arquivo)
            # Pega a extensão (ex: '.jpg' ou '.pdf')
            extensao = os.path.splitext(nome_arquivo)[1].lower() 

            if extensao == '.pdf':
                mime_type = 'application/pdf'
            elif extensao in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif extensao == '.png': # <-- ADICIONADO ELIF
                mime_type = 'image/png'
            else:
                messagebox.showerror("Erro", "Tipo de arquivo não suportado. Use PDF, JPG ou PNG.", parent=popup)
                return
            # --- FIM DA CORREÇÃO 2 ---

            # Prepara os dados para enviar à API
            url_upload = f"{config.API_BASE_URL}/documentos/upload" # ATENÇÃO AO IP!
            dados_payload = {
                'funcionario_id': funcionario_id,
                'tipo_documento': tipo,
                'mes_ano': data_ref.strftime('%Y-%m-%d'),
            }
            
            try:
                with open(caminho_arquivo, 'rb') as f:
                    # --- CORREÇÃO 3: Usa o nome e o MIME type dinâmicos ---
                    arquivos_payload = {'file': (nome_arquivo, f, mime_type)}
                    # --- FIM DA CORREÇÃO 3 ---
                    
                    # Faz a requisição para a API
                    response = requests.post(url_upload, data=dados_payload, files=arquivos_payload)

                if response.status_code == 201:
                    messagebox.showinfo("Sucesso", "Documento enviado com sucesso!", parent=popup)
                    popup.destroy()
                    self.on_rh_funcionario_selecionado(None) # Atualiza a lista de documentos
                else:
                    messagebox.showerror("Erro da API", f"Falha no upload: {response.json().get('mensagem', response.text)}", parent=popup)
            except Exception as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}", parent=popup)

        # Botão de Envio
        btn_salvar = ttk.Button(frame, text="Salvar e Disponibilizar", command=enviar_documento)
        btn_salvar.grid(row=3, column=0, columnspan=2, pady=20, ipady=5)

        frame.columnconfigure(1, weight=1)

    def solicitar_onboarding_funcionario(self):
        """Dispara a notificação para o funcionário iniciar o processo de onboarding."""
        selecionado = self.tree_rh_funcionarios.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário na lista da esquerda primeiro.")
            return
        
        dados_func = self.tree_rh_funcionarios.item(selecionado, 'values')
        funcionario_id = dados_func[0]
        nome_funcionario = dados_func[1]
        
        # 1. Tenta inicializar o status no banco (seta para 'Pendente')
        if not database.iniciar_onboarding_funcionario(funcionario_id):
            messagebox.showerror("Erro", "Falha ao registrar o status de onboarding no banco.")
            return

        # 2. Busca o ChatID para notificar
        func_obj = database.buscar_funcionario_por_id(funcionario_id)
        if not func_obj or not func_obj.ChatIDTelegram:
             messagebox.showwarning("Aviso", "Funcionário sem ChatID Telegram cadastrado. Não é possível notificar.")
             return

        # 3. Envia a notificação inicial que fará o fluxo de bloqueio começar
        mensagem = (f"🎉 **Bem-vindo(a) à Gela Boca, {nome_funcionario}!** 🎉\n\n"
                    "Para dar início ao seu registro, precisamos que você nos envie seus documentos e dados pessoais. "
                    "Seu acesso ao sistema será bloqueado até que o processo seja concluído.\n\n"
                    "Por favor, digite **qualquer mensagem** (ou /start) para começar o envio de documentos.")
        
        notificador_telegram.enviar_mensagem(func_obj.ChatIDTelegram, mensagem)
        messagebox.showinfo("Sucesso", f"Notificação de Onboarding enviada para {nome_funcionario}!")
    
    def atualizar_lista_comunicados(self, filtro=None):
        for i in self.tree_comunicados.get_children(): self.tree_comunicados.delete(i)
        comunicados = database.listar_comunicados_com_status(filtro_titulo=filtro)
        for doc in comunicados:
            status = f"{doc.TotalCientes} / {doc.TotalEnviado} Cientes"
            data_formatada = doc.DataCriacao.strftime("%d/%m/%Y %H:%M")
            self.tree_comunicados.insert("", "end", values=(doc.DocumentoID, doc.Titulo, data_formatada, status))

    def abrir_janela_criacao(self): # <<< ESTA FUNÇÃO ESTAVA FALTANDO!
            # --- CORREÇÃO: Limpa resíduos de seleções anteriores ---
        if hasattr(self, 'caminho_imagem_selecionada'):
            del self.caminho_imagem_selecionada
        # -------------------------------------------------------
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
        frame_imagem = Frame(self.popup_criacao)
        frame_imagem.pack(padx=10, pady=5, fill='x')
        btn_selecionar_img = Button(frame_imagem, text="Anexar Imagem...", command=lambda: self.selecionar_imagem(lbl_caminho_imagem))
        btn_selecionar_img.pack(side="left")
        lbl_caminho_imagem = Label(frame_imagem, text="Nenhuma imagem selecionada.", font=("Arial", 9, "italic"))
        lbl_caminho_imagem.pack(side="left", padx=10)
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
    
    # Em gestao_pessoas_main.py, SUBSTITUA a função antiga por esta:

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

        # Prepara dados iniciais na Thread principal para evitar erros de GUI
        destinatarios_nomes = [listbox.get(i) for i in indices_selecionados]
        destinatarios_objs = [self.dados_funcionarios[nome] for nome in destinatarios_nomes]
        imagem_anexada = hasattr(self, 'caminho_imagem_selecionada') and self.caminho_imagem_selecionada
        caminho_imagem = self.caminho_imagem_selecionada if imagem_anexada else None

        # Desabilita botão para evitar múltiplos cliques
        btn_enviar = self.popup_criacao.nametowidget(listbox.master.master.winfo_children()[-1]) # Pega o botão enviar (último widget)
        if btn_enviar: btn_enviar.config(state="disabled", text="Enviando... Aguarde")

        def tarefa_envio_background():
            try:
                GESTOR_ID = 2  # Assumindo ID 2 para o gestor
                documento_id = database.criar_documento(titulo, conteudo.strip(), GESTOR_ID, pontos)
                if not documento_id:
                    self.root.after(0, lambda: messagebox.showerror("Erro de BD", "Não foi possível criar o registro do documento.", parent=self.popup_criacao))
                    return

                telegram_file_id = None
                enviados_com_sucesso = 0

                # 1. Prepara as mensagens
                legenda_imagem_curta = f"🚨 **NOVO COMUNICADO** 🚨\n\n**Título:** {titulo}"
                texto_principal = f"**Conteúdo:**\n{conteudo.strip()}\n\nSua confirmação de leitura é obrigatória e será registrada."

                # 2. Envio da imagem inicial (se houver) com Fallback
                telegram_file_id = None
                if caminho_imagem:
                    try:
                        logger.info(f"Tentando obter file_id via Grupo Gestor ({config.GESTOR_GROUP_CHAT_ID})...")
                        resposta_api_foto = notificador_telegram.enviar_foto_com_botoes(
                            config.GESTOR_GROUP_CHAT_ID, 
                            caminho_imagem, 
                            f"(Log de Envio: {titulo})" 
                        )

                        if resposta_api_foto and resposta_api_foto.get('ok'):
                            telegram_file_id = resposta_api_foto['result']['photo'][-1]['file_id']
                            database.atualizar_documento_com_file_id(documento_id, telegram_file_id)
                        else:
                            logger.warning(f"Falha ao enviar imagem para grupo de controle: {resposta_api_foto}")
                            # Não aborta, apenas segue sem imagem
                    except Exception as e_img:
                        logger.error(f"Erro de conexão ao enviar imagem de controle: {e_img}")
                        # Não aborta

                # 3. Itera sobre TODOS os funcionários
                for func in destinatarios_objs:
                    assinatura_id = database.registrar_pendencia_assinatura(documento_id, func.FuncionarioID)
                    if not assinatura_id:
                        logger.warning(f"!!! Falha ao registrar pendência para {func.NomeCompleto}")
                        continue

                    keyboard = [[InlineKeyboardButton("✅ Li e estou ciente", callback_data=f"doc_ciente_{assinatura_id}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    if telegram_file_id:
                        notificador_telegram.enviar_foto_com_botoes(
                            func.ChatIDTelegram,
                            telegram_file_id, 
                            legenda_imagem_curta
                        )
                        time.sleep(0.2) 

                    notificador_telegram.enviar_mensagem_com_botao(
                        func.ChatIDTelegram,
                        texto_principal,
                        reply_markup
                    )
                    enviados_com_sucesso += 1
                    time.sleep(0.1)

                # Finalização na Thread Principal
                def finalizar_ui():
                    messagebox.showinfo("Sucesso", f"{enviados_com_sucesso} de {len(destinatarios_objs)} comunicados foram enviados.", parent=self.popup_criacao)
                    if hasattr(self, 'caminho_imagem_selecionada'):
                        del self.caminho_imagem_selecionada
                    self.popup_criacao.destroy()
                    self.atualizar_lista_comunicados()
                
                self.root.after(0, finalizar_ui)

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Erro Inesperado", f"O processo foi interrompido:\n{e}", parent=self.popup_criacao))
                # Reabilita botão em caso de erro
                self.root.after(0, lambda: btn_enviar.config(state="normal", text="ENVIAR COMUNICADO"))

        # Inicia a thread
        import threading
        threading.Thread(target=tarefa_envio_background, daemon=True).start()

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

    def selecionar_imagem(self, label_caminho):
        filepath = filedialog.askopenfilename(title="Selecione uma Imagem para o Comunicado", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.gif"),("Todos os arquivos", "*.*")])
        if filepath:
            self.caminho_imagem_selecionada = filepath
            label_caminho.config(text=os.path.basename(filepath))
        else:
            if hasattr(self, 'caminho_imagem_selecionada'): del self.caminho_imagem_selecionada
            label_caminho.config(text="Nenhuma imagem selecionada.")

    def reiniciar_processo_onboarding(self):
        """Limpa os dados de onboarding do funcionário para que ele faça de novo."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista.")
            return

        dados = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id = dados[0]
        nome = dados[1]

        confirmacao = messagebox.askyesno(
            "Reiniciar Onboarding",
            f"Deseja reiniciar o processo de admissão para '{nome}'?\n\n"
            "Isso apagará os documentos e dados preenchidos (Escolaridade, Filhos, etc), "
            "permitindo que ele comece do zero pelo Telegram.\n\n"
            "O funcionário NÃO será excluído do sistema.",
            parent=self.root
        )

        if confirmacao:
            if database.resetar_onboarding_completo(funcionario_id):
                # Opcional: Notificar o funcionário que o processo foi reiniciado
                func_obj = database.buscar_funcionario_por_id(funcionario_id)
                if func_obj and func_obj.ChatIDTelegram:
                    notificador_telegram.enviar_mensagem(
                        func_obj.ChatIDTelegram,
                        "🔄 **Processo de Admissão Reiniciado**\n\n"
                        "O RH solicitou o preenchimento novamente dos seus dados.\n"
                        "Por favor, digite 'Começar' para enviar as informações corretas."
                    )

                messagebox.showinfo("Sucesso", "Processo reiniciado! O funcionário pode preencher os dados novamente.", parent=self.root)
                self.carregar_onboarding_lista()
            else:
                messagebox.showerror("Erro", "Falha ao reiniciar o processo no banco de dados.", parent=self.root)        
        
if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoPessoas(root) 
    root.mainloop()
=======
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
from tkinter import ttk, messagebox, Toplevel, Listbox, Checkbutton, Text, Entry, Scrollbar, Frame, Label, Button
from datetime import datetime
import database
import notificador_telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import time
import os
from tkinter import filedialog
from tkcalendar import DateEntry
import comunicado_generator
import file_utils
import recibo_generator
import config
import requests
import json
from PIL import Image, ImageTk
from fpdf import FPDF
import tempfile
import shutil

class AppGestaoPessoas:
    def __init__(self, root):
        self.root = root
        self.root.title("Módulo de Gestão de Pessoas (RH)")
        self.root.geometry("900x600")
        self.root.minsize(700, 400)
        
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        self.frame_comunicados = ttk.Frame(self.notebook, padding="10")
        self.frame_documentos = ttk.Frame(self.notebook, padding="10")
        # --- Variáveis de Login para Simulação de Acesso (Gestor ID 2) ---
        # Defina self.USUARIO_LOGADO_ID e self.nivel_usuario AQUI
        self.USUARIO_LOGADO_ID = 2 
        # Esta chamada requer que _buscar_nivel_acesso exista, o que faremos acima.
        # CORREÇÃO: Garante que o nível de usuário seja recuperado corretamente ou define um padrão para teste
        nivel_banco = self._buscar_nivel_acesso(self.USUARIO_LOGADO_ID)
        self.nivel_usuario = nivel_banco if nivel_banco else 'Gestor' # Fallback para 'Gestor' se não encontrar no banco para testes
        print(f"--> [DEBUG] Nível de Acesso do Usuário {self.USUARIO_LOGADO_ID}: {self.nivel_usuario}")
        self.frame_onboarding = ttk.Frame(self.notebook, padding="10") # <<< NOVA ABA

        self.notebook.add(self.frame_onboarding, text='📝 Onboarding/Admissional') # <<< NOVA ABA
        self.notebook.add(self.frame_comunicados, text='Comunicados')
        self.notebook.add(self.frame_documentos, text='Documentos Pessoais (RH)')
        
        self.dados_funcionarios = {}
        self.popup_criacao = None

        self.criar_aba_comunicados()
        self.criar_aba_documentos()
        self.criar_aba_onboarding() # <<< CHAMA A NOVA ABA
        
        self.atualizar_lista_comunicados()
        self.carregar_rh_funcionarios() # Carrega funcionários para a nova aba

    # --- ABA 1: COMUNICADOS ---
    def criar_aba_comunicados(self):
        self.frame_comunicados.grid_rowconfigure(2, weight=1)
        self.frame_comunicados.grid_columnconfigure(0, weight=1)
        # ... (código da interface da aba comunicados que já tínhamos)
        frame_botoes = ttk.Frame(self.frame_comunicados)
        frame_botoes.grid(row=0, column=0, sticky="ew")
        btn_novo = ttk.Button(frame_botoes, text="Criar Novo Comunicado", command=self.abrir_janela_criacao)
        btn_novo.pack(side="left")
        btn_atualizar = ttk.Button(frame_botoes, text="Atualizar Lista", command=self.atualizar_lista_comunicados)
        btn_atualizar.pack(side="left", padx=10)
        btn_detalhes = ttk.Button(frame_botoes, text="Ver Detalhes do Selecionado", command=self.abrir_janela_detalhes)
        btn_detalhes.pack(side="left", padx=10)
        btn_excluir = ttk.Button(frame_botoes, text="Excluir Comunicado", command=self.excluir_comunicado_selecionado)
        btn_excluir.pack(side="left", padx=10)
        frame_filtro = ttk.Frame(self.frame_comunicados)
        frame_filtro.grid(row=1, column=0, sticky="ew", pady=(5,0))
        lbl_filtro = ttk.Label(frame_filtro, text="Filtrar por Título:")
        lbl_filtro.pack(side="left")
        self.entry_filtro = ttk.Entry(frame_filtro, width=40)
        self.entry_filtro.pack(side="left", padx=5, fill="x", expand=True)
        btn_buscar = ttk.Button(frame_filtro, text="Buscar", command=self.filtrar_lista_comunicados)
        btn_buscar.pack(side="left", padx=(0, 5))
        btn_limpar = ttk.Button(frame_filtro, text="Limpar", command=self.limpar_filtro)
        btn_limpar.pack(side="left")
        frame_lista = ttk.Frame(self.frame_comunicados)
        frame_lista.grid(row=2, column=0, sticky="nsew", pady=(5,0))
        frame_lista.grid_rowconfigure(0, weight=1)
        frame_lista.grid_columnconfigure(0, weight=1)
        cols = ('ID', 'Título', 'Data de Criação', 'Status')
        self.tree_comunicados = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')
        self.tree_comunicados.heading('ID', text='ID'); self.tree_comunicados.column('ID', width=50, anchor='center')
        self.tree_comunicados.heading('Título', text='Título'); self.tree_comunicados.column('Título', width=350)
        self.tree_comunicados.heading('Data de Criação', text='Enviado em'); self.tree_comunicados.column('Data de Criação', width=150, anchor='center')
        self.tree_comunicados.heading('Status', text='Status'); self.tree_comunicados.column('Status', width=120, anchor='center')
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.tree_comunicados.yview)
        self.tree_comunicados.configure(yscrollcommand=scrollbar.set)
        self.tree_comunicados.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    # --- ABA 2: DOCUMENTOS PESSOAIS ---
    def criar_aba_documentos(self):
        main_frame = ttk.Frame(self.frame_documentos)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)
        frame_funcionarios = ttk.LabelFrame(main_frame, text="Selecionar Funcionário", padding="10")
        frame_funcionarios.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame_funcionarios.rowconfigure(0, weight=1)
        frame_funcionarios.columnconfigure(0, weight=1)
        cols_func = ('ID', 'Nome')
        self.tree_rh_funcionarios = ttk.Treeview(frame_funcionarios, columns=cols_func, show='headings', selectmode='browse')
        self.tree_rh_funcionarios.heading('ID', text='ID'); self.tree_rh_funcionarios.column('ID', width=40)
        self.tree_rh_funcionarios.heading('Nome', text='Nome')
        self.tree_rh_funcionarios.grid(row=0, column=0, sticky="nsew")
        self.tree_rh_funcionarios.bind('<<TreeviewSelect>>', self.on_rh_funcionario_selecionado)
        frame_docs = ttk.LabelFrame(main_frame, text="Documentos Enviados", padding="10")
        frame_docs.grid(row=0, column=1, sticky="nsew")
        frame_docs.rowconfigure(0, weight=1)
        frame_docs.columnconfigure(0, weight=1)
        cols_docs = ('ID Doc', 'Tipo', 'Referência', 'Data Upload', 'Status Ciência', 'Data da Ciência')
        self.tree_rh_documentos = ttk.Treeview(frame_docs, columns=cols_docs, show='headings', selectmode='browse')
        self.tree_rh_documentos.heading('ID Doc', text='ID'); self.tree_rh_documentos.column('ID Doc', width=40)
        self.tree_rh_documentos.heading('Tipo', text='Tipo de Documento'); self.tree_rh_documentos.column('Tipo', width=150)
        self.tree_rh_documentos.heading('Referência', text='Mês/Ano Ref.'); self.tree_rh_documentos.column('Referência', width=100, anchor='center')
        self.tree_rh_documentos.heading('Data Upload', text='Data de Upload'); self.tree_rh_documentos.column('Data Upload', width=150, anchor='center')
        self.tree_rh_documentos.heading('Status Ciência', text='Status')
        self.tree_rh_documentos.column('Status Ciência', width=100, anchor='center')
        self.tree_rh_documentos.heading('Data da Ciência', text='Data da Ciência')
        self.tree_rh_documentos.column('Data da Ciência', width=150, anchor='center')
        self.tree_rh_documentos.grid(row=0, column=0, sticky="nsew")
        frame_botoes_docs = ttk.Frame(frame_docs)
        frame_botoes_docs.grid(row=1, column=0, sticky="ew", pady=(10,0))
        
        btn_solicitar_onboarding = ttk.Button(frame_botoes_docs, text="🚀 Solicitar Documentos (Onboarding)", command=self.solicitar_onboarding_funcionario)
        btn_solicitar_onboarding.pack(side="left", padx=(0, 20))
        btn_add = ttk.Button(frame_botoes_docs, text="Adicionar Novo Documento...", command=self.abrir_janela_add_documento)
        btn_add.pack(side="left")
        
        # --- NOVOS BOTÕES ---
        btn_edit = ttk.Button(frame_botoes_docs, text="Editar Metadados", command=self.abrir_janela_edicao_documento)
        btn_edit.pack(side="left", padx=10)
        
        btn_del = ttk.Button(frame_botoes_docs, text="Excluir Documento", command=self.excluir_documento_selecionado)
        btn_del.pack(side="left", padx=10)
        # --- FIM NOVOS BOTÕES ---

        btn_vis = ttk.Button(frame_botoes_docs, text="Visualizar/Baixar Documento", command=self.visualizar_documento_selecionado)
        btn_vis.pack(side="right")


    def criar_aba_onboarding(self):
        """Cria a interface para gerenciar a aprovação do exame admissional."""
        # Acesso restrito apenas a Gestores e RH para evitar leaks de dados
        if self.nivel_usuario not in ('RH', 'Gestor'):
            ttk.Label(self.frame_onboarding, text="ACESSO NEGADO: Esta área é restrita ao RH/Gestão.", font=("Arial", 16, "bold"), foreground="red").pack(pady=50)
            return

        main_frame = ttk.Frame(self.frame_onboarding)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # Treeview de Funcionários Prontos
        cols = ('ID', 'Nome', 'Status Documentos', 'Status Admissional', 'Última Etapa', 'Data Admissional')
        self.tree_onboarding = ttk.Treeview(main_frame, columns=cols, show='headings', selectmode='browse')
        for col in cols: self.tree_onboarding.heading(col, text=col)

        self.tree_onboarding.column('ID', width=40)
        self.tree_onboarding.column('Status Documentos', width=120, anchor='center')
        self.tree_onboarding.column('Status Admissional', width=120, anchor='center')
        self.tree_onboarding.column('Data Admissional', width=120, anchor='center')

        self.tree_onboarding.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tree_onboarding.bind('<<TreeviewSelect>>', self.on_onboarding_selecionado)

        # Botões de Ação
        frame_botoes = ttk.Frame(main_frame)
        frame_botoes.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        
        ttk.Button(frame_botoes, text="🔄 Atualizar Lista", command=self.carregar_onboarding_lista).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="📂 Ver Documentos Enviados", command=self.abrir_janela_documentos_onboarding).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="📋 Ver Dados Cadastrais", command=self.ver_dados_cadastrais_selecionado).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="🗑️ Excluir Cadastro", command=self.excluir_candidato_onboarding).pack(side="left", padx=5)
        ttk.Button(frame_botoes, text="🔄 Reiniciar Processo", command=self.reiniciar_processo_onboarding).pack(side="left", padx=5)
        self.btn_aprovar_admissional = ttk.Button(frame_botoes, text="✅ Aprovar Exame Admissional", command=self.aprovar_exame_admissional_rh)
        self.btn_aprovar_admissional.pack(side="right", padx=5)

        self.carregar_onboarding_lista()

    def carregar_onboarding_lista(self):
        """Carrega a lista de funcionários com onboarding completo/pendente para a Treeview."""
        for i in self.tree_onboarding.get_children(): self.tree_onboarding.delete(i)
        
        funcionarios = database.buscar_onboarding_lista_rh()
        
        for f in funcionarios:
            data_admissional = f.DataAdmissional.strftime('%d/%m/%Y') if f.DataAdmissional else '---'
            
            self.tree_onboarding.insert("", "end", values=(
                f.FuncionarioID, f.NomeCompleto, f.StatusWorkflow, f.StatusAdmissional, f.UltimaEtapa, data_admissional
            ))

    def on_onboarding_selecionado(self, event):
        """Habilita/desabilita o botão de aprovação e armazena os dados de download."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado: return
        
        dados = self.tree_onboarding.item(selecionado, 'values')
        status_admissional = dados[3]
        
        if status_admissional == 'Pendente':
            self.btn_aprovar_admissional.config(state="normal")
        else:
            self.btn_aprovar_admissional.config(state="disabled")

    def aprovar_exame_admissional_rh(self):
        """Dispara a aprovação manual do exame admissional."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado: return
        
        dados = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id = dados[0]
        nome_funcionario = dados[1]

        if dados[3] != 'Pendente':
            messagebox.showwarning("Aviso", "O exame deste funcionário já foi aprovado.")
            return

        confirmado = messagebox.askyesno("Confirmar Aprovação", f"Tem certeza que deseja aprovar o exame admissional para {nome_funcionario}?\n\nIsso liberará o acesso TOTAL dele ao Bot Telegram.")

        if confirmado:
            hoje = datetime.now()
            if database.aprovar_exame_admissional(funcionario_id, hoje):
                
                # 1. Notificação de Liberação Total
                func_obj = database.buscar_funcionario_por_id(funcionario_id)
                if func_obj and func_obj.ChatIDTelegram:
                     notificador_telegram.enviar_mensagem(
                        func_obj.ChatIDTelegram,
                        "🎉 **PARABÉNS! SEU EXAME ADMISSIONAL FOI APROVADO!** 🎉\n\n"
                        "Seu acesso ao sistema de Gamificação está **TOTALMENTE LIBERADO**! "
                        "Você já pode usar todos os comandos (Tarefas, Ranking, Saldo). Bom trabalho! 🚀"
                    )

                # 2. Atualiza a lista na interface
                self.carregar_onboarding_lista()
                messagebox.showinfo("Sucesso", "Admissional Aprovado! Acesso liberado no sistema.")
            else:
                messagebox.showerror("Erro", "Falha ao atualizar o status no banco de dados.")

    def excluir_candidato_onboarding(self):
        """Exclui permanentemente o cadastro do candidato selecionado."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista para excluir.")
            return

        # Recupera dados da linha selecionada
        dados = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id = dados[0]
        nome = dados[1]

        # Confirmação de Segurança
        confirmacao = messagebox.askyesno(
            "Confirmar Exclusão",
            f"Tem certeza que deseja excluir o cadastro de '{nome}'?\n\n"
            "⚠️ ATENÇÃO: Esta ação apagará TODOS os dados, documentos e histórico deste funcionário permanentemente.\n"
            "Não será possível desfazer.",
            icon='warning',
            default='no',
            parent=self.root
        )

        if confirmacao:
            try:
                # Usa a função do database que já faz a limpeza em cascata
                database.excluir_funcionario(funcionario_id)
                messagebox.showinfo("Sucesso", "Cadastro excluído com sucesso!", parent=self.root)
                self.carregar_onboarding_lista() # Atualiza a lista
            except Exception as e:
                logger.error(f"Erro ao excluir candidato {funcionario_id}: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao excluir cadastro:\n{e}", parent=self.root)

    def abrir_janela_documentos_onboarding(self):
        """Abre uma janela para visualizar os File IDs dos documentos enviados."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um funcionário da lista.")
            return

        funcionario_id = self.tree_onboarding.item(selecionado, 'values')[0]
        nome_funcionario = self.tree_onboarding.item(selecionado, 'values')[1]
        
        file_ids = database.buscar_documentos_onboarding_para_download(funcionario_id)

        popup = Toplevel(self.root)
        popup.title(f"Documentos de Admissão - {nome_funcionario}")
        popup.geometry("600x400")
        popup.transient(self.root)

        # ... (Implementação do painel de download que utiliza a função buscar_documentos_onboarding_para_download) ...
        # (O painel de download em si é complexo, mas a função de banco está no lugar certo)
        
        # Simplificação: Apenas mostra os botões de download
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Documentos Enviados (Clique para Download):", font=("Arial", 12)).pack(anchor='w', pady=(0, 10))
        
        if not file_ids:
             ttk.Label(frame, text="Nenhum documento finalizado (Workflow incompleto).", foreground="gray").pack()
             return

        for doc_name, file_id in file_ids.items():
            if file_id:
                # O botão deve ter uma função que chama o notificador_telegram para baixar a foto/documento
                ttk.Button(frame, text=f"📥 Baixar {doc_name}", 
                           command=lambda fid=file_id, dn=doc_name: self.disparar_download_documento(fid, dn, popup)
                ).pack(fill='x', pady=5)
            else:
                 ttk.Label(frame, text=f"❌ {doc_name}: Não enviado ou File ID inválido.").pack(anchor='w', pady=2)

    def ver_dados_cadastrais_selecionado(self):
        """
        Exibe dados textuais E imagens dos documentos, com opção de gerar PDF profissional.
        """
        selecionado = self.tree_onboarding.focus()
        if not selecionado: return

        vals = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id, nome = vals[0], vals[1]

        status = database.buscar_onboarding_status(funcionario_id)
        if not status: 
            messagebox.showinfo("Aviso", "Sem dados de onboarding encontrados.", parent=self.root)
            return

        # --- 1. Preparação da Janela com Scroll (Necessário para muitas fotos) ---
        popup = Toplevel(self.root)
        popup.title(f"Prontuário Digital - {nome}")
        popup.geometry("650x800")

        # Container principal
        main_container = ttk.Frame(popup)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- 2. Preparação dos Dados ---
        # Dicionário para guardar caminhos locais das imagens baixadas (para o PDF)
        cache_imagens = {} 

        # Função interna para o botão de PDF
        def acao_gerar_pdf():
            self.gerar_pdf_prontuario(nome, status, cache_imagens)

        # Botão de Exportação no Topo
        frame_topo = ttk.Frame(scrollable_frame, padding="10")
        frame_topo.pack(fill="x")
        btn_pdf = ttk.Button(frame_topo, text="🖨️ Gerar PDF Completo (Dados + Fotos)", command=acao_gerar_pdf)
        btn_pdf.pack(fill="x", ipady=8)

        # --- 3. Exibição dos Dados (Texto) ---
        lbl_dados = tk.Label(scrollable_frame, text="DADOS CADASTRAIS", font=("Arial", 12, "bold"), bg="#e0e0e0", anchor="w", padx=5)
        lbl_dados.pack(fill="x", pady=(10, 5))

        texto_dados = f"Funcionário: {nome} (ID: {funcionario_id})\n"
        texto_dados += f"Escolaridade: {status.Escolaridade or '---'}\n"
        texto_dados += f"Estado Civil: {status.EstadoCivil or '---'}\n"

        if status.EstadoCivil and 'CASADO' in status.EstadoCivil.upper():
            texto_dados += f"Data Casamento: {status.DataCasamento or '---'}\n"
            texto_dados += f"Cônjuge: {status.NomeConjugue or '---'}\n"
            texto_dados += f"CPF Cônjuge: {status.CPFConjugue or '---'}\n"

        texto_dados += f"\nDEPENDENTES ({status.QtdFilhos or 0}):\n"
        if status.DadosFilhos:
            try:
                filhos = json.loads(status.DadosFilhos)
                for i, f in enumerate(filhos, 1):
                    texto_dados += f"- {f.get('Nome', '')} ({f.get('Nasc', '')}) CPF: {f.get('CPF', '')}\n"
            except: texto_dados += "(Erro na leitura dos dependentes)"
        else:
            texto_dados += "- Nenhum dependente declarado."

        tk.Label(scrollable_frame, text=texto_dados, justify="left", font=("Consolas", 10), bg="white", relief="solid", bd=1, padx=10, pady=10).pack(fill="x", padx=10)

        # --- 4. Exibição das Imagens (Visualização) ---
        lbl_docs = tk.Label(scrollable_frame, text="DOCUMENTOS DIGITALIZADOS", font=("Arial", 12, "bold"), bg="#e0e0e0", anchor="w", padx=5)
        lbl_docs.pack(fill="x", pady=(20, 5))

        docs_map = {
            "RG (Identidade)": status.RG_FileID,
            "CPF": status.CPF_FileID,
            "Carteira de Trabalho (CTPS)": status.CTPS_FileID,
            "Título de Eleitor": status.TituloEleitor_FileID
        }

        # Diretório temporário para cache de visualização
        temp_dir = os.path.join(os.getcwd(), "temp_view")
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)

        for titulo, file_id in docs_map.items():
            frame_doc = ttk.LabelFrame(scrollable_frame, text=titulo, padding="5")
            frame_doc.pack(fill="x", padx=10, pady=5)

            if file_id:
                # Baixa a imagem para exibir
                caminho_local = self._baixar_imagem_cache(file_id, temp_dir)

                if caminho_local:
                    cache_imagens[titulo] = caminho_local # Guarda referência para o PDF

                    try:
                        # Carrega e Redimensiona para o Painel (Thumbnail)
                        pil_img = Image.open(caminho_local)
                        # Redimensiona mantendo proporção (largura max 400px)
                        base_width = 400
                        w_percent = (base_width / float(pil_img.size[0]))
                        h_size = int((float(pil_img.size[1]) * float(w_percent)))
                        pil_img = pil_img.resize((base_width, h_size), Image.Resampling.LANCZOS)

                        tk_img = ImageTk.PhotoImage(pil_img)

                        lbl_img = tk.Label(frame_doc, image=tk_img)
                        lbl_img.image = tk_img # Mantém referência na memória para não sumir
                        lbl_img.pack()
                    except Exception:
                        tk.Label(frame_doc, text="[Arquivo PDF ou Formato não suportado para prévia]", fg="blue").pack()
                else:
                    tk.Label(frame_doc, text="Erro ao baixar arquivo do servidor.", fg="red").pack()
            else:
                tk.Label(frame_doc, text="Pendente / Não enviado", fg="gray").pack()

    def _baixar_imagem_cache(self, file_id, pasta_destino):
        """Baixa arquivo do Telegram para cache local."""
        try:
            token = config.TELEGRAM_TOKEN
            # 1. Pega o caminho
            url_info = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
            r = requests.get(url_info, timeout=5).json()
            if not r.get('ok'): return None

            file_path = r['result']['file_path']
            ext = os.path.splitext(file_path)[1]
            if not ext: ext = ".jpg"

            nome_arquivo = f"{file_id}{ext}"
            caminho_completo = os.path.join(pasta_destino, nome_arquivo)

            # Cache: Se já baixou, usa o local
            if os.path.exists(caminho_completo): return caminho_completo

            # 2. Baixa o conteúdo
            url_download = f"https://api.telegram.org/file/bot{token}/{file_path}"
            r_img = requests.get(url_download, timeout=20)

            if r_img.status_code == 200:
                with open(caminho_completo, 'wb') as f:
                    f.write(r_img.content)
                return caminho_completo
        except: return None
        return None

    def gerar_pdf_prontuario(self, nome_funcionario, status, cache_imagens):
        """Gera PDF profissional com dados e imagens anexadas."""
        try:
            dest = filedialog.asksaveasfilename(
                title="Salvar Prontuário PDF",
                defaultextension=".pdf",
                initialfile=f"Prontuario_{nome_funcionario.replace(' ', '_')}.pdf"
            )
            if not dest: return

            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # --- Cabeçalho ---
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Ficha de Registro de Colaborador", ln=True, align="C")
            pdf.set_font("Arial", "I", 10)
            pdf.cell(0, 10, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
            pdf.ln(10)

            # --- Tabela de Dados ---
            pdf.set_fill_color(240, 240, 240)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "1. DADOS PESSOAIS", ln=True, fill=True)
            pdf.ln(2)

            pdf.set_font("Arial", "", 11)
            pdf.multi_cell(0, 8, f"Nome: {nome_funcionario}\nEscolaridade: {status.Escolaridade}\nEstado Civil: {status.EstadoCivil}")

            if status.EstadoCivil and 'CASADO' in status.EstadoCivil.upper():
                pdf.multi_cell(0, 8, f"Cônjuge: {status.NomeConjugue}\nCPF Cônjuge: {status.CPFConjugue}")

            pdf.ln(5)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, f"2. DEPENDENTES ({status.QtdFilhos or 0})", ln=True, fill=True)

            if status.DadosFilhos:
                try:
                    filhos = json.loads(status.DadosFilhos)
                    pdf.set_font("Arial", "", 10)
                    for i, f in enumerate(filhos, 1):
                        pdf.cell(0, 8, f"{i}. {f.get('Nome','')} - CPF: {f.get('CPF','')}", ln=True)
                except: pass
            else:
                pdf.set_font("Arial", "I", 10)
                pdf.cell(0, 8, "Nenhum dependente declarado.", ln=True)

            # --- Imagens (Uma por página ou ajustada) ---
            pdf.add_page()
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "3. DOCUMENTOS DIGITALIZADOS", ln=True, fill=True)
            pdf.ln(5)

            for titulo, caminho_img in cache_imagens.items():
                if caminho_img and os.path.exists(caminho_img) and caminho_img.endswith(('.jpg', '.png', '.jpeg')):
                    pdf.set_font("Arial", "B", 11)
                    pdf.cell(0, 10, titulo, ln=True)

                    # Centraliza imagem na página A4 (largura aprox 190mm útil)
                    try:
                        pdf.image(caminho_img, w=170) 
                    except:
                        pdf.cell(0, 10, "[Erro ao renderizar imagem no PDF]", ln=True)

                    pdf.ln(10)
                elif caminho_img and ".pdf" in caminho_img:
                    pdf.set_font("Arial", "I", 10)
                    pdf.cell(0, 10, f"{titulo}: Arquivo PDF anexado original não pode ser mesclado aqui.", ln=True)

            pdf.output(dest)
            messagebox.showinfo("Sucesso", "Prontuário PDF gerado com sucesso!", parent=self.root)
            file_utils.abrir_arquivo(dest)

        except Exception as e:
            logger.error(f"Erro PDF: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Falha ao criar PDF: {e}", parent=self.root)

    def disparar_download_documento(self, file_id, doc_name, parent_popup):
        """Baixa o arquivo real da API do Telegram e salva onde o usuário escolher."""
        try:
            # 1. Define extensão provável
            ext = ".jpg" # Padrão fotos Telegram
            if "pdf" in doc_name.lower(): ext = ".pdf"

            # 2. Pede ao usuário onde salvar
            caminho_destino = filedialog.asksaveasfilename(
                title=f"Salvar {doc_name}",
                defaultextension=ext,
                initialfile=f"{doc_name}_{file_id[:5]}{ext}",
                parent=parent_popup
            )

            if not caminho_destino: return # Cancelado pelo usuário

            # 3. Obtém o caminho do arquivo na API Telegram
            token = config.TELEGRAM_TOKEN
            url_info = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"

            r_info = requests.get(url_info, timeout=10)
            if r_info.status_code != 200:
                messagebox.showerror("Erro API", "Falha ao localizar arquivo no Telegram.", parent=parent_popup)
                return

            file_path_remoto = r_info.json().get('result', {}).get('file_path')
            if not file_path_remoto:
                messagebox.showerror("Erro API", "Caminho remoto não encontrado.", parent=parent_popup)
                return

            # 4. Baixa o conteúdo binário
            url_download = f"https://api.telegram.org/file/bot{token}/{file_path_remoto}"
            r_content = requests.get(url_download, timeout=30)

            if r_content.status_code == 200:
                with open(caminho_destino, 'wb') as f:
                    f.write(r_content.content)

                messagebox.showinfo("Sucesso", f"Download concluído!\nSalvo em: {caminho_destino}", parent=parent_popup)
                file_utils.abrir_arquivo(caminho_destino)
            else:
                messagebox.showerror("Erro Download", f"Falha ao baixar bytes: {r_content.status_code}", parent=parent_popup)

        except Exception as e:
            logger.error(f"Erro no download manual: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Falha no download: {e}", parent=parent_popup)


    def visualizar_documento_selecionado(self):
        """Baixa o documento selecionado da API e o abre."""
        selecionado = self.tree_rh_documentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista da direita.")
            return
        dados_doc = self.tree_rh_documentos.item(selecionado, 'values')
        documento_id = dados_doc[0]
        # REMOVIDO: A linha que forçava .pdf foi substituída pela lógica abaixo

        url_download = f"{config.API_BASE_URL}/documentos/download/{documento_id}"

        try:
            print(f"--> Solicitando download do documento ID {documento_id}...")
            response = requests.get(url_download, stream=True)

            if response.status_code == 200:
                # --- CORREÇÃO DE PARSE DE HEADER ---
                import cgi
                nome_remoto = ""
                
                header_content = response.headers.get("Content-Disposition")
                if header_content:
                    try:
                        # Tenta usar cgi para parsear corretamente (lida com aspas, utf-8, etc)
                        _, params = cgi.parse_header(header_content)
                        if 'filename' in params:
                            nome_remoto = params['filename']
                        elif 'filename*' in params:
                            # Tratamento básico para filename* (UTF-8)
                            encoding, _, filename = params['filename*'].split("'", 2)
                            nome_remoto = urllib.parse.unquote(filename)
                    except Exception:
                        # Fallback para regex simples se cgi falhar
                        import re
                        fname = re.findall('filename="?([^"]+)"?', header_content)
                        if fname:
                            nome_remoto = fname[0]

                # Fallback final se o header falhar ou não existir
                if not nome_remoto:
                    ext = ".pdf" 
                    content_type = response.headers.get("Content-Type", "")
                    if "image/jpeg" in content_type: ext = ".jpg"
                    elif "image/png" in content_type: ext = ".png"
                    
                    # Nome seguro baseado nos dados da lista
                    safe_tipo = "".join(x for x in dados_doc[1] if x.isalnum())
                    nome_remoto = f"{safe_tipo}_{documento_id}{ext}"

                # Limpeza de caracteres inválidos no nome do arquivo (segurança extra)
                nome_remoto = os.path.basename(nome_remoto) 
                # -----------------------------------

                pasta_downloads = "downloads"
                if not os.path.exists(pasta_downloads):
                    os.makedirs(pasta_downloads)

                caminho_local = os.path.join(pasta_downloads, nome_remoto)
                # Salva o arquivo recebido no disco local
                with open(caminho_local, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                print(f"--> Download concluído! Arquivo salvo em: {caminho_local}")
                file_utils.abrir_arquivo(caminho_local)
            else:
                # --- CORREÇÃO: Tratamento seguro de resposta de erro ---
                try:
                    # Tenta ler como JSON se a API retornar estrutura padrão
                    erro_json = response.json()
                    msg_erro = erro_json.get('mensagem', 'Erro desconhecido no servidor.')
                except Exception:
                    # Se falhar (ex: erro 500 HTML ou Proxy), usa o texto cru limitado
                    texto_erro = response.text[:200] if response.text else "Sem conteúdo"
                    msg_erro = f"Erro HTTP {response.status_code}: {texto_erro}"

                messagebox.showerror("Erro da API", f"Não foi possível baixar o arquivo:\n{msg_erro}")

        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API para baixar o arquivo: {e}")

    def carregar_rh_funcionarios(self):
        for i in self.tree_rh_funcionarios.get_children(): self.tree_rh_funcionarios.delete(i)
        funcionarios = database.listar_funcionarios()
        for func in funcionarios: self.tree_rh_funcionarios.insert("", "end", values=(func.FuncionarioID, func.NomeCompleto))

    def on_rh_funcionario_selecionado(self, event):
        """Chamada quando um funcionário é selecionado. Carrega seus documentos e status de ciência."""
        for i in self.tree_rh_documentos.get_children():
            self.tree_rh_documentos.delete(i)

        selecionado = self.tree_rh_funcionarios.focus()
        if not selecionado:
            return

        funcionario_id = self.tree_rh_funcionarios.item(selecionado, 'values')[0]
        
        documentos = database.listar_documentos_por_funcionario(funcionario_id)
        for doc in documentos:
            # Formata as datas para exibição
            mes_ano_ref = doc.MesAno.strftime("%m/%Y")
            data_upload = doc.DataUpload.strftime("%d/%m/%Y %H:%M")
            status_ciencia = doc.Status or "N/A" # Pega o status
            data_ciencia = doc.DataCiencia.strftime("%d/%m/%Y %H:%M") if doc.DataCiencia else "---" # Pega a data da ciência

            # Insere todos os dados na tabela
            self.tree_rh_documentos.insert("", "end", values=(
                doc.DocumentoID, doc.TipoDocumento, mes_ano_ref, data_upload, status_ciencia, data_ciencia
            ))
    def excluir_documento_selecionado(self):
        """Chama a API para excluir o documento selecionado (banco + arquivo)."""
        selecionado = self.tree_rh_documentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista para excluir.")
            return

        dados_doc = self.tree_rh_documentos.item(selecionado, 'values')
        documento_id = dados_doc[0]
        tipo_doc = dados_doc[1]
        mes_ano_ref = dados_doc[2]

        confirmado = messagebox.askyesno(
            "Confirmar Exclusão", 
            f"Tem certeza que deseja excluir o documento:\n\nTipo: {tipo_doc}\nReferência: {mes_ano_ref}\n\n"
            f"Esta ação removerá o registro do banco e o arquivo físico no servidor. NÃO PODE SER DESFEITA.", 
            icon='warning'
        )

        if confirmado:
            try:
                # Chamada DELETE para a API
                url = f"{config.API_BASE_URL}/documentos/excluir/{documento_id}"
                response = requests.delete(url)

                if response.status_code == 200:
                    messagebox.showinfo("Sucesso", "Documento excluído com sucesso!")
                    self.on_rh_funcionario_selecionado(None) # Recarrega a lista
                else:
                    msg_erro = response.json().get('mensagem', 'Erro desconhecido')
                    messagebox.showerror("Erro da API", f"Falha ao excluir: {msg_erro}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Erro de conexão ao excluir documento: {e}", exc_info=True)
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar ao servidor: {e}")
                
    def _buscar_nivel_acesso(self, funcionario_id):
        """Busca o NivelAcesso de um funcionário pelo ID (função auxiliar)."""
        conn = database.get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                sql = "SELECT NivelAcesso FROM Funcionarios WHERE FuncionarioID = ?"
                cursor.execute(sql, funcionario_id)
                resultado = cursor.fetchone()
                return resultado[0] if resultado else 'Funcionario' # Retorna o primeiro campo
            except Exception as e:
                logger.error(f"Falha ao buscar NivelAcesso para ID {funcionario_id}: {e}")
                return 'Funcionario' # Default seguro
            finally:
                conn.close()
        return 'Funcionario'

    def abrir_janela_edicao_documento(self):
        """Abre a janela Toplevel para editar os metadados do documento selecionado."""
        selecionado = self.tree_rh_documentos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista para editar.")
            return

        dados_doc = self.tree_rh_documentos.item(selecionado, 'values')
        documento_id = dados_doc[0]
        tipo_atual = dados_doc[1]
        mes_ano_ref_atual = dados_doc[2] # dd/mm/yyyy

        # Converte para objeto datetime para o DateEntry usar
        try:
            data_ref_obj = datetime.strptime(f"01/{mes_ano_ref_atual}", "%d/%m/%Y").date()
        except ValueError:
            data_ref_obj = datetime.now().date() # Fallback

        # --- Criação da Janela Pop-up ---
        popup = Toplevel(self.root)
        popup.title(f"Editar Documento ID: {documento_id}")
        popup.geometry("350x250")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        # --- Widgets do Formulário ---
        ttk.Label(frame, text="Tipo de Documento:").grid(row=0, column=0, sticky="w", pady=5)
        combo_tipo = ttk.Combobox(frame, values=['Holerite', 'Cartão Ponto', 'Comprovante de Consumo', 'Contrato', 'Atestado', 'Advertência', 'Outro'])
        combo_tipo.grid(row=0, column=1, sticky="ew", pady=5)
        combo_tipo.set(tipo_atual)

        ttk.Label(frame, text="Mês/Ano de Referência:").grid(row=1, column=0, sticky="w", pady=5)
        entry_data_ref = DateEntry(frame, date_pattern='dd/mm/yyyy', width=18)
        entry_data_ref.grid(row=1, column=1, sticky="w", pady=5)
        entry_data_ref.set_date(data_ref_obj)

        ttk.Label(frame, text=f"Arquivo atual: {dados_doc[3].split()[0]}").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 5))
        ttk.Label(frame, text="*Não é possível alterar o arquivo físico.", font=("Arial", 8, "italic")).grid(row=3, column=0, columnspan=2, sticky="w")


        def salvar_edicao():
            novo_tipo = combo_tipo.get()
            nova_data_ref_obj = entry_data_ref.get_date()
            nova_data_ref_db = nova_data_ref_obj.strftime('%Y-%m-%d') # Formato que o banco espera

            if not novo_tipo:
                messagebox.showerror("Erro", "O Tipo de Documento é obrigatório.", parent=popup)
                return

            try:
                sucesso = database.atualizar_documento_pessoal_metadados(documento_id, novo_tipo, nova_data_ref_db)

                if sucesso:
                    messagebox.showinfo("Sucesso", "Metadados do documento atualizados!", parent=popup)
                    popup.destroy()
                    self.on_rh_funcionario_selecionado(None) # Recarrega a lista
                else:
                    messagebox.showwarning("Aviso", "Nenhuma alteração detectada ou falha na atualização.")

            except Exception as e:
                messagebox.showerror("Erro", f"Ocorreu um erro ao salvar: {e}", parent=popup)

        # Botão de Envio
        btn_salvar = ttk.Button(frame, text="Salvar Metadados", command=salvar_edicao)
        btn_salvar.grid(row=4, column=0, columnspan=2, pady=20, ipady=5)

        frame.columnconfigure(1, weight=1)

    def abrir_janela_add_documento(self):
        """Abre a janela (Toplevel) para adicionar um novo documento pessoal."""
        selecionado = self.tree_rh_funcionarios.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário na lista da esquerda primeiro.")
            return
        
        dados_func = self.tree_rh_funcionarios.item(selecionado, 'values')
        funcionario_id = dados_func[0]
        nome_funcionario = dados_func[1]

        # --- Criação da Janela Pop-up ---
        popup = Toplevel(self.root)
        popup.title(f"Adicionar Documento para {nome_funcionario}")
        popup.geometry("450x300")
        popup.transient(self.root) # Mantém o pop-up na frente da janela principal

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        # --- Widgets do Formulário ---
        ttk.Label(frame, text="Tipo de Documento:").grid(row=0, column=0, sticky="w", pady=5)
        combo_tipo = ttk.Combobox(frame, values=['Holerite', 'Cartão Ponto', 'Comprovante de Consumo', 'Contrato', 'Atestado', 'Advertência', 'Outro'])
        combo_tipo.grid(row=0, column=1, sticky="ew", pady=5)
        combo_tipo.set('Holerite')

        ttk.Label(frame, text="Mês/Ano de Referência:").grid(row=1, column=0, sticky="w", pady=5)
        # Usaremos um DateEntry para facilitar a seleção
        from tkcalendar import DateEntry
        entry_data_ref = DateEntry(frame, date_pattern='dd/mm/yyyy', width=18)
        entry_data_ref.grid(row=1, column=1, sticky="w", pady=5)

        ttk.Label(frame, text="Arquivo (PDF, JPG, PNG):").grid(row=2, column=0, sticky="w", pady=5) # <-- Texto alterado
        frame_arquivo = ttk.Frame(frame)
        frame_arquivo.grid(row=2, column=1, sticky="ew", pady=5)
        
        lbl_caminho_pdf = ttk.Label(frame_arquivo, text="Nenhum arquivo selecionado.")
        lbl_caminho_pdf.pack(side="right", fill="x", expand=True)
        
        caminho_arquivo_selecionado = {"path": ""} # Usamos um dicionário para passar por referência

        # --- CORREÇÃO 1: Adicionado suporte a .png na seleção ---
        def selecionar_arquivo():
            filepath = filedialog.askopenfilename(
                title="Selecione o documento (PDF, JPG ou PNG)",
                filetypes=[
                    ("Documentos Suportados", "*.pdf *.jpg *.jpeg *.png"), # <-- ADICIONADO .png
                    ("Arquivos PDF", "*.pdf"),
                    ("Imagens JPG", "*.jpg *.jpeg"),
                    ("Imagens PNG", "*.png") # <-- ADICIONADA NOVA LINHA
                ]
            )
            if filepath:
                caminho_arquivo_selecionado["path"] = filepath
                lbl_caminho_pdf.config(text=os.path.basename(filepath))

        btn_selecionar = ttk.Button(frame_arquivo, text="Selecionar...", command=selecionar_arquivo) # <-- Usa a nova função
        btn_selecionar.pack(side="left")

        # --- Lógica de Envio ---
        def enviar_documento():
            # Coleta de dados
            tipo = combo_tipo.get()
            data_ref = entry_data_ref.get_date()
            caminho_arquivo = caminho_arquivo_selecionado["path"]

            if not all([tipo, data_ref, caminho_arquivo]):
                messagebox.showerror("Erro", "Todos os campos são obrigatórios.", parent=popup)
                return

            # --- CORREÇÃO 2: Adicionado suporte a .png no MIME type ---
            nome_arquivo = os.path.basename(caminho_arquivo)
            # Pega a extensão (ex: '.jpg' ou '.pdf')
            extensao = os.path.splitext(nome_arquivo)[1].lower() 

            if extensao == '.pdf':
                mime_type = 'application/pdf'
            elif extensao in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif extensao == '.png': # <-- ADICIONADO ELIF
                mime_type = 'image/png'
            else:
                messagebox.showerror("Erro", "Tipo de arquivo não suportado. Use PDF, JPG ou PNG.", parent=popup)
                return
            # --- FIM DA CORREÇÃO 2 ---

            # Prepara os dados para enviar à API
            url_upload = f"{config.API_BASE_URL}/documentos/upload" # ATENÇÃO AO IP!
            dados_payload = {
                'funcionario_id': funcionario_id,
                'tipo_documento': tipo,
                'mes_ano': data_ref.strftime('%Y-%m-%d'),
            }
            
            try:
                with open(caminho_arquivo, 'rb') as f:
                    # --- CORREÇÃO 3: Usa o nome e o MIME type dinâmicos ---
                    arquivos_payload = {'file': (nome_arquivo, f, mime_type)}
                    # --- FIM DA CORREÇÃO 3 ---
                    
                    # Faz a requisição para a API
                    response = requests.post(url_upload, data=dados_payload, files=arquivos_payload)

                if response.status_code == 201:
                    messagebox.showinfo("Sucesso", "Documento enviado com sucesso!", parent=popup)
                    popup.destroy()
                    self.on_rh_funcionario_selecionado(None) # Atualiza a lista de documentos
                else:
                    messagebox.showerror("Erro da API", f"Falha no upload: {response.json().get('mensagem', response.text)}", parent=popup)
            except Exception as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}", parent=popup)

        # Botão de Envio
        btn_salvar = ttk.Button(frame, text="Salvar e Disponibilizar", command=enviar_documento)
        btn_salvar.grid(row=3, column=0, columnspan=2, pady=20, ipady=5)

        frame.columnconfigure(1, weight=1)

    def solicitar_onboarding_funcionario(self):
        """Dispara a notificação para o funcionário iniciar o processo de onboarding."""
        selecionado = self.tree_rh_funcionarios.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário na lista da esquerda primeiro.")
            return
        
        dados_func = self.tree_rh_funcionarios.item(selecionado, 'values')
        funcionario_id = dados_func[0]
        nome_funcionario = dados_func[1]
        
        # 1. Tenta inicializar o status no banco (seta para 'Pendente')
        if not database.iniciar_onboarding_funcionario(funcionario_id):
            messagebox.showerror("Erro", "Falha ao registrar o status de onboarding no banco.")
            return

        # 2. Busca o ChatID para notificar
        func_obj = database.buscar_funcionario_por_id(funcionario_id)
        if not func_obj or not func_obj.ChatIDTelegram:
             messagebox.showwarning("Aviso", "Funcionário sem ChatID Telegram cadastrado. Não é possível notificar.")
             return

        # 3. Envia a notificação inicial que fará o fluxo de bloqueio começar
        mensagem = (f"🎉 **Bem-vindo(a) à Gela Boca, {nome_funcionario}!** 🎉\n\n"
                    "Para dar início ao seu registro, precisamos que você nos envie seus documentos e dados pessoais. "
                    "Seu acesso ao sistema será bloqueado até que o processo seja concluído.\n\n"
                    "Por favor, digite **qualquer mensagem** (ou /start) para começar o envio de documentos.")
        
        notificador_telegram.enviar_mensagem(func_obj.ChatIDTelegram, mensagem)
        messagebox.showinfo("Sucesso", f"Notificação de Onboarding enviada para {nome_funcionario}!")
    
    def atualizar_lista_comunicados(self, filtro=None):
        for i in self.tree_comunicados.get_children(): self.tree_comunicados.delete(i)
        comunicados = database.listar_comunicados_com_status(filtro_titulo=filtro)
        for doc in comunicados:
            status = f"{doc.TotalCientes} / {doc.TotalEnviado} Cientes"
            data_formatada = doc.DataCriacao.strftime("%d/%m/%Y %H:%M")
            self.tree_comunicados.insert("", "end", values=(doc.DocumentoID, doc.Titulo, data_formatada, status))

    def abrir_janela_criacao(self): # <<< ESTA FUNÇÃO ESTAVA FALTANDO!
            # --- CORREÇÃO: Limpa resíduos de seleções anteriores ---
        if hasattr(self, 'caminho_imagem_selecionada'):
            del self.caminho_imagem_selecionada
        # -------------------------------------------------------
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
        frame_imagem = Frame(self.popup_criacao)
        frame_imagem.pack(padx=10, pady=5, fill='x')
        btn_selecionar_img = Button(frame_imagem, text="Anexar Imagem...", command=lambda: self.selecionar_imagem(lbl_caminho_imagem))
        btn_selecionar_img.pack(side="left")
        lbl_caminho_imagem = Label(frame_imagem, text="Nenhuma imagem selecionada.", font=("Arial", 9, "italic"))
        lbl_caminho_imagem.pack(side="left", padx=10)
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
    
    # Em gestao_pessoas_main.py, SUBSTITUA a função antiga por esta:

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

        # Prepara dados iniciais na Thread principal para evitar erros de GUI
        destinatarios_nomes = [listbox.get(i) for i in indices_selecionados]
        destinatarios_objs = [self.dados_funcionarios[nome] for nome in destinatarios_nomes]
        imagem_anexada = hasattr(self, 'caminho_imagem_selecionada') and self.caminho_imagem_selecionada
        caminho_imagem = self.caminho_imagem_selecionada if imagem_anexada else None

        # Desabilita botão para evitar múltiplos cliques
        btn_enviar = self.popup_criacao.nametowidget(listbox.master.master.winfo_children()[-1]) # Pega o botão enviar (último widget)
        if btn_enviar: btn_enviar.config(state="disabled", text="Enviando... Aguarde")

        def tarefa_envio_background():
            try:
                GESTOR_ID = 2  # Assumindo ID 2 para o gestor
                documento_id = database.criar_documento(titulo, conteudo.strip(), GESTOR_ID, pontos)
                if not documento_id:
                    self.root.after(0, lambda: messagebox.showerror("Erro de BD", "Não foi possível criar o registro do documento.", parent=self.popup_criacao))
                    return

                telegram_file_id = None
                enviados_com_sucesso = 0

                # 1. Prepara as mensagens
                legenda_imagem_curta = f"🚨 **NOVO COMUNICADO** 🚨\n\n**Título:** {titulo}"
                texto_principal = f"**Conteúdo:**\n{conteudo.strip()}\n\nSua confirmação de leitura é obrigatória e será registrada."

                # 2. Envio da imagem inicial (se houver) com Fallback
                telegram_file_id = None
                if caminho_imagem:
                    try:
                        logger.info(f"Tentando obter file_id via Grupo Gestor ({config.GESTOR_GROUP_CHAT_ID})...")
                        resposta_api_foto = notificador_telegram.enviar_foto_com_botoes(
                            config.GESTOR_GROUP_CHAT_ID, 
                            caminho_imagem, 
                            f"(Log de Envio: {titulo})" 
                        )

                        if resposta_api_foto and resposta_api_foto.get('ok'):
                            telegram_file_id = resposta_api_foto['result']['photo'][-1]['file_id']
                            database.atualizar_documento_com_file_id(documento_id, telegram_file_id)
                        else:
                            logger.warning(f"Falha ao enviar imagem para grupo de controle: {resposta_api_foto}")
                            # Não aborta, apenas segue sem imagem
                    except Exception as e_img:
                        logger.error(f"Erro de conexão ao enviar imagem de controle: {e_img}")
                        # Não aborta

                # 3. Itera sobre TODOS os funcionários
                for func in destinatarios_objs:
                    assinatura_id = database.registrar_pendencia_assinatura(documento_id, func.FuncionarioID)
                    if not assinatura_id:
                        logger.warning(f"!!! Falha ao registrar pendência para {func.NomeCompleto}")
                        continue

                    keyboard = [[InlineKeyboardButton("✅ Li e estou ciente", callback_data=f"doc_ciente_{assinatura_id}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    if telegram_file_id:
                        notificador_telegram.enviar_foto_com_botoes(
                            func.ChatIDTelegram,
                            telegram_file_id, 
                            legenda_imagem_curta
                        )
                        time.sleep(0.2) 

                    notificador_telegram.enviar_mensagem_com_botao(
                        func.ChatIDTelegram,
                        texto_principal,
                        reply_markup
                    )
                    enviados_com_sucesso += 1
                    time.sleep(0.1)

                # Finalização na Thread Principal
                def finalizar_ui():
                    messagebox.showinfo("Sucesso", f"{enviados_com_sucesso} de {len(destinatarios_objs)} comunicados foram enviados.", parent=self.popup_criacao)
                    if hasattr(self, 'caminho_imagem_selecionada'):
                        del self.caminho_imagem_selecionada
                    self.popup_criacao.destroy()
                    self.atualizar_lista_comunicados()
                
                self.root.after(0, finalizar_ui)

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Erro Inesperado", f"O processo foi interrompido:\n{e}", parent=self.popup_criacao))
                # Reabilita botão em caso de erro
                self.root.after(0, lambda: btn_enviar.config(state="normal", text="ENVIAR COMUNICADO"))

        # Inicia a thread
        import threading
        threading.Thread(target=tarefa_envio_background, daemon=True).start()

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

    def selecionar_imagem(self, label_caminho):
        filepath = filedialog.askopenfilename(title="Selecione uma Imagem para o Comunicado", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.gif"),("Todos os arquivos", "*.*")])
        if filepath:
            self.caminho_imagem_selecionada = filepath
            label_caminho.config(text=os.path.basename(filepath))
        else:
            if hasattr(self, 'caminho_imagem_selecionada'): del self.caminho_imagem_selecionada
            label_caminho.config(text="Nenhuma imagem selecionada.")

    def reiniciar_processo_onboarding(self):
        """Limpa os dados de onboarding do funcionário para que ele faça de novo."""
        selecionado = self.tree_onboarding.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista.")
            return

        dados = self.tree_onboarding.item(selecionado, 'values')
        funcionario_id = dados[0]
        nome = dados[1]

        confirmacao = messagebox.askyesno(
            "Reiniciar Onboarding",
            f"Deseja reiniciar o processo de admissão para '{nome}'?\n\n"
            "Isso apagará os documentos e dados preenchidos (Escolaridade, Filhos, etc), "
            "permitindo que ele comece do zero pelo Telegram.\n\n"
            "O funcionário NÃO será excluído do sistema.",
            parent=self.root
        )

        if confirmacao:
            if database.resetar_onboarding_completo(funcionario_id):
                # Opcional: Notificar o funcionário que o processo foi reiniciado
                func_obj = database.buscar_funcionario_por_id(funcionario_id)
                if func_obj and func_obj.ChatIDTelegram:
                    notificador_telegram.enviar_mensagem(
                        func_obj.ChatIDTelegram,
                        "🔄 **Processo de Admissão Reiniciado**\n\n"
                        "O RH solicitou o preenchimento novamente dos seus dados.\n"
                        "Por favor, digite 'Começar' para enviar as informações corretas."
                    )

                messagebox.showinfo("Sucesso", "Processo reiniciado! O funcionário pode preencher os dados novamente.", parent=self.root)
                self.carregar_onboarding_lista()
            else:
                messagebox.showerror("Erro", "Falha ao reiniciar o processo no banco de dados.", parent=self.root)        
        
if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoPessoas(root) 
    root.mainloop()
>>>>>>> master

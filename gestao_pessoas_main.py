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
import requests
import comunicado_generator
import file_utils
import recibo_generator
import config


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

        self.notebook.add(self.frame_comunicados, text='Comunicados')
        self.notebook.add(self.frame_documentos, text='Documentos Pessoais (RH)')
        
        self.dados_funcionarios = {}
        self.popup_criacao = None

        self.criar_aba_comunicados()
        self.criar_aba_documentos()
        
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
        btn_add = ttk.Button(frame_botoes_docs, text="Adicionar Novo Documento...", command=self.abrir_janela_add_documento)
        btn_add.pack(side="left")
        btn_vis = ttk.Button(frame_botoes_docs, text="Visualizar/Baixar Documento", command=self.visualizar_documento_selecionado)
        btn_vis.pack(side="left", padx=10)

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
                # --- CORREÇÃO LÓGICA: Extrair nome e extensão reais do Header ---
                import re
                nome_remoto = ""
                # Tenta pegar o nome real do arquivo enviado pelo servidor
                if "Content-Disposition" in response.headers:
                    fname = re.findall('filename="?([^"]+)"?', response.headers["Content-Disposition"])
                    if fname:
                        nome_remoto = fname[0]

                # Fallback se o header falhar: usa PDF padrão, mas tenta detectar imagem pelo Content-Type
                if not nome_remoto:
                    ext = ".pdf" # Padrão seguro
                    content_type = response.headers.get("Content-Type", "")
                    if "image/jpeg" in content_type: ext = ".jpg"
                    elif "image/png" in content_type: ext = ".png"
                    
                    # CORREÇÃO: Adiciona ID do documento para garantir unicidade local e evitar PermissionError
                    nome_remoto = f"{dados_doc[1]}_{dados_doc[2].replace('/', '-')}_{documento_id}{ext}"

                pasta_downloads = "downloads"
                if not os.path.exists(pasta_downloads):
                    os.makedirs(pasta_downloads)

                caminho_local = os.path.join(pasta_downloads, nome_remoto)
                # Salva o arquivo recebido no disco local
                with open(caminho_local, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                print(f"--> Download concluído! Arquivo salvo em: {caminho_local}")

                # Abre o arquivo com o programa padrão do Windows
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

# Em gestao_pessoas_main.py, SUBSTITUA a função inteira pelo código abaixo:

# Em gestao_pessoas_main.py, SUBSTITUA a função inteira pelo código abaixo:

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

        try:
            destinatarios_nomes = [listbox.get(i) for i in indices_selecionados]
            destinatarios_objs = [self.dados_funcionarios[nome] for nome in destinatarios_nomes]

            GESTOR_ID = 2  # Assumindo ID 2 para o gestor
            documento_id = database.criar_documento(titulo, conteudo.strip(), GESTOR_ID, pontos)
            if not documento_id:
                messagebox.showerror("Erro de BD", "Não foi possível criar o registro do documento.", parent=self.popup_criacao)
                return

            imagem_anexada = hasattr(self, 'caminho_imagem_selecionada') and self.caminho_imagem_selecionada
            telegram_file_id = None
            enviados_com_sucesso = 0

            # --- LÓGICA DE ENVIO EM DUAS ETAPAS ---
            
            # 1. Prepara as mensagens
            legenda_imagem_curta = f"🚨 **NOVO COMUNICADO** 🚨\n\n**Título:** {titulo}"
            texto_principal = f"**Conteúdo:**\n{conteudo.strip()}\n\nSua confirmação de leitura é obrigatória e será registrada."

            # 2. Envia para o primeiro funcionário para obter o file_id da imagem (se houver)
            # 2. Envia para o GRUPO DE GESTORES para obter o file_id da imagem (se houver)
            if imagem_anexada:
                # ENVIAMOS PARA O GRUPO DE GESTÃO (um ID seguro) EM VEZ DO PRIMEIRO USUÁRIO
                logger.info(f"Enviando foto para GESTOR_GROUP_CHAT_ID ({config.GESTOR_GROUP_CHAT_ID}) para obter file_id...")
                resposta_api_foto = notificador_telegram.enviar_foto_com_botoes(
                    config.GESTOR_GROUP_CHAT_ID, 
                    self.caminho_imagem_selecionada, 
                    f"(Log de Envio: {titulo})" # Legenda curta para o log do gestor
                ) # Envia a foto SÓ com a legenda curta, sem botões

                if resposta_api_foto and resposta_api_foto.get('ok'):
                    telegram_file_id = resposta_api_foto['result']['photo'][-1]['file_id']
                    database.atualizar_documento_com_file_id(documento_id, telegram_file_id)
                else:
                    messagebox.showerror("Erro Telegram", "Não foi possível enviar a imagem inicial.", parent=self.popup_criacao)
                    database.excluir_documento(documento_id)
                    return

            # 3. Itera sobre TODOS os funcionários para enviar o conteúdo e o botão
            for func in destinatarios_objs:
                assinatura_id = database.registrar_pendencia_assinatura(documento_id, func.FuncionarioID)
                if not assinatura_id:
                    logger.warning(f"!!! Falha ao registrar pendência para {func.NomeCompleto}")
                    continue

                keyboard = [[InlineKeyboardButton("✅ Li e estou ciente", callback_data=f"doc_ciente_{assinatura_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Se tivermos um file_id (de uma imagem), enviamos a foto primeiro
                if telegram_file_id:
                    notificador_telegram.enviar_foto_com_botoes(
                        func.ChatIDTelegram,
                        telegram_file_id, # Reutiliza o file_id
                        legenda_imagem_curta
                    )
                    time.sleep(0.2) # Pequena pausa entre as mensagens

                # Envia a mensagem de texto com o conteúdo completo e o botão
                notificador_telegram.enviar_mensagem_com_botao(
                    func.ChatIDTelegram,
                    texto_principal,
                    reply_markup
                )
                enviados_com_sucesso += 1
                # Atualiza a interface gráfica para evitar congelamento ("Não Respondendo")
                self.root.update()
                time.sleep(0.1)

            messagebox.showinfo("Sucesso", f"{enviados_com_sucesso} de {len(destinatarios_objs)} comunicados foram enviados.", parent=self.popup_criacao)
            if imagem_anexada:
                del self.caminho_imagem_selecionada
            self.popup_criacao.destroy()
            self.atualizar_lista_comunicados()

        except Exception as e:
            # CORREÇÃO: Removemos a exclusão automática do documento aqui.
            # Se o erro ocorrer no meio do loop, não podemos apagar o documento,
            # pois alguns funcionários já podem ter recebido a notificação.
            messagebox.showerror("Erro Inesperado", f"O processo foi interrompido:\n{e}\n\nVerifique a lista para ver quem recebeu.", parent=self.popup_criacao)


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
        
if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoPessoas(root) 
    root.mainloop()

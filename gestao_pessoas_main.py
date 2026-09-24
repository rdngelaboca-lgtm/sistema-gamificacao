# ==============================================================================
# == gestao_pessoas_main.py  -  Módulo de Gestão de Pessoas (RH)  ===============
# ==============================================================================
# Versão DEPURADA. Todas as correções estão marcadas com o comentário [DEPURAÇÃO]
# para você conseguir encontrar (Ctrl+F "[DEPURAÇÃO]") e entender o que mudou.
#
# Abas desta janela:
#   1) Onboarding/Admissional -> aprovar exame, ver dados/fotos, gerar PDF
#   2) Comunicados            -> criar, enviar pelo Telegram, ver quem deu ciência
#   3) Documentos Pessoais    -> enviar/baixar/editar/excluir holerites etc. (via api_server.py)
# ==============================================================================

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
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        print(f"Pasta de logs criada em: {log_dir}") # Print inicial para confirmar criação
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        # Se não conseguir criar a pasta, tenta logar no diretório atual
        log_dir = os.path.dirname(os.path.abspath(__file__))

log_filepath = os.path.join(log_dir, LOG_FILENAME)

# --- Configuração do Handler de Arquivo Rotativo ---
file_handler = logging.handlers.RotatingFileHandler(
    log_filepath, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
)
file_handler.setLevel(LOG_LEVEL)
file_formatter = logging.Formatter(LOG_FORMAT)
file_handler.setFormatter(file_formatter)

# --- Configuração do Handler do Console ---
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL)
console_formatter = logging.Formatter(LOG_FORMAT)
console_handler.setFormatter(console_formatter)

# --- Configuração do Logger Raiz ---
logging.getLogger('').handlers = []
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[file_handler, console_handler])

# Obtém um logger específico para este módulo
logger = logging.getLogger(__name__)

logger.info(f"*** Logging configurado para o módulo: {__name__} ***")
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================

import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, Listbox, Checkbutton, Text, Entry, Scrollbar, Frame, Label, Button
from tkinter import filedialog
from datetime import datetime
import email.message   # [DEPURAÇÃO] substitui o módulo "cgi", que NÃO EXISTE MAIS no Python 3.13
import html            # [DEPURAÇÃO] para "escapar" textos enviados ao Telegram em modo HTML
import json
import queue           # [DEPURAÇÃO] comunicação segura entre a thread de envio e a janela
import re
import threading
import time

import requests
from PIL import Image, ImageTk
from fpdf import FPDF
from tkcalendar import DateEntry
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
import database
import file_utils
import recibo_generator

# [DEPURAÇÃO] REMOVIDO: "import comunicado_generator".
#   Esse arquivo é uma cópia ANTIGA do bot do Telegram e não era usado aqui.
#   Importá-lo obrigava a ter "exifread" e "telegram.ext" instalados e rodava
#   configurações do bot antigo (locale, logging). Se faltasse algo, ESTA janela
#   nem abria. Também removidos "tempfile" e "shutil", que não eram usados.
# [DEPURAÇÃO] "notificador_telegram" não é mais usado neste arquivo: a função
#   enviar_mensagem_com_botao() dele usa parse_mode 'Markdown' (quebra com "_" ou "*"
#   no texto do comunicado) e não diz se o envio deu certo. Aqui usamos o envio
#   próprio abaixo (HTML + confere a resposta do Telegram + timeout).


# ==============================================================================
# == [DEPURAÇÃO] CONSTANTES E FUNÇÕES AUXILIARES ================================
# ==============================================================================

# ID do gestor que "está usando" esta janela (antes estava fixo no número 2 no código).
ID_GESTOR = getattr(config, 'ID_GESTOR_PADRAO', 2)

TIMEOUT_API = 30            # segundos esperando o api_server.py responder
TIMEOUT_UPLOAD = 120        # upload pode demorar mais (arquivo grande)
LIMITE_TEXTO_TELEGRAM = 3000   # Telegram aceita 4096; deixamos folga p/ título e recibo de ciência
LIMITE_LEGENDA_TELEGRAM = 900  # Legenda de foto aceita 1024
NIVEIS_COM_ACESSO_RH = ('RH', 'Gestor')
TIPOS_DOCUMENTO = ['Holerite', 'Cartão Ponto', 'Comprovante de Consumo', 'Contrato',
                   'Atestado', 'Advertência', 'Outro']


def esc(valor):
    """Escapa <, > e & para o texto não quebrar o modo HTML do Telegram."""
    return html.escape('' if valor is None else str(valor), quote=False)


def fmt_data(valor, formato='%d/%m/%Y', vazio='---'):
    """
    Formata datas sem travar a tela.
    Aceita datetime/date (do banco), texto '2025-01-31', ou None.
    """
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return vazio
    if hasattr(valor, 'strftime'):
        try:
            return valor.strftime(formato)
        except Exception:
            return str(valor)
    texto = str(valor).strip()
    try:
        return datetime.fromisoformat(texto.replace('Z', '')).strftime(formato)
    except ValueError:
        return texto


def _sem_token(texto):
    """Remove o token do bot de mensagens de erro (os erros do 'requests' mostram a URL)."""
    token = str(getattr(config, 'TELEGRAM_TOKEN', '') or '')
    texto = str(texto)
    return texto.replace(token, '***TOKEN***') if token else texto


def headers_api():
    """Cabeçalho com a chave da API (só se você criar API_KEY no config.py)."""
    chave = getattr(config, 'API_KEY', None)
    return {'X-API-Key': str(chave)} if chave else {}


def mensagem_erro_api(response):
    """Transforma a resposta de erro do api_server.py em uma frase legível."""
    if response.status_code == 401:
        return ("Acesso negado pela API (erro 401).\n\n"
                "O api_server.py só libera documentos para:\n"
                " • o próprio computador onde ele está rodando, ou\n"
                " • quem enviar a chave API_KEY correta.\n\n"
                "Se esta janela roda em OUTRO computador, crie a mesma linha\n"
                "API_KEY = \"uma-senha-longa\" no config.py dos dois computadores.")
    try:
        dados = response.json()
        if isinstance(dados, dict) and dados.get('mensagem'):
            return f"{dados['mensagem']} (HTTP {response.status_code})"
    except ValueError:
        pass
    texto = (response.text or '').strip()[:200] or 'Sem conteúdo'
    return f"Erro HTTP {response.status_code}: {texto}"


def nome_arquivo_seguro(nome):
    """Tira pastas e caracteres proibidos no Windows (<>:\"/\\|?*) do nome do arquivo."""
    nome = os.path.basename(str(nome or '').replace('\\', '/'))
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', nome).strip(' .')
    return nome[:150]


def nome_arquivo_do_header(header):
    """
    [DEPURAÇÃO] Lê o nome do arquivo do cabeçalho 'Content-Disposition'.
    Antes usava cgi.parse_header() -> o módulo 'cgi' foi REMOVIDO no Python 3.13,
    então o botão "Visualizar/Baixar" dava ImportError e não fazia nada.
    """
    if not header:
        return ''
    try:
        msg = email.message.Message()
        msg['content-disposition'] = header
        nome = msg.get_filename()  # entende filename="..." e filename*=UTF-8''...
        if nome:
            return nome_arquivo_seguro(nome)
    except Exception:
        pass
    achados = re.findall(r'filename="?([^";]+)"?', header)
    return nome_arquivo_seguro(achados[0]) if achados else ''


def pdf_txt(valor, vazio='---'):
    """
    [DEPURAÇÃO] As fontes padrão do FPDF só aceitam o alfabeto 'latin-1'.
    Emojis, travessões '–' ou aspas curvas '“ ”' faziam o PDF inteiro falhar.
    Aqui trocamos esses caracteres por equivalentes simples.
    """
    if valor is None or not str(valor).strip():
        return vazio
    texto = str(valor)
    trocas = {'–': '-', '—': '-', '‘': "'", '’': "'", '“': '"',
              '”': '"', '•': '-', '…': '...', ' ': ' '}
    for antigo, novo in trocas.items():
        texto = texto.replace(antigo, novo)
    return texto.encode('latin-1', 'replace').decode('latin-1')


def dividir_texto(texto, limite):
    """Divide um texto longo em pedaços (de preferência quebrando em linhas)."""
    texto = texto or ''
    partes = []
    while len(texto) > limite:
        corte = texto.rfind('\n', 0, limite)
        if corte < limite // 2:
            corte = texto.rfind(' ', 0, limite)
        if corte < limite // 2:
            corte = limite
        partes.append(texto[:corte].rstrip())
        texto = texto[corte:].lstrip('\n ')
    partes.append(texto)
    return partes


def carregar_filhos(dados_filhos_json):
    """Lê o JSON de dependentes salvo pelo bot. Devolve [] se estiver vazio/estragado."""
    if not dados_filhos_json:
        return []
    try:
        filhos = json.loads(dados_filhos_json)
        return [f for f in filhos if isinstance(f, dict)] if isinstance(filhos, list) else []
    except (TypeError, ValueError):
        return None  # None = "estava estragado" (diferente de lista vazia)


# ------------------------------------------------------------------------------
# [DEPURAÇÃO] Envio direto ao Telegram (HTML + timeout + confere se deu certo)
# ------------------------------------------------------------------------------
def telegram_api(metodo, dados, arquivos=None, timeout=30):
    """Chama a API do Telegram e devolve o JSON de resposta (ou None se a rede falhar)."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{metodo}"
    try:
        resposta = requests.post(url, data=dados, files=arquivos, timeout=timeout).json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"Falha de rede ao chamar Telegram/{metodo}: {_sem_token(e)}")
        return None
    if not resposta.get('ok'):
        logger.warning(f"Telegram recusou {metodo}: {resposta.get('description')}")
    return resposta


def enviar_texto_telegram(chat_id, texto_html, reply_markup=None):
    """Envia mensagem em HTML. Devolve True só se o Telegram confirmou."""
    if not chat_id:
        return False
    dados = {'chat_id': chat_id, 'text': texto_html, 'parse_mode': 'HTML',
             'disable_web_page_preview': 'true'}
    if reply_markup is not None:
        dados['reply_markup'] = json.dumps(reply_markup.to_dict())
    resposta = telegram_api('sendMessage', dados)
    return bool(resposta and resposta.get('ok'))


def enviar_foto_telegram(chat_id, foto, legenda_html):
    """
    Envia foto (caminho de arquivo no PC ou file_id do Telegram).
    Devolve o file_id da foto enviada, ou None se falhou.
    """
    if not chat_id or not foto:
        return None
    dados = {'chat_id': chat_id, 'caption': legenda_html, 'parse_mode': 'HTML'}
    if isinstance(foto, str) and os.path.isfile(foto):
        try:
            with open(foto, 'rb') as arquivo:
                resposta = telegram_api('sendPhoto', dados, arquivos={'photo': arquivo}, timeout=90)
        except OSError as e:
            logger.error(f"Não foi possível abrir a imagem {foto}: {e}")
            return None
    else:
        dados['photo'] = foto
        resposta = telegram_api('sendPhoto', dados)
    if resposta and resposta.get('ok'):
        try:
            return resposta['result']['photo'][-1]['file_id']
        except (KeyError, IndexError, TypeError):
            return None
    return None


def montar_partes_comunicado(titulo, conteudo, importante=False):
    """Monta o texto do comunicado em HTML, dividido em partes que cabem no Telegram."""
    titulo_curto = (titulo or '').strip()[:300]
    selo = "🚨 <b>NOVO COMUNICADO IMPORTANTE</b> 🚨" if importante else "🚨 <b>NOVO COMUNICADO</b> 🚨"
    pedacos = dividir_texto((conteudo or '').strip(), LIMITE_TEXTO_TELEGRAM)
    partes = []
    for i, pedaco in enumerate(pedacos):
        if i == 0:
            partes.append(f"{selo}\n\n<b>Título:</b> {esc(titulo_curto)}\n\n<b>Conteúdo:</b>\n{esc(pedaco)}")
        else:
            partes.append(f"<i>(continuação {i + 1}/{len(pedacos)})</i>\n\n{esc(pedaco)}")
    partes[-1] += "\n\n<i>Sua confirmação de leitura é obrigatória e será registrada.</i>"
    return partes


def enviar_comunicado_para_funcionario(chat_id, assinatura_id, partes_html, foto=None, legenda_html=''):
    """
    Envia (foto opcional) + texto do comunicado + botão "Li e estou ciente".
    O botão vai SEMPRE na última parte. Devolve (ok, file_id_da_foto).
    """
    file_id = None
    if foto:
        file_id = enviar_foto_telegram(chat_id, foto, legenda_html)
        time.sleep(0.2)
    for parte in partes_html[:-1]:
        if not enviar_texto_telegram(chat_id, parte):
            return False, file_id
        time.sleep(0.1)
    teclado = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Li e estou ciente",
                                                          callback_data=f"doc_ciente_{int(assinatura_id)}")]])
    return enviar_texto_telegram(chat_id, partes_html[-1], teclado), file_id


def buscar_arquivo_telegram(file_id):
    """Pergunta ao Telegram onde está o arquivo. Devolve file_path (ex: 'photos/file_1.jpg') ou None."""
    try:
        r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getFile",
                         params={'file_id': file_id}, timeout=15)
        dados = r.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"Falha ao consultar arquivo no Telegram: {_sem_token(e)}")
        return None
    if not dados.get('ok'):
        logger.warning(f"Telegram não encontrou o arquivo: {dados.get('description')}")
        return None
    return (dados.get('result') or {}).get('file_path')


def baixar_bytes_telegram(file_path, timeout=60):
    """Baixa o conteúdo de um arquivo do Telegram. Devolve bytes ou None."""
    try:
        r = requests.get(f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{file_path}",
                         timeout=timeout)
    except requests.exceptions.RequestException as e:
        logger.error(f"Falha ao baixar arquivo do Telegram: {_sem_token(e)}")
        return None
    if r.status_code != 200:
        logger.warning(f"Download do Telegram respondeu HTTP {r.status_code}")
        return None
    return r.content


# ==============================================================================
# == JANELA PRINCIPAL ==========================================================
# ==============================================================================
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

        # [DEPURAÇÃO] Antes: self.USUARIO_LOGADO_ID = 2 (fixo) + print de DEBUG.
        # Agora vem do config.py (ID_GESTOR_PADRAO) e vai para o log.
        self.USUARIO_LOGADO_ID = ID_GESTOR
        self.nivel_usuario = self._buscar_nivel_acesso(self.USUARIO_LOGADO_ID)
        logger.info(f"Gestão de Pessoas aberta pelo usuário ID {self.USUARIO_LOGADO_ID} "
                    f"(nível de acesso: {self.nivel_usuario})")

        self.frame_onboarding = ttk.Frame(self.notebook, padding="10")

        self.notebook.add(self.frame_onboarding, text='📝 Onboarding/Admissional')
        self.notebook.add(self.frame_comunicados, text='Comunicados')
        self.notebook.add(self.frame_documentos, text='Documentos Pessoais (RH)')

        self.dados_funcionarios = {}
        self.popup_criacao = None
        self.btn_enviar_comunicado = None
        self.caminho_imagem_selecionada = None   # [DEPURAÇÃO] sempre existe (antes usava hasattr/del)
        self.tree_onboarding = None              # [DEPURAÇÃO] só é criada se o usuário tiver acesso
        self.btn_aprovar_admissional = None
        self._fila_envio = None

        self.criar_aba_comunicados()
        self.criar_aba_documentos()
        self.criar_aba_onboarding()

        self.atualizar_lista_comunicados()
        self.carregar_rh_funcionarios()

    # ------------------------------------------------------------------
    # Auxiliares de janela
    # ------------------------------------------------------------------
    @staticmethod
    def _janela_existe(janela):
        """True se a janela (Toplevel) ainda está aberta."""
        try:
            return janela is not None and bool(janela.winfo_exists())
        except tk.TclError:
            return False

    def _pai_seguro(self, janela):
        """Usa a janela pedida como 'pai' da caixa de mensagem, ou a principal se ela já fechou."""
        return janela if self._janela_existe(janela) else self.root

    def _linha_selecionada(self, tree):
        """Devolve os valores da linha selecionada numa Treeview, ou None."""
        if tree is None:
            return None
        item = tree.focus()
        if not item:
            return None
        valores = tree.item(item, 'values')
        return valores if valores else None

    # --- ABA 1: COMUNICADOS ---
    def criar_aba_comunicados(self):
        self.frame_comunicados.grid_rowconfigure(2, weight=1)
        self.frame_comunicados.grid_columnconfigure(0, weight=1)
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
        frame_filtro.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        lbl_filtro = ttk.Label(frame_filtro, text="Filtrar por Título:")
        lbl_filtro.pack(side="left")
        self.entry_filtro = ttk.Entry(frame_filtro, width=40)
        self.entry_filtro.pack(side="left", padx=5, fill="x", expand=True)
        self.entry_filtro.bind('<Return>', lambda e: self.filtrar_lista_comunicados())  # Enter também busca
        btn_buscar = ttk.Button(frame_filtro, text="Buscar", command=self.filtrar_lista_comunicados)
        btn_buscar.pack(side="left", padx=(0, 5))
        btn_limpar = ttk.Button(frame_filtro, text="Limpar", command=self.limpar_filtro)
        btn_limpar.pack(side="left")
        frame_lista = ttk.Frame(self.frame_comunicados)
        frame_lista.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
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
        frame_botoes_docs.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        btn_solicitar_onboarding = ttk.Button(frame_botoes_docs, text="🚀 Solicitar Documentos (Onboarding)", command=self.solicitar_onboarding_funcionario)
        btn_solicitar_onboarding.pack(side="left", padx=(0, 20))
        btn_add = ttk.Button(frame_botoes_docs, text="Adicionar Novo Documento...", command=self.abrir_janela_add_documento)
        btn_add.pack(side="left")

        btn_edit = ttk.Button(frame_botoes_docs, text="Editar Metadados", command=self.abrir_janela_edicao_documento)
        btn_edit.pack(side="left", padx=10)

        btn_del = ttk.Button(frame_botoes_docs, text="Excluir Documento", command=self.excluir_documento_selecionado)
        btn_del.pack(side="left", padx=10)

        btn_vis = ttk.Button(frame_botoes_docs, text="Visualizar/Baixar Documento", command=self.visualizar_documento_selecionado)
        btn_vis.pack(side="right")

    # --- ABA 3: ONBOARDING ---
    def criar_aba_onboarding(self):
        """Cria a interface para gerenciar a aprovação do exame admissional."""
        # Acesso restrito apenas a Gestores e RH para evitar vazamento de dados
        if self.nivel_usuario not in NIVEIS_COM_ACESSO_RH:
            ttk.Label(self.frame_onboarding, text="ACESSO NEGADO: Esta área é restrita ao RH/Gestão.",
                      font=("Arial", 16, "bold"), foreground="red").pack(pady=(50, 10))
            # [DEPURAÇÃO] explica COMO liberar, em vez de só negar
            ttk.Label(self.frame_onboarding,
                      text=(f"Usuário configurado: ID {self.USUARIO_LOGADO_ID} (nível '{self.nivel_usuario}').\n"
                            "Para liberar: no cadastro desse funcionário, NivelAcesso deve ser 'Gestor' ou 'RH',\n"
                            "ou ajuste ID_GESTOR_PADRAO no config.py."),
                      justify="center").pack()
            return

        main_frame = ttk.Frame(self.frame_onboarding)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)

        cols = ('ID', 'Nome', 'Status Documentos', 'Status Admissional', 'Última Etapa', 'Data Admissional')
        self.tree_onboarding = ttk.Treeview(main_frame, columns=cols, show='headings', selectmode='browse')
        for col in cols:
            self.tree_onboarding.heading(col, text=col)

        self.tree_onboarding.column('ID', width=40)
        self.tree_onboarding.column('Status Documentos', width=120, anchor='center')
        self.tree_onboarding.column('Status Admissional', width=120, anchor='center')
        self.tree_onboarding.column('Data Admissional', width=120, anchor='center')

        self.tree_onboarding.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tree_onboarding.bind('<<TreeviewSelect>>', self.on_onboarding_selecionado)

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
        if self.tree_onboarding is None:
            return
        for i in self.tree_onboarding.get_children():
            self.tree_onboarding.delete(i)

        funcionarios = database.buscar_onboarding_lista_rh() or []

        for f in funcionarios:
            # [DEPURAÇÃO] fmt_data não trava se a data vier como texto ou vazia
            self.tree_onboarding.insert("", "end", values=(
                f.FuncionarioID, f.NomeCompleto, f.StatusWorkflow or '---', f.StatusAdmissional or '---',
                f.UltimaEtapa or '---', fmt_data(f.DataAdmissional)
            ))

    def on_onboarding_selecionado(self, event):
        """Habilita/desabilita o botão de aprovação conforme o status."""
        dados = self._linha_selecionada(self.tree_onboarding)
        if not dados or self.btn_aprovar_admissional is None:
            return
        estado = "normal" if dados[3] == 'Pendente' else "disabled"
        self.btn_aprovar_admissional.config(state=estado)

    def aprovar_exame_admissional_rh(self):
        """Dispara a aprovação manual do exame admissional."""
        dados = self._linha_selecionada(self.tree_onboarding)
        if not dados:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista.")  # [DEPURAÇÃO] antes não dizia nada
            return

        funcionario_id = dados[0]
        nome_funcionario = dados[1]

        if dados[3] != 'Pendente':
            messagebox.showwarning("Aviso", "O exame deste funcionário já foi aprovado.")
            return

        confirmado = messagebox.askyesno(
            "Confirmar Aprovação",
            f"Tem certeza que deseja aprovar o exame admissional para {nome_funcionario}?\n\n"
            "Isso liberará o acesso TOTAL dele ao Bot Telegram.")
        if not confirmado:
            return

        if not database.aprovar_exame_admissional(funcionario_id, datetime.now()):
            messagebox.showerror("Erro", "Falha ao atualizar o status no banco de dados.")
            return

        # [DEPURAÇÃO] Mensagem em HTML (<b>) - antes usava **, que aparecia literalmente no Telegram
        aviso_telegram = ""
        func_obj = database.buscar_funcionario_por_id(funcionario_id)
        chat_id = getattr(func_obj, 'ChatIDTelegram', None) if func_obj else None
        if chat_id:
            ok = enviar_texto_telegram(
                chat_id,
                "🎉 <b>PARABÉNS! SEU EXAME ADMISSIONAL FOI APROVADO!</b> 🎉\n\n"
                "Seu acesso ao sistema de Gamificação está <b>TOTALMENTE LIBERADO</b>! "
                "Você já pode usar todos os comandos (Tarefas, Ranking, Saldo). Bom trabalho! 🚀")
            if not ok:
                aviso_telegram = "\n\n⚠️ Não foi possível avisar o funcionário pelo Telegram."
        else:
            aviso_telegram = "\n\n⚠️ Funcionário sem Telegram cadastrado: avise-o pessoalmente."

        self.carregar_onboarding_lista()
        messagebox.showinfo("Sucesso", "Admissional Aprovado! Acesso liberado no sistema." + aviso_telegram)

    def excluir_candidato_onboarding(self):
        """Exclui permanentemente o cadastro do candidato selecionado."""
        dados = self._linha_selecionada(self.tree_onboarding)
        if not dados:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista para excluir.")
            return

        funcionario_id = dados[0]
        nome = dados[1]

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
                # database.excluir_funcionario faz a limpeza em cascata e LEVANTA erro se falhar
                database.excluir_funcionario(funcionario_id)
                messagebox.showinfo("Sucesso", "Cadastro excluído com sucesso!", parent=self.root)
                self.carregar_onboarding_lista()
                self.carregar_rh_funcionarios()  # [DEPURAÇÃO] a aba Documentos também mostrava o excluído
            except Exception as e:
                logger.error(f"Erro ao excluir candidato {funcionario_id}: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao excluir cadastro:\n{e}", parent=self.root)

    def abrir_janela_documentos_onboarding(self):
        """Abre uma janela com botões para baixar os documentos enviados pelo Telegram."""
        dados = self._linha_selecionada(self.tree_onboarding)
        if not dados:
            messagebox.showwarning("Aviso", "Selecione um funcionário da lista.")
            return

        funcionario_id, nome_funcionario = dados[0], dados[1]
        file_ids = database.buscar_documentos_onboarding_para_download(funcionario_id) or {}

        popup = Toplevel(self.root)
        popup.title(f"Documentos de Admissão - {nome_funcionario}")
        popup.geometry("600x400")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Documentos Enviados (Clique para Download):", font=("Arial", 12)).pack(anchor='w', pady=(0, 10))

        if not file_ids:
            ttk.Label(frame, text="Nenhum documento finalizado (Workflow incompleto).", foreground="gray").pack()
            return

        for doc_name, file_id in file_ids.items():
            if file_id:
                ttk.Button(frame, text=f"📥 Baixar {doc_name}",
                           command=lambda fid=file_id, dn=doc_name: self.disparar_download_documento(fid, dn, popup)
                           ).pack(fill='x', pady=5)
            else:
                ttk.Label(frame, text=f"❌ {doc_name}: Não enviado ou File ID inválido.").pack(anchor='w', pady=2)

    def ver_dados_cadastrais_selecionado(self):
        """Exibe dados textuais E imagens dos documentos, com opção de gerar PDF."""
        dados = self._linha_selecionada(self.tree_onboarding)
        if not dados:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista.")  # [DEPURAÇÃO]
            return

        funcionario_id, nome = dados[0], dados[1]

        status = database.buscar_onboarding_status(funcionario_id)
        if not status:
            messagebox.showinfo("Aviso", "Sem dados de onboarding encontrados.", parent=self.root)
            return

        # --- 1. Janela com barra de rolagem ---
        popup = Toplevel(self.root)
        popup.title(f"Prontuário Digital - {nome}")
        popup.geometry("650x800")

        main_container = ttk.Frame(popup)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- 2. Dados ---
        cache_imagens = {}  # caminhos locais das imagens (usado pelo PDF)

        def acao_gerar_pdf():
            self.gerar_pdf_prontuario(nome, status, cache_imagens, parent=popup)

        frame_topo = ttk.Frame(scrollable_frame, padding="10")
        frame_topo.pack(fill="x")
        ttk.Button(frame_topo, text="🖨️ Gerar PDF Completo (Dados + Fotos)", command=acao_gerar_pdf).pack(fill="x", ipady=8)

        # --- 3. Texto ---
        tk.Label(scrollable_frame, text="DADOS CADASTRAIS", font=("Arial", 12, "bold"), bg="#e0e0e0",
                 anchor="w", padx=5).pack(fill="x", pady=(10, 5))

        estado_civil = getattr(status, 'EstadoCivil', None)
        texto_dados = f"Funcionário: {nome} (ID: {funcionario_id})\n"
        texto_dados += f"Escolaridade: {getattr(status, 'Escolaridade', None) or '---'}\n"
        texto_dados += f"Estado Civil: {estado_civil or '---'}\n"

        if estado_civil and 'CASADO' in str(estado_civil).upper():
            texto_dados += f"Data Casamento: {fmt_data(getattr(status, 'DataCasamento', None))}\n"
            texto_dados += f"Cônjuge: {getattr(status, 'NomeConjugue', None) or '---'}\n"
            texto_dados += f"CPF Cônjuge: {getattr(status, 'CPFConjugue', None) or '---'}\n"

        texto_dados += f"\nDEPENDENTES ({getattr(status, 'QtdFilhos', None) or 0}):\n"
        filhos = carregar_filhos(getattr(status, 'DadosFilhos', None))
        if filhos is None:
            texto_dados += "(Erro na leitura dos dependentes)"
        elif filhos:
            for f in filhos:
                texto_dados += f"- {f.get('Nome', '')} ({f.get('Nasc', '')}) CPF: {f.get('CPF', '') or '---'}\n"
        else:
            texto_dados += "- Nenhum dependente declarado."

        tk.Label(scrollable_frame, text=texto_dados, justify="left", font=("Consolas", 10), bg="white",
                 relief="solid", bd=1, padx=10, pady=10).pack(fill="x", padx=10)

        # --- 4. Imagens ---
        tk.Label(scrollable_frame, text="DOCUMENTOS DIGITALIZADOS", font=("Arial", 12, "bold"), bg="#e0e0e0",
                 anchor="w", padx=5).pack(fill="x", pady=(20, 5))

        docs_map = {
            "RG (Identidade)": getattr(status, 'RG_FileID', None),
            "CPF": getattr(status, 'CPF_FileID', None),
            "Carteira de Trabalho (CTPS)": getattr(status, 'CTPS_FileID', None),
            "Título de Eleitor": getattr(status, 'TituloEleitor_FileID', None),
        }

        temp_dir = os.path.join(os.getcwd(), "temp_view")
        os.makedirs(temp_dir, exist_ok=True)

        popup.config(cursor="watch")   # [DEPURAÇÃO] mostra "carregando" enquanto baixa as fotos
        popup.update_idletasks()
        try:
            for titulo, file_id in docs_map.items():
                frame_doc = ttk.LabelFrame(scrollable_frame, text=titulo, padding="5")
                frame_doc.pack(fill="x", padx=10, pady=5)

                if not file_id:
                    tk.Label(frame_doc, text="Pendente / Não enviado", fg="gray").pack()
                    continue

                caminho_local = self._baixar_imagem_cache(file_id, temp_dir)
                if not caminho_local:
                    tk.Label(frame_doc, text="Erro ao baixar arquivo do Telegram (veja o log).", fg="red").pack()
                    continue

                cache_imagens[titulo] = caminho_local
                try:
                    # [DEPURAÇÃO] "with" fecha o arquivo (no Windows o arquivo ficava travado);
                    # thumbnail mantém a proporção e nunca aumenta imagens pequenas.
                    with Image.open(caminho_local) as img_original:
                        pil_img = img_original.copy()
                    pil_img.thumbnail((400, 2000))
                    tk_img = ImageTk.PhotoImage(pil_img)
                    lbl_img = tk.Label(frame_doc, image=tk_img)
                    lbl_img.image = tk_img  # guarda referência para a imagem não sumir
                    lbl_img.pack()
                except Exception:
                    tk.Label(frame_doc, text="[Arquivo PDF ou formato sem prévia - use 'Ver Documentos Enviados']",
                             fg="blue").pack()
        finally:
            if self._janela_existe(popup):
                popup.config(cursor="")

    def _baixar_imagem_cache(self, file_id, pasta_destino):
        """Baixa arquivo do Telegram para cache local. Devolve o caminho ou None."""
        # [DEPURAÇÃO] antes: "except: return None" escondia qualquer erro e o log ficava vazio.
        try:
            # Cache: se já baixou antes (qualquer extensão), reaproveita
            nome_base = nome_arquivo_seguro(file_id)
            for ext in ('.jpg', '.jpeg', '.png', '.pdf', '.webp'):
                caminho = os.path.join(pasta_destino, nome_base + ext)
                if os.path.exists(caminho) and os.path.getsize(caminho) > 0:
                    return caminho

            file_path = buscar_arquivo_telegram(file_id)
            if not file_path:
                return None
            ext = os.path.splitext(file_path)[1].lower() or ".jpg"
            caminho_completo = os.path.join(pasta_destino, nome_base + ext)

            conteudo = baixar_bytes_telegram(file_path, timeout=30)
            if not conteudo:
                return None
            with open(caminho_completo, 'wb') as f:
                f.write(conteudo)
            return caminho_completo
        except OSError as e:
            logger.error(f"Erro ao salvar imagem em cache: {e}")
            return None

    def _preparar_imagem_para_pdf(self, caminho_img):
        """
        [DEPURAÇÃO] Converte a imagem para JPG comum (RGB) antes de pôr no PDF.
        PNG com transparência ou WEBP faziam o FPDF falhar.
        Devolve (caminho_jpg, largura_mm, altura_mm) ou None.
        """
        try:
            with Image.open(caminho_img) as img:
                img = img.convert('RGB')
                largura_px, altura_px = img.size
                destino = os.path.splitext(caminho_img)[0] + "_pdf.jpg"
                img.save(destino, 'JPEG', quality=85)
        except Exception as e:
            logger.warning(f"Imagem não pôde ser preparada para o PDF ({caminho_img}): {e}")
            return None
        if not largura_px or not altura_px:
            return None
        largura_mm = 170.0
        altura_mm = largura_mm * altura_px / largura_px
        if altura_mm > 230:  # não deixa passar do tamanho da página A4
            altura_mm = 230.0
            largura_mm = altura_mm * largura_px / altura_px
        return destino, largura_mm, altura_mm

    def gerar_pdf_prontuario(self, nome_funcionario, status, cache_imagens, parent=None):
        """Gera PDF com dados e imagens anexadas."""
        pai = self._pai_seguro(parent)
        try:
            dest = filedialog.asksaveasfilename(
                title="Salvar Prontuário PDF",
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
                initialfile=f"Prontuario_{nome_arquivo_seguro(str(nome_funcionario).replace(' ', '_'))}.pdf",
                parent=pai
            )
            if not dest:
                return

            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # [DEPURAÇÃO] "Helvetica" existe em TODAS as versões do FPDF (fpdf e fpdf2).
            # --- Cabeçalho ---
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, pdf_txt("Ficha de Registro de Colaborador"), ln=True, align="C")
            pdf.set_font("Helvetica", "I", 10)
            pdf.cell(0, 10, pdf_txt(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"), ln=True, align="C")
            pdf.ln(10)

            # --- Dados ---
            pdf.set_fill_color(240, 240, 240)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 10, pdf_txt("1. DADOS PESSOAIS"), ln=True, fill=True)
            pdf.ln(2)

            estado_civil = getattr(status, 'EstadoCivil', None)
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 8, pdf_txt(
                f"Nome: {pdf_txt(nome_funcionario)}\n"
                f"Escolaridade: {pdf_txt(getattr(status, 'Escolaridade', None))}\n"
                f"Estado Civil: {pdf_txt(estado_civil)}"))
            pdf.set_x(pdf.l_margin)  # [DEPURAÇÃO] no fpdf2 o cursor ficava na margem direita

            if estado_civil and 'CASADO' in str(estado_civil).upper():
                pdf.multi_cell(0, 8, pdf_txt(
                    f"Data Casamento: {fmt_data(getattr(status, 'DataCasamento', None))}\n"
                    f"Cônjuge: {pdf_txt(getattr(status, 'NomeConjugue', None))}\n"
                    f"CPF Cônjuge: {pdf_txt(getattr(status, 'CPFConjugue', None))}"))
                pdf.set_x(pdf.l_margin)

            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 10, pdf_txt(f"2. DEPENDENTES ({getattr(status, 'QtdFilhos', None) or 0})"), ln=True, fill=True)

            filhos = carregar_filhos(getattr(status, 'DadosFilhos', None))
            if filhos:
                pdf.set_font("Helvetica", "", 10)
                for i, f in enumerate(filhos, 1):
                    pdf.cell(0, 8, pdf_txt(f"{i}. {f.get('Nome', '')} - Nasc.: {f.get('Nasc', '') or '---'} "
                                           f"- CPF: {f.get('CPF', '') or '---'}"), ln=True)
            elif filhos is None:
                pdf.set_font("Helvetica", "I", 10)
                pdf.cell(0, 8, pdf_txt("(Erro na leitura dos dependentes)"), ln=True)
            else:
                pdf.set_font("Helvetica", "I", 10)
                pdf.cell(0, 8, pdf_txt("Nenhum dependente declarado."), ln=True)

            # --- Imagens ---
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 10, pdf_txt("3. DOCUMENTOS DIGITALIZADOS"), ln=True, fill=True)
            pdf.ln(5)

            if not cache_imagens:
                pdf.set_font("Helvetica", "I", 10)
                pdf.cell(0, 10, pdf_txt("Nenhum documento digitalizado disponível."), ln=True)

            for titulo, caminho_img in cache_imagens.items():
                if not caminho_img or not os.path.exists(caminho_img):
                    continue
                if caminho_img.lower().endswith('.pdf'):
                    pdf.set_font("Helvetica", "I", 10)
                    pdf.cell(0, 10, pdf_txt(f"{titulo}: arquivo PDF original (baixe pelo botão 'Ver Documentos Enviados')."), ln=True)
                    continue

                pdf.set_font("Helvetica", "B", 11)
                pdf.cell(0, 10, pdf_txt(titulo), ln=True)
                preparada = self._preparar_imagem_para_pdf(caminho_img)
                if preparada:
                    caminho_jpg, largura_mm, altura_mm = preparada
                    if pdf.get_y() + altura_mm > pdf.h - 15:   # não cabe -> nova página
                        pdf.add_page()
                    try:
                        pdf.image(caminho_jpg, x=pdf.l_margin, w=largura_mm, h=altura_mm)
                    except Exception as e:
                        logger.warning(f"Erro ao inserir imagem no PDF: {e}")
                        pdf.cell(0, 10, pdf_txt("[Erro ao renderizar imagem no PDF]"), ln=True)
                else:
                    pdf.cell(0, 10, pdf_txt("[Formato de imagem não suportado]"), ln=True)
                pdf.ln(10)

            pdf.output(dest)
            messagebox.showinfo("Sucesso", "Prontuário PDF gerado com sucesso!", parent=self._pai_seguro(parent))
            file_utils.abrir_arquivo(dest)

        except Exception as e:
            logger.error(f"Erro PDF: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Falha ao criar PDF: {e}", parent=self._pai_seguro(parent))

    def disparar_download_documento(self, file_id, doc_name, parent_popup):
        """Baixa o arquivo real do Telegram e salva onde o usuário escolher."""
        try:
            # [DEPURAÇÃO] Primeiro descobre o arquivo no Telegram, para saber a extensão certa
            # (antes sempre salvava como .jpg, mesmo quando o funcionário tinha mandado PDF).
            file_path_remoto = buscar_arquivo_telegram(file_id)
            if not file_path_remoto:
                messagebox.showerror("Erro API", "Arquivo não encontrado no Telegram (ou sem internet).\n"
                                     "Veja os detalhes no log.", parent=parent_popup)
                return
            ext = os.path.splitext(file_path_remoto)[1].lower() or ".jpg"

            caminho_destino = filedialog.asksaveasfilename(
                title=f"Salvar {doc_name}",
                defaultextension=ext,
                initialfile=f"{nome_arquivo_seguro(doc_name)}_{str(file_id)[:5]}{ext}",
                parent=parent_popup
            )
            if not caminho_destino:
                return  # Cancelado pelo usuário

            conteudo = baixar_bytes_telegram(file_path_remoto)
            if conteudo is None:
                messagebox.showerror("Erro Download", "Falha ao baixar o arquivo do Telegram.", parent=parent_popup)
                return

            with open(caminho_destino, 'wb') as f:
                f.write(conteudo)

            messagebox.showinfo("Sucesso", f"Download concluído!\nSalvo em: {caminho_destino}", parent=parent_popup)
            file_utils.abrir_arquivo(caminho_destino)

        except Exception as e:
            logger.error(f"Erro no download manual: {_sem_token(e)}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Falha no download: {_sem_token(e)}", parent=parent_popup)

    # ------------------------------------------------------------------
    # DOCUMENTOS PESSOAIS (conversa com o api_server.py)
    # ------------------------------------------------------------------
    def visualizar_documento_selecionado(self):
        """Baixa o documento selecionado da API e o abre."""
        dados_doc = self._linha_selecionada(self.tree_rh_documentos)
        if not dados_doc:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista da direita.")
            return
        documento_id = dados_doc[0]

        url_download = f"{config.API_BASE_URL}/documentos/download/{documento_id}"

        try:
            logger.info(f"Solicitando download do documento ID {documento_id}...")
            # [DEPURAÇÃO] timeout: antes, se a API estivesse fora do ar, a janela congelava para sempre.
            with requests.get(url_download, stream=True, timeout=TIMEOUT_API, headers=headers_api()) as response:
                if response.status_code != 200:
                    messagebox.showerror("Erro da API", f"Não foi possível baixar o arquivo:\n{mensagem_erro_api(response)}")
                    return

                # [DEPURAÇÃO] sem o módulo 'cgi' (removido no Python 3.13) e sem 'urllib' não importado
                nome_remoto = nome_arquivo_do_header(response.headers.get("Content-Disposition"))

                if not nome_remoto:
                    content_type = response.headers.get("Content-Type", "")
                    ext = ".pdf"
                    if "image/jpeg" in content_type:
                        ext = ".jpg"
                    elif "image/png" in content_type:
                        ext = ".png"
                    safe_tipo = "".join(x for x in str(dados_doc[1]) if x.isalnum()) or "Documento"
                    nome_remoto = f"{safe_tipo}_{documento_id}{ext}"

                pasta_downloads = os.path.join(os.getcwd(), "downloads")
                os.makedirs(pasta_downloads, exist_ok=True)

                caminho_local = os.path.join(pasta_downloads, nome_remoto)
                with open(caminho_local, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            logger.info(f"Download concluído! Arquivo salvo em: {caminho_local}")
            file_utils.abrir_arquivo(caminho_local)

        except requests.exceptions.Timeout:
            messagebox.showerror("Erro de Conexão", "A API demorou demais para responder. Ela está ligada?")
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Erro de Conexão",
                                 f"Não foi possível conectar à API para baixar o arquivo.\n"
                                 f"Verifique se o api_server.py está rodando.\n\nDetalhe: {e}")
        except OSError as e:
            messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar o arquivo na pasta 'downloads':\n{e}")

    def carregar_rh_funcionarios(self):
        for i in self.tree_rh_funcionarios.get_children():
            self.tree_rh_funcionarios.delete(i)
        for i in self.tree_rh_documentos.get_children():   # [DEPURAÇÃO] limpa docs do funcionário antigo
            self.tree_rh_documentos.delete(i)
        funcionarios = database.listar_funcionarios() or []
        for func in funcionarios:
            self.tree_rh_funcionarios.insert("", "end", values=(func.FuncionarioID, func.NomeCompleto))

    def on_rh_funcionario_selecionado(self, event):
        """Chamada quando um funcionário é selecionado. Carrega seus documentos e status de ciência."""
        for i in self.tree_rh_documentos.get_children():
            self.tree_rh_documentos.delete(i)

        dados_func = self._linha_selecionada(self.tree_rh_funcionarios)
        if not dados_func:
            return
        funcionario_id = dados_func[0]

        documentos = database.listar_documentos_por_funcionario(funcionario_id) or []
        for doc in documentos:
            # [DEPURAÇÃO] datas vazias ou em texto não travam mais a lista
            self.tree_rh_documentos.insert("", "end", values=(
                doc.DocumentoID, doc.TipoDocumento,
                fmt_data(doc.MesAno, "%m/%Y"),
                fmt_data(doc.DataUpload, "%d/%m/%Y %H:%M"),
                doc.Status or "N/A",
                fmt_data(doc.DataCiencia, "%d/%m/%Y %H:%M"),
            ))

    def excluir_documento_selecionado(self):
        """Chama a API para excluir o documento selecionado (banco + arquivo)."""
        dados_doc = self._linha_selecionada(self.tree_rh_documentos)
        if not dados_doc:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista para excluir.")
            return

        documento_id, tipo_doc, mes_ano_ref = dados_doc[0], dados_doc[1], dados_doc[2]

        confirmado = messagebox.askyesno(
            "Confirmar Exclusão",
            f"Tem certeza que deseja excluir o documento:\n\nTipo: {tipo_doc}\nReferência: {mes_ano_ref}\n\n"
            f"Esta ação removerá o registro do banco e o arquivo físico no servidor. NÃO PODE SER DESFEITA.",
            icon='warning'
        )
        if not confirmado:
            return

        try:
            url = f"{config.API_BASE_URL}/documentos/excluir/{documento_id}"
            response = requests.delete(url, timeout=TIMEOUT_API, headers=headers_api())

            if response.status_code == 200:
                messagebox.showinfo("Sucesso", "Documento excluído com sucesso!")
                self.on_rh_funcionario_selecionado(None)
            else:
                # [DEPURAÇÃO] antes: response.json() travava se a API devolvesse HTML (erro 500)
                messagebox.showerror("Erro da API", f"Falha ao excluir:\n{mensagem_erro_api(response)}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de conexão ao excluir documento: {e}", exc_info=True)
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar ao servidor: {e}")

    def _buscar_nivel_acesso(self, funcionario_id):
        """Busca o NivelAcesso de um funcionário pelo ID. Padrão seguro: 'Funcionario'."""
        try:
            funcionario = database.buscar_funcionario_por_id(funcionario_id)
        except Exception as e:
            logger.error(f"Falha ao buscar NivelAcesso para ID {funcionario_id}: {e}")
            return 'Funcionario'
        if not funcionario:
            logger.warning(f"Usuário ID {funcionario_id} não encontrado (ou banco fora do ar).")
            return 'Funcionario'
        return (getattr(funcionario, 'NivelAcesso', None) or 'Funcionario').strip()

    def abrir_janela_edicao_documento(self):
        """Abre a janela para editar os metadados do documento selecionado."""
        dados_doc = self._linha_selecionada(self.tree_rh_documentos)
        if not dados_doc:
            messagebox.showwarning("Aviso", "Por favor, selecione um documento na lista para editar.")
            return

        documento_id = dados_doc[0]
        tipo_atual = dados_doc[1]
        mes_ano_ref_atual = dados_doc[2]  # formato mm/aaaa

        try:
            data_ref_obj = datetime.strptime(f"01/{mes_ano_ref_atual}", "%d/%m/%Y").date()
        except ValueError:
            data_ref_obj = datetime.now().date()

        popup = Toplevel(self.root)
        popup.title(f"Editar Documento ID: {documento_id}")
        popup.geometry("350x250")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Tipo de Documento:").grid(row=0, column=0, sticky="w", pady=5)
        combo_tipo = ttk.Combobox(frame, values=TIPOS_DOCUMENTO)
        combo_tipo.grid(row=0, column=1, sticky="ew", pady=5)
        combo_tipo.set(tipo_atual)

        ttk.Label(frame, text="Mês/Ano de Referência:").grid(row=1, column=0, sticky="w", pady=5)
        entry_data_ref = DateEntry(frame, date_pattern='dd/mm/yyyy', width=18)
        entry_data_ref.grid(row=1, column=1, sticky="w", pady=5)
        entry_data_ref.set_date(data_ref_obj)

        # [DEPURAÇÃO] o texto dizia "Arquivo atual:" mas mostrava a DATA de upload
        ttk.Label(frame, text=f"Enviado em: {str(dados_doc[3]).split(' ')[0]}").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 5))
        ttk.Label(frame, text="*Não é possível alterar o arquivo físico.", font=("Arial", 8, "italic")).grid(row=3, column=0, columnspan=2, sticky="w")

        def salvar_edicao():
            novo_tipo = combo_tipo.get().strip()
            if not novo_tipo:
                messagebox.showerror("Erro", "O Tipo de Documento é obrigatório.", parent=popup)
                return
            try:
                nova_data_ref_db = entry_data_ref.get_date().replace(day=1).strftime('%Y-%m-%d')
            except Exception:
                messagebox.showerror("Erro", "Data de referência inválida.", parent=popup)
                return

            try:
                sucesso = database.atualizar_documento_pessoal_metadados(documento_id, novo_tipo, nova_data_ref_db)
                if sucesso:
                    messagebox.showinfo("Sucesso", "Metadados do documento atualizados!", parent=popup)
                    popup.destroy()
                    self.on_rh_funcionario_selecionado(None)
                else:
                    messagebox.showwarning("Aviso", "Nenhuma alteração detectada ou falha na atualização.", parent=popup)
            except Exception as e:
                messagebox.showerror("Erro", f"Ocorreu um erro ao salvar: {e}", parent=popup)

        ttk.Button(frame, text="Salvar Metadados", command=salvar_edicao).grid(row=4, column=0, columnspan=2, pady=20, ipady=5)
        frame.columnconfigure(1, weight=1)

    def abrir_janela_add_documento(self):
        """Abre a janela para adicionar um novo documento pessoal."""
        dados_func = self._linha_selecionada(self.tree_rh_funcionarios)
        if not dados_func:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário na lista da esquerda primeiro.")
            return

        funcionario_id, nome_funcionario = dados_func[0], dados_func[1]

        popup = Toplevel(self.root)
        popup.title(f"Adicionar Documento para {nome_funcionario}")
        popup.geometry("450x300")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Tipo de Documento:").grid(row=0, column=0, sticky="w", pady=5)
        combo_tipo = ttk.Combobox(frame, values=TIPOS_DOCUMENTO)
        combo_tipo.grid(row=0, column=1, sticky="ew", pady=5)
        combo_tipo.set('Holerite')

        ttk.Label(frame, text="Mês/Ano de Referência:").grid(row=1, column=0, sticky="w", pady=5)
        entry_data_ref = DateEntry(frame, date_pattern='dd/mm/yyyy', width=18)
        entry_data_ref.grid(row=1, column=1, sticky="w", pady=5)

        ttk.Label(frame, text="Arquivo (PDF, JPG, PNG):").grid(row=2, column=0, sticky="w", pady=5)
        frame_arquivo = ttk.Frame(frame)
        frame_arquivo.grid(row=2, column=1, sticky="ew", pady=5)

        lbl_caminho_pdf = ttk.Label(frame_arquivo, text="Nenhum arquivo selecionado.")
        lbl_caminho_pdf.pack(side="right", fill="x", expand=True)

        caminho_arquivo_selecionado = {"path": ""}

        def selecionar_arquivo():
            filepath = filedialog.askopenfilename(
                title="Selecione o documento (PDF, JPG ou PNG)",
                filetypes=[
                    ("Documentos Suportados", "*.pdf *.jpg *.jpeg *.png"),
                    ("Arquivos PDF", "*.pdf"),
                    ("Imagens JPG", "*.jpg *.jpeg"),
                    ("Imagens PNG", "*.png")
                ],
                parent=popup
            )
            if filepath:
                caminho_arquivo_selecionado["path"] = filepath
                lbl_caminho_pdf.config(text=os.path.basename(filepath))

        ttk.Button(frame_arquivo, text="Selecionar...", command=selecionar_arquivo).pack(side="left")

        def enviar_documento():
            tipo = combo_tipo.get().strip()
            caminho_arquivo = caminho_arquivo_selecionado["path"]
            try:
                data_ref = entry_data_ref.get_date()
            except Exception:
                data_ref = None

            if not all([tipo, data_ref, caminho_arquivo]):
                messagebox.showerror("Erro", "Todos os campos são obrigatórios.", parent=popup)
                return
            if not os.path.isfile(caminho_arquivo):
                messagebox.showerror("Erro", "O arquivo escolhido não existe mais. Selecione de novo.", parent=popup)
                return

            nome_arquivo = os.path.basename(caminho_arquivo)
            extensao = os.path.splitext(nome_arquivo)[1].lower()
            tipos_mime = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
            mime_type = tipos_mime.get(extensao)
            if not mime_type:
                messagebox.showerror("Erro", "Tipo de arquivo não suportado. Use PDF, JPG ou PNG.", parent=popup)
                return

            url_upload = f"{config.API_BASE_URL}/documentos/upload"
            dados_payload = {
                'funcionario_id': funcionario_id,
                'tipo_documento': tipo,
                'mes_ano': data_ref.replace(day=1).strftime('%Y-%m-%d'),
            }

            btn_salvar.config(state="disabled")  # [DEPURAÇÃO] evita enviar 2x com duplo clique
            try:
                with open(caminho_arquivo, 'rb') as f:
                    arquivos_payload = {'file': (nome_arquivo, f, mime_type)}
                    response = requests.post(url_upload, data=dados_payload, files=arquivos_payload,
                                             timeout=TIMEOUT_UPLOAD, headers=headers_api())

                if response.status_code == 201:
                    try:
                        resposta = response.json()
                    except ValueError:
                        resposta = {}
                    # [DEPURAÇÃO] a API avisa (status 'alerta') quando salvou mas não conseguiu avisar o funcionário
                    if resposta.get('status') == 'alerta':
                        messagebox.showwarning("Enviado com alerta", resposta.get('mensagem', ''), parent=popup)
                    else:
                        messagebox.showinfo("Sucesso", "Documento enviado com sucesso!", parent=popup)
                    popup.destroy()
                    self.on_rh_funcionario_selecionado(None)
                    return
                messagebox.showerror("Erro da API", f"Falha no upload:\n{mensagem_erro_api(response)}", parent=popup)
            except requests.exceptions.RequestException as e:
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à API: {e}", parent=popup)
            except OSError as e:
                messagebox.showerror("Erro", f"Não foi possível ler o arquivo: {e}", parent=popup)
            if self._janela_existe(popup):
                btn_salvar.config(state="normal")

        btn_salvar = ttk.Button(frame, text="Salvar e Disponibilizar", command=enviar_documento)
        btn_salvar.grid(row=3, column=0, columnspan=2, pady=20, ipady=5)
        frame.columnconfigure(1, weight=1)

    def solicitar_onboarding_funcionario(self):
        """Dispara a notificação para o funcionário iniciar o processo de onboarding."""
        dados_func = self._linha_selecionada(self.tree_rh_funcionarios)
        if not dados_func:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário na lista da esquerda primeiro.")
            return

        funcionario_id, nome_funcionario = dados_func[0], dados_func[1]

        # [DEPURAÇÃO] 1º confere o Telegram. Antes o status virava 'Pendente' (bloqueando o
        # funcionário no bot) e SÓ DEPOIS descobria que não dava para avisá-lo.
        func_obj = database.buscar_funcionario_por_id(funcionario_id)
        chat_id = getattr(func_obj, 'ChatIDTelegram', None) if func_obj else None
        if not chat_id:
            messagebox.showwarning("Aviso", "Funcionário sem ChatID Telegram cadastrado. Não é possível notificar.\n\n"
                                            "Peça para ele iniciar uma conversa com o bot primeiro.")
            return

        # [DEPURAÇÃO] confirmação: isso bloqueia o acesso dele ao bot até enviar os documentos
        if not messagebox.askyesno(
                "Confirmar",
                f"Solicitar documentos de admissão para {nome_funcionario}?\n\n"
                "O acesso dele ao bot ficará BLOQUEADO até concluir o envio dos documentos."):
            return

        if not database.iniciar_onboarding_funcionario(funcionario_id):
            messagebox.showerror("Erro", "Falha ao registrar o status de onboarding no banco.")
            return

        mensagem = (f"🎉 <b>Bem-vindo(a) à Gela Boca, {esc(nome_funcionario)}!</b> 🎉\n\n"
                    "Para dar início ao seu registro, precisamos que você nos envie seus documentos e dados pessoais. "
                    "Seu acesso ao sistema será bloqueado até que o processo seja concluído.\n\n"
                    "Por favor, digite <b>Começar</b> (ou qualquer mensagem) para iniciar o envio de documentos.")

        if enviar_texto_telegram(chat_id, mensagem):
            messagebox.showinfo("Sucesso", f"Notificação de Onboarding enviada para {nome_funcionario}!")
        else:
            messagebox.showwarning("Atenção", "O onboarding foi registrado, mas o Telegram NÃO confirmou o envio.\n"
                                              "Avise o funcionário pessoalmente (veja o log para detalhes).")

    # ------------------------------------------------------------------
    # COMUNICADOS
    # ------------------------------------------------------------------
    def atualizar_lista_comunicados(self, filtro=None):
        for i in self.tree_comunicados.get_children():
            self.tree_comunicados.delete(i)
        comunicados = database.listar_comunicados_com_status(filtro_titulo=filtro) or []
        for doc in comunicados:
            # [DEPURAÇÃO] comunicado sem destinatários mostrava "None / 0 Cientes"
            status = f"{doc.TotalCientes or 0} / {doc.TotalEnviado or 0} Cientes"
            self.tree_comunicados.insert("", "end", values=(
                doc.DocumentoID, doc.Titulo, fmt_data(doc.DataCriacao, "%d/%m/%Y %H:%M"), status))

    def abrir_janela_criacao(self):
        if self._janela_existe(self.popup_criacao):
            self.popup_criacao.focus()
            return
        self.caminho_imagem_selecionada = None  # limpa imagem de envios anteriores

        self.popup_criacao = Toplevel(self.root)
        self.popup_criacao.title("Novo Comunicado")
        self.popup_criacao.geometry("800x600")
        self.popup_criacao.transient(self.root)
        Label(self.popup_criacao, text="Título:", font=("Arial", 10, "bold")).pack(padx=10, pady=(10, 0), anchor='w')
        entry_titulo = Entry(self.popup_criacao, font=("Arial", 10))
        entry_titulo.pack(padx=10, fill='x')
        Label(self.popup_criacao, text="Conteúdo:", font=("Arial", 10, "bold")).pack(padx=10, pady=(10, 0), anchor='w')
        text_conteudo = Text(self.popup_criacao, height=10, font=("Arial", 10))
        text_conteudo.pack(padx=10, fill='both', expand=True)
        frame_pontos = Frame(self.popup_criacao)
        frame_pontos.pack(padx=10, pady=5, fill='x')
        var_premiar = tk.BooleanVar()
        Checkbutton(frame_pontos, text="Premiar com pontos pela ciência?", variable=var_premiar).pack(side="left")
        entry_pontos = Entry(frame_pontos, width=5)
        entry_pontos.pack(side="left", padx=5)
        entry_pontos.insert(0, "10")
        frame_imagem = Frame(self.popup_criacao)
        frame_imagem.pack(padx=10, pady=5, fill='x')
        Button(frame_imagem, text="Anexar Imagem...", command=lambda: self.selecionar_imagem(lbl_caminho_imagem)).pack(side="left")
        lbl_caminho_imagem = Label(frame_imagem, text="Nenhuma imagem selecionada.", font=("Arial", 9, "italic"))
        lbl_caminho_imagem.pack(side="left", padx=10)
        Label(self.popup_criacao, text="Enviar para (Ctrl/Shift para vários):", font=("Arial", 10, "bold")).pack(padx=10, pady=(10, 0), anchor='w')
        frame_funcionarios = Frame(self.popup_criacao)
        frame_funcionarios.pack(padx=10, pady=5, fill='both', expand=True)
        listbox_funcionarios = Listbox(frame_funcionarios, selectmode=tk.EXTENDED)
        scrollbar_func = Scrollbar(frame_funcionarios, orient="vertical", command=listbox_funcionarios.yview)
        listbox_funcionarios.configure(yscrollcommand=scrollbar_func.set)
        listbox_funcionarios.pack(side="left", fill="both", expand=True)
        scrollbar_func.pack(side="left", fill="y")
        self.dados_funcionarios.clear()
        for func in database.listar_funcionarios() or []:
            display_text = f"{func.NomeCompleto} (ID: {func.FuncionarioID})"
            listbox_funcionarios.insert(tk.END, display_text)
            self.dados_funcionarios[display_text] = func
        Button(self.popup_criacao, text="Selecionar Todos",
               command=lambda: listbox_funcionarios.select_set(0, tk.END)).pack(padx=10, anchor='w')
        # [DEPURAÇÃO] guardamos o botão numa variável (antes era "adivinhado" pela ordem dos widgets,
        # e o botão "Selecionar Todos" acima teria quebrado essa adivinhação)
        self.btn_enviar_comunicado = Button(
            self.popup_criacao, text="ENVIAR COMUNICADO", bg="green", fg="white", font=("Arial", 12, "bold"),
            command=lambda: self.enviar_comunicado(
                entry_titulo.get(), text_conteudo.get("1.0", tk.END),
                var_premiar.get(), entry_pontos.get(),
                listbox_funcionarios.curselection(), listbox_funcionarios
            ))
        self.btn_enviar_comunicado.pack(pady=10, padx=10, fill='x', ipady=5)

    def enviar_comunicado(self, titulo, conteudo, premiar, pontos_str, indices_selecionados, listbox):
        titulo = (titulo or '').strip()
        conteudo = (conteudo or '').strip()
        if not titulo or not conteudo:
            messagebox.showerror("Erro", "Título e Conteúdo são obrigatórios.", parent=self.popup_criacao)
            return
        if not indices_selecionados:
            messagebox.showerror("Erro", "Selecione pelo menos um funcionário.", parent=self.popup_criacao)
            return

        pontos = 0
        if premiar:
            try:
                pontos = int(str(pontos_str).strip())
                if pontos <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Erro", "A pontuação deve ser um número inteiro positivo.", parent=self.popup_criacao)
                return

        destinatarios = [self.dados_funcionarios[listbox.get(i)] for i in indices_selecionados
                         if listbox.get(i) in self.dados_funcionarios]
        dados_envio = {
            'titulo': titulo,
            'conteudo': conteudo,
            'pontos': pontos,
            'destinatarios': destinatarios,
            'caminho_imagem': self.caminho_imagem_selecionada,
        }

        if self.btn_enviar_comunicado is not None:
            self.btn_enviar_comunicado.config(state="disabled", text="Enviando... Aguarde")

        # [DEPURAÇÃO] A thread de envio NÃO mexe na janela (Tkinter não é seguro entre threads).
        # Ela coloca o resultado numa fila, e a janela confere a fila a cada 200 ms.
        self._fila_envio = queue.Queue()

        def tarefa_envio_background(fila=self._fila_envio):
            try:
                fila.put(('fim', self._executar_envio_comunicado(dados_envio, fila)))
            except Exception as e:
                logger.error(f"Erro inesperado no envio do comunicado: {e}", exc_info=True)
                # [DEPURAÇÃO] antes: lambda usando "e" depois do except -> NameError, e o erro
                # real nunca aparecia (o Python apaga a variável "e" ao sair do except).
                fila.put(('erro', str(e)))

        threading.Thread(target=tarefa_envio_background, daemon=True).start()
        self.root.after(200, self._verificar_fila_envio)

    def _executar_envio_comunicado(self, dados, fila=None):
        """
        Faz o trabalho pesado (banco + Telegram). Roda FORA da janela (thread).
        Devolve um resumo com o que aconteceu.
        """
        titulo, conteudo = dados['titulo'], dados['conteudo']
        destinatarios = dados['destinatarios']
        resumo = {'ok': False, 'erro': None, 'enviados': 0, 'total': len(destinatarios),
                  'sem_telegram': [], 'falhas': [], 'imagem': None}

        documento_id = database.criar_documento(titulo, conteudo, self.USUARIO_LOGADO_ID, dados['pontos'])
        if not documento_id:
            resumo['erro'] = "Não foi possível criar o registro do comunicado no banco de dados."
            return resumo
        resumo['ok'] = True
        resumo['documento_id'] = documento_id

        partes = montar_partes_comunicado(titulo, conteudo)
        legenda = f"🚨 <b>NOVO COMUNICADO</b> 🚨\n\n<b>Título:</b> {esc(titulo[:LIMITE_LEGENDA_TELEGRAM - 100])}"

        # --- Imagem: tenta obter um file_id enviando ao grupo de gestores ---
        foto = None
        caminho_imagem = dados.get('caminho_imagem')
        if caminho_imagem:
            grupo = getattr(config, 'GESTOR_GROUP_CHAT_ID', None)
            file_id = enviar_foto_telegram(grupo, caminho_imagem, f"(Log de Envio: {esc(titulo[:200])})") if grupo else None
            if file_id:
                database.atualizar_documento_com_file_id(documento_id, file_id)
                foto = file_id
                resumo['imagem'] = True
            else:
                # [DEPURAÇÃO] Fallback de verdade: envia o arquivo direto ao 1º funcionário
                # e reaproveita o file_id nos próximos.
                logger.warning("Grupo de gestores não aceitou a imagem; enviando o arquivo direto aos funcionários.")
                foto = caminho_imagem
                resumo['imagem'] = False

        for posicao, func in enumerate(destinatarios, 1):
            if fila is not None:
                fila.put(('progresso', f"Enviando {posicao}/{len(destinatarios)}..."))
            nome = getattr(func, 'NomeCompleto', '?')
            chat_id = getattr(func, 'ChatIDTelegram', None)

            assinatura_id = database.registrar_pendencia_assinatura(documento_id, func.FuncionarioID)
            if not assinatura_id:
                logger.warning(f"Falha ao registrar pendência para {nome}")
                resumo['falhas'].append(nome)
                continue

            if not chat_id:
                # A pendência fica registrada: o aviso aparece quando ele entrar no bot
                resumo['sem_telegram'].append(nome)
                continue

            ok, file_id_enviado = enviar_comunicado_para_funcionario(chat_id, assinatura_id, partes, foto, legenda)
            if file_id_enviado and isinstance(foto, str) and os.path.isfile(foto):
                # enviou o arquivo do PC uma vez -> daqui pra frente usa o file_id (mais rápido)
                foto = file_id_enviado
                database.atualizar_documento_com_file_id(documento_id, file_id_enviado)
            if ok:
                resumo['enviados'] += 1
            else:
                resumo['falhas'].append(nome)
            time.sleep(0.1)

        return resumo

    def _verificar_fila_envio(self):
        """Roda na janela: lê as mensagens da thread de envio."""
        fila = self._fila_envio
        if fila is None:
            return
        try:
            while True:
                tipo, conteudo = fila.get_nowait()
                if tipo == 'progresso':
                    if self._janela_existe(self.popup_criacao) and self.btn_enviar_comunicado is not None:
                        self.btn_enviar_comunicado.config(text=conteudo)
                elif tipo == 'fim':
                    self._fila_envio = None
                    self._finalizar_envio_comunicado(conteudo)
                    return
                elif tipo == 'erro':
                    self._fila_envio = None
                    self._finalizar_envio_comunicado({'ok': False, 'erro': conteudo})
                    return
        except queue.Empty:
            pass
        self.root.after(200, self._verificar_fila_envio)

    def _finalizar_envio_comunicado(self, resumo):
        """Mostra o resultado do envio e fecha/reativa a janela de criação."""
        pai = self._pai_seguro(self.popup_criacao)
        if not resumo.get('ok'):
            messagebox.showerror("Erro", f"O envio foi interrompido:\n{resumo.get('erro')}", parent=pai)
            if self._janela_existe(self.popup_criacao) and self.btn_enviar_comunicado is not None:
                self.btn_enviar_comunicado.config(state="normal", text="ENVIAR COMUNICADO")
            self.atualizar_lista_comunicados()
            return

        texto = f"{resumo['enviados']} de {resumo['total']} comunicados foram entregues pelo Telegram."
        if resumo.get('sem_telegram'):
            texto += ("\n\nSem Telegram cadastrado (a pendência ficou registrada):\n - "
                      + "\n - ".join(resumo['sem_telegram']))
        if resumo.get('falhas'):
            texto += "\n\nFalharam (veja o log):\n - " + "\n - ".join(resumo['falhas'])
        if resumo.get('imagem') is False:
            texto += "\n\n⚠️ O grupo de gestores não aceitou a imagem; ela foi enviada direto aos funcionários."

        if resumo.get('falhas') or resumo.get('sem_telegram'):
            messagebox.showwarning("Envio concluído com avisos", texto, parent=pai)
        else:
            messagebox.showinfo("Sucesso", texto, parent=pai)

        self.caminho_imagem_selecionada = None
        if self._janela_existe(self.popup_criacao):
            self.popup_criacao.destroy()
        self.popup_criacao = None
        self.atualizar_lista_comunicados()

    def abrir_janela_detalhes(self):
        dados_comunicado = self._linha_selecionada(self.tree_comunicados)
        if not dados_comunicado:
            messagebox.showwarning("Aviso", "Por favor, selecione um comunicado na lista para ver os detalhes.")
            return
        documento_id = dados_comunicado[0]
        detalhes_doc = database.buscar_detalhes_completos_documento(documento_id)
        if not detalhes_doc:
            messagebox.showerror("Erro", "Não foi possível encontrar os detalhes deste comunicado.")
            return
        popup_detalhes = Toplevel(self.root)
        popup_detalhes.title(f"Detalhes: {detalhes_doc.Titulo}")
        popup_detalhes.geometry("700x550")
        popup_detalhes.transient(self.root)
        frame_conteudo = ttk.LabelFrame(popup_detalhes, text="Conteúdo do Comunicado", padding="10")
        frame_conteudo.pack(padx=10, pady=10, fill="x")
        text_widget = Text(frame_conteudo, height=8, wrap="word", font=("Arial", 10))
        text_widget.insert("1.0", detalhes_doc.Conteudo or '')
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
        for dest in database.listar_destinatarios_de_documento(documento_id) or []:
            tree_detalhes.insert("", "end", values=(
                dest.AssinaturaID, dest.NomeCompleto, dest.StatusAssinatura,
                fmt_data(dest.DataCiencia, "%d/%m/%Y %H:%M:%S")))
        ttk.Button(popup_detalhes, text="Gerar Recibo PDF para Selecionado",
                   command=lambda: self.gerar_recibo_para_selecionado(tree_detalhes, popup_detalhes)
                   ).pack(pady=(5, 10), side="left", padx=10)
        ttk.Button(popup_detalhes, text="Adicionar Funcionário(s)",
                   command=lambda: self.abrir_janela_adicionar_funcionario(documento_id, popup_detalhes)
                   ).pack(pady=(5, 10), side="left", padx=10)

    def excluir_comunicado_selecionado(self):
        dados_comunicado = self._linha_selecionada(self.tree_comunicados)
        if not dados_comunicado:
            messagebox.showwarning("Aviso", "Por favor, selecione um comunicado na lista para excluir.")
            return
        documento_id, titulo_comunicado = dados_comunicado[0], dados_comunicado[1]
        confirmado = messagebox.askyesno(
            "Confirmar Exclusão",
            f"Tem certeza que deseja excluir permanentemente o comunicado:\n\n'{titulo_comunicado}'\n\n"
            "Esta ação não pode ser desfeita.", icon='warning')
        if not confirmado:
            return
        database.excluir_documento(documento_id)
        # [DEPURAÇÃO] database.excluir_documento não avisa se falhou; antes a tela dizia
        # "Sucesso" mesmo com erro. Agora conferimos se o comunicado sumiu mesmo.
        if database.buscar_detalhes_completos_documento(documento_id):
            messagebox.showerror("Erro", "Não foi possível excluir o comunicado (veja o log).")
        else:
            messagebox.showinfo("Sucesso", "O comunicado foi excluído com sucesso.")
        self.atualizar_lista_comunicados()

    def gerar_recibo_para_selecionado(self, tree_detalhes, popup_pai):
        dados_assinatura = self._linha_selecionada(tree_detalhes)
        if not dados_assinatura:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista para gerar o recibo.", parent=popup_pai)
            return
        assinatura_id, status = dados_assinatura[0], dados_assinatura[2]
        if status != 'Ciente':
            messagebox.showerror("Erro", "Só é possível gerar recibos para funcionários que já confirmaram a ciência.", parent=popup_pai)
            return
        try:
            dados_recibo = database.buscar_dados_completos_para_recibo(assinatura_id)
            if not dados_recibo:
                messagebox.showerror("Erro de Dados", "Não foi possível encontrar os dados completos para gerar este recibo.", parent=popup_pai)
                return
            # [DEPURAÇÃO] pdf_txt: emojis no comunicado faziam o recibo falhar
            path_do_pdf = recibo_generator.gerar_recibo_pdf(
                assinatura_id=assinatura_id, nome_funcionario=pdf_txt(dados_recibo.NomeCompleto),
                titulo_doc=pdf_txt(dados_recibo.Titulo), conteudo_doc=pdf_txt(dados_recibo.Conteudo, vazio=''),
                data_ciencia=dados_recibo.DataCiencia
            )
            file_utils.abrir_arquivo(path_do_pdf)
            messagebox.showinfo("Sucesso", f"Recibo em PDF gerado e aberto com sucesso!\n\nSalvo em: {os.path.abspath(path_do_pdf)}", parent=popup_pai)
        except Exception as e:
            logger.error(f"Erro ao gerar recibo {assinatura_id}: {e}", exc_info=True)
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao gerar o PDF: {e}", parent=popup_pai)

    def abrir_janela_adicionar_funcionario(self, documento_id, popup_pai):
        funcionarios_disponiveis = database.listar_funcionarios_nao_destinatarios(documento_id) or []
        if not funcionarios_disponiveis:
            # [DEPURAÇÃO] antes abria a janela vazia e fechava logo em seguida
            messagebox.showinfo("Informação", "Todos os funcionários já receberam este comunicado.", parent=popup_pai)
            return
        popup_adicionar = Toplevel(popup_pai)
        popup_adicionar.title("Adicionar Destinatários")
        popup_adicionar.geometry("400x500")
        popup_adicionar.transient(popup_pai)
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
        Button(popup_adicionar, text="Confirmar e Enviar Notificação", bg="green", fg="white",
               command=lambda: self.confirmar_e_enviar_para_novos(
                   documento_id, listbox_novos, dados_disponiveis, popup_adicionar)
               ).pack(pady=10, padx=10, fill='x', ipady=5)

    def confirmar_e_enviar_para_novos(self, documento_id, listbox, dados_funcionarios, popup):
        indices_selecionados = listbox.curselection()
        if not indices_selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos um funcionário.", parent=popup)
            return
        detalhes_doc = database.buscar_detalhes_completos_documento(documento_id)
        if not detalhes_doc:
            messagebox.showerror("Erro Crítico", "Não foi possível encontrar os dados do comunicado original.", parent=popup)
            return

        partes = montar_partes_comunicado(detalhes_doc.Titulo, detalhes_doc.Conteudo, importante=True)
        enviados, sem_telegram, falhas = 0, [], []
        popup.config(cursor="watch")
        popup.update_idletasks()
        for i in indices_selecionados:
            funcionario = dados_funcionarios.get(listbox.get(i))
            if funcionario is None:
                continue
            assinatura_id = database.registrar_pendencia_assinatura(documento_id, funcionario.FuncionarioID)
            if not assinatura_id:
                falhas.append(funcionario.NomeCompleto)
                continue
            chat_id = getattr(funcionario, 'ChatIDTelegram', None)
            if not chat_id:
                sem_telegram.append(funcionario.NomeCompleto)
                continue
            # [DEPURAÇÃO] HTML + confere se o Telegram aceitou (antes contava sucesso sempre)
            ok, _ = enviar_comunicado_para_funcionario(chat_id, assinatura_id, partes)
            if ok:
                enviados += 1
            else:
                falhas.append(funcionario.NomeCompleto)
            time.sleep(0.1)
        if self._janela_existe(popup):
            popup.config(cursor="")

        texto = f"{enviados} funcionário(s) foram notificados com sucesso!"
        if sem_telegram:
            texto += "\n\nSem Telegram (pendência registrada):\n - " + "\n - ".join(sem_telegram)
        if falhas:
            texto += "\n\nFalharam (veja o log):\n - " + "\n - ".join(falhas)
        if falhas or sem_telegram:
            messagebox.showwarning("Concluído com avisos", texto, parent=popup)
        else:
            messagebox.showinfo("Sucesso", texto, parent=popup)
        popup.destroy()
        self.atualizar_lista_comunicados()

    def filtrar_lista_comunicados(self):
        self.atualizar_lista_comunicados(filtro=self.entry_filtro.get().strip())

    def limpar_filtro(self):
        self.entry_filtro.delete(0, "end")
        self.atualizar_lista_comunicados()

    def selecionar_imagem(self, label_caminho):
        filepath = filedialog.askopenfilename(
            title="Selecione uma Imagem para o Comunicado",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.gif"), ("Todos os arquivos", "*.*")],
            parent=self._pai_seguro(self.popup_criacao))
        if filepath:
            self.caminho_imagem_selecionada = filepath
            label_caminho.config(text=os.path.basename(filepath))
        else:
            self.caminho_imagem_selecionada = None
            label_caminho.config(text="Nenhuma imagem selecionada.")

    def reiniciar_processo_onboarding(self):
        """Limpa os dados de onboarding do funcionário para que ele faça de novo."""
        dados = self._linha_selecionada(self.tree_onboarding)
        if not dados:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista.")
            return

        funcionario_id, nome = dados[0], dados[1]

        confirmacao = messagebox.askyesno(
            "Reiniciar Onboarding",
            f"Deseja reiniciar o processo de admissão para '{nome}'?\n\n"
            "Isso apagará os documentos e dados preenchidos (Escolaridade, Filhos, etc), "
            "permitindo que ele comece do zero pelo Telegram.\n\n"
            "O funcionário NÃO será excluído do sistema.",
            parent=self.root
        )
        if not confirmacao:
            return

        if not database.resetar_onboarding_completo(funcionario_id):
            messagebox.showerror("Erro", "Falha ao reiniciar o processo no banco de dados.", parent=self.root)
            return

        func_obj = database.buscar_funcionario_por_id(funcionario_id)
        chat_id = getattr(func_obj, 'ChatIDTelegram', None) if func_obj else None
        if chat_id:
            # [DEPURAÇÃO] HTML em vez de ** (que aparecia com os asteriscos no Telegram)
            enviar_texto_telegram(
                chat_id,
                "🔄 <b>Processo de Admissão Reiniciado</b>\n\n"
                "O RH solicitou o preenchimento novamente dos seus dados.\n"
                "Por favor, digite <b>Começar</b> para enviar as informações corretas.")

        messagebox.showinfo("Sucesso", "Processo reiniciado! O funcionário pode preencher os dados novamente.", parent=self.root)
        self.carregar_onboarding_lista()


if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoPessoas(root)
    root.mainloop()

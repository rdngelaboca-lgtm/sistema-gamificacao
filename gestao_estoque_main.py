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
import config
import json
import re
from datetime import datetime, date
from tkcalendar import DateEntry
from decimal import Decimal, InvalidOperation # <-- Adicionado InvalidOperation

# [DEPURAÇÃO] O "lxml" NÃO faz parte da lista de instalação do projeto. Antes, se ele
# não estivesse instalado, esta janela inteira não abria. Agora usamos o lxml se existir
# e, se não existir, o leitor de XML que já vem junto com o Python.
try:
    from lxml import etree as ET
    USANDO_LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    USANDO_LXML = False

PASTA_DO_PROGRAMA = os.path.dirname(os.path.abspath(__file__))


# ==============================================================================
# == [DEPURAÇÃO] FUNÇÕES AUXILIARES (números, datas e ordenação) ================
# ==============================================================================
def para_decimal(texto, nome_campo="valor", permitir_zero=True, permitir_negativo=False):
    """
    Converte o que o usuário digitou em número exato (Decimal).
    Aceita: 10   10.5   10,5   R$ 1.234,56   1,234.56
    Levanta ValueError com uma mensagem clara quando o valor é inválido.
    """
    bruto = str(texto if texto is not None else '').replace('R$', '').replace(' ', '').strip()
    if not bruto:
        raise ValueError(f"O campo '{nome_campo}' está vazio.")
    if ',' in bruto and '.' in bruto:
        # O separador que aparece por ÚLTIMO é o decimal (1.234,56 ou 1,234.56)
        if bruto.rfind(',') > bruto.rfind('.'):
            bruto = bruto.replace('.', '').replace(',', '.')
        else:
            bruto = bruto.replace(',', '')
    else:
        bruto = bruto.replace(',', '.')
    try:
        valor = Decimal(bruto)
    except InvalidOperation:
        raise ValueError(f"O campo '{nome_campo}' deve ser um número (ex: 15,50).")
    if not valor.is_finite():  # bloqueia 'NaN' e 'Infinity', que o Decimal aceitaria
        raise ValueError(f"O campo '{nome_campo}' deve ser um número (ex: 15,50).")
    if valor < 0 and not permitir_negativo:
        raise ValueError(f"O campo '{nome_campo}' não pode ser negativo.")
    if valor == 0 and not permitir_zero:
        raise ValueError(f"O campo '{nome_campo}' deve ser maior que zero.")
    return valor


def fmt_num(valor, casas=2, vazio="0"):
    """Formata número sem travar quando vem None (vazio) do banco."""
    if valor is None:
        return vazio
    try:
        return f"{Decimal(str(valor)):.{casas}f}"
    except (InvalidOperation, ValueError):
        return str(valor)


def fmt_data(valor, formato='%d/%m/%Y', vazio='--'):
    """Formata data que pode vir do banco como date, datetime, texto ou None."""
    if valor is None or valor == '':
        return vazio
    if hasattr(valor, 'strftime'):
        return valor.strftime(formato)
    texto = str(valor).strip()
    try:
        return datetime.fromisoformat(texto[:19]).strftime(formato)
    except ValueError:
        return texto[:10]


def data_de_texto_br(texto):
    """'31/01/2025' -> date(2025, 1, 31). Devolve None se não conseguir."""
    try:
        return datetime.strptime(str(texto).strip()[:10], '%d/%m/%Y').date()
    except ValueError:
        return None


def chave_ordenacao(texto):
    """
    [DEPURAÇÃO] Chave para ordenar colunas. Antes misturava número e texto na mesma
    coluna (ex: '1.5 meses' e 'Sem Giro'), o que dava TypeError e a ordenação não funcionava.
    Agora números vêm primeiro (em ordem numérica) e textos depois (em ordem alfabética).
    """
    limpo = str(texto).replace('R$', '').replace('meses', '').replace('>', '').strip()
    if ',' in limpo:  # formato brasileiro: 1.234,56
        limpo = limpo.replace('.', '').replace(',', '.')
    try:
        return (0, float(limpo), '')
    except ValueError:
        return (1, 0.0, str(texto).lower())


def nome_arquivo_seguro(nome):
    """Remove caracteres que o Windows não aceita em nomes de arquivo."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(nome)).strip(' .') or 'arquivo'


def so_digitos(texto):
    return re.sub(r'\D', '', str(texto or ''))


# ==============================================================================
# == [MELHORIA UX] FUNÇÕES AUXILIARES DAS MELHORIAS DE USABILIDADE =============
# ==============================================================================
import unicodedata
import math

ARQUIVO_RASCUNHO_CONTAGEM = os.path.join(PASTA_DO_PROGRAMA, 'rascunho_contagem.json')
ARQUIVO_PREFERENCIAS = os.path.join(PASTA_DO_PROGRAMA, 'estoque_preferencias.json')
PASTA_BACKUPS = os.path.join(PASTA_DO_PROGRAMA, 'backups_estoque')


def sem_acento(texto):
    """'Açaí Côco' -> 'acai coco' (para a busca achar com ou sem acento)."""
    t = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def buscar_nomes(termo, nomes):
    """
    [MELHORIA UX] Busca "inteligente" usada na contagem:
      - ignora acentos e maiúsculas ("acai" acha "Açaí");
      - aceita várias palavras em qualquer ordem ("1kg choc" acha "Chocolate 1KG");
      - os nomes que COMEÇAM com o que foi digitado aparecem primeiro.
    """
    palavras = sem_acento(termo).split()
    if not palavras:
        return list(nomes)
    achados = [n for n in nomes if all(p in sem_acento(n) for p in palavras)]
    inicio = sem_acento(termo).strip()
    return sorted(achados, key=lambda n: (not sem_acento(n).startswith(inicio), sem_acento(n)))


def fmt_qtd(valor):
    """3.500 -> '3,5'   2.000 -> '2'   (quantidade no jeito brasileiro, sem zeros sobrando)."""
    try:
        v = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return str(valor)
    texto = f"{v:.3f}".rstrip('0').rstrip('.')
    return texto.replace('.', ',') if texto else '0'


def fmt_reais(valor):
    """1234.5 -> 'R$ 1.234,50'."""
    try:
        v = Decimal(str(valor or 0))
    except (InvalidOperation, ValueError):
        v = Decimal('0')
    return "R$ " + f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


UNIDADES_FRACIONADAS = {'KG', 'G', 'GR', 'L', 'LT', 'ML', 'M'}


def qtd_para_pedido(sugestao, unidade):
    """
    Arredonda a sugestão para uma quantidade que dá para pedir:
    unidades inteiras (UN, CX, PCT...) sobem para o próximo número inteiro;
    peso/volume (KG, L...) ficam com até 3 casas.
    """
    s = Decimal(str(sugestao or 0))
    if s <= 0:
        return Decimal('0')
    if str(unidade or '').strip().upper() in UNIDADES_FRACIONADAS:
        return s.quantize(Decimal('0.001'))
    return Decimal(math.ceil(s))


def linhas_do_banco_para_dicts(linhas):
    """Converte o que o banco devolve (Row do pyodbc, dict ou objeto) em lista de dicionários."""
    resultado = []
    for linha in linhas or []:
        if isinstance(linha, dict):
            resultado.append(dict(linha))
        elif hasattr(linha, 'cursor_description'):
            resultado.append({c[0]: v for c, v in zip(linha.cursor_description, linha)})
        elif hasattr(linha, '__dict__'):
            resultado.append({k: v for k, v in vars(linha).items() if not k.startswith('_')})
        else:
            resultado.append({'valor': str(linha)})
    for d in resultado:  # o Excel não aceita alguns tipos (Decimal fica como número)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
    return resultado


def nome_aba_excel(nome, usados):
    """Nome de aba válido no Excel (máx. 31 letras, sem []:*?/\\) e sem repetir."""
    base = re.sub(r'[\[\]:*?/\\]', '_', str(nome or 'Sem nome')).strip()[:28] or 'Aba'
    nome_final, n = base, 2
    while nome_final.lower() in usados:
        nome_final = f"{base[:25]}_{n}"; n += 1
    usados.add(nome_final.lower())
    return nome_final


# [MELHORIA VALOR] Tipo da operação de cada item da nota (CFOP, últimos 3 dígitos).
# Bonificação / brinde / amostra grátis: a mercadoria entra no estoque com CUSTO ZERO
# (não foi paga). Comodato (ex: freezer emprestado pela fábrica), remessas, conserto,
# vasilhame e devoluções NÃO são compra: esses itens são ignorados.
CFOP_BONIFICACAO = {'910', '911'}
CFOP_IGNORAR = {'908', '909', '912', '913', '915', '916', '920', '921', '201', '202', '410', '411'}


def tipo_item_por_cfop(cfop):
    """'compra', 'bonificacao' ou 'ignorar'."""
    final = so_digitos(cfop)[-3:]
    if final in CFOP_BONIFICACAO:
        return 'bonificacao'
    if final in CFOP_IGNORAR:
        return 'ignorar'
    return 'compra'


def criar_tree_zebrada(pai, **kwargs):
    """
    [MELHORIA UX] Cria uma tabela (Treeview) com linhas alternadas cinza/branco,
    que facilitam acompanhar a linha com os olhos em listas longas.
    """
    tree = ttk.Treeview(pai, **kwargs)
    insert_original = tree.insert

    def insert_zebrado(parent, index, *args, **kw):
        qtd = len(tree.get_children(parent))
        tags = kw.get('tags', ())
        if isinstance(tags, str):
            tags = (tags,) if tags else ()
        kw['tags'] = tuple(tags) + ('zebra_impar' if qtd % 2 else 'zebra_par',)
        return insert_original(parent, index, *args, **kw)

    tree.insert = insert_zebrado
    try:
        tree.tag_configure('zebra_impar', background='#f3f6fa')
        tree.tag_configure('zebra_par', background='#ffffff')
    except tk.TclError:
        pass
    return tree

class AppGestaoEstoque:
    def __init__(self, root):
        self.root = root
        self.root.title("Módulo de Gestão de Estoque")
        self.root.geometry("1200x700") 

        # [MELHORIA UX] Barra de status no rodapé: mostra "✅ Produto salvo" etc. sem
        # abrir uma janelinha que precisa de clique em OK. (Criada ANTES das abas para
        # ficar sempre visível embaixo.)
        self._status_job = None
        self.barra_status = ttk.Frame(root, relief="sunken", padding=(8, 3))
        self.barra_status.pack(side=tk.BOTTOM, fill=tk.X)
        self.lbl_status = ttk.Label(self.barra_status, text="", anchor="w")
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(self.barra_status, foreground="gray",
                  text="Atalhos: Ctrl+F = buscar · F5 = atualizar · Delete = excluir selecionado").pack(side=tk.RIGHT)

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
        self.custo_carregado_texto = None  # [DEPURAÇÃO] custo mostrado ao abrir o produto p/ edição
        self.fornecedor_selecionado_id = None

        self.itens_xml_nao_vinculados = []
        self.dados_notas_processadas = []
        self.ultima_pasta_xml = None       # [DEPURAÇÃO] permite "Reprocessar" sem escolher de novo
        self.mapa_produtos_mestre = {}
        self.lista_mestre_produtos_nomes = []

        self.mapa_produtos_mestre_contagem = {}
        self.lista_itens_para_salvar_contagem = []
        self.lista_mestre_contagem_nomes = []

        self.cache_relatorio_posicao = {}
        self.mapa_contagens_historico = {}
        # [DEPURAÇÃO] A aba 5 tinha o MESMO dicionário da aba 4; atualizar a aba 4 apagava
        # a opção "DESDE A PRIMEIRA COMPRA" da aba 5. Agora cada aba tem o seu.
        self.mapa_contagens_sugestao = {}

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
        self.carregar_categorias_do_banco()
        self.carregar_solicitacoes()  # [DEPURAÇÃO] antes a aba 7 abria sempre vazia

        # [MELHORIA UX] Atalhos de teclado, lembrar tamanho da janela / última aba,
        # aviso ao fechar e recuperação de contagem não salva.
        self.configurar_atalhos()
        self.aplicar_preferencias()
        self.root.protocol("WM_DELETE_WINDOW", self.ao_fechar_janela)
        self.root.after(400, self.verificar_rascunho_contagem)

    # ===================================================================
    # == [MELHORIA UX] BARRA DE STATUS, ATALHOS E PREFERÊNCIAS ==========
    # ===================================================================
    def status(self, mensagem, tipo='ok', segundos=10):
        """
        Mostra uma mensagem no rodapé. tipo: 'ok' (verde), 'aviso' (laranja),
        'erro' (vermelho) ou 'info' (preto). Some sozinha depois de alguns segundos.
        """
        icones = {'ok': '✅ ', 'aviso': '⚠️ ', 'erro': '❌ ', 'info': 'ℹ️ '}
        cores = {'ok': '#1b7a2f', 'aviso': '#b35c00', 'erro': '#c62828', 'info': '#222222'}
        texto = " ".join(str(mensagem).split())  # tira quebras de linha
        self.ultimo_status = texto
        try:
            self.lbl_status.config(text=icones.get(tipo, '') + texto, foreground=cores.get(tipo, '#222222'))
            if self._status_job:
                self.root.after_cancel(self._status_job)
            self._status_job = self.root.after(segundos * 1000, lambda: self.lbl_status.config(text=""))
        except tk.TclError:
            pass
        logger.info(f"[status] {texto}")

    def aba_atual(self):
        try:
            return self.notebook.tab(self.notebook.select(), "text")
        except tk.TclError:
            return ''

    def configurar_atalhos(self):
        """Ctrl+F = ir para a busca da aba; F5 = atualizar a aba; Delete = excluir o selecionado."""
        self.root.bind_all("<Control-f>", self.atalho_buscar)
        self.root.bind_all("<Control-F>", self.atalho_buscar)
        self.root.bind_all("<F5>", lambda e: (self.on_tab_changed(None), self.status("Aba atualizada.", 'info', 4)))
        atalhos_delete = [
            (self.tree_produtos, self.excluir_produto_selecionado),
            (self.tree_fornecedores, self.excluir_fornecedor_selecionado),
            (self.tree_contagem_atual, self.remover_item_contagem),
            (self.tree_admin_nfs, self.excluir_nfs_selecionadas),
            (self.tree_admin_cont, self.excluir_contagens_selecionadas),
        ]
        for tree, acao in atalhos_delete:
            tree.bind("<Delete>", lambda e, f=acao: f())

    def atalho_buscar(self, event=None):
        campos = {
            '1.': getattr(self, 'entry_filtro_mestre', None),
            '3.': getattr(self, 'entry_filtro_importacao', None),
            '4.': getattr(self, 'entry_filtro_contagem', None),
        }
        campo = campos.get(self.aba_atual()[:2])
        if campo is not None:
            campo.focus_set()
            campo.select_range(0, tk.END)
        return "break"

    def ler_preferencias(self):
        try:
            with open(ARQUIVO_PREFERENCIAS, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def aplicar_preferencias(self):
        """Abre a janela do mesmo tamanho/posição e na mesma aba da última vez."""
        pref = self.ler_preferencias()
        geo = str(pref.get('geometria', ''))
        m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', geo)
        if m:
            larg, alt, x, y = map(int, m.groups())
            try:
                tela_l, tela_a = int(self.root.winfo_screenwidth()), int(self.root.winfo_screenheight())
            except (tk.TclError, TypeError, ValueError):
                tela_l, tela_a = 0, 0
            # Só usa se a janela couber na tela atual (ex: monitor extra desligado)
            if 400 <= larg <= tela_l and 300 <= alt <= tela_a and 0 <= x < tela_l - 100 and 0 <= y < tela_a - 100:
                self.root.geometry(geo)
        aba = pref.get('aba')
        if isinstance(aba, int) and 0 <= aba < 7:
            try:
                self.notebook.select(aba)
            except tk.TclError:
                pass

    def salvar_preferencias(self):
        try:
            dados = {'geometria': self.root.geometry(), 'aba': self.notebook.index(self.notebook.select())}
            with open(ARQUIVO_PREFERENCIAS, 'w', encoding='utf-8') as f:
                json.dump(dados, f)
        except Exception as e:  # nunca impede o programa de fechar
            logger.warning(f"Não foi possível salvar as preferências da janela: {e}")

    def ao_fechar_janela(self):
        """Antes de fechar: avisa sobre contagem não salva e guarda tamanho/aba."""
        qtd = len(self.lista_itens_para_salvar_contagem)
        if qtd:
            if not messagebox.askyesno(
                    "Contagem não salva",
                    f"Há {qtd} item(ns) na contagem que ainda NÃO foram salvos no banco.\n\n"
                    "Fique tranquilo: eles ficam guardados como rascunho e o programa vai "
                    "oferecer para continuar na próxima vez que abrir.\n\n"
                    "Deseja fechar o programa mesmo assim?",
                    icon='warning', parent=self.root):
                return
            self.salvar_rascunho_contagem()
        self.salvar_preferencias()
        self.root.destroy()

    def carregar_categorias_do_banco(self):
        """Busca as categorias dinâmicas do banco e atualiza todos os Comboboxes do sistema."""
        try:
            categorias_db = database.listar_categorias_produto()
            # Se por algum motivo o banco retornar vazio, usa um fallback seguro
            if not categorias_db:
                categorias_db = ["Geral"]
                
            self.lista_categorias = categorias_db
            lista_com_todas = ["Todas"] + self.lista_categorias

            # 1. Aba 1: Formulário Novo Produto
            if hasattr(self, 'combo_prod_categoria'):
                self.combo_prod_categoria['values'] = self.lista_categorias
                if self.combo_prod_categoria.get() not in self.lista_categorias:
                    self.combo_prod_categoria.set("Geral" if "Geral" in self.lista_categorias else self.lista_categorias[0])
            
            # 2. Aba 1: Filtro da Tabela
            if hasattr(self, 'combo_filtro_cat_mestre'):
                valor_atual = self.combo_filtro_cat_mestre.get()
                self.combo_filtro_cat_mestre['values'] = lista_com_todas
                if valor_atual not in lista_com_todas:
                    self.combo_filtro_cat_mestre.set("Todas")

            # 3. Aba 3: Importação XML (Criar Mestre)
            if hasattr(self, 'combo_cat_importacao'):
                self.combo_cat_importacao['values'] = self.lista_categorias
                if self.combo_cat_importacao.get() not in self.lista_categorias:
                    self.combo_cat_importacao.set("Geral" if "Geral" in self.lista_categorias else self.lista_categorias[0])

            # 4. Aba 5: Filtro Sugestão de Compra
            if hasattr(self, 'combo_sugestao_categoria'):
                valor_atual_sug = self.combo_sugestao_categoria.get()
                self.combo_sugestao_categoria['values'] = lista_com_todas
                if valor_atual_sug not in lista_com_todas:
                    self.combo_sugestao_categoria.set("Todas")
                    
        except Exception as e:
            logger.error(f"Erro ao carregar categorias do banco no Tkinter: {e}", exc_info=True)

    def on_tab_changed(self, event):
        """Atualiza os dados das abas quando elas são selecionadas."""
        try:
            tab_selecionada = self.notebook.tab(self.notebook.select(), "text")
        except tk.TclError:
            return

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
        elif tab_selecionada.startswith('7.'):
            # [DEPURAÇÃO] comparava com '7. Aprovar Compras/Manutenção', mas a aba se chama
            # '7. Solicitações (Líderes)' -> a lista NUNCA atualizava sozinha.
            self.carregar_solicitacoes()

    # ===================================================================
    # == ABA 1: CATÁLOGO MESTRE (Sem alterações) ========================
    # ===================================================================
    def criar_aba_catalogo_produtos(self):
        main_frame = ttk.Frame(self.frame_produtos)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Lado Esquerdo: Formulário ---
        self.form_frame_mestre = ttk.LabelFrame(main_frame, text="Modo: NOVO CADASTRO", padding="10")
        self.form_frame_mestre.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        ttk.Label(self.form_frame_mestre, text="Nome do Produto:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_prod_nome = ttk.Entry(self.form_frame_mestre, width=40)
        self.entry_prod_nome.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        # A lista self.lista_categorias agora nasce vazia e será preenchida pelo banco no __init__
        self.lista_categorias = []

        ttk.Label(self.form_frame_mestre, text="Unidade (Ex: UN, KG):").grid(row=2, column=0, sticky="w", pady=2)
        self.entry_prod_unidade = ttk.Entry(self.form_frame_mestre, width=10)
        self.entry_prod_unidade.grid(row=3, column=0, sticky="w", pady=(0, 10))

        ttk.Label(self.form_frame_mestre, text="Categoria:").grid(row=2, column=1, sticky="w", pady=2)
        
        # Sub-frame para colocar o Combobox e o botão "Gerenciar" lado a lado
        frame_categoria_mestre = ttk.Frame(self.form_frame_mestre)
        frame_categoria_mestre.grid(row=3, column=1, sticky="w", pady=(0, 10))
        
        self.combo_prod_categoria = ttk.Combobox(frame_categoria_mestre, values=self.lista_categorias, width=15, state="readonly")
        self.combo_prod_categoria.pack(side=tk.LEFT)
        
        # Botão para abrir o Popup de Gerenciamento
        btn_gerir_categorias = ttk.Button(frame_categoria_mestre, text="⚙️", width=3, command=self.abrir_gestor_categorias)
        btn_gerir_categorias.pack(side=tk.LEFT, padx=(2, 0))

        # --- NOVO LAYOUT: Lado a Lado (Estoque Mínimo e Custo) ---
        ttk.Label(self.form_frame_mestre, text="Estoque Mínimo:").grid(row=4, column=0, sticky="w", pady=2)
        self.entry_prod_estoque_min = ttk.Entry(self.form_frame_mestre, width=15)
        self.entry_prod_estoque_min.grid(row=5, column=0, sticky="w", pady=(0, 10))
        self.entry_prod_estoque_min.insert(0, "0.0")

        ttk.Label(self.form_frame_mestre, text="Custo Inicial (R$):").grid(row=4, column=1, sticky="w", pady=2)
        self.entry_prod_custo = ttk.Entry(self.form_frame_mestre, width=15)
        self.entry_prod_custo.grid(row=5, column=1, sticky="w", pady=(0, 10))
        self.entry_prod_custo.insert(0, "0.00")
        # ---------------------------------------------------------

        btn_frame = ttk.Frame(self.form_frame_mestre)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=10)
        self.btn_prod_salvar = ttk.Button(btn_frame, text="Salvar Novo", command=self.salvar_produto)
        self.btn_prod_salvar.pack(side=tk.LEFT, padx=5)
        self.btn_prod_limpar = ttk.Button(btn_frame, text="Limpar", command=self.limpar_formulario_produto)
        self.btn_prod_limpar.pack(side=tk.LEFT, padx=5)

        # Botão Excluir movido para o formulário (inicialmente desabilitado)
        self.btn_excluir_mestre = ttk.Button(self.form_frame_mestre, text="🗑️ Excluir Produto", command=self.excluir_produto_selecionado, state=tk.DISABLED)
        self.btn_excluir_mestre.grid(row=7, column=0, columnspan=2, pady=15, sticky="ew")

        # --- Lado Direito: Tabela e Filtros ---
        lista_frame = ttk.LabelFrame(main_frame, text="Catálogo Mestre de Produtos (Duplo-clique no item para ver vínculos)", padding="10")
        lista_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        lista_frame.rowconfigure(1, weight=1)
        lista_frame.columnconfigure(0, weight=1)

        # Barra de Filtros Inteligentes
        filtro_frame = ttk.Frame(lista_frame)
        filtro_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(filtro_frame, text="Buscar:").pack(side=tk.LEFT)
        self.entry_filtro_mestre = ttk.Entry(filtro_frame, width=30)
        self.entry_filtro_mestre.pack(side=tk.LEFT, padx=5)
        self.entry_filtro_mestre.bind("<KeyRelease>", self.atualizar_lista_produtos)

        ttk.Label(filtro_frame, text="Categoria:").pack(side=tk.LEFT, padx=(15,0))
        self.combo_filtro_cat_mestre = ttk.Combobox(filtro_frame, values=["Todas"] + self.lista_categorias, state="readonly", width=15)
        self.combo_filtro_cat_mestre.pack(side=tk.LEFT, padx=5)
        self.combo_filtro_cat_mestre.set("Todas")
        self.combo_filtro_cat_mestre.bind("<<ComboboxSelected>>", self.atualizar_lista_produtos)

        # Tabela
        cols = ('ID', 'Nome', 'Unidade', 'Categoria', 'Estoque Mínimo')
        self.tree_produtos = ttk.Treeview(lista_frame, columns=cols, show='headings', selectmode='browse')
        self.tree_produtos.heading('ID', text='ID'); self.tree_produtos.column('ID', width=40, anchor='center')
        self.tree_produtos.heading('Nome', text='Nome'); self.tree_produtos.column('Nome', width=200)
        self.tree_produtos.heading('Unidade', text='UN'); self.tree_produtos.column('Unidade', width=40, anchor='center')
        self.tree_produtos.heading('Categoria', text='Categoria'); self.tree_produtos.column('Categoria', width=120)
        self.tree_produtos.heading('Estoque Mínimo', text='Est. Mínimo'); self.tree_produtos.column('Estoque Mínimo', width=80, anchor='e')

        # Tags para Listras Zebra
        self.tree_produtos.tag_configure('impar', background='#f9f9f9')
        self.tree_produtos.tag_configure('par', background='#ffffff')

        scrollbar = ttk.Scrollbar(lista_frame, orient="vertical", command=self.tree_produtos.yview)
        self.tree_produtos.configure(yscrollcommand=scrollbar.set)
        self.tree_produtos.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        # Eventos (Binds)
        self.tree_produtos.bind('<<TreeviewSelect>>', self.selecionar_produto_para_edicao)
        self.tree_produtos.bind('<Double-1>', self.abrir_popup_vinculos_produto)

        # Rodapé com Indicador
        self.lbl_total_mestre = ttk.Label(lista_frame, text="Carregando...", font=("Arial", 9, "italic"), foreground="gray")
        self.lbl_total_mestre.grid(row=2, column=0, sticky="w", pady=(5,0))

    def limpar_formulario_produto(self, limpar_selecao=True):
        self.entry_prod_nome.delete(0, tk.END)
        self.entry_prod_unidade.delete(0, tk.END)
        categorias = getattr(self, 'lista_categorias', []) or ["Geral"]
        self.combo_prod_categoria.set("Geral" if "Geral" in categorias else categorias[0])
        # [DEPURAÇÃO] o Estoque Mínimo não era limpo: um produto novo herdava o do anterior
        self.entry_prod_estoque_min.delete(0, tk.END)
        self.entry_prod_estoque_min.insert(0, "0.0")
        if hasattr(self, 'entry_prod_custo'):
            self.entry_prod_custo.delete(0, tk.END)
            self.entry_prod_custo.insert(0, "0.00")
        self.produto_selecionado_id = None
        self.custo_carregado_texto = None

        # Restaura visuais para Novo Cadastro
        self.form_frame_mestre.config(text="Modo: NOVO CADASTRO")
        self.btn_prod_salvar.config(text="Salvar Novo")
        self.btn_excluir_mestre.config(state=tk.DISABLED) # Oculta botão excluir

        self.entry_prod_nome.focus()
        if limpar_selecao and self.tree_produtos.selection():
            # [DEPURAÇÃO] Antes, esta função era chamada também ao CLICAR num produto: ela tirava
            # a seleção da linha clicada (a linha "piscava" e perdia o destaque) e isso disparava
            # o evento de seleção de novo, carregando o produto 2 vezes do banco.
            # Agora só tira a seleção quando o usuário clica em "Limpar"/salva/exclui.
            self.tree_produtos.selection_remove(*self.tree_produtos.selection())
            self.tree_produtos.focus('')
    
    def abrir_gestor_categorias(self):
        """Abre uma janela pop-up para criar, editar e excluir categorias do sistema."""
        popup = Toplevel(self.root)
        popup.title("Gerenciador de Categorias")
        popup.geometry("400x500")
        popup.transient(self.root) # Mantém a janela sempre à frente da principal
        popup.grab_set() # Impede que o usuário clique fora enquanto não fechar

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Categorias Atuais do Sistema:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 5))

        # Lista visual
        listbox_frame = ttk.Frame(frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical")
        lista_categorias_ui = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set, font=("Arial", 11), selectbackground="#0078D7")
        scrollbar.config(command=lista_categorias_ui.yview)
        
        lista_categorias_ui.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def atualizar_lista_ui():
            lista_categorias_ui.delete(0, tk.END)
            for cat in self.lista_categorias: # Lê da memória que acabou de ser atualizada do banco
                lista_categorias_ui.insert(tk.END, cat)

        atualizar_lista_ui()

        # Área de Formulário (Edição/Criação)
        ttk.Label(frame, text="Nome da Categoria:").pack(anchor="w", pady=(10, 2))
        entry_cat = ttk.Entry(frame, font=("Arial", 11))
        entry_cat.pack(fill=tk.X, pady=2)

        def on_select(event):
            # Preenche o input quando clica num item da lista
            selecao = lista_categorias_ui.curselection()
            if selecao:
                entry_cat.delete(0, tk.END)
                entry_cat.insert(0, lista_categorias_ui.get(selecao[0]))

        lista_categorias_ui.bind('<<ListboxSelect>>', on_select)

        # Botões de Ação
        frame_botoes = ttk.Frame(frame)
        frame_botoes.pack(fill=tk.X, pady=15)

        def acao_salvar_nova():
            nome = entry_cat.get().strip()
            if not nome: return messagebox.showwarning("Aviso", "Digite um nome.", parent=popup)
            
            sucesso, msg = database.criar_categoria_produto(nome)
            if sucesso:
                self.carregar_categorias_do_banco() # Sincroniza o app todo
                atualizar_lista_ui()
                entry_cat.delete(0, tk.END)
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        def acao_atualizar():
            selecao = lista_categorias_ui.curselection()
            if not selecao: return messagebox.showwarning("Aviso", "Selecione uma categoria na lista para editar.", parent=popup)
            
            nome_antigo = lista_categorias_ui.get(selecao[0])
            novo_nome = entry_cat.get().strip()
            
            if not novo_nome or novo_nome == nome_antigo: return
            
            if messagebox.askyesno("Confirmar Edição", f"Deseja renomear '{nome_antigo}' para '{novo_nome}'?\n\nISSO ATUALIZARÁ TODOS OS PRODUTOS DESTA CATEGORIA AUTOMATICAMENTE.", parent=popup):
                sucesso, msg = database.atualizar_categoria_produto(nome_antigo, novo_nome)
                if sucesso:
                    self.carregar_categorias_do_banco()
                    self.atualizar_lista_produtos() # Atualiza a tabela principal atrás do popup
                    atualizar_lista_ui()
                    entry_cat.delete(0, tk.END)
                    messagebox.showinfo("Sucesso", msg, parent=popup)
                else:
                    messagebox.showerror("Erro", msg, parent=popup)

        def acao_excluir():
            selecao = lista_categorias_ui.curselection()
            if not selecao: return messagebox.showwarning("Aviso", "Selecione uma categoria na lista para excluir.", parent=popup)
            
            nome_excluir = lista_categorias_ui.get(selecao[0])
            
            if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir a categoria '{nome_excluir}'?", parent=popup):
                sucesso, msg = database.excluir_categoria_produto(nome_excluir)
                if sucesso:
                    self.carregar_categorias_do_banco()
                    atualizar_lista_ui()
                    entry_cat.delete(0, tk.END)
                else:
                    messagebox.showerror("Bloqueado", msg, parent=popup)

        ttk.Button(frame_botoes, text="➕ Nova", command=acao_salvar_nova).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(frame_botoes, text="💾 Atualizar", command=acao_atualizar).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(frame_botoes, text="🗑️ Excluir", command=acao_excluir).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        
        ttk.Label(frame, text="💡 Dica: Se quiser apagar uma categoria, você deve primeiro alterar a categoria dos produtos que estão nela.", foreground="gray", font=("Arial", 8, "italic"), wraplength=350).pack(side=tk.BOTTOM, pady=5)

    def salvar_produto(self):
        nome = self.entry_prod_nome.get().strip()
        unidade = self.entry_prod_unidade.get().strip().upper()
        categoria = self.combo_prod_categoria.get() or "Geral"
        custo_texto = self.entry_prod_custo.get().strip()

        if not nome or not unidade:
            messagebox.showerror("Erro", "Nome e Unidade são obrigatórios.", parent=self.root)
            return
        try:
            # [DEPURAÇÃO] para_decimal aceita vírgula, "R$" e recusa 'NaN'/'Infinity'
            estoque_min = para_decimal(self.entry_prod_estoque_min.get() or "0", "Estoque Mínimo")
            custo_inicial = para_decimal(custo_texto, "Custo") if custo_texto else Decimal('0.00')
        except ValueError as ve:
            messagebox.showerror("Erro de Formatação", str(ve), parent=self.root)
            return

        # 3. Comunicação com o Banco de Dados
        try:
            if self.produto_selecionado_id:
                # Se estiver editando, atualiza os dados básicos (Nome, Estoque Min)
                database.atualizar_produto_estoque(self.produto_selecionado_id, nome, unidade, estoque_min, categoria)

                # [DEPURAÇÃO] Antes o custo era SEMPRE regravado, mesmo sem ninguém mexer nele.
                # Isso criava uma "nota fiscal manual" com a data de HOJE, que passava a ser
                # o "último custo" e escondia as notas reais importadas depois.
                # Agora só grava se o valor da caixinha foi realmente alterado.
                if custo_texto != (self.custo_carregado_texto or ""):
                    if database.atualizar_custo_manual_produto(self.produto_selecionado_id, custo_inicial):
                        self.status("Produto e Custo atualizados com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
                    else:
                        messagebox.showwarning("Atenção", "Os dados do produto foram salvos, mas o CUSTO não pôde "
                                                          "ser gravado (veja o log).", parent=self.root)
                else:
                    self.status("Produto atualizado com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            else:
                # SE FOR NOVO: Chama nossa nova função mágica!
                novo_id = database.criar_produto_manual_com_custo(nome, unidade, estoque_min, categoria, custo_inicial) 
                
                if not novo_id: 
                    raise Exception("Falha ao criar produto. O banco não retornou o ID.")
                
                msg_extra = "\n\nCusto inicial salvo com sucesso via Fornecedor Interno!" if custo_inicial > 0 else ""
                self.status(f"Produto '{nome}' criado com sucesso!{msg_extra}")  # [MELHORIA UX] rodapé em vez de janelinha
            
            # Limpa e atualiza tudo
            self.limpar_formulario_produto()
            self.atualizar_lista_produtos()
            self.popular_combobox_produtos_mestre()
            
        except Exception as e:
            logger.error(f"Erro ao salvar produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível salvar o produto.\nErro: {e}", parent=self.root)

    def atualizar_lista_produtos(self, event=None):
        for i in self.tree_produtos.get_children():
            self.tree_produtos.delete(i)
        try:
            produtos = database.listar_produtos_estoque()

            # Captura valores dos filtros
            termo = self.entry_filtro_mestre.get().lower() if hasattr(self, 'entry_filtro_mestre') else ""
            cat_filtro = self.combo_filtro_cat_mestre.get() if hasattr(self, 'combo_filtro_cat_mestre') else "Todas"

            count = 0
            for p in produtos or []:
                cat = getattr(p, 'Categoria', None) or 'Geral'
                nome = p.NomeProduto or ''

                # Aplica filtros em memória
                if cat_filtro != "Todas" and cat != cat_filtro: continue
                if termo and termo not in nome.lower(): continue

                # Zebra striping (Cores alternadas)
                tag = 'par' if count % 2 == 0 else 'impar'

                # [DEPURAÇÃO] EstoqueMinimo vazio (NULL) no banco fazia a LISTA INTEIRA sumir
                self.tree_produtos.insert("", "end", values=(p.ProdutoID, nome, p.UnidadeMedida or 'UN', cat,
                                                             fmt_num(p.EstoqueMinimo, 3, "0.000")), tags=(tag,))
                count += 1

            # Atualiza o rodapé numérico
            if hasattr(self, 'lbl_total_mestre'):
                self.lbl_total_mestre.config(text=f"Total exibido: {count} produto(s)")

        except Exception as e:
            logger.error(f"Erro ao atualizar lista de produtos: {e}", exc_info=True)

    def selecionar_produto_para_edicao(self, event=None):
        # [DEPURAÇÃO] usa a SELEÇÃO (e não o foco): assim "Limpar" funciona de verdade
        selecao = self.tree_produtos.selection()
        if not selecao: return
        selecionado = selecao[0]
        dados = self.tree_produtos.item(selecionado, 'values')
        if not dados or len(dados) < 5: return
        produto_id, nome, unidade, categoria, estoque_min = dados[:5]

        # 1. Limpa a tela inteira primeiro (sem tirar a seleção do item clicado)
        self.limpar_formulario_produto(limpar_selecao=False)

        # 2. Preenche os dados básicos que vieram da tabela
        self.produto_selecionado_id = int(produto_id)
        self.entry_prod_nome.insert(0, nome)
        self.entry_prod_unidade.insert(0, unidade)
        self.combo_prod_categoria.set(categoria)
        self.entry_prod_estoque_min.delete(0, tk.END)
        self.entry_prod_estoque_min.insert(0, estoque_min)

        # 3. MÁGICA: Busca o custo real no banco de dados e preenche a caixinha
        if hasattr(self, 'entry_prod_custo'):
            custo_real = database.buscar_ultimo_custo_por_produto(self.produto_selecionado_id)
            self.entry_prod_custo.delete(0, tk.END)
            # Formata para ficar bonito com duas casas decimais (Ex: 15.50)
            self.custo_carregado_texto = fmt_num(custo_real, 2, "0.00")  # [DEPURAÇÃO] None não trava
            self.entry_prod_custo.insert(0, self.custo_carregado_texto)

        # 4. Visuais do Modo de Edição
        self.form_frame_mestre.config(text="🚨 MODO: EDIÇÃO")
        self.btn_prod_salvar.config(text="Atualizar Produto")
        self.btn_excluir_mestre.config(state=tk.NORMAL) # Habilita o botão de excluir apenas na edição

    def excluir_produto_selecionado(self):
        if not self.produto_selecionado_id:
            messagebox.showwarning("Aviso", "Selecione um produto da lista para excluir.", parent=self.root)
            return
        nome_produto = self.entry_prod_nome.get()
        if not messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o produto:\n\n'{nome_produto}'?", icon='warning', parent=self.root):
            return
        try:
            database.excluir_produto_estoque(self.produto_selecionado_id)
            self.status("Produto excluído com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            self.limpar_formulario_produto()
            self.atualizar_lista_produtos()
            self.popular_combobox_produtos_mestre()
        except Exception as e:
            logger.error(f"Erro ao excluir produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", "Não foi possível excluir o produto.\nVerifique se ele já está vinculado a notas fiscais ou contagens.", parent=self.root)

    def abrir_popup_vinculos_produto(self, event):
        """Disparado pelo duplo clique na tabela mestre. Mostra vínculos com opção de edição rápida."""
        selecionado = self.tree_produtos.focus()
        if not selecionado: return

        dados = self.tree_produtos.item(selecionado, 'values')
        produto_id = int(dados[0])
        nome_produto = dados[1]

        popup = Toplevel(self.root)
        popup.title(f"Vínculos do Produto Mestre: {nome_produto}")
        popup.geometry("800x350")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"Fornecedores que entregam '{nome_produto}':", font=("Arial", 10, "bold")).pack(anchor="w", pady=(0,10))

        # Tabela Pop-up (Adicionado ID oculto e mudado selectmode para 'browse')
        cols = ('ID', 'Fornecedor', 'Descrição no XML', 'EAN', 'Fator (Qtd/Cx)')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings', selectmode='browse')

        tree.heading('ID', text='ID'); tree.column('ID', width=0, stretch=tk.NO) # Esconde a coluna ID
        tree.heading('Fornecedor', text='Fornecedor'); tree.column('Fornecedor', width=150)
        tree.heading('Descrição no XML', text='Descrição na Nota Fiscal (XML)'); tree.column('Descrição no XML', width=250)
        tree.heading('EAN', text='EAN'); tree.column('EAN', width=100, anchor='center')
        tree.heading('Fator (Qtd/Cx)', text='Qtd por Caixa'); tree.column('Fator (Qtd/Cx)', width=100, anchor='center')

        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def carregar_lista_vinculos():
            for i in tree.get_children(): tree.delete(i)
            vinculos = database.buscar_vinculos_por_produto_mestre(produto_id)
            if not vinculos:
                tree.insert("", "end", values=("", "Nenhum vínculo encontrado.", "", "", ""))
            else:
                for v in vinculos:
                    # v = (ID, Fornecedor, Descricao, Fator, EAN)
                    fator_fmt = fmt_num(v[3], 2, "1.00") if v[3] else "1.00"
                    ean_fmt = v[4] if v[4] else "Sem EAN cadastrado"
                    tree.insert("", "end", values=(v[0], v[1], v[2], ean_fmt, fator_fmt))

        def editar_vinculo_clicado(event_tree):
            sel = tree.focus()
            if not sel: return
            vals = tree.item(sel, 'values')
            if not vals[0]: return 

            vinculo_id = vals[0]
            fornecedor = vals[1]
            desc_xml = vals[2]
            ean_atual = vals[3] if vals[3] != "Sem EAN cadastrado" else ""
            fator_atual = vals[4]

            edit_win = Toplevel(popup)
            edit_win.title("Edição Rápida de Vínculo")
            # Aumentamos um pouco a altura para caber o novo campo
            edit_win.geometry("400x320") 
            edit_win.transient(popup)

            f_edit = ttk.Frame(edit_win, padding="15")
            f_edit.pack(fill=tk.BOTH, expand=True)

            ttk.Label(f_edit, text=f"Fornecedor: {fornecedor}", font=("Arial", 9, "bold")).pack(anchor="w", pady=2)
            ttk.Label(f_edit, text=f"XML: {desc_xml}", font=("Arial", 8, "italic")).pack(anchor="w", pady=(0, 10))

            # --- NOVO CAMPO: Troca de Mestre ---
            ttk.Label(f_edit, text="Vinculado ao Produto Mestre:").pack(anchor="w")
            combo_mestre = ttk.Combobox(f_edit, values=self.lista_mestre_produtos_nomes, state="readonly")
            combo_mestre.pack(fill="x", pady=(0, 10))

            # Busca o nome de exibição do mestre atual para deixar pré-selecionado
            nome_mestre_atual_display = next((k for k, v in self.mapa_produtos_mestre.items() if v == produto_id), "")
            combo_mestre.set(nome_mestre_atual_display)
            # -----------------------------------

            ttk.Label(f_edit, text="EAN (Código de Barras):").pack(anchor="w")
            ent_ean = ttk.Entry(f_edit)
            ent_ean.pack(fill="x", pady=2)
            ent_ean.insert(0, ean_atual)

            ttk.Label(f_edit, text="Fator de Conversão (Qtd p/ Caixa):").pack(anchor="w", pady=(10,0))
            ent_fator = ttk.Entry(f_edit)
            ent_fator.pack(fill="x", pady=2)
            ent_fator.insert(0, fator_atual)

            def salvar():
                # [DEPURAÇÃO] fator 0 ou negativo gerava um ValueError que ninguém tratava
                # (a janela simplesmente não fazia nada). Agora aparece a mensagem de erro.
                try:
                    novo_fator = para_decimal(ent_fator.get(), "Fator", permitir_zero=False)
                except ValueError:
                    messagebox.showerror("Erro", "O Fator deve ser um número válido maior que zero.", parent=edit_win)
                    return
                try:
                    novo_ean = ent_ean.get().strip()

                    # Pega o ID do novo mestre selecionado no Combobox
                    novo_mestre_display = combo_mestre.get()
                    novo_mestre_id = self.mapa_produtos_mestre.get(novo_mestre_display)

                    if not novo_mestre_id:
                        messagebox.showerror("Erro", "Selecione um Produto Mestre válido.", parent=edit_win)
                        return

                    if database.atualizar_vinculo_simples(vinculo_id, novo_fator, novo_ean, novo_mestre_id):
                        messagebox.showinfo("Sucesso", "Vínculo atualizado com sucesso!", parent=edit_win)
                        edit_win.destroy()
                        carregar_lista_vinculos() # Atualiza a tabela imediatamente
                    else:
                        messagebox.showerror("Erro", "Falha ao salvar no banco de dados.", parent=edit_win)
                except Exception as e:
                    logger.error(f"Erro ao salvar vínculo {vinculo_id}: {e}", exc_info=True)
                    messagebox.showerror("Erro", f"Falha ao salvar: {e}", parent=edit_win)

            ttk.Button(f_edit, text="💾 Salvar Alterações", command=salvar).pack(pady=20, fill="x", ipady=5)

        # Bind do duplo-clique na sub-janela
        tree.bind("<Double-1>", editar_vinculo_clicado)

        # Carga Inicial
        carregar_lista_vinculos()

        ttk.Label(frame, text="* DICA: Dê um duplo-clique no vínculo acima para ajustar a Qtd/Caixa e o EAN rapidamente.", font=("Arial", 8, "italic"), foreground="green").pack(side=tk.BOTTOM, anchor="w", pady=(10,0))


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
        self.tree_fornecedores = criar_tree_zebrada(lista_frame, columns=cols_forn, show='headings', selectmode='browse')
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

    def limpar_formulario_fornecedor(self, limpar_selecao=True):
        self.entry_forn_nome.delete(0, tk.END)
        self.entry_forn_cnpj.delete(0, tk.END)
        self.fornecedor_selecionado_id = None
        self.btn_forn_salvar.config(text="Salvar Novo")
        self.entry_forn_nome.focus()
        if limpar_selecao and self.tree_fornecedores.selection():
            self.tree_fornecedores.selection_remove(*self.tree_fornecedores.selection())
            self.tree_fornecedores.focus('')

    def salvar_fornecedor(self):
        nome = self.entry_forn_nome.get().strip()
        # [DEPURAÇÃO] Guardamos só os números. Antes, "12.345.678/0001-90" digitado à mão
        # não era reconhecido na importação do XML (que usa só números) e o sistema
        # criava o MESMO fornecedor duas vezes.
        cnpj = so_digitos(self.entry_forn_cnpj.get())
        if not nome or not cnpj:
            messagebox.showerror("Erro", "Nome Fantasia e CNPJ são obrigatórios.", parent=self.root)
            return
        if len(cnpj) not in (11, 14):
            messagebox.showerror("Erro", "O CNPJ deve ter 14 números (ou 11, se for CPF de produtor).", parent=self.root)
            return
        try:
            if self.fornecedor_selecionado_id:
                database.atualizar_fornecedor(self.fornecedor_selecionado_id, cnpj, nome)
                self.status("Fornecedor atualizado com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            else:
                database.criar_fornecedor(cnpj, nome)
                self.status("Fornecedor criado com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
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
            for f in fornecedores or []:
                self.tree_fornecedores.insert("", "end", values=(f.FornecedorID, f.NomeFantasia or '', f.CNPJ or ''))
        except Exception as e:
            logger.error(f"Erro ao atualizar lista de fornecedores: {e}", exc_info=True)

    def selecionar_fornecedor_para_edicao(self, event=None):
        selecao = self.tree_fornecedores.selection()   # [DEPURAÇÃO] seleção, não foco
        if not selecao: return
        dados = self.tree_fornecedores.item(selecao[0], 'values')
        if not dados or len(dados) < 3: return
        fornecedor_id, nome, cnpj = dados[:3]
        self.limpar_formulario_fornecedor(limpar_selecao=False)
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
            self.status("Fornecedor excluído com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
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
        # [DEPURAÇÃO] Depois de vincular itens, basta clicar aqui (não precisa escolher a pasta de novo)
        btn_reprocessar = ttk.Button(frame_botoes, text="🔄 Reprocessar Pasta Atual", command=self.reprocessar_pasta_xml)
        btn_reprocessar.pack(side=tk.LEFT, padx=(5, 0), ipady=10)
        # [MELHORIA UX] Placar da importação: quanto falta e quanto já está pronto
        self.lbl_resumo_importacao = ttk.Label(frame_botoes, text="Nenhuma pasta carregada ainda.",
                                               font=("Arial", 10, "bold"))
        self.lbl_resumo_importacao.pack(side=tk.LEFT, padx=15)
        frame_vincular = ttk.LabelFrame(main_frame, text="2. Itens Pendentes de Vinculação (DE/PARA)", padding="10")
        frame_vincular.grid(row=1, column=0, sticky="nsew", pady=5)
        frame_vincular.rowconfigure(0, weight=1)
        frame_vincular.columnconfigure(0, weight=1)
        # --- COLUNAS ATUALIZADAS (Removido NCM, Adicionado Qtd/Custo) ---
        cols_vinc = ('Fornecedor', 'Produto no XML', 'EAN', 'Qtd na Nota', 'Custo Unit.', 'Custo Total')
        self.tree_vincular = criar_tree_zebrada(frame_vincular, columns=cols_vinc, show='headings', selectmode='browse')

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
        
        ttk.Label(frame_ferramenta, text="EAN (Opc.):").grid(row=0, column=6, sticky="w")
        self.entry_ean_importacao = ttk.Entry(frame_ferramenta, width=10)
        self.entry_ean_importacao.grid(row=0, column=7, sticky="w", padx=(0,5))

        ttk.Label(frame_ferramenta, text="Cat. Novo:").grid(row=0, column=8, sticky="w")
        self.combo_cat_importacao = ttk.Combobox(frame_ferramenta, values=self.lista_categorias, width=10, state="readonly")
        self.combo_cat_importacao.grid(row=0, column=9, sticky="w", padx=(0,5))
        self.combo_cat_importacao.set("Geral")

        btn_vincular = ttk.Button(frame_ferramenta, text="Vincular", command=self.vincular_produto_selecionado)
        btn_vincular.grid(row=0, column=10, sticky="w", padx=2)
        btn_criar_vincular = ttk.Button(frame_ferramenta, text="Criar e Vincular", command=self.criar_mestre_e_vincular)
        btn_criar_vincular.grid(row=0, column=11, sticky="w", padx=2)
        frame_prontos = ttk.LabelFrame(main_frame, text="3. Itens Prontos para Salvar (Já Vinculados)", padding="10")
        frame_prontos.grid(row=3, column=0, sticky="nsew", pady=5)
        frame_prontos.rowconfigure(0, weight=1)
        frame_prontos.columnconfigure(0, weight=1)
        cols_prontos = ('NF', 'Fornecedor', 'Produto Mestre', 'Qtd', 'Custo Unit.', 'Custo Total')
        self.tree_prontos = criar_tree_zebrada(frame_prontos, columns=cols_prontos, show='headings', selectmode='none')
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
        self.btn_salvar_notas = btn_salvar_tudo
        self.btn_salvar_notas.state(['disabled'])  # [MELHORIA UX] só libera quando há nota pronta
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
                logger.info(f"Sugestão Automática: {texto_combo}")
            else:
                self.combo_produtos_mestre.set('')
        else:
            # Se não achou nada, limpa para não confundir
            self.combo_produtos_mestre.set('')

    def popular_combobox_produtos_mestre(self):
        try:
            produtos = database.listar_produtos_estoque()

            # Limpa memórias globais
            self.mapa_produtos_mestre.clear()
            self.lista_mestre_produtos_nomes.clear() 
            self.mapa_produtos_mestre_contagem.clear() 

            nomes_produtos_mestre = []

            for p in produtos:
                # Dados para a Aba 3 (Vínculos)
                nome_display = f"{p.NomeProduto} (ID: {p.ProdutoID})"
                nomes_produtos_mestre.append(nome_display)
                self.mapa_produtos_mestre[nome_display] = p.ProdutoID

                # Dados para a Aba 4 (Contagem - Independente de filtros)
                self.mapa_produtos_mestre_contagem[p.NomeProduto] = {'id': p.ProdutoID, 'un': p.UnidadeMedida}

            # Configurações da Aba 3
            self.lista_mestre_produtos_nomes = sorted(nomes_produtos_mestre) 
            self.combo_produtos_mestre['values'] = self.lista_mestre_produtos_nomes

            # Configurações da Aba 4
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
        pasta_selecionada = filedialog.askdirectory(title="Selecione a pasta contendo os XMLs", parent=self.root)
        if not pasta_selecionada:
            return
        self._carregar_pasta_xml(pasta_selecionada)

    def reprocessar_pasta_xml(self):
        """[DEPURAÇÃO] Lê de novo a última pasta escolhida (útil depois de criar vínculos)."""
        if not self.ultima_pasta_xml or not os.path.isdir(self.ultima_pasta_xml):
            messagebox.showwarning("Aviso", "Nenhuma pasta foi carregada ainda. Use o botão '1. Selecionar Pasta'.", parent=self.root)
            return
        self._carregar_pasta_xml(self.ultima_pasta_xml)

    def atualizar_resumo_importacao(self):
        """[MELHORIA UX] Atualiza o placar e libera o botão 'Salvar' só quando há o que salvar."""
        pendentes = len(self.itens_xml_nao_vinculados)
        prontos = len(self.tree_prontos.get_children())
        completas = sum(1 for n in self.dados_notas_processadas
                        if n.get('itens_pendentes', 0) == 0 and n.get('itens_vinculados'))
        if not self.ultima_pasta_xml:
            texto = "Nenhuma pasta carregada ainda."
        elif pendentes:
            texto = (f"📋 {pendentes} item(ns) para vincular   ·   ✅ {prontos} pronto(s)   ·   "
                     f"🧾 {completas} nota(s) completa(s)")
        elif completas:
            texto = f"🎉 Tudo vinculado! {completas} nota(s) prontas — clique no botão 4 para salvar."
        else:
            texto = "Nada pendente nesta pasta."
        try:
            self.lbl_resumo_importacao.config(text=texto)
            self.btn_salvar_notas.state(['!disabled'] if any(n.get('itens_vinculados') for n in self.dados_notas_processadas)
                                        else ['disabled'])
        except (tk.TclError, AttributeError):
            pass

    def _apos_vincular(self, indice_removido):
        """
        [MELHORIA UX] Depois de vincular um item:
          - seleciona sozinho o PRÓXIMO pendente (não precisa clicar nele);
          - quando não sobra nenhum, relê a pasta sozinho (antes era preciso lembrar
            de clicar em 'Reprocessar' para os itens irem para a lista de salvar).
        """
        restantes = self.tree_vincular.get_children()
        if restantes:
            proximo = restantes[min(indice_removido, len(restantes) - 1)]
            self.tree_vincular.focus(proximo)
            self.tree_vincular.selection_set(proximo)
            try:
                self.tree_vincular.see(proximo)
            except tk.TclError:
                pass
            self.atualizar_resumo_importacao()
        elif self.ultima_pasta_xml and os.path.isdir(self.ultima_pasta_xml):
            self.status("Último item vinculado! Relendo a pasta para liberar as notas...", 'info')
            self._carregar_pasta_xml(self.ultima_pasta_xml)
        else:
            self.atualizar_resumo_importacao()

    def _carregar_pasta_xml(self, pasta_selecionada):
        self.ultima_pasta_xml = pasta_selecionada
        for i in self.tree_vincular.get_children(): self.tree_vincular.delete(i)
        for i in self.tree_prontos.get_children(): self.tree_prontos.delete(i)
        self.itens_xml_nao_vinculados.clear()
        self.dados_notas_processadas.clear()
        try:
            self.processar_arquivos_xml(pasta_selecionada)
        except Exception as e:
            logger.error(f"Erro GERAL ao processar pasta XML: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico no Processamento", f"Ocorreu um erro ao ler os arquivos:\n{e}", parent=self.root)
        self.atualizar_resumo_importacao()
        # [MELHORIA UX] já deixa o primeiro pendente selecionado
        pendentes = self.tree_vincular.get_children()
        if pendentes:
            self.tree_vincular.focus(pendentes[0])
            self.tree_vincular.selection_set(pendentes[0])

    def ler_xml_nota_fiscal(self, caminho_arquivo_xml):
        def dec(texto):
            """Número do XML -> Decimal (tag vazia vale 0)."""
            texto = (texto or '').strip()
            return Decimal(texto) if texto else Decimal('0')

        try:
            if USANDO_LXML:
                # resolve_entities=False: não deixa um XML malicioso ler arquivos do computador
                parser = ET.XMLParser(remove_blank_text=True, resolve_entities=False)
                tree = ET.parse(caminho_arquivo_xml, parser)
            else:
                tree = ET.parse(caminho_arquivo_xml)
            root = tree.getroot()

            # Remove namespaces para facilitar a busca das tags
            # [DEPURAÇÃO] getiterator() está obsoleto (foi removido do Python); iter() é o correto
            for elem in root.iter():
                if not isinstance(elem.tag, str): continue  # comentários do XML
                i = elem.tag.find('}')
                if i >= 0:
                    elem.tag = elem.tag[i+1:]

            # Busca direta sem namespace (mais robusto)
            ide = root.find('.//ide')
            emit = root.find('.//emit')
            total = root.find('.//total/ICMSTot')

            if ide is None or emit is None or total is None:
                raise Exception("Estrutura do XML inválida (tags essenciais não encontradas após limpeza).")

            inf_nfe = root.find('.//infNFe')
            chave = (inf_nfe.get('Id') or '').replace('NFe', '') if inf_nfe is not None else ''

            dados_nf = {
                'NumeroNF': (ide.findtext('nNF', default='') or '').strip(),
                'Serie': (ide.findtext('serie', default='') or '').strip(),
                'ChaveAcesso': chave,
                # Alguns XMLs usam dhEmi, outros dEmi. Tenta ambos.
                'DataEmissao': (ide.findtext('dhEmi') or ide.findtext('dEmi') or datetime.now().strftime('%Y-%m-%dT')).split('T')[0],
                'ValorTotalNF': dec(total.findtext('vNF', default='0.0')),
                # [DEPURAÇÃO] Produtor rural emite NF-e com CPF (não CNPJ). Antes o arquivo era recusado.
                'FornecedorCNPJ': so_digitos(emit.findtext('CNPJ', default='') or emit.findtext('CPF', default='')),
                'FornecedorNome': (emit.findtext('xNome', default='') or '').strip(),
                # [MELHORIA VALOR] finNFe=4 é nota de DEVOLUÇÃO (não é compra)
                'Finalidade': (ide.findtext('finNFe', default='1') or '1').strip(),
            }

            itens = []
            detalhes = root.findall('.//det')
            for det in detalhes:
                prod = det.find('prod')
                if prod is None: continue

                # 1. Quantidade comprada
                qtd_xml = dec(prod.findtext('qCom', default='0.0'))

                # 2. Valores brutos e rateios do produto
                vProd = dec(prod.findtext('vProd', default='0.0')) # Valor total bruto dos itens
                vFrete = dec(prod.findtext('vFrete', default='0.0'))
                vSeg = dec(prod.findtext('vSeg', default='0.0'))
                vOutro = dec(prod.findtext('vOutro', default='0.0'))
                vDesc = dec(prod.findtext('vDesc', default='0.0'))

                # 3. Impostos agregados (Substituição Tributária e IPI)
                # O './/' faz o robô varrer profundamente qualquer tag de imposto procurando a ST
                vICMSST = dec(det.findtext('.//vICMSST', default='0.0'))
                vIPI = dec(det.findtext('.//vIPI', default='0.0'))
                # [MELHORIA VALOR] FCP-ST (Fundo de Combate à Pobreza cobrado junto com a ST)
                # também é pago na compra e faz parte do custo.
                vFCPST = dec(det.findtext('.//vFCPST', default='0.0'))

                # 4. Cálculo do Custo Real de Aquisição Contábil
                custo_total_item = vProd + vICMSST + vFCPST + vIPI + vFrete + vSeg + vOutro - vDesc
                
                # 5. Custo Unitário Certo (c/ Impostos Rateados)
                custo_unit_real = custo_total_item / qtd_xml if qtd_xml > 0 else Decimal('0.0')

                itens.append({
                    'cProd': prod.findtext('cProd', default=''),
                    'cEAN': (prod.findtext('cEAN', default='') or '').strip(),
                    'DescricaoXML': prod.findtext('xProd', default=''),
                    'NCM': prod.findtext('NCM', default=''),
                    'Quantidade': qtd_xml,
                    'PrecoCustoUnitario': custo_unit_real, # Agora leva o custo REAL!
                    'CFOP': (prod.findtext('CFOP', default='') or '').strip(),
                })

            return dados_nf, itens

        except Exception as e:
            logger.error(f"Erro ao ler o arquivo XML '{caminho_arquivo_xml}': {e}", exc_info=True)
            raise Exception(f"Falha estrutural no XML: {e}")

    def processar_arquivos_xml(self, pasta_selecionada):
        # ... (código idêntico ao anterior, agora com pop-up de erro) ...
        extensoes_permitidas = ('.xml', '.txt')
        arquivos_xml = sorted(os.path.join(pasta_selecionada, f) for f in os.listdir(pasta_selecionada) if f.lower().endswith(extensoes_permitidas))
        notas_processadas_nesta_sessao = {}
        arquivos_com_falha = 0
        arquivos_repetidos = 0
        notas_ignoradas, itens_ignorados, itens_bonificados = [], [], []  # [MELHORIA VALOR]
        reconhecidos_por_codigo = []  # [MELHORIA] itens reconhecidos pelo código/EAN (descrição mudou)
        for caminho_xml in arquivos_xml:
            try:
                cabecalho_nf, itens_nf = self.ler_xml_nota_fiscal(caminho_xml)
                cnpj = cabecalho_nf['FornecedorCNPJ']
                nome_fornecedor = cabecalho_nf['FornecedorNome']
                num_nf = cabecalho_nf['NumeroNF']
                if not cnpj or not itens_nf:
                    raise Exception("Arquivo XML não contém CNPJ ou lista de itens.")

                # [MELHORIA VALOR] Nota de devolução não é compra: fica de fora
                if cabecalho_nf.get('Finalidade') == '4':
                    notas_ignoradas.append(f"NF {num_nf} ({nome_fornecedor}) - nota de devolução")
                    continue
                # Itens de comodato/remessa/devolução saem; bonificação entra com custo zero
                itens_filtrados = []
                for it in itens_nf:
                    tipo = tipo_item_por_cfop(it.get('CFOP'))
                    if tipo == 'ignorar':
                        itens_ignorados.append(f"NF {num_nf}: {it['DescricaoXML']} (CFOP {it.get('CFOP')})")
                        continue
                    if tipo == 'bonificacao':
                        it = dict(it, PrecoCustoUnitario=Decimal('0'))
                        itens_bonificados.append(f"NF {num_nf}: {it['DescricaoXML']}")
                    itens_filtrados.append(it)
                if not itens_filtrados:
                    notas_ignoradas.append(f"NF {num_nf} ({nome_fornecedor}) - só itens de comodato/remessa")
                    continue
                itens_nf = itens_filtrados

                # [DEPURAÇÃO] Antes as notas eram separadas SÓ pelo número. Duas notas nº 123 de
                # fornecedores diferentes viravam UMA nota só (e os itens do 2º iam para o 1º).
                # E o mesmo XML duas vezes na pasta (ex: nota.xml e nota.txt) DOBRAVA as quantidades.
                chave_nota = cabecalho_nf.get('ChaveAcesso') or f"{cnpj}-{cabecalho_nf.get('Serie', '')}-{num_nf}"
                if chave_nota in notas_processadas_nesta_sessao:
                    arquivos_repetidos += 1
                    logger.warning(f"Arquivo {caminho_xml} ignorado: a NF {num_nf} ({nome_fornecedor}) já foi lida em outro arquivo.")
                    continue

                fornecedor_id = database.buscar_fornecedor_por_cnpj(cnpj)
                if not fornecedor_id:
                    database.criar_fornecedor(cnpj, nome_fornecedor)
                    fornecedor_id = database.buscar_fornecedor_por_cnpj(cnpj)
                    self.atualizar_lista_fornecedores()
                if not fornecedor_id:
                    raise Exception(f"Não foi possível cadastrar o fornecedor {nome_fornecedor} ({cnpj}).")
                cabecalho_nf['FornecedorID'] = fornecedor_id
                nota = {
                    'cabecalho': cabecalho_nf,
                    'itens_vinculados': [],
                    'itens_pendentes': 0,   # [DEPURAÇÃO] quantos itens desta nota ainda não têm vínculo
                }
                # [DEPURAÇÃO] As linhas só vão para a tela DEPOIS que o arquivo inteiro foi lido.
                # Antes, um erro no meio do arquivo deixava meia nota na lista "Prontos para Salvar".
                linhas_prontos, linhas_pendentes, novos_pendentes = [], [], []
                for item in itens_nf:
                    desc_xml = item['DescricaoXML']
                    # [MELHORIA] Reconhece também pelo código do fornecedor ou EAN quando a
                    # descrição muda (lote/validade no nome). Antes cada variação virava um
                    # vínculo novo (duplicado) e o item caía de novo nos pendentes.
                    if hasattr(database, 'buscar_vinculo_inteligente'):
                        achado = database.buscar_vinculo_inteligente(fornecedor_id, desc_xml, item.get('cProd'), item.get('cEAN'))
                        vinculo_existente = (achado['ProdutoFornecedorID'], achado['ProdutoID'], achado['Fator']) if achado else None
                        if achado and achado['Como'] != 'descricao':
                            reconhecidos_por_codigo.append(f"NF {num_nf}: {desc_xml}")
                    else:
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
                        item_pronto['NomeMestre'] = next((k for k, v in self.mapa_produtos_mestre.items() if v == produto_mestre_id), "Desconhecido")
                        # Atualiza para os valores convertidos antes de salvar
                        item_pronto['Quantidade'] = qtd_real 
                        item_pronto['PrecoCustoUnitario'] = custo_real
                        nota['itens_vinculados'].append(item_pronto)

                        # Custo total não muda (R$ 60 continua R$ 60)
                        custo_total_nota = qtd_real * custo_real 

                        # Exibe na tela informando a conversão se houver
                        txt_qtd = f"{qtd_real:.2f}"
                        if fator != 1:
                            # [DEPURAÇÃO] int(fator) mostrava "x2" para um fator 2,5
                            txt_qtd += f" (Conv. x{fator.normalize():f})"

                        linhas_prontos.append((
                            num_nf, nome_fornecedor, item_pronto['NomeMestre'],
                            txt_qtd, f"{custo_real:.4f}", f"{custo_total_nota:.2f}"
                        ))

                    else:
                        nota['itens_pendentes'] += 1
                        item_pendente = {
                            'FornecedorID': fornecedor_id,
                            'FornecedorNome': nome_fornecedor,
                            'DescricaoXML': desc_xml,
                            'cProd': item['cProd'],
                            'cEAN': item['cEAN'],
                            'NCM': item['NCM'],
                            'CustoXML': item['PrecoCustoUnitario'],   # [MELHORIA VALOR] p/ conferir o fator
                        }

                        ja_listado = any(p['DescricaoXML'] == desc_xml and p['FornecedorID'] == fornecedor_id
                                         for p in self.itens_xml_nao_vinculados + novos_pendentes)
                        if not ja_listado:
                            novos_pendentes.append(item_pendente)

                            # Usa Decimal c/ string para garantir precisão financeira e de estoque
                            qtd_xml = Decimal(str(item['Quantidade']))
                            custo_unit = Decimal(str(item['PrecoCustoUnitario']))
                            custo_total = qtd_xml * custo_unit

                            linhas_pendentes.append((
                                nome_fornecedor, 
                                desc_xml, 
                                item['cEAN'], 
                                f"{qtd_xml:.2f}".rstrip('0').rstrip('.'), # Qtd formatada
                                f"R$ {custo_unit:.2f}", 
                                f"R$ {custo_total:.2f}"
                            ))

                # Arquivo lido por completo: agora sim registra a nota e mostra na tela
                notas_processadas_nesta_sessao[chave_nota] = nota
                self.itens_xml_nao_vinculados.extend(novos_pendentes)
                for valores in linhas_prontos:
                    self.tree_prontos.insert("", "end", values=valores)
                for valores in linhas_pendentes:
                    self.tree_vincular.insert("", "end", values=valores)

            except Exception as e:
                arquivos_com_falha += 1
                logger.error(f"Falha ao processar o arquivo {caminho_xml}: {e}", exc_info=True)

        self.dados_notas_processadas = list(notas_processadas_nesta_sessao.values())
        completas = sum(1 for n in self.dados_notas_processadas if n['itens_pendentes'] == 0)

        msg_final = (f"Leitura de XMLs concluída.\n\n"
                     f"- {len(self.itens_xml_nao_vinculados)} itens precisam de vinculação (Passo 2).\n"
                     f"- {len(self.dados_notas_processadas)} NFs lidas, das quais {completas} estão completas "
                     f"e prontas para salvar (Passo 3).")
        if arquivos_repetidos:
            msg_final += f"\n\nℹ️ {arquivos_repetidos} arquivo(s) eram cópias de notas já lidas e foram ignorados."
        # [MELHORIA VALOR] Resumo do que NÃO é compra
        if notas_ignoradas:
            msg_final += f"\n\nℹ️ {len(notas_ignoradas)} nota(s) ignorada(s) (não são compra):\n  • " + "\n  • ".join(notas_ignoradas[:5])
        if itens_ignorados:
            msg_final += f"\n\nℹ️ {len(itens_ignorados)} item(ns) de comodato/remessa/devolução ignorado(s):\n  • " + "\n  • ".join(itens_ignorados[:5])
        if itens_bonificados:
            msg_final += f"\n\n🎁 {len(itens_bonificados)} item(ns) de BONIFICAÇÃO entram no estoque com custo zero:\n  • " + "\n  • ".join(itens_bonificados[:5])
        if reconhecidos_por_codigo:
            msg_final += (f"\n\n🔎 {len(reconhecidos_por_codigo)} item(ns) com a descrição diferente da última nota foram "
                          "reconhecidos pelo código do fornecedor / EAN (não precisaram de novo vínculo).")
        for lista in (notas_ignoradas, itens_ignorados, itens_bonificados, reconhecidos_por_codigo):
            for linha in lista:
                logger.info(f"[importação XML] {linha}")

        if arquivos_com_falha > 0:
            msg_final += f"\n\n⚠️ AVISO: {arquivos_com_falha} arquivo(s) na pasta não eram Notas Fiscais válidas ou estavam corrompidos e foram ignorados."
            messagebox.showwarning("Processamento Concluído com Avisos", msg_final, parent=self.root)
        else:
            messagebox.showinfo("Processamento Concluído", msg_final, parent=self.root)

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

        produto_mestre_id = self.mapa_produtos_mestre.get(produto_mestre_selecionado)
        if not produto_mestre_id:
            messagebox.showwarning("Aviso", "Produto Mestre não encontrado. Escolha novamente na lista.", parent=self.root)
            return

        # Pega o fator digitado
        try:
            fator = para_decimal(self.entry_fator_conversao.get(), "Itens p/ Cx", permitir_zero=False)
        except ValueError:
            messagebox.showerror("Erro", "O Fator de Conversão deve ser um número válido maior que 0.", parent=self.root)
            return

        if not self.conferir_fator_com_custo_anterior(item_pendente, produto_mestre_id, produto_mestre_selecionado, fator):
            return

        try:
            # Verifica se o usuário digitou um EAN manualmente na tela
            ean_digitado = self.entry_ean_importacao.get().strip()
            ean_final = ean_digitado if ean_digitado else item_pendente['cEAN']

            # [DEPURAÇÃO] o resultado era ignorado: se o banco falhasse, a tela dizia "Vínculo criado!"
            novo_vinculo = database.criar_vinculo_produto_fornecedor(
                produto_id_mestre=produto_mestre_id,
                fornecedor_id=item_pendente['FornecedorID'],
                descricao_xml=item_pendente['DescricaoXML'],
                cProd=item_pendente['cProd'],
                cEAN=ean_final,
                NCM=item_pendente['NCM'],
                fator_conversao=fator # <-- Passa o fator
            )
            if not novo_vinculo:
                messagebox.showerror("Erro de Banco", "Não foi possível criar o vínculo (veja o log).", parent=self.root)
                return

            # Remove o objeto específico da lista e da árvore
            indice = list(self.tree_vincular.get_children()).index(selecionado_tree)
            self.itens_xml_nao_vinculados.remove(item_pendente)
            self.tree_vincular.delete(selecionado_tree)
            self.entry_ean_importacao.delete(0, tk.END) # Limpa o campo para o próximo
            self.entry_fator_conversao.delete(0, tk.END); self.entry_fator_conversao.insert(0, "1")
            # [MELHORIA UX] rodapé em vez de janelinha + próximo item já selecionado
            self.status(f"Vínculo criado: '{item_pendente['DescricaoXML']}' → {produto_mestre_selecionado}")
            self._apos_vincular(indice)
        except Exception as e:
            logger.error(f"Erro ao criar vínculo: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível criar o vínculo.\n{e}", parent=self.root)

    def conferir_fator_com_custo_anterior(self, item_pendente, produto_mestre_id, nome_mestre, fator):
        """
        [MELHORIA VALOR] Fator de caixa errado é o erro que MAIS distorce o valor do estoque
        (ex: CX com 12 vinculada com fator 1 -> custo 12x maior). Compara o custo por
        unidade que vai resultar com o último custo do produto e avisa se ficar muito diferente.
        Devolve True para continuar.
        """
        custo_xml = item_pendente.get('CustoXML')
        if not custo_xml:
            return True
        try:
            custo_anterior = Decimal(str(database.buscar_ultimo_custo_por_produto(produto_mestre_id) or 0))
        except Exception:
            return True
        if custo_anterior <= 0:
            return True
        custo_novo = Decimal(str(custo_xml)) / fator
        razao = custo_novo / custo_anterior
        if Decimal('0.34') < razao < Decimal('3'):
            return True
        fator_sugerido = (Decimal(str(custo_xml)) / custo_anterior).quantize(Decimal('1'))
        dica = f"\n\nDica: para o custo ficar parecido com o anterior, o fator seria perto de {fator_sugerido}." if fator_sugerido > 0 else ""
        return messagebox.askyesno(
            "Confira o fator (Itens p/ Cx)",
            f"'{item_pendente['DescricaoXML']}' → {nome_mestre}\n\n"
            f"Com fator {fmt_qtd(fator)}, o custo vai ficar {fmt_reais(custo_novo)} por unidade.\n"
            f"A última compra deste produto custou {fmt_reais(custo_anterior)} por unidade "
            f"({fmt_qtd(razao.quantize(Decimal('0.1')))}x de diferença).{dica}\n\n"
            "Um fator errado distorce o VALOR DO ESTOQUE.\n\nContinuar com este fator mesmo assim?",
            icon='warning', parent=self.root)

    def salvar_notas_processadas(self):
        if not self.dados_notas_processadas:
            messagebox.showwarning("Aviso", "Nenhuma nota fiscal foi processada ou não há itens vinculados para salvar.", parent=self.root)
            return

        # [DEPURAÇÃO] Uma nota salva NÃO pode ser importada de novo (o banco bloqueia duplicidade).
        # Antes, notas com itens ainda sem vínculo eram salvas pela metade e os itens que
        # faltavam NUNCA mais conseguiam entrar no estoque. Agora essas notas ficam
        # esperando, a não ser que você confirme que quer salvar mesmo incompletas.
        completas = [nf for nf in self.dados_notas_processadas if nf.get('itens_pendentes', 0) == 0 and nf['itens_vinculados']]
        incompletas = [nf for nf in self.dados_notas_processadas if nf.get('itens_pendentes', 0) > 0 and nf['itens_vinculados']]

        para_salvar = list(completas)
        if incompletas:
            lista = "\n".join(f"  • NF {nf['cabecalho']['NumeroNF']} - {nf['cabecalho']['FornecedorNome']} "
                              f"({nf['itens_pendentes']} item(ns) sem vínculo)" for nf in incompletas[:10])
            resposta = messagebox.askyesno(
                "Notas Incompletas",
                f"{len(incompletas)} nota(s) ainda têm itens sem vínculo:\n{lista}\n\n"
                "Se salvar agora, esses itens NUNCA mais poderão entrar pelo XML "
                "(a nota ficará marcada como importada).\n\n"
                "SIM = salvar também as incompletas (só os itens já vinculados)\n"
                "NÃO = salvar só as completas; as incompletas ficam aguardando",
                icon='warning', parent=self.root)
            if resposta:
                para_salvar += incompletas

        if not para_salvar:
            messagebox.showwarning("Aviso", "Nenhuma nota completa para salvar. Vincule os itens do Passo 2 "
                                            "e clique em '🔄 Reprocessar Pasta Atual'.", parent=self.root)
            return

        sucessos = 0
        falhas = 0
        duplicadas = []
        notas_remanescentes = [nf for nf in self.dados_notas_processadas if nf not in para_salvar]

        for nf in para_salvar:
            cabecalho = nf['cabecalho']
            itens_para_salvar = nf['itens_vinculados']
            try:
                sucesso_db, msg_db = database.salvar_nota_fiscal_completa(cabecalho, itens_para_salvar)
                if sucesso_db:
                    sucessos += 1
                elif "já foi importada" in (msg_db or ""):
                    # Já está no banco: não adianta manter na tela
                    duplicadas.append(str(cabecalho['NumeroNF']))
                else:
                    falhas += 1
                    notas_remanescentes.append(nf)
                    logger.error(f"Falha ao salvar NF {cabecalho['NumeroNF']} no banco: {msg_db}")
            except Exception as e:
                falhas += 1
                notas_remanescentes.append(nf)
                logger.error(f"Erro crítico ao tentar salvar NF {cabecalho['NumeroNF']}: {e}", exc_info=True)

        # Atualiza a memória principal com apenas o que sobrou
        self.dados_notas_processadas = notas_remanescentes

        texto = (f"Processo de salvamento finalizado.\n\n"
                 f"Notas salvas com sucesso: {sucessos}\n"
                 f"Notas com erro: {falhas}\n"
                 f"Notas aguardando vínculo: {len([n for n in notas_remanescentes if n.get('itens_pendentes', 0) > 0 or not n['itens_vinculados']])}")
        if duplicadas:
            texto += f"\n\nJá existiam no sistema (ignoradas): NF {', '.join(duplicadas)}"
        if falhas or duplicadas:
            messagebox.showwarning("Processamento Concluído", texto, parent=self.root)
        else:
            messagebox.showinfo("Processamento Concluído", texto, parent=self.root)

        # Atualiza a interface visual
        for i in self.tree_prontos.get_children(): 
            self.tree_prontos.delete(i)
            
        # Recarrega na visualização APENAS o que sobrou na memória
        for nf in self.dados_notas_processadas:
            cabecalho = nf['cabecalho']
            for item in nf['itens_vinculados']:
                nome_exibicao = item.get('NomeMestre') or item.get('DescricaoXML', 'Item')
                qtd_rec = item['Quantidade']
                custo_rec = item['PrecoCustoUnitario']
                custo_tot_rec = qtd_rec * custo_rec

                self.tree_prontos.insert("", "end", values=(
                    cabecalho['NumeroNF'], cabecalho['FornecedorNome'], nome_exibicao, 
                    f"{qtd_rec:.2f}", f"{custo_rec:.4f}", f"{custo_tot_rec:.2f}"
                ))

        self.atualizar_resumo_importacao()
        if not self.dados_notas_processadas and not self.itens_xml_nao_vinculados:
            self.status("Todas as notas e itens foram processados com sucesso! Tela limpa.")  # [MELHORIA UX] rodapé em vez de janelinha

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

        # [DEPURAÇÃO] O fator é conferido ANTES de criar qualquer coisa. Antes, um fator
        # digitado errado virava "1" em silêncio (e a quantidade entrava errada no estoque).
        try:
            fator = para_decimal(self.entry_fator_conversao.get(), "Itens p/ Cx", permitir_zero=False)
        except ValueError:
            messagebox.showerror("Erro", "O Fator de Conversão (Itens p/ Cx) deve ser um número maior que 0.", parent=self.root)
            return

        try:
            produto_id_mestre = database.buscar_produto_mestre_por_nome(nome_novo_produto)
            produto_foi_criado = False
            if not produto_id_mestre:
                cat_selecionada = self.combo_cat_importacao.get()
                if not messagebox.askyesno("Confirmar Auto-Criação",
                                        f"O produto mestre '{nome_novo_produto}' não existe no Catálogo.\n\n"
                                        f"Deseja criá-lo agora?\n"
                                        f"(UN, Est. Mín: 0.0, Categoria: {cat_selecionada})",
                                        parent=self.root):
                    return
                produto_id_mestre = database.criar_produto_estoque(
                    nome=nome_novo_produto,
                    unidade="UN", 
                    estoque_min=Decimal('0.0'),
                    categoria=cat_selecionada
                )
                if not produto_id_mestre:
                    raise Exception("Falha ao criar o produto mestre, não retornou ID.")
                produto_foi_criado = True
            elif not self.conferir_fator_com_custo_anterior(item_pendente, produto_id_mestre, nome_novo_produto, fator):
                return  # [MELHORIA VALOR] produto já existia: confere o fator com o custo anterior

            # Verifica se o usuário digitou um EAN manualmente na tela
            ean_digitado = self.entry_ean_importacao.get().strip()
            ean_final = ean_digitado if ean_digitado else item_pendente['cEAN']

            novo_vinculo = database.criar_vinculo_produto_fornecedor(
                produto_id_mestre=produto_id_mestre,
                fornecedor_id=item_pendente['FornecedorID'],
                descricao_xml=item_pendente['DescricaoXML'],
                cProd=item_pendente['cProd'],
                cEAN=ean_final,
                NCM=item_pendente['NCM'],
                fator_conversao=fator
            )
            if produto_foi_criado:
                self.atualizar_lista_produtos()
                self.popular_combobox_produtos_mestre()
            if not novo_vinculo:
                raise Exception("O banco não conseguiu gravar o vínculo (veja o log).")

            # Remove o objeto específico da lista e da árvore
            indice = list(self.tree_vincular.get_children()).index(selecionado_tree)
            self.itens_xml_nao_vinculados.remove(item_pendente)
            self.tree_vincular.delete(selecionado_tree)
            self.entry_ean_importacao.delete(0, tk.END) # Limpa o campo
            self.entry_fator_conversao.delete(0, tk.END); self.entry_fator_conversao.insert(0, "1")
            criado = "criado e vinculado" if produto_foi_criado else "vinculado"
            self.status(f"Produto '{nome_novo_produto}' {criado}.")
            self._apos_vincular(indice)
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
        # [MELHORIA UX] Contagem só pelo teclado:
        #   digite parte do nome -> Enter -> digite a quantidade -> Enter (e repete).
        #   Setas ↑/↓ no campo de busca escolhem entre os produtos encontrados.
        ttk.Label(frame_lancamento, text="Buscar Produto (digite e tecle Enter):").grid(row=0, column=0, sticky="w")
        self.entry_filtro_contagem = ttk.Entry(frame_lancamento)
        self.entry_filtro_contagem.grid(row=1, column=0, sticky="ew", padx=(0, 5))
        self.entry_filtro_contagem.bind("<KeyRelease>", self.filtrar_combo_contagem)
        self.entry_filtro_contagem.bind("<Return>", self.contagem_enter_na_busca)
        self.entry_filtro_contagem.bind("<Down>", lambda e: self.contagem_navegar_resultados(1))
        self.entry_filtro_contagem.bind("<Up>", lambda e: self.contagem_navegar_resultados(-1))
        self.lbl_contagem_encontrados = ttk.Label(frame_lancamento, text="", foreground="gray")
        self.lbl_contagem_encontrados.grid(row=1, column=1, columnspan=3, sticky="w", padx=5)
        ttk.Label(frame_lancamento, text="Produto do Catálogo Mestre:").grid(row=2, column=0, sticky="w", pady=(5,0))
        self.combo_contagem_produtos = ttk.Combobox(frame_lancamento, state="readonly")
        self.combo_contagem_produtos.grid(row=3, column=0, sticky="ew", padx=(0, 5))
        self.combo_contagem_produtos.bind("<<ComboboxSelected>>", self.atualizar_label_unidade_contagem)
        ttk.Label(frame_lancamento, text="Quantidade:").grid(row=2, column=1, sticky="w", pady=(5,0))
        self.entry_contagem_qtd = ttk.Entry(frame_lancamento, width=10)
        self.entry_contagem_qtd.grid(row=3, column=1, sticky="w", padx=5)
        self.entry_contagem_qtd.bind("<Return>", lambda e: self.adicionar_item_contagem())
        self.entry_contagem_qtd.bind("<KP_Enter>", lambda e: self.adicionar_item_contagem())
        self.entry_contagem_qtd.bind("<Escape>", lambda e: self.entry_filtro_contagem.focus_set())
        self.lbl_contagem_unidade = ttk.Label(frame_lancamento, text="UN", font=("Arial", 10, "italic"))
        self.lbl_contagem_unidade.grid(row=3, column=2, sticky="w", padx=5)
        btn_adicionar_item = ttk.Button(frame_lancamento, text="Adicionar à Lista", command=self.adicionar_item_contagem)
        btn_adicionar_item.grid(row=3, column=3, sticky="w", padx=10)
        frame_lista_lancar = ttk.LabelFrame(main_frame, text="2. Itens nesta Contagem (0) — duplo clique corrige a quantidade", padding="10")
        self.frame_lista_lancar = frame_lista_lancar
        frame_lista_lancar.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=10)
        frame_lista_lancar.rowconfigure(0, weight=1)
        frame_lista_lancar.columnconfigure(0, weight=1)
        cols_cont = ('Produto Mestre', 'Qtd Contada', 'UN')
        self.tree_contagem_atual = criar_tree_zebrada(frame_lista_lancar, columns=cols_cont, show='headings', selectmode='browse')
        self.tree_contagem_atual.bind("<Double-1>", lambda e: self.editar_item_contagem())
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
        self.date_contagem = DateEntry(frame_salvar, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_contagem.grid(row=0, column=1, sticky="w")
        
        ttk.Label(frame_salvar, text="Nome/Ref:").grid(row=0, column=2, sticky="w", padx=(10, 5))
        self.entry_nome_contagem = ttk.Entry(frame_salvar, width=20)
        self.entry_nome_contagem.grid(row=0, column=3, sticky="w")
        self.entry_nome_contagem.insert(0, "Geral")

        self.id_funcionario_contagem = getattr(config, 'ID_GESTOR_PADRAO', 2) 

        btn_salvar_contagem = ttk.Button(frame_salvar, text="Salvar Contagem Completa", command=self.salvar_contagem_completa)
        btn_salvar_contagem.grid(row=0, column=4, sticky="e", padx=20, ipady=5)

        # Botão para exportar a planilha de conferência manual (A caneta)
        btn_planilha_contagem = ttk.Button(frame_salvar, text="📊 Exportar Folha de Contagem (Excel)", command=self.exportar_folha_contagem_manual)
        btn_planilha_contagem.grid(row=1, column=4, sticky="e", padx=20, pady=(5, 0))
        
        frame_historico = ttk.LabelFrame(main_frame, text="Histórico de Contagens Realizadas", padding="10")
        frame_historico.grid(row=0, column=1, rowspan=3, sticky="nsew", pady=5)
        frame_historico.rowconfigure(0, weight=1)
        frame_historico.rowconfigure(1, weight=1)
        frame_historico.columnconfigure(0, weight=1)
        
        cols_hist = ('ID', 'Data', 'Nome', 'Responsável', 'Valor')
        # Mudança de selectmode='browse' para 'extended'
        self.tree_hist_contagens = criar_tree_zebrada(frame_historico, columns=cols_hist, show='headings', selectmode='extended', height=5)
        # [MELHORIA VALOR] mostra o valor das contagens já FECHADAS (🔒)
        self.tree_hist_contagens.heading('Valor', text='Valor Fechado'); self.tree_hist_contagens.column('Valor', width=110, anchor='e')
        self.tree_hist_contagens.heading('ID', text='ID'); self.tree_hist_contagens.column('ID', width=30, anchor='center')
        self.tree_hist_contagens.heading('Data', text='Data'); self.tree_hist_contagens.column('Data', width=80, anchor='center')
        self.tree_hist_contagens.heading('Nome', text='Nome/Ref'); self.tree_hist_contagens.column('Nome', width=120)
        self.tree_hist_contagens.heading('Responsável', text='Responsável'); self.tree_hist_contagens.column('Responsável', width=120)
        self.tree_hist_contagens.grid(row=0, column=0, sticky="nsew")
        self.tree_hist_contagens.bind("<<TreeviewSelect>>", self.carregar_itens_contagem_historico)
        cols_hist_itens = ('Produto', 'Qtd Contada', 'UN')
        self.tree_hist_itens = criar_tree_zebrada(frame_historico, columns=cols_hist_itens, show='headings')
        self.tree_hist_itens.heading('Produto', text='Produto'); self.tree_hist_itens.column('Produto', width=200)
        self.tree_hist_itens.heading('Qtd Contada', text='Qtd'); self.tree_hist_itens.column('Qtd Contada', width=60, anchor='e')
        self.tree_hist_itens.heading('UN', text='UN'); self.tree_hist_itens.column('UN', width=40, anchor='center')
        self.tree_hist_itens.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        # Novos botões de Ação para a Contagem Finalizada
        frame_botoes_hist = ttk.Frame(frame_historico)
        frame_botoes_hist.grid(row=2, column=0, sticky="ew", pady=5)
        
        btn_resolver_avulsos = ttk.Button(frame_botoes_hist, text="⚠️ Resolver Itens Avulsos", command=self.abrir_gerenciador_avulsos)
        btn_resolver_avulsos.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        btn_editar_contagem = ttk.Button(frame_botoes_hist, text="✏️ Editar Contagem Selecionada", command=self.abrir_edicao_contagem)
        btn_editar_contagem.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        btn_consolidar = ttk.Button(frame_botoes_hist, text="🗜️ Consolidar Selecionadas", command=self.consolidar_contagens_selecionadas)
        btn_consolidar.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        btn_relatorio_cmv = ttk.Button(frame_botoes_hist, text="💰 Valor do Estoque", command=self.abrir_relatorio_valoracao)
        btn_relatorio_cmv.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

    def filtrar_combo_contagem(self, event=None):
        # [MELHORIA UX] Busca sem acento, com várias palavras, e ignorando teclas de
        # navegação (antes, apertar a seta ou o Enter refazia a busca e perdia a escolha).
        if event is not None and getattr(event, 'keysym', '') in ('Return', 'KP_Enter', 'Up', 'Down', 'Tab', 'Escape'):
            return
        texto = self.entry_filtro_contagem.get()
        if not texto.strip():
            self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes
            self.combo_contagem_produtos.set('')
            self.lbl_contagem_unidade.config(text="UN")
            self.lbl_contagem_encontrados.config(text="")
            return
        filtrados = buscar_nomes(texto, self.lista_mestre_contagem_nomes)
        self.combo_contagem_produtos['values'] = filtrados
        if filtrados:
            self.combo_contagem_produtos.set(filtrados[0])
            self.atualizar_label_unidade_contagem()  # [CORREÇÃO] Atualiza a unidade visualmente
            extra = " (use ↑ ↓ para trocar)" if len(filtrados) > 1 else ""
            self.lbl_contagem_encontrados.config(text=f"{len(filtrados)} encontrado(s){extra}", foreground="gray")
        else:
            self.combo_contagem_produtos.set('')
            self.lbl_contagem_unidade.config(text="UN")
            self.lbl_contagem_encontrados.config(text="Nenhum produto encontrado", foreground="#c62828")

    def contagem_navegar_resultados(self, passo):
        """Setas ↑/↓ no campo de busca trocam o produto escolhido."""
        valores = list(self.combo_contagem_produtos['values'] or [])
        if not valores:
            return "break"
        atual = self.combo_contagem_produtos.get()
        pos = valores.index(atual) if atual in valores else -1
        novo = valores[(pos + passo) % len(valores)]
        self.combo_contagem_produtos.set(novo)
        self.atualizar_label_unidade_contagem()
        self.lbl_contagem_encontrados.config(
            text=f"{valores.index(novo) + 1} de {len(valores)}: {novo}", foreground="gray")
        return "break"

    def contagem_enter_na_busca(self, event=None):
        """Enter na busca: confirma o produto e pula para o campo de quantidade."""
        if self.combo_contagem_produtos.get() in self.mapa_produtos_mestre_contagem:
            self.entry_contagem_qtd.focus_set()
            self.entry_contagem_qtd.select_range(0, tk.END)
        else:
            self.status("Nenhum produto encontrado com esse nome. Confira a digitação.", 'aviso')
        return "break"

    def atualizar_label_unidade_contagem(self, event=None):
        # ... (código idêntico ao anterior) ...
        produto_selecionado = self.combo_contagem_produtos.get()
        if produto_selecionado and produto_selecionado in self.mapa_produtos_mestre_contagem:
            unidade = self.mapa_produtos_mestre_contagem[produto_selecionado]['un']
            self.lbl_contagem_unidade.config(text=unidade)
        else:
            self.lbl_contagem_unidade.config(text="UN")

    def _item_contagem_por_id(self, produto_id):
        return next((i for i in self.lista_itens_para_salvar_contagem if i['ProdutoID'] == produto_id), None)

    def _redesenhar_lista_contagem(self, destacar_id=None):
        """Mostra a lista da contagem atual (e o total de itens no título)."""
        for i in self.tree_contagem_atual.get_children():
            self.tree_contagem_atual.delete(i)
        for item in self.lista_itens_para_salvar_contagem:
            self.tree_contagem_atual.insert("", "end", iid=str(item['ProdutoID']), values=(
                item['NomeProduto'], f"{Decimal(str(item['QuantidadeContada'])):.3f}", item['Unidade']))
        qtd = len(self.lista_itens_para_salvar_contagem)
        try:
            self.frame_lista_lancar.config(text=f"2. Itens nesta Contagem ({qtd}) — duplo clique corrige a quantidade")
        except (tk.TclError, AttributeError):
            pass
        if destacar_id is not None:
            iid = str(destacar_id)
            try:
                self.tree_contagem_atual.see(iid)
                self.tree_contagem_atual.selection_set(iid)
            except tk.TclError:
                pass

    def _limpar_campos_lancamento(self):
        self.combo_contagem_produtos.set('')
        self.entry_contagem_qtd.delete(0, tk.END)
        self.lbl_contagem_unidade.config(text="UN")
        self.lbl_contagem_encontrados.config(text="")
        self.entry_filtro_contagem.delete(0, tk.END)
        self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes
        self.entry_filtro_contagem.focus_set()

    def adicionar_item_contagem(self):
        produto_nome = self.combo_contagem_produtos.get()
        qtd_str = self.entry_contagem_qtd.get()
        if not produto_nome or not qtd_str.strip():
            messagebox.showwarning("Aviso", "Selecione um produto e digite a quantidade.", parent=self.root)
            return
        try:
            # [MELHORIA UX] aceita "1.234,5" e "1,5" (antes "1.234,5" virava erro)
            quantidade = para_decimal(qtd_str, "Quantidade")  # [DEPURAÇÃO] recusa 'NaN'/'Infinity'
        except ValueError:
            messagebox.showerror("Erro", "A quantidade deve ser um número válido, maior ou igual a zero.", parent=self.root)
            # Limpa o campo para evitar reenvio de dados inválidos e foca
            self.entry_contagem_qtd.delete(0, tk.END)
            self.entry_contagem_qtd.focus_set()
            return

        if produto_nome not in self.mapa_produtos_mestre_contagem:
            messagebox.showwarning("Aviso", "Produto não encontrado. Selecione um item válido da lista.", parent=self.root)
            self.entry_filtro_contagem.focus_set()
            return

        dados_produto = self.mapa_produtos_mestre_contagem[produto_nome]
        produto_id = dados_produto['id']
        unidade = dados_produto['un']

        existente = self._item_contagem_por_id(produto_id)
        if existente:
            # [MELHORIA UX] Antes: "já está na lista, remova-o". Agora dá para SOMAR
            # (ex: 2 caixas no freezer + 1 no depósito) ou SUBSTITUIR.
            anterior = Decimal(str(existente['QuantidadeContada']))
            resposta = messagebox.askyesnocancel(
                "Produto já contado",
                f"'{produto_nome}' já está na lista com {fmt_qtd(anterior)} {unidade}.\n\n"
                f"SIM = SOMAR ({fmt_qtd(anterior)} + {fmt_qtd(quantidade)} = {fmt_qtd(anterior + quantidade)} {unidade})\n"
                f"NÃO = SUBSTITUIR por {fmt_qtd(quantidade)} {unidade}\n"
                f"CANCELAR = não mudar nada",
                parent=self.root)
            if resposta is None:
                self.entry_contagem_qtd.focus_set()
                return
            existente['QuantidadeContada'] = anterior + quantidade if resposta else quantidade
            acao = "somado" if resposta else "substituído"
            msg = f"{produto_nome}: {acao}, agora {fmt_qtd(existente['QuantidadeContada'])} {unidade}."
        else:
            self.lista_itens_para_salvar_contagem.append({
                'ProdutoID': produto_id,
                'NomeProduto': produto_nome,
                'QuantidadeContada': quantidade,
                'Unidade': unidade
            })
            msg = f"{produto_nome}: {fmt_qtd(quantidade)} {unidade} adicionado."

        self._redesenhar_lista_contagem(destacar_id=produto_id)
        self.salvar_rascunho_contagem()
        self.status(f"{msg} ({len(self.lista_itens_para_salvar_contagem)} itens na contagem)")
        self._limpar_campos_lancamento()

    def editar_item_contagem(self):
        """[MELHORIA UX] Duplo clique num item da lista: corrige a quantidade."""
        selecionado = self.tree_contagem_atual.focus()
        if not selecionado:
            return
        item = next((i for i in self.lista_itens_para_salvar_contagem if str(i['ProdutoID']) == str(selecionado)), None)
        if not item:
            return
        texto = simpledialog.askstring(
            "Corrigir quantidade",
            f"{item['NomeProduto']}\n\nNova quantidade ({item['Unidade']}):",
            initialvalue=fmt_qtd(item['QuantidadeContada']), parent=self.root)
        if texto is None:
            return
        try:
            item['QuantidadeContada'] = para_decimal(texto, "Quantidade")
        except ValueError as e:
            messagebox.showerror("Erro", str(e), parent=self.root)
            return
        self._redesenhar_lista_contagem(destacar_id=item['ProdutoID'])
        self.salvar_rascunho_contagem()
        self.status(f"{item['NomeProduto']}: quantidade corrigida para {fmt_qtd(item['QuantidadeContada'])} {item['Unidade']}.")

    def remover_item_contagem(self):
        selecionado = self.tree_contagem_atual.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um item da lista 'Itens nesta Contagem' para remover.", parent=self.root)
            return
        item = next((i for i in self.lista_itens_para_salvar_contagem if str(i['ProdutoID']) == str(selecionado)), None)
        nome_produto = item['NomeProduto'] if item else self.tree_contagem_atual.item(selecionado, 'values')[0]
        # [MELHORIA UX] confirmação (com a tecla Delete ficou fácil apagar sem querer)
        if not messagebox.askyesno("Remover item", f"Remover '{nome_produto}' desta contagem?", parent=self.root):
            return
        self.lista_itens_para_salvar_contagem = [
            i for i in self.lista_itens_para_salvar_contagem if str(i['ProdutoID']) != str(selecionado)
        ]
        self._redesenhar_lista_contagem()
        self.salvar_rascunho_contagem()
        self.status(f"'{nome_produto}' removido da contagem.", 'info')

    def salvar_contagem_completa(self):
        if not self.lista_itens_para_salvar_contagem:
            messagebox.showwarning("Aviso", "Adicione pelo menos um item à lista de contagem antes de salvar.", parent=self.root)
            return
        data_contagem = self.date_contagem.get_date().strftime('%Y-%m-%d')
        funcionario_id = self.id_funcionario_contagem 
        nome_cont = self.entry_nome_contagem.get().strip() or "Geral"
        # [MELHORIA UX] confirmação com o resumo (evita salvar pela metade por engano)
        if not messagebox.askyesno(
                "Salvar contagem",
                f"Salvar a contagem '{nome_cont}' de {self.date_contagem.get_date().strftime('%d/%m/%Y')} "
                f"com {len(self.lista_itens_para_salvar_contagem)} itens?", parent=self.root):
            return
        try:
            sucesso, msg = database.salvar_contagem_estoque(
                data_contagem,
                funcionario_id,
                self.lista_itens_para_salvar_contagem,
                nome_cont
            )
            if sucesso:
                self.status(msg)
                self.entry_nome_contagem.delete(0, tk.END)
                self.entry_nome_contagem.insert(0, "Geral")
                self.lista_itens_para_salvar_contagem.clear()
                self._redesenhar_lista_contagem()
                self.apagar_rascunho_contagem()  # [MELHORIA UX] salvo no banco: rascunho não é mais necessário
                self.atualizar_lista_contagens_historico()
            else:
                messagebox.showerror("Erro de Banco", msg, parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao salvar contagem completa: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado: {e}\n\n"
                                 "Os itens continuam na lista (e guardados no rascunho).", parent=self.root)

    # -------------------------------------------------------------------
    # [MELHORIA UX] RASCUNHO AUTOMÁTICO DA CONTAGEM
    # -------------------------------------------------------------------
    # A cada item lançado, a lista é gravada em "rascunho_contagem.json" (na pasta do
    # programa). Se o programa fechar, travar ou faltar luz, nada se perde: ao abrir de
    # novo, ele pergunta se você quer continuar de onde parou.
    def salvar_rascunho_contagem(self):
        if not self.lista_itens_para_salvar_contagem:
            self.apagar_rascunho_contagem()
            return
        try:
            data_txt = self.date_contagem.get_date().strftime('%Y-%m-%d')
        except Exception:
            data_txt = date.today().strftime('%Y-%m-%d')
        dados = {
            'salvo_em': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'data_contagem': data_txt,
            'nome_contagem': self.entry_nome_contagem.get().strip() or 'Geral',
            'itens': [{'ProdutoID': i['ProdutoID'], 'NomeProduto': i['NomeProduto'],
                       'QuantidadeContada': str(i['QuantidadeContada']), 'Unidade': i['Unidade']}
                      for i in self.lista_itens_para_salvar_contagem],
        }
        temporario = ARQUIVO_RASCUNHO_CONTAGEM + '.tmp'
        try:
            with open(temporario, 'w', encoding='utf-8') as f:
                json.dump(dados, f, ensure_ascii=False, indent=1)
            os.replace(temporario, ARQUIVO_RASCUNHO_CONTAGEM)  # troca de uma vez (não corrompe)
        except OSError as e:
            logger.error(f"Não foi possível salvar o rascunho da contagem: {e}")
            self.status("Não foi possível guardar o rascunho da contagem (veja o log).", 'erro')

    def apagar_rascunho_contagem(self):
        try:
            if os.path.exists(ARQUIVO_RASCUNHO_CONTAGEM):
                os.remove(ARQUIVO_RASCUNHO_CONTAGEM)
        except OSError as e:
            logger.warning(f"Não foi possível apagar o rascunho da contagem: {e}")

    def verificar_rascunho_contagem(self):
        """Ao abrir o programa: oferece continuar uma contagem que não foi salva."""
        if not os.path.exists(ARQUIVO_RASCUNHO_CONTAGEM) or self.lista_itens_para_salvar_contagem:
            return
        try:
            with open(ARQUIVO_RASCUNHO_CONTAGEM, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            itens = []
            for i in dados.get('itens', []):
                itens.append({'ProdutoID': i['ProdutoID'], 'NomeProduto': i['NomeProduto'],
                              'QuantidadeContada': Decimal(str(i['QuantidadeContada'])),
                              'Unidade': i.get('Unidade') or 'UN'})
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as e:
            logger.error(f"Rascunho de contagem ilegível: {e}")
            return
        if not itens:
            self.apagar_rascunho_contagem()
            return

        if messagebox.askyesno(
                "Contagem não salva encontrada",
                f"Existe uma contagem que NÃO foi salva no banco:\n\n"
                f"  • Nome: {dados.get('nome_contagem', 'Geral')}\n"
                f"  • Itens lançados: {len(itens)}\n"
                f"  • Último lançamento: {dados.get('salvo_em', '?')}\n\n"
                "Deseja CONTINUAR essa contagem?\n\n"
                "(Se responder NÃO, ela é descartada — uma cópia fica guardada na pasta "
                "'backups_estoque', por segurança.)", parent=self.root):
            self.lista_itens_para_salvar_contagem = itens
            self.entry_nome_contagem.delete(0, tk.END)
            self.entry_nome_contagem.insert(0, dados.get('nome_contagem', 'Geral'))
            try:
                self.date_contagem.set_date(datetime.strptime(dados['data_contagem'], '%Y-%m-%d').date())
            except (KeyError, ValueError, tk.TclError):
                pass
            self._redesenhar_lista_contagem()
            try:
                self.notebook.select(self.frame_contagem)
            except tk.TclError:
                pass
            self.status(f"Contagem recuperada: {len(itens)} itens. Continue de onde parou.")
        else:
            try:
                os.makedirs(PASTA_BACKUPS, exist_ok=True)
                destino = os.path.join(PASTA_BACKUPS, f"rascunho_descartado_{datetime.now():%Y%m%d_%H%M%S}.json")
                os.replace(ARQUIVO_RASCUNHO_CONTAGEM, destino)
            except OSError as e:
                logger.warning(f"Não foi possível arquivar o rascunho descartado: {e}")
                self.apagar_rascunho_contagem()
            self.status("Rascunho descartado (cópia guardada em 'backups_estoque').", 'info')

    def atualizar_lista_contagens_historico(self):
        # ... (código idêntico ao anterior) ...
        for i in self.tree_hist_contagens.get_children():
            self.tree_hist_contagens.delete(i)
        
        self.mapa_contagens_historico.clear()
        nomes_contagens = []
        
        try:
            contagens = database.listar_contagens_cabecalho()
            try:
                fechados = database.listar_valores_estoque_fechados()
            except Exception as e:
                logger.warning(f"Não foi possível ler os valores fechados: {e}")
                fechados = {}
            for c in contagens:
                # Tratamento seguro para compatibilidade Date vs String
                data_f = fmt_data(c.DataContagem)
                
                nome_contagem_db = getattr(c, 'NomeContagem', 'Geral')
                if not nome_contagem_db: nome_contagem_db = 'Geral'
                
                nome_display = f"ID: {c.ContagemID} - {data_f} - {nome_contagem_db} ({c.NomeCompleto})"
                
                valor_txt = f"🔒 {fmt_reais(fechados[c.ContagemID][0])}" if c.ContagemID in fechados else ""
                self.tree_hist_contagens.insert("", "end", values=(c.ContagemID, data_f, nome_contagem_db, c.NomeCompleto, valor_txt))
                
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
            for item in itens or []:
                self.tree_hist_itens.insert("", "end", values=(item.NomeProduto, fmt_num(item.QuantidadeContada, 3, "0.000"), item.UnidadeMedida))
        except Exception as e:
            logger.error(f"Erro ao carregar itens do histórico (ContagemID {contagem_id}): {e}", exc_info=True)

    def abrir_gerenciador_avulsos(self):
        """Abre janela para resolver itens marcados como avulsos em qualquer contagem."""
        popup = Toplevel(self.root)
        popup.title("Resolver Itens Avulsos de Contagem")
        popup.geometry("800x400")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        cols = ('ContagemID', 'Data', 'Nome Provisório', 'Qtd', 'EAN Fornecido')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings', selectmode='browse')
        for c in cols: tree.heading(c, text=c)
        tree.column('ContagemID', width=80, anchor='center')
        tree.column('Data', width=100, anchor='center')
        tree.column('Nome Provisório', width=250)
        tree.column('Qtd', width=80, anchor='center')
        tree.column('EAN Fornecido', width=120, anchor='center')

        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def carregar():
            for i in tree.get_children(): tree.delete(i)
            try:
                avulsos = database.listar_itens_avulsos_pendentes()
            except Exception as e:  # [DEPURAÇÃO] erro do banco não derruba mais a janela
                logger.error(f"Erro ao listar itens avulsos: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao carregar os itens avulsos:\n{e}", parent=popup)
                avulsos = []
            for av in avulsos or []:
                tree.insert("", "end", values=(av.ContagemID, fmt_data(av.DataContagem), av.NomeAvulso,
                                               fmt_num(av.QuantidadeContada, 3, "0.000"), av.EANAvulso or "Sem EAN"))

        def resolver_clicado(event):
            sel = tree.focus()
            if not sel: return
            vals = tree.item(sel, 'values')
            contagem_id, nome_avulso, qtd_contada, ean_fornecido = vals[0], vals[2], vals[3], vals[4]
            if self.contagem_bloqueada(contagem_id, "resolver este item avulso", popup):
                return

            edit_win = Toplevel(popup)
            edit_win.title("Resolução Inteligente de Avulsos")
            edit_win.geometry("580x550")
            edit_win.transient(popup)

            ttk.Label(edit_win, text=f"Item Contado: {nome_avulso}", font=("Arial", 11, "bold")).pack(pady=(10,2), padx=10, anchor="w")
            ttk.Label(edit_win, text=f"Qtd Original: {qtd_contada} | EAN Bipado: {ean_fornecido}", font=("Arial", 9), foreground="blue").pack(pady=(0,10), padx=10, anchor="w")

            notebook_res = ttk.Notebook(edit_win)
            notebook_res.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

            # --- ABA A: Vínculo Direto ---
            tab_direto = ttk.Frame(notebook_res, padding="10")
            notebook_res.add(tab_direto, text='Opção A: Produto Normal')

            ttk.Label(tab_direto, text="Este item já existe no sistema na medida correta (UN ou KG).\nSó esquecemos de cadastrar o código de barras.", font=("Arial", 9, "italic")).pack(anchor="w", pady=(0,15))

            ttk.Label(tab_direto, text="Vincular ao Produto Mestre:").pack(anchor="w")
            combo_mestre = ttk.Combobox(tab_direto, values=self.lista_mestre_produtos_nomes, state="readonly", width=50)
            combo_mestre.pack(fill="x", pady=5)

            ttk.Label(tab_direto, text="Ajuste de Quantidade a Lançar:").pack(anchor="w", pady=(10,0))
            entry_qtd_a = ttk.Entry(tab_direto, width=15)
            entry_qtd_a.pack(anchor="w", pady=5)
            entry_qtd_a.insert(0, qtd_contada.strip())

            var_salvar_ean = tk.BooleanVar(value=True)
            check_ean = ttk.Checkbutton(tab_direto, text=f"Aprender EAN {ean_fornecido} para não dar erro na próxima vez?", variable=var_salvar_ean)
            if ean_fornecido != "Sem EAN": check_ean.pack(anchor="w", pady=10)

            def salvar_direto():
                sel_mestre = combo_mestre.get()
                if not sel_mestre: return messagebox.showerror("Erro", "Selecione o Mestre.", parent=edit_win)
                try: nova_qtd = para_decimal(entry_qtd_a.get(), "Quantidade")
                except ValueError as ve: return messagebox.showerror("Erro", f"Qtd inválida: {ve}", parent=edit_win)

                mestre_id = self.mapa_produtos_mestre.get(sel_mestre)
                if not mestre_id: return messagebox.showerror("Erro", "Produto Mestre não encontrado. Escolha de novo.", parent=edit_win)
                salvar_perm = var_salvar_ean.get() if ean_fornecido != "Sem EAN" else False

                if database.vincular_item_avulso_inteligente(contagem_id, nome_avulso, mestre_id, nova_qtd, ean_fornecido, salvar_perm):
                    messagebox.showinfo("Sucesso", "Item integrado com sucesso!", parent=edit_win)
                    edit_win.destroy(); carregar(); self.carregar_itens_contagem_historico()
                else: messagebox.showerror("Erro", "Falha ao gravar.", parent=edit_win)

            ttk.Button(tab_direto, text="✅ Confirmar Vinculação (Opção A)", command=salvar_direto).pack(pady=15, fill="x", ipady=5)


            # --- ABA B: Fracionar Caixa ---
            tab_caixa = ttk.Frame(notebook_res, padding="10")
            notebook_res.add(tab_caixa, text='Opção B: Desmembrar Caixa')

            ttk.Label(tab_caixa, text="Este item é a UNIDADE de uma caixa que compramos fechada.\nO sistema calculará o custo e aprenderá o código de barras novo.", font=("Arial", 9, "italic")).pack(anchor="w", pady=(0,10))

            ttk.Label(tab_caixa, text="1. Buscar Cadastro da Caixa (por Nome XML ou Mestre):").pack(anchor="w")
            frame_busca = ttk.Frame(tab_caixa)
            frame_busca.pack(fill="x", pady=5)
            entry_busca_caixa = ttk.Entry(frame_busca)
            entry_busca_caixa.pack(side=tk.LEFT, fill="x", expand=True, padx=(0,5))

            tree_caixas = criar_tree_zebrada(tab_caixa, columns=('ID', 'Mestre', 'Desc XML', 'Forn'), show='headings', height=4)
            tree_caixas.heading('ID', text='ID'); tree_caixas.column('ID', width=0, stretch=tk.NO)
            tree_caixas.heading('Mestre', text='Produto Mestre'); tree_caixas.column('Mestre', width=120)
            tree_caixas.heading('Desc XML', text='Descrição NF'); tree_caixas.column('Desc XML', width=150)
            tree_caixas.heading('Forn', text='Fornecedor'); tree_caixas.column('Forn', width=100)
            tree_caixas.pack(fill="x", pady=5)

            def buscar_caixas():
                termo = entry_busca_caixa.get()
                if not termo: return
                for i in tree_caixas.get_children(): tree_caixas.delete(i)
                # Reutiliza inteligentemente a função da API do celular
                try:
                    res = database.buscar_produtos_mobile_por_nome(termo)
                except Exception as e:
                    logger.error(f"Erro na busca de caixas: {e}", exc_info=True)
                    res = []
                for r in res or []:
                    # r = [ProdutoFornecedorID, NomeMestre, DescricaoXML, Fornecedor...]
                    tree_caixas.insert("", "end", values=(r[0], r[1], r[2], r[3]))

            entry_busca_caixa.bind("<Return>", lambda e: buscar_caixas())
            ttk.Button(frame_busca, text="🔍 Buscar", command=buscar_caixas).pack(side=tk.LEFT)

            ttk.Label(tab_caixa, text="2. Quantas unidades vêm na caixa selecionada acima?").pack(anchor="w", pady=(10,0))
            entry_fator_caixa = ttk.Entry(tab_caixa, width=15)
            entry_fator_caixa.pack(anchor="w", pady=5)

            ttk.Label(tab_caixa, text="3. Quantidade de UNIDADES contadas na loja:").pack(anchor="w", pady=(10,0))
            entry_qtd_b = ttk.Entry(tab_caixa, width=15)
            entry_qtd_b.pack(anchor="w", pady=5)
            entry_qtd_b.insert(0, qtd_contada.strip())

            def salvar_fracao():
                sel_caixa = tree_caixas.focus()
                if not sel_caixa: return messagebox.showerror("Erro", "Selecione a Caixa na tabela.", parent=edit_win)
                id_vinculo_caixa = tree_caixas.item(sel_caixa, 'values')[0]

                try:
                    qtd_na_caixa = float(para_decimal(entry_fator_caixa.get(), "Unidades na caixa", permitir_zero=False))
                    nova_qtd_contada = para_decimal(entry_qtd_b.get(), "Quantidade contada")
                except ValueError as ve: return messagebox.showerror("Erro", f"Valores preenchidos inválidos: {ve}", parent=edit_win)

                if ean_fornecido == "Sem EAN" or not ean_fornecido:
                    return messagebox.showerror("Erro", "Para desmembrar uma caixa, o item avulso deve ter um Código de Barras válido bipado no celular.", parent=edit_win)

                sucesso, msg = database.resolver_avulso_fracionando_caixa(contagem_id, nome_avulso, id_vinculo_caixa, ean_fornecido, qtd_na_caixa, nova_qtd_contada)
                if sucesso:
                    messagebox.showinfo("Sucesso", msg, parent=edit_win)
                    edit_win.destroy(); carregar(); self.carregar_itens_contagem_historico()
                else: messagebox.showerror("Erro", msg, parent=edit_win)

            ttk.Button(tab_caixa, text="📦 Desmembrar e Confirmar (Opção B)", command=salvar_fracao).pack(pady=15, fill="x", ipady=5)

        tree.bind("<Double-1>", resolver_clicado)
        carregar()

    def contagem_bloqueada(self, contagem_id, acao, janela=None):
        """
        [MELHORIA VALOR] Contagem com valor FECHADO não pode mudar (senão o valor lançado
        no outro sistema deixa de bater com as quantidades). Devolve True se estiver bloqueada.
        """
        try:
            fechados = database.listar_valores_estoque_fechados()
        except Exception:
            return False
        try:
            chave = int(contagem_id)
        except (TypeError, ValueError):
            return False
        if chave not in fechados:
            return False
        messagebox.showwarning(
            "Contagem com valor fechado",
            f"A contagem ID {chave} está com o VALOR DO ESTOQUE FECHADO ({fmt_reais(fechados[chave][0])}).\n\n"
            f"Para {acao}, selecione a contagem, clique em '💰 Valor do Estoque' e depois em '🔓 Reabrir'.\n"
            "(Se você já lançou esse valor em outro lugar, lembre de corrigir lá também.)",
            parent=janela or self.root)
        return True

    def abrir_edicao_contagem(self):
        """Abre janela para alterar quantidades ou adicionar/remover itens de uma contagem existente."""
        selecionado = self.tree_hist_contagens.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione uma contagem no Histórico primeiro.", parent=self.root)
            return
        contagem_id = self.tree_hist_contagens.item(selecionado, 'values')[0]
        if self.contagem_bloqueada(contagem_id, "editar esta contagem"):
            return

        popup = Toplevel(self.root)
        popup.title(f"Editor de Contagem ID: {contagem_id}")
        popup.geometry("700x500")
        popup.transient(self.root)

        frame_add = ttk.LabelFrame(popup, text="Adicionar Item Esquecido", padding="10")
        frame_add.pack(fill=tk.X, padx=10, pady=5)
        
        combo_mestre = ttk.Combobox(frame_add, values=self.lista_mestre_produtos_nomes, state="readonly", width=40)
        combo_mestre.pack(side=tk.LEFT, padx=5)
        entry_qtd = ttk.Entry(frame_add, width=10)
        entry_qtd.pack(side=tk.LEFT, padx=5)
        
        cols = ('Nome', 'Qtd', 'IDProduto', 'NomeAvulso')
        tree = criar_tree_zebrada(popup, columns=cols, show='headings', selectmode='browse')
        tree.heading('Nome', text='Produto / Avulso'); tree.column('Nome', width=300)
        tree.heading('Qtd', text='Qtd'); tree.column('Qtd', width=100, anchor='center')
        tree.heading('IDProduto', text='IDProduto'); tree.column('IDProduto', width=0, stretch=tk.NO)
        tree.heading('NomeAvulso', text='NomeAvulso'); tree.column('NomeAvulso', width=0, stretch=tk.NO)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        def carregar():
            for i in tree.get_children(): tree.delete(i)
            itens = database.buscar_itens_contagem(contagem_id)
            for item in itens or []:
                # Retorno do banco agora tem 5 posicoes: Nome, Qtd, UN, ProdutoID, NomeAvulso
                tree.insert("", "end", values=(item.NomeProduto, fmt_num(item.QuantidadeContada, 3, "0.000"), item.ProdutoID or "", item.NomeAvulso or ""))

        def adicionar():
            sel = combo_mestre.get()
            if not sel or not entry_qtd.get().strip():
                messagebox.showwarning("Aviso", "Escolha o produto e digite a quantidade.", parent=popup)
                return
            # [DEPURAÇÃO] Antes QUALQUER erro (até do banco) aparecia como "Quantidade inválida",
            # e se o banco recusasse, nada avisava. Agora cada caso tem sua mensagem.
            try:
                qtd = para_decimal(entry_qtd.get(), "Quantidade")
            except ValueError as ve:
                messagebox.showerror("Erro", str(ve), parent=popup)
                return
            mestre_id = self.mapa_produtos_mestre.get(sel)
            if not mestre_id:
                messagebox.showerror("Erro", "Produto Mestre não encontrado. Escolha de novo.", parent=popup)
                return
            if not database.adicionar_item_contagem_existente(contagem_id, mestre_id, qtd):
                messagebox.showerror("Erro de Banco", "Não foi possível inserir o item (veja o log).", parent=popup)
                return
            entry_qtd.delete(0, tk.END)
            combo_mestre.set("")
            carregar()
            self.carregar_itens_contagem_historico()

        ttk.Button(frame_add, text="➕ Inserir", command=adicionar).pack(side=tk.LEFT, padx=5)

        def editar_remover(event):
            sel = tree.focus()
            if not sel: return
            vals = tree.item(sel, 'values')
            nome, qtd, prod_id, nome_avulso = vals[0], vals[1], vals[2], vals[3]

            edit_win = Toplevel(popup)
            edit_win.title("Alterar/Remover")
            edit_win.geometry("300x150")
            edit_win.transient(popup)

            ttk.Label(edit_win, text=f"{nome}").pack(pady=5)
            e_qtd = ttk.Entry(edit_win, justify='center'); e_qtd.pack(pady=5); e_qtd.insert(0, qtd)

            def salvar():
                try:
                    nova_qtd = para_decimal(e_qtd.get(), "Quantidade")

                    # Tipagem rigorosa para evitar falha na query do banco
                    id_produto_limpo = int(prod_id) if prod_id and str(prod_id).strip() != "" else None
                    avulso_limpo = str(nome_avulso) if nome_avulso and str(nome_avulso).strip() != "" else None

                    sucesso = database.atualizar_qtd_item_contagem(contagem_id, id_produto_limpo, avulso_limpo, nova_qtd)

                    if sucesso:
                        edit_win.destroy()
                        carregar()
                        self.carregar_itens_contagem_historico()
                    else:
                        messagebox.showerror("Erro de Banco", "Falha ao salvar a nova quantidade no banco de dados.", parent=edit_win)

                except (InvalidOperation, ValueError) as e:
                    messagebox.showerror("Entrada Inválida", "Por favor, digite um número válido maior ou igual a zero.\nUse ponto ou vírgula para decimais.", parent=edit_win)
                    e_qtd.focus() # Retorna o foco para o usuário corrigir

            def apagar():
                if not messagebox.askyesno("Confirmar", f"Tem certeza que deseja remover o item '{nome}' desta contagem?", parent=edit_win):
                    return

                # Sanitização rigorosa de tipos (String da Treeview -> Tipos Nativos Python)
                id_produto_limpo = int(prod_id) if prod_id and str(prod_id).strip() != "" else None
                avulso_limpo = str(nome_avulso) if nome_avulso and str(nome_avulso).strip() != "" else None

                try:
                    sucesso = database.remover_item_contagem(contagem_id, id_produto_limpo, avulso_limpo)
                except Exception as e:  # [DEPURAÇÃO] essa função do banco não trata erros sozinha
                    logger.error(f"Erro ao remover item da contagem: {e}", exc_info=True)
                    sucesso = False

                if sucesso:
                    edit_win.destroy()
                    carregar()
                    self.carregar_itens_contagem_historico()
                else:
                    messagebox.showerror("Erro", "Falha ao remover o item do banco de dados.", parent=edit_win)

            f_btn = ttk.Frame(edit_win); f_btn.pack(pady=10)
            ttk.Button(f_btn, text="💾 Salvar Qtd", command=salvar).pack(side=tk.LEFT, padx=5)
            ttk.Button(f_btn, text="🗑️ Remover", command=apagar).pack(side=tk.LEFT, padx=5)

        tree.bind("<Double-1>", editar_remover)
        carregar()

    def consolidar_contagens_selecionadas(self):
        """
        Lógica completa de consolidação blindada contra congelamentos (UI Freeze)
        e falhas de duplicação em grandes volumes de dados.
        """
        selecionados = self.tree_hist_contagens.selection()
        if len(selecionados) < 2:
            messagebox.showwarning("Aviso", "Selecione pelo menos duas contagens no histórico para consolidar.", parent=self.root)
            return
        for item in selecionados:  # [MELHORIA VALOR] consolidar apaga as originais
            if self.contagem_bloqueada(self.tree_hist_contagens.item(item, 'values')[0], "consolidar esta contagem"):
                return

        if not messagebox.askyesno("Confirmar Consolidação", 
                                f"Deseja mesclar as {len(selecionados)} contagens selecionadas?\n\n"
                                "Os itens iguais serão somados em uma ÚNICA contagem (com a data da contagem mais recente), "
                                "e as contagens originais serão excluídas do histórico.", 
                                parent=self.root):
            return

        nome_nova_contagem = simpledialog.askstring("Nome da Consolidação", "Digite um nome/referência para a nova contagem (Ex: Balanço Consolidado):", parent=self.root)
        if not nome_nova_contagem:
            return

        # BLINDAGEM 1: Muda o cursor para "Carregando" (Cross-platform seguro)
        try:
            self.root.config(cursor="watch") # 'watch' funciona no Linux/Lubuntu
        except Exception:
            pass # Ignora a falha visual do SO e segue com a regra de negócio

        self.root.update_idletasks() # Força a tela a desenhar antes de travar

        itens_agrupados = {}
        ids_para_excluir = []
        datas_selecionadas = []

        try:
            for item in selecionados:
                dados = self.tree_hist_contagens.item(item, 'values')
                contagem_id = int(dados[0])
                ids_para_excluir.append(contagem_id)
                data_cont = data_de_texto_br(dados[1])
                if data_cont:
                    datas_selecionadas.append(data_cont)

                itens_da_contagem = database.buscar_itens_contagem(contagem_id)

                for i in itens_da_contagem:
                    prod_id = getattr(i, 'ProdutoID', None)
                    avulso = getattr(i, 'NomeAvulso', None)
                    qtd = Decimal(str(i.QuantidadeContada)) if getattr(i, 'QuantidadeContada', None) is not None else Decimal('0.0')

                    chave_agrupamento = f"PROD_{prod_id}" if prod_id else f"AVULSO_{avulso}"

                    if chave_agrupamento in itens_agrupados:
                        itens_agrupados[chave_agrupamento]['QuantidadeContada'] += qtd
                    else:
                        itens_agrupados[chave_agrupamento] = {
                            'ProdutoID': prod_id,
                            'QuantidadeContada': qtd,
                            'NomeAvulso': avulso,
                            'EANAvulso': getattr(i, 'EANAvulso', None)
                        }

                # BLINDAGEM 2: Avisa o Windows que o app não travou a cada volta do loop
                self.root.update_idletasks()

            lista_para_salvar = list(itens_agrupados.values())
            # [DEPURAÇÃO] A contagem consolidada recebia a data de HOJE. Consolidar as contagens
            # do dia 31/01 numa terça-feira qualquer jogava o estoque para a data errada e
            # bagunçava a Sugestão de Compra e o CMV. Agora usa a data da contagem mais recente.
            data_consolidada = max(datas_selecionadas) if datas_selecionadas else datetime.now().date()
            data_consolidada_txt = data_consolidada.strftime('%Y-%m-%d')

            # Executa a transação de salvamento
            sucesso_salvar, msg = database.salvar_contagem_estoque(
                data_consolidada_txt, 
                self.id_funcionario_contagem, 
                lista_para_salvar, 
                nome_nova_contagem.strip()
            )

            if sucesso_salvar:
                falhas_exclusao = 0
                # BLINDAGEM 3: Exclusão com tolerância a falhas
                for cid in ids_para_excluir:
                    if not database.excluir_contagem_estoque(cid):
                        falhas_exclusao += 1
                    self.root.update_idletasks() # Mantém a tela viva durante a limpeza

                if falhas_exclusao == 0:
                    messagebox.showinfo("Sucesso", f"Contagens consolidadas com sucesso!\n({len(lista_para_salvar)} itens únicos processados)\n"
                                                   f"Data da nova contagem: {data_consolidada.strftime('%d/%m/%Y')}", parent=self.root)
                else:
                    messagebox.showwarning("Aviso de Limpeza", f"A nova contagem consolidada foi criada com sucesso, mas houve falha ao excluir {falhas_exclusao} contagem(ns) antigas.\n\nAtualize a tela e exclua as antigas manualmente para não duplicar o estoque.", parent=self.root)

                self.atualizar_lista_contagens_historico()
                self.popular_combos_contagem_sugestao()
                for i in self.tree_hist_itens.get_children(): self.tree_hist_itens.delete(i)
            else:
                messagebox.showerror("Erro de Banco", f"Falha ao gerar contagem consolidada:\n{msg}", parent=self.root)

        except Exception as e:
            logger.error(f"Erro crítico ao consolidar contagens: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro no processamento:\n{e}", parent=self.root)
        finally:
            # BLINDAGEM 4: SEMPRE restaura o cursor do mouse, mesmo se o banco der erro
            try:
                self.root.config(cursor="")
            except Exception:
                pass 

    def abrir_relatorio_valoracao(self):
        """
        [MELHORIA VALOR] Janela "💰 Valor do Estoque" da contagem selecionada.
        - custo de cada produto = MÉDIA PONDERADA das compras dos 90 dias até a data da contagem;
        - conferência antes de fechar: não contados, avulsos, sem custo e custo suspeito;
        - total e subtotal por categoria;
        - "🔒 Fechar valor" grava tudo: o total nunca mais muda (dá para reabrir).
        """
        selecionado = self.tree_hist_contagens.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione uma contagem no Histórico primeiro para ver o valor do estoque.", parent=self.root)
            return
        dados_contagem = self.tree_hist_contagens.item(selecionado, 'values')
        contagem_id = int(dados_contagem[0])
        data_contagem = dados_contagem[1]
        nome_contagem = dados_contagem[2]

        popup = Toplevel(self.root)
        popup.title(f"💰 Valor do Estoque - {nome_contagem} ({data_contagem})")
        popup.geometry("1050x720")
        popup.transient(self.root)
        estado = {'dados': None}

        frame = ttk.Frame(popup, padding="12")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"💰 Valor do Estoque — {nome_contagem} ({data_contagem})",
                  font=("Arial", 14, "bold"), foreground="#0056b3").pack(anchor="w")
        lbl_situacao = ttk.Label(frame, text="", font=("Arial", 10, "bold"))
        lbl_situacao.pack(anchor="w", pady=(2, 8))

        # ---------- Conferência ----------
        frame_avisos = ttk.LabelFrame(frame, text="⚠️ Conferência antes de fechar — duplo clique numa linha para resolver", padding="6")
        cols_av = ('Tipo', 'Produto', 'Detalhe')
        tree_av = criar_tree_zebrada(frame_avisos, columns=cols_av, show='headings', selectmode='browse', height=6)
        tree_av.heading('Tipo', text='Tipo'); tree_av.column('Tipo', width=130)
        tree_av.heading('Produto', text='Produto'); tree_av.column('Produto', width=260)
        tree_av.heading('Detalhe', text='O que fazer / detalhe'); tree_av.column('Detalhe', width=560)
        tree_av.pack(fill=tk.X)
        mapa_avisos = {}

        # ---------- Itens ----------
        cols = ('Categoria', 'Produto', 'Qtd', 'UN', 'Custo Unit.', 'Valor', 'Origem do custo')
        frame_tab = ttk.Frame(frame)
        tree = criar_tree_zebrada(frame_tab, columns=cols, show='headings', selectmode='browse')
        for col in cols:
            tree.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(tree, c, False))
        for col, larg, anc in (('Categoria', 120, 'w'), ('Produto', 250, 'w'), ('Qtd', 80, 'e'), ('UN', 45, 'center'),
                               ('Custo Unit.', 100, 'e'), ('Valor', 110, 'e'), ('Origem do custo', 290, 'w')):
            tree.column(col, width=larg, anchor=anc)
        sb = ttk.Scrollbar(frame_tab, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # ---------- Rodapé: categorias + total + botões ----------
        frame_rodape = ttk.Frame(frame)
        tree_cat = criar_tree_zebrada(frame_rodape, columns=('Categoria', 'Valor', '%'), show='headings', height=5)
        tree_cat.heading('Categoria', text='Categoria'); tree_cat.column('Categoria', width=160)
        tree_cat.heading('Valor', text='Valor'); tree_cat.column('Valor', width=120, anchor='e')
        tree_cat.heading('%', text='%'); tree_cat.column('%', width=60, anchor='e')
        tree_cat.pack(side=tk.LEFT)
        frame_dir = ttk.Frame(frame_rodape)
        frame_dir.pack(side=tk.RIGHT, fill=tk.Y)
        lbl_total = ttk.Label(frame_dir, text="", font=("Arial", 18, "bold"), foreground="green")
        lbl_total.pack(anchor="e", pady=(0, 10))
        frame_bot = ttk.Frame(frame_dir)
        frame_bot.pack(anchor="e")

        frame_avisos.pack(fill=tk.X, pady=(0, 8))
        frame_tab.pack(fill=tk.BOTH, expand=True)
        frame_rodape.pack(fill=tk.X, pady=(8, 0))

        def recarregar():
            try:
                popup.config(cursor="watch"); popup.update_idletasks()
                dados = database.calcular_valor_estoque(contagem_id)
            except Exception as e:
                logger.error(f"Erro ao calcular o valor do estoque (contagem {contagem_id}): {e}", exc_info=True)
                messagebox.showerror("Erro", f"Não foi possível calcular o valor do estoque:\n{e}", parent=popup)
                return
            finally:
                try:
                    popup.config(cursor="")
                except tk.TclError:
                    pass
            estado['dados'] = dados

            for t in (tree, tree_av, tree_cat):
                for i in t.get_children():
                    t.delete(i)
            for it in dados['itens']:
                tree.insert("", "end", values=(
                    it.get('Categoria') or 'Geral', it['NomeProduto'], fmt_qtd(it['Quantidade']), it.get('Unidade') or 'UN',
                    fmt_reais(it['CustoUnitario']), fmt_reais(it['ValorTotal']), it.get('OrigemCusto') or ''))
            total = Decimal(str(dados['total'] or 0))
            for cat, valor in dados['por_categoria'].items():
                pct = (Decimal(str(valor)) / total * 100) if total > 0 else Decimal('0')
                tree_cat.insert("", "end", values=(cat or 'Geral', fmt_reais(valor), f"{pct:.1f}%".replace('.', ',')))
            lbl_total.config(text=f"TOTAL: {fmt_reais(total)}")

            mapa_avisos.clear()
            av = dados['avisos']
            textos = {
                'nao_contados': ("❓ Não contado", "{Detalhe} → duplo clique para informar a quantidade (0 se acabou)"),
                'avulsos': ("📦 Avulso", "não entra no valor → duplo clique para resolver"),
                'sem_custo': ("💲 Sem custo", "vai valer R$ 0,00 → duplo clique para informar o custo"),
                'custo_suspeito': ("🔍 Custo suspeito", "{Detalhe} → duplo clique para ver os vínculos"),
            }
            for tipo, lista in av.items():
                rotulo, modelo = textos[tipo]
                for a in lista:
                    iid = tree_av.insert("", "end", values=(rotulo, a['NomeProduto'], modelo.format(Detalhe=a.get('Detalhe', ''))))
                    mapa_avisos[iid] = (tipo, a)
            qtd_avisos = sum(len(v) for v in av.values())

            if dados['fechado']:
                data_f = dados['fechado']['data']
                data_txt = data_f.strftime('%d/%m/%Y %H:%M') if hasattr(data_f, 'strftime') else str(data_f)[:16]
                lbl_situacao.config(text=f"🔒 VALOR FECHADO em {data_txt} — este total não muda mais.", foreground="#1b7a2f")
                frame_avisos.pack_forget()
                btn_fechar.pack_forget(); btn_reabrir.pack(side=tk.LEFT, padx=3, before=btn_copiar)
            else:
                lbl_situacao.config(
                    text="🔓 Valor em aberto — custo médio ponderado das compras dos 90 dias até a data da contagem. "
                         "Confira os avisos e clique em '🔒 Fechar valor'.", foreground="#b35c00")
                btn_reabrir.pack_forget(); btn_fechar.pack(side=tk.LEFT, padx=3, before=btn_copiar)
                if qtd_avisos:
                    frame_avisos.config(text=f"⚠️ Conferência antes de fechar: {qtd_avisos} aviso(s) — duplo clique numa linha para resolver")
                    frame_avisos.pack(fill=tk.X, pady=(0, 8), before=frame_tab)
                else:
                    frame_avisos.pack_forget()

        def resolver_aviso(event=None):
            sel = tree_av.focus()
            if not sel or sel not in mapa_avisos:
                return
            tipo, a = mapa_avisos[sel]
            if tipo == 'nao_contados':
                texto = simpledialog.askstring(
                    "Produto não contado",
                    f"{a['NomeProduto']}\n\nQuantos {a.get('Unidade') or 'UN'} havia na data da contagem?\n(digite 0 se tinha acabado)",
                    parent=popup)
                if texto is None:
                    return
                try:
                    qtd = para_decimal(texto, "Quantidade")
                except ValueError as e:
                    messagebox.showerror("Erro", str(e), parent=popup); return
                if database.adicionar_item_contagem_existente(contagem_id, a['ProdutoID'], qtd):
                    self.status(f"{a['NomeProduto']}: {fmt_qtd(qtd)} adicionado à contagem.")
                    recarregar()
                else:
                    messagebox.showerror("Erro", "Não foi possível adicionar o item à contagem (veja o log).", parent=popup)
            elif tipo == 'sem_custo':
                texto = simpledialog.askstring(
                    "Produto sem custo",
                    f"{a['NomeProduto']}\n\nCusto por {a.get('Unidade') or 'UN'} (R$):", parent=popup)
                if texto is None:
                    return
                try:
                    custo = para_decimal(texto, "Custo", permitir_zero=False)
                except ValueError as e:
                    messagebox.showerror("Erro", str(e), parent=popup); return
                if database.atualizar_custo_manual_produto(a['ProdutoID'], custo):
                    self.status(f"Custo de {a['NomeProduto']} gravado: {fmt_reais(custo)}.")
                    recarregar()
                else:
                    messagebox.showerror("Erro", "Não foi possível gravar o custo (veja o log).", parent=popup)
            elif tipo == 'avulsos':
                messagebox.showinfo("Item avulso", f"'{a['NomeProduto']}' foi contado sem produto do Catálogo e NÃO entra no valor.\n\n"
                                    "Vou abrir a janela 'Resolver Itens Avulsos'. Depois de resolver, clique em '🔄 Recalcular'.",
                                    parent=popup)
                self.abrir_gerenciador_avulsos()
            elif tipo == 'custo_suspeito':
                # [MELHORIA UX] abre direto nos vínculos DESTE produto; ao salvar, o valor é recalculado
                self.abrir_gestor_vinculos(produto_id=a['ProdutoID'], nome_produto=a['NomeProduto'], ao_salvar=recarregar)

        tree_av.bind("<Double-1>", resolver_aviso)

        def fechar_valor():
            dados = estado['dados']
            if not dados:
                return
            av = dados['avisos']
            qtd_avisos = sum(len(v) for v in av.values())
            texto = f"Fechar o valor do estoque desta contagem em {fmt_reais(dados['total'])}?\n\n" \
                    "Depois de fechado, o total NÃO muda mais (nem com notas novas).\n" \
                    "Você poderá reabrir se precisar corrigir."
            if qtd_avisos:
                texto = (f"⚠️ Ainda há {qtd_avisos} aviso(s) na conferência:\n"
                         f"  • {len(av['nao_contados'])} produto(s) não contado(s)\n"
                         f"  • {len(av['avulsos'])} item(ns) avulso(s)\n"
                         f"  • {len(av['sem_custo'])} produto(s) sem custo\n"
                         f"  • {len(av['custo_suspeito'])} custo(s) suspeito(s)\n\n") + texto
            if not messagebox.askyesno("Fechar valor do estoque", texto, icon='warning' if qtd_avisos else 'question', parent=popup):
                return
            ok, msg, total = database.fechar_valor_estoque(contagem_id)
            if ok:
                self.status(f"Valor do estoque fechado: {fmt_reais(total)} (contagem {nome_contagem} de {data_contagem}).")
                recarregar()
                self.atualizar_lista_contagens_historico()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        def reabrir_valor():
            dados = estado['dados']
            valor = fmt_reais(dados['total']) if dados else ''
            if not messagebox.askyesno(
                    "Reabrir valor",
                    f"Reabrir o valor desta contagem (hoje fechado em {valor})?\n\n"
                    "Ele será recalculado com os custos e quantidades ATUAIS e pode mudar.\n"
                    "Se você já lançou esse valor em outro lugar, lembre de corrigir lá também.",
                    icon='warning', parent=popup):
                return
            if database.reabrir_valor_estoque(contagem_id):
                self.status("Valor do estoque reaberto.", 'aviso')
                recarregar()
                self.atualizar_lista_contagens_historico()
            else:
                messagebox.showerror("Erro", "Não foi possível reabrir (veja o log).", parent=popup)

        def copiar_total():
            dados = estado['dados']
            if not dados:
                return
            texto = f"{Decimal(str(dados['total'])):.2f}".replace('.', ',')
            popup.clipboard_clear(); popup.clipboard_append(texto)
            self.status(f"Total {fmt_reais(dados['total'])} copiado. Cole com Ctrl+V onde for lançar.")

        def exportar_para_excel():
            dados = estado['dados']
            if not dados:
                return
            pd = self._importar_pandas(popup)
            if pd is None:
                return
            caminho_arquivo = filedialog.asksaveasfilename(
                parent=popup, title="Salvar Valor do Estoque", defaultextension=".xlsx",
                filetypes=[("Arquivos Excel", "*.xlsx")],
                initialfile=nome_arquivo_seguro(f"Valor_Estoque_{nome_contagem.replace(' ', '_')}_{data_contagem.replace('/', '-')}.xlsx"))
            if not caminho_arquivo:
                return
            try:
                linhas = [{'Categoria': it.get('Categoria') or 'Geral', 'Produto': it['NomeProduto'],
                           'Quantidade': float(it['Quantidade']), 'UN': it.get('Unidade') or 'UN',
                           'Custo Unitário (R$)': float(it['CustoUnitario']), 'Valor (R$)': float(it['ValorTotal']),
                           'Origem do custo': it.get('OrigemCusto') or ''} for it in dados['itens']]
                df = pd.DataFrame(linhas, columns=['Categoria', 'Produto', 'Quantidade', 'UN', 'Custo Unitário (R$)', 'Valor (R$)', 'Origem do custo'])
                df.loc[len(df)] = ['', '', None, '', None, None, '']
                df.loc[len(df)] = ['TOTAL', '', None, '', None, float(dados['total']), '']
                situacao = "FECHADO" if dados['fechado'] else "EM ABERTO (pode mudar)"
                resumo = pd.DataFrame([
                    {'Item': 'Contagem', 'Valor': f"{nome_contagem} ({data_contagem})"},
                    {'Item': 'Situação do valor', 'Valor': situacao},
                    {'Item': 'Método de custo', 'Valor': 'Custo médio ponderado das compras dos 90 dias até a data da contagem'},
                    {'Item': 'VALOR TOTAL DO ESTOQUE (R$)', 'Valor': float(dados['total'])},
                ] + [{'Item': f"Categoria: {c}", 'Valor': float(v)} for c, v in dados['por_categoria'].items()])
                with pd.ExcelWriter(caminho_arquivo, engine='openpyxl') as escritor:
                    resumo.to_excel(escritor, sheet_name='Resumo', index=False)
                    df.to_excel(escritor, sheet_name='Itens', index=False)
                    avisos = [{'Tipo': t, 'Produto': a['NomeProduto'], 'Detalhe': a.get('Detalhe', '')}
                              for t, lista in dados['avisos'].items() for a in lista]
                    if avisos:
                        pd.DataFrame(avisos).to_excel(escritor, sheet_name='Avisos', index=False)
                messagebox.showinfo("Sucesso", f"Valor do estoque exportado!\nSalvo em: {caminho_arquivo}", parent=popup)
            except Exception as e:
                logger.error(f"Erro ao exportar valor do estoque: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Não foi possível salvar o Excel.\n{e}\n\n"
                                     "Se o arquivo estiver aberto no Excel, feche-o e tente de novo.", parent=popup)

        ttk.Button(frame_bot, text="🔄 Recalcular", command=recarregar).pack(side=tk.LEFT, padx=3)
        btn_fechar = ttk.Button(frame_bot, text="🔒 Fechar valor", command=fechar_valor)
        btn_reabrir = ttk.Button(frame_bot, text="🔓 Reabrir", command=reabrir_valor)
        btn_copiar = ttk.Button(frame_bot, text="📋 Copiar total", command=copiar_total)
        btn_copiar.pack(side=tk.LEFT, padx=3)
        btn_exportar = ttk.Button(frame_bot, text="💾 Exportar para Excel", command=exportar_para_excel)
        btn_exportar.pack(side=tk.LEFT, padx=3)
        self._janela_valor = {'popup': popup, 'recarregar': recarregar, 'estado': estado, 'tree': tree,
                              'tree_av': tree_av, 'mapa_avisos': mapa_avisos, 'fechar': fechar_valor,
                              'reabrir': reabrir_valor, 'copiar': copiar_total, 'exportar': exportar_para_excel,
                              'lbl_total': lbl_total}
        recarregar()

    # ===================================================================
    # == ABA 5: SUGESTÃO DE COMPRA (ATUALIZADA) =========================
    # ===================================================================

    def _importar_pandas(self, janela_pai):
        """[DEPURAÇÃO] Antes, sem o pandas instalado, o botão dava erro e não fazia nada."""
        try:
            import pandas as pd
            return pd
        except ImportError:
            messagebox.showerror("Biblioteca Faltando",
                                 "Para exportar para Excel instale as bibliotecas:\n\npip install pandas openpyxl",
                                 parent=janela_pai)
            return None

    def exportar_folha_contagem_manual(self):
        """Gera um arquivo Excel estruturado por categorias e ordem alfabética para conferência física."""
        pd = self._importar_pandas(self.root)
        if pd is None:
            return

        # Busca os dados processados do banco
        dados_banco = database.buscar_produtos_para_folha_contagem()
        if not dados_banco:
            messagebox.showerror("Erro", "Nenhum produto encontrado no catálogo mestre.", parent=self.root)
            return

        # Abre a caixa de diálogo para escolher onde salvar o arquivo
        caminho_arquivo = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salvar Folha de Contagem Manual",
            defaultextension=".xlsx",
            filetypes=[("Arquivos Excel", "*.xlsx")],
            initialfile=f"Folha_Contagem_Manual_{datetime.now().strftime('%d-%m-%Y')}.xlsx"
        )

        if not caminho_arquivo:
            return

        try:
            # FILTRO MÁGICO: Remove caracteres de controle invisíveis que corrompem o MS Excel
            def limpar_texto(texto):
                if not texto: return ""
                # Substitui tudo que for sujeira invisível (hexadecimais de controle) por NADA
                return re.sub(r'[\x00-\x1f\x7f-\x9f]', '', str(texto)).strip()

            lista_exportacao = []
            for item in dados_banco:
                custo_puro = float(item['UltimoCusto'] or 0)  # [DEPURAÇÃO] vazio não trava
                
                lista_exportacao.append({
                    'Categoria': limpar_texto(item['Categoria']),
                    'ID': item['ProdutoID'],
                    'Nome do Produto Mestre': limpar_texto(item['NomeProduto']),
                    'UN': limpar_texto(item['UnidadeMedida']),
                    'Custo Unitário (c/ Imposto)': custo_puro,
                    'CONTAGEM FÍSICA (Quantidade)': '________________' 
                })

            df = pd.DataFrame(lista_exportacao)
            # engine='openpyxl' força a formatação estrita que o Windows exige
            df.to_excel(caminho_arquivo, index=False, engine='openpyxl')
            
            messagebox.showinfo("Sucesso", f"Folha de contagem gerada com sucesso!\n\nImprima a planilha para realizar a checagem manual.\n\nSalvo em: {caminho_arquivo}", parent=self.root)

        except ImportError:
            messagebox.showerror("Biblioteca Faltando", "Para gerar Excel, instale o openpyxl:\n\npip install openpyxl", parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao exportar folha de contagem manual: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível gerar a planilha Excel.\nErro: {e}", parent=self.root)


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
        # Criamos um sub-frame para o spinbox e o label "dias."
        frame_spin = ttk.Frame(frame_filtros)
        frame_spin.grid(row=1, column=1, sticky="w") # .grid() para o sub-frame

        self.spin_dias_cobertura = ttk.Spinbox(frame_spin, from_=1, to=365, width=5)
        self.spin_dias_cobertura.set("30") 
        self.spin_dias_cobertura.pack(side=tk.LEFT, padx=5) # .pack() dentro do sub-frame

        ttk.Label(frame_spin, text="dias.").pack(side=tk.LEFT) # .pack() dentro do sub-frame
        # --- FIM DA CORREÇÃO ---
        
        btn_gerar_sugestao = ttk.Button(frame_filtros, text="Gerar Sugestão de Compra", command=self.gerar_sugestao_compra)
        btn_gerar_sugestao.grid(row=1, column=2, columnspan=2, sticky="e", padx=5, pady=5, ipady=5)

        ttk.Separator(frame_filtros, orient="horizontal").grid(row=2, column=0, columnspan=4, sticky="ew", pady=10)

        # Filtros Inteligentes
        ttk.Label(frame_filtros, text="Filtro Categoria:").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        self.combo_sugestao_categoria = ttk.Combobox(frame_filtros, state="readonly", values=["Todas"] + self.lista_categorias)
        self.combo_sugestao_categoria.grid(row=3, column=1, sticky="ew", padx=5, pady=5)
        self.combo_sugestao_categoria.set("Todas")

        ttk.Label(frame_filtros, text="Filtro Fornecedor:").grid(row=3, column=2, sticky="w", padx=10, pady=5)
        self.combo_sugestao_fornecedor = ttk.Combobox(frame_filtros, state="readonly")
        self.combo_sugestao_fornecedor.grid(row=3, column=3, sticky="ew", padx=5, pady=5)
        self.combo_sugestao_fornecedor.set("Todos")

        self.var_ocultar_zeros = tk.BooleanVar(value=False)
        self.check_ocultar_zeros = ttk.Checkbutton(frame_filtros, text="Ocultar itens que não precisam de compra (Sugestão = 0)", variable=self.var_ocultar_zeros)
        self.check_ocultar_zeros.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=5)
        # --- FIM DO FRAME DE FILTROS ---

        # Botão Gerenciador de Buffet
        btn_gerir_buffet = ttk.Button(frame_filtros, text="🍦 Gerenciar Buffet (Top Sabores)", command=self.abrir_gestor_buffet)
        btn_gerir_buffet.grid(row=4, column=2, columnspan=2, sticky="e", padx=5, pady=5)

        # [MELHORIA UX] Resumo colorido + botão que transforma a sugestão em PEDIDO
        frame_acoes_sug = ttk.Frame(frame_filtros)
        frame_acoes_sug.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(5, 0))
        self.lbl_resumo_sugestao = ttk.Label(frame_acoes_sug, text="Clique em 'Gerar Sugestão de Compra' para ver a posição do estoque.",
                                             font=("Arial", 10, "bold"))
        self.lbl_resumo_sugestao.pack(side=tk.LEFT)
        ttk.Button(frame_acoes_sug, text="📤 Montar Pedido por Fornecedor",
                   command=self.abrir_pedido_compra).pack(side=tk.RIGHT, ipady=4)
        self.dados_sugestao_tela = {}

        # --- Frame 2: Tabela de Sugestões (Mesma de antes, mas o bind foi movido) ---
        frame_resultado = ttk.LabelFrame(main_frame, text="Relatório de Posição de Estoque e Sugestão (Duplo-clique para ver histórico de compras)", padding="10")
        frame_resultado.grid(row=1, column=0, sticky="nsew")
        frame_resultado.rowconfigure(0, weight=1)
        frame_resultado.columnconfigure(0, weight=1)
        
    # [ATUALIZAÇÃO] Adicionada coluna 'Duração (Meses)'
        cols = ('Produto', 'UN', 'Estoque Atual', 'Total Comprado', 'Consumo Médio/Mês', 'Consumo Médio/Dia', 'Duração (Meses)', 'Sugestão Compra', 'Status')
        self.tree_sugestao = ttk.Treeview(frame_resultado, columns=cols, show='headings')
        for col in cols: 
            # Acopla a função de ordenação inteligente ao clique de cada cabeçalho
            self.tree_sugestao.heading(
                col, 
                text=col, 
                command=lambda c=col: self.ordenar_coluna_treeview(self.tree_sugestao, c, False)
            )

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
        # [MELHORIA UX] Cores por situação do item
        self.tree_sugestao.tag_configure('critico', background='#ffd6d6')
        self.tree_sugestao.tag_configure('comprar', background='#fff4cc')
        self.tree_sugestao.tag_configure('ok', background='#e3f5e1')
        self.tree_sugestao.tag_configure('sem_giro', background='#eeeeee', foreground='#666666')

    def gerar_sugestao_compra(self):
        """Busca o relatório do banco baseado no período selecionado e calcula a sugestão."""
        try:
            # Validação robusta do Spinbox agora em DIAS
            valor_spin = self.spin_dias_cobertura.get().strip()
            if not valor_spin.isdigit() or int(valor_spin) <= 0: 
                dias_para_cobrir = 30 # Padrão seguro de 1 mês
                self.spin_dias_cobertura.set("30")
            else:
                dias_para_cobrir = int(valor_spin)

            # Converte direto para Decimal usando os dias exatos solicitados
            dias_cobertura = Decimal(dias_para_cobrir)

            str_contagem_inicio = self.combo_contagem_inicio.get()
            str_contagem_fim = self.combo_contagem_fim.get()
            
            if not str_contagem_inicio or not str_contagem_fim:
                messagebox.showwarning("Aviso", "Selecione uma Contagem Inicial (Ponto A) e uma Contagem Final (Ponto B).", parent=self.root)
                return

            contagem_id_inicio = self.mapa_contagens_sugestao[str_contagem_inicio]
            contagem_id_fim = self.mapa_contagens_sugestao[str_contagem_fim]

        except (ValueError, KeyError) as e:
            messagebox.showerror("Erro de Seleção", f"Parâmetros inválidos. Verifique suas seleções.\n{e}", parent=self.root)
            return

        for i in self.tree_sugestao.get_children():
            self.tree_sugestao.delete(i)
        self.dados_sugestao_tela = {}
        contadores = {'critico': 0, 'comprar': 0, 'ok': 0, 'sem_giro': 0}

        try:
            # Chama a função corrigida do database, que já retorna Decimals prontos
            relatorio_posicao = database.gerar_sugestao_por_periodo(contagem_id_inicio, contagem_id_fim)
            self.cache_relatorio_posicao.clear()

            if not relatorio_posicao:
                messagebox.showinfo("Aviso", "Nenhum produto encontrado ou erro de processamento.", parent=self.root)
                return

            # Captura o estado dos filtros
            categoria_filtro = self.combo_sugestao_categoria.get()
            forn_filtro_str = self.combo_sugestao_fornecedor.get()
            ocultar_zeros = self.var_ocultar_zeros.get()

            # Se filtrou por fornecedor, busca quais IDs de produto pertencem a ele
            ids_produtos_fornecedor = None
            if forn_filtro_str and forn_filtro_str != "Todos":
                try:
                    inicio_id = forn_filtro_str.rfind("ID: ")
                    if inicio_id != -1:
                        str_id = forn_filtro_str[inicio_id + 4:].replace(")", "").strip()
                        forn_id = int(str_id)
                        ids_produtos_fornecedor = database.buscar_ids_produtos_por_fornecedor(forn_id)
                except (IndexError, ValueError) as e:
                    logger.warning(f"Falha ao extrair ID do fornecedor do texto '{forn_filtro_str}': {e}")
                    pass # Continua sem aplicar o filtro em caso de falha de string

            def dec(valor):
                return Decimal(str(valor)) if valor is not None else Decimal('0')

            ids_na_tela = set()
            for item in relatorio_posicao:
                # 1. Filtro de Categoria
                if categoria_filtro != "Todas" and (item.get('Categoria') or 'Geral') != categoria_filtro:
                    continue
                # [DEPURAÇÃO] o mesmo produto 2x na lista dava TclError e a tabela ficava pela metade
                iid_item = str(item['ProdutoID'])
                if iid_item in ids_na_tela:
                    continue

                # 2. Filtro de Fornecedor
                if ids_produtos_fornecedor is not None and item['ProdutoID'] not in ids_produtos_fornecedor:
                    continue

                # Armazena no cache para o recurso de duplo-clique (histórico)
                self.cache_relatorio_posicao[item['ProdutoID']] = item

                # Extração direta dos dados já calculados no database.py
                nome = item.get('NomeProduto') or ''
                un = item.get('Unidade') or 'UN'
                atual = dec(item.get('EstoqueAtual'))
                umd = dec(item.get('UsoMedioDiario'))
                minimo = dec(item.get('EstoqueMinimo'))
                total_comprado = dec(item.get('TotalComprado'))

                # Cálculo de apresentação: Consumo Mensal
                consumo_mes = umd * 30

                # Cálculo da Sugestão de Compra
                # Estoque Ideal = (Consumo Diário * Dias a Cobrir) + Estoque de Segurança
                estoque_ideal = (umd * dias_cobertura) + minimo
                sugestao_calc = estoque_ideal - atual

                # A sugestão não pode ser negativa
                sugestao_compra = max(sugestao_calc, Decimal('0.0'))

                # 3. Filtro de Zeros (Ocultar o que não precisa comprar)
                if ocultar_zeros and sugestao_compra <= 0:
                    continue

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

                # [MELHORIA UX] Situação calculada (antes o banco mandava sempre "OK").
                #   🔴 CRÍTICO: estoque abaixo do mínimo, ou acaba em menos de 7 dias
                #   🟡 COMPRAR: precisa comprar para cobrir o período escolhido
                #   🟢 OK: estoque suficiente   ⚪ SEM GIRO: não teve consumo no período
                dias_restantes = (atual / umd) if umd > 0 else None
                if umd <= 0 and sugestao_compra <= 0:
                    situacao, tag = "⚪ SEM GIRO", 'sem_giro'
                elif (minimo > 0 and atual <= minimo) or (dias_restantes is not None and dias_restantes < 7):
                    situacao, tag = "🔴 CRÍTICO", 'critico'
                elif sugestao_compra > 0:
                    situacao, tag = "🟡 COMPRAR", 'comprar'
                else:
                    situacao, tag = "🟢 OK", 'ok'
                contadores[tag] += 1

                # Insere na Treeview
                self.tree_sugestao.insert("", "end", values=(
                    nome, un, atual_f, total_comprado_f, consumo_mes_f, umd_f, duracao_f, sugestao_f, situacao
                ), iid=iid_item, tags=(tag,))
                ids_na_tela.add(iid_item)
                self.dados_sugestao_tela[item['ProdutoID']] = {
                    'nome': nome, 'un': un, 'sugestao': sugestao_compra, 'situacao': situacao}

            self.lbl_resumo_sugestao.config(
                text=f"🔴 {contadores['critico']} crítico(s)   🟡 {contadores['comprar']} para comprar   "
                     f"🟢 {contadores['ok']} ok   ⚪ {contadores['sem_giro']} sem giro")
            self.status(f"Sugestão gerada para {dias_para_cobrir} dias: {len(ids_na_tela)} produtos na tabela.")

        except Exception as e:
            logger.error(f"Erro ao gerar sugestão de compra (Frontend): {e}", exc_info=True)
            messagebox.showerror("Erro de Processamento", f"Falha ao exibir relatório:\n{e}", parent=self.root)

    # -------------------------------------------------------------------
    # [MELHORIA UX] PEDIDO DE COMPRA POR FORNECEDOR
    # -------------------------------------------------------------------
    def montar_pedido_por_fornecedor(self):
        """
        Agrupa os itens da sugestão (com quantidade > 0) pelo fornecedor da ÚLTIMA compra.
        Devolve {fornecedor: [ {nome, un, qtd, custo, total}, ... ]}.
        """
        pedido = {}
        for produto_id, dados in self.dados_sugestao_tela.items():
            qtd = qtd_para_pedido(dados['sugestao'], dados['un'])
            if qtd <= 0:
                continue
            fornecedor, custo = "Sem fornecedor (nunca comprado)", Decimal('0')
            try:
                historico = database.buscar_historico_compras_produto(produto_id) or []
                # [MELHORIA VALOR] ignora as "notas fantasmas" do custo manual (quantidade 0,
                # fornecedor "PRODUÇÃO INTERNA / AVULSO"): ninguém compra desse fornecedor.
                reais = [h for h in historico
                         if Decimal(str(getattr(h, 'Quantidade', 0) or 0)) > 0
                         and 'PRODUÇÃO INTERNA' not in str(getattr(h, 'NomeFantasia', '') or '').upper()]
                if reais:
                    ultima = reais[0]  # o banco devolve da mais nova para a mais antiga
                    fornecedor = getattr(ultima, 'NomeFantasia', None) or fornecedor
                    custo = Decimal(str(getattr(ultima, 'PrecoCustoUnitario', 0) or 0))
            except Exception as e:
                logger.warning(f"Não foi possível ver o último fornecedor do produto {produto_id}: {e}")
            pedido.setdefault(fornecedor, []).append({
                'nome': dados['nome'], 'un': dados['un'], 'qtd': qtd,
                'custo': custo, 'total': qtd * custo, 'situacao': dados.get('situacao', '')})
        for itens in pedido.values():
            itens.sort(key=lambda i: sem_acento(i['nome']))
        return dict(sorted(pedido.items(), key=lambda kv: (kv[0].startswith("Sem fornecedor"), sem_acento(kv[0]))))

    @staticmethod
    def texto_pedido_whatsapp(fornecedor, itens):
        """Mensagem pronta para colar no WhatsApp do fornecedor."""
        empresa = getattr(config, 'NOME_EMPRESA', '') or ''
        linhas = [f"Olá, {fornecedor}! Tudo bem?", "",
                  "Gostaria de fazer o seguinte pedido:", ""]
        for i in itens:
            linhas.append(f"• {fmt_qtd(i['qtd'])} {i['un']} - {i['nome']}")
        linhas += ["", "Pode me confirmar a disponibilidade, o valor e o prazo de entrega?", "Obrigado!"]
        if empresa:
            linhas.append(empresa)
        return "\n".join(linhas)

    def abrir_pedido_compra(self):
        if not self.dados_sugestao_tela:
            messagebox.showwarning("Aviso", "Primeiro clique em 'Gerar Sugestão de Compra'.", parent=self.root)
            return
        self.root.config(cursor="watch"); self.root.update_idletasks()
        try:
            pedido = self.montar_pedido_por_fornecedor()
        finally:
            self.root.config(cursor="")
        if not pedido:
            messagebox.showinfo("Nada para comprar", "Pela sugestão atual, nenhum produto precisa ser comprado. 🎉", parent=self.root)
            return
        self.ultimo_pedido = pedido

        popup = Toplevel(self.root)
        popup.title("📤 Pedido de Compra por Fornecedor")
        popup.geometry("760x560")
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        total_geral = sum(i['total'] for itens in pedido.values() for i in itens)
        ttk.Label(frame, text=f"{len(pedido)} fornecedor(es) · valor estimado {fmt_reais(total_geral)} "
                              "(pelo último custo pago)", font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Escolha o fornecedor, confira a mensagem (dá para editar) e clique em Copiar. "
                              "Depois é só colar no WhatsApp.", foreground="gray").pack(anchor="w", pady=(0, 8))

        opcoes = [f"{f}  ({len(itens)} itens · {fmt_reais(sum(i['total'] for i in itens))})" for f, itens in pedido.items()]
        mapa = dict(zip(opcoes, pedido.keys()))
        combo = ttk.Combobox(frame, values=opcoes, state="readonly")
        combo.pack(fill=tk.X)
        texto = tk.Text(frame, height=18, wrap="word", font=("Consolas", 10))
        texto.pack(fill=tk.BOTH, expand=True, pady=8)

        def mostrar(event=None):
            fornecedor = mapa.get(combo.get())
            if fornecedor is None:
                return
            texto.delete("1.0", tk.END)
            texto.insert("1.0", self.texto_pedido_whatsapp(fornecedor, pedido[fornecedor]))

        def copiar():
            conteudo = texto.get("1.0", tk.END).strip()
            popup.clipboard_clear()
            popup.clipboard_append(conteudo)
            self.status(f"Pedido de '{mapa.get(combo.get(), '')}' copiado. Cole no WhatsApp com Ctrl+V.")

        def salvar_excel():
            self.exportar_pedido_excel(pedido, popup)

        combo.bind("<<ComboboxSelected>>", mostrar)
        combo.set(opcoes[0]); mostrar()

        botoes = ttk.Frame(frame)
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="📋 Copiar mensagem", command=copiar).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5), ipady=4)
        ttk.Button(botoes, text="💾 Salvar Excel (todos os fornecedores)", command=salvar_excel).pack(side=tk.LEFT, expand=True, fill=tk.X, ipady=4)

    def exportar_pedido_excel(self, pedido, janela_pai=None):
        """Excel com uma aba de resumo e uma aba para cada fornecedor."""
        pai = janela_pai or self.root
        pd = self._importar_pandas(pai)
        if pd is None:
            return None
        caminho = filedialog.asksaveasfilename(
            parent=pai, title="Salvar Pedido de Compra", defaultextension=".xlsx",
            filetypes=[("Arquivos Excel", "*.xlsx")],
            initialfile=f"Pedido_Compra_{datetime.now():%d-%m-%Y}.xlsx")
        if not caminho:
            return None
        try:
            usados = set()
            resumo = [{'Fornecedor': f, 'Qtd de itens': len(itens),
                       'Valor estimado (R$)': float(sum(i['total'] for i in itens))} for f, itens in pedido.items()]
            with pd.ExcelWriter(caminho, engine='openpyxl') as escritor:
                pd.DataFrame(resumo).to_excel(escritor, sheet_name=nome_aba_excel('Resumo', usados), index=False)
                for fornecedor, itens in pedido.items():
                    linhas = [{'Produto': i['nome'], 'Quantidade': float(i['qtd']), 'UN': i['un'],
                               'Último custo (R$)': float(i['custo']), 'Total estimado (R$)': float(i['total']),
                               'Situação': i['situacao']} for i in itens]
                    pd.DataFrame(linhas).to_excel(escritor, sheet_name=nome_aba_excel(fornecedor, usados), index=False)
            self.status(f"Pedido salvo em: {caminho}")
            messagebox.showinfo("Pedido salvo", f"Pedido de compra salvo em:\n{caminho}", parent=pai)
            return caminho
        except Exception as e:
            logger.error(f"Erro ao exportar pedido de compra: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível salvar o Excel.\n{e}\n\n"
                                 "Se o arquivo estiver aberto no Excel, feche-o e tente de novo.", parent=pai)
            return None

    def popular_combos_contagem_sugestao(self):
        """Atualiza os combos da Aba 5 com os dados mais recentes da Aba 4."""
        try:
            contagens = database.listar_contagens_cabecalho() or []
            # [DEPURAÇÃO] dicionário próprio da aba 5 (antes dividia com a aba 4)
            selecao_ini_antiga = self.combo_contagem_inicio.get()
            selecao_fim_antiga = self.combo_contagem_fim.get()
            self.mapa_contagens_sugestao.clear()

            # Limpa os combos preventivamente
            self.combo_contagem_inicio.set('')
            self.combo_contagem_fim.set('')
            self.combo_contagem_inicio['values'] = []
            self.combo_contagem_fim['values'] = []

            # --- NOVA OPÇÃO ESPECIAL ---
            opcao_primeira_compra = "⏮️ DESDE A PRIMEIRA COMPRA (Histórico Completo)"
            self.mapa_contagens_sugestao[opcao_primeira_compra] = -1 # Código especial -1
            
            nomes_contagens = []
            
            # Adiciona as contagens físicas reais
            for c in contagens:
                data_f = fmt_data(c.DataContagem)  # [DEPURAÇÃO] data em texto travava os combos
                nome_contagem_db = getattr(c, 'NomeContagem', 'Geral')
                if not nome_contagem_db: nome_contagem_db = 'Geral'
                
                nome_display = f"ID: {c.ContagemID} - {data_f} - {nome_contagem_db} ({c.NomeCompleto})"
                nomes_contagens.append(nome_display)
                self.mapa_contagens_sugestao[nome_display] = c.ContagemID

            # Configura Combo Final (Apenas contagens reais, pois "Hoje" é sempre uma contagem física)
            self.combo_contagem_fim['values'] = nomes_contagens
            
            # Configura Combo Inicial (Contagens Reais + Opção Especial no topo)
            self.combo_contagem_inicio['values'] = [opcao_primeira_compra] + nomes_contagens

            # Lógica inteligente de seleção padrão
            # [DEPURAÇÃO] Mantém o que o usuário já tinha escolhido (antes, trocar de aba e voltar
            # apagava a escolha dos combos).
            if nomes_contagens:
                self.combo_contagem_fim.set(selecao_fim_antiga if selecao_fim_antiga in self.mapa_contagens_sugestao else nomes_contagens[0])
                self.combo_contagem_inicio.set(selecao_ini_antiga if selecao_ini_antiga in self.mapa_contagens_sugestao else opcao_primeira_compra)

            # Preenche o filtro de Fornecedores
            fornecedores = database.listar_fornecedores() or []
            nomes_forn = ["Todos"] + [f"{f.NomeFantasia} (ID: {f.FornecedorID})" for f in fornecedores]
            if hasattr(self, 'combo_sugestao_fornecedor'):
                self.combo_sugestao_fornecedor['values'] = nomes_forn

        except Exception as e:
            logger.error(f"Erro ao popular combos de contagem (Aba 5): {e}", exc_info=True)


    def abrir_gestor_buffet(self):
        """Abre o painel de gestão inteligente do Buffet (Regra Fixos/Rotativos)."""
        # [DEPURAÇÃO] O arquivo era salvo na "pasta atual" do terminal. Abrindo o programa
        # por um atalho (outra pasta), a seleção de sabores "sumia". Agora fica sempre
        # na pasta do programa (e ainda lê o arquivo antigo, se existir).
        ARQUIVO_CONFIG_BUFFET = os.path.join(PASTA_DO_PROGRAMA, 'config_sabores_buffet.json')
        ARQUIVO_ANTIGO = os.path.abspath('config_sabores_buffet.json')

        # Funções internas para gerenciar o "Cérebro" de seleção
        def carregar_ids_salvos():
            for caminho in (ARQUIVO_CONFIG_BUFFET, ARQUIVO_ANTIGO):
                if os.path.exists(caminho):
                    try:
                        with open(caminho, 'r', encoding='utf-8') as f:
                            dados = json.load(f)
                        return [int(x) for x in dados] if isinstance(dados, list) else []
                    except (OSError, ValueError, TypeError) as e:
                        logger.warning(f"Arquivo de sabores do buffet ilegível ({caminho}): {e}")
            return []

        def salvar_ids_config(lista_ids):
            with open(ARQUIVO_CONFIG_BUFFET, 'w', encoding='utf-8') as f:
                json.dump(lista_ids, f)

        popup = Toplevel(self.root)
        popup.title("🍦 Gerenciador Inteligente de Buffet")
        popup.geometry("1000x600")
        popup.transient(self.root)

        # --- Controle Superior ---
        frame_topo = ttk.Frame(popup, padding="15")
        frame_topo.pack(fill=tk.X)

        ttk.Label(frame_topo, text="Analisar últimos:").pack(side=tk.LEFT)
        spin_dias = ttk.Spinbox(frame_topo, from_=30, to=365, width=5)
        spin_dias.set(90)
        spin_dias.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_topo, text="dias.").pack(side=tk.LEFT)

        ttk.Label(frame_topo, text="| Vagas FIXAS:").pack(side=tk.LEFT, padx=(10, 5))
        spin_vagas = ttk.Spinbox(frame_topo, from_=1, to=100, width=5)
        spin_vagas.set(36)
        spin_vagas.pack(side=tk.LEFT, padx=5)

        btn_processar = ttk.Button(frame_topo, text="🔄 Atualizar Tabela", command=lambda: gerar_analise())
        btn_processar.pack(side=tk.LEFT, padx=10)

        # NOVO BOTÃO: SELETOR MANUAL
        btn_seletor = ttk.Button(frame_topo, text="🛠️ Selecionar Sabores do Buffet", command=lambda: abrir_seletor_manual())
        btn_seletor.pack(side=tk.RIGHT, padx=5)

        # --- Tabela ---
        frame_tabela = ttk.Frame(popup, padding="10")
        frame_tabela.pack(fill=tk.BOTH, expand=True)

        cols = ('Posição', 'Status no Buffet', 'Sabor (Produto Mestre)', 'Unidades Compradas', 'UMD (Consumo/Dia)')
        tree = ttk.Treeview(frame_tabela, columns=cols, show='headings', selectmode='none')

        tree.heading('Posição', text='#'); tree.column('Posição', width=40, anchor='center')
        tree.heading('Status no Buffet', text='Status no Buffet'); tree.column('Status no Buffet', width=150, anchor='center')
        tree.heading('Sabor (Produto Mestre)', text='Sabor (Produto Mestre)'); tree.column('Sabor (Produto Mestre)', width=350)
        tree.heading('Unidades Compradas', text='Unid. Compradas'); tree.column('Unidades Compradas', width=150, anchor='center')
        tree.heading('UMD (Consumo/Dia)', text='UMD (Velocidade Diária)'); tree.column('UMD (Consumo/Dia)', width=150, anchor='center')

        tree.tag_configure('fixo', background='#e6f4ea')
        tree.tag_configure('rotativo', background='#fff3cd')

        sb = ttk.Scrollbar(frame_tabela, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def gerar_analise():
            for i in tree.get_children(): tree.delete(i)

            ids_permitidos = carregar_ids_salvos()

            # Se o arquivo não existir ou estiver vazio, avisa o usuário
            if not ids_permitidos:
                tree.insert("", "end", values=("", "⚠️ Nenhum sabor selecionado.", "Clique em 'Selecionar Sabores' acima para começar.", "", ""))
                return

            try:
                dias = int(spin_dias.get())
                vagas = int(spin_vagas.get())
                if dias <= 0 or vagas <= 0: raise ValueError
            except ValueError:
                messagebox.showerror("Erro", "Dias e Vagas devem ser números inteiros maiores que zero.", parent=popup)
                return

            dados = database.gerar_ranking_sabores_buffet(dias, ids_permitidos)

            if not dados:
                tree.insert("", "end", values=("", "Sem dados de compra neste período.", "Nenhum dos sabores selecionados foi comprado nesses dias.", "", ""))
                return

            for index, item in enumerate(dados):
                posicao = index + 1
                if posicao <= vagas:
                    status, tag = "⭐ FIXO", "fixo"
                else:
                    status, tag = "🔄 ROTATIVO", "rotativo"

                umd_fmt = f"{float(item['UMD'] or 0):.4f}"
                comprado_fmt = f"{float(item['TotalComprado'] or 0):.2f}".rstrip('0').rstrip('.')

                tree.insert("", "end", values=(posicao, status, item['NomeProduto'], comprado_fmt, umd_fmt), tags=(tag,))

        def abrir_seletor_manual():
            """Abre uma sub-janela com Checklist para você escolher os produtos reais do Buffet."""
            win_sel = Toplevel(popup)
            win_sel.title("Selecione os Produtos que vão para o Buffet")
            win_sel.geometry("500x600")
            win_sel.transient(popup)
            win_sel.grab_set() # Foca o mouse apenas aqui

            ttk.Label(win_sel, text="Marque na lista os verdadeiros sorvetes de massa do Buffet:\n(Pressione e arraste ou clique para marcar vários)", font=("Arial", 10, "bold")).pack(pady=10, padx=10, anchor="w")

            # Lista com Scroll
            frame_list = ttk.Frame(win_sel, padding="10")
            frame_list.pack(fill=tk.BOTH, expand=True)

            sb_list = ttk.Scrollbar(frame_list, orient="vertical")

            # selectmode=tk.MULTIPLE permite clicar em vários sem precisar segurar o CTRL
            listbox = tk.Listbox(frame_list, selectmode=tk.MULTIPLE, yscrollcommand=sb_list.set, font=("Arial", 10))
            sb_list.config(command=listbox.yview)
            listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb_list.pack(side=tk.RIGHT, fill=tk.Y)

            # Busca todos os produtos do estoque e organiza em ordem alfabética
            produtos = database.listar_produtos_estoque() or []
            produtos_ordenados = sorted(produtos, key=lambda x: (x.NomeProduto or '').lower())

            mapa_indice_id = {}
            ids_salvos = carregar_ids_salvos()

            for idx, p in enumerate(produtos_ordenados):
                # Mostra o nome do produto na lista
                listbox.insert(tk.END, f"{p.NomeProduto} (Cat: {getattr(p, 'Categoria', None) or 'Geral'})")
                # Salva o ID verdadeiro dele escondido na memória
                mapa_indice_id[idx] = p.ProdutoID

                # Se ele já estava selecionado antes, já deixa azulzinho
                if p.ProdutoID in ids_salvos:
                    listbox.selection_set(idx)

            def salvar_selecao():
                selecionados_idx = listbox.curselection()
                # Converte a seleção da tela para os IDs verdadeiros do banco
                ids_para_salvar = [mapa_indice_id[i] for i in selecionados_idx]

                try:
                    salvar_ids_config(ids_para_salvar)
                except OSError as e:
                    messagebox.showerror("Erro", f"Não foi possível salvar a seleção:\n{e}", parent=win_sel)
                    return
                messagebox.showinfo("Sucesso", f"{len(ids_para_salvar)} sabores configurados para análise de Buffet!", parent=win_sel)

                win_sel.destroy()
                gerar_analise() # Atualiza a tabela na mesma hora!

            ttk.Button(win_sel, text="💾 Salvar Seleção", command=salvar_selecao).pack(pady=15, fill=tk.X, padx=20, ipady=5)

        # Roda a primeira vez automaticamente
        gerar_analise()

    def abrir_popup_historico_compras(self, event):
        selecionado = self.tree_sugestao.focus()
        if not selecionado: return
        try: produto_id = int(selecionado)
        except ValueError: return

        dados_produto = self.cache_relatorio_posicao.get(produto_id)
        if not dados_produto:
            messagebox.showwarning("Aviso", "Gere a sugestão novamente para atualizar o cache.", parent=self.root)
            return

        nome_produto = dados_produto['NomeProduto']
        popup = Toplevel(self.root)
        popup.title(f"Histórico e Correção de Compras - {nome_produto}")
        popup.geometry("850x500")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # CORREÇÃO LÓGICA: Substituído .pack() por .grid() para não conflitar com a Treeview e Scrollbar que também usam grid no mesmo frame.
        ttk.Label(frame, text="⚠️ DICA: Dê um duplo-clique em uma linha para corrigir quantidades e custos antigos importados com fator errado.", foreground="red", font=("Arial", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        # Adicionado o ItemNotaID invisível na tabela
        cols_hist = ('Data Compra', 'NF', 'Fornecedor', 'Qtd', 'Custo Unit.', 'ItemNotaID')
        tree_hist = criar_tree_zebrada(frame, columns=cols_hist, show='headings', selectmode='browse')

        tree_hist.heading('Data Compra', text='Data Compra'); tree_hist.column('Data Compra', width=100, anchor='center')
        tree_hist.heading('NF', text='NF'); tree_hist.column('NF', width=80, anchor='center')
        tree_hist.heading('Fornecedor', text='Fornecedor'); tree_hist.column('Fornecedor', width=250)
        tree_hist.heading('Qtd', text='Qtd'); tree_hist.column('Qtd', width=80, anchor='e')
        tree_hist.heading('Custo Unit.', text='Custo Unit.'); tree_hist.column('Custo Unit.', width=100, anchor='e')
        tree_hist.heading('ItemNotaID', text='ID Oculto'); tree_hist.column('ItemNotaID', width=0, stretch=tk.NO)

        sb = ttk.Scrollbar(frame, orient="vertical", command=tree_hist.yview)
        tree_hist.configure(yscrollcommand=sb.set)
        tree_hist.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        def carregar_dados():
            for i in tree_hist.get_children(): tree_hist.delete(i)
            try:
                historico = database.buscar_historico_compras_produto(produto_id)
                for compra in historico or []:
                    data_f = fmt_data(compra.DataEmissao, vazio="--/--/----")
                    qtd_f = fmt_num(compra.Quantidade, 3, "0.000")
                    custo_f = f"R$ {fmt_num(compra.PrecoCustoUnitario, 4, '0.0000')}"
                    item_id = compra.ItemNotaID # O ID que criamos no banco

                    tree_hist.insert("", "end", values=(data_f, compra.NumeroNF, compra.NomeFantasia, qtd_f, custo_f, item_id))
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao carregar histórico: {e}", parent=popup)

        def editar_linha(event_tree):
            sel = tree_hist.focus()
            if not sel: return
            vals = tree_hist.item(sel, 'values')
            data_nf, num_nf, qtd_atual, custo_atual, item_nota_id = vals[0], vals[1], vals[3], vals[4], vals[5]

            edit_win = Toplevel(popup)
            edit_win.title(f"Corrigir NF {num_nf} ({data_nf})")
            edit_win.geometry("300x200")
            edit_win.transient(popup)

            ttk.Label(edit_win, text="Qtd Exata que Entrou na Loja:").pack(pady=(10,2))
            e_qtd = ttk.Entry(edit_win, justify="center")
            e_qtd.pack(pady=2)
            # [DEPURAÇÃO] BUG GRAVE: a tabela mostra "12.500" (ponto = decimal) e o código antigo
            # APAGAVA o ponto -> a caixinha vinha com 12500. O custo "R$ 10.5000" virava 105000.
            # Bastava abrir e clicar em Salvar para multiplicar a nota por 1000!
            e_qtd.insert(0, qtd_atual.strip())

            ttk.Label(edit_win, text="Custo da Unidade (R$):").pack(pady=(10,2))
            e_custo = ttk.Entry(edit_win, justify="center")
            e_custo.pack(pady=2)
            e_custo.insert(0, custo_atual.replace("R$", "").strip())

            def salvar():
                try:
                    n_qtd = para_decimal(e_qtd.get(), "Quantidade")
                    n_custo = para_decimal(e_custo.get(), "Custo")
                    
                    if database.atualizar_item_historico_compra(item_nota_id, n_qtd, n_custo):
                        edit_win.destroy()
                        carregar_dados() # Recarrega a tabelinha
                        # Mostra um aviso pro gestor recalcular a tela de trás
                        messagebox.showinfo("Sucesso", "Histórico corrigido!\nClique em 'Gerar Sugestão' novamente para ver a matemática atualizada.", parent=popup)
                    else:
                        messagebox.showerror("Erro", "Falha ao gravar no banco.", parent=edit_win)
                except ValueError as ve:
                    messagebox.showerror("Erro", str(ve), parent=edit_win)

            ttk.Button(edit_win, text="💾 Salvar Correção", command=salvar).pack(pady=15)

        tree_hist.bind("<Double-1>", editar_linha)
        carregar_dados()

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
        self.tree_solicitacoes = criar_tree_zebrada(frame_lista, columns=cols, show='headings', selectmode='browse')
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
        self._limpar_detalhes_solicitacao()

        try:
            dados = database.listar_solicitacoes_pendentes() or []
        except Exception as e:  # [DEPURAÇÃO] essa função do banco não trata erros sozinha
            logger.error(f"Erro ao listar solicitações: {e}", exc_info=True)
            dados = []
        # Colunas SQL: 0:ID, 1:Nome, 2:Tipo, 3:Cat, 4:Desc, 5:Qtd, 6:Foto, 7:Data
        self.cache_solicitacoes = {int(row[0]): row for row in dados}
        
        for row in dados:
            data_fmt = fmt_data(row[7], '%d/%m %H:%M', vazio="")
            self.tree_solicitacoes.insert("", "end", values=(row[0], row[1], row[2], row[3], data_fmt))

    def _limpar_detalhes_solicitacao(self):
        self.solicitacao_atual_id = None
        self.solicitacao_atual_foto = None
        self.lbl_solic_detalhes.config(state='normal')
        self.lbl_solic_detalhes.delete("1.0", tk.END)
        self.lbl_solic_detalhes.config(state='disabled')
        self.btn_ver_foto_solic.config(state='disabled')

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
        texto += f"Data: {fmt_data(dados[7], '%d/%m/%Y %H:%M')}\n\n"
        texto += f"DESCRIÇÃO:\n{dados[4]}\n"
        if dados[5]: texto += f"\nQuantidade: {dados[5]}"
        
        self.lbl_solic_detalhes.config(state='normal')
        self.lbl_solic_detalhes.delete("1.0", tk.END)
        self.lbl_solic_detalhes.insert("1.0", texto)
        self.lbl_solic_detalhes.config(state='disabled')
        
        if dados[6]:
            self.solicitacao_atual_foto = dados[6]
            self.btn_ver_foto_solic.config(state='normal')
        else:
            self.solicitacao_atual_foto = None
            self.btn_ver_foto_solic.config(state='disabled')

    def ver_foto_solicitacao(self):
        caminho = self.solicitacao_atual_foto
        # [DEPURAÇÃO] a foto é salva pelo bot; se o caminho for relativo, procura também na pasta do programa
        if caminho and not os.path.isabs(caminho) and not os.path.exists(caminho):
            caminho = os.path.join(PASTA_DO_PROGRAMA, caminho)
        if caminho and os.path.exists(caminho):
            file_utils.abrir_arquivo(caminho)
        else:
            messagebox.showerror("Erro", "Arquivo de foto não encontrado no disco.", parent=self.root)

    def _mudar_status_solicitacao(self, novo_status, motivo=None):
        try:
            return database.atualizar_status_solicitacao(self.solicitacao_atual_id, novo_status, motivo)
        except Exception as e:  # [DEPURAÇÃO] antes um erro do banco derrubava o botão
            logger.error(f"Erro ao atualizar solicitação {self.solicitacao_atual_id}: {e}", exc_info=True)
            return False

    def aprovar_solicitacao(self):
        if not self.solicitacao_atual_id:
            messagebox.showwarning("Aviso", "Selecione uma solicitação na lista.", parent=self.root)
            return
        if not messagebox.askyesno("Confirmar", "Aprovar a solicitação selecionada?", parent=self.root):
            return
        if self._mudar_status_solicitacao('Aprovado'):
            self.status("Solicitação Aprovada!")  # [MELHORIA UX] rodapé em vez de janelinha
            self.carregar_solicitacoes()
        else:
            messagebox.showerror("Erro", "Não foi possível aprovar (veja o log).", parent=self.root)

    def recusar_solicitacao(self):
        if not self.solicitacao_atual_id:
            messagebox.showwarning("Aviso", "Selecione uma solicitação na lista.", parent=self.root)
            return
        motivo = simpledialog.askstring("Recusa", "Motivo da recusa:", parent=self.root)
        if motivo and motivo.strip():
            if self._mudar_status_solicitacao('Recusado', motivo.strip()):
                self.status("Solicitação Recusada.")  # [MELHORIA UX] rodapé em vez de janelinha
                self.carregar_solicitacoes()  # [DEPURAÇÃO] agora também limpa os detalhes da tela
            else:
                messagebox.showerror("Erro", "Não foi possível recusar (veja o log).", parent=self.root)

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
        self.tree_admin_nfs = criar_tree_zebrada(frame_nfs, columns=cols_nf, show='headings', selectmode='extended')
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

        cols_cont = ('ID', 'Data', 'Nome', 'Responsável')
        self.tree_admin_cont = criar_tree_zebrada(frame_cont, columns=cols_cont, show='headings', selectmode='extended')
        self.tree_admin_cont.heading('ID', text='ID'); self.tree_admin_cont.column('ID', width=30, anchor='center')
        self.tree_admin_cont.heading('Data', text='Data'); self.tree_admin_cont.column('Data', width=80, anchor='center')
        self.tree_admin_cont.heading('Nome', text='Nome/Ref'); self.tree_admin_cont.column('Nome', width=150)
        self.tree_admin_cont.heading('Responsável', text='Responsável'); self.tree_admin_cont.column('Responsável', width=130)

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

        # [MELHORIA UX] O botão fica TRAVADO até marcar a caixinha abaixo (evita clique
        # acidental) e, antes de apagar, o programa faz um BACKUP em Excel de tudo.
        self.var_liberar_reset = tk.BooleanVar(value=False)
        self.btn_reset_total = ttk.Button(frame_perigo, text="☢️ APAGAR TUDO E RECOMEÇAR ESTOQUE ☢️", style="Danger.TButton", command=self.resetar_sistema_estoque)

        def alternar_trava():
            self.btn_reset_total.state(['!disabled'] if self.var_liberar_reset.get() else ['disabled'])

        ttk.Checkbutton(frame_perigo, text="Eu entendo que esta ação apaga TODO o estoque (liberar o botão)",
                        variable=self.var_liberar_reset, command=alternar_trava).pack(pady=(0, 5))
        self.btn_reset_total.pack(ipadx=10, ipady=10)
        self.btn_reset_total.state(['disabled'])
        ttk.Label(frame_perigo, foreground="gray",
                  text="Um backup em Excel é salvo automaticamente na pasta 'backups_estoque' antes de apagar.").pack(pady=(5, 0))

    def atualizar_lista_nfs_admin(self):
        for i in self.tree_admin_nfs.get_children(): self.tree_admin_nfs.delete(i)
        try:
            nfs = database.listar_notas_fiscais_entrada_completa()
            for nf in nfs or []:
                # nf = (NotaID, NumeroNF, NomeFantasia, DataEmissao, ValorTotalNF, QtdItens)
                # [DEPURAÇÃO] data em texto ou valor vazio faziam a lista inteira sumir
                self.tree_admin_nfs.insert("", "end", values=(nf[0], nf[1], nf[2], fmt_data(nf[3]), fmt_num(nf[4], 2, "0.00"), nf[5]))
        except Exception as e:
            logger.error(f"Erro lista admin NF: {e}", exc_info=True)

    def atualizar_lista_contagens_admin(self):
        for i in self.tree_admin_cont.get_children(): self.tree_admin_cont.delete(i)
        try:
            contagens = database.listar_contagens_cabecalho()
            for c in contagens or []:
                data_fmt = fmt_data(c.DataContagem)

                # Resgata o nome da contagem
                nome_contagem_db = getattr(c, 'NomeContagem', 'Geral')
                if not nome_contagem_db: nome_contagem_db = 'Geral'

                self.tree_admin_cont.insert("", "end", values=(c.ContagemID, data_fmt, nome_contagem_db, c.NomeCompleto))
        except Exception as e:
            logger.error(f"Erro lista admin Contagem: {e}", exc_info=True)

    def excluir_nfs_selecionadas(self):
        selecionados = self.tree_admin_nfs.selection()
        if not selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma Nota Fiscal para excluir.", parent=self.root)
            return
        
        if not messagebox.askyesno("Confirmar Exclusão", f"Você selecionou {len(selecionados)} notas fiscais.\n\nEsta ação apagará o registro da nota e todo o histórico de entrada de estoque associado a ela.\n\nDeseja continuar?", icon='warning', parent=self.root):
            return

        sucessos = 0
        for item in selecionados:
            dados = self.tree_admin_nfs.item(item, 'values')
            nota_id = dados[0]
            if database.excluir_nota_fiscal_entrada(nota_id):
                sucessos += 1
        
        if sucessos == len(selecionados):
            self.status(f"{sucessos} de {len(selecionados)} nota(s) excluída(s) com sucesso.")  # [MELHORIA UX] rodapé em vez de janelinha
        else:
            messagebox.showwarning("Resultado", f"{sucessos} de {len(selecionados)} nota(s) excluída(s) com sucesso.", parent=self.root)
        self.atualizar_lista_nfs_admin()

    def excluir_contagens_selecionadas(self):
        selecionados = self.tree_admin_cont.selection()
        if not selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma Contagem para excluir.", parent=self.root)
            return
        
        if not messagebox.askyesno("Confirmar Exclusão", f"Você selecionou {len(selecionados)} contagens.\n\nEsta ação apagará o registro histórico dessa contagem de estoque.\n\nDeseja continuar?", icon='warning', parent=self.root):
            return

        sucessos = 0
        for item in selecionados:
            dados = self.tree_admin_cont.item(item, 'values')
            cont_id = dados[0]
            if database.excluir_contagem_estoque(cont_id):
                sucessos += 1
        
        if sucessos == len(selecionados):
            self.status(f"{sucessos} de {len(selecionados)} contagem(ns) excluída(s) com sucesso.")  # [MELHORIA UX] rodapé em vez de janelinha
        else:
            messagebox.showwarning("Resultado", f"{sucessos} de {len(selecionados)} contagem(ns) excluída(s) com sucesso.", parent=self.root)
        self.atualizar_lista_contagens_admin()
        # [DEPURAÇÃO] as abas 4 e 5 continuavam mostrando as contagens apagadas
        self.atualizar_lista_contagens_historico()
        self.popular_combos_contagem_sugestao()

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
                # [MELHORIA UX] Backup automático ANTES de apagar
                caminho_backup = self.backup_estoque_excel()
                if not caminho_backup:
                    if not messagebox.askyesno(
                            "Backup falhou",
                            "NÃO foi possível fazer o backup antes de apagar (veja o log).\n\n"
                            "Deseja apagar MESMO SEM BACKUP?\n(Recomendado: NÃO)",
                            icon='warning', default='no', parent=self.root):
                        return

                # Chama a função do banco de dados
                sucesso = database.resetar_dados_estoque_completo()
                
                if sucesso:
                    texto_backup = f"\n\nBackup do que existia antes:\n{caminho_backup}" if caminho_backup else ""
                    messagebox.showinfo("Sistema Resetado", "O banco de dados de estoque foi limpo com sucesso.\n\nVocê pode começar a cadastrar e vincular novamente." + texto_backup, parent=self.root)
                    self.var_liberar_reset.set(False)
                    self.btn_reset_total.state(['disabled'])
                    
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

    def backup_estoque_excel(self):
        """
        [MELHORIA UX] Salva uma cópia de TODO o estoque em Excel (uma aba para cada tipo
        de dado) na pasta 'backups_estoque'. Devolve o caminho do arquivo, ou None se falhar.
        """
        try:
            import pandas as pd
        except ImportError:
            logger.error("Backup antes do reset: pandas não instalado.")
            return None
        try:
            os.makedirs(PASTA_BACKUPS, exist_ok=True)
            caminho = os.path.join(PASTA_BACKUPS, f"backup_estoque_antes_reset_{datetime.now():%Y-%m-%d_%H%M%S}.xlsx")
            itens_contagens = []
            for c in database.listar_contagens_cabecalho() or []:
                for it in linhas_do_banco_para_dicts(database.buscar_itens_contagem(c.ContagemID)):
                    it = {'ContagemID': c.ContagemID, 'DataContagem': fmt_data(c.DataContagem),
                          'NomeContagem': getattr(c, 'NomeContagem', '') or 'Geral', **it}
                    itens_contagens.append(it)
            abas = {
                'Produtos': linhas_do_banco_para_dicts(database.listar_produtos_estoque()),
                'Fornecedores': linhas_do_banco_para_dicts(database.listar_fornecedores()),
                'Vinculos': linhas_do_banco_para_dicts(database.listar_todos_vinculos_detalhado()),
                'NotasFiscais': linhas_do_banco_para_dicts(database.listar_notas_fiscais_entrada_completa()),
                'Contagens': itens_contagens,
            }
            with pd.ExcelWriter(caminho, engine='openpyxl') as escritor:
                for nome, linhas in abas.items():
                    df = pd.DataFrame(linhas) if linhas else pd.DataFrame({'(vazio)': []})
                    # datas/horas com fuso e objetos estranhos viram texto (o Excel não aceita tudo)
                    for col in df.columns:
                        if df[col].dtype == object:
                            df[col] = df[col].map(lambda v: v if isinstance(v, (str, int, float)) or v is None else str(v))
                    df.to_excel(escritor, sheet_name=nome, index=False)
            logger.info(f"Backup do estoque salvo em {caminho}")
            return caminho
        except Exception as e:
            logger.error(f"Falha no backup do estoque antes do reset: {e}", exc_info=True)
            return None

    # ===================================================================
    # == [MELHORIA UX] VÍNCULOS + AUDITORIA (uma janela só) ==============
    # ===================================================================
    FILTROS_PROBLEMA = [
        ('todos', 'Todos os vínculos'),
        ('qualquer', '❗ Precisa de atenção (duplicado, fator suspeito, sem produto)'),
        ('duplicado', '🔁 Duplicados'),
        ('suspeito', '🔴 Fator suspeito'),
        ('sem_ean', '🏷️ Sem EAN'),
        ('sem_compras', '💤 Sem compras'),
        ('orfao', '⚠️ Sem produto / produto excluído'),
    ]

    # Só estes contam como "precisa de atenção". Sem EAN / sem compras são informativos
    # (muitos itens legítimos não têm código de barras, ex: frutas e frios vendidos por KG).
    PROBLEMAS_GRAVES = ('duplicado', 'suspeito', 'orfao')

    @staticmethod
    def problemas_do_vinculo(v):
        """Lista de chaves de problema de um vínculo (usada no filtro e na coluna 'Problemas')."""
        lista = []
        if v.get('Duplicado'): lista.append('duplicado')
        if v.get('Suspeito'): lista.append('suspeito')
        if v.get('SemEAN'): lista.append('sem_ean')
        if v.get('SemCompras'): lista.append('sem_compras')
        if v.get('Orfao') or v.get('SemProduto'): lista.append('orfao')
        return lista

    def abrir_tela_auditoria(self):
        """
        [MELHORIA UX] A Auditoria agora é a MESMA janela do Gerenciar Vínculos, já aberta
        mostrando só os cadastros com algum problema (duplicados, fator suspeito, sem EAN,
        sem compras, sem produto). Assim existe UM editor só, com as mesmas regras.
        """
        self.abrir_gestor_vinculos(modo_auditoria=True)

    def abrir_gestor_vinculos(self, produto_id=None, nome_produto=None, ao_salvar=None, modo_auditoria=False):
        """
        [MELHORIA UX] Vínculos e Auditoria de Cadastros (DE/PARA):
          - aberto a partir de um aviso, já vem FILTRADO no produto em questão;
          - filtro por PROBLEMA: duplicados, fator suspeito, sem EAN, sem compras, órfãos;
          - custo por unidade do estoque E custo da embalagem na nota, lado a lado;
          - busca sem acento, por várias palavras (fornecedor, XML, produto, EAN, código);
          - editor único: produto, fator (com prévia), EAN e NCM; corrigir o fator
            oferece corrigir também as compras já importadas;
          - "🧹 Juntar duplicados": une vínculos repetidos sem perder nenhuma compra;
          - Enter salva; duplo clique vai para o fator; Delete exclui (se não tiver compras).
        ao_salvar: função chamada depois de cada alteração (ex: recalcular o Valor do Estoque).
        """
        popup = Toplevel(self.root)
        popup.title("Vínculos e Auditoria de Cadastros")
        popup.geometry("1320x740")
        popup.transient(self.root)
        estado = {'dados': {}, 'produto_id': produto_id}
        rotulos = dict(self.FILTROS_PROBLEMA)
        icones = {'duplicado': '🔁', 'suspeito': '🔴', 'sem_ean': '🏷️', 'sem_compras': '💤', 'orfao': '⚠️'}

        # ---------- Topo: filtros ----------
        frame_topo = ttk.Frame(popup, padding=(10, 10, 10, 0))
        frame_topo.pack(fill=tk.X)
        ttk.Label(frame_topo, text="🔍 Buscar:").pack(side=tk.LEFT)
        entry_filtro = ttk.Entry(frame_topo, width=34)
        entry_filtro.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_topo, text="Mostrar:").pack(side=tk.LEFT, padx=(10, 3))
        combo_problema = ttk.Combobox(frame_topo, state="readonly", width=34)
        combo_problema.pack(side=tk.LEFT)
        btn_juntar = ttk.Button(frame_topo, text="🧹 Juntar duplicados", command=lambda: self.abrir_juntar_duplicados(popup, ao_mudar=recarregar_tudo))
        btn_juntar.pack(side=tk.LEFT, padx=10)
        lbl_contador = ttk.Label(frame_topo, text="", foreground="gray")
        lbl_contador.pack(side=tk.RIGHT)

        frame_produto = ttk.Frame(popup, padding=(10, 4, 10, 0))
        frame_produto.pack(fill=tk.X)
        lbl_produto = ttk.Label(frame_produto, text="", font=("Arial", 10, "bold"), foreground="#0056b3")
        lbl_produto.pack(side=tk.LEFT)
        btn_todos = ttk.Button(frame_produto, text="Mostrar todos os vínculos", command=lambda: mostrar_todos())

        # ---------- Lista ----------
        frame_lista = ttk.Frame(popup, padding="10")
        frame_lista.pack(fill=tk.BOTH, expand=True)
        cols = ('ID', 'Fornecedor', 'Descrição no XML', 'Produto Mestre', 'EAN', 'Qtd/Cx',
                'Custo/Unid.', 'Custo Emb.', 'Compras', 'Última compra', 'Problemas')
        titulos = {'Produto Mestre': 'Produto Mestre (Seu Estoque)', 'Custo/Unid.': 'Custo/Unid. estoque',
                   'Custo Emb.': 'Custo embalagem'}
        tree_vinculos = criar_tree_zebrada(frame_lista, columns=cols, show='headings', selectmode='browse')
        for col, larg, anc in (('ID', 50, 'center'), ('Fornecedor', 160, 'w'), ('Descrição no XML', 250, 'w'),
                               ('Produto Mestre', 230, 'w'), ('EAN', 110, 'center'), ('Qtd/Cx', 55, 'center'),
                               ('Custo/Unid.', 95, 'e'), ('Custo Emb.', 95, 'e'), ('Compras', 60, 'center'),
                               ('Última compra', 90, 'center'), ('Problemas', 80, 'center')):
            tree_vinculos.heading(col, text=titulos.get(col, col),
                                  command=lambda c=col: self.ordenar_coluna_treeview(tree_vinculos, c, False))
            tree_vinculos.column(col, width=larg, anchor=anc)
        tree_vinculos.tag_configure('orfao', background='#ffe3b3')
        tree_vinculos.tag_configure('duplicado', background='#ece4ff')
        tree_vinculos.tag_configure('suspeito', background='#ffd6d6')
        sb = ttk.Scrollbar(frame_lista, orient="vertical", command=tree_vinculos.yview)
        tree_vinculos.configure(yscrollcommand=sb.set)
        tree_vinculos.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Label(popup, foreground="gray", padding=(10, 0), text=(
            "🔴 vermelho = fator provavelmente errado (custo/unid. muito diferente do normal)   "
            "🔁 lilás = duplicado   ⚠️ laranja = sem produto   ·   Custo/Unid. = por unidade do SEU estoque; "
            "Custo embalagem = como veio na nota (Custo/Unid. × Qtd/Cx)")).pack(anchor="w")

        # ---------- Edição ----------
        frame_edit = ttk.LabelFrame(popup, text="Editar Vínculo Selecionado", padding="10")
        frame_edit.pack(fill=tk.X, padx=10, pady=10)
        frame_edit.columnconfigure(0, weight=1)
        lbl_selecionado = ttk.Label(frame_edit, text="Selecione um vínculo na lista.", font=("Arial", 10, "bold"))
        lbl_selecionado.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

        ttk.Label(frame_edit, text="Produto Mestre (digite para buscar):").grid(row=1, column=0, sticky="w")
        frame_mestre = ttk.Frame(frame_edit)
        frame_mestre.grid(row=2, column=0, sticky="ew", padx=(0, 10))
        frame_mestre.columnconfigure(1, weight=1)
        entry_busca_mestre = ttk.Entry(frame_mestre, width=16)
        entry_busca_mestre.grid(row=0, column=0, sticky="w", padx=(0, 5))
        combo_mestre_edit = ttk.Combobox(frame_mestre, values=self.lista_mestre_produtos_nomes, state="readonly")
        combo_mestre_edit.grid(row=0, column=1, sticky="ew")

        ttk.Label(frame_edit, text="Qtd/Cx (Fator):").grid(row=1, column=1, sticky="w")
        entry_fator_edit = ttk.Entry(frame_edit, width=8)
        entry_fator_edit.grid(row=2, column=1, sticky="w", padx=(0, 10))
        ttk.Label(frame_edit, text="EAN (código de barras):").grid(row=1, column=2, sticky="w")
        entry_ean_edit = ttk.Entry(frame_edit, width=16)
        entry_ean_edit.grid(row=2, column=2, sticky="w", padx=(0, 10))
        ttk.Label(frame_edit, text="NCM:").grid(row=1, column=3, sticky="w")
        entry_ncm_edit = ttk.Entry(frame_edit, width=10)
        entry_ncm_edit.grid(row=2, column=3, sticky="w", padx=(0, 10))

        lbl_previa = ttk.Label(frame_edit, text="", foreground="#0056b3")
        lbl_previa.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))

        # ---------- Funções ----------
        def carregar_dados():
            try:
                lista = database.listar_vinculos_com_resumo()
            except Exception as e:
                logger.error(f"Erro ao carregar vínculos: {e}", exc_info=True)
                messagebox.showerror("Erro de Carregamento", f"Falha ao ler os vínculos: {e}", parent=popup)
                lista = []
            estado['dados'] = {str(v['ID']): v for v in lista}
            # Opções do filtro com a quantidade de cada problema
            contagem = {chave: 0 for chave, _ in self.FILTROS_PROBLEMA}
            for v in lista:
                probs = self.problemas_do_vinculo(v)
                contagem['todos'] += 1
                contagem['qualquer'] += 1 if any(p in self.PROBLEMAS_GRAVES for p in probs) else 0
                for p in probs:
                    contagem[p] += 1
            estado['opcoes'] = {f"{rot} ({contagem[ch]})": ch for ch, rot in self.FILTROS_PROBLEMA}
            atual = estado.get('filtro_problema', 'qualquer' if modo_auditoria else 'todos')
            combo_problema['values'] = list(estado['opcoes'])
            combo_problema.set(next(k for k, ch in estado['opcoes'].items() if ch == atual))
            grupos = len({v['Grupo'] for v in lista if v.get('Grupo')})
            btn_juntar.config(text=f"🧹 Juntar duplicados ({grupos} grupo(s))")
            btn_juntar.state(['!disabled'] if grupos else ['disabled'])

        def mostrar(manter=None):
            manter = manter or tree_vinculos.focus()
            for i in tree_vinculos.get_children():
                tree_vinculos.delete(i)
            palavras = sem_acento(entry_filtro.get()).split()
            filtro_prob = estado['opcoes'].get(combo_problema.get(), 'todos') if estado.get('opcoes') else 'todos'
            estado['filtro_problema'] = filtro_prob
            n = 0
            for iid, v in estado['dados'].items():
                if estado['produto_id'] is not None and v['ProdutoID'] != estado['produto_id']:
                    continue
                probs = self.problemas_do_vinculo(v)
                if filtro_prob == 'qualquer' and not any(p in self.PROBLEMAS_GRAVES for p in probs):
                    continue
                if filtro_prob not in ('todos', 'qualquer') and filtro_prob not in probs:
                    continue
                texto = sem_acento(f"{v['Fornecedor']} {v['DescricaoXML']} {v['NomeMestre']} {v['EAN']} {v.get('Codigo', '')} {v['ID']}")
                if palavras and not all(p in texto for p in palavras):
                    continue
                tem_compra = v['UltimoCustoUnid'] is not None
                custo = fmt_reais(v['UltimoCustoUnid']) if tem_compra else "—"
                custo_emb = fmt_reais(v['UltimoCustoUnid'] * v['Fator']) if tem_compra else "—"
                data = v['UltimaData'].strftime('%d/%m/%Y') if v['UltimaData'] else "—"
                tag = ('suspeito',) if 'suspeito' in probs else ('orfao',) if 'orfao' in probs else ('duplicado',) if 'duplicado' in probs else ()
                grupo_txt = f"{icones['duplicado']}{v['Grupo']}" if v.get('Grupo') else ''
                probs_txt = " ".join(icones[p] if p != 'duplicado' else grupo_txt for p in probs)
                tree_vinculos.insert("", "end", iid=iid, tags=tag, values=(
                    v['ID'], v['Fornecedor'], v['DescricaoXML'], v['NomeMestre'], v['EAN'], fmt_qtd(v['Fator']),
                    custo, custo_emb, v['QtdCompras'], data, probs_txt))
                n += 1
            lbl_contador.config(text=f"{n} de {len(estado['dados'])} vínculo(s) na lista")
            if manter and tree_vinculos.exists(manter):
                tree_vinculos.focus(manter); tree_vinculos.selection_set(manter); tree_vinculos.see(manter)
            elif n == 1:
                unico = tree_vinculos.get_children()[0]
                tree_vinculos.focus(unico); tree_vinculos.selection_set(unico)

        def recarregar_tudo():
            carregar_dados(); mostrar(); preencher_edicao()
            if ao_salvar:
                try:
                    ao_salvar()
                except Exception as e:
                    logger.warning(f"Falha ao atualizar a janela de origem: {e}")

        def mostrar_todos():
            estado['produto_id'] = None
            lbl_produto.config(text="")
            btn_todos.pack_forget()
            mostrar()

        def selecionado_atual():
            sel = tree_vinculos.focus()
            return (sel, estado['dados'].get(sel)) if sel else (None, None)

        def atualizar_previa(event=None):
            sel, v = selecionado_atual()
            if not v:
                lbl_previa.config(text=""); return
            try:
                novo = para_decimal(entry_fator_edit.get(), "Fator", permitir_zero=False)
            except ValueError:
                lbl_previa.config(text="⚠️ Digite um número maior que zero no Qtd/Cx (ex: 12).", foreground="#c62828"); return
            if not v['UltimoCustoUnid']:
                lbl_previa.config(text="Ainda não há compras por este vínculo: o fator vale para as próximas notas.",
                                  foreground="gray"); return
            custo_embalagem = v['UltimoCustoUnid'] * v['Fator']
            embalagens = v['UltimaQtd'] / v['Fator'] if v['UltimaQtd'] else Decimal('0')
            unidade = self.mapa_produtos_mestre_contagem.get(v['NomeMestre'], {}).get('un', 'UN')
            texto = (f"Última compra: {fmt_qtd(embalagens)} embalagem(ns) de {fmt_reais(custo_embalagem)} (custo na nota).  "
                     f"Com Qtd/Cx {fmt_qtd(novo)} → {fmt_qtd(embalagens * novo)} {unidade} a "
                     f"{fmt_reais(custo_embalagem / novo)} cada (custo por unidade do estoque).")
            ref = v.get('CustoReferencia')
            if ref:
                texto += f"  Normal deste produto: ~{fmt_reais(ref)} por {unidade}."
            lbl_previa.config(text=texto, foreground="#0056b3")

        def preencher_edicao(event=None):
            sel, v = selecionado_atual()
            if not v:
                return
            codigo = f"  •  cód. fornecedor {v['Codigo']}" if v.get('Codigo') else ""
            lbl_selecionado.config(text=f"ID {v['ID']}  •  {v['Fornecedor']}  •  {v['DescricaoXML']}{codigo}")
            # [DEPURAÇÃO] só aceita o nome EXATO do mestre (antes "Sal" virava "Bacon Salgado")
            prefixo = f"{v['NomeMestre']} (ID: "
            candidatos = [n for n in self.lista_mestre_produtos_nomes if n.startswith(prefixo)]
            if v['ProdutoID'] is not None:
                exato = f"{v['NomeMestre']} (ID: {v['ProdutoID']})"
                candidatos = [exato] if exato in self.lista_mestre_produtos_nomes else candidatos
            combo_mestre_edit['values'] = self.lista_mestre_produtos_nomes
            combo_mestre_edit.set(candidatos[0] if len(candidatos) == 1 else "")
            entry_busca_mestre.delete(0, tk.END)
            for campo, valor in ((entry_fator_edit, fmt_qtd(v['Fator'])), (entry_ean_edit, v['EAN']), (entry_ncm_edit, v.get('NCM', ''))):
                campo.delete(0, tk.END); campo.insert(0, valor)
            atualizar_previa()

        def filtrar_mestre(event=None):
            if event is not None and getattr(event, 'keysym', '') in ('Return', 'Tab', 'Up', 'Down'):
                return
            achados = buscar_nomes(entry_busca_mestre.get(), self.lista_mestre_produtos_nomes)
            combo_mestre_edit['values'] = achados
            if achados and entry_busca_mestre.get().strip():
                combo_mestre_edit.set(achados[0])

        def salvar_alteracao(event=None):
            sel, v = selecionado_atual()
            if not v:
                messagebox.showwarning("Aviso", "Selecione um vínculo na lista.", parent=popup)
                return
            novo_mestre_nome = combo_mestre_edit.get()
            novo_mestre_id = self.mapa_produtos_mestre.get(novo_mestre_nome)
            if not novo_mestre_id:
                messagebox.showerror("Erro", "Selecione um Produto Mestre válido.", parent=popup)
                return
            try:
                novo_fator = para_decimal(entry_fator_edit.get(), "Fator", permitir_zero=False)
            except ValueError:
                messagebox.showerror("Erro", "Qtd/Cx (fator) inválido. Use um número maior que 0.", parent=popup)
                return
            novo_ean = entry_ean_edit.get().strip()
            novo_ncm = entry_ncm_edit.get().strip()

            recalcular = False
            if novo_fator != v['Fator'] and v['QtdCompras'] > 0:
                fator_antigo, previa = database.previa_recalculo_vinculo(v['ID'], novo_fator)
                exemplos = "\n".join(
                    f"  • NF {p['NF']} ({p['Data'].strftime('%d/%m/%Y') if p['Data'] else '?'}): "
                    f"{fmt_qtd(p['QtdAtual'])} a {fmt_reais(p['CustoAtual'])}  →  "
                    f"{fmt_qtd(p['QtdNova'])} a {fmt_reais(p['CustoNovo'])}" for p in previa[:5])
                mais = f"\n  ... e mais {len(previa) - 5}" if len(previa) > 5 else ""
                resposta = messagebox.askyesnocancel(
                    "Corrigir também as compras já importadas?",
                    f"O Qtd/Cx vai mudar de {fmt_qtd(fator_antigo)} para {fmt_qtd(novo_fator)}.\n\n"
                    f"Existem {len(previa)} compra(s) já importada(s) com o fator antigo:\n{exemplos}{mais}\n\n"
                    "SIM = corrigir também essas compras (recomendado se o fator estava ERRADO;\n"
                    "         o valor total de cada nota não muda)\n"
                    "NÃO = mudar só para as PRÓXIMAS notas\n"
                    "CANCELAR = não salvar\n\n"
                    "Obs.: contagens com o valor do estoque já FECHADO não mudam.",
                    parent=popup)
                if resposta is None:
                    return
                recalcular = bool(resposta)

            if database.atualizar_vinculo_existente(v['ID'], novo_mestre_id, novo_fator, recalcular_compras=recalcular,
                                                    novo_ean=novo_ean, novo_ncm=novo_ncm):
                extra = " e compras antigas corrigidas" if recalcular else ""
                self.status(f"Vínculo '{v['DescricaoXML']}' salvo (Qtd/Cx {fmt_qtd(novo_fator)}{extra}).")
                carregar_dados(); mostrar(manter=sel); preencher_edicao()
                if ao_salvar:
                    try:
                        ao_salvar()
                    except Exception as e:
                        logger.warning(f"Falha ao atualizar a janela de origem após salvar vínculo: {e}")
            else:
                messagebox.showerror("Erro", "Falha ao atualizar (veja o log).", parent=popup)
            return "break"

        def excluir_vinculo():
            sel, v = selecionado_atual()
            if not v:
                return
            if v['QtdCompras'] > 0:
                dica = ("Se for um DUPLICADO, use '🧹 Juntar duplicados'." if v.get('Grupo')
                        else "Se o produto está errado, troque o Produto Mestre e clique em 'Salvar Alterações'.")
                messagebox.showwarning(
                    "Não é possível excluir",
                    f"'{v['DescricaoXML']}' já tem {v['QtdCompras']} compra(s) registrada(s).\n\n"
                    f"Excluir apagaria a ligação dessas compras com o estoque.\n{dica}",
                    parent=popup)
                return
            if messagebox.askyesno("Excluir", f"Deseja excluir o vínculo para '{v['DescricaoXML']}'?\n\n"
                                   "Na próxima importação, o sistema pedirá para vincular novamente.", parent=popup):
                if database.excluir_vinculo_existente(v['ID']):
                    self.status(f"Vínculo '{v['DescricaoXML']}' excluído.", 'info')
                    carregar_dados(); mostrar()
                else:
                    messagebox.showerror("Erro", "Falha ao excluir.", parent=popup)

        def ir_para_fator(event=None):
            entry_fator_edit.focus_set(); entry_fator_edit.select_range(0, tk.END)

        entry_filtro.bind("<KeyRelease>", lambda e: mostrar())
        combo_problema.bind("<<ComboboxSelected>>", lambda e: mostrar())
        entry_busca_mestre.bind("<KeyRelease>", filtrar_mestre)
        entry_fator_edit.bind("<KeyRelease>", atualizar_previa)
        for campo in (entry_fator_edit, entry_ean_edit, entry_ncm_edit):
            campo.bind("<Return>", salvar_alteracao)
        tree_vinculos.bind("<<TreeviewSelect>>", preencher_edicao)
        tree_vinculos.bind("<Double-1>", ir_para_fator)
        tree_vinculos.bind("<Delete>", lambda e: excluir_vinculo())

        btn_salvar = ttk.Button(frame_edit, text="💾 Salvar Alterações", command=salvar_alteracao)
        btn_salvar.grid(row=2, column=4, padx=10)
        btn_excluir = ttk.Button(frame_edit, text="🗑️ Excluir Vínculo", command=excluir_vinculo)
        btn_excluir.grid(row=2, column=5, padx=(0, 5))

        if produto_id is not None:
            lbl_produto.config(text=f"Mostrando só os vínculos de: {nome_produto or produto_id}")
            btn_todos.pack(side=tk.LEFT, padx=10)
            estado['filtro_problema'] = 'todos'
        carregar_dados()
        mostrar()
        entry_filtro.focus_set()
        self._janela_vinculos = {'popup': popup, 'tree': tree_vinculos, 'filtro': entry_filtro,
                                 'fator': entry_fator_edit, 'ean': entry_ean_edit, 'ncm': entry_ncm_edit,
                                 'combo': combo_mestre_edit, 'busca_mestre': entry_busca_mestre,
                                 'previa': lbl_previa, 'salvar': salvar_alteracao, 'excluir': excluir_vinculo,
                                 'problema': combo_problema, 'opcoes': lambda: estado['opcoes'],
                                 'mostrar': mostrar, 'mostrar_todos': mostrar_todos,
                                 'contador': lbl_contador, 'btn_juntar': btn_juntar}

    def abrir_juntar_duplicados(self, janela_pai=None, ao_mudar=None):
        """
        [MELHORIA UX] Junta vínculos duplicados (mesmo fornecedor + mesmo produto + mesmo
        código do fornecedor ou EAN). As compras passam para o vínculo mantido; nenhuma
        quantidade ou custo muda. Grupos com Qtd/Cx diferentes precisam de revisão.
        """
        pai = janela_pai or self.root
        popup = Toplevel(pai)
        popup.title("🧹 Juntar vínculos duplicados")
        popup.geometry("1050x560")
        popup.transient(pai)
        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        lbl_resumo = ttk.Label(frame, text="", font=("Arial", 10, "bold"))
        lbl_resumo.pack(anchor="w")
        ttk.Label(frame, foreground="gray", text=(
            "Cada grupo é o MESMO item do MESMO fornecedor, cadastrado várias vezes (a descrição mudou de uma nota para outra). "
            "Juntar mantém a linha marcada como MANTER e passa para ela todas as compras das outras.")).pack(anchor="w", pady=(0, 6))

        cols = ('Ação', 'ID', 'Descrição no XML', 'EAN', 'Qtd/Cx', 'Custo/Unid.', 'Compras', 'Última compra')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings', selectmode='browse')
        for col, larg, anc in (('Ação', 150, 'w'), ('ID', 60, 'center'), ('Descrição no XML', 360, 'w'), ('EAN', 120, 'center'),
                               ('Qtd/Cx', 60, 'center'), ('Custo/Unid.', 100, 'e'), ('Compras', 70, 'center'),
                               ('Última compra', 100, 'center')):
            tree.heading(col, text=col); tree.column(col, width=larg, anchor=anc)
        tree.tag_configure('grupo', background='#dfe8f5')
        tree.tag_configure('manter', foreground='#1b7a2f')
        tree.tag_configure('fator_diferente', foreground='#c62828')
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        estado = {'grupos': {}, 'manter': {}}

        def carregar():
            for i in tree.get_children():
                tree.delete(i)
            try:
                grupos = database.listar_grupos_duplicados()
            except Exception as e:
                logger.error(f"Erro ao listar duplicados: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao listar duplicados:\n{e}", parent=popup)
                grupos = []
            estado['grupos'] = {g['Grupo']: g for g in grupos}
            for g in grupos:
                estado['manter'].setdefault(g['Grupo'], g['ManterID'])
                if estado['manter'][g['Grupo']] not in [v['ID'] for v in g['Vinculos']]:
                    estado['manter'][g['Grupo']] = g['ManterID']
                situacao = "✅ mesmo Qtd/Cx" if g['FatoresIguais'] else "⚠️ Qtd/Cx DIFERENTES - revise"
                tree.insert("", "end", iid=f"g{g['Grupo']}", tags=('grupo',), values=(
                    f"Grupo {g['Grupo']}", '', f"{g['Fornecedor']}  →  {g['NomeMestre']}", '', '', '',
                    f"{len(g['Vinculos'])} cadastros", situacao))
                for v in g['Vinculos']:
                    manter = v['ID'] == estado['manter'][g['Grupo']]
                    tags = ['manter'] if manter else []
                    if not g['FatoresIguais']:
                        tags.append('fator_diferente')
                    tree.insert("", "end", iid=f"v{v['ID']}", tags=tuple(tags), values=(
                        "✅ MANTER" if manter else "   juntar", v['ID'], v['DescricaoXML'], v['EAN'], fmt_qtd(v['Fator']),
                        fmt_reais(v['UltimoCustoUnid']) if v['UltimoCustoUnid'] is not None else '—', v['QtdCompras'],
                        v['UltimaData'].strftime('%d/%m/%Y') if v['UltimaData'] else '—'))
            iguais = sum(1 for g in grupos if g['FatoresIguais'])
            lbl_resumo.config(text=f"{len(grupos)} grupo(s) de duplicados · {iguais} com o mesmo Qtd/Cx (podem ser juntados de uma vez) · "
                                   f"{len(grupos) - iguais} para revisar")
            btn_todos.config(text=f"✅ Juntar os {iguais} grupo(s) com o mesmo Qtd/Cx")
            btn_todos.state(['!disabled'] if iguais else ['disabled'])

        def grupo_da_linha(iid):
            if iid.startswith('g'):
                return int(iid[1:]), None
            vid = int(iid[1:])
            for n, g in estado['grupos'].items():
                if any(v['ID'] == vid for v in g['Vinculos']):
                    return n, vid
            return None, None

        def definir_manter(event=None):
            sel = tree.focus()
            if not sel:
                return
            n, vid = grupo_da_linha(sel)
            if vid is None:
                return
            estado['manter'][n] = vid
            carregar()
            tree.focus(sel); tree.selection_set(sel)

        def juntar_grupo(n):
            g = estado['grupos'][n]
            manter = estado['manter'][n]
            outros = [v['ID'] for v in g['Vinculos'] if v['ID'] != manter]
            return database.juntar_vinculos(manter, outros)

        def juntar_selecionado():
            sel = tree.focus()
            if not sel:
                messagebox.showwarning("Aviso", "Clique numa linha do grupo que você quer juntar.", parent=popup)
                return
            n, _ = grupo_da_linha(sel)
            if n is None:
                return
            g = estado['grupos'][n]
            manter = next(v for v in g['Vinculos'] if v['ID'] == estado['manter'][n])
            aviso = ""
            if not g['FatoresIguais']:
                fatores = ", ".join(sorted({fmt_qtd(v['Fator']) for v in g['Vinculos']}))
                aviso = (f"\n\n⚠️ Os Qtd/Cx são diferentes ({fatores}). Depois de juntar, as PRÓXIMAS notas usarão "
                         f"o Qtd/Cx {fmt_qtd(manter['Fator'])} do vínculo mantido. As compras já gravadas não mudam.")
            if not messagebox.askyesno("Juntar grupo", f"Juntar os {len(g['Vinculos'])} cadastros do Grupo {n} no ID {manter['ID']} "
                                       f"('{manter['DescricaoXML']}')?{aviso}", parent=popup):
                return
            ok, msg = juntar_grupo(n)
            if ok:
                self.status(msg); carregar()
                if ao_mudar: ao_mudar()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        def juntar_todos_iguais():
            iguais = [n for n, g in estado['grupos'].items() if g['FatoresIguais']]
            if not iguais:
                return
            total = sum(len(estado['grupos'][n]['Vinculos']) - 1 for n in iguais)
            if not messagebox.askyesno("Juntar duplicados",
                                       f"Juntar {len(iguais)} grupo(s)? {total} cadastro(s) repetido(s) serão unidos "
                                       "ao cadastro marcado como MANTER de cada grupo.\n\n"
                                       "Nenhuma compra é perdida e nenhuma quantidade ou custo muda.", parent=popup):
                return
            ok_n, erros = 0, []
            for n in iguais:
                ok, msg = juntar_grupo(n)
                if ok:
                    ok_n += 1
                else:
                    erros.append(f"Grupo {n}: {msg}")
            self.status(f"{ok_n} grupo(s) de duplicados juntado(s).")
            if erros:
                messagebox.showwarning("Alguns grupos não foram juntados", "\n".join(erros[:10]), parent=popup)
            carregar()
            if ao_mudar: ao_mudar()

        tree.bind("<Double-1>", definir_manter)
        botoes = ttk.Frame(popup, padding=(10, 0, 10, 10))
        botoes.pack(fill=tk.X)
        ttk.Label(botoes, foreground="gray", text="Duplo clique numa linha = marcar como MANTER.").pack(side=tk.LEFT)
        btn_todos = ttk.Button(botoes, text="✅ Juntar grupos com o mesmo Qtd/Cx", command=juntar_todos_iguais)
        btn_todos.pack(side=tk.RIGHT, padx=5, ipady=3)
        ttk.Button(botoes, text="🔗 Juntar o grupo selecionado", command=juntar_selecionado).pack(side=tk.RIGHT, padx=5, ipady=3)
        carregar()
        self._janela_juntar = {'popup': popup, 'tree': tree, 'manter': estado['manter'], 'grupos': lambda: estado['grupos'],
                               'juntar_todos': juntar_todos_iguais, 'juntar_selecionado': juntar_selecionado,
                               'definir_manter': definir_manter, 'resumo': lbl_resumo}

    def ordenar_coluna_treeview(self, tree, col, reverse):
        """
        Ordena dinamicamente a coluna da Treeview, identificando 
        valores numéricos mascarados por strings (ex: '0.4 meses', 'R$ 10.00').
        """
        # Extrai os dados atuais da visualização
        lista_itens = [(tree.set(k, col), k) for k in tree.get_children('')]

        # [DEPURAÇÃO] chave_ordenacao nunca compara número com texto (antes dava TypeError
        # na coluna "Duração") e entende "R$ 1.234,56" (antes ordenava como texto).
        lista_itens.sort(key=lambda t: chave_ordenacao(t[0]), reverse=reverse)

        # Aplica a nova ordem visual realocando os índices no Tkinter
        for index, (val, k) in enumerate(lista_itens):
            tree.move(k, '', index)

        # Inverte o estado da ordenação para o próximo clique no mesmo cabeçalho
        tree.heading(col, command=lambda: self.ordenar_coluna_treeview(tree, col, not reverse))      

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoEstoque(root)
    root.mainloop()


# ==============================================================================
# == agendamentos_main.py  -  Controle de Agendamentos (com tela de login) =====
# ==============================================================================
# Programa de janela (Tkinter) que conversa com a API (api_server.py) para:
#   • listar, criar, editar, cancelar e excluir agendamentos;
#   • marcar o pagamento como Pago/Pendente;
#   • enviar o "Lembrete Geral" para o grupo do Telegram.
#
# Como rodar:  python agendamentos_main.py
# Precisa: a API (api_server.py) no ar e a biblioteca tkcalendar
#          (pip install tkcalendar requests)
#
# Versão DEPURADA: procure por [DEPURAÇÃO] para ver cada correção.
# ==============================================================================

# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING ===================================
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

PASTA_DO_PROGRAMA = os.path.dirname(os.path.abspath(__file__))

# [DEPURAÇÃO] Só configura o log se ninguém configurou antes (antes APAGAVA a
# configuração de quem importasse este arquivo).
if not logging.getLogger().handlers:
    log_dir = os.path.join(PASTA_DO_PROGRAMA, LOG_FOLDER)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        log_dir = PASTA_DO_PROGRAMA
    _file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, LOG_FILENAME), maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    _console_handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[_file_handler, _console_handler])

logger = logging.getLogger(__name__)
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================

import re
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel
from datetime import datetime, date
from types import SimpleNamespace

import requests

import config

# [DEPURAÇÃO] Se a biblioteca do calendário não estiver instalada, antes o programa
# fechava com um erro em inglês. Agora mostra o comando para instalar.
try:
    from tkcalendar import DateEntry
except ImportError:
    _raiz = tk.Tk(); _raiz.withdraw()
    messagebox.showerror(
        "Biblioteca faltando",
        "A biblioteca 'tkcalendar' não está instalada.\n\n"
        "Abra o Prompt de Comando (com o ambiente virtual ativado) e digite:\n\n"
        "pip install tkcalendar")
    sys.exit(1)

# [DEPURAÇÃO] Removidos: 'import database' (não era usado e obrigava o computador do
# atendimento a ter o driver do SQL Server instalado) e 'import hashlib' (não usado).

# ------------------------------------------------------------------------------
# Configurações
# ------------------------------------------------------------------------------
TIPOS_EVENTO = ['Carrinho de Sorvete', 'Festa de Aniversario', 'Reserva de Tortas de Sorvete']
STATUS_PAGAMENTO = ['Pendente', 'Pago']
STATUS_AGENDAMENTO = ['Confirmado', 'Cancelado']

# [DEPURAÇÃO] Tempo máximo de espera pela API. Antes NÃO havia limite: se o servidor
# ou o ngrok travassem, a janela congelava ("Não está respondendo") para sempre.
TIMEOUT_PADRAO = 15      # segundos
TIMEOUT_LEMBRETE = 60    # o lembrete geral fala com o Telegram, pode demorar mais


# ==============================================================================
# == COMUNICAÇÃO COM A API =====================================================
# ==============================================================================
class ErroAPI(Exception):
    """Erro com uma mensagem já pronta para mostrar ao usuário."""


def _url(caminho):
    return f"{str(config.API_BASE_URL).rstrip('/')}{caminho}"


def _cabecalhos():
    cab = {
        # Evita a página de aviso do ngrok (que vem em HTML e não em JSON)
        'ngrok-skip-browser-warning': 'true',
    }
    chave = getattr(config, 'API_KEY', None)
    if chave:
        cab['X-API-Key'] = str(chave)
    return cab


def ler_json(response):
    """
    [DEPURAÇÃO] Antes o programa fazia response.json() direto. Quando a API devolvia
    uma página de erro (HTML do ngrok, erro 502...), isso dava um erro que NÃO era
    tratado: nada aparecia na tela e o botão simplesmente "não fazia nada".
    """
    try:
        return response.json()
    except ValueError:
        return None


def mensagem_da_api(response, padrao="Erro desconhecido."):
    dados = ler_json(response)
    if isinstance(dados, dict) and dados.get('mensagem'):
        return str(dados['mensagem'])
    return f"{padrao} (código {response.status_code})"


def chamar_api(metodo, caminho, timeout=TIMEOUT_PADRAO, **kwargs):
    """Faz o pedido à API. Em caso de falha de conexão, levanta ErroAPI com texto amigável."""
    try:
        return requests.request(metodo, _url(caminho), headers=_cabecalhos(), timeout=timeout, **kwargs)
    except requests.exceptions.Timeout:
        raise ErroAPI("O servidor demorou demais para responder.\n"
                      "Verifique se a API e o ngrok estão no ar e tente de novo.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Falha de conexão com a API ({metodo} {caminho}): {e}")
        raise ErroAPI("Não foi possível conectar ao servidor.\n"
                      "Verifique se a API e o ngrok estão no ar e se há internet.\n\n"
                      f"Detalhe: {e}")


# ==============================================================================
# == VALIDAÇÕES ================================================================
# ==============================================================================
def so_digitos(texto):
    return re.sub(r'\D', '', str(texto or ''))


def validar_telefone(telefone):
    """
    [DEPURAÇÃO] Nenhuma conferência era feita. Um telefone errado fazia a confirmação
    e o pós-venda do WhatsApp falharem sem ninguém perceber.
    Aceita vazio, ou 10 a 13 dígitos (com ou sem DDD/55).
    """
    if not telefone.strip():
        return None
    qtd = len(so_digitos(telefone))
    if qtd < 10 or qtd > 13:
        return "O telefone deve ter DDD + número (ex: (65) 99999-8888)."
    return None


def validar_cpf(cpf):
    """Aceita vazio, CPF (11 dígitos) ou CNPJ (14 dígitos)."""
    if not cpf.strip():
        return None
    if len(so_digitos(cpf)) not in (11, 14):
        return "O CPF deve ter 11 dígitos (ou 14 se for CNPJ)."
    return None


def montar_data_hora(data_escolhida, hora_digitada):
    """Junta a data do calendário com a hora digitada. Levanta ValueError se a hora for inválida."""
    hora = datetime.strptime(hora_digitada.strip(), "%H:%M").time()
    return datetime.combine(data_escolhida, hora)


def ler_data_da_api(texto):
    """A API envia 'dd/mm/aaaa HH:MM'. Devolve datetime ou None (se vazio/inválido)."""
    try:
        return datetime.strptime(str(texto or '').strip(), '%d/%m/%Y %H:%M')
    except ValueError:
        return None


# ==============================================================================
# == TELA DE LOGIN =============================================================
# ==============================================================================
class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("Gela Boca - Acesso ao Sistema")
        self.root.geometry("350x280")
        self.root.resizable(False, False)
        try:
            self.root.eval('tk::PlaceWindow . center')
        except tk.TclError:
            pass

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

        self.btn_login = ttk.Button(frame, text="Entrar", command=self.fazer_login)
        self.btn_login.pack(pady=20, fill="x", ipady=8)

        self.funcionario_logado = None

    def fazer_login(self, event=None):
        # [DEPURAÇÃO] .strip(): um espaço digitado sem querer ("12 ") recusava o ID
        funcionario_id = self.entry_id.get().strip()
        senha = self.entry_senha.get()

        if not funcionario_id.isdigit() or not senha:
            messagebox.showerror("Erro", "Digite o ID (somente números) e a senha.", parent=self.root)
            return

        self.btn_login.state(['disabled'])  # [DEPURAÇÃO] evita cliques repetidos
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            response = chamar_api('POST', '/login', json={"id": int(funcionario_id), "senha": senha})
            dados = ler_json(response)

            if response.status_code == 200 and isinstance(dados, dict) and isinstance(dados.get('funcionario'), dict):
                func = dados['funcionario']
                # [DEPURAÇÃO] Antes usava type('Funcionario', (), ...), que cria uma CLASSE
                # (e não um objeto). Funcionava por acaso; agora é um objeto simples.
                self.funcionario_logado = SimpleNamespace(
                    id=func.get('id'), nome=func.get('nome', ''),
                    FuncionarioID=func.get('id'), NomeCompleto=func.get('nome', ''))
                messagebox.showinfo("Bem-vindo(a)!", dados.get('mensagem', 'Acesso liberado!'), parent=self.root)
                self.root.destroy()
                return
            if response.status_code == 200:
                messagebox.showerror("Erro", "O servidor respondeu em um formato inesperado.\n"
                                             "Confira se o endereço API_BASE_URL do config.py está certo.",
                                     parent=self.root)
            else:
                messagebox.showerror("Acesso Negado", mensagem_da_api(response), parent=self.root)
        except ErroAPI as e:
            messagebox.showerror("Erro de Conexão", str(e), parent=self.root)
        except Exception as e:
            logger.exception(f"Erro inesperado no login: {e}")
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado: {e}", parent=self.root)

        # Só chega aqui se o login NÃO deu certo: libera o botão de novo
        self.btn_login.state(['!disabled'])
        self.root.config(cursor="")


# ==============================================================================
# == TELA PRINCIPAL ============================================================
# ==============================================================================
class AppAgendamentos:
    def __init__(self, root, funcionario_logado):
        self.root = root
        self.funcionario_logado = funcionario_logado
        self.id_funcionario_logado = self.funcionario_logado.FuncionarioID
        self.dados_por_item = {}  # guarda os dados completos de cada linha da lista

        self.root.title(f"Gela Boca - Controle de Agendamentos (Logado como: {self.funcionario_logado.NomeCompleto})")
        self.root.geometry("1100x600")

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=2)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # ---------------- Lista de agendamentos ----------------
        frame_lista = ttk.LabelFrame(main_frame, text="Agendamentos Futuros", padding="10")
        frame_lista.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.frame_lista = frame_lista

        # [DEPURAÇÃO] A lista dizia "Futuros" mas mostrava TODOS (inclusive os de meses
        # atrás e os cancelados). Agora mostra de hoje em diante, com opção de ver todos.
        frame_filtro = ttk.Frame(frame_lista)
        frame_filtro.pack(fill=tk.X, pady=(0, 5))
        self.var_mostrar_todos = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_filtro, text="Mostrar também passados e cancelados",
                        variable=self.var_mostrar_todos,
                        command=self.carregar_agendamentos).pack(side=tk.LEFT)
        ttk.Button(frame_filtro, text="🔄 Atualizar", command=self.carregar_agendamentos).pack(side=tk.RIGHT)

        frame_tree = ttk.Frame(frame_lista)
        frame_tree.pack(fill=tk.BOTH, expand=True)
        cols = ('ID', 'Cliente', 'Tipo', 'Data/Hora', 'Status Pagamento', 'Situação')
        self.tree_agendamentos = ttk.Treeview(frame_tree, columns=cols, show='headings', selectmode='browse')
        for col in cols:
            self.tree_agendamentos.heading(col, text=col)
        self.tree_agendamentos.column('ID', width=40, anchor='center')
        self.tree_agendamentos.column('Cliente', width=200)
        self.tree_agendamentos.column('Tipo', width=150)
        self.tree_agendamentos.column('Data/Hora', width=120, anchor='center')
        self.tree_agendamentos.column('Status Pagamento', width=110, anchor='center')
        self.tree_agendamentos.column('Situação', width=90, anchor='center')
        # [DEPURAÇÃO] Barra de rolagem (com muitos agendamentos não dava para ver os últimos)
        barra = ttk.Scrollbar(frame_tree, orient=tk.VERTICAL, command=self.tree_agendamentos.yview)
        self.tree_agendamentos.configure(yscrollcommand=barra.set)
        barra.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_agendamentos.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_agendamentos.tag_configure('cancelado', foreground='gray')
        self.tree_agendamentos.tag_configure('passado', foreground='#777777')
        self.tree_agendamentos.tag_configure('hoje', background='#FFF6D5')
        # Duplo clique abre a edição
        self.tree_agendamentos.bind("<Double-1>", lambda e: self.abrir_janela_edicao())

        frame_botoes_acao = ttk.Frame(frame_lista)
        frame_botoes_acao.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(frame_botoes_acao, text="Editar Selecionado", command=self.abrir_janela_edicao).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(frame_botoes_acao, text="Excluir Selecionado", command=self.excluir_agendamento_selecionado).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_botoes_acao, text="Alterar Status Pag.", command=self.alterar_status_pagamento).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_botoes_acao, text="📢 Enviar Lembrete Geral", command=self.enviar_lembrete_geral).pack(side=tk.RIGHT, padx=5)

        # ---------------- Formulário de novo agendamento ----------------
        frame_form = ttk.LabelFrame(main_frame, text="Novo Agendamento", padding="10")
        frame_form.grid(row=0, column=1, sticky="nsew")
        ttk.Label(frame_form, text="Nome do Cliente:").pack(anchor="w")
        self.entry_nome = ttk.Entry(frame_form)
        self.entry_nome.pack(fill="x", pady=(0, 5))
        ttk.Label(frame_form, text="CPF:").pack(anchor="w")
        self.entry_cpf = ttk.Entry(frame_form)
        self.entry_cpf.pack(fill="x", pady=(0, 5))
        ttk.Label(frame_form, text="Telefone (com DDD):").pack(anchor="w")
        self.entry_telefone = ttk.Entry(frame_form)
        self.entry_telefone.pack(fill="x", pady=(0, 5))
        ttk.Label(frame_form, text="Tipo de Evento:").pack(anchor="w")
        # [DEPURAÇÃO] readonly: antes dava para digitar qualquer coisa (ex: "carrinho"),
        # criando tipos diferentes para o mesmo evento nos relatórios.
        self.combo_tipo_evento = ttk.Combobox(frame_form, values=TIPOS_EVENTO, state='readonly')
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
        self.btn_salvar = ttk.Button(frame_form, text="Salvar Agendamento", command=self.salvar_agendamento)
        self.btn_salvar.pack(fill="x", ipady=5)

        self.carregar_agendamentos()

    # ------------------------------------------------------------------
    # Auxiliares da tela
    # ------------------------------------------------------------------
    def _ocupado(self, sim):
        """Mostra a ampulheta enquanto espera a API."""
        try:
            self.root.config(cursor="watch" if sim else "")
            self.root.update_idletasks()
        except tk.TclError:
            pass

    def _selecionado(self, acao):
        """Devolve (item, dados) do agendamento selecionado, ou (None, None) com aviso."""
        item = self.tree_agendamentos.focus()
        if not item or item not in self.dados_por_item:
            messagebox.showwarning("Aviso", f"Selecione um agendamento na lista para {acao}.", parent=self.root)
            return None, None
        return item, self.dados_por_item[item]

    # ------------------------------------------------------------------
    # Lista
    # ------------------------------------------------------------------
    def carregar_agendamentos(self):
        item_antes = self.tree_agendamentos.focus()
        self._ocupado(True)
        try:
            response = chamar_api('GET', '/api/agendamentos')
            agendamentos = ler_json(response)
            if response.status_code != 200 or not isinstance(agendamentos, list):
                messagebox.showerror("Erro de API", "Não foi possível buscar os agendamentos.\n"
                                     + mensagem_da_api(response, "Resposta inválida do servidor."), parent=self.root)
                return
        except ErroAPI as e:
            messagebox.showerror("Erro de Conexão", str(e), parent=self.root)
            return
        finally:
            self._ocupado(False)

        # [DEPURAÇÃO] Só limpa a lista DEPOIS de receber os dados novos (antes, se a API
        # falhasse, a lista ficava vazia e parecia que os agendamentos tinham sumido).
        for i in self.tree_agendamentos.get_children():
            self.tree_agendamentos.delete(i)
        self.dados_por_item = {}

        hoje = date.today()
        mostrar_todos = self.var_mostrar_todos.get()
        linhas = []
        for ag in agendamentos:
            if not isinstance(ag, dict) or ag.get('agendamento_id') is None:
                continue
            dt = ler_data_da_api(ag.get('data_evento'))
            cancelado = str(ag.get('status_agendamento') or '').strip().lower() == 'cancelado'
            passado = dt is not None and dt.date() < hoje
            if not mostrar_todos and (cancelado or passado):
                continue
            linhas.append((dt or datetime.max, ag, dt, cancelado, passado))

        # [DEPURAÇÃO] Ordena por data (sem data vai para o fim)
        linhas.sort(key=lambda x: x[0])
        for _, ag, dt, cancelado, passado in linhas:
            item = str(ag['agendamento_id'])
            tags = ('cancelado',) if cancelado else ('passado',) if passado else \
                   ('hoje',) if dt and dt.date() == hoje else ()
            self.tree_agendamentos.insert("", "end", iid=item, tags=tags, values=(
                ag['agendamento_id'], ag.get('nome_cliente') or '', ag.get('tipo_evento') or '',
                ag.get('data_evento') or '(sem data)', ag.get('status_pagamento') or 'Pendente',
                ag.get('status_agendamento') or 'Confirmado'))
            self.dados_por_item[item] = ag

        titulo = "Todos os Agendamentos" if mostrar_todos else "Agendamentos Futuros"
        self.frame_lista.config(text=f"{titulo} ({len(linhas)})")

        # Mantém selecionado o mesmo agendamento de antes (se ainda existir)
        if item_antes and self.tree_agendamentos.exists(item_antes):
            self.tree_agendamentos.selection_set(item_antes)
            self.tree_agendamentos.focus(item_antes)
            self.tree_agendamentos.see(item_antes)

    # ------------------------------------------------------------------
    # Novo agendamento
    # ------------------------------------------------------------------
    def salvar_agendamento(self):
        nome = self.entry_nome.get().strip()
        cpf = self.entry_cpf.get().strip()
        telefone = self.entry_telefone.get().strip()
        tipo_evento = self.combo_tipo_evento.get().strip()
        hora_digitada = self.entry_hora.get().strip()
        obs = self.txt_observacoes.get("1.0", tk.END).strip()

        if not all([nome, tipo_evento, hora_digitada]):
            messagebox.showwarning("Campos Obrigatórios", "Nome do Cliente, Tipo e Hora são obrigatórios.", parent=self.root)
            return
        for erro in (validar_cpf(cpf), validar_telefone(telefone)):
            if erro:
                messagebox.showwarning("Dados inválidos", erro, parent=self.root)
                return
        try:
            data_hora_evento = montar_data_hora(self.entry_data.get_date(), hora_digitada)
        except ValueError:
            messagebox.showerror("Erro de Formato", "A hora deve estar no formato HH:MM (ex: 14:30).", parent=self.root)
            return

        # [DEPURAÇÃO] Aviso de data no passado (erro comum ao esquecer de trocar a data
        # do calendário, que abre sempre no dia de hoje).
        if data_hora_evento < datetime.now():
            if not messagebox.askyesno("Data no passado",
                                       f"A data/hora {data_hora_evento.strftime('%d/%m/%Y %H:%M')} já passou.\n"
                                       "Deseja salvar mesmo assim?", parent=self.root):
                return

        payload = {
            "nome_cliente": nome, "cpf_cliente": cpf, "telefone_cliente": telefone,
            "tipo_evento": tipo_evento, "data_evento": data_hora_evento.strftime('%Y-%m-%d %H:%M'),
            "observacoes": obs, "funcionario_id": self.id_funcionario_logado
        }
        # [DEPURAÇÃO] Removido o print "DEBUG ENVIANDO", que mostrava CPF e telefone
        # do cliente na tela preta a cada agendamento.
        logger.info(f"Criando agendamento para '{nome}' em {payload['data_evento']}")

        self.btn_salvar.state(['disabled'])  # [DEPURAÇÃO] evita agendamento duplicado por clique duplo
        self._ocupado(True)
        try:
            response = chamar_api('POST', '/agendamentos/novo', json=payload)
            if response.status_code == 201:
                messagebox.showinfo("Sucesso", "Agendamento salvo com sucesso!", parent=self.root)
                self.limpar_formulario()
                self.carregar_agendamentos()
            else:
                messagebox.showerror("Erro da API", f"Não foi possível salvar.\nErro: {mensagem_da_api(response)}", parent=self.root)
        except ErroAPI as e:
            messagebox.showerror("Erro de Conexão", str(e), parent=self.root)
        finally:
            self._ocupado(False)
            self.btn_salvar.state(['!disabled'])

    def limpar_formulario(self):
        self.entry_nome.delete(0, tk.END)
        self.entry_cpf.delete(0, tk.END)
        self.entry_telefone.delete(0, tk.END)
        self.combo_tipo_evento.set('')
        self.entry_hora.delete(0, tk.END)
        self.entry_hora.insert(0, "14:00")
        self.txt_observacoes.delete("1.0", tk.END)

    # ------------------------------------------------------------------
    # Excluir / pagamento
    # ------------------------------------------------------------------
    def excluir_agendamento_selecionado(self):
        item, ag = self._selecionado("excluir")
        if not item:
            return
        agendamento_id, nome_cliente = ag['agendamento_id'], ag.get('nome_cliente') or ''
        if not messagebox.askyesno("Confirmar Exclusão",
                                   f"Tem certeza que deseja EXCLUIR o agendamento de '{nome_cliente}'?\n\n"
                                   "Dica: se o cliente desistiu, prefira EDITAR e mudar a situação para "
                                   "'Cancelado' (assim o histórico é mantido).", parent=self.root):
            return
        self._ocupado(True)
        try:
            response = chamar_api('DELETE', f'/agendamentos/{agendamento_id}')
            if response.status_code in (200, 204):
                messagebox.showinfo("Sucesso", "Agendamento excluído com sucesso!", parent=self.root)
                self.carregar_agendamentos()
            else:
                messagebox.showerror("Erro da API", f"Falha ao excluir: {mensagem_da_api(response)}", parent=self.root)
        except ErroAPI as e:
            messagebox.showerror("Erro de Conexão", str(e), parent=self.root)
        finally:
            self._ocupado(False)

    def alterar_status_pagamento(self):
        item, ag = self._selecionado("alterar o pagamento")
        if not item:
            return
        agendamento_id = ag['agendamento_id']
        status_atual = ag.get('status_pagamento') or 'Pendente'
        novo_status = "Pendente" if status_atual == "Pago" else "Pago"
        # [DEPURAÇÃO] Confirmação: um clique errado mudava o pagamento sem aviso
        if not messagebox.askyesno("Confirmar",
                                   f"Mudar o pagamento de '{ag.get('nome_cliente') or ''}' "
                                   f"de '{status_atual}' para '{novo_status}'?", parent=self.root):
            return
        self._ocupado(True)
        try:
            response = chamar_api('PATCH', f'/agendamentos/{agendamento_id}/pagamento', json={"status": novo_status})
            if response.status_code == 200:
                messagebox.showinfo("Sucesso", f"Status do pagamento alterado para '{novo_status}'.", parent=self.root)
                self.carregar_agendamentos()
            else:
                messagebox.showerror("Erro da API", f"Falha ao alterar status: {mensagem_da_api(response)}", parent=self.root)
        except ErroAPI as e:
            messagebox.showerror("Erro de Conexão", str(e), parent=self.root)
        finally:
            self._ocupado(False)

    # ------------------------------------------------------------------
    # Edição
    # ------------------------------------------------------------------
    def abrir_janela_edicao(self):
        item, ag = self._selecionado("editar")
        if not item:
            return
        agendamento_id = ag['agendamento_id']

        self._ocupado(True)
        try:
            response = chamar_api('GET', f'/agendamentos/{agendamento_id}')
            dados_completos = ler_json(response)
            if response.status_code != 200 or not isinstance(dados_completos, dict):
                messagebox.showerror("Erro", "Não foi possível buscar os detalhes do agendamento.\n"
                                     + mensagem_da_api(response), parent=self.root)
                return
        except ErroAPI as e:
            messagebox.showerror("Erro de Conexão", str(e), parent=self.root)
            return
        finally:
            self._ocupado(False)

        popup = Toplevel(self.root)
        popup.title(f"Editar Agendamento #{agendamento_id}")
        popup.geometry("450x620")
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Nome do Cliente:").pack(anchor="w")
        edit_entry_nome = ttk.Entry(frame)
        edit_entry_nome.pack(fill="x", pady=(0, 5))
        edit_entry_nome.insert(0, dados_completos.get('nome_cliente') or '')

        ttk.Label(frame, text="CPF:").pack(anchor="w")
        edit_entry_cpf = ttk.Entry(frame)
        edit_entry_cpf.pack(fill="x", pady=(0, 5))
        edit_entry_cpf.insert(0, dados_completos.get('cpf_cliente') or '')

        ttk.Label(frame, text="Telefone (com DDD):").pack(anchor="w")
        edit_entry_telefone = ttk.Entry(frame)
        edit_entry_telefone.pack(fill="x", pady=(0, 5))
        edit_entry_telefone.insert(0, dados_completos.get('telefone_cliente') or '')

        # Se o agendamento tiver um tipo antigo que não está na lista, ele continua aparecendo
        tipo_atual = dados_completos.get('tipo_evento') or ''
        tipos = TIPOS_EVENTO + ([tipo_atual] if tipo_atual and tipo_atual not in TIPOS_EVENTO else [])
        ttk.Label(frame, text="Tipo de Evento:").pack(anchor="w")
        edit_combo_tipo = ttk.Combobox(frame, values=tipos, state='readonly')
        edit_combo_tipo.pack(fill="x", pady=(0, 5))
        edit_combo_tipo.set(tipo_atual)

        frame_data_hora = ttk.Frame(frame)
        frame_data_hora.pack(fill="x", pady=(5, 5))
        ttk.Label(frame_data_hora, text="Data:").pack(side="left")
        edit_entry_data = DateEntry(frame_data_hora, width=12, date_pattern='dd/mm/yyyy')
        edit_entry_data.pack(side="left", padx=(5, 10))
        ttk.Label(frame_data_hora, text="Hora (HH:MM):").pack(side="left")
        edit_entry_hora = ttk.Entry(frame_data_hora, width=8)
        edit_entry_hora.pack(side="left", padx=5)

        # [DEPURAÇÃO] Um agendamento sem data (ou com data em outro formato) dava erro
        # aqui e a janela abria PELA METADE (sem botão de salvar). Agora avisa e deixa corrigir.
        data_evento_obj = ler_data_da_api(dados_completos.get('data_evento'))
        if data_evento_obj:
            edit_entry_data.set_date(data_evento_obj.date())
            edit_entry_hora.insert(0, data_evento_obj.strftime('%H:%M'))
        else:
            ttk.Label(frame, text="⚠ Este agendamento está sem data. Escolha a data e a hora.",
                      foreground="red").pack(anchor="w")

        ttk.Label(frame, text="Observações:").pack(anchor="w")
        edit_txt_obs = tk.Text(frame, height=3)
        edit_txt_obs.pack(fill="x", pady=(0, 5))
        edit_txt_obs.insert("1.0", dados_completos.get('observacoes') or '')

        # [DEPURAÇÃO] readonly: antes dava para digitar "pago" (minúsculo) e o sistema
        # passava a tratar o agendamento como NÃO pago ("RECEBER") nos lembretes.
        ttk.Label(frame, text="Status Pagamento:").pack(anchor="w")
        edit_combo_pagamento = ttk.Combobox(frame, values=STATUS_PAGAMENTO, state='readonly')
        edit_combo_pagamento.pack(fill="x", pady=(0, 5))
        pag_atual = dados_completos.get('status_pagamento') or 'Pendente'
        edit_combo_pagamento.set(pag_atual if pag_atual in STATUS_PAGAMENTO else 'Pendente')

        # [DEPURAÇÃO] NOVO: situação do agendamento. Marcando "Cancelado", o robô de
        # lembretes deixa de avisar o grupo e de mandar WhatsApp para o cliente.
        situacao_atual = dados_completos.get('status_agendamento') or 'Confirmado'
        situacoes = STATUS_AGENDAMENTO + ([situacao_atual] if situacao_atual not in STATUS_AGENDAMENTO else [])
        ttk.Label(frame, text="Situação do Agendamento:").pack(anchor="w")
        edit_combo_situacao = ttk.Combobox(frame, values=situacoes, state='readonly')
        edit_combo_situacao.pack(fill="x", pady=(0, 5))
        edit_combo_situacao.set(situacao_atual)

        def salvar_edicao():
            nome = edit_entry_nome.get().strip()
            cpf = edit_entry_cpf.get().strip()
            telefone = edit_entry_telefone.get().strip()
            if not nome or not edit_combo_tipo.get().strip():
                messagebox.showwarning("Campos Obrigatórios", "Nome do Cliente e Tipo são obrigatórios.", parent=popup)
                return
            for erro in (validar_cpf(cpf), validar_telefone(telefone)):
                if erro:
                    messagebox.showwarning("Dados inválidos", erro, parent=popup)
                    return
            try:
                nova_data_hora = montar_data_hora(edit_entry_data.get_date(), edit_entry_hora.get())
            except ValueError:
                messagebox.showerror("Erro de Formato", "A hora deve estar no formato HH:MM (ex: 14:30).", parent=popup)
                return

            payload_editado = {
                "nome_cliente": nome,
                "cpf_cliente": cpf,
                "telefone_cliente": telefone,
                "tipo_evento": edit_combo_tipo.get(),
                "status_pagamento": edit_combo_pagamento.get(),
                "observacoes": edit_txt_obs.get("1.0", tk.END).strip(),
                "data_evento": nova_data_hora.strftime('%Y-%m-%d %H:%M'),
                # [DEPURAÇÃO] .get(): se a API não mandasse estes campos, dava erro ao salvar
                "funcionario_id": dados_completos.get('funcionario_id') or self.id_funcionario_logado,
                "status_agendamento": edit_combo_situacao.get() or 'Confirmado',
            }

            botao_salvar.state(['disabled'])
            try:
                response = chamar_api('PUT', f'/agendamentos/{agendamento_id}', json=payload_editado)
                if response.status_code == 200:
                    messagebox.showinfo("Sucesso", "Agendamento atualizado!", parent=popup)
                    popup.destroy()
                    self.carregar_agendamentos()
                    return
                messagebox.showerror("Erro da API", f"Falha ao atualizar: {mensagem_da_api(response)}", parent=popup)
            except ErroAPI as e:
                messagebox.showerror("Erro de Conexão", str(e), parent=popup)
            botao_salvar.state(['!disabled'])

        botao_salvar = ttk.Button(frame, text="Salvar Alterações", command=salvar_edicao)
        botao_salvar.pack(pady=20, fill="x")
        # [DEPURAÇÃO] Mantém a janela de edição na frente e evita abrir várias ao mesmo tempo
        try:
            popup.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Lembrete geral
    # ------------------------------------------------------------------
    def enviar_lembrete_geral(self):
        if not messagebox.askyesno("Confirmar Envio",
                                   "Deseja enviar um resumo de TODOS os agendamentos futuros para o grupo do Telegram agora?",
                                   parent=self.root):
            return
        self._ocupado(True)
        try:
            response = chamar_api('POST', '/agendamentos/enviar-lembrete-geral', timeout=TIMEOUT_LEMBRETE)
            if response.status_code == 200:
                messagebox.showinfo("Sucesso", "Resumo de agendamentos enviado para o grupo!", parent=self.root)
            else:
                messagebox.showerror("Erro da API", f"Falha ao enviar o lembrete: {mensagem_da_api(response)}", parent=self.root)
        except ErroAPI as e:
            messagebox.showerror("Erro de Conexão", str(e), parent=self.root)
        finally:
            self._ocupado(False)


if __name__ == "__main__":
    # 1. Cria e mostra a janela de login primeiro
    login_root = tk.Tk()
    login_app = LoginWindow(login_root)
    login_root.mainloop()

    # 2. O código só continua se o login for bem-sucedido
    if login_app.funcionario_logado:
        # 3. Abre a janela principal, passando os dados do funcionário que logou
        main_app_root = tk.Tk()
        app_principal = AppAgendamentos(main_app_root, login_app.funcionario_logado)
        main_app_root.mainloop()

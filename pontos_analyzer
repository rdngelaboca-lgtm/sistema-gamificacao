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
from tkinter import ttk, messagebox
from tkcalendar import DateEntry
from datetime import datetime, date, timedelta
import database # Importa nosso módulo de banco de dados
import config # Necessário para buscar_extrato_pontos_funcionario

class AppExtratoPontos: # <<< NOME DA CLASSE ALTERADO
    def __init__(self, root):
        self.root = root
        self.root.title("Extrato Detalhado de Pontos") # <<< TÍTULO ALTERADO
        self.root.geometry("900x600") # <<< Geometria pode ser ajustada

        self.dados_funcionarios = {}

        # --- Frame Principal ---
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1) # Linha do Extrato expande

        # --- Frame de Filtros (Mantido, mas simplificado) ---
        frame_filtros = ttk.LabelFrame(main_frame, text="Filtros", padding="10")
        frame_filtros.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(frame_filtros, text="Funcionário:").pack(side=tk.LEFT, padx=(0, 5))
        self.combo_funcionarios = ttk.Combobox(frame_filtros, state="readonly", width=40)
        self.combo_funcionarios.pack(side=tk.LEFT, padx=5)

        ttk.Label(frame_filtros, text="De:").pack(side=tk.LEFT, padx=(15, 5))
        self.date_inicio = DateEntry(frame_filtros, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_inicio.pack(side=tk.LEFT)
        hoje = date.today()
        primeiro_dia_mes = hoje.replace(day=1)
        self.date_inicio.set_date(primeiro_dia_mes)

        ttk.Label(frame_filtros, text="Até:").pack(side=tk.LEFT, padx=5)
        self.date_fim = DateEntry(frame_filtros, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_fim.pack(side=tk.LEFT)
        self.date_fim.set_date(hoje)

        btn_buscar = ttk.Button(frame_filtros, text="Buscar Extrato", command=self.buscar_extrato) # <<< COMANDO ALTERADO
        btn_buscar.pack(side=tk.LEFT, padx=20)

        # --- Frame Extrato ---
        frame_extrato = ttk.LabelFrame(main_frame, text="Extrato de Pontos", padding="10")
        frame_extrato.grid(row=1, column=0, sticky="nsew") # Ocupa a linha 1
        frame_extrato.rowconfigure(1, weight=1) # Linha da Treeview expande
        frame_extrato.columnconfigure(0, weight=1) # Coluna da Treeview expande

        # Labels Saldo Inicial/Final
        frame_saldos = ttk.Frame(frame_extrato)
        frame_saldos.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.lbl_saldo_inicial = ttk.Label(frame_saldos, text="Saldo Inicial no Período: --", font=("Arial", 10, "bold"))
        self.lbl_saldo_inicial.pack(side=tk.LEFT, padx=10)
        self.lbl_saldo_final = ttk.Label(frame_saldos, text="Saldo Final no Período: --", font=("Arial", 10, "bold"))
        self.lbl_saldo_final.pack(side=tk.RIGHT, padx=10)

        # Treeview do Extrato
        cols_ext = ('Data/Hora', 'Descrição/Origem', 'Pontos (+/-)', 'Saldo na Data') # <<< COLUNAS ALTERADAS
        self.tree_extrato = ttk.Treeview(frame_extrato, columns=cols_ext, show='headings') # <<< NOVO TREEVIEW

        # Configuração das Colunas
        self.tree_extrato.heading('Data/Hora', text='Data/Hora')
        self.tree_extrato.column('Data/Hora', width=150, anchor='center')
        self.tree_extrato.heading('Descrição/Origem', text='Descrição/Origem')
        self.tree_extrato.column('Descrição/Origem', width=350) # Maior largura
        self.tree_extrato.heading('Pontos (+/-)', text='Pontos (+/-)')
        self.tree_extrato.column('Pontos (+/-)', width=100, anchor='e') # Alinhado à direita
        self.tree_extrato.heading('Saldo na Data', text='Saldo na Data')
        self.tree_extrato.column('Saldo na Data', width=120, anchor='e') # Alinhado à direita

        # Adiciona Scrollbar
        scrollbar = ttk.Scrollbar(frame_extrato, orient="vertical", command=self.tree_extrato.yview)
        self.tree_extrato.configure(yscrollcommand=scrollbar.set)

        self.tree_extrato.grid(row=1, column=0, sticky="nsew") # Treeview na linha 1
        scrollbar.grid(row=1, column=1, sticky="ns")

        self.carregar_funcionarios()

    def carregar_funcionarios(self):
        """Carrega a lista de funcionários para o combobox."""
        funcionarios = database.listar_funcionarios()
        self.dados_funcionarios = {f.NomeCompleto: f.FuncionarioID for f in funcionarios}
        self.combo_funcionarios['values'] = list(self.dados_funcionarios.keys())
        if self.combo_funcionarios['values']:
            self.combo_funcionarios.current(0)

    def buscar_extrato(self): # <<< NOME DA FUNÇÃO ALTERADO
        """Busca o extrato de pontos e atualiza a interface."""
        # Limpa resultados anteriores
        for i in self.tree_extrato.get_children():
            self.tree_extrato.delete(i)
        self.lbl_saldo_inicial.config(text="Saldo Inicial no Período: --")
        self.lbl_saldo_final.config(text="Saldo Final no Período: --")

        nome_selecionado = self.combo_funcionarios.get()
        if not nome_selecionado:
            messagebox.showerror("Erro", "Selecione um funcionário.")
            return

        funcionario_id = self.dados_funcionarios[nome_selecionado]
        data_inicio = self.date_inicio.get_date()
        data_fim = self.date_fim.get_date()

        if data_inicio > data_fim:
            messagebox.showerror("Erro", "A data de início não pode ser posterior à data de fim.")
            return

        # Busca dados no banco usando a NOVA função
        try:
            extrato_completo, saldo_inicial_periodo = database.buscar_extrato_pontos_funcionario(funcionario_id, data_inicio, data_fim)
        except Exception as e:
            messagebox.showerror("Erro de Banco", f"Erro ao buscar extrato: {e}")
            logger.exception("Erro em buscar_extrato:") # Loga o traceback
            return

        # Preenche a Treeview do Extrato
        saldo_final_periodo = saldo_inicial_periodo # Começa com o saldo inicial
        if not extrato_completo:
            self.tree_extrato.insert("", "end", values=("", "Nenhuma transação no período.", "", ""))
        else:
            for transacao in extrato_completo:
                data_hora_f = transacao['DataTransacao'].strftime('%d/%m/%Y %H:%M:%S') if transacao['DataTransacao'] else 'N/A'
                pontos_f = f"+{transacao['Pontos']}" if transacao['Pontos'] > 0 else str(transacao['Pontos'])
                saldo_f = transacao.get('SaldoNaData', 'N/A') # Pega o saldo calculado no DB

                # Atualiza o saldo final com a última transação
                if saldo_f != 'N/A':
                     saldo_final_periodo = saldo_f

                self.tree_extrato.insert("", "end", values=(
                    data_hora_f,
                    transacao['Descricao'],
                    pontos_f,
                    saldo_f
                ))

        # Atualiza os labels de Saldo Inicial e Final
        self.lbl_saldo_inicial.config(text=f"Saldo Inicial no Período: {saldo_inicial_periodo}")
        self.lbl_saldo_final.config(text=f"Saldo Final no Período: {saldo_final_periodo}")


# Início do Bloco Principal (fora da classe)
if __name__ == "__main__":
    root = tk.Tk()
    app = AppExtratoPontos(root) # <<< NOME DA CLASSE ALTERADO
    root.mainloop()

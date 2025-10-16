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
        self.frame_solicitacoes = ttk.Frame(self.notebook)
        self.frame_agenda = ttk.Frame(self.notebook)
        self.frame_loja = ttk.Frame(self.notebook)
        self.frame_metas = ttk.Frame(self.notebook, padding="10")

        self.notebook.add(self.frame_dashboard, text='Dashboard')
        self.notebook.add(self.frame_funcionarios, text='Gerenciar Funcionários')
        self.notebook.add(self.frame_grupos, text='Gerenciar Grupos')
        self.notebook.add(self.frame_tarefas, text='Catálogo de Tarefas')
        self.notebook.add(self.frame_atribuicoes, text='Atribuir Tarefas')
        self.notebook.add(self.frame_validacao, text='Validar Entregas')
        self.notebook.add(self.frame_ranking, text='Ranking')
        self.notebook.add(self.frame_relatorios, text='Relatórios')
        self.notebook.add(self.frame_feedbacks, text='Feedbacks')
        self.notebook.add(self.frame_solicitacoes, text='Feedbacks Pendentes')
        self.notebook.add(self.frame_agenda, text='Agenda Semanal')
        self.notebook.add(self.frame_loja, text='Loja e Resgates')
        self.notebook.add(self.frame_metas, text='Gestão de Metas')

        self.criar_aba_dashboard()
        self.criar_aba_funcionarios()
        self.criar_aba_grupos()
        self.criar_aba_tarefas()
        self.criar_aba_atribuicoes()
        self.criar_aba_validacao()
        self.criar_aba_ranking()
        self.criar_aba_relatorios()
        self.criar_aba_feedbacks()
        self.criar_aba_solicitacoes()
        self.criar_aba_agenda()
        self.criar_aba_loja()
        self.criar_aba_metas()



    def popular_combobox_filtro_setor(self):
        """Busca os setores únicos e popula o combobox de filtro."""
        setores = database.listar_setores_unicos()
        # Adicionamos a opção "Outras Tarefas" para tarefas sem setor definido
        self.combo_filtro_setor['values'] = setores + ["Outras Tarefas"]

    def limpar_filtro_tarefas(self):
        """Limpa o filtro de setor e de título, e recarrega todas as tarefas."""
        self.combo_filtro_setor.set('')
        self.entry_filtro_atr_tarefas.delete(0, tk.END)
        self.atualizar_lista_tarefas_atribuicao() # Chama a função principal sem filtro

    def filtrar_tarefas_por_setor(self, event=None):
        """Pega o setor selecionado e chama a função de atualização com o filtro."""
        setor_selecionado = self.combo_filtro_setor.get()
        if setor_selecionado:
            # Chama a função de atualização, passando o setor como filtro
            self.atualizar_lista_tarefas_atribuicao(filtro_setor=setor_selecionado)

    # --- SEÇÃO DE CRIAÇÃO DAS ABAS ---
    def criar_aba_dashboard(self):
        ttk.Label(self.frame_dashboard, text="Dashboard de Performance", font=("Arial", 16)).pack(pady=10)
        frame_grafico = ttk.Frame(self.frame_dashboard); frame_grafico.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        fig = Figure(figsize=(8, 5), dpi=100, tight_layout=True); self.ax_ranking = fig.add_subplot(111)
        self.canvas_grafico = FigureCanvasTkAgg(fig, master=frame_grafico)
        self.canvas_grafico.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        btn_atualizar = ttk.Button(self.frame_dashboard, text="Atualizar Dashboard", command=self.desenhar_grafico_ranking); btn_atualizar.pack(pady=10)
        self.desenhar_grafico_ranking()

    # Em main.py, dentro da class App
    def atualizar_combobox_setores(self):
        """Busca os setores únicos do banco e atualiza a lista do combobox."""
        setores = database.listar_setores_unicos()
        self.combo_setor_tarefa['values'] = setores

    def criar_aba_agenda(self):
        """Cria a interface da aba de Agenda Semanal."""
        main_frame = ttk.Frame(self.frame_agenda, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Frame de Filtro ---
        frame_filtro = ttk.Frame(main_frame, padding="10")
        frame_filtro.pack(fill=tk.X)
        
        ttk.Label(frame_filtro, text="Selecione o Funcionário:", font=("Arial", 12)).pack(side=tk.LEFT)
        
        self.combo_funcionarios_agenda = ttk.Combobox(frame_filtro, state="readonly", width=40, font=("Arial", 10))
        self.combo_funcionarios_agenda.pack(side=tk.LEFT, padx=10)
        self.combo_funcionarios_agenda.bind("<<ComboboxSelected>>", self.exibir_agenda_funcionario)
        
        # --- Frame da Agenda (Tabela) ---
        frame_tabela = ttk.Frame(main_frame, padding="10")
        frame_tabela.pack(fill=tk.BOTH, expand=True)
        
        # Definindo as colunas para os dias da semana
        dias_semana = ('Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo')
        self.tree_agenda = ttk.Treeview(frame_tabela, columns=dias_semana, show='headings')
        
        # Configurando os cabeçalhos
        for dia in dias_semana:
            self.tree_agenda.heading(dia, text=dia)
            self.tree_agenda.column(dia, width=150)

        # Remove a coluna fantasma "#0"
        self.tree_agenda.column("#0", width=0, stretch=tk.NO)
        
        self.tree_agenda.pack(fill=tk.BOTH, expand=True)

        self.carregar_funcionarios_agenda()

    def criar_aba_loja(self):
        main_frame = ttk.Frame(self.frame_loja, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1) 
        main_frame.columnconfigure(1, weight=1)

        # --- PAINEL ESQUERDO: GESTÃO DE PRODUTOS ---
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

        # --- PAINEL DIREITO: GESTÃO DE RESGATES ---
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
        # Criamos um dicionário para mapear o nome exibido para o ID do funcionário
        self.dados_funcionarios_agenda = {f"{f.NomeCompleto} (ID: {f.FuncionarioID})": f.FuncionarioID for f in funcionarios}
        self.combo_funcionarios_agenda['values'] = list(self.dados_funcionarios_agenda.keys())

    def exibir_agenda_funcionario(self, event=None):
        """Busca as tarefas do funcionário selecionado e as exibe na agenda semanal."""
        # Limpa a tabela
        for i in self.tree_agenda.get_children():
            self.tree_agenda.delete(i)

        nome_selecionado = self.combo_funcionarios_agenda.get()
        if not nome_selecionado:
            return

        funcionario_id = self.dados_funcionarios_agenda[nome_selecionado]
        tarefas = database.listar_agenda_semanal_por_funcionario(funcionario_id)
        
        # Dicionário para organizar as tarefas por dia
        agenda_semanal = {
            '2': [], '3': [], '4': [], '5': [], '6': [], '7': [], '1': []
        }
        tarefas_diarias = []

        for tarefa in tarefas:
            if tarefa.TipoFrequencia == 'Diaria':
                tarefas_diarias.append(tarefa.Titulo)
            elif tarefa.TipoFrequencia == 'Semanal':
                # ValorFrequencia: 1=Dom, 2=Seg, ..., 7=Sab
                agenda_semanal[str(tarefa.ValorFrequencia)].append(tarefa.Titulo)
        
        # Preenche as tarefas diárias em todos os dias da semana
        for dia in agenda_semanal:
            agenda_semanal[dia].extend(tarefas_diarias)

        # Encontra o número máximo de tarefas em um único dia para criar as linhas
        max_linhas = 0
        for tarefas_do_dia in agenda_semanal.values():
            if len(tarefas_do_dia) > max_linhas:
                max_linhas = len(tarefas_do_dia)
                
        if max_linhas == 0 and not tarefas_diarias:
            return

        # Insere as linhas na tabela
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

    # Em main.py, SUBSTITUA a função desenhar_grafico_ranking inteira:
    # Em main.py, SUBSTITUA a função antiga por esta versão com espaçamento aprimorado

    def desenhar_grafico_ranking(self):
        self.ax_ranking.clear()
        
        # Usando a calculadora de desempenho original conforme seu código
        ranking_data = database.calcular_ranking_desempenho()[:5]

        if not ranking_data:
            self.ax_ranking.text(0.5, 0.5, "Sem dados para exibir.", ha='center', va='center')
            self.canvas_grafico.draw()
            return

        ranking_data.reverse() 
        nomes = [row['NomeCompleto'] for row in ranking_data]
        percentuais = [row['Desempenho'] for row in ranking_data]
        
        # <<< MUDANÇA 1: Ajustando a espessura das barras
        # Adicionamos o parâmetro 'height' para que as barras não sejam tão grossas. 0.6 é um bom valor.
        self.ax_ranking.barh(nomes, percentuais, color='skyblue', height=0.6)
        
        # Adiciona o valor do percentual no final de cada barra
        for index, value in enumerate(percentuais):
            # <<< MUDANÇA 2: Adicionando espaçamento e alinhamento
            # Adicionamos '+ 0.5' ao 'value' para criar uma margem à direita da barra.
            # Adicionamos 'va='center'' para garantir que o texto fique perfeitamente alinhado no meio da barra.
            self.ax_ranking.text(value + 0.5, index, f' {value}%', va='center')
            
        self.ax_ranking.set_title('Top 5 Funcionários por Desempenho (%)')
        self.ax_ranking.set_xlabel('Percentual de Desempenho')
        self.ax_ranking.set_xlim(0, 110)
        self.ax_ranking.spines['top'].set_visible(False)
        self.ax_ranking.spines['right'].set_visible(False)
        
        # <<< MUDANÇA 3: Garantindo que o layout não se sobreponha
        # Força o Matplotlib a ajustar todos os elementos para que caibam sem cortar títulos ou eixos.
        self.canvas_grafico.figure.tight_layout()
        
        self.canvas_grafico.draw()


    def on_funcionario_selecionado(self, event):
        """Chamada quando um funcionário é selecionado na lista."""
        # Limpa a lista de tarefas do funcionário anterior
        for i in self.tree_tarefas_funcionario.get_children():
            self.tree_tarefas_funcionario.delete(i)

        indices = self.lista_funcionarios.curselection()
        if not indices:
            return

        # Pega o ID do funcionário selecionado
        texto_selecionado = self.lista_funcionarios.get(indices[0])
        funcionario_selecionado = self.dados_funcionarios[texto_selecionado]
        funcionario_id = funcionario_selecionado.FuncionarioID

        # Busca as tarefas ativas para esse funcionário no banco
        tarefas_ativas = database.listar_atribuicoes_ativas_por_funcionario(funcionario_id)

        # Preenche a nova lista de tarefas
        for tarefa in tarefas_ativas:
            self.tree_tarefas_funcionario.insert("", "end", values=tuple(tarefa))
        
        # Opcional: muda para a aba de tarefas automaticamente
        self.notebook_funcionarios.select(self.notebook_funcionarios.tabs()[1])


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
        """
        Esta função é chamada SEMPRE que um grupo é selecionado na lista.
        Ela busca os membros e não-membros do grupo no banco de dados e atualiza as listas.
        """
        # Limpa as duas listas (de membros e não-membros) antes de preenchê-las
        for i in self.tree_membros.get_children():
            self.tree_membros.delete(i)
        for i in self.tree_nao_membros.get_children():
            self.tree_nao_membros.delete(i)

        # Pega o item que foi selecionado na lista de grupos
        selecionado = self.tree_grupos.focus()
        if not selecionado:
            return # Se nada estiver selecionado, não faz nada

        # Pega o ID do grupo a partir dos valores da linha selecionada
        dados_grupo = self.tree_grupos.item(selecionado, 'values')
        if not dados_grupo:
            return # Se a linha estiver vazia, não faz nada
            
        grupo_id = dados_grupo[0]

        # Busca no banco de dados quem é membro e quem não é
        membros, nao_membros = database.listar_membros_e_nao_membros(grupo_id)

        # Preenche a lista da direita (membros atuais)
        for membro in membros:
            self.tree_membros.insert("", "end", values=(membro.FuncionarioID, membro.NomeCompleto))
        
        # Preenche a lista da esquerda (funcionários disponíveis para adicionar)
        for nao_membro in nao_membros:
            self.tree_nao_membros.insert("", "end", values=(nao_membro.FuncionarioID, nao_membro.NomeCompleto))    

    def atualizar_lista_grupos(self):
        """Limpa e recarrega a lista de grupos do banco de dados."""
        for i in self.tree_grupos.get_children():
            self.tree_grupos.delete(i)
        for grupo in database.listar_grupos():
            self.tree_grupos.insert("", "end", values=(grupo.GrupoID, grupo.NomeGrupo, grupo.ChatIDTelegram))

    def criar_novo_grupo(self):
        """Abre pop-ups para pedir o nome e o chat_id e cria um novo grupo."""
        nome = simpledialog.askstring("Novo Grupo", "Digite o nome do novo grupo:", parent=self.root)
        if nome:
            chat_id = simpledialog.askstring("Chat ID", f"Digite o Chat ID do Telegram para o grupo '{nome}':", parent=self.root)
            if chat_id:
                database.criar_grupo(nome, chat_id)
                self.atualizar_lista_grupos() # Atualiza a lista para mostrar o novo grupo

    def editar_grupo_selecionado(self):
        """Pega o grupo selecionado e abre pop-ups para editar seus dados."""
        selecionado = self.tree_grupos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um grupo para editar.")
            return

        dados_grupo = self.tree_grupos.item(selecionado, 'values')
        grupo_id, nome_antigo, chat_id_antigo = dados_grupo

        novo_nome = simpledialog.askstring("Editar Grupo", "Digite o novo nome do grupo:", initialvalue=nome_antigo, parent=self.root)
        if novo_nome:
            novo_chat_id = simpledialog.askstring("Editar Chat ID", "Digite o novo Chat ID do Telegram:", initialvalue=chat_id_antigo, parent=self.root)
            if novo_chat_id:
                database.atualizar_grupo(grupo_id, novo_nome, novo_chat_id)
                self.atualizar_lista_grupos()

    def excluir_grupo_selecionado(self):
        """Exclui o grupo selecionado após uma confirmação."""
        selecionado = self.tree_grupos.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione um grupo para excluir.")
            return

        dados_grupo = self.tree_grupos.item(selecionado, 'values')
        grupo_id, nome_grupo, _ = dados_grupo

        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o grupo '{nome_grupo}'?"):
            database.excluir_grupo(grupo_id)
            self.atualizar_lista_grupos()

    def adicionar_membros_ao_grupo(self):
        """Adiciona os funcionários selecionados da lista de 'disponíveis' ao grupo."""
        grupo_selecionado = self.tree_grupos.focus()
        if not grupo_selecionado:
            messagebox.showwarning("Aviso", "Selecione um grupo primeiro.")
            return
        
        funcionarios_selecionados = self.tree_nao_membros.selection()
        if not funcionarios_selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos um funcionário da lista de 'Disponíveis'.")
            return

        grupo_id = self.tree_grupos.item(grupo_selecionado, 'values')[0]
        for item in funcionarios_selecionados:
            funcionario_id = self.tree_nao_membros.item(item, 'values')[0]
            database.adicionar_membro_ao_grupo(funcionario_id, grupo_id)

        # Dispara o evento de seleção novamente para atualizar os painéis
        self.popular_paineis_de_membros(None) 
    
    def remover_membros_do_grupo(self):
        """Remove os funcionários selecionados da lista de 'membros' do grupo."""
        grupo_selecionado = self.tree_grupos.focus()
        if not grupo_selecionado:
            messagebox.showwarning("Aviso", "Selecione um grupo primeiro.")
            return

        funcionarios_selecionados = self.tree_membros.selection()
        if not funcionarios_selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos um funcionário da lista de 'Membros Atuais'.")
            return

        grupo_id = self.tree_grupos.item(grupo_selecionado, 'values')[0]
        for item in funcionarios_selecionados:
            funcionario_id = self.tree_membros.item(item, 'values')[0]
            database.remover_membro_do_grupo(funcionario_id, grupo_id)
        
        # Dispara o evento de seleção novamente para atualizar os painéis
        self.popular_paineis_de_membros(None)        

    # COPIE ESTE BLOCO DE CÓDIGO INTEIRO E COLE NO LUGAR DO ANTIGO
    # Em main.py, SUBSTITUA a função atualizar_lista_tarefas_atribuicao por esta:

    def atualizar_lista_tarefas_atribuicao(self, filtro_setor=None):
        """(VERSÃO FINAL) Carrega a lista de tarefas, agrupada por setor, aplicando um filtro opcional."""
        for i in self.tree_atr_tarefas.get_children():
            self.tree_atr_tarefas.delete(i)

        setores_nodes = {}
        
        # Passamos o filtro para a função do banco de dados
        tarefas = database.listar_tarefas_para_atribuicao(filtro_setor)

        for tarefa in tarefas:
            setor_nome = tarefa.Setor if tarefa.Setor else "Outras Tarefas"

            if setor_nome not in setores_nodes:
                setor_node = self.tree_atr_tarefas.insert("", "end", text=setor_nome, open=True) # open=True para já vir expandido
                setores_nodes[setor_nome] = setor_node
            else:
                setor_node = setores_nodes[setor_nome]

            self.tree_atr_tarefas.insert(setor_node, "end", text=tarefa.Titulo, values=(tarefa.TarefaID, tarefa.Titulo))

    # Em main.py, substitua a função antiga por esta:

    def filtrar_lista_tarefas_atribuicao(self):
        """
        (VERSÃO CORRIGIDA)
        Filtra a lista de tarefas, mas MANTÉM a estrutura de agrupamento por setor.
        """
        termo_busca = self.entry_filtro_atr_tarefas.get().lower()

        # Limpa a árvore de tarefas completamente
        for i in self.tree_atr_tarefas.get_children():
            self.tree_atr_tarefas.delete(i)

        # Reutiliza a mesma lógica da função principal de atualização
        setores_nodes = {}
        
        # Busca todas as tarefas disponíveis no banco
        tarefas = database.listar_tarefas_para_atribuicao()

        # Itera sobre as tarefas e aplica o filtro ANTES de inserir na árvore
        for tarefa in tarefas:
            # A MÁGICA ESTÁ AQUI: Só continua se o termo de busca estiver no título
            if termo_busca not in tarefa.Titulo.lower():
                continue # Pula para a próxima tarefa

            # O resto do código é idêntico ao de 'atualizar_lista_tarefas_atribuicao'
            setor_nome = tarefa.Setor if tarefa.Setor else "Outras Tarefas"

            if setor_nome not in setores_nodes:
                setor_node = self.tree_atr_tarefas.insert("", "end", text=setor_nome, open=True)
                setores_nodes[setor_nome] = setor_node
            else:
                setor_node = setores_nodes[setor_nome]

            self.tree_atr_tarefas.insert(setor_node, "end", text=tarefa.Titulo, values=(tarefa.TarefaID, tarefa.Titulo))

    def atualizar_painel_selecao(self, tarefa_id=None):
        """
        Atualiza a lista de alvos (funcionários ou grupos).
        Se um tarefa_id for fornecido, filtra os funcionários.
        """
        for i in self.tree_atr_selecao.get_children():
            self.tree_atr_selecao.delete(i)
        
        modo = self.modo_atribuicao.get()
        if modo == "Individual":
            # --- LÓGICA NOVA E INTELIGENTE ---
            if tarefa_id:
                # Se temos uma tarefa, usamos a nova função do banco
                _, disponiveis = database.listar_funcionarios_por_tarefa(tarefa_id)
                alvos = disponiveis # Usaremos apenas a lista de disponíveis
            else:
                # Se nenhuma tarefa foi selecionada, mostra todos como antes
                alvos = database.listar_funcionarios()
            
            for alvo in alvos:
                self.tree_atr_selecao.insert("", "end", values=(alvo.FuncionarioID, alvo.NomeCompleto))

        elif modo == "Grupo":
            # Para grupos, a lógica continua a mesma de antes
            alvos = database.listar_grupos()
            for alvo in alvos:
                self.tree_atr_selecao.insert("", "end", values=(alvo.GrupoID, alvo.NomeGrupo))

    def atualizar_lista_atribuicoes_ativas(self):
        """Carrega/Atualiza a lista de tarefas que já foram atribuídas."""
        for i in self.tree_atribuicoes_ativas.get_children():
            self.tree_atribuicoes_ativas.delete(i)
        for atribuicao in database.listar_atribuicoes_ativas():
            self.tree_atribuicoes_ativas.insert("", "end", values=atribuicao)

    def desatribuir_tarefa_selecionada(self):
        """
        Encerra a validade de uma atribuição e atualiza AMBAS as listas na tela.
        """
        # Primeiro, verificamos qual tarefa está selecionada no painel 1 (de tarefas)
        # para sabermos qual contexto de funcionários recarregar depois.
        tarefa_selecionada_item = self.tree_atr_tarefas.focus()
        if not tarefa_selecionada_item:
            messagebox.showwarning("Aviso", "Por favor, selecione uma tarefa no painel da esquerda primeiro.")
            return

        # Agora, verificamos qual atribuição está selecionada no painel 3 (de atribuições)
        atribuicao_selecionada_item = self.tree_atribuicoes_ativas.focus()
        if not atribuicao_selecionada_item:
            messagebox.showwarning("Aviso", "Selecione uma atribuição da lista da direita para encerrar.")
            return
        
        # Com tudo selecionado, pegamos os IDs de que precisamos
        atribuicao_id = self.tree_atribuicoes_ativas.item(atribuicao_selecionada_item, 'values')[0]
        tarefa_id_contexto = self.tree_atr_tarefas.item(tarefa_selecionada_item, 'values')[0]
        
        if messagebox.askyesno("Confirmar Encerramento", "Tem certeza que deseja encerrar esta atribuição?\n\nA tarefa não será mais considerada para o funcionário a partir de hoje."):
            # 1. Encerra a atribuição no banco de dados
            database.encerrar_atribuicao_tarefa(atribuicao_id)

            # 2. Atualiza a lista da DIREITA (Atribuições Ativas)
            self.atualizar_lista_atribuicoes_ativas()

            # 3. A CORREÇÃO MÁGICA: Atualiza a lista do MEIO (Alvos Disponíveis)
            self.atualizar_painel_selecao(tarefa_id=tarefa_id_contexto)
            
            messagebox.showinfo("Sucesso", "Atribuição encerrada com sucesso.")


    def abrir_popup_frequencia_universal(self):
        """
        Abre um pop-up inteligente para atribuição e
        garante que a tela principal seja atualizada após a ação. (VERSÃO COM BLOQUEIO DE DUPLICIDADE)
        """
        tarefa_selecionada_item = self.tree_atr_tarefas.focus()
        alvos_selecionados_items = self.tree_atr_selecao.selection()

        if not tarefa_selecionada_item or not alvos_selecionados_items:
            messagebox.showwarning("Aviso", "Selecione uma tarefa e pelo menos um alvo (funcionário ou grupo).")
            return

        tarefa_id = self.tree_atr_tarefas.item(tarefa_selecionada_item, 'values')[0]
        tarefa_titulo = self.tree_atr_tarefas.item(tarefa_selecionada_item, 'values')[1]

        popup = tk.Toplevel(self.root)
        popup.title(f"Atribuir '{tarefa_titulo}'")
        frame = ttk.Frame(popup, padding="10"); frame.pack(fill="both", expand=True)
        modo = self.modo_atribuicao.get()

        if modo == "Grupo":
            # ... (a lógica de grupo não muda)
            popup.geometry("300x200")
            ttk.Label(frame, text="Disparar esta tarefa para o grupo no horário:").pack(pady=5)
            horario_var = tk.StringVar(value="18:00"); ttk.Entry(frame, textvariable=horario_var, width=10).pack(pady=5)
            def confirmar_atribuicao_grupo():
                horario = horario_var.get()
                try: datetime.strptime(horario, '%H:%M')
                except ValueError: messagebox.showerror("Erro", "Formato inválido. Use HH:MM.", parent=popup); return
                for item in alvos_selecionados_items:
                    grupo_id = self.tree_atr_selecao.item(item, 'values')[0]
                    # A MÁGICA ESTÁ AQUI: Usamos o novo nome da função
                    database.agendar_tarefa_competitiva_para_grupo(tarefa_id, grupo_id, horario) # <<< LINHA CORRIGIDA
                messagebox.showinfo("Sucesso", "Tarefa de grupo agendada!", parent=popup); popup.destroy(); self.atualizar_lista_atribuicoes_ativas()
            ttk.Button(frame, text="Agendar Tarefa de Grupo", command=confirmar_atribuicao_grupo).pack(pady=20)
        
        else: # modo == "Individual"
            # Lógica Individual (COM A NOVA VERIFICAÇÃO)
            popup.geometry("350x350")
            ttk.Label(frame, text="Selecione a Frequência:").pack(anchor=tk.W)
            frequencia = tk.StringVar(value="Diaria")
            ttk.Radiobutton(frame, text="Tarefa Única", variable=frequencia, value="Unica").pack(anchor=tk.W)
            ttk.Radiobutton(frame, text="Diária", variable=frequencia, value="Diaria").pack(anchor=tk.W)
            ttk.Radiobutton(frame, text="Semanal (marque os dias):", variable=frequencia, value="Semanal").pack(anchor=tk.W, pady=(10,0))
            frame_semanal = ttk.Frame(frame, padding=(20, 2, 0, 0)); frame_semanal.pack(fill=tk.X)
            dias_semana_vars = {"Seg": (tk.BooleanVar(), "2"), "Ter": (tk.BooleanVar(), "3"), "Qua": (tk.BooleanVar(), "4"),
                                "Qui": (tk.BooleanVar(), "5"), "Sex": (tk.BooleanVar(), "6"), "Sáb": (tk.BooleanVar(), "7"),
                                "Dom": (tk.BooleanVar(), "1")}
            for dia, (var, _) in dias_semana_vars.items(): ttk.Checkbutton(frame_semanal, text=dia, variable=var).pack(side=tk.LEFT)
            frame_mensal = ttk.Frame(frame); frame_mensal.pack(anchor=tk.W, fill=tk.X, pady=(10,0))
            ttk.Radiobutton(frame_mensal, text="Mensal (dia):", variable=frequencia, value="Mensal").pack(side=tk.LEFT)
            valor_mensal = tk.StringVar(); ttk.Entry(frame_mensal, textvariable=valor_mensal, width=5).pack(side=tk.LEFT)

            def confirmar_atribuicao_individual():
                tipo_freq = frequencia.get()
                alvos = {item: self.tree_atr_selecao.item(item, 'values') for item in alvos_selecionados_items}
                ignorados = []
                
                for item_id, (func_id, func_nome) in alvos.items():
                    # --- AQUI ESTÁ A NOVA VERIFICAÇÃO ---
                    if database.verificar_atribuicao_existente(tarefa_id, func_id):
                        ignorados.append(func_nome)
                        continue # Pula para o próximo funcionário

                    # Se não existe, atribui normalmente
                    if tipo_freq == "Semanal":
                        dias = [val for _, (var, val) in dias_semana_vars.items() if var.get()]
                        if not dias: messagebox.showerror("Erro", "Selecione um dia da semana.", parent=popup); return
                        for dia in dias: database.atribuir_tarefa(tarefa_id, func_id, tipo_freq, dia)
                    else:
                        val = valor_mensal.get() if tipo_freq == "Mensal" else None
                        if tipo_freq == "Mensal" and not val: messagebox.showerror("Erro", "Digite o dia do mês.", parent=popup); return
                        database.atribuir_tarefa(tarefa_id, func_id, tipo_freq, val)

                mensagem_sucesso = "Tarefa(s) atribuída(s) com sucesso!"
                if ignorados:
                    mensagem_sucesso += f"\n\nAviso: As atribuições para {', '.join(ignorados)} foram ignoradas pois já existiam."

                messagebox.showinfo("Sucesso", mensagem_sucesso, parent=popup)
                popup.destroy()
                
                self.atualizar_lista_atribuicoes_ativas()
                self.atualizar_painel_selecao(tarefa_id=tarefa_id)

            ttk.Button(frame, text="Confirmar Atribuição", command=confirmar_atribuicao_individual).pack(pady=20)

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
        
    def criar_aba_ranking(self):
        ttk.Label(self.frame_ranking, text="Ranking de Desempenho Mensal", font=("Arial", 16)).pack(pady=10)
        
        cols = ('Posição', 'Nome', 'Score Final', 'Desempenho %', 'Pontos Ganhos', 'Pontos Possíveis')
        self.tree_ranking = ttk.Treeview(self.frame_ranking, columns=cols, show='headings')
        
        self.tree_ranking.heading('Posição', text='Pos.')
        self.tree_ranking.column('Posição', width=40, anchor='center')
        self.tree_ranking.heading('Nome', text='Funcionário')
        self.tree_ranking.column('Nome', width=300)
        self.tree_ranking.heading('Score Final', text='Score Final') # <<< NOVA COLUNA
        self.tree_ranking.column('Score Final', width=100, anchor='center')
        self.tree_ranking.heading('Desempenho %', text='Confiabilidade (%)') # <<< NOME MELHORADO
        self.tree_ranking.column('Desempenho %', width=120, anchor='center')
        self.tree_ranking.heading('Pontos Ganhos', text='Pontos (Esforço)') # <<< NOME MELHORADO
        self.tree_ranking.column('Pontos Ganhos', width=120, anchor='center')
        self.tree_ranking.heading('Pontos Possíveis', text='Pontos Possíveis')
        self.tree_ranking.column('Pontos Possíveis', width=120, anchor='center')

        self.tree_ranking.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        btn_atualizar_ranking = ttk.Button(self.frame_ranking, text="Atualizar Ranking", command=self.atualizar_ranking)
        btn_atualizar_ranking.pack(pady=10)
        
        self.atualizar_ranking()

    def criar_aba_relatorios(self):
        # Frame principal que usará um grid para dividir a tela
        frame_principal = ttk.Frame(self.frame_relatorios, padding="10")
        frame_principal.pack(fill=tk.BOTH, expand=True)
        frame_principal.columnconfigure(1, weight=1) # Coluna da direita (resultados) cresce
        frame_principal.rowconfigure(0, weight=1)    # A linha inteira cresce

        # --- PAINEL ESQUERDO: SELEÇÃO DE RELATÓRIOS ---
        frame_selecao = ttk.LabelFrame(frame_principal, text="Tipos de Relatório", padding="10")
        frame_selecao.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        # Usaremos uma Listbox para o usuário escolher o relatório
        self.lista_relatorios = tk.Listbox(frame_selecao, exportselection=False)
        self.lista_relatorios.pack(fill=tk.Y, expand=True)

        # Adicionamos as opções de relatório
        self.lista_relatorios.insert(tk.END, "Pendências Recorrentes")
        self.lista_relatorios.insert(tk.END, "Análise de Tarefas")
        # Futuramente, adicionaremos mais relatórios aqui...
        # self.lista_relatorios.insert(tk.END, "Desempenho por Grupo")
        # self.lista_relatorios.insert(tk.END, "Análise de Tendências")

        # Configura um evento para chamar uma função sempre que a seleção mudar
        self.lista_relatorios.bind('<<ListboxSelect>>', self.on_report_select)

        # Seleciona o primeiro item por padrão
        self.lista_relatorios.select_set(0)

        # --- PAINEL DIREITO: FILTROS E RESULTADOS ---
        self.frame_conteudo_relatorio = ttk.Frame(frame_principal)
        self.frame_conteudo_relatorio.grid(row=0, column=1, sticky="nsew")

        # Dispara o evento manualmente para carregar a tela do primeiro relatório
        self.on_report_select(None)

    # Em main.py, adicione esta NOVA função
    def on_report_select(self, event):
        """
        Chamada sempre que um relatório é selecionado na lista.
        Ela limpa o painel da direita e constrói a interface para o relatório escolhido.
        """
        # Pega o índice do item selecionado
        selecionado_indices = self.lista_relatorios.curselection()
        if not selecionado_indices:
            return 
        
        nome_relatorio = self.lista_relatorios.get(selecionado_indices[0])

        # Limpa tudo que estava no frame da direita
        for widget in self.frame_conteudo_relatorio.winfo_children():
            widget.destroy()

        # Decide qual interface construir com base na seleção
        if nome_relatorio == "Pendências Recorrentes":
            self.construir_ui_relatorio_pendencias()
        elif nome_relatorio == "Análise de Tarefas":
            self.construir_ui_relatorio_analise_tarefas()
        # Futuramente, teremos mais 'elifs' para outros relatórios

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
                # Pega o texto da aba que foi selecionada
                tab_text = event.widget.tab(event.widget.select(), "text")

                # O dicionário mapeia o nome da aba para a função que deve ser executada
                tab_map = {
                    "Gerenciar Grupos": self.atualizar_lista_grupos,
                    "Atribuir Tarefas": self.on_tab_atribuir_tarefas_selected,
                    "Dashboard": self.desenhar_grafico_ranking,
                    "Ranking": self.atualizar_ranking,
                    "Gerenciar Funcionários": self.atualizar_lista_funcionarios,
                    "Catálogo de Tarefas": self.atualizar_catalogo_tarefas,
                    "Feedbacks Pendentes": self.atualizar_lista_solicitacoes,
                    "Loja e Resgates": self.carregar_dados_loja,
                    "Gestão de Metas": self.carregar_dados_metas
                }

                # Verifica se a aba selecionada está no nosso mapa de funções
                if tab_text in tab_map:
                    # Se estiver, executa a função correspondente
                    tab_map[tab_text]()

            except tk.TclError:
                # Isso evita um erro que pode acontecer se a janela for fechada
                # enquanto uma aba está sendo trocada.
                pass
        
   
    def on_tab_atribuir_tarefas_selected(self):
        self.atualizar_lista_tarefas_atribuicao()
        self.atualizar_painel_selecao()
        self.atualizar_lista_atribuicoes_ativas()

    def carregar_dados_loja(self):
        # Carrega produtos
        for i in self.tree_produtos_loja.get_children(): self.tree_produtos_loja.delete(i)
        produtos = database.listar_produtos_loja(incluir_inativos=True)
        for p in produtos:
            estoque = p.EstoqueDisponivel if p.EstoqueDisponivel is not None else "Ilimitado"
            status = "Ativo" if p.Ativo else "Inativo"
            self.tree_produtos_loja.insert("", "end", values=(p.ProdutoID, p.Nome, p.CustoEmPontos, estoque, status))

        # Carrega resgates pendentes
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
        
        GESTOR_ID = 2 # IMPORTANTE: Assumindo que o gestor logado tem ID 2. Mude se for outro.
        sucesso = database.aprovar_resgate(resgate_id, GESTOR_ID)
        
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
        # Limpa o painel da direita para começar
        for i in self.tree_atribuicoes_ativas.get_children():
            self.tree_atribuicoes_ativas.delete(i)

        selecionado = self.tree_atr_tarefas.focus()
        if not selecionado: # Se nada estiver selecionado, não faz nada
            return

        # Pega os valores do item clicado
        values = self.tree_atr_tarefas.item(selecionado, 'values')

        # --- O PORTEIRO INTELIGENTE ESTÁ AQUI ---
        if not values or not values[0]:
            # Se 'values' estiver vazio ou o primeiro item for vazio, significa
            # que o usuário clicou em um cabeçalho de setor (uma "pasta").
            # Neste caso, apenas limpamos os painéis e paramos a função.
            self.atualizar_painel_selecao() # Limpa o painel do meio
            return # Para a execução aqui
        # ----------------------------------------
        
        # Se o código chegou até aqui, sabemos que é uma tarefa válida ("arquivo").
        # A execução continua normalmente.
        tarefa_id_selecionada = values[0]
        tarefa_titulo_selecionado = values[1]

        # Atualiza o painel do meio (alvos) como antes
        if self.modo_atribuicao.get() == "Individual":
            self.atualizar_painel_selecao(tarefa_id=tarefa_id_selecionada)
        else:
            self.atualizar_painel_selecao()

        # FILTRA o painel da direita (atribuições ativas)
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

        database.adicionar_funcionario(nome, chat_id, cargo, horario, dia_folga_valor)
        messagebox.showinfo("Sucesso", f"Funcionário {nome} adicionado com sucesso!")
        
        self.entry_nome.delete(0, tk.END)
        self.entry_chat_id.delete(0, tk.END)
        self.entry_cargo.delete(0, tk.END)
        self.entry_horario.delete(0, tk.END); self.entry_horario.insert(0, "08:00")
        self.combo_folga.set('Sem Folga Definida')
        
        self.atualizar_todas_as_listas()

    def abrir_janela_edicao_funcionario(self):
        indices = self.lista_funcionarios.curselection()
        if not indices:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário da lista para editar.")
            return
        
        texto_selecionado = self.lista_funcionarios.get(indices[0])
        funcionario_selecionado = self.dados_funcionarios[texto_selecionado]

        # Cria uma nova janela (Toplevel) para a edição
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
        # Busca o valor atual no banco e preenche o campo
        verificador_atual = getattr(funcionario_selecionado, 'VerificadorCPF', '')
        edit_entry_verificador.insert(0, verificador_atual or "")

        # Encontra o nome do dia da folga a partir do número salvo no banco
        folga_atual_num = getattr(funcionario_selecionado, 'DiaDeFolga', 0)
        folga_atual_texto = next((nome for nome, num in self.dias_semana_mapa.items() if num == folga_atual_num), 'Sem Folga Definida')
        edit_combo_folga.set(folga_atual_texto)

        # Substitua a chamada do botão de salvar por esta:
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
        
        # Validação simples para garantir 3 dígitos
        if verificador_cpf and len(verificador_cpf) != 3:
            messagebox.showerror("Erro", "O Verificador de Segurança deve ter exatamente 3 dígitos.")
            return

        # 2. Passa o novo parâmetro para a função do banco
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
        # Passo 1: Descobrir qual funcionário está selecionado na lista.
        indices = self.lista_funcionarios.curselection()
        if not indices:
            messagebox.showwarning("Aviso", "Por favor, selecione um funcionário da lista para ver o histórico.")
            return

        # Passo 2: Pegar os dados completos do funcionário selecionado.
        texto_selecionado = self.lista_funcionarios.get(indices[0])
        funcionario = self.dados_funcionarios[texto_selecionado]
        funcionario_id = funcionario.FuncionarioID

        # Passo 3: Buscar o histórico no banco de dados usando a função que já temos.
        historico = database.obter_historico_funcionario(funcionario_id)

        # Passo 4: Criar a janela de pop-up (Toplevel).
        popup_historico = Toplevel(self.root)
        popup_historico.title(f"Histórico de - {funcionario.NomeCompleto}")
        popup_historico.geometry("800x500")
        popup_historico.transient(self.root) # Faz a janela ficar sobre a principal.

        # Passo 5: Criar um Frame e uma Treeview (tabela) para exibir os dados.
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

        # Adiciona uma barra de rolagem
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=tree_historico.yview)
        tree_historico.configure(yscrollcommand=scrollbar.set)
        
        tree_historico.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Passo 6: Preencher a tabela com os dados do histórico.
        if not historico:
            tree_historico.insert("", "end", values=("Nenhum histórico encontrado.", "", "", "", "", ""))
        else:
            for item in historico:
                # Formata as datas para ficarem mais legíveis
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
        # A linha abaixo DEVE ter um recuo
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

    # O laço 'for' agora está corretamente dentro da função
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
        if not indices: messagebox.showwarning("Aviso", "Selecione uma entrega para aprovar."); return
        texto = self.lista_entregas.get(indices[0]); entrega_id = int(texto.split(" | ")[0].split(": ")[1]); entrega_atual = self.dados_entregas[entrega_id]
        database.aprovar_entrega(entrega_atual.EntregaID, entrega_atual.FuncionarioID, entrega_atual.Pontos)
        texto_notificacao = (f"🎉 Parabéns, <b>{entrega_atual.NomeCompleto}</b>! 🎉\n\n" f"Sua entrega para a tarefa '<b>{entrega_atual.Titulo}</b>' foi APROVADA!\n\n" f"Você ganhou <b>{entrega_atual.Pontos}</b> pontos. Continue assim!")
        notificador_telegram.enviar_mensagem(entrega_atual.ChatIDTelegram, texto_notificacao)
        messagebox.showinfo("Sucesso", "Entrega aprovada e pontuação atribuída!"); self.atualizar_todas_as_listas()
    
    def recusar_entrega_selecionada(self):
        indices = self.lista_entregas.curselection()
        if not indices: messagebox.showwarning("Aviso", "Selecione uma entrega para recusar."); return
        texto = self.lista_entregas.get(indices[0]); entrega_id = int(texto.split(" | ")[0].split(": ")[1]); entrega_atual = self.dados_entregas[entrega_id]
        motivo = simpledialog.askstring("Motivo da Recusa", "Por favor, digite o motivo para recusar esta entrega:", parent=self.root)
        if motivo:
            database.recusar_entrega(entrega_atual.EntregaID, motivo)
            texto_notificacao = (f"⚠️ Atenção, <b>{entrega_atual.NomeCompleto}</b>! ⚠️\n\n" f"Sua entrega para a tarefa '<b>{entrega_atual.Titulo}</b>' foi RECUSADA.\n\n" f"<b>Motivo:</b> {motivo}\n\n" "Por favor, corrija e envie novamente.")
            notificador_telegram.enviar_mensagem(entrega_atual.ChatIDTelegram, texto_notificacao); messagebox.showinfo("Sucesso", "Entrega recusada e funcionário notificado."); self.atualizar_todas_as_listas()
        else: messagebox.showinfo("Cancelado", "Ação de recusa cancelada.")

    
    def limpar_detalhes_validacao(self):
        self.lbl_nome_funcionario.config(text="Funcionário: "); self.lbl_titulo_tarefa.config(text="Tarefa: "); self.lbl_imagem.config(image='')
        
    def atualizar_ranking(self):
        for i in self.tree_ranking.get_children(): self.tree_ranking.delete(i)
        
        ranking_data = database.calcular_ranking_desempenho()
        
        for i, row in enumerate(ranking_data):
            posicao = f"{i+1}º"
            nome = row['NomeCompleto']
            score_final = f"{row['ScoreHibrido']}" # <<< NOVO DADO
            desempenho = f"{row['Desempenho']}%"
            ganhos = row['PontosGanhos']
            possiveis = row['PontosPossiveis']
            
            self.tree_ranking.insert("", "end", values=(posicao, nome, score_final, desempenho, ganhos, possiveis))

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
        for func in funcionarios:
            horario_str = func.HorarioNotificacao if func.HorarioNotificacao else "N/D"
            texto = f"ID: {func.FuncionarioID} | {func.NomeCompleto} | Notificar às: {horario_str}"
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
        indices = self.lista_entregas.curselection()
        if not indices: return
        texto = self.lista_entregas.get(indices[0]); entrega_id = int(texto.split(" | ")[0].split(": ")[1]); entrega_atual = self.dados_entregas[entrega_id]
        self.lbl_nome_funcionario.config(text=f"Funcionário: {entrega_atual.NomeCompleto}")
        self.lbl_titulo_tarefa.config(text=f"Tarefa: {entrega_atual.Titulo} ({entrega_atual.Pontos} pts)")
        # Primeiro checamos se o caminho da foto não é Nulo (None)
        if entrega_atual.PathFotoEvidencia and os.path.exists(entrega_atual.PathFotoEvidencia):
            img = Image.open(entrega_atual.PathFotoEvidencia)
            img.thumbnail((500, 400))
            self.photo_img = ImageTk.PhotoImage(img)
            self.lbl_imagem.config(image=self.photo_img)
        else:
            # A mensagem agora reflete melhor a situação real
            self.lbl_imagem.config(image='', text="Foto ainda não processada pelo servidor ou não encontrada!")

    def carregar_funcionarios_feedback(self):
        """Carrega a lista de funcionários para o combobox de filtro."""
        funcionarios = database.listar_funcionarios()
        # Guardamos os dados em um dicionário para fácil acesso
        self.dados_funcionarios_feedback = {f.NomeCompleto: f.FuncionarioID for f in funcionarios}
        # A primeira opção será "Todos"
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
        # Limpa a lista antiga
        for i in self.tree_feedbacks.get_children():
            self.tree_feedbacks.delete(i)

        # --- Coleta de dados dos filtros ---
        nome_selecionado = self.combo_funcionarios_feedback.get()
        func_id = self.dados_funcionarios_feedback.get(nome_selecionado) if nome_selecionado != "Todos" else None

        data_inicio = self.entry_data_inicio_feedback.get()
        if data_inicio == "AAAA-MM-DD": data_inicio = None

        data_fim = self.entry_data_fim_feedback.get()
        if data_fim == "AAAA-MM-DD": data_fim = None

        # Busca os dados no banco
        feedbacks = database.buscar_feedbacks(func_id, data_inicio, data_fim)

        total_notas = 0

        # Popula a lista e calcula a soma das notas
        for fb in feedbacks:
            data_formatada = fb.DataFeedback.strftime("%d/%m/%Y")
            self.tree_feedbacks.insert("", "end", values=(fb.FeedbackID, fb.NomeCompleto, data_formatada, fb.NotaDia))
            total_notas += fb.NotaDia

        # Calcula e exibe a média
        if feedbacks:
            media = total_notas / len(feedbacks)
            self.lbl_media_feedback.config(text=f"Nota Média do Período: {media:.2f}")
        else:
            self.lbl_media_feedback.config(text="Nota Média do Período: --")

    def executar_relatorio_analise_tarefas(self):
        """Busca os dados e preenche a tabela de análise de tarefas."""
        # 1. Limpa a tabela de resultados antigos
        for i in self.tree_analise_tarefas.get_children():
            self.tree_analise_tarefas.delete(i)

        # 2. Pega as datas dos campos de entrada
        data_inicio = self.entry_data_inicio_analise.get()
        data_fim = self.entry_data_fim_analise.get()

        # 3. Valida o formato das datas ANTES de consultar o banco
        try:
            datetime.strptime(data_inicio, "%Y-%m-%d")
            datetime.strptime(data_fim, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Erro de Formato", "As datas devem estar no formato AAAA-MM-DD.")
            return # Para a execução se o formato estiver errado

        # 4. Agora sim, busca os dados no banco de dados
        resultados = database.relatorio_analise_tarefas(data_inicio, data_fim)
        
        # 5. Preenche a tabela com os resultados da busca
        if not resultados:
            self.tree_analise_tarefas.insert("", "end", values=("Nenhum dado problemático encontrado no período!", "", "", ""))
        else:
            for res in resultados:
                # Usando a versão corrigida com tuple()
                self.tree_analise_tarefas.insert("", "end", values=tuple(res))

        # Em main.py, adicione esta nova função à classe App
    def abrir_janela_justificativas(self):
        """Abre uma janela para mostrar os detalhes das justificativas 'Não Aplicável'."""
        # 1. Verifica se uma tarefa está selecionada na tabela
        selecionado = self.tree_analise_tarefas.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione uma tarefa na lista de resultados.")
            return

        # 2. Pega os dados da tarefa selecionada e dos filtros de data
        dados_tarefa = self.tree_analise_tarefas.item(selecionado, 'values')
        titulo_tarefa = dados_tarefa[0]
        data_inicio = self.entry_data_inicio_analise.get()
        data_fim = self.entry_data_fim_analise.get()

        # 3. Busca as justificativas no banco de dados
        justificativas = database.buscar_justificativas_nao_aplicavel(titulo_tarefa, data_inicio, data_fim)

        # 4. Cria a janela de pop-up
        popup = Toplevel(self.root)
        popup.title(f"Justificativas para '{titulo_tarefa}'")
        popup.geometry("600x400")
        popup.transient(self.root)

        if not justificativas:
            ttk.Label(popup, text="Nenhuma justificativa encontrada para esta tarefa no período.").pack(pady=20)
            return

        # 5. Cria a tabela (Treeview) para mostrar os detalhes
        frame_lista = ttk.Frame(popup, padding="10")
        frame_lista.pack(fill="both", expand=True)
        
        cols = ('Data', 'Funcionário', 'Justificativa')
        tree_justificativas = ttk.Treeview(frame_lista, columns=cols, show='headings')
        
        tree_justificativas.heading('Data', text='Data'); tree_justificativas.column('Data', width=120)
        tree_justificativas.heading('Funcionário', text='Funcionário'); tree_justificativas.column('Funcionário', width=150)
        tree_justificativas.heading('Justificativa', text='Justificativa'); tree_justificativas.column('Justificativa', width=300)
        
        tree_justificativas.pack(fill="both", expand=True)

        # 6. Preenche a tabela com os dados
        for just in justificativas:
            # Remove o prefixo "Não aplicável: " da justificativa para ficar mais limpo
            motivo_limpo = just.MotivoRecusa.replace("Não aplicável: ", "", 1)
            data_formatada = just.DataEnvio.strftime('%d/%m/%Y %H:%M')
            tree_justificativas.insert("", "end", values=(data_formatada, just.NomeCompleto, motivo_limpo))
    
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

    # Em main.py, adicione estas TRÊS novas funções à classe App

    def criar_aba_solicitacoes(self):
        """Cria a interface da aba de solicitações de feedback."""
        # Layout principal com dois painéis
        main_frame = ttk.Frame(self.frame_solicitacoes, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # Painel da Esquerda: Lista de Solicitações
        frame_lista = ttk.LabelFrame(main_frame, text="Solicitações Pendentes", padding="10")
        frame_lista.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        cols = ('ID', 'Funcionário', 'Data')
        self.tree_solicitacoes = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')
        self.tree_solicitacoes.heading('ID', text='ID')
        self.tree_solicitacoes.column('ID', width=40)
        self.tree_solicitacoes.heading('Funcionário', text='Funcionário')
        self.tree_solicitacoes.column('Funcionário', width=200)
        self.tree_solicitacoes.heading('Data', text='Data')
        self.tree_solicitacoes.column('Data', width=120)
        self.tree_solicitacoes.pack(fill=tk.BOTH, expand=True)
        self.tree_solicitacoes.bind('<<ListboxSelect>>', self.on_solicitacao_select)
        
        # Adicionamos um dicionário para guardar os dados completos
        self.dados_solicitacoes = {}

        # Painel da Direita: Detalhes e Resposta
        frame_detalhes = ttk.LabelFrame(main_frame, text="Responder Solicitação", padding="10")
        frame_detalhes.grid(row=0, column=1, sticky="nsew")
        frame_detalhes.rowconfigure(1, weight=1)
        frame_detalhes.columnconfigure(0, weight=1)
        
        ttk.Label(frame_detalhes, text="Assunto Solicitado:").grid(row=0, column=0, sticky="w")
        self.lbl_assunto_feedback = ttk.Label(frame_detalhes, text="...", wraplength=400, font=("Arial", 10, "italic"))
        self.lbl_assunto_feedback.grid(row=1, column=0, sticky="new", pady=5)
        
        ttk.Label(frame_detalhes, text="Escreva seu Feedback Abaixo:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.txt_resposta_feedback = tk.Text(frame_detalhes, height=10)
        self.txt_resposta_feedback.grid(row=3, column=0, sticky="nsew", pady=5)
        frame_detalhes.rowconfigure(3, weight=1)

        btn_enviar_resposta = ttk.Button(frame_detalhes, text="Enviar Resposta e Notificar Funcionário", command=self.enviar_resposta_feedback)
        btn_enviar_resposta.grid(row=4, column=0, sticky="e", pady=10)

        # Carrega os dados na lista
        self.atualizar_lista_solicitacoes()

    def atualizar_lista_solicitacoes(self):
        """Limpa e recarrega a lista de solicitações de feedback pendentes."""
        for i in self.tree_solicitacoes.get_children():
            self.tree_solicitacoes.delete(i)
        
        self.dados_solicitacoes.clear()
        solicitacoes = database.listar_solicitacoes_pendentes()
        for sol in solicitacoes:
            self.tree_solicitacoes.insert("", "end", values=(sol.SolicitacaoID, sol.NomeCompleto, sol.DataSolicitacao.strftime("%d/%m/%Y %H:%M")))
            # Guarda o objeto completo para uso posterior
            self.dados_solicitacoes[sol.SolicitacaoID] = sol

    def on_solicitacao_select(self, event):
        """Mostra o assunto da solicitação selecionada."""
        selecionado = self.tree_solicitacoes.focus()
        if not selecionado:
            return

        solicitacao_id = self.tree_solicitacoes.item(selecionado, 'values')[0]
        dados_completos = self.dados_solicitacoes.get(int(solicitacao_id))

        if dados_completos:
            self.lbl_assunto_feedback.config(text=dados_completos.TextoAssunto)
            self.txt_resposta_feedback.delete("1.0", tk.END) # Limpa a caixa de texto

    def enviar_resposta_feedback(self):
        """Salva a resposta do gestor no banco e notifica o funcionário."""
        selecionado = self.tree_solicitacoes.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Por favor, selecione uma solicitação na lista para responder.")
            return

        solicitacao_id = self.tree_solicitacoes.item(selecionado, 'values')[0]
        texto_resposta = self.txt_resposta_feedback.get("1.0", tk.END).strip()

        if not texto_resposta:
            messagebox.showwarning("Aviso", "O campo de feedback não pode estar vazio.")
            return

        # Salva no banco de dados
        sucesso_db = database.responder_solicitacao_feedback(solicitacao_id, texto_resposta)

        if sucesso_db:
            # Busca os dados do funcionário para notificar
            dados_notificacao = database.buscar_dados_para_notificacao_feedback(solicitacao_id)
            if dados_notificacao:
                mensagem_telegram = (
                f"Olá, <b>{dados_notificacao.NomeCompleto}</b>! 👋\n\n"
                "Você recebeu um novo feedback do seu gestor:\n\n"
                f"<i>\"{texto_resposta}\"</i>\n\n"
                "Continue com o bom trabalho!"
            )
                notificador_telegram.enviar_mensagem(dados_notificacao.ChatIDTelegram, mensagem_telegram)
            
            messagebox.showinfo("Sucesso", "Feedback enviado e funcionário notificado com sucesso!")
            
            # Limpa a tela e atualiza a lista
            self.lbl_assunto_feedback.config(text="...")
            self.txt_resposta_feedback.delete("1.0", tk.END)
            self.atualizar_lista_solicitacoes()
        else:
            messagebox.showerror("Erro", "Ocorreu um erro ao salvar o feedback no banco de dados.")


    def criar_aba_metas(self):
        """Cria a interface V3 para Gestão de Metas, com painel de detalhes."""
        main_frame = ttk.Frame(self.frame_metas)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(2, weight=1) # A nova linha de detalhes vai se expandir
        main_frame.columnconfigure(0, weight=1)

        # --- Frame 1: Lançamento Diário ---
        frame_lancamento = ttk.LabelFrame(main_frame, text="Lançar Apuração Diária", padding="10")
        frame_lancamento.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        # ... (o conteúdo deste frame continua igual) ...
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

        # --- Frame 2: Gerenciamento das Metas Principais ---
        frame_gerenciamento = ttk.LabelFrame(main_frame, text="Gerenciar Metas Principais (Clique para ver detalhes)", padding="10")
        frame_gerenciamento.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        # ... (o conteúdo deste frame continua igual, mas adicionamos o bind) ...
        frame_gerenciamento.rowconfigure(0, weight=1)
        frame_gerenciamento.columnconfigure(0, weight=1)
        cols_principais = ('ID', 'Nome', 'Valor Total', 'Início', 'Fim', 'Status')
        self.tree_metas_principais = ttk.Treeview(frame_gerenciamento, columns=cols_principais, show='headings', selectmode='browse')
        for col in cols_principais: self.tree_metas_principais.heading(col, text=col)
        self.tree_metas_principais.column('ID', width=40); self.tree_metas_principais.column('Nome', width=250)
        self.tree_metas_principais.column('Valor Total', width=120, anchor="e"); self.tree_metas_principais.column('Início', width=100, anchor="center")
        self.tree_metas_principais.column('Fim', width=100, anchor="center"); self.tree_metas_principais.column('Status', width=80, anchor="center")
        self.tree_metas_principais.pack(fill="x", expand=True, side="left")
        # A MÁGICA COMEÇA AQUI: Conectamos o clique na lista a uma nova função
        self.tree_metas_principais.bind('<<TreeviewSelect>>', self.on_meta_principal_selecionada)
        frame_botoes_gerenciamento = ttk.Frame(frame_gerenciamento)
        frame_botoes_gerenciamento.pack(side="left", fill="y", padx=10)
        ttk.Button(frame_botoes_gerenciamento, text="Criar Nova Meta Principal...", command=self.abrir_janela_criar_meta_principal).pack(pady=5)
        ttk.Button(frame_botoes_gerenciamento, text="Definir Metas Diárias...", command=self.abrir_janela_metas_diarias).pack(pady=5)

        # --- Frame 3: ACOMPANHAMENTO E DETALHES (NOVO!) ---
        frame_detalhes = ttk.LabelFrame(main_frame, text="Detalhes e Evolução da Meta Selecionada", padding="10")
        frame_detalhes.grid(row=2, column=0, sticky="nsew")
        frame_detalhes.rowconfigure(0, weight=1)
        frame_detalhes.columnconfigure(0, weight=2) # Coluna da lista de lançamentos cresce mais
        frame_detalhes.columnconfigure(1, weight=1) # Coluna do resumo

        # Sub-painel esquerdo: Lista de Lançamentos Diários
        cols_detalhes = ('Data do Lançamento', 'Valor Lançado (R$)')
        self.tree_detalhes_apuracoes = ttk.Treeview(frame_detalhes, columns=cols_detalhes, show='headings', selectmode='browse')
        self.tree_detalhes_apuracoes.heading('Data do Lançamento', text='Data do Lançamento')
        self.tree_detalhes_apuracoes.column('Data do Lançamento', anchor='center')
        self.tree_detalhes_apuracoes.heading('Valor Lançado (R$)', text='Valor Lançado (R$)')
        self.tree_detalhes_apuracoes.column('Valor Lançado (R$)', anchor='e')
        self.tree_detalhes_apuracoes.grid(row=0, column=0, sticky="nsew")
        self.tree_detalhes_apuracoes.bind("<Double-1>", self.abrir_janela_edicao_apuracao)

        # Sub-painel direito: Resumo do Progresso
        frame_resumo = ttk.Frame(frame_detalhes, padding="20")
        frame_resumo.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        
        self.lbl_total_atingido = ttk.Label(frame_resumo, text="Total Atingido: R$ 0,00", font=("Arial", 12, "bold"))
        self.lbl_total_atingido.pack(anchor="w", pady=5)
        
        self.lbl_progresso_percentual = ttk.Label(frame_resumo, text="Progresso: 0.00%", font=("Arial", 12))
        self.lbl_progresso_percentual.pack(anchor="w", pady=5)

        self.lbl_projecao_vendas = ttk.Label(frame_resumo, text="Projeção Final: R$ 0,00", font=("Arial", 12, "italic"))
        self.lbl_projecao_vendas.pack(anchor="w", pady=(15, 5))

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

    def on_meta_principal_selecionada(self, event):
        """
        (VERSÃO FINAL) Carrega o histórico, o resumo E CALCULA A PROJEÇÃO de vendas.
        """
        # Limpa os campos de detalhes antigos
        for i in self.tree_detalhes_apuracoes.get_children():
            self.tree_detalhes_apuracoes.delete(i)
        self.lbl_total_atingido.config(text="Total Atingido: R$ 0,00")
        self.lbl_progresso_percentual.config(text="Progresso: 0.00%")
        self.lbl_projecao_vendas.config(text="Projeção Final: R$ 0,00") # Reseta a projeção também

        selecionados = self.tree_metas_principais.selection()
        if not selecionados:
            return
        item_selecionado = selecionados[0]

        dados_meta = self.tree_metas_principais.item(item_selecionado, 'values')
        if not dados_meta: return
            
        meta_id = int(dados_meta[0])
        valor_meta_total_str = dados_meta[2].replace("R$ ", "").replace(".", "").replace(",", ".")
        valor_meta_total = float(valor_meta_total_str)
        
        # --- NOVAS LINHAS PARA PEGAR AS DATAS ---
        data_inicio_str = dados_meta[3]
        data_fim_str = dados_meta[4]

        apuracoes = database.listar_apuracoes_por_meta_principal(meta_id)

        total_atingido = 0.0
        for apuracao in apuracoes:
            data_f = apuracao.DataApuracao.strftime('%d/%m/%Y')
            valor_f = f"{apuracao.ValorDia:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            self.tree_detalhes_apuracoes.insert("", "end", values=(data_f, valor_f))
            total_atingido += float(apuracao.ValorDia)

        percentual = (total_atingido / valor_meta_total) * 100 if valor_meta_total > 0 else 0

        total_atingido_f = f"R$ {total_atingido:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        self.lbl_total_atingido.config(text=f"Total Atingido: {total_atingido_f}")
        self.lbl_progresso_percentual.config(text=f"Progresso: {percentual:.2f}%")

        # --- LÓGICA DE CÁLCULO DA PROJEÇÃO (NOVA!) ---
        dias_com_lancamento = len(apuracoes)
        if dias_com_lancamento > 0:
            # 1. Calcular a Média Diária
            media_diaria = total_atingido / dias_com_lancamento

            # 2. Calcular o Total de Dias da Meta
            data_inicio = datetime.strptime(data_inicio_str, '%d/%m/%Y')
            data_fim = datetime.strptime(data_fim_str, '%d/%m/%Y')
            total_dias_meta = (data_fim - data_inicio).days + 1

            # 3. Calcular a Projeção
            projecao = media_diaria * total_dias_meta
            
            # 4. Exibir na tela
            projecao_f = f"R$ {projecao:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            self.lbl_projecao_vendas.config(text=f"Projeção Final: {projecao_f}")
        # -------------------------------------------------


    def abrir_janela_edicao_apuracao(self, event):
        """Abre um pop-up para editar o valor de um lançamento diário selecionado."""
        # Pega o item que foi duplamente clicado
        selecionado = self.tree_detalhes_apuracoes.focus()
        if not selecionado:
            return

        # Extrai os dados da linha selecionada
        dados_apuracao = self.tree_detalhes_apuracoes.item(selecionado, 'values')
        data_lancamento_str = dados_apuracao[0]
        valor_antigo_str = dados_apuracao[1].replace(".", "").replace(",", ".")

        # Cria a janela de pop-up
        popup = Toplevel(self.root)
        popup.title(f"Editar Lançamento de {data_lancamento_str}")
        popup.geometry("350x200")
        popup.transient(self.root) # Mantém na frente da janela principal
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)

        # Mostra a data (não editável)
        ttk.Label(frame, text=f"Data da Apuração: {data_lancamento_str}", font=("Arial", 10, "bold")).pack(pady=5)

        # Campo para o novo valor, já preenchido com o valor antigo
        ttk.Label(frame, text="Novo Valor Lançado (R$):").pack(pady=5)
        entry_novo_valor = ttk.Entry(frame, justify="center")
        entry_novo_valor.pack(pady=5, ipady=4)
        entry_novo_valor.insert(0, valor_antigo_str)
        entry_novo_valor.focus() # Foca no campo de texto

        # Função interna para o botão Salvar
        def salvar_edicao():
            novo_valor_str = entry_novo_valor.get().replace(",", ".")
            try:
                novo_valor = float(novo_valor_str)
                # Converte a data de 'dd/mm/yyyy' para 'yyyy-mm-dd' que o banco espera
                data_db_format = datetime.strptime(data_lancamento_str, '%d/%m/%Y').strftime('%Y-%m-%d')
                
                # Pega o ID da meta principal que está selecionada na outra lista
                meta_selecionada_item = self.tree_metas_principais.selection()[0]
                meta_id = self.tree_metas_principais.item(meta_selecionada_item, 'values')[0]
                
                id_funcionario_logado = 2 # Lembre-se de ajustar se necessário
                
                # Reutilizamos a mesma função de lançamento!
                sucesso = database.lancar_apuracao_diaria(meta_id, data_db_format, novo_valor, id_funcionario_logado)
                
                if sucesso:
                    messagebox.showinfo("Sucesso", "Apuração atualizada com sucesso!", parent=popup)
                    popup.destroy()
                    # Força a atualização da tela principal para refletir a mudança
                    self.on_meta_principal_selecionada(None)
                else:
                    messagebox.showerror("Erro", "Não foi possível atualizar a apuração no banco.", parent=popup)

            except (ValueError, IndexError):
                messagebox.showerror("Erro de Formato", "O valor deve ser um número.", parent=popup)

        # Botão para salvar
        btn_salvar = ttk.Button(frame, text="Salvar Alterações", command=salvar_edicao)
        btn_salvar.pack(pady=15)
            # Permite salvar pressionando Enter
        entry_novo_valor.bind("<Return>", lambda e: salvar_edicao())


    def carregar_dados_metas(self):
        """Carrega as metas principais na lista e popula o combobox de metas ativas."""
        for i in self.tree_metas_principais.get_children():
            self.tree_metas_principais.delete(i)
        
        metas = database.listar_metas_principais()
        metas_ativas = []
        
        for meta in metas:
            data_inicio_f = meta.DataInicio.strftime('%d/%m/%Y')
            data_fim_f = meta.DataFim.strftime('%d/%m/%Y')
            valor_total_f = f"R$ {meta.ValorMetaTotal:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            self.tree_metas_principais.insert("", "end", values=(
                meta.MetaPrincipalID, meta.NomeMeta, valor_total_f, data_inicio_f, data_fim_f, meta.Status
            ))
            
            if meta.Status == 'Ativa':
                metas_ativas.append(f"{meta.NomeMeta} (ID: {meta.MetaPrincipalID})")
                
        self.combo_metas_ativas['values'] = metas_ativas
        if metas_ativas:
            self.combo_metas_ativas.current(0)


    def lancar_apuracao_diaria(self):
        """(VERSÃO V2) Lança a apuração, verifica a meta diária e premia se atingida."""
        meta_selecionada_str = self.combo_metas_ativas.get()
        data_apuracao_str = self.date_apuracao.get_date().strftime('%Y-%m-%d')
        valor_dia_str = self.entry_valor_dia.get().replace(',', '.')
        
        if not meta_selecionada_str or not valor_dia_str:
            messagebox.showwarning("Aviso", "Selecione uma meta e preencha o valor vendido no dia.")
            return
                
        try:
            meta_id = int(meta_selecionada_str.split('(ID: ')[1][:-1])
            valor_dia = float(valor_dia_str)
            id_funcionario_logado = 2
                
            sucesso, resultado = database.lancar_apuracao_diaria(meta_id, data_apuracao_str, valor_dia, id_funcionario_logado)
                
            if sucesso:
                apuracao_id = resultado # Agora temos o ID do lançamento
                messagebox.showinfo("Sucesso", "Apuração diária lançada com sucesso!")
                self.entry_valor_dia.delete(0, tk.END)
                self.on_meta_principal_selecionada(None)

                # --- NOVA LÓGICA DE VERIFICAÇÃO E PREMIAÇÃO ---
                modelo_meta_diaria = database.buscar_modelo_meta_para_data(data_apuracao_str)
                if modelo_meta_diaria and valor_dia >= modelo_meta_diaria.ValorMeta and modelo_meta_diaria.PontosPremio > 0:
                    # O setor da meta principal determina para quem vão os pontos
                    meta_principal = next((m for m in database.listar_metas_principais() if m.MetaPrincipalID == meta_id), None)
                    if meta_principal:
                        sucesso_pontos = database.registrar_pontos_meta_diaria(apuracao_id, modelo_meta_diaria.PontosPremio, meta_principal.SetorAlvo)
                        if sucesso_pontos:
                            messagebox.showinfo("Parabéns!", f"Meta diária atingida!\n\n{modelo_meta_diaria.PontosPremio} pontos foram distribuídos para a equipe do setor '{meta_principal.SetorAlvo}'.")
                # -----------------------------------------------

            else:
                messagebox.showerror("Erro", f"Não foi possível salvar a apuração no banco de dados.\nDetalhe: {resultado}")
        except (ValueError, IndexError):
            messagebox.showerror("Erro de Formato", "Verifique o valor vendido e a seleção da meta.")

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

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()

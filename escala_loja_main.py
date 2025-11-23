import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
from tkcalendar import DateEntry
from PIL import Image, ImageTk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import database
import config # Importar config para pegar o ID do grupo
import notificador_telegram # Importar notificador para enviar a escala
import calculadora_logica # Importa o novo módulo lógico
import os
import webbrowser
import urllib.parse
import re
from datetime import datetime, date
import threading

class AppEscalaLoja:
    def __init__(self, root):
        self.root = root
        self.root.title("Gestão de Escala Inteligente v2.0")
        self.root.geometry("1200x750")

        # Variáveis de Estado
        self.modo_edicao = False
        self.data_selecionada = None
        self.escala_atual = {} 
        self.posicoes = [] 
        self.tk_img = None

        # --- Layout Principal ---
        self.frame_topo = ttk.Frame(root, padding="10")
        self.frame_topo.pack(fill=tk.X)

        self.frame_mapa = ttk.Frame(root)
        self.frame_mapa.pack(fill=tk.BOTH, expand=True)

        # --- Painel Inferior (Dividido: Alertas | Gráfico) ---
        self.frame_inferior = ttk.LabelFrame(root, text="Painel de Controle Operacional", padding="5", height=200)
        self.frame_inferior.pack(fill=tk.BOTH, side=tk.BOTTOM, expand=False)

        # Coluna Esquerda: Alertas
        self.frame_alertas = ttk.Frame(self.frame_inferior)
        self.frame_alertas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(self.frame_alertas, text="⚠️ Alertas de Regras e Conflitos:", font=("Arial", 9, "bold")).pack(anchor="w")

        self.lbl_alertas = tk.Label(self.frame_alertas, text="Sistema pronto.", fg="gray", justify=tk.LEFT, font=("Consolas", 9), wraplength=600, anchor="nw")
        self.lbl_alertas.pack(fill=tk.BOTH, expand=True)

       # Coluna Direita: Gráfico de Fluxo
        self.frame_grafico = ttk.Frame(self.frame_inferior, width=600)
        self.frame_grafico.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # --- Controle do Gráfico (Seletor de Setor) ---
        self.frame_combo_grafico = ttk.Frame(self.frame_grafico)
        self.frame_combo_grafico.pack(fill=tk.X, side=tk.TOP)

        ttk.Label(self.frame_combo_grafico, text="Visualizar Fluxo do Setor:", font=("Arial", 8)).pack(side=tk.LEFT, padx=5)

        self.combo_setor_grafico = ttk.Combobox(self.frame_combo_grafico, state="readonly", height=10, width=20)
        self.combo_setor_grafico.pack(side=tk.LEFT)
        self.combo_setor_grafico['values'] = ["Geral (Todos)", "Varanda", "Frente Loja", "Salão", "Caixa", "Buffet", "Cozinha", "Limpeza", "Camara Fria"]
        self.combo_setor_grafico.set("Geral (Todos)")
        self.combo_setor_grafico.bind("<<ComboboxSelected>>", lambda e: self.atualizar_grafico_fluxo())

        # Inicializa o objeto do gráfico
        self.fig = Figure(figsize=(6, 1.8), dpi=100) # Ajuste de altura para caber o combo
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(bottom=0.2, top=0.85) # Margens para os textos não cortarem
        self.canvas_grafico = FigureCanvasTkAgg(self.fig, master=self.frame_grafico)
        self.canvas_grafico.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # --- Controles do Topo ---
        ttk.Label(self.frame_topo, text="Data:").pack(side=tk.LEFT)
        self.date_entry = DateEntry(self.frame_topo, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_entry.pack(side=tk.LEFT, padx=5)
        self.date_entry.bind("<<DateEntrySelected>>", self.carregar_escala_do_dia)

        ttk.Separator(self.frame_topo, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        self.btn_modo = ttk.Button(self.frame_topo, text="🔧 Configurar Mapa (Setores)", command=self.alternar_modo)
        self.btn_modo.pack(side=tk.LEFT, padx=5)

        self.lbl_legenda = ttk.Label(self.frame_topo, text="Modo: ESCALAÇÃO", foreground="green", font=("Arial", 10, "bold"))
        self.lbl_legenda.pack(side=tk.LEFT, padx=10)

        # Botão Mágico de Automação
        self.btn_magic = ttk.Button(self.frame_topo, text="🪄 Gerar Intervalos Automáticos", command=self.gerar_intervalos)
        self.btn_magic.pack(side=tk.LEFT, padx=20)

        # Botão Telegram
        self.btn_telegram = ttk.Button(self.frame_topo, text="📢 Enviar Escala Telegram", command=self.enviar_escala_telegram)
        self.btn_telegram.pack(side=tk.LEFT, padx=5)

        # --- Canvas do Mapa ---
        self.canvas = tk.Canvas(self.frame_mapa, bg="#e0e0e0", cursor="hand2")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.clique_no_mapa) 

        self.root.after(200, self.inicializar)

    def inicializar(self):
        self.carregar_imagem_mapa()
        self.carregar_escala_do_dia()

    def carregar_imagem_mapa(self):
        if self.tk_img is not None: return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        caminho_img = os.path.join(base_dir, "layout_loja.png")

        if not os.path.exists(caminho_img):
            self.canvas.create_text(500, 300, text=f"ERRO: Imagem '{caminho_img}' não encontrada!", fill="red")
            return

        pil_img = Image.open(caminho_img)
        # Redimensiona para caber na tela confortavelmente
        self.tk_img = ImageTk.PhotoImage(pil_img.resize((1180, 600), Image.Resampling.LANCZOS))
        self.canvas.create_image(590, 300, image=self.tk_img, anchor=tk.CENTER, tags="fundo")

    def carregar_escala_do_dia(self, event=None):
        self.data_selecionada = self.date_entry.get_date().strftime('%Y-%m-%d')
        self.posicoes = database.listar_posicoes_loja()
        self.escala_atual = database.buscar_escala_do_dia(self.data_selecionada)
        self.redesenhar_marcadores()
        # [CORREÇÃO] Garante que o gráfico seja redesenhado junto com o mapa
        self.atualizar_grafico_fluxo()

    def redesenhar_marcadores(self):
        self.canvas.delete("marcador")
        self.canvas.delete("texto_marcador")
        self.canvas.delete("setor_tag")

        dia_semana_hoje = datetime.strptime(self.data_selecionada, '%Y-%m-%d').isoweekday() + 1
        if dia_semana_hoje == 8: dia_semana_hoje = 1

        for pos in self.posicoes:
            # Desempacotamento seguro (trata casos onde 'setor' pode não vir do banco)
            pos_id = pos[0]
            nome = pos[1]
            x = pos[2]
            y = pos[3]
            # ativo = pos[4] (não usado aqui)
            setor = pos[5] if len(pos) > 5 else None

            nome_pessoa = "Vazio"
            cor = "#ff4444" # Vermelho (Vazio)
            info_intervalo = ""

            if pos_id in self.escala_atual:
                dados = self.escala_atual[pos_id]
                nome_pessoa = dados.NomePessoa if dados.NomePessoa else "(Livre)"
                cor = "#00C851" if dados.NomePessoa else "#FFBB33" # Verde ou Amarelo

                # Exibe o intervalo se estiver agendado
                if dados.InicioIntervalo and dados.FimIntervalo:
                    # Função segura para formatar independente se é objeto ou string
                    fmt_hora = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5]

                    i_ini = fmt_hora(dados.InicioIntervalo)
                    i_fim = fmt_hora(dados.FimIntervalo)
                    info_intervalo = f"\n☕ {i_ini}-{i_fim}"

            elif not self.modo_edicao:
                # Verifica ocupante fixo (padrão)
                func_padrao = database.buscar_funcionarios_com_posicao_padrao(pos_id)
                if func_padrao:
                    f_id, f_nome, f_folga = func_padrao
                    if str(f_folga) != str(dia_semana_hoje):
                        nome_pessoa = f"{f_nome} (Fixo)"
                        cor = "#33b5e5" # Azul

            tag = f"pos_{pos_id}"

            # Desenha Marcador (Bolinha)
            self.canvas.create_oval(x-15, y-15, x+15, y+15, fill=cor, outline="white", width=2, tags=("marcador", tag))

            # Desenha Texto (Nome + Intervalo)
            label = f"{nome}\n{nome_pessoa}{info_intervalo}"
            self.canvas.create_text(x, y+30, text=label, fill="black", font=("Arial", 8, "bold"), justify=tk.CENTER, tags=("texto_marcador", tag))

            # Desenha Tag do Setor (Visível no modo edição ou se existir)
            if self.modo_edicao or setor:
                cor_setor = "blue" if setor else "gray"
                txt_setor = f"[{setor}]" if setor else "[Sem Setor]"
                # Exibe acima da bolinha
                self.canvas.create_text(x, y-25, text=txt_setor, fill=cor_setor, font=("Arial", 7), tags=("setor_tag", tag))

        self.canvas.tag_lower("fundo")

    def atualizar_grafico_fluxo(self):
            """Calcula a ocupação hora a hora, filtrando por setor e descontando intervalos."""
            self.ax.clear()

            # 1. Captura o setor selecionado no filtro
            setor_filtro = self.combo_setor_grafico.get()
            if not setor_filtro: setor_filtro = "Geral (Todos)"

            # Busca dados brutos (Ent, Sai, IntIni, IntFim, Setor)
            horarios = database.buscar_horarios_ocupacao_hoje(self.data_selecionada, 0)

            horas_eixo = range(7, 24) # 07:00 as 23:00
            contagem_por_hora = []

            def para_time(val):
                if val is None: return None
                if hasattr(val, 'time'): return val.time()
                if isinstance(val, str):
                    try:
                        # Tenta converter string HH:MM ou HH:MM:SS para time
                        fmt = "%H:%M:%S" if len(val.split(':')) == 3 else "%H:%M"
                        return datetime.strptime(val, fmt).time()
                    except ValueError:
                        return None
                return val

            for h in horas_eixo:
                momento = datetime.strptime(f"{h}:00", "%H:%M").time()
                qtd_pessoas = 0

                for row in horarios:
                    ent = para_time(row[0])
                    sai = para_time(row[1])
                    int_ini = para_time(row[2])
                    int_fim = para_time(row[3])
                    setor_bd = row[4] # Nova coluna Setor

                    # --- FILTRO DE SETOR ---
                    if setor_filtro != "Geral (Todos)":
                        # Se o setor do funcionário for diferente do filtro, ignora
                        if setor_bd != setor_filtro:
                            continue

                    if not ent or not sai: continue

                    # 1. Verifica Turno
                    no_turno = False
                    if ent <= sai:
                        if ent <= momento < sai: no_turno = True
                    else:
                        if momento >= ent or momento < sai: no_turno = True

                    if no_turno:
                        # 2. Verifica Intervalo (Desconto)
                        no_intervalo = False
                        if int_ini and int_fim:
                            if int_ini <= int_fim:
                                if int_ini <= momento < int_fim: no_intervalo = True
                            else:
                                if momento >= int_ini or momento < int_fim: no_intervalo = True

                        if not no_intervalo:
                            qtd_pessoas += 1

                contagem_por_hora.append(qtd_pessoas)

            # Desenha o gráfico
            # Cores dinâmicas: Se selecionar um setor específico, usa azul. Se for Geral, usa a lógica verde/vermelho.
            if setor_filtro == "Geral (Todos)":
                cores = ['#d9534f' if c < 3 else '#5cb85c' for c in contagem_por_hora]
            else:
                cores = '#33b5e5' # Azul padrão para setores específicos

            barras = self.ax.bar(horas_eixo, contagem_por_hora, color=cores)

            # Título Dinâmico
            titulo = f"Fluxo: {setor_filtro} (Pessoas Ativas)"
            self.ax.set_title(titulo, fontsize=9, fontweight='bold')

            self.ax.set_xticks(horas_eixo)
            self.ax.set_xticklabels([f"{h}h" for h in horas_eixo], fontsize=7, rotation=0)
            self.ax.tick_params(axis='y', labelsize=7)
            self.ax.grid(axis='y', linestyle='--', alpha=0.3)

            # --- NOVO: Números em cima das colunas ---
            for i, rect in enumerate(barras):
                altura = rect.get_height()
                if altura > 0:
                    self.ax.text(rect.get_x() + rect.get_width()/2.0, altura, 
                                f'{int(altura)}', 
                                ha='center', va='bottom', fontsize=8, fontweight='bold')

            # Remove bordas desnecessárias para limpar o visual
            self.ax.spines['top'].set_visible(False)
            self.ax.spines['right'].set_visible(False)

            self.canvas_grafico.draw()

    def clique_no_mapa(self, event):
        x, y = event.x, event.y
        itens = self.canvas.find_overlapping(x-10, y-10, x+10, y+10)

        pos_id_clicado = None
        for item in itens:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("pos_"):
                    pos_id_clicado = int(tag.split("_")[1])
                    break

        if self.modo_edicao:
            if pos_id_clicado:
                self.abrir_configuracao_posicao(pos_id_clicado)
            else:
                self.criar_nova_posicao(x, y)
        else:
            if pos_id_clicado:
                self.abrir_janela_escalacao(pos_id_clicado)

    # --- Janela de Configuração da Posição (Setor) ---
    def abrir_configuracao_posicao(self, pos_id):
        dados_pos = next((p for p in self.posicoes if p[0] == pos_id), None)
        if not dados_pos: return

        popup = Toplevel(self.root)
        popup.title("Configurar Posição")
        popup.geometry("300x350")

        ttk.Label(popup, text="Nome da Posição:").pack(pady=5)
        entry_nome = ttk.Entry(popup)
        entry_nome.insert(0, dados_pos[1])
        entry_nome.pack(pady=5)

        ttk.Label(popup, text="Setor (Para Intervalo Automático):").pack(pady=5)
        # Adicionados: Limpeza e Camara Fria
        setores = ["Varanda", "Frente Loja", "Salão", "Caixa", "Buffet", "Cozinha", "Limpeza", "Camara Fria"]
        combo_setor = ttk.Combobox(popup, values=setores, state="readonly")
        combo_setor.pack(pady=5)

        # Carrega o setor atual, se houver
        if dados_pos[5]: 
            combo_setor.set(dados_pos[5])

        def salvar_cfg():
            novo_nome = entry_nome.get()
            novo_setor = combo_setor.get()
            if novo_nome:
                database.atualizar_dados_posicao(pos_id, novo_nome, novo_setor)
                self.carregar_escala_do_dia()
                popup.destroy()

        def excluir_cfg():
            if messagebox.askyesno("Excluir", "Tem certeza? Isso apaga o histórico desta posição."):
                database.excluir_posicao_loja(pos_id)
                self.carregar_escala_do_dia()
                popup.destroy()

    # --- Frame de Botões (Fixo no Rodapé) ---
        frame_btns = ttk.Frame(popup, padding="10")
        frame_btns.pack(side=tk.BOTTOM, fill=tk.X)

        # Correção: Aponta para a função local salvar_cfg
        btn_salvar = ttk.Button(frame_btns, text="💾 Salvar Alterações", command=salvar_cfg)
        btn_salvar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Correção: Adicionado botão de Excluir que estava faltando
        btn_excluir = ttk.Button(frame_btns, text="🗑️ Excluir Posição", command=excluir_cfg)
        btn_excluir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    def criar_nova_posicao(self, x, y):
        popup = Toplevel(self.root)
        popup.title("Nova Posição")

        ttk.Label(popup, text="Nome:").pack()
        entry_nome = ttk.Entry(popup)
        entry_nome.pack()

        ttk.Label(popup, text="Setor:").pack()
        # Lista atualizada
        combo_setor = ttk.Combobox(popup, values=["Varanda", "Frente Loja", "Salão", "Caixa", "Buffet", "Cozinha", "Limpeza", "Camara Fria"])
        combo_setor.pack()

        def confirmar():
            nome = entry_nome.get()
            setor = combo_setor.get()
            # Garante que setor vazio vire None para o banco
            if not setor: setor = None

            if nome:
                database.criar_posicao_loja(nome, x, y, setor)
                self.carregar_escala_do_dia()
                popup.destroy()

        ttk.Button(popup, text="Criar", command=confirmar).pack(pady=10)

    # --- INTEGRAÇÃO COM O CÉREBRO (CALCULADORA) ---
    def gerar_intervalos(self):
        # [CORREÇÃO] Função auxiliar robusta para converter qualquer formato em time object
        def extrair_tempo(val):
            from datetime import timedelta # Garante importação local
            if isinstance(val, timedelta):
                # Converte timedelta (ex: 8:00:00) para time
                segundos = val.total_seconds()
                horas = int(segundos // 3600)
                minutos = int((segundos % 3600) // 60)
                return (datetime.min + timedelta(hours=horas, minutes=minutos)).time()
            if val is None: return None
            if isinstance(val, str):
                try:
                    formato = "%H:%M:%S" if len(val.split(':')) == 3 else "%H:%M"
                    return datetime.strptime(val, formato).time()
                except ValueError:
                    print(f"ERRO DE FORMATO DE HORA: {val}") # Log para debug
                    return None
            if hasattr(val, 'time'): return val.time()
            return val
        # 1. Coleta dados da tela e do banco
        pessoas_para_calcular = []

        dia_obj = self.date_entry.get_date()
        dia_iso = dia_obj.isoweekday() # 1-7

        for pos in self.posicoes:
            pos_id, nome, x, y, ativo, setor = pos

            if pos_id in self.escala_atual:
                dados = self.escala_atual[pos_id]
                # Só calcula para quem tem horário de entrada e saída E nome definido
                if dados.HorarioEntrada and dados.HorarioSaida and dados.NomePessoa:
                    # Combina a data selecionada com a hora do banco de forma segura
                    t_ent = extrair_tempo(dados.HorarioEntrada)
                    t_sai = extrair_tempo(dados.HorarioSaida)

                    dt_entrada = datetime.combine(dia_obj, t_ent)
                    dt_saida = datetime.combine(dia_obj, t_sai)

                    pessoas_para_calcular.append({
                        'id_posicao': pos_id,
                        'nome': dados.NomePessoa,
                        'setor': setor,
                        'entrada': dt_entrada,
                        'saida': dt_saida
                    })

        if not pessoas_para_calcular:
            messagebox.showwarning("Vazio", "Não há funcionários escalados com horário de entrada/saída para calcular.")
            return

        # 2. Chama o Cérebro Lógico
        try:
            sugestoes, erros = calculadora_logica.calcular_intervalos_automaticos(pessoas_para_calcular, dia_iso)
        except Exception as e:
            messagebox.showerror("Erro de Cálculo", f"Falha na calculadora lógica: {e}")
            return

        # 3. Exibe Erros no Rodapé
        texto_erros = "\n".join(erros) if erros else "Cálculo concluído sem conflitos."
        color = "red" if erros else "green"
        self.lbl_alertas.config(text=texto_erros, fg=color)

        # 4. Aplica Sugestões no Banco
        count_aplicados = 0
        for pos_id, (ini, fim) in sugestoes.items():
            dados_antigos = self.escala_atual[pos_id]

            # Preserva os dados antigos, atualizando apenas o intervalo
            database.salvar_escala_dia(
                self.data_selecionada, pos_id, 
                dados_antigos.FuncionarioID, dados_antigos.FreelancerID,
                dados_antigos.HorarioEntrada, dados_antigos.HorarioSaida,
                ini.strftime('%H:%M'), fim.strftime('%H:%M'), # Novos Intervalos
                dados_antigos.FocoDoDia
            )
            count_aplicados += 1

        self.carregar_escala_do_dia()

        if erros:
            messagebox.showwarning("Atenção", f"{count_aplicados} intervalos agendados, mas houve conflitos!\nVerifique os alertas no rodapé.")
        else:
            messagebox.showinfo("Sucesso", f"{count_aplicados} intervalos agendados com sucesso!")


    # Melhoria 4: Função para enviar escala no Telegram (Assíncrona)
    def enviar_escala_telegram(self):
        if not self.data_selecionada: return

        resposta = messagebox.askyesno("Confirmar Envio", 
            f"Deseja enviar a escala do dia {self.data_selecionada} para o grupo TODOS OS FUNCIONÁRIOS no Telegram?")

        if resposta:
            # Função interna para rodar em thread separada
            def tarefa_background():
                try:
                    texto_escala = database.gerar_relatorio_escala_texto(self.data_selecionada)
                    notificador_telegram.enviar_mensagem(config.TODOS_FUNCIONARIOS_GROUP_ID, texto_escala)
                    self.root.after(0, lambda: messagebox.showinfo("Sucesso", "Escala enviada para o grupo do Telegram!"))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Erro", f"Falha ao enviar Telegram: {e}"))

            # Inicia a thread para não travar a interface
            threading.Thread(target=tarefa_background, daemon=True).start()

    # --- Funções Auxiliares Originais (Mantidas) ---
    def alternar_modo(self):
        self.modo_edicao = not self.modo_edicao
        if self.modo_edicao:
            self.btn_modo.config(text="✅ Salvar e Voltar")
            self.lbl_legenda.config(text="Modo: CONFIGURAÇÃO (Clique para editar setor)", foreground="red")
        else:
            self.btn_modo.config(text="🔧 Configurar Mapa")
            self.lbl_legenda.config(text="Modo: ESCALAÇÃO", foreground="green")
            self.carregar_escala_do_dia()

    def cadastrar_freelancer(self):
        nome = simpledialog.askstring("Novo Freelancer", "Nome Completo:")
        if nome:
            tel = simpledialog.askstring("Contato", "Telefone (WhatsApp) com DDD:")
            if tel:
                digitos = re.sub(r'\D', '', tel)
                if len(digitos) < 8:
                    messagebox.showerror("Erro", "Telefone inválido.")
                    return
                database.criar_freelancer(nome, tel)
                messagebox.showinfo("Sucesso", "Freelancer cadastrado!")

    def abrir_janela_escalacao(self, pos_id):
        try:
            dados_pos = next((p for p in self.posicoes if p[0] == pos_id), None)
            if not dados_pos: return
            nome_pos = dados_pos[1]
        except StopIteration: return 

        popup = Toplevel(self.root)
        popup.title(f"Escalar: {nome_pos}")
        # Ajuste para um tamanho mais vertical e centralizado
        popup.geometry("500x450")
        # Centraliza a janela na tela
        popup.update_idletasks()
        x_c = self.root.winfo_x() + (self.root.winfo_width() // 2) - (500 // 2)
        y_c = self.root.winfo_y() + (self.root.winfo_height() // 2) - (450 // 2)
        popup.geometry(f"+{x_c}+{y_c}")

        dados_atuais = self.escala_atual.get(pos_id)

        ttk.Label(popup, text="Quem vai trabalhar aqui?").pack(pady=5)
        combo_pessoas = ttk.Combobox(popup, width=40)
        combo_pessoas.pack()

        mapa_ids = {} 
        lista_nomes = ["(Vazio)"]
        for f in database.listar_funcionarios():
            label = f"[Fixo] {f.NomeCompleto}"; lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'func', 'id': f.FuncionarioID, 'tel': f.ChatIDTelegram}
        for fr in database.listar_freelancers():
            label = f"[Free] {fr.Nome}"; lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'free', 'id': fr.FreelancerID, 'tel': fr.Telefone}
        combo_pessoas['values'] = lista_nomes

        pessoa_tel = None
        if dados_atuais:
            if dados_atuais.FuncionarioID:
                match = next((k for k, v in mapa_ids.items() if v['tipo'] == 'func' and v['id'] == dados_atuais.FuncionarioID), "")
                combo_pessoas.set(match)
            elif dados_atuais.FreelancerID:
                match = next((k for k, v in mapa_ids.items() if v['tipo'] == 'free' and v['id'] == dados_atuais.FreelancerID), "")
                combo_pessoas.set(match)
                pessoa_tel = dados_atuais.TelefonePessoa

        frame_hor = ttk.LabelFrame(popup, text="Horários", padding=10)
        frame_hor.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(frame_hor, text="Entrada:").grid(row=0, column=0); e_ent = ttk.Entry(frame_hor, width=8); e_ent.grid(row=0, column=1)
        ttk.Label(frame_hor, text="Saída:").grid(row=0, column=2); e_sai = ttk.Entry(frame_hor, width=8); e_sai.grid(row=0, column=3)
        ttk.Label(frame_hor, text="Intervalo Início:").grid(row=1, column=0); e_int_ini = ttk.Entry(frame_hor, width=8); e_int_ini.grid(row=1, column=1)
        ttk.Label(frame_hor, text="Intervalo Fim:").grid(row=1, column=2); e_int_fim = ttk.Entry(frame_hor, width=8); e_int_fim.grid(row=1, column=3)

        if dados_atuais:
            # Helper seguro para formatar (objeto time ou string)
            def safe_fmt(val):
                if not val: return ""
                if hasattr(val, 'strftime'): return val.strftime('%H:%M')
                return str(val)[:5] # Se for string, pega os 5 primeiros chars (HH:MM)

            if getattr(dados_atuais, 'HorarioEntrada', None): e_ent.insert(0, safe_fmt(dados_atuais.HorarioEntrada))
            if getattr(dados_atuais, 'HorarioSaida', None): e_sai.insert(0, safe_fmt(dados_atuais.HorarioSaida))
            if getattr(dados_atuais, 'InicioIntervalo', None): e_int_ini.insert(0, safe_fmt(dados_atuais.InicioIntervalo))
            if getattr(dados_atuais, 'FimIntervalo', None): e_int_fim.insert(0, safe_fmt(dados_atuais.FimIntervalo))
        else:
            e_ent.insert(0, "08:00"); e_sai.insert(0, "18:00")

        ttk.Label(popup, text="Foco do Dia:").pack(anchor=tk.W, padx=10)
        txt_foco = tk.Text(popup, height=5, width=40); txt_foco.pack(padx=10, pady=5)

        # Melhoria 2: Pré-preenchimento por Setor (Com proteção de índice)
        # Verifica se a tupla tem tamanho suficiente (6 itens) antes de acessar o índice 5
        setor_atual = next((p[5] for p in self.posicoes if p[0] == pos_id and len(p) > 5), None)

        msg_foco_padrao = ""
        if setor_atual:
            msgs_padrao = {
                "Cozinha": "Foco: Agilidade nos pedidos e organização da praça.",
                "Caixa": "Foco: Simpatia, oferta de adicionais e conferência.",
                "Salão": "Foco: Limpeza das mesas e atenção aos clientes.",
                "Frente Loja": "Foco: Abordagem convidativa e reposição.",
                "Buffet": "Foco: Reposição constante e limpeza das bordas.",
                "Limpeza": "Foco: Banheiros e chão sempre limpos.",
                "Camara Fria": "Foco: Organização PVPS e contagem."
            }
            msg_foco_padrao = msgs_padrao.get(setor_atual, "")

        if dados_atuais and dados_atuais.FocoDoDia: 
            txt_foco.insert("1.0", dados_atuais.FocoDoDia)
        elif msg_foco_padrao:
            txt_foco.insert("1.0", msg_foco_padrao)

        def salvar():
            # Validação de Formato de Hora
            def validar_hora(texto):
                if not texto or texto.strip() == "": return True
                try:
                    datetime.strptime(texto, '%H:%M')
                    return True
                except ValueError:
                    return False

            horarios = [e_ent.get(), e_sai.get(), e_int_ini.get(), e_int_fim.get()]
            for h in horarios:
                if not validar_hora(h):
                    messagebox.showerror("Erro de Formato", f"Horário inválido: '{h}'.\nUse o formato HH:MM (ex: 08:00).")
                    return

            def tratar_vazio(valor): return valor if valor and valor.strip() else None
            selecao = combo_pessoas.get()
            if not selecao: return 

            # Inicialização segura de ambas as variáveis
            func_id = None
            free_id = None

            if selecao != "(Vazio)":
                d = mapa_ids[selecao]
                func_id = d['id'] if d['tipo'] == 'func' else None
                free_id = d['id'] if d['tipo'] == 'free' else None

        # Salva a escala do dia
            database.salvar_escala_dia(self.data_selecionada, pos_id, func_id, free_id,
                tratar_vazio(e_ent.get()), tratar_vazio(e_sai.get()), 
                tratar_vazio(e_int_ini.get()), tratar_vazio(e_int_fim.get()),
                txt_foco.get("1.0", tk.END).strip())

            # Melhoria 1: Perguntar se é fixo (Apenas para Funcionários)
            if func_id:
                # Verifica se já é o fixo atual para não perguntar à toa
                fixo_atual = database.buscar_funcionarios_com_posicao_padrao(pos_id)
                id_fixo_atual = fixo_atual[0] if fixo_atual else None

                if func_id != id_fixo_atual:
                    if messagebox.askyesno("Posição Fixa", "Deseja definir este funcionário como FIXO nesta posição para todos os dias futuros?"):
                        database.definir_posicao_padrao_funcionario(func_id, pos_id)
                        messagebox.showinfo("Atualizado", "Funcionário definido como fixo nesta posição.")

            popup.destroy()
            self.carregar_escala_do_dia()

        def enviar_zap():
            selecao = combo_pessoas.get()
            if not selecao or selecao == "(Vazio)": return
            d = mapa_ids.get(selecao)
            tel = d.get('tel') if d else None
            if not tel and pessoa_tel: tel = pessoa_tel

            if tel:
                # Limpeza do telefone e formatação da data
                try:
                    if not self.data_selecionada: raise ValueError("Data não selecionada")
                    data_obj = datetime.strptime(self.data_selecionada, '%Y-%m-%d')
                    data_fmt = data_obj.strftime('%d/%m/%y')
                except ValueError:
                    data_fmt = self.data_selecionada or "Data Indefinida"

                # Construção da mensagem BÁSICA
                texto_msg = f"Escala {data_fmt}: {nome_pos}\nHorário: {e_ent.get()} às {e_sai.get()}"
                
                # Adiciona Intervalo se houver
                if e_int_ini.get() and e_int_fim.get():
                    texto_msg += f"\nIntervalo: {e_int_ini.get()} às {e_int_fim.get()}"

                # [CORREÇÃO] Adiciona o Foco do Dia se houver texto
                foco_texto = txt_foco.get("1.0", "end-1c").strip()
                if foco_texto:
                    texto_msg += f"\n\n🎯 Foco do Dia:\n{foco_texto}"

                # Codificação e abertura do navegador
                tel_limpo = re.sub(r'\D', '', tel)
                texto_encoded = urllib.parse.quote(texto_msg)
                url = f"https://wa.me/{tel_limpo}?text={texto_encoded}"
                webbrowser.open(url)
            else:
                messagebox.showwarning("Aviso", "Nenhum telefone encontrado para a pessoa selecionada.")

        # --- Recriação dos Botões de Ação (Faltavam no código) ---
        frame_botoes = ttk.Frame(popup, padding="10")
        frame_botoes.pack(fill=tk.X, side=tk.BOTTOM)

        btn_salvar = ttk.Button(frame_botoes, text="✅ Salvar Escala", command=salvar)
        btn_salvar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        btn_zap = ttk.Button(frame_botoes, text="📱 Enviar WhatsApp", command=enviar_zap)
        btn_zap.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
                

if __name__ == "__main__":
    root = tk.Tk()
    app = AppEscalaLoja(root)
    root.mainloop()

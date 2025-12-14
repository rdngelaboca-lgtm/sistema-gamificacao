import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
from tkcalendar import DateEntry
from PIL import Image, ImageTk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import database
import re
import config # Importar config para pegar o ID do grupo
import notificador_telegram # Importar notificador para enviar a escala
import notificador_whatsapp # Importar notificador para envio via API/Link
import calculadora_logica # Importa o novo módulo lógico
import os
import webbrowser
import urllib.parse
from datetime import datetime, date, timedelta
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
        # Carrega setores do banco dinamicamente + opção Geral
        setores_db = database.listar_setores_unicos()
        self.combo_setor_grafico['values'] = ["Geral (Todos)"] + setores_db
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

        # [ATUALIZAÇÃO] Botão de Gestão de Freelancers
        self.btn_free = ttk.Button(self.frame_topo, text="👤 Gerenciar Freelancers", command=self.abrir_gestao_freelancers)
        self.btn_free.pack(side=tk.LEFT, padx=5)

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
        self.btn_config = ttk.Button(self.frame_topo, text="⚙️ Configurações Automação", command=self.abrir_janela_configuracoes)
        self.btn_config.pack(side=tk.LEFT, padx=5)

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

        try:
            pil_img = Image.open(caminho_img)
            # Redimensiona para caber na tela confortavelmente
            self.tk_img = ImageTk.PhotoImage(pil_img.resize((1180, 600), Image.Resampling.LANCZOS))
            self.canvas.create_image(590, 300, image=self.tk_img, anchor=tk.CENTER, tags="fundo")
        except Exception as e:
            print(f"Erro ao carregar imagem do mapa: {e}")
            self.canvas.create_text(590, 300, text=f"Erro ao carregar 'layout_loja.png':\n{e}\nO sistema continua funcional sem o mapa de fundo.", fill="red", font=("Arial", 12, "bold"))

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

    @staticmethod
    def _parse_horario_seguro(valor):
        """Converte string, datetime ou time para time object de forma segura."""
        if valor is None: return None
        if hasattr(valor, 'time'): return valor.time() # Já é datetime
        if isinstance(valor, str):
            try:
                # Tenta HH:MM:SS ou HH:MM
                fmt = "%H:%M:%S" if len(valor.split(':')) == 3 else "%H:%M"
                return datetime.strptime(valor, fmt).time()
            except ValueError:
                return None
        return valor # Já é time ou desconhecido

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

            # (A função para_time foi removida daqui pois agora usamos self._parse_horario_seguro)

            for h in horas_eixo:
                momento = datetime.strptime(f"{h}:00", "%H:%M").time()
                qtd_pessoas = 0

                for row in horarios:
                    # Usa a nova ferramenta universal criada na Etapa 1
                    ent = self._parse_horario_seguro(row[0])
                    sai = self._parse_horario_seguro(row[1])
                    int_ini = self._parse_horario_seguro(row[2])
                    int_fim = self._parse_horario_seguro(row[3])
                    setor_bd = row[4]

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
        # (A função extrair_tempo foi removida pois agora usamos self._parse_horario_seguro)
        
        # 1. Coleta dados da tela e do banco
        pessoas_para_calcular = []

        dia_obj = self.date_entry.get_date()

        # CORREÇÃO: Converter isoweekday (Seg=1...Dom=7) para o padrão do Banco (Dom=1...Sab=7)
        dia_iso = (dia_obj.isoweekday() % 7) + 1

        for pos in self.posicoes:
            pos_id, nome, x, y, ativo, setor = pos

            if pos_id in self.escala_atual:
                dados = self.escala_atual[pos_id]
                # Só calcula para quem tem horário de entrada e saída E nome definido
                if dados.HorarioEntrada and dados.HorarioSaida and dados.NomePessoa:
                    # Combina a data selecionada com a hora do banco de forma segura
                    # USA A NOVA FERRAMENTA AQUI:
                    t_ent = self._parse_horario_seguro(dados.HorarioEntrada)
                    t_sai = self._parse_horario_seguro(dados.HorarioSaida)

                    # CORREÇÃO: Validação de segurança para evitar crash se horário for inválido
                    if t_ent is None or t_sai is None:
                        print(f"Aviso: Ignorando posição {pos_id} ({dados.NomePessoa}) por horário incompleto.")
                        continue

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
            # O objeto datetime.datetime é passado e o driver pyodbc extrai corretamente o time.
            database.salvar_escala_dia(
                self.data_selecionada, pos_id, 
                dados_antigos.FuncionarioID, dados_antigos.FreelancerID,
                dados_antigos.HorarioEntrada, dados_antigos.HorarioSaida,
                ini, fim, # Novos Intervalos (Passando objetos datetime.datetime)
                dados_antigos.FocoDoDia
            )
            count_aplicados += 1

        self.carregar_escala_do_dia()

        if erros:
            messagebox.showwarning("Atenção", f"{count_aplicados} intervalos agendados, mas houve conflitos!\nVerifique os alertas no rodapé.")
        else:
            messagebox.showinfo("Sucesso", f"{count_aplicados} intervalos agendados com sucesso!")


    def enviar_escala_telegram(self):
        if not self.data_selecionada: return

        resposta = messagebox.askyesno("Confirmar Envio", 
            f"Deseja enviar a escala do dia {self.data_selecionada} para o grupo TODOS OS FUNCIONÁRIOS no Telegram?")

        if resposta:
            # Desabilita o botão para evitar cliques múltiplos
            self.btn_telegram.config(state='disabled', text="Enviando...")

            def tarefa_background():
                try:
                    texto_escala = database.gerar_relatorio_escala_texto(self.data_selecionada)
                    notificador_telegram.enviar_mensagem(config.TODOS_FUNCIONARIOS_GROUP_ID, texto_escala)

                    # Sucesso: Reabilita botão e avisa
                    self.root.after(0, lambda: self._finalizar_envio_telegram(True))
                except Exception as e:
                    # Erro: Reabilita botão e avisa erro
                    self.root.after(0, lambda: self._finalizar_envio_telegram(False, str(e)))

            threading.Thread(target=tarefa_background, daemon=True).start()

    def _finalizar_envio_telegram(self, sucesso, erro_msg=None):
        self.btn_telegram.config(state='normal', text="📢 Enviar Escala Telegram")
        if sucesso:
            messagebox.showinfo("Sucesso", "Escala enviada para o grupo do Telegram!")
        else:
            messagebox.showerror("Erro", f"Falha ao enviar Telegram: {erro_msg}")

    def abrir_janela_configuracoes(self):
        """Abre a janela Toplevel para editar os parâmetros da automação de escala."""
        popup = Toplevel(self.root)
        popup.title("Configurações de Automação de Escala")
        popup.geometry("450x380") # Aumentado altura
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        # 1. Carregar valores atuais
        config_atual = database.buscar_configuracoes_escala()
        if not config_atual:
            messagebox.showerror("Erro", "Não foi possível carregar as configurações globais do banco. Usando padrões.", parent=popup)
            max_h_val, dur_int_val, jornada_val = 5, 1, 8
        else:
            # Configs Globais (MaxHoras, Duração Intervalo, Jornada Padrão)
            max_h_val = config_atual.MaxHorasSemPausa
            dur_int_val = config_atual.DuracaoIntervalo
            # Req 1: Carrega jornada padrão (default 8 se nulo)
            jornada_val = getattr(config_atual, 'DuracaoJornadaPadrao', 8) or 8

        # 2. Campos de Input (Regras CLT)
        ttk.Label(frame, text="Max. Horas sem Pausa (CLT):").grid(row=0, column=0, sticky=tk.W, pady=5)
        entry_max_horas = ttk.Entry(frame, width=10)
        entry_max_horas.insert(0, str(max_h_val))
        entry_max_horas.grid(row=0, column=1, sticky=tk.E, pady=5)

        ttk.Label(frame, text="Duração do Intervalo (Horas):").grid(row=1, column=0, sticky=tk.W, pady=5)
        entry_duracao = ttk.Entry(frame, width=10)
        entry_duracao.insert(0, str(dur_int_val))
        entry_duracao.grid(row=1, column=1, sticky=tk.E, pady=5)

        # Req 1: Novo campo Jornada
        ttk.Label(frame, text="Jornada de Trabalho Padrão (Horas):").grid(row=2, column=0, sticky=tk.W, pady=5)
        entry_jornada = ttk.Entry(frame, width=10)
        entry_jornada.insert(0, str(jornada_val))
        entry_jornada.grid(row=2, column=1, sticky=tk.E, pady=5)
        ttk.Label(frame, text="(Usado para calcular saída automática)", font=("Arial", 8, "italic"), foreground="gray").grid(row=3, column=0, columnspan=2, sticky=tk.W)

        # Separador para Pico Diário
        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=10)
        ttk.Label(frame, text="Gerenciar Horário de Pico por Dia:").grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))

        # 3. Botão para Abrir Configurações de Pico
        btn_abrir_pico = ttk.Button(frame, text="Abrir Gerenciador de Pico Diário", command=lambda: self.abrir_janela_pico_diario(popup))
        btn_abrir_pico.grid(row=6, column=0, columnspan=2, pady=10, sticky=tk.EW)

        def salvar_config():
            max_horas_str = entry_max_horas.get().strip()
            duracao_str = entry_duracao.get().strip()
            jornada_str = entry_jornada.get().strip()

            try:
                # 1. Converte Max Horas e Duração Intervalo (Inteiros simples)
                max_horas = int(max_horas_str)
                duracao = int(duracao_str)

                # 2. Lógica Inteligente para Jornada (Aceita "8:20" ou "8.33")
                if ":" in jornada_str:
                    horas, minutos = map(int, jornada_str.split(':'))
                    # Converte minutos em fração de hora (ex: 20 min / 60 = 0.33)
                    jornada = horas + (minutos / 60.0)
                else:
                    # Aceita número inteiro ou com ponto (8 ou 8.5)
                    jornada = float(jornada_str.replace(',', '.'))

                if max_horas <= 0 or duracao <= 0 or jornada <= 0:
                    raise ValueError("Valores numéricos devem ser positivos.")

                # Atualiza configurações globais
                # Nota: O banco precisa aceitar FLOAT/DECIMAL na coluna DuracaoJornadaPadrao
                if database.atualizar_configuracoes_escala(None, None, max_horas, duracao, jornada):
                    messagebox.showinfo("Sucesso", "Configurações globais salvas! Atualize a escala.", parent=popup)
                    popup.destroy()
                else:
                    messagebox.showerror("Erro", "Falha ao salvar no banco de dados.", parent=popup)

            except ValueError as e:
                messagebox.showerror("Erro de Formato", f"Verifique o formato.\nPara 8h e 20min, digite '8:20' ou '8.33'.\nDetalhe: {e}", parent=popup)
            except Exception as e:
                messagebox.showerror("Erro", f"Ocorreu um erro inesperado: {e}", parent=popup)

        # 5. Botão Salvar
        btn_salvar = ttk.Button(frame, text="💾 Salvar Configurações", command=salvar_config)
        btn_salvar.grid(row=7, column=0, columnspan=2, pady=20, sticky=tk.EW)

    def abrir_janela_pico_diario(self, parent_popup):
        """Abre a janela Toplevel para editar o horário de pico por dia da semana."""
        popup = Toplevel(self.root)
        popup.title("Gerenciar Horários de Pico Diário")
        popup.geometry("400x350")
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill="both", expand=True)
        
        # Mapa para armazenar os campos de entrada (DiaID: (Entry_Ini, Entry_Fim))
        campos_pico = {}
        
        # 1. Carregar valores atuais
        picos_atuais = database.listar_configuracoes_pico_diario()
        
        # 2. Criação da Tabela/Grid de Edição
        
        ttk.Label(frame, text="Dia").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Label(frame, text="Início (HH:MM)").grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(frame, text="Fim (HH:MM)").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        
        for i, pico in enumerate(picos_atuais):
            row_num = i + 1
            dia_id, nome_dia, h_ini, h_fim = pico
            
            ttk.Label(frame, text=f"{nome_dia}:").grid(row=row_num, column=0, sticky=tk.W, padx=5, pady=2)
            
            # Campo de Início
            entry_ini = ttk.Entry(frame, width=8, justify="center")
            # Fatiamento seguro, se for None, insere vazio
            entry_ini.insert(0, str(h_ini)[:5] if h_ini else "")
            entry_ini.grid(row=row_num, column=1, sticky=tk.W, padx=5, pady=2)
            
            # Campo de Fim
            entry_fim = ttk.Entry(frame, width=8, justify="center")
            entry_fim.insert(0, str(h_fim)[:5] if h_fim else "")
            entry_fim.grid(row=row_num, column=2, sticky=tk.W, padx=5, pady=2)
            
            campos_pico[dia_id] = (entry_ini, entry_fim)

        # 3. Função de Salvamento
        def salvar_picos():
            erros = []
            sucessos = 0
            
            for dia_id, (entry_ini, entry_fim) in campos_pico.items():
                h_ini_str = entry_ini.get().strip()
                h_fim_str = entry_fim.get().strip()
                
                # Trata string vazia como NULL para o banco
                h_ini = h_ini_str if h_ini_str else None
                h_fim = h_fim_str if h_fim_str else None

                # Validação de formato HH:MM (só se o campo não estiver vazio)
                if h_ini and not re.match(r'^\d{2}:\d{2}$', h_ini):
                    erros.append(f"Dia {dia_id} (Início): Formato inválido.")
                    continue
                if h_fim and not re.match(r'^\d{2}:\d{2}$', h_fim):
                    erros.append(f"Dia {dia_id} (Fim): Formato inválido.")
                    continue

                if database.atualizar_pico_diario(dia_id, h_ini, h_fim):
                    sucessos += 1
                else:
                    erros.append(f"Dia {dia_id}: Falha de escrita no banco.")
            
            if erros:
                messagebox.showerror("Erros de Salva.", "\n".join(erros) + f"\n\n{sucessos} dia(s) salvo(s) com sucesso.", parent=popup)
            else:
                messagebox.showinfo("Sucesso", "Horários de pico diários salvos com sucesso! A automação agora usará estas regras.", parent=popup)
                popup.destroy()

        # 4. Botão Salvar
        # CORREÇÃO: Posiciona o botão Salvar IMEDIATAMENTE após a última linha populada (row_num + 1)
        btn_salvar = ttk.Button(frame, text="💾 Salvar Regras de Pico", command=salvar_picos)
        btn_salvar.grid(row=len(picos_atuais) + 1, column=0, columnspan=3, pady=20, sticky=tk.EW)


    def alternar_modo(self):
        self.modo_edicao = not self.modo_edicao
        if self.modo_edicao:
            self.btn_modo.config(text="✅ Salvar e Voltar")
            self.lbl_legenda.config(text="Modo: CONFIGURAÇÃO (Clique para editar setor)", foreground="red")
        else:
            self.btn_modo.config(text="🔧 Configurar Mapa")
            self.lbl_legenda.config(text="Modo: ESCALAÇÃO", foreground="green")
            self.carregar_escala_do_dia()

    def abrir_gestao_freelancers(self):
        """Abre uma janela para listar, criar e editar freelancers."""
        popup = Toplevel(self.root)
        popup.title("Gerenciar Freelancers")
        popup.geometry("550x450")
        popup.transient(self.root)

        # --- Área de Lista ---
        frame_lista = ttk.Frame(popup, padding="10")
        frame_lista.pack(fill=tk.BOTH, expand=True)

        cols = ('ID', 'Nome', 'Telefone')
        tree = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')
        tree.heading('ID', text='ID'); tree.column('ID', width=40, anchor='center')
        tree.heading('Nome', text='Nome'); tree.column('Nome', width=200)
        tree.heading('Telefone', text='Telefone'); tree.column('Telefone', width=150, anchor='center')
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(frame_lista, orient="vertical", command=tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=sb.set)

        def carregar_lista():
            for i in tree.get_children(): tree.delete(i)
            frees = database.listar_freelancers() # Reusa função existente
            for f in frees:
                # Ajuste dependendo de como o banco retorna (Objeto ou Tupla)
                # O código existente sugere Objeto (f.Nome), mas drivers as vezes retornam Tupla.
                # Assumindo Objeto baseado no padrão do projeto:
                tree.insert("", "end", values=(f.FreelancerID, f.Nome, f.Telefone))

        def novo():
            nome = simpledialog.askstring("Novo", "Nome Completo:", parent=popup)
            if nome:
                tel = simpledialog.askstring("Contato", "Telefone (WhatsApp) com DDD:", parent=popup)
                if tel:
                    if database.criar_freelancer(nome, tel):
                        carregar_lista()
                        messagebox.showinfo("Sucesso", "Freelancer cadastrado!", parent=popup)
        # --- NOVA FUNÇÃO: Excluir Freelancer ---
        def excluir():
            selecionado = tree.focus()
            if not selecionado: 
                messagebox.showwarning("Aviso", "Selecione um freelancer na lista para excluir.", parent=popup)
                return
            
            f_id = tree.item(selecionado, 'values')[0]
            f_nome = tree.item(selecionado, 'values')[1]

            if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o freelancer {f_nome}?\n\nIsso limpará todas as escalas onde ele estiver.", parent=popup):
                 # Chama a função de exclusão do banco
                 if database.excluir_freelancer(f_id):
                    carregar_lista()
                    messagebox.showinfo("Sucesso", "Freelancer excluído!", parent=popup)
                 else:
                    messagebox.showerror("Erro", "Falha ao excluir no banco.", parent=popup)
        def editar():
            selecionado = tree.focus()
            if not selecionado: 
                messagebox.showwarning("Aviso", "Selecione um freelancer na lista para editar.", parent=popup)
                return

            dados = tree.item(selecionado, 'values')
            f_id, f_nome, f_tel = dados

            novo_nome = simpledialog.askstring("Editar", "Nome Completo:", initialvalue=f_nome, parent=popup)
            if novo_nome:
                novo_tel = simpledialog.askstring("Editar", "Telefone:", initialvalue=f_tel, parent=popup)
                if novo_tel:
                    if database.atualizar_freelancer(f_id, novo_nome, novo_tel):
                        carregar_lista()
                        messagebox.showinfo("Sucesso", "Dados atualizados!", parent=popup)
                    else:
                        messagebox.showerror("Erro", "Falha ao atualizar no banco.", parent=popup)

        # --- Área de Botões ---
        frame_btns = ttk.Frame(popup, padding="10")
        frame_btns.pack(fill=tk.X, side=tk.BOTTOM)

        ttk.Button(frame_btns, text="➕ Novo Cadastro", command=novo).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        ttk.Button(frame_btns, text="✏️ Editar Selecionado", command=editar).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        # Carrega dados iniciais
        carregar_lista()


    def abrir_janela_escalacao(self, pos_id):
        try:
            dados_pos = next((p for p in self.posicoes if p[0] == pos_id), None)
            if not dados_pos: return
            nome_pos = dados_pos[1]
        except StopIteration: return 

        popup = Toplevel(self.root)
        popup.title(f"Escalar: {nome_pos}")
        popup.geometry("500x500") # Aumentado para caber alertas
        popup.update_idletasks()
        x_c = self.root.winfo_x() + (self.root.winfo_width() // 2) - (500 // 2)
        y_c = self.root.winfo_y() + (self.root.winfo_height() // 2) - (500 // 2)
        popup.geometry(f"+{x_c}+{y_c}")

        dados_atuais = self.escala_atual.get(pos_id)

        # --- Carregar Configurações para Cálculo Automático ---
        config_db = database.buscar_configuracoes_escala()
        JORNADA_PADRAO = getattr(config_db, 'DuracaoJornadaPadrao', 8) or 8
        INTERVALO_PADRAO = getattr(config_db, 'DuracaoIntervalo', 1) or 1

        ttk.Label(popup, text="Quem vai trabalhar aqui?").pack(pady=5)
        combo_pessoas = ttk.Combobox(popup, width=40)
        combo_pessoas.pack()

        # Req 2: Mapa agora inclui Telefone também para funcionários
        mapa_ids = {} 
        lista_nomes = ["(Vazio)"]
        for f in database.listar_funcionarios():
            # f[4] é TelefoneWhatsApp na query do database.py
            label = f"[Fixo] {f.NomeCompleto}"; lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'func', 'id': f.FuncionarioID, 'tel': f.TelefoneWhatsApp} 
        for fr in database.listar_freelancers():
            label = f"[Free] {fr.Nome}"; lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'free', 'id': fr.FreelancerID, 'tel': fr.Telefone}
        combo_pessoas['values'] = lista_nomes

        # Label de Alerta (Req 3)
        lbl_alerta = tk.Label(popup, text="", fg="red", font=("Arial", 9, "bold"), wraplength=450)
        lbl_alerta.pack(pady=5)

        # Variável para armazenar telefone atual para o botão WhatsApp
        self.telefone_atual_para_envio = None 

        selecao_inicial = ""
        if dados_atuais:
            if dados_atuais.FuncionarioID:
                selecao_inicial = next((k for k, v in mapa_ids.items() if v['tipo'] == 'func' and v['id'] == dados_atuais.FuncionarioID), "")
            elif dados_atuais.FreelancerID:
                selecao_inicial = next((k for k, v in mapa_ids.items() if v['tipo'] == 'free' and v['id'] == dados_atuais.FreelancerID), "")

        combo_pessoas.set(selecao_inicial)

        frame_hor = ttk.LabelFrame(popup, text="Horários", padding=10)
        frame_hor.pack(fill=tk.X, padx=10, pady=10)

        # Variáveis de controle para auto-cálculo
        var_ent = tk.StringVar()
        var_sai = tk.StringVar()

        ttk.Label(frame_hor, text="Entrada:").grid(row=0, column=0); e_ent = ttk.Entry(frame_hor, textvariable=var_ent, width=8); e_ent.grid(row=0, column=1)
        ttk.Label(frame_hor, text="Saída:").grid(row=0, column=2); e_sai = ttk.Entry(frame_hor, textvariable=var_sai, width=8); e_sai.grid(row=0, column=3)
        ttk.Label(frame_hor, text="Intervalo Início:").grid(row=1, column=0); e_int_ini = ttk.Entry(frame_hor, width=8); e_int_ini.grid(row=1, column=1)
        ttk.Label(frame_hor, text="Intervalo Fim:").grid(row=1, column=2); e_int_fim = ttk.Entry(frame_hor, width=8); e_int_fim.grid(row=1, column=3)

        # --- Lógica Req 1: Auto-Cálculo de Saída ---
        def calcular_saida(*args):
            entrada = var_ent.get()
            if len(entrada) == 5 and re.match(r'^\d{2}:\d{2}$', entrada):
                try:
                    dt_ent = datetime.strptime(entrada, '%H:%M')
                    # Adiciona Jornada + Intervalo
                    total_horas = JORNADA_PADRAO + INTERVALO_PADRAO
                    # CORREÇÃO: Converter Decimal para float, pois timedelta não aceita Decimal
                    dt_sai = dt_ent + timedelta(hours=float(total_horas))
                    var_sai.set(dt_sai.strftime('%H:%M'))
                except ValueError:
                    pass

        # O trace dispara sempre que a variável muda (digitação)
        var_ent.trace_add("write", calcular_saida)

        # --- Lógica Req 2 e 3: Ao selecionar pessoa ---
        def ao_selecionar_pessoa(event):
            nome_sel = combo_pessoas.get()
            lbl_alerta.config(text="") # Limpa alertas
            self.telefone_atual_para_envio = None # Reseta telefone

            if nome_sel and nome_sel != "(Vazio)":
                dados = mapa_ids.get(nome_sel)
                if dados:
                    # Req 2: Puxa o telefone (já carregado no mapa)
                    self.telefone_atual_para_envio = dados.get('tel')

                    # Req 3: Se for funcionário fixo, verifica conflitos
                    if dados['tipo'] == 'func':
                        msg_conflito = database.verificar_status_disponibilidade(dados['id'], self.data_selecionada)
                        if msg_conflito:
                            lbl_alerta.config(text=msg_conflito)

        combo_pessoas.bind("<<ComboboxSelected>>", ao_selecionar_pessoa)

        # Preenchimento inicial de valores
        if dados_atuais:
            safe_fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5] if v else ""
            var_ent.set(safe_fmt(dados_atuais.HorarioEntrada))
            var_sai.set(safe_fmt(dados_atuais.HorarioSaida))
            if getattr(dados_atuais, 'InicioIntervalo', None): e_int_ini.insert(0, safe_fmt(dados_atuais.InicioIntervalo))
            if getattr(dados_atuais, 'FimIntervalo', None): e_int_fim.insert(0, safe_fmt(dados_atuais.FimIntervalo))

            # Dispara a lógica de seleção para carregar telefone/alertas do atual
            ao_selecionar_pessoa(None)
        else:
            var_ent.set("08:00") # Dispara o auto-cálculo para saída padrão

        ttk.Label(popup, text="Foco do Dia:").pack(anchor=tk.W, padx=10)
        txt_foco = tk.Text(popup, height=5, width=40); txt_foco.pack(padx=10, pady=5)

        # Lógica de Foco (Mantida original)
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

        foco_para_exibir = dados_atuais.FocoDoDia if (dados_atuais and dados_atuais.FocoDoDia) else ""
        if not foco_para_exibir:
            try:
                ultimo = database.buscar_ultimo_foco_posicao(pos_id)
                foco_para_exibir = ultimo if ultimo else msg_foco_padrao
            except: foco_para_exibir = msg_foco_padrao

        txt_foco.insert("1.0", foco_para_exibir)

        def salvar():
            def validar_hora(texto):
                if not texto or texto.strip() == "": return True
                try: datetime.strptime(texto, '%H:%M'); return True
                except ValueError: return False

            horarios = [var_ent.get(), var_sai.get(), e_int_ini.get(), e_int_fim.get()]
            for h in horarios:
                if not validar_hora(h):
                    messagebox.showerror("Erro", f"Horário inválido: '{h}'. Use HH:MM.")
                    return

            def tratar_vazio(valor): return valor if valor and valor.strip() else None
            selecao = combo_pessoas.get()

            func_id = None; free_id = None
            if selecao and selecao != "(Vazio)":
                d = mapa_ids.get(selecao)
                if d:
                    if d['tipo'] == 'func': func_id = d['id']
                    else: free_id = d['id']

            database.salvar_escala_dia(self.data_selecionada, pos_id, func_id, free_id,
                tratar_vazio(var_ent.get()), tratar_vazio(var_sai.get()), 
                tratar_vazio(e_int_ini.get()), tratar_vazio(e_int_fim.get()),
                txt_foco.get("1.0", tk.END).strip())

            if func_id:
                fixo_atual = database.buscar_funcionarios_com_posicao_padrao(pos_id)
                id_fixo_atual = fixo_atual[0] if fixo_atual else None
                if func_id != id_fixo_atual:
                    if messagebox.askyesno("Posição Fixa", "Definir este funcionário como FIXO nesta posição?"):
                        database.definir_posicao_padrao_funcionario(func_id, pos_id)

            popup.destroy()
            self.carregar_escala_do_dia()

        def enviar_zap():
            selecao = combo_pessoas.get()
            if not selecao or selecao == "(Vazio)": return

            # Req 2: Usa o telefone recuperado e armazenado na seleção
            tel = self.telefone_atual_para_envio
            nome_pessoa_limpo = selecao.split('] ')[1] if ']' in selecao else selecao

            if not tel:
                # Fallback: Pede manual se não achou no banco
                tel = simpledialog.askstring("Telefone", f"Telefone não encontrado para {nome_pessoa_limpo}. Digite (DDD+Num):", parent=popup)
                if not tel: return

            try:
                data_obj = datetime.strptime(self.data_selecionada, '%Y-%m-%d')
                data_fmt = data_obj.strftime('%d/%m/%y')
            except ValueError: data_fmt = self.data_selecionada

            texto_msg = (
                f"Olá, *{nome_pessoa_limpo}*! 👋\nPor favor, *confirme sua presença*.\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📅 *Data:* {data_fmt}\n📍 *Posição:* {nome_pos}\n⏰ *Horário:* {var_ent.get()} às {var_sai.get()}"
            )
            if e_int_ini.get() and e_int_fim.get(): texto_msg += f"\n☕ *Intervalo:* {e_int_ini.get()} às {e_int_fim.get()}"
            if txt_foco.get("1.0", "end-1c").strip(): texto_msg += f"\n\n🎯 *FOCO:* {txt_foco.get('1.0', 'end-1c').strip()}"

            import notificador_whatsapp
            if messagebox.askyesno("Enviar", "Enviar via BOT automático? (Não = Web)"):
                ok, res = notificador_whatsapp.enviar_mensagem_whatsapp(tel, texto_msg)
                if ok: messagebox.showinfo("Sucesso", res); popup.destroy()
                else: messagebox.showerror("Erro", res)
            else:
                tel_limpo = re.sub(r'\D', '', tel)
                url = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(texto_msg)}"
                webbrowser.open(url); popup.destroy()

        frame_botoes = ttk.Frame(popup, padding="10")
        frame_botoes.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(frame_botoes, text="✅ Salvar", command=salvar).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(frame_botoes, text="📱 WhatsApp", command=enviar_zap).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)                

if __name__ == "__main__":
    root = tk.Tk()
    app = AppEscalaLoja(root)
    root.mainloop()

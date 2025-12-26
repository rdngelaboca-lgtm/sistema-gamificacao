import tkinter as tk
import logging
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
import time

logger = logging.getLogger(__name__)

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
        # Botão de Envio em Massa WhatsApp
        self.btn_wpp_mass = ttk.Button(self.frame_topo, text="📱 Confirmar Escala (WhatsApp)", command=self.enviar_confirmacoes_em_massa)
        self.btn_wpp_mass.pack(side=tk.LEFT, padx=5)
        self.btn_config = ttk.Button(self.frame_topo, text="⚙️ Configurações Automação", command=self.abrir_janela_configuracoes)
        self.btn_config.pack(side=tk.LEFT, padx=5)

        # --- Canvas do Mapa ---
        self.canvas = tk.Canvas(self.frame_mapa, bg="#e0e0e0", cursor="hand2")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.clique_no_mapa) 
        # Garante que os marcadores acompanhem o mapa em caso de redimensionamento da janela
        self.canvas.bind("<Configure>", lambda e: self.redesenhar_marcadores())

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
        if not self.data_selecionada:
            return
        self.canvas.delete("marcador")
        self.canvas.delete("texto_marcador")
        self.canvas.delete("setor_tag")

        dia_semana_hoje = datetime.strptime(self.data_selecionada, '%Y-%m-%d').isoweekday() + 1
        if dia_semana_hoje == 8: dia_semana_hoje = 1

        for pos in self.posicoes:
            pos_id, nome, coord_x_db, coord_y_db, _, setor = pos 

            # Captura o tamanho atual do canvas para renderização responsiva
            W = self.canvas.winfo_width() if self.canvas.winfo_width() > 1 else 1180
            H = self.canvas.winfo_height() if self.canvas.winfo_height() > 1 else 600

            # --- LÓGICA HÍBRIDA DE SEGURANÇA (PIXELS VS PERCENTUAL) ---
            # Se o valor no banco for maior que 1, tratamos como pixel fixo (legado).
            # Se for menor ou igual a 1, aplicamos a escala responsiva (novo).
            try:
                val_x = float(coord_x_db)
                val_y = float(coord_y_db)

                if val_x > 1.0:
                    x, y = val_x, val_y
                else:
                    x, y = val_x * W, val_y * H
            except (ValueError, TypeError):
                continue # Pula se as coordenadas estiverem corrompidas no banco
            # ----------------------------------------------------------

            label_final = f"{nome}\n"
            cor = "#ff4444" # Vermelho (Vazio) padrão
            
            # --- LÓGICA MULTI-TURNO ---
            lista_turnos = self.escala_atual.get(pos_id, [])
            
            if lista_turnos:
                # Se tem alguém escalado (um ou mais)
                cor = "#00C851" # Verde
                
                # Monta a lista de nomes e horários
                nomes_formatados = []
                for dados in lista_turnos:
                    nome_p = dados.NomePessoa if dados.NomePessoa else "?"
                    
                    # Formata horário curto (Ex: 13-18)
                    h_ent = str(dados.HorarioEntrada)[:5] if dados.HorarioEntrada else ""
                    h_sai = str(dados.HorarioSaida)[:5] if dados.HorarioSaida else ""
                    
                    # Se não tiver nome, muda cor para amarelo (alerta)
                    if not dados.NomePessoa: cor = "#FFBB33"
                        
                    nomes_formatados.append(f"{nome_p} ({h_ent}-{h_sai})")
                
                label_final += "\n".join(nomes_formatados)

            elif not self.modo_edicao:
                # Lógica de Sugestão (Azul) - Se estiver vazio
                func_padrao = database.buscar_funcionarios_com_posicao_padrao(pos_id)
                if func_padrao:
                    f_id, f_nome, f_folga = func_padrao
                    status_indisponivel = database.verificar_status_disponibilidade(f_id, self.data_selecionada)

                    if not status_indisponivel and str(f_folga) != str(dia_semana_hoje):
                        label_final += f"{f_nome} (Fixo)"
                        cor = "#33b5e5" # Azul
                    else:
                        label_final += "(Vazio)"
            else:
                label_final += "(Vazio)"

            tag = f"pos_{pos_id}"

            # Desenha Marcador (Bolinha)
            self.canvas.create_oval(x-15, y-15, x+15, y+15, fill=cor, outline="white", width=2, tags=("marcador", tag))

            # Desenha Texto (Nome + Horários)
            self.canvas.create_text(x, y+35, text=label_final, fill="black", font=("Arial", 7, "bold"), justify=tk.CENTER, tags=("texto_marcador", tag))

            # Desenha Tag do Setor
            if self.modo_edicao or setor:
                cor_setor = "blue" if setor else "gray"
                txt_setor = f"[{setor}]" if setor else "[Sem Setor]"
                self.canvas.create_text(x, y-25, text=txt_setor, fill=cor_setor, font=("Arial", 7), tags=("setor_tag", tag))

        self.canvas.tag_lower("fundo")

    @staticmethod
    def _parse_horario_seguro(valor):
        """Converte string, datetime, time ou timedelta para time object de forma segura."""
        if valor is None: return None

        # [CORREÇÃO] Tratamento para timedelta (comum em retornos SQL TIME via ODBC)
        if isinstance(valor, timedelta):
            total_seconds = int(valor.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            # Cria um tempo dummy para extrair o objeto .time()
            return (datetime.min + timedelta(hours=hours, minutes=minutes)).time()

        if hasattr(valor, 'time'): return valor.time() # Já é datetime

        if isinstance(valor, str):
            try:
                # Tenta HH:MM:SS ou HH:MM
                fmt = "%H:%M:%S" if len(valor.split(':')) == 3 else "%H:%M"
                return datetime.strptime(valor, fmt).time()
            except ValueError:
                return None

        # Se já for objeto time puro (importação local para evitar erro de referência se não estiver no topo)
        from datetime import time as dt_time
        if isinstance(valor, dt_time):
            return valor

        return None # Tipo desconhecido

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
            
            # Captura o tamanho atual do mapa para converter o clique em percentagem
            # Fallback de segurança para 1180x600 se o canvas reportar dimensão inválida
            W = self.canvas.winfo_width() if self.canvas.winfo_width() > 1 else 1180
            H = self.canvas.winfo_height() if self.canvas.winfo_height() > 1 else 600
            
            # Cálculo da coordenada relativa (0.0 a 1.0)
            rel_x = x / W
            rel_y = y / H
            
            # Normalização do setor para o SQL
            setor_limpo = setor if setor else None

            if nome:
                # PERSISTÊNCIA: Agora guardamos o valor relativo (EX: 0.4567) em vez de pixels (EX: 540)
                database.criar_posicao_loja(nome, rel_x, rel_y, setor_limpo)
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

        # Coleta turnos considerando que escala_atual agora é um dicionário de listas (v2)
        for pos_id, turnos in self.escala_atual.items():
            # Busca o setor da posição correspondente
            setor = next((p[5] for p in self.posicoes if p[0] == pos_id), "Geral")

            for dados in turnos:
                # Validação rigorosa para evitar falhas na calculadora lógica
                if dados.HorarioEntrada and dados.HorarioSaida and dados.NomePessoa:
                    t_ent = self._parse_horario_seguro(dados.HorarioEntrada)
                    t_sai = self._parse_horario_seguro(dados.HorarioSaida)

                    if t_ent and t_sai:
                        dt_entrada = datetime.combine(dia_obj, t_ent)
                        dt_saida = datetime.combine(dia_obj, t_sai)

                        pessoas_para_calcular.append({
                            'id_posicao': pos_id,
                            'nome': dados.NomePessoa,
                            'setor': setor,
                            'entrada': dt_entrada,
                            'saida': dt_saida
                        })
                    else:
                        logger.warning(f"Horário inválido ignorado na posição {pos_id}: {dados.NomePessoa}")

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

        # 4. Acumula sugestões e aplica em Lote (Atômico)
        lote_para_salvar = []
        for pos_id, (ini, fim) in sugestoes.items():
            lote_para_salvar.append({
                'pos_id': pos_id,
                'ini': ini,
                'fim': fim
            })

        if lote_para_salvar:
            if database.salvar_escalas_em_lote(self.data_selecionada, lote_para_salvar):
                count_aplicados = len(lote_para_salvar)
            else:
                messagebox.showerror("Erro Crítico", "Falha ao persistir lote de intervalos. Nenhuma alteração foi salva.")
                return

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
        # [CORREÇÃO FORENSICS] Verifica se a janela ainda existe antes de tentar modificar widgets
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return

        self.btn_telegram.config(state='normal', text="📢 Enviar Escala Telegram")
        if sucesso:
            messagebox.showinfo("Sucesso", "Escala enviada para o grupo do Telegram!")
        else:
            messagebox.showerror("Erro", f"Falha ao enviar Telegram: {erro_msg}")

    # --- NOVO: Envio em Massa WhatsApp ---
    def enviar_confirmacoes_em_massa(self):
        if not self.data_selecionada: return

        # Snapshot (Cópia de segurança) para evitar conflito se o usuário mudar a data na tela
        data_snapshot = self.data_selecionada
        escala_dia = database.buscar_escala_do_dia(data_snapshot)
        lista_envio = []

        # Cruzamento de dados: Escala + Nome da Posição
        for pos_id, turnos in escala_dia.items():
            # CORREÇÃO: 'turnos' é uma lista (v2 Multi-Turno), precisamos iterar sobre ela
            for dados in turnos:
                # Verifica se tem pessoa e telefone cadastrado no banco
                if dados.NomePessoa and dados.TelefonePessoa:
                    # Busca o nome amigável da posição na lista em memória
                    nome_posicao = next((p[1] for p in self.posicoes if p[0] == pos_id), "Posição")

                    lista_envio.append({
                        'nome': dados.NomePessoa,
                        'telefone': dados.TelefonePessoa,
                        'posicao': nome_posicao,
                        'entrada': dados.HorarioEntrada,
                        'saida': dados.HorarioSaida
                    })

        if not lista_envio:
            messagebox.showwarning("Aviso", "Nenhuma pessoa com telefone encontrado na escala de hoje.")
            return

        # 2. Confirmação
        if not messagebox.askyesno("Confirmação em Massa", 
            f"Encontradas {len(lista_envio)} pessoas com telefone na escala.\n\n"
            "Deseja enviar a confirmação de horário individual para o WhatsApp de cada um via BOT?\n\n"
            "⚠️ Isso pode levar alguns segundos."):
            return

        # 3. Execução em Thread (Background)
        self.btn_wpp_mass.config(state='disabled', text="Enviando...")

        def run_envio():
            enviados = 0
            erros = 0

            for item in lista_envio:
                try:
                    # Formatação de Horário Segura
                    fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5]
                    horario_str = f"{fmt(item['entrada'])} às {fmt(item['saida'])}"
                    data_fmt = datetime.strptime(self.data_selecionada, '%Y-%m-%d').strftime('%d/%m')

                    mensagem = (
                        f"Olá, *{item['nome']}*! 👋\n"
                        f"Confirmação de Escala:\n"
                        f"📅 Data: *{data_fmt}*\n"
                        f"📍 Posição: *{item['posicao']}*\n"
                        f"⏰ Horário: *{horario_str}*\n\n"
                        f"Bom trabalho!"
                    )

                    ok, _ = notificador_whatsapp.enviar_mensagem_whatsapp(item['telefone'], mensagem)
                    if ok: enviados += 1
                    else: erros += 1

                    time.sleep(1.5) # Delay de segurança para a API (Anti-Spam)

                except Exception as e:
                    print(f"Erro ao enviar para {item['nome']}: {e}")
                    erros += 1

            # Callback para UI
            self.root.after(0, lambda: self._finalizar_envio_wpp(enviados, erros))

        threading.Thread(target=run_envio, daemon=True).start()

    def _finalizar_envio_wpp(self, enviados, erros):
        self.btn_wpp_mass.config(state='normal', text="📱 Confirmar Escala (WhatsApp)")
        msg = f"Processo finalizado!\n\n✅ Enviados: {enviados}\n❌ Falhas: {erros}"
        if erros > 0:
            messagebox.showwarning("Relatório de Envio", msg)
        else:
            messagebox.showinfo("Sucesso", msg)

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
        popup.geometry("600x650") 
        popup.update_idletasks()
        
        # Centraliza a janela em relação à tela principal
        x_c = self.root.winfo_x() + (self.root.winfo_width() // 2) - (600 // 2)
        y_c = self.root.winfo_y() + (self.root.winfo_height() // 2) - (650 // 2)
        popup.geometry(f"+{x_c}+{y_c}")

        # --- Parte 1: Lista de Turnos Existentes ---
        frame_lista = ttk.LabelFrame(popup, text=f"Quem já está em '{nome_pos}' hoje?", padding=10)
        frame_lista.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        cols = ('ID', 'Nome', 'Entrada', 'Saída')
        tree = ttk.Treeview(frame_lista, columns=cols, show='headings', height=4)
        tree.heading('ID', text='ID'); tree.column('ID', width=30)
        tree.heading('Nome', text='Nome'); tree.column('Nome', width=180)
        tree.heading('Entrada', text='Entrada'); tree.column('Entrada', width=70)
        tree.heading('Saída', text='Saída'); tree.column('Saída', width=70)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)

        # Carrega dados atuais da escala para a lista
        lista_turnos = self.escala_atual.get(pos_id, [])
        for t in lista_turnos:
            fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5]
            tree.insert("", "end", values=(t.EscalaID, t.NomePessoa, fmt(t.HorarioEntrada), fmt(t.HorarioSaida)))

        # --- Parte 2: Formulário de Adição/Edição ---
        frame_form = ttk.LabelFrame(popup, text="Adicionar / Editar Turno", padding=10)
        frame_form.pack(fill=tk.X, padx=10, pady=10)

        var_ent = tk.StringVar(value="08:00")
        var_sai = tk.StringVar()
        var_escala_id_edit = tk.StringVar(value="") # Vazio = Novo, Com Valor = Edição

        # Carregar Configurações de jornada
        config_db = database.buscar_configuracoes_escala()
        JORNADA_PADRAO = getattr(config_db, 'DuracaoJornadaPadrao', 8) or 8

        ttk.Label(frame_form, text="Funcionário / Freelancer:").pack(anchor="w")
        combo_pessoas = ttk.Combobox(frame_form, width=40)
        combo_pessoas.pack(fill="x", pady=5)

        mapa_ids = {} 
        lista_nomes = ["(Vazio)"]
        for f in database.listar_funcionarios():
            label = f"[Fixo] {f.NomeCompleto}"; lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'func', 'id': f.FuncionarioID, 'tel': f.TelefoneWhatsApp} 
        for fr in database.listar_freelancers():
            label = f"[Free] {fr.Nome}"; lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'free', 'id': fr.FreelancerID, 'tel': fr.Telefone}
        combo_pessoas['values'] = lista_nomes

        frame_h = ttk.Frame(frame_form)
        frame_h.pack(fill="x", pady=5)
        ttk.Label(frame_h, text="Entrada:").pack(side=tk.LEFT)
        e_ent = ttk.Entry(frame_h, textvariable=var_ent, width=8); e_ent.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_h, text="Saída:").pack(side=tk.LEFT)
        e_sai = ttk.Entry(frame_h, textvariable=var_sai, width=8); e_sai.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(frame_form, text="Intervalo (Início - Fim):").pack(anchor="w")
        frame_int = ttk.Frame(frame_form)
        frame_int.pack(fill="x", pady=5)
        e_int_ini = ttk.Entry(frame_int, width=8); e_int_ini.pack(side=tk.LEFT, padx=(0,5))
        e_int_fim = ttk.Entry(frame_int, width=8); e_int_fim.pack(side=tk.LEFT)

        ttk.Label(frame_form, text="Foco do Dia:").pack(anchor="w")
        txt_foco = tk.Text(frame_form, height=3, width=40); txt_foco.pack(fill="x", pady=5)

        # --- Lógica de Auto-Cálculo de Saída ---
        def calcular_saida(*args):
            entrada = var_ent.get()
            if len(entrada) == 5 and re.match(r'^\d{2}:\d{2}$', entrada):
                try:
                    dt_ent = datetime.strptime(entrada, '%H:%M')
                    dt_sai = dt_ent + timedelta(hours=float(JORNADA_PADRAO))
                    var_sai.set(dt_sai.strftime('%H:%M'))
                except ValueError: pass
        var_ent.trace_add("write", calcular_saida)

        # --- Função para Carregar Edição ao Clicar na Lista ---
        def carregar_para_edicao(event):
            sel = tree.focus()
            if not sel: return
            item = tree.item(sel, 'values')
            escala_id = int(item[0])
            
            turno = next((t for t in lista_turnos if t.EscalaID == escala_id), None)
            if not turno: return

            var_escala_id_edit.set(escala_id)
            
            nome_combo = ""
            if turno.FuncionarioID:
                nome_combo = next((k for k, v in mapa_ids.items() if v['tipo'] == 'func' and v['id'] == turno.FuncionarioID), "")
            elif turno.FreelancerID:
                nome_combo = next((k for k, v in mapa_ids.items() if v['tipo'] == 'free' and v['id'] == turno.FreelancerID), "")
            combo_pessoas.set(nome_combo)

            fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5] if v else ""
            var_ent.set(fmt(turno.HorarioEntrada))
            var_sai.set(fmt(turno.HorarioSaida))
            e_int_ini.delete(0, tk.END); e_int_ini.insert(0, fmt(turno.InicioIntervalo))
            e_int_fim.delete(0, tk.END); e_int_fim.insert(0, fmt(turno.FimIntervalo))
            txt_foco.delete("1.0", tk.END); txt_foco.insert("1.0", turno.FocoDoDia or "")

            btn_salvar.config(text="🔄 Atualizar Turno")
            btn_novo.config(state="normal")

        tree.bind("<<TreeviewSelect>>", carregar_para_edicao)

        def limpar_form():
            var_escala_id_edit.set("")
            combo_pessoas.set("")
            var_ent.set("08:00")
            e_int_ini.delete(0, tk.END); e_int_fim.delete(0, tk.END)
            txt_foco.delete("1.0", tk.END)
            btn_salvar.config(text="✅ Adicionar Turno")
            tree.selection_remove(tree.selection())

        def salvar():
            selecao = combo_pessoas.get()
            if not selecao or selecao == "(Vazio)":
                messagebox.showwarning("Aviso", "Selecione um funcionário ou freelancer.", parent=popup)
                return

            func_id = None; free_id = None
            d = mapa_ids.get(selecao)
            if d:
                if d['tipo'] == 'func': func_id = d['id']
                else: free_id = d['id']

            escala_id = var_escala_id_edit.get()

            if database.salvar_escala_dia_v3(
                escala_id if escala_id else None,
                self.data_selecionada, pos_id, func_id, free_id,
                var_ent.get(), var_sai.get(), 
                e_int_ini.get(), e_int_fim.get(),
                txt_foco.get("1.0", tk.END).strip()
            ):
                popup.destroy()
                self.carregar_escala_do_dia()
            else:
                messagebox.showerror("Erro", "Conflito de horário detectado!", parent=popup)

        # --- NOVA FUNÇÃO DE EXCLUSÃO ---
        def excluir_selecionado():
            sel = tree.focus()
            if not sel:
                messagebox.showwarning("Aviso", "Selecione um turno na lista acima para excluir.", parent=popup)
                return
            
            item = tree.item(sel, 'values')
            escala_id = item[0]
            nome_pessoa = item[1]

            confirmar = messagebox.askyesno("Confirmar Exclusão", 
                                            f"Deseja realmente remover a escalação de {nome_pessoa}?", 
                                            parent=popup)
            
            if confirmar:
                if database.excluir_turno_escala(escala_id):
                    messagebox.showinfo("Sucesso", "Escalação removida.", parent=popup)
                    popup.destroy()
                    self.carregar_escala_do_dia()
                else:
                    messagebox.showerror("Erro", "Falha ao excluir o registro.", parent=popup)

        # --- Frame de Botões (Rodapé) ---
        frame_btns = ttk.Frame(popup, padding=10)
        frame_btns.pack(fill=tk.X, side=tk.BOTTOM)
        
        btn_novo = ttk.Button(frame_btns, text="✨ Novo (Limpar)", command=limpar_form, state="disabled")
        btn_novo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Botão de Exclusão integrado
        btn_excluir = ttk.Button(frame_btns, text="🗑️ Excluir Turno", command=excluir_selecionado)
        btn_excluir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        btn_salvar = ttk.Button(frame_btns, text="✅ Adicionar Turno", command=salvar)
        btn_salvar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)                

if __name__ == "__main__":
    root = tk.Tk()
    app = AppEscalaLoja(root)
    root.mainloop()

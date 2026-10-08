# ==============================================================================
# escala_loja_main.py - Gestão de Escala da Loja (Mapa + Intervalos)
# ------------------------------------------------------------------------------
# VERSÃO DEPURADA
# Procure por "[DEPURAÇÃO]" para ver cada ponto corrigido e o motivo.
# Nenhum botão ou tela foi removido; foi ADICIONADO o botão "Excluir" nos Freelancers.
#
# [MELHORIA ESCALA] (procure por esta marca):
#   - 💰 Pagamentos de Freelancers: diária LONGA (8h20) ou CURTA (6h),
#     valores de seg-sáb e de domingo/feriado, hora extra em blocos de 20 min,
#     proporcional quando sai mais cedo, correção do horário real, ajuste
#     (bônus/desconto), marcar como PAGO, recibo para o WhatsApp, Excel e feriados.
#   - Barra do topo organizada em 2 linhas, ◀ Hoje ▶ para trocar o dia,
#     resumo do dia (pessoas, vagas, custo de freelancers) e barra de status.
#   - Proteções: não apaga/copia por cima de turno de freelancer já PAGO.
# ==============================================================================
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
from decimal import Decimal, InvalidOperation
import threading
import time

logger = logging.getLogger(__name__)

# [GESTÃO WEB] As regras da escala (conflitos, folga, jornada, intervalo, cores do mapa,
# fluxo, mensagens) ficam em escala_regras.py e valem igual para o PC e para a Web.
from escala_regras import (  # noqa: E402
    PADRAO_HORA, hora_ou_none, normalizar_folga, folga_do_funcionario, formatar_hora_curta,
    SETOR_TODOS, LIMITE_JORNADA_DIA_MIN, TURNO_EXIGE_INTERVALO_MIN, minutos_do_horario, faixa_turno,
    sobrepoe, hm, problema_intervalo, chave_pessoa, analisar_escala_do_dia, conflitos_ao_salvar,
    DIAS_SEMANA, DIAS_CURTOS, fmt_reais, para_decimal_br, fmt_horas, fmt_data_br, nome_tipo_dia,
    texto_calculo, SETORES_MAPA, MAPA_IMAGEM_LARGURA, MAPA_IMAGEM_ALTURA, parse_horario, dia_semana_banco,
    rotulo_e_cor_posicao, fluxo_por_hora, HORAS_FLUXO, pessoas_para_intervalos, gravar_intervalos,
    lista_envio_whatsapp, enviar_confirmacoes_whatsapp)


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
        self._cache_indisponibilidade = {}
        self._config_escala_cache = None  # [DEPURAÇÃO] evita consultar o banco a cada tecla digitada

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
        # [AUDITORIA ESCALA] Os setores vinham da tabela de TAREFAS (gamificação), que tem um
        # setor chamado "Geral". Escolhendo "Geral" o gráfico ficava VAZIO (nenhuma posição do
        # mapa tem setor "Geral"). Agora a lista vem dos setores das posições do mapa
        # (preenchida em carregar_escala_do_dia).
        self.combo_setor_grafico['values'] = [SETOR_TODOS]
        self.combo_setor_grafico.set(SETOR_TODOS)
        self.combo_setor_grafico.bind("<<ComboboxSelected>>", lambda e: self.atualizar_grafico_fluxo())

        # Inicializa o objeto do gráfico
        self.fig = Figure(figsize=(6, 1.8), dpi=100) # Ajuste de altura para caber o combo
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(bottom=0.2, top=0.85) # Margens para os textos não cortarem
        self.canvas_grafico = FigureCanvasTkAgg(self.fig, master=self.frame_grafico)
        self.canvas_grafico.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # --- Controles do Topo ---
        # [MELHORIA ESCALA] Organizado em 2 linhas:
        #   1ª linha = o DIA (data, ◀ Hoje ▶, copiar) e as ações do dia a dia;
        #   2ª linha = cadastros e configurações + resumo do dia.
        linha1 = ttk.Frame(self.frame_topo)
        linha1.pack(fill=tk.X)
        linha2 = ttk.Frame(self.frame_topo)
        linha2.pack(fill=tk.X, pady=(6, 0))

        ttk.Label(linha1, text="Data:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(linha1, text="◀", width=3, command=lambda: self.mudar_dia(-1)).pack(side=tk.LEFT, padx=(5, 0))
        self.date_entry = DateEntry(linha1, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_entry.pack(side=tk.LEFT, padx=3)
        self.date_entry.bind("<<DateEntrySelected>>", self._ao_trocar_data)
        ttk.Button(linha1, text="▶", width=3, command=lambda: self.mudar_dia(1)).pack(side=tk.LEFT)
        ttk.Button(linha1, text="Hoje", width=6, command=self.ir_para_hoje).pack(side=tk.LEFT, padx=(3, 0))
        self.lbl_dia_semana = ttk.Label(linha1, text="", font=("Arial", 10, "bold"), foreground="#0056b3")
        self.lbl_dia_semana.pack(side=tk.LEFT, padx=6)
        # [NOVO] Botão de Copiar Escala Anterior
        self.btn_copiar = ttk.Button(linha1, text="📋 Copiar Escala Anterior", command=self.abrir_dialogo_copiar_escala)
        self.btn_copiar.pack(side=tk.LEFT, padx=5)

        ttk.Separator(linha1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        # Botão Mágico de Automação
        self.btn_magic = ttk.Button(linha1, text="🪄 Gerar Intervalos Automáticos", command=self.gerar_intervalos)
        self.btn_magic.pack(side=tk.LEFT, padx=3)
        # Botão Gerenciador de Intervalos
        self.btn_intervalos = ttk.Button(linha1, text="⏱️ Gerenciar Intervalos", command=self.abrir_gerenciador_intervalos)
        self.btn_intervalos.pack(side=tk.LEFT, padx=3)

        ttk.Separator(linha1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        # Botão Telegram
        self.btn_telegram = ttk.Button(linha1, text="📢 Enviar Escala Telegram", command=self.enviar_escala_telegram)
        self.btn_telegram.pack(side=tk.LEFT, padx=3)
        # Botão de Envio em Massa WhatsApp
        self.btn_wpp_mass = ttk.Button(linha1, text="📱 Confirmar Escala (WhatsApp)", command=self.enviar_confirmacoes_em_massa)
        self.btn_wpp_mass.pack(side=tk.LEFT, padx=3)

        # 2ª linha: cadastros / configurações
        # [MELHORIA ESCALA] Pagamentos de freelancers
        self.btn_pagamentos = ttk.Button(linha2, text="💰 Pagamentos Freelancers", command=self.abrir_pagamentos_freelancers)
        self.btn_pagamentos.pack(side=tk.LEFT, padx=(0, 3))
        # [ATUALIZAÇÃO] Botão de Gestão de Freelancers
        self.btn_free = ttk.Button(linha2, text="👤 Gerenciar Freelancers", command=self.abrir_gestao_freelancers)
        self.btn_free.pack(side=tk.LEFT, padx=3)
        self.btn_modo = ttk.Button(linha2, text="🔧 Configurar Mapa (Setores)", command=self.alternar_modo)
        self.btn_modo.pack(side=tk.LEFT, padx=3)
        # Botão Editor de Diretrizes
        self.btn_diretrizes = ttk.Button(linha2, text="📝 Editar Diretrizes", command=self.abrir_editor_diretrizes)
        self.btn_diretrizes.pack(side=tk.LEFT, padx=3)
        self.btn_config = ttk.Button(linha2, text="⚙️ Configurações Automação", command=self.abrir_janela_configuracoes)
        self.btn_config.pack(side=tk.LEFT, padx=3)
        self.lbl_legenda = ttk.Label(linha2, text="Modo: ESCALAÇÃO", foreground="green", font=("Arial", 10, "bold"))
        self.lbl_legenda.pack(side=tk.LEFT, padx=10)
        # [MELHORIA ESCALA] Resumo do dia (pessoas, vagas, custo de freelancers)
        self.lbl_resumo_dia = ttk.Label(linha2, text="", font=("Arial", 9, "bold"))
        self.lbl_resumo_dia.pack(side=tk.RIGHT, padx=5)

        # [MELHORIA ESCALA] Barra de status (mensagens rápidas, sem janelinha para clicar OK)
        self.lbl_status = tk.Label(root, text="", anchor="w", fg="#555555", font=("Arial", 9))
        self.lbl_status.pack(fill=tk.X, side=tk.BOTTOM, before=self.frame_inferior)
        self._id_status = None

        # --- Painel Lateral Embutido (Oculto por padrão) ---
        self.frame_lateral = ttk.LabelFrame(self.frame_mapa, text="Selecione uma Posição", width=380)
        self.frame_lateral.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)
        self.frame_lateral.pack_propagate(False) # Impede que o painel encolha

        self.pos_id_selecionada = None
        self.mapa_ids_lateral = {} # Guarda IDs de func/free
        self._construir_painel_lateral()
        self.frame_lateral.pack_forget() # Esconde o painel ao iniciar o app

        # --- Canvas do Mapa ---
        # Empacotado com side=tk.LEFT para dividir o espaço harmonicamente com o painel
        self.canvas = tk.Canvas(self.frame_mapa, bg="#e0e0e0", cursor="hand2")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
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
            logger.error(f"Erro ao carregar imagem do mapa: {e}")
            self.canvas.create_text(590, 300, text=f"Erro ao carregar 'layout_loja.png':\n{e}\nO sistema continua funcional sem o mapa de fundo.", fill="red", font=("Arial", 12, "bold"))

    def _indisponivel_no_dia(self, funcionario_id):
        """
        [DEPURAÇÃO] Consulta férias/afastamento/folga UMA vez por funcionário por dia.
        O mapa é redesenhado a cada redimensionamento da janela; sem este "cache" o
        banco seria consultado dezenas de vezes por segundo.
        """
        chave = (funcionario_id, self.data_selecionada)
        if chave not in self._cache_indisponibilidade:
            self._cache_indisponibilidade[chave] = database.verificar_status_disponibilidade(funcionario_id, self.data_selecionada)
        return self._cache_indisponibilidade[chave]

    def _ao_trocar_data(self, event=None):
        """
        [DEPURAÇÃO] Ao trocar a data, fecha o painel lateral. Antes ele continuava
        mostrando os turnos do dia ANTERIOR, e um "Salvar" gravava no dia novo.
        """
        self.frame_lateral.pack_forget()
        self.pos_id_selecionada = None
        self.carregar_escala_do_dia()

    def carregar_escala_do_dia(self, event=None):
        self.data_selecionada = self.date_entry.get_date().strftime('%Y-%m-%d')
        self._cache_indisponibilidade = {}  # Dados novos: esquece o cache antigo
        self.posicoes = database.listar_posicoes_loja()
        self.escala_atual = database.buscar_escala_do_dia(self.data_selecionada)
        # [AUDITORIA ESCALA] Funcionários e "posição fixa" lidos UMA vez por carga.
        # Antes o mapa consultava o banco a cada redesenho (e a janela redesenha várias
        # vezes por segundo enquanto é redimensionada), deixando a tela lenta.
        self._funcionarios_cache = list(database.listar_funcionarios())
        self._posicao_padrao_cache = {}
        self._atualizar_setores_grafico()
        self.redesenhar_marcadores()
        # [CORREÇÃO] Garante que o gráfico seja redesenhado junto com o mapa
        self.atualizar_grafico_fluxo()
        self.atualizar_resumo_dia()
        self.mostrar_alertas_do_dia()

    def _atualizar_setores_grafico(self):
        """[AUDITORIA ESCALA] Setores do filtro do gráfico = setores das posições do mapa."""
        setores = sorted({p[5] for p in self.posicoes if p[5]}, key=str.lower)
        self.combo_setor_grafico['values'] = [SETOR_TODOS] + setores
        if self.combo_setor_grafico.get() not in self.combo_setor_grafico['values']:
            self.combo_setor_grafico.set(SETOR_TODOS)

    def _motivo_indisponivel(self, funcionario_id):
        """Férias / afastamento / folga fixa / domingo de folga do funcionário no dia (texto) ou None."""
        return self._indisponivel_no_dia(funcionario_id)

    def mostrar_alertas_do_dia(self, extra=None, cor_extra=None):
        """
        [AUDITORIA ESCALA] O painel "Alertas de Regras e Conflitos" só era preenchido ao clicar
        em "Gerar Intervalos": com alguém escalado na folga, em dois lugares ao mesmo tempo
        ou com 14h no dia, ele continuava dizendo "Sistema pronto.". Agora ele confere a
        escala sempre que o dia é carregado ou alterado.
        'extra' = mensagens da calculadora de intervalos (aparecem primeiro).
        """
        try:
            alertas = analisar_escala_do_dia(self.escala_atual, self.posicoes, self._motivo_indisponivel)
        except Exception as e:
            logger.error(f"Erro ao conferir a escala do dia: {e}", exc_info=True)
            alertas = [('aviso', f"Não consegui conferir a escala: {e}")]
        icones = {'erro': '❌', 'aviso': '⚠️', 'info': ''}
        linhas = [extra] if extra else []
        linhas += [f"{icones.get(n, '')} {t}".strip() for n, t in alertas]
        if len(linhas) > 10:      # o painel tem altura fixa: não deixa a lista sumir pela borda
            linhas = linhas[:9] + [f"... e mais {len(linhas) - 9} alerta(s)."]
        if not linhas:
            self.lbl_alertas.config(text="✅ Nenhum conflito encontrado na escala deste dia.", fg="#1b7a2f")
            return
        tem_erro = any(n == 'erro' for n, _ in alertas)
        cor = cor_extra or ("#c62828" if tem_erro else ("#b26a00" if any(n == 'aviso' for n, _ in alertas) else "#555555"))
        self.lbl_alertas.config(text="\n".join(linhas), fg=cor)

    # -------------------------------------------------------------------
    # [MELHORIA ESCALA] Navegação de dias, status e resumo do dia
    # -------------------------------------------------------------------
    def mudar_dia(self, passo):
        """◀ / ▶: dia anterior / próximo."""
        self.date_entry.set_date(self.date_entry.get_date() + timedelta(days=passo))
        self._ao_trocar_data()

    def ir_para_hoje(self):
        self.date_entry.set_date(date.today())
        self._ao_trocar_data()

    def status(self, mensagem, tipo='ok', segundos=8):
        """Mensagem rápida no rodapé (some sozinha)."""
        cores = {'ok': '#1b7a2f', 'info': '#555555', 'aviso': '#b26a00', 'erro': '#c62828'}
        try:
            self.lbl_status.config(text=mensagem, fg=cores.get(tipo, '#555555'))
            if self._id_status:
                self.root.after_cancel(self._id_status)
            self._id_status = self.root.after(segundos * 1000, lambda: self.lbl_status.config(text=""))
        except Exception:
            pass

    def _config_pagamento(self, recarregar=False):
        if recarregar or getattr(self, '_cfg_pag_cache', None) is None:
            try:
                self._cfg_pag_cache = database.buscar_config_pagamento_freelancer()
            except Exception as e:
                logger.warning(f"Não foi possível ler os valores de pagamento de freelancer: {e}")
                self._cfg_pag_cache = dict(database.CONFIG_PAGAMENTO_PADRAO)
        return self._cfg_pag_cache

    def _feriado_do_dia(self, data_txt=None):
        """Nome do feriado do dia selecionado (ou None). Guardado para não ir ao banco toda hora."""
        data_txt = data_txt or self.data_selecionada
        cache = self.__dict__.setdefault('_cache_feriados', {})
        if data_txt not in cache:
            try:
                cache[data_txt] = database.nome_feriado(data_txt)
            except Exception as e:
                logger.warning(f"Não foi possível consultar feriados: {e}")
                cache[data_txt] = None
        return cache[data_txt]

    def _calcular_turno_free(self, entrada, saida, data_txt=None, tipo=None, ajuste=0, ent_escala=None, sai_escala=None):
        return database.calcular_pagamento_turno(entrada, saida, self._config_pagamento(), ajuste,
                                                 data_txt or self.data_selecionada, tipo,
                                                 ent_escala or entrada, sai_escala or saida,
                                                 self._feriado_do_dia(data_txt))

    def atualizar_resumo_dia(self):
        """Linha de resumo: quantas pessoas, posições vazias e quanto custam os freelancers do dia."""
        try:
            dia = datetime.strptime(self.data_selecionada, '%Y-%m-%d').date()
            feriado = self._feriado_do_dia()
            self.lbl_dia_semana.config(text=DIAS_SEMANA[dia.weekday()].capitalize()
                                       + (" (hoje)" if dia == date.today() else "")
                                       + (f" · 🎉 {feriado}" if feriado else ""))
            turnos = [t for lista in self.escala_atual.values() for t in lista]
            pessoas = len([t for t in turnos if t.NomePessoa])
            frees = [t for t in turnos if getattr(t, 'FreelancerID', None)]
            vazias = len([p for p in self.posicoes if not self.escala_atual.get(p[0])])
            texto = f"👥 {pessoas} na escala   ⭕ {vazias} posição(ões) vazia(s)"
            if frees:
                custo = Decimal('0')
                for t in frees:
                    calc = self._calcular_turno_free(t.HorarioEntrada, t.HorarioSaida, tipo=getattr(t, 'TipoDiaria', None))
                    custo += calc['Total'] if calc else Decimal('0')
                pagos = len(database.turnos_pagos(data_escala=self.data_selecionada))
                texto += f"   🧑‍🍳 {len(frees)} freelancer(s): {fmt_reais(custo)}"
                if pagos:
                    texto += f" ({pagos} pago(s))"
            self.lbl_resumo_dia.config(text=texto)
        except Exception as e:
            logger.warning(f"Não foi possível montar o resumo do dia: {e}")

    def abrir_dialogo_copiar_escala(self):
        """Abre opções rápidas para clonar escalas de dias anteriores."""
        if not self.data_selecionada:
            messagebox.showwarning("Aviso", "Selecione uma data no calendário primeiro.", parent=self.root)
            return

        # Proteção: Se a escala do dia atual já tiver dados, avisa que vai sobrescrever
        if any(self.escala_atual.values()):
            if not messagebox.askyesno("Atenção", f"Já existem pessoas escaladas para o dia {self.data_selecionada}.\n\nSe você copiar uma escala anterior, o preenchimento atual SERÁ APAGADO.\n\nDeseja continuar?", icon='warning', parent=self.root):
                return

        popup = Toplevel(self.root)
        popup.title("Copiar Escala")
        popup.geometry("380x150")
        popup.transient(self.root)
        popup.grab_set()

        ttk.Label(popup, text="Deseja copiar a escala de qual período?", font=("Arial", 11, "bold")).pack(pady=15)

        frame_btns = ttk.Frame(popup)
        frame_btns.pack(fill=tk.X, padx=10)

        # Cálculos das datas dinâmicas baseadas no dia selecionado na tela
        data_alvo_obj = datetime.strptime(self.data_selecionada, '%Y-%m-%d')
        data_ontem_str = (data_alvo_obj - timedelta(days=1)).strftime('%Y-%m-%d')
        data_semana_str = (data_alvo_obj - timedelta(days=7)).strftime('%Y-%m-%d')

        def executar_copia(data_origem):
            sucesso, msg = database.copiar_escala_dia(data_origem, self.data_selecionada)
            if sucesso:
                popup.destroy()
                self.carregar_escala_do_dia() # Recarrega a tela com os novos dados copiados
                self.status(f"Escala de {fmt_data_br(data_origem, True)} copiada para {fmt_data_br(self.data_selecionada, True)}.")
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        # Botão 1: Copiar de Ontem
        btn_ontem = ttk.Button(frame_btns, text="Copiar de Ontem", command=lambda: executar_copia(data_ontem_str))
        btn_ontem.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, ipady=5)

        # Botão 2: Copiar da Semana Passada (Mesmo dia da semana)
        btn_semana = ttk.Button(frame_btns, text="Copiar Semana Passada", command=lambda: executar_copia(data_semana_str))
        btn_semana.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, ipady=5)

    def redesenhar_marcadores(self):
        if not self.data_selecionada:
            return
        self.canvas.delete("marcador")
        self.canvas.delete("texto_marcador")
        self.canvas.delete("setor_tag")

        dia_db = dia_semana_banco(datetime.strptime(self.data_selecionada, '%Y-%m-%d').date())
        # Folga de todos os funcionários lida uma vez (o mapa redesenha várias vezes por segundo)
        funcionarios = getattr(self, '_funcionarios_cache', None)
        if funcionarios is None:
            funcionarios = self._funcionarios_cache = list(database.listar_funcionarios())
        mapa_folgas = {f.FuncionarioID: folga_do_funcionario(f) for f in funcionarios}
        cache_padrao = self.__dict__.setdefault('_posicao_padrao_cache', {})

        # Captura o tamanho atual do canvas para renderização responsiva
        W = self.canvas.winfo_width() if self.canvas.winfo_width() > 1 else MAPA_IMAGEM_LARGURA
        H = self.canvas.winfo_height() if self.canvas.winfo_height() > 1 else MAPA_IMAGEM_ALTURA
        self._registrar_tamanho_mapa(W, H)

        for pos in self.posicoes:
            pos_id, nome, coord_x_db, coord_y_db, _, setor = pos
            # Valor > 1 = pixel fixo (legado); <= 1 = proporção da área do mapa (novo)
            try:
                val_x, val_y = float(coord_x_db), float(coord_y_db)
                x, y = (val_x, val_y) if val_x > 1.0 else (val_x * W, val_y * H)
            except (ValueError, TypeError):
                continue  # coordenadas corrompidas no banco

            lista_turnos = self.escala_atual.get(pos_id, [])
            fixo = None
            if not lista_turnos and not self.modo_edicao:
                if pos_id not in cache_padrao:
                    cache_padrao[pos_id] = database.buscar_funcionarios_com_posicao_padrao(pos_id)
                fixo = cache_padrao[pos_id]
            # [GESTÃO WEB] cor e texto vêm de escala_regras (a Web mostra igual)
            cor, linhas = rotulo_e_cor_posicao(nome, lista_turnos, mapa_folgas, self._indisponivel_no_dia,
                                               dia_db, fixo, self.modo_edicao)
            label_final = "\n".join(linhas)
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

    def _registrar_tamanho_mapa(self, largura, altura):
        """
        [GESTÃO WEB] As posições novas são guardadas em PROPORÇÃO da área do mapa desta janela.
        A versão Web precisa saber esse tamanho para pôr as bolinhas no mesmo lugar: grava no
        banco (só quando o tamanho muda e fica parado 2 segundos).
        """
        if largura < 300 or altura < 200:
            return
        # Com o painel lateral aberto a área do mapa fica mais estreita: guarda só a visão normal
        if self.frame_lateral.winfo_ismapped():
            return
        if getattr(self, '_tamanho_mapa_gravado', None) == (largura, altura):
            return
        if getattr(self, '_id_tamanho_mapa', None):
            try:
                self.root.after_cancel(self._id_tamanho_mapa)
            except Exception:
                pass

        def gravar():
            self._id_tamanho_mapa = None
            try:
                # confere de novo na hora de gravar (o painel pode ter aberto nesses 2 segundos)
                if self.frame_lateral.winfo_ismapped():
                    return
                larg, alt = self.canvas.winfo_width(), self.canvas.winfo_height()
                if larg < 300 or alt < 200 or getattr(self, '_tamanho_mapa_gravado', None) == (larg, alt):
                    return
                if database.registrar_tamanho_mapa_escala(larg, alt):
                    self._tamanho_mapa_gravado = (larg, alt)
            except Exception as e:
                logger.warning(f"Não deu para guardar o tamanho do mapa: {e}")
        self._id_tamanho_mapa = self.root.after(2000, gravar)

    @staticmethod
    def _parse_horario_seguro(valor):
        """Converte string, datetime, time ou timedelta para time (escala_regras.parse_horario)."""
        return parse_horario(valor)

    @staticmethod
    def _aplicar_mascara_hora(event):
        """
        Formata automaticamente um campo de entrada para o padrão HH:MM
        enquanto o usuário digita. Ignora teclas de navegação/deleção para não travar o cursor.
        """
        # Se apertou Backspace, Delete ou setinhas, não faz nada para permitir correção
        if event.keysym in ('BackSpace', 'Delete', 'Left', 'Right', 'Up', 'Down', 'Tab'):
            return

        widget = event.widget
        # Remove qualquer coisa que não seja dígito (ex: letras, ou os próprios dois pontos)
        texto_limpo = ''.join(filter(str.isdigit, widget.get()))

        # Limita a apenas 4 números
        if len(texto_limpo) > 4:
            texto_limpo = texto_limpo[:4]

        # Injeta os dois pontos se já tivermos 3 ou mais dígitos (ex: "080" vira "08:0")
        nova_string = texto_limpo
        if len(texto_limpo) >= 3:
            nova_string = f"{texto_limpo[:2]}:{texto_limpo[2:]}"

        # Só atualiza a caixa de texto se a string formatada for diferente da atual
        if widget.get() != nova_string:
            widget.delete(0, tk.END)
            widget.insert(0, nova_string)

    def atualizar_grafico_fluxo(self):
            """Calcula a ocupação hora a hora, filtrando por setor e descontando intervalos."""
            self.ax.clear()

            # 1. Captura o setor selecionado no filtro
            setor_filtro = self.combo_setor_grafico.get()
            if not setor_filtro: setor_filtro = SETOR_TODOS

            # Busca dados brutos (Ent, Sai, IntIni, IntFim, Setor)
            horarios = database.buscar_horarios_ocupacao_hoje(self.data_selecionada, 0)
            horas_eixo = HORAS_FLUXO  # 07:00 as 23:00
            # [GESTÃO WEB] mesma conta da Web (escala_regras.fluxo_por_hora)
            contagem_por_hora = fluxo_por_hora(horarios, setor_filtro)

            # Desenha o gráfico
            # Cores dinâmicas: Se selecionar um setor específico, usa azul. Se for Geral, usa a lógica verde/vermelho.
            if setor_filtro == SETOR_TODOS:
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
        setores = SETORES_MAPA
        combo_setor = ttk.Combobox(popup, values=setores, state="readonly")
        combo_setor.pack(pady=5)

        # Carrega o setor atual, se houver
        if dados_pos[5]: 
            combo_setor.set(dados_pos[5])

        def salvar_cfg():
            novo_nome = entry_nome.get().strip()
            novo_setor = combo_setor.get() or None
            # [DEPURAÇÃO] Nome vazio era ignorado em silêncio e falhas do banco não apareciam.
            if not novo_nome:
                messagebox.showwarning("Aviso", "O nome da posição não pode ficar vazio.", parent=popup)
                return
            if database.atualizar_dados_posicao(pos_id, novo_nome, novo_setor):
                self.carregar_escala_do_dia()
                popup.destroy()
            else:
                messagebox.showerror("Erro", "Não foi possível salvar a posição no banco.", parent=popup)

        def excluir_cfg():
            # [DEPURAÇÃO] O aviso dizia que o histórico seria apagado, mas a posição é apenas
            # DESATIVADA (some do mapa; as escalas antigas continuam guardadas).
            if messagebox.askyesno("Excluir", "Remover esta posição do mapa?\n\nAs escalas antigas continuam guardadas no histórico.", parent=popup):
                if database.excluir_posicao_loja(pos_id):
                    self.carregar_escala_do_dia()
                    popup.destroy()
                else:
                    messagebox.showerror("Erro", "Não foi possível remover a posição.", parent=popup)

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
        combo_setor = ttk.Combobox(popup, values=SETORES_MAPA)
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

            if nome and nome.strip():
                # PERSISTÊNCIA: Agora guardamos o valor relativo (EX: 0.4567) em vez de pixels (EX: 540)
                if database.criar_posicao_loja(nome.strip(), rel_x, rel_y, setor_limpo):
                    self.carregar_escala_do_dia()
                    popup.destroy()
                else:
                    messagebox.showerror("Erro", "Não foi possível criar a posição no banco.", parent=popup)
            else:
                messagebox.showwarning("Aviso", "Digite um nome para a posição.", parent=popup)

        ttk.Button(popup, text="Criar", command=confirmar).pack(pady=10)

    # --- INTEGRAÇÃO COM O CÉREBRO (CALCULADORA) ---
    def gerar_intervalos(self):
        """
        Calcula os intervalos automaticamente (calculadora_logica) e grava no banco.

        [DEPURAÇÃO] Correções:
        - A calculadora identifica cada pessoa pelo campo 'id_posicao'. Antes era passado
          o ID da POSIÇÃO: se a mesma posição tivesse 2 turnos no dia (manhã e noite),
          o intervalo do 2º SOBRESCREVIA o do 1º, e ao salvar os DOIS turnos recebiam o
          mesmo horário. Agora é passado o ID do TURNO (EscalaID), único por pessoa.
        - Turnos que viram a meia-noite (ex.: 18:00 às 02:00) tinham saída "antes" da
          entrada e a duração dava negativa. Agora a saída passa para o dia seguinte.
        - Se nenhuma sugestão fosse gerada, a variável 'count_aplicados' não existia e a
          função quebrava com erro no final.
        - A gravação agora é feita por turno, numa única transação (tudo ou nada).
        """
        if not self.data_selecionada:
            messagebox.showwarning("Aviso", "Selecione uma data primeiro.", parent=self.root)
            return

        # 1. Coleta dados da tela e do banco
        dia_obj = self.date_entry.get_date()
        # Converter isoweekday (Seg=1...Dom=7) para o padrão do Banco (Dom=1...Sab=7)
        dia_iso = dia_semana_banco(dia_obj)
        # [GESTÃO WEB] mesmo preparo da Web (escala_regras.pessoas_para_intervalos)
        pessoas_para_calcular, dados_por_turno = pessoas_para_intervalos(self.escala_atual, self.posicoes, dia_obj)

        if not pessoas_para_calcular:
            messagebox.showwarning("Vazio", "Não há funcionários escalados com horário de entrada/saída para calcular.", parent=self.root)
            return

        # [AUDITORIA ESCALA] O cálculo SUBSTITUI os intervalos já digitados à mão, sem avisar.
        ja_tem = [d for d in dados_por_turno.values() if d.InicioIntervalo and d.FimIntervalo]
        if ja_tem and not messagebox.askyesno(
                "Substituir intervalos?",
                f"{len(ja_tem)} turno(s) deste dia já têm intervalo (alguns podem ter sido ajustados à mão).\n\n"
                "O cálculo automático vai SUBSTITUIR esses intervalos.\n\nContinuar?", icon='warning', parent=self.root):
            return

        # 2. Chama o Cérebro Lógico
        try:
            sugestoes, erros = calculadora_logica.calcular_intervalos_automaticos(pessoas_para_calcular, dia_iso)
        except Exception as e:
            logger.exception(f"Falha na calculadora de intervalos: {e}")
            messagebox.showerror("Erro de Cálculo", f"Falha na calculadora lógica: {e}", parent=self.root)
            return

        # 3. Texto do resultado (vai para o painel de alertas depois de recarregar o dia)
        # [AUDITORIA ESCALA] Antes este texto era escrito no painel e logo em seguida APAGADO
        # pelo recarregamento do dia. Agora ele aparece junto com os alertas da escala.
        texto_erros = ("🪄 Intervalos automáticos:\n" + "\n".join(erros)) if erros else "🪄 Intervalos automáticos: cálculo concluído sem conflitos."

        # 4. Grava as sugestões (uma por turno, tudo ou nada)
        count_aplicados = 0
        if sugestoes:
            if self._salvar_intervalos_por_turno(sugestoes):
                count_aplicados = len(sugestoes)
            else:
                messagebox.showerror("Erro Crítico", "Falha ao gravar os intervalos. Nenhuma alteração foi salva.", parent=self.root)
                return

        self.carregar_escala_do_dia()
        self.mostrar_alertas_do_dia(extra=texto_erros, cor_extra="#c62828" if erros else None)

        if count_aplicados == 0:
            messagebox.showwarning("Nenhum intervalo", "Nenhum intervalo pôde ser agendado automaticamente.\nVeja o motivo nos alertas do rodapé.", parent=self.root)
        elif erros:
            messagebox.showwarning("Atenção", f"{count_aplicados} intervalos agendados, mas houve conflitos!\nVerifique os alertas no rodapé.", parent=self.root)
        else:
            messagebox.showinfo("Sucesso", f"{count_aplicados} intervalos agendados com sucesso!", parent=self.root)

    def _salvar_intervalos_por_turno(self, sugestoes):
        """Grava {EscalaID: (inicio, fim)} numa única transação (escala_regras.gravar_intervalos)."""
        return gravar_intervalos(sugestoes)

    def enviar_escala_telegram(self):
        if not self.data_selecionada: return

        resposta = messagebox.askyesno("Confirmar Envio",
            f"Deseja enviar a escala do dia {fmt_data_br(self.data_selecionada, True)} para o grupo TODOS OS FUNCIONÁRIOS no Telegram?",
            parent=self.root)

        if resposta:
            # Desabilita o botão para evitar cliques múltiplos
            self.btn_telegram.config(state='disabled', text="Enviando...")

            data_snapshot = self.data_selecionada  # [DEPURAÇÃO] a data não muda se o usuário mexer no calendário durante o envio

            def tarefa_background():
                try:
                    texto_escala = database.gerar_relatorio_escala_texto(data_snapshot)
                    # [DEPURAÇÃO] Em caso de problema, a função do banco devolve um TEXTO de erro
                    # ("Erro de conexão.", "Nenhuma escala definida..."), que era enviado ao grupo
                    # de TODOS os funcionários como se fosse a escala.
                    if not texto_escala or texto_escala.startswith(("Erro", "Nenhuma escala")):
                        raise RuntimeError(texto_escala or "Escala vazia.")

                    resposta = notificador_telegram.enviar_mensagem(config.TODOS_FUNCIONARIOS_GROUP_ID, texto_escala)
                    # [DEPURAÇÃO] Antes dizia "Sucesso" mesmo quando o Telegram recusava a mensagem.
                    if not (resposta and resposta.get('ok')):
                        raise RuntimeError(f"O Telegram recusou o envio: {resposta}")

                    # Sucesso: Reabilita botão e avisa
                    self.root.after(0, lambda: self._finalizar_envio_telegram(True))
                except Exception as e:
                    # Erro: Reabilita botão e avisa erro
                    erro_txt = str(e)  # [DEPURAÇÃO] guarda o texto: 'e' deixa de existir quando o 'except' termina
                    logger.error(f"Falha ao enviar escala ao Telegram: {erro_txt}")
                    self.root.after(0, lambda: self._finalizar_envio_telegram(False, erro_txt))

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
            self.status("Escala enviada para o grupo do Telegram! ✅")
        else:
            messagebox.showerror("Erro", f"Falha ao enviar Telegram: {erro_msg}", parent=self.root)

    # --- NOVO: Envio em Massa WhatsApp ---
    def enviar_confirmacoes_em_massa(self):
        if not self.data_selecionada: return

        # Snapshot (Cópia de segurança) para evitar conflito se o usuário mudar a data na tela
        data_snapshot = self.data_selecionada
        escala_dia = database.buscar_escala_do_dia(data_snapshot)
        # [GESTÃO WEB] mesma lista da Web (escala_regras.lista_envio_whatsapp)
        lista_envio = lista_envio_whatsapp(escala_dia, self.posicoes)

        if not lista_envio:
            messagebox.showwarning("Aviso", "Nenhuma pessoa com telefone encontrada na escala deste dia.", parent=self.root)
            return

        # 2. Confirmação
        if not messagebox.askyesno("Confirmação em Massa", 
            f"Encontradas {len(lista_envio)} pessoas com telefone na escala.\n\n"
            "Deseja enviar a confirmação de horário individual para o WhatsApp de cada um via BOT?\n\n"
            "⚠️ Isso pode levar alguns segundos.", parent=self.root):
            return

        # 3. Execução em Thread (Background)
        self.btn_wpp_mass.config(state='disabled', text="Enviando...")

        def run_envio():
            # [GESTÃO WEB] mensagens e diretriz do setor iguais às da Web (escala_regras)
            enviados, erros = enviar_confirmacoes_whatsapp(
                lista_envio, data_snapshot, notificador_whatsapp.enviar_mensagem_whatsapp,
                database.buscar_descricao_setor)
            self.root.after(0, lambda: self._finalizar_envio_wpp(enviados, erros))

        threading.Thread(target=run_envio, daemon=True).start()

    def _finalizar_envio_wpp(self, enviados, erros):
        self.btn_wpp_mass.config(state='normal', text="📱 Confirmar Escala (WhatsApp)")
        msg = f"Processo finalizado!\n\n✅ Enviados: {enviados}\n❌ Falhas: {erros}"
        if erros > 0:
            messagebox.showwarning("Relatório de Envio", msg, parent=self.root)
        else:
            self.status(f"WhatsApp: {enviados} confirmação(ões) enviada(s). ✅")

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
                # [DEPURAÇÃO] A coluna DuracaoJornadaPadrao do banco é INT (número inteiro).
                # '8:20' virava 8,33 e o banco guardava só 8, sem avisar. Agora o usuário é avisado.
                if jornada != int(jornada):
                    if not messagebox.askyesno(
                        "Jornada fracionada",
                        f"O banco guarda a jornada apenas em HORAS INTEIRAS.\n\n{jornada_str} será salvo como {int(jornada)}h.\n\nDeseja continuar?",
                        parent=popup):
                        return
                    jornada = int(jornada)

                if database.atualizar_configuracoes_escala(None, None, max_horas, duracao, jornada):
                    self._config_escala_cache = None  # [DEPURAÇÃO] força reler a jornada nova
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
        nomes_dias = {}  # [DEPURAÇÃO] mensagens de erro mostram "Sábado" em vez de "Dia 7"
        
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
            nomes_dias[dia_id] = nome_dia

        # 3. Função de Salvamento
        def salvar_picos():
            erros = []
            sucessos = 0
            
            for dia_id, (entry_ini, entry_fim) in campos_pico.items():
                nome_dia = nomes_dias.get(dia_id, f"Dia {dia_id}")
                # [DEPURAÇÃO] A validação antiga aceitava horários impossíveis como 25:99,
                # e aceitava só o início ou só o fim (o pico nunca era aplicado).
                try:
                    h_ini = hora_ou_none(entry_ini.get())
                except ValueError:
                    erros.append(f"{nome_dia} (Início): use HH:MM entre 00:00 e 23:59.")
                    continue
                try:
                    h_fim = hora_ou_none(entry_fim.get())
                except ValueError:
                    erros.append(f"{nome_dia} (Fim): use HH:MM entre 00:00 e 23:59.")
                    continue
                if bool(h_ini) != bool(h_fim):
                    erros.append(f"{nome_dia}: preencha início E fim (ou deixe os dois vazios).")
                    continue

                if database.atualizar_pico_diario(dia_id, h_ini, h_fim):
                    sucessos += 1
                else:
                    erros.append(f"{nome_dia}: Falha de escrita no banco.")
            
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
            self.btn_modo.config(text="🔧 Configurar Mapa (Setores)")
            self.lbl_legenda.config(text="Modo: ESCALAÇÃO", foreground="green")
            self.carregar_escala_do_dia()

    def abrir_gestao_freelancers(self):
        """Abre uma janela para listar, criar e editar freelancers."""
        popup = Toplevel(self.root)
        popup.title("Gerenciar Freelancers")
        popup.geometry("720x450")
        popup.transient(self.root)

        # --- Área de Lista ---
        frame_lista = ttk.Frame(popup, padding="10")
        frame_lista.pack(fill=tk.BOTH, expand=True)

        cols = ('ID', 'Nome', 'Telefone', 'A pagar')
        tree = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')
        tree.heading('ID', text='ID'); tree.column('ID', width=40, anchor='center')
        tree.heading('Nome', text='Nome'); tree.column('Nome', width=200)
        tree.heading('Telefone', text='Telefone'); tree.column('Telefone', width=150, anchor='center')
        # [MELHORIA ESCALA] quanto falta pagar a cada freelancer (turnos até hoje)
        tree.heading('A pagar', text='A pagar (até hoje)'); tree.column('A pagar', width=170, anchor='e')
        tree.tag_configure('deve', foreground='#b26a00')
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(frame_lista, orient="vertical", command=tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=sb.set)

        def carregar_lista():
            for i in tree.get_children(): tree.delete(i)
            frees = database.listar_freelancers() # Reusa função existente
            try:
                pendentes = database.total_pendente_por_freelancer()
            except Exception as e:
                logger.warning(f"Não foi possível somar o que falta pagar: {e}")
                pendentes = {}
            for f in frees:
                qtd, total = pendentes.get(f.FreelancerID, (0, Decimal('0')))
                a_pagar = f"{fmt_reais(total)} ({qtd} turno{'s' if qtd != 1 else ''})" if qtd else "—"
                tree.insert("", "end", values=(f.FreelancerID, f.Nome, f.Telefone, a_pagar),
                            tags=('deve',) if qtd else ())

        def novo():
            nome = simpledialog.askstring("Novo", "Nome Completo:", parent=popup)
            if nome and nome.strip():
                tel = simpledialog.askstring("Contato", "Telefone (WhatsApp) com DDD:", parent=popup)
                if tel and tel.strip():
                    # [DEPURAÇÃO] Um erro de banco aqui fechava a ação sem nenhum aviso.
                    try:
                        criado = database.criar_freelancer(nome.strip(), tel.strip())
                    except Exception as e:
                        logger.exception(f"Erro ao cadastrar freelancer: {e}")
                        criado = False
                    if criado:
                        carregar_lista()
                        messagebox.showinfo("Sucesso", "Freelancer cadastrado!", parent=popup)
                    else:
                        messagebox.showerror("Erro", "Não foi possível cadastrar o freelancer.", parent=popup)
        # --- NOVA FUNÇÃO: Excluir Freelancer ---
        def excluir():
            selecionado = tree.focus()
            if not selecionado: 
                messagebox.showwarning("Aviso", "Selecione um freelancer na lista para excluir.", parent=popup)
                return
            
            f_id = tree.item(selecionado, 'values')[0]
            f_nome = tree.item(selecionado, 'values')[1]

            a_pagar = tree.item(selecionado, 'values')[3] if len(tree.item(selecionado, 'values')) > 3 else "—"
            aviso = (f"\n\n⚠️ Ainda falta pagar {a_pagar} a este freelancer! Excluindo, esses turnos somem "
                     "da lista de pagamentos (os já PAGOS continuam registrados).") if a_pagar != "—" else ""
            if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o freelancer {f_nome}?\n\nIsso limpará todas as escalas onde ele estiver.{aviso}", parent=popup):
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
            f_id, f_nome, f_tel = dados[0], dados[1], dados[2]

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
        # [DEPURAÇÃO] A função excluir() existia, mas o BOTÃO nunca foi criado:
        # não havia como excluir um freelancer pela tela.
        ttk.Button(frame_btns, text="🗑️ Excluir Selecionado", command=excluir).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        def ver_pagamentos():
            sel = tree.focus()
            fid = int(tree.item(sel, 'values')[0]) if sel else None
            self.abrir_pagamentos_freelancers(freelancer_id=fid)
        # [MELHORIA ESCALA]
        ttk.Button(frame_btns, text="💰 Pagamentos", command=ver_pagamentos).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        tree.bind("<Double-1>", lambda e: editar())
        self._janela_freelancers = {'popup': popup, 'tree': tree, 'carregar': carregar_lista}

        # Carrega dados iniciais
        carregar_lista()


    def _construir_painel_lateral(self):
        """Monta a interface gráfica do painel lateral fixo (criado apenas uma vez)."""
        # Lista (Treeview)
        cols = ('ID', 'Nome', 'Ent', 'Sai')
        self.tree_lateral = ttk.Treeview(self.frame_lateral, columns=cols, show='headings', height=4)
        self.tree_lateral.heading('ID', text='ID'); self.tree_lateral.column('ID', width=30)
        self.tree_lateral.heading('Nome', text='Nome'); self.tree_lateral.column('Nome', width=160)
        self.tree_lateral.heading('Ent', text='Ent'); self.tree_lateral.column('Ent', width=60, anchor='center')
        self.tree_lateral.heading('Sai', text='Sai'); self.tree_lateral.column('Sai', width=60, anchor='center')
        self.tree_lateral.pack(fill=tk.X, padx=10, pady=10)
        self.tree_lateral.bind("<<TreeviewSelect>>", self._carregar_edicao_lateral)

        # Variáveis de Estado
        self.var_escala_id_edit = tk.StringVar()
        self.var_ent_lateral = tk.StringVar(value="08:00")
        self.var_sai_lateral = tk.StringVar()

        # Formulário
        ttk.Label(self.frame_lateral, text="Funcionário / Freelancer:").pack(anchor="w", padx=10)
        self.combo_pessoas_lateral = ttk.Combobox(self.frame_lateral, state="readonly")
        self.combo_pessoas_lateral.pack(fill=tk.X, padx=10, pady=2)

        frame_h = ttk.Frame(self.frame_lateral)
        frame_h.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(frame_h, text="Entrada:").pack(side=tk.LEFT)
        self.e_ent_lat = ttk.Entry(frame_h, textvariable=self.var_ent_lateral, width=8)
        self.e_ent_lat.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_h, text="Saída:").pack(side=tk.LEFT)
        self.e_sai_lat = ttk.Entry(frame_h, textvariable=self.var_sai_lateral, width=8)
        self.e_sai_lat.pack(side=tk.LEFT, padx=5)

        ttk.Label(self.frame_lateral, text="Intervalo (Início - Fim):").pack(anchor="w", padx=10)
        frame_i = ttk.Frame(self.frame_lateral)
        frame_i.pack(fill=tk.X, padx=10, pady=2)
        self.e_int_ini_lat = ttk.Entry(frame_i, width=8)
        self.e_int_ini_lat.pack(side=tk.LEFT, padx=(0,5))
        self.e_int_fim_lat = ttk.Entry(frame_i, width=8)
        self.e_int_fim_lat.pack(side=tk.LEFT)

        # [DIÁRIA NA ESCALA] Freelancer: o gestor escolhe a diária (fica gravada no turno e
        # é a que o pagamento usa). Já vem marcada a sugestão pela duração do turno.
        self.var_tipo_diaria = tk.StringVar(value="")
        self._tipo_diaria_manual = False
        self.frame_diaria_lat = ttk.Frame(self.frame_lateral)
        ttk.Label(self.frame_diaria_lat, text="Diária do freelancer:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        self.rb_curta_lat = ttk.Radiobutton(self.frame_diaria_lat, text="Curta", value="curta",
                                            variable=self.var_tipo_diaria, command=self._escolheu_tipo_diaria)
        self.rb_curta_lat.pack(side=tk.LEFT, padx=(8, 4))
        self.rb_longa_lat = ttk.Radiobutton(self.frame_diaria_lat, text="Longa", value="longa",
                                            variable=self.var_tipo_diaria, command=self._escolheu_tipo_diaria)
        self.rb_longa_lat.pack(side=tk.LEFT, padx=4)

        # [MELHORIA ESCALA] Prévia do pagamento quando a pessoa é freelancer
        self.lbl_pag_lateral = tk.Label(self.frame_lateral, text="", fg="#1b5e20", justify=tk.LEFT,
                                        anchor="w", wraplength=340, font=("Arial", 9, "bold"))
        self.lbl_pag_lateral.pack(fill=tk.X, padx=10, pady=(4, 2))

        ttk.Label(self.frame_lateral, text="Foco do Dia:").pack(anchor="w", padx=10)
        self.txt_foco_lateral = tk.Text(self.frame_lateral, height=3)
        self.txt_foco_lateral.pack(fill=tk.X, padx=10, pady=2)

        # Binds (Máscaras de Horário e Auto-cálculo)
        self.e_ent_lat.bind('<KeyRelease>', self._aplicar_mascara_hora)
        self.e_sai_lat.bind('<KeyRelease>', self._aplicar_mascara_hora)
        self.e_int_ini_lat.bind('<KeyRelease>', self._aplicar_mascara_hora)
        self.e_int_fim_lat.bind('<KeyRelease>', self._aplicar_mascara_hora)
        self.var_ent_lateral.trace_add("write", self._calcular_saida_lateral)
        # [MELHORIA ESCALA] prévia do valor do freelancer + Enter salva
        self.var_ent_lateral.trace_add("write", self._previa_pagamento_lateral)
        self.var_sai_lateral.trace_add("write", self._previa_pagamento_lateral)
        self.combo_pessoas_lateral.bind("<<ComboboxSelected>>", self._previa_pagamento_lateral)
        for campo in (self.e_ent_lat, self.e_sai_lat, self.e_int_ini_lat, self.e_int_fim_lat):
            campo.bind("<Return>", lambda e: self._salvar_lateral())

        # Botões
        frame_btn = ttk.Frame(self.frame_lateral)
        frame_btn.pack(fill=tk.X, side=tk.BOTTOM, pady=15, padx=10)

        ttk.Button(frame_btn, text="✨ Limpar", command=self._limpar_form_lateral).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(frame_btn, text="🗑️ Excluir", command=self._excluir_lateral).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self.btn_salvar_lat = ttk.Button(frame_btn, text="✅ Salvar", command=self._salvar_lateral)
        self.btn_salvar_lat.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        ttk.Button(self.frame_lateral, text="❌ Fechar Painel", command=self.frame_lateral.pack_forget).pack(side=tk.BOTTOM, fill=tk.X, padx=10)

    # --- LÓGICA DO PAINEL LATERAL ---

    def _previa_pagamento_lateral(self, *args):
        """[MELHORIA ESCALA] Mostra quanto o freelancer vai receber por este turno."""
        if not hasattr(self, 'lbl_pag_lateral'):
            return
        d = self.mapa_ids_lateral.get(self.combo_pessoas_lateral.get())
        if not d or d.get('tipo') != 'free':
            self.lbl_pag_lateral.config(text="")
            self.frame_diaria_lat.pack_forget()
            return
        if not self.frame_diaria_lat.winfo_ismapped():
            self.frame_diaria_lat.pack(fill=tk.X, padx=10, pady=(4, 0), before=self.lbl_pag_lateral)
        self._sugerir_tipo_diaria()
        calc = self._calcular_turno_free(self.var_ent_lateral.get(), self.var_sai_lateral.get(),
                                         tipo=self.var_tipo_diaria.get() or None)
        if not calc:
            self.lbl_pag_lateral.config(text="💰 Preencha entrada e saída para ver o valor.", fg="gray")
            return
        texto = "💰 " + texto_calculo(calc)
        escala_id = self.var_escala_id_edit.get()
        if escala_id and int(escala_id) in database.turnos_pagos([escala_id]):
            texto += "   ✅ JÁ PAGO"
        self.lbl_pag_lateral.config(text=texto, fg="#1b5e20")

    def _escolheu_tipo_diaria(self):
        """[DIÁRIA NA ESCALA] O gestor clicou em Curta/Longa: a sugestão automática não muda mais."""
        self._tipo_diaria_manual = True
        self._previa_pagamento_lateral()

    def _sugerir_tipo_diaria(self):
        """Enquanto o gestor não escolher, marca Curta/Longa pela duração (mesma regra do pagamento)."""
        if self._tipo_diaria_manual:
            return
        faixa = faixa_turno(self.var_ent_lateral.get(), self.var_sai_lateral.get())
        if faixa is None:
            return
        limite = int(self._config_pagamento().get('LimiteCurtaMinutos', 420))
        self.var_tipo_diaria.set('curta' if faixa[1] - faixa[0] <= limite else 'longa')

    def _calcular_saida_lateral(self, *args):
        # [DEPURAÇÃO] Antes o banco era consultado a CADA tecla digitada no campo Entrada.
        # Agora a configuração é lida uma vez (e relida ao salvar as Configurações).
        if self._config_escala_cache is None:
            self._config_escala_cache = database.buscar_configuracoes_escala() or False
        config_db = self._config_escala_cache or None
        jornada = getattr(config_db, 'DuracaoJornadaPadrao', 8) or 8
        entrada = self.var_ent_lateral.get()
        if len(entrada) == 5 and re.match(r'^\d{2}:\d{2}$', entrada):
            try:
                dt_ent = datetime.strptime(entrada, '%H:%M')
                dt_sai = dt_ent + timedelta(hours=float(jornada))
                self.var_sai_lateral.set(dt_sai.strftime('%H:%M'))
            except ValueError: pass

    def _carregar_edicao_lateral(self, event):
        sel = self.tree_lateral.focus()
        if not sel: return
        item = self.tree_lateral.item(sel, 'values')
        escala_id = int(item[0])

        lista_turnos = self.escala_atual.get(self.pos_id_selecionada, [])
        turno = next((t for t in lista_turnos if t.EscalaID == escala_id), None)
        if not turno: return

        self.var_escala_id_edit.set(escala_id)
        tipo_gravado = getattr(turno, 'TipoDiaria', None)
        self._tipo_diaria_manual = tipo_gravado in ('curta', 'longa')
        self.var_tipo_diaria.set(tipo_gravado if self._tipo_diaria_manual else "")

        nome_combo = ""
        if turno.FuncionarioID:
            nome_combo = next((k for k, v in self.mapa_ids_lateral.items() if v['tipo'] == 'func' and v['id'] == turno.FuncionarioID), "")
        elif turno.FreelancerID:
            nome_combo = next((k for k, v in self.mapa_ids_lateral.items() if v['tipo'] == 'free' and v['id'] == turno.FreelancerID), "")
        self.combo_pessoas_lateral.set(nome_combo)

        fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5] if v else ""
        self.var_ent_lateral.set(fmt(turno.HorarioEntrada))
        self.var_sai_lateral.set(fmt(turno.HorarioSaida))
        self.e_int_ini_lat.delete(0, tk.END); self.e_int_ini_lat.insert(0, fmt(turno.InicioIntervalo))
        self.e_int_fim_lat.delete(0, tk.END); self.e_int_fim_lat.insert(0, fmt(turno.FimIntervalo))
        self.txt_foco_lateral.delete("1.0", tk.END); self.txt_foco_lateral.insert("1.0", turno.FocoDoDia or "")

        self.btn_salvar_lat.config(text="🔄 Atualizar")
        self._previa_pagamento_lateral()

    def _limpar_form_lateral(self):
        self._tipo_diaria_manual = False
        self.var_tipo_diaria.set("")
        self.var_escala_id_edit.set("")
        self.combo_pessoas_lateral.set("")
        self.var_ent_lateral.set("08:00")
        self.e_int_ini_lat.delete(0, tk.END); self.e_int_fim_lat.delete(0, tk.END)
        self.txt_foco_lateral.delete("1.0", tk.END)
        self.btn_salvar_lat.config(text="✅ Salvar")
        if hasattr(self, 'lbl_pag_lateral'):
            self.lbl_pag_lateral.config(text="")
        if self.tree_lateral.selection():
            self.tree_lateral.selection_remove(self.tree_lateral.selection())

    def _salvar_lateral(self):
        if not self.pos_id_selecionada: return
        selecao = self.combo_pessoas_lateral.get()
        if not selecao or selecao == "(Vazio)":
            messagebox.showwarning("Aviso", "Selecione um funcionário ou freelancer.", parent=self.root)
            return

        func_id = None; free_id = None
        d = self.mapa_ids_lateral.get(selecao)
        # [DEPURAÇÃO] Se a pessoa não estivesse no mapa, o turno era salvo SEM ninguém.
        if not d:
            messagebox.showwarning("Aviso", "Pessoa não encontrada na lista. Feche e abra a posição novamente.", parent=self.root)
            return
        if d['tipo'] == 'func': func_id = d['id']
        else: free_id = d['id']

        # [DEPURAÇÃO] Validação dos horários antes de ir ao banco.
        # Campos vazios viravam 00:00 no SQL Server (meia-noite).
        try:
            h_ent = hora_ou_none(self.var_ent_lateral.get())
            h_sai = hora_ou_none(self.var_sai_lateral.get())
            h_int_ini = hora_ou_none(self.e_int_ini_lat.get())
            h_int_fim = hora_ou_none(self.e_int_fim_lat.get())
        except ValueError as e:
            messagebox.showerror("Horário inválido", f"'{e}' não é um horário válido. Use HH:MM (ex.: 08:00).", parent=self.root)
            return
        if not h_ent or not h_sai:
            messagebox.showwarning("Aviso", "Preencha os horários de Entrada e Saída.", parent=self.root)
            return
        if bool(h_int_ini) != bool(h_int_fim):
            messagebox.showwarning("Aviso", "Preencha o início E o fim do intervalo (ou deixe os dois vazios).", parent=self.root)
            return

        escala_id = self.var_escala_id_edit.get()

        # [AUDITORIA ESCALA] Regras que antes não eram conferidas ao salvar:
        nome_pessoa = selecao.replace('[Fixo] ', '').replace('[Free] ', '').replace(' [FOLGA]', '')
        if h_ent == h_sai:
            messagebox.showwarning("Aviso", "Entrada e saída não podem ser iguais.", parent=self.root)
            return
        prob = problema_intervalo(h_ent, h_sai, h_int_ini, h_int_fim)
        if prob:
            messagebox.showwarning("Intervalo inválido", f"O {prob} ({h_ent} às {h_sai}).", parent=self.root)
            return
        # 1) a mesma pessoa em duas posições ao mesmo tempo (só era conferido dentro da MESMA posição)
        nomes_pos = {p[0]: p[1] for p in self.posicoes}
        pessoa = ('func', func_id) if func_id else ('free', free_id)
        erros, avisos = conflitos_ao_salvar(self.escala_atual, escala_id, pessoa, h_ent, h_sai, nome_pessoa, nomes_pos)
        if erros:
            messagebox.showerror("Conflito de horário", "\n".join(erros) + "\n\nAjuste os horários ou escolha outra pessoa.", parent=self.root)
            return
        # 2) escalar quem está de folga/férias: a etiqueta [FOLGA] aparecia, mas salvava sem perguntar
        turno_antigo = next((t for lista in self.escala_atual.values() for t in lista
                             if escala_id and str(t.EscalaID) == str(escala_id)), None)
        pessoa_mudou = turno_antigo is None or chave_pessoa(turno_antigo) != pessoa
        motivo = self._motivo_indisponivel(func_id) if (func_id and pessoa_mudou) else None
        if motivo and not messagebox.askyesno(
                "Funcionário indisponível",
                f"{nome_pessoa}: {str(motivo).replace('⚠️', '').strip()}\n\nEscalar mesmo assim?", icon='warning', parent=self.root):
            return
        # 3) jornada do dia acima de 10h
        if avisos and not messagebox.askyesno("Jornada longa", "\n".join(avisos) + "\n\nSalvar mesmo assim?",
                                              icon='warning', parent=self.root):
            return
        # [MELHORIA ESCALA] turno de freelancer já PAGO: avisa que o pagamento não muda sozinho
        if escala_id and database.turnos_pagos([escala_id]):
            if not messagebox.askyesno(
                    "Turno já pago",
                    "Este turno de freelancer já foi marcado como PAGO.\n\n"
                    "Mudar a escala NÃO altera o valor pago (fica registrado como foi pago).\n"
                    "Se precisar refazer o valor, use '💰 Pagamentos' → '↩️ Desfazer pagamento'.\n\n"
                    "Salvar a alteração na escala mesmo assim?", icon='warning', parent=self.root):
                return

        if database.salvar_escala_dia_v3(
            escala_id if escala_id else None,
            self.data_selecionada, self.pos_id_selecionada, func_id, free_id,
            h_ent, h_sai, h_int_ini, h_int_fim,
            self.txt_foco_lateral.get("1.0", tk.END).strip()
        ):
            self.carregar_escala_do_dia()
            aviso_diaria = ""
            if free_id:
                # [DIÁRIA NA ESCALA] grava Curta/Longa no turno (o pagamento usa esta escolha)
                tipo = self.var_tipo_diaria.get() or None
                eid = int(escala_id) if escala_id else next((t.EscalaID for t in self.escala_atual.get(self.pos_id_selecionada, [])
                                         if t.FreelancerID == free_id and formatar_hora_curta(t.HorarioEntrada) == h_ent), None)
                if eid:
                    ok_tipo, msg_tipo = database.definir_tipo_diaria_escala(eid, tipo)
                    if ok_tipo:
                        aviso_diaria = f", diária {tipo}" if tipo else ""
                        self.carregar_escala_do_dia()
                    else:
                        aviso_diaria = f" ({msg_tipo})"
            self.abrir_janela_escalacao(self.pos_id_selecionada) # Recarrega a lista lateral em tempo real
            self.status(f"Turno de {nome_pessoa} salvo ({h_ent}–{h_sai}{aviso_diaria}).")
        else:
            messagebox.showerror("Erro", "Não foi possível salvar.\n\nProvável conflito de horário com outro turno desta posição (ou falha no banco).", parent=self.root)

    def _excluir_lateral(self):
        sel = self.tree_lateral.focus()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione um turno na lista para excluir.", parent=self.root)
            return

        item = self.tree_lateral.item(sel, 'values')
        escala_id = item[0]
        nome_pessoa = item[1]

        aviso_pago = ""
        if database.turnos_pagos([escala_id]):   # [MELHORIA ESCALA]
            aviso_pago = ("\n\n⚠️ Este turno já foi PAGO. O pagamento continua registrado em "
                          "'💰 Pagamentos' (marcado como 'turno excluído').")
        if messagebox.askyesno("Confirmar Exclusão", f"Remover a escalação de {nome_pessoa}?{aviso_pago}", parent=self.root):
            if database.excluir_turno_escala(escala_id):
                self.carregar_escala_do_dia()
                self.abrir_janela_escalacao(self.pos_id_selecionada)
            else:
                messagebox.showerror("Erro", "Falha ao excluir o registro.", parent=self.root)

    def abrir_janela_escalacao(self, pos_id):
        """Nova versão: Apenas injeta os dados no painel lateral em vez de abrir um Pop-up!"""
        try:
            dados_pos = next((p for p in self.posicoes if p[0] == pos_id), None)
            if not dados_pos: return
            nome_pos = dados_pos[1]
        except StopIteration: return 

        self.pos_id_selecionada = pos_id

        # Exibe o painel lateral e ajusta o título
        self.frame_lateral.config(text=f"Escalando: {nome_pos}")
        self.frame_lateral.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5) 

        self._limpar_form_lateral()
        self.tree_lateral.delete(*self.tree_lateral.get_children())

        # Carrega dados atuais da escala para a lista
        lista_turnos = self.escala_atual.get(pos_id, [])
        for t in lista_turnos:
            fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5] if v else ""
            nome_lista = t.NomePessoa or "?"
            if getattr(t, 'FreelancerID', None) and getattr(t, 'TipoDiaria', None) in ('curta', 'longa'):
                nome_lista += f" ({t.TipoDiaria})"
            self.tree_lateral.insert("", "end", values=(t.EscalaID, nome_lista, fmt(t.HorarioEntrada), fmt(t.HorarioSaida)))

        # Atualiza o dropdown de funcionários do banco de dados
        self.mapa_ids_lateral = {} 
        lista_nomes = ["(Vazio)"]

        # Descobre o dia da semana no padrão do banco (Dom=1, Seg=2... Sab=7)
        try:
            dia_obj = datetime.strptime(self.data_selecionada, '%Y-%m-%d')
            dia_semana_hoje = (dia_obj.isoweekday() % 7) + 1
        except Exception:
            dia_semana_hoje = -1

        for f in database.listar_funcionarios():
            # 1. Verifica Férias/Atestados/Afastamentos pelo banco
            indisponivel = self._indisponivel_no_dia(f.FuncionarioID)

            # 2. Verifica a Folga Fixa da semana
            folga_fixa = folga_do_funcionario(f)  # [DEPURAÇÃO] a coluna é 'DiaDeFolga', não 'DiaFolga'
            esta_de_folga = indisponivel or (folga_fixa is not None and folga_fixa == dia_semana_hoje)

            # Monta a etiqueta com o Alerta
            tag_aviso = " [FOLGA]" if esta_de_folga else ""
            label = f"[Fixo] {f.NomeCompleto}{tag_aviso}"

            lista_nomes.append(label)
            self.mapa_ids_lateral[label] = {'tipo': 'func', 'id': f.FuncionarioID, 'tel': getattr(f, 'TelefoneWhatsApp', '')} 

        for fr in database.listar_freelancers():
            label = f"[Free] {fr.Nome}"
            lista_nomes.append(label)
            self.mapa_ids_lateral[label] = {'tipo': 'free', 'id': fr.FreelancerID, 'tel': getattr(fr, 'Telefone', '')}

        self.combo_pessoas_lateral['values'] = lista_nomes    

    def abrir_gerenciador_intervalos(self):
        """
        Abre uma janela focada em lista para edição rápida de intervalos (Opção B).
        Agrupada visualmente por setor e ordenada por horário.
        """
        if not self.data_selecionada:
            messagebox.showwarning("Aviso", "Selecione uma data primeiro.")
            return

        # [DEPURAÇÃO] Guarda a data desta janela. Antes, se o gestor trocasse a data no
        # calendário com esta janela aberta, os intervalos eram gravados no DIA ERRADO.
        data_janela = self.data_selecionada

        popup = Toplevel(self.root)
        popup.title(f"Gerenciador de Intervalos - {datetime.strptime(data_janela, '%Y-%m-%d').strftime('%d/%m/%Y')}")
        popup.geometry("900x600")
        popup.transient(self.root)

        # --- Layout Principal ---
        frame_lista = ttk.Frame(popup)
        frame_lista.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

        frame_editor = ttk.LabelFrame(popup, text="Edição Rápida (Selecione acima)", padding="10")
        frame_editor.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        # --- Tabela (Treeview) ---
        cols = ('ID', 'Setor', 'Posição', 'Nome', 'Entrada', 'Saída', 'Início Int.', 'Fim Int.')
        tree = ttk.Treeview(frame_lista, columns=cols, show='headings', selectmode='browse')

        # Configuração das Colunas
        tree.heading('ID', text='ID'); tree.column('ID', width=0, stretch=tk.NO) # Oculto
        tree.heading('Setor', text='Setor'); tree.column('Setor', width=120)
        tree.heading('Posição', text='Posição'); tree.column('Posição', width=150)
        tree.heading('Nome', text='Funcionário'); tree.column('Nome', width=200)
        tree.heading('Entrada', text='Entrada'); tree.column('Entrada', width=80, anchor='center')
        tree.heading('Saída', text='Saída'); tree.column('Saída', width=80, anchor='center')
        tree.heading('Início Int.', text='Início Int.'); tree.column('Início Int.', width=100, anchor='center')
        tree.heading('Fim Int.', text='Fim Int.'); tree.column('Fim Int.', width=100, anchor='center')

        # Scrollbar
        sb = ttk.Scrollbar(frame_lista, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Tags para cores
        tree.tag_configure('definido', foreground='green')
        tree.tag_configure('pendente', foreground='red')
        tree.tag_configure('impar', background='#f0f0f0')

        # --- Controles do Rodapé (Editor) ---
        # Variáveis de controle
        var_id_escala = tk.StringVar()
        var_nome = tk.StringVar(value="Selecione alguém...")
        var_int_ini = tk.StringVar()
        var_int_fim = tk.StringVar()

        # Dados ocultos necessários para salvar (Ids, Horarios originais, etc)
        dados_ocultos = {} 

        # Layout do Editor
        frame_info = ttk.Frame(frame_editor)
        frame_info.pack(fill=tk.X, pady=(0, 10))

        lbl_info = ttk.Label(frame_info, textvariable=var_nome, font=("Arial", 11, "bold"), foreground="#0056b3")
        lbl_info.pack(anchor='w')

        frame_inputs = ttk.Frame(frame_editor)
        frame_inputs.pack(fill=tk.X)

        ttk.Label(frame_inputs, text="Início Intervalo (HH:MM):").pack(side=tk.LEFT)
        entry_ini = ttk.Entry(frame_inputs, textvariable=var_int_ini, width=10, font=("Arial", 11))
        entry_ini.pack(side=tk.LEFT, padx=5)

        ttk.Label(frame_inputs, text="Fim Intervalo (HH:MM):").pack(side=tk.LEFT, padx=(20, 0))
        entry_fim = ttk.Entry(frame_inputs, textvariable=var_int_fim, width=10, font=("Arial", 11))
        entry_fim.pack(side=tk.LEFT, padx=5)

        # [NOVO] Liga a máscara de auto-formatação aos campos de intervalo
        entry_ini.bind('<KeyRelease>', self._aplicar_mascara_hora)
        entry_fim.bind('<KeyRelease>', self._aplicar_mascara_hora)

        btn_salvar = ttk.Button(frame_inputs, text="✅ SALVAR (Enter)", command=lambda: salvar_alteracao())
        btn_salvar.pack(side=tk.LEFT, padx=20)

        # --- Funções Internas ---
        def carregar_dados():
            # Limpa e recarrega
            for i in tree.get_children(): tree.delete(i)

            dados = database.listar_escala_detalhada_ordenada(data_janela)

            for i, row in enumerate(dados):
                # Row: 0:EscalaID, 1:PosID, 2:Setor, 3:NomePos, 4:NomePessoa, 5:Ent, 6:Sai, 7:IniInt, 8:FimInt...
                escala_id = row[0]

                fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5] if v else ""

                ini_int = fmt(row[7])
                fim_int = fmt(row[8])

                tag_status = 'definido' if (ini_int and fim_int) else 'pendente'
                tag_bg = 'impar' if i % 2 else 'par'

                tree.insert("", "end", iid=str(escala_id), values=(
                    escala_id,
                    row[2], # Setor
                    row[3], # Posicao
                    row[4], # Nome
                    fmt(row[5]), # Ent
                    fmt(row[6]), # Sai
                    ini_int,
                    fim_int
                ), tags=(tag_status, tag_bg))

                # Guarda dados extras para o save
                dados_ocultos[str(escala_id)] = {
                    'pos_id': row[1],
                    'func_id': row[9],
                    'free_id': row[10],
                    'h_ent': fmt(row[5]),
                    'h_sai': fmt(row[6]),
                    'foco': row[11]
                }

        def ao_selecionar(event):
            sel = tree.focus()
            if not sel: return

            vals = tree.item(sel, 'values')
            # vals: 0:ID, 1:Setor, 2:Pos, 3:Nome, 4:Ent, 5:Sai, 6:Ini, 7:Fim

            var_id_escala.set(vals[0])
            var_nome.set(f"{vals[3]} ({vals[1]} - {vals[2]}) | Turno: {vals[4]} às {vals[5]}")
            var_int_ini.set(vals[6])
            var_int_fim.set(vals[7])

            entry_ini.focus_set()
            entry_ini.select_range(0, tk.END)

        def salvar_alteracao(event=None):
            escala_id = var_id_escala.get()
            if not escala_id: return

            meta_dados = dados_ocultos.get(escala_id)
            if not meta_dados: return

            # [DEPURAÇÃO] Valida o formato e trata campo vazio como "sem intervalo".
            # Antes, apagar o intervalo gravava 00:00 (meia-noite) no banco.
            try:
                int_ini = hora_ou_none(var_int_ini.get())
                int_fim = hora_ou_none(var_int_fim.get())
            except ValueError as e:
                messagebox.showerror("Horário inválido", f"'{e}' não é um horário válido. Use HH:MM.", parent=popup)
                return
            if bool(int_ini) != bool(int_fim):
                messagebox.showwarning("Aviso", "Preencha o início E o fim do intervalo (ou deixe os dois vazios para remover).", parent=popup)
                return
            # [AUDITORIA ESCALA] Aceitava intervalo fora do turno (ex.: turno 15:00-23:20 e intervalo 10:00-11:00)
            prob = problema_intervalo(meta_dados['h_ent'], meta_dados['h_sai'], int_ini, int_fim)
            if prob:
                messagebox.showwarning("Intervalo inválido",
                                       f"O {prob} ({meta_dados['h_ent']} às {meta_dados['h_sai']}).", parent=popup)
                return

            # Chama a função de salvar existente (v3)
            # Note que passamos os mesmos dados antigos para campos que não mudaram (entrada, saida, etc)
            sucesso = database.salvar_escala_dia_v3(
                escala_id,
                data_janela,
                meta_dados['pos_id'],
                meta_dados['func_id'],
                meta_dados['free_id'],
                meta_dados['h_ent'] or None,
                meta_dados['h_sai'] or None,
                int_ini, # Novo Valor
                int_fim, # Novo Valor
                meta_dados['foco']
            )

            if sucesso:
                # Atualiza visualmente a linha (sem recarregar tudo do banco para ser rápido)
                tree.set(escala_id, column='Início Int.', value=int_ini or "")
                tree.set(escala_id, column='Fim Int.', value=int_fim or "")

                # Verde se tem intervalo, vermelho se ficou sem
                tags_atuais = [t for t in tree.item(escala_id, 'tags') if t not in ('pendente', 'definido')]
                tags_atuais.append('definido' if int_ini else 'pendente')
                tree.item(escala_id, tags=tags_atuais)
                # [DEPURAÇÃO] O mapa e o gráfico por trás desta janela ficavam desatualizados.
                self.carregar_escala_do_dia()

                # Seleciona o próximo
                proximo = tree.next(escala_id)
                if proximo:
                    tree.selection_set(proximo)
                    tree.focus(proximo)
                    tree.see(proximo) # Garante que está visível no scroll
                else:
                    messagebox.showinfo("Fim", "Último da lista editado!", parent=popup)
            else:
                messagebox.showerror("Erro", "Falha ao salvar. Verifique conflitos.", parent=popup)

        # Binds
        tree.bind("<<TreeviewSelect>>", ao_selecionar)
        entry_ini.bind("<Return>", lambda e: entry_fim.focus_set())
        entry_fim.bind("<Return>", salvar_alteracao)

        # Inicializa
        carregar_dados()                   

    def abrir_editor_diretrizes(self):
        """Abre uma janela para editar as mensagens padrão de cada setor."""
        popup = Toplevel(self.root)
        popup.title("Editor de Diretrizes por Setor")
        popup.geometry("700x500")
        popup.transient(self.root)

        # Layout: Painel Esquerdo (Lista) e Direito (Texto)
        paned = ttk.PanedWindow(popup, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Esquerda: Lista de Setores ---
        frame_lista = ttk.LabelFrame(paned, text="Selecione o Setor", padding=5)
        paned.add(frame_lista, weight=1)

        listbox = tk.Listbox(frame_lista, font=("Arial", 11))
        listbox.pack(fill=tk.BOTH, expand=True)
        
        # --- Direita: Editor de Texto ---
        frame_editor = ttk.LabelFrame(paned, text="Mensagem de Foco (WhatsApp)", padding=5)
        paned.add(frame_editor, weight=3)

        txt_msg = tk.Text(frame_editor, font=("Arial", 10), wrap=tk.WORD, height=15)
        txt_msg.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        lbl_info = ttk.Label(frame_editor, text="* Dica: Use asteriscos para negrito (ex: *Foco*)", foreground="gray")
        lbl_info.pack(anchor="w")

        # --- Dados e Eventos ---
        mapa_descricoes = {} # Cache local

        def carregar_lista():
            listbox.delete(0, tk.END)
            mapa_descricoes.clear()
            dados = database.listar_todas_diretrizes_setores()
            for setor, desc in dados:
                listbox.insert(tk.END, setor)
                mapa_descricoes[setor] = desc

        def ao_selecionar(event):
            sel = listbox.curselection()
            if not sel: return
            setor = listbox.get(sel[0])
            texto_atual = mapa_descricoes.get(setor, "")
            
            txt_msg.delete("1.0", tk.END)
            txt_msg.insert("1.0", texto_atual)

        def salvar():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("Aviso", "Selecione um setor na lista à esquerda antes de salvar.", parent=popup)
                return

            setor = listbox.get(sel[0])
            # Captura o texto do widget, garantindo que pegamos tudo
            novo_texto = txt_msg.get("1.0", "end-1c").strip() 

            logger.info(f"Salvando diretriz do setor '{setor}'")  # [DEPURAÇÃO] print de teste virou log

            if database.atualizar_diretriz_setor(setor, novo_texto):
                # ATUALIZAÇÃO CRÍTICA: Força a atualização do cache local com o valor salvo
                mapa_descricoes[setor] = novo_texto 
                messagebox.showinfo("Sucesso", f"Diretriz do setor '{setor}' salva com sucesso!", parent=popup)
            else:
                messagebox.showerror("Erro", "Falha ao salvar no banco de dados. Verifique o log.", parent=popup)

        listbox.bind("<<ListboxSelect>>", ao_selecionar)
        
        btn_salvar = ttk.Button(frame_editor, text="💾 Salvar Alterações", command=salvar)
        btn_salvar.pack(fill=tk.X, pady=10)

        carregar_lista()


    # ===================================================================
    # == [MELHORIA ESCALA] PAGAMENTOS DE FREELANCERS ====================
    # ===================================================================
    FORMAS_PAGAMENTO = ["Pix", "Dinheiro", "Transferência", "Outro"]
    STATUS_PAGAMENTO = [('pendentes', '⏳ Pendentes'), ('pagos', '✅ Pagos'), ('todos', 'Todos')]

    def abrir_pagamentos_freelancers(self, freelancer_id=None):
        """
        Lista os turnos de freelancers do período com o valor calculado
        (diária + hora extra), permite corrigir o horário real, marcar como pago,
        desfazer, copiar o recibo para o WhatsApp e exportar para o Excel.
        """
        popup = Toplevel(self.root)
        popup.title("💰 Pagamentos de Freelancers")
        popup.geometry("1400x680")
        popup.transient(self.root)
        estado = {'itens': {}}

        # ---------- Filtros ----------
        topo = ttk.Frame(popup, padding=(10, 10, 10, 0))
        topo.pack(fill=tk.X)
        ttk.Label(topo, text="De:").pack(side=tk.LEFT)
        de = DateEntry(topo, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        de.pack(side=tk.LEFT, padx=3)
        ttk.Label(topo, text="até:").pack(side=tk.LEFT)
        ate = DateEntry(topo, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        ate.pack(side=tk.LEFT, padx=3)
        hoje = date.today()
        de.set_date(hoje - timedelta(days=hoje.weekday()))      # segunda-feira desta semana
        ate.set_date(hoje)

        def periodo(rapido):
            h = date.today()
            if rapido == 'semana':
                ini, fim = h - timedelta(days=h.weekday()), h
            elif rapido == 'semana_passada':
                ini = h - timedelta(days=h.weekday() + 7)
                fim = ini + timedelta(days=6)
            elif rapido == 'mes':
                ini, fim = h.replace(day=1), h
            else:                                  # tudo que está pendente
                ini, fim = date(2000, 1, 1), h
            de.set_date(ini); ate.set_date(fim)
            carregar()

        for texto, chave in (("Esta semana", 'semana'), ("Semana passada", 'semana_passada'),
                             ("Este mês", 'mes'), ("Tudo até hoje", 'tudo')):
            ttk.Button(topo, text=texto, command=lambda c=chave: periodo(c)).pack(side=tk.LEFT, padx=2)
        ttk.Label(topo, text="   Freelancer:").pack(side=tk.LEFT)
        combo_free = ttk.Combobox(topo, state="readonly", width=24)
        combo_free.pack(side=tk.LEFT, padx=3)
        ttk.Label(topo, text="Mostrar:").pack(side=tk.LEFT, padx=(8, 0))
        combo_status = ttk.Combobox(topo, state="readonly", width=12, values=[r for _, r in self.STATUS_PAGAMENTO])
        combo_status.pack(side=tk.LEFT, padx=3)
        combo_status.set(self.STATUS_PAGAMENTO[0][1])
        ttk.Button(topo, text="🔄", width=3, command=lambda: carregar()).pack(side=tk.LEFT, padx=3)

        mapa_free = {"Todos": None}
        for f in database.listar_freelancers():
            mapa_free[f"{f.Nome} (ID {f.FreelancerID})"] = f.FreelancerID
        combo_free['values'] = list(mapa_free)
        combo_free.set(next((k for k, v in mapa_free.items() if v == freelancer_id), "Todos"))
        if freelancer_id is not None:      # vindo do cadastro: mostra tudo o que está pendente dele
            de.set_date(date(2000, 1, 1))

        linha_cfg = ttk.Frame(popup, padding=(10, 6, 10, 0))
        linha_cfg.pack(fill=tk.X)
        lbl_cfg = ttk.Label(linha_cfg, text="", foreground="#0056b3")
        lbl_cfg.pack(side=tk.LEFT)
        ttk.Button(linha_cfg, text="📅 Feriados",
                   command=lambda: self.abrir_feriados(popup, ao_salvar=carregar)).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(linha_cfg, text="⚙️ Valores (diárias / hora extra)",
                   command=lambda: self.abrir_config_pagamento(popup, ao_salvar=carregar)).pack(side=tk.RIGHT)

        # ---------- Tabela ----------
        meio = ttk.Frame(popup, padding=10)
        meio.pack(fill=tk.BOTH, expand=True)
        cols = ('Data', 'Freelancer', 'Posição', 'Escala', 'Real', 'Horas', 'Diária', 'Valor diária', 'Extras',
                'Valor extras', 'Ajuste', 'Total', 'Situação')
        tree = ttk.Treeview(meio, columns=cols, show='headings', selectmode='extended')
        for col, larg, anc in (('Data', 105, 'center'), ('Freelancer', 150, 'w'), ('Posição', 105, 'w'),
                               ('Escala', 90, 'center'), ('Real', 90, 'center'), ('Horas', 55, 'center'),
                               ('Diária', 115, 'w'), ('Valor diária', 85, 'e'), ('Extras', 55, 'center'),
                               ('Valor extras', 85, 'e'), ('Ajuste', 70, 'e'), ('Total', 90, 'e'), ('Situação', 190, 'w')):
            tree.heading(col, text=col); tree.column(col, width=larg, anchor=anc)
        tree.tag_configure('pago', background='#e3f5e1')
        tree.tag_configure('pendente', background='#fff4cc')
        tree.tag_configure('problema', background='#ffd6d6')
        sb = ttk.Scrollbar(meio, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)

        # Resumo por freelancer (à direita)
        frame_res = ttk.LabelFrame(meio, text="Por freelancer (duplo clique filtra)", padding=5)
        frame_res.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))
        tree_res = ttk.Treeview(frame_res, columns=('Nome', 'Turnos', 'Pendente', 'Pago'), show='headings', height=12)
        for col, larg, anc in (('Nome', 130, 'w'), ('Turnos', 50, 'center'), ('Pendente', 90, 'e'), ('Pago', 90, 'e')):
            tree_res.heading(col, text=col); tree_res.column(col, width=larg, anchor=anc)
        tree_res.pack(fill=tk.Y, expand=True)

        rodape = ttk.Frame(popup, padding=(10, 0, 10, 10))
        rodape.pack(fill=tk.X)
        lbl_totais = ttk.Label(rodape, text="", font=("Arial", 10, "bold"))
        lbl_totais.pack(anchor="w", pady=(0, 6))
        botoes = ttk.Frame(rodape)
        botoes.pack(fill=tk.X)

        def selecionados():
            ids = tree.selection() or ()
            return [estado['itens'][i] for i in ids if i in estado['itens']]

        def atualizar_totais(event=None):
            itens = list(estado['itens'].values())
            pend = [i for i in itens if not i['Pago']]
            pagos = [i for i in itens if i['Pago']]
            sel = selecionados()
            texto = (f"⏳ A pagar: {fmt_reais(sum((i['Total'] for i in pend), Decimal('0')))} ({len(pend)} turno(s))     "
                     f"✅ Pago: {fmt_reais(sum((i['Total'] for i in pagos), Decimal('0')))} ({len(pagos)})")
            if sel:
                texto += f"     🔹 Selecionados: {fmt_reais(sum((i['Total'] for i in sel), Decimal('0')))} ({len(sel)})"
            lbl_totais.config(text=texto)

        def carregar(manter=None):
            cfg = self._config_pagamento(recarregar=True)
            self.__dict__['_cache_feriados'] = {}
            lbl_cfg.config(text=(
                f"Longa ({fmt_horas(minutos=cfg['MinutosLonga'])}): {fmt_reais(cfg['DiariaLongaSemana'])} seg-sáb · "
                f"{fmt_reais(cfg['DiariaLongaDomingo'])} dom/feriado     "
                f"Curta ({fmt_horas(minutos=cfg['MinutosCurta'])}): {fmt_reais(cfg['DiariaCurtaSemana'])} · "
                f"{fmt_reais(cfg['DiariaCurtaDomingo'])}     Extra: {fmt_reais(cfg['HoraExtraSemana'])}/h · "
                f"{fmt_reais(cfg['HoraExtraDomingo'])}/h dom/fer, blocos de {cfg['BlocoExtraMinutos']} min"),
                foreground="#0056b3")
            status = next((ch for ch, r in self.STATUS_PAGAMENTO if r == combo_status.get()), 'pendentes')
            fid = mapa_free.get(combo_free.get())
            try:
                itens = database.listar_pagamentos_freelancers(de.get_date(), ate.get_date(), fid, status)
            except Exception as e:
                logger.error(f"Erro ao carregar pagamentos: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Não foi possível carregar os pagamentos:\n{e}", parent=popup)
                itens = []
            for i in tree.get_children():
                tree.delete(i)
            estado['itens'] = {}
            resumo = {}
            for n, it in enumerate(itens):
                iid = f"P{it['PagamentoID']}" if it['Pago'] else f"E{it['EscalaID']}"
                estado['itens'][iid] = it
                c = it['Calculo'] or {}
                if it['Pago']:
                    sit = f"✅ Pago {fmt_data_br(it['DataPagamento'])}" + (f" ({it['FormaPagamento']})" if it['FormaPagamento'] else "")
                    if it['TurnoExcluido']:
                        sit += " · turno excluído"
                    tag = 'pago'
                elif it['SemHorario']:
                    sit, tag = "⚠️ Turno sem horário", 'problema'
                else:
                    extras_sit = [t for t, cond in (("horário corrigido", it['Corrigido']),
                                                     ("proporcional", c.get('Proporcional')),
                                                     ("diária trocada", it.get('TipoForcado'))) if cond]
                    sit, tag = "⏳ Pendente" + "".join(f" · {t}" for t in extras_sit), 'pendente'
                escala = f"{it['EntradaEscala'] or '?'}–{it['SaidaEscala'] or '?'}"
                real = f"{it['EntradaReal']}–{it['SaidaReal']}" if it['Corrigido'] else "= escala"
                tipo_txt = (nome_tipo_dia(c).replace(' (seg a sáb)', '') + (" (prop.)" if c.get('Proporcional') else "")) if c else "—"
                data_txt = fmt_data_br(it['Data'], True) + (" 🎉" if it.get('Feriado') else "")
                tree.insert("", "end", iid=iid, tags=(tag,), values=(
                    data_txt, it['Nome'], it['Posicao'], escala, real,
                    fmt_horas(c['Horas']) if c else "—", tipo_txt,
                    fmt_reais(c['ValorDiaria']) if c else "—", fmt_horas(c['HorasExtras']) if c and c['HorasExtras'] else "—",
                    fmt_reais(c['ValorExtras']) if c and c['ValorExtras'] else "—",
                    fmt_reais(it['Ajuste']) if it['Ajuste'] else "—", fmt_reais(it['Total']), sit))
                r = resumo.setdefault((it['FreelancerID'], it['Nome']), [0, Decimal('0'), Decimal('0')])
                r[0] += 1
                r[2 if it['Pago'] else 1] += it['Total']
            for i in tree_res.get_children():
                tree_res.delete(i)
            for (fid_r, nome), (qtd, pend, pago) in sorted(resumo.items(), key=lambda kv: str(kv[0][1]).lower()):
                tree_res.insert("", "end", iid=f"F{fid_r}", values=(nome, qtd, fmt_reais(pend), fmt_reais(pago)))
            if manter:
                for iid in manter:
                    if tree.exists(iid):
                        tree.selection_add(iid)
            atualizar_totais()

        def corrigir(event=None):
            sel = selecionados()
            if len(sel) != 1:
                messagebox.showwarning("Aviso", "Selecione UM turno para corrigir.", parent=popup)
                return
            it = sel[0]
            if it['Pago']:
                messagebox.showinfo("Turno pago", "Este turno já está PAGO. Para corrigir, primeiro clique em "
                                    "'↩️ Desfazer pagamento'.", parent=popup)
                return
            self.abrir_correcao_pagamento(it, popup, ao_salvar=lambda: carregar(manter=[f"E{it['EscalaID']}"]))

        def pagar():
            sel = [i for i in selecionados() if not i['Pago']]
            if not sel:
                messagebox.showwarning("Aviso", "Selecione os turnos PENDENTES que você pagou "
                                       "(Ctrl+clique ou Shift+clique para vários).", parent=popup)
                return
            if any(i['SemHorario'] for i in sel):
                messagebox.showwarning("Aviso", "Há turno sem horário de entrada/saída na seleção. Corrija antes de pagar.", parent=popup)
                return
            total = sum((i['Total'] for i in sel), Decimal('0'))
            nomes = sorted({i['Nome'] for i in sel})
            resposta = self._dialogo_confirmar_pagamento(popup, len(sel), total, nomes)
            if not resposta:
                return
            data_pag, forma = resposta
            ok, msg, total_pago = database.marcar_pagamentos_pagos([i['EscalaID'] for i in sel], data_pag, forma)
            if ok:
                self.status(f"{msg} Total {fmt_reais(total_pago)}.")
                carregar()
                self.atualizar_resumo_dia()
            else:
                messagebox.showerror("Não foi possível marcar como pago", msg, parent=popup)

        def desfazer():
            sel = [i for i in selecionados() if i['Pago']]
            if not sel:
                messagebox.showwarning("Aviso", "Selecione os turnos PAGOS que quer voltar para pendente.", parent=popup)
                return
            total = sum((i['Total'] for i in sel), Decimal('0'))
            if not messagebox.askyesno("Desfazer pagamento",
                                       f"Voltar {len(sel)} turno(s) ({fmt_reais(total)}) para PENDENTE?\n\n"
                                       "Use quando marcou como pago por engano.", parent=popup):
                return
            ok, msg = database.desfazer_pagamentos([i['PagamentoID'] for i in sel])
            if ok:
                self.status(msg, 'info')
                carregar()
                self.atualizar_resumo_dia()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        def recibo():
            sel = selecionados() or list(estado['itens'].values())
            nomes = {i['FreelancerID'] for i in sel}
            if not sel:
                messagebox.showwarning("Aviso", "Não há turnos na lista.", parent=popup)
                return
            if len(nomes) != 1:
                messagebox.showwarning("Aviso", "O recibo é de UM freelancer: escolha o freelancer no filtro "
                                       "ou selecione só os turnos dele.", parent=popup)
                return
            texto = self.texto_recibo_freelancer(sel)
            popup.clipboard_clear()
            popup.clipboard_append(texto)
            self._ultimo_recibo = texto
            self.status(f"Recibo de {sel[0]['Nome']} copiado. Cole no WhatsApp com Ctrl+V.")
            messagebox.showinfo("Recibo copiado", texto + "\n\n(Já está copiado: cole no WhatsApp com Ctrl+V.)", parent=popup)

        def filtrar_por_resumo(event=None):
            sel = tree_res.focus()
            if not sel:
                return
            fid = int(sel[1:]) if sel[1:].isdigit() else None
            combo_free.set(next((k for k, v in mapa_free.items() if v == fid), "Todos"))
            carregar()

        for texto, cmd in (("✏️ Corrigir horário / ajuste", corrigir), ("✅ Marcar como PAGO", pagar),
                           ("↩️ Desfazer pagamento", desfazer), ("📋 Copiar recibo (WhatsApp)", recibo),
                           ("📊 Exportar Excel", lambda: self.exportar_pagamentos_excel(list(estado['itens'].values()), popup))):
            ttk.Button(botoes, text=texto, command=cmd).pack(side=tk.LEFT, padx=(0, 6), ipady=3)
        ttk.Label(botoes, text="Ctrl+clique / Shift+clique seleciona vários · duplo clique corrige", foreground="gray").pack(side=tk.RIGHT)

        tree.bind("<<TreeviewSelect>>", atualizar_totais)
        tree.bind("<Double-1>", corrigir)
        tree_res.bind("<Double-1>", filtrar_por_resumo)
        for combo in (combo_free, combo_status):
            combo.bind("<<ComboboxSelected>>", lambda e: carregar())
        for campo in (de, ate):
            campo.bind("<<DateEntrySelected>>", lambda e: carregar())
        carregar()
        self._janela_pagamentos = {'popup': popup, 'tree': tree, 'tree_res': tree_res, 'carregar': carregar,
                                   'pagar': pagar, 'desfazer': desfazer, 'corrigir': corrigir, 'recibo': recibo,
                                   'de': de, 'ate': ate, 'free': combo_free, 'status': combo_status,
                                   'totais': lbl_totais, 'cfg': lbl_cfg, 'estado': estado, 'periodo': periodo}
        return popup

    @staticmethod
    def texto_recibo_freelancer(itens):
        """Texto para o WhatsApp com os turnos e o total de UM freelancer."""
        itens = sorted(itens, key=lambda i: (i['Data'] or date.min, i['EntradaEscala'] or ''))
        nome = itens[0]['Nome']
        linhas = [f"Olá, {nome.split()[0] if nome else ''}! Segue o resumo dos seus turnos:", ""]
        for i in itens:
            c = i['Calculo'] or {}
            ent = i['EntradaReal'] or i['EntradaEscala'] or '?'
            sai = i['SaidaReal'] or i['SaidaEscala'] or '?'
            extra = f" + {fmt_horas(c['HorasExtras'])} extra" if c and c.get('HorasExtras') else ""
            prop = " (proporcional)" if c and c.get('Proporcional') else ""
            ajuste = f" {'+' if i['Ajuste'] > 0 else ''}{fmt_reais(i['Ajuste'])} ajuste" if i['Ajuste'] else ""
            tipo = f" · diária {nome_tipo_dia(c).replace(' (seg a sáb)', '')}" if c and c.get('Tipo') else ""
            feriado = f" 🎉 {i['Feriado']}" if i.get('Feriado') else ""
            linhas.append(f"• {fmt_data_br(i['Data'], True)}{feriado} {ent}–{sai} · {fmt_horas(c['Horas']) if c else '?'}"
                          f"{tipo}{extra}{prop}{ajuste} → {fmt_reais(i['Total'])}" + (" ✅ pago" if i['Pago'] else ""))
            if i.get('Observacao'):
                linhas.append(f"   obs: {i['Observacao']}")
        total = sum((i['Total'] for i in itens), Decimal('0'))
        pendente = sum((i['Total'] for i in itens if not i['Pago']), Decimal('0'))
        linhas += ["", f"*Total: {fmt_reais(total)}*"]
        if pendente and pendente != total:
            linhas.append(f"A receber: {fmt_reais(pendente)}")
        empresa = getattr(config, 'NOME_EMPRESA', '') or ''
        linhas += ["", "Obrigado pelo trabalho! 🙌"] + ([empresa] if empresa else [])
        return "\n".join(linhas)

    def _dialogo_confirmar_pagamento(self, pai, qtd, total, nomes):
        """Pergunta a data e a forma de pagamento. Devolve (data, forma) ou None."""
        dlg = Toplevel(pai)
        dlg.title("Confirmar pagamento")
        dlg.geometry("420x260")
        dlg.transient(pai)
        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        quem = ", ".join(nomes[:3]) + (f" e mais {len(nomes) - 3}" if len(nomes) > 3 else "")
        ttk.Label(frame, text=f"{qtd} turno(s) de {quem}", wraplength=380).pack(anchor="w")
        ttk.Label(frame, text=f"Total: {fmt_reais(total)}", font=("Arial", 14, "bold"), foreground="#1b7a2f").pack(anchor="w", pady=8)
        linha = ttk.Frame(frame)
        linha.pack(fill=tk.X, pady=4)
        ttk.Label(linha, text="Pago em:").pack(side=tk.LEFT)
        data_pag = DateEntry(linha, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        data_pag.set_date(date.today())
        data_pag.pack(side=tk.LEFT, padx=5)
        ttk.Label(linha, text="Forma:").pack(side=tk.LEFT, padx=(10, 0))
        forma = ttk.Combobox(linha, values=self.FORMAS_PAGAMENTO, width=14)
        forma.set(getattr(self, '_ultima_forma_pag', "Pix"))
        forma.pack(side=tk.LEFT, padx=5)
        resultado = {}

        def confirmar():
            resultado['ok'] = (data_pag.get_date(), forma.get().strip())
            self._ultima_forma_pag = forma.get().strip() or "Pix"
            dlg.destroy()

        botoes = ttk.Frame(frame)
        botoes.pack(fill=tk.X, pady=(15, 0))
        ttk.Button(botoes, text="✅ Confirmar pagamento", command=confirmar).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5), ipady=4)
        ttk.Button(botoes, text="Cancelar", command=dlg.destroy).pack(side=tk.LEFT, expand=True, fill=tk.X, ipady=4)
        dlg.bind("<Return>", lambda e: confirmar())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self._janela_confirmar_pag = {'dlg': dlg, 'confirmar': confirmar, 'forma': forma, 'data': data_pag}
        try:
            dlg.grab_set()
            pai.wait_window(dlg)
        except tk.TclError:
            pass
        return resultado.get('ok')

    def abrir_correcao_pagamento(self, item, pai, ao_salvar=None):
        """Corrige o horário REAL do turno e/ou lança um ajuste (+ bônus / - desconto)."""
        dlg = Toplevel(pai)
        dlg.title("Corrigir horário / ajuste")
        dlg.geometry("500x400")
        dlg.transient(pai)
        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"{item['Nome']} · {fmt_data_br(item['Data'], True)} · {item['Posicao']}",
                  font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(frame, text=f"Na escala: {item['EntradaEscala'] or '?'} às {item['SaidaEscala'] or '?'}",
                  foreground="gray").grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="Entrada real:").grid(row=2, column=0, sticky="w")
        e_ent = ttk.Entry(frame, width=8)
        e_ent.grid(row=2, column=1, sticky="w", padx=5)
        ttk.Label(frame, text="Saída real:").grid(row=2, column=2, sticky="w")
        e_sai = ttk.Entry(frame, width=8)
        e_sai.grid(row=2, column=3, sticky="w", padx=5)
        ttk.Label(frame, text="(vazio = usar o horário da escala)", foreground="gray").grid(row=3, column=0, columnspan=4, sticky="w")
        ttk.Label(frame, text="Ajuste R$:").grid(row=4, column=0, sticky="w", pady=(10, 0))
        e_aj = ttk.Entry(frame, width=10)
        e_aj.grid(row=4, column=1, sticky="w", padx=5, pady=(10, 0))
        ttk.Label(frame, text="(+ bônus / - desconto, ex: -10)", foreground="gray").grid(row=4, column=2, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(frame, text="Observação:").grid(row=5, column=0, sticky="w", pady=(10, 0))
        e_obs = ttk.Entry(frame, width=40)
        e_obs.grid(row=5, column=1, columnspan=3, sticky="ew", padx=5, pady=(10, 0))
        ttk.Label(frame, text="Diária:").grid(row=8, column=0, sticky="w", pady=(10, 0))
        tipo_escala = item.get('TipoEscala')
        rotulo_escala = f"Como está na escala ({tipo_escala})" if tipo_escala else "Automático (pela duração)"
        opcoes_tipo = {rotulo_escala: None, "Longa": 'longa', "Curta": 'curta'}
        combo_tipo = ttk.Combobox(frame, state="readonly", width=24, values=list(opcoes_tipo))
        combo_tipo.grid(row=8, column=1, columnspan=3, sticky="w", padx=5, pady=(10, 0))
        combo_tipo.set(next(k for k, v in opcoes_tipo.items() if v == item.get('TipoForcado')))
        lbl_prev = ttk.Label(frame, text="", font=("Arial", 10, "bold"), foreground="#1b7a2f", wraplength=460)
        lbl_prev.grid(row=6, column=0, columnspan=4, sticky="w", pady=12)
        if item.get('EntradaReal'):
            e_ent.insert(0, item['EntradaReal']); e_sai.insert(0, item['SaidaReal'] or '')
        if item.get('Ajuste'):
            e_aj.insert(0, str(item['Ajuste']).replace('.', ','))
        if item.get('Observacao'):
            e_obs.insert(0, item['Observacao'])

        def ler():
            ent = hora_ou_none(e_ent.get())
            sai = hora_ou_none(e_sai.get())
            aj = para_decimal_br(e_aj.get(), "Ajuste", permitir_negativo=True)
            return ent, sai, aj

        def previa(event=None):
            if event is not None and getattr(event, 'widget', None) in (e_ent, e_sai):
                self._aplicar_mascara_hora(event)
            try:
                ent, sai, aj = ler()
            except ValueError as e:
                lbl_prev.config(text=f"⚠️ {e}", foreground="#c62828")
                return
            calc = self._calcular_turno_free(ent or item['EntradaEscala'], sai or item['SaidaEscala'],
                                             item['Data'].strftime('%Y-%m-%d'), opcoes_tipo.get(combo_tipo.get()) or tipo_escala, aj,
                                             item['EntradaEscala'], item['SaidaEscala'])
            if not calc:
                lbl_prev.config(text="⚠️ Preencha entrada e saída.", foreground="#c62828")
                return
            lbl_prev.config(text=texto_calculo(calc), foreground="#1b7a2f")

        def salvar(event=None):
            try:
                ent, sai, aj = ler()
            except ValueError as e:
                messagebox.showerror("Valor inválido", f"{e}\n\nHorários no formato HH:MM (ex: 18:30).", parent=dlg)
                return
            # horário igual ao da escala não precisa ser guardado como "corrigido"
            if ent == item['EntradaEscala'] and sai == item['SaidaEscala']:
                ent = sai = None
            ok, msg = database.salvar_correcao_pagamento(item['EscalaID'], ent, sai, aj, e_obs.get(),
                                                         opcoes_tipo.get(combo_tipo.get()))
            if not ok:
                messagebox.showerror("Não foi possível salvar", msg, parent=dlg)
                return
            self.status(f"Turno de {item['Nome']} em {fmt_data_br(item['Data'])}: {msg.lower()}")
            dlg.destroy()
            if ao_salvar:
                ao_salvar()

        for campo in (e_ent, e_sai, e_aj):
            campo.bind("<KeyRelease>", previa)
        combo_tipo.bind("<<ComboboxSelected>>", previa)
        dlg.bind("<Return>", salvar)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        botoes = ttk.Frame(frame)
        botoes.grid(row=9, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Button(botoes, text="💾 Salvar", command=salvar).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5), ipady=3)
        ttk.Button(botoes, text="Cancelar", command=dlg.destroy).pack(side=tk.LEFT, expand=True, fill=tk.X, ipady=3)
        previa()
        e_ent.focus_set()
        self._janela_correcao = {'dlg': dlg, 'ent': e_ent, 'sai': e_sai, 'ajuste': e_aj, 'obs': e_obs, 'tipo': combo_tipo,
                                 'previa': lbl_prev, 'salvar': salvar, 'atualizar': previa}

    def abrir_config_pagamento(self, pai=None, ao_salvar=None):
        """Valores das diárias (longa/curta × seg-sáb/domingo-feriado), hora extra e regras."""
        pai = pai or self.root
        cfg = self._config_pagamento(recarregar=True)
        dlg = Toplevel(pai)
        dlg.title("⚙️ Valores dos Freelancers")
        dlg.geometry("620x520")
        dlg.transient(pai)
        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        campos = {}

        def campo(linha, coluna, chave, valor, largura=9):
            e = ttk.Entry(frame, width=largura, justify="center")
            e.insert(0, valor)
            e.grid(row=linha, column=coluna, padx=4, pady=3)
            campos[chave] = e
            return e

        def hm(minutos):
            return f"{int(minutos) // 60}:{int(minutos) % 60:02d}"

        def br(v):
            return f"{Decimal(str(v)):.2f}".replace('.', ',')

        ttk.Label(frame, text="", width=26).grid(row=0, column=0)
        for col, titulo in ((1, "Tempo na loja"), (2, "Seg a sáb"), (3, "Dom / feriado")):
            ttk.Label(frame, text=titulo, font=("Arial", 9, "bold")).grid(row=0, column=col)
        ttk.Label(frame, text="Diária LONGA (R$):").grid(row=1, column=0, sticky="w")
        campo(1, 1, 'MinutosLonga', hm(cfg['MinutosLonga']))
        campo(1, 2, 'DiariaLongaSemana', br(cfg['DiariaLongaSemana']))
        campo(1, 3, 'DiariaLongaDomingo', br(cfg['DiariaLongaDomingo']))
        ttk.Label(frame, text="Diária CURTA (R$):").grid(row=2, column=0, sticky="w")
        campo(2, 1, 'MinutosCurta', hm(cfg['MinutosCurta']))
        campo(2, 2, 'DiariaCurtaSemana', br(cfg['DiariaCurtaSemana']))
        campo(2, 3, 'DiariaCurtaDomingo', br(cfg['DiariaCurtaDomingo']))
        ttk.Label(frame, text="Hora extra (R$ por hora):").grid(row=3, column=0, sticky="w")
        campo(3, 2, 'HoraExtraSemana', br(cfg['HoraExtraSemana']))
        campo(3, 3, 'HoraExtraDomingo', br(cfg['HoraExtraDomingo']))
        ttk.Separator(frame).grid(row=4, column=0, columnspan=4, sticky="ew", pady=8)
        ttk.Label(frame, text="Hora extra conta em blocos de (min):").grid(row=5, column=0, sticky="w")
        campo(5, 1, 'BlocoExtraMinutos', str(cfg['BlocoExtraMinutos']))
        ttk.Label(frame, text="só blocos completos", foreground="gray").grid(row=5, column=2, columnspan=2, sticky="w")
        ttk.Label(frame, text="Na escala, até (horas) = diária curta:").grid(row=6, column=0, sticky="w")
        campo(6, 1, 'LimiteCurtaMinutos', hm(cfg['LimiteCurtaMinutos']))
        ttk.Label(frame, text="acima disso = longa", foreground="gray").grid(row=6, column=2, columnspan=2, sticky="w")
        lbl_ex = ttk.Label(frame, text="", foreground="#0056b3", wraplength=580, justify="left")
        lbl_ex.grid(row=7, column=0, columnspan=4, sticky="w", pady=10)
        ttk.Label(frame, foreground="gray", justify="left", wraplength=580, text=(
            "• Conta só ENTRADA → SAÍDA (o intervalo é remunerado).\n"
            "• Saiu antes do tempo da diária: paga proporcional ao tempo trabalhado.\n"
            "• Domingos e os feriados cadastrados em '📅 Feriados' usam a coluna 'Dom / feriado'.\n"
            "• Mudar os valores vale para os turnos ainda NÃO pagos.")).grid(row=8, column=0, columnspan=4, sticky="w")

        def minutos_de(texto, nome):
            t = str(texto).strip().lower().replace('h', ':')
            try:
                if ':' in t:
                    h, m = (t.split(':') + ['0'])[:2]
                    return int(h or 0) * 60 + int(m or 0)
                return int((para_decimal_br(t, nome) * 60).to_integral_value())
            except (ValueError, InvalidOperation):
                raise ValueError(f"'{texto}' não é um tempo válido para {nome} (ex: 8:20).")

        def ler():
            novo = {}
            for chave, e in campos.items():
                if chave in ('MinutosLonga', 'MinutosCurta', 'LimiteCurtaMinutos'):
                    novo[chave] = minutos_de(e.get(), "o tempo")
                elif chave == 'BlocoExtraMinutos':
                    if not e.get().strip().isdigit():
                        raise ValueError("O bloco da hora extra deve ser um número inteiro de minutos (ex: 20).")
                    novo[chave] = int(e.get().strip())
                else:
                    novo[chave] = para_decimal_br(e.get(), "o valor")
            return novo

        def exemplo(event=None):
            try:
                novo = ler()
            except ValueError as e:
                lbl_ex.config(text=f"⚠️ {e}", foreground="#c62828")
                return
            base = datetime(2000, 1, 1, 10, 0)
            linhas = []
            for rotulo, data_ex, minutos in (("Segunda", '2026-09-28', novo['MinutosLonga'] + 60),
                                             ("Domingo", '2026-09-27', novo['MinutosLonga'] + 60),
                                             ("Sábado", '2026-10-03', novo['MinutosLonga'] - 140)):
                fim_ex = base + timedelta(minutes=minutos)
                calc = database.calcular_pagamento_turno(base.strftime('%H:%M'), fim_ex.strftime('%H:%M'), novo, 0, data_ex)
                if calc:
                    linhas.append(f"{rotulo} 10:00–{fim_ex.strftime('%H:%M')}: {texto_calculo(calc)}")
            lbl_ex.config(text="Exemplos:\n" + "\n".join(linhas), foreground="#0056b3")

        def salvar(event=None):
            try:
                novo = ler()
            except ValueError as e:
                messagebox.showerror("Valor inválido", str(e), parent=dlg)
                return
            ok, msg = database.salvar_config_pagamento_freelancer(novo)
            if not ok:
                messagebox.showerror("Não foi possível salvar", msg, parent=dlg)
                return
            self._config_pagamento(recarregar=True)
            self.status("Valores dos freelancers salvos.")
            dlg.destroy()
            self.atualizar_resumo_dia()
            if ao_salvar:
                ao_salvar()

        for e in campos.values():
            e.bind("<KeyRelease>", exemplo)
        dlg.bind("<Return>", salvar)
        botoes = ttk.Frame(frame)
        botoes.grid(row=9, column=0, columnspan=4, sticky="ew", pady=(15, 0))
        ttk.Button(botoes, text="💾 Salvar valores", command=salvar).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5), ipady=3)
        ttk.Button(botoes, text="📅 Feriados", command=lambda: self.abrir_feriados(dlg)).pack(side=tk.LEFT, ipady=3)
        exemplo()
        self._janela_config_pag = {'dlg': dlg, 'campos': campos, 'salvar': salvar, 'exemplo': lbl_ex}

    def abrir_feriados(self, pai=None, ao_salvar=None):
        """Cadastro dos feriados (pagos com os valores de domingo)."""
        pai = pai or self.root
        dlg = Toplevel(pai)
        dlg.title("📅 Feriados (pagos como domingo)")
        dlg.geometry("480x520")
        dlg.transient(pai)
        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        topo = ttk.Frame(frame)
        topo.pack(fill=tk.X)
        ttk.Label(topo, text="Ano:").pack(side=tk.LEFT)
        spin_ano = ttk.Spinbox(topo, from_=2020, to=2100, width=6)
        spin_ano.set(str(date.today().year))
        spin_ano.pack(side=tk.LEFT, padx=5)
        tree = ttk.Treeview(frame, columns=('Data', 'Nome'), show='headings', selectmode='extended', height=14)
        tree.heading('Data', text='Data'); tree.column('Data', width=130, anchor='center')
        tree.heading('Nome', text='Feriado'); tree.column('Nome', width=290)
        tree.pack(fill=tk.BOTH, expand=True, pady=8)
        linha = ttk.Frame(frame)
        linha.pack(fill=tk.X)
        nova_data = DateEntry(linha, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        nova_data.pack(side=tk.LEFT)
        novo_nome = ttk.Entry(linha, width=26)
        novo_nome.pack(side=tk.LEFT, padx=5)

        def ano():
            t = str(spin_ano.get()).strip()
            return int(t) if t.isdigit() else date.today().year

        def carregar(event=None):
            for i in tree.get_children():
                tree.delete(i)
            for d, n in database.listar_feriados(ano()):
                tree.insert("", "end", iid=d.isoformat(), values=(fmt_data_br(d, True), n))

        def mudou():
            self.__dict__['_cache_feriados'] = {}
            self.atualizar_resumo_dia()
            if ao_salvar:
                ao_salvar()

        def adicionar():
            ok, msg = database.salvar_feriados([(nova_data.get_date(), novo_nome.get().strip() or "Feriado")])
            if ok:
                novo_nome.delete(0, tk.END)
                spin_ano.set(str(nova_data.get_date().year)); carregar(); mudou()
            else:
                messagebox.showerror("Erro", msg, parent=dlg)

        def nacionais():
            lista = database.feriados_nacionais(ano())
            if not messagebox.askyesno("Feriados nacionais", f"Cadastrar os {len(lista)} feriados nacionais de {ano()}?\n\n"
                                       + "\n".join(f"{fmt_data_br(d, True)} - {n}" for d, n in lista)
                                       + "\n\nFeriados do estado e da cidade (ex: aniversário da cidade) "
                                       "cadastre à mão.", parent=dlg):
                return
            ok, msg = database.salvar_feriados(lista)
            if ok:
                carregar(); mudou(); self.status(msg)
            else:
                messagebox.showerror("Erro", msg, parent=dlg)

        def remover():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Aviso", "Selecione o(s) feriado(s) na lista.", parent=dlg)
                return
            if messagebox.askyesno("Remover", f"Remover {len(sel)} feriado(s)?", parent=dlg):
                for iid in sel:
                    database.excluir_feriado(iid)
                carregar(); mudou()

        ttk.Button(linha, text="➕ Adicionar", command=adicionar).pack(side=tk.LEFT)
        botoes = ttk.Frame(frame)
        botoes.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(botoes, text="🇧🇷 Cadastrar feriados nacionais do ano", command=nacionais).pack(side=tk.LEFT)
        ttk.Button(botoes, text="🗑️ Remover selecionados", command=remover).pack(side=tk.RIGHT)
        spin_ano.bind("<Return>", carregar)
        spin_ano.bind("<<Increment>>", lambda e: dlg.after(10, carregar))
        spin_ano.bind("<<Decrement>>", lambda e: dlg.after(10, carregar))
        carregar()
        self._janela_feriados = {'dlg': dlg, 'tree': tree, 'ano': spin_ano, 'data': nova_data, 'nome': novo_nome,
                                 'adicionar': adicionar, 'nacionais': nacionais, 'remover': remover, 'carregar': carregar}

    def exportar_pagamentos_excel(self, itens, pai=None):
        """Excel (ou CSV, se o Excel não estiver disponível) com os turnos da lista."""
        from tkinter import filedialog
        pai = pai or self.root
        if not itens:
            messagebox.showwarning("Aviso", "Não há turnos na lista para exportar.", parent=pai)
            return None
        caminho = filedialog.asksaveasfilename(parent=pai, title="Salvar pagamentos", defaultextension=".xlsx",
                                               filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
                                               initialfile=f"Pagamentos_Freelancers_{datetime.now():%d-%m-%Y}.xlsx")
        if not caminho:
            return None
        linhas = []
        for i in itens:
            c = i['Calculo'] or {}
            linhas.append({'Data': fmt_data_br(i['Data']), 'Dia': DIAS_CURTOS[i['Data'].weekday()] if i['Data'] else '',
                           'Freelancer': i['Nome'], 'Posição': i['Posicao'],
                           'Entrada': i['EntradaReal'] or i['EntradaEscala'], 'Saída': i['SaidaReal'] or i['SaidaEscala'],
                           'Horário corrigido': 'sim' if i['Corrigido'] else '',
                           'Diária': nome_tipo_dia(c).replace(' (seg a sáb)', '') if c else '',
                           'Feriado': i.get('Feriado') or '',
                           'Horas': float(c.get('Horas', 0) or 0), 'Horas extras': float(c.get('HorasExtras', 0) or 0),
                           'Valor diária (R$)': float(c.get('ValorDiaria', 0) or 0), 'Extras (R$)': float(c.get('ValorExtras', 0) or 0),
                           'Ajuste (R$)': float(i['Ajuste'] or 0), 'Total (R$)': float(i['Total'] or 0),
                           'Situação': 'Pago' if i['Pago'] else 'Pendente',
                           'Pago em': fmt_data_br(i['DataPagamento']) if i['Pago'] else '',
                           'Forma': i['FormaPagamento'] or '', 'Observação': i['Observacao'] or ''})
        try:
            if caminho.lower().endswith('.csv'):
                raise ImportError
            import pandas as pd
            pd.DataFrame(linhas).to_excel(caminho, index=False, sheet_name='Pagamentos')
        except ImportError:
            import csv
            if not caminho.lower().endswith('.csv'):
                caminho = os.path.splitext(caminho)[0] + '.csv'
            with open(caminho, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=';')
                w.writeheader()
                w.writerows(linhas)
        except Exception as e:
            logger.error(f"Erro ao exportar pagamentos: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível salvar.\n{e}\n\nSe o arquivo estiver aberto no Excel, feche-o.", parent=pai)
            return None
        self.status(f"Pagamentos salvos em: {caminho}")
        return caminho

if __name__ == "__main__":
    root = tk.Tk()
    app = AppEscalaLoja(root)
    root.mainloop()

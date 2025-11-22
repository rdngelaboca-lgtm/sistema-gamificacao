import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
from tkcalendar import DateEntry
from PIL import Image, ImageTk
import database
import calculadora_logica # Importa o novo módulo lógico
import os
import webbrowser
import urllib.parse
import re
from datetime import datetime, date

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

        self.frame_inferior = ttk.LabelFrame(root, text="Fluxo de Equipe & Alertas do Sistema", padding="10", height=150)
        self.frame_inferior.pack(fill=tk.X, side=tk.BOTTOM)
        # Adicionado wraplength=1150 para quebrar linhas em mensagens longas de erro
        self.lbl_alertas = tk.Label(self.frame_inferior, text="Sistema pronto. Nenhuma ação pendente.", fg="gray", justify=tk.LEFT, font=("Consolas", 10), wraplength=1150)
        self.lbl_alertas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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

        ttk.Button(self.frame_topo, text="👤 Novo Freelancer", command=self.cadastrar_freelancer).pack(side=tk.RIGHT, padx=5)

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

    def redesenhar_marcadores(self):
        self.canvas.delete("marcador")
        self.canvas.delete("texto_marcador")
        self.canvas.delete("setor_tag")

        dia_semana_hoje = datetime.strptime(self.data_selecionada, '%Y-%m-%d').isoweekday() + 1
        if dia_semana_hoje == 8: dia_semana_hoje = 1

        for pos in self.posicoes:
            # Desempacota os dados (agora incluindo Setor no índice 5)
            pos_id, nome, x, y, ativo, setor = pos 

            nome_pessoa = "Vazio"
            cor = "#ff4444" # Vermelho (Vazio)
            info_intervalo = ""

            if pos_id in self.escala_atual:
                dados = self.escala_atual[pos_id]
                nome_pessoa = dados.NomePessoa if dados.NomePessoa else "(Livre)"
                cor = "#00C851" if dados.NomePessoa else "#FFBB33" # Verde ou Amarelo

                # Exibe o intervalo se estiver agendado
                if dados.InicioIntervalo and dados.FimIntervalo:
                    i_ini = dados.InicioIntervalo.strftime('%H:%M')
                    i_fim = dados.FimIntervalo.strftime('%H:%M')
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
        setores = ["Varanda", "Frente Loja", "Salão", "Caixa", "Buffet", "Cozinha"]
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

        ttk.Button(popup, text="💾 Salvar Alterações", command=salvar_cfg).pack(pady=15, fill=tk.X, padx=20)
        ttk.Button(popup, text="🗑️ Excluir Posição", command=excluir_cfg).pack(pady=5, fill=tk.X, padx=20)

    def criar_nova_posicao(self, x, y):
        popup = Toplevel(self.root)
        popup.title("Nova Posição")

        ttk.Label(popup, text="Nome:").pack()
        entry_nome = ttk.Entry(popup)
        entry_nome.pack()

        ttk.Label(popup, text="Setor:").pack()
        combo_setor = ttk.Combobox(popup, values=["Varanda", "Frente Loja", "Salão", "Caixa", "Buffet", "Cozinha"])
        combo_setor.pack()

        def confirmar():
            if entry_nome.get():
                # Passa o setor para a função de criação
                database.criar_posicao_loja(entry_nome.get(), x, y, combo_setor.get())
                self.carregar_escala_do_dia()
                popup.destroy()

        ttk.Button(popup, text="Criar", command=confirmar).pack(pady=10)

    # --- INTEGRAÇÃO COM O CÉREBRO (CALCULADORA) ---
    def gerar_intervalos(self):
        # Função auxiliar para evitar erro se o banco retornar 'time' em vez de 'datetime'
        def extrair_tempo(val):
            if hasattr(val, 'time'): return val.time() # É datetime
            return val # Já é time
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
        popup.geometry("450x550")

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
            if getattr(dados_atuais, 'HorarioEntrada', None): e_ent.insert(0, dados_atuais.HorarioEntrada.strftime('%H:%M'))
            if getattr(dados_atuais, 'HorarioSaida', None): e_sai.insert(0, dados_atuais.HorarioSaida.strftime('%H:%M'))
            if getattr(dados_atuais, 'InicioIntervalo', None): e_int_ini.insert(0, dados_atuais.InicioIntervalo.strftime('%H:%M'))
            if getattr(dados_atuais, 'FimIntervalo', None): e_int_fim.insert(0, dados_atuais.FimIntervalo.strftime('%H:%M'))
        else:
            e_ent.insert(0, "08:00"); e_sai.insert(0, "18:00")

        ttk.Label(popup, text="Foco do Dia:").pack(anchor=tk.W, padx=10)
        txt_foco = tk.Text(popup, height=5, width=40); txt_foco.pack(padx=10, pady=5)
        if dados_atuais and dados_atuais.FocoDoDia: txt_foco.insert("1.0", dados_atuais.FocoDoDia)

        def salvar():
            def tratar_vazio(valor): return valor if valor and valor.strip() else None
            selecao = combo_pessoas.get()
            if not selecao: return 
            if selecao == "(Vazio)": func_id = None; free_id = None
            else:
                d = mapa_ids[selecao]
                func_id = d['id'] if d['tipo'] == 'func' else None
                free_id = d['id'] if d['tipo'] == 'free' else None

            database.salvar_escala_dia(self.data_selecionada, pos_id, func_id, free_id,
                tratar_vazio(e_ent.get()), tratar_vazio(e_sai.get()), 
                tratar_vazio(e_int_ini.get()), tratar_vazio(e_int_fim.get()),
                txt_foco.get("1.0", tk.END).strip())
            popup.destroy(); self.carregar_escala_do_dia()

        def enviar_zap():
            selecao = combo_pessoas.get()
            if not selecao or selecao == "(Vazio)": return
            d = mapa_ids.get(selecao)
            tel = d.get('tel') if d else None
            if not tel and pessoa_tel: tel = pessoa_tel
            if tel:
                msg = f"Escala {self.data_selecionada}: {nome_pos} ({e_ent.get()}-{e_sai.get()}). Intervalo: {e_int_ini.get()}-{e_int_fim.get()}"
                # Correção: Executa o regex fora da f-string para evitar SyntaxError com a barra invertida
                numeros_limpos = re.sub(r'\D', '', tel)
                webbrowser.open(f"https://wa.me/55{numeros_limpos}?text={urllib.parse.quote(msg)}")

        ttk.Button(popup, text="💾 Salvar", command=salvar).pack(pady=10)
        ttk.Button(popup, text="📱 WhatsApp", command=enviar_zap).pack(pady=5)

if __name__ == "__main__":
    root = tk.Tk()
    app = AppEscalaLoja(root)
    root.mainloop()

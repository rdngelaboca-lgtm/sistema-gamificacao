import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
from tkcalendar import DateEntry
from PIL import Image, ImageTk
import database
import os
import webbrowser
import urllib.parse
from datetime import datetime

class AppEscalaLoja:
    def __init__(self, root):
        self.root = root
        self.root.title("Gestão de Escala Visual - Mapa da Loja")
        self.root.geometry("1100x700")

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

        # --- Controles do Topo ---
        ttk.Label(self.frame_topo, text="Data da Escala:").pack(side=tk.LEFT, padx=5)
        self.date_entry = DateEntry(self.frame_topo, width=12, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_entry.pack(side=tk.LEFT, padx=5)
        self.date_entry.bind("<<DateEntrySelected>>", self.carregar_escala_do_dia)

        ttk.Separator(self.frame_topo, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        self.btn_modo = ttk.Button(self.frame_topo, text="🔧 Ativar Modo Configuração (Criar Posições)", command=self.alternar_modo)
        self.btn_modo.pack(side=tk.LEFT, padx=5)
        
        self.lbl_legenda = ttk.Label(self.frame_topo, text="Modo: ESCALAÇÃO (Clique para escalar)", foreground="green", font=("Arial", 10, "bold"))
        self.lbl_legenda.pack(side=tk.LEFT, padx=10)

        ttk.Button(self.frame_topo, text="👤 Novo Freelancer", command=self.cadastrar_freelancer).pack(side=tk.RIGHT, padx=5)

        # --- Canvas do Mapa ---
        self.canvas = tk.Canvas(self.frame_mapa, bg="#e0e0e0", cursor="hand2")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.clique_no_mapa) 
        self.canvas.bind("<Button-3>", self.clique_direito_mapa) 

        # Inicialização atrasada para garantir carregamento da UI
        self.root.after(200, self.inicializar)

    def inicializar(self):
        self.carregar_imagem_mapa()
        self.carregar_escala_do_dia()

    def carregar_imagem_mapa(self):
        """Carrega a imagem de fundo."""
        caminho_img = "layout_loja.png"
        if not os.path.exists(caminho_img):
            self.canvas.create_text(500, 300, text=f"ERRO: Imagem '{caminho_img}' não encontrada!", fill="red", font=("Arial", 16))
            return

        try:
            pil_img = Image.open(caminho_img)
            largura_display = 1080
            altura_display = 600
            pil_img.thumbnail((largura_display, altura_display), Image.Resampling.LANCZOS)
            
            self.tk_img = ImageTk.PhotoImage(pil_img)
            # Tag 'fundo' é crucial para o ordenamento
            self.canvas.create_image(largura_display/2, altura_display/2, image=self.tk_img, anchor=tk.CENTER, tags="fundo")
        except Exception as e:
            messagebox.showerror("Erro Imagem", f"Falha ao carregar imagem: {e}")

    def carregar_escala_do_dia(self, event=None):
        """Recarrega dados e redesenha."""
        self.data_selecionada = self.date_entry.get_date().strftime('%Y-%m-%d')
        try:
            self.posicoes = database.listar_posicoes_loja()
            self.escala_atual = database.buscar_escala_do_dia(self.data_selecionada)
            self.redesenhar_marcadores()
        except Exception as e:
            print(f"Erro ao carregar dados do banco: {e}")

    def redesenhar_marcadores(self):
        """Desenha as bolinhas. Blindado contra erros de dados."""
        self.canvas.delete("marcador")
        self.canvas.delete("texto_marcador")

        dia_semana_hoje = datetime.strptime(self.data_selecionada, '%Y-%m-%d').isoweekday() + 1
        if dia_semana_hoje == 8: dia_semana_hoje = 1

        for pos in self.posicoes:
            try:
                # Desempacotamento seguro (pega pelo índice para evitar erro se vierem colunas extras)
                pos_id = pos[0]
                nome = pos[1]
                # CONVERSÃO FORÇADA PARA FLOAT (Corrige o problema silencioso)
                x = float(pos[2])
                y = float(pos[3])
                
                ocupado = False
                nome_pessoa = "Vazio"
                cor = "#ff4444" # Vermelho

                if pos_id in self.escala_atual:
                    dados = self.escala_atual[pos_id]
                    nome_pessoa = dados.NomePessoa if dados.NomePessoa else "Erro Nome"
                    ocupado = True
                    cor = "#00C851" # Verde
                
                elif not self.modo_edicao:
                    func_padrao = database.buscar_funcionarios_com_posicao_padrao(pos_id)
                    if func_padrao:
                        f_id, f_nome, f_folga = func_padrao
                        if str(f_folga) != str(dia_semana_hoje):
                            nome_pessoa = f"{f_nome} (Fixo)"
                            cor = "#33b5e5" # Azul

                # Desenha a bolinha
                raio = 15
                self.canvas.create_oval(x-raio, y-raio, x+raio, y+raio, fill=cor, outline="white", width=2, tags=("marcador", f"pos_{pos_id}"))
                
                # Desenha o texto
                label_texto = f"{nome}\n{nome_pessoa}"
                self.canvas.create_text(x, y+25, text=label_texto, fill="black", font=("Arial", 8, "bold"), justify=tk.CENTER, tags=("texto_marcador"))
            
            except Exception as e:
                print(f"Erro ao desenhar posição {pos}: {e}")
                # Se der erro em uma, continua tentando desenhar as outras
                continue
        
        # REFORÇA A ORDEM DAS CAMADAS
        self.canvas.tag_lower("fundo")      # Manda a imagem para o fundo
        self.canvas.tag_raise("marcador")   # Traz as bolinhas para frente
        self.canvas.tag_raise("texto_marcador") # Traz o texto para frente de tudo

    def clique_no_mapa(self, event):
        x, y = event.x, event.y
        
        if self.modo_edicao:
            # Verifica sobreposição
            itens = self.canvas.find_overlapping(x-10, y-10, x+10, y+10)
            for item in itens:
                tags = self.canvas.gettags(item)
                if "marcador" in tags:
                    messagebox.showinfo("Aviso", "Já existe uma posição aqui.")
                    return

            nome = simpledialog.askstring("Nova Posição", "Nome do local (ex: Caixa 1):")
            if nome:
                # Salva no banco
                sucesso = database.criar_posicao_loja(nome, x, y)
                if sucesso:
                    # Recarrega imediatamente para mostrar a bolinha nova
                    self.carregar_escala_do_dia()
                    # Feedback visual forçado
                    self.canvas.update_idletasks()
                else:
                    messagebox.showerror("Erro", "Falha ao salvar no banco de dados.")
        else:
            # Modo Escalar (Click na bolinha)
            itens = self.canvas.find_overlapping(x-10, y-10, x+10, y+10)
            for item in itens:
                tags = self.canvas.gettags(item)
                for tag in tags:
                    if tag.startswith("pos_"):
                        pos_id = int(tag.split("_")[1])
                        self.abrir_janela_escalacao(pos_id)
                        return

    def clique_direito_mapa(self, event):
        if not self.modo_edicao: return
        itens = self.canvas.find_overlapping(event.x-10, event.y-10, event.x+10, event.y+10)
        for item in itens:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("pos_"):
                    pos_id = int(tag.split("_")[1])
                    if messagebox.askyesno("Excluir", "Remover esta posição do mapa?"):
                        database.excluir_posicao_loja(pos_id)
                        self.carregar_escala_do_dia()

    def alternar_modo(self):
        self.modo_edicao = not self.modo_edicao
        if self.modo_edicao:
            self.btn_modo.config(text="✅ Salvar e Voltar para Escalação")
            self.lbl_legenda.config(text="Modo: CONFIGURAÇÃO (Clique no mapa para adicionar locais)", foreground="red")
            self.canvas.config(cursor="cross")
        else:
            self.btn_modo.config(text="🔧 Ativar Modo Configuração")
            self.lbl_legenda.config(text="Modo: ESCALAÇÃO (Clique nas bolinhas para escalar)", foreground="green")
            self.canvas.config(cursor="hand2")
            self.carregar_escala_do_dia()

    def cadastrar_freelancer(self):
        nome = simpledialog.askstring("Novo Freelancer", "Nome Completo:")
        if nome:
            tel = simpledialog.askstring("Contato", "Telefone (WhatsApp):")
            if tel:
                database.criar_freelancer(nome, tel)
                messagebox.showinfo("Sucesso", "Freelancer cadastrado!")

    def abrir_janela_escalacao(self, pos_id):
        try:
            # Busca nome de forma segura
            dados_pos = next((p for p in self.posicoes if p[0] == pos_id), None)
            if not dados_pos: return
            nome_pos = dados_pos[1]
        except StopIteration:
            return 
        
        popup = Toplevel(self.root)
        popup.title(f"Escalar: {nome_pos} - {self.data_selecionada}")
        popup.geometry("450x550")

        dados_atuais = self.escala_atual.get(pos_id)
        
        ttk.Label(popup, text="Quem vai trabalhar aqui?").pack(pady=5)
        combo_pessoas = ttk.Combobox(popup, width=40)
        combo_pessoas.pack()
        
        mapa_ids = {} 
        lista_nomes = ["(Vazio)"]
        
        for f in database.listar_funcionarios():
            label = f"[Fixo] {f.NomeCompleto}"
            lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'func', 'id': f.FuncionarioID, 'tel': f.ChatIDTelegram}
            
        for fr in database.listar_freelancers():
            label = f"[Free] {fr.Nome}"
            lista_nomes.append(label)
            mapa_ids[label] = {'tipo': 'free', 'id': fr.FreelancerID, 'tel': fr.Telefone}

        combo_pessoas['values'] = lista_nomes
        
        pessoa_selecionada_tel = None
        if dados_atuais:
            if dados_atuais.FuncionarioID:
                match = next((k for k, v in mapa_ids.items() if v['tipo'] == 'func' and v['id'] == dados_atuais.FuncionarioID), "")
                combo_pessoas.set(match)
            elif dados_atuais.FreelancerID:
                match = next((k for k, v in mapa_ids.items() if v['tipo'] == 'free' and v['id'] == dados_atuais.FreelancerID), "")
                combo_pessoas.set(match)
                pessoa_selecionada_tel = dados_atuais.TelefonePessoa

        frame_hor = ttk.LabelFrame(popup, text="Horários", padding=10)
        frame_hor.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(frame_hor, text="Entrada:").grid(row=0, column=0); e_ent = ttk.Entry(frame_hor, width=8); e_ent.grid(row=0, column=1)
        ttk.Label(frame_hor, text="Saída:").grid(row=0, column=2); e_sai = ttk.Entry(frame_hor, width=8); e_sai.grid(row=0, column=3)
        ttk.Label(frame_hor, text="Intervalo Início:").grid(row=1, column=0); e_int_ini = ttk.Entry(frame_hor, width=8); e_int_ini.grid(row=1, column=1)
        ttk.Label(frame_hor, text="Intervalo Fim:").grid(row=1, column=2); e_int_fim = ttk.Entry(frame_hor, width=8); e_int_fim.grid(row=1, column=3)

        if dados_atuais:
            if dados_atuais.HorarioEntrada: e_ent.insert(0, dados_atuais.HorarioEntrada.strftime('%H:%M'))
            if dados_atuais.HorarioSaida: e_sai.insert(0, dados_atuais.HorarioSaida.strftime('%H:%M'))
            if dados_atuais.InicioIntervalo: e_int_ini.insert(0, dados_atuais.InicioIntervalo.strftime('%H:%M'))
            if dados_atuais.FimIntervalo: e_int_fim.insert(0, dados_atuais.FimIntervalo.strftime('%H:%M'))
        else:
            e_ent.insert(0, "08:00"); e_sai.insert(0, "18:00")

        ttk.Label(popup, text="Foco do Dia / Instruções (Vai no Zap):").pack(anchor=tk.W, padx=10)
        txt_foco = tk.Text(popup, height=5, width=40)
        txt_foco.pack(padx=10, pady=5)
        if dados_atuais and dados_atuais.FocoDoDia:
            txt_foco.insert("1.0", dados_atuais.FocoDoDia)

        def salvar():
            selecao = combo_pessoas.get()
            if not selecao or selecao == "(Vazio)": return 
            
            dados_pessoa = mapa_ids[selecao]
            func_id = dados_pessoa['id'] if dados_pessoa['tipo'] == 'func' else None
            free_id = dados_pessoa['id'] if dados_pessoa['tipo'] == 'free' else None
            
            sucesso = database.salvar_escala_dia(
                self.data_selecionada, pos_id, func_id, free_id,
                e_ent.get(), e_sai.get(), e_int_ini.get(), e_int_fim.get(),
                txt_foco.get("1.0", tk.END).strip()
            )
            
            if sucesso:
                popup.destroy()
                self.carregar_escala_do_dia()
            else:
                messagebox.showerror("Erro", "Erro ao salvar.")

        def enviar_zap():
            selecao = combo_pessoas.get()
            if not selecao: return
            dados_pessoa = mapa_ids.get(selecao)
            
            telefone = dados_pessoa.get('tel')
            if not telefone and pessoa_selecionada_tel: telefone = pessoa_selecionada_tel
            
            if not telefone:
                messagebox.showwarning("Sem Telefone", "Esta pessoa não tem telefone cadastrado.")
                return
                
            texto_msg = (
                f"Olá *{selecao.split('] ')[1]}*, confirmo sua escala para *{self.data_selecionada}* na Gela Boca.\n\n"
                f"📍 *Local:* {nome_pos}\n"
                f"🕒 *Horário:* {e_ent.get()} às {e_sai.get()}\n"
                f"🍽️ *Intervalo:* {e_int_ini.get()} às {e_int_fim.get()}\n\n"
                f"🎯 *Foco do dia:* {txt_foco.get('1.0', tk.END).strip()}\n\n"
                "Por favor, confirme o recebimento. Bom trabalho! 🍦"
            )
            
            link = f"https://wa.me/55{telefone.replace(' ', '').replace('-', '')}?text={urllib.parse.quote(texto_msg)}"
            webbrowser.open(link)

        btn_frame = ttk.Frame(popup)
        btn_frame.pack(fill=tk.X, pady=20, padx=10)
        ttk.Button(btn_frame, text="💾 Salvar Escala", command=salvar).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(btn_frame, text="📱 Enviar WhatsApp", command=enviar_zap).pack(side=tk.LEFT, padx=5)

if __name__ == "__main__":
    root = tk.Tk()
    app = AppEscalaLoja(root)
    root.mainloop()

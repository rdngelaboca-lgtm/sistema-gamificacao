# comunicado_generator.py (Versão Final, Corrigida e Mais Segura)
from fpdf import FPDF
from datetime import datetime
import os

class PDFComunicado(FPDF):
    def __init__(self, titulo_doc):
        super().__init__()
        self.titulo_doc = titulo_doc

    def header(self):
        self.set_font('Arial', 'B', 14)
        # --- CORREÇÃO APLICADA AQUI ---
        # Usando argumentos nomeados para clareza e compatibilidade
        self.multi_cell(w=0, h=10, text='COMUNICADO INTERNO', border=0, align='C', ln=1)
        
        self.set_font('Arial', 'B', 12)
        # --- E CORREÇÃO APLICADA AQUI TAMBÉM ---
        self.multi_cell(w=0, h=10, text=self.titulo_doc, border=0, align='C', ln=1)
        
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        # Boa prática: vamos usar argumentos nomeados aqui também
        self.cell(w=0, h=10, text=f'Página {self.page_no()}', border=0, align='C', ln=0)

def gerar_comunicado_pdf(titulo, conteudo):
    try:
        # Com a fpdf2, o texto em português funciona diretamente
        pdf = PDFComunicado(titulo_doc=titulo)
        pdf.add_page()
        pdf.set_font('Arial', '', 12)
        
        # E aqui também, para consistência
        pdf.multi_cell(w=0, h=10, text=conteudo, border=0, align='J', ln=1)
        pdf.ln(10)

        pasta_temporaria = 'temp_comunicados'
        if not os.path.exists(pasta_temporaria):
            os.makedirs(pasta_temporaria)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_arquivo = f"comunicado_{timestamp}.pdf"
        
        caminho_relativo = os.path.join(pasta_temporaria, nome_arquivo)
        caminho_absoluto = os.path.abspath(caminho_relativo)

        pdf.output(caminho_absoluto)
        print(f"--> [PDF COMUNICADO] Gerado com sucesso em: {caminho_absoluto}")
        return caminho_absoluto

    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar o PDF do comunicado com fpdf2: {e}")
        return None
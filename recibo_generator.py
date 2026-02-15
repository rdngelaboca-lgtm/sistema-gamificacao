<<<<<<< HEAD
# recibo_generator.py
from fpdf import FPDF
from datetime import datetime
import os

class PDF(FPDF):
    def header(self):
        # Logo ou Título (opcional)
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Recibo de Ciência de Comunicado Interno', 0, 1, 'C')
        self.ln(10) # Pular uma linha

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def gerar_recibo_pdf(assinatura_id, nome_funcionario, titulo_doc, conteudo_doc, data_ciencia):
    """
    Gera um recibo em PDF com os detalhes da ciência do comunicado.
    """
    # --- Configuração Inicial ---
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', '', 12)

    # --- Dados do Funcionário ---
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(40, 10, 'Funcionário:')
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, nome_funcionario)
    pdf.ln()

    # --- Dados do Comunicado ---
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(40, 10, 'Comunicado:')
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, titulo_doc)
    pdf.ln(15)

    # --- Conteúdo do Comunicado ---
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'Conteúdo do Comunicado', 0, 1, 'C')
    pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # Linha separadora
    pdf.ln(5)

    pdf.set_font('Arial', '', 12)
    # multi_cell é usado para textos longos que quebram a linha automaticamente
    pdf.multi_cell(0, 10, conteudo_doc)
    pdf.ln(10)

    # --- Confirmação de Ciência ---
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'Confirmação de Ciência', 0, 1, 'C')
    pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # Linha separadora
    pdf.ln(5)

    texto_confirmacao = (
        f"Eu, {nome_funcionario}, confirmo que recebi, li e estou ciente do conteúdo "
        f"do comunicado supracitado."
    )
    pdf.set_font('Arial', 'I', 12)
    pdf.multi_cell(0, 10, texto_confirmacao, 0, 'C')
    pdf.ln(10)

    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, f"Protocolo de Confirmação: {assinatura_id}", 0, 1, 'C')
    pdf.cell(0, 10, f"Data e Hora da Confirmação: {data_ciencia.strftime('%d/%m/%Y às %H:%M:%S')}", 0, 1, 'C')

    # --- Salvando o arquivo ---
    # --- Salvando o arquivo ---
    if not os.path.exists('recibos'):
        os.makedirs('recibos')

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 1. Montamos o caminho relativo como antes
    relative_path = f"recibos/recibo_{assinatura_id}_{timestamp}.pdf"

    # 2. A MÁGICA: Convertemos para um caminho absoluto e sem ambiguidades
    absolute_path = os.path.abspath(relative_path)

    # 3. Usamos o caminho absoluto para salvar o arquivo
    pdf.output(absolute_path)

    print(f"--> [PDF] Recibo gerado com sucesso em: {absolute_path}")
    # 4. Retornamos o caminho absoluto para a outra função usar
    return absolute_path
=======
# recibo_generator.py
from fpdf import FPDF
from datetime import datetime
import os

class PDF(FPDF):
    def header(self):
        # Logo ou Título (opcional)
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Recibo de Ciência de Comunicado Interno', 0, 1, 'C')
        self.ln(10) # Pular uma linha

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def gerar_recibo_pdf(assinatura_id, nome_funcionario, titulo_doc, conteudo_doc, data_ciencia):
    """
    Gera um recibo em PDF com os detalhes da ciência do comunicado.
    """
    # --- Configuração Inicial ---
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', '', 12)

    # --- Dados do Funcionário ---
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(40, 10, 'Funcionário:')
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, nome_funcionario)
    pdf.ln()

    # --- Dados do Comunicado ---
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(40, 10, 'Comunicado:')
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, titulo_doc)
    pdf.ln(15)

    # --- Conteúdo do Comunicado ---
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'Conteúdo do Comunicado', 0, 1, 'C')
    pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # Linha separadora
    pdf.ln(5)

    pdf.set_font('Arial', '', 12)
    # multi_cell é usado para textos longos que quebram a linha automaticamente
    pdf.multi_cell(0, 10, conteudo_doc)
    pdf.ln(10)

    # --- Confirmação de Ciência ---
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'Confirmação de Ciência', 0, 1, 'C')
    pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # Linha separadora
    pdf.ln(5)

    texto_confirmacao = (
        f"Eu, {nome_funcionario}, confirmo que recebi, li e estou ciente do conteúdo "
        f"do comunicado supracitado."
    )
    pdf.set_font('Arial', 'I', 12)
    pdf.multi_cell(0, 10, texto_confirmacao, 0, 'C')
    pdf.ln(10)

    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, f"Protocolo de Confirmação: {assinatura_id}", 0, 1, 'C')
    pdf.cell(0, 10, f"Data e Hora da Confirmação: {data_ciencia.strftime('%d/%m/%Y às %H:%M:%S')}", 0, 1, 'C')

    # --- Salvando o arquivo ---
    # --- Salvando o arquivo ---
    if not os.path.exists('recibos'):
        os.makedirs('recibos')

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 1. Montamos o caminho relativo como antes
    relative_path = f"recibos/recibo_{assinatura_id}_{timestamp}.pdf"

    # 2. A MÁGICA: Convertemos para um caminho absoluto e sem ambiguidades
    absolute_path = os.path.abspath(relative_path)

    # 3. Usamos o caminho absoluto para salvar o arquivo
    pdf.output(absolute_path)

    print(f"--> [PDF] Recibo gerado com sucesso em: {absolute_path}")
    # 4. Retornamos o caminho absoluto para a outra função usar
    return absolute_path
>>>>>>> master

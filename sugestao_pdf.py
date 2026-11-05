# ==============================================================================
# == sugestao_pdf.py - 🖨️ Relatório da Sugestão de Compra em PDF (aba 5 do Gestão de Estoque) ==
# ==============================================================================
# Monta um PDF (A4 deitado) com o que está na tabela da aba 5, na mesma ordem e com os mesmos filtros:
#   cabeçalho (parâmetros e filtros), resumo (críticos, para comprar, pedido estimado), a tabela colorida como na
#   tela (com uma coluna "Ok" em branco para marcar no papel), o total e, se escolher, separado por fornecedor
#   (com subtotal) e com o "como calculei" de cada produto.
# Usa a biblioteca fpdf (a mesma do recibo e do DANFE). Funciona com a fpdf antiga (1.7) e com a fpdf2.
# As fontes padrão do PDF só têm letras do português (latin-1): os emojis da tela viram texto.
# ==============================================================================
import os
import re
from datetime import datetime
from decimal import Decimal

CORES = {'critico': (255, 214, 214), 'comprar': (255, 244, 204), 'ok': (227, 245, 225), 'conferir': (255, 224, 178),
         'nunca': (227, 238, 252), 'sem_giro': (238, 238, 238)}
ORDEM_SITUACAO = [('critico', 'crítico(s)'), ('comprar', 'para comprar'), ('ok', 'ok'), ('conferir', 'conferir'),
                  ('sem_giro', 'sem giro'), ('nunca', 'nunca contado(s)')]
# (título, largura em mm, alinhamento) — A4 deitado: 297 - 2 x 10 de margem = 277 mm
COLUNAS = [('Produto', 62, 'L'), ('UN', 9, 'C'), ('Últ. contagem', 19, 'C'), ('Estoque hoje', 19, 'R'),
           ('Consumo/mês', 19, 'R'), ('Acaba em', 19, 'C'), ('Sugestão', 16, 'R'), ('Pedir', 31, 'L'),
           ('Fornecedor', 30, 'L'), ('Custo', 19, 'R'), ('Situação', 26, 'L'), ('Ok', 8, 'C')]
TROCAS = {'—': '-', '–': '-', '≈': '~', '…': '...', '→': '->', '×': 'x', '“': '"', '”': '"', '‘': "'", '’': "'",
          '📏': '*', ' ': ' '}


class ErroPdf(Exception):
    pass


def texto_pdf(valor):
    """O texto como as fontes padrão do PDF aceitam: troca os símbolos da tela e tira os emojis."""
    s = str(valor if valor is not None else '')
    for a, b in TROCAS.items():
        s = s.replace(a, b)
    s = s.encode('latin-1', 'ignore').decode('latin-1')    # emojis e símbolos de fora saem
    return re.sub(r'\s{2,}', ' ', s).strip()


def reais(valor):
    v = Decimal(str(valor or 0)).quantize(Decimal('0.01'))
    return "R$ " + f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _classe_fpdf():
    try:
        from fpdf import FPDF
    except ImportError:
        raise ErroPdf("Falta a biblioteca do PDF. No terminal, rode:\n\n    pip install fpdf2\n\ne abra o programa de novo.")
    return FPDF


def gerar(caminho, cabecalho, linhas, separar_fornecedor=False, incluir_calculo=False, empresa='', agora=None):
    """
    caminho: onde salvar o PDF.
    cabecalho: {'titulo', 'parametros': [texto], 'filtros': [texto], 'avisos': [texto]}
    linhas: na ordem da tela, cada uma {'colunas': (os 10 valores da tabela), 'tag', 'custo', 'fornecedor', 'explicacao': [..]}
    Devolve {'caminho', 'paginas', 'itens', 'total'}.
    """
    FPDF = _classe_fpdf()
    agora = agora or datetime.now()
    rodape = texto_pdf(f"{empresa + ' - ' if empresa else ''}Sugestão de Compra - gerado em {agora:%d/%m/%Y %H:%M}")

    class Relatorio(FPDF):
        def footer(self):
            self.set_y(-9)
            self.set_font('Helvetica', 'I', 7)
            self.set_text_color(120, 120, 120)
            self.cell((self.w - 20) / 2, 4, rodape, 0, 0, 'L')
            self.cell(0, 4, texto_pdf(f"Página {self.page_no()} de {{nb}}"), 0, 0, 'R')

    pdf = Relatorio(orientation='L', unit='mm', format='A4')
    try:
        pdf.alias_nb_pages()
    except Exception:
        pass
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(False)
    pdf.add_page()
    limite = pdf.h - 13                                   # deixa lugar para o rodapé
    colunas = [c for c in COLUNAS if not (separar_fornecedor and c[0] == 'Fornecedor')]
    if separar_fornecedor:                               # sem a coluna do fornecedor, o produto ganha o espaço
        colunas = [(t, w + 30 if t == 'Produto' else w, a) for t, w, a in colunas]

    def caber(texto, largura):
        """Corta o texto para caber na coluna (com '...')."""
        texto = texto_pdf(texto)
        if pdf.get_string_width(texto) <= largura - 1.6:
            return texto
        while texto and pdf.get_string_width(texto + '...') > largura - 1.6:
            texto = texto[:-1]
        return texto.rstrip() + '...'

    def cabecalho_tabela():
        pdf.set_font('Helvetica', 'B', 7.5)
        pdf.set_fill_color(46, 74, 98)
        pdf.set_text_color(255, 255, 255)
        pdf.set_draw_color(200, 200, 200)
        for titulo, largura, alinha in colunas:
            pdf.cell(largura, 6, texto_pdf(titulo), 1, 0, 'C', True)
        pdf.ln(6)
        pdf.set_text_color(0, 0, 0)

    def texto_longo(altura, texto):
        """Texto que quebra linha. A fpdf2 deixa o cursor no fim da linha (a 1.7 volta para a margem): volta sempre."""
        pdf.multi_cell(0, altura, texto, 0, 'L')
        pdf.set_x(pdf.l_margin)

    def precisa_de(altura, repetir_cabecalho=True):
        if pdf.get_y() + altura > limite:
            pdf.add_page()
            if repetir_cabecalho:
                cabecalho_tabela()

    # ---- topo: título, parâmetros, filtros e resumo
    pdf.set_font('Helvetica', 'B', 15)
    pdf.set_text_color(31, 52, 70)
    pdf.cell(0, 8, texto_pdf(cabecalho.get('titulo') or 'Sugestão de Compra'), 0, 1, 'L')
    pdf.set_text_color(60, 60, 60)
    pdf.set_font('Helvetica', '', 8.5)
    for rotulo, chave in (('Parâmetros', 'parametros'), ('Filtros', 'filtros')):
        itens = [texto_pdf(x) for x in cabecalho.get(chave) or [] if texto_pdf(x)]
        if itens:
            pdf.set_font('Helvetica', 'B', 8.5)
            pdf.cell(20, 4.6, texto_pdf(rotulo + ':'), 0, 0, 'L')
            pdf.set_font('Helvetica', '', 8.5)
            texto_longo(4.6, '   |   '.join(itens))
    contagem = {tag: 0 for tag, _ in ORDEM_SITUACAO}
    total = Decimal('0')
    for l in linhas:
        contagem[l.get('tag')] = contagem.get(l.get('tag'), 0) + 1
        total += Decimal(str(l.get('custo') or 0))
    resumo = '  ·  '.join(f"{contagem[t]} {nome}" for t, nome in ORDEM_SITUACAO if contagem.get(t))
    pdf.ln(1)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, texto_pdf(f"{len(linhas)} produto(s):  {resumo}       Pedido estimado: {reais(total)}"), 0, 1, 'L')
    pdf.set_font('Helvetica', 'I', 7.5)
    pdf.set_text_color(178, 106, 0)
    for aviso in cabecalho.get('avisos') or []:
        if texto_pdf(aviso):
            texto_longo(4, texto_pdf(aviso))
    pdf.set_text_color(110, 110, 110)
    texto_longo(4, texto_pdf("* = produto não contado no Ponto B (vale a última contagem dele + compras - consumo)   "
                             "~ = consumo estimado pelas compras (só 1 contagem)   Ok = para marcar no papel quando pedir"))
    pdf.ln(2)

    # ---- a tabela (ou um bloco por fornecedor)
    if separar_fornecedor:
        grupos, ordem = {}, []
        for l in linhas:
            nome = l.get('fornecedor') or 'Sem fornecedor definido'
            if nome not in grupos:
                grupos[nome] = []
                ordem.append(nome)
            grupos[nome].append(l)
        blocos = [(nome, grupos[nome]) for nome in ordem]
    else:
        blocos = [(None, linhas)]

    def linha_tabela(l):
        valores = list(l.get('colunas') or ())
        valores = (valores + [''] * 10)[:10]
        dados = {'Produto': valores[0], 'UN': valores[1], 'Últ. contagem': valores[2], 'Estoque hoje': valores[3],
                 'Consumo/mês': valores[4], 'Acaba em': valores[5], 'Sugestão': valores[6], 'Pedir': valores[7],
                 'Fornecedor': valores[8], 'Custo': reais(l.get('custo')) if Decimal(str(l.get('custo') or 0)) > 0 else '',
                 'Situação': valores[9], 'Ok': ''}
        explicacao = [texto_pdf(x) for x in (l.get('explicacao') or [])[1:] if texto_pdf(x)] if incluir_calculo else []
        altura_exp = 3.4 * len(explicacao) + (1 if explicacao else 0)
        precisa_de(5.4 + altura_exp)
        pdf.set_fill_color(*CORES.get(l.get('tag'), (255, 255, 255)))
        negrito = l.get('tag') == 'critico'
        for titulo, largura, alinha in colunas:
            pdf.set_font('Helvetica', 'B' if negrito and titulo in ('Produto', 'Pedir', 'Situação') else '', 7.5)
            pdf.cell(largura, 5.4, caber(dados[titulo], largura), 1, 0, alinha, True)
        pdf.ln(5.4)
        if explicacao:
            pdf.set_font('Helvetica', '', 6.5)
            pdf.set_text_color(90, 90, 90)
            for texto in explicacao:
                pdf.set_x(pdf.l_margin + 4)
                pdf.cell(0, 3.4, caber(texto, sum(c[1] for c in colunas) - 4), 0, 1, 'L')
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)

    for nome, itens in blocos:
        if nome is not None:
            subtotal = sum((Decimal(str(l.get('custo') or 0)) for l in itens), Decimal('0'))
            precisa_de(7 + 6 + 5.4, repetir_cabecalho=False)
            pdf.ln(1.5)
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_fill_color(227, 234, 241)
            pdf.cell(0, 6.5, texto_pdf(f"{nome}   -   {len(itens)} item(ns)   -   {reais(subtotal)}"), 0, 1, 'L', True)
        cabecalho_tabela()
        for l in itens:
            linha_tabela(l)
    precisa_de(8, repetir_cabecalho=False)
    pdf.ln(2)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(sum(c[1] for c in colunas), 6, texto_pdf(f"Total do pedido estimado: {reais(total)}"), 0, 1, 'R')

    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    pdf.output(caminho)
    return {'caminho': caminho, 'paginas': pdf.page_no(), 'itens': len(linhas), 'total': total}

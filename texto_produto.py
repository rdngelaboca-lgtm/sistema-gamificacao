# -*- coding: utf-8 -*-
"""
Textos de produto compartilhados (programa do Estoque e Cadastro na Franquia).

sugerir_nome_limpo: o nome do XML do fornecedor ("003 FERRERO ROCHER T3X16....%AGR: 2") vira um
nome de cadastro ("Ferrero Rocher T3X16"). Antes ficava dentro do gestao_estoque_main.py.
"""
import re

_PALAVRAS_MINUSCULAS = {'de', 'da', 'do', 'das', 'dos', 'com', 'sem', 'e', 'em', 'a', 'o', 'ao', 'na', 'no', 'p/', 'c/', 's/'}
_SIGLAS_MAIUSCULAS = {'KG', 'G', 'GR', 'ML', 'L', 'LT', 'UN', 'UND', 'PCT', 'PC', 'CX', 'FD', 'DZ', 'PT', 'SC', 'TP', 'PET'}


def sugerir_nome_limpo(nome):
    """
    '003 FERRERO ROCHER T3X16..........01X37.5GR %AGR: 2'  ->  'Ferrero Rocher T3X16 01X37.5GR'
    '160068-BARBIE FAB BARBIE FASHION   BARBIE   12X'      ->  'Barbie Fab Barbie Fashion Barbie 12X'
    '232 - CARNE CONG. FRANGO S/O FILE'                    ->  'Carne Cong. Frango s/o File'
    Regras: tira o código numérico do início, as sequências de pontos, os textos técnicos do
    fornecedor (%AGR:, CXA:, ***), espaços repetidos, e deixa só a 1ª letra maiúscula.
    Palavras com números (12X, 5KG, T3X16) ficam como estão.
    """
    t = str(nome or '')
    t = re.split(r'%AGR:|\bCXA:|\bCX\.:', t, maxsplit=1, flags=re.IGNORECASE)[0]   # lixo técnico no fim
    t = re.sub(r'\*{2,}', ' ', t)                                                 # ***
    t = re.sub(r'\.{3,}', ' ', t)                                                 # ..........
    t = re.sub(r'^\s*\d{2,}\s*(?:-\s*|\s+)', '', t)                                # "003 " / "160068-" / "232 - "
    t = ' '.join(t.split()).strip(' -.:;')
    if not t:
        return str(nome or '').strip()
    palavras = []
    for i, p in enumerate(t.split(' ')):
        if any(ch.isdigit() for ch in p):
            palavras.append(p)
        elif p.upper() in _SIGLAS_MAIUSCULAS or ('/' in p and len(p) <= 4 and p.lower() not in _PALAVRAS_MINUSCULAS):
            palavras.append(p.upper())          # KG, UN, S/O, C/G ficam em maiúsculas
        elif i > 0 and p.lower() in _PALAVRAS_MINUSCULAS:
            palavras.append(p.lower())
        else:
            palavras.append(p[:1].upper() + p[1:].lower())
    return ' '.join(palavras)

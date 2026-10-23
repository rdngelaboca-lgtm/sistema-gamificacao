# ==============================================================================
# == tarefas_relatorio.py - 📋 Relatório dos modelos de tarefa (Gestão Web) =====
# ==============================================================================
# Todos os modelos do "Catálogo de Modelos de Tarefa" (tabela Tarefas, criados no programa da Gamificação) com o
# título, a descrição, o setor e os pontos, agrupados por setor. Só leitura: criar, editar e excluir continuam no
# programa. A página imprime (ou salva em PDF) e baixa a planilha do Excel (.xlsx).
# ==============================================================================
import re
from datetime import datetime

import database

SEM_SETOR = 'Sem setor'


def _ordem_natural(texto):
    """'Produção - 2º' antes de 'Produção - 10º' (a ordem do programa põe o 10º antes do 2º)."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', texto or '')]


def listar():
    conn = database.get_db_connection()
    if not conn:
        raise RuntimeError("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT TarefaID, Titulo, Descricao, Pontos, Setor FROM Tarefas")
        linhas = cur.fetchall()
    finally:
        conn.close()
    tarefas = [{'id': int(r[0]), 'titulo': ' '.join(str(r[1] or '').split()) or '(sem título)',
                'descricao': str(r[2] or '').replace('\r\n', '\n').strip(),
                'pontos': int(r[3] or 0), 'setor': ' '.join(str(r[4] or '').split()) or SEM_SETOR} for r in linhas]
    tarefas.sort(key=lambda t: (t['setor'] == SEM_SETOR, t['setor'].lower(), _ordem_natural(t['titulo'])))
    setores = []
    for t in tarefas:
        if not setores or setores[-1]['setor'] != t['setor']:
            setores.append({'setor': t['setor'], 'tarefas': []})
        setores[-1]['tarefas'].append(t)
    return {'setores': setores, 'total': len(tarefas), 'sem_descricao': sum(1 for t in tarefas if not t['descricao'])}


def planilha():
    """(conteúdo do .xlsx, nome do arquivo). Usa o mesmo gerador de planilha dos 💰 Pagamentos (sem openpyxl)."""
    from gestao_pagamentos import _xlsx
    linhas = [{'Setor': t['setor'], 'ID': t['id'], 'Título': t['titulo'], 'Descrição': t['descricao'], 'Pontos': t['pontos']}
              for s in listar()['setores'] for t in s['tarefas']]
    if not linhas:
        linhas = [{'Setor': '', 'ID': '', 'Título': '(nenhuma tarefa cadastrada)', 'Descrição': '', 'Pontos': ''}]
    return _xlsx(linhas, aba='Tarefas'), f"Tarefas_{datetime.now():%d-%m-%Y}.xlsx"

# ==============================================================================
# == INÍCIO BLOCO DE CONFIGURAÇÃO DE LOGGING (Igual ao anterior) ================
# ==============================================================================
import logging
import logging.handlers
import sys
import file_utils
import os

LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs'
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

log_dir = os.path.join(os.path.dirname(__file__), LOG_FOLDER)
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir)
        print(f"Pasta de logs criada em: {log_dir}")
    except OSError as e:
        print(f"Erro ao criar pasta de logs '{log_dir}': {e}", file=sys.stderr)
        log_dir = os.path.dirname(__file__)

log_filepath = os.path.join(log_dir, LOG_FILENAME)
file_handler = logging.handlers.RotatingFileHandler(
    log_filepath, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
)
file_handler.setLevel(LOG_LEVEL)
file_formatter = logging.Formatter(LOG_FORMAT)
file_handler.setFormatter(file_formatter)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL)
console_formatter = logging.Formatter(LOG_FORMAT)
console_handler.setFormatter(console_formatter)
logging.getLogger('').handlers = []
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[file_handler, console_handler])
logger = logging.getLogger(__name__)
logger.info(f"*** Logging configurado para o módulo: {__name__} ***")
# ==============================================================================
# == FIM BLOCO DE CONFIGURAÇÃO DE LOGGING ======================================
# ==============================================================================

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, Toplevel
import database # Importa nosso arquivo de banco de dados
import config
import json
import re
from datetime import datetime, date, timedelta
from tkcalendar import DateEntry
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# [DEPURAÇÃO] O "lxml" NÃO faz parte da lista de instalação do projeto. Antes, se ele
# não estivesse instalado, esta janela inteira não abria. Agora usamos o lxml se existir
# e, se não existir, o leitor de XML que já vem junto com o Python.
try:
    from lxml import etree as ET
    USANDO_LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    USANDO_LXML = False

PASTA_DO_PROGRAMA = os.path.dirname(os.path.abspath(__file__))


# ==============================================================================
# == [DEPURAÇÃO] FUNÇÕES AUXILIARES (números, datas e ordenação) ================
# ==============================================================================
def para_decimal(texto, nome_campo="valor", permitir_zero=True, permitir_negativo=False):
    """
    Converte o que o usuário digitou em número exato (Decimal).
    Aceita: 10   10.5   10,5   R$ 1.234,56   1,234.56
    Levanta ValueError com uma mensagem clara quando o valor é inválido.
    """
    bruto = str(texto if texto is not None else '').replace('R$', '').replace(' ', '').strip()
    if not bruto:
        raise ValueError(f"O campo '{nome_campo}' está vazio.")
    if ',' in bruto and '.' in bruto:
        # O separador que aparece por ÚLTIMO é o decimal (1.234,56 ou 1,234.56)
        if bruto.rfind(',') > bruto.rfind('.'):
            bruto = bruto.replace('.', '').replace(',', '.')
        else:
            bruto = bruto.replace(',', '')
    else:
        bruto = bruto.replace(',', '.')
    try:
        valor = Decimal(bruto)
    except InvalidOperation:
        raise ValueError(f"O campo '{nome_campo}' deve ser um número (ex: 15,50).")
    if not valor.is_finite():  # bloqueia 'NaN' e 'Infinity', que o Decimal aceitaria
        raise ValueError(f"O campo '{nome_campo}' deve ser um número (ex: 15,50).")
    if valor < 0 and not permitir_negativo:
        raise ValueError(f"O campo '{nome_campo}' não pode ser negativo.")
    if valor == 0 and not permitir_zero:
        raise ValueError(f"O campo '{nome_campo}' deve ser maior que zero.")
    return valor


def fmt_num(valor, casas=2, vazio="0"):
    """Formata número sem travar quando vem None (vazio) do banco."""
    if valor is None:
        return vazio
    try:
        return f"{Decimal(str(valor)):.{casas}f}"
    except (InvalidOperation, ValueError):
        return str(valor)


def fmt_data(valor, formato='%d/%m/%Y', vazio='--'):
    """Formata data que pode vir do banco como date, datetime, texto ou None."""
    if valor is None or valor == '':
        return vazio
    if hasattr(valor, 'strftime'):
        return valor.strftime(formato)
    texto = str(valor).strip()
    try:
        return datetime.fromisoformat(texto[:19]).strftime(formato)
    except ValueError:
        return texto[:10]


def data_de_texto_br(texto):
    """'31/01/2025' -> date(2025, 1, 31). Devolve None se não conseguir."""
    try:
        return datetime.strptime(str(texto).strip()[:10], '%d/%m/%Y').date()
    except ValueError:
        return None


def chave_ordenacao(texto):
    """
    [DEPURAÇÃO] Chave para ordenar colunas. Antes misturava número e texto na mesma
    coluna (ex: '1.5 meses' e 'Sem Giro'), o que dava TypeError e a ordenação não funcionava.
    Agora números vêm primeiro (em ordem numérica) e textos depois (em ordem alfabética).
    """
    m = re.match(r'^\s*(\d{2})/(\d{2})/(\d{4})', str(texto))
    if m:  # [MELHORIA SUGESTÃO] datas dd/mm/aaaa em ordem de calendário
        try:
            return (0, float(date(int(m.group(3)), int(m.group(2)), int(m.group(1))).toordinal()), '')
        except ValueError:
            pass
    limpo = str(texto).replace('R$', '').replace('meses', '').replace('>', '').replace('📏', '').replace('≈', '').strip()
    if ',' in limpo:  # formato brasileiro: 1.234,56
        limpo = limpo.replace('.', '').replace(',', '.')
    try:
        return (0, float(limpo), '')
    except ValueError:
        return (1, 0.0, str(texto).lower())


def nome_arquivo_seguro(nome):
    """Remove caracteres que o Windows não aceita em nomes de arquivo."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(nome)).strip(' .') or 'arquivo'


def so_digitos(texto):
    return re.sub(r'\D', '', str(texto or ''))


# ==============================================================================
# == [MELHORIA UX] FUNÇÕES AUXILIARES DAS MELHORIAS DE USABILIDADE =============
# ==============================================================================
import unicodedata
import math
import collections

ARQUIVO_RASCUNHO_CONTAGEM = os.path.join(PASTA_DO_PROGRAMA, 'rascunho_contagem.json')
ARQUIVO_PREFERENCIAS = os.path.join(PASTA_DO_PROGRAMA, 'estoque_preferencias.json')
PASTA_BACKUPS = os.path.join(PASTA_DO_PROGRAMA, 'backups_estoque')


def sem_acento(texto):
    """'Açaí Côco' -> 'acai coco' (para a busca achar com ou sem acento)."""
    t = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def linha_do_clique(tree, event=None):
    """
    [DEPURAÇÃO 2] Linha em que o usuário DEU o duplo clique. Antes usava tree.focus(): um
    duplo clique no CABEÇALHO (para ordenar) agia sobre a última linha clicada.
    Devolve '' quando o clique não foi numa linha.
    """
    if event is not None and hasattr(event, 'y'):
        try:
            linha = tree.identify_row(event.y)
        except Exception:
            linha = None
        if isinstance(linha, str):
            if linha:
                tree.focus(linha)
            return linha
    return tree.focus() or ''


def buscar_nomes(termo, nomes):
    """
    [MELHORIA UX] Busca "inteligente" usada na contagem:
      - ignora acentos e maiúsculas ("acai" acha "Açaí");
      - aceita várias palavras em qualquer ordem ("1kg choc" acha "Chocolate 1KG");
      - os nomes que COMEÇAM com o que foi digitado aparecem primeiro.
    """
    palavras = sem_acento(termo).split()
    if not palavras:
        return list(nomes)
    achados = [n for n in nomes if all(p in sem_acento(n) for p in palavras)]
    inicio = sem_acento(termo).strip()
    return sorted(achados, key=lambda n: (not sem_acento(n).startswith(inicio), sem_acento(n)))


def fmt_qtd(valor):
    """3.500 -> '3,5'   2.000 -> '2'   (quantidade no jeito brasileiro, sem zeros sobrando)."""
    try:
        v = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return str(valor)
    texto = f"{v:.3f}".rstrip('0').rstrip('.')
    return texto.replace('.', ',') if texto else '0'


def fmt_reais(valor):
    """1234.5 -> 'R$ 1.234,50'."""
    try:
        v = Decimal(str(valor or 0))
    except (InvalidOperation, ValueError):
        v = Decimal('0')
    v = v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)  # 9,405 -> 9,41 (arredondamento comercial)
    return "R$ " + f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


UNIDADES_FRACIONADAS = {'KG', 'G', 'GR', 'L', 'LT', 'ML', 'M'}


def qtd_para_pedido(sugestao, unidade):
    """
    Arredonda a sugestão para uma quantidade que dá para pedir:
    unidades inteiras (UN, CX, PCT...) sobem para o próximo número inteiro;
    peso/volume (KG, L...) ficam com até 3 casas.
    """
    s = Decimal(str(sugestao or 0))
    if s <= 0:
        return Decimal('0')
    if str(unidade or '').strip().upper() in UNIDADES_FRACIONADAS:
        return s.quantize(Decimal('0.001'))
    return Decimal(math.ceil(s))


def calcular_qtd_contagem(texto, fator=1, unidade='UN'):
    """
    [MELHORIA CONTAGEM] Lê a quantidade digitada na contagem. Aceita:
      '36'          -> 36 (na unidade escolhida: se for 'CX de 12', vira 36 x 12)
      '3+5'         -> com 'CX de 12' escolhida: 3 caixas + 5 soltas = 41
      '3x12' / '3*12' / '3x12+5' -> conta pronta, sempre em UNIDADES (41)
    Devolve (total_na_unidade_do_estoque, detalhe_em_texto_ou_None).
    Levanta ValueError com mensagem clara.
    """
    bruto = str(texto or '').strip().lower().replace('×', 'x').replace('*', 'x').replace(' ', '')
    if not bruto:
        raise ValueError("Digite a quantidade.")
    fator = Decimal(str(fator or 1))
    total, partes, primeira = Decimal('0'), [], True
    for termo in bruto.split('+'):
        if not termo:
            raise ValueError("Quantidade incompleta. Exemplos: 36   ou   3+5   ou   3x12+5")
        if 'x' in termo:
            fatores = termo.split('x')
            if len(fatores) != 2 or not all(fatores):
                raise ValueError(f"Não entendi '{termo}'. Use, por exemplo, 3x12 (3 caixas de 12).")
            a = para_decimal(fatores[0], "Quantidade")
            b = para_decimal(fatores[1], "Quantidade")
            total += a * b
            partes.append(f"{fmt_qtd(a)}×{fmt_qtd(b)}")
        else:
            n = para_decimal(termo, "Quantidade")
            if primeira and fator > 1:
                total += n * fator
                partes.append(f"{fmt_qtd(n)} cx de {fmt_qtd(fator)}")
            else:
                total += n
                partes.append(f"{fmt_qtd(n)} {unidade} soltas" if fator > 1 else fmt_qtd(n))
        primeira = False
    detalhe = " + ".join(partes)
    simples = re.fullmatch(r'[\d.,]+', bruto) and fator <= 1
    return total, (None if simples else detalhe)


def sugerir_unidade_contagem(total, fator_usado, fatores, anterior, digitado_simples=True):
    """
    [MELHORIA CONTAGEM] Detecta o erro "contei em caixa e lancei em unidade" (ou o contrário)
    comparando com a ÚLTIMA contagem do produto. Só sugere quando a quantidade lançada está
    MUITO longe da anterior (mais de 3x) e a alternativa fica perto (até 2x).
    Devolve (quantidade_sugerida, fator_da_sugestao) ou None.
    """
    try:
        anterior = Decimal(str(anterior)) if anterior is not None else None
    except (InvalidOperation, ValueError):
        return None
    if not anterior or anterior <= 0 or total <= 0 or not digitado_simples:
        return None

    def distancia(x):
        return abs(math.log(float(x) / float(anterior)))

    if distancia(total) <= math.log(3):
        return None
    fator_usado = Decimal(str(fator_usado or 1))
    if fator_usado <= 1:
        candidatos = [(total * Decimal(str(f)), Decimal(str(f))) for f in fatores if Decimal(str(f)) > 1]
    else:
        candidatos = [(total / fator_usado, Decimal('1'))]
    if not candidatos:
        return None
    melhor = min(candidatos, key=lambda c: distancia(c[0]))
    return melhor if distancia(melhor[0]) <= math.log(2) else None


def _fmt_d(d):
    return d.strftime('%d/%m/%Y') if d else '--'


def calcular_linha_sugestao(item, dias_cobertura, prazo_dias, data_ref, preferir='ultimo'):
    """
    [MELHORIA SUGESTÃO] Decide quanto comprar de UM produto e explica a conta.
      Sugestão = consumo/dia x (prazo de entrega + dias a cobrir) + estoque mínimo - estoque hoje
    (o prazo entra porque o estoque continua saindo enquanto o pedido não chega).
    A quantidade é arredondada para CAIXAS do fornecedor escolhido (Qtd/Cx do vínculo).
    preferir: 'ultimo' = fornecedor da última compra; 'barato' = mais barato em 12 meses.
    Devolve um dicionário com os números, a situação (cor) e as linhas de explicação.
    """
    D0 = Decimal('0')
    cobertura, prazo = Decimal(int(dias_cobertura)), Decimal(int(prazo_dias))
    un = item['Unidade']
    minimo = item['EstoqueMinimo'] or D0
    umd = item['UsoMedioDiario'] or D0
    estoque = item['EstoqueHoje']
    if isinstance(preferir, tuple) and preferir[0] == 'fornecedor':
        # [DEPURAÇÃO 2] pedido para um fornecedor escolhido (o do filtro da tela)
        forn = (item.get('PorFornecedor') or {}).get(preferir[1]) or item.get('FornecedorUltimo')
    else:
        forn = (item.get('FornecedorBarato') if preferir == 'barato' else None) or item.get('FornecedorUltimo')
    fator = forn['Fator'] if forn and forn.get('Fator') and forn['Fator'] > 0 else Decimal('1')
    nome = item['NomeProduto']
    exp = [f"{nome} ({un})"]
    comprado_recente = (item.get('ComprasJanela') or D0) > 0
    resultado = {'item': item, 'estoque': estoque, 'umd': umd, 'sugestao': D0, 'qtd_pedido': D0, 'embalagens': D0,
                 'fator': fator, 'texto_pedido': '', 'fornecedor': forn, 'custo_total': D0, 'acaba_em': None,
                 'dias_restantes': None, 'comprado_recente': comprado_recente, 'parado': False, 'explicacao': exp}

    if not item['Contado']:
        resultado.update(situacao="❔ NUNCA CONTADO", tag='nunca')
        exp.append(f"❔ Este produto NUNCA foi contado até {_fmt_d(item.get('DataUltimaContagem') or data_ref)}: "
                   "sem contagem não dá para saber o estoque nem o consumo.")
        if comprado_recente:
            exp.append(f"   Foram comprados {fmt_qtd(item['ComprasJanela'])} {un} nos últimos dias analisados. "
                       "Inclua este produto na próxima contagem.")
        resultado['colunas'] = (nome, un, "nunca", "—", "—", "—", "—", "", forn['Fornecedor'] if forn else "", "❔ NUNCA CONTADO")
        return resultado

    # ---- Estoque de hoje ----
    marca = "" if item['ContadoNoPontoB'] else "📏 "
    q_l, d_l = item['QtdUltimaContagem'], item['DataUltimaContagem']
    texto_est = f"📦 Estoque hoje ≈ {fmt_qtd(estoque)} {un}: contado {fmt_qtd(q_l)} em {_fmt_d(d_l)}"
    if item['ContagensNoDia'] > 1:
        texto_est += f" (soma de {item['ContagensNoDia']} contagens do mesmo dia)"
    if item['DiasDesdeContagem'] > 0:
        texto_est += (f" + {fmt_qtd(item['ComprasDepois'])} comprado depois - {fmt_qtd(umd * item['DiasDesdeContagem'])} "
                      f"de consumo em {item['DiasDesdeContagem']} dia(s)")
    if not item['ContadoNoPontoB']:
        texto_est += "   [📏 não foi contado no Ponto B]"
    exp.append(texto_est)

    # ---- Consumo ----
    metodo = item['MetodoConsumo']
    if metodo == 'contagens' and item.get('InicioPrimeiraCompra'):
        exp.append(f"📉 Consumo: 0 (estoque considerado ZERO antes da 1ª compra, em {_fmt_d(item['DataInicio'] + timedelta(days=1))}) "
                   f"+ {fmt_qtd(item['ComprasPeriodo'])} comprado - {fmt_qtd(q_l)} contado em {_fmt_d(d_l)} = "
                   f"{fmt_qtd(item['Consumo'])} {un} em {item['DiasPeriodo']} dias = {fmt_qtd(umd)} {un}/dia "
                   f"({fmt_qtd(umd * 30)} {un}/mês)")
    elif metodo == 'contagens':
        exp.append(f"📉 Consumo: {fmt_qtd(item['QtdInicio'])} contado em {_fmt_d(item['DataInicio'])} + {fmt_qtd(item['ComprasPeriodo'])} "
                   f"comprado - {fmt_qtd(q_l)} contado em {_fmt_d(d_l)} = {fmt_qtd(item['Consumo'])} {un} em "
                   f"{item['DiasPeriodo']} dias = {fmt_qtd(umd)} {un}/dia ({fmt_qtd(umd * 30)} {un}/mês)")
    elif metodo == 'compras':
        exp.append(f"📉 Consumo ≈ {fmt_qtd(item['ComprasPeriodo'])} {un} comprados nos últimos {item['DiasPeriodo']} dias = "
                   f"{fmt_qtd(umd)} {un}/dia. Aproximado: o produto só tem 1 contagem (com 2 contagens a conta fica exata).")
    else:
        exp.append("📉 Consumo: sem dados (só 1 contagem e nenhuma compra recente) - considerado zero.")

    if item['ConsumoNegativo']:
        exp.append(f"⚠️ A CONTA NÃO FECHA: {fmt_qtd(item['QtdInicio'])} + {fmt_qtd(item['ComprasPeriodo'])} comprado = "
                   f"{fmt_qtd(item['QtdInicio'] + item['ComprasPeriodo'])}, mas foram contados {fmt_qtd(q_l)} (sobrou mais do que tinha).")
        if item.get('InicioPrimeiraCompra'):
            exp.append("   No modo 'desde a primeira compra' isto também acontece quando JÁ havia estoque antes da "
                       "1ª nota importada (o sistema supõe zero). Nesse caso, use o modo automático.")
        exp.append("   Causas comuns: erro na contagem, nota fiscal não importada, vínculo/Qtd-Cx errado ou "
                   "o mesmo produto cadastrado 2 vezes. Confira antes de comprar.")

    # ---- Sugestão ----
    necessidade = umd * (prazo + cobertura) + minimo - estoque
    sugestao = max(necessidade, D0)
    if fator > 1 and sugestao > 0:
        embalagens = Decimal(math.ceil(sugestao / fator))
        qtd = embalagens * fator
        texto_pedido = f"{fmt_qtd(embalagens)} cx de {fmt_qtd(fator)} ({fmt_qtd(qtd)} {un})"
    else:
        qtd = qtd_para_pedido(sugestao, un)
        embalagens = qtd
        texto_pedido = f"{fmt_qtd(qtd)} {un}" if qtd > 0 else ""
    custo_total = qtd * forn['CustoUnid'] if forn and qtd > 0 else D0
    exp.append(f"🛒 Sugestão: {fmt_qtd(umd)}/dia × ({int(prazo)} de prazo + {int(cobertura)} a cobrir) + mínimo {fmt_qtd(minimo)} "
               f"- estoque {fmt_qtd(estoque)} = {fmt_qtd(necessidade)} → "
               + (f"pedir {texto_pedido}" if qtd > 0 else "não precisa comprar"))
    if forn:
        qual = "mais barato em 12 meses" if preferir == 'barato' and item.get('FornecedorBarato') else "última compra"
        exp.append(f"🏪 {forn['Fornecedor']} ({qual}, {_fmt_d(forn['Data'])}): {fmt_reais(forn['CustoUnid'])}/{un}"
                   + (f" · caixa de {fmt_qtd(fator)}" if fator > 1 else "")
                   + (f" · total ≈ {fmt_reais(custo_total)}" if qtd > 0 else ""))
        barato = item.get('FornecedorBarato')
        if preferir != 'barato' and barato and barato['CustoUnid'] < forn['CustoUnid'] and barato['FornecedorID'] != forn['FornecedorID']:
            exp.append(f"   💡 Mais barato em 12 meses: {barato['Fornecedor']} a {fmt_reais(barato['CustoUnid'])}/{un} "
                       f"({_fmt_d(barato['Data'])}).")

    # ---- Duração e situação ----
    dias_restantes = (estoque / umd) if umd > 0 else None
    acaba_em = (data_ref + timedelta(days=int(dias_restantes))) if dias_restantes is not None and dias_restantes <= 3650 else None
    if item['ConsumoNegativo']:
        situacao, tag = "⚠️ CONFERIR", 'conferir'
    elif umd <= 0 and sugestao <= 0:
        situacao, tag = "⚪ SEM GIRO", 'sem_giro'
    elif (minimo > 0 and estoque <= minimo) or (dias_restantes is not None and dias_restantes < max(7, int(prazo))):
        situacao, tag = "🔴 CRÍTICO", 'critico'
    elif sugestao > 0:
        situacao, tag = "🟡 COMPRAR", 'comprar'
    else:
        situacao, tag = "🟢 OK", 'ok'
    if dias_restantes is not None and dias_restantes > 365:
        exp.append("⏳ Com o consumo atual, o estoque dura mais de 1 ano.")
    elif dias_restantes is not None:
        exp.append(f"⏳ Dura ≈ {fmt_qtd(dias_restantes.quantize(Decimal('0.1')))} dias → acaba por volta de {_fmt_d(acaba_em)}"
                   + (" (ANTES de um pedido feito hoje chegar!)" if dias_restantes < prazo else ""))
    if estoque <= 0 and umd > 0:
        texto_acaba = "Já acabou"
    elif dias_restantes is not None:
        texto_acaba = "> 1 ano" if dias_restantes > 365 else _fmt_d(acaba_em)
    else:
        texto_acaba = "—"
    parado = tag == 'sem_giro' and estoque <= 0 and not comprado_recente
    consumo_txt = ("≈ " if metodo == 'compras' else "") + fmt_qtd((umd * 30).quantize(Decimal('0.001')))
    resultado.update({
        'sugestao': sugestao, 'qtd_pedido': qtd, 'embalagens': embalagens, 'texto_pedido': texto_pedido,
        'custo_total': custo_total, 'acaba_em': acaba_em, 'dias_restantes': dias_restantes,
        'situacao': situacao, 'tag': tag, 'parado': parado,
        'colunas': (nome, un, _fmt_d(d_l), marca + fmt_qtd(estoque.quantize(Decimal('0.001'))), consumo_txt, texto_acaba,
                    fmt_qtd(sugestao.quantize(Decimal('0.001'))), texto_pedido, forn['Fornecedor'] if forn else "", situacao)})
    return resultado


def linhas_do_banco_para_dicts(linhas):
    """Converte o que o banco devolve (Row do pyodbc, dict ou objeto) em lista de dicionários."""
    resultado = []
    for linha in linhas or []:
        if isinstance(linha, dict):
            resultado.append(dict(linha))
        elif hasattr(linha, 'cursor_description'):
            resultado.append({c[0]: v for c, v in zip(linha.cursor_description, linha)})
        elif hasattr(linha, '__dict__'):
            resultado.append({k: v for k, v in vars(linha).items() if not k.startswith('_')})
        else:
            resultado.append({'valor': str(linha)})
    for d in resultado:  # o Excel não aceita alguns tipos (Decimal fica como número)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
    return resultado


def nome_aba_excel(nome, usados):
    """Nome de aba válido no Excel (máx. 31 letras, sem []:*?/\\) e sem repetir."""
    base = re.sub(r'[\[\]:*?/\\]', '_', str(nome or 'Sem nome')).strip()[:28] or 'Aba'
    nome_final, n = base, 2
    while nome_final.lower() in usados:
        nome_final = f"{base[:25]}_{n}"; n += 1
    usados.add(nome_final.lower())
    return nome_final


# [MELHORIA VALOR] Tipo da operação de cada item da nota (CFOP, últimos 3 dígitos).
# Bonificação / brinde / amostra grátis: a mercadoria entra no estoque com CUSTO ZERO
# (não foi paga). Comodato (ex: freezer emprestado pela fábrica), remessas, conserto,
# vasilhame e devoluções NÃO são compra: esses itens são ignorados.
CFOP_BONIFICACAO = {'910', '911'}
CFOP_IGNORAR = {'908', '909', '912', '913', '915', '916', '920', '921', '201', '202', '410', '411'}


def tipo_item_por_cfop(cfop):
    """'compra', 'bonificacao' ou 'ignorar'."""
    final = so_digitos(cfop)[-3:]
    if final in CFOP_BONIFICACAO:
        return 'bonificacao'
    if final in CFOP_IGNORAR:
        return 'ignorar'
    return 'compra'


# [MELHORIA CATÁLOGO] Sugestão de nome "limpo" para produtos criados a partir do XML
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


def criar_tree_zebrada(pai, **kwargs):
    """
    [MELHORIA UX] Cria uma tabela (Treeview) com linhas alternadas cinza/branco,
    que facilitam acompanhar a linha com os olhos em listas longas.
    """
    tree = ttk.Treeview(pai, **kwargs)
    insert_original = tree.insert

    def insert_zebrado(parent, index, *args, **kw):
        qtd = len(tree.get_children(parent))
        tags = kw.get('tags', ())
        if isinstance(tags, str):
            tags = (tags,) if tags else ()
        kw['tags'] = tuple(tags) + ('zebra_impar' if qtd % 2 else 'zebra_par',)
        return insert_original(parent, index, *args, **kw)

    tree.insert = insert_zebrado
    try:
        tree.tag_configure('zebra_impar', background='#f3f6fa')
        tree.tag_configure('zebra_par', background='#ffffff')
    except tk.TclError:
        pass
    return tree

class AppGestaoEstoque:
    def __init__(self, root):
        self.root = root
        self.root.title("Módulo de Gestão de Estoque")
        self.root.geometry("1200x700") 

        # [MELHORIA UX] Barra de status no rodapé: mostra "✅ Produto salvo" etc. sem
        # abrir uma janelinha que precisa de clique em OK. (Criada ANTES das abas para
        # ficar sempre visível embaixo.)
        self._status_job = None
        self.barra_status = ttk.Frame(root, relief="sunken", padding=(8, 3))
        self.barra_status.pack(side=tk.BOTTOM, fill=tk.X)
        self.lbl_status = ttk.Label(self.barra_status, text="", anchor="w")
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(self.barra_status, foreground="gray",
                  text="Atalhos: Ctrl+F = buscar · F5 = atualizar · Delete = excluir selecionado").pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        self.frame_produtos = ttk.Frame(self.notebook, padding="10")
        self.frame_fornecedores = ttk.Frame(self.notebook, padding="10")
        self.frame_importacao = ttk.Frame(self.notebook, padding="10") 
        self.frame_contagem = ttk.Frame(self.notebook, padding="10")
        self.frame_sugestao = ttk.Frame(self.notebook, padding="10") 
        self.frame_admin = ttk.Frame(self.notebook, padding="10") # Nova Aba Admin

        self.notebook.add(self.frame_produtos, text='1. Catálogo Mestre')
        self.notebook.add(self.frame_fornecedores, text='2. Fornecedores')
        self.notebook.add(self.frame_importacao, text='3. Importar XMLs (DE/PARA)')
        self.notebook.add(self.frame_contagem, text='4. Lançar Contagem Física')
        self.notebook.add(self.frame_sugestao, text='5. Sugestão de Compra') 
        self.notebook.add(self.frame_admin, text='6. Administração / Reset')
        self.frame_solicitacoes = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.frame_solicitacoes, text='7. Solicitações (Líderes)')
        # [MELHORIA] Aba de consultas rápidas: histórico de preços do produto e itens das notas
        self.frame_consultas = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.frame_consultas, text='8. 🔎 Consultas')
        self.criar_aba_solicitacoes()

        self.produto_selecionado_id = None
        self.custo_carregado_texto = None  # [DEPURAÇÃO] custo mostrado ao abrir o produto p/ edição
        self.fornecedor_selecionado_id = None

        self.itens_xml_nao_vinculados = []
        self.dados_notas_processadas = []
        self.ultima_pasta_xml = None       # [DEPURAÇÃO] permite "Reprocessar" sem escolher de novo
        self.mapa_produtos_mestre = {}
        self.lista_mestre_produtos_nomes = []

        self.mapa_produtos_mestre_contagem = {}
        self.lista_itens_para_salvar_contagem = []
        self.lista_mestre_contagem_nomes = []

        self.cache_relatorio_posicao = {}
        self.mapa_contagens_historico = {}
        # [DEPURAÇÃO] A aba 5 tinha o MESMO dicionário da aba 4; atualizar a aba 4 apagava
        # a opção "DESDE A PRIMEIRA COMPRA" da aba 5. Agora cada aba tem o seu.
        self.mapa_contagens_sugestao = {}

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.criar_aba_catalogo_produtos()
        self.criar_aba_fornecedores()
        self.criar_aba_importacao_xml() 
        self.criar_aba_contagem_estoque()
        self.criar_aba_sugestao_compra() 
        self.criar_aba_administracao()
        self.criar_aba_consultas()  # [MELHORIA]
        
        # Carregamento inicial
        self.atualizar_lista_produtos() 
        self.atualizar_lista_fornecedores() 
        self.popular_combobox_produtos_mestre() 
        self.atualizar_lista_contagens_historico() 
        self.popular_combos_contagem_sugestao() # <-- CORREÇÃO: Inicializa os combos da aba 5
        self.carregar_categorias_do_banco()
        self.carregar_solicitacoes()  # [DEPURAÇÃO] antes a aba 7 abria sempre vazia

        # [MELHORIA UX] Atalhos de teclado, lembrar tamanho da janela / última aba,
        # aviso ao fechar e recuperação de contagem não salva.
        self.configurar_atalhos()
        self.aplicar_preferencias()
        self.root.protocol("WM_DELETE_WINDOW", self.ao_fechar_janela)
        self.root.after(400, self.verificar_rascunho_contagem)

    # ===================================================================
    # == [MELHORIA UX] BARRA DE STATUS, ATALHOS E PREFERÊNCIAS ==========
    # ===================================================================
    def status(self, mensagem, tipo='ok', segundos=10):
        """
        Mostra uma mensagem no rodapé. tipo: 'ok' (verde), 'aviso' (laranja),
        'erro' (vermelho) ou 'info' (preto). Some sozinha depois de alguns segundos.
        """
        icones = {'ok': '✅ ', 'aviso': '⚠️ ', 'erro': '❌ ', 'info': 'ℹ️ '}
        cores = {'ok': '#1b7a2f', 'aviso': '#b35c00', 'erro': '#c62828', 'info': '#222222'}
        texto = " ".join(str(mensagem).split())  # tira quebras de linha
        self.ultimo_status = texto
        try:
            self.lbl_status.config(text=icones.get(tipo, '') + texto, foreground=cores.get(tipo, '#222222'))
            if self._status_job:
                self.root.after_cancel(self._status_job)
            self._status_job = self.root.after(segundos * 1000, lambda: self.lbl_status.config(text=""))
        except tk.TclError:
            pass
        logger.info(f"[status] {texto}")

    def aba_atual(self):
        try:
            return self.notebook.tab(self.notebook.select(), "text")
        except tk.TclError:
            return ''

    def configurar_atalhos(self):
        """Ctrl+F = ir para a busca da aba; F5 = atualizar a aba; Delete = excluir o selecionado."""
        self.root.bind_all("<Control-f>", self.atalho_buscar)
        self.root.bind_all("<Control-F>", self.atalho_buscar)
        self.root.bind_all("<F5>", lambda e: (self.on_tab_changed(None), self.status("Aba atualizada.", 'info', 4)))
        atalhos_delete = [
            (self.tree_produtos, self.excluir_produto_selecionado),
            (self.tree_fornecedores, self.excluir_fornecedor_selecionado),
            (self.tree_contagem_atual, self.remover_item_contagem),
            (self.tree_admin_nfs, self.excluir_nfs_selecionadas),
            (self.tree_admin_cont, self.excluir_contagens_selecionadas),
        ]
        for tree, acao in atalhos_delete:
            tree.bind("<Delete>", lambda e, f=acao: f())

    def atalho_buscar(self, event=None):
        campos = {
            '1.': getattr(self, 'entry_filtro_mestre', None),
            '3.': getattr(self, 'entry_filtro_importacao', None),
            '4.': getattr(self, 'entry_filtro_contagem', None),
            '5.': getattr(self, 'entry_busca_sugestao', None),
            '8.': self._campo_busca_consultas() if hasattr(self, 'nb_consultas') else None,
        }
        campo = campos.get(self.aba_atual()[:2])
        if campo is not None:
            campo.focus_set()
            campo.select_range(0, tk.END)
        return "break"

    def ler_preferencias(self):
        try:
            with open(ARQUIVO_PREFERENCIAS, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def aplicar_preferencias(self):
        """Abre a janela do mesmo tamanho/posição e na mesma aba da última vez."""
        pref = self.ler_preferencias()
        geo = str(pref.get('geometria', ''))
        m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', geo)
        if m:
            larg, alt, x, y = map(int, m.groups())
            try:
                tela_l, tela_a = int(self.root.winfo_screenwidth()), int(self.root.winfo_screenheight())
            except (tk.TclError, TypeError, ValueError):
                tela_l, tela_a = 0, 0
            # Só usa se a janela couber na tela atual (ex: monitor extra desligado)
            if 400 <= larg <= tela_l and 300 <= alt <= tela_a and 0 <= x < tela_l - 100 and 0 <= y < tela_a - 100:
                self.root.geometry(geo)
        aba = pref.get('aba')
        if isinstance(aba, int) and 0 <= aba < 8:
            try:
                self.notebook.select(aba)
            except tk.TclError:
                pass

    def salvar_preferencias(self):
        try:
            dados = self.ler_preferencias()   # [MELHORIA SUGESTÃO] mantém as outras preferências
            dados.update({'geometria': self.root.geometry(), 'aba': self.notebook.index(self.notebook.select())})
            with open(ARQUIVO_PREFERENCIAS, 'w', encoding='utf-8') as f:
                json.dump(dados, f)
        except Exception as e:  # nunca impede o programa de fechar
            logger.warning(f"Não foi possível salvar as preferências da janela: {e}")

    def ao_fechar_janela(self):
        """Antes de fechar: avisa sobre contagem não salva e guarda tamanho/aba."""
        qtd = len(self.lista_itens_para_salvar_contagem)
        if qtd:
            if not messagebox.askyesno(
                    "Contagem não salva",
                    f"Há {qtd} item(ns) na contagem que ainda NÃO foram salvos no banco.\n\n"
                    "Fique tranquilo: eles ficam guardados como rascunho e o programa vai "
                    "oferecer para continuar na próxima vez que abrir.\n\n"
                    "Deseja fechar o programa mesmo assim?",
                    icon='warning', parent=self.root):
                return
            self.salvar_rascunho_contagem()
        self.salvar_preferencias()
        self.root.destroy()

    def carregar_categorias_do_banco(self):
        """Busca as categorias dinâmicas do banco e atualiza todos os Comboboxes do sistema."""
        try:
            categorias_db = database.listar_categorias_produto()
            # Se por algum motivo o banco retornar vazio, usa um fallback seguro
            if not categorias_db:
                categorias_db = ["Geral"]
                
            self.lista_categorias = categorias_db
            lista_com_todas = ["Todas"] + self.lista_categorias

            # 1. Aba 1: Formulário Novo Produto
            if hasattr(self, 'combo_prod_categoria'):
                self.combo_prod_categoria['values'] = self.lista_categorias
                if self.combo_prod_categoria.get() not in self.lista_categorias:
                    self.combo_prod_categoria.set("Geral" if "Geral" in self.lista_categorias else self.lista_categorias[0])
            
            # 2. Aba 1: Filtro da Tabela
            if hasattr(self, 'combo_filtro_cat_mestre'):
                valor_atual = self.combo_filtro_cat_mestre.get()
                self.combo_filtro_cat_mestre['values'] = lista_com_todas
                if valor_atual not in lista_com_todas:
                    self.combo_filtro_cat_mestre.set("Todas")

            # 3. Aba 3: Importação XML (Criar Mestre)
            if hasattr(self, 'combo_cat_importacao'):
                self.combo_cat_importacao['values'] = self.lista_categorias
                if self.combo_cat_importacao.get() not in self.lista_categorias:
                    self.combo_cat_importacao.set("Geral" if "Geral" in self.lista_categorias else self.lista_categorias[0])

            # 4. Aba 5: Filtro Sugestão de Compra
            if hasattr(self, 'combo_sugestao_categoria'):
                valor_atual_sug = self.combo_sugestao_categoria.get()
                self.combo_sugestao_categoria['values'] = lista_com_todas
                if valor_atual_sug not in lista_com_todas:
                    self.combo_sugestao_categoria.set("Todas")
                    
        except Exception as e:
            logger.error(f"Erro ao carregar categorias do banco no Tkinter: {e}", exc_info=True)

    def on_tab_changed(self, event):
        """Atualiza os dados das abas quando elas são selecionadas."""
        try:
            tab_selecionada = self.notebook.tab(self.notebook.select(), "text")
        except tk.TclError:
            return

        if tab_selecionada == '5. Sugestão de Compra':
            self.popular_combos_contagem_sugestao()
        elif tab_selecionada == '4. Lançar Contagem Física':
            self.atualizar_lista_contagens_historico()
        elif tab_selecionada == '1. Catálogo Mestre':
            self.atualizar_lista_produtos()
        elif tab_selecionada == '2. Fornecedores':
            self.atualizar_lista_fornecedores()
        elif tab_selecionada == '6. Administração / Reset':
            self.atualizar_lista_nfs_admin()
            self.atualizar_lista_contagens_admin()
        elif tab_selecionada.startswith('8.'):
            self.atualizar_consultas()  # [MELHORIA] notas/produtos novos aparecem ao abrir a aba
        elif tab_selecionada.startswith('7.'):
            # [DEPURAÇÃO] comparava com '7. Aprovar Compras/Manutenção', mas a aba se chama
            # '7. Solicitações (Líderes)' -> a lista NUNCA atualizava sozinha.
            self.carregar_solicitacoes()

    # ===================================================================
    # == ABA 1: CATÁLOGO MESTRE (Sem alterações) ========================
    # ===================================================================
    def criar_aba_catalogo_produtos(self):
        main_frame = ttk.Frame(self.frame_produtos)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Lado Esquerdo: Formulário ---
        self.form_frame_mestre = ttk.LabelFrame(main_frame, text="Modo: NOVO CADASTRO", padding="10")
        self.form_frame_mestre.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        ttk.Label(self.form_frame_mestre, text="Nome do Produto:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_prod_nome = ttk.Entry(self.form_frame_mestre, width=40)
        self.entry_prod_nome.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        # A lista self.lista_categorias agora nasce vazia e será preenchida pelo banco no __init__
        self.lista_categorias = []

        ttk.Label(self.form_frame_mestre, text="Unidade (Ex: UN, KG):").grid(row=2, column=0, sticky="w", pady=2)
        self.entry_prod_unidade = ttk.Entry(self.form_frame_mestre, width=10)
        self.entry_prod_unidade.grid(row=3, column=0, sticky="w", pady=(0, 10))

        ttk.Label(self.form_frame_mestre, text="Categoria:").grid(row=2, column=1, sticky="w", pady=2)
        
        # Sub-frame para colocar o Combobox e o botão "Gerenciar" lado a lado
        frame_categoria_mestre = ttk.Frame(self.form_frame_mestre)
        frame_categoria_mestre.grid(row=3, column=1, sticky="w", pady=(0, 10))
        
        self.combo_prod_categoria = ttk.Combobox(frame_categoria_mestre, values=self.lista_categorias, width=15, state="readonly")
        self.combo_prod_categoria.pack(side=tk.LEFT)
        
        # Botão para abrir o Popup de Gerenciamento
        btn_gerir_categorias = ttk.Button(frame_categoria_mestre, text="⚙️", width=3, command=self.abrir_gestor_categorias)
        btn_gerir_categorias.pack(side=tk.LEFT, padx=(2, 0))

        # --- NOVO LAYOUT: Lado a Lado (Estoque Mínimo e Custo) ---
        ttk.Label(self.form_frame_mestre, text="Estoque Mínimo:").grid(row=4, column=0, sticky="w", pady=2)
        self.entry_prod_estoque_min = ttk.Entry(self.form_frame_mestre, width=15)
        self.entry_prod_estoque_min.grid(row=5, column=0, sticky="w", pady=(0, 10))
        self.entry_prod_estoque_min.insert(0, "0.0")

        # [MELHORIA CATÁLOGO] "Custo" honesto: só é editável quando o produto NUNCA foi
        # comprado por nota. Se tem nota, mostra o custo que o sistema realmente usa.
        self.lbl_prod_custo = ttk.Label(self.form_frame_mestre, text="Custo manual (R$):")
        self.lbl_prod_custo.grid(row=4, column=1, sticky="w", pady=2)
        self.entry_prod_custo = ttk.Entry(self.form_frame_mestre, width=15)
        self.entry_prod_custo.grid(row=5, column=1, sticky="w", pady=(0, 10))
        self.entry_prod_custo.insert(0, "0.00")
        self.lbl_prod_custo_info = ttk.Label(self.form_frame_mestre, text="Opcional: custo para produto sem nota fiscal.",
                                             foreground="gray", wraplength=330, justify="left")
        self.lbl_prod_custo_info.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 6))
        # ---------------------------------------------------------

        btn_frame = ttk.Frame(self.form_frame_mestre)
        btn_frame.grid(row=7, column=0, columnspan=2, pady=10)
        self.btn_prod_salvar = ttk.Button(btn_frame, text="Salvar Novo", command=self.salvar_produto)
        self.btn_prod_salvar.pack(side=tk.LEFT, padx=5)
        self.btn_prod_limpar = ttk.Button(btn_frame, text="Limpar", command=self.limpar_formulario_produto)
        self.btn_prod_limpar.pack(side=tk.LEFT, padx=5)

        # Botão Excluir movido para o formulário (inicialmente desabilitado)
        self.btn_excluir_mestre = ttk.Button(self.form_frame_mestre, text="🗑️ Excluir Produto", command=self.excluir_produto_selecionado, state=tk.DISABLED)
        self.btn_excluir_mestre.grid(row=8, column=0, columnspan=2, pady=15, sticky="ew")

        # --- Lado Direito: Tabela e Filtros ---
        lista_frame = ttk.LabelFrame(main_frame, text="Catálogo Mestre de Produtos (Duplo-clique no item para ver vínculos)", padding="10")
        lista_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        lista_frame.rowconfigure(1, weight=1)
        lista_frame.columnconfigure(0, weight=1)

        # Barra de Filtros Inteligentes
        filtro_frame = ttk.Frame(lista_frame)
        filtro_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(filtro_frame, text="Buscar:").pack(side=tk.LEFT)
        self.entry_filtro_mestre = ttk.Entry(filtro_frame, width=30)
        self.entry_filtro_mestre.pack(side=tk.LEFT, padx=5)
        self.entry_filtro_mestre.bind("<KeyRelease>", self.atualizar_lista_produtos)

        ttk.Label(filtro_frame, text="Categoria:").pack(side=tk.LEFT, padx=(15,0))
        self.combo_filtro_cat_mestre = ttk.Combobox(filtro_frame, values=["Todas"] + self.lista_categorias, state="readonly", width=15)
        self.combo_filtro_cat_mestre.pack(side=tk.LEFT, padx=5)
        self.combo_filtro_cat_mestre.set("Todas")
        self.combo_filtro_cat_mestre.bind("<<ComboboxSelected>>", self.atualizar_lista_produtos)
        # [MELHORIA CATÁLOGO] filtro por situação
        ttk.Label(filtro_frame, text="Mostrar:").pack(side=tk.LEFT, padx=(10, 0))
        self.combo_filtro_situacao = ttk.Combobox(filtro_frame, state="readonly", width=30,
                                                  values=[r for _, r in self.FILTROS_CATALOGO])
        self.combo_filtro_situacao.set(self.FILTROS_CATALOGO[0][1])
        self.combo_filtro_situacao.pack(side=tk.LEFT, padx=5)
        self.combo_filtro_situacao.bind("<<ComboboxSelected>>", self.atualizar_lista_produtos)
        acoes_frame = ttk.Frame(lista_frame)
        acoes_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.btn_editar_massa = ttk.Button(acoes_frame, text="✏️ Editar selecionados", command=self.abrir_edicao_em_massa)
        self.btn_editar_massa.pack(side=tk.LEFT)
        ttk.Button(acoes_frame, text="🧹 Sugerir nomes limpos", command=self.abrir_sugestao_nomes).pack(side=tk.LEFT, padx=5)
        ttk.Button(acoes_frame, text="🔗 Juntar produtos duplicados", command=lambda: self.abrir_juntar_produtos()).pack(side=tk.LEFT)
        ttk.Label(acoes_frame, foreground="gray", text="  Ctrl ou Shift + clique = selecionar vários").pack(side=tk.LEFT)

        # Tabela
        # [MELHORIA CATÁLOGO] colunas novas (as 5 primeiras continuam na mesma ordem) e
        # seleção de VÁRIOS produtos (Ctrl/Shift + clique) para editar em massa.
        cols = ('ID', 'Nome', 'Unidade', 'Categoria', 'Estoque Mínimo', 'Custo atual', 'Última compra',
                'Mais barato (12m)', 'Última contagem', 'Situação')
        self.tree_produtos = ttk.Treeview(lista_frame, columns=cols, show='headings', selectmode='extended')
        for col, titulo, larg, anc in (('ID', 'ID', 45, 'center'), ('Nome', 'Nome', 260, 'w'), ('Unidade', 'UN', 40, 'center'),
                                       ('Categoria', 'Categoria', 110, 'w'), ('Estoque Mínimo', 'Est. Mínimo', 75, 'e'),
                                       ('Custo atual', 'Custo atual', 90, 'e'), ('Última compra', 'Última compra', 90, 'center'),
                                       ('Mais barato (12m)', 'Mais barato (12m)', 200, 'w'),
                                       ('Última contagem', 'Última contagem', 120, 'e'), ('Situação', 'Situação', 110, 'w')):
            self.tree_produtos.heading(col, text=titulo, command=lambda c=col: self.ordenar_coluna_treeview(self.tree_produtos, c, False))
            self.tree_produtos.column(col, width=larg, anchor=anc)

        # Tags para Listras Zebra
        self.tree_produtos.tag_configure('impar', background='#f9f9f9')
        self.tree_produtos.tag_configure('par', background='#ffffff')

        scrollbar = ttk.Scrollbar(lista_frame, orient="vertical", command=self.tree_produtos.yview)
        self.tree_produtos.configure(yscrollcommand=scrollbar.set)
        self.tree_produtos.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        # Eventos (Binds)
        self.tree_produtos.bind('<<TreeviewSelect>>', self.selecionar_produto_para_edicao)
        self.tree_produtos.bind('<Double-1>', self.abrir_popup_vinculos_produto)

        # Rodapé com Indicador
        self.lbl_total_mestre = ttk.Label(lista_frame, text="Carregando...", font=("Arial", 9, "italic"), foreground="gray")
        self.lbl_total_mestre.grid(row=2, column=0, sticky="w", pady=(5,0))

    # ===================================================================
    # == [MELHORIA CATÁLOGO] custo, edição em massa, nomes, duplicados ===
    # ===================================================================
    def _custo_editavel(self, sim):
        try:
            self.entry_prod_custo.config(state='normal' if sim else 'readonly')
        except tk.TclError:
            pass

    def _ids_selecionados_catalogo(self):
        return [int(i) for i in self.tree_produtos.selection() if str(i).isdigit()]

    def abrir_edicao_em_massa(self):
        """Muda categoria, unidade e/ou estoque mínimo de VÁRIOS produtos de uma vez."""
        ids = self._ids_selecionados_catalogo()
        if not ids:
            messagebox.showwarning("Aviso", "Selecione os produtos na lista (Ctrl ou Shift + clique para vários).", parent=self.root)
            return
        popup = Toplevel(self.root)
        popup.title(f"✏️ Editar {len(ids)} produto(s)")
        popup.geometry("460x330")
        popup.transient(self.root)
        f = ttk.Frame(popup, padding=15)
        f.pack(fill=tk.BOTH, expand=True)
        nomes = [self.tree_produtos.item(str(i), 'values')[1] for i in ids[:4] if self.tree_produtos.exists(str(i))]
        ttk.Label(f, text=f"{len(ids)} produto(s): " + ", ".join(nomes) + (" ..." if len(ids) > 4 else ""),
                  wraplength=420, font=("Arial", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(f, foreground="gray", text="Marque só o que você quer mudar. O resto fica como está.").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        var_cat, var_un, var_min = tk.BooleanVar(value=False), tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Categoria:", variable=var_cat).grid(row=2, column=0, sticky="w", pady=4)
        combo_cat = ttk.Combobox(f, values=self.lista_categorias, state="readonly", width=25)
        combo_cat.grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(f, text="Unidade:", variable=var_un).grid(row=3, column=0, sticky="w", pady=4)
        entry_un = ttk.Entry(f, width=10)
        entry_un.grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(f, text="Estoque mínimo:", variable=var_min).grid(row=4, column=0, sticky="w", pady=4)
        entry_min = ttk.Entry(f, width=10)
        entry_min.grid(row=4, column=1, sticky="w")
        # escolher um valor já marca a caixinha
        combo_cat.bind("<<ComboboxSelected>>", lambda e: var_cat.set(True))
        entry_un.bind("<KeyRelease>", lambda e: var_un.set(bool(entry_un.get().strip())))
        entry_min.bind("<KeyRelease>", lambda e: var_min.set(bool(entry_min.get().strip())))

        def aplicar():
            categoria = combo_cat.get() if var_cat.get() else None
            unidade = entry_un.get().strip().upper() if var_un.get() else None
            minimo = None
            if var_cat.get() and not categoria:
                messagebox.showerror("Erro", "Escolha a categoria.", parent=popup); return
            if var_un.get() and not unidade:
                messagebox.showerror("Erro", "Digite a unidade (ex: UN, KG).", parent=popup); return
            if var_min.get():
                if not entry_min.get().strip():   # [DEPURAÇÃO 2] vazio gravava 0 em todos sem avisar
                    messagebox.showerror("Erro", "Digite o estoque mínimo (ou desmarque a opção).", parent=popup); return
                try:
                    minimo = para_decimal(entry_min.get(), "Estoque mínimo")
                except ValueError as e:
                    messagebox.showerror("Erro", str(e), parent=popup); return
            if categoria is None and unidade is None and minimo is None:
                messagebox.showwarning("Aviso", "Marque pelo menos um campo para mudar.", parent=popup); return
            if unidade is not None and not messagebox.askyesno(
                    "Mudar a unidade", "Atenção: a unidade é a forma como você CONTA o produto. Se mudar de UN para KG, "
                    "confira também o Qtd/Cx dos vínculos (fornecedores) desses produtos.\n\nContinuar?", parent=popup):
                return
            ok, msg = database.atualizar_produtos_em_massa(ids, categoria=categoria, unidade=unidade, estoque_min=minimo)
            if ok:
                self.status(msg)
                popup.destroy()
                self.atualizar_lista_produtos()
                self.popular_combobox_produtos_mestre()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        ttk.Button(f, text=f"💾 Aplicar nos {len(ids)} produto(s)", command=aplicar).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0), ipady=4)
        self._janela_massa = {'popup': popup, 'var_cat': var_cat, 'cat': combo_cat, 'var_un': var_un, 'un': entry_un,
                              'var_min': var_min, 'min': entry_min, 'aplicar': aplicar}

    def abrir_sugestao_nomes(self):
        """Sugere nomes limpos para os produtos (os selecionados, ou todos da lista) e aplica os aprovados."""
        ids = self._ids_selecionados_catalogo()
        # [DEPURAÇÃO 2] sem seleção = só o que está NA LISTA (respeita busca/filtros), não o catálogo inteiro
        visiveis = {int(i) for i in self.tree_produtos.get_children()}
        base = [p for p in getattr(self, '_cache_produtos', []) if (p.ProdutoID in ids if ids else p.ProdutoID in visiveis)]
        sugestoes = []
        for p in base:
            novo = sugerir_nome_limpo(p.NomeProduto)
            if novo and novo != (p.NomeProduto or '').strip():
                sugestoes.append({'ProdutoID': p.ProdutoID, 'Atual': p.NomeProduto or '', 'Novo': novo})
        if not sugestoes:
            messagebox.showinfo("Nomes", "Nenhum nome para limpar. 👍", parent=self.root)
            return
        popup = Toplevel(self.root)
        popup.title("🧹 Sugerir nomes limpos")
        popup.geometry("1100x620")
        popup.transient(self.root)
        f = ttk.Frame(popup, padding=10)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, wraplength=1050, justify="left", text=(
            "Os nomes vieram da nota fiscal. Abaixo está uma sugestão mais limpa. Marque (✔) os que você aprova — "
            "duplo clique no ✔ marca/desmarca; duplo clique no NOME SUGERIDO deixa você escrever outro. "
            "Renomear é seguro: as próximas notas continuam sendo reconhecidas pelo vínculo, não pelo nome.")).pack(anchor="w", pady=(0, 6))
        lbl = ttk.Label(f, font=("Arial", 10, "bold"))
        lbl.pack(anchor="w")
        cols = ('✔', 'ID', 'Nome atual', 'Nome sugerido')
        tree = criar_tree_zebrada(f, columns=cols, show='headings', selectmode='browse')
        for col, larg, anc in (('✔', 35, 'center'), ('ID', 55, 'center'), ('Nome atual', 480, 'w'), ('Nome sugerido', 480, 'w')):
            tree.heading(col, text=col); tree.column(col, width=larg, anchor=anc)
        sb = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=6); sb.pack(side=tk.LEFT, fill=tk.Y, pady=6)
        # [DEPURAÇÃO 2] com seleção feita, vem tudo marcado; sem seleção (lista toda), começa desmarcado
        marcados = set(s_['ProdutoID'] for s_ in sugestoes) if ids else set()
        por_id = {str(s_['ProdutoID']): s_ for s_ in sugestoes}

        def mostrar():
            for i in tree.get_children():
                tree.delete(i)
            for s_ in sugestoes:
                tree.insert("", "end", iid=str(s_['ProdutoID']), values=(
                    "✔" if s_['ProdutoID'] in marcados else "", s_['ProdutoID'], s_['Atual'], s_['Novo']))
            lbl.config(text=f"{len(sugestoes)} sugestão(ões) · ✔ {len(marcados)} marcada(s)")

        def duplo_clique(event=None):
            sel = linha_do_clique(tree, event)
            if not sel:
                return
            coluna = tree.identify_column(event.x) if event is not None and hasattr(event, 'x') else '#1'
            s_ = por_id[sel]
            if coluna == '#4':
                novo = simpledialog.askstring("Nome do produto", f"Nome atual:\n{s_['Atual']}\n\nNovo nome:",
                                              initialvalue=s_['Novo'], parent=popup)
                if novo and novo.strip():
                    s_['Novo'] = ' '.join(novo.split()); marcados.add(s_['ProdutoID'])
            else:
                marcados.symmetric_difference_update({s_['ProdutoID']})
            mostrar(); tree.focus(sel); tree.selection_set(sel)

        def marcar_todos(sim):
            marcados.clear()
            if sim:
                marcados.update(s_['ProdutoID'] for s_ in sugestoes)
            mostrar()

        def aplicar():
            escolhidos = [(s_['ProdutoID'], s_['Novo']) for s_ in sugestoes if s_['ProdutoID'] in marcados]
            if not escolhidos:
                messagebox.showwarning("Aviso", "Nenhum nome marcado.", parent=popup); return
            if not messagebox.askyesno("Renomear", f"Renomear {len(escolhidos)} produto(s)?", parent=popup):
                return
            ok_n, erros = database.renomear_produtos(escolhidos)
            self.status(f"{ok_n} produto(s) renomeado(s).")
            if erros:
                messagebox.showwarning("Alguns nomes não foram trocados", "\n".join(erros[:15]), parent=popup)
            self.atualizar_lista_produtos()
            self.popular_combobox_produtos_mestre()
            popup.destroy()

        tree.bind("<Double-1>", duplo_clique)
        botoes = ttk.Frame(popup, padding=(10, 0, 10, 10))
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="✅ Renomear os marcados", command=aplicar).pack(side=tk.RIGHT, ipady=3)
        ttk.Button(botoes, text="Desmarcar todos", command=lambda: marcar_todos(False)).pack(side=tk.RIGHT, padx=5, ipady=3)
        ttk.Button(botoes, text="Marcar todos", command=lambda: marcar_todos(True)).pack(side=tk.RIGHT, ipady=3)
        mostrar()
        self._janela_nomes = {'popup': popup, 'tree': tree, 'sugestoes': sugestoes, 'marcados': marcados,
                              'duplo_clique': duplo_clique, 'aplicar': aplicar, 'marcar_todos': marcar_todos}

    def abrir_juntar_produtos(self):
        """
        Junta produtos duplicados do Catálogo. Se houver 2+ produtos selecionados na lista,
        junta ESSES; senão, procura sozinho (mesmo nome ou mesmo EAN em produtos diferentes).
        """
        ids = self._ids_selecionados_catalogo()
        if len(ids) >= 2:
            produtos = [{'ProdutoID': p.ProdutoID, 'NomeProduto': p.NomeProduto or '', 'UnidadeMedida': p.UnidadeMedida or 'UN',
                         'Categoria': getattr(p, 'Categoria', None) or 'Geral', 'Compras': None, 'Vinculos': None}
                        for p in self._cache_produtos if p.ProdutoID in ids]
            grupos = [{'Grupo': 1, 'Motivo': 'selecionados por você', 'Produtos': produtos, 'ManterID': min(ids)}]
        else:
            grupos = database.listar_produtos_duplicados() if hasattr(database, 'listar_produtos_duplicados') else []
        if not grupos:
            messagebox.showinfo("Duplicados", "Não encontrei produtos duplicados (mesmo nome ou mesmo EAN). 👍\n\n"
                                "Dica: para juntar dois produtos de nomes diferentes, selecione os dois na lista "
                                "(Ctrl + clique) e clique em '🔗 Juntar produtos duplicados'.", parent=self.root)
            return
        popup = Toplevel(self.root)
        popup.title("🔗 Juntar produtos duplicados")
        popup.geometry("1000x560")
        popup.transient(self.root)
        f = ttk.Frame(popup, padding=10)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, wraplength=960, justify="left", text=(
            "Cada grupo parece ser o MESMO produto cadastrado mais de uma vez. Juntar mantém o produto marcado como "
            "MANTER: os fornecedores/compras dos outros passam para ele e, nas contagens, as quantidades são SOMADAS. "
            "Duplo clique numa linha = escolher qual MANTER.")).pack(anchor="w", pady=(0, 6))
        cols = ('Ação', 'ID', 'Nome', 'UN', 'Categoria', 'Compras', 'Fornecedores')
        tree = criar_tree_zebrada(f, columns=cols, show='headings', selectmode='browse')
        for col, larg, anc in (('Ação', 160, 'w'), ('ID', 60, 'center'), ('Nome', 380, 'w'), ('UN', 45, 'center'),
                               ('Categoria', 120, 'w'), ('Compras', 70, 'center'), ('Fornecedores', 90, 'center')):
            tree.heading(col, text=col); tree.column(col, width=larg, anchor=anc)
        tree.tag_configure('grupo', background='#dfe8f5')
        tree.tag_configure('manter', foreground='#1b7a2f')
        sb = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.LEFT, fill=tk.Y)
        manter = {g['Grupo']: g['ManterID'] for g in grupos}

        def mostrar():
            for i in tree.get_children():
                tree.delete(i)
            for g in grupos:
                unidades = {p['UnidadeMedida'] for p in g['Produtos']}
                alerta = "  ⚠️ unidades diferentes!" if len(unidades) > 1 else ""
                tree.insert("", "end", iid=f"g{g['Grupo']}", tags=('grupo',), values=(
                    f"Grupo {g['Grupo']}", '', f"{len(g['Produtos'])} produtos · {g['Motivo']}{alerta}", '', '', '', ''))
                for p in g['Produtos']:
                    m = p['ProdutoID'] == manter[g['Grupo']]
                    tree.insert("", "end", iid=f"p{g['Grupo']}_{p['ProdutoID']}", tags=('manter',) if m else (), values=(
                        "✅ MANTER" if m else "   juntar", p['ProdutoID'], p['NomeProduto'], p['UnidadeMedida'], p['Categoria'],
                        '' if p['Compras'] is None else p['Compras'], '' if p['Vinculos'] is None else p['Vinculos']))

        def definir_manter(event=None):
            sel = linha_do_clique(tree, event)
            if not sel or not sel.startswith('p'):
                return
            g, pid = sel[1:].split('_')
            manter[int(g)] = int(pid)
            mostrar(); tree.focus(sel); tree.selection_set(sel)

        def juntar_grupo():
            sel = tree.focus()
            if not sel:
                messagebox.showwarning("Aviso", "Clique numa linha do grupo que você quer juntar.", parent=popup); return
            n = int(sel[1:].split('_')[0])
            g = next(x for x in grupos if x['Grupo'] == n)
            alvo = next(p for p in g['Produtos'] if p['ProdutoID'] == manter[n])
            outros = [p for p in g['Produtos'] if p['ProdutoID'] != manter[n]]
            unidades = {p['UnidadeMedida'] for p in g['Produtos']}
            aviso = (f"\n\n⚠️ As unidades são diferentes ({', '.join(sorted(unidades))}). As quantidades das contagens "
                     f"serão SOMADAS como se fossem {alvo['UnidadeMedida']}. Confira antes!") if len(unidades) > 1 else ""
            if not messagebox.askyesno("Juntar produtos",
                                       f"Juntar {len(outros)} produto(s) em:\n'{alvo['NomeProduto']}' (ID {alvo['ProdutoID']})?\n\n"
                                       + "\n".join(f"  • {p['NomeProduto']} (ID {p['ProdutoID']})" for p in outros[:8])
                                       + aviso, icon='warning' if aviso else 'question', parent=popup):
                return
            ok, msg = database.juntar_produtos(alvo['ProdutoID'], [p['ProdutoID'] for p in outros])
            if ok:
                self.status(msg)
                # [DEPURAÇÃO 2] se o produto aberto no formulário foi apagado, limpa o formulário
                if self.produto_selecionado_id in [p['ProdutoID'] for p in outros]:
                    self.limpar_formulario_produto()
                self._atualizar_buffet_apos_juntar(alvo['ProdutoID'], [p['ProdutoID'] for p in outros])
                grupos.remove(g)
                mostrar()
                self.atualizar_lista_produtos(); self.popular_combobox_produtos_mestre()
                if not grupos:
                    popup.destroy()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        tree.bind("<Double-1>", definir_manter)
        botoes = ttk.Frame(popup, padding=(10, 0, 10, 10))
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="🔗 Juntar o grupo selecionado", command=juntar_grupo).pack(side=tk.RIGHT, ipady=3)
        mostrar()
        self._janela_juntar_produtos = {'popup': popup, 'tree': tree, 'manter': manter, 'grupos': grupos,
                                        'definir_manter': definir_manter, 'juntar': juntar_grupo}

    def _atualizar_buffet_apos_juntar(self, manter_id, removidos):
        """Se algum produto juntado estava na lista de sabores do Buffet, troca pelo produto mantido."""
        caminho = os.path.join(PASTA_DO_PROGRAMA, 'config_sabores_buffet.json')
        try:
            if not os.path.exists(caminho):
                return
            with open(caminho, 'r', encoding='utf-8') as f:
                ids = json.load(f)
            if not isinstance(ids, list) or not any(int(i) in removidos for i in ids):
                return
            novos = []
            for i in ids:
                i = manter_id if int(i) in removidos else int(i)
                if i not in novos:
                    novos.append(i)
            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(novos, f)
        except (OSError, ValueError, TypeError) as e:
            logger.warning(f"Não foi possível atualizar a lista de sabores do buffet: {e}")

    def limpar_formulario_produto(self, limpar_selecao=True):
        self.entry_prod_nome.delete(0, tk.END)
        self.entry_prod_unidade.delete(0, tk.END)
        categorias = getattr(self, 'lista_categorias', []) or ["Geral"]
        self.combo_prod_categoria.set("Geral" if "Geral" in categorias else categorias[0])
        # [DEPURAÇÃO] o Estoque Mínimo não era limpo: um produto novo herdava o do anterior
        self.entry_prod_estoque_min.delete(0, tk.END)
        self.entry_prod_estoque_min.insert(0, "0.0")
        if hasattr(self, 'entry_prod_custo'):
            self._custo_editavel(True)
            self.entry_prod_custo.delete(0, tk.END)
            self.entry_prod_custo.insert(0, "0.00")
            self.lbl_prod_custo.config(text="Custo manual (R$):")
            self.lbl_prod_custo_info.config(text="Opcional: custo para produto sem nota fiscal.", foreground="gray")
        self.produto_selecionado_id = None
        self._form_produto_id = None
        self.produto_tem_nota = False
        self.custo_carregado_texto = None

        # Restaura visuais para Novo Cadastro
        self.form_frame_mestre.config(text="Modo: NOVO CADASTRO")
        self.btn_prod_salvar.config(text="Salvar Novo", state=tk.NORMAL)
        self.btn_excluir_mestre.config(state=tk.DISABLED) # Oculta botão excluir

        self.entry_prod_nome.focus()
        if limpar_selecao and self.tree_produtos.selection():
            # [DEPURAÇÃO] Antes, esta função era chamada também ao CLICAR num produto: ela tirava
            # a seleção da linha clicada (a linha "piscava" e perdia o destaque) e isso disparava
            # o evento de seleção de novo, carregando o produto 2 vezes do banco.
            # Agora só tira a seleção quando o usuário clica em "Limpar"/salva/exclui.
            self.tree_produtos.selection_remove(*self.tree_produtos.selection())
            self.tree_produtos.focus('')
    
    def abrir_gestor_categorias(self):
        """Abre uma janela pop-up para criar, editar e excluir categorias do sistema."""
        popup = Toplevel(self.root)
        popup.title("Gerenciador de Categorias")
        popup.geometry("400x500")
        popup.transient(self.root) # Mantém a janela sempre à frente da principal
        popup.grab_set() # Impede que o usuário clique fora enquanto não fechar

        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Categorias Atuais do Sistema:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 5))

        # Lista visual
        listbox_frame = ttk.Frame(frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical")
        # [DEPURAÇÃO 2] exportselection=False: selecionar texto no campo não "perde" a categoria marcada
        lista_categorias_ui = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set, font=("Arial", 11),
                                         selectbackground="#0078D7", exportselection=False)
        scrollbar.config(command=lista_categorias_ui.yview)
        
        lista_categorias_ui.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def atualizar_lista_ui():
            lista_categorias_ui.delete(0, tk.END)
            for cat in self.lista_categorias: # Lê da memória que acabou de ser atualizada do banco
                lista_categorias_ui.insert(tk.END, cat)

        atualizar_lista_ui()

        # Área de Formulário (Edição/Criação)
        ttk.Label(frame, text="Nome da Categoria:").pack(anchor="w", pady=(10, 2))
        entry_cat = ttk.Entry(frame, font=("Arial", 11))
        entry_cat.pack(fill=tk.X, pady=2)

        def on_select(event):
            # Preenche o input quando clica num item da lista
            selecao = lista_categorias_ui.curselection()
            if selecao:
                entry_cat.delete(0, tk.END)
                entry_cat.insert(0, lista_categorias_ui.get(selecao[0]))

        lista_categorias_ui.bind('<<ListboxSelect>>', on_select)

        # Botões de Ação
        frame_botoes = ttk.Frame(frame)
        frame_botoes.pack(fill=tk.X, pady=15)

        def acao_salvar_nova():
            nome = entry_cat.get().strip()
            if not nome: return messagebox.showwarning("Aviso", "Digite um nome.", parent=popup)
            
            sucesso, msg = database.criar_categoria_produto(nome)
            if sucesso:
                self.carregar_categorias_do_banco() # Sincroniza o app todo
                atualizar_lista_ui()
                entry_cat.delete(0, tk.END)
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        def acao_atualizar():
            selecao = lista_categorias_ui.curselection()
            if not selecao: return messagebox.showwarning("Aviso", "Selecione uma categoria na lista para editar.", parent=popup)
            
            nome_antigo = lista_categorias_ui.get(selecao[0])
            novo_nome = entry_cat.get().strip()
            
            if not novo_nome or novo_nome == nome_antigo: return
            
            if messagebox.askyesno("Confirmar Edição", f"Deseja renomear '{nome_antigo}' para '{novo_nome}'?\n\nISSO ATUALIZARÁ TODOS OS PRODUTOS DESTA CATEGORIA AUTOMATICAMENTE.", parent=popup):
                sucesso, msg = database.atualizar_categoria_produto(nome_antigo, novo_nome)
                if sucesso:
                    # [DEPURAÇÃO 2] o produto aberto no formulário acompanha o nome novo
                    # (antes a caixinha voltava para "Geral" e, ao salvar, o produto mudava de categoria)
                    if self.combo_prod_categoria.get() == nome_antigo:
                        self.combo_prod_categoria.set(novo_nome)
                    self.carregar_categorias_do_banco()
                    self.atualizar_lista_produtos() # Atualiza a tabela principal atrás do popup
                    atualizar_lista_ui()
                    entry_cat.delete(0, tk.END)
                    messagebox.showinfo("Sucesso", msg, parent=popup)
                else:
                    messagebox.showerror("Erro", msg, parent=popup)

        def acao_excluir():
            selecao = lista_categorias_ui.curselection()
            if not selecao: return messagebox.showwarning("Aviso", "Selecione uma categoria na lista para excluir.", parent=popup)
            
            nome_excluir = lista_categorias_ui.get(selecao[0])
            
            if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir a categoria '{nome_excluir}'?", parent=popup):
                sucesso, msg = database.excluir_categoria_produto(nome_excluir)
                if sucesso:
                    self.carregar_categorias_do_banco()
                    atualizar_lista_ui()
                    entry_cat.delete(0, tk.END)
                else:
                    messagebox.showerror("Bloqueado", msg, parent=popup)

        ttk.Button(frame_botoes, text="➕ Nova", command=acao_salvar_nova).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(frame_botoes, text="💾 Atualizar", command=acao_atualizar).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(frame_botoes, text="🗑️ Excluir", command=acao_excluir).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        
        ttk.Label(frame, text="💡 Dica: Se quiser apagar uma categoria, você deve primeiro alterar a categoria dos produtos que estão nela.", foreground="gray", font=("Arial", 8, "italic"), wraplength=350).pack(side=tk.BOTTOM, pady=5)

    def salvar_produto(self):
        nome = self.entry_prod_nome.get().strip()
        unidade = self.entry_prod_unidade.get().strip().upper()
        categoria = self.combo_prod_categoria.get() or "Geral"
        custo_texto = self.entry_prod_custo.get().strip()

        if not nome or not unidade:
            messagebox.showerror("Erro", "Nome e Unidade são obrigatórios.", parent=self.root)
            return
        try:
            # [DEPURAÇÃO] para_decimal aceita vírgula, "R$" e recusa 'NaN'/'Infinity'
            estoque_min = para_decimal(self.entry_prod_estoque_min.get() or "0", "Estoque Mínimo")
            custo_inicial = para_decimal(custo_texto, "Custo") if custo_texto else Decimal('0.00')
        except ValueError as ve:
            messagebox.showerror("Erro de Formatação", str(ve), parent=self.root)
            return

        # 3. Comunicação com o Banco de Dados
        try:
            if self.produto_selecionado_id:
                # Se estiver editando, atualiza os dados básicos (Nome, Estoque Min)
                database.atualizar_produto_estoque(self.produto_selecionado_id, nome, unidade, estoque_min, categoria)

                # [DEPURAÇÃO] Antes o custo era SEMPRE regravado, mesmo sem ninguém mexer nele.
                # Isso criava uma "nota fiscal manual" com a data de HOJE, que passava a ser
                # o "último custo" e escondia as notas reais importadas depois.
                # Agora só grava se o valor da caixinha foi realmente alterado.
                if not getattr(self, 'produto_tem_nota', False) and custo_texto and self._custo_mudou(custo_inicial):
                    if database.atualizar_custo_manual_produto(self.produto_selecionado_id, custo_inicial):
                        self.status("Produto e Custo atualizados com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
                    else:
                        messagebox.showwarning("Atenção", "Os dados do produto foram salvos, mas o CUSTO não pôde "
                                                          "ser gravado (veja o log).", parent=self.root)
                else:
                    self.status("Produto atualizado com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            else:
                # SE FOR NOVO: Chama nossa nova função mágica!
                novo_id = database.criar_produto_manual_com_custo(nome, unidade, estoque_min, categoria, custo_inicial) 
                
                if not novo_id: 
                    raise Exception("Falha ao criar produto. O banco não retornou o ID.")
                
                msg_extra = "\n\nCusto inicial salvo com sucesso via Fornecedor Interno!" if custo_inicial > 0 else ""
                self.status(f"Produto '{nome}' criado com sucesso!{msg_extra}")  # [MELHORIA UX] rodapé em vez de janelinha
            
            # Limpa e atualiza tudo
            self.limpar_formulario_produto()
            self.atualizar_lista_produtos()
            self.popular_combobox_produtos_mestre()
            
        except Exception as e:
            logger.error(f"Erro ao salvar produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível salvar o produto.\nErro: {e}", parent=self.root)

    def _custo_mudou(self, custo_novo):
        """[DEPURAÇÃO 2] compara NÚMEROS (antes '' x '0.00' contava como mudança e criava uma nota fantasma)."""
        try:
            antigo = para_decimal(self.custo_carregado_texto or "0", "Custo")
        except ValueError:
            return True
        return antigo != custo_novo

    FILTROS_CATALOGO = [
        ('todos', 'Todos os produtos'),
        ('minimo_zero', 'Estoque mínimo zerado'),
        ('sem_compra_90', 'Sem compra há mais de 90 dias'),
        ('nunca_comprado', 'Nunca comprado por nota'),
        ('sem_custo', 'Sem custo (vale R$ 0 no estoque)'),
        ('custo_manual', 'Com custo manual'),
    ]

    def _carregar_cache_catalogo(self):
        self._cache_produtos = database.listar_produtos_estoque() or []
        try:
            self._cache_resumo_catalogo = database.resumo_catalogo() if hasattr(database, 'resumo_catalogo') else {}
        except Exception as e:
            logger.error(f"Erro ao carregar resumo do catálogo: {e}", exc_info=True)
            self._cache_resumo_catalogo = {}

    def situacao_produto(self, p, r):
        """Lista de situações do produto (para a coluna 'Situação' e o filtro 'Mostrar')."""
        sit = []
        if r.get('CustoAtual') is None or r.get('CustoAtual') <= 0:
            sit.append('sem_custo')
        elif not r.get('TemNota'):
            sit.append('custo_manual')
        if not r.get('TemNota'):
            sit.append('nunca_comprado')
        elif r.get('UltimaCompra') and (date.today() - r['UltimaCompra']).days > 90:
            sit.append('sem_compra_90')
        try:
            if Decimal(str(p.EstoqueMinimo or 0)) <= 0:
                sit.append('minimo_zero')
        except (InvalidOperation, ValueError):
            sit.append('minimo_zero')
        return sit

    def atualizar_lista_produtos(self, event=None):
        """
        [MELHORIA CATÁLOGO] Quando chamada por uma tecla/filtro (event), usa os dados já carregados
        (rápido). Quando chamada pelo programa (sem event), relê o banco.
        """
        if event is None or not hasattr(self, '_cache_produtos'):
            try:
                self._carregar_cache_catalogo()
            except Exception as e:
                logger.error(f"Erro ao atualizar lista de produtos: {e}", exc_info=True)
                return
        selecionados = set(self.tree_produtos.selection())
        for i in self.tree_produtos.get_children():
            self.tree_produtos.delete(i)
        try:
            # [MELHORIA CATÁLOGO] busca sem acento, por várias palavras, também pelo ID
            palavras = sem_acento(self.entry_filtro_mestre.get()).split() if hasattr(self, 'entry_filtro_mestre') else []
            cat_filtro = self.combo_filtro_cat_mestre.get() if hasattr(self, 'combo_filtro_cat_mestre') else "Todas"
            rotulo = self.combo_filtro_situacao.get() if hasattr(self, 'combo_filtro_situacao') else ''
            filtro_sit = next((ch for ch, r in self.FILTROS_CATALOGO if r == rotulo), 'todos')
            icones = {'sem_custo': '⚠️ sem custo', 'custo_manual': '✍️ manual', 'sem_compra_90': '💤 +90 dias',
                      'nunca_comprado': '', 'minimo_zero': ''}
            count = 0
            for p in self._cache_produtos or []:
                cat = getattr(p, 'Categoria', None) or 'Geral'
                nome = p.NomeProduto or ''
                if cat_filtro != "Todas" and cat != cat_filtro: continue
                if palavras and not all(w in sem_acento(f"{nome} {p.ProdutoID}") for w in palavras): continue
                r = self._cache_resumo_catalogo.get(p.ProdutoID, {})
                sit = self.situacao_produto(p, r)
                if filtro_sit != 'todos' and filtro_sit not in sit: continue
                tag = 'par' if count % 2 == 0 else 'impar'
                un = p.UnidadeMedida or 'UN'
                custo = fmt_reais(r['CustoAtual']) if r.get('CustoAtual') else '—'
                ultima = r['UltimaCompra'].strftime('%d/%m/%Y') if r.get('UltimaCompra') else '—'
                barato = (f"{r['MaisBaratoFornecedor'][:22]} {fmt_reais(r['MaisBaratoCusto'])}"
                          if r.get('MaisBaratoFornecedor') and r.get('QtdFornecedores', 0) > 1 else
                          (r.get('FornecedorUltimo') or '—'))
                contagem = (f"{fmt_qtd(r['UltContagemQtd'])} {un} ({r['UltContagemData'].strftime('%d/%m')})"
                            if r.get('UltContagemData') and r.get('UltContagemQtd') is not None else '—')
                situacao = " ".join(t for t in (icones[x] for x in sit) if t)
                # [DEPURAÇÃO] EstoqueMinimo vazio (NULL) no banco fazia a LISTA INTEIRA sumir
                self.tree_produtos.insert("", "end", iid=str(p.ProdutoID), values=(
                    p.ProdutoID, nome, un, cat, fmt_num(p.EstoqueMinimo, 3, "0.000"),
                    custo, ultima, barato, contagem, situacao), tags=(tag,))
                count += 1
            for iid in selecionados:
                if self.tree_produtos.exists(iid):
                    self.tree_produtos.selection_add(iid)
            if hasattr(self, 'lbl_total_mestre'):
                self.lbl_total_mestre.config(text=f"Total exibido: {count} de {len(self._cache_produtos or [])} produto(s)")
        except Exception as e:
            logger.error(f"Erro ao atualizar lista de produtos: {e}", exc_info=True)

    def selecionar_produto_para_edicao(self, event=None):
        # [DEPURAÇÃO] usa a SELEÇÃO (e não o foco): assim "Limpar" funciona de verdade
        selecao = self.tree_produtos.selection()
        if not selecao: return
        if len(selecao) > 1:
            # [MELHORIA CATÁLOGO] vários produtos selecionados: edição em massa
            # [DEPURAÇÃO 2] o formulário é esvaziado e Salvar/Excluir ficam travados: antes eles
            # continuavam valendo para o 1º produto (Delete apagava só ele; "Atualizar" desfazia
            # a edição em massa nele; e "Salvar" podia criar um produto repetido).
            self.limpar_formulario_produto(limpar_selecao=False)
            self.form_frame_mestre.config(text=f"✅ {len(selecao)} PRODUTOS SELECIONADOS")
            self.btn_editar_massa.config(text=f"✏️ Editar os {len(selecao)} selecionados")
            self.btn_prod_salvar.config(state=tk.DISABLED)
            self.btn_excluir_mestre.config(state=tk.DISABLED)
            return
        self.btn_editar_massa.config(text="✏️ Editar selecionados")
        self.btn_prod_salvar.config(state=tk.NORMAL)
        selecionado = selecao[0]
        # [DEPURAÇÃO 2] A lista é redesenhada ao buscar/filtrar/F5 e a seleção é restaurada; isso
        # recarregava o formulário e APAGAVA o que você estava digitando. Mesmo produto = não recarrega.
        if self.produto_selecionado_id == int(selecionado) and getattr(self, '_form_produto_id', None) == int(selecionado):
            return
        dados = self.tree_produtos.item(selecionado, 'values')
        if not dados or len(dados) < 5: return
        produto_id, nome, unidade, categoria, estoque_min = dados[:5]

        # 1. Limpa a tela inteira primeiro (sem tirar a seleção do item clicado)
        self.limpar_formulario_produto(limpar_selecao=False)

        # 2. Preenche os dados básicos que vieram da tabela
        self.produto_selecionado_id = int(produto_id)
        self.entry_prod_nome.insert(0, nome)
        self.entry_prod_unidade.insert(0, unidade)
        self.combo_prod_categoria.set(categoria)
        self.entry_prod_estoque_min.delete(0, tk.END)
        self.entry_prod_estoque_min.insert(0, estoque_min)

        # 3. Custo
        # [MELHORIA CATÁLOGO] Se o produto já foi comprado por NOTA, o custo vem das notas
        # (média ponderada de 90 dias) e NÃO é editável aqui: antes dava para "mudar" o custo,
        # mas o Valor do Estoque ignorava, sem avisar. Sem nota, continua o custo manual.
        if hasattr(self, 'entry_prod_custo'):
            r = getattr(self, '_cache_resumo_catalogo', {}).get(self.produto_selecionado_id, {})
            # [DEPURAÇÃO 2] só recebido em BONIFICAÇÃO (custo 0): o custo manual volta a valer
            self.produto_tem_nota = bool(r.get('TemNota')) and bool(r.get('CustoAtual'))
            self._custo_editavel(True)
            self.entry_prod_custo.delete(0, tk.END)
            if self.produto_tem_nota:
                self.custo_carregado_texto = fmt_num(r.get('CustoAtual'), 2, "0.00")
                self.entry_prod_custo.insert(0, self.custo_carregado_texto)
                self._custo_editavel(False)
                self.lbl_prod_custo.config(text="Custo atual (das notas):")
                self.lbl_prod_custo_info.config(foreground="#0056b3", text=(
                    f"{r.get('OrigemCusto', '')}. Este é o custo usado no Valor do Estoque. "
                    "Para corrigir, ajuste a nota/vínculo (aba 8 Consultas ou Vínculos)."))
            else:
                custo_real = database.buscar_ultimo_custo_por_produto(self.produto_selecionado_id)
                # Formata para ficar bonito com duas casas decimais (Ex: 15.50)
                self.custo_carregado_texto = fmt_num(custo_real, 2, "0.00")  # [DEPURAÇÃO] None não trava
                self.entry_prod_custo.insert(0, self.custo_carregado_texto)
                self.lbl_prod_custo.config(text="Custo manual (R$):")
                self.lbl_prod_custo_info.config(foreground="gray", text=(
                    "Só recebido em BONIFICAÇÃO (custo 0): informe aqui o custo para o Valor do Estoque."
                    if r.get('TemNota') else
                    "Produto nunca comprado por nota: este custo manual é o usado no Valor do Estoque."))

        self._form_produto_id = self.produto_selecionado_id
        # 4. Visuais do Modo de Edição
        self.form_frame_mestre.config(text="🚨 MODO: EDIÇÃO")
        self.btn_prod_salvar.config(text="Atualizar Produto")
        self.btn_excluir_mestre.config(state=tk.NORMAL) # Habilita o botão de excluir apenas na edição

    def excluir_produto_selecionado(self):
        if not self.produto_selecionado_id:
            messagebox.showwarning("Aviso", "Selecione um produto da lista para excluir.", parent=self.root)
            return
        nome_produto = self.entry_prod_nome.get()
        if not messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o produto:\n\n'{nome_produto}'?", icon='warning', parent=self.root):
            return
        try:
            database.excluir_produto_estoque(self.produto_selecionado_id)
            self.status("Produto excluído com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            self.limpar_formulario_produto()
            self.atualizar_lista_produtos()
            self.popular_combobox_produtos_mestre()
        except ValueError as e:   # [AUDITORIA ESTOQUE] produto com compras/contagens: explica o que fazer
            messagebox.showwarning("Produto com histórico", str(e), parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao excluir produto: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", "Não foi possível excluir o produto.\nVerifique se ele já está vinculado a notas fiscais ou contagens.", parent=self.root)

    def abrir_popup_vinculos_produto(self, event):
        """
        Disparado pelo duplo clique na tabela mestre.
        [MELHORIA CATÁLOGO] Abre a janela única "Vínculos e Auditoria" já filtrada no produto
        (mesmo editor, com prévia do Qtd/Cx e correção das compras antigas).
        """
        selecionado = linha_do_clique(self.tree_produtos, event)
        if not selecionado: return
        dados = self.tree_produtos.item(selecionado, 'values')
        if hasattr(database, 'listar_vinculos_com_resumo'):
            self.abrir_gestor_vinculos(produto_id=int(dados[0]), nome_produto=dados[1],
                                       ao_salvar=self.atualizar_lista_produtos)
            return
        self._popup_vinculos_antigo(selecionado)

    def _popup_vinculos_antigo(self, selecionado):

        dados = self.tree_produtos.item(selecionado, 'values')
        produto_id = int(dados[0])
        nome_produto = dados[1]

        popup = Toplevel(self.root)
        popup.title(f"Vínculos do Produto Mestre: {nome_produto}")
        popup.geometry("800x350")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"Fornecedores que entregam '{nome_produto}':", font=("Arial", 10, "bold")).pack(anchor="w", pady=(0,10))

        # Tabela Pop-up (Adicionado ID oculto e mudado selectmode para 'browse')
        cols = ('ID', 'Fornecedor', 'Descrição no XML', 'EAN', 'Fator (Qtd/Cx)')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings', selectmode='browse')

        tree.heading('ID', text='ID'); tree.column('ID', width=0, stretch=tk.NO) # Esconde a coluna ID
        tree.heading('Fornecedor', text='Fornecedor'); tree.column('Fornecedor', width=150)
        tree.heading('Descrição no XML', text='Descrição na Nota Fiscal (XML)'); tree.column('Descrição no XML', width=250)
        tree.heading('EAN', text='EAN'); tree.column('EAN', width=100, anchor='center')
        tree.heading('Fator (Qtd/Cx)', text='Qtd por Caixa'); tree.column('Fator (Qtd/Cx)', width=100, anchor='center')

        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def carregar_lista_vinculos():
            for i in tree.get_children(): tree.delete(i)
            vinculos = database.buscar_vinculos_por_produto_mestre(produto_id)
            if not vinculos:
                tree.insert("", "end", values=("", "Nenhum vínculo encontrado.", "", "", ""))
            else:
                for v in vinculos:
                    # v = (ID, Fornecedor, Descricao, Fator, EAN)
                    fator_fmt = fmt_num(v[3], 2, "1.00") if v[3] else "1.00"
                    ean_fmt = v[4] if v[4] else "Sem EAN cadastrado"
                    tree.insert("", "end", values=(v[0], v[1], v[2], ean_fmt, fator_fmt))

        def editar_vinculo_clicado(event_tree):
            sel = tree.focus()
            if not sel: return
            vals = tree.item(sel, 'values')
            if not vals[0]: return 

            vinculo_id = vals[0]
            fornecedor = vals[1]
            desc_xml = vals[2]
            ean_atual = vals[3] if vals[3] != "Sem EAN cadastrado" else ""
            fator_atual = vals[4]

            edit_win = Toplevel(popup)
            edit_win.title("Edição Rápida de Vínculo")
            # Aumentamos um pouco a altura para caber o novo campo
            edit_win.geometry("400x320") 
            edit_win.transient(popup)

            f_edit = ttk.Frame(edit_win, padding="15")
            f_edit.pack(fill=tk.BOTH, expand=True)

            ttk.Label(f_edit, text=f"Fornecedor: {fornecedor}", font=("Arial", 9, "bold")).pack(anchor="w", pady=2)
            ttk.Label(f_edit, text=f"XML: {desc_xml}", font=("Arial", 8, "italic")).pack(anchor="w", pady=(0, 10))

            # --- NOVO CAMPO: Troca de Mestre ---
            ttk.Label(f_edit, text="Vinculado ao Produto Mestre:").pack(anchor="w")
            combo_mestre = ttk.Combobox(f_edit, values=self.lista_mestre_produtos_nomes, state="readonly")
            combo_mestre.pack(fill="x", pady=(0, 10))

            # Busca o nome de exibição do mestre atual para deixar pré-selecionado
            nome_mestre_atual_display = next((k for k, v in self.mapa_produtos_mestre.items() if v == produto_id), "")
            combo_mestre.set(nome_mestre_atual_display)
            # -----------------------------------

            ttk.Label(f_edit, text="EAN (Código de Barras):").pack(anchor="w")
            ent_ean = ttk.Entry(f_edit)
            ent_ean.pack(fill="x", pady=2)
            ent_ean.insert(0, ean_atual)

            ttk.Label(f_edit, text="Fator de Conversão (Qtd p/ Caixa):").pack(anchor="w", pady=(10,0))
            ent_fator = ttk.Entry(f_edit)
            ent_fator.pack(fill="x", pady=2)
            ent_fator.insert(0, fator_atual)

            def salvar():
                # [DEPURAÇÃO] fator 0 ou negativo gerava um ValueError que ninguém tratava
                # (a janela simplesmente não fazia nada). Agora aparece a mensagem de erro.
                try:
                    novo_fator = para_decimal(ent_fator.get(), "Fator", permitir_zero=False)
                except ValueError:
                    messagebox.showerror("Erro", "O Fator deve ser um número válido maior que zero.", parent=edit_win)
                    return
                try:
                    novo_ean = ent_ean.get().strip()

                    # Pega o ID do novo mestre selecionado no Combobox
                    novo_mestre_display = combo_mestre.get()
                    novo_mestre_id = self.mapa_produtos_mestre.get(novo_mestre_display)

                    if not novo_mestre_id:
                        messagebox.showerror("Erro", "Selecione um Produto Mestre válido.", parent=edit_win)
                        return

                    if database.atualizar_vinculo_simples(vinculo_id, novo_fator, novo_ean, novo_mestre_id):
                        messagebox.showinfo("Sucesso", "Vínculo atualizado com sucesso!", parent=edit_win)
                        edit_win.destroy()
                        carregar_lista_vinculos() # Atualiza a tabela imediatamente
                    else:
                        messagebox.showerror("Erro", "Falha ao salvar no banco de dados.", parent=edit_win)
                except Exception as e:
                    logger.error(f"Erro ao salvar vínculo {vinculo_id}: {e}", exc_info=True)
                    messagebox.showerror("Erro", f"Falha ao salvar: {e}", parent=edit_win)

            ttk.Button(f_edit, text="💾 Salvar Alterações", command=salvar).pack(pady=20, fill="x", ipady=5)

        # Bind do duplo-clique na sub-janela
        tree.bind("<Double-1>", editar_vinculo_clicado)

        # Carga Inicial
        carregar_lista_vinculos()

        ttk.Label(frame, text="* DICA: Dê um duplo-clique no vínculo acima para ajustar a Qtd/Caixa e o EAN rapidamente.", font=("Arial", 8, "italic"), foreground="green").pack(side=tk.BOTTOM, anchor="w", pady=(10,0))


    # ===================================================================
    # == ABA 2: FORNECEDORES (Sem alterações) ===========================
    # ===================================================================
    def criar_aba_fornecedores(self):
        # ... (código idêntico ao anterior) ...
        main_frame = ttk.Frame(self.frame_fornecedores)
        main_frame.pack(fill=tk.BOTH, expand=True)
        form_frame = ttk.LabelFrame(main_frame, text="Cadastrar/Editar Fornecedor", padding="10")
        form_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        ttk.Label(form_frame, text="Nome Fantasia:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_forn_nome = ttk.Entry(form_frame, width=40)
        self.entry_forn_nome.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(form_frame, text="CNPJ (apenas números):").grid(row=2, column=0, sticky="w", pady=2)
        self.entry_forn_cnpj = ttk.Entry(form_frame, width=40)
        self.entry_forn_cnpj.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 10))
        btn_frame = ttk.Frame(form_frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)
        self.btn_forn_salvar = ttk.Button(btn_frame, text="Salvar Novo", command=self.salvar_fornecedor)
        self.btn_forn_salvar.pack(side=tk.LEFT, padx=5)
        self.btn_forn_limpar = ttk.Button(btn_frame, text="Limpar", command=self.limpar_formulario_fornecedor)
        self.btn_forn_limpar.pack(side=tk.LEFT, padx=5)
        lista_frame = ttk.LabelFrame(main_frame, text="Fornecedores Cadastrados", padding="10")
        lista_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        lista_frame.rowconfigure(0, weight=1)
        lista_frame.columnconfigure(0, weight=1)
        cols_forn = ('ID', 'Nome Fantasia', 'CNPJ')
        self.tree_fornecedores = criar_tree_zebrada(lista_frame, columns=cols_forn, show='headings', selectmode='browse')
        self.tree_fornecedores.heading('ID', text='ID'); self.tree_fornecedores.column('ID', width=40, anchor='center')
        self.tree_fornecedores.heading('Nome Fantasia', text='Nome'); self.tree_fornecedores.column('Nome Fantasia', width=250)
        self.tree_fornecedores.heading('CNPJ', text='CNPJ'); self.tree_fornecedores.column('CNPJ', width=150, anchor='center')
        scrollbar_forn = ttk.Scrollbar(lista_frame, orient="vertical", command=self.tree_fornecedores.yview)
        self.tree_fornecedores.configure(yscrollcommand=scrollbar_forn.set)
        self.tree_fornecedores.grid(row=0, column=0, sticky="nsew")
        scrollbar_forn.grid(row=0, column=1, sticky="ns")
        self.tree_fornecedores.bind('<<TreeviewSelect>>', self.selecionar_fornecedor_para_edicao)
        lista_btn_frame_forn = ttk.Frame(lista_frame)
        lista_btn_frame_forn.grid(row=1, column=0, columnspan=2, pady=(10, 0))
        btn_excluir_forn = ttk.Button(lista_btn_frame_forn, text="Excluir Selecionado", command=self.excluir_fornecedor_selecionado)
        btn_excluir_forn.pack(side=tk.LEFT)

    def limpar_formulario_fornecedor(self, limpar_selecao=True):
        self.entry_forn_nome.delete(0, tk.END)
        self.entry_forn_cnpj.delete(0, tk.END)
        self.fornecedor_selecionado_id = None
        self.btn_forn_salvar.config(text="Salvar Novo")
        self.entry_forn_nome.focus()
        if limpar_selecao and self.tree_fornecedores.selection():
            self.tree_fornecedores.selection_remove(*self.tree_fornecedores.selection())
            self.tree_fornecedores.focus('')

    def salvar_fornecedor(self):
        nome = self.entry_forn_nome.get().strip()
        # [DEPURAÇÃO] Guardamos só os números. Antes, "12.345.678/0001-90" digitado à mão
        # não era reconhecido na importação do XML (que usa só números) e o sistema
        # criava o MESMO fornecedor duas vezes.
        cnpj = so_digitos(self.entry_forn_cnpj.get())
        if not nome or not cnpj:
            messagebox.showerror("Erro", "Nome Fantasia e CNPJ são obrigatórios.", parent=self.root)
            return
        if len(cnpj) not in (11, 14):
            messagebox.showerror("Erro", "O CNPJ deve ter 14 números (ou 11, se for CPF de produtor).", parent=self.root)
            return
        try:
            if self.fornecedor_selecionado_id:
                database.atualizar_fornecedor(self.fornecedor_selecionado_id, cnpj, nome)
                self.status("Fornecedor atualizado com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            else:
                database.criar_fornecedor(cnpj, nome)
                self.status("Fornecedor criado com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            self.limpar_formulario_fornecedor()
            self.atualizar_lista_fornecedores()
        except Exception as e:
            logger.error(f"Erro ao salvar fornecedor: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível salvar o fornecedor.\nVerifique se o CNPJ já não está cadastrado.\nErro: {e}", parent=self.root)

    def atualizar_lista_fornecedores(self):
        # ... (código idêntico ao anterior) ...
        for i in self.tree_fornecedores.get_children():
            self.tree_fornecedores.delete(i)
        try:
            fornecedores = database.listar_fornecedores()
            for f in fornecedores or []:
                self.tree_fornecedores.insert("", "end", values=(f.FornecedorID, f.NomeFantasia or '', f.CNPJ or ''))
        except Exception as e:
            logger.error(f"Erro ao atualizar lista de fornecedores: {e}", exc_info=True)

    def selecionar_fornecedor_para_edicao(self, event=None):
        selecao = self.tree_fornecedores.selection()   # [DEPURAÇÃO] seleção, não foco
        if not selecao: return
        dados = self.tree_fornecedores.item(selecao[0], 'values')
        if not dados or len(dados) < 3: return
        fornecedor_id, nome, cnpj = dados[:3]
        self.limpar_formulario_fornecedor(limpar_selecao=False)
        self.fornecedor_selecionado_id = int(fornecedor_id)
        self.entry_forn_nome.insert(0, nome)
        self.entry_forn_cnpj.insert(0, cnpj)
        self.btn_forn_salvar.config(text="Atualizar Fornecedor")

    def excluir_fornecedor_selecionado(self):
        # ... (código idêntico ao anterior) ...
        if not self.fornecedor_selecionado_id:
            messagebox.showwarning("Aviso", "Selecione um fornecedor da lista para excluir.", parent=self.root)
            return
        nome_fornecedor = self.entry_forn_nome.get()
        if not messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o fornecedor:\n\n'{nome_fornecedor}'?", icon='warning', parent=self.root):
            return
        try:
            database.excluir_fornecedor(self.fornecedor_selecionado_id)
            self.status("Fornecedor excluído com sucesso!")  # [MELHORIA UX] rodapé em vez de janelinha
            self.limpar_formulario_fornecedor()
            self.atualizar_lista_fornecedores()
        except Exception as e:
            logger.error(f"Erro ao excluir fornecedor: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", "Não foi possível excluir o fornecedor.\nVerifique se ele já está vinculado a notas fiscais.", parent=self.root)

    # ===================================================================
    # == ABA 3: IMPORTAÇÃO XML (ATUALIZADA com Filtro) ==================
    # ===================================================================
    def criar_aba_importacao_xml(self):
        main_frame = ttk.Frame(self.frame_importacao)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1) 
        main_frame.rowconfigure(3, weight=1) 
        frame_botoes = ttk.Frame(main_frame)
        frame_botoes.grid(row=0, column=0, sticky="ew", pady=5)
        btn_selecionar_pasta = ttk.Button(frame_botoes, text="1. Selecionar Pasta com XMLs de Compra", command=self.abrir_seletor_pasta_xml)
        btn_selecionar_pasta.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10)
        # [DEPURAÇÃO] Depois de vincular itens, basta clicar aqui (não precisa escolher a pasta de novo)
        btn_reprocessar = ttk.Button(frame_botoes, text="🔄 Reprocessar Pasta Atual", command=self.reprocessar_pasta_xml)
        btn_reprocessar.pack(side=tk.LEFT, padx=(5, 0), ipady=10)
        # [MELHORIA ST] Corrige o custo de notas JÁ SALVAS (ex: importadas sem a ST)
        ttk.Button(frame_botoes, text="🧾 Recalcular custos de notas já salvas",
                   command=self.recalcular_custos_notas_salvas).pack(side=tk.LEFT, padx=(5, 0), ipady=10)
        # [MELHORIA ST] Sem XML: usa o valor total da nota que já está gravado
        ttk.Button(frame_botoes, text="🧮 Ajustar notas antigas (sem XML)",
                   command=self.abrir_ajuste_por_valor_da_nota).pack(side=tk.LEFT, padx=(5, 0), ipady=10)
        # [MELHORIA UX] Placar da importação: quanto falta e quanto já está pronto
        self.lbl_resumo_importacao = ttk.Label(frame_botoes, text="Nenhuma pasta carregada ainda.",
                                               font=("Arial", 10, "bold"))
        self.lbl_resumo_importacao.pack(side=tk.LEFT, padx=15)
        frame_vincular = ttk.LabelFrame(main_frame, text="2. Itens Pendentes de Vinculação (DE/PARA)", padding="10")
        frame_vincular.grid(row=1, column=0, sticky="nsew", pady=5)
        frame_vincular.rowconfigure(0, weight=1)
        frame_vincular.columnconfigure(0, weight=1)
        # --- COLUNAS ATUALIZADAS (Removido NCM, Adicionado Qtd/Custo) ---
        cols_vinc = ('Fornecedor', 'Produto no XML', 'EAN', 'Qtd na Nota', 'Custo Unit.', 'Custo Total')
        self.tree_vincular = criar_tree_zebrada(frame_vincular, columns=cols_vinc, show='headings', selectmode='browse')

        self.tree_vincular.heading('Fornecedor', text='Fornecedor'); self.tree_vincular.column('Fornecedor', width=150)
        self.tree_vincular.heading('Produto no XML', text='Produto no XML'); self.tree_vincular.column('Produto no XML', width=250)
        self.tree_vincular.heading('EAN', text='EAN'); self.tree_vincular.column('EAN', width=100, anchor='center')
        self.tree_vincular.heading('Qtd na Nota', text='Qtd Nota'); self.tree_vincular.column('Qtd na Nota', width=60, anchor='center')
        self.tree_vincular.heading('Custo Unit.', text='Custo Unit.'); self.tree_vincular.column('Custo Unit.', width=80, anchor='e')
        self.tree_vincular.heading('Custo Total', text='Custo Total'); self.tree_vincular.column('Custo Total', width=80, anchor='e')
        self.tree_vincular.grid(row=0, column=0, sticky="nsew")
        self.tree_vincular.bind("<<TreeviewSelect>>", self.sugerir_mestre_por_ean)
        frame_ferramenta = ttk.Frame(main_frame)
        frame_ferramenta.grid(row=2, column=0, sticky="ew", pady=10)
        frame_ferramenta.columnconfigure(1, weight=1)
        ttk.Label(frame_ferramenta, text="Filtrar Lista:").grid(row=0, column=0, sticky="w", padx=(0,5))
        self.entry_filtro_importacao = ttk.Entry(frame_ferramenta, width=25)
        self.entry_filtro_importacao.grid(row=0, column=1, sticky="ew", padx=(0,10))
        self.entry_filtro_importacao.bind("<KeyRelease>", self.filtrar_combo_importacao)
        ttk.Label(frame_ferramenta, text="Vincular ao Mestre:").grid(row=0, column=2, sticky="w", padx=(10,5))
        self.combo_produtos_mestre = ttk.Combobox(frame_ferramenta, state="readonly", width=35)
        self.combo_produtos_mestre.grid(row=0, column=3, sticky="ew", padx=(0,5))
       # --- NOVO CAMPO: FATOR DE CONVERSÃO ---
        ttk.Label(frame_ferramenta, text="Itens p/ Cx:").grid(row=0, column=4, sticky="w")
        self.entry_fator_conversao = ttk.Entry(frame_ferramenta, width=5)
        self.entry_fator_conversao.insert(0, "1") # Padrão é 1 para 1
        self.entry_fator_conversao.grid(row=0, column=5, sticky="w", padx=(0,10))
        
        ttk.Label(frame_ferramenta, text="EAN (Opc.):").grid(row=0, column=6, sticky="w")
        self.entry_ean_importacao = ttk.Entry(frame_ferramenta, width=10)
        self.entry_ean_importacao.grid(row=0, column=7, sticky="w", padx=(0,5))

        ttk.Label(frame_ferramenta, text="Cat. Novo:").grid(row=0, column=8, sticky="w")
        self.combo_cat_importacao = ttk.Combobox(frame_ferramenta, values=self.lista_categorias, width=10, state="readonly")
        self.combo_cat_importacao.grid(row=0, column=9, sticky="w", padx=(0,5))
        self.combo_cat_importacao.set("Geral")

        btn_vincular = ttk.Button(frame_ferramenta, text="Vincular", command=self.vincular_produto_selecionado)
        btn_vincular.grid(row=0, column=10, sticky="w", padx=2)
        btn_criar_vincular = ttk.Button(frame_ferramenta, text="Criar e Vincular", command=self.criar_mestre_e_vincular)
        btn_criar_vincular.grid(row=0, column=11, sticky="w", padx=2)
        frame_prontos = ttk.LabelFrame(main_frame, text="3. Itens Prontos para Salvar (Já Vinculados)", padding="10")
        frame_prontos.grid(row=3, column=0, sticky="nsew", pady=5)
        frame_prontos.rowconfigure(0, weight=1)
        frame_prontos.columnconfigure(0, weight=1)
        cols_prontos = ('NF', 'Fornecedor', 'Produto Mestre', 'Qtd', 'Custo Unit.', 'Custo Total')
        self.tree_prontos = criar_tree_zebrada(frame_prontos, columns=cols_prontos, show='headings', selectmode='none')
        for col in cols_prontos: self.tree_prontos.heading(col, text=col)
        self.tree_prontos.column('NF', width=80, anchor='center')
        self.tree_prontos.column('Fornecedor', width=150)
        self.tree_prontos.column('Produto Mestre', width=200)
        self.tree_prontos.column('Qtd', width=60, anchor='e')
        self.tree_prontos.column('Custo Unit.', width=80, anchor='e')
        self.tree_prontos.column('Custo Total', width=80, anchor='e')
        self.tree_prontos.grid(row=0, column=0, sticky="nsew")
        btn_salvar_tudo = ttk.Button(main_frame, text="4. Salvar Todas as Notas Processadas no Banco", command=self.salvar_notas_processadas)
        btn_salvar_tudo.grid(row=4, column=0, sticky="ew", pady=10, ipady=10)
        self.btn_salvar_notas = btn_salvar_tudo
        self.btn_salvar_notas.state(['disabled'])  # [MELHORIA UX] só libera quando há nota pronta
        # Botão de Gerenciamento de Vínculos (Correção)
        btn_gerir_vinculos = ttk.Button(main_frame, text="🛠️ Gerenciar / Corrigir Vínculos Salvos", command=self.abrir_gestor_vinculos)
        btn_gerir_vinculos.grid(row=5, column=0, sticky="ew", pady=(0, 10))

    def _pendente_da_linha(self, iid, valores):
        """
        [DEPURAÇÃO 2] Item pendente da linha clicada. Antes procurava pelo NOME do fornecedor +
        descrição: duas filiais com o mesmo nome (CNPJs diferentes) vendendo o mesmo item
        faziam o vínculo ir para a filial errada.
        """
        if str(iid).startswith('pend_'):
            uid = int(str(iid)[5:])
            achado = next((i for i in self.itens_xml_nao_vinculados if i.get('_uid') == uid), None)
            if achado:
                return achado
        return next((i for i in self.itens_xml_nao_vinculados
                     if i['DescricaoXML'] == valores[1] and i['FornecedorNome'] == valores[0]), None)

    def sugerir_mestre_por_ean(self, event):
        """
        Ao clicar num item pendente, verifica se o EAN já existe no sistema.
        Se existir, seleciona automaticamente o Produto Mestre no Combobox.
        """
        selecionado = self.tree_vincular.focus()
        if not selecionado: return

        # Pega os dados da linha clicada
        # Ordem das colunas: Fornecedor, ProdutoXML, EAN, Qtd, Custo...
        valores = self.tree_vincular.item(selecionado, 'values')
        ean_clicado = valores[2] # O EAN é a terceira coluna (índice 2)
        # [DEPURAÇÃO 2] trocou de item: limpa o EAN e o Qtd/Cx digitados para o item anterior
        if getattr(self, '_ultimo_pendente_clicado', None) != selecionado:
            self._ultimo_pendente_clicado = selecionado
            for campo, padrao in ((getattr(self, 'entry_ean_importacao', None), ''),
                                  (getattr(self, 'entry_fator_conversao', None), '1')):
                if campo is not None:
                    campo.delete(0, tk.END)
                    if padrao:
                        campo.insert(0, padrao)

        # 1. Tenta descobrir quem é esse EAN
        try:
            sugestao = database.descobrir_produto_mestre_por_ean(ean_clicado)
        except Exception as e:
            logger.error(f"Erro ao procurar o EAN {ean_clicado}: {e}", exc_info=True)
            sugestao = None

        if sugestao:
            nome_mestre, id_mestre = sugestao
            # Formata como aparece no Combobox: "Nome (ID: 123)"
            texto_combo = f"{nome_mestre} (ID: {id_mestre})"

            # Verifica se essa opção existe na lista atual do combo
            if texto_combo in self.lista_mestre_produtos_nomes:
                self.combo_produtos_mestre.set(texto_combo)
                logger.info(f"Sugestão Automática: {texto_combo}")
            else:
                self.combo_produtos_mestre.set('')
        else:
            # Se não achou nada, limpa para não confundir
            self.combo_produtos_mestre.set('')

    def popular_combobox_produtos_mestre(self):
        try:
            produtos = database.listar_produtos_estoque()

            # Limpa memórias globais
            self.mapa_produtos_mestre.clear()
            self.lista_mestre_produtos_nomes.clear() 
            self.mapa_produtos_mestre_contagem.clear() 

            nomes_produtos_mestre = []
            self._unidade_por_id = {}
            # [DEPURAÇÃO 2] Dois produtos com o MESMO nome viravam um só na contagem (o 2º
            # apagava o 1º, que nunca podia ser contado). Agora o repetido leva o ID no nome.
            # Nome vazio no banco também não derruba mais a lista inteira.
            def nome_de(p):
                return (p.NomeProduto or '').strip() or f"Produto {p.ProdutoID}"
            repetidos = collections.Counter(nome_de(p) for p in produtos)

            for p in produtos:
                # Dados para a Aba 3 (Vínculos)
                nome_display = f"{nome_de(p)} (ID: {p.ProdutoID})"
                nomes_produtos_mestre.append(nome_display)
                self.mapa_produtos_mestre[nome_display] = p.ProdutoID
                self._unidade_por_id[p.ProdutoID] = (p.UnidadeMedida or 'UN')

                # Dados para a Aba 4 (Contagem - Independente de filtros)
                chave = nome_de(p) if repetidos[nome_de(p)] == 1 else nome_display
                self.mapa_produtos_mestre_contagem[chave] = {'id': p.ProdutoID, 'un': p.UnidadeMedida or 'UN'}

            # Configurações da Aba 3
            self.lista_mestre_produtos_nomes = sorted(nomes_produtos_mestre) 
            self.combo_produtos_mestre['values'] = self.lista_mestre_produtos_nomes

            # Configurações da Aba 4
            self.lista_mestre_contagem_nomes = sorted(list(self.mapa_produtos_mestre_contagem.keys()))
            # [MELHORIA CONTAGEM] caixas conhecidas de cada produto (Qtd/Cx dos vínculos)
            try:
                self.embalagens_contagem = getattr(database, 'embalagens_por_produto', lambda: {})() or {}
            except Exception as e:
                logger.warning(f"Não foi possível carregar as embalagens para a contagem: {e}")
                self.embalagens_contagem = {}
            if hasattr(self, 'combo_contagem_produtos'):
                self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes
        except Exception as e:
            logger.error(f"Erro ao carregar produtos mestre no combobox: {e}", exc_info=True)

    def unidade_do_produto(self, produto_id):
        """Unidade do estoque de um produto pelo ID (UN se não souber)."""
        return (getattr(self, '_unidade_por_id', {}) or {}).get(produto_id) or 'UN'

    def filtrar_combo_importacao(self, event=None):
        # ... (código idêntico ao anterior) ...
        texto = self.entry_filtro_importacao.get().lower()
        if not texto:
            self.combo_produtos_mestre['values'] = self.lista_mestre_produtos_nomes
            self.combo_produtos_mestre.set('')
        else:
            filtrados = [nome for nome in self.lista_mestre_produtos_nomes if texto in nome.lower()]
            self.combo_produtos_mestre['values'] = filtrados
            if filtrados:
                self.combo_produtos_mestre.set(filtrados[0])
            else:
                self.combo_produtos_mestre.set('')

    def abrir_seletor_pasta_xml(self):
        pasta_selecionada = filedialog.askdirectory(title="Selecione a pasta contendo os XMLs", parent=self.root)
        if not pasta_selecionada:
            return
        self._carregar_pasta_xml(pasta_selecionada)

    def reprocessar_pasta_xml(self):
        """[DEPURAÇÃO] Lê de novo a última pasta escolhida (útil depois de criar vínculos)."""
        if not self.ultima_pasta_xml or not os.path.isdir(self.ultima_pasta_xml):
            messagebox.showwarning("Aviso", "Nenhuma pasta foi carregada ainda. Use o botão '1. Selecionar Pasta'.", parent=self.root)
            return
        self._carregar_pasta_xml(self.ultima_pasta_xml)

    def montar_recalculo_custos(self, pasta):
        """
        [MELHORIA ST] Lê os XMLs da pasta e compara o custo que DEVERIA ter (com ST, FCP-ST,
        frete etc. — inclusive os valores que vêm só no total da nota) com o custo gravado
        nas notas que JÁ FORAM SALVAS. Não grava nada: devolve (alteracoes, resumo).
        alteracoes = [{'ItemNotaID','NF','Fornecedor','Descricao','Quantidade','CustoAtual','CustoNovo'}]
        """
        alteracoes, resumo = [], {'arquivos': 0, 'notas': 0, 'nao_importadas': 0, 'sem_vinculo': 0, 'falhas': 0}
        arquivos = sorted(os.path.join(pasta, f) for f in os.listdir(pasta) if f.lower().endswith(('.xml', '.txt')))
        vistas = set()
        for caminho in arquivos:
            resumo['arquivos'] += 1
            try:
                cab, itens = self.ler_xml_nota_fiscal(caminho)
            except Exception:
                resumo['falhas'] += 1
                continue
            if cab.get('Finalidade') == '4':
                continue
            fornecedor_id = database.buscar_fornecedor_por_cnpj(cab['FornecedorCNPJ'])
            nota_id = (database.buscar_nota_importada(cab['NumeroNF'], fornecedor_id, cab.get('Serie'), cab.get('ChaveAcesso'))
                       if fornecedor_id else None)
            if not nota_id:
                resumo['nao_importadas'] += 1
                continue
            if nota_id in vistas:
                continue
            vistas.add(nota_id)
            resumo['notas'] += 1
            gravados = database.itens_nota_para_recalculo(nota_id)
            usados = set()
            for it in itens:
                tipo = tipo_item_por_cfop(it.get('CFOP'))
                if tipo == 'ignorar':
                    continue
                achado = database.buscar_vinculo_inteligente(fornecedor_id, it['DescricaoXML'], it.get('cProd'), it.get('cEAN'))
                if not achado:
                    resumo['sem_vinculo'] += 1
                    continue
                total_xml = Decimal('0') if tipo == 'bonificacao' else it['PrecoCustoUnitario'] * it['Quantidade']
                fator = Decimal(str(achado['Fator'] or 1)) if Decimal(str(achado['Fator'] or 1)) > 0 else Decimal('1')
                qtd_esperada = it['Quantidade'] * fator
                candidatos = [g for g in gravados if g['ProdutoFornecedorID'] == achado['ProdutoFornecedorID']
                              and g['ItemNotaID'] not in usados]
                # prefere a linha com a mesma quantidade (o mesmo produto pode vir 2x na nota)
                candidatos.sort(key=lambda g: abs(g['Quantidade'] - qtd_esperada))
                if not candidatos or candidatos[0]['Quantidade'] <= 0:
                    resumo['sem_vinculo'] += 1
                    continue
                g = candidatos[0]
                usados.add(g['ItemNotaID'])
                novo = (total_xml / g['Quantidade']).quantize(Decimal('0.0001'))
                if abs(novo - g['Custo']) >= Decimal('0.0001'):
                    alteracoes.append({'ItemNotaID': g['ItemNotaID'], 'NF': cab['NumeroNF'], 'Fornecedor': cab['FornecedorNome'],
                                       'Descricao': it['DescricaoXML'], 'Quantidade': g['Quantidade'],
                                       'CustoAtual': g['Custo'], 'CustoNovo': novo})
        return alteracoes, resumo

    def recalcular_custos_notas_salvas(self):
        """[MELHORIA ST] Escolhe a pasta de XMLs, mostra a prévia das mudanças e aplica se o usuário confirmar."""
        pasta = filedialog.askdirectory(title="Pasta com os XMLs das notas JÁ SALVAS", parent=self.root)
        if not pasta:
            return
        self.root.config(cursor="watch"); self.root.update_idletasks()
        try:
            alteracoes, resumo = self.montar_recalculo_custos(pasta)
        except Exception as e:
            logger.error(f"Erro ao preparar recálculo de custos: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível ler a pasta:\n{e}", parent=self.root)
            return
        finally:
            self.root.config(cursor="")
        info = (f"{resumo['arquivos']} arquivo(s) lido(s) · {resumo['notas']} nota(s) já salvas conferidas · "
                f"{resumo['nao_importadas']} ainda não importada(s)")
        if not alteracoes:
            messagebox.showinfo("Custos conferidos", f"Nenhum custo precisa mudar. 👍\n\n{info}", parent=self.root)
            return

        popup = Toplevel(self.root)
        popup.title("🧾 Recalcular custos de notas já salvas")
        popup.geometry("1100x560")
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        diferenca = sum(((a['CustoNovo'] - a['CustoAtual']) * a['Quantidade'] for a in alteracoes), Decimal('0'))
        notas = len({(a['NF'], a['Fornecedor']) for a in alteracoes})
        ttk.Label(frame, font=("Arial", 11, "bold"), text=(
            f"{len(alteracoes)} item(ns) em {notas} nota(s) estão com o custo diferente do XML "
            f"(diferença total: {'+' if diferenca >= 0 else ''}{fmt_reais(diferenca)}).")).pack(anchor="w")
        ttk.Label(frame, foreground="gray", text=(
            f"{info}.  Só o CUSTO muda (as quantidades ficam iguais). Contagens com o valor do estoque já "
            "FECHADO não mudam.")).pack(anchor="w", pady=(0, 6))
        cols = ('NF', 'Fornecedor', 'Item na nota', 'Qtd', 'Custo atual/unid.', 'Custo novo/unid.', 'Diferença')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings')
        for col, larg, anc in (('NF', 70, 'center'), ('Fornecedor', 200, 'w'), ('Item na nota', 330, 'w'), ('Qtd', 70, 'e'),
                               ('Custo atual/unid.', 120, 'e'), ('Custo novo/unid.', 120, 'e'), ('Diferença', 110, 'e')):
            tree.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(tree, c, False))
            tree.column(col, width=larg, anchor=anc)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.LEFT, fill=tk.Y)
        for a in alteracoes:
            dif = (a['CustoNovo'] - a['CustoAtual']) * a['Quantidade']
            tree.insert("", "end", values=(a['NF'], a['Fornecedor'], a['Descricao'], fmt_qtd(a['Quantidade']),
                                           fmt_reais(a['CustoAtual']), fmt_reais(a['CustoNovo']),
                                           f"{'+' if dif >= 0 else ''}{fmt_reais(dif)}"))

        def aplicar():
            if not messagebox.askyesno("Aplicar", f"Gravar os novos custos em {len(alteracoes)} item(ns)?", parent=popup):
                return
            ok, msg = database.atualizar_custos_itens([(a['ItemNotaID'], a['CustoNovo']) for a in alteracoes])
            if ok:
                self.status(f"Custos recalculados: {msg}")
                self.atualizar_lista_produtos()   # [DEPURAÇÃO 2] coluna "Custo atual" do catálogo
                messagebox.showinfo("Pronto", f"{msg}\n\nAbra o '💰 Valor do Estoque' e clique em '🔄 Recalcular' "
                                    "nas contagens em aberto para ver o efeito.", parent=popup)
                popup.destroy()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        botoes = ttk.Frame(popup, padding=(10, 0, 10, 10))
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="✅ Aplicar os novos custos", command=aplicar).pack(side=tk.RIGHT, ipady=3)
        ttk.Button(botoes, text="Cancelar", command=popup.destroy).pack(side=tk.RIGHT, padx=5, ipady=3)
        self._janela_recalculo = {'popup': popup, 'tree': tree, 'aplicar': aplicar, 'alteracoes': alteracoes}

    def abrir_ajuste_por_valor_da_nota(self):
        """
        [MELHORIA ST - sem XML] Para notas antigas importadas sem a ST (ou frete etc.) que vinha
        só no total. Compara o VALOR TOTAL DA NOTA (gravado na importação) com a soma dos itens
        e reparte a diferença nos itens, proporcional ao valor de cada um.
        A diferença também pode ser item de comodato ignorado ou item não salvo, por isso
        VOCÊ escolhe as notas (filtro por fornecedor, marcar/desmarcar, prévia dos itens).
        """
        popup = Toplevel(self.root)
        popup.title("🧮 Ajustar custos pelo valor total da nota (sem XML)")
        popup.geometry("1150x700")
        popup.transient(self.root)
        estado = {'notas': [], 'marcadas': set()}

        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, wraplength=1100, justify="left", text=(
            "Estas notas têm o VALOR TOTAL maior que a soma dos itens gravados. Normalmente a diferença é ST, FCP-ST "
            "ou frete que vinham só no total da nota e ficaram FORA do custo. Marque (✔) as notas que você sabe que "
            "têm ST e clique em Aplicar: a diferença é dividida entre os itens, proporcional ao valor de cada um.")).pack(anchor="w")
        ttk.Label(frame, foreground="#b35c00", wraplength=1100, justify="left", text=(
            "⚠️ Em LARANJA: diferença grande ou nota com item de BONIFICAÇÃO — pode NÃO ser imposto (comodato, "
            "bonificação ou nota salva incompleta). Essas não são marcadas no 'Marcar todas': confira os itens embaixo. "
            "Notas importadas a partir desta versão já descontam sozinhas o valor da bonificação e do comodato.")).pack(anchor="w", pady=(2, 8))

        filtros = ttk.Frame(frame)
        filtros.pack(fill=tk.X)
        ttk.Label(filtros, text="Fornecedor:").pack(side=tk.LEFT)
        combo_forn = ttk.Combobox(filtros, state="readonly", width=40)
        combo_forn.pack(side=tk.LEFT, padx=5)
        ttk.Label(filtros, text="Buscar:").pack(side=tk.LEFT, padx=(10, 3))
        entry_busca = ttk.Entry(filtros, width=20)
        entry_busca.pack(side=tk.LEFT)
        lbl_resumo = ttk.Label(filtros, text="", font=("Arial", 10, "bold"))
        lbl_resumo.pack(side=tk.RIGHT)

        cols = ('✔', 'Data', 'NF', 'Fornecedor', 'Itens', 'Valor da nota', 'Soma dos itens', 'Diferença', '%')
        frame_notas = ttk.Frame(frame)
        frame_notas.pack(fill=tk.BOTH, expand=True, pady=6)
        tree = criar_tree_zebrada(frame_notas, columns=cols, show='headings', selectmode='browse', height=12)
        for col, larg, anc in (('✔', 35, 'center'), ('Data', 90, 'center'), ('NF', 80, 'center'), ('Fornecedor', 330, 'w'),
                               ('Itens', 55, 'center'), ('Valor da nota', 120, 'e'), ('Soma dos itens', 120, 'e'),
                               ('Diferença', 110, 'e'), ('%', 70, 'e')):
            if col == '✔':
                tree.heading(col, text=col)
            else:
                tree.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(tree, c, False))
            tree.column(col, width=larg, anchor=anc)
        tree.tag_configure('alerta', background='#ffe3b3')
        tree.tag_configure('marcada', foreground='#1b7a2f')
        sb = ttk.Scrollbar(frame_notas, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.LEFT, fill=tk.Y)

        lbl_itens = ttk.Label(frame, text="Itens da nota selecionada (prévia — nada é gravado até clicar em Aplicar):",
                              font=("Arial", 10, "bold"))
        lbl_itens.pack(anchor="w")
        cols_i = ('Produto', 'Descrição na nota', 'Qtd', 'Custo atual/unid.', 'Custo novo/unid.', 'Acréscimo no item')
        tree_itens = criar_tree_zebrada(frame, columns=cols_i, show='headings', height=6)
        for col, larg, anc in (('Produto', 230, 'w'), ('Descrição na nota', 330, 'w'), ('Qtd', 70, 'e'),
                               ('Custo atual/unid.', 120, 'e'), ('Custo novo/unid.', 120, 'e'), ('Acréscimo no item', 130, 'e')):
            tree_itens.heading(col, text=col); tree_itens.column(col, width=larg, anchor=anc)
        tree_itens.pack(fill=tk.X)

        LIMITE_ALERTA = Decimal('40')   # % acima disso: provavelmente não é só imposto

        def carregar():
            try:
                estado['notas'] = database.listar_notas_com_diferenca() or []
            except Exception as e:
                logger.error(f"Erro ao listar notas com diferença: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao ler as notas:\n{e}", parent=popup)
                estado['notas'] = []
            ids = {n['NotaID'] for n in estado['notas']}
            estado['marcadas'] &= ids
            fornecedores = sorted({n['Fornecedor'] for n in estado['notas']})
            atual = combo_forn.get()
            combo_forn['values'] = ['Todos'] + fornecedores
            combo_forn.set(atual if atual in fornecedores else 'Todos')
            mostrar()

        def visiveis():
            forn = combo_forn.get()
            palavras = sem_acento(entry_busca.get()).split()
            for n in estado['notas']:
                if forn and forn != 'Todos' and n['Fornecedor'] != forn:
                    continue
                if palavras and not all(p in sem_acento(f"{n['NumeroNF']} {n['Fornecedor']}") for p in palavras):
                    continue
                yield n

        def mostrar():
            sel = tree.focus()
            for i in tree.get_children():
                tree.delete(i)
            for n in visiveis():
                marcada = n['NotaID'] in estado['marcadas']
                duvida = n['Percentual'] > LIMITE_ALERTA or (n.get('ItensCustoZero') and n.get('ImportadaAntes'))
                tags = (('alerta',) if duvida else ()) + (('marcada',) if marcada else ())
                tree.insert("", "end", iid=f"n{n['NotaID']}", tags=tags, values=(
                    "✔" if marcada else "", n['Data'].strftime('%d/%m/%Y') if n['Data'] else '?', n['NumeroNF'],
                    n['Fornecedor'], n['Itens'], fmt_reais(n['ValorNF']), fmt_reais(n['SomaItens']),
                    fmt_reais(n['Diferenca']), f"{n['Percentual']:.1f}%".replace('.', ',')))
            if sel and tree.exists(sel):
                tree.focus(sel); tree.selection_set(sel)
            marcadas = [n for n in estado['notas'] if n['NotaID'] in estado['marcadas']]
            total = sum((n['Diferenca'] for n in marcadas), Decimal('0'))
            lbl_resumo.config(text=f"{len(estado['notas'])} nota(s) com diferença · ✔ {len(marcadas)} marcada(s) = {fmt_reais(total)}")

        def nota_da_linha(iid):
            return next((n for n in estado['notas'] if f"n{n['NotaID']}" == iid), None)

        def mostrar_itens(event=None):
            for i in tree_itens.get_children():
                tree_itens.delete(i)
            n = nota_da_linha(tree.focus() or '')
            if not n:
                return
            for it in database.previa_rateio_nota(n['NotaID']) or []:
                acrescimo = (it['CustoNovo'] - it['CustoAtual']) * it['Quantidade']
                tree_itens.insert("", "end", values=(it['Produto'], it['Descricao'], fmt_qtd(it['Quantidade']),
                                                     fmt_reais(it['CustoAtual']), fmt_reais(it['CustoNovo']),
                                                     f"+{fmt_reais(acrescimo)}"))
            lbl_itens.config(text=f"Itens da NF {n['NumeroNF']} — {n['Fornecedor']} (prévia — nada é gravado até clicar em Aplicar):")

        def alternar(event=None):
            n = nota_da_linha(tree.focus() or '')
            if not n:
                return "break"
            estado['marcadas'].symmetric_difference_update({n['NotaID']})
            mostrar()
            return "break"

        def marcar_visiveis(marcar=True):
            if not marcar:
                # [DEPURAÇÃO 2] desmarca TODAS (antes só as do filtro atual; as escondidas
                # continuavam marcadas e eram ajustadas no Aplicar sem você ver)
                estado['marcadas'].clear()
                mostrar()
                return
            for n in visiveis():
                if n['Percentual'] > LIMITE_ALERTA:
                    continue   # as de diferença grande ficam para conferir uma a uma
                if n.get('ItensCustoZero') and n.get('ImportadaAntes'):
                    continue   # [DEPURAÇÃO 2] tem bonificação e é antiga: o valor dela pode estar no total
                estado['marcadas'].add(n['NotaID'])
            mostrar()

        def aplicar():
            marcadas = [n for n in estado['notas'] if n['NotaID'] in estado['marcadas']]
            if not marcadas:
                messagebox.showwarning("Aviso", "Marque (✔) pelo menos uma nota. Dica: duplo clique na nota ou tecla Espaço.", parent=popup)
                return
            total = sum((n['Diferenca'] for n in marcadas), Decimal('0'))
            grandes = sum(1 for n in marcadas if n['Percentual'] > LIMITE_ALERTA)
            aviso = f"\n\n⚠️ {grandes} delas têm diferença GRANDE (acima de {LIMITE_ALERTA}%). Confira se é mesmo imposto." if grandes else ""
            if not messagebox.askyesno("Aplicar ajuste",
                                       f"Incluir {fmt_reais(total)} no custo dos itens de {len(marcadas)} nota(s)?\n\n"
                                       "Só o CUSTO muda (as quantidades ficam iguais). Contagens com o valor do estoque "
                                       f"já FECHADO não mudam.{aviso}", icon='warning' if grandes else 'question', parent=popup):
                return
            ok, msg = database.ratear_diferenca_nas_notas([n['NotaID'] for n in marcadas])
            if ok:
                self.status(f"Ajuste pelo valor da nota: {msg}")
                self.atualizar_lista_produtos()   # [DEPURAÇÃO 2] coluna "Custo atual" do catálogo
                messagebox.showinfo("Pronto", f"{msg}\n\nAbra o '💰 Valor do Estoque' e clique em '🔄 Recalcular' nas contagens "
                                    "em aberto para ver o efeito.", parent=popup)
                estado['marcadas'].clear()
                carregar()
                for i in tree_itens.get_children():
                    tree_itens.delete(i)
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        combo_forn.bind("<<ComboboxSelected>>", lambda e: mostrar())
        entry_busca.bind("<KeyRelease>", lambda e: mostrar())
        tree.bind("<<TreeviewSelect>>", mostrar_itens)
        tree.bind("<Double-1>", alternar)
        tree.bind("<space>", alternar)

        botoes = ttk.Frame(popup, padding=(10, 0, 10, 10))
        botoes.pack(fill=tk.X)
        ttk.Label(botoes, foreground="gray", text="Duplo clique ou Espaço = marcar/desmarcar a nota.").pack(side=tk.LEFT)
        ttk.Button(botoes, text="✅ Aplicar nas notas marcadas", command=aplicar).pack(side=tk.RIGHT, ipady=3)
        ttk.Button(botoes, text="Desmarcar todas", command=lambda: marcar_visiveis(False)).pack(side=tk.RIGHT, padx=5, ipady=3)
        ttk.Button(botoes, text=f"Marcar todas da lista (menos as acima de {LIMITE_ALERTA}%)",
                   command=lambda: marcar_visiveis(True)).pack(side=tk.RIGHT, padx=5, ipady=3)
        carregar()
        if not estado['notas']:
            messagebox.showinfo("Nada para ajustar", "Nenhuma nota tem o valor total maior que a soma dos itens. 👍", parent=popup)
        self._janela_ajuste_nota = {'popup': popup, 'tree': tree, 'itens': tree_itens, 'fornecedor': combo_forn,
                                    'mostrar': mostrar, 'alternar': alternar, 'marcar': marcar_visiveis,
                                    'aplicar': aplicar, 'resumo': lbl_resumo, 'mostrar_itens': mostrar_itens,
                                    'estado': estado}

    def atualizar_resumo_importacao(self):
        """[MELHORIA UX] Atualiza o placar e libera o botão 'Salvar' só quando há o que salvar."""
        pendentes = len(self.itens_xml_nao_vinculados)
        prontos = len(self.tree_prontos.get_children())
        completas = sum(1 for n in self.dados_notas_processadas
                        if n.get('itens_pendentes', 0) == 0 and n.get('itens_vinculados'))
        if not self.ultima_pasta_xml:
            texto = "Nenhuma pasta carregada ainda."
        elif pendentes:
            texto = (f"📋 {pendentes} item(ns) para vincular   ·   ✅ {prontos} pronto(s)   ·   "
                     f"🧾 {completas} nota(s) completa(s)")
        elif completas:
            texto = f"🎉 Tudo vinculado! {completas} nota(s) prontas — clique no botão 4 para salvar."
        else:
            texto = "Nada pendente nesta pasta."
        try:
            self.lbl_resumo_importacao.config(text=texto)
            self.btn_salvar_notas.state(['!disabled'] if any(n.get('itens_vinculados') for n in self.dados_notas_processadas)
                                        else ['disabled'])
        except (tk.TclError, AttributeError):
            pass

    def _apos_vincular(self, indice_removido):
        """
        [MELHORIA UX] Depois de vincular um item:
          - seleciona sozinho o PRÓXIMO pendente (não precisa clicar nele);
          - quando não sobra nenhum, relê a pasta sozinho (antes era preciso lembrar
            de clicar em 'Reprocessar' para os itens irem para a lista de salvar).
        """
        restantes = self.tree_vincular.get_children()
        if restantes:
            proximo = restantes[min(indice_removido, len(restantes) - 1)]
            self.tree_vincular.focus(proximo)
            self.tree_vincular.selection_set(proximo)
            try:
                self.tree_vincular.see(proximo)
            except tk.TclError:
                pass
            self.atualizar_resumo_importacao()
        elif self.ultima_pasta_xml and os.path.isdir(self.ultima_pasta_xml):
            self.status("Último item vinculado! Relendo a pasta para liberar as notas...", 'info')
            self._carregar_pasta_xml(self.ultima_pasta_xml)
        else:
            self.atualizar_resumo_importacao()

    def _carregar_pasta_xml(self, pasta_selecionada, silencioso=False):
        self.ultima_pasta_xml = pasta_selecionada
        for i in self.tree_vincular.get_children(): self.tree_vincular.delete(i)
        for i in self.tree_prontos.get_children(): self.tree_prontos.delete(i)
        self.itens_xml_nao_vinculados.clear()
        self.dados_notas_processadas.clear()
        try:
            self.processar_arquivos_xml(pasta_selecionada, silencioso=silencioso)
        except Exception as e:
            logger.error(f"Erro GERAL ao processar pasta XML: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico no Processamento", f"Ocorreu um erro ao ler os arquivos:\n{e}", parent=self.root)
        self.atualizar_resumo_importacao()
        # [MELHORIA UX] já deixa o primeiro pendente selecionado
        pendentes = self.tree_vincular.get_children()
        if pendentes:
            self.tree_vincular.focus(pendentes[0])
            self.tree_vincular.selection_set(pendentes[0])

    def ler_xml_nota_fiscal(self, caminho_arquivo_xml):
        def dec(texto):
            """Número do XML -> Decimal (tag vazia vale 0)."""
            texto = (texto or '').strip()
            return Decimal(texto) if texto else Decimal('0')

        try:
            if USANDO_LXML:
                # resolve_entities=False: não deixa um XML malicioso ler arquivos do computador
                parser = ET.XMLParser(remove_blank_text=True, resolve_entities=False)
                tree = ET.parse(caminho_arquivo_xml, parser)
            else:
                tree = ET.parse(caminho_arquivo_xml)
            root = tree.getroot()

            # Remove namespaces para facilitar a busca das tags
            # [DEPURAÇÃO] getiterator() está obsoleto (foi removido do Python); iter() é o correto
            for elem in root.iter():
                if not isinstance(elem.tag, str): continue  # comentários do XML
                i = elem.tag.find('}')
                if i >= 0:
                    elem.tag = elem.tag[i+1:]

            # Busca direta sem namespace (mais robusto)
            ide = root.find('.//ide')
            emit = root.find('.//emit')
            total = root.find('.//total/ICMSTot')

            if ide is None or emit is None or total is None:
                raise Exception("Estrutura do XML inválida (tags essenciais não encontradas após limpeza).")

            inf_nfe = root.find('.//infNFe')
            chave = (inf_nfe.get('Id') or '').replace('NFe', '') if inf_nfe is not None else ''

            dados_nf = {
                'NumeroNF': (ide.findtext('nNF', default='') or '').strip(),
                'Serie': (ide.findtext('serie', default='') or '').strip(),
                'ChaveAcesso': chave,
                # Alguns XMLs usam dhEmi, outros dEmi. Tenta ambos.
                'DataEmissao': (ide.findtext('dhEmi') or ide.findtext('dEmi') or datetime.now().strftime('%Y-%m-%dT')).split('T')[0],
                'ValorTotalNF': dec(total.findtext('vNF', default='0.0')),
                # [DEPURAÇÃO] Produtor rural emite NF-e com CPF (não CNPJ). Antes o arquivo era recusado.
                'FornecedorCNPJ': so_digitos(emit.findtext('CNPJ', default='') or emit.findtext('CPF', default='')),
                'FornecedorNome': (emit.findtext('xNome', default='') or '').strip(),
                # [MELHORIA VALOR] finNFe=4 é nota de DEVOLUÇÃO (não é compra)
                'Finalidade': (ide.findtext('finNFe', default='1') or '1').strip(),
            }

            itens = []
            somas_itens = {k: Decimal('0') for k in ('vST', 'vFCPST', 'vFrete', 'vSeg', 'vOutro', 'vIPI', 'vDesc')}
            detalhes = root.findall('.//det')
            for det in detalhes:
                prod = det.find('prod')
                if prod is None: continue

                # 1. Quantidade comprada
                qtd_xml = dec(prod.findtext('qCom', default='0.0'))

                # 2. Valores brutos e rateios do produto
                vProd = dec(prod.findtext('vProd', default='0.0')) # Valor total bruto dos itens
                vFrete = dec(prod.findtext('vFrete', default='0.0'))
                vSeg = dec(prod.findtext('vSeg', default='0.0'))
                vOutro = dec(prod.findtext('vOutro', default='0.0'))
                vDesc = dec(prod.findtext('vDesc', default='0.0'))

                # 3. Impostos agregados (Substituição Tributária e IPI)
                # O './/' faz o robô varrer profundamente qualquer tag de imposto procurando a ST
                vICMSST = dec(det.findtext('.//vICMSST', default='0.0'))
                vIPI = dec(det.findtext('.//vIPI', default='0.0'))
                # [MELHORIA VALOR] FCP-ST (Fundo de Combate à Pobreza cobrado junto com a ST)
                # também é pago na compra e faz parte do custo.
                vFCPST = dec(det.findtext('.//vFCPST', default='0.0'))

                # 4. Cálculo do Custo Real de Aquisição Contábil
                custo_total_item = vProd + vICMSST + vFCPST + vIPI + vFrete + vSeg + vOutro - vDesc
                
                # 5. Custo Unitário Certo (c/ Impostos Rateados)
                custo_unit_real = custo_total_item / qtd_xml if qtd_xml > 0 else Decimal('0.0')

                # [MELHORIA ST] guarda cada parte do item para conferir com o TOTAL da nota
                partes_item = {'vST': vICMSST, 'vFCPST': vFCPST, 'vFrete': vFrete, 'vSeg': vSeg,
                               'vOutro': vOutro, 'vIPI': vIPI, 'vDesc': vDesc}
                for chave_parte, valor_parte in partes_item.items():
                    somas_itens[chave_parte] += valor_parte

                itens.append({
                    '_vProd': vProd, '_custo_total': custo_total_item,
                    'ValorItemNota': custo_total_item,   # [DEPURAÇÃO 2] valor do item na nota (p/ "fora do estoque")
                    'cProd': prod.findtext('cProd', default=''),
                    'cEAN': (prod.findtext('cEAN', default='') or '').strip(),
                    'DescricaoXML': prod.findtext('xProd', default=''),
                    'NCM': prod.findtext('NCM', default=''),
                    'Quantidade': qtd_xml,
                    'PrecoCustoUnitario': custo_unit_real, # Agora leva o custo REAL!
                    'CFOP': (prod.findtext('CFOP', default='') or '').strip(),
                })

            # [MELHORIA ST] Algumas notas trazem a ST (ou o frete, seguro, outras despesas,
            # IPI, desconto) SÓ no TOTAL da nota, sem o valor em cada item. Antes isso ficava
            # FORA do custo dos produtos. Agora a diferença entre o total da nota e a soma dos
            # itens é dividida entre os itens, proporcional ao valor de cada um (vProd).
            # Itens com ST em CST 60 (ST já paga antes) não mudam: o preço já a inclui.
            ajustes = {}
            # [DEPURAÇÃO 2] Rateia só entre os itens que são COMPRA. Antes entravam também os de
            # comodato/remessa (que depois são descartados) e os de bonificação (que viram custo 0):
            # a parte deles sumia e os itens comprados ficavam com ST/frete a menos.
            compraveis = [i for i in itens if tipo_item_por_cfop(i.get('CFOP')) == 'compra'] or itens
            total_vprod = sum((i['_vProd'] for i in compraveis), Decimal('0'))
            if total_vprod > 0:
                for chave_parte in somas_itens:
                    valor_total = dec(total.findtext(chave_parte, default='0'))
                    diferenca = valor_total - somas_itens[chave_parte]
                    # Só ACRESCENTA o que faltou nos itens. Se o total vier menor (ou sem a
                    # tag), confia nos valores dos itens e não tira nada.
                    if diferenca >= Decimal('0.01'):
                        ajustes[chave_parte] = diferenca
                if ajustes:
                    sinal = {'vDesc': Decimal('-1')}
                    for item in compraveis:
                        parte = item['_vProd'] / total_vprod
                        extra = sum((d * sinal.get(k, Decimal('1')) * parte for k, d in ajustes.items()), Decimal('0'))
                        item['_custo_total'] += extra
                        if item['Quantidade'] > 0:
                            item['PrecoCustoUnitario'] = item['_custo_total'] / item['Quantidade']
                    logger.info(f"NF {dados_nf['NumeroNF']}: valores só no total rateados nos itens: "
                                + ", ".join(f"{k}={v}" for k, v in ajustes.items()))
            dados_nf['AjustesRateados'] = ajustes
            for item in itens:
                item.pop('_vProd', None); item.pop('_custo_total', None)

            return dados_nf, itens

        except Exception as e:
            logger.error(f"Erro ao ler o arquivo XML '{caminho_arquivo_xml}': {e}", exc_info=True)
            raise Exception(f"Falha estrutural no XML: {e}")

    def processar_arquivos_xml(self, pasta_selecionada, silencioso=False):
        # silencioso=True: relê a pasta sem mostrar o resumo (usado antes de salvar)
        extensoes_permitidas = ('.xml', '.txt')
        arquivos_xml = sorted(os.path.join(pasta_selecionada, f) for f in os.listdir(pasta_selecionada) if f.lower().endswith(extensoes_permitidas))
        notas_processadas_nesta_sessao = {}
        arquivos_com_falha = 0
        arquivos_repetidos = 0
        notas_ignoradas, itens_ignorados, itens_bonificados = [], [], []  # [MELHORIA VALOR]
        notas_com_rateio = []  # [MELHORIA ST] notas com ST/frete só no total (rateados nos itens)
        reconhecidos_por_codigo = []  # [MELHORIA] itens reconhecidos pelo código/EAN (descrição mudou)
        ja_importadas = []  # [DEPURAÇÃO 2] notas que já estão no banco (não aparecem de novo)
        for caminho_xml in arquivos_xml:
            try:
                cabecalho_nf, itens_nf = self.ler_xml_nota_fiscal(caminho_xml)
                cnpj = cabecalho_nf['FornecedorCNPJ']
                nome_fornecedor = cabecalho_nf['FornecedorNome']
                num_nf = cabecalho_nf['NumeroNF']
                if not cnpj or not itens_nf:
                    raise Exception("Arquivo XML não contém CNPJ ou lista de itens.")

                if cabecalho_nf.get('AjustesRateados'):
                    nomes = {'vST': 'ST', 'vFCPST': 'FCP-ST', 'vFrete': 'frete', 'vSeg': 'seguro',
                             'vOutro': 'outras despesas', 'vIPI': 'IPI', 'vDesc': 'desconto'}
                    notas_com_rateio.append(f"NF {num_nf} ({nome_fornecedor}): " + ", ".join(
                        f"{nomes[k]} {fmt_reais(v)}" for k, v in cabecalho_nf['AjustesRateados'].items()))

                # [MELHORIA VALOR] Nota de devolução não é compra: fica de fora
                if cabecalho_nf.get('Finalidade') == '4':
                    notas_ignoradas.append(f"NF {num_nf} ({nome_fornecedor}) - nota de devolução")
                    continue
                # Itens de comodato/remessa/devolução saem; bonificação entra com custo zero
                itens_filtrados = []
                valor_fora = Decimal('0')   # [DEPURAÇÃO 2] valor da nota que NÃO é compra paga
                for it in itens_nf:
                    tipo = tipo_item_por_cfop(it.get('CFOP'))
                    if tipo == 'ignorar':
                        itens_ignorados.append(f"NF {num_nf}: {it['DescricaoXML']} (CFOP {it.get('CFOP')})")
                        valor_fora += it.get('ValorItemNota', Decimal('0'))
                        continue
                    if tipo == 'bonificacao':
                        valor_fora += it.get('ValorItemNota', Decimal('0'))
                        it = dict(it, PrecoCustoUnitario=Decimal('0'))
                        itens_bonificados.append(f"NF {num_nf}: {it['DescricaoXML']}")
                    itens_filtrados.append(it)
                cabecalho_nf['ValorForaDoEstoque'] = valor_fora
                if not itens_filtrados:
                    notas_ignoradas.append(f"NF {num_nf} ({nome_fornecedor}) - só itens de comodato/remessa")
                    continue
                itens_nf = itens_filtrados

                # [DEPURAÇÃO] Antes as notas eram separadas SÓ pelo número. Duas notas nº 123 de
                # fornecedores diferentes viravam UMA nota só (e os itens do 2º iam para o 1º).
                # E o mesmo XML duas vezes na pasta (ex: nota.xml e nota.txt) DOBRAVA as quantidades.
                chave_nota = cabecalho_nf.get('ChaveAcesso') or f"{cnpj}-{cabecalho_nf.get('Serie', '')}-{num_nf}"
                if chave_nota in notas_processadas_nesta_sessao:
                    arquivos_repetidos += 1
                    logger.warning(f"Arquivo {caminho_xml} ignorado: a NF {num_nf} ({nome_fornecedor}) já foi lida em outro arquivo.")
                    continue

                fornecedor_id = database.buscar_fornecedor_por_cnpj(cnpj)
                if not fornecedor_id:
                    database.criar_fornecedor(cnpj, nome_fornecedor)
                    fornecedor_id = database.buscar_fornecedor_por_cnpj(cnpj)
                    self.atualizar_lista_fornecedores()
                if not fornecedor_id:
                    raise Exception(f"Não foi possível cadastrar o fornecedor {nome_fornecedor} ({cnpj}).")
                cabecalho_nf['FornecedorID'] = fornecedor_id
                # [DEPURAÇÃO 2] Nota que JÁ está no banco não volta para a tela (antes os itens
                # dela apareciam de novo para vincular e só no "Salvar" vinha o aviso).
                try:
                    # [AUDITORIA ESTOQUE] série e chave: mesmo número em séries diferentes NÃO é a mesma nota
                    ja_existe = database.verificar_nota_fiscal_existente(num_nf, fornecedor_id, cabecalho_nf.get('Serie'),
                                                                         cabecalho_nf.get('ChaveAcesso'))
                except Exception:
                    ja_existe = False
                if ja_existe:
                    ja_importadas.append(f"NF {num_nf} ({nome_fornecedor})")
                    notas_processadas_nesta_sessao[chave_nota] = None
                    continue
                nota = {
                    'cabecalho': cabecalho_nf,
                    'itens_vinculados': [],
                    'itens_pendentes': 0,   # [DEPURAÇÃO] quantos itens desta nota ainda não têm vínculo
                }
                # [DEPURAÇÃO] As linhas só vão para a tela DEPOIS que o arquivo inteiro foi lido.
                # Antes, um erro no meio do arquivo deixava meia nota na lista "Prontos para Salvar".
                linhas_prontos, linhas_pendentes, novos_pendentes = [], [], []
                for item in itens_nf:
                    desc_xml = item['DescricaoXML']
                    # [MELHORIA] Reconhece também pelo código do fornecedor ou EAN quando a
                    # descrição muda (lote/validade no nome). Antes cada variação virava um
                    # vínculo novo (duplicado) e o item caía de novo nos pendentes.
                    if hasattr(database, 'buscar_vinculo_inteligente'):
                        achado = database.buscar_vinculo_inteligente(fornecedor_id, desc_xml, item.get('cProd'), item.get('cEAN'))
                        vinculo_existente = (achado['ProdutoFornecedorID'], achado['ProdutoID'], achado['Fator']) if achado else None
                        if achado and achado['Como'] != 'descricao':
                            reconhecidos_por_codigo.append(f"NF {num_nf}: {desc_xml}")
                    else:
                        vinculo_existente = database.buscar_vinculo_produto_fornecedor(fornecedor_id, desc_xml)

                    if vinculo_existente:
                        # Desempacota os 3 valores. Se fator vier None do banco, trata aqui.
                        produto_fornecedor_id, produto_mestre_id, fator_db = vinculo_existente

                        # Tratamento defensivo: se for None ou <= 0, assume 1.0
                        if fator_db is None or fator_db <= 0:
                            fator = Decimal('1.0')
                        else:
                            fator = Decimal(str(fator_db))

                        # --- A MÁGICA DA CONVERSÃO ---
                        qtd_xml = item['Quantidade'] # Ex: 1 (caixa)
                        custo_xml = item['PrecoCustoUnitario'] # Ex: 60.00 (caixa)

                        qtd_real = qtd_xml * fator # Ex: 1 * 6 = 6 Unidades
                        custo_real = custo_xml / fator # Ex: 60 / 6 = 10.00 Unidade

                        item_pronto = item.copy()
                        item_pronto['ProdutoFornecedorID'] = produto_fornecedor_id
                        item_pronto['FatorUsado'] = fator   # [DEPURAÇÃO 2] guardado em cada item da nota
                        item_pronto['NomeMestre'] = next((k for k, v in self.mapa_produtos_mestre.items() if v == produto_mestre_id), "Desconhecido")
                        # Atualiza para os valores convertidos antes de salvar
                        item_pronto['Quantidade'] = qtd_real 
                        item_pronto['PrecoCustoUnitario'] = custo_real
                        nota['itens_vinculados'].append(item_pronto)

                        # Custo total não muda (R$ 60 continua R$ 60)
                        custo_total_nota = qtd_real * custo_real 

                        # Exibe na tela informando a conversão se houver
                        txt_qtd = f"{qtd_real:.2f}"
                        if fator != 1:
                            # [DEPURAÇÃO] int(fator) mostrava "x2" para um fator 2,5
                            txt_qtd += f" (Conv. x{fator.normalize():f})"

                        linhas_prontos.append((
                            num_nf, nome_fornecedor, item_pronto['NomeMestre'],
                            txt_qtd, f"{custo_real:.4f}", f"{custo_total_nota:.2f}"
                        ))

                    else:
                        nota['itens_pendentes'] += 1
                        self._seq_pendente = getattr(self, '_seq_pendente', 0) + 1
                        item_pendente = {
                            '_uid': self._seq_pendente,   # [DEPURAÇÃO 2] identifica a LINHA da tabela
                            'FornecedorID': fornecedor_id,
                            'FornecedorNome': nome_fornecedor,
                            'DescricaoXML': desc_xml,
                            'cProd': item['cProd'],
                            'cEAN': item['cEAN'],
                            'NCM': item['NCM'],
                            'CustoXML': item['PrecoCustoUnitario'],   # [MELHORIA VALOR] p/ conferir o fator
                        }

                        ja_listado = any(p['DescricaoXML'] == desc_xml and p['FornecedorID'] == fornecedor_id
                                         for p in self.itens_xml_nao_vinculados + novos_pendentes)
                        if not ja_listado:
                            novos_pendentes.append(item_pendente)

                            # Usa Decimal c/ string para garantir precisão financeira e de estoque
                            qtd_xml = Decimal(str(item['Quantidade']))
                            custo_unit = Decimal(str(item['PrecoCustoUnitario']))
                            custo_total = qtd_xml * custo_unit

                            linhas_pendentes.append((item_pendente['_uid'], (
                                nome_fornecedor, 
                                desc_xml, 
                                item['cEAN'], 
                                f"{qtd_xml:.2f}".rstrip('0').rstrip('.'), # Qtd formatada
                                f"R$ {custo_unit:.2f}", 
                                f"R$ {custo_total:.2f}"
                            )))

                # Arquivo lido por completo: agora sim registra a nota e mostra na tela
                notas_processadas_nesta_sessao[chave_nota] = nota
                self.itens_xml_nao_vinculados.extend(novos_pendentes)
                for valores in linhas_prontos:
                    self.tree_prontos.insert("", "end", values=valores)
                for uid, valores in linhas_pendentes:
                    self.tree_vincular.insert("", "end", iid=f"pend_{uid}", values=valores)

            except Exception as e:
                arquivos_com_falha += 1
                logger.error(f"Falha ao processar o arquivo {caminho_xml}: {e}", exc_info=True)

        self.dados_notas_processadas = [n for n in notas_processadas_nesta_sessao.values() if n is not None]
        self._notas_ja_importadas = ja_importadas
        if silencioso:
            return
        completas = sum(1 for n in self.dados_notas_processadas if n['itens_pendentes'] == 0)

        msg_final = (f"Leitura de XMLs concluída.\n\n"
                     f"- {len(self.itens_xml_nao_vinculados)} itens precisam de vinculação (Passo 2).\n"
                     f"- {len(self.dados_notas_processadas)} NFs lidas, das quais {completas} estão completas "
                     f"e prontas para salvar (Passo 3).")
        if arquivos_repetidos:
            msg_final += f"\n\nℹ️ {arquivos_repetidos} arquivo(s) eram cópias de notas já lidas e foram ignorados."
        if ja_importadas:
            msg_final += (f"\n\n✅ {len(ja_importadas)} nota(s) JÁ estavam salvas no estoque e foram puladas:\n  • "
                          + "\n  • ".join(ja_importadas[:5]) + ("\n  • ..." if len(ja_importadas) > 5 else ""))
        # [MELHORIA VALOR] Resumo do que NÃO é compra
        if notas_ignoradas:
            msg_final += f"\n\nℹ️ {len(notas_ignoradas)} nota(s) ignorada(s) (não são compra):\n  • " + "\n  • ".join(notas_ignoradas[:5])
        if itens_ignorados:
            msg_final += f"\n\nℹ️ {len(itens_ignorados)} item(ns) de comodato/remessa/devolução ignorado(s):\n  • " + "\n  • ".join(itens_ignorados[:5])
        if itens_bonificados:
            msg_final += f"\n\n🎁 {len(itens_bonificados)} item(ns) de BONIFICAÇÃO entram no estoque com custo zero:\n  • " + "\n  • ".join(itens_bonificados[:5])
        if notas_com_rateio:
            msg_final += (f"\n\n🧾 {len(notas_com_rateio)} nota(s) traziam ST/frete/etc. só no TOTAL — o valor foi "
                          "dividido entre os itens e entrou no custo:\n  • " + "\n  • ".join(notas_com_rateio[:5]))
        if reconhecidos_por_codigo:
            msg_final += (f"\n\n🔎 {len(reconhecidos_por_codigo)} item(ns) com a descrição diferente da última nota foram "
                          "reconhecidos pelo código do fornecedor / EAN (não precisaram de novo vínculo).")
        for lista in (notas_ignoradas, itens_ignorados, itens_bonificados, reconhecidos_por_codigo):
            for linha in lista:
                logger.info(f"[importação XML] {linha}")

        if arquivos_com_falha > 0:
            msg_final += f"\n\n⚠️ AVISO: {arquivos_com_falha} arquivo(s) na pasta não eram Notas Fiscais válidas ou estavam corrompidos e foram ignorados."
            messagebox.showwarning("Processamento Concluído com Avisos", msg_final, parent=self.root)
        else:
            messagebox.showinfo("Processamento Concluído", msg_final, parent=self.root)

    def vincular_produto_selecionado(self):
        # ... (código idêntico ao anterior) ...
        selecionado_tree = self.tree_vincular.focus()
        produto_mestre_selecionado = self.combo_produtos_mestre.get()
        if not selecionado_tree:
            messagebox.showwarning("Aviso", "Selecione um item pendente na lista 'Itens Pendentes' (Passo 2).", parent=self.root)
            return
        if not produto_mestre_selecionado:
            messagebox.showwarning("Aviso", "Selecione um 'Produto Mestre' no menu dropdown para vincular.", parent=self.root)
            return
        # [CORREÇÃO] Busca segura pelo conteúdo visual para evitar erro de índice
        valores_visuais = self.tree_vincular.item(selecionado_tree, 'values')
        # valores = ('Fornecedor', 'Produto no XML', ...)

        # Busca na lista interna o item que corresponde ao fornecedor e descrição visual
        item_pendente = self._pendente_da_linha(selecionado_tree, valores_visuais)

        if not item_pendente:
            messagebox.showerror("Erro de Sincronia", "O item selecionado não foi encontrado na memória. Tente recarregar a pasta.", parent=self.root)
            return

        produto_mestre_id = self.mapa_produtos_mestre.get(produto_mestre_selecionado)
        if not produto_mestre_id:
            messagebox.showwarning("Aviso", "Produto Mestre não encontrado. Escolha novamente na lista.", parent=self.root)
            return

        # Pega o fator digitado
        try:
            fator = para_decimal(self.entry_fator_conversao.get(), "Itens p/ Cx", permitir_zero=False)
        except ValueError:
            messagebox.showerror("Erro", "O Fator de Conversão deve ser um número válido maior que 0.", parent=self.root)
            return

        if not self.conferir_fator_com_custo_anterior(item_pendente, produto_mestre_id, produto_mestre_selecionado, fator):
            return

        try:
            # Verifica se o usuário digitou um EAN manualmente na tela
            ean_digitado = self.entry_ean_importacao.get().strip()
            ean_final = ean_digitado if ean_digitado else item_pendente['cEAN']

            # [DEPURAÇÃO] o resultado era ignorado: se o banco falhasse, a tela dizia "Vínculo criado!"
            novo_vinculo = database.criar_vinculo_produto_fornecedor(
                produto_id_mestre=produto_mestre_id,
                fornecedor_id=item_pendente['FornecedorID'],
                descricao_xml=item_pendente['DescricaoXML'],
                cProd=item_pendente['cProd'],
                cEAN=ean_final,
                NCM=item_pendente['NCM'],
                fator_conversao=fator # <-- Passa o fator
            )
            if not novo_vinculo:
                messagebox.showerror("Erro de Banco", "Não foi possível criar o vínculo (veja o log).", parent=self.root)
                return

            # Remove o objeto específico da lista e da árvore
            indice = list(self.tree_vincular.get_children()).index(selecionado_tree)
            self.itens_xml_nao_vinculados.remove(item_pendente)
            self.tree_vincular.delete(selecionado_tree)
            self.entry_ean_importacao.delete(0, tk.END) # Limpa o campo para o próximo
            self.entry_fator_conversao.delete(0, tk.END); self.entry_fator_conversao.insert(0, "1")
            # [MELHORIA UX] rodapé em vez de janelinha + próximo item já selecionado
            self.status(f"Vínculo criado: '{item_pendente['DescricaoXML']}' → {produto_mestre_selecionado}")
            self._apos_vincular(indice)
        except Exception as e:
            logger.error(f"Erro ao criar vínculo: {e}", exc_info=True)
            messagebox.showerror("Erro de Banco", f"Não foi possível criar o vínculo.\n{e}", parent=self.root)

    def conferir_fator_com_custo_anterior(self, item_pendente, produto_mestre_id, nome_mestre, fator):
        """
        [MELHORIA VALOR] Fator de caixa errado é o erro que MAIS distorce o valor do estoque
        (ex: CX com 12 vinculada com fator 1 -> custo 12x maior). Compara o custo por
        unidade que vai resultar com o último custo do produto e avisa se ficar muito diferente.
        Devolve True para continuar.
        """
        custo_xml = item_pendente.get('CustoXML')
        if not custo_xml:
            return True
        try:
            # [DEPURAÇÃO 2] último custo PAGO (antes uma bonificação de custo 0 pulava a conferência)
            buscar = getattr(database, 'ultimo_custo_real_produto', database.buscar_ultimo_custo_por_produto)
            custo_anterior = Decimal(str(buscar(produto_mestre_id) or 0))
        except Exception:
            return True
        if custo_anterior <= 0:
            return True
        custo_novo = Decimal(str(custo_xml)) / fator
        razao = custo_novo / custo_anterior
        if Decimal('0.34') < razao < Decimal('3'):
            return True
        fator_sugerido = (Decimal(str(custo_xml)) / custo_anterior).quantize(Decimal('1'))
        dica = f"\n\nDica: para o custo ficar parecido com o anterior, o fator seria perto de {fator_sugerido}." if fator_sugerido > 0 else ""
        return messagebox.askyesno(
            "Confira o fator (Itens p/ Cx)",
            f"'{item_pendente['DescricaoXML']}' → {nome_mestre}\n\n"
            f"Com fator {fmt_qtd(fator)}, o custo vai ficar {fmt_reais(custo_novo)} por unidade.\n"
            f"A última compra deste produto custou {fmt_reais(custo_anterior)} por unidade "
            f"({fmt_qtd(razao.quantize(Decimal('0.1')))}x de diferença).{dica}\n\n"
            "Um fator errado distorce o VALOR DO ESTOQUE.\n\nContinuar com este fator mesmo assim?",
            icon='warning', parent=self.root)

    def salvar_notas_processadas(self):
        if not self.dados_notas_processadas:
            messagebox.showwarning("Aviso", "Nenhuma nota fiscal foi processada ou não há itens vinculados para salvar.", parent=self.root)
            return
        # [DEPURAÇÃO 2] Itens vinculados depois da leitura não atualizavam a nota: ela continuava
        # "incompleta" e, salvando assim, os itens já vinculados ficavam de fora para sempre.
        # Agora a pasta é relida (sem mensagens) antes de decidir o que está completo.
        if any(nf.get('itens_pendentes', 0) for nf in self.dados_notas_processadas) \
                and self.ultima_pasta_xml and os.path.isdir(self.ultima_pasta_xml):
            self._carregar_pasta_xml(self.ultima_pasta_xml, silencioso=True)
            if not self.dados_notas_processadas:
                messagebox.showinfo("Nada para salvar", "Todas as notas da pasta já estão salvas no estoque.", parent=self.root)
                return

        # [DEPURAÇÃO] Uma nota salva NÃO pode ser importada de novo (o banco bloqueia duplicidade).
        # Antes, notas com itens ainda sem vínculo eram salvas pela metade e os itens que
        # faltavam NUNCA mais conseguiam entrar no estoque. Agora essas notas ficam
        # esperando, a não ser que você confirme que quer salvar mesmo incompletas.
        completas = [nf for nf in self.dados_notas_processadas if nf.get('itens_pendentes', 0) == 0 and nf['itens_vinculados']]
        incompletas = [nf for nf in self.dados_notas_processadas if nf.get('itens_pendentes', 0) > 0 and nf['itens_vinculados']]

        para_salvar = list(completas)
        if incompletas:
            lista = "\n".join(f"  • NF {nf['cabecalho']['NumeroNF']} - {nf['cabecalho']['FornecedorNome']} "
                              f"({nf['itens_pendentes']} item(ns) sem vínculo)" for nf in incompletas[:10])
            resposta = messagebox.askyesno(
                "Notas Incompletas",
                f"{len(incompletas)} nota(s) ainda têm itens sem vínculo:\n{lista}\n\n"
                "Se salvar agora, esses itens NUNCA mais poderão entrar pelo XML "
                "(a nota ficará marcada como importada).\n\n"
                "SIM = salvar também as incompletas (só os itens já vinculados)\n"
                "NÃO = salvar só as completas; as incompletas ficam aguardando",
                icon='warning', parent=self.root)
            if resposta:
                para_salvar += incompletas

        if not para_salvar:
            messagebox.showwarning("Aviso", "Nenhuma nota completa para salvar. Vincule os itens do Passo 2 "
                                            "e clique em '🔄 Reprocessar Pasta Atual'.", parent=self.root)
            return

        sucessos = 0
        falhas = 0
        duplicadas = []
        notas_salvas = []        # [ALERTA PREÇO] IDs das notas que acabaram de entrar
        notas_remanescentes = [nf for nf in self.dados_notas_processadas if nf not in para_salvar]

        for nf in para_salvar:
            cabecalho = nf['cabecalho']
            itens_para_salvar = nf['itens_vinculados']
            try:
                sucesso_db, msg_db = database.salvar_nota_fiscal_completa(cabecalho, itens_para_salvar)
                if sucesso_db:
                    sucessos += 1
                    if cabecalho.get('NotaID'):
                        notas_salvas.append(cabecalho['NotaID'])
                elif "já foi importada" in (msg_db or ""):
                    # Já está no banco: não adianta manter na tela
                    duplicadas.append(str(cabecalho['NumeroNF']))
                else:
                    falhas += 1
                    notas_remanescentes.append(nf)
                    logger.error(f"Falha ao salvar NF {cabecalho['NumeroNF']} no banco: {msg_db}")
            except Exception as e:
                falhas += 1
                notas_remanescentes.append(nf)
                logger.error(f"Erro crítico ao tentar salvar NF {cabecalho['NumeroNF']}: {e}", exc_info=True)

        # Atualiza a memória principal com apenas o que sobrou
        self.dados_notas_processadas = notas_remanescentes

        texto = (f"Processo de salvamento finalizado.\n\n"
                 f"Notas salvas com sucesso: {sucessos}\n"
                 f"Notas com erro: {falhas}\n"
                 f"Notas aguardando vínculo: {len([n for n in notas_remanescentes if n.get('itens_pendentes', 0) > 0 or not n['itens_vinculados']])}")
        if duplicadas:
            texto += f"\n\nJá existiam no sistema (ignoradas): NF {', '.join(duplicadas)}"
        if falhas or duplicadas:
            messagebox.showwarning("Processamento Concluído", texto, parent=self.root)
        else:
            messagebox.showinfo("Processamento Concluído", texto, parent=self.root)
        self.avisar_aumentos_de_preco(notas_salvas)

        # Atualiza a interface visual
        for i in self.tree_prontos.get_children(): 
            self.tree_prontos.delete(i)
            
        # Recarrega na visualização APENAS o que sobrou na memória
        for nf in self.dados_notas_processadas:
            cabecalho = nf['cabecalho']
            for item in nf['itens_vinculados']:
                nome_exibicao = item.get('NomeMestre') or item.get('DescricaoXML', 'Item')
                qtd_rec = item['Quantidade']
                custo_rec = item['PrecoCustoUnitario']
                custo_tot_rec = qtd_rec * custo_rec

                self.tree_prontos.insert("", "end", values=(
                    cabecalho['NumeroNF'], cabecalho['FornecedorNome'], nome_exibicao, 
                    f"{qtd_rec:.2f}", f"{custo_rec:.4f}", f"{custo_tot_rec:.2f}"
                ))

        self.atualizar_resumo_importacao()
        if not self.dados_notas_processadas and not self.itens_xml_nao_vinculados:
            self.status("Todas as notas e itens foram processados com sucesso! Tela limpa.")  # [MELHORIA UX] rodapé em vez de janelinha

    def avisar_aumentos_de_preco(self, nota_ids):
        """[ALERTA PREÇO] Depois de salvar as notas: avisa o que ficou mais caro que na compra anterior."""
        if not nota_ids or not hasattr(database, 'aumentos_de_preco'):
            return
        try:
            aumentos = database.aumentos_de_preco(nota_ids=nota_ids)
        except Exception as e:
            logger.error(f"Não foi possível conferir os aumentos de preço: {e}", exc_info=True)
            return
        if not aumentos:
            return
        linhas = [f"  • {database.texto_aumento_preco(a)}" for a in aumentos[:15]]
        if len(aumentos) > 15:
            linhas.append(f"  … e mais {len(aumentos) - 15} produto(s).")
        messagebox.showwarning(
            "Preços que subiram",
            f"{len(aumentos)} produto(s) ficaram {database.LIMITE_AUMENTO_PRECO_PCT:.0f}% ou mais caros "
            "do que na compra anterior:\n\n" + "\n".join(linhas) +
            "\n\nSe algum aumento parecer exagerado, confira o fator (Qtd/Cx) do vínculo.", parent=self.root)

    def criar_mestre_e_vincular(self):
        # ... (código idêntico ao anterior) ...
        selecionado_tree = self.tree_vincular.focus()
        if not selecionado_tree:
            messagebox.showwarning("Aviso", "Selecione um item pendente na lista 'Itens Pendentes' (Passo 2).", parent=self.root)
            return

        # [CORREÇÃO] Busca segura pelo conteúdo visual
        valores_visuais = self.tree_vincular.item(selecionado_tree, 'values')
        item_pendente = self._pendente_da_linha(selecionado_tree, valores_visuais)

        if not item_pendente:
            messagebox.showerror("Erro de Sincronia", "O item selecionado não foi encontrado na memória.", parent=self.root)
            return

        nome_novo_produto = item_pendente['DescricaoXML']

        # [DEPURAÇÃO] O fator é conferido ANTES de criar qualquer coisa. Antes, um fator
        # digitado errado virava "1" em silêncio (e a quantidade entrava errada no estoque).
        try:
            fator = para_decimal(self.entry_fator_conversao.get(), "Itens p/ Cx", permitir_zero=False)
        except ValueError:
            messagebox.showerror("Erro", "O Fator de Conversão (Itens p/ Cx) deve ser um número maior que 0.", parent=self.root)
            return

        try:
            produto_id_mestre = database.buscar_produto_mestre_por_nome(nome_novo_produto)
            produto_foi_criado = False
            if not produto_id_mestre:
                cat_selecionada = self.combo_cat_importacao.get()
                if not messagebox.askyesno("Confirmar Auto-Criação",
                                        f"O produto mestre '{nome_novo_produto}' não existe no Catálogo.\n\n"
                                        f"Deseja criá-lo agora?\n"
                                        f"(UN, Est. Mín: 0.0, Categoria: {cat_selecionada})",
                                        parent=self.root):
                    return
                produto_id_mestre = database.criar_produto_estoque(
                    nome=nome_novo_produto,
                    unidade="UN", 
                    estoque_min=Decimal('0.0'),
                    categoria=cat_selecionada
                )
                if not produto_id_mestre:
                    raise Exception("Falha ao criar o produto mestre, não retornou ID.")
                produto_foi_criado = True
            elif not self.conferir_fator_com_custo_anterior(item_pendente, produto_id_mestre, nome_novo_produto, fator):
                return  # [MELHORIA VALOR] produto já existia: confere o fator com o custo anterior

            # Verifica se o usuário digitou um EAN manualmente na tela
            ean_digitado = self.entry_ean_importacao.get().strip()
            ean_final = ean_digitado if ean_digitado else item_pendente['cEAN']

            novo_vinculo = database.criar_vinculo_produto_fornecedor(
                produto_id_mestre=produto_id_mestre,
                fornecedor_id=item_pendente['FornecedorID'],
                descricao_xml=item_pendente['DescricaoXML'],
                cProd=item_pendente['cProd'],
                cEAN=ean_final,
                NCM=item_pendente['NCM'],
                fator_conversao=fator
            )
            if produto_foi_criado:
                self.atualizar_lista_produtos()
                self.popular_combobox_produtos_mestre()
            if not novo_vinculo:
                raise Exception("O banco não conseguiu gravar o vínculo (veja o log).")

            # Remove o objeto específico da lista e da árvore
            indice = list(self.tree_vincular.get_children()).index(selecionado_tree)
            self.itens_xml_nao_vinculados.remove(item_pendente)
            self.tree_vincular.delete(selecionado_tree)
            self.entry_ean_importacao.delete(0, tk.END) # Limpa o campo
            self.entry_fator_conversao.delete(0, tk.END); self.entry_fator_conversao.insert(0, "1")
            criado = "criado e vinculado" if produto_foi_criado else "vinculado"
            self.status(f"Produto '{nome_novo_produto}' {criado}.")
            self._apos_vincular(indice)
        except Exception as e:
            logger.error(f"Erro ao auto-criar e vincular: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Não foi possível criar e vincular o produto.\nVerifique se o nome já existe no Catálogo Mestre com alguma variação.\n\nErro: {e}", parent=self.root)

    # ===================================================================
    # == ABA 4: LANÇAR CONTAGEM FÍSICA (Com Filtro) =====================
    # ===================================================================
    def criar_aba_contagem_estoque(self):
        # ... (código idêntico ao anterior) ...
        main_frame = ttk.Frame(self.frame_contagem)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1) 
        frame_lancamento = ttk.LabelFrame(main_frame, text="1. Lançar Itens Contados", padding="10")
        frame_lancamento.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        frame_lancamento.columnconfigure(0, weight=1)
        # [MELHORIA UX] Contagem só pelo teclado:
        #   digite parte do nome -> Enter -> digite a quantidade -> Enter (e repete).
        #   Setas ↑/↓ no campo de busca escolhem entre os produtos encontrados.
        ttk.Label(frame_lancamento, text="Buscar Produto (digite e tecle Enter):").grid(row=0, column=0, sticky="w")
        self.entry_filtro_contagem = ttk.Entry(frame_lancamento)
        self.entry_filtro_contagem.grid(row=1, column=0, sticky="ew", padx=(0, 5))
        self.entry_filtro_contagem.bind("<KeyRelease>", self.filtrar_combo_contagem)
        self.entry_filtro_contagem.bind("<Return>", self.contagem_enter_na_busca)
        self.entry_filtro_contagem.bind("<Down>", lambda e: self.contagem_navegar_resultados(1))
        self.entry_filtro_contagem.bind("<Up>", lambda e: self.contagem_navegar_resultados(-1))
        self.lbl_contagem_encontrados = ttk.Label(frame_lancamento, text="", foreground="gray")
        self.lbl_contagem_encontrados.grid(row=1, column=1, columnspan=3, sticky="w", padx=5)
        ttk.Label(frame_lancamento, text="Produto do Catálogo Mestre:").grid(row=2, column=0, sticky="w", pady=(5,0))
        self.combo_contagem_produtos = ttk.Combobox(frame_lancamento, state="readonly")
        self.combo_contagem_produtos.grid(row=3, column=0, sticky="ew", padx=(0, 5))
        self.combo_contagem_produtos.bind("<<ComboboxSelected>>", self.atualizar_label_unidade_contagem)
        ttk.Label(frame_lancamento, text="Quantidade:").grid(row=2, column=1, sticky="w", pady=(5,0))
        self.entry_contagem_qtd = ttk.Entry(frame_lancamento, width=10)
        self.entry_contagem_qtd.grid(row=3, column=1, sticky="w", padx=5)
        self.entry_contagem_qtd.bind("<Return>", lambda e: self.adicionar_item_contagem())
        self.entry_contagem_qtd.bind("<KP_Enter>", lambda e: self.adicionar_item_contagem())
        self.entry_contagem_qtd.bind("<Escape>", lambda e: self.entry_filtro_contagem.focus_set())
        # [MELHORIA CONTAGEM] "Contado em": unidade do estoque OU caixa do fornecedor.
        # Ex: escolha "CX de 12" e digite 3 -> lança 36 UN.  "3+5" = 3 caixas + 5 soltas.
        self.lbl_contagem_unidade = ttk.Label(frame_lancamento, text="UN", font=("Arial", 10, "italic"))  # (compatibilidade)
        ttk.Label(frame_lancamento, text="Contado em:").grid(row=2, column=2, sticky="w", pady=(5, 0))
        self.combo_contagem_embalagem = ttk.Combobox(frame_lancamento, state="readonly", width=30)
        self.combo_contagem_embalagem.grid(row=3, column=2, sticky="w", padx=5)
        self.combo_contagem_embalagem.bind("<<ComboboxSelected>>", self.ao_escolher_embalagem_contagem)
        btn_adicionar_item = ttk.Button(frame_lancamento, text="Adicionar à Lista", command=self.adicionar_item_contagem)
        btn_adicionar_item.grid(row=3, column=3, sticky="w", padx=10)
        self.lbl_contagem_conversao = ttk.Label(frame_lancamento, text="", foreground="#0056b3")
        self.lbl_contagem_conversao.grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.entry_contagem_qtd.bind("<KeyRelease>", self.atualizar_previa_contagem)
        self._opcoes_embalagem = {}
        self._ultimas_contagens = None
        frame_lista_lancar = ttk.LabelFrame(main_frame, text="2. Itens nesta Contagem (0) — duplo clique corrige a quantidade", padding="10")
        self.frame_lista_lancar = frame_lista_lancar
        frame_lista_lancar.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=10)
        frame_lista_lancar.rowconfigure(0, weight=1)
        frame_lista_lancar.columnconfigure(0, weight=1)
        cols_cont = ('Produto Mestre', 'Qtd Contada', 'UN', 'Como contou')
        self.tree_contagem_atual = criar_tree_zebrada(frame_lista_lancar, columns=cols_cont, show='headings', selectmode='browse')
        self.tree_contagem_atual.bind("<Double-1>", lambda e: self.editar_item_contagem())
        self.tree_contagem_atual.heading('Produto Mestre', text='Produto'); self.tree_contagem_atual.column('Produto Mestre', width=200)
        self.tree_contagem_atual.heading('Qtd Contada', text='Qtd'); self.tree_contagem_atual.column('Qtd Contada', width=60, anchor='e')
        self.tree_contagem_atual.heading('UN', text='UN'); self.tree_contagem_atual.column('UN', width=40, anchor='center')
        self.tree_contagem_atual.heading('Como contou', text='Como contou'); self.tree_contagem_atual.column('Como contou', width=150)
        self.tree_contagem_atual.grid(row=0, column=0, sticky="nsew")
        btn_remover_item = ttk.Button(frame_lista_lancar, text="Remover Item Selecionado da Lista", command=self.remover_item_contagem)
        btn_remover_item.grid(row=1, column=0, sticky="w", pady=(10, 0))
        frame_salvar = ttk.Frame(main_frame)
        frame_salvar.grid(row=2, column=0, sticky="nsew", padx=(0, 5))
        frame_salvar.columnconfigure(1, weight=1)
        ttk.Label(frame_salvar, text="Data da Contagem:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.date_contagem = DateEntry(frame_salvar, width=10, date_pattern='dd/mm/yyyy', locale='pt_BR')
        self.date_contagem.grid(row=0, column=1, sticky="w")
        
        ttk.Label(frame_salvar, text="Nome/Ref:").grid(row=0, column=2, sticky="w", padx=(10, 5))
        self.entry_nome_contagem = ttk.Entry(frame_salvar, width=20)
        self.entry_nome_contagem.grid(row=0, column=3, sticky="w")
        self.entry_nome_contagem.insert(0, "Geral")
        # [DEPURAÇÃO 2] o rascunho guarda também a data e o nome quando eles mudam
        # (antes só ao lançar um item: mudando a data por último, a recuperação voltava a data antiga)
        self.date_contagem.bind("<<DateEntrySelected>>", lambda e: self.lista_itens_para_salvar_contagem and self.salvar_rascunho_contagem())
        self.entry_nome_contagem.bind("<KeyRelease>", lambda e: self.lista_itens_para_salvar_contagem and self.salvar_rascunho_contagem())

        self.id_funcionario_contagem = getattr(config, 'ID_GESTOR_PADRAO', 2) 

        btn_salvar_contagem = ttk.Button(frame_salvar, text="Salvar Contagem Completa", command=self.salvar_contagem_completa)
        btn_salvar_contagem.grid(row=0, column=4, sticky="e", padx=20, ipady=5)

        # Botão para exportar a planilha de conferência manual (A caneta)
        btn_planilha_contagem = ttk.Button(frame_salvar, text="📊 Exportar Folha de Contagem (Excel)", command=self.exportar_folha_contagem_manual)
        btn_planilha_contagem.grid(row=1, column=4, sticky="e", padx=20, pady=(5, 0))
        
        frame_historico = ttk.LabelFrame(main_frame, text="Histórico de Contagens Realizadas", padding="10")
        frame_historico.grid(row=0, column=1, rowspan=3, sticky="nsew", pady=5)
        frame_historico.rowconfigure(0, weight=1)
        frame_historico.rowconfigure(1, weight=1)
        frame_historico.columnconfigure(0, weight=1)
        
        cols_hist = ('ID', 'Data', 'Nome', 'Responsável', 'Valor')
        # Mudança de selectmode='browse' para 'extended'
        self.tree_hist_contagens = criar_tree_zebrada(frame_historico, columns=cols_hist, show='headings', selectmode='extended', height=5)
        # [MELHORIA VALOR] mostra o valor das contagens já FECHADAS (🔒)
        self.tree_hist_contagens.heading('Valor', text='Valor Fechado'); self.tree_hist_contagens.column('Valor', width=110, anchor='e')
        self.tree_hist_contagens.heading('ID', text='ID'); self.tree_hist_contagens.column('ID', width=30, anchor='center')
        self.tree_hist_contagens.heading('Data', text='Data'); self.tree_hist_contagens.column('Data', width=80, anchor='center')
        self.tree_hist_contagens.heading('Nome', text='Nome/Ref'); self.tree_hist_contagens.column('Nome', width=120)
        self.tree_hist_contagens.heading('Responsável', text='Responsável'); self.tree_hist_contagens.column('Responsável', width=120)
        self.tree_hist_contagens.grid(row=0, column=0, sticky="nsew")
        self.tree_hist_contagens.bind("<<TreeviewSelect>>", self.carregar_itens_contagem_historico)
        cols_hist_itens = ('Produto', 'Qtd Contada', 'UN')
        self.tree_hist_itens = criar_tree_zebrada(frame_historico, columns=cols_hist_itens, show='headings')
        self.tree_hist_itens.heading('Produto', text='Produto'); self.tree_hist_itens.column('Produto', width=200)
        self.tree_hist_itens.heading('Qtd Contada', text='Qtd'); self.tree_hist_itens.column('Qtd Contada', width=60, anchor='e')
        self.tree_hist_itens.heading('UN', text='UN'); self.tree_hist_itens.column('UN', width=40, anchor='center')
        self.tree_hist_itens.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        # Novos botões de Ação para a Contagem Finalizada
        frame_botoes_hist = ttk.Frame(frame_historico)
        frame_botoes_hist.grid(row=2, column=0, sticky="ew", pady=5)
        
        btn_resolver_avulsos = ttk.Button(frame_botoes_hist, text="⚠️ Resolver Itens Avulsos", command=self.abrir_gerenciador_avulsos)
        btn_resolver_avulsos.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        btn_editar_contagem = ttk.Button(frame_botoes_hist, text="✏️ Editar Contagem Selecionada", command=self.abrir_edicao_contagem)
        btn_editar_contagem.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        btn_consolidar = ttk.Button(frame_botoes_hist, text="🗜️ Consolidar Selecionadas", command=self.consolidar_contagens_selecionadas)
        btn_consolidar.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        btn_relatorio_cmv = ttk.Button(frame_botoes_hist, text="💰 Valor do Estoque", command=self.abrir_relatorio_valoracao)
        btn_relatorio_cmv.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

    def filtrar_combo_contagem(self, event=None):
        # [MELHORIA UX] Busca sem acento, com várias palavras, e ignorando teclas de
        # navegação (antes, apertar a seta ou o Enter refazia a busca e perdia a escolha).
        if event is not None and getattr(event, 'keysym', '') in ('Return', 'KP_Enter', 'Up', 'Down', 'Tab', 'Escape'):
            return
        texto = self.entry_filtro_contagem.get()
        if not texto.strip():
            self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes
            self.combo_contagem_produtos.set('')
            self.lbl_contagem_unidade.config(text="UN")
            self.lbl_contagem_encontrados.config(text="")
            return
        filtrados = buscar_nomes(texto, self.lista_mestre_contagem_nomes)
        self.combo_contagem_produtos['values'] = filtrados
        if filtrados:
            self.combo_contagem_produtos.set(filtrados[0])
            self.atualizar_label_unidade_contagem()  # [CORREÇÃO] Atualiza a unidade visualmente
            extra = " (use ↑ ↓ para trocar)" if len(filtrados) > 1 else ""
            self.lbl_contagem_encontrados.config(text=f"{len(filtrados)} encontrado(s){extra}", foreground="gray")
        else:
            self.combo_contagem_produtos.set('')
            self.lbl_contagem_unidade.config(text="UN")
            self.lbl_contagem_encontrados.config(text="Nenhum produto encontrado", foreground="#c62828")

    def contagem_navegar_resultados(self, passo):
        """Setas ↑/↓ no campo de busca trocam o produto escolhido."""
        valores = list(self.combo_contagem_produtos['values'] or [])
        if not valores:
            return "break"
        atual = self.combo_contagem_produtos.get()
        pos = valores.index(atual) if atual in valores else -1
        novo = valores[(pos + passo) % len(valores)]
        self.combo_contagem_produtos.set(novo)
        self.atualizar_label_unidade_contagem()
        self.lbl_contagem_encontrados.config(
            text=f"{valores.index(novo) + 1} de {len(valores)}: {novo}", foreground="gray")
        return "break"

    def contagem_enter_na_busca(self, event=None):
        """Enter na busca: confirma o produto e pula para o campo de quantidade."""
        if self.combo_contagem_produtos.get() in self.mapa_produtos_mestre_contagem:
            self.entry_contagem_qtd.focus_set()
            self.entry_contagem_qtd.select_range(0, tk.END)
        else:
            self.status("Nenhum produto encontrado com esse nome. Confira a digitação.", 'aviso')
        return "break"

    def atualizar_label_unidade_contagem(self, event=None):
        # ... (código idêntico ao anterior) ...
        produto_selecionado = self.combo_contagem_produtos.get()
        if produto_selecionado and produto_selecionado in self.mapa_produtos_mestre_contagem:
            unidade = self.mapa_produtos_mestre_contagem[produto_selecionado]['un']
            self.lbl_contagem_unidade.config(text=unidade)
        else:
            self.lbl_contagem_unidade.config(text="UN")
        self._preencher_embalagens_contagem()

    # -------------------------------------------------------------------
    # [MELHORIA CONTAGEM] CONTAR EM CAIXAS
    # -------------------------------------------------------------------
    TEXTO_OUTRA_EMBALAGEM = "➕ Outra embalagem..."

    def _produto_contagem_atual(self):
        nome = self.combo_contagem_produtos.get()
        return (nome, self.mapa_produtos_mestre_contagem[nome]) if nome in self.mapa_produtos_mestre_contagem else (None, None)

    def _preencher_embalagens_contagem(self, escolher_fator=None):
        """Opções do 'Contado em': a unidade do estoque + as caixas dos fornecedores."""
        if not hasattr(self, 'combo_contagem_embalagem'):
            return
        nome, dados = self._produto_contagem_atual()
        un = (dados or {}).get('un') or 'UN'
        opcoes = {f"{un} (unidade do estoque)": Decimal('1')}
        extras = getattr(self, '_embalagens_extras', {})
        lista = list((getattr(self, 'embalagens_contagem', {}) or {}).get((dados or {}).get('id'), []))
        lista += [{'Fator': f, 'Fornecedores': ['digitada por você']} for f in extras.get((dados or {}).get('id'), [])]
        for emb in lista:
            fator = Decimal(str(emb['Fator']))
            forn = ", ".join(emb.get('Fornecedores') or [])[:40]
            texto = f"📦 CX de {fmt_qtd(fator)} {un}" + (f"  ({forn})" if forn else "")
            if fator > 1 and fator not in opcoes.values():
                opcoes[texto] = fator
        if dados:
            opcoes[self.TEXTO_OUTRA_EMBALAGEM] = None
        self._opcoes_embalagem = opcoes
        self.combo_contagem_embalagem['values'] = list(opcoes)
        if escolher_fator is None and dados:
            memoria = self.ler_preferencias().get('embalagem_contagem', {})
            escolher_fator = memoria.get(str(dados['id'])) if isinstance(memoria, dict) else None
        alvo = next((t for t, f in opcoes.items() if f is not None and escolher_fator is not None
                     and f == Decimal(str(escolher_fator))), None)
        self.combo_contagem_embalagem.set(alvo or next(iter(opcoes)))
        self.atualizar_previa_contagem()

    def _fator_contagem_atual(self):
        return self._opcoes_embalagem.get(self.combo_contagem_embalagem.get()) or Decimal('1')

    def ao_escolher_embalagem_contagem(self, event=None):
        if self.combo_contagem_embalagem.get() == self.TEXTO_OUTRA_EMBALAGEM:
            nome, dados = self._produto_contagem_atual()
            texto = simpledialog.askstring(
                "Outra embalagem", f"{nome}\n\nQuantas {dados['un'] if dados else 'UN'} tem em 1 embalagem?\n(ex: 12)",
                parent=self.root)
            try:
                fator = para_decimal(texto, "Embalagem", permitir_zero=False) if texto is not None else None
            except ValueError as e:
                messagebox.showerror("Valor inválido", str(e), parent=self.root)
                fator = None
            if fator and fator > 1 and dados:
                self._embalagens_extras = getattr(self, '_embalagens_extras', {})
                self._embalagens_extras.setdefault(dados['id'], []).append(fator)
                self._preencher_embalagens_contagem(escolher_fator=fator)
            else:
                self._preencher_embalagens_contagem()
        self.atualizar_previa_contagem()
        self.entry_contagem_qtd.focus_set()

    def atualizar_previa_contagem(self, event=None):
        """Mostra, enquanto digita, quanto vai ser lançado na unidade do estoque."""
        if not hasattr(self, 'lbl_contagem_conversao'):
            return
        nome, dados = self._produto_contagem_atual()
        texto = self.entry_contagem_qtd.get().strip()
        fator = self._fator_contagem_atual()
        un = (dados or {}).get('un') or 'UN'
        if not dados:
            self.lbl_contagem_conversao.config(text="")
            return
        if not texto:
            dica = (f"Digite o nº de CAIXAS de {fmt_qtd(fator)} (ex: 3) ou caixas + soltas (ex: 3+5)." if fator > 1 else
                    "Digite a quantidade. Contou em caixa? Escolha a caixa em 'Contado em' ou digite 3x12.")
            self.lbl_contagem_conversao.config(text=dica, foreground="gray")
            return
        try:
            total, detalhe = calcular_qtd_contagem(texto, fator, un)
        except ValueError as e:
            self.lbl_contagem_conversao.config(text=f"⚠️ {e}", foreground="#c62828")
            return
        extra = f"  ({detalhe})" if detalhe else ""
        self.lbl_contagem_conversao.config(text=f"= {fmt_qtd(total)} {un}{extra}", foreground="#0056b3")

    def _lembrar_embalagem_contagem(self, produto_id, fator):
        try:
            dados = self.ler_preferencias()
            memoria = dados.get('embalagem_contagem') if isinstance(dados.get('embalagem_contagem'), dict) else {}
            memoria[str(produto_id)] = str(fator)
            dados['embalagem_contagem'] = memoria
            with open(ARQUIVO_PREFERENCIAS, 'w', encoding='utf-8') as f:
                json.dump(dados, f)
        except Exception as e:
            logger.warning(f"Não foi possível lembrar a embalagem usada na contagem: {e}")

    def _ultima_contagem_do_produto(self, produto_id):
        if self._ultimas_contagens is None:
            try:
                self._ultimas_contagens = getattr(database, 'ultimas_contagens_por_produto', lambda: {})() or {}
            except Exception as e:
                logger.warning(f"Não foi possível ler as últimas contagens: {e}")
                self._ultimas_contagens = {}
        return self._ultimas_contagens.get(produto_id)

    def _item_contagem_por_id(self, produto_id):
        return next((i for i in self.lista_itens_para_salvar_contagem if i['ProdutoID'] == produto_id), None)

    def _redesenhar_lista_contagem(self, destacar_id=None):
        """Mostra a lista da contagem atual (e o total de itens no título)."""
        for i in self.tree_contagem_atual.get_children():
            self.tree_contagem_atual.delete(i)
        for item in self.lista_itens_para_salvar_contagem:
            self.tree_contagem_atual.insert("", "end", iid=str(item['ProdutoID']), values=(
                item['NomeProduto'], fmt_qtd(item['QuantidadeContada']), item['Unidade'], item.get('Detalhe') or ''))
        qtd = len(self.lista_itens_para_salvar_contagem)
        try:
            self.frame_lista_lancar.config(text=f"2. Itens nesta Contagem ({qtd}) — duplo clique corrige a quantidade")
        except (tk.TclError, AttributeError):
            pass
        if destacar_id is not None:
            iid = str(destacar_id)
            try:
                self.tree_contagem_atual.see(iid)
                self.tree_contagem_atual.selection_set(iid)
            except tk.TclError:
                pass

    def _limpar_campos_lancamento(self):
        self.combo_contagem_produtos.set('')
        self.entry_contagem_qtd.delete(0, tk.END)
        self.lbl_contagem_unidade.config(text="UN")
        self._preencher_embalagens_contagem()
        self.lbl_contagem_encontrados.config(text="")
        self.entry_filtro_contagem.delete(0, tk.END)
        self.combo_contagem_produtos['values'] = self.lista_mestre_contagem_nomes
        self.entry_filtro_contagem.focus_set()

    def adicionar_item_contagem(self):
        produto_nome = self.combo_contagem_produtos.get()
        qtd_str = self.entry_contagem_qtd.get()
        if not produto_nome or not qtd_str.strip():
            messagebox.showwarning("Aviso", "Selecione um produto e digite a quantidade.", parent=self.root)
            return
        if produto_nome not in self.mapa_produtos_mestre_contagem:
            messagebox.showwarning("Aviso", "Produto não encontrado. Selecione um item válido da lista.", parent=self.root)
            self.entry_filtro_contagem.focus_set()
            return

        dados_produto = self.mapa_produtos_mestre_contagem[produto_nome]
        produto_id = dados_produto['id']
        unidade = dados_produto['un']
        fator = self._fator_contagem_atual()
        try:
            # [MELHORIA CONTAGEM] aceita caixas: "3" com 'CX de 12' = 36; "3+5" = 3 cx + 5 soltas; "3x12+5"
            quantidade, detalhe = calcular_qtd_contagem(qtd_str, fator, unidade)
        except ValueError as e:
            messagebox.showerror("Quantidade inválida", str(e), parent=self.root)
            self.entry_contagem_qtd.focus_set()
            self.entry_contagem_qtd.select_range(0, tk.END)
            return

        # [MELHORIA CONTAGEM] "Contou em caixa e lançou em unidade?" (compara com a última contagem)
        anterior = self._ultima_contagem_do_produto(produto_id)
        fatores = [e['Fator'] for e in (getattr(self, 'embalagens_contagem', {}) or {}).get(produto_id, [])]
        fatores += getattr(self, '_embalagens_extras', {}).get(produto_id, [])
        simples = bool(re.fullmatch(r'\s*[\d.,]+\s*', qtd_str))
        sugestao = sugerir_unidade_contagem(quantidade, fator, fatores, anterior[0] if anterior else None, simples)
        if sugestao:
            alternativa, fator_alt = sugestao
            como_alt = (f"{qtd_str.strip()} CAIXAS de {fmt_qtd(fator_alt)} = {fmt_qtd(alternativa)} {unidade}" if fator_alt > 1
                        else f"{qtd_str.strip()} {unidade} (unidades)")
            resposta = messagebox.askyesnocancel(
                "Confere a unidade?",
                f"{produto_nome}\n\nVocê lançou {fmt_qtd(quantidade)} {unidade}"
                + (f" ({detalhe})" if detalhe else "") + ".\n"
                f"Na última contagem ({anterior[1].strftime('%d/%m/%Y')}) eram {fmt_qtd(anterior[0])} {unidade}.\n\n"
                f"Você quis dizer {como_alt}?\n\n"
                f"SIM = usar {fmt_qtd(alternativa)} {unidade}\n"
                f"NÃO = manter {fmt_qtd(quantidade)} {unidade}\n"
                "CANCELAR = voltar e corrigir", parent=self.root)
            if resposta is None:
                self.entry_contagem_qtd.focus_set()
                return
            if resposta:
                quantidade = alternativa
                fator = fator_alt
                detalhe = f"{qtd_str.strip()} cx de {fmt_qtd(fator_alt)}" if fator_alt > 1 else None
        memoria = self.ler_preferencias().get('embalagem_contagem', {})
        if fator > 1 or (isinstance(memoria, dict) and str(produto_id) in memoria):
            self._lembrar_embalagem_contagem(produto_id, fator)   # na próxima, já vem na mesma caixa

        existente = self._item_contagem_por_id(produto_id)
        if existente:
            # [MELHORIA UX] Antes: "já está na lista, remova-o". Agora dá para SOMAR
            # (ex: 2 caixas no freezer + 1 no depósito) ou SUBSTITUIR.
            anterior = Decimal(str(existente['QuantidadeContada']))
            resposta = messagebox.askyesnocancel(
                "Produto já contado",
                f"'{produto_nome}' já está na lista com {fmt_qtd(anterior)} {unidade}.\n\n"
                f"SIM = SOMAR ({fmt_qtd(anterior)} + {fmt_qtd(quantidade)} = {fmt_qtd(anterior + quantidade)} {unidade})\n"
                f"NÃO = SUBSTITUIR por {fmt_qtd(quantidade)} {unidade}\n"
                f"CANCELAR = não mudar nada",
                parent=self.root)
            if resposta is None:
                self.entry_contagem_qtd.focus_set()
                return
            existente['QuantidadeContada'] = anterior + quantidade if resposta else quantidade
            if resposta:
                partes = [p for p in (existente.get('Detalhe') or fmt_qtd(anterior), detalhe or fmt_qtd(quantidade)) if p]
                existente['Detalhe'] = " + ".join(partes) if (existente.get('Detalhe') or detalhe) else None
            else:
                existente['Detalhe'] = detalhe
            acao = "somado" if resposta else "substituído"
            msg = f"{produto_nome}: {acao}, agora {fmt_qtd(existente['QuantidadeContada'])} {unidade}."
        else:
            self.lista_itens_para_salvar_contagem.append({
                'ProdutoID': produto_id,
                'NomeProduto': produto_nome,
                'QuantidadeContada': quantidade,
                'Unidade': unidade,
                'Detalhe': detalhe,
            })
            msg = f"{produto_nome}: {fmt_qtd(quantidade)} {unidade}" + (f" ({detalhe})" if detalhe else "") + " adicionado."

        self._redesenhar_lista_contagem(destacar_id=produto_id)
        self.salvar_rascunho_contagem()
        self.status(f"{msg} ({len(self.lista_itens_para_salvar_contagem)} itens na contagem)")
        self._limpar_campos_lancamento()

    def editar_item_contagem(self):
        """[MELHORIA UX] Duplo clique num item da lista: corrige a quantidade."""
        selecionado = self.tree_contagem_atual.focus()
        if not selecionado:
            return
        item = next((i for i in self.lista_itens_para_salvar_contagem if str(i['ProdutoID']) == str(selecionado)), None)
        if not item:
            return
        texto = simpledialog.askstring(
            "Corrigir quantidade",
            f"{item['NomeProduto']}\n\nNova quantidade em {item['Unidade']}:\n(contou em caixas? digite 3x12 ou 3x12+5)",
            initialvalue=fmt_qtd(item['QuantidadeContada']), parent=self.root)
        if texto is None:
            return
        try:
            item['QuantidadeContada'], item['Detalhe'] = calcular_qtd_contagem(texto, 1, item['Unidade'])
        except ValueError as e:
            messagebox.showerror("Erro", str(e), parent=self.root)
            return
        self._redesenhar_lista_contagem(destacar_id=item['ProdutoID'])
        self.salvar_rascunho_contagem()
        self.status(f"{item['NomeProduto']}: quantidade corrigida para {fmt_qtd(item['QuantidadeContada'])} {item['Unidade']}.")

    def remover_item_contagem(self):
        selecionado = self.tree_contagem_atual.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione um item da lista 'Itens nesta Contagem' para remover.", parent=self.root)
            return
        item = next((i for i in self.lista_itens_para_salvar_contagem if str(i['ProdutoID']) == str(selecionado)), None)
        nome_produto = item['NomeProduto'] if item else self.tree_contagem_atual.item(selecionado, 'values')[0]
        # [MELHORIA UX] confirmação (com a tecla Delete ficou fácil apagar sem querer)
        if not messagebox.askyesno("Remover item", f"Remover '{nome_produto}' desta contagem?", parent=self.root):
            return
        self.lista_itens_para_salvar_contagem = [
            i for i in self.lista_itens_para_salvar_contagem if str(i['ProdutoID']) != str(selecionado)
        ]
        self._redesenhar_lista_contagem()
        self.salvar_rascunho_contagem()
        self.status(f"'{nome_produto}' removido da contagem.", 'info')

    def salvar_contagem_completa(self):
        if not self.lista_itens_para_salvar_contagem:
            messagebox.showwarning("Aviso", "Adicione pelo menos um item à lista de contagem antes de salvar.", parent=self.root)
            return
        data_contagem = self.date_contagem.get_date().strftime('%Y-%m-%d')
        funcionario_id = self.id_funcionario_contagem 
        nome_cont = self.entry_nome_contagem.get().strip() or "Geral"
        # [AUDITORIA ESTOQUE] A Sugestão de Compra SOMA as contagens do mesmo dia (para contar por
        # área: freezer + depósito). Se o produto já foi contado nesta data (ex: pelo App de
        # Compras) e esta é uma RECONTAGEM, o estoque fica em DOBRO. Antes não havia aviso.
        aviso = ""
        try:
            ja_contados = database.contagens_do_dia_por_produto(
                data_contagem, [i['ProdutoID'] for i in self.lista_itens_para_salvar_contagem])
        except Exception as e:
            logger.warning(f"Não foi possível conferir as contagens do mesmo dia: {e}")
            ja_contados = {}
        if ja_contados:
            nomes = {i['ProdutoID']: (i['NomeProduto'], i['Unidade']) for i in self.lista_itens_para_salvar_contagem}
            linhas = [f"  • {nomes.get(pid, ('?', ''))[0]}: já tem {fmt_qtd(r['qtd'])} {nomes.get(pid, ('', 'UN'))[1]} "
                      f"em {', '.join(r['contagens'])}" for pid, r in list(ja_contados.items())[:8]]
            mais = f"\n  ... e mais {len(ja_contados) - 8}" if len(ja_contados) > 8 else ""
            aviso = (f"\n\n⚠️ {len(ja_contados)} produto(s) desta lista JÁ FORAM CONTADOS nesta data em outra contagem:\n"
                     + "\n".join(linhas) + mais +
                     "\n\nContagens do MESMO DIA são SOMADAS (serve para contar por área: freezer + depósito).\n"
                     "Se você contou esses produtos DE NOVO (recontagem), NÃO salve: corrija a contagem antiga "
                     "('✏️ Editar Contagem'), senão o estoque desses produtos fica em DOBRO.")
        # [MELHORIA UX] confirmação com o resumo (evita salvar pela metade por engano)
        if not messagebox.askyesno(
                "Salvar contagem",
                f"Salvar a contagem '{nome_cont}' de {self.date_contagem.get_date().strftime('%d/%m/%Y')} "
                f"com {len(self.lista_itens_para_salvar_contagem)} itens?" + aviso,
                icon='warning' if aviso else 'question', parent=self.root):
            return
        try:
            sucesso, msg = database.salvar_contagem_estoque(
                data_contagem,
                funcionario_id,
                self.lista_itens_para_salvar_contagem,
                nome_cont
            )
            if sucesso:
                self.status(msg)
                self.entry_nome_contagem.delete(0, tk.END)
                self.entry_nome_contagem.insert(0, "Geral")
                self.lista_itens_para_salvar_contagem.clear()
                self._redesenhar_lista_contagem()
                self.apagar_rascunho_contagem()  # [MELHORIA UX] salvo no banco: rascunho não é mais necessário
                self._ultimas_contagens = None   # [MELHORIA CONTAGEM] recarrega na próxima
                self.atualizar_lista_contagens_historico()
            else:
                messagebox.showerror("Erro de Banco", msg, parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao salvar contagem completa: {e}", exc_info=True)
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado: {e}\n\n"
                                 "Os itens continuam na lista (e guardados no rascunho).", parent=self.root)

    # -------------------------------------------------------------------
    # [MELHORIA UX] RASCUNHO AUTOMÁTICO DA CONTAGEM
    # -------------------------------------------------------------------
    # A cada item lançado, a lista é gravada em "rascunho_contagem.json" (na pasta do
    # programa). Se o programa fechar, travar ou faltar luz, nada se perde: ao abrir de
    # novo, ele pergunta se você quer continuar de onde parou.
    def salvar_rascunho_contagem(self):
        if not self.lista_itens_para_salvar_contagem:
            self.apagar_rascunho_contagem()
            return
        try:
            data_txt = self.date_contagem.get_date().strftime('%Y-%m-%d')
        except Exception:
            data_txt = date.today().strftime('%Y-%m-%d')
        dados = {
            'salvo_em': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'data_contagem': data_txt,
            'nome_contagem': self.entry_nome_contagem.get().strip() or 'Geral',
            'itens': [{'ProdutoID': i['ProdutoID'], 'NomeProduto': i['NomeProduto'],
                       'QuantidadeContada': str(i['QuantidadeContada']), 'Unidade': i['Unidade'],
                       'Detalhe': i.get('Detalhe')}
                      for i in self.lista_itens_para_salvar_contagem],
        }
        temporario = ARQUIVO_RASCUNHO_CONTAGEM + '.tmp'
        try:
            with open(temporario, 'w', encoding='utf-8') as f:
                json.dump(dados, f, ensure_ascii=False, indent=1)
            os.replace(temporario, ARQUIVO_RASCUNHO_CONTAGEM)  # troca de uma vez (não corrompe)
        except OSError as e:
            logger.error(f"Não foi possível salvar o rascunho da contagem: {e}")
            self.status("Não foi possível guardar o rascunho da contagem (veja o log).", 'erro')

    def apagar_rascunho_contagem(self):
        try:
            if os.path.exists(ARQUIVO_RASCUNHO_CONTAGEM):
                os.remove(ARQUIVO_RASCUNHO_CONTAGEM)
        except OSError as e:
            logger.warning(f"Não foi possível apagar o rascunho da contagem: {e}")

    def verificar_rascunho_contagem(self):
        """Ao abrir o programa: oferece continuar uma contagem que não foi salva."""
        if not os.path.exists(ARQUIVO_RASCUNHO_CONTAGEM) or self.lista_itens_para_salvar_contagem:
            return
        try:
            with open(ARQUIVO_RASCUNHO_CONTAGEM, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            itens = []
            for i in dados.get('itens', []):
                itens.append({'ProdutoID': i['ProdutoID'], 'NomeProduto': i['NomeProduto'],
                              'QuantidadeContada': Decimal(str(i['QuantidadeContada'])),
                              'Unidade': i.get('Unidade') or 'UN', 'Detalhe': i.get('Detalhe')})
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as e:
            logger.error(f"Rascunho de contagem ilegível: {e}")
            return
        if not itens:
            self.apagar_rascunho_contagem()
            return

        if messagebox.askyesno(
                "Contagem não salva encontrada",
                f"Existe uma contagem que NÃO foi salva no banco:\n\n"
                f"  • Nome: {dados.get('nome_contagem', 'Geral')}\n"
                f"  • Itens lançados: {len(itens)}\n"
                f"  • Último lançamento: {dados.get('salvo_em', '?')}\n\n"
                "Deseja CONTINUAR essa contagem?\n\n"
                "(Se responder NÃO, ela é descartada — uma cópia fica guardada na pasta "
                "'backups_estoque', por segurança.)", parent=self.root):
            self.lista_itens_para_salvar_contagem = itens
            self.entry_nome_contagem.delete(0, tk.END)
            self.entry_nome_contagem.insert(0, dados.get('nome_contagem', 'Geral'))
            try:
                self.date_contagem.set_date(datetime.strptime(dados['data_contagem'], '%Y-%m-%d').date())
            except (KeyError, ValueError, tk.TclError):
                pass
            self._redesenhar_lista_contagem()
            try:
                self.notebook.select(self.frame_contagem)
            except tk.TclError:
                pass
            self.status(f"Contagem recuperada: {len(itens)} itens. Continue de onde parou.")
        else:
            try:
                os.makedirs(PASTA_BACKUPS, exist_ok=True)
                destino = os.path.join(PASTA_BACKUPS, f"rascunho_descartado_{datetime.now():%Y%m%d_%H%M%S}.json")
                os.replace(ARQUIVO_RASCUNHO_CONTAGEM, destino)
            except OSError as e:
                logger.warning(f"Não foi possível arquivar o rascunho descartado: {e}")
                self.apagar_rascunho_contagem()
            self.status("Rascunho descartado (cópia guardada em 'backups_estoque').", 'info')

    def atualizar_lista_contagens_historico(self):
        # ... (código idêntico ao anterior) ...
        for i in self.tree_hist_contagens.get_children():
            self.tree_hist_contagens.delete(i)
        
        self.mapa_contagens_historico.clear()
        nomes_contagens = []
        
        try:
            contagens = database.listar_contagens_cabecalho()
            try:
                fechados = database.listar_valores_estoque_fechados()
            except Exception as e:
                logger.warning(f"Não foi possível ler os valores fechados: {e}")
                fechados = {}
            for c in contagens:
                # Tratamento seguro para compatibilidade Date vs String
                data_f = fmt_data(c.DataContagem)
                
                nome_contagem_db = getattr(c, 'NomeContagem', 'Geral')
                if not nome_contagem_db: nome_contagem_db = 'Geral'
                
                nome_display = f"ID: {c.ContagemID} - {data_f} - {nome_contagem_db} ({c.NomeCompleto})"
                
                valor_txt = f"🔒 {fmt_reais(fechados[c.ContagemID][0])}" if c.ContagemID in fechados else ""
                self.tree_hist_contagens.insert("", "end", values=(c.ContagemID, data_f, nome_contagem_db, c.NomeCompleto, valor_txt))
                
                nomes_contagens.append(nome_display)
                self.mapa_contagens_historico[nome_display] = c.ContagemID

        except Exception as e:
            logger.error(f"Erro ao atualizar histórico de contagens: {e}", exc_info=True)

    def carregar_itens_contagem_historico(self, event=None):
        # ... (código idêntico ao anterior) ...
        for i in self.tree_hist_itens.get_children():
            self.tree_hist_itens.delete(i)
        selecionado = self.tree_hist_contagens.focus()
        if not selecionado:
            return
        contagem_id = self.tree_hist_contagens.item(selecionado, 'values')[0]
        try:
            itens = database.buscar_itens_contagem(contagem_id)
            for item in itens or []:
                self.tree_hist_itens.insert("", "end", values=(item.NomeProduto, fmt_num(item.QuantidadeContada, 3, "0.000"), item.UnidadeMedida))
        except Exception as e:
            logger.error(f"Erro ao carregar itens do histórico (ContagemID {contagem_id}): {e}", exc_info=True)

    def abrir_gerenciador_avulsos(self):
        """Abre janela para resolver itens marcados como avulsos em qualquer contagem."""
        popup = Toplevel(self.root)
        popup.title("Resolver Itens Avulsos de Contagem")
        popup.geometry("800x400")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        cols = ('ContagemID', 'Data', 'Nome Provisório', 'Qtd', 'EAN Fornecido')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings', selectmode='browse')
        for c in cols: tree.heading(c, text=c)
        tree.column('ContagemID', width=80, anchor='center')
        tree.column('Data', width=100, anchor='center')
        tree.column('Nome Provisório', width=250)
        tree.column('Qtd', width=80, anchor='center')
        tree.column('EAN Fornecido', width=120, anchor='center')

        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def carregar():
            for i in tree.get_children(): tree.delete(i)
            try:
                avulsos = database.listar_itens_avulsos_pendentes()
            except Exception as e:  # [DEPURAÇÃO] erro do banco não derruba mais a janela
                logger.error(f"Erro ao listar itens avulsos: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao carregar os itens avulsos:\n{e}", parent=popup)
                avulsos = []
            # [AUDITORIA ESTOQUE] o mesmo avulso bipado 2x na mesma contagem aparecia em 2 linhas; ao
            # resolver a 1ª, as duas linhas recebiam a quantidade dela. Agora aparece UMA linha com a soma.
            agrupados = {}
            for av in avulsos or []:
                g = agrupados.setdefault((av.ContagemID, av.NomeAvulso), {
                    'data': av.DataContagem, 'qtd': Decimal('0'), 'ean': None})
                g['qtd'] += Decimal(str(av.QuantidadeContada or 0))
                g['ean'] = g['ean'] or (av.EANAvulso or None)
            for (cid, nome), g in agrupados.items():
                tree.insert("", "end", values=(cid, fmt_data(g['data']), nome, fmt_num(g['qtd'], 3, "0.000"),
                                               g['ean'] or "Sem EAN"))

        def resolver_clicado(event):
            sel = tree.focus()
            if not sel: return
            vals = tree.item(sel, 'values')
            contagem_id, nome_avulso, qtd_contada, ean_fornecido = vals[0], vals[2], vals[3], vals[4]
            if self.contagem_bloqueada(contagem_id, "resolver este item avulso", popup):
                return

            edit_win = Toplevel(popup)
            edit_win.title("Resolução Inteligente de Avulsos")
            edit_win.geometry("580x550")
            edit_win.transient(popup)

            ttk.Label(edit_win, text=f"Item Contado: {nome_avulso}", font=("Arial", 11, "bold")).pack(pady=(10,2), padx=10, anchor="w")
            ttk.Label(edit_win, text=f"Qtd Original: {qtd_contada} | EAN Bipado: {ean_fornecido}", font=("Arial", 9), foreground="blue").pack(pady=(0,10), padx=10, anchor="w")

            notebook_res = ttk.Notebook(edit_win)
            notebook_res.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

            # --- ABA A: Vínculo Direto ---
            tab_direto = ttk.Frame(notebook_res, padding="10")
            notebook_res.add(tab_direto, text='Opção A: Produto Normal')

            ttk.Label(tab_direto, text="Este item já existe no sistema na medida correta (UN ou KG).\nSó esquecemos de cadastrar o código de barras.", font=("Arial", 9, "italic")).pack(anchor="w", pady=(0,15))

            ttk.Label(tab_direto, text="Vincular ao Produto Mestre:").pack(anchor="w")
            combo_mestre = ttk.Combobox(tab_direto, values=self.lista_mestre_produtos_nomes, state="readonly", width=50)
            combo_mestre.pack(fill="x", pady=5)

            ttk.Label(tab_direto, text="Ajuste de Quantidade a Lançar:").pack(anchor="w", pady=(10,0))
            entry_qtd_a = ttk.Entry(tab_direto, width=15)
            entry_qtd_a.pack(anchor="w", pady=5)
            entry_qtd_a.insert(0, qtd_contada.strip())

            var_salvar_ean = tk.BooleanVar(value=True)
            check_ean = ttk.Checkbutton(tab_direto, text=f"Aprender EAN {ean_fornecido} para não dar erro na próxima vez?", variable=var_salvar_ean)
            if ean_fornecido != "Sem EAN": check_ean.pack(anchor="w", pady=10)

            def salvar_direto():
                sel_mestre = combo_mestre.get()
                if not sel_mestre: return messagebox.showerror("Erro", "Selecione o Mestre.", parent=edit_win)
                try: nova_qtd = para_decimal(entry_qtd_a.get(), "Quantidade")
                except ValueError as ve: return messagebox.showerror("Erro", f"Qtd inválida: {ve}", parent=edit_win)

                mestre_id = self.mapa_produtos_mestre.get(sel_mestre)
                if not mestre_id: return messagebox.showerror("Erro", "Produto Mestre não encontrado. Escolha de novo.", parent=edit_win)
                salvar_perm = var_salvar_ean.get() if ean_fornecido != "Sem EAN" else False

                if database.vincular_item_avulso_inteligente(contagem_id, nome_avulso, mestre_id, nova_qtd, ean_fornecido, salvar_perm):
                    messagebox.showinfo("Sucesso", "Item integrado com sucesso!", parent=edit_win)
                    edit_win.destroy(); carregar(); self.carregar_itens_contagem_historico()
                else: messagebox.showerror("Erro", "Falha ao gravar.", parent=edit_win)

            ttk.Button(tab_direto, text="✅ Confirmar Vinculação (Opção A)", command=salvar_direto).pack(pady=15, fill="x", ipady=5)


            # --- ABA B: Fracionar Caixa ---
            tab_caixa = ttk.Frame(notebook_res, padding="10")
            notebook_res.add(tab_caixa, text='Opção B: Desmembrar Caixa')

            ttk.Label(tab_caixa, text="Este item é a UNIDADE de uma caixa que compramos fechada.\nO sistema calculará o custo e aprenderá o código de barras novo.", font=("Arial", 9, "italic")).pack(anchor="w", pady=(0,10))

            ttk.Label(tab_caixa, text="1. Buscar Cadastro da Caixa (por Nome XML ou Mestre):").pack(anchor="w")
            frame_busca = ttk.Frame(tab_caixa)
            frame_busca.pack(fill="x", pady=5)
            entry_busca_caixa = ttk.Entry(frame_busca)
            entry_busca_caixa.pack(side=tk.LEFT, fill="x", expand=True, padx=(0,5))

            tree_caixas = criar_tree_zebrada(tab_caixa, columns=('ID', 'Mestre', 'Desc XML', 'Forn'), show='headings', height=4)
            tree_caixas.heading('ID', text='ID'); tree_caixas.column('ID', width=0, stretch=tk.NO)
            tree_caixas.heading('Mestre', text='Produto Mestre'); tree_caixas.column('Mestre', width=120)
            tree_caixas.heading('Desc XML', text='Descrição NF'); tree_caixas.column('Desc XML', width=150)
            tree_caixas.heading('Forn', text='Fornecedor'); tree_caixas.column('Forn', width=100)
            tree_caixas.pack(fill="x", pady=5)

            def buscar_caixas():
                termo = entry_busca_caixa.get()
                if not termo: return
                for i in tree_caixas.get_children(): tree_caixas.delete(i)
                # Reutiliza inteligentemente a função da API do celular
                try:
                    res = database.buscar_produtos_mobile_por_nome(termo)
                except Exception as e:
                    logger.error(f"Erro na busca de caixas: {e}", exc_info=True)
                    res = []
                for r in res or []:
                    # r = [ProdutoFornecedorID, NomeMestre, DescricaoXML, Fornecedor...]
                    tree_caixas.insert("", "end", values=(r[0], r[1], r[2], r[3]))

            entry_busca_caixa.bind("<Return>", lambda e: buscar_caixas())
            ttk.Button(frame_busca, text="🔍 Buscar", command=buscar_caixas).pack(side=tk.LEFT)

            ttk.Label(tab_caixa, text="2. Quantas unidades vêm na caixa selecionada acima?").pack(anchor="w", pady=(10,0))
            entry_fator_caixa = ttk.Entry(tab_caixa, width=15)
            entry_fator_caixa.pack(anchor="w", pady=5)

            ttk.Label(tab_caixa, text="3. Quantidade de UNIDADES contadas na loja:").pack(anchor="w", pady=(10,0))
            entry_qtd_b = ttk.Entry(tab_caixa, width=15)
            entry_qtd_b.pack(anchor="w", pady=5)
            entry_qtd_b.insert(0, qtd_contada.strip())

            def salvar_fracao():
                sel_caixa = tree_caixas.focus()
                if not sel_caixa: return messagebox.showerror("Erro", "Selecione a Caixa na tabela.", parent=edit_win)
                id_vinculo_caixa = tree_caixas.item(sel_caixa, 'values')[0]

                try:
                    qtd_na_caixa = para_decimal(entry_fator_caixa.get(), "Unidades na caixa", permitir_zero=False)
                    nova_qtd_contada = para_decimal(entry_qtd_b.get(), "Quantidade contada")
                except ValueError as ve: return messagebox.showerror("Erro", f"Valores preenchidos inválidos: {ve}", parent=edit_win)

                if ean_fornecido == "Sem EAN" or not ean_fornecido:
                    return messagebox.showerror("Erro", "Para desmembrar uma caixa, o item avulso deve ter um Código de Barras válido bipado no celular.", parent=edit_win)

                # [DEPURAÇÃO 2] Mostra ANTES tudo o que vai mudar (antes era sem confirmação nenhuma)
                previa = getattr(database, 'previa_desmembrar_caixa', lambda *a: None)(id_vinculo_caixa, qtd_na_caixa)
                if previa:
                    mult = previa['Multiplicador']
                    if mult == 1:
                        texto = (f"'{previa['Produto']}' já está em unidades (Qtd/Cx {fmt_qtd(previa['FatorAtual'])}).\n\n"
                                 f"Só será criado o vínculo do EAN {ean_fornecido} e lançadas {fmt_qtd(nova_qtd_contada)} UN na contagem.")
                    else:
                        texto = (f"O produto '{previa['Produto']}' passa a ser contado em UNIDADES (cada caixa = {fmt_qtd(qtd_na_caixa)} UN).\n\n"
                                 f"Vai mudar (multiplicando por {fmt_qtd(mult)}):\n"
                                 f"  • {previa['Compras']} compra(s) já importada(s) (quantidade × {fmt_qtd(mult)}, custo ÷ {fmt_qtd(mult)})\n"
                                 f"  • o Qtd/Cx de {previa['Vinculos']} vínculo(s) deste produto\n"
                                 f"  • {previa['Contagens'] - previa['Fechadas']} contagem(ns) (quantidade × {fmt_qtd(mult)})"
                                 + (f"\n  • {previa['Fechadas']} contagem(ns) com valor FECHADO NÃO mudam" if previa['Fechadas'] else "")
                                 + f"\n  • o nome ganha '(UNIDADE)' e a unidade vira UN\n\n"
                                 "O valor total de cada compra não muda. Faça backup antes se tiver dúvida.")
                    if not messagebox.askyesno("Confirmar: desmembrar caixa", texto + "\n\nContinuar?", icon='warning', parent=edit_win):
                        return
                sucesso, msg = database.resolver_avulso_fracionando_caixa(contagem_id, nome_avulso, id_vinculo_caixa, ean_fornecido, qtd_na_caixa, nova_qtd_contada)
                if sucesso:
                    messagebox.showinfo("Sucesso", msg, parent=edit_win)
                    edit_win.destroy(); carregar(); self.carregar_itens_contagem_historico()
                    # [DEPURAÇÃO 2] o produto mudou de nome/unidade: atualiza as listas do programa
                    self.atualizar_lista_produtos(); self.popular_combobox_produtos_mestre()
                else: messagebox.showerror("Erro", msg, parent=edit_win)

            ttk.Button(tab_caixa, text="📦 Desmembrar e Confirmar (Opção B)", command=salvar_fracao).pack(pady=15, fill="x", ipady=5)

        tree.bind("<Double-1>", resolver_clicado)
        carregar()

    def contagem_bloqueada(self, contagem_id, acao, janela=None):
        """
        [MELHORIA VALOR] Contagem com valor FECHADO não pode mudar (senão o valor lançado
        no outro sistema deixa de bater com as quantidades). Devolve True se estiver bloqueada.
        """
        # [DEPURAÇÃO 2] se o banco falhar, NÃO libera (antes uma falha momentânea deixava
        # editar/consolidar/excluir uma contagem com valor fechado)
        try:
            try:
                fechados = database.listar_valores_estoque_fechados(levantar_erro=True)
            except TypeError:
                fechados = database.listar_valores_estoque_fechados()
        except Exception as e:
            logger.error(f"Não foi possível conferir se a contagem {contagem_id} está fechada: {e}")
            messagebox.showerror("Banco indisponível", "Não foi possível conferir se esta contagem está com o valor "
                                 "FECHADO. Por segurança, nada foi alterado. Tente de novo.", parent=janela or self.root)
            return True
        try:
            chave = int(contagem_id)
        except (TypeError, ValueError):
            return False
        if chave not in fechados:
            return False
        messagebox.showwarning(
            "Contagem com valor fechado",
            f"A contagem ID {chave} está com o VALOR DO ESTOQUE FECHADO ({fmt_reais(fechados[chave][0])}).\n\n"
            f"Para {acao}, selecione a contagem, clique em '💰 Valor do Estoque' e depois em '🔓 Reabrir'.\n"
            "(Se você já lançou esse valor em outro lugar, lembre de corrigir lá também.)",
            parent=janela or self.root)
        return True

    def abrir_edicao_contagem(self):
        """Abre janela para alterar quantidades ou adicionar/remover itens de uma contagem existente."""
        selecionado = self.tree_hist_contagens.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione uma contagem no Histórico primeiro.", parent=self.root)
            return
        contagem_id = self.tree_hist_contagens.item(selecionado, 'values')[0]
        if self.contagem_bloqueada(contagem_id, "editar esta contagem"):
            return

        popup = Toplevel(self.root)
        popup.title(f"Editor de Contagem ID: {contagem_id}")
        popup.geometry("700x500")
        popup.transient(self.root)

        frame_add = ttk.LabelFrame(popup, text="Adicionar Item Esquecido", padding="10")
        frame_add.pack(fill=tk.X, padx=10, pady=5)
        
        combo_mestre = ttk.Combobox(frame_add, values=self.lista_mestre_produtos_nomes, state="readonly", width=40)
        combo_mestre.pack(side=tk.LEFT, padx=5)
        entry_qtd = ttk.Entry(frame_add, width=10)
        entry_qtd.pack(side=tk.LEFT, padx=5)
        
        cols = ('Nome', 'Qtd', 'IDProduto', 'NomeAvulso')
        tree = criar_tree_zebrada(popup, columns=cols, show='headings', selectmode='browse')
        tree.heading('Nome', text='Produto / Avulso'); tree.column('Nome', width=300)
        tree.heading('Qtd', text='Qtd'); tree.column('Qtd', width=100, anchor='center')
        tree.heading('IDProduto', text='IDProduto'); tree.column('IDProduto', width=0, stretch=tk.NO)
        tree.heading('NomeAvulso', text='NomeAvulso'); tree.column('NomeAvulso', width=0, stretch=tk.NO)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        def carregar():
            for i in tree.get_children(): tree.delete(i)
            itens = database.buscar_itens_contagem(contagem_id)
            for item in itens or []:
                # Retorno do banco agora tem 5 posicoes: Nome, Qtd, UN, ProdutoID, NomeAvulso
                tree.insert("", "end", values=(item.NomeProduto, fmt_num(item.QuantidadeContada, 3, "0.000"), item.ProdutoID or "", item.NomeAvulso or ""))

        def adicionar():
            sel = combo_mestre.get()
            if not sel or not entry_qtd.get().strip():
                messagebox.showwarning("Aviso", "Escolha o produto e digite a quantidade.", parent=popup)
                return
            # [DEPURAÇÃO] Antes QUALQUER erro (até do banco) aparecia como "Quantidade inválida",
            # e se o banco recusasse, nada avisava. Agora cada caso tem sua mensagem.
            try:
                qtd = calcular_qtd_contagem(entry_qtd.get(), 1)[0]   # [MELHORIA CONTAGEM] aceita 3x12+5
            except ValueError as ve:
                messagebox.showerror("Erro", str(ve), parent=popup)
                return
            mestre_id = self.mapa_produtos_mestre.get(sel)
            if not mestre_id:
                messagebox.showerror("Erro", "Produto Mestre não encontrado. Escolha de novo.", parent=popup)
                return
            # [DEPURAÇÃO 2] Produto que JÁ está na contagem: antes somava sem avisar (10 + 10 = 20)
            existente = next((i for i in tree.get_children()
                              if str(tree.item(i, 'values')[2]) == str(mestre_id)), None)
            if existente:
                atual = tree.item(existente, 'values')[1]
                resposta = messagebox.askyesnocancel(
                    "Produto já está na contagem",
                    f"Este produto já tem {atual} nesta contagem.\n\n"
                    f"SIM = SOMAR {fmt_qtd(qtd)}\nNÃO = SUBSTITUIR por {fmt_qtd(qtd)}\nCANCELAR = não mudar", parent=popup)
                if resposta is None:
                    return
                if resposta is False:
                    if not database.atualizar_qtd_item_contagem(contagem_id, int(mestre_id), None, qtd):
                        messagebox.showerror("Erro de Banco", "Não foi possível corrigir o item (veja o log).", parent=popup)
                        return
                    entry_qtd.delete(0, tk.END); combo_mestre.set("")
                    carregar(); self.carregar_itens_contagem_historico()
                    return
            if not database.adicionar_item_contagem_existente(contagem_id, mestre_id, qtd):
                messagebox.showerror("Erro de Banco", "Não foi possível inserir o item (veja o log).", parent=popup)
                return
            entry_qtd.delete(0, tk.END)
            combo_mestre.set("")
            carregar()
            self.carregar_itens_contagem_historico()

        ttk.Button(frame_add, text="➕ Inserir", command=adicionar).pack(side=tk.LEFT, padx=5)

        def editar_remover(event):
            sel = tree.focus()
            if not sel: return
            vals = tree.item(sel, 'values')
            nome, qtd, prod_id, nome_avulso = vals[0], vals[1], vals[2], vals[3]

            edit_win = Toplevel(popup)
            edit_win.title("Alterar/Remover")
            edit_win.geometry("320x175")
            edit_win.transient(popup)

            ttk.Label(edit_win, text=f"{nome}").pack(pady=5)
            ttk.Label(edit_win, text="(contou em caixas? digite 3x12 ou 3x12+5)", foreground="gray").pack()
            e_qtd = ttk.Entry(edit_win, justify='center'); e_qtd.pack(pady=5); e_qtd.insert(0, qtd)

            def salvar():
                try:
                    nova_qtd = calcular_qtd_contagem(e_qtd.get(), 1)[0]   # [MELHORIA CONTAGEM] aceita 3x12+5

                    # Tipagem rigorosa para evitar falha na query do banco
                    id_produto_limpo = int(prod_id) if prod_id and str(prod_id).strip() != "" else None
                    avulso_limpo = str(nome_avulso) if nome_avulso and str(nome_avulso).strip() != "" else None

                    sucesso = database.atualizar_qtd_item_contagem(contagem_id, id_produto_limpo, avulso_limpo, nova_qtd)

                    if sucesso:
                        edit_win.destroy()
                        carregar()
                        self.carregar_itens_contagem_historico()
                    else:
                        messagebox.showerror("Erro de Banco", "Falha ao salvar a nova quantidade no banco de dados.", parent=edit_win)

                except (InvalidOperation, ValueError) as e:
                    messagebox.showerror("Entrada Inválida", "Por favor, digite um número válido maior ou igual a zero.\nUse ponto ou vírgula para decimais.", parent=edit_win)
                    e_qtd.focus() # Retorna o foco para o usuário corrigir

            def apagar():
                if not messagebox.askyesno("Confirmar", f"Tem certeza que deseja remover o item '{nome}' desta contagem?", parent=edit_win):
                    return

                # Sanitização rigorosa de tipos (String da Treeview -> Tipos Nativos Python)
                id_produto_limpo = int(prod_id) if prod_id and str(prod_id).strip() != "" else None
                avulso_limpo = str(nome_avulso) if nome_avulso and str(nome_avulso).strip() != "" else None

                try:
                    sucesso = database.remover_item_contagem(contagem_id, id_produto_limpo, avulso_limpo)
                except Exception as e:  # [DEPURAÇÃO] essa função do banco não trata erros sozinha
                    logger.error(f"Erro ao remover item da contagem: {e}", exc_info=True)
                    sucesso = False

                if sucesso:
                    edit_win.destroy()
                    carregar()
                    self.carregar_itens_contagem_historico()
                else:
                    messagebox.showerror("Erro", "Falha ao remover o item do banco de dados.", parent=edit_win)

            f_btn = ttk.Frame(edit_win); f_btn.pack(pady=10)
            ttk.Button(f_btn, text="💾 Salvar Qtd", command=salvar).pack(side=tk.LEFT, padx=5)
            ttk.Button(f_btn, text="🗑️ Remover", command=apagar).pack(side=tk.LEFT, padx=5)

        tree.bind("<Double-1>", editar_remover)
        carregar()

    def consolidar_contagens_selecionadas(self):
        """
        Junta as contagens selecionadas numa só (somando produtos iguais).
        [DEPURAÇÃO 2] Tudo numa transação no banco (antes: salvava a nova e depois apagava as
        antigas uma a uma; uma falha no meio deixava o estoque em DOBRO). Mostra as datas e
        avisa quando são de dias diferentes. O EAN dos itens avulsos é mantido.
        """
        selecionados = self.tree_hist_contagens.selection()
        if len(selecionados) < 2:
            messagebox.showwarning("Aviso", "Selecione pelo menos duas contagens no histórico para consolidar.", parent=self.root)
            return
        for item in selecionados:  # [MELHORIA VALOR] consolidar apaga as originais
            if self.contagem_bloqueada(self.tree_hist_contagens.item(item, 'values')[0], "consolidar esta contagem"):
                return
        linhas = [self.tree_hist_contagens.item(i, 'values') for i in selecionados]
        ids = [int(v[0]) for v in linhas]
        datas = {data_de_texto_br(v[1]) for v in linhas if data_de_texto_br(v[1])}
        data_consolidada = max(datas) if datas else date.today()
        lista = "\n".join(f"  • ID {v[0]} - {v[1]} - {v[2]}" for v in linhas[:10])
        aviso_datas = ""
        if len(datas) > 1:
            aviso_datas = (f"\n\n⚠️ ATENÇÃO: as contagens são de DIAS DIFERENTES. As quantidades serão SOMADAS "
                           f"e a contagem ficará com a data {data_consolidada.strftime('%d/%m/%Y')}.\n"
                           "Consolidar serve para juntar partes da MESMA contagem (ex: freezer + estoque seco).")
        if not messagebox.askyesno("Confirmar Consolidação",
                                   f"Mesclar estas {len(ids)} contagens?\n{lista}\n\n"
                                   "Os itens iguais serão somados em uma ÚNICA contagem e as originais serão excluídas."
                                   + aviso_datas, icon='warning' if aviso_datas else 'question', parent=self.root):
            return
        nome_nova_contagem = simpledialog.askstring("Nome da Consolidação", "Digite um nome/referência para a nova contagem (Ex: Balanço Consolidado):", parent=self.root)
        if not nome_nova_contagem or not nome_nova_contagem.strip():
            return
        try:
            self.root.config(cursor="watch"); self.root.update_idletasks()
        except Exception:
            pass
        try:
            ok, msg, novo_id = database.consolidar_contagens(ids, data_consolidada.strftime('%Y-%m-%d'),
                                                             self.id_funcionario_contagem, nome_nova_contagem.strip())
        except Exception as e:
            logger.error(f"Erro crítico ao consolidar contagens: {e}", exc_info=True)
            ok, msg = False, str(e)
        finally:
            try:
                self.root.config(cursor="")
            except Exception:
                pass
        if not ok:
            messagebox.showerror("Não foi possível consolidar", msg, parent=self.root)
            return
        self.status(f"{msg} Data: {data_consolidada.strftime('%d/%m/%Y')} (ID {novo_id}).")
        self.atualizar_lista_contagens_historico()
        self.popular_combos_contagem_sugestao()
        for i in self.tree_hist_itens.get_children():
            self.tree_hist_itens.delete(i)

    def abrir_relatorio_valoracao(self):
        """
        [MELHORIA VALOR] Janela "💰 Valor do Estoque" da contagem selecionada.
        - custo de cada produto = MÉDIA PONDERADA das compras dos 90 dias até a data da contagem;
        - conferência antes de fechar: não contados, avulsos, sem custo e custo suspeito;
        - total e subtotal por categoria;
        - "🔒 Fechar valor" grava tudo: o total nunca mais muda (dá para reabrir).
        """
        selecionado = self.tree_hist_contagens.focus()
        if not selecionado:
            messagebox.showwarning("Aviso", "Selecione uma contagem no Histórico primeiro para ver o valor do estoque.", parent=self.root)
            return
        dados_contagem = self.tree_hist_contagens.item(selecionado, 'values')
        contagem_id = int(dados_contagem[0])
        data_contagem = dados_contagem[1]
        nome_contagem = dados_contagem[2]

        popup = Toplevel(self.root)
        popup.title(f"💰 Valor do Estoque - {nome_contagem} ({data_contagem})")
        popup.geometry("1050x720")
        popup.transient(self.root)
        estado = {'dados': None}

        frame = ttk.Frame(popup, padding="12")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"💰 Valor do Estoque — {nome_contagem} ({data_contagem})",
                  font=("Arial", 14, "bold"), foreground="#0056b3").pack(anchor="w")
        lbl_situacao = ttk.Label(frame, text="", font=("Arial", 10, "bold"))
        lbl_situacao.pack(anchor="w", pady=(2, 8))

        # ---------- Conferência ----------
        frame_avisos = ttk.LabelFrame(frame, text="⚠️ Conferência antes de fechar — duplo clique numa linha para resolver", padding="6")
        cols_av = ('Tipo', 'Produto', 'Detalhe')
        tree_av = criar_tree_zebrada(frame_avisos, columns=cols_av, show='headings', selectmode='browse', height=6)
        tree_av.heading('Tipo', text='Tipo'); tree_av.column('Tipo', width=130)
        tree_av.heading('Produto', text='Produto'); tree_av.column('Produto', width=260)
        tree_av.heading('Detalhe', text='O que fazer / detalhe'); tree_av.column('Detalhe', width=560)
        tree_av.pack(fill=tk.X)
        mapa_avisos = {}

        # ---------- Itens ----------
        cols = ('Categoria', 'Produto', 'Qtd', 'UN', 'Custo Unit.', 'Valor', 'Origem do custo')
        frame_tab = ttk.Frame(frame)
        tree = criar_tree_zebrada(frame_tab, columns=cols, show='headings', selectmode='browse')
        for col in cols:
            tree.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(tree, c, False))
        for col, larg, anc in (('Categoria', 120, 'w'), ('Produto', 250, 'w'), ('Qtd', 80, 'e'), ('UN', 45, 'center'),
                               ('Custo Unit.', 100, 'e'), ('Valor', 110, 'e'), ('Origem do custo', 290, 'w')):
            tree.column(col, width=larg, anchor=anc)
        sb = ttk.Scrollbar(frame_tab, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # ---------- Rodapé: categorias + total + botões ----------
        frame_rodape = ttk.Frame(frame)
        tree_cat = criar_tree_zebrada(frame_rodape, columns=('Categoria', 'Valor', '%'), show='headings', height=5)
        tree_cat.heading('Categoria', text='Categoria'); tree_cat.column('Categoria', width=160)
        tree_cat.heading('Valor', text='Valor'); tree_cat.column('Valor', width=120, anchor='e')
        tree_cat.heading('%', text='%'); tree_cat.column('%', width=60, anchor='e')
        tree_cat.pack(side=tk.LEFT)
        frame_dir = ttk.Frame(frame_rodape)
        frame_dir.pack(side=tk.RIGHT, fill=tk.Y)
        lbl_total = ttk.Label(frame_dir, text="", font=("Arial", 18, "bold"), foreground="green")
        lbl_total.pack(anchor="e", pady=(0, 10))
        frame_bot = ttk.Frame(frame_dir)
        frame_bot.pack(anchor="e")

        frame_avisos.pack(fill=tk.X, pady=(0, 8))
        frame_tab.pack(fill=tk.BOTH, expand=True)
        frame_rodape.pack(fill=tk.X, pady=(8, 0))

        def recarregar():
            try:
                popup.config(cursor="watch"); popup.update_idletasks()
                dados = database.calcular_valor_estoque(contagem_id)
            except Exception as e:
                logger.error(f"Erro ao calcular o valor do estoque (contagem {contagem_id}): {e}", exc_info=True)
                messagebox.showerror("Erro", f"Não foi possível calcular o valor do estoque:\n{e}", parent=popup)
                return
            finally:
                try:
                    popup.config(cursor="")
                except tk.TclError:
                    pass
            estado['dados'] = dados

            for t in (tree, tree_av, tree_cat):
                for i in t.get_children():
                    t.delete(i)
            for it in dados['itens']:
                tree.insert("", "end", values=(
                    it.get('Categoria') or 'Geral', it['NomeProduto'], fmt_qtd(it['Quantidade']), it.get('Unidade') or 'UN',
                    fmt_reais(it['CustoUnitario']), fmt_reais(it['ValorTotal']), it.get('OrigemCusto') or ''))
            total = Decimal(str(dados['total'] or 0))
            for cat, valor in dados['por_categoria'].items():
                pct = (Decimal(str(valor)) / total * 100) if total > 0 else Decimal('0')
                tree_cat.insert("", "end", values=(cat or 'Geral', fmt_reais(valor), f"{pct:.1f}%".replace('.', ',')))
            lbl_total.config(text=f"TOTAL: {fmt_reais(total)}")

            mapa_avisos.clear()
            av = dados['avisos']
            textos = {
                'nao_contados': ("❓ Não contado", "{Detalhe} → duplo clique para informar a quantidade (0 se acabou)"),
                'avulsos': ("📦 Avulso", "não entra no valor → duplo clique para resolver"),
                'sem_custo': ("💲 Sem custo", "vai valer R$ 0,00 → duplo clique para informar o custo"),
                'custo_suspeito': ("🔍 Custo suspeito", "{Detalhe} → duplo clique para ver os vínculos"),
            }
            for tipo, lista in av.items():
                rotulo, modelo = textos[tipo]
                for a in lista:
                    iid = tree_av.insert("", "end", values=(rotulo, a['NomeProduto'], modelo.format(Detalhe=a.get('Detalhe', ''))))
                    mapa_avisos[iid] = (tipo, a)
            qtd_avisos = sum(len(v) for v in av.values())

            if dados['fechado']:
                data_f = dados['fechado']['data']
                data_txt = data_f.strftime('%d/%m/%Y %H:%M') if hasattr(data_f, 'strftime') else str(data_f)[:16]
                lbl_situacao.config(text=f"🔒 VALOR FECHADO em {data_txt} — este total não muda mais.", foreground="#1b7a2f")
                frame_avisos.pack_forget()
                btn_fechar.pack_forget(); btn_reabrir.pack(side=tk.LEFT, padx=3, before=btn_copiar)
            else:
                lbl_situacao.config(
                    text="🔓 Valor em aberto — custo médio ponderado das compras dos 90 dias até a data da contagem. "
                         "Confira os avisos e clique em '🔒 Fechar valor'.", foreground="#b35c00")
                btn_reabrir.pack_forget(); btn_fechar.pack(side=tk.LEFT, padx=3, before=btn_copiar)
                if qtd_avisos:
                    frame_avisos.config(text=f"⚠️ Conferência antes de fechar: {qtd_avisos} aviso(s) — duplo clique numa linha para resolver")
                    frame_avisos.pack(fill=tk.X, pady=(0, 8), before=frame_tab)
                else:
                    frame_avisos.pack_forget()

        def resolver_aviso(event=None):
            sel = tree_av.focus()
            if not sel or sel not in mapa_avisos:
                return
            tipo, a = mapa_avisos[sel]
            if tipo == 'nao_contados':
                texto = simpledialog.askstring(
                    "Produto não contado",
                    f"{a['NomeProduto']}\n\nQuantos {a.get('Unidade') or 'UN'} havia na data da contagem?\n(digite 0 se tinha acabado)",
                    parent=popup)
                if texto is None:
                    return
                try:
                    qtd = para_decimal(texto, "Quantidade")
                except ValueError as e:
                    messagebox.showerror("Erro", str(e), parent=popup); return
                if database.adicionar_item_contagem_existente(contagem_id, a['ProdutoID'], qtd):
                    self.status(f"{a['NomeProduto']}: {fmt_qtd(qtd)} adicionado à contagem.")
                    recarregar()
                    self.carregar_itens_contagem_historico()   # [DEPURAÇÃO 2] o painel do histórico também
                else:
                    messagebox.showerror("Erro", "Não foi possível adicionar o item à contagem (veja o log).", parent=popup)
            elif tipo == 'sem_custo':
                texto = simpledialog.askstring(
                    "Produto sem custo",
                    f"{a['NomeProduto']}\n\nCusto por {a.get('Unidade') or 'UN'} (R$):", parent=popup)
                if texto is None:
                    return
                try:
                    custo = para_decimal(texto, "Custo", permitir_zero=False)
                except ValueError as e:
                    messagebox.showerror("Erro", str(e), parent=popup); return
                if database.atualizar_custo_manual_produto(a['ProdutoID'], custo):
                    self.status(f"Custo de {a['NomeProduto']} gravado: {fmt_reais(custo)}.")
                    recarregar()
                else:
                    messagebox.showerror("Erro", "Não foi possível gravar o custo (veja o log).", parent=popup)
            elif tipo == 'avulsos':
                messagebox.showinfo("Item avulso", f"'{a['NomeProduto']}' foi contado sem produto do Catálogo e NÃO entra no valor.\n\n"
                                    "Vou abrir a janela 'Resolver Itens Avulsos'. Depois de resolver, clique em '🔄 Recalcular'.",
                                    parent=popup)
                self.abrir_gerenciador_avulsos()
            elif tipo == 'custo_suspeito':
                # [MELHORIA UX] abre direto nos vínculos DESTE produto; ao salvar, o valor é recalculado
                self.abrir_gestor_vinculos(produto_id=a['ProdutoID'], nome_produto=a['NomeProduto'], ao_salvar=recarregar)

        tree_av.bind("<Double-1>", resolver_aviso)

        def fechar_valor():
            dados = estado['dados']
            if not dados:
                return
            av = dados['avisos']
            qtd_avisos = sum(len(v) for v in av.values())
            texto = f"Fechar o valor do estoque desta contagem em {fmt_reais(dados['total'])}?\n\n" \
                    "Depois de fechado, o total NÃO muda mais (nem com notas novas).\n" \
                    "Você poderá reabrir se precisar corrigir."
            if qtd_avisos:
                texto = (f"⚠️ Ainda há {qtd_avisos} aviso(s) na conferência:\n"
                         f"  • {len(av['nao_contados'])} produto(s) não contado(s)\n"
                         f"  • {len(av['avulsos'])} item(ns) avulso(s)\n"
                         f"  • {len(av['sem_custo'])} produto(s) sem custo\n"
                         f"  • {len(av['custo_suspeito'])} custo(s) suspeito(s)\n\n") + texto
            if not messagebox.askyesno("Fechar valor do estoque", texto, icon='warning' if qtd_avisos else 'question', parent=popup):
                return
            ok, msg, total = database.fechar_valor_estoque(contagem_id)
            if ok:
                self.status(f"Valor do estoque fechado: {fmt_reais(total)} (contagem {nome_contagem} de {data_contagem}).")
                recarregar()
                self.atualizar_lista_contagens_historico()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        def reabrir_valor():
            dados = estado['dados']
            valor = fmt_reais(dados['total']) if dados else ''
            if not messagebox.askyesno(
                    "Reabrir valor",
                    f"Reabrir o valor desta contagem (hoje fechado em {valor})?\n\n"
                    "Ele será recalculado com os custos e quantidades ATUAIS e pode mudar.\n"
                    "Se você já lançou esse valor em outro lugar, lembre de corrigir lá também.",
                    icon='warning', parent=popup):
                return
            if database.reabrir_valor_estoque(contagem_id):
                self.status("Valor do estoque reaberto.", 'aviso')
                recarregar()
                self.atualizar_lista_contagens_historico()
            else:
                messagebox.showerror("Erro", "Não foi possível reabrir (veja o log).", parent=popup)

        def copiar_total():
            dados = estado['dados']
            if not dados:
                return
            texto = f"{Decimal(str(dados['total'])):.2f}".replace('.', ',')
            popup.clipboard_clear(); popup.clipboard_append(texto)
            self.status(f"Total {fmt_reais(dados['total'])} copiado. Cole com Ctrl+V onde for lançar.")

        def exportar_para_excel():
            dados = estado['dados']
            if not dados:
                return
            pd = self._importar_pandas(popup)
            if pd is None:
                return
            caminho_arquivo = filedialog.asksaveasfilename(
                parent=popup, title="Salvar Valor do Estoque", defaultextension=".xlsx",
                filetypes=[("Arquivos Excel", "*.xlsx")],
                initialfile=nome_arquivo_seguro(f"Valor_Estoque_{nome_contagem.replace(' ', '_')}_{data_contagem.replace('/', '-')}.xlsx"))
            if not caminho_arquivo:
                return
            try:
                linhas = [{'Categoria': it.get('Categoria') or 'Geral', 'Produto': it['NomeProduto'],
                           'Quantidade': float(it['Quantidade']), 'UN': it.get('Unidade') or 'UN',
                           'Custo Unitário (R$)': float(it['CustoUnitario']), 'Valor (R$)': float(it['ValorTotal']),
                           'Origem do custo': it.get('OrigemCusto') or ''} for it in dados['itens']]
                df = pd.DataFrame(linhas, columns=['Categoria', 'Produto', 'Quantidade', 'UN', 'Custo Unitário (R$)', 'Valor (R$)', 'Origem do custo'])
                df.loc[len(df)] = ['', '', None, '', None, None, '']
                df.loc[len(df)] = ['TOTAL', '', None, '', None, float(dados['total']), '']
                situacao = "FECHADO" if dados['fechado'] else "EM ABERTO (pode mudar)"
                resumo = pd.DataFrame([
                    {'Item': 'Contagem', 'Valor': f"{nome_contagem} ({data_contagem})"},
                    {'Item': 'Situação do valor', 'Valor': situacao},
                    {'Item': 'Método de custo', 'Valor': 'Custo médio ponderado das compras dos 90 dias até a data da contagem'},
                    {'Item': 'VALOR TOTAL DO ESTOQUE (R$)', 'Valor': float(dados['total'])},
                ] + [{'Item': f"Categoria: {c}", 'Valor': float(v)} for c, v in dados['por_categoria'].items()])
                with pd.ExcelWriter(caminho_arquivo, engine='openpyxl') as escritor:
                    resumo.to_excel(escritor, sheet_name='Resumo', index=False)
                    df.to_excel(escritor, sheet_name='Itens', index=False)
                    avisos = [{'Tipo': t, 'Produto': a['NomeProduto'], 'Detalhe': a.get('Detalhe', '')}
                              for t, lista in dados['avisos'].items() for a in lista]
                    if avisos:
                        pd.DataFrame(avisos).to_excel(escritor, sheet_name='Avisos', index=False)
                messagebox.showinfo("Sucesso", f"Valor do estoque exportado!\nSalvo em: {caminho_arquivo}", parent=popup)
            except Exception as e:
                logger.error(f"Erro ao exportar valor do estoque: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Não foi possível salvar o Excel.\n{e}\n\n"
                                     "Se o arquivo estiver aberto no Excel, feche-o e tente de novo.", parent=popup)

        ttk.Button(frame_bot, text="🔄 Recalcular", command=recarregar).pack(side=tk.LEFT, padx=3)
        btn_fechar = ttk.Button(frame_bot, text="🔒 Fechar valor", command=fechar_valor)
        btn_reabrir = ttk.Button(frame_bot, text="🔓 Reabrir", command=reabrir_valor)
        btn_copiar = ttk.Button(frame_bot, text="📋 Copiar total", command=copiar_total)
        btn_copiar.pack(side=tk.LEFT, padx=3)
        btn_exportar = ttk.Button(frame_bot, text="💾 Exportar para Excel", command=exportar_para_excel)
        btn_exportar.pack(side=tk.LEFT, padx=3)
        self._janela_valor = {'popup': popup, 'recarregar': recarregar, 'estado': estado, 'tree': tree,
                              'tree_av': tree_av, 'mapa_avisos': mapa_avisos, 'fechar': fechar_valor,
                              'reabrir': reabrir_valor, 'copiar': copiar_total, 'exportar': exportar_para_excel,
                              'lbl_total': lbl_total}
        recarregar()

    # ===================================================================
    # == ABA 5: SUGESTÃO DE COMPRA (ATUALIZADA) =========================
    # ===================================================================

    def _importar_pandas(self, janela_pai):
        """[DEPURAÇÃO] Antes, sem o pandas instalado, o botão dava erro e não fazia nada."""
        try:
            import pandas as pd
            return pd
        except ImportError:
            messagebox.showerror("Biblioteca Faltando",
                                 "Para exportar para Excel instale as bibliotecas:\n\npip install pandas openpyxl",
                                 parent=janela_pai)
            return None

    def exportar_folha_contagem_manual(self):
        """Gera um arquivo Excel estruturado por categorias e ordem alfabética para conferência física."""
        pd = self._importar_pandas(self.root)
        if pd is None:
            return

        # Busca os dados processados do banco
        dados_banco = database.buscar_produtos_para_folha_contagem()
        if not dados_banco:
            messagebox.showerror("Erro", "Nenhum produto encontrado no catálogo mestre.", parent=self.root)
            return

        # Abre a caixa de diálogo para escolher onde salvar o arquivo
        caminho_arquivo = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salvar Folha de Contagem Manual",
            defaultextension=".xlsx",
            filetypes=[("Arquivos Excel", "*.xlsx")],
            initialfile=f"Folha_Contagem_Manual_{datetime.now().strftime('%d-%m-%Y')}.xlsx"
        )

        if not caminho_arquivo:
            return

        try:
            # FILTRO MÁGICO: Remove caracteres de controle invisíveis que corrompem o MS Excel
            def limpar_texto(texto):
                if not texto: return ""
                # Substitui tudo que for sujeira invisível (hexadecimais de controle) por NADA
                return re.sub(r'[\x00-\x1f\x7f-\x9f]', '', str(texto)).strip()

            lista_exportacao = []
            for item in dados_banco:
                custo_puro = float(item['UltimoCusto'] or 0)  # [DEPURAÇÃO] vazio não trava
                
                caixas = (getattr(self, 'embalagens_contagem', {}) or {}).get(item['ProdutoID'], [])
                lista_exportacao.append({
                    'Categoria': limpar_texto(item['Categoria']),
                    'ID': item['ProdutoID'],
                    'Nome do Produto Mestre': limpar_texto(item['NomeProduto']),
                    'UN': limpar_texto(item['UnidadeMedida']),
                    'Custo Unitário (c/ Imposto)': custo_puro,
                    # [MELHORIA CONTAGEM] anote caixas fechadas e unidades soltas separadamente
                    'Caixa de (UN)': " / ".join(fmt_qtd(c['Fator']) for c in caixas[:3]),
                    'CAIXAS fechadas': '__________',
                    'UNIDADES (soltas ou total)': '__________',
                })

            df = pd.DataFrame(lista_exportacao)
            # engine='openpyxl' força a formatação estrita que o Windows exige
            df.to_excel(caminho_arquivo, index=False, engine='openpyxl')
            
            messagebox.showinfo("Sucesso", f"Folha de contagem gerada com sucesso!\n\nImprima a planilha para realizar a checagem manual.\n\nSalvo em: {caminho_arquivo}", parent=self.root)

        except ImportError:
            messagebox.showerror("Biblioteca Faltando", "Para gerar Excel, instale o openpyxl:\n\npip install openpyxl", parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao exportar folha de contagem manual: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível gerar a planilha Excel.\nErro: {e}", parent=self.root)


    # ===================================================================
    # == [MELHORIA SUGESTÃO] ABA 5 - SUGESTÃO DE COMPRA (refeita) =======
    # ===================================================================
    OPCAO_A_AUTOMATICO = "🔄 AUTOMÁTICO - consumo dos últimos dias (recomendado)"
    OPCAO_A_PRIMEIRA_COMPRA = "🧾 DESDE A PRIMEIRA COMPRA (estoque zero antes da 1ª nota)"
    OPCAO_A_HISTORICO = "⏮️ TODO O HISTÓRICO de contagens"
    MOSTRAR_SUGESTAO = [
        ('ativos', '✅ Produtos ativos (contados)'),
        ('comprar', '🛒 Só o que precisa comprar'),
        ('conferir', '⚠️ Conferir (conta não fecha)'),
        ('nunca_recente', '❔ Nunca contados, mas comprados recentemente'),
        ('parados', '💤 Parados (zerados e sem movimento)'),
        ('todos', 'Todos os produtos'),
    ]

    def criar_aba_sugestao_compra(self):
        main_frame = ttk.Frame(self.frame_sugestao)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(1, weight=1)
        main_frame.columnconfigure(0, weight=1)
        pref = self.ler_preferencias().get('sugestao', {})
        pref = pref if isinstance(pref, dict) else {}

        # ---------- Parâmetros (mudar aqui exige "Gerar" de novo) ----------
        frame_filtros = ttk.LabelFrame(main_frame, text="Parâmetros da Sugestão", padding="10")
        frame_filtros.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        frame_filtros.columnconfigure(1, weight=1)
        frame_filtros.columnconfigure(3, weight=1)

        ttk.Label(frame_filtros, text="Contagem Final (Ponto B):").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        self.combo_contagem_fim = ttk.Combobox(frame_filtros, state="readonly", width=40)
        self.combo_contagem_fim.grid(row=0, column=1, sticky="ew", padx=5, pady=4)
        ttk.Label(frame_filtros, text="Consumo medido (Ponto A):").grid(row=0, column=2, sticky="w", padx=(15, 5), pady=4)
        frame_a = ttk.Frame(frame_filtros)
        frame_a.grid(row=0, column=3, sticky="ew", padx=5, pady=4)
        frame_a.columnconfigure(0, weight=1)
        self.combo_contagem_inicio = ttk.Combobox(frame_a, state="readonly", width=40)
        self.combo_contagem_inicio.grid(row=0, column=0, sticky="ew")
        self.frame_janela_sug = ttk.Frame(frame_a)
        self.frame_janela_sug.grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(self.frame_janela_sug, text="últimos").pack(side=tk.LEFT)
        self.spin_janela_sugestao = ttk.Spinbox(self.frame_janela_sug, from_=14, to=365, width=5)
        self.spin_janela_sugestao.set(str(pref.get('janela', 90)))
        self.spin_janela_sugestao.pack(side=tk.LEFT, padx=3)
        ttk.Label(self.frame_janela_sug, text="dias").pack(side=tk.LEFT)

        frame_dias = ttk.Frame(frame_filtros)
        frame_dias.grid(row=1, column=0, columnspan=3, sticky="w", padx=5, pady=4)
        ttk.Label(frame_dias, text="Comprar para cobrir").pack(side=tk.LEFT)
        self.spin_dias_cobertura = ttk.Spinbox(frame_dias, from_=1, to=365, width=5)
        self.spin_dias_cobertura.set(str(pref.get('cobertura', 30)))
        self.spin_dias_cobertura.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_dias, text="dias      Prazo de entrega do fornecedor:").pack(side=tk.LEFT)
        self.spin_prazo_entrega = ttk.Spinbox(frame_dias, from_=0, to=60, width=4)
        self.spin_prazo_entrega.set(str(pref.get('prazo', 2)))
        self.spin_prazo_entrega.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_dias, text="dias").pack(side=tk.LEFT)

        btn_gerar_sugestao = ttk.Button(frame_filtros, text="🔄 Gerar Sugestão de Compra", command=self.gerar_sugestao_compra)
        btn_gerar_sugestao.grid(row=1, column=3, sticky="e", padx=5, pady=4, ipady=4)

        # ---------- Filtros (aplicados NA HORA, sem gerar de novo) ----------
        ttk.Separator(frame_filtros, orient="horizontal").grid(row=2, column=0, columnspan=4, sticky="ew", pady=8)
        linha_f = ttk.Frame(frame_filtros)
        linha_f.grid(row=3, column=0, columnspan=4, sticky="ew")
        linha_f.columnconfigure(1, weight=1)
        ttk.Label(linha_f, text="🔍 Buscar:").grid(row=0, column=0, sticky="w", padx=5)
        self.entry_busca_sugestao = ttk.Entry(linha_f, width=22)
        self.entry_busca_sugestao.grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Label(linha_f, text="Mostrar:").grid(row=0, column=2, sticky="w", padx=(10, 3))
        self.combo_mostrar_sugestao = ttk.Combobox(linha_f, state="readonly", width=42)
        self.combo_mostrar_sugestao.grid(row=0, column=3, sticky="w")
        ttk.Label(linha_f, text="Categoria:").grid(row=0, column=4, sticky="w", padx=(10, 3))
        self.combo_sugestao_categoria = ttk.Combobox(linha_f, state="readonly", width=18, values=["Todas"] + self.lista_categorias)
        self.combo_sugestao_categoria.grid(row=0, column=5, sticky="w")
        self.combo_sugestao_categoria.set("Todas")
        ttk.Label(linha_f, text="Fornecedor:").grid(row=0, column=6, sticky="w", padx=(10, 3))
        self.combo_sugestao_fornecedor = ttk.Combobox(linha_f, state="readonly", width=26)
        self.combo_sugestao_fornecedor.grid(row=0, column=7, sticky="w")
        self.combo_sugestao_fornecedor.set("Todos")
        self._mostrar_sug_atual = pref.get('mostrar', 'ativos') if pref.get('mostrar') in dict(self.MOSTRAR_SUGESTAO) else 'ativos'
        self.combo_mostrar_sugestao['values'] = [rot for _, rot in self.MOSTRAR_SUGESTAO]
        self.combo_mostrar_sugestao.set(dict(self.MOSTRAR_SUGESTAO)[self._mostrar_sug_atual])

        frame_acoes_sug = ttk.Frame(frame_filtros)
        frame_acoes_sug.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.lbl_resumo_sugestao = ttk.Label(frame_acoes_sug, text="Clique em '🔄 Gerar Sugestão de Compra' para ver a posição do estoque.",
                                             font=("Arial", 10, "bold"))
        self.lbl_resumo_sugestao.pack(side=tk.LEFT)
        ttk.Button(frame_acoes_sug, text="🍦 Buffet (Top Sabores)", command=self.abrir_gestor_buffet).pack(side=tk.RIGHT, padx=(5, 0), ipady=3)
        ttk.Button(frame_acoes_sug, text="📊 Exportar Excel", command=self.exportar_sugestao_excel).pack(side=tk.RIGHT, padx=(5, 0), ipady=3)
        ttk.Button(frame_acoes_sug, text="📤 Montar Pedido por Fornecedor",
                   command=self.abrir_pedido_compra).pack(side=tk.RIGHT, ipady=3)
        self.lbl_aviso_sugestao = ttk.Label(frame_filtros, text="", foreground="#b26a00", wraplength=1250, justify="left")
        self.lbl_aviso_sugestao.grid(row=5, column=0, columnspan=4, sticky="w", pady=(4, 0))

        self.dados_sugestao_tela = {}
        self.linhas_sugestao = {}
        self.resultado_sugestao = None
        # compatibilidade com código antigo (o "Ocultar zeros" virou a opção "🛒 Só o que precisa comprar")
        self.var_ocultar_zeros = tk.BooleanVar(value=False)

        # ---------- Tabela ----------
        frame_resultado = ttk.LabelFrame(main_frame, text="Posição do Estoque e Sugestão  (clique = ver o cálculo · duplo clique = histórico de compras)", padding="10")
        frame_resultado.grid(row=1, column=0, sticky="nsew")
        frame_resultado.rowconfigure(0, weight=1)
        frame_resultado.columnconfigure(0, weight=1)
        cols = ('Produto', 'UN', 'Última contagem', 'Estoque hoje', 'Consumo/mês', 'Acaba em',
                'Sugestão', 'Pedir', 'Fornecedor', 'Situação')
        self.tree_sugestao = ttk.Treeview(frame_resultado, columns=cols, show='headings')
        for col, larg, anc in (('Produto', 250, 'w'), ('UN', 45, 'center'), ('Última contagem', 105, 'center'),
                               ('Estoque hoje', 95, 'e'), ('Consumo/mês', 95, 'e'), ('Acaba em', 115, 'center'),
                               ('Sugestão', 80, 'e'), ('Pedir', 150, 'w'), ('Fornecedor', 170, 'w'), ('Situação', 125, 'w')):
            self.tree_sugestao.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(self.tree_sugestao, c, False))
            self.tree_sugestao.column(col, width=larg, anchor=anc)
        scrollbar = ttk.Scrollbar(frame_resultado, orient="vertical", command=self.tree_sugestao.yview)
        self.tree_sugestao.configure(yscrollcommand=scrollbar.set)
        self.tree_sugestao.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        for tag, cor in (('critico', '#ffd6d6'), ('comprar', '#fff4cc'), ('ok', '#e3f5e1'), ('conferir', '#ffe0b2'),
                         ('nunca', '#e3eefc')):
            self.tree_sugestao.tag_configure(tag, background=cor)
        self.tree_sugestao.tag_configure('sem_giro', background='#eeeeee', foreground='#666666')
        ttk.Label(frame_resultado, foreground="gray", text=(
            "📏 = produto NÃO contado no Ponto B (vale a última contagem dele + compras - consumo)   ≈ = consumo estimado pelas compras "
            "(só 1 contagem)   Estoque hoje = contagem + notas importadas depois - consumo dos dias que passaram")
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        frame_calc = ttk.LabelFrame(main_frame, text="🧮 Como calculei (clique num produto)", padding=(10, 4))
        frame_calc.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.lbl_calculo_sugestao = ttk.Label(frame_calc, text="Clique num produto da tabela para ver a conta passo a passo.",
                                              justify="left", font=("Consolas", 9), wraplength=1250)
        self.lbl_calculo_sugestao.pack(anchor="w", fill=tk.X)

        self.tree_sugestao.bind("<Double-1>", self.abrir_popup_historico_compras)
        self.tree_sugestao.bind("<<TreeviewSelect>>", self.mostrar_calculo_sugestao)
        self.entry_busca_sugestao.bind("<KeyRelease>", lambda e: self.renderizar_sugestao())
        for combo in (self.combo_mostrar_sugestao, self.combo_sugestao_categoria, self.combo_sugestao_fornecedor):
            combo.bind("<<ComboboxSelected>>", lambda e: self.renderizar_sugestao())
        self.combo_contagem_inicio.bind("<<ComboboxSelected>>", lambda e: self._ajustar_janela_sugestao())
        for spin in (self.spin_dias_cobertura, self.spin_prazo_entrega):
            spin.bind("<Return>", lambda e: self.recalcular_sugestao_na_tela())
            spin.bind("<<Increment>>", lambda e: self.root.after(10, self.recalcular_sugestao_na_tela))
            spin.bind("<<Decrement>>", lambda e: self.root.after(10, self.recalcular_sugestao_na_tela))
            spin.bind("<FocusOut>", lambda e: self.recalcular_sugestao_na_tela())

    def _ajustar_janela_sugestao(self):
        """Os 'últimos N dias' só aparecem no modo automático."""
        if self.combo_contagem_inicio.get() == self.OPCAO_A_AUTOMATICO:
            self.frame_janela_sug.grid()
        else:
            self.frame_janela_sug.grid_remove()

    @staticmethod
    def _inteiro_do_campo(campo, padrao, minimo, maximo):
        texto = str(campo.get()).strip()
        if not texto.isdigit() or not (minimo <= int(texto) <= maximo):
            campo.set(str(padrao))
            return padrao
        return int(texto)

    def _parametros_sugestao(self):
        return {'cobertura': self._inteiro_do_campo(self.spin_dias_cobertura, 30, 1, 365),
                'prazo': self._inteiro_do_campo(self.spin_prazo_entrega, 2, 0, 60),
                'janela': self._inteiro_do_campo(self.spin_janela_sugestao, 90, 14, 365)}

    def gerar_sugestao_compra(self):
        """Busca no banco a posição de cada produto e monta a tabela."""
        params = self._parametros_sugestao()
        str_fim, str_ini = self.combo_contagem_fim.get(), self.combo_contagem_inicio.get()
        if not str_fim:
            messagebox.showwarning("Aviso", "Ainda não há contagem salva. Faça uma contagem na aba 4 primeiro.", parent=self.root)
            return
        try:
            id_fim = self.mapa_contagens_sugestao[str_fim]
            id_ini = self.mapa_contagens_sugestao.get(str_ini)  # None = automático
        except KeyError as e:
            messagebox.showerror("Erro de Seleção", f"Contagem inválida. Atualize a aba (F5).\n{e}", parent=self.root)
            return
        self.root.config(cursor="watch"); self.root.update_idletasks()
        try:
            self.resultado_sugestao = database.calcular_sugestao_compra(id_fim, id_ini, params['janela'])
        except Exception as e:
            logger.error(f"Erro ao gerar sugestão de compra: {e}", exc_info=True)
            messagebox.showerror("Erro ao calcular", str(e), parent=self.root)
            return
        finally:
            self.root.config(cursor="")
        self._salvar_preferencias_sugestao(params)
        self.__dict__['_cache_ids_forn'] = {}
        self.recalcular_sugestao_na_tela()

    def recalcular_sugestao_na_tela(self):
        """Refaz só a conta (dias a cobrir / prazo) sem ir ao banco de novo."""
        if not self.resultado_sugestao:
            return
        params = self._parametros_sugestao()
        r = self.resultado_sugestao
        self.linhas_sugestao = {}
        self.cache_relatorio_posicao.clear()
        for item in r['itens']:
            linha = calcular_linha_sugestao(item, params['cobertura'], params['prazo'], r['DataReferencia'])
            self.linhas_sugestao[item['ProdutoID']] = linha
            self.cache_relatorio_posicao[item['ProdutoID']] = item
        self.renderizar_sugestao()

    def _salvar_preferencias_sugestao(self, params):
        try:
            dados = self.ler_preferencias()
            dados['sugestao'] = dict(params, mostrar=self._mostrar_sug_atual)
            modo_a = self.combo_contagem_inicio.get()
            if modo_a in (self.OPCAO_A_AUTOMATICO, self.OPCAO_A_PRIMEIRA_COMPRA, self.OPCAO_A_HISTORICO):
                dados['sugestao']['modo_a'] = modo_a   # lembra o modo escolhido para a próxima vez
            with open(ARQUIVO_PREFERENCIAS, 'w', encoding='utf-8') as f:
                json.dump(dados, f)
        except Exception as e:
            logger.warning(f"Não foi possível salvar as preferências da sugestão: {e}")

    def _filtro_mostrar_sugestao(self):
        rotulo = self.combo_mostrar_sugestao.get()
        chave = next((ch for ch, rot in self.MOSTRAR_SUGESTAO if rotulo.startswith(rot)), 'ativos')
        self._mostrar_sug_atual = chave
        return chave

    @staticmethod
    def _passa_no_mostrar(chave, linha):
        if chave == 'todos':
            return True
        if chave == 'nunca_recente':
            return linha['tag'] == 'nunca' and linha['comprado_recente']
        if chave == 'parados':
            return linha['parado']
        if chave == 'comprar':
            return linha['qtd_pedido'] > 0
        if chave == 'conferir':
            return linha['tag'] == 'conferir'
        return linha['tag'] != 'nunca' and not linha['parado']   # ativos

    def renderizar_sugestao(self):
        """Desenha a tabela a partir do que já foi calculado (filtros aplicados na hora)."""
        for i in self.tree_sugestao.get_children():
            self.tree_sugestao.delete(i)
        self.dados_sugestao_tela = {}
        if not self.linhas_sugestao:
            return
        chave = self._filtro_mostrar_sugestao()
        categoria = self.combo_sugestao_categoria.get() or "Todas"
        palavras = sem_acento(self.entry_busca_sugestao.get()).split()
        ids_forn = None
        forn_id = self._fornecedor_filtro_sugestao()
        if forn_id is not None:
            # [DEPURAÇÃO 2] consulta UMA vez por fornecedor (antes ia ao banco a cada tecla da busca)
            cache = self.__dict__.setdefault('_cache_ids_forn', {})
            if forn_id not in cache:
                cache[forn_id] = database.buscar_ids_produtos_por_fornecedor(forn_id)
            ids_forn = cache[forn_id]

        # Contadores (sobre o filtro de categoria/fornecedor/busca, antes do "Mostrar")
        contagem_mostrar = {ch: 0 for ch, _ in self.MOSTRAR_SUGESTAO}
        cont_sit = {'critico': 0, 'comprar': 0, 'ok': 0, 'sem_giro': 0, 'conferir': 0, 'nunca': 0}
        total_pedido = Decimal('0')
        visiveis = []
        for pid, linha in self.linhas_sugestao.items():
            item = linha['item']
            if categoria != "Todas" and item['Categoria'] != categoria:
                continue
            if ids_forn is not None and pid not in ids_forn:
                continue
            if palavras and not all(p in sem_acento(f"{item['NomeProduto']} {pid}") for p in palavras):
                continue
            for ch, _ in self.MOSTRAR_SUGESTAO:
                contagem_mostrar[ch] += 1 if self._passa_no_mostrar(ch, linha) else 0
            if not self._passa_no_mostrar(chave, linha):
                continue
            visiveis.append(linha)
        ordem = {'critico': 0, 'conferir': 1, 'comprar': 2, 'ok': 3, 'nunca': 4, 'sem_giro': 5}
        visiveis.sort(key=lambda l: (ordem.get(l['tag'], 9), sem_acento(l['item']['NomeProduto'])))
        for linha in visiveis:
            item = linha['item']
            cont_sit[linha['tag']] += 1
            total_pedido += linha['custo_total']
            iid = str(item['ProdutoID'])
            self.tree_sugestao.insert("", "end", iid=iid, tags=(linha['tag'],), values=linha['colunas'])
            self.dados_sugestao_tela[item['ProdutoID']] = {
                'nome': item['NomeProduto'], 'un': item['Unidade'], 'sugestao': linha['sugestao'],
                'situacao': linha['situacao']}

        rotulos = {ch: f"{rot} ({contagem_mostrar[ch]})" for ch, rot in self.MOSTRAR_SUGESTAO}
        self.combo_mostrar_sugestao['values'] = [rotulos[ch] for ch, _ in self.MOSTRAR_SUGESTAO]
        self.combo_mostrar_sugestao.set(rotulos[chave])
        r = self.resultado_sugestao or {}
        self.lbl_resumo_sugestao.config(text=(
            f"🔴 {cont_sit['critico']} crítico(s)   🟡 {cont_sit['comprar']} para comprar   🟢 {cont_sit['ok']} ok   "
            f"⚠️ {cont_sit['conferir']} conferir   ⚪ {cont_sit['sem_giro']} sem giro      "
            f"Pedido estimado: {fmt_reais(total_pedido)}"))
        avisos = []
        if r.get('DataReferencia') and r.get('DataB') and r['DataReferencia'] > r['DataB']:
            avisos.append(f"Posição projetada para HOJE ({fmt_data(r['DataReferencia'])}): contagem de {fmt_data(r['DataB'])} "
                          "+ notas importadas depois - consumo estimado.")
        if contagem_mostrar['nunca_recente'] and chave != 'nunca_recente':
            avisos.append(f"❔ {contagem_mostrar['nunca_recente']} produto(s) foram comprados nos últimos "
                          f"{r.get('JanelaDias', 90)} dias mas NUNCA foram contados (escolha em 'Mostrar' para ver).")
        self.lbl_aviso_sugestao.config(text="   ".join(avisos))
        self.status(f"Sugestão: {len(visiveis)} produto(s) na tabela.")

    def _fornecedor_filtro_sugestao(self):
        """ID do fornecedor escolhido no filtro da aba 5 (ou None = Todos)."""
        forn_txt = self.combo_sugestao_fornecedor.get() if hasattr(self, 'combo_sugestao_fornecedor') else ''
        m = re.search(r'\(ID: (\d+)\)\s*$', forn_txt or '')
        return int(m.group(1)) if forn_txt and forn_txt != "Todos" and m else None

    def mostrar_calculo_sugestao(self, event=None):
        sel = self.tree_sugestao.focus()
        try:
            linha = self.linhas_sugestao.get(int(sel)) if sel else None
        except ValueError:
            linha = None
        self.lbl_calculo_sugestao.config(text="\n".join(linha['explicacao']) if linha else
                                         "Clique num produto da tabela para ver a conta passo a passo.")

    def exportar_sugestao_excel(self):
        """Salva em Excel exatamente o que está na tabela (com os filtros atuais)."""
        if not self.tree_sugestao.get_children():
            messagebox.showwarning("Aviso", "Primeiro clique em 'Gerar Sugestão de Compra'.", parent=self.root)
            return None
        pd = self._importar_pandas(self.root)
        if pd is None:
            return None
        caminho = filedialog.asksaveasfilename(
            parent=self.root, title="Salvar Sugestão de Compra", defaultextension=".xlsx",
            filetypes=[("Arquivos Excel", "*.xlsx")], initialfile=f"Sugestao_Compra_{datetime.now():%d-%m-%Y}.xlsx")
        if not caminho:
            return None
        try:
            linhas = []
            for iid in self.tree_sugestao.get_children():
                l = self.linhas_sugestao[int(iid)]
                it = l['item']
                linhas.append({
                    'Produto': it['NomeProduto'], 'Categoria': it['Categoria'], 'UN': it['Unidade'],
                    'Última contagem': fmt_data(it['DataUltimaContagem'], vazio=''),
                    'Estoque hoje': float(l['estoque']) if l['estoque'] is not None else None,
                    'Consumo por mês': float(l['umd'] * 30), 'Acaba em': fmt_data(l['acaba_em'], vazio=''),
                    'Sugestão (UN)': float(l['sugestao']), 'Pedir': l['texto_pedido'],
                    'Fornecedor': (l['fornecedor'] or {}).get('Fornecedor', ''),
                    'Custo estimado (R$)': float(l['custo_total']), 'Situação': l['situacao'],
                    'Como calculei': " | ".join(l['explicacao'][1:])})
            pd.DataFrame(linhas).to_excel(caminho, index=False, sheet_name='Sugestão')
            self.status(f"Sugestão salva em: {caminho}")
            messagebox.showinfo("Excel salvo", f"Sugestão salva em:\n{caminho}", parent=self.root)
            return caminho
        except Exception as e:
            logger.error(f"Erro ao exportar sugestão: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível salvar o Excel.\n{e}\n\n"
                                 "Se o arquivo estiver aberto no Excel, feche-o e tente de novo.", parent=self.root)
            return None

    # -------------------------------------------------------------------
    # [MELHORIA UX] PEDIDO DE COMPRA POR FORNECEDOR
    # -------------------------------------------------------------------
    def montar_pedido_por_fornecedor(self, preferir='ultimo'):
        """
        Agrupa os itens da tabela que precisam de compra pelo fornecedor escolhido:
        preferir='ultimo' (fornecedor da última compra) ou 'barato' (mais barato em 12 meses).
        A quantidade sai em CAIXAS do fornecedor (Qtd/Cx do vínculo).
        Devolve {fornecedor: [ {nome, un, qtd, embalagens, fator, texto, custo, total, situacao}, ... ]}.
        """
        params = self._parametros_sugestao()
        data_ref = (self.resultado_sugestao or {}).get('DataReferencia')
        pedido = {}
        for produto_id in self.dados_sugestao_tela:
            linha = self.linhas_sugestao.get(produto_id)
            if not linha:
                continue
            if preferir != 'ultimo':
                linha = calcular_linha_sugestao(linha['item'], params['cobertura'], params['prazo'], data_ref, preferir)
            if linha['qtd_pedido'] <= 0:
                continue
            forn = linha['fornecedor']
            nome_forn = forn['Fornecedor'] if forn else "Sem fornecedor (nunca comprado)"
            pedido.setdefault(nome_forn, []).append({
                'nome': linha['item']['NomeProduto'], 'un': linha['item']['Unidade'], 'qtd': linha['qtd_pedido'],
                'embalagens': linha['embalagens'], 'fator': linha['fator'], 'texto': linha['texto_pedido'],
                'custo': forn['CustoUnid'] if forn else Decimal('0'), 'total': linha['custo_total'],
                'situacao': linha['situacao']})
        for itens in pedido.values():
            itens.sort(key=lambda i: sem_acento(i['nome']))
        return dict(sorted(pedido.items(), key=lambda kv: (kv[0].startswith("Sem fornecedor"), sem_acento(kv[0]))))

    @staticmethod
    def texto_pedido_whatsapp(fornecedor, itens):
        """Mensagem pronta para colar no WhatsApp do fornecedor."""
        empresa = getattr(config, 'NOME_EMPRESA', '') or ''
        linhas = [f"Olá, {fornecedor}! Tudo bem?", "",
                  "Gostaria de fazer o seguinte pedido:", ""]
        for i in itens:
            linhas.append(f"• {i.get('texto') or (fmt_qtd(i['qtd']) + ' ' + i['un'])} - {i['nome']}")
        linhas += ["", "Pode me confirmar a disponibilidade, o valor e o prazo de entrega?", "Obrigado!"]
        if empresa:
            linhas.append(empresa)
        return "\n".join(linhas)

    def abrir_pedido_compra(self):
        if not self.dados_sugestao_tela:
            messagebox.showwarning("Aviso", "Primeiro clique em 'Gerar Sugestão de Compra'.", parent=self.root)
            return
        popup = Toplevel(self.root)
        popup.title("📤 Pedido de Compra por Fornecedor")
        popup.geometry("820x600")
        popup.transient(self.root)
        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        forn_filtro = self._fornecedor_filtro_sugestao()
        nome_filtro = self.combo_sugestao_fornecedor.get().rsplit(' (ID:', 1)[0] if forn_filtro is not None else ''
        var_pref = tk.StringVar(value='filtro' if forn_filtro is not None else 'ultimo')
        linha_pref = ttk.Frame(frame)
        linha_pref.pack(fill=tk.X)
        ttk.Label(linha_pref, text="Comprar de:").pack(side=tk.LEFT)
        lbl_total = ttk.Label(frame, text="", font=("Arial", 10, "bold"))
        lbl_total.pack(anchor="w", pady=(6, 0))
        ttk.Label(frame, text="Só entram os itens da tabela (com os filtros atuais) que precisam de compra. "
                              "Escolha o fornecedor, confira a mensagem (dá para editar) e clique em Copiar.",
                  foreground="gray", wraplength=780, justify="left").pack(anchor="w", pady=(0, 8))
        combo = ttk.Combobox(frame, state="readonly")
        combo.pack(fill=tk.X)
        texto = tk.Text(frame, height=18, wrap="word", font=("Consolas", 10))
        texto.pack(fill=tk.BOTH, expand=True, pady=8)
        estado = {'pedido': {}, 'mapa': {}}

        def montar(*_):
            escolha = var_pref.get()
            preferir = ('fornecedor', forn_filtro) if escolha == 'filtro' and forn_filtro is not None else escolha
            pedido = self.montar_pedido_por_fornecedor(preferir)
            estado['pedido'] = pedido
            self.ultimo_pedido = pedido
            opcoes = [f"{f}  ({len(itens)} itens · {fmt_reais(sum(i['total'] for i in itens))})" for f, itens in pedido.items()]
            estado['mapa'] = dict(zip(opcoes, pedido.keys()))
            combo['values'] = opcoes
            total = sum((i['total'] for itens in pedido.values() for i in itens), Decimal('0'))
            lbl_total.config(text=f"{len(pedido)} fornecedor(es) · valor estimado {fmt_reais(total)}")
            texto.delete("1.0", tk.END)
            if opcoes:
                combo.set(opcoes[0]); mostrar()
            else:
                combo.set("")
                texto.insert("1.0", "Pela sugestão atual (com os filtros da tabela), nenhum produto precisa ser comprado. 🎉")

        def mostrar(event=None):
            fornecedor = estado['mapa'].get(combo.get())
            if fornecedor is None:
                return
            texto.delete("1.0", tk.END)
            texto.insert("1.0", self.texto_pedido_whatsapp(fornecedor, estado['pedido'][fornecedor]))

        def copiar():
            conteudo = texto.get("1.0", tk.END).strip()
            popup.clipboard_clear()
            popup.clipboard_append(conteudo)
            self.status(f"Pedido de '{estado['mapa'].get(combo.get(), '')}' copiado. Cole no WhatsApp com Ctrl+V.")

        opcoes_pref = [('ultimo', "fornecedor da ÚLTIMA compra"), ('barato', "fornecedor MAIS BARATO (últimos 12 meses)")]
        if forn_filtro is not None:   # [DEPURAÇÃO 2] filtrou um fornecedor: o pedido pode ir todo para ele
            opcoes_pref.insert(0, ('filtro', f"o fornecedor do filtro ({nome_filtro[:30]})"))
        for valor, rotulo in opcoes_pref:
            ttk.Radiobutton(linha_pref, text=rotulo, value=valor, variable=var_pref, command=montar).pack(side=tk.LEFT, padx=8)
        combo.bind("<<ComboboxSelected>>", mostrar)
        botoes = ttk.Frame(frame)
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="📋 Copiar mensagem", command=copiar).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5), ipady=4)
        ttk.Button(botoes, text="💾 Salvar Excel (todos os fornecedores)",
                   command=lambda: self.exportar_pedido_excel(estado['pedido'], popup)).pack(side=tk.LEFT, expand=True, fill=tk.X, ipady=4)
        montar()
        self._janela_pedido = {'popup': popup, 'preferir': var_pref, 'montar': montar, 'texto': texto,
                               'combo': combo, 'estado': estado, 'total': lbl_total}

    def exportar_pedido_excel(self, pedido, janela_pai=None):
        """Excel com uma aba de resumo e uma aba para cada fornecedor."""
        pai = janela_pai or self.root
        if not pedido:
            messagebox.showinfo("Nada para salvar", "O pedido está vazio.", parent=pai)
            return None
        pd = self._importar_pandas(pai)
        if pd is None:
            return None
        caminho = filedialog.asksaveasfilename(
            parent=pai, title="Salvar Pedido de Compra", defaultextension=".xlsx",
            filetypes=[("Arquivos Excel", "*.xlsx")],
            initialfile=f"Pedido_Compra_{datetime.now():%d-%m-%Y}.xlsx")
        if not caminho:
            return None
        try:
            usados = set()
            resumo = [{'Fornecedor': f, 'Qtd de itens': len(itens),
                       'Valor estimado (R$)': float(sum(i['total'] for i in itens))} for f, itens in pedido.items()]
            with pd.ExcelWriter(caminho, engine='openpyxl') as escritor:
                pd.DataFrame(resumo).to_excel(escritor, sheet_name=nome_aba_excel('Resumo', usados), index=False)
                for fornecedor, itens in pedido.items():
                    linhas = [{'Produto': i['nome'], 'Pedir': i.get('texto') or f"{fmt_qtd(i['qtd'])} {i['un']}",
                               'Quantidade': float(i['qtd']), 'UN': i['un'],
                               'Último custo (R$)': float(i['custo']), 'Total estimado (R$)': float(i['total']),
                               'Situação': i['situacao']} for i in itens]
                    pd.DataFrame(linhas).to_excel(escritor, sheet_name=nome_aba_excel(fornecedor, usados), index=False)
            self.status(f"Pedido salvo em: {caminho}")
            messagebox.showinfo("Pedido salvo", f"Pedido de compra salvo em:\n{caminho}", parent=pai)
            return caminho
        except Exception as e:
            logger.error(f"Erro ao exportar pedido de compra: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível salvar o Excel.\n{e}\n\n"
                                 "Se o arquivo estiver aberto no Excel, feche-o e tente de novo.", parent=pai)
            return None

    def popular_combos_contagem_sugestao(self):
        """Atualiza os combos da Aba 5 com as contagens salvas (mantendo a escolha do usuário)."""
        try:
            contagens = database.listar_contagens_cabecalho() or []
            selecao_ini_antiga = self.combo_contagem_inicio.get()
            selecao_fim_antiga = self.combo_contagem_fim.get()
            # [AUDITORIA ESTOQUE] quem estava na contagem MAIS RECENTE passa para a nova quando outra é
            # salva (antes o Ponto B ficava na antiga e a sugestão saía com o estoque velho)
            valores_antigos = list(self.combo_contagem_fim['values'] or [])
            estava_na_mais_recente = not valores_antigos or selecao_fim_antiga == valores_antigos[0]
            self.mapa_contagens_sugestao.clear()
            self.mapa_contagens_sugestao[self.OPCAO_A_AUTOMATICO] = None
            self.mapa_contagens_sugestao[self.OPCAO_A_PRIMEIRA_COMPRA] = -2
            self.mapa_contagens_sugestao[self.OPCAO_A_HISTORICO] = -1
            nomes_contagens = []
            for c in contagens:
                nome_contagem_db = getattr(c, 'NomeContagem', None) or 'Geral'
                nome_display = f"ID: {c.ContagemID} - {fmt_data(c.DataContagem)} - {nome_contagem_db} ({c.NomeCompleto})"
                nomes_contagens.append(nome_display)
                self.mapa_contagens_sugestao[nome_display] = c.ContagemID
            self.combo_contagem_fim['values'] = nomes_contagens
            self.combo_contagem_inicio['values'] = [self.OPCAO_A_AUTOMATICO, self.OPCAO_A_PRIMEIRA_COMPRA,
                                                    self.OPCAO_A_HISTORICO] + nomes_contagens
            self.combo_contagem_fim.set(selecao_fim_antiga if selecao_fim_antiga in nomes_contagens and not estava_na_mais_recente
                                        else (nomes_contagens[0] if nomes_contagens else ''))
            if selecao_ini_antiga not in self.mapa_contagens_sugestao:
                pref = self.ler_preferencias().get('sugestao', {})
                selecao_ini_antiga = pref.get('modo_a') if isinstance(pref, dict) else None
            self.combo_contagem_inicio.set(selecao_ini_antiga if selecao_ini_antiga in self.mapa_contagens_sugestao
                                           else self.OPCAO_A_AUTOMATICO)
            self._ajustar_janela_sugestao()
            fornecedores = database.listar_fornecedores() or []
            self.combo_sugestao_fornecedor['values'] = ["Todos"] + [f"{f.NomeFantasia} (ID: {f.FornecedorID})" for f in fornecedores]
        except Exception as e:
            logger.error(f"Erro ao popular combos de contagem (Aba 5): {e}", exc_info=True)


    def abrir_gestor_buffet(self):
        """Abre o painel de gestão inteligente do Buffet (Regra Fixos/Rotativos)."""
        # [DEPURAÇÃO] O arquivo era salvo na "pasta atual" do terminal. Abrindo o programa
        # por um atalho (outra pasta), a seleção de sabores "sumia". Agora fica sempre
        # na pasta do programa (e ainda lê o arquivo antigo, se existir).
        ARQUIVO_CONFIG_BUFFET = os.path.join(PASTA_DO_PROGRAMA, 'config_sabores_buffet.json')
        ARQUIVO_ANTIGO = os.path.abspath('config_sabores_buffet.json')

        # Funções internas para gerenciar o "Cérebro" de seleção
        def carregar_ids_salvos():
            for caminho in (ARQUIVO_CONFIG_BUFFET, ARQUIVO_ANTIGO):
                if os.path.exists(caminho):
                    try:
                        with open(caminho, 'r', encoding='utf-8') as f:
                            dados = json.load(f)
                        return [int(x) for x in dados] if isinstance(dados, list) else []
                    except (OSError, ValueError, TypeError) as e:
                        logger.warning(f"Arquivo de sabores do buffet ilegível ({caminho}): {e}")
            return []

        def salvar_ids_config(lista_ids):
            with open(ARQUIVO_CONFIG_BUFFET, 'w', encoding='utf-8') as f:
                json.dump(lista_ids, f)

        popup = Toplevel(self.root)
        popup.title("🍦 Gerenciador Inteligente de Buffet")
        popup.geometry("1000x600")
        popup.transient(self.root)

        # --- Controle Superior ---
        frame_topo = ttk.Frame(popup, padding="15")
        frame_topo.pack(fill=tk.X)

        ttk.Label(frame_topo, text="Analisar últimos:").pack(side=tk.LEFT)
        spin_dias = ttk.Spinbox(frame_topo, from_=30, to=365, width=5)
        spin_dias.set(90)
        spin_dias.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_topo, text="dias.").pack(side=tk.LEFT)

        ttk.Label(frame_topo, text="| Vagas FIXAS:").pack(side=tk.LEFT, padx=(10, 5))
        spin_vagas = ttk.Spinbox(frame_topo, from_=1, to=100, width=5)
        spin_vagas.set(36)
        spin_vagas.pack(side=tk.LEFT, padx=5)

        btn_processar = ttk.Button(frame_topo, text="🔄 Atualizar Tabela", command=lambda: gerar_analise())
        btn_processar.pack(side=tk.LEFT, padx=10)

        # NOVO BOTÃO: SELETOR MANUAL
        btn_seletor = ttk.Button(frame_topo, text="🛠️ Selecionar Sabores do Buffet", command=lambda: abrir_seletor_manual())
        btn_seletor.pack(side=tk.RIGHT, padx=5)

        # --- Tabela ---
        frame_tabela = ttk.Frame(popup, padding="10")
        frame_tabela.pack(fill=tk.BOTH, expand=True)

        cols = ('Posição', 'Status no Buffet', 'Sabor (Produto Mestre)', 'Unidades Compradas', 'UMD (Consumo/Dia)')
        tree = ttk.Treeview(frame_tabela, columns=cols, show='headings', selectmode='none')

        tree.heading('Posição', text='#'); tree.column('Posição', width=40, anchor='center')
        tree.heading('Status no Buffet', text='Status no Buffet'); tree.column('Status no Buffet', width=150, anchor='center')
        tree.heading('Sabor (Produto Mestre)', text='Sabor (Produto Mestre)'); tree.column('Sabor (Produto Mestre)', width=350)
        tree.heading('Unidades Compradas', text='Unid. Compradas'); tree.column('Unidades Compradas', width=150, anchor='center')
        tree.heading('UMD (Consumo/Dia)', text='UMD (Velocidade Diária)'); tree.column('UMD (Consumo/Dia)', width=150, anchor='center')

        tree.tag_configure('fixo', background='#e6f4ea')
        tree.tag_configure('rotativo', background='#fff3cd')

        sb = ttk.Scrollbar(frame_tabela, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def gerar_analise():
            for i in tree.get_children(): tree.delete(i)

            ids_permitidos = carregar_ids_salvos()

            # Se o arquivo não existir ou estiver vazio, avisa o usuário
            if not ids_permitidos:
                tree.insert("", "end", values=("", "⚠️ Nenhum sabor selecionado.", "Clique em 'Selecionar Sabores' acima para começar.", "", ""))
                return

            try:
                dias = int(spin_dias.get())
                vagas = int(spin_vagas.get())
                if dias <= 0 or vagas <= 0: raise ValueError
            except ValueError:
                messagebox.showerror("Erro", "Dias e Vagas devem ser números inteiros maiores que zero.", parent=popup)
                return

            dados = list(database.gerar_ranking_sabores_buffet(dias, ids_permitidos) or [])
            # [DEPURAÇÃO 2] sabores escolhidos que NÃO foram comprados no período também aparecem
            # (no fim, como rotativos com consumo zero); antes sumiam da lista
            com_compra = {d.get('ProdutoID') for d in dados}
            nomes_por_id = {d['id']: n for n, d in self.mapa_produtos_mestre_contagem.items()}
            for pid in ids_permitidos:
                if pid not in com_compra and pid in nomes_por_id:
                    dados.append({'ProdutoID': pid, 'NomeProduto': nomes_por_id[pid], 'TotalComprado': 0, 'UMD': 0})

            if not dados:
                tree.insert("", "end", values=("", "Sem dados de compra neste período.", "Nenhum dos sabores selecionados foi comprado nesses dias.", "", ""))
                return

            for index, item in enumerate(dados):
                posicao = index + 1
                if posicao <= vagas and float(item.get('UMD') or 0) > 0:   # sem compra nunca vira FIXO
                    status, tag = "⭐ FIXO", "fixo"
                else:
                    status, tag = "🔄 ROTATIVO", "rotativo"

                umd_fmt = f"{float(item['UMD'] or 0):.4f}"
                comprado_fmt = f"{float(item['TotalComprado'] or 0):.2f}".rstrip('0').rstrip('.')

                tree.insert("", "end", values=(posicao, status, item['NomeProduto'], comprado_fmt, umd_fmt), tags=(tag,))

        def abrir_seletor_manual():
            """Abre uma sub-janela com Checklist para você escolher os produtos reais do Buffet."""
            win_sel = Toplevel(popup)
            win_sel.title("Selecione os Produtos que vão para o Buffet")
            win_sel.geometry("500x600")
            win_sel.transient(popup)
            win_sel.grab_set() # Foca o mouse apenas aqui

            ttk.Label(win_sel, text="Marque na lista os verdadeiros sorvetes de massa do Buffet:\n(Pressione e arraste ou clique para marcar vários)", font=("Arial", 10, "bold")).pack(pady=10, padx=10, anchor="w")

            # Lista com Scroll
            frame_list = ttk.Frame(win_sel, padding="10")
            frame_list.pack(fill=tk.BOTH, expand=True)

            sb_list = ttk.Scrollbar(frame_list, orient="vertical")

            # selectmode=tk.MULTIPLE permite clicar em vários sem precisar segurar o CTRL
            listbox = tk.Listbox(frame_list, selectmode=tk.MULTIPLE, yscrollcommand=sb_list.set, font=("Arial", 10))
            sb_list.config(command=listbox.yview)
            listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb_list.pack(side=tk.RIGHT, fill=tk.Y)

            # Busca todos os produtos do estoque e organiza em ordem alfabética
            produtos = database.listar_produtos_estoque() or []
            produtos_ordenados = sorted(produtos, key=lambda x: (x.NomeProduto or '').lower())

            mapa_indice_id = {}
            ids_salvos = carregar_ids_salvos()

            for idx, p in enumerate(produtos_ordenados):
                # Mostra o nome do produto na lista
                listbox.insert(tk.END, f"{p.NomeProduto} (Cat: {getattr(p, 'Categoria', None) or 'Geral'})")
                # Salva o ID verdadeiro dele escondido na memória
                mapa_indice_id[idx] = p.ProdutoID

                # Se ele já estava selecionado antes, já deixa azulzinho
                if p.ProdutoID in ids_salvos:
                    listbox.selection_set(idx)

            def salvar_selecao():
                selecionados_idx = listbox.curselection()
                # Converte a seleção da tela para os IDs verdadeiros do banco
                ids_para_salvar = [mapa_indice_id[i] for i in selecionados_idx]

                try:
                    salvar_ids_config(ids_para_salvar)
                except OSError as e:
                    messagebox.showerror("Erro", f"Não foi possível salvar a seleção:\n{e}", parent=win_sel)
                    return
                messagebox.showinfo("Sucesso", f"{len(ids_para_salvar)} sabores configurados para análise de Buffet!", parent=win_sel)

                win_sel.destroy()
                gerar_analise() # Atualiza a tabela na mesma hora!

            ttk.Button(win_sel, text="💾 Salvar Seleção", command=salvar_selecao).pack(pady=15, fill=tk.X, padx=20, ipady=5)

        # Roda a primeira vez automaticamente
        gerar_analise()

    def abrir_popup_historico_compras(self, event):
        selecionado = linha_do_clique(self.tree_sugestao, event)   # [DEPURAÇÃO 2] não age no cabeçalho
        if not selecionado: return
        try: produto_id = int(selecionado)
        except ValueError: return

        dados_produto = self.cache_relatorio_posicao.get(produto_id)
        if not dados_produto:
            messagebox.showwarning("Aviso", "Gere a sugestão novamente para atualizar o cache.", parent=self.root)
            return

        nome_produto = dados_produto['NomeProduto']
        popup = Toplevel(self.root)
        popup.title(f"Histórico e Correção de Compras - {nome_produto}")
        popup.geometry("850x500")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # CORREÇÃO LÓGICA: Substituído .pack() por .grid() para não conflitar com a Treeview e Scrollbar que também usam grid no mesmo frame.
        ttk.Label(frame, text="⚠️ DICA: Dê um duplo-clique em uma linha para corrigir quantidades e custos antigos importados com fator errado.", foreground="red", font=("Arial", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        # Adicionado o ItemNotaID invisível na tabela
        cols_hist = ('Data Compra', 'NF', 'Fornecedor', 'Qtd', 'Custo Unit.', 'ItemNotaID')
        tree_hist = criar_tree_zebrada(frame, columns=cols_hist, show='headings', selectmode='browse')

        tree_hist.heading('Data Compra', text='Data Compra'); tree_hist.column('Data Compra', width=100, anchor='center')
        tree_hist.heading('NF', text='NF'); tree_hist.column('NF', width=80, anchor='center')
        tree_hist.heading('Fornecedor', text='Fornecedor'); tree_hist.column('Fornecedor', width=250)
        tree_hist.heading('Qtd', text='Qtd'); tree_hist.column('Qtd', width=80, anchor='e')
        tree_hist.heading('Custo Unit.', text='Custo Unit.'); tree_hist.column('Custo Unit.', width=100, anchor='e')
        tree_hist.heading('ItemNotaID', text='ID Oculto'); tree_hist.column('ItemNotaID', width=0, stretch=tk.NO)

        sb = ttk.Scrollbar(frame, orient="vertical", command=tree_hist.yview)
        tree_hist.configure(yscrollcommand=sb.set)
        tree_hist.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        def carregar_dados():
            for i in tree_hist.get_children(): tree_hist.delete(i)
            try:
                historico = database.buscar_historico_compras_produto(produto_id)
                for compra in historico or []:
                    # [DEPURAÇÃO 2] o custo manual do Catálogo (nota "fantasma" de quantidade 0) não é
                    # compra: editar aqui transformava o custo manual em compra de verdade
                    if Decimal(str(getattr(compra, 'Quantidade', 0) or 0)) <= 0 or \
                            'PRODUÇÃO INTERNA' in str(getattr(compra, 'NomeFantasia', '') or '').upper():
                        continue
                    data_f = fmt_data(compra.DataEmissao, vazio="--/--/----")
                    qtd_f = fmt_num(compra.Quantidade, 3, "0.000")
                    custo_f = f"R$ {fmt_num(compra.PrecoCustoUnitario, 4, '0.0000')}"
                    item_id = compra.ItemNotaID # O ID que criamos no banco

                    tree_hist.insert("", "end", values=(data_f, compra.NumeroNF, compra.NomeFantasia, qtd_f, custo_f, item_id))
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao carregar histórico: {e}", parent=popup)

        def editar_linha(event_tree):
            sel = tree_hist.focus()
            if not sel: return
            vals = tree_hist.item(sel, 'values')
            data_nf, num_nf, qtd_atual, custo_atual, item_nota_id = vals[0], vals[1], vals[3], vals[4], vals[5]

            edit_win = Toplevel(popup)
            edit_win.title(f"Corrigir NF {num_nf} ({data_nf})")
            edit_win.geometry("300x200")
            edit_win.transient(popup)

            ttk.Label(edit_win, text="Qtd Exata que Entrou na Loja:").pack(pady=(10,2))
            e_qtd = ttk.Entry(edit_win, justify="center")
            e_qtd.pack(pady=2)
            # [DEPURAÇÃO] BUG GRAVE: a tabela mostra "12.500" (ponto = decimal) e o código antigo
            # APAGAVA o ponto -> a caixinha vinha com 12500. O custo "R$ 10.5000" virava 105000.
            # Bastava abrir e clicar em Salvar para multiplicar a nota por 1000!
            e_qtd.insert(0, qtd_atual.strip())

            ttk.Label(edit_win, text="Custo da Unidade (R$):").pack(pady=(10,2))
            e_custo = ttk.Entry(edit_win, justify="center")
            e_custo.pack(pady=2)
            e_custo.insert(0, custo_atual.replace("R$", "").strip())

            def salvar():
                try:
                    # [DEPURAÇÃO 2] quantidade 0 fazia a compra sumir de todos os cálculos
                    n_qtd = para_decimal(e_qtd.get(), "Quantidade", permitir_zero=False)
                    n_custo = para_decimal(e_custo.get(), "Custo")
                    v_qtd = para_decimal(qtd_atual, "Quantidade")
                    v_custo = para_decimal(custo_atual.replace("R$", ""), "Custo")
                    if n_qtd == v_qtd and n_custo == v_custo:
                        edit_win.destroy()   # nada mudou: não grava
                        return
                    if not messagebox.askyesno(
                            "Corrigir compra",
                            f"NF {num_nf} ({data_nf})\n\n"
                            f"Quantidade: {fmt_qtd(v_qtd)} → {fmt_qtd(n_qtd)}\n"
                            f"Custo/unid.: {fmt_reais(v_custo)} → {fmt_reais(n_custo)}\n"
                            f"Total: {fmt_reais(v_qtd * v_custo)} → {fmt_reais(n_qtd * n_custo)}\n\nConfirmar?",
                            parent=edit_win):
                        return
                    if database.atualizar_item_historico_compra(item_nota_id, n_qtd, n_custo):
                        edit_win.destroy()
                        carregar_dados() # Recarrega a tabelinha
                        # Mostra um aviso pro gestor recalcular a tela de trás
                        messagebox.showinfo("Sucesso", "Histórico corrigido!\nClique em 'Gerar Sugestão' novamente para ver a matemática atualizada.", parent=popup)
                    else:
                        messagebox.showerror("Erro", "Falha ao gravar no banco (a compra pode ter sido apagada; "
                                             "gere a sugestão de novo).", parent=edit_win)
                except ValueError as ve:
                    messagebox.showerror("Erro", str(ve), parent=edit_win)

            ttk.Button(edit_win, text="💾 Salvar Correção", command=salvar).pack(pady=15)

        tree_hist.bind("<Double-1>", editar_linha)
        carregar_dados()

    # ===================================================================
    # == ABA 7: SOLICITAÇÕES (Transplantada do main.py) =================
    # ===================================================================
    def criar_aba_solicitacoes(self):
        main_frame = ttk.Frame(self.frame_solicitacoes)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- ESQUERDA: LISTA ---
        frame_lista = ttk.LabelFrame(main_frame, text="Solicitações Pendentes", padding="10")
        frame_lista.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))
        
        cols = ('ID', 'Solicitante', 'Tipo', 'Categoria', 'Data')
        self.tree_solicitacoes = criar_tree_zebrada(frame_lista, columns=cols, show='headings', selectmode='browse')
        self.tree_solicitacoes.heading('ID', text='ID'); self.tree_solicitacoes.column('ID', width=40)
        self.tree_solicitacoes.heading('Solicitante', text='Solicitante'); self.tree_solicitacoes.column('Solicitante', width=150)
        self.tree_solicitacoes.heading('Tipo', text='Tipo'); self.tree_solicitacoes.column('Tipo', width=80)
        self.tree_solicitacoes.heading('Categoria', text='Categoria'); self.tree_solicitacoes.column('Categoria', width=100)
        self.tree_solicitacoes.heading('Data', text='Data'); self.tree_solicitacoes.column('Data', width=120)
        
        self.tree_solicitacoes.pack(fill=tk.BOTH, expand=True)
        self.tree_solicitacoes.bind('<<TreeviewSelect>>', self.on_solicitacao_selecionada)
        
        ttk.Button(frame_lista, text="🔄 Atualizar Lista", command=self.carregar_solicitacoes).pack(pady=5)
        
        # --- DIREITA: DETALHES ---
        frame_detalhes = ttk.LabelFrame(main_frame, text="Detalhes & Ação", padding="10")
        frame_detalhes.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.lbl_solic_detalhes = tk.Text(frame_detalhes, height=15, width=40, wrap=tk.WORD, state='disabled', font=("Arial", 10))
        self.lbl_solic_detalhes.pack(fill=tk.X, pady=5)
        
        self.btn_ver_foto_solic = ttk.Button(frame_detalhes, text="📸 Ver Foto (Manutenção)", state='disabled', command=self.ver_foto_solicitacao)
        self.btn_ver_foto_solic.pack(pady=5, fill=tk.X)
        
        frame_botoes = ttk.Frame(frame_detalhes)
        frame_botoes.pack(pady=20, fill=tk.X)
        
        ttk.Button(frame_botoes, text="✅ Aprovar", command=self.aprovar_solicitacao).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        ttk.Button(frame_botoes, text="❌ Recusar", command=self.recusar_solicitacao).pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        self.solicitacao_atual_foto = None
        self.solicitacao_atual_id = None
        self.cache_solicitacoes = {}

    def carregar_solicitacoes(self):
        for i in self.tree_solicitacoes.get_children(): self.tree_solicitacoes.delete(i)
        self._limpar_detalhes_solicitacao()

        try:
            dados = database.listar_solicitacoes_pendentes() or []
        except Exception as e:  # [DEPURAÇÃO] essa função do banco não trata erros sozinha
            logger.error(f"Erro ao listar solicitações: {e}", exc_info=True)
            dados = []
        # Colunas SQL: 0:ID, 1:Nome, 2:Tipo, 3:Cat, 4:Desc, 5:Qtd, 6:Foto, 7:Data
        self.cache_solicitacoes = {int(row[0]): row for row in dados}
        
        for row in dados:
            data_fmt = fmt_data(row[7], '%d/%m %H:%M', vazio="")
            self.tree_solicitacoes.insert("", "end", values=(row[0], row[1], row[2], row[3], data_fmt))

    def _limpar_detalhes_solicitacao(self):
        self.solicitacao_atual_id = None
        self.solicitacao_atual_foto = None
        self.lbl_solic_detalhes.config(state='normal')
        self.lbl_solic_detalhes.delete("1.0", tk.END)
        self.lbl_solic_detalhes.config(state='disabled')
        self.btn_ver_foto_solic.config(state='disabled')

    def on_solicitacao_selecionada(self, event):
        sel = self.tree_solicitacoes.focus()
        if not sel: return
        item = self.tree_solicitacoes.item(sel, 'values')
        s_id = int(item[0])
        self.solicitacao_atual_id = s_id
        
        dados = self.cache_solicitacoes.get(s_id)
        if not dados: return
        
        texto = f"Solicitante: {dados[1]}\n"
        texto += f"Tipo: {dados[2]} - {dados[3]}\n"
        texto += f"Data: {fmt_data(dados[7], '%d/%m/%Y %H:%M')}\n\n"
        texto += f"DESCRIÇÃO:\n{dados[4]}\n"
        if dados[5]: texto += f"\nQuantidade: {dados[5]}"
        
        self.lbl_solic_detalhes.config(state='normal')
        self.lbl_solic_detalhes.delete("1.0", tk.END)
        self.lbl_solic_detalhes.insert("1.0", texto)
        self.lbl_solic_detalhes.config(state='disabled')
        
        if dados[6]:
            self.solicitacao_atual_foto = dados[6]
            self.btn_ver_foto_solic.config(state='normal')
        else:
            self.solicitacao_atual_foto = None
            self.btn_ver_foto_solic.config(state='disabled')

    def ver_foto_solicitacao(self):
        caminho = self.solicitacao_atual_foto
        # [DEPURAÇÃO] a foto é salva pelo bot; se o caminho for relativo, procura também na pasta do programa
        if caminho and not os.path.isabs(caminho) and not os.path.exists(caminho):
            caminho = os.path.join(PASTA_DO_PROGRAMA, caminho)
        if caminho and os.path.exists(caminho):
            file_utils.abrir_arquivo(caminho)
        else:
            messagebox.showerror("Erro", "Arquivo de foto não encontrado no disco.", parent=self.root)

    def _mudar_status_solicitacao(self, novo_status, motivo=None):
        try:
            # [DEPURAÇÃO 2] só muda se ainda estiver PENDENTE (outro gestor ou o bot pode ter decidido)
            try:
                return database.atualizar_status_solicitacao(self.solicitacao_atual_id, novo_status, motivo,
                                                             status_esperado='Pendente')
            except TypeError:
                return database.atualizar_status_solicitacao(self.solicitacao_atual_id, novo_status, motivo)
        except Exception as e:  # [DEPURAÇÃO] antes um erro do banco derrubava o botão
            logger.error(f"Erro ao atualizar solicitação {self.solicitacao_atual_id}: {e}", exc_info=True)
            return False

    def aprovar_solicitacao(self):
        if not self.solicitacao_atual_id:
            messagebox.showwarning("Aviso", "Selecione uma solicitação na lista.", parent=self.root)
            return
        if not messagebox.askyesno("Confirmar", "Aprovar a solicitação selecionada?", parent=self.root):
            return
        if self._mudar_status_solicitacao('Aprovado'):
            self.status("Solicitação Aprovada!")  # [MELHORIA UX] rodapé em vez de janelinha
            self.carregar_solicitacoes()
        else:
            messagebox.showerror("Erro", "Não foi possível aprovar. Ela pode já ter sido decidida por outra pessoa "
                                 "(a lista foi atualizada) ou houve falha no banco (veja o log).", parent=self.root)
            self.carregar_solicitacoes()

    def recusar_solicitacao(self):
        if not self.solicitacao_atual_id:
            messagebox.showwarning("Aviso", "Selecione uma solicitação na lista.", parent=self.root)
            return
        motivo = simpledialog.askstring("Recusa", "Motivo da recusa:", parent=self.root)
        if motivo and motivo.strip():
            if self._mudar_status_solicitacao('Recusado', motivo.strip()):
                self.status("Solicitação Recusada.")  # [MELHORIA UX] rodapé em vez de janelinha
                self.carregar_solicitacoes()  # [DEPURAÇÃO] agora também limpa os detalhes da tela
            else:
                messagebox.showerror("Erro", "Não foi possível recusar. Ela pode já ter sido decidida por outra pessoa "
                                     "(a lista foi atualizada) ou houve falha no banco (veja o log).", parent=self.root)
                self.carregar_solicitacoes()

# ===================================================================
    # == ABA 6: ADMINISTRAÇÃO / RESET ===================================
    # ===================================================================
    def criar_aba_administracao(self):
        main_frame = ttk.Frame(self.frame_admin)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Título ---
        ttk.Label(main_frame, text="⚠️ Área de Gestão de Dados - Ações Destrutivas", font=("Arial", 12, "bold"), foreground="red").pack(pady=10)

        # --- Painel Dividido ---
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # --- Esquerda: Gestão de Notas Fiscais ---
        frame_nfs = ttk.LabelFrame(paned, text="Gerenciar Notas Fiscais Importadas", padding="10")
        paned.add(frame_nfs, weight=1)

        cols_nf = ('ID', 'Número', 'Fornecedor', 'Data', 'Valor', 'Itens')
        self.tree_admin_nfs = criar_tree_zebrada(frame_nfs, columns=cols_nf, show='headings', selectmode='extended')
        self.tree_admin_nfs.heading('ID', text='ID'); self.tree_admin_nfs.column('ID', width=30, anchor='center')
        self.tree_admin_nfs.heading('Número', text='Número'); self.tree_admin_nfs.column('Número', width=80)
        self.tree_admin_nfs.heading('Fornecedor', text='Fornecedor'); self.tree_admin_nfs.column('Fornecedor', width=120)
        self.tree_admin_nfs.heading('Data', text='Data'); self.tree_admin_nfs.column('Data', width=80, anchor='center')
        self.tree_admin_nfs.heading('Valor', text='Valor (R$)'); self.tree_admin_nfs.column('Valor', width=80, anchor='e')
        self.tree_admin_nfs.heading('Itens', text='Qtd. Itens'); self.tree_admin_nfs.column('Itens', width=60, anchor='center')
        
        sb_nf = ttk.Scrollbar(frame_nfs, orient="vertical", command=self.tree_admin_nfs.yview)
        self.tree_admin_nfs.configure(yscrollcommand=sb_nf.set)
        self.tree_admin_nfs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_nf.pack(side=tk.RIGHT, fill=tk.Y)

        btn_del_nf = ttk.Button(frame_nfs, text="🗑️ Excluir Nota(s) Selecionada(s)", command=self.excluir_nfs_selecionadas)
        btn_del_nf.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        # --- Botão de Auditoria ---
        frame_auditoria = ttk.LabelFrame(main_frame, text="Revisão de Cadastros", padding="10")
        frame_auditoria.pack(fill=tk.X, pady=10, padx=10)
        
        btn_auditoria = ttk.Button(frame_auditoria, text="🔍 Abrir Auditoria Completa de Produtos (EAN, NCM, Fator)", 
                                   command=self.abrir_tela_auditoria)
        btn_auditoria.pack(fill=tk.X, ipady=5)

        # --- Direita: Gestão de Contagens ---
        frame_cont = ttk.LabelFrame(paned, text="Gerenciar Contagens de Estoque", padding="10")
        paned.add(frame_cont, weight=1)

        cols_cont = ('ID', 'Data', 'Nome', 'Responsável')
        self.tree_admin_cont = criar_tree_zebrada(frame_cont, columns=cols_cont, show='headings', selectmode='extended')
        self.tree_admin_cont.heading('ID', text='ID'); self.tree_admin_cont.column('ID', width=30, anchor='center')
        self.tree_admin_cont.heading('Data', text='Data'); self.tree_admin_cont.column('Data', width=80, anchor='center')
        self.tree_admin_cont.heading('Nome', text='Nome/Ref'); self.tree_admin_cont.column('Nome', width=150)
        self.tree_admin_cont.heading('Responsável', text='Responsável'); self.tree_admin_cont.column('Responsável', width=130)

        sb_cont = ttk.Scrollbar(frame_cont, orient="vertical", command=self.tree_admin_cont.yview)
        self.tree_admin_cont.configure(yscrollcommand=sb_cont.set)
        self.tree_admin_cont.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_cont.pack(side=tk.RIGHT, fill=tk.Y)

        btn_del_cont = ttk.Button(frame_cont, text="🗑️ Excluir Contagem(s) Selecionada(s)", command=self.excluir_contagens_selecionadas)
        btn_del_cont.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        # --- Área de Perigo (Reset Total) ---
        frame_perigo = ttk.LabelFrame(main_frame, text="ZONA DE PERIGO", padding="10")
        frame_perigo.pack(fill=tk.X, pady=20, padx=10)

        lbl_aviso = ttk.Label(frame_perigo, text="Atenção: O botão abaixo apagará TODOS os Produtos, Vínculos, Notas Fiscais e Contagens.\nUse apenas se quiser recomeçar o estoque do zero. Os Fornecedores serão mantidos.", foreground="red", justify=tk.CENTER)
        lbl_aviso.pack(pady=5)

        style = ttk.Style()
        style.configure("Danger.TButton", foreground="red", font=("Arial", 10, "bold"))

        # [MELHORIA UX] O botão fica TRAVADO até marcar a caixinha abaixo (evita clique
        # acidental) e, antes de apagar, o programa faz um BACKUP em Excel de tudo.
        self.var_liberar_reset = tk.BooleanVar(value=False)
        self.btn_reset_total = ttk.Button(frame_perigo, text="☢️ APAGAR TUDO E RECOMEÇAR ESTOQUE ☢️", style="Danger.TButton", command=self.resetar_sistema_estoque)

        def alternar_trava():
            self.btn_reset_total.state(['!disabled'] if self.var_liberar_reset.get() else ['disabled'])

        ttk.Checkbutton(frame_perigo, text="Eu entendo que esta ação apaga TODO o estoque (liberar o botão)",
                        variable=self.var_liberar_reset, command=alternar_trava).pack(pady=(0, 5))
        self.btn_reset_total.pack(ipadx=10, ipady=10)
        self.btn_reset_total.state(['disabled'])
        ttk.Label(frame_perigo, foreground="gray",
                  text="Um backup em Excel é salvo automaticamente na pasta 'backups_estoque' antes de apagar.").pack(pady=(5, 0))

    def atualizar_lista_nfs_admin(self):
        for i in self.tree_admin_nfs.get_children(): self.tree_admin_nfs.delete(i)
        try:
            nfs = database.listar_notas_fiscais_entrada_completa()
            for nf in nfs or []:
                # nf = (NotaID, NumeroNF, NomeFantasia, DataEmissao, ValorTotalNF, QtdItens)
                # [DEPURAÇÃO] data em texto ou valor vazio faziam a lista inteira sumir
                self.tree_admin_nfs.insert("", "end", values=(nf[0], nf[1], nf[2], fmt_data(nf[3]), fmt_num(nf[4], 2, "0.00"), nf[5]))
        except Exception as e:
            logger.error(f"Erro lista admin NF: {e}", exc_info=True)

    def atualizar_lista_contagens_admin(self):
        for i in self.tree_admin_cont.get_children(): self.tree_admin_cont.delete(i)
        try:
            contagens = database.listar_contagens_cabecalho()
            for c in contagens or []:
                data_fmt = fmt_data(c.DataContagem)

                # Resgata o nome da contagem
                nome_contagem_db = getattr(c, 'NomeContagem', 'Geral')
                if not nome_contagem_db: nome_contagem_db = 'Geral'

                self.tree_admin_cont.insert("", "end", values=(c.ContagemID, data_fmt, nome_contagem_db, c.NomeCompleto))
        except Exception as e:
            logger.error(f"Erro lista admin Contagem: {e}", exc_info=True)

    def excluir_nfs_selecionadas(self):
        selecionados = self.tree_admin_nfs.selection()
        if not selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma Nota Fiscal para excluir.", parent=self.root)
            return
        
        # [DEPURAÇÃO 2] as "notas" de custo manual do Catálogo também aparecem aqui: avisa antes
        manuais = [self.tree_admin_nfs.item(i, 'values') for i in selecionados
                   if 'PRODUÇÃO INTERNA' in str(self.tree_admin_nfs.item(i, 'values')[2]).upper()]
        aviso_manual = (f"\n\n⚠️ {len(manuais)} delas são o CUSTO MANUAL de produtos (cadastrado no Catálogo). "
                        "Excluindo, esses produtos ficam SEM custo no Valor do Estoque.") if manuais else ""
        if not messagebox.askyesno("Confirmar Exclusão", f"Você selecionou {len(selecionados)} notas fiscais.\n\nEsta ação apagará o registro da nota e todo o histórico de entrada de estoque associado a ela.{aviso_manual}\n\nDeseja continuar?", icon='warning', parent=self.root):
            return

        sucessos = 0
        for item in selecionados:
            dados = self.tree_admin_nfs.item(item, 'values')
            nota_id = dados[0]
            if database.excluir_nota_fiscal_entrada(nota_id):
                sucessos += 1
        
        if sucessos == len(selecionados):
            self.status(f"{sucessos} de {len(selecionados)} nota(s) excluída(s) com sucesso.")  # [MELHORIA UX] rodapé em vez de janelinha
        else:
            messagebox.showwarning("Resultado", f"{sucessos} de {len(selecionados)} nota(s) excluída(s) com sucesso.", parent=self.root)
        self.atualizar_lista_nfs_admin()
        self._invalidar_sugestao()

    def excluir_contagens_selecionadas(self):
        selecionados = self.tree_admin_cont.selection()
        if not selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma Contagem para excluir.", parent=self.root)
            return
        
        # [AUDITORIA ESTOQUE] Contagem com o VALOR DO ESTOQUE FECHADO era apagada junto com o valor,
        # sem nenhum aviso (editar, consolidar e resolver avulsos já protegiam).
        try:
            fechados = database.listar_valores_estoque_fechados(levantar_erro=True)
        except Exception as e:
            logger.error(f"Não foi possível conferir os valores fechados: {e}")
            messagebox.showerror("Banco indisponível", "Não foi possível conferir se as contagens têm o valor do estoque "
                                 "FECHADO. Por segurança, nada foi apagado. Tente de novo.", parent=self.root)
            return
        ids_sel = [int(self.tree_admin_cont.item(i, 'values')[0]) for i in selecionados]
        com_valor = [(cid, fechados[cid][0]) for cid in ids_sel if cid in fechados]
        aviso = ""
        if com_valor:
            aviso = ("\n\n🔒 ATENÇÃO: " + ", ".join(f"ID {cid} ({fmt_reais(v)})" for cid, v in com_valor[:6])
                     + (" ..." if len(com_valor) > 6 else "")
                     + " tem(têm) o VALOR DO ESTOQUE FECHADO. Esse valor também será APAGADO.\n"
                     "Se você já lançou esse valor em outro lugar (contabilidade, planilha), ele deixa de existir aqui.")
        if not messagebox.askyesno("Confirmar Exclusão", f"Você selecionou {len(selecionados)} contagens.\n\nEsta ação apagará o registro histórico dessa contagem de estoque.{aviso}\n\nDeseja continuar?", icon='warning', parent=self.root):
            return

        sucessos = 0
        for item in selecionados:
            dados = self.tree_admin_cont.item(item, 'values')
            cont_id = dados[0]
            if database.excluir_contagem_estoque(cont_id):
                sucessos += 1
        
        if sucessos == len(selecionados):
            self.status(f"{sucessos} de {len(selecionados)} contagem(ns) excluída(s) com sucesso.")  # [MELHORIA UX] rodapé em vez de janelinha
        else:
            messagebox.showwarning("Resultado", f"{sucessos} de {len(selecionados)} contagem(ns) excluída(s) com sucesso.", parent=self.root)
        self.atualizar_lista_contagens_admin()
        self._ultimas_contagens = None   # [AUDITORIA ESTOQUE] o aviso "contou em caixa?" usava a contagem apagada
        # [DEPURAÇÃO] as abas 4 e 5 continuavam mostrando as contagens apagadas
        self.atualizar_lista_contagens_historico()
        self.popular_combos_contagem_sugestao()
        self._invalidar_sugestao()   # [DEPURAÇÃO 2]

    def resetar_sistema_estoque(self):
            """Executa o reset completo após dupla confirmação."""
            # Confirmação 1
            if not messagebox.askyesno("PERIGO - Reset Total", 
                                    "Tem certeza absoluta que deseja APAGAR TODO O ESTOQUE?\n\n"
                                    "Isso excluirá:\n"
                                    "- Todos os Produtos Mestre\n"
                                    "- Todos os Vínculos criados\n"
                                    "- Todo o histórico de Notas Fiscais\n"
                                    "- Todo o histórico de Contagens\n\n"
                                    "Essa ação NÃO PODE ser desfeita.", 
                                    icon='warning', default='no', parent=self.root):
                return

            # Confirmação 2 (Segurança extra)
            codigo_seguranca = simpledialog.askstring("Confirmação Final", "Para confirmar, digite 'DELETAR' (em maiúsculo) abaixo:", parent=self.root)
            
            if codigo_seguranca == "DELETAR":
                # [MELHORIA UX] Backup automático ANTES de apagar
                caminho_backup = self.backup_estoque_excel()
                if not caminho_backup:
                    if not messagebox.askyesno(
                            "Backup falhou",
                            "NÃO foi possível fazer o backup antes de apagar (veja o log).\n\n"
                            "Deseja apagar MESMO SEM BACKUP?\n(Recomendado: NÃO)",
                            icon='warning', default='no', parent=self.root):
                        return

                # Chama a função do banco de dados
                sucesso = database.resetar_dados_estoque_completo()
                
                if sucesso:
                    texto_backup = f"\n\nBackup do que existia antes:\n{caminho_backup}" if caminho_backup else ""
                    messagebox.showinfo("Sistema Resetado", "O banco de dados de estoque foi limpo com sucesso.\n\nVocê pode começar a cadastrar e vincular novamente." + texto_backup, parent=self.root)
                    self.var_liberar_reset.set(False)
                    self.btn_reset_total.state(['disabled'])
                    
                    # Atualiza todas as listas para refletir o vazio
                    self.atualizar_lista_produtos()
                    self.atualizar_lista_fornecedores() 
                    self.popular_combobox_produtos_mestre()
                    self.atualizar_lista_contagens_historico()
                    self.popular_combos_contagem_sugestao()
                    self.atualizar_lista_nfs_admin()
                    self.atualizar_lista_contagens_admin()
                    
                    # Limpa as árvores de importação
                    for i in self.tree_vincular.get_children(): self.tree_vincular.delete(i)
                    for i in self.tree_prontos.get_children(): self.tree_prontos.delete(i)
                    self.itens_xml_nao_vinculados.clear()
                    self.dados_notas_processadas.clear()
                    self._limpar_estado_apos_reset()
                    
                else:
                    messagebox.showerror("Erro", "Falha ao resetar o banco. Verifique os logs.", parent=self.root)
            else:
                messagebox.showinfo("Cancelado", "Ação cancelada. O código de confirmação estava incorreto.", parent=self.root)

    def _invalidar_sugestao(self):
        """
        [DEPURAÇÃO 2] Notas/contagens apagadas: a sugestão que estava na tela ficou velha
        (o pedido sairia com dados que não existem mais). Limpa e pede para gerar de novo.
        """
        self.resultado_sugestao = None
        for nome in ('linhas_sugestao', 'dados_sugestao_tela', 'cache_relatorio_posicao'):
            if isinstance(getattr(self, nome, None), dict):
                getattr(self, nome).clear()
        if hasattr(self, 'tree_sugestao'):
            for i in self.tree_sugestao.get_children():
                self.tree_sugestao.delete(i)
        if hasattr(self, 'lbl_resumo_sugestao'):
            self.lbl_resumo_sugestao.config(text="Os dados mudaram: clique em '🔄 Gerar Sugestão de Compra' de novo.")

    def _limpar_estado_apos_reset(self):
        """
        [DEPURAÇÃO 2] Depois do reset os IDs recomeçam do 1. Tudo o que estava guardado na tela
        ou em arquivo com os IDs ANTIGOS precisa sair, senão aponta para produtos errados:
        sugestão de compra (o pedido saía com produtos apagados), consultas, formulário do
        catálogo, sabores do buffet e rascunho de contagem.
        """
        self._invalidar_sugestao()
        self.historico_consulta = []
        self.produto_consulta = None
        self.limpar_formulario_produto()
        for arquivo in (os.path.join(PASTA_DO_PROGRAMA, 'config_sabores_buffet.json'), ARQUIVO_RASCUNHO_CONTAGEM):
            try:
                if os.path.exists(arquivo):
                    os.makedirs(PASTA_BACKUPS, exist_ok=True)
                    destino = os.path.join(PASTA_BACKUPS, f"{datetime.now():%Y%m%d_%H%M%S}_antes_reset_{os.path.basename(arquivo)}")
                    os.replace(arquivo, destino)
            except OSError as e:
                logger.warning(f"Não foi possível arquivar {arquivo} depois do reset: {e}")

    def backup_estoque_excel(self):
        """
        [MELHORIA UX] Salva uma cópia de TODO o estoque em Excel (uma aba para cada tipo
        de dado) na pasta 'backups_estoque'. Devolve o caminho do arquivo, ou None se falhar.
        """
        try:
            import pandas as pd
        except ImportError:
            logger.error("Backup antes do reset: pandas não instalado.")
            return None
        # [DEPURAÇÃO 2] Backup COMPLETO: todas as tabelas como estão no banco (inclusive os itens
        # das notas, que antes ficavam de fora). Se qualquer leitura falhar, o backup FALHA
        # (antes um erro virava uma aba "vazia" e o reset seguia como se estivesse tudo salvo).
        if hasattr(database, 'exportar_tabelas_estoque'):
            try:
                os.makedirs(PASTA_BACKUPS, exist_ok=True)
                caminho = os.path.join(PASTA_BACKUPS, f"backup_estoque_antes_reset_{datetime.now():%Y-%m-%d_%H%M%S}.xlsx")
                tabelas = database.exportar_tabelas_estoque()
                with pd.ExcelWriter(caminho, engine='openpyxl') as escritor:
                    for tabela, (colunas, linhas) in tabelas.items():
                        df = pd.DataFrame([list(l) for l in linhas], columns=colunas) if linhas else pd.DataFrame(columns=colunas)
                        for col in df.columns:
                            if df[col].dtype == object:
                                df[col] = df[col].map(lambda v: v if isinstance(v, (str, int, float)) or v is None else str(v))
                        df.to_excel(escritor, sheet_name=tabela[:31], index=False)
                logger.info(f"Backup completo do estoque salvo em {caminho}")
                return caminho
            except Exception as e:
                logger.error(f"Falha no backup do estoque antes do reset: {e}", exc_info=True)
                return None
        try:
            os.makedirs(PASTA_BACKUPS, exist_ok=True)
            caminho = os.path.join(PASTA_BACKUPS, f"backup_estoque_antes_reset_{datetime.now():%Y-%m-%d_%H%M%S}.xlsx")
            itens_contagens = []
            for c in database.listar_contagens_cabecalho() or []:
                for it in linhas_do_banco_para_dicts(database.buscar_itens_contagem(c.ContagemID)):
                    it = {'ContagemID': c.ContagemID, 'DataContagem': fmt_data(c.DataContagem),
                          'NomeContagem': getattr(c, 'NomeContagem', '') or 'Geral', **it}
                    itens_contagens.append(it)
            abas = {
                'Produtos': linhas_do_banco_para_dicts(database.listar_produtos_estoque()),
                'Fornecedores': linhas_do_banco_para_dicts(database.listar_fornecedores()),
                'Vinculos': linhas_do_banco_para_dicts(database.listar_todos_vinculos_detalhado()),
                'NotasFiscais': linhas_do_banco_para_dicts(database.listar_notas_fiscais_entrada_completa()),
                'Contagens': itens_contagens,
            }
            with pd.ExcelWriter(caminho, engine='openpyxl') as escritor:
                for nome, linhas in abas.items():
                    df = pd.DataFrame(linhas) if linhas else pd.DataFrame({'(vazio)': []})
                    # datas/horas com fuso e objetos estranhos viram texto (o Excel não aceita tudo)
                    for col in df.columns:
                        if df[col].dtype == object:
                            df[col] = df[col].map(lambda v: v if isinstance(v, (str, int, float)) or v is None else str(v))
                    df.to_excel(escritor, sheet_name=nome, index=False)
            logger.info(f"Backup do estoque salvo em {caminho}")
            return caminho
        except Exception as e:
            logger.error(f"Falha no backup do estoque antes do reset: {e}", exc_info=True)
            return None

    # ===================================================================
    # == [MELHORIA UX] VÍNCULOS + AUDITORIA (uma janela só) ==============
    # ===================================================================
    FILTROS_PROBLEMA = [
        ('todos', 'Todos os vínculos'),
        ('qualquer', '❗ Precisa de atenção (duplicado, fator/custo suspeito, sem produto)'),
        ('duplicado', '🔁 Duplicados'),
        ('suspeito', '🔴 Fator suspeito'),
        ('custo_errado', '💸 Custo maior que a nota inteira'),
        ('sem_ean', '🏷️ Sem EAN'),
        ('sem_compras', '💤 Sem compras'),
        ('orfao', '⚠️ Sem produto / produto excluído'),
    ]

    # Só estes contam como "precisa de atenção". Sem EAN / sem compras são informativos
    # (muitos itens legítimos não têm código de barras, ex: frutas e frios vendidos por KG).
    PROBLEMAS_GRAVES = ('duplicado', 'suspeito', 'custo_errado', 'orfao')

    @staticmethod
    def problemas_do_vinculo(v):
        """Lista de chaves de problema de um vínculo (usada no filtro e na coluna 'Problemas')."""
        lista = []
        if v.get('Duplicado'): lista.append('duplicado')
        if v.get('Suspeito'): lista.append('suspeito')
        if v.get('CustoErrado'): lista.append('custo_errado')
        if v.get('SemEAN'): lista.append('sem_ean')
        if v.get('SemCompras'): lista.append('sem_compras')
        if v.get('Orfao') or v.get('SemProduto'): lista.append('orfao')
        return lista

    def abrir_tela_auditoria(self):
        """
        [MELHORIA UX] A Auditoria agora é a MESMA janela do Gerenciar Vínculos, já aberta
        mostrando só os cadastros com algum problema (duplicados, fator suspeito, sem EAN,
        sem compras, sem produto). Assim existe UM editor só, com as mesmas regras.
        """
        self.abrir_gestor_vinculos(modo_auditoria=True)

    def abrir_gestor_vinculos(self, produto_id=None, nome_produto=None, ao_salvar=None, modo_auditoria=False):
        """
        [MELHORIA UX] Vínculos e Auditoria de Cadastros (DE/PARA):
          - aberto a partir de um aviso, já vem FILTRADO no produto em questão;
          - filtro por PROBLEMA: duplicados, fator suspeito, sem EAN, sem compras, órfãos;
          - custo por unidade do estoque E custo da embalagem na nota, lado a lado;
          - busca sem acento, por várias palavras (fornecedor, XML, produto, EAN, código);
          - editor único: produto, fator (com prévia), EAN e NCM; corrigir o fator
            oferece corrigir também as compras já importadas;
          - "🧹 Juntar duplicados": une vínculos repetidos sem perder nenhuma compra;
          - Enter salva; duplo clique vai para o fator; Delete exclui (se não tiver compras).
        ao_salvar: função chamada depois de cada alteração (ex: recalcular o Valor do Estoque).
        """
        popup = Toplevel(self.root)
        popup.title("Vínculos e Auditoria de Cadastros")
        popup.geometry("1320x740")
        popup.transient(self.root)
        estado = {'dados': {}, 'produto_id': produto_id}
        rotulos = dict(self.FILTROS_PROBLEMA)
        icones = {'duplicado': '🔁', 'suspeito': '🔴', 'custo_errado': '💸', 'sem_ean': '🏷️', 'sem_compras': '💤', 'orfao': '⚠️'}

        # ---------- Topo: filtros ----------
        frame_topo = ttk.Frame(popup, padding=(10, 10, 10, 0))
        frame_topo.pack(fill=tk.X)
        ttk.Label(frame_topo, text="🔍 Buscar:").pack(side=tk.LEFT)
        entry_filtro = ttk.Entry(frame_topo, width=34)
        entry_filtro.pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_topo, text="Mostrar:").pack(side=tk.LEFT, padx=(10, 3))
        combo_problema = ttk.Combobox(frame_topo, state="readonly", width=34)
        combo_problema.pack(side=tk.LEFT)
        btn_juntar = ttk.Button(frame_topo, text="🧹 Juntar duplicados", command=lambda: self.abrir_juntar_duplicados(popup, ao_mudar=recarregar_tudo))
        btn_juntar.pack(side=tk.LEFT, padx=10)
        lbl_contador = ttk.Label(frame_topo, text="", foreground="gray")
        lbl_contador.pack(side=tk.RIGHT)

        frame_produto = ttk.Frame(popup, padding=(10, 4, 10, 0))
        frame_produto.pack(fill=tk.X)
        lbl_produto = ttk.Label(frame_produto, text="", font=("Arial", 10, "bold"), foreground="#0056b3")
        lbl_produto.pack(side=tk.LEFT)
        btn_todos = ttk.Button(frame_produto, text="Mostrar todos os vínculos", command=lambda: mostrar_todos())

        # ---------- Lista ----------
        frame_lista = ttk.Frame(popup, padding="10")
        frame_lista.pack(fill=tk.BOTH, expand=True)
        cols = ('ID', 'Fornecedor', 'Descrição no XML', 'Produto Mestre', 'EAN', 'Qtd/Cx',
                'Custo/Unid.', 'Custo Emb.', 'Compras', 'Última compra', 'Problemas')
        titulos = {'Produto Mestre': 'Produto Mestre (Seu Estoque)', 'Custo/Unid.': 'Custo/Unid. estoque',
                   'Custo Emb.': 'Custo embalagem'}
        tree_vinculos = criar_tree_zebrada(frame_lista, columns=cols, show='headings', selectmode='browse')
        for col, larg, anc in (('ID', 50, 'center'), ('Fornecedor', 160, 'w'), ('Descrição no XML', 250, 'w'),
                               ('Produto Mestre', 230, 'w'), ('EAN', 110, 'center'), ('Qtd/Cx', 55, 'center'),
                               ('Custo/Unid.', 95, 'e'), ('Custo Emb.', 95, 'e'), ('Compras', 60, 'center'),
                               ('Última compra', 90, 'center'), ('Problemas', 80, 'center')):
            tree_vinculos.heading(col, text=titulos.get(col, col),
                                  command=lambda c=col: self.ordenar_coluna_treeview(tree_vinculos, c, False))
            tree_vinculos.column(col, width=larg, anchor=anc)
        tree_vinculos.tag_configure('orfao', background='#ffe3b3')
        tree_vinculos.tag_configure('duplicado', background='#ece4ff')
        tree_vinculos.tag_configure('suspeito', background='#ffd6d6')
        sb = ttk.Scrollbar(frame_lista, orient="vertical", command=tree_vinculos.yview)
        tree_vinculos.configure(yscrollcommand=sb.set)
        tree_vinculos.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Label(popup, foreground="gray", padding=(10, 0), text=(
            "🔴 vermelho = fator ou custo provavelmente errado (💸 = item mais caro que a nota inteira)   "
            "🔁 lilás = duplicado   ⚠️ laranja = sem produto   ·   Custo/Unid. = por unidade do SEU estoque; "
            "Custo embalagem = como veio na nota (Custo/Unid. × Qtd/Cx)")).pack(anchor="w")

        # ---------- Edição ----------
        frame_edit = ttk.LabelFrame(popup, text="Editar Vínculo Selecionado", padding="10")
        frame_edit.pack(fill=tk.X, padx=10, pady=10)
        frame_edit.columnconfigure(0, weight=1)
        lbl_selecionado = ttk.Label(frame_edit, text="Selecione um vínculo na lista.", font=("Arial", 10, "bold"))
        lbl_selecionado.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

        ttk.Label(frame_edit, text="Produto Mestre (digite para buscar):").grid(row=1, column=0, sticky="w")
        frame_mestre = ttk.Frame(frame_edit)
        frame_mestre.grid(row=2, column=0, sticky="ew", padx=(0, 10))
        frame_mestre.columnconfigure(1, weight=1)
        entry_busca_mestre = ttk.Entry(frame_mestre, width=16)
        entry_busca_mestre.grid(row=0, column=0, sticky="w", padx=(0, 5))
        combo_mestre_edit = ttk.Combobox(frame_mestre, values=self.lista_mestre_produtos_nomes, state="readonly")
        combo_mestre_edit.grid(row=0, column=1, sticky="ew")

        ttk.Label(frame_edit, text="Qtd/Cx (Fator):").grid(row=1, column=1, sticky="w")
        entry_fator_edit = ttk.Entry(frame_edit, width=8)
        entry_fator_edit.grid(row=2, column=1, sticky="w", padx=(0, 10))
        ttk.Label(frame_edit, text="EAN (código de barras):").grid(row=1, column=2, sticky="w")
        entry_ean_edit = ttk.Entry(frame_edit, width=16)
        entry_ean_edit.grid(row=2, column=2, sticky="w", padx=(0, 10))
        ttk.Label(frame_edit, text="NCM:").grid(row=1, column=3, sticky="w")
        entry_ncm_edit = ttk.Entry(frame_edit, width=10)
        entry_ncm_edit.grid(row=2, column=3, sticky="w", padx=(0, 10))

        lbl_previa = ttk.Label(frame_edit, text="", foreground="#0056b3")
        lbl_previa.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))

        # ---------- Funções ----------
        def carregar_dados():
            try:
                lista = database.listar_vinculos_com_resumo()
            except Exception as e:
                logger.error(f"Erro ao carregar vínculos: {e}", exc_info=True)
                messagebox.showerror("Erro de Carregamento", f"Falha ao ler os vínculos: {e}", parent=popup)
                lista = []
            estado['dados'] = {str(v['ID']): v for v in lista}
            # Opções do filtro com a quantidade de cada problema
            contagem = {chave: 0 for chave, _ in self.FILTROS_PROBLEMA}
            for v in lista:
                probs = self.problemas_do_vinculo(v)
                contagem['todos'] += 1
                contagem['qualquer'] += 1 if any(p in self.PROBLEMAS_GRAVES for p in probs) else 0
                for p in probs:
                    contagem[p] += 1
            estado['opcoes'] = {f"{rot} ({contagem[ch]})": ch for ch, rot in self.FILTROS_PROBLEMA}
            atual = estado.get('filtro_problema', 'qualquer' if modo_auditoria else 'todos')
            combo_problema['values'] = list(estado['opcoes'])
            combo_problema.set(next(k for k, ch in estado['opcoes'].items() if ch == atual))
            grupos = len({v['Grupo'] for v in lista if v.get('Grupo')})
            btn_juntar.config(text=f"🧹 Juntar duplicados ({grupos} grupo(s))")
            btn_juntar.state(['!disabled'] if grupos else ['disabled'])

        def mostrar(manter=None):
            manter = manter or tree_vinculos.focus()
            for i in tree_vinculos.get_children():
                tree_vinculos.delete(i)
            palavras = sem_acento(entry_filtro.get()).split()
            filtro_prob = estado['opcoes'].get(combo_problema.get(), 'todos') if estado.get('opcoes') else 'todos'
            estado['filtro_problema'] = filtro_prob
            n = 0
            for iid, v in estado['dados'].items():
                if estado['produto_id'] is not None and v['ProdutoID'] != estado['produto_id']:
                    continue
                probs = self.problemas_do_vinculo(v)
                if filtro_prob == 'qualquer' and not any(p in self.PROBLEMAS_GRAVES for p in probs):
                    continue
                if filtro_prob not in ('todos', 'qualquer') and filtro_prob not in probs:
                    continue
                texto = sem_acento(f"{v['Fornecedor']} {v['DescricaoXML']} {v['NomeMestre']} {v['EAN']} {v.get('Codigo', '')} {v['ID']}")
                if palavras and not all(p in texto for p in palavras):
                    continue
                tem_compra = v['UltimoCustoUnid'] is not None
                custo = fmt_reais(v['UltimoCustoUnid']) if tem_compra else "—"
                custo_emb = fmt_reais(v['UltimoCustoUnid'] * v['Fator']) if tem_compra else "—"
                data = v['UltimaData'].strftime('%d/%m/%Y') if v['UltimaData'] else "—"
                tag = ('suspeito',) if ('suspeito' in probs or 'custo_errado' in probs) else ('orfao',) if 'orfao' in probs else ('duplicado',) if 'duplicado' in probs else ()
                grupo_txt = f"{icones['duplicado']}{v['Grupo']}" if v.get('Grupo') else ''
                probs_txt = " ".join(icones[p] if p != 'duplicado' else grupo_txt for p in probs)
                tree_vinculos.insert("", "end", iid=iid, tags=tag, values=(
                    v['ID'], v['Fornecedor'], v['DescricaoXML'], v['NomeMestre'], v['EAN'], fmt_qtd(v['Fator']),
                    custo, custo_emb, v['QtdCompras'], data, probs_txt))
                n += 1
            lbl_contador.config(text=f"{n} de {len(estado['dados'])} vínculo(s) na lista")
            if manter and tree_vinculos.exists(manter):
                tree_vinculos.focus(manter); tree_vinculos.selection_set(manter); tree_vinculos.see(manter)
            elif n == 1:
                unico = tree_vinculos.get_children()[0]
                tree_vinculos.focus(unico); tree_vinculos.selection_set(unico)

        def recarregar_tudo():
            carregar_dados(); mostrar(); preencher_edicao()
            if ao_salvar:
                try:
                    ao_salvar()
                except Exception as e:
                    logger.warning(f"Falha ao atualizar a janela de origem: {e}")

        def mostrar_todos():
            estado['produto_id'] = None
            lbl_produto.config(text="")
            btn_todos.pack_forget()
            mostrar()

        def selecionado_atual():
            sel = tree_vinculos.focus()
            return (sel, estado['dados'].get(sel)) if sel else (None, None)

        def atualizar_previa(event=None):
            sel, v = selecionado_atual()
            if not v:
                lbl_previa.config(text=""); return
            try:
                novo = para_decimal(entry_fator_edit.get(), "Fator", permitir_zero=False)
            except ValueError:
                lbl_previa.config(text="⚠️ Digite um número maior que zero no Qtd/Cx (ex: 12).", foreground="#c62828"); return
            if not v['UltimoCustoUnid']:
                lbl_previa.config(text="Ainda não há compras por este vínculo: o fator vale para as próximas notas.",
                                  foreground="gray"); return
            custo_embalagem = v['UltimoCustoUnid'] * v['Fator']
            embalagens = v['UltimaQtd'] / v['Fator'] if v['UltimaQtd'] else Decimal('0')
            unidade = self.unidade_do_produto(v.get('ProdutoID'))
            texto = (f"Última compra: {fmt_qtd(embalagens)} embalagem(ns) de {fmt_reais(custo_embalagem)} (custo na nota).  "
                     f"Com Qtd/Cx {fmt_qtd(novo)} → {fmt_qtd(embalagens * novo)} {unidade} a "
                     f"{fmt_reais(custo_embalagem / novo)} cada (custo por unidade do estoque).")
            ref = v.get('CustoReferencia')
            if ref:
                texto += f"  Normal deste produto: ~{fmt_reais(ref)} por {unidade}."
            if v.get('CustoErrado'):
                texto = ("💸 Uma compra deste vínculo custa MAIS QUE A NOTA INTEIRA: o PREÇO foi gravado errado "
                         "(o Qtd/Cx não é o problema). Clique em '🧾 Compras / corrigir custo'.\n") + texto
                lbl_previa.config(text=texto, foreground="#c62828"); return
            lbl_previa.config(text=texto, foreground="#0056b3")

        def preencher_edicao(event=None):
            sel, v = selecionado_atual()
            if not v:
                # [DEPURAÇÃO 2] nada selecionado (ex: vínculo excluído): o editor não fica com o antigo
                lbl_selecionado.config(text="Selecione um vínculo na lista.")
                for campo in (entry_fator_edit, entry_ean_edit, entry_ncm_edit, entry_busca_mestre):
                    campo.delete(0, tk.END)
                combo_mestre_edit.set("")
                lbl_previa.config(text="")
                return
            codigo = f"  •  cód. fornecedor {v['Codigo']}" if v.get('Codigo') else ""
            lbl_selecionado.config(text=f"ID {v['ID']}  •  {v['Fornecedor']}  •  {v['DescricaoXML']}{codigo}")
            # [DEPURAÇÃO] só aceita o nome EXATO do mestre (antes "Sal" virava "Bacon Salgado")
            prefixo = f"{v['NomeMestre']} (ID: "
            candidatos = [n for n in self.lista_mestre_produtos_nomes if n.startswith(prefixo)]
            if v['ProdutoID'] is not None:
                exato = f"{v['NomeMestre']} (ID: {v['ProdutoID']})"
                candidatos = [exato] if exato in self.lista_mestre_produtos_nomes else candidatos
            combo_mestre_edit['values'] = self.lista_mestre_produtos_nomes
            combo_mestre_edit.set(candidatos[0] if len(candidatos) == 1 else "")
            entry_busca_mestre.delete(0, tk.END)
            for campo, valor in ((entry_fator_edit, fmt_qtd(v['Fator'])), (entry_ean_edit, v['EAN']), (entry_ncm_edit, v.get('NCM', ''))):
                campo.delete(0, tk.END); campo.insert(0, valor)
            atualizar_previa()

        def filtrar_mestre(event=None):
            if event is not None and getattr(event, 'keysym', '') in ('Return', 'Tab', 'Up', 'Down'):
                return
            achados = buscar_nomes(entry_busca_mestre.get(), self.lista_mestre_produtos_nomes)
            combo_mestre_edit['values'] = achados
            if achados and entry_busca_mestre.get().strip():
                combo_mestre_edit.set(achados[0])

        def salvar_alteracao(event=None):
            sel, v = selecionado_atual()
            if not v:
                messagebox.showwarning("Aviso", "Selecione um vínculo na lista.", parent=popup)
                return
            novo_mestre_nome = combo_mestre_edit.get()
            novo_mestre_id = self.mapa_produtos_mestre.get(novo_mestre_nome)
            if not novo_mestre_id:
                messagebox.showerror("Erro", "Selecione um Produto Mestre válido.", parent=popup)
                return
            try:
                novo_fator = para_decimal(entry_fator_edit.get(), "Fator", permitir_zero=False)
            except ValueError:
                messagebox.showerror("Erro", "Qtd/Cx (fator) inválido. Use um número maior que 0.", parent=popup)
                return
            novo_ean = entry_ean_edit.get().strip()
            novo_ncm = entry_ncm_edit.get().strip()

            recalcular = False
            if novo_fator != v['Fator'] and v['QtdCompras'] > 0:
                fator_antigo, previa = database.previa_recalculo_vinculo(v['ID'], novo_fator)
                exemplos = "\n".join(
                    f"  • NF {p['NF']} ({p['Data'].strftime('%d/%m/%Y') if p['Data'] else '?'}): "
                    f"{fmt_qtd(p['QtdAtual'])} a {fmt_reais(p['CustoAtual'])}  →  "
                    f"{fmt_qtd(p['QtdNova'])} a {fmt_reais(p['CustoNovo'])}" for p in previa[:5])
                mais = f"\n  ... e mais {len(previa) - 5}" if len(previa) > 5 else ""
                resposta = messagebox.askyesnocancel(
                    "Corrigir também as compras já importadas?",
                    f"O Qtd/Cx vai mudar de {fmt_qtd(fator_antigo)} para {fmt_qtd(novo_fator)}.\n\n"
                    f"Existem {len(previa)} compra(s) já importada(s) com o fator antigo:\n{exemplos}{mais}\n\n"
                    "SIM = corrigir também essas compras (recomendado se o fator estava ERRADO;\n"
                    "         o valor total de cada nota não muda)\n"
                    "NÃO = mudar só para as PRÓXIMAS notas\n"
                    "CANCELAR = não salvar\n\n"
                    "Obs.: contagens com o valor do estoque já FECHADO não mudam.",
                    parent=popup)
                if resposta is None:
                    return
                recalcular = bool(resposta)

            if database.atualizar_vinculo_existente(v['ID'], novo_mestre_id, novo_fator, recalcular_compras=recalcular,
                                                    novo_ean=novo_ean, novo_ncm=novo_ncm):
                extra = " e compras antigas corrigidas" if recalcular else ""
                self.status(f"Vínculo '{v['DescricaoXML']}' salvo (Qtd/Cx {fmt_qtd(novo_fator)}{extra}).")
                carregar_dados(); mostrar(manter=sel); preencher_edicao()
                if ao_salvar:
                    try:
                        ao_salvar()
                    except Exception as e:
                        logger.warning(f"Falha ao atualizar a janela de origem após salvar vínculo: {e}")
            else:
                messagebox.showerror("Erro", "Falha ao atualizar (veja o log).", parent=popup)
            return "break"

        def excluir_vinculo():
            sel, v = selecionado_atual()
            if not v:
                return
            # [DEPURAÇÃO 2] conta também o custo manual (nota de quantidade 0): excluir o vínculo dele
            # apagava o custo do produto
            itens = getattr(database, 'vinculo_tem_itens', lambda _id: None)(v['ID'])
            if v['QtdCompras'] == 0 and itens:
                messagebox.showwarning("Não é possível excluir",
                                       f"'{v['DescricaoXML']}' guarda o CUSTO MANUAL do produto (cadastrado no Catálogo).\n\n"
                                       "Excluir apagaria esse custo.", parent=popup)
                return
            if v['QtdCompras'] > 0:
                dica = ("Se for um DUPLICADO, use '🧹 Juntar duplicados'." if v.get('Grupo')
                        else "Se o produto está errado, troque o Produto Mestre e clique em 'Salvar Alterações'.")
                messagebox.showwarning(
                    "Não é possível excluir",
                    f"'{v['DescricaoXML']}' já tem {v['QtdCompras']} compra(s) registrada(s).\n\n"
                    f"Excluir apagaria a ligação dessas compras com o estoque.\n{dica}",
                    parent=popup)
                return
            if messagebox.askyesno("Excluir", f"Deseja excluir o vínculo para '{v['DescricaoXML']}'?\n\n"
                                   "Na próxima importação, o sistema pedirá para vincular novamente.", parent=popup):
                if database.excluir_vinculo_existente(v['ID']):
                    self.status(f"Vínculo '{v['DescricaoXML']}' excluído.", 'info')
                    recarregar_tudo()   # [DEPURAÇÃO 2] atualiza também o editor e a janela de origem
                else:
                    messagebox.showerror("Erro", "Falha ao excluir (o vínculo pode ter compras; veja o log).", parent=popup)

        def ir_para_fator(event=None):
            entry_fator_edit.focus_set(); entry_fator_edit.select_range(0, tk.END)

        entry_filtro.bind("<KeyRelease>", lambda e: mostrar())
        combo_problema.bind("<<ComboboxSelected>>", lambda e: mostrar())
        entry_busca_mestre.bind("<KeyRelease>", filtrar_mestre)
        entry_fator_edit.bind("<KeyRelease>", atualizar_previa)
        for campo in (entry_fator_edit, entry_ean_edit, entry_ncm_edit):
            campo.bind("<Return>", salvar_alteracao)
        tree_vinculos.bind("<<TreeviewSelect>>", preencher_edicao)
        tree_vinculos.bind("<Double-1>", ir_para_fator)
        tree_vinculos.bind("<Delete>", lambda e: excluir_vinculo())

        btn_salvar = ttk.Button(frame_edit, text="💾 Salvar Alterações", command=salvar_alteracao)
        btn_salvar.grid(row=2, column=4, padx=10)
        btn_excluir = ttk.Button(frame_edit, text="🗑️ Excluir Vínculo", command=excluir_vinculo)
        btn_excluir.grid(row=2, column=5, padx=(0, 5))

        def abrir_compras():
            sel, v = selecionado_atual()
            if not v:
                messagebox.showwarning("Aviso", "Selecione um vínculo na lista.", parent=popup)
                return
            if not v['QtdCompras']:
                messagebox.showinfo("Sem compras", "Este vínculo ainda não tem compras registradas.", parent=popup)
                return
            def depois():
                carregar_dados(); mostrar(manter=sel); preencher_edicao()
                if ao_salvar:
                    try:
                        ao_salvar()
                    except Exception as e:
                        logger.warning(f"Falha ao atualizar a janela de origem após corrigir custo: {e}")
            self.abrir_compras_do_vinculo(v, popup, ao_mudar=depois)

        # [MELHORIA] ver as compras do vínculo e corrigir um PREÇO gravado errado
        btn_compras = ttk.Button(frame_edit, text="🧾 Compras / corrigir custo", command=abrir_compras)
        btn_compras.grid(row=0, column=4, columnspan=2, sticky="e", padx=(0, 5))

        if produto_id is not None:
            lbl_produto.config(text=f"Mostrando só os vínculos de: {nome_produto or produto_id}")
            btn_todos.pack(side=tk.LEFT, padx=10)
            estado['filtro_problema'] = 'todos'
        carregar_dados()
        mostrar()
        entry_filtro.focus_set()
        self._janela_vinculos = {'popup': popup, 'tree': tree_vinculos, 'filtro': entry_filtro,
                                 'fator': entry_fator_edit, 'ean': entry_ean_edit, 'ncm': entry_ncm_edit,
                                 'combo': combo_mestre_edit, 'busca_mestre': entry_busca_mestre,
                                 'previa': lbl_previa, 'salvar': salvar_alteracao, 'excluir': excluir_vinculo,
                                 'problema': combo_problema, 'opcoes': lambda: estado['opcoes'],
                                 'mostrar': mostrar, 'mostrar_todos': mostrar_todos,
                                 'contador': lbl_contador, 'btn_juntar': btn_juntar, 'compras': abrir_compras}

    def abrir_compras_do_vinculo(self, v, janela_pai=None, ao_mudar=None):
        """
        [MELHORIA] Mostra todas as compras de um vínculo (nota, data, embalagens, preço da
        embalagem, total do item x total da nota) e deixa corrigir o PREÇO de uma compra
        gravado errado (ex: R$ 840.000,00 no lugar de R$ 84,00). A quantidade não muda.
        O usuário digita o preço da EMBALAGEM como está no DANFE (papel da nota).
        """
        pai = janela_pai or self.root
        popup = Toplevel(pai)
        popup.title(f"🧾 Compras de: {v['DescricaoXML']}")
        popup.geometry("1050x520")
        popup.transient(pai)
        fator = v['Fator'] if v['Fator'] and v['Fator'] > 0 else Decimal('1')

        def fator_de(c):
            """[DEPURAÇÃO 2] Qtd/Cx com que ESTA compra foi importada (antes usava o Qtd/Cx atual
            do vínculo para todas: depois de trocar o Qtd/Cx, as embalagens e o preço ficavam errados)."""
            f = c.get('Fator')
            return f if f and f > 0 else fator
        unidade = self.unidade_do_produto(v.get('ProdutoID'))
        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, font=("Arial", 10, "bold"), text=(
            f"{v['Fornecedor']}  •  {v['DescricaoXML']}  →  {v['NomeMestre']}  (Qtd/Cx {fmt_qtd(fator)})")).pack(anchor="w")
        ttk.Label(frame, foreground="gray", text=(
            "Selecione a compra com o preço errado, digite o preço CERTO de UMA embalagem (como está no DANFE) e clique em Corrigir. "
            "Só o preço muda; a quantidade fica igual.")).pack(anchor="w", pady=(0, 6))

        cols = ('NF', 'Data', 'Embalagens', 'Preço embalagem', f'Qtd ({unidade})', f'Custo/{unidade}',
                'Total do item', 'Total da nota', 'Alerta')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings', selectmode='browse')
        for col, larg, anc in zip(cols, (70, 90, 85, 120, 85, 110, 120, 120, 200),
                                  ('center', 'center', 'center', 'e', 'center', 'e', 'e', 'e', 'w')):
            tree.heading(col, text=col); tree.column(col, width=larg, anchor=anc)
        tree.tag_configure('errado', background='#ffd6d6')
        tree.pack(fill=tk.BOTH, expand=True)

        frame_corr = ttk.LabelFrame(popup, text="Corrigir o preço da compra selecionada", padding=10)
        frame_corr.pack(fill=tk.X, padx=10, pady=(0, 10))
        lbl_sel = ttk.Label(frame_corr, text="Selecione uma compra na lista.", font=("Arial", 10, "bold"))
        lbl_sel.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(frame_corr, text="Preço CERTO de 1 embalagem (R$):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        entry_preco = ttk.Entry(frame_corr, width=14)
        entry_preco.grid(row=1, column=1, sticky="w", padx=5, pady=(6, 0))
        lbl_sugestao = ttk.Label(frame_corr, text="", foreground="#0056b3")
        lbl_sugestao.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        estado = {'compras': {}}

        def carregar(manter=None):
            for i in tree.get_children():
                tree.delete(i)
            estado['compras'] = {}
            for c in database.listar_compras_do_vinculo(v['ID']):
                iid = str(c['ItemNotaID'])
                estado['compras'][iid] = c
                embalagens = c['Quantidade'] / fator_de(c)
                alerta = "💸 Mais caro que a nota inteira!" if c['MaiorQueNota'] else ""
                tree.insert("", "end", iid=iid, tags=('errado',) if c['MaiorQueNota'] else (), values=(
                    c['NF'], c['Data'].strftime('%d/%m/%Y') if c['Data'] else "—", fmt_qtd(embalagens),
                    fmt_reais(c['Custo'] * fator_de(c)), fmt_qtd(c['Quantidade']), fmt_reais(c['Custo']),
                    fmt_reais(c['TotalItem']), fmt_reais(c['TotalNota']) if c['TotalNota'] > 0 else "—", alerta))
            filhos = tree.get_children()
            alvo = manter if manter and tree.exists(manter) else next(
                (i for i in filhos if estado['compras'][i]['MaiorQueNota']), filhos[0] if filhos else None)
            if alvo:
                tree.focus(alvo); tree.selection_set(alvo); tree.see(alvo)
            preencher()

        def preencher(event=None):
            sel = tree.focus()
            c = estado['compras'].get(sel)
            entry_preco.delete(0, tk.END)
            if not c:
                lbl_sel.config(text="Selecione uma compra na lista."); lbl_sugestao.config(text=""); return
            embalagens = c['Quantidade'] / fator_de(c)
            lbl_sel.config(text=(f"NF {c['NF']} de {c['Data'].strftime('%d/%m/%Y') if c['Data'] else '?'}: "
                                 f"{fmt_qtd(embalagens)} embalagem(ns) a {fmt_reais(c['Custo'] * fator_de(c))} cada "
                                 f"(total do item {fmt_reais(c['TotalItem'])})"))
            texto = ""
            if c['TotalNota'] > 0 and embalagens > 0:
                sobra = c['TotalNota'] - c['SomaOutrosItens']
                if sobra > 0:
                    sugestao = (sobra / embalagens).quantize(Decimal('0.01'))
                    texto = (f"💡 Pelo total da nota ({fmt_reais(c['TotalNota'])}) menos os outros itens "
                             f"({fmt_reais(c['SomaOutrosItens'])}), sobram {fmt_reais(sobra)} para este item = "
                             f"~{fmt_reais(sugestao)} por embalagem (pode incluir frete/ST). Confira no DANFE.")
                    if c['MaiorQueNota']:
                        entry_preco.insert(0, fmt_reais(sugestao).replace('R$', '').strip())
            lbl_sugestao.config(text=texto)

        def corrigir(event=None):
            sel = tree.focus()
            c = estado['compras'].get(sel)
            if not c:
                messagebox.showwarning("Aviso", "Selecione a compra que quer corrigir.", parent=popup)
                return
            try:
                preco_emb = para_decimal(entry_preco.get(), "Preço da embalagem", permitir_zero=False)
            except ValueError as e:
                messagebox.showerror("Valor inválido", str(e), parent=popup)
                return
            novo_custo = (preco_emb / fator_de(c)).quantize(Decimal('0.0001'))
            embalagens = c['Quantidade'] / fator_de(c)
            novo_total = c['Quantidade'] * novo_custo
            aviso = ""
            if c['TotalNota'] > 0 and novo_total > c['TotalNota'] * Decimal('1.05') + 1:
                aviso = (f"\n\n⚠️ ATENÇÃO: mesmo assim o item ({fmt_reais(novo_total)}) continua mais caro que a "
                         f"nota inteira ({fmt_reais(c['TotalNota'])}). Confira o valor digitado.")
            if not messagebox.askyesno("Corrigir preço", (
                    f"NF {c['NF']} — {v['DescricaoXML']}\n\n"
                    f"Preço da embalagem: {fmt_reais(c['Custo'] * fator_de(c))}  →  {fmt_reais(preco_emb)}\n"
                    f"Custo por {unidade}: {fmt_reais(c['Custo'])}  →  {fmt_reais(novo_custo)}\n"
                    f"Total do item: {fmt_reais(c['TotalItem'])}  →  {fmt_reais(novo_total)}\n"
                    f"A quantidade ({fmt_qtd(embalagens)} emb. = {fmt_qtd(c['Quantidade'])} {unidade}) não muda.\n\n"
                    f"Contagens com o valor do estoque já FECHADO não mudam.{aviso}\n\nConfirmar?"), parent=popup):
                return
            ok, msg = database.atualizar_custos_itens([(c['ItemNotaID'], novo_custo)])
            if not ok:
                messagebox.showerror("Erro", msg, parent=popup)
                return
            self.status(f"Preço corrigido: NF {c['NF']} • {v['DescricaoXML']} → {fmt_reais(preco_emb)} por embalagem.")
            carregar(manter=sel)
            if ao_mudar:
                try:
                    ao_mudar()
                except Exception as e:
                    logger.warning(f"Falha ao atualizar a janela de vínculos: {e}")
            messagebox.showinfo("Pronto", "Preço corrigido! 👍\n\nSe houver contagem em aberto no '💰 Valor do Estoque', "
                                "clique em '🔄 Recalcular' para ver o efeito.", parent=popup)

        btn_corrigir = ttk.Button(frame_corr, text="💾 Corrigir preço", command=corrigir)
        btn_corrigir.grid(row=1, column=2, padx=10, pady=(6, 0))
        ttk.Button(frame_corr, text="Fechar", command=popup.destroy).grid(row=1, column=3, pady=(6, 0))
        tree.bind("<<TreeviewSelect>>", preencher)
        entry_preco.bind("<Return>", corrigir)
        carregar()
        entry_preco.focus_set()
        self._janela_compras = {'popup': popup, 'tree': tree, 'preco': entry_preco, 'corrigir': corrigir,
                                'sugestao': lbl_sugestao, 'selecionado': lbl_sel}

    def abrir_juntar_duplicados(self, janela_pai=None, ao_mudar=None):
        """
        [MELHORIA UX] Junta vínculos duplicados (mesmo fornecedor + mesmo produto + mesmo
        código do fornecedor ou EAN). As compras passam para o vínculo mantido; nenhuma
        quantidade ou custo muda. Grupos com Qtd/Cx diferentes precisam de revisão.
        """
        pai = janela_pai or self.root
        popup = Toplevel(pai)
        popup.title("🧹 Juntar vínculos duplicados")
        popup.geometry("1050x560")
        popup.transient(pai)
        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        lbl_resumo = ttk.Label(frame, text="", font=("Arial", 10, "bold"))
        lbl_resumo.pack(anchor="w")
        ttk.Label(frame, foreground="gray", text=(
            "Cada grupo é o MESMO item do MESMO fornecedor, cadastrado várias vezes (a descrição mudou de uma nota para outra). "
            "Juntar mantém a linha marcada como MANTER e passa para ela todas as compras das outras.")).pack(anchor="w", pady=(0, 6))

        cols = ('Ação', 'ID', 'Descrição no XML', 'EAN', 'Qtd/Cx', 'Custo/Unid.', 'Compras', 'Última compra')
        tree = criar_tree_zebrada(frame, columns=cols, show='headings', selectmode='browse')
        for col, larg, anc in (('Ação', 150, 'w'), ('ID', 60, 'center'), ('Descrição no XML', 360, 'w'), ('EAN', 120, 'center'),
                               ('Qtd/Cx', 60, 'center'), ('Custo/Unid.', 100, 'e'), ('Compras', 70, 'center'),
                               ('Última compra', 100, 'center')):
            tree.heading(col, text=col); tree.column(col, width=larg, anchor=anc)
        tree.tag_configure('grupo', background='#dfe8f5')
        tree.tag_configure('manter', foreground='#1b7a2f')
        tree.tag_configure('fator_diferente', foreground='#c62828')
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        estado = {'grupos': {}, 'manter': {}}

        def carregar():
            for i in tree.get_children():
                tree.delete(i)
            try:
                grupos = database.listar_grupos_duplicados()
            except Exception as e:
                logger.error(f"Erro ao listar duplicados: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Falha ao listar duplicados:\n{e}", parent=popup)
                grupos = []
            estado['grupos'] = {g['Grupo']: g for g in grupos}
            for g in grupos:
                estado['manter'].setdefault(g['Grupo'], g['ManterID'])
                if estado['manter'][g['Grupo']] not in [v['ID'] for v in g['Vinculos']]:
                    estado['manter'][g['Grupo']] = g['ManterID']
                situacao = "✅ mesmo Qtd/Cx" if g['FatoresIguais'] else "⚠️ Qtd/Cx DIFERENTES - revise"
                tree.insert("", "end", iid=f"g{g['Grupo']}", tags=('grupo',), values=(
                    f"Grupo {g['Grupo']}", '', f"{g['Fornecedor']}  →  {g['NomeMestre']}", '', '', '',
                    f"{len(g['Vinculos'])} cadastros", situacao))
                for v in g['Vinculos']:
                    manter = v['ID'] == estado['manter'][g['Grupo']]
                    tags = ['manter'] if manter else []
                    if not g['FatoresIguais']:
                        tags.append('fator_diferente')
                    tree.insert("", "end", iid=f"v{v['ID']}", tags=tuple(tags), values=(
                        "✅ MANTER" if manter else "   juntar", v['ID'], v['DescricaoXML'], v['EAN'], fmt_qtd(v['Fator']),
                        fmt_reais(v['UltimoCustoUnid']) if v['UltimoCustoUnid'] is not None else '—', v['QtdCompras'],
                        v['UltimaData'].strftime('%d/%m/%Y') if v['UltimaData'] else '—'))
            iguais = sum(1 for g in grupos if g['FatoresIguais'])
            lbl_resumo.config(text=f"{len(grupos)} grupo(s) de duplicados · {iguais} com o mesmo Qtd/Cx (podem ser juntados de uma vez) · "
                                   f"{len(grupos) - iguais} para revisar")
            btn_todos.config(text=f"✅ Juntar os {iguais} grupo(s) com o mesmo Qtd/Cx")
            btn_todos.state(['!disabled'] if iguais else ['disabled'])

        def grupo_da_linha(iid):
            if iid.startswith('g'):
                return int(iid[1:]), None
            vid = int(iid[1:])
            for n, g in estado['grupos'].items():
                if any(v['ID'] == vid for v in g['Vinculos']):
                    return n, vid
            return None, None

        def definir_manter(event=None):
            sel = tree.focus()
            if not sel:
                return
            n, vid = grupo_da_linha(sel)
            if vid is None:
                return
            estado['manter'][n] = vid
            carregar()
            tree.focus(sel); tree.selection_set(sel)

        def juntar_grupo(n):
            g = estado['grupos'][n]
            manter = estado['manter'][n]
            outros = [v['ID'] for v in g['Vinculos'] if v['ID'] != manter]
            return database.juntar_vinculos(manter, outros)

        def juntar_selecionado():
            sel = tree.focus()
            if not sel:
                messagebox.showwarning("Aviso", "Clique numa linha do grupo que você quer juntar.", parent=popup)
                return
            n, _ = grupo_da_linha(sel)
            if n is None:
                return
            g = estado['grupos'][n]
            manter = next(v for v in g['Vinculos'] if v['ID'] == estado['manter'][n])
            aviso = ""
            if not g['FatoresIguais']:
                fatores = ", ".join(sorted({fmt_qtd(v['Fator']) for v in g['Vinculos']}))
                aviso = (f"\n\n⚠️ Os Qtd/Cx são diferentes ({fatores}). Depois de juntar, as PRÓXIMAS notas usarão "
                         f"o Qtd/Cx {fmt_qtd(manter['Fator'])} do vínculo mantido. As compras já gravadas não mudam.")
            if not messagebox.askyesno("Juntar grupo", f"Juntar os {len(g['Vinculos'])} cadastros do Grupo {n} no ID {manter['ID']} "
                                       f"('{manter['DescricaoXML']}')?{aviso}", parent=popup):
                return
            ok, msg = juntar_grupo(n)
            if ok:
                self.status(msg); carregar()
                if ao_mudar: ao_mudar()
            else:
                messagebox.showerror("Erro", msg, parent=popup)

        def juntar_todos_iguais():
            iguais = [n for n, g in estado['grupos'].items() if g['FatoresIguais']]
            if not iguais:
                return
            total = sum(len(estado['grupos'][n]['Vinculos']) - 1 for n in iguais)
            if not messagebox.askyesno("Juntar duplicados",
                                       f"Juntar {len(iguais)} grupo(s)? {total} cadastro(s) repetido(s) serão unidos "
                                       "ao cadastro marcado como MANTER de cada grupo.\n\n"
                                       "Nenhuma compra é perdida e nenhuma quantidade ou custo muda.", parent=popup):
                return
            ok_n, erros = 0, []
            for n in iguais:
                ok, msg = juntar_grupo(n)
                if ok:
                    ok_n += 1
                else:
                    erros.append(f"Grupo {n}: {msg}")
            self.status(f"{ok_n} grupo(s) de duplicados juntado(s).")
            if erros:
                messagebox.showwarning("Alguns grupos não foram juntados", "\n".join(erros[:10]), parent=popup)
            carregar()
            if ao_mudar: ao_mudar()

        tree.bind("<Double-1>", definir_manter)
        botoes = ttk.Frame(popup, padding=(10, 0, 10, 10))
        botoes.pack(fill=tk.X)
        ttk.Label(botoes, foreground="gray", text="Duplo clique numa linha = marcar como MANTER.").pack(side=tk.LEFT)
        btn_todos = ttk.Button(botoes, text="✅ Juntar grupos com o mesmo Qtd/Cx", command=juntar_todos_iguais)
        btn_todos.pack(side=tk.RIGHT, padx=5, ipady=3)
        ttk.Button(botoes, text="🔗 Juntar o grupo selecionado", command=juntar_selecionado).pack(side=tk.RIGHT, padx=5, ipady=3)
        carregar()
        self._janela_juntar = {'popup': popup, 'tree': tree, 'manter': estado['manter'], 'grupos': lambda: estado['grupos'],
                               'juntar_todos': juntar_todos_iguais, 'juntar_selecionado': juntar_selecionado,
                               'definir_manter': definir_manter, 'resumo': lbl_resumo}


    # ===================================================================
    # == [MELHORIA] ABA 8: CONSULTAS RÁPIDAS ============================
    # ===================================================================
    PERIODOS_CONSULTA = [('Últimos 90 dias', 90), ('Últimos 6 meses', 183), ('Últimos 12 meses', 365), ('Todo o histórico', None)]

    def _campo_busca_consultas(self):
        try:
            aba = self.nb_consultas.index(self.nb_consultas.select())
        except (tk.TclError, TypeError, ValueError):
            aba = 0
        return self.entry_busca_nota if aba == 1 else self.entry_busca_produto_consulta

    def criar_aba_consultas(self):
        """
        Duas consultas rápidas:
          📦 Produto: histórico de compras de um produto, comparação de preços entre
             fornecedores (o mais barato primeiro), menor/último preço e quantidades.
          🧾 Nota Fiscal: busca a nota (número, fornecedor ou um produto que veio nela)
             e mostra todos os itens.
        """
        self.nb_consultas = ttk.Notebook(self.frame_consultas)
        self.nb_consultas.pack(fill=tk.BOTH, expand=True)
        aba_prod = ttk.Frame(self.nb_consultas, padding=8)
        aba_nota = ttk.Frame(self.nb_consultas, padding=8)
        self.nb_consultas.add(aba_prod, text='📦 Produto: histórico de preços')
        self.nb_consultas.add(aba_nota, text='🧾 Nota Fiscal: itens da nota')
        self.cache_consulta_notas = []
        self.historico_consulta = []
        self.produto_consulta = None

        # ======================= PRODUTO =======================
        aba_prod.columnconfigure(1, weight=1)
        aba_prod.rowconfigure(0, weight=1)
        esquerda = ttk.LabelFrame(aba_prod, text="1. Escolha o produto", padding=6)
        esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        esquerda.rowconfigure(2, weight=1)
        ttk.Label(esquerda, text="Buscar (nome ou ID):").grid(row=0, column=0, sticky="w")
        self.entry_busca_produto_consulta = ttk.Entry(esquerda, width=34)
        self.entry_busca_produto_consulta.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.tree_consulta_produtos = criar_tree_zebrada(esquerda, columns=('Produto', 'UN'), show='headings',
                                                         selectmode='browse', height=20)
        self.tree_consulta_produtos.heading('Produto', text='Produto'); self.tree_consulta_produtos.column('Produto', width=250)
        self.tree_consulta_produtos.heading('UN', text='UN'); self.tree_consulta_produtos.column('UN', width=45, anchor='center')
        self.tree_consulta_produtos.grid(row=2, column=0, sticky="nsew")
        self.lbl_consulta_qtd_produtos = ttk.Label(esquerda, text="", foreground="gray")
        self.lbl_consulta_qtd_produtos.grid(row=3, column=0, sticky="w")

        direita = ttk.Frame(aba_prod)
        direita.grid(row=0, column=1, sticky="nsew")
        direita.columnconfigure(0, weight=1)
        direita.rowconfigure(3, weight=1)
        direita.rowconfigure(5, weight=2)

        topo = ttk.Frame(direita)
        topo.grid(row=0, column=0, sticky="ew")
        self.lbl_consulta_produto = ttk.Label(topo, text="Escolha um produto na lista à esquerda.",
                                              font=("Arial", 13, "bold"), foreground="#0056b3")
        self.lbl_consulta_produto.pack(side=tk.LEFT)
        ttk.Button(topo, text="💾 Exportar Excel", command=self.exportar_consulta_produto).pack(side=tk.RIGHT)
        self.combo_periodo_consulta = ttk.Combobox(topo, state="readonly", width=18,
                                                   values=[p for p, _ in self.PERIODOS_CONSULTA])
        self.combo_periodo_consulta.set('Últimos 12 meses')
        self.combo_periodo_consulta.pack(side=tk.RIGHT, padx=8)
        ttk.Label(topo, text="Período:").pack(side=tk.RIGHT)

        cartoes = ttk.Frame(direita)
        cartoes.grid(row=1, column=0, sticky="ew", pady=8)
        self.cartoes_consulta = {}
        for i, (chave, titulo) in enumerate((('ultimo', 'Último preço pago'), ('menor', 'Menor preço no período'),
                                             ('media', 'Média ponderada no período'), ('comprado', 'Comprado no período'))):
            cartoes.columnconfigure(i, weight=1)
            caixa = ttk.LabelFrame(cartoes, text=titulo, padding=6)
            caixa.grid(row=0, column=i, sticky="nsew", padx=3)
            valor = ttk.Label(caixa, text="—", font=("Arial", 14, "bold"))
            valor.pack(anchor="w")
            detalhe = ttk.Label(caixa, text="", foreground="gray")
            detalhe.pack(anchor="w")
            self.cartoes_consulta[chave] = (valor, detalhe)

        ttk.Label(direita, text="Comparação por fornecedor (o mais barato primeiro) — preços por unidade do seu estoque",
                  font=("Arial", 10, "bold")).grid(row=2, column=0, sticky="w")
        cols_f = ('Fornecedor', 'Compras', 'Qtd comprada', 'Média/unid.', 'Menor', 'Maior', 'Último', 'Última compra', 'vs. mais barato')
        self.tree_consulta_fornecedores = criar_tree_zebrada(direita, columns=cols_f, show='headings', selectmode='browse', height=5)
        for col, larg, anc in (('Fornecedor', 220, 'w'), ('Compras', 65, 'center'), ('Qtd comprada', 100, 'e'),
                               ('Média/unid.', 95, 'e'), ('Menor', 85, 'e'), ('Maior', 85, 'e'), ('Último', 85, 'e'),
                               ('Última compra', 95, 'center'), ('vs. mais barato', 100, 'center')):
            self.tree_consulta_fornecedores.heading(col, text=col)
            self.tree_consulta_fornecedores.column(col, width=larg, anchor=anc)
        self.tree_consulta_fornecedores.tag_configure('mais_barato', background='#d8f3dc')
        self.tree_consulta_fornecedores.grid(row=3, column=0, sticky="nsew")

        ttk.Label(direita, text="Histórico de compras (duplo clique abre a nota)", font=("Arial", 10, "bold")).grid(
            row=4, column=0, sticky="w", pady=(8, 0))
        frame_hist = ttk.Frame(direita)
        frame_hist.grid(row=5, column=0, sticky="nsew")
        frame_hist.columnconfigure(0, weight=1); frame_hist.rowconfigure(0, weight=1)
        cols_h = ('Data', 'NF', 'Fornecedor', 'Descrição na nota', 'Embalagens', 'Custo emb.', 'Qtd', 'Custo/unid.', 'Total')
        self.tree_consulta_historico = criar_tree_zebrada(frame_hist, columns=cols_h, show='headings', selectmode='browse')
        for col, larg, anc in (('Data', 85, 'center'), ('NF', 70, 'center'), ('Fornecedor', 170, 'w'),
                               ('Descrição na nota', 240, 'w'), ('Embalagens', 80, 'e'), ('Custo emb.', 90, 'e'),
                               ('Qtd', 70, 'e'), ('Custo/unid.', 90, 'e'), ('Total', 95, 'e')):
            self.tree_consulta_historico.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(self.tree_consulta_historico, c, False))
            self.tree_consulta_historico.column(col, width=larg, anchor=anc)
        self.tree_consulta_historico.tag_configure('menor', background='#d8f3dc')
        self.tree_consulta_historico.tag_configure('maior', background='#ffe0e0')
        sb_h = ttk.Scrollbar(frame_hist, orient="vertical", command=self.tree_consulta_historico.yview)
        self.tree_consulta_historico.configure(yscrollcommand=sb_h.set)
        self.tree_consulta_historico.grid(row=0, column=0, sticky="nsew"); sb_h.grid(row=0, column=1, sticky="ns")
        ttk.Label(direita, foreground="gray", text="🟩 verde = compra mais barata do período   🟥 vermelho = mais cara.  "
                  "Embalagens/Custo emb. = como veio na nota; Qtd/Custo/unid. = na unidade do seu estoque.").grid(row=6, column=0, sticky="w")

        self.entry_busca_produto_consulta.bind("<KeyRelease>", lambda e: self.listar_produtos_consulta())
        self.entry_busca_produto_consulta.bind("<Return>", lambda e: self._consulta_escolher_primeiro())
        self.tree_consulta_produtos.bind("<<TreeviewSelect>>", lambda e: self.mostrar_consulta_produto())
        self.combo_periodo_consulta.bind("<<ComboboxSelected>>", lambda e: self.mostrar_consulta_produto(recarregar=False))
        self.tree_consulta_historico.bind("<Double-1>", lambda e: self._consulta_abrir_nota_do_historico())

        # ======================= NOTA FISCAL =======================
        aba_nota.columnconfigure(0, weight=1)
        aba_nota.rowconfigure(1, weight=1)
        aba_nota.rowconfigure(3, weight=1)
        filtros = ttk.Frame(aba_nota)
        filtros.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(filtros, text="🔍 Buscar (número da nota, fornecedor ou um produto que veio na nota):").pack(side=tk.LEFT)
        self.entry_busca_nota = ttk.Entry(filtros, width=36)
        self.entry_busca_nota.pack(side=tk.LEFT, padx=5)
        ttk.Label(filtros, text="Período:").pack(side=tk.LEFT, padx=(10, 3))
        self.combo_periodo_nota = ttk.Combobox(filtros, state="readonly", width=16,
                                               values=['Últimos 30 dias'] + [p for p, _ in self.PERIODOS_CONSULTA])
        self.combo_periodo_nota.set('Todo o histórico')
        self.combo_periodo_nota.pack(side=tk.LEFT)
        self.lbl_consulta_qtd_notas = ttk.Label(filtros, text="", foreground="gray")
        self.lbl_consulta_qtd_notas.pack(side=tk.RIGHT)

        frame_notas = ttk.Frame(aba_nota)
        frame_notas.grid(row=1, column=0, sticky="nsew")
        frame_notas.columnconfigure(0, weight=1); frame_notas.rowconfigure(0, weight=1)
        cols_n = ('Data', 'Número', 'Fornecedor', 'Itens', 'Valor da nota')
        self.tree_consulta_notas = criar_tree_zebrada(frame_notas, columns=cols_n, show='headings', selectmode='browse', height=9)
        for col, larg, anc in (('Data', 90, 'center'), ('Número', 90, 'center'), ('Fornecedor', 380, 'w'),
                               ('Itens', 60, 'center'), ('Valor da nota', 120, 'e')):
            self.tree_consulta_notas.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(self.tree_consulta_notas, c, False))
            self.tree_consulta_notas.column(col, width=larg, anchor=anc)
        sb_n = ttk.Scrollbar(frame_notas, orient="vertical", command=self.tree_consulta_notas.yview)
        self.tree_consulta_notas.configure(yscrollcommand=sb_n.set)
        self.tree_consulta_notas.grid(row=0, column=0, sticky="nsew"); sb_n.grid(row=0, column=1, sticky="ns")

        self.lbl_consulta_nota = ttk.Label(aba_nota, text="Itens da nota selecionada (duplo clique num item mostra o histórico de preços do produto)",
                                           font=("Arial", 10, "bold"))
        self.lbl_consulta_nota.grid(row=2, column=0, sticky="w", pady=(8, 0))
        frame_itens = ttk.Frame(aba_nota)
        frame_itens.grid(row=3, column=0, sticky="nsew")
        frame_itens.columnconfigure(0, weight=1); frame_itens.rowconfigure(0, weight=1)
        cols_i = ('Produto do estoque', 'Descrição na nota', 'Embalagens', 'Qtd/Cx', 'Custo emb.', 'Qtd', 'UN', 'Custo/unid.', 'Total')
        self.tree_consulta_itens = criar_tree_zebrada(frame_itens, columns=cols_i, show='headings', selectmode='browse')
        for col, larg, anc in (('Produto do estoque', 230, 'w'), ('Descrição na nota', 250, 'w'), ('Embalagens', 80, 'e'),
                               ('Qtd/Cx', 60, 'center'), ('Custo emb.', 90, 'e'), ('Qtd', 70, 'e'), ('UN', 40, 'center'),
                               ('Custo/unid.', 90, 'e'), ('Total', 95, 'e')):
            self.tree_consulta_itens.heading(col, text=col, command=lambda c=col: self.ordenar_coluna_treeview(self.tree_consulta_itens, c, False))
            self.tree_consulta_itens.column(col, width=larg, anchor=anc)
        self.tree_consulta_itens.tag_configure('achado', background='#fff4cc')
        sb_i = ttk.Scrollbar(frame_itens, orient="vertical", command=self.tree_consulta_itens.yview)
        self.tree_consulta_itens.configure(yscrollcommand=sb_i.set)
        self.tree_consulta_itens.grid(row=0, column=0, sticky="nsew"); sb_i.grid(row=0, column=1, sticky="ns")
        self.lbl_consulta_total_nota = ttk.Label(aba_nota, text="", font=("Arial", 11, "bold"), foreground="green")
        self.lbl_consulta_total_nota.grid(row=4, column=0, sticky="e", pady=(4, 0))

        self.entry_busca_nota.bind("<KeyRelease>", lambda e: self.listar_notas_consulta())
        self.combo_periodo_nota.bind("<<ComboboxSelected>>", lambda e: self.listar_notas_consulta())
        self.tree_consulta_notas.bind("<<TreeviewSelect>>", lambda e: self.mostrar_itens_nota_consulta())
        self.tree_consulta_itens.bind("<Double-1>", lambda e: self._consulta_ir_para_produto_do_item())

    # -------------------------- dados --------------------------
    def atualizar_consultas(self):
        try:
            self.cache_consulta_notas = database.listar_notas_para_consulta() or []
        except Exception as e:
            logger.error(f"Erro ao carregar notas para consulta: {e}", exc_info=True)
            self.cache_consulta_notas = []
        self.listar_produtos_consulta()
        self.listar_notas_consulta()

    def listar_produtos_consulta(self):
        busca = self.entry_busca_produto_consulta.get().strip()
        nomes = self.lista_mestre_contagem_nomes or sorted(self.mapa_produtos_mestre_contagem)
        if busca.isdigit():
            achados = [n for n in nomes if str(self.mapa_produtos_mestre_contagem[n]['id']) == busca] or buscar_nomes(busca, nomes)
        else:
            achados = buscar_nomes(busca, nomes)
        for i in self.tree_consulta_produtos.get_children():
            self.tree_consulta_produtos.delete(i)
        for nome in achados[:500]:
            dados = self.mapa_produtos_mestre_contagem[nome]
            self.tree_consulta_produtos.insert("", "end", iid=str(dados['id']), values=(nome, dados['un']))
        extra = " (mostrando 500)" if len(achados) > 500 else ""
        self.lbl_consulta_qtd_produtos.config(text=f"{len(achados)} produto(s){extra}")

    def _consulta_escolher_primeiro(self):
        itens = self.tree_consulta_produtos.get_children()
        if itens:
            self.tree_consulta_produtos.focus(itens[0]); self.tree_consulta_produtos.selection_set(itens[0])
            self.mostrar_consulta_produto()
        return "break"

    def _data_inicio_periodo(self, texto):
        dias = dict(self.PERIODOS_CONSULTA + [('Últimos 30 dias', 30)]).get(texto)
        return (date.today() - timedelta(days=dias)) if dias else None

    def mostrar_consulta_produto(self, recarregar=True, produto_id=None):
        """Mostra os cartões, a comparação por fornecedor e o histórico do produto escolhido."""
        if produto_id is None:
            sel = self.tree_consulta_produtos.focus()
            if sel:
                produto_id = int(sel)
            elif getattr(self, 'produto_consulta', None) is not None and not recarregar:
                # [DEPURAÇÃO 2] a lista foi filtrada pela busca (o foco some), mas o produto na tela
                # continua o mesmo: trocar o período tem que atualizar os cartões dele
                produto_id = self.produto_consulta
            else:
                return
        if recarregar or self.produto_consulta != produto_id:
            try:
                self.historico_consulta = database.historico_compras_detalhado(produto_id) or []
            except Exception as e:
                logger.error(f"Erro ao consultar histórico do produto {produto_id}: {e}", exc_info=True)
                messagebox.showerror("Erro", f"Não foi possível carregar o histórico:\n{e}", parent=self.root)
                return
            self.produto_consulta = produto_id
        nome = next((n for n, d in self.mapa_produtos_mestre_contagem.items() if d['id'] == produto_id), f"Produto {produto_id}")
        un = self.unidade_do_produto(produto_id)
        self.nome_produto_consulta = nome
        self.lbl_consulta_produto.config(text=f"📦 {nome}  (ID {produto_id}, {un})")

        desde = self._data_inicio_periodo(self.combo_periodo_consulta.get())
        periodo = [r for r in self.historico_consulta if not desde or (r['Data'] and r['Data'] >= desde)]
        pagos = [r for r in periodo if r['CustoUnitario'] > 0]

        def cartao(chave, valor, detalhe=""):
            self.cartoes_consulta[chave][0].config(text=valor)
            self.cartoes_consulta[chave][1].config(text=detalhe)

        # [DEPURAÇÃO 2] último preço PAGO (bonificação de custo 0 mostrava "R$ 0,00")
        pagos_todos = [r for r in self.historico_consulta if r['CustoUnitario'] > 0]
        if pagos_todos:
            u = pagos_todos[0]
            cartao('ultimo', f"{fmt_reais(u['CustoUnitario'])} /{un}",
                   f"{u['Fornecedor'][:28]} · {u['Data'].strftime('%d/%m/%Y') if u['Data'] else '?'}")
        else:
            cartao('ultimo', "—", "nunca comprado por nota")
        if pagos:
            m = min(pagos, key=lambda r: r['CustoUnitario'])
            cartao('menor', f"{fmt_reais(m['CustoUnitario'])} /{un}",
                   f"{m['Fornecedor'][:28]} · {m['Data'].strftime('%d/%m/%Y') if m['Data'] else '?'}")
        else:
            cartao('menor', "—", "sem compras no período")
        qtd = sum((r['Quantidade'] for r in periodo), Decimal('0'))
        valor = sum((r['Total'] for r in periodo), Decimal('0'))
        cartao('media', f"{fmt_reais(valor / qtd)} /{un}" if qtd > 0 else "—", f"{len(periodo)} compra(s)")
        cartao('comprado', f"{fmt_qtd(qtd)} {un}", f"total pago {fmt_reais(valor)}")

        for i in self.tree_consulta_fornecedores.get_children():
            self.tree_consulta_fornecedores.delete(i)
        resumo = database.resumo_precos_por_fornecedor(self.historico_consulta, desde)
        mais_barato = next((r['CustoMedio'] for r in resumo if r['CustoMedio'] > 0), None)
        for n, r in enumerate(resumo):
            if mais_barato and r['CustoMedio'] > 0:
                dif = (r['CustoMedio'] / mais_barato - 1) * 100
                comparacao = "⭐ mais barato" if n == 0 else f"+{dif:.0f}%".replace('.', ',')
            else:
                comparacao = "bonificação" if r['CustoMedio'] <= 0 else "—"
            self.tree_consulta_fornecedores.insert("", "end", tags=('mais_barato',) if n == 0 and mais_barato else (), values=(
                r['Fornecedor'], r['Compras'], f"{fmt_qtd(r['Quantidade'])} {un}", fmt_reais(r['CustoMedio']),
                fmt_reais(r['Menor']), fmt_reais(r['Maior']), fmt_reais(r['Ultimo']),
                r['UltimaData'].strftime('%d/%m/%Y') if r['UltimaData'] else '—', comparacao))

        for i in self.tree_consulta_historico.get_children():
            self.tree_consulta_historico.delete(i)
        menor = min((r['CustoUnitario'] for r in pagos), default=None)
        maior = max((r['CustoUnitario'] for r in pagos), default=None)
        for r in periodo:
            tag = ()
            if menor is not None and maior is not None and menor != maior:
                tag = ('menor',) if r['CustoUnitario'] == menor else ('maior',) if r['CustoUnitario'] == maior else ()
            self.tree_consulta_historico.insert("", "end", iid=f"h{r['ItemNotaID']}", tags=tag, values=(
                r['Data'].strftime('%d/%m/%Y') if r['Data'] else '?', r['NumeroNF'], r['Fornecedor'], r['DescricaoXML'],
                fmt_qtd(r['Embalagens']), fmt_reais(r['CustoEmbalagem']), fmt_qtd(r['Quantidade']),
                fmt_reais(r['CustoUnitario']), fmt_reais(r['Total'])))

    def _consulta_abrir_nota_do_historico(self):
        sel = self.tree_consulta_historico.focus()
        if not sel:
            return
        item_id = sel[1:]
        registro = next((r for r in self.historico_consulta if str(r['ItemNotaID']) == item_id), None)
        if registro:
            self.abrir_nota_na_consulta(registro['NotaID'], destacar=self.nome_produto_consulta)

    def listar_notas_consulta(self):
        busca = sem_acento(self.entry_busca_nota.get()).split()
        desde = self._data_inicio_periodo(self.combo_periodo_nota.get())
        for i in self.tree_consulta_notas.get_children():
            self.tree_consulta_notas.delete(i)
        n = 0
        for nota in self.cache_consulta_notas:
            if desde and (not nota['Data'] or nota['Data'] < desde):
                continue
            if busca:
                texto = sem_acento(f"{nota['NumeroNF']} {nota['Fornecedor']} {nota['CNPJ']} {nota['TextoItens']}")
                if not all(p in texto for p in busca):
                    continue
            self.tree_consulta_notas.insert("", "end", iid=f"n{nota['NotaID']}", values=(
                nota['Data'].strftime('%d/%m/%Y') if nota['Data'] else '?', nota['NumeroNF'], nota['Fornecedor'],
                nota['Itens'], fmt_reais(nota['ValorNF'] or nota['TotalItens'])))
            n += 1
        self.lbl_consulta_qtd_notas.config(text=f"{n} nota(s)")

    def mostrar_itens_nota_consulta(self, destacar=None):
        sel = self.tree_consulta_notas.focus()
        for i in self.tree_consulta_itens.get_children():
            self.tree_consulta_itens.delete(i)
        if not sel:
            return
        nota_id = int(sel[1:])
        nota = next((n for n in self.cache_consulta_notas if n['NotaID'] == nota_id), None)
        try:
            itens = database.itens_da_nota(nota_id) or []
        except Exception as e:
            logger.error(f"Erro ao carregar itens da nota {nota_id}: {e}", exc_info=True)
            itens = []
        self.itens_nota_consulta = itens
        palavras = sem_acento(destacar).split() if destacar else sem_acento(self.entry_busca_nota.get()).split()
        total = Decimal('0')
        for it in itens:
            texto = sem_acento(f"{it['NomeProduto']} {it['DescricaoXML']}")
            achou = bool(palavras) and all(p in texto for p in palavras)
            self.tree_consulta_itens.insert("", "end", iid=f"i{it['ItemNotaID']}", tags=('achado',) if achou else (), values=(
                it['NomeProduto'], it['DescricaoXML'], fmt_qtd(it['Embalagens']), fmt_qtd(it['Fator']),
                fmt_reais(it['CustoEmbalagem']), fmt_qtd(it['Quantidade']), it['Unidade'],
                fmt_reais(it['CustoUnitario']), fmt_reais(it['Total'])))
            total += it['Total']
        if nota:
            self.lbl_consulta_nota.config(text=f"🧾 NF {nota['NumeroNF']} — {nota['Fornecedor']} — "
                                               f"{nota['Data'].strftime('%d/%m/%Y') if nota['Data'] else '?'} — {len(itens)} item(ns)")
        texto_total = f"Total dos itens: {fmt_reais(total)}"
        if nota and nota['ValorNF'] and abs(nota['ValorNF'] - total) >= Decimal('0.05'):
            texto_total += f"   ·   Valor da nota: {fmt_reais(nota['ValorNF'])} (a diferença são itens ignorados, como comodato, ou itens não salvos)"
        self.lbl_consulta_total_nota.config(text=texto_total)

    def abrir_nota_na_consulta(self, nota_id, destacar=None):
        """Vai para a aba 8 > Nota Fiscal e mostra a nota (usado pelo histórico do produto)."""
        if not self.cache_consulta_notas:
            self.cache_consulta_notas = database.listar_notas_para_consulta() or []
        self.entry_busca_nota.delete(0, tk.END)
        self.combo_periodo_nota.set('Todo o histórico')
        self.listar_notas_consulta()
        iid = f"n{nota_id}"
        try:
            self.nb_consultas.select(1)
        except tk.TclError:
            pass
        if self.tree_consulta_notas.exists(iid):
            self.tree_consulta_notas.focus(iid); self.tree_consulta_notas.selection_set(iid); self.tree_consulta_notas.see(iid)
            self.mostrar_itens_nota_consulta(destacar=destacar)

    def _consulta_ir_para_produto_do_item(self):
        sel = self.tree_consulta_itens.focus()
        if not sel:
            return
        item = next((i for i in getattr(self, 'itens_nota_consulta', []) if f"i{i['ItemNotaID']}" == sel), None)
        if not item or not item['ProdutoID']:
            self.status("Este item não está ligado a um produto do estoque.", 'aviso')
            return
        self.abrir_produto_na_consulta(item['ProdutoID'])

    def abrir_produto_na_consulta(self, produto_id):
        """Vai para a aba 8 > Produto e mostra o histórico de preços do produto."""
        self.entry_busca_produto_consulta.delete(0, tk.END)
        self.listar_produtos_consulta()
        try:
            self.nb_consultas.select(0)
        except tk.TclError:
            pass
        iid = str(produto_id)
        if self.tree_consulta_produtos.exists(iid):
            self.tree_consulta_produtos.focus(iid); self.tree_consulta_produtos.selection_set(iid); self.tree_consulta_produtos.see(iid)
        self.mostrar_consulta_produto(produto_id=int(produto_id))

    def exportar_consulta_produto(self):
        if not self.produto_consulta:
            messagebox.showwarning("Aviso", "Escolha um produto primeiro.", parent=self.root)
            return
        pd = self._importar_pandas(self.root)
        if pd is None:
            return
        caminho = filedialog.asksaveasfilename(
            parent=self.root, title="Salvar histórico de preços", defaultextension=".xlsx",
            filetypes=[("Arquivos Excel", "*.xlsx")],
            initialfile=nome_arquivo_seguro(f"Historico_Precos_{self.nome_produto_consulta}.xlsx"))
        if not caminho:
            return
        try:
            desde = self._data_inicio_periodo(self.combo_periodo_consulta.get())
            periodo = [r for r in self.historico_consulta if not desde or (r['Data'] and r['Data'] >= desde)]
            resumo = database.resumo_precos_por_fornecedor(self.historico_consulta, desde)
            with pd.ExcelWriter(caminho, engine='openpyxl') as escritor:
                pd.DataFrame([{'Fornecedor': r['Fornecedor'], 'Compras': r['Compras'], 'Qtd comprada': float(r['Quantidade']),
                               'Custo médio/unid.': float(r['CustoMedio']), 'Menor': float(r['Menor']), 'Maior': float(r['Maior']),
                               'Último': float(r['Ultimo']), 'Última compra': r['UltimaData'].strftime('%d/%m/%Y') if r['UltimaData'] else ''}
                              for r in resumo]).to_excel(escritor, sheet_name='Por fornecedor', index=False)
                pd.DataFrame([{'Data': r['Data'].strftime('%d/%m/%Y') if r['Data'] else '', 'NF': r['NumeroNF'],
                               'Fornecedor': r['Fornecedor'], 'Descrição na nota': r['DescricaoXML'],
                               'Embalagens': float(r['Embalagens']), 'Custo embalagem': float(r['CustoEmbalagem']),
                               'Quantidade': float(r['Quantidade']), 'Custo/unid.': float(r['CustoUnitario']),
                               'Total': float(r['Total'])} for r in periodo]).to_excel(escritor, sheet_name='Histórico', index=False)
            self.status(f"Histórico de preços salvo em: {caminho}")
            messagebox.showinfo("Salvo", f"Histórico salvo em:\n{caminho}", parent=self.root)
        except Exception as e:
            logger.error(f"Erro ao exportar histórico de preços: {e}", exc_info=True)
            messagebox.showerror("Erro", f"Não foi possível salvar o Excel.\n{e}", parent=self.root)

    def ordenar_coluna_treeview(self, tree, col, reverse):
        """
        Ordena dinamicamente a coluna da Treeview, identificando 
        valores numéricos mascarados por strings (ex: '0.4 meses', 'R$ 10.00').
        """
        # Extrai os dados atuais da visualização
        lista_itens = [(tree.set(k, col), k) for k in tree.get_children('')]

        # [DEPURAÇÃO] chave_ordenacao nunca compara número com texto (antes dava TypeError
        # na coluna "Duração") e entende "R$ 1.234,56" (antes ordenava como texto).
        lista_itens.sort(key=lambda t: chave_ordenacao(t[0]), reverse=reverse)

        # Aplica a nova ordem visual realocando os índices no Tkinter
        for index, (val, k) in enumerate(lista_itens):
            tree.move(k, '', index)

        # Inverte o estado da ordenação para o próximo clique no mesmo cabeçalho
        tree.heading(col, command=lambda: self.ordenar_coluna_treeview(tree, col, not reverse))      

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = AppGestaoEstoque(root)
    root.mainloop()


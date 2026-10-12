# ==============================================================================
# financas_database.py - BANCO DE DADOS DO APP DE FINANÇAS DA FAMÍLIA
# ------------------------------------------------------------------------------
# O app (navegador do celular ou do computador, em /financas) serve para saber
# com detalhe TUDO que a família gasta:
#   1) CONTAS e CARTÕES (Nubank, Inter, Bradesco, Mercado Pago, Nomad, dinheiro...);
#   2) CATEGORIAS em dois níveis (ex.: Mercado > Carnes e peixes);
#   3) LANÇAMENTOS: gasto, receita ou transferência (pagar a fatura = transferência
#      da conta para o cartão), com parcelas e "quem gastou";
#   4) CUPOM FISCAL: o QR Code vira UM lançamento, mas cada item do cupom tem a
#      sua categoria. O total é dividido entre as categorias (tabela
#      lancamento_partes), então os relatórios mostram "quanto foi de carne",
#      e não só "R$ 312,45 no mercado".
#
# IMPORTANTE: este banco é SEPARADO do banco da loja (SQL Server). É um arquivo
# SQLite (dados_financas/financas.db) que nada da sorveteria lê ou escreve.
# FAÇA CÓPIA DESSE ARQUIVO de vez em quando (pendrive, Google Drive...).
#
# Valores em dinheiro ficam em CENTAVOS (número inteiro) para não ter erro de
# arredondamento. O celular recebe e manda em reais.
# ==============================================================================

import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import unicodedata
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

logger = logging.getLogger(__name__)

try:
    import config
except Exception:                     # permite usar o arquivo sem o config.py (testes)
    config = None

# ------------------------------------------------------------------------------
# Regras que você pode ajustar (ou mudar pelo config.py)
# ------------------------------------------------------------------------------
PASTA_BASE = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_BANCO = getattr(config, 'FINANCAS_ARQUIVO_BANCO', None) or os.path.join(PASTA_BASE, 'dados_financas', 'financas.db')
PIN_TAMANHO = 4
PIN_MAX_ERROS = 5
PIN_BLOQUEIO_MINUTOS = 15
MAX_PARCELAS = 48

TIPOS_CONTA = {
    'corrente': 'Conta corrente',
    'poupanca': 'Poupança',
    'carteira': 'Dinheiro',
    'cartao': 'Cartão de crédito',
    'investimento': 'Investimento',
}
TIPOS_LANCAMENTO = ('despesa', 'receita', 'transferencia')

# Situação do cupom
CUP_PENDENTE = 'pendente'     # lido: conferir as categorias e lançar
CUP_LANCADO = 'lancado'       # virou lançamento
CUP_ERRO = 'erro'             # não deu para ler a página da SEFAZ (dá para tentar de novo)

VERSAO_BANCO = 1


class ErroFinancas(Exception):
    """Erro com mensagem pronta para mostrar na tela."""


# ==============================================================================
# == Categorias que já vêm cadastradas =========================================
# ==============================================================================
# (nome, [subcategorias]). Dá para mudar tudo depois, pelo app (Ajustes).
CATEGORIAS_PADRAO = {
    'despesa': [
        ('Moradia', ['Aluguel / Financiamento', 'Condomínio', 'Energia', 'Água', 'Gás', 'Internet / TV / Celular',
                     'Manutenção da casa', 'IPTU']),
        ('Mercado', ['Hortifrúti', 'Carnes e peixes', 'Frios e laticínios', 'Padaria', 'Mercearia', 'Bebidas',
                     'Bebidas alcoólicas', 'Limpeza', 'Higiene e beleza', 'Pet', 'Utilidades do lar']),
        ('Alimentação fora', ['Restaurante', 'Lanche / Delivery', 'Café / Padaria']),
        ('Transporte', ['Combustível', 'Estacionamento', 'Manutenção do carro', 'Seguro / IPVA / Licenciamento',
                        'Uber / Táxi', 'Pedágio']),
        ('Saúde', ['Farmácia', 'Plano de saúde', 'Consultas e exames', 'Academia']),
        ('Educação', ['Escola', 'Cursos', 'Material escolar']),
        ('Lazer', ['Passeios', 'Viagens', 'Assinaturas / Streaming', 'Hobbies']),
        ('Compras', ['Roupas e calçados', 'Eletrônicos', 'Casa e decoração', 'Presentes']),
        ('Serviços financeiros', ['Tarifas bancárias', 'Juros e multas', 'Anuidade', 'IOF']),
        ('Impostos', []),
        ('Outros gastos', []),
    ],
    'receita': [
        ('Salário', []),
        ('Pró-labore / Retirada', []),
        ('Rendimentos', []),
        ('Reembolsos', []),
        ('Outras receitas', []),
    ],
}

# Palavras do item do cupom -> categoria (usado quando o sistema ainda não aprendeu o item).
# Basta o começo da palavra: 'CERV' pega CERVEJA. As palavras MAIS LONGAS são testadas
# primeiro ('AGUA SANITARIA' ganha de 'AGUA').
PALAVRAS_ITEM = {
    'Mercado/Hortifrúti': [
        'BANANA', 'MACA', 'LARANJA', 'LIMAO', 'TOMATE', 'CEBOLA', 'ALHO', 'BATATA', 'CENOURA', 'ALFACE',
        'MAMAO', 'MELANCIA', 'MELAO', 'ABACAXI', 'UVA', 'MANGA', 'PEPINO', 'PIMENTAO', 'ABOBRINHA', 'ABOBORA',
        'CHUCHU', 'REPOLHO', 'BROCOLIS', 'COUVE', 'MANDIOCA', 'BETERRABA', 'MORANGO', 'ABACATE', 'TANGERINA',
        'MEXERICA', 'POKAN', 'GOIABA', 'MARACUJA', 'KIWI', 'PERA ', 'QUIABO', 'JILO', 'BERINJELA', 'CHEIRO VERDE',
        'SALSA', 'CEBOLINHA', 'COENTRO', 'RUCULA', 'AGRIAO', 'ESPINAFRE', 'VAGEM', 'INHAME', 'GENGIBRE', 'HORTI',
    ],
    'Mercado/Carnes e peixes': [
        'CARNE', 'BOVIN', 'FRANGO', 'COXA', 'SOBRECOXA', 'ASA FRANGO', 'COXINHA DA ASA', 'PICANHA', 'ALCATRA',
        'PATINHO', 'ACEM', 'COSTELA', 'LINGUICA', 'SUIN', 'PERNIL', 'BISTECA', 'LOMBO', 'PEIXE', 'TILAPIA',
        'PINTADO', 'PACU', 'TAMBAQUI', 'MAMINHA', 'CUPIM', 'FRALDINHA', 'CONTRA FILE', 'CONTRAFILE', 'FILE MIGNON',
        'MIUDO', 'COXAO', 'MUSCULO', 'PALETA', 'CAMARAO', 'SALSICHA', 'HAMBURGUER', 'BACON', 'CHARQUE',
        'CARNE SECA', 'ALMONDEGA', 'FIGADO', 'MOELA', 'CORACAO',
    ],
    'Mercado/Frios e laticínios': [
        'LEITE', 'QUEIJO', 'MUSSARELA', 'MUCARELA', 'MUSS', 'PRESUNTO', 'IOGURTE', 'IOG', 'REQUEIJAO', 'REQ',
        'MANTEIGA', 'MARGARINA', 'NATA', 'PEITO PERU', 'PEITO DE PERU', 'SALAME', 'MORTADELA', 'BEBIDA LACTEA',
        'COALHADA', 'RICOTA', 'PROVOLONE', 'PARMESAO', 'CATUPIRY', 'CREAM CHEESE', 'BLANQUET',
    ],
    'Mercado/Padaria': [
        'PAO', 'BISNAGUINHA', 'BOLO', 'ROSCA', 'TORRADA', 'SONHO', 'CROISSANT', 'BAGUETE', 'CHIPA', 'PAO DE QUEIJO',
    ],
    'Mercado/Mercearia': [
        'ARROZ', 'FEIJAO', 'MACARRAO', 'ESPAGUETE', 'OLEO', 'ACUCAR', 'SAL REFINADO', 'SAL GROSSO', 'CAFE',
        'FARINHA', 'MOLHO', 'EXTRATO', 'MILHO', 'ERVILHA', 'BISCOITO', 'BISC', 'BOLACHA', 'ACHOCOLATADO', 'NESCAU',
        'TODDY', 'AVEIA', 'CEREAL', 'GRANOLA', 'TEMPERO', 'MAIONESE', 'KETCHUP', 'MOSTARDA', 'ATUM', 'SARDINHA',
        'LEITE CONDENSADO', 'LEITE COCO', 'LEITE DE COCO', 'CREME DE LEITE', 'CR LEITE', 'GELATINA', 'CHOCOLATE',
        'BOMBOM', 'BALA', 'SALGADINHO', 'PIPOCA', 'OVO', 'FUBA', 'POLVILHO', 'VINAGRE', 'AZEITE', 'AMIDO', 'FERMENTO',
        'TAPIOCA', 'GRANULADO', 'LASANHA', 'PIZZA', 'NUGGETS', 'BATATA PALHA', 'CALDO', 'CATCHUP', 'MEL ',
        'GELEIA', 'DOCE DE LEITE', 'PANETONE', 'SORVETE', 'PICOLE', 'ACAI', 'AMENDOIM', 'CASTANHA', 'LENTILHA',
        'GRAO DE BICO', 'QUINOA', 'CHIA', 'LINHACA', 'ADOCANTE', 'MISTURA BOLO', 'MIOJO', 'LAMEN', 'COLORAU',
        'OREGANO', 'PIMENTA DO REINO', 'CANELA', 'COMINHO', 'AZEITONA', 'PALMITO', 'SELETA', 'CONSERVA',
    ],
    'Mercado/Bebidas': [
        'REFRI', 'REFRIG', 'COCA', 'GUARANA', 'PEPSI', 'FANTA', 'SPRITE', 'SCHWEPPES', 'SUCO', 'AGUA MINERAL',
        'AGUA MIN', 'AGUA S GAS', 'AGUA C GAS', 'AGUA COCO', 'AGUA DE COCO', 'CHA ', 'MATE', 'ENERGETICO',
        'RED BULL', 'MONSTER', 'ISOTONICO', 'GATORADE', 'POWERADE', 'H2OH', 'DEL VALLE', 'TANG', 'KAPO',
    ],
    'Mercado/Bebidas alcoólicas': [
        'CERV', 'CERVEJA', 'CHOPP', 'CHOPE', 'VINHO', 'ESPUMANTE', 'VODKA', 'VODCA', 'WHISKY', 'WHISKEY', 'UISQUE',
        'CACHACA', 'PINGA', 'GIN ', 'RUM ', 'TEQUILA', 'LICOR', 'SKOL', 'BRAHMA', 'HEINEKEN', 'AMSTEL', 'BUDWEISER',
        'SPATEN', 'STELLA', 'CORONA', 'ITAIPAVA', 'PETRA', 'DEVASSA', 'ANTARCTICA', 'BOHEMIA', 'EISENBAHN',
        'ORIGINAL 600', 'IMPERIO', 'BADEN', 'BEATS', 'CAMPARI', 'MARTINI', 'SAKE ', 'SMIRNOFF',
    ],
    'Mercado/Limpeza': [
        'DETERG', 'SABAO', 'SAB PO', 'SAB LIQ ROUPA', 'LAVA ROUPA', 'AMACIANTE', 'DESINF', 'AGUA SANITARIA',
        'AGUA SANIT', 'ALVEJANTE', 'LIMPADOR', 'ESPONJA', 'MULTIUSO', 'MULTI USO', 'VEJA', 'YPE', 'OMO', 'BOMBRIL',
        'SACO LIXO', 'SACO P LIXO', 'SACO DE LIXO', 'SACO PARA LIXO', 'DESENGORDURANTE', 'LUSTRA', 'CLORO',
        'PANO', 'RODO', 'VASSOURA', 'INSETICIDA', 'REPELENTE', 'LIMPA', 'TIRA MANCHA', 'VANISH', 'PINHO',
        'CANDIDA', 'QBOA', 'LYSOFORM', 'PEDRA SANITARIA', 'BOM AR', 'AROMATIZ', 'LUVA', 'ALCOOL',
    ],
    'Mercado/Higiene e beleza': [
        'SHAMPOO', 'SHAMP', 'XAMPU', 'CONDICIONADOR', 'SABONETE', 'SAB LIQ', 'SAB BARRA', 'CREME DENTAL',
        'CR DENTAL', 'CR DENT', 'ESCOVA DENTAL', 'ESC DENTAL', 'FIO DENTAL', 'DESODORANTE', 'DESOD', 'PAPEL HIG',
        'PAP HIG', 'PAPEL HIGIENICO', 'ABSORVENTE', 'FRALDA', 'LENCO UMEDECIDO', 'APARELHO BARBEAR', 'BARBEAR',
        'HIDRATANTE', 'ALGODAO', 'COTONETE', 'HASTE FLEXIVEL', 'ENXAGUANTE', 'ANTISSEPTICO BUCAL', 'PROTETOR SOLAR',
        'CREME PENTEAR', 'GEL CAB', 'ESMALTE', 'ACETONA', 'TINTURA', 'COLGATE', 'SORRISO', 'ORAL B', 'DOVE',
        'NIVEA', 'REXONA', 'PAMPERS', 'HUGGIES',
    ],
    'Mercado/Pet': [
        'RACAO', 'PET ', 'AREIA GATO', 'AREIA HIGIENICA', 'PEDIGREE', 'WHISKAS', 'PETISCO', 'GOLDEN', 'PREMIER PET',
        'FRISKIES', 'TAPETE HIGIENICO',
    ],
    'Mercado/Utilidades do lar': [
        'PILHA', 'LAMPADA', 'VELA', 'FOSFORO', 'ISQUEIRO', 'PAPEL ALUMINIO', 'PAPEL ALUM', 'FILME PVC',
        'GUARDANAPO', 'PAPEL TOALHA', 'PAP TOALHA', 'COPO DESC', 'PRATO DESC', 'CARVAO', 'SACOLA', 'POTE',
        'TALHER DESC', 'ASSADEIRA', 'PAPEL MANTEIGA', 'FITA ADESIVA', 'EXTENSAO', 'BENJAMIN',
    ],
    'Transporte/Combustível': [
        'GASOLINA', 'ETANOL', 'ALCOOL COMUM', 'ALCOOL HIDRATADO', 'DIESEL', 'GNV', 'ARLA', 'OLEO MOTOR', 'LUBRIFICANTE',
    ],
}

# Nome do estabelecimento -> categoria "geral" do cupom (o que não tiver categoria
# própria fica nela). Ex.: tudo de farmácia vai para Saúde > Farmácia.
PALAVRAS_ESTABELECIMENTO = {
    'Saúde/Farmácia': ['FARMA', 'DROGA', 'DROGARIA', 'PAGUE MENOS', 'PACHECO', 'RAIA', 'DROGASIL', 'ULTRAFARMA'],
    'Transporte/Combustível': ['POSTO', 'COMBUST', 'AUTO POSTO', 'PETROLEO', 'IPIRANGA', 'SHELL'],
    'Alimentação fora/Restaurante': ['RESTAUR', 'CHURRASC', 'PIZZ', 'BURGER', 'GRILL', 'SUSHI', 'TEMAKI', 'BAR E',
                                     'CHOPERIA', 'CHOPPERIA', 'CANTINA', 'BISTRO'],
    'Alimentação fora/Lanche / Delivery': ['LANCH', 'SORVET', 'ACAI', 'PASTEL', 'SALGAD'],
    'Alimentação fora/Café / Padaria': ['PADARIA', 'PANIFIC', 'CAFE', 'CAFETERIA', 'CONFEITARIA'],
    'Compras/Roupas e calçados': ['CALCAD', 'MODA', 'CONFEC', 'RENNER', 'RIACHUELO', 'C&A', 'HERING', 'MARISA'],
    'Mercado': ['SUPERMERC', 'MERCADO', 'ATACAD', 'ASSAI', 'ATACADAO', 'COMPER', 'CARREFOUR', 'MERCEARIA',
                'HIPERMERC', 'HORTIFRUTI', 'SACOLAO', 'ACOUGUE', 'CASA DE CARNES', 'EMPORIO', 'DISTRIBUIDORA'],
}


# ==============================================================================
# == Funções auxiliares =========================================================
# ==============================================================================

def _agora():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def normalizar(texto):
    """'Cerv. SKOL Lt 350ml' -> 'CERV SKOL LT 350ML' (sem acento, maiúsculas, só letras/números)."""
    t = unicodedata.normalize('NFD', str(texto or ''))
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn').upper()
    t = re.sub(r'[^A-Z0-9&]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def chave_item(descricao):
    """
    Chave usada para APRENDER a categoria de um item do cupom. Tira números, pesos e
    tamanhos para 'COCA COLA 2L' e 'COCA COLA 600ML' virarem a mesma coisa.
    """
    t = normalizar(descricao)
    t = re.sub(r'\b\d+([.,]\d+)?\s*(KG|G|GR|L|LT|ML|UN|UND|UNID|CX|PCT|PC|M|CM|MM|X)?\b', ' ', t)
    t = re.sub(r'\b(KG|GR|LT|ML|UN|UND|UNID|PCT|PC|CX|C|X)\b', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()[:80]


def chave_descricao(descricao):
    """Chave para aprender a categoria pela descrição do lançamento ('UBER *TRIP 1234' -> 'UBER TRIP')."""
    t = normalizar(descricao)
    t = re.sub(r'\b\d+\b', ' ', t)
    t = re.sub(r'\b(PARC|PARCELA)\b.*$', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()[:80]


def para_centavos(valor, obrigatorio=True, permite_zero=False):
    """Aceita 12.5, '12,50', '1.234,56', 'R$ 3,00' -> centavos (int). Valor sempre positivo."""
    if valor is None or str(valor).strip() == '':
        if obrigatorio:
            raise ErroFinancas("Informe o valor.")
        return None
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        d = Decimal(str(valor))
    else:
        t = str(valor).strip().replace('R$', '').replace(' ', '')
        if ',' in t:
            t = t.replace('.', '').replace(',', '.')
        elif t.count('.') > 1:
            t = t.replace('.', '')
        try:
            d = Decimal(t)
        except InvalidOperation:
            raise ErroFinancas(f"Valor inválido: {valor}")
    if not d.is_finite():
        raise ErroFinancas(f"Valor inválido: {valor}")
    cent = int((d * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if cent < 0:
        raise ErroFinancas("O valor não pode ser negativo (escolha se é gasto ou receita).")
    if cent == 0 and not permite_zero:
        raise ErroFinancas("O valor precisa ser maior que zero.")
    if cent > 100_000_000_00:
        raise ErroFinancas("Valor grande demais.")
    return cent


def reais(cent):
    """Centavos -> reais (float com 2 casas) para mandar em JSON."""
    return None if cent is None else round(cent / 100, 2)


def _como_data(valor, obrigatorio=True):
    if valor in (None, ''):
        if obrigatorio:
            raise ErroFinancas("Informe a data.")
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    t = str(valor).strip()[:10]
    for formato in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(t, formato).date()
        except ValueError:
            continue
    raise ErroFinancas(f"Data inválida: {valor}")


def _intervalo_mes(mes):
    """'2026-10' -> (date(2026,10,1), date(2026,10,31))."""
    m = re.fullmatch(r'(\d{4})-(\d{2})', str(mes or ''))
    if not m:
        hoje = date.today()
        ano, num = hoje.year, hoje.month
    else:
        ano, num = int(m.group(1)), int(m.group(2))
        if not 1 <= num <= 12 or not 2000 <= ano <= 2100:
            raise ErroFinancas("Mês inválido.")
    return date(ano, num, 1), date(ano, num, monthrange(ano, num)[1])


def somar_meses(d, n):
    """Mesmo dia n meses depois (31/01 + 1 mês = 28 ou 29/02)."""
    total = d.month - 1 + n
    ano, mes = d.year + total // 12, total % 12 + 1
    return date(ano, mes, min(d.day, monthrange(ano, mes)[1]))


def ratear(total, pesos):
    """
    Divide 'total' centavos na proporção de 'pesos' (lista de inteiros) sem perder
    nenhum centavo: quem tem a maior sobra fica com o centavo que faltar.
    """
    soma = sum(pesos)
    if not pesos:
        return []
    if soma <= 0:
        partes = [0] * len(pesos)
        partes[0] = total
        return partes
    brutos = [total * p / soma for p in pesos]
    partes = [int(b) for b in brutos]
    faltam = total - sum(partes)
    ordem = sorted(range(len(pesos)), key=lambda i: brutos[i] - partes[i], reverse=True)
    for i in ordem[:faltam]:
        partes[i] += 1
    return partes


# ==============================================================================
# == Conexão e tabelas ==========================================================
# ==============================================================================

_tabelas_ok = False


def _conectar():
    global _tabelas_ok
    pasta = os.path.dirname(ARQUIVO_BANCO)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    conn = sqlite3.connect(ARQUIVO_BANCO, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    if not _tabelas_ok:
        _criar_tabelas(conn)
        _tabelas_ok = True
    return conn


def _criar_tabelas(conn):
    versao = conn.execute('PRAGMA user_version').fetchone()[0]
    if versao >= VERSAO_BANCO:
        return
    conn.execute('PRAGMA journal_mode = WAL')
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL UNIQUE,
            pin_hash TEXT, pin_salt TEXT,
            erros INTEGER NOT NULL DEFAULT 0,
            bloqueado_ate TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT
        );
        CREATE TABLE IF NOT EXISTS contas (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            instituicao TEXT,
            saldo_inicial INTEGER NOT NULL DEFAULT 0,
            limite INTEGER,
            dia_fechamento INTEGER,
            dia_vencimento INTEGER,
            dono_id INTEGER REFERENCES usuarios(id),
            ativa INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER NOT NULL DEFAULT 0,
            criada_em TEXT
        );
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            pai_id INTEGER REFERENCES categorias(id),
            ativa INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS cupons (
            id INTEGER PRIMARY KEY,
            chave TEXT NOT NULL UNIQUE,
            url TEXT,
            emitente TEXT, cnpj TEXT, numero TEXT, serie TEXT,
            data_emissao TEXT,
            valor_total INTEGER, descontos INTEGER, valor_pagar INTEGER,
            categoria_id INTEGER REFERENCES categorias(id),
            status TEXT NOT NULL,
            erro TEXT,
            lido_por INTEGER REFERENCES usuarios(id),
            lido_em TEXT
        );
        CREATE TABLE IF NOT EXISTS cupom_itens (
            cupom_id INTEGER NOT NULL REFERENCES cupons(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            codigo TEXT,
            qtd REAL, unidade TEXT,
            valor_unit REAL,
            valor_total INTEGER NOT NULL,
            categoria_id INTEGER REFERENCES categorias(id),
            categoria_origem TEXT,              -- 'aprendido', 'palavra', 'estabelecimento' ou 'manual'
            PRIMARY KEY (cupom_id, seq)
        );
        CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY,
            tipo TEXT NOT NULL,
            data TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor INTEGER NOT NULL,
            conta_id INTEGER NOT NULL REFERENCES contas(id),
            conta_destino_id INTEGER REFERENCES contas(id),
            categoria_id INTEGER REFERENCES categorias(id),
            pessoa_id INTEGER REFERENCES usuarios(id),
            observacao TEXT,
            cupom_id INTEGER REFERENCES cupons(id),
            grupo_parcela TEXT,
            parcela INTEGER, parcelas INTEGER,
            origem TEXT NOT NULL DEFAULT 'manual',
            criado_por INTEGER REFERENCES usuarios(id),
            criado_em TEXT, atualizado_em TEXT
        );
        CREATE TABLE IF NOT EXISTS lancamento_partes (
            lancamento_id INTEGER NOT NULL REFERENCES lancamentos(id) ON DELETE CASCADE,
            categoria_id INTEGER NOT NULL REFERENCES categorias(id),
            valor INTEGER NOT NULL,
            PRIMARY KEY (lancamento_id, categoria_id)
        );
        CREATE TABLE IF NOT EXISTS regras (
            id INTEGER PRIMARY KEY,
            tipo TEXT NOT NULL,                 -- 'item' (item do cupom) ou 'descricao' (lançamento)
            padrao TEXT NOT NULL,
            categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
            usos INTEGER NOT NULL DEFAULT 1,
            atualizado_em TEXT,
            UNIQUE (tipo, padrao)
        );
        CREATE INDEX IF NOT EXISTS ix_lanc_data ON lancamentos(data);
        CREATE INDEX IF NOT EXISTS ix_lanc_conta ON lancamentos(conta_id);
        CREATE INDEX IF NOT EXISTS ix_lanc_destino ON lancamentos(conta_destino_id);
        CREATE INDEX IF NOT EXISTS ix_lanc_cupom ON lancamentos(cupom_id);
        CREATE INDEX IF NOT EXISTS ix_lanc_grupo ON lancamentos(grupo_parcela);
    """)
    if not conn.execute('SELECT 1 FROM categorias LIMIT 1').fetchone():
        for tipo, lista in CATEGORIAS_PADRAO.items():
            for ordem, (nome, filhas) in enumerate(lista):
                pai = conn.execute('INSERT INTO categorias (nome, tipo, ordem) VALUES (?, ?, ?)', (nome, tipo, ordem)).lastrowid
                for o2, filha in enumerate(filhas):
                    conn.execute('INSERT INTO categorias (nome, tipo, pai_id, ordem) VALUES (?, ?, ?, ?)', (filha, tipo, pai, o2))
    if not conn.execute('SELECT 1 FROM contas LIMIT 1').fetchone():
        conn.execute("INSERT INTO contas (nome, tipo, ordem, criada_em) VALUES ('Dinheiro', 'carteira', 0, ?)", (_agora(),))
    conn.execute(f'PRAGMA user_version = {VERSAO_BANCO}')
    conn.commit()


def garantir_tabelas():
    _conectar().close()


# ==============================================================================
# == Usuários e PIN ============================================================
# ==============================================================================

def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(salt), 120_000).hex()


def validar_formato_pin(pin):
    pin = str(pin or '').strip()
    if not re.fullmatch(r'\d{%d}' % PIN_TAMANHO, pin):
        raise ErroFinancas(f"O PIN precisa ter exatamente {PIN_TAMANHO} números.")
    return pin


def definir_usuario(nome, pin):
    """Cria a pessoa (ou troca o PIN de quem já existe). Também desbloqueia e reativa."""
    nome = str(nome or '').strip()[:40]
    if not nome:
        raise ErroFinancas("Informe o nome.")
    pin = validar_formato_pin(pin)
    salt = secrets.token_hex(16)
    conn = _conectar()
    try:
        conn.execute("""INSERT INTO usuarios (nome, pin_hash, pin_salt, erros, ativo, criado_em) VALUES (?, ?, ?, 0, 1, ?)
                        ON CONFLICT(nome) DO UPDATE SET pin_hash = excluded.pin_hash, pin_salt = excluded.pin_salt,
                                                       erros = 0, bloqueado_ate = NULL, ativo = 1""",
                     (nome, _hash_pin(pin, salt), salt, _agora()))
        conn.commit()
    finally:
        conn.close()


def listar_usuarios(incluir_inativos=False):
    conn = _conectar()
    try:
        sql = 'SELECT id, nome, ativo FROM usuarios' + ('' if incluir_inativos else ' WHERE ativo = 1') + ' ORDER BY nome'
        return [{'id': r['id'], 'nome': r['nome'], 'ativo': bool(r['ativo'])} for r in conn.execute(sql)]
    finally:
        conn.close()


def desativar_usuario(usuario_id):
    conn = _conectar()
    try:
        n = conn.execute('UPDATE usuarios SET ativo = 0 WHERE id = ?', (int(usuario_id),)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def verificar_pin(usuario_id, pin, agora=None):
    """Confere o PIN. Devolve {'id', 'nome'} ou levanta ErroFinancas."""
    agora = agora or datetime.now()
    try:
        usuario_id = int(usuario_id)
    except (TypeError, ValueError):
        raise ErroFinancas("Escolha seu nome.")
    conn = _conectar()
    try:
        u = conn.execute('SELECT * FROM usuarios WHERE id = ? AND ativo = 1', (usuario_id,)).fetchone()
        if not u or not u['pin_hash']:
            raise ErroFinancas("Pessoa sem acesso ao app.")
        if u['bloqueado_ate'] and datetime.strptime(u['bloqueado_ate'], '%Y-%m-%d %H:%M:%S') > agora:
            raise ErroFinancas(f"PIN bloqueado por erros seguidos. Tente de novo em {PIN_BLOQUEIO_MINUTOS} minutos.")
        if not hmac.compare_digest(_hash_pin(str(pin or '').strip(), u['pin_salt']), u['pin_hash']):
            erros = u['erros'] + 1
            bloqueio = None
            if erros >= PIN_MAX_ERROS:
                bloqueio = (agora + timedelta(minutes=PIN_BLOQUEIO_MINUTOS)).strftime('%Y-%m-%d %H:%M:%S')
                erros = 0
            conn.execute('UPDATE usuarios SET erros = ?, bloqueado_ate = ? WHERE id = ?', (erros, bloqueio, usuario_id))
            conn.commit()
            if bloqueio:
                raise ErroFinancas(f"PIN errado {PIN_MAX_ERROS} vezes: bloqueado por {PIN_BLOQUEIO_MINUTOS} minutos.")
            raise ErroFinancas(f"PIN errado. Restam {PIN_MAX_ERROS - erros} tentativa(s).")
        conn.execute('UPDATE usuarios SET erros = 0, bloqueado_ate = NULL WHERE id = ?', (usuario_id,))
        conn.commit()
        return {'id': u['id'], 'nome': u['nome']}
    finally:
        conn.close()


def usuario_ativo(usuario_id):
    conn = _conectar()
    try:
        r = conn.execute('SELECT 1 FROM usuarios WHERE id = ? AND ativo = 1', (int(usuario_id),)).fetchone()
        return bool(r)
    finally:
        conn.close()


# ==============================================================================
# == Contas e cartões ==========================================================
# ==============================================================================

def _conta_dict(r):
    return {'id': r['id'], 'nome': r['nome'], 'tipo': r['tipo'], 'tipo_nome': TIPOS_CONTA.get(r['tipo'], r['tipo']),
            'instituicao': r['instituicao'] or '', 'saldo_inicial': reais(r['saldo_inicial']),
            'limite': reais(r['limite']), 'dia_fechamento': r['dia_fechamento'], 'dia_vencimento': r['dia_vencimento'],
            'dono_id': r['dono_id'], 'ativa': bool(r['ativa']), 'ordem': r['ordem']}


def listar_contas(incluir_inativas=False):
    conn = _conectar()
    try:
        sql = 'SELECT * FROM contas' + ('' if incluir_inativas else ' WHERE ativa = 1') + ' ORDER BY ativa DESC, ordem, nome'
        return [_conta_dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def _dia(valor):
    if valor in (None, ''):
        return None
    try:
        d = int(valor)
    except (TypeError, ValueError):
        raise ErroFinancas("Dia inválido.")
    if not 1 <= d <= 31:
        raise ErroFinancas("O dia precisa ser de 1 a 31.")
    return d


def salvar_conta(dados):
    """Cria (sem 'id') ou altera uma conta/cartão. Devolve a conta salva."""
    nome = str(dados.get('nome') or '').strip()[:60]
    if not nome:
        raise ErroFinancas("Dê um nome para a conta (ex.: Nubank, Cartão Bradesco).")
    tipo = dados.get('tipo') or 'corrente'
    if tipo not in TIPOS_CONTA:
        raise ErroFinancas("Tipo de conta inválido.")
    cartao = tipo == 'cartao'
    # saldo inicial: número com sinal (conta no vermelho, fatura em aberto = negativo)
    saldo_txt = str(dados.get('saldo_inicial') if dados.get('saldo_inicial') is not None else '').strip()
    negativo = saldo_txt.startswith('-')
    saldo = para_centavos(saldo_txt.lstrip('-'), obrigatorio=False, permite_zero=True) or 0
    saldo = -saldo if negativo else saldo
    valores = (nome, tipo, str(dados.get('instituicao') or '').strip()[:60] or None, saldo,
               para_centavos(dados.get('limite'), obrigatorio=False, permite_zero=True) if cartao else None,
               _dia(dados.get('dia_fechamento')) if cartao else None,
               _dia(dados.get('dia_vencimento')) if cartao else None,
               int(dados['dono_id']) if dados.get('dono_id') else None,
               0 if dados.get('ativa') is False else 1)
    conn = _conectar()
    try:
        if dados.get('id'):
            n = conn.execute("""UPDATE contas SET nome = ?, tipo = ?, instituicao = ?, saldo_inicial = ?, limite = ?,
                                dia_fechamento = ?, dia_vencimento = ?, dono_id = ?, ativa = ? WHERE id = ?""",
                             valores + (int(dados['id']),)).rowcount
            if not n:
                raise ErroFinancas("Conta não encontrada.")
            conta_id = int(dados['id'])
        else:
            ordem = conn.execute('SELECT COALESCE(MAX(ordem), 0) + 1 FROM contas').fetchone()[0]
            conta_id = conn.execute("""INSERT INTO contas (nome, tipo, instituicao, saldo_inicial, limite, dia_fechamento,
                                       dia_vencimento, dono_id, ativa, ordem, criada_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                    valores + (ordem, _agora())).lastrowid
        conn.commit()
        return _conta_dict(conn.execute('SELECT * FROM contas WHERE id = ?', (conta_id,)).fetchone())
    finally:
        conn.close()


def apagar_conta(conta_id):
    """Conta com lançamentos não some: só fica desativada (o histórico continua certo)."""
    conn = _conectar()
    try:
        usada = conn.execute('SELECT 1 FROM lancamentos WHERE conta_id = ? OR conta_destino_id = ? LIMIT 1',
                             (conta_id, conta_id)).fetchone()
        if usada:
            conn.execute('UPDATE contas SET ativa = 0 WHERE id = ?', (conta_id,))
            resultado = 'desativada'
        else:
            conn.execute('DELETE FROM contas WHERE id = ?', (conta_id,))
            resultado = 'apagada'
        conn.commit()
        return {'ok': True, 'resultado': resultado}
    finally:
        conn.close()


def saldos_contas(ate=None):
    """Saldo de cada conta ativa até a data (cartão: negativo = quanto está devendo)."""
    ate = (_como_data(ate, obrigatorio=False) or date.today()).isoformat()
    conn = _conectar()
    try:
        linhas = conn.execute("""
            SELECT c.id,
                   c.saldo_inicial
                   + COALESCE((SELECT SUM(CASE l.tipo WHEN 'receita' THEN l.valor ELSE -l.valor END)
                               FROM lancamentos l WHERE l.conta_id = c.id AND l.data <= ?), 0)
                   + COALESCE((SELECT SUM(l.valor) FROM lancamentos l
                               WHERE l.conta_destino_id = c.id AND l.tipo = 'transferencia' AND l.data <= ?), 0) AS saldo
            FROM contas c WHERE c.ativa = 1""", (ate, ate)).fetchall()
        return {r['id']: reais(r['saldo']) for r in linhas}
    finally:
        conn.close()


# ==============================================================================
# == Categorias =================================================================
# ==============================================================================

def listar_categorias(incluir_inativas=False):
    """Lista plana com 'caminho' (ex.: 'Mercado › Carnes e peixes'), pais antes das filhas."""
    conn = _conectar()
    try:
        linhas = conn.execute('SELECT * FROM categorias' + ('' if incluir_inativas else ' WHERE ativa = 1')).fetchall()
    finally:
        conn.close()
    pais = sorted([r for r in linhas if not r['pai_id']], key=lambda r: (r['tipo'] != 'despesa', r['ordem'], r['nome']))
    resultado = []
    for p in pais:
        resultado.append({'id': p['id'], 'nome': p['nome'], 'tipo': p['tipo'], 'pai_id': None, 'caminho': p['nome'],
                          'ativa': bool(p['ativa'])})
        filhas = sorted([r for r in linhas if r['pai_id'] == p['id']], key=lambda r: (r['ordem'], r['nome']))
        for f in filhas:
            resultado.append({'id': f['id'], 'nome': f['nome'], 'tipo': f['tipo'], 'pai_id': p['id'],
                              'caminho': f"{p['nome']} › {f['nome']}", 'ativa': bool(f['ativa'])})
    return resultado


def salvar_categoria(dados):
    nome = str(dados.get('nome') or '').strip()[:50]
    if not nome:
        raise ErroFinancas("Dê um nome para a categoria.")
    conn = _conectar()
    try:
        pai_id = int(dados['pai_id']) if dados.get('pai_id') else None
        if pai_id:
            pai = conn.execute('SELECT * FROM categorias WHERE id = ?', (pai_id,)).fetchone()
            if not pai:
                raise ErroFinancas("Categoria principal não encontrada.")
            if pai['pai_id']:
                raise ErroFinancas("Só dá para ter dois níveis (categoria › subcategoria).")
            tipo = pai['tipo']
        else:
            tipo = dados.get('tipo') or 'despesa'
            if tipo not in ('despesa', 'receita'):
                raise ErroFinancas("Tipo de categoria inválido.")
        if dados.get('id'):
            cat_id = int(dados['id'])
            if pai_id == cat_id:
                raise ErroFinancas("A categoria não pode ficar dentro dela mesma.")
            if pai_id and conn.execute('SELECT 1 FROM categorias WHERE pai_id = ? LIMIT 1', (cat_id,)).fetchone():
                raise ErroFinancas("Esta categoria tem subcategorias: ela não pode virar subcategoria.")
            n = conn.execute('UPDATE categorias SET nome = ?, pai_id = ?, tipo = ? WHERE id = ?',
                             (nome, pai_id, tipo, cat_id)).rowcount
            if not n:
                raise ErroFinancas("Categoria não encontrada.")
            conn.execute('UPDATE categorias SET tipo = ? WHERE pai_id = ?', (tipo, cat_id))
        else:
            repetida = conn.execute('SELECT 1 FROM categorias WHERE nome = ? AND tipo = ? AND COALESCE(pai_id, 0) = ? AND ativa = 1',
                                    (nome, tipo, pai_id or 0)).fetchone()
            if repetida:
                raise ErroFinancas("Já existe uma categoria com esse nome aqui.")
            ordem = conn.execute('SELECT COALESCE(MAX(ordem), 0) + 1 FROM categorias WHERE COALESCE(pai_id, 0) = ?',
                                 (pai_id or 0,)).fetchone()[0]
            cat_id = conn.execute('INSERT INTO categorias (nome, tipo, pai_id, ordem) VALUES (?, ?, ?, ?)',
                                  (nome, tipo, pai_id, ordem)).lastrowid
        conn.commit()
        return {'id': cat_id}
    finally:
        conn.close()


def apagar_categoria(cat_id):
    """Desativa a categoria (e as subcategorias). Os lançamentos antigos continuam com ela."""
    conn = _conectar()
    try:
        conn.execute('UPDATE categorias SET ativa = 0 WHERE id = ? OR pai_id = ?', (cat_id, cat_id))
        conn.execute('DELETE FROM regras WHERE categoria_id IN (SELECT id FROM categorias WHERE id = ? OR pai_id = ?)',
                     (cat_id, cat_id))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


def _categoria_por_caminho(conn, caminho, tipo='despesa'):
    """'Mercado/Carnes e peixes' -> id (ou None se a pessoa renomeou/apagou)."""
    partes = caminho.split('/', 1)
    pai = conn.execute('SELECT id FROM categorias WHERE nome = ? AND tipo = ? AND pai_id IS NULL AND ativa = 1',
                       (partes[0], tipo)).fetchone()
    if not pai or len(partes) == 1:
        return pai['id'] if pai else None
    filha = conn.execute('SELECT id FROM categorias WHERE nome = ? AND pai_id = ? AND ativa = 1', (partes[1], pai['id'])).fetchone()
    return filha['id'] if filha else None


def _categoria_valida(conn, cat_id, tipo):
    if not cat_id:
        return None
    r = conn.execute('SELECT tipo FROM categorias WHERE id = ?', (int(cat_id),)).fetchone()
    if not r:
        raise ErroFinancas("Categoria não encontrada.")
    if r['tipo'] != tipo:
        raise ErroFinancas("Essa categoria é de " + ('receita' if r['tipo'] == 'receita' else 'gasto') + ".")
    return int(cat_id)


# ==============================================================================
# == Aprender categorias ========================================================
# ==============================================================================

def _aprender(conn, tipo, padrao, categoria_id):
    if not padrao or not categoria_id:
        return
    conn.execute("""INSERT INTO regras (tipo, padrao, categoria_id, usos, atualizado_em) VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(tipo, padrao) DO UPDATE SET
                        usos = CASE WHEN regras.categoria_id = excluded.categoria_id THEN regras.usos + 1 ELSE 1 END,
                        categoria_id = excluded.categoria_id, atualizado_em = excluded.atualizado_em""",
                 (tipo, padrao, int(categoria_id), _agora()))


def _regra(conn, tipo, padrao):
    if not padrao:
        return None
    r = conn.execute("""SELECT r.categoria_id FROM regras r JOIN categorias c ON c.id = r.categoria_id
                        WHERE r.tipo = ? AND r.padrao = ? AND c.ativa = 1""", (tipo, padrao)).fetchone()
    return r['categoria_id'] if r else None


def _por_palavras(texto_normalizado, tabela):
    """Acha a categoria pela 1ª palavra-chave encontrada (as mais longas primeiro)."""
    pares = sorted(((p, cat) for cat, palavras in tabela.items() for p in palavras), key=lambda x: -len(x[0]))
    texto = ' ' + texto_normalizado + ' '
    for palavra, cat in pares:
        if re.search(r'(?<![A-Z0-9])' + re.escape(palavra.strip()) + (r'(?![A-Z0-9])' if palavra.endswith(' ') else ''), texto):
            return cat
    return None


def sugerir_categoria(descricao, tipo='despesa'):
    """Sugestão para o formulário de lançamento (o que foi usado antes com a mesma descrição)."""
    conn = _conectar()
    try:
        cat = _regra(conn, 'descricao', chave_descricao(descricao))
        if cat is None and tipo == 'despesa':
            caminho = _por_palavras(normalizar(descricao), PALAVRAS_ESTABELECIMENTO)
            cat = _categoria_por_caminho(conn, caminho) if caminho else None
        return {'categoria_id': cat}
    finally:
        conn.close()


# ==============================================================================
# == Lançamentos ================================================================
# ==============================================================================

def _lanc_dict(r, partes=None):
    d = {'id': r['id'], 'tipo': r['tipo'], 'data': r['data'], 'descricao': r['descricao'], 'valor': reais(r['valor']),
         'conta_id': r['conta_id'], 'conta_destino_id': r['conta_destino_id'], 'categoria_id': r['categoria_id'],
         'pessoa_id': r['pessoa_id'], 'observacao': r['observacao'] or '', 'cupom_id': r['cupom_id'],
         'grupo_parcela': r['grupo_parcela'], 'parcela': r['parcela'], 'parcelas': r['parcelas'], 'origem': r['origem']}
    if partes is not None:
        d['partes'] = [{'categoria_id': p['categoria_id'], 'valor': reais(p['valor'])} for p in partes]
    return d


def _validar_lancamento(conn, dados):
    tipo = dados.get('tipo') or 'despesa'
    if tipo not in TIPOS_LANCAMENTO:
        raise ErroFinancas("Tipo de lançamento inválido.")
    conta_id = int(dados.get('conta_id') or 0)
    conta = conn.execute('SELECT * FROM contas WHERE id = ?', (conta_id,)).fetchone()
    if not conta:
        raise ErroFinancas("Escolha a conta ou cartão." if tipo != 'transferencia' else "Escolha a conta de origem.")
    destino = None
    categoria = None
    if tipo == 'transferencia':
        destino = int(dados.get('conta_destino_id') or 0)
        if not conn.execute('SELECT 1 FROM contas WHERE id = ?', (destino,)).fetchone():
            raise ErroFinancas("Escolha a conta de destino.")
        if destino == conta_id:
            raise ErroFinancas("A conta de origem e a de destino são a mesma.")
    else:
        categoria = _categoria_valida(conn, dados.get('categoria_id'), tipo)
        if not categoria:
            raise ErroFinancas("Escolha a categoria.")
    pessoa = dados.get('pessoa_id')
    pessoa = int(pessoa) if pessoa not in (None, '', 0, '0') else None
    if pessoa and not conn.execute('SELECT 1 FROM usuarios WHERE id = ?', (pessoa,)).fetchone():
        raise ErroFinancas("Pessoa não encontrada.")
    descricao = str(dados.get('descricao') or '').strip()[:120]
    if not descricao:
        if tipo == 'transferencia':
            descricao = 'Transferência'
        else:
            raise ErroFinancas("Escreva uma descrição (ex.: Mercado Comper, Gasolina).")
    return {'tipo': tipo, 'data': _como_data(dados.get('data')), 'descricao': descricao,
            'valor': para_centavos(dados.get('valor')), 'conta_id': conta_id, 'conta_destino_id': destino,
            'categoria_id': categoria, 'pessoa_id': pessoa,
            'observacao': str(dados.get('observacao') or '').strip()[:500] or None}


def criar_lancamento(dados, usuario):
    """
    Cria o lançamento. Com 'parcelas' > 1 (só gasto), cria uma parcela por mês com
    o valor dividido (o centavo que sobrar vai na 1ª). 'valor' é o TOTAL da compra.
    Devolve a lista dos lançamentos criados.
    """
    conn = _conectar()
    try:
        v = _validar_lancamento(conn, dados)
        try:
            parcelas = int(dados.get('parcelas') or 1)
        except (TypeError, ValueError):
            raise ErroFinancas("Número de parcelas inválido.")
        if parcelas < 1 or parcelas > MAX_PARCELAS:
            raise ErroFinancas(f"Parcelas: de 1 a {MAX_PARCELAS}.")
        if parcelas > 1 and v['tipo'] != 'despesa':
            raise ErroFinancas("Só gasto pode ser parcelado.")
        if parcelas > 1 and v['valor'] < parcelas:
            raise ErroFinancas("Valor pequeno demais para tantas parcelas.")
        grupo = uuid.uuid4().hex[:16] if parcelas > 1 else None
        base, resto = divmod(v['valor'], parcelas)
        ids = []
        agora = _agora()
        for n in range(1, parcelas + 1):
            valor = base + (resto if n == 1 else 0)
            ids.append(conn.execute("""
                INSERT INTO lancamentos (tipo, data, descricao, valor, conta_id, conta_destino_id, categoria_id, pessoa_id,
                                         observacao, grupo_parcela, parcela, parcelas, origem, criado_por, criado_em, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?, ?)""",
                (v['tipo'], somar_meses(v['data'], n - 1).isoformat(), v['descricao'], valor, v['conta_id'],
                 v['conta_destino_id'], v['categoria_id'], v['pessoa_id'], v['observacao'], grupo,
                 n if grupo else None, parcelas if grupo else None, usuario.get('id'), agora, agora)).lastrowid)
        if v['tipo'] != 'transferencia':
            _aprender(conn, 'descricao', chave_descricao(v['descricao']), v['categoria_id'])
        conn.commit()
        return [obter_lancamento(i, conn) for i in ids]
    finally:
        conn.close()


def obter_lancamento(lanc_id, conn=None):
    proprio = conn is None
    conn = conn or _conectar()
    try:
        r = conn.execute('SELECT * FROM lancamentos WHERE id = ?', (int(lanc_id),)).fetchone()
        if not r:
            raise ErroFinancas("Lançamento não encontrado.")
        partes = conn.execute('SELECT * FROM lancamento_partes WHERE lancamento_id = ? ORDER BY valor DESC', (r['id'],)).fetchall()
        return _lanc_dict(r, partes)
    finally:
        if proprio:
            conn.close()


def alterar_lancamento(lanc_id, dados, usuario, todas_parcelas=False):
    """
    Altera um lançamento. Em compra parcelada, 'todas_parcelas' muda descrição, conta,
    categoria e pessoa de todas as parcelas (valor e data mudam só nesta).
    """
    conn = _conectar()
    try:
        atual = conn.execute('SELECT * FROM lancamentos WHERE id = ?', (int(lanc_id),)).fetchone()
        if not atual:
            raise ErroFinancas("Lançamento não encontrado.")
        v = _validar_lancamento(conn, dict(dados, tipo=atual['tipo'] if atual['cupom_id'] else dados.get('tipo')))
        agora = _agora()
        conn.execute("""UPDATE lancamentos SET tipo = ?, data = ?, descricao = ?, valor = ?, conta_id = ?, conta_destino_id = ?,
                        categoria_id = ?, pessoa_id = ?, observacao = ?, atualizado_em = ? WHERE id = ?""",
                     (v['tipo'], v['data'].isoformat(), v['descricao'], v['valor'], v['conta_id'], v['conta_destino_id'],
                      v['categoria_id'], v['pessoa_id'], v['observacao'], agora, atual['id']))
        if todas_parcelas and atual['grupo_parcela']:
            conn.execute("""UPDATE lancamentos SET descricao = ?, conta_id = ?, categoria_id = ?, pessoa_id = ?, atualizado_em = ?
                            WHERE grupo_parcela = ? AND id <> ?""",
                         (v['descricao'], v['conta_id'], v['categoria_id'], v['pessoa_id'], agora,
                          atual['grupo_parcela'], atual['id']))
        if v['tipo'] == 'despesa' and atual['cupom_id']:
            _recalcular_partes(conn, atual['cupom_id'])
        elif v['tipo'] != 'despesa':
            conn.execute('DELETE FROM lancamento_partes WHERE lancamento_id = ?', (atual['id'],))
        if v['tipo'] != 'transferencia' and v['categoria_id'] != atual['categoria_id']:
            _aprender(conn, 'descricao', chave_descricao(v['descricao']), v['categoria_id'])
        conn.commit()
        return obter_lancamento(atual['id'], conn)
    finally:
        conn.close()


def apagar_lancamento(lanc_id, todas_parcelas=False):
    """Apaga. Se veio de um cupom, o cupom volta para 'pendente' (dá para lançar de novo)."""
    conn = _conectar()
    try:
        atual = conn.execute('SELECT * FROM lancamentos WHERE id = ?', (int(lanc_id),)).fetchone()
        if not atual:
            raise ErroFinancas("Lançamento não encontrado.")
        if atual['cupom_id']:
            # as parcelas de um cupom andam juntas: apagar uma apaga o lançamento do cupom inteiro
            alvos = [r['id'] for r in conn.execute('SELECT id FROM lancamentos WHERE cupom_id = ?', (atual['cupom_id'],))]
        elif todas_parcelas and atual['grupo_parcela']:
            alvos = [r['id'] for r in conn.execute('SELECT id FROM lancamentos WHERE grupo_parcela = ?', (atual['grupo_parcela'],))]
        else:
            alvos = [atual['id']]
        for i in alvos:
            conn.execute('DELETE FROM lancamentos WHERE id = ?', (i,))
        if atual['cupom_id']:
            conn.execute('UPDATE cupons SET status = ? WHERE id = ?', (CUP_PENDENTE, atual['cupom_id']))
        conn.commit()
        return {'ok': True, 'apagados': len(alvos)}
    finally:
        conn.close()


def listar_lancamentos(mes=None, conta_id=None, categoria_id=None, pessoa_id=None, busca=None, tipo=None):
    inicio, fim = _intervalo_mes(mes)
    sql = ['SELECT l.* FROM lancamentos l WHERE l.data BETWEEN ? AND ?']
    args = [inicio.isoformat(), fim.isoformat()]
    if conta_id:
        sql.append('AND (l.conta_id = ? OR l.conta_destino_id = ?)')
        args += [int(conta_id), int(conta_id)]
    if categoria_id:
        # a categoria principal pega as subcategorias também; e vale a divisão do cupom
        sql.append("""AND (l.categoria_id IN (SELECT id FROM categorias WHERE id = ? OR pai_id = ?)
                     OR l.id IN (SELECT lancamento_id FROM lancamento_partes
                                 WHERE categoria_id IN (SELECT id FROM categorias WHERE id = ? OR pai_id = ?)))""")
        args += [int(categoria_id)] * 4
    if pessoa_id == 'casa':
        sql.append('AND l.pessoa_id IS NULL')
    elif pessoa_id:
        sql.append('AND l.pessoa_id = ?')
        args.append(int(pessoa_id))
    if tipo in TIPOS_LANCAMENTO:
        sql.append('AND l.tipo = ?')
        args.append(tipo)
    if busca:
        sql.append("""AND (l.descricao LIKE ? OR l.observacao LIKE ?
                     OR l.cupom_id IN (SELECT cupom_id FROM cupom_itens WHERE descricao LIKE ?))""")
        termo = f"%{str(busca).strip()}%"
        args += [termo, termo, termo]
    sql.append('ORDER BY l.data DESC, l.id DESC')
    conn = _conectar()
    try:
        linhas = conn.execute(' '.join(sql), args).fetchall()
        ids = [r['id'] for r in linhas]
        partes = {}
        if ids:
            marcas = ','.join('?' * len(ids))
            for p in conn.execute(f'SELECT * FROM lancamento_partes WHERE lancamento_id IN ({marcas}) ORDER BY valor DESC', ids):
                partes.setdefault(p['lancamento_id'], []).append(p)
        return [_lanc_dict(r, partes.get(r['id'], [])) for r in linhas]
    finally:
        conn.close()


# ==============================================================================
# == Resumo do mês (painel) ====================================================
# ==============================================================================

def _gastos_por_categoria(conn, inicio, fim, pessoa_id=None):
    """{categoria_id: centavos} dos gastos do período, já com a divisão dos cupons."""
    filtro, args = '', [inicio.isoformat(), fim.isoformat()]
    if pessoa_id == 'casa':
        filtro = 'AND l.pessoa_id IS NULL'
    elif pessoa_id:
        filtro, args = 'AND l.pessoa_id = ?', args + [int(pessoa_id)]
    linhas = conn.execute(f"""
        SELECT COALESCE(p.categoria_id, l.categoria_id) AS cat, SUM(COALESCE(p.valor, l.valor)) AS total
        FROM lancamentos l LEFT JOIN lancamento_partes p ON p.lancamento_id = l.id
        WHERE l.tipo = 'despesa' AND l.data BETWEEN ? AND ? {filtro}
        GROUP BY COALESCE(p.categoria_id, l.categoria_id)""", args).fetchall()
    return {r['cat']: r['total'] for r in linhas}


def resumo_mes(mes=None, pessoa_id=None):
    """
    Painel do mês: entradas, saídas, saldo, gastos por categoria (com subcategorias e a
    média dos 3 meses anteriores), gastos por pessoa e saldo das contas.
    Transferências (ex.: pagar a fatura) NÃO contam como gasto: o gasto já foi
    contado no dia da compra no cartão.
    """
    inicio, fim = _intervalo_mes(mes)
    conn = _conectar()
    try:
        filtro, args = '', [inicio.isoformat(), fim.isoformat()]
        if pessoa_id == 'casa':
            filtro = 'AND pessoa_id IS NULL'
        elif pessoa_id:
            filtro, args = 'AND pessoa_id = ?', args + [int(pessoa_id)]
        tot = conn.execute(f"""SELECT
                COALESCE(SUM(CASE WHEN tipo = 'receita' THEN valor END), 0) AS entradas,
                COALESCE(SUM(CASE WHEN tipo = 'despesa' THEN valor END), 0) AS saidas,
                COUNT(CASE WHEN tipo = 'despesa' THEN 1 END) AS qtd_gastos
            FROM lancamentos WHERE data BETWEEN ? AND ? {filtro}""", args).fetchone()
        atual = _gastos_por_categoria(conn, inicio, fim, pessoa_id)
        ini_ant = somar_meses(inicio, -3)
        anteriores = _gastos_por_categoria(conn, ini_ant, inicio - timedelta(days=1), pessoa_id)
        cats = {r['id']: r for r in conn.execute('SELECT * FROM categorias')}
        por_pessoa = conn.execute("""SELECT pessoa_id, SUM(valor) AS total FROM lancamentos
                                     WHERE tipo = 'despesa' AND data BETWEEN ? AND ? GROUP BY pessoa_id""",
                                  (inicio.isoformat(), fim.isoformat())).fetchall()
        nomes = {r['id']: r['nome'] for r in conn.execute('SELECT id, nome FROM usuarios')}
    finally:
        conn.close()

    grupos = {}
    def somar(destino, cat_id, valor, chave):
        c = cats.get(cat_id)
        pai_id = (c['pai_id'] or c['id']) if c else 0
        pai = cats.get(pai_id)
        g = destino.setdefault(pai_id, {'categoria_id': pai_id or None, 'nome': pai['nome'] if pai else 'Sem categoria',
                                         'total': 0, 'media_3m': 0, 'subs': {}})
        g[chave] += valor
        sub_id = cat_id if c and c['pai_id'] else None
        if sub_id:
            s = g['subs'].setdefault(sub_id, {'categoria_id': sub_id, 'nome': c['nome'], 'total': 0, 'media_3m': 0})
            s[chave] += valor
    for cat_id, valor in atual.items():
        somar(grupos, cat_id, valor, 'total')
    for cat_id, valor in anteriores.items():
        somar(grupos, cat_id, valor, 'media_3m')

    categorias = []
    for g in grupos.values():
        subs = sorted(g['subs'].values(), key=lambda s: -s['total'])
        categorias.append({'categoria_id': g['categoria_id'], 'nome': g['nome'], 'total': reais(g['total']),
                           'media_3m': reais(round(g['media_3m'] / 3)),
                           'subs': [{'categoria_id': s['categoria_id'], 'nome': s['nome'], 'total': reais(s['total']),
                                     'media_3m': reais(round(s['media_3m'] / 3))} for s in subs if s['total'] or s['media_3m']]})
    categorias.sort(key=lambda g: (-g['total'], -g['media_3m']))

    saldos = saldos_contas(min(fim, date.today()) if fim >= date.today() >= inicio else fim)
    contas = [dict(c, saldo=saldos.get(c['id'], 0)) for c in listar_contas()]
    return {
        'mes': inicio.strftime('%Y-%m'),
        'entradas': reais(tot['entradas']), 'saidas': reais(tot['saidas']),
        'resultado': reais(tot['entradas'] - tot['saidas']), 'qtd_gastos': tot['qtd_gastos'],
        'categorias': categorias,
        'por_pessoa': [{'pessoa_id': r['pessoa_id'], 'nome': nomes.get(r['pessoa_id'], 'Casa (família)'),
                        'total': reais(r['total'])} for r in sorted(por_pessoa, key=lambda r: -r['total'])],
        'contas': contas,
    }


# ==============================================================================
# == Cupom fiscal (QR Code da NFC-e) ===========================================
# ==============================================================================
# A leitura da página da SEFAZ é a MESMA do app de compras da loja (compras_cupom.py,
# já testada com os cupons de MT). Aqui só guardamos o resultado no banco da família.

def _leitor_sefaz():
    try:
        import compras_cupom
        return compras_cupom
    except Exception as e:
        logger.error(f"Finanças: não consegui carregar o leitor de cupom (compras_cupom.py): {e}")
        raise ErroFinancas("A leitura de cupom não está funcionando no servidor (veja o log do servidor).")


def _erro_do_leitor(leitor, e):
    """Transforma o erro do leitor da loja em erro do app de finanças (mesma mensagem)."""
    if isinstance(e, getattr(leitor, 'ErroCompras', ())):
        return ErroFinancas(str(e))
    return None


def ler_qr_da_foto(foto):
    leitor = _leitor_sefaz()
    try:
        return leitor.ler_qr_da_foto(foto)
    except Exception as e:
        erro = _erro_do_leitor(leitor, e)
        if erro:
            raise erro
        raise


def _ler_pagina_sefaz(leitor, chave, url, html=None):
    """Baixa e entende a página. Devolve (pagina, None) ou (None, mensagem_de_erro)."""
    try:
        pagina_html = html if html is not None else leitor.baixar_pagina(url)
        try:
            pagina = leitor.interpretar_pagina(pagina_html)
        except Exception:
            leitor.guardar_para_diagnostico(chave, pagina_html)
            raise
        if pagina['chave_pagina'] and pagina['chave_pagina'] != chave:
            return None, "A página da SEFAZ mostrou outro cupom. Tente ler de novo."
        return pagina, None
    except Exception as e:
        erro = _erro_do_leitor(leitor, e)
        if erro is None:
            raise
        return None, str(erro)


def _cent_dec(valor):
    return None if valor is None else int((Decimal(valor) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _categorizar_itens(conn, cupom_id):
    """Dá uma categoria a cada item que ainda não tem: aprendido > palavra-chave > estabelecimento."""
    geral = conn.execute('SELECT categoria_id FROM cupons WHERE id = ?', (cupom_id,)).fetchone()['categoria_id']
    for it in conn.execute('SELECT * FROM cupom_itens WHERE cupom_id = ? AND categoria_id IS NULL', (cupom_id,)).fetchall():
        cat, origem = _regra(conn, 'item', chave_item(it['descricao'])), 'aprendido'
        if cat is None:
            caminho = _por_palavras(normalizar(it['descricao']), PALAVRAS_ITEM)
            cat, origem = (_categoria_por_caminho(conn, caminho) if caminho else None), 'palavra'
        if cat is None:
            cat, origem = geral, 'estabelecimento'
        conn.execute('UPDATE cupom_itens SET categoria_id = ?, categoria_origem = ? WHERE cupom_id = ? AND seq = ?',
                     (cat, origem if cat else None, cupom_id, it['seq']))


def _gravar_pagina(conn, cupom_id, pagina):
    emitente = (pagina['emitente_nome'] or '').strip()
    geral = _regra(conn, 'descricao', chave_descricao(emitente))
    if geral is None:
        caminho = _por_palavras(normalizar(emitente), PALAVRAS_ESTABELECIMENTO) or 'Mercado'
        geral = _categoria_por_caminho(conn, caminho)
    conn.execute("""UPDATE cupons SET emitente = ?, cnpj = COALESCE(NULLIF(?, ''), cnpj), data_emissao = ?, valor_total = ?,
                    descontos = ?, valor_pagar = ?, categoria_id = ?, status = ?, erro = NULL WHERE id = ?""",
                 (emitente[:150], pagina['emitente_cnpj'],
                  pagina['data_emissao'].strftime('%Y-%m-%d %H:%M:%S') if pagina['data_emissao'] else None,
                  _cent_dec(pagina['valor_total']), _cent_dec(pagina['descontos']), _cent_dec(pagina['valor_pagar']),
                  geral, CUP_PENDENTE, cupom_id))
    conn.execute('DELETE FROM cupom_itens WHERE cupom_id = ?', (cupom_id,))
    for it in pagina['itens']:
        conn.execute("""INSERT INTO cupom_itens (cupom_id, seq, descricao, codigo, qtd, unidade, valor_unit, valor_total)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                     (cupom_id, it['seq'], it['descricao'][:150], (it.get('codigo') or '')[:60] or None,
                      float(it['qtd']) if it['qtd'] is not None else None, it.get('unidade'),
                      float(it['valor_unit']) if it.get('valor_unit') is not None else None, _cent_dec(it['valor_total'])))
    _categorizar_itens(conn, cupom_id)


def registrar_cupom(texto_qr, usuario, html=None):
    """
    Guarda o cupom lido e os itens da página da SEFAZ. Ler o mesmo QR de novo não
    duplica (e, se tinha dado erro, tenta a SEFAZ outra vez). 'html' é só para testes.
    """
    leitor = _leitor_sefaz()
    try:
        chave, url = leitor.extrair_chave(texto_qr)
        info = leitor.dados_da_chave(chave)
        if info['modelo'] not in ('65', '55'):
            raise ErroFinancas("Este QR Code não é de nota fiscal.")
        if not url:
            raise ErroFinancas("Só a chave não basta: a SEFAZ pede o QR Code completo. Leia o QR Code do cupom.")
        leitor.endereco_seguro(url)
    except ErroFinancas:
        raise
    except Exception as e:
        erro = _erro_do_leitor(leitor, e)
        if erro:
            raise erro
        raise
    conn = _conectar()
    try:
        existente = conn.execute('SELECT id, status FROM cupons WHERE chave = ?', (chave,)).fetchone()
    finally:
        conn.close()
    if existente:
        if existente['status'] == CUP_ERRO:
            return tentar_cupom_de_novo(existente['id'], html=html)
        return dict(obter_cupom(existente['id']), ja_existia=True)

    pagina, erro = _ler_pagina_sefaz(leitor, chave, url, html)
    conn = _conectar()
    try:
        cupom_id = conn.execute("""INSERT INTO cupons (chave, url, cnpj, numero, serie, status, erro, lido_por, lido_em)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (chave, url[:600], info['cnpj'], info['numero'], info['serie'],
                                 CUP_ERRO if erro else CUP_PENDENTE, erro, usuario.get('id'), _agora())).lastrowid
        if pagina:
            _gravar_pagina(conn, cupom_id, pagina)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Finanças: cupom {chave} lido por {usuario.get('nome')}: {erro or 'ok'}")
    return obter_cupom(cupom_id)


def tentar_cupom_de_novo(cupom_id, html=None):
    leitor = _leitor_sefaz()
    conn = _conectar()
    try:
        c = conn.execute('SELECT * FROM cupons WHERE id = ?', (int(cupom_id),)).fetchone()
    finally:
        conn.close()
    if not c:
        raise ErroFinancas("Cupom não encontrado.")
    if c['status'] != CUP_ERRO:
        return obter_cupom(c['id'])
    pagina, erro = _ler_pagina_sefaz(leitor, c['chave'], c['url'], html)
    conn = _conectar()
    try:
        if pagina:
            _gravar_pagina(conn, c['id'], pagina)
        else:
            conn.execute('UPDATE cupons SET erro = ? WHERE id = ?', (erro, c['id']))
        conn.commit()
    finally:
        conn.close()
    return obter_cupom(c['id'])


def _cupom_dict(c, itens, lanc):
    return {'id': c['id'], 'chave': c['chave'], 'emitente': c['emitente'] or '', 'cnpj': c['cnpj'] or '',
            'numero': c['numero'], 'data_emissao': c['data_emissao'], 'valor_total': reais(c['valor_total']),
            'descontos': reais(c['descontos']), 'valor_pagar': reais(c['valor_pagar']),
            'categoria_id': c['categoria_id'], 'status': c['status'], 'erro': c['erro'] or '', 'lido_em': c['lido_em'],
            'lancamento': lanc,
            'itens': [{'seq': i['seq'], 'descricao': i['descricao'], 'codigo': i['codigo'] or '', 'qtd': i['qtd'],
                       'unidade': i['unidade'] or '', 'valor_unit': i['valor_unit'], 'valor_total': reais(i['valor_total']),
                       'categoria_id': i['categoria_id'], 'categoria_origem': i['categoria_origem']} for i in itens]}


def obter_cupom(cupom_id):
    conn = _conectar()
    try:
        c = conn.execute('SELECT * FROM cupons WHERE id = ?', (int(cupom_id),)).fetchone()
        if not c:
            raise ErroFinancas("Cupom não encontrado.")
        itens = conn.execute('SELECT * FROM cupom_itens WHERE cupom_id = ? ORDER BY seq', (c['id'],)).fetchall()
        l = conn.execute('SELECT * FROM lancamentos WHERE cupom_id = ? ORDER BY id LIMIT 1', (c['id'],)).fetchone()
        return _cupom_dict(c, itens, _lanc_dict(l) if l else None)
    finally:
        conn.close()


def listar_cupons(dias=90):
    desde = (datetime.now() - timedelta(days=int(dias or 90))).strftime('%Y-%m-%d')
    conn = _conectar()
    try:
        linhas = conn.execute("""SELECT c.*, (SELECT COUNT(*) FROM cupom_itens i WHERE i.cupom_id = c.id) AS qtd_itens
                                 FROM cupons c WHERE c.lido_em >= ? OR c.status <> ?
                                 ORDER BY c.lido_em DESC""", (desde, CUP_LANCADO)).fetchall()
        return [{'id': c['id'], 'emitente': c['emitente'] or '', 'data_emissao': c['data_emissao'],
                 'valor_pagar': reais(c['valor_pagar']), 'status': c['status'], 'erro': c['erro'] or '',
                 'qtd_itens': c['qtd_itens'], 'lido_em': c['lido_em']} for c in linhas]
    finally:
        conn.close()


def mudar_categoria_item(cupom_id, seq, categoria_id, aplicar_iguais=True):
    """
    Troca a categoria de um item e APRENDE (da próxima vez o mesmo produto já vem certo).
    Com 'aplicar_iguais', os outros itens iguais deste cupom mudam junto. Se o cupom já
    foi lançado, a divisão do lançamento é refeita na hora.
    """
    conn = _conectar()
    try:
        categoria_id = _categoria_valida(conn, categoria_id, 'despesa')
        if not categoria_id:
            raise ErroFinancas("Escolha a categoria.")
        it = conn.execute('SELECT * FROM cupom_itens WHERE cupom_id = ? AND seq = ?', (int(cupom_id), int(seq))).fetchone()
        if not it:
            raise ErroFinancas("Item não encontrado.")
        chave = chave_item(it['descricao'])
        alvos = [it['seq']]
        if aplicar_iguais and chave:
            alvos = [i['seq'] for i in conn.execute('SELECT seq, descricao FROM cupom_itens WHERE cupom_id = ?', (it['cupom_id'],))
                     if chave_item(i['descricao']) == chave]
        for s in alvos:
            conn.execute("UPDATE cupom_itens SET categoria_id = ?, categoria_origem = 'manual' WHERE cupom_id = ? AND seq = ?",
                         (categoria_id, it['cupom_id'], s))
        _aprender(conn, 'item', chave, categoria_id)
        _recalcular_partes(conn, it['cupom_id'])
        conn.commit()
    finally:
        conn.close()
    return obter_cupom(cupom_id)


def mudar_categoria_geral(cupom_id, categoria_id):
    """Categoria 'geral' do cupom: vai para os itens que vieram do estabelecimento (não aprendidos)."""
    conn = _conectar()
    try:
        categoria_id = _categoria_valida(conn, categoria_id, 'despesa')
        c = conn.execute('SELECT * FROM cupons WHERE id = ?', (int(cupom_id),)).fetchone()
        if not c:
            raise ErroFinancas("Cupom não encontrado.")
        conn.execute('UPDATE cupons SET categoria_id = ? WHERE id = ?', (categoria_id, c['id']))
        conn.execute("""UPDATE cupom_itens SET categoria_id = ? WHERE cupom_id = ?
                        AND (categoria_origem = 'estabelecimento' OR categoria_id IS NULL)""", (categoria_id, c['id']))
        conn.execute("UPDATE cupom_itens SET categoria_origem = 'estabelecimento' WHERE cupom_id = ? AND categoria_origem IS NULL",
                     (c['id'],))
        if c['emitente']:
            _aprender(conn, 'descricao', chave_descricao(c['emitente']), categoria_id)
        _recalcular_partes(conn, c['id'])
        conn.commit()
    finally:
        conn.close()
    return obter_cupom(cupom_id)


def _partes_do_cupom(conn, cupom_id, total):
    """Divide o valor pago entre as categorias dos itens (o desconto é dividido na proporção)."""
    somas = {}
    for it in conn.execute('SELECT categoria_id, valor_total FROM cupom_itens WHERE cupom_id = ?', (cupom_id,)):
        if it['categoria_id']:
            somas[it['categoria_id']] = somas.get(it['categoria_id'], 0) + (it['valor_total'] or 0)
    cats = list(somas)
    return dict(zip(cats, ratear(total, [somas[c] for c in cats])))


def _recalcular_partes(conn, cupom_id):
    """Refaz a divisão por categoria dos lançamentos deste cupom (depois de trocar categoria ou valor)."""
    for l in conn.execute("SELECT id, valor FROM lancamentos WHERE cupom_id = ? AND tipo = 'despesa'", (cupom_id,)).fetchall():
        partes = _partes_do_cupom(conn, cupom_id, l['valor'])
        conn.execute('DELETE FROM lancamento_partes WHERE lancamento_id = ?', (l['id'],))
        for cat, valor in partes.items():
            if valor:
                conn.execute('INSERT INTO lancamento_partes (lancamento_id, categoria_id, valor) VALUES (?, ?, ?)',
                             (l['id'], cat, valor))
        if partes:
            principal = max(partes, key=partes.get)
            conn.execute('UPDATE lancamentos SET categoria_id = ? WHERE id = ?', (principal, l['id']))


def lancar_cupom(cupom_id, dados, usuario):
    """
    Transforma o cupom em UM lançamento de gasto (valor pago, data da compra, nome da
    loja), dividido entre as categorias dos itens. 'dados': conta_id, pessoa_id,
    descricao (opcional) e parcelas (opcional, compra parcelada no cartão).
    """
    conn = _conectar()
    try:
        c = conn.execute('SELECT * FROM cupons WHERE id = ?', (int(cupom_id),)).fetchone()
        if not c:
            raise ErroFinancas("Cupom não encontrado.")
        if c['status'] == CUP_LANCADO:
            raise ErroFinancas("Este cupom já foi lançado.")
        if c['status'] == CUP_ERRO or not c['valor_pagar']:
            raise ErroFinancas("Este cupom ainda não foi lido da SEFAZ. Toque em 'Tentar de novo'.")
        if conn.execute('SELECT 1 FROM cupom_itens WHERE cupom_id = ? AND categoria_id IS NULL', (c['id'],)).fetchone():
            raise ErroFinancas("Tem item sem categoria. Escolha a categoria geral do cupom.")
        data = c['data_emissao'][:10] if c['data_emissao'] else (c['lido_em'] or _agora())[:10]
        descricao = str(dados.get('descricao') or '').strip() or (c['emitente'] or 'Compra com cupom').title()
        principal = max(_partes_do_cupom(conn, c['id'], c['valor_pagar']).items(), key=lambda x: x[1])[0]
    finally:
        conn.close()
    criados = criar_lancamento({'tipo': 'despesa', 'data': data, 'descricao': descricao[:120], 'valor': reais(c['valor_pagar']),
                                'conta_id': dados.get('conta_id'), 'categoria_id': principal, 'pessoa_id': dados.get('pessoa_id'),
                                'observacao': dados.get('observacao'), 'parcelas': dados.get('parcelas') or 1}, usuario)
    conn = _conectar()
    try:
        for l in criados:
            conn.execute("UPDATE lancamentos SET cupom_id = ?, origem = 'cupom' WHERE id = ?", (c['id'], l['id']))
        conn.execute('UPDATE cupons SET status = ? WHERE id = ?', (CUP_LANCADO, c['id']))
        _recalcular_partes(conn, c['id'])
        if c['emitente'] and c['categoria_id']:
            # a loja fica ligada à categoria GERAL do cupom (ex.: Comper -> Mercado), não à maior parte
            _aprender(conn, 'descricao', chave_descricao(descricao), c['categoria_id'])
        conn.commit()
    finally:
        conn.close()
    return obter_cupom(c['id'])


def apagar_cupom(cupom_id):
    conn = _conectar()
    try:
        if conn.execute('SELECT 1 FROM lancamentos WHERE cupom_id = ?', (int(cupom_id),)).fetchone():
            raise ErroFinancas("Este cupom já virou lançamento. Apague o lançamento primeiro.")
        conn.execute('DELETE FROM cupons WHERE id = ?', (int(cupom_id),))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


# ==============================================================================
# == Tudo que o app precisa ao abrir ===========================================
# ==============================================================================

def dados_iniciais():
    return {'usuarios': listar_usuarios(), 'contas': listar_contas(incluir_inativas=True),
            'categorias': listar_categorias(incluir_inativas=True), 'tipos_conta': TIPOS_CONTA}

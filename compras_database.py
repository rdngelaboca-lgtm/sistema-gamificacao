# ==============================================================================
# compras_database.py - BANCO DE DADOS DO APP DE COMPRAS (celular)
# ------------------------------------------------------------------------------
# O app do celular ajuda a fazer a lista de compras da sorveteria:
#   1) a pessoa escolhe uma ROTINA (ex.: "Mercado semanal") e para quantos dias comprar;
#   2) o app pergunta, item por item, quanto tem na loja (isso vira uma CONTAGEM DE
#      ESTOQUE normal, a mesma do Gestão de Estoque);
#   3) o sistema calcula quanto comprar com o consumo aprendido das contagens e das
#      notas XML, e indica o fornecedor mais barato de cada item;
#   4) no mercado, a pessoa marca o que pôs no carrinho e o que "não tinha".
#
# Este arquivo NÃO mexe nas tabelas antigas do sistema, a não ser para gravar a
# contagem (ContagensEstoque / ItensContagemEstoque), exatamente como o Gestão de
# Estoque faz. As tabelas novas começam com "Compra" e são criadas sozinhas na
# primeira vez que o app é usado.
#
# A compra NÃO é somada ao estoque por aqui: quem lança a compra (quantidade e preço)
# é a importação do XML no Gestão de Estoque. Se o app também somasse, a mesma compra
# entraria duas vezes.
# ==============================================================================

import hashlib
import hmac
import json
import logging
import math
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import database
from database import get_db_connection, _como_data, _dec

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Regras que você pode ajustar
# ------------------------------------------------------------------------------
PIN_TAMANHO = 4                 # PIN de 4 dígitos
PIN_MAX_ERROS = 5               # depois de 5 erros seguidos o usuário fica bloqueado...
PIN_BLOQUEIO_MINUTOS = 15       # ...por 15 minutos (impede "chutar" o PIN pela internet)
PRECO_VALIDO_DIAS = 365         # preços mais velhos que isso não entram na comparação
DIAS_COBERTURA_MAX = 90
UNIDADES_FRACIONADAS = {'KG', 'G', 'GR', 'L', 'LT', 'ML', 'M'}

# Situação da lista
ST_AGUARDANDO = 'aguardando'    # funcionário contou: falta o gestor aprovar
ST_APROVADA = 'aprovada'        # pronta para comprar (modo carrinho)
ST_FINALIZADA = 'finalizada'
ST_CANCELADA = 'cancelada'
ST_PROCESSANDO = 'processando'  # uso interno: lista sendo gravada
ST_CONTAGEM = 'contagem'        # [CONTAGEM GERAL] rotina só de contagem: grava o estoque, sem lista de compra

# Situação de cada item no carrinho
SIT_COMPRADO = 'comprado'
SIT_FALTOU = 'faltou'
SITUACOES_ITEM = {'', SIT_COMPRADO, SIT_FALTOU}

_tabelas_ok = False


class ErroCompras(Exception):
    """Erro com mensagem pronta para mostrar no celular."""


# ==============================================================================
# == Funções auxiliares =========================================================
# ==============================================================================

def _como_datahora(valor):
    """Aceita datetime ou texto 'AAAA-MM-DD HH:MM:SS' e devolve datetime (ou None)."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    texto = str(valor).strip().replace('T', ' ')
    for formato in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(texto[:26], formato)
        except ValueError:
            continue
    return None


def _num(valor, casas=3):
    """Decimal -> float arredondado (para mandar ao celular em JSON)."""
    if valor is None:
        return None
    return round(float(valor), casas)


def _iso(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.strftime('%Y-%m-%dT%H:%M:%S')
    if isinstance(valor, date):
        return valor.isoformat()
    dh = _como_datahora(valor)
    return dh.strftime('%Y-%m-%dT%H:%M:%S') if dh else str(valor)


def dia_semana_sistema(d):
    """Dia da semana no padrão do sistema inteiro: 1=Domingo ... 7=Sábado."""
    return d.isoweekday() % 7 + 1


def _ler_dias_semana(texto):
    dias = []
    for parte in str(texto or '').split(','):
        parte = parte.strip()
        if parte.isdigit() and 1 <= int(parte) <= 7 and int(parte) not in dias:
            dias.append(int(parte))
    return sorted(dias)


def _ler_ids(texto):
    return [int(p) for p in str(texto or '').split(',') if p.strip().isdigit()]


SEM_LOCAL = ''
MAX_LOCAIS = 10
_tam_secao = 80          # [VÁRIOS LOCAIS] vira 400 quando o campo da rotina foi aumentado (garantir_tabelas)


def locais_do_texto(texto):
    """[VÁRIOS LOCAIS] 'Freezer 1, Estoque seco' (ou com | ou ;) -> ['Freezer 1', 'Estoque seco']."""
    if isinstance(texto, (list, tuple)):
        partes = [str(x) for x in texto]
    else:
        partes = re.split(r'[|;,]', str(texto or ''))
    locais = []
    for x in partes:
        x = re.sub(r'\s+', ' ', x).strip()[:80]
        if x and x.lower() not in [l.lower() for l in locais]:
            locais.append(x)
    return locais[:MAX_LOCAIS]


MAX_PARAMETROS_IN = 900   # o SQL Server aceita até 2100 parâmetros por consulta


def _em(coluna, ids):
    """
    'coluna IN (?, ?, ...)' e os parâmetros. Com muitos ids (cadastro inteiro: 1000+ produtos) devolve
    '1 = 1' sem parâmetros: a consulta traz tudo e quem chamou usa só os ids que pediu (todas as
    chamadas guardam o resultado num dicionário por ProdutoID).
    """
    ids = list(ids)
    if len(ids) > MAX_PARAMETROS_IN:
        return '1 = 1', []
    return f"{coluna} IN ({','.join('?' * len(ids))})", ids


def _qtd_valida(valor, nome="Quantidade"):
    """Converte o que veio do celular em Decimal >= 0 (ou None = item pulado)."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        q = Decimal(str(valor).replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise ErroCompras(f"{nome} inválida: {valor}")
    if not q.is_finite() or q < 0 or q > Decimal('1000000'):
        raise ErroCompras(f"{nome} fora do limite: {valor}")
    return q.quantize(Decimal('0.001'))


def arredondar_pedido(sugestao, unidade, fator):
    """
    Transforma a necessidade em algo que dá para comprar:
      - com caixa (fator > 1): caixas inteiras  -> 13 un com caixa de 20 = 1 cx (20 un)
      - unidade inteira (UN, PCT...): sobe para o próximo inteiro -> 2,3 = 3
      - peso/volume (KG, L): fica com até 3 casas
    Devolve (quantidade_em_unidades, numero_de_caixas_ou_None).
    """
    s = _dec(sugestao)
    if s <= 0:
        return Decimal('0'), None
    f = _dec(fator)
    if f > 1:
        caixas = Decimal(math.ceil(s / f))
        return caixas * f, caixas
    if str(unidade or '').strip().upper() in UNIDADES_FRACIONADAS:
        return s.quantize(Decimal('0.001')), None
    return Decimal(math.ceil(s)), None


def escolher_fornecedor(precos, permitidos=None):
    """
    Escolhe o fornecedor MAIS BARATO para um produto.
      precos: [{'FornecedorID', 'Fornecedor', 'CustoUnid', 'Data', 'Fator'}] = o ÚLTIMO preço
              pago em cada fornecedor (preço por unidade do estoque, vindo das notas XML).
      permitidos: IDs dos fornecedores da rotina (vazio = todos).
    Se nenhum fornecedor da rotina tem preço, usa o mais barato de todos e avisa.
    Devolve (preco_escolhido_ou_None, aviso_ou_None).
    """
    if not precos:
        return None, None
    candidatos = [p for p in precos if not permitidos or p['FornecedorID'] in permitidos]
    aviso = None
    if not candidatos:
        candidatos = list(precos)
        aviso = "Nunca comprado nos fornecedores desta rotina"
    melhor = min(candidatos, key=lambda p: (_dec(p['CustoUnid']), -(_como_data(p['Data']) or date.min).toordinal()))
    return melhor, aviso


def calcular_item(produto, estoque, consumo_dia, minimo, dias, prazo, preco):
    """
    A MESMA conta da aba Sugestão de Compras do Gestão de Estoque:
        comprar = consumo/dia x (prazo + dias a cobrir) + estoque mínimo - estoque de hoje
    (o app do celular faz esta mesma conta em JavaScript quando está sem internet).
    """
    necessidade = _dec(consumo_dia) * (int(prazo) + int(dias)) + _dec(minimo) - _dec(estoque)
    sugestao = max(necessidade, Decimal('0'))
    fator = _dec(preco['Fator']) if preco and preco.get('Fator') and _dec(preco['Fator']) > 1 else Decimal('1')
    qtd, caixas = arredondar_pedido(sugestao, produto.get('Unidade'), fator)
    return {'QtdSugerida': sugestao, 'QtdPedido': qtd, 'Caixas': caixas, 'Fator': fator}


# ==============================================================================
# == Criação das tabelas ========================================================
# ==============================================================================

def garantir_tabelas():
    """Cria as tabelas do app (só na primeira vez) e grava com COMMIT."""
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = get_db_connection()
    if not conn:
        raise ErroCompras("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraUsuariosApp')
            CREATE TABLE CompraUsuariosApp (
                FuncionarioID INT PRIMARY KEY,
                PinHash VARCHAR(128) NOT NULL,
                PinSalt VARCHAR(64) NOT NULL,
                EhGestor BIT NOT NULL DEFAULT 0,
                Ativo BIT NOT NULL DEFAULT 1,
                ErrosSeguidos INT NOT NULL DEFAULT 0,
                BloqueadoAte DATETIME NULL,
                AtualizadoEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraRotinas')
            CREATE TABLE CompraRotinas (
                RotinaID INT IDENTITY(1,1) PRIMARY KEY,
                Nome NVARCHAR(100) NOT NULL,
                DiasSemana VARCHAR(20) NULL,
                DiasCobertura INT NOT NULL DEFAULT 7,
                PrazoDias INT NOT NULL DEFAULT 0,
                Fornecedores VARCHAR(400) NULL,
                Ativa BIT NOT NULL DEFAULT 1,
                CriadaEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraRotinaItens')
            CREATE TABLE CompraRotinaItens (
                RotinaID INT NOT NULL,
                ProdutoID INT NOT NULL,
                Ordem INT NOT NULL DEFAULT 0,
                Secao NVARCHAR(80) NULL,
                PRIMARY KEY (RotinaID, ProdutoID)
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraListas')
            CREATE TABLE CompraListas (
                ListaID INT IDENTITY(1,1) PRIMARY KEY,
                Codigo VARCHAR(40) NOT NULL UNIQUE,
                RotinaID INT NULL,
                NomeRotina NVARCHAR(100) NULL,
                FuncionarioID INT NULL,
                NomeFuncionario NVARCHAR(150) NULL,
                CriadaEm DATETIME NULL,
                DataContagem DATE NULL,
                DiasCobertura INT NOT NULL DEFAULT 7,
                PrazoDias INT NOT NULL DEFAULT 0,
                Status VARCHAR(20) NOT NULL,
                ContagemID INT NULL,
                AprovadaPor NVARCHAR(150) NULL,
                AprovadaEm DATETIME NULL,
                FinalizadaEm DATETIME NULL,
                ValorEstimado DECIMAL(18, 2) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraListaItens')
            CREATE TABLE CompraListaItens (
                ListaID INT NOT NULL,
                ProdutoID INT NOT NULL,
                Ordem INT NOT NULL DEFAULT 0,
                Secao NVARCHAR(80) NULL,
                NomeProduto NVARCHAR(255) NULL,
                Unidade VARCHAR(20) NULL,
                QtdContada DECIMAL(18, 3) NULL,
                EstoqueUsado DECIMAL(18, 3) NULL,
                ConsumoDia DECIMAL(18, 4) NULL,
                EstoqueMinimo DECIMAL(18, 3) NULL,
                QtdSugerida DECIMAL(18, 3) NULL,
                QtdPedido DECIMAL(18, 3) NULL,
                Fator DECIMAL(18, 4) NULL,
                FornecedorID INT NULL,
                FornecedorNome NVARCHAR(150) NULL,
                CustoUnid DECIMAL(18, 4) NULL,
                DataPreco DATE NULL,
                Situacao VARCHAR(20) NOT NULL DEFAULT '',
                Alerta NVARCHAR(250) NULL,
                PRIMARY KEY (ListaID, ProdutoID)
            )
        """)
        # [CONTAGEM GERAL] rotina que só conta o estoque (organizada por local), sem lista de compra
        cur.execute("IF COL_LENGTH('CompraRotinas', 'SoContagem') IS NULL ALTER TABLE CompraRotinas ADD SoContagem BIT NULL")
        # [ABA ESTOQUE] rotina automática "Estoque completo" (todos os produtos do cadastro)
        cur.execute("IF COL_LENGTH('CompraRotinas', 'Automatica') IS NULL ALTER TABLE CompraRotinas ADD Automatica BIT NULL")
        # [VÁRIOS LOCAIS] o mesmo produto em mais de um local ("Freezer 1|Estoque seco") e a contagem de cada local
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraContagemLocais')
            CREATE TABLE CompraContagemLocais (
                ContagemID INT NOT NULL,
                ProdutoID INT NOT NULL,
                Local NVARCHAR(80) NOT NULL,
                Qtd DECIMAL(18, 3) NOT NULL,
                ContadoPor NVARCHAR(150) NULL,
                PRIMARY KEY (ContagemID, ProdutoID, Local)
            )
        """)
        # [PAINEL DO BALANÇO] o que cada celular está contando agora (o celular manda de tempos em tempos)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraContagemAndamento')
            CREATE TABLE CompraContagemAndamento (
                Codigo VARCHAR(40) NOT NULL PRIMARY KEY,
                RotinaID INT NOT NULL,
                Dia DATE NOT NULL,
                FuncionarioID INT NULL,
                Usuario NVARCHAR(150) NULL,
                Dados NVARCHAR(MAX) NULL,
                Atualizado DATETIME NOT NULL
            )
        """)
        conn.commit()
        global _tam_secao
        try:
            cur.execute("IF COL_LENGTH('CompraRotinaItens', 'Secao') < 800 ALTER TABLE CompraRotinaItens ALTER COLUMN Secao NVARCHAR(400) NULL")
            conn.commit()
            _tam_secao = 400
        except Exception as e:
            conn.rollback()
            logger.warning(f"App de compras: não deu para aumentar o campo de locais da rotina: {e}")
        _tabelas_ok = True
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao criar as tabelas do app de compras: {e}", exc_info=True)
        raise ErroCompras("Não foi possível preparar o banco do app de compras (veja o log).")
    finally:
        conn.close()


def _conectar():
    garantir_tabelas()
    conn = get_db_connection()
    if not conn:
        raise ErroCompras("Sem conexão com o banco de dados. O computador da loja está ligado?")
    return conn


# ==============================================================================
# == Usuários e PIN =============================================================
# ==============================================================================

def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(salt), 120_000).hex()


def validar_formato_pin(pin):
    pin = str(pin or '').strip()
    if not re.fullmatch(r'\d{%d}' % PIN_TAMANHO, pin):
        raise ErroCompras(f"O PIN precisa ter exatamente {PIN_TAMANHO} números.")
    return pin


def listar_funcionarios():
    """Todos os funcionários cadastrados (para o script de cadastro de PIN)."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT F.FuncionarioID, F.NomeCompleto, U.EhGestor, U.Ativo
            FROM Funcionarios F
            LEFT JOIN CompraUsuariosApp U ON U.FuncionarioID = F.FuncionarioID
            ORDER BY F.NomeCompleto
        """)
        return [{'FuncionarioID': r[0], 'Nome': r[1] or f'Funcionário {r[0]}',
                 'TemPin': r[3] is not None, 'EhGestor': bool(r[2]), 'Ativo': bool(r[3])}
                for r in cur.fetchall()]
    finally:
        conn.close()


def listar_usuarios_app():
    """Quem pode entrar no app (tela de login). Mostra só o PRIMEIRO nome."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT U.FuncionarioID, F.NomeCompleto
            FROM CompraUsuariosApp U
            JOIN Funcionarios F ON F.FuncionarioID = U.FuncionarioID
            WHERE U.Ativo = 1
            ORDER BY F.NomeCompleto
        """)
        return [{'id': r[0], 'nome': (r[1] or f'Funcionário {r[0]}').split()[0].capitalize()}
                for r in cur.fetchall()]
    finally:
        conn.close()


def definir_pin(funcionario_id, pin, eh_gestor=False):
    """Cria ou troca o PIN de um funcionário (e libera se estava bloqueado)."""
    pin = validar_formato_pin(pin)
    salt = secrets.token_hex(16)
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM Funcionarios WHERE FuncionarioID = ?", (int(funcionario_id),))
        if not cur.fetchone():
            raise ErroCompras(f"Funcionário {funcionario_id} não existe.")
        cur.execute("DELETE FROM CompraUsuariosApp WHERE FuncionarioID = ?", (int(funcionario_id),))
        cur.execute("""
            INSERT INTO CompraUsuariosApp (FuncionarioID, PinHash, PinSalt, EhGestor, Ativo, ErrosSeguidos, BloqueadoAte, AtualizadoEm)
            VALUES (?, ?, ?, ?, 1, 0, NULL, ?)
        """, (int(funcionario_id), _hash_pin(pin, salt), salt, 1 if eh_gestor else 0, datetime.now()))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def desativar_usuario_app(funcionario_id):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE CompraUsuariosApp SET Ativo = 0 WHERE FuncionarioID = ?", (int(funcionario_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def verificar_pin(funcionario_id, pin, agora=None):
    """
    Confere o PIN. Devolve {'id', 'nome', 'gestor'} se estiver certo.
    Levanta ErroCompras com a mensagem para o celular se estiver errado ou bloqueado.
    """
    agora = agora or datetime.now()
    try:
        funcionario_id = int(funcionario_id)
    except (TypeError, ValueError):
        raise ErroCompras("Escolha seu nome na lista.")
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT U.PinHash, U.PinSalt, U.EhGestor, U.Ativo, U.ErrosSeguidos, U.BloqueadoAte, F.NomeCompleto
            FROM CompraUsuariosApp U JOIN Funcionarios F ON F.FuncionarioID = U.FuncionarioID
            WHERE U.FuncionarioID = ?
        """, (funcionario_id,))
        r = cur.fetchone()
        if not r or not r[3]:
            raise ErroCompras("Usuário sem acesso ao app. Peça ao gestor para cadastrar seu PIN.")
        bloqueado_ate = _como_datahora(r[5])
        if bloqueado_ate and bloqueado_ate > agora:
            minutos = max(1, math.ceil((bloqueado_ate - agora).total_seconds() / 60))
            raise ErroCompras(f"Muitas tentativas erradas. Tente de novo em {minutos} min.")
        pin_ok = hmac.compare_digest(_hash_pin(str(pin or '').strip(), r[1]), r[0]) if re.fullmatch(r'\d+', str(pin or '').strip()) else False
        if pin_ok:
            cur.execute("UPDATE CompraUsuariosApp SET ErrosSeguidos = 0, BloqueadoAte = NULL WHERE FuncionarioID = ?",
                        (funcionario_id,))
            conn.commit()
            return {'id': funcionario_id, 'nome': (r[6] or '').split()[0].capitalize() if r[6] else f'Funcionário {funcionario_id}',
                    'nome_completo': r[6] or '', 'gestor': bool(r[2])}
        erros = int(r[4] or 0) + 1
        if erros >= PIN_MAX_ERROS:
            cur.execute("UPDATE CompraUsuariosApp SET ErrosSeguidos = 0, BloqueadoAte = ? WHERE FuncionarioID = ?",
                        (agora + timedelta(minutes=PIN_BLOQUEIO_MINUTOS), funcionario_id))
            conn.commit()
            raise ErroCompras(f"PIN errado {PIN_MAX_ERROS} vezes. Acesso bloqueado por {PIN_BLOQUEIO_MINUTOS} minutos.")
        cur.execute("UPDATE CompraUsuariosApp SET ErrosSeguidos = ? WHERE FuncionarioID = ?", (erros, funcionario_id))
        conn.commit()
        raise ErroCompras(f"PIN errado. Restam {PIN_MAX_ERROS - erros} tentativa(s).")
    finally:
        conn.close()


def usuario_ainda_ativo(funcionario_id):
    """Confere a cada pedido se o acesso não foi desativado depois do login."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT EhGestor, Ativo FROM CompraUsuariosApp WHERE FuncionarioID = ?", (int(funcionario_id),))
        r = cur.fetchone()
        if not r or not r[1]:
            return None
        return {'gestor': bool(r[0])}
    finally:
        conn.close()


# ==============================================================================
# == Rotinas de compra ==========================================================
# ==============================================================================

def _proxima_data(dias_semana, hoje):
    if not dias_semana:
        return None
    for n in range(0, 8):
        d = hoje + timedelta(days=n)
        if dia_semana_sistema(d) in dias_semana:
            return d
    return None


def categoria_do(texto):
    """Categoria do produto (vazia = 'Geral', igual ao Gestão de Estoque)."""
    return (texto or '').strip() or 'Geral'


def listar_rotinas(incluir_inativas=False, hoje=None):
    hoje = _como_data(hoje) or date.today()
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT R.RotinaID, R.Nome, R.DiasSemana, R.DiasCobertura, R.PrazoDias, R.Fornecedores, R.Ativa,
                   (SELECT COUNT(*) FROM CompraRotinaItens I WHERE I.RotinaID = R.RotinaID) AS QtdItens, R.SoContagem,
                   R.Automatica
            FROM CompraRotinas R
            ORDER BY R.Nome
        """)
        linhas = cur.fetchall()
        # [CATEGORIAS] categorias dos produtos de cada rotina (para contar só algumas, ex.: só Brinquedos)
        cur.execute("""SELECT DISTINCT I.RotinaID, P.Categoria FROM CompraRotinaItens I
                       JOIN ProdutosEstoque P ON P.ProdutoID = I.ProdutoID""")
        categorias = {}
        for rid, cat in cur.fetchall():
            categorias.setdefault(rid, set()).add(categoria_do(cat))
        rotinas = []
        for r in linhas:
            if not r[6] and not incluir_inativas:
                continue
            dias = _ler_dias_semana(r[2])
            prox = _proxima_data(dias, hoje)
            rotinas.append({'id': r[0], 'nome': r[1], 'dias_semana': dias, 'dias_cobertura': int(r[3] or 7),
                            'prazo_dias': int(r[4] or 0), 'fornecedores': _ler_ids(r[5]), 'ativa': bool(r[6]),
                            'qtd_itens': int(r[7] or 0), 'hoje': prox == hoje, 'proxima': _iso(prox),
                            'so_contagem': bool(r[8]), 'automatica': bool(r[9]),
                            'categorias': sorted(categorias.get(r[0], set()), key=lambda c: c.lower())})
        rotinas.sort(key=lambda x: (not x['hoje'], x['proxima'] or '9999', x['nome']))
        return rotinas
    finally:
        conn.close()


def obter_rotina(rotina_id):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT RotinaID, Nome, DiasSemana, DiasCobertura, PrazoDias, Fornecedores, Ativa, SoContagem
                       FROM CompraRotinas WHERE RotinaID = ?""", (int(rotina_id),))
        r = cur.fetchone()
        if not r:
            raise ErroCompras("Rotina não encontrada.")
        cur.execute("""
            SELECT I.ProdutoID, I.Ordem, I.Secao, P.NomeProduto, P.UnidadeMedida, P.Categoria
            FROM CompraRotinaItens I
            LEFT JOIN ProdutosEstoque P ON P.ProdutoID = I.ProdutoID
            WHERE I.RotinaID = ?
            ORDER BY I.Ordem, I.ProdutoID
        """, (int(rotina_id),))
        itens = []
        for i in cur.fetchall():
            # [VÁRIOS LOCAIS] só na contagem geral; na rotina de COMPRA o texto é o corredor inteiro
            # (ex.: "Corredor 3, Secos" é UM lugar só)
            if r[7]:
                locais = locais_do_texto(i[2])
            else:
                corredor = re.sub(r'\s*\|\s*', ', ', str(i[2] or '')).strip()
                locais = [corredor] if corredor else []
            itens.append({'produto_id': i[0], 'ordem': i[1], 'secao': locais[0] if locais else '', 'locais': locais,
                          'nome': i[3] or f'Produto {i[0]} (apagado do estoque)', 'unidade': (i[4] or 'UN').strip() or 'UN',
                          'categoria': i[5] or '', 'existe': i[3] is not None})
        return {'id': r[0], 'nome': r[1], 'dias_semana': _ler_dias_semana(r[2]), 'dias_cobertura': int(r[3] or 7),
                'prazo_dias': int(r[4] or 0), 'fornecedores': _ler_ids(r[5]), 'ativa': bool(r[6]),
                'so_contagem': bool(r[7]), 'itens': itens}
    finally:
        conn.close()


def salvar_rotina(dados):
    """
    Cria (sem 'id') ou altera (com 'id') uma rotina e a lista de itens, na ordem recebida.
    dados = {'id'?, 'nome', 'dias_semana': [1..7], 'dias_cobertura', 'prazo_dias',
             'fornecedores': [ids], 'itens': [{'produto_id', 'secao'}], 'so_contagem'?}
    so_contagem: rotina de CONTAGEM GERAL (seção = local: freezer 1, estoque seco...): grava o
    estoque e não gera lista de compra.
    Devolve o ID da rotina.
    """
    nome = str(dados.get('nome') or '').strip()
    if not nome:
        raise ErroCompras("Dê um nome para a rotina.")
    if len(nome) > 100:
        raise ErroCompras("Nome muito comprido (máximo 100 letras).")
    try:
        cobertura = int(dados.get('dias_cobertura') or 7)
        prazo = int(dados.get('prazo_dias') or 0)
    except (TypeError, ValueError):
        raise ErroCompras("Dias a cobrir e prazo precisam ser números inteiros.")
    if not 1 <= cobertura <= DIAS_COBERTURA_MAX or not 0 <= prazo <= 60:
        raise ErroCompras(f"Dias a cobrir: de 1 a {DIAS_COBERTURA_MAX}. Prazo: de 0 a 60.")
    dias = _ler_dias_semana(','.join(str(d) for d in (dados.get('dias_semana') or [])))
    fornecedores = sorted({int(f) for f in (dados.get('fornecedores') or []) if str(f).isdigit()})
    garantir_tabelas()
    so_contagem = bool(dados.get('so_contagem'))
    itens, vistos = [], set()
    for it in dados.get('itens') or []:
        try:
            pid = int(it.get('produto_id'))
        except (TypeError, ValueError, AttributeError):
            raise ErroCompras("Item da rotina sem produto válido.")
        if pid in vistos:
            continue
        vistos.add(pid)
        if so_contagem:
            locais = locais_do_texto(it.get('locais') if it.get('locais') else it.get('secao'))
            secao = '|'.join(locais)
            if len(secao) > _tam_secao:
                raise ErroCompras(f"Locais demais num produto (máximo {_tam_secao} letras somando todos). Encurte os nomes.")
        else:
            secao = re.sub(r'\s+', ' ', str(it.get('secao') or '')).strip()[:80]
        itens.append((pid, secao))
    if not itens:
        raise ErroCompras("Coloque pelo menos um produto na rotina.")

    conn = _conectar()
    try:
        cur = conn.cursor()
        marcas = ','.join('?' * len(itens))
        filtro, params = _em('ProdutoID', [p for p, _ in itens])
        cur.execute(f"SELECT ProdutoID FROM ProdutosEstoque WHERE {filtro}", params)
        existentes = {r[0] for r in cur.fetchall()}
        faltando = [p for p, _ in itens if p not in existentes]
        if faltando:
            raise ErroCompras(f"Produto(s) não encontrado(s) no estoque: {faltando}")
        rotina_id = dados.get('id')
        valores = (nome, ','.join(map(str, dias)), cobertura, prazo, ','.join(map(str, fornecedores)),
                   1 if dados.get('so_contagem') else 0)
        if rotina_id:
            cur.execute("""UPDATE CompraRotinas SET Nome = ?, DiasSemana = ?, DiasCobertura = ?, PrazoDias = ?,
                           Fornecedores = ?, SoContagem = ?, Ativa = 1 WHERE RotinaID = ?""", valores + (int(rotina_id),))
            if cur.rowcount == 0:
                raise ErroCompras("Rotina não encontrada (pode ter sido apagada).")
            rotina_id = int(rotina_id)
        else:
            cur.execute("""INSERT INTO CompraRotinas (Nome, DiasSemana, DiasCobertura, PrazoDias, Fornecedores, SoContagem,
                                                     Ativa, CriadaEm)
                           OUTPUT INSERTED.RotinaID VALUES (?, ?, ?, ?, ?, ?, 1, ?)""", valores + (datetime.now(),))
            rotina_id = int(cur.fetchone()[0])
        cur.execute("DELETE FROM CompraRotinaItens WHERE RotinaID = ?", (rotina_id,))
        for ordem, (pid, secao) in enumerate(itens):
            cur.execute("INSERT INTO CompraRotinaItens (RotinaID, ProdutoID, Ordem, Secao) VALUES (?, ?, ?, ?)",
                        (rotina_id, pid, ordem, secao or None))
        conn.commit()
        return rotina_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def desativar_rotina(rotina_id):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE CompraRotinas SET Ativa = 0 WHERE RotinaID = ?", (int(rotina_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ==============================================================================
# == [ABA ESTOQUE] "Estoque completo": todos os produtos, para contar por categoria
# ==============================================================================
NOME_ESTOQUE_COMPLETO = 'Estoque completo'


def estoque_completo():
    """
    Garante a rotina automática de CONTAGEM com TODOS os produtos do cadastro (para contar só
    uma categoria, ex.: Brinquedos, mesmo que nenhuma rotina tenha esses produtos). Produto novo
    no cadastro entra sozinho; apagado sai. O local de cada produto: o que ele já tem nesta rotina
    (o gestor pode mudar), senão o de outra contagem geral, senão a categoria.
    Devolve {'id', 'nome', 'total', 'categorias': [{'nome', 'qtd'}]}.
    """
    garantir_tabelas()
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT RotinaID, Ativa FROM CompraRotinas WHERE Automatica = 1 ORDER BY RotinaID")
        r = cur.fetchone()
        if r:
            rotina_id = int(r[0])
            if not r[1]:
                cur.execute("UPDATE CompraRotinas SET Ativa = 1 WHERE RotinaID = ?", (rotina_id,))
        else:
            cur.execute("""INSERT INTO CompraRotinas (Nome, DiasSemana, DiasCobertura, PrazoDias, Fornecedores, SoContagem,
                                                     Ativa, CriadaEm, Automatica)
                           OUTPUT INSERTED.RotinaID VALUES (?, '', 7, 0, '', 1, 1, ?, 1)""",
                        (NOME_ESTOQUE_COMPLETO, datetime.now()))
            rotina_id = int(cur.fetchone()[0])
        cur.execute("SELECT ProdutoID, NomeProduto, Categoria FROM ProdutosEstoque")
        produtos = {pid: (nome or '', categoria_do(cat)) for pid, nome, cat in cur.fetchall()}
        cur.execute("SELECT ProdutoID, Ordem FROM CompraRotinaItens WHERE RotinaID = ?", (rotina_id,))
        atuais = {pid: ordem or 0 for pid, ordem in cur.fetchall()}
        apagados = [pid for pid in atuais if pid not in produtos]
        for pid in apagados:
            cur.execute("DELETE FROM CompraRotinaItens WHERE RotinaID = ? AND ProdutoID = ?", (rotina_id, pid))
        novos = sorted((pid for pid in produtos if pid not in atuais), key=lambda p: (produtos[p][1].lower(), produtos[p][0].lower()))
        if novos:
            # local já usado numa contagem geral do gestor (Freezer 1, Estoque seco...)
            cur.execute("""SELECT I.ProdutoID, I.Secao FROM CompraRotinaItens I JOIN CompraRotinas R ON R.RotinaID = I.RotinaID
                           WHERE R.SoContagem = 1 AND R.Ativa = 1 AND R.RotinaID <> ? AND I.Secao IS NOT NULL""", (rotina_id,))
            local_de = {}
            for pid, secao in cur.fetchall():
                local_de.setdefault(pid, secao)
            base = max(atuais.values(), default=-1) + 1
            for k, pid in enumerate(novos):
                cur.execute("INSERT INTO CompraRotinaItens (RotinaID, ProdutoID, Ordem, Secao) VALUES (?, ?, ?, ?)",
                            (rotina_id, pid, base + k, (local_de.get(pid) or re.sub(r'[|;,]', ' -', produtos[pid][1]))[:_tam_secao]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if novos or apagados:
        logger.info(f"Estoque completo: +{len(novos)} produto(s), -{len(apagados)}.")
    qtd = {}
    for _, cat in produtos.values():
        qtd[cat] = qtd.get(cat, 0) + 1
    return {'id': rotina_id, 'nome': NOME_ESTOQUE_COMPLETO, 'total': len(produtos),
            'categorias': [{'nome': c, 'qtd': n} for c, n in sorted(qtd.items(), key=lambda x: x[0].lower())]}


def buscar_produtos(termo='', limite=40):
    """Produtos do estoque para colocar numa rotina (busca por nome ou categoria)."""
    termo = str(termo or '').strip()
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ProdutoID, NomeProduto, UnidadeMedida, Categoria FROM ProdutosEstoque")
        palavras = [p for p in database_normalizar(termo).split() if p]
        achados = []
        for pid, nome, un, cat in cur.fetchall():
            alvo = database_normalizar(f"{nome or ''} {cat or ''}")
            if all(p in alvo for p in palavras):
                achados.append({'produto_id': pid, 'nome': nome or f'Produto {pid}',
                                'unidade': (un or 'UN').strip() or 'UN', 'categoria': cat or ''})
        achados.sort(key=lambda x: x['nome'].lower())
        return achados[:limite]
    finally:
        conn.close()


def database_normalizar(texto):
    """Minúsculas e sem acento (para a busca achar 'acucar' em 'Açúcar')."""
    import unicodedata
    t = unicodedata.normalize('NFKD', str(texto or '').lower())
    return ''.join(c for c in t if not unicodedata.combining(c))


def listar_fornecedores_com_compras():
    """Fornecedores que já venderam algo (para marcar os mercados da rotina)."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT F.FornecedorID, F.NomeFantasia, F.CNPJ, COUNT(NF.NotaID)
            FROM Fornecedores F
            JOIN NotasFiscaisEntrada NF ON NF.FornecedorID = F.FornecedorID
            GROUP BY F.FornecedorID, F.NomeFantasia, F.CNPJ
            ORDER BY F.NomeFantasia
        """)
        return [{'id': r[0], 'nome': r[1] or f'Fornecedor {r[0]}', 'notas': int(r[3] or 0)}
                for r in cur.fetchall() if (r[2] or '').strip() != database.CNPJ_FORNECEDOR_INTERNO]
    finally:
        conn.close()


# ==============================================================================
# == Dados para contar e calcular ==============================================
# ==============================================================================

def _precos_por_produto(cur, produtos, data_ref):
    """
    ÚLTIMO preço PAGO de cada produto em cada fornecedor (nos últimos 365 dias), por
    unidade do estoque, com o Qtd/Cx do vínculo (para arredondar em caixas).
    Bonificação (custo 0) e produção interna não contam como preço.
    """
    if not produtos:
        return {}
    cur.execute(f"""
        SELECT PF.ProdutoID, NF.DataEmissao, INI.ItemNotaID, INI.PrecoCustoUnitario, PF.FatorConversao,
               F.FornecedorID, F.NomeFantasia, F.CNPJ
        FROM ItensNotaFiscalEntrada INI
        JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
        JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
        LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        WHERE INI.Quantidade > 0 AND INI.PrecoCustoUnitario > 0 AND {_em('PF.ProdutoID', produtos)[0]}
    """, _em('PF.ProdutoID', produtos)[1])
    limite = data_ref - timedelta(days=PRECO_VALIDO_DIAS)
    ultimo = {}   # (pid, forn) -> (data, item_id, custo, fator, nome)
    for pid, dt, item_id, custo, fator, forn_id, forn_nome, cnpj in cur.fetchall():
        d = _como_data(dt)
        if not d or d < limite or d > data_ref or forn_id is None or (cnpj or '').strip() == database.CNPJ_FORNECEDOR_INTERNO:
            continue
        chave = (pid, forn_id)
        if chave not in ultimo or (d, item_id or 0) > ultimo[chave][:2]:
            ultimo[chave] = (d, item_id or 0, _dec(custo), _dec(fator) if fator is not None else Decimal('1'),
                             forn_nome or f'Fornecedor {forn_id}')
    precos = {}
    for (pid, forn_id), (d, _, custo, fator, nome) in ultimo.items():
        precos.setdefault(pid, []).append({'FornecedorID': forn_id, 'Fornecedor': nome, 'CustoUnid': custo,
                                           'Data': d, 'Fator': fator if fator > 0 else Decimal('1')})
    for lista in precos.values():
        lista.sort(key=lambda p: (p['CustoUnid'], p['Fornecedor']))
    return precos


def _minimos(cur, pids):
    """Estoque mínimo de cada produto (cadastro do Gestão de Estoque)."""
    if not pids:
        return {}
    filtro, params = _em('ProdutoID', pids)
    cur.execute(f"SELECT ProdutoID, EstoqueMinimo FROM ProdutosEstoque WHERE {filtro}", params)
    return {r[0]: _dec(r[1]) for r in cur.fetchall()}


def _ultima_contagem_id(cur):
    cur.execute("SELECT ContagemID, DataContagem FROM ContagensEstoque")
    todas = [(_como_data(d), cid) for cid, d in cur.fetchall() if _como_data(d)]
    return max(todas)[1] if todas else None


def _sugestao_por_produto(contagem_id, hoje):
    """Consumo e estoque de hoje de cada produto (o mesmo cálculo do Gestão de Estoque)."""
    if not contagem_id:
        return {}
    try:
        resultado = database.calcular_sugestao_compra(contagem_id, None, hoje=hoje)
    except Exception as e:
        logger.error(f"App de compras: falha no cálculo do consumo (contagem {contagem_id}): {e}", exc_info=True)
        raise ErroCompras("Não foi possível calcular o consumo agora (veja o log do servidor).")
    itens = {i['ProdutoID']: i for i in resultado['itens']}
    _ajustar_consumo_aprendizado(itens, _como_data(resultado.get('DataReferencia')) or hoje)
    return itens


# [MELHORIA APRENDIZADO] Com só 1 contagem, o Gestão de Estoque estima o consumo pelas
# compras dos últimos 90 dias. Se o ritmo de compra mudou (ex.: comprou muito há 4 meses e
# pouco agora), o consumo sai baixo demais e a sugestão vira zero. No app, enquanto o produto
# está "aprendendo", o consumo usa o MAIOR entre: últimos 90 dias e últimos 12 meses (desde a
# 1ª compra nesse período). As compras de TODOS os vínculos/fornecedores do produto entram.
DIAS_CONSUMO_LONGO = 365
DIAS_MINIMOS_CONSUMO_LONGO = 30


def _compras_recentes(cur, pids, ate, dias=DIAS_CONSUMO_LONGO):
    """{pid: [(data, qtd_em_unidades_do_estoque, custo, fornecedor, descricao, nf)]} dos últimos 'dias'."""
    if not pids:
        return {}
    desde = ate - timedelta(days=dias)
    cur.execute(f"""
        SELECT PF.ProdutoID, NF.DataEmissao, INI.Quantidade, INI.PrecoCustoUnitario, F.NomeFantasia, F.CNPJ,
               PF.DescricaoXML, NF.NumeroNF, PF.ProdutoFornecedorID
        FROM ItensNotaFiscalEntrada INI
        JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
        JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
        LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        WHERE INI.Quantidade > 0 AND {_em('PF.ProdutoID', pids)[0]}
    """, _em('PF.ProdutoID', pids)[1])
    res = {}
    for pid, dt, q, custo, forn, cnpj, desc, nf, vid in cur.fetchall():
        d = _como_data(dt)
        if not d or d <= desde or d > ate or (cnpj or '').strip() == database.CNPJ_FORNECEDOR_INTERNO:
            continue
        res.setdefault(pid, []).append((d, _dec(q), _dec(custo), forn or 'Fornecedor', desc or '', nf or '', vid))
    for lista in res.values():
        lista.sort(key=lambda c: c[0])
    return res


def _taxa_longa(compras, ate):
    """Consumo/dia pelas compras de até 12 meses: total ÷ dias desde a 1ª compra (mínimo 30 dias)."""
    if not compras:
        return Decimal('0'), Decimal('0'), 0
    total = sum((c[1] for c in compras), Decimal('0'))
    dias = max((ate - compras[0][0]).days, DIAS_MINIMOS_CONSUMO_LONGO)
    return total / dias, total, dias


def _ajustar_consumo_aprendizado(itens, ate):
    alvo = [pid for pid, i in itens.items() if i.get('Contado') and i.get('MetodoConsumo') in ('compras', 'sem_dados')]
    if not alvo:
        return
    conn = _conectar()
    try:
        compras = _compras_recentes(conn.cursor(), alvo, ate)
    finally:
        conn.close()
    for pid in alvo:
        i = itens[pid]
        taxa, total, dias = _taxa_longa(compras.get(pid, []), ate)
        i['ConsumoLongo'] = {'por_dia': taxa, 'total': total, 'dias': dias}
        atual = _dec(i.get('UsoMedioDiario'))
        if taxa > atual:
            i['UsoMedioDiario'] = taxa
            i['MetodoConsumo'] = 'compras'
            i['ConsumoPor12Meses'] = True
            if i.get('QtdUltimaContagem') is not None:     # estoque de hoje com o consumo novo
                est = _dec(i['QtdUltimaContagem']) + _dec(i.get('ComprasDepois')) - taxa * int(i.get('DiasDesdeContagem') or 0)
                i['EstoqueHoje'] = max(est, Decimal('0'))


def historico_produto(produto_id, hoje=None):
    """
    Tudo que entra na conta de um produto: os vínculos (códigos de todos os fornecedores),
    as compras dos últimos 12 meses e as últimas contagens. Para conferir no celular.
    """
    hoje = _como_data(hoje) or date.today()
    produto_id = int(produto_id)
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE ProdutoID = ?", (produto_id,))
        p = cur.fetchone()
        if not p:
            raise ErroCompras("Produto não encontrado.")
        cur.execute("""SELECT PF.ProdutoFornecedorID, F.NomeFantasia, PF.DescricaoXML, PF.FatorConversao
                       FROM ProdutosFornecedor PF LEFT JOIN Fornecedores F ON F.FornecedorID = PF.FornecedorID
                       WHERE PF.ProdutoID = ?""", (produto_id,))
        vinculos = [{'id': r[0], 'fornecedor': r[1] or '', 'descricao': r[2] or '', 'fator': _num(r[3] or 1)} for r in cur.fetchall()]
        compras = _compras_recentes(cur, [produto_id], hoje).get(produto_id, [])
        cur.execute("""SELECT C.DataContagem, I.QuantidadeContada FROM ItensContagemEstoque I
                       JOIN ContagensEstoque C ON C.ContagemID = I.ContagemID WHERE I.ProdutoID = ?""", (produto_id,))
        por_dia = {}
        for d, q in cur.fetchall():
            d = _como_data(d)
            if d:
                por_dia[d] = por_dia.get(d, Decimal('0')) + _dec(q)
    finally:
        conn.close()
    limite90 = hoje - timedelta(days=90)
    total90 = sum((c[1] for c in compras if c[0] > limite90), Decimal('0'))
    taxa, total, dias = _taxa_longa(compras, hoje)
    return {
        'produto_id': produto_id, 'nome': p[0], 'unidade': (p[1] or 'UN').strip() or 'UN',
        'vinculos': vinculos,
        'compras': [{'data': _iso(c[0]), 'qtd': _num(c[1]), 'custo': _num(c[2], 4), 'fornecedor': c[3], 'descricao': c[4],
                     'nf': c[5], 'nos_90_dias': c[0] > limite90} for c in reversed(compras)],
        'contagens': [{'data': _iso(d), 'qtd': _num(q)} for d, q in sorted(por_dia.items(), reverse=True)[:6]],
        'consumo_90': {'total': _num(total90), 'por_dia': _num(total90 / 90, 4)},
        'consumo_12m': {'total': _num(total), 'dias': dias, 'por_dia': _num(taxa, 4)},
    }


def _alerta_consumo(info):
    if not info or not info.get('Contado'):
        return "Nunca contado antes: o consumo ainda não é conhecido"
    if info.get('ConsumoNegativo'):
        return "Conferir: a conta do consumo não fecha (contagem ou nota)"
    if info.get('ConsumoPor12Meses'):
        return "Consumo aproximado pelas compras dos últimos 12 meses (só 1 contagem)"
    if info.get('MetodoConsumo') == 'compras':
        return "Consumo aproximado pelas compras (só 1 contagem)"
    if info.get('MetodoConsumo') == 'sem_dados':
        return "Sem histórico de consumo: confira a quantidade"
    return None


def _contagens_de_hoje(cur, produtos, hoje, ignorar_ids):
    """Quanto de cada produto já foi contado HOJE em outras contagens (avisa para não somar sem querer)."""
    if not produtos:
        return {}
    cur.execute("SELECT ContagemID, DataContagem, NomeContagem FROM ContagensEstoque")
    de_hoje = {cid: nome for cid, d, nome in cur.fetchall() if _como_data(d) == hoje and cid not in ignorar_ids}
    if not de_hoje:
        return {}
    marcas_c = ','.join('?' * len(de_hoje))
    marcas_p = ','.join('?' * len(produtos))
    cur.execute(f"""SELECT ContagemID, ProdutoID, QuantidadeContada FROM ItensContagemEstoque
                    WHERE ContagemID IN ({marcas_c}) AND {_em('ProdutoID', produtos)[0]}""",
                list(de_hoje) + _em('ProdutoID', produtos)[1])
    resultado = {}
    for cid, pid, q in cur.fetchall():
        r = resultado.setdefault(pid, {'qtd': Decimal('0'), 'contagens': []})
        r['qtd'] += _dec(q)
        if de_hoje[cid] not in r['contagens']:
            r['contagens'].append(de_hoje[cid] or f'Contagem {cid}')
    return resultado


def _breakdown(cur, contagem_id):
    """{ProdutoID: {local: (qtd, quem contou)}} gravado para uma contagem (vazio se ela é antiga, sem locais)."""
    cur.execute("SELECT ProdutoID, Local, Qtd, ContadoPor FROM CompraContagemLocais WHERE ContagemID = ?", (contagem_id,))
    resultado = {}
    for pid, local, q, por in cur.fetchall():
        resultado.setdefault(pid, {})[local or SEM_LOCAL] = (_dec(q), por)
    return resultado


def _juntar_locais(*mapas):
    """
    [VÁRIOS LOCAIS] Junta {local: valor} na ordem (o último vence). 'Freezer 1' e 'freezer 1 ' são o
    MESMO local: o SQL Server não diferencia maiúsculas nem espaço no fim, e gravar os dois daria erro.
    """
    juntos = {}
    for m in mapas:
        for local, v in (m or {}).items():
            chave = str(local or '').strip().lower()
            juntos.pop(chave, None)
            juntos[chave] = (str(local or '').strip(), v)
    return {nome: v for nome, v in juntos.values()}


def _locais_contados_hoje(cur, anteriores):
    """[VÁRIOS LOCAIS] {pid: {local: {'qtd', 'por'}}} das contagens de HOJE desta rotina (para o celular mostrar)."""
    resultado = {}
    for cod, cid, _ in sorted(anteriores, key=lambda x: x[1] or 0):
        for pid, locais in _breakdown(cur, cid).items():
            for local, (q, por) in locais.items():
                resultado.setdefault(pid, {})[local] = {'qtd': _num(q), 'por': por or '?'}
    return resultado


def _contagens_substituidas(cur, rotina_id, hoje, ignorar_codigo=None):
    """Contagens que o app já fez HOJE para esta mesma rotina (serão trocadas pela nova)."""
    cur.execute("SELECT Codigo, ContagemID, DataContagem, Status FROM CompraListas WHERE RotinaID = ? AND ContagemID IS NOT NULL",
                (int(rotina_id),))
    return [(cod, cid, st) for cod, cid, d, st in cur.fetchall() if _como_data(d) == hoje and cod != ignorar_codigo]


def preparar_contagem(rotina_id, hoje=None):
    """
    Tudo que o celular precisa para contar a rotina (e calcular a lista mesmo SEM internet):
    itens na ordem do corredor, última contagem, consumo por dia, estoque estimado de hoje,
    caixas conhecidas e o último preço em cada fornecedor.
    """
    hoje = _como_data(hoje) or date.today()
    rotina = obter_rotina(rotina_id)
    itens_ok = [i for i in rotina['itens'] if i['existe']]
    pids = [i['produto_id'] for i in itens_ok]
    conn = _conectar()
    try:
        cur = conn.cursor()
        ultima = _ultima_contagem_id(cur)
        minimos = _minimos(cur, pids)
        precos = _precos_por_produto(cur, pids, hoje)
        anteriores = _contagens_substituidas(cur, rotina_id, hoje)
        substituidas = {cid for _, cid, _ in anteriores}
        hoje_outras = _contagens_de_hoje(cur, pids, hoje, substituidas)
        hoje_locais = _locais_contados_hoje(cur, anteriores)
    finally:
        conn.close()
    sug = _sugestao_por_produto(ultima, hoje)
    embalagens = database.embalagens_por_produto()
    itens = []
    for it in itens_ok:
        pid = it['produto_id']
        info = sug.get(pid) or {}
        ja = hoje_outras.get(pid)
        itens.append({
            'produto_id': pid, 'nome': it['nome'], 'unidade': it['unidade'], 'secao': it['secao'], 'ordem': it['ordem'],
            'locais': it['locais'], 'categoria': categoria_do(it.get('categoria')),
            'hoje_locais': hoje_locais.get(pid),     # [VÁRIOS LOCAIS] já contado hoje nesta rotina (outra pessoa/celular)
            'estoque_minimo': _num(minimos.get(pid, Decimal('0'))),
            'ultima_contagem': {'data': _iso(info.get('DataUltimaContagem')), 'qtd': _num(info.get('QtdUltimaContagem'))}
                               if info.get('Contado') else None,
            'compras_depois': _num(info.get('ComprasDepois')),
            'consumo_dia': _num(info.get('UsoMedioDiario') or 0, 4),
            'estoque_estimado': _num(info.get('EstoqueHoje')),
            'alerta': _alerta_consumo(info),
            'caixas': [_num(e['Fator']) for e in embalagens.get(pid, [])][:3],
            'contado_hoje': {'qtd': _num(ja['qtd']), 'contagens': ja['contagens']} if ja else None,
            'precos': [{'fornecedor_id': p['FornecedorID'], 'fornecedor': p['Fornecedor'], 'custo': _num(p['CustoUnid'], 4),
                        'data': _iso(p['Data']), 'fator': _num(p['Fator'])} for p in precos.get(pid, [])],
        })
    rotina['itens'] = itens
    rotina['gerado_em'] = _iso(datetime.now())
    rotina['hoje'] = _iso(hoje)
    return rotina


# ==============================================================================
# == Listas de compra ===========================================================
# ==============================================================================

def _itens_so_contagem(rotina, contados):
    """[CONTAGEM GERAL] Itens do registro de uma contagem geral: só o que foi contado (nada para comprar)."""
    return [{'ProdutoID': it['produto_id'], 'Ordem': it['ordem'], 'Secao': it['secao'], 'NomeProduto': it['nome'][:255],
             'Unidade': it['unidade'][:20], 'QtdContada': contados.get(it['produto_id']), 'EstoqueUsado': None,
             'ConsumoDia': None, 'EstoqueMinimo': None, 'QtdSugerida': None, 'QtdPedido': Decimal('0'),
             'Fator': Decimal('1'), 'FornecedorID': None, 'FornecedorNome': None, 'CustoUnid': None,
             'DataPreco': None, 'Alerta': None}
            for it in rotina['itens'] if it['existe']]


def _calcular_itens(rotina, contados, dias, hoje, contagem_id):
    """Monta os itens da lista (quanto comprar e onde) para a rotina inteira."""
    pids = [i['produto_id'] for i in rotina['itens'] if i['existe']]
    conn = _conectar()
    try:
        cur = conn.cursor()
        precos = _precos_por_produto(cur, pids, hoje)
        minimos = _minimos(cur, pids)
        if not contagem_id:
            contagem_id = _ultima_contagem_id(cur)
    finally:
        conn.close()
    sug = _sugestao_por_produto(contagem_id, hoje)
    permitidos = set(rotina['fornecedores'])
    itens = []
    for it in rotina['itens']:
        if not it['existe']:
            continue
        pid = it['produto_id']
        info = sug.get(pid) or {}
        contado = contados.get(pid)
        alertas = []
        if contado is not None:
            estoque = contado
        elif info.get('EstoqueHoje') is not None:
            estoque = _dec(info['EstoqueHoje'])
            alertas.append("Não contado agora: usado o estoque estimado")
        else:
            estoque = Decimal('0')
            alertas.append("Sem contagem: estoque considerado zero")
        a = _alerta_consumo(info)
        if a:
            alertas.append(a)
        preco, aviso = escolher_fornecedor(precos.get(pid, []), permitidos)
        if aviso:
            alertas.append(aviso)
        conta = calcular_item(it, estoque, info.get('UsoMedioDiario') or 0, minimos.get(pid, 0),
                              dias, rotina['prazo_dias'], preco)
        itens.append({
            'ProdutoID': pid, 'Ordem': it['ordem'], 'Secao': it['secao'], 'NomeProduto': it['nome'][:255],
            'Unidade': it['unidade'][:20], 'QtdContada': contado, 'EstoqueUsado': estoque,
            'ConsumoDia': _dec(info.get('UsoMedioDiario') or 0), 'EstoqueMinimo': minimos.get(pid, Decimal('0')),
            'QtdSugerida': conta['QtdSugerida'], 'QtdPedido': conta['QtdPedido'], 'Fator': conta['Fator'],
            'FornecedorID': preco['FornecedorID'] if preco else None,
            'FornecedorNome': (preco['Fornecedor'] if preco else None),
            'CustoUnid': preco['CustoUnid'] if preco else None, 'DataPreco': preco['Data'] if preco else None,
            'Alerta': ' · '.join(alertas)[:250] or None,
        })
    return itens


def registrar_lista(codigo, rotina_id, usuario, dias, contagens, hoje=None, categorias=None):
    """
    Grava a contagem feita no celular e cria a lista de compras.
      codigo: identificador criado pelo celular (se o celular reenviar por causa de internet
              ruim, a mesma lista é devolvida, sem duplicar nada);
      usuario: {'id', 'nome', 'gestor'} de quem contou;
      contagens: [{'produto_id', 'qtd'}] (qtd None = item pulado).
    Gestor: a lista já sai APROVADA. Funcionário: fica AGUARDANDO o gestor.
    Se a mesma rotina já foi contada HOJE pelo app, a contagem anterior é trocada pela nova
    (senão as duas seriam somadas no estoque) e a lista anterior, se aberta, é cancelada.
    Itens que foram contados na vez anterior e NÃO recontados agora são mantidos na contagem nova.
    categorias: [CATEGORIAS] contou só estas categorias da rotina (ex.: ['Brinquedos']): a lista
              só tem os produtos delas e leva o nome "Rotina (Brinquedos)".
    """
    hoje = _como_data(hoje) or date.today()
    codigo = str(codigo or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9-]{8,40}', codigo):
        raise ErroCompras("Código da lista inválido.")
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        raise ErroCompras("Dias a cobrir inválido.")
    if not 1 <= dias <= DIAS_COBERTURA_MAX:
        raise ErroCompras(f"Dias a cobrir: de 1 a {DIAS_COBERTURA_MAX}.")

    existente = _buscar_lista_cabecalho(codigo)
    if existente and existente['status'] != ST_PROCESSANDO:
        lista = obter_lista(codigo)          # reenvio: devolve a mesma lista, sem gravar de novo
        lista['ja_existia'] = True
        return lista

    rotina = obter_rotina(rotina_id)
    cats = sorted({categoria_do(str(c)) for c in categorias[:100] if c is not None and str(c).strip()}) if isinstance(categorias, list) else []
    if cats:
        rotina['itens'] = [i for i in rotina['itens'] if categoria_do(i.get('categoria')) in cats]
        if not rotina['itens']:
            raise ErroCompras("Nenhum produto da rotina nessas categorias.")
        rotina['nome'] = f"{rotina['nome']} ({', '.join(cats)})"[:100]
    da_rotina = {i['produto_id'] for i in rotina['itens'] if i['existe']}
    contados, extras = {}, {}
    por_local = {}     # [VÁRIOS LOCAIS] {pid: {local: qtd}} do que foi contado agora
    for c in contagens or []:
        try:
            pid = int(c.get('produto_id'))
        except (TypeError, ValueError, AttributeError):
            raise ErroCompras("Item contado sem produto válido.")
        q = _qtd_valida(c.get('qtd'))
        if isinstance(c.get('locais'), dict) and c['locais']:
            locais = {}
            for local, ql in c['locais'].items():
                ql = _qtd_valida(ql)
                if ql is not None:
                    locais[str(local or '').strip()[:80]] = ql
            locais = _juntar_locais(locais)
            if locais:
                q = sum(locais.values(), Decimal('0'))     # o total é a soma dos locais
                por_local[pid] = {local: (ql, usuario.get('nome')) for local, ql in locais.items()}
        if pid not in da_rotina:
            # [BIPAR] produto bipado que não está na rotina: entra na contagem e na lista
            # (só se foi contado e existe no estoque); senão, ignora
            if q is not None and c.get('extra'):
                extras[pid] = q
            continue
        if q is not None:
            contados[pid] = q
    if extras:
        conn = _conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT ProdutoID, NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE ProdutoID IN ({','.join('?' * len(extras))})",
                        list(extras))
            achados = cur.fetchall()
        finally:
            conn.close()
        base = max([i['ordem'] for i in rotina['itens']] + [0]) + 1
        for k, (pid, nome, un) in enumerate(sorted(achados, key=lambda r: (r[1] or '').lower())):
            rotina['itens'].append({'produto_id': pid, 'ordem': base + k, 'secao': 'Bipados fora da rotina',
                                    'nome': nome or f'Produto {pid}', 'unidade': (un or 'UN').strip() or 'UN',
                                    'categoria': '', 'existe': True})
            contados[pid] = extras[pid]

    fora_da_lista = {}
    conn = _conectar()
    try:
        cur = conn.cursor()
        if existente:                        # tentativa anterior parou no meio: refaz
            lista_id, contagem_id = existente['lista_id'], existente['contagem_id']
            cur.execute("DELETE FROM CompraListaItens WHERE ListaID = ?", (lista_id,))
        else:
            fechadas = database.listar_valores_estoque_fechados(levantar_erro=True)
            herdados = {}                    # contados na vez anterior e NÃO recontados agora
            locais_ant = {}                  # [VÁRIOS LOCAIS] {pid: {local: qtd}} das contagens de hoje
            # a lista aberta de hoje da mesma rotina é trocada pela nova. [CATEGORIAS] a de OUTRAS categorias
            # (ex.: só Brinquedos, quando agora contou Descartáveis) continua valendo.
            cur.execute("SELECT Codigo, DataContagem, Status, NomeRotina FROM CompraListas WHERE RotinaID = ?", (int(rotina_id),))
            for cod_ant, d_ant, st_ant, nome_ant in cur.fetchall():
                if (cod_ant != codigo and _como_data(d_ant) == hoje and nome_ant == rotina['nome']
                        and st_ant not in (ST_FINALIZADA, ST_CANCELADA, ST_CONTAGEM)):
                    cur.execute("UPDATE CompraListas SET Status = ? WHERE Codigo = ?", (ST_CANCELADA, cod_ant))
            for cod_ant, cid_ant, st_ant in sorted(_contagens_substituidas(cur, rotina_id, hoje, codigo), key=lambda x: x[1] or 0):
                if cid_ant in fechadas:
                    continue                 # valor do estoque já fechado: não mexe
                cur.execute("SELECT ProdutoID, QuantidadeContada FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID IS NOT NULL",
                            (cid_ant,))
                for pid_ant, q_ant in cur.fetchall():
                    if pid_ant not in contados and q_ant is not None:
                        herdados[pid_ant] = _dec(q_ant)      # a contagem mais nova vence se repetir
                for pid_ant, locais in _breakdown(cur, cid_ant).items():
                    locais_ant[pid_ant] = _juntar_locais(locais_ant.get(pid_ant), locais)
                cur.execute("DELETE FROM CompraContagemLocais WHERE ContagemID = ?", (cid_ant,))
                cur.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ?", (cid_ant,))
                cur.execute("DELETE FROM ContagensEstoque WHERE ContagemID = ?", (cid_ant,))
                cur.execute("UPDATE CompraListas SET ContagemID = NULL WHERE Codigo = ?", (cod_ant,))
            for pid_ant, q_ant in herdados.items():
                if pid_ant in da_rotina:
                    contados[pid_ant] = q_ant          # entra na lista como contado
                else:
                    fora_da_lista[pid_ant] = q_ant     # bipado fora da rotina antes: só no estoque
            # [VÁRIOS LOCAIS] outra pessoa contou OUTRO local do mesmo produto hoje: SOMA (o mesmo local, vale o mais novo).
            # Antes a contagem mais nova trocava o número inteiro e o outro local se perdia.
            detalhe = {}
            for pid, ant in locais_ant.items():
                if pid in por_local:
                    detalhe[pid] = _juntar_locais(ant, por_local[pid])
                elif pid in herdados:
                    detalhe[pid] = dict(ant)
            for pid, locais in por_local.items():
                detalhe.setdefault(pid, _juntar_locais(locais))
            for pid, locais in detalhe.items():
                total = sum((ql for ql, _ in locais.values()), Decimal('0'))
                if pid in contados:
                    contados[pid] = total
                elif pid in fora_da_lista:
                    fora_da_lista[pid] = total
                elif pid in extras:
                    extras[pid] = total
            contagem_id = None
            if contados or fora_da_lista:
                cur.execute("""INSERT INTO ContagensEstoque (DataContagem, FuncionarioID, NomeContagem)
                               OUTPUT INSERTED.ContagemID VALUES (?, ?, ?)""",
                            (hoje, usuario['id'], f"App compras: {rotina['nome']}"[:100]))
                contagem_id = int(cur.fetchone()[0])
                for pid, q in list(contados.items()) + list(fora_da_lista.items()):
                    cur.execute("""INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada, NomeAvulso, EANAvulso)
                                   VALUES (?, ?, ?, NULL, NULL)""", (contagem_id, pid, q))
                for pid, locais in detalhe.items():
                    if pid in contados or pid in fora_da_lista:
                        for local, (ql, por) in locais.items():
                            cur.execute("INSERT INTO CompraContagemLocais (ContagemID, ProdutoID, Local, Qtd, ContadoPor) VALUES (?, ?, ?, ?, ?)",
                                        (contagem_id, pid, local, ql, (por or '')[:150] or None))
            cur.execute("""INSERT INTO CompraListas (Codigo, RotinaID, NomeRotina, FuncionarioID, NomeFuncionario, CriadaEm,
                                                    DataContagem, DiasCobertura, PrazoDias, Status, ContagemID)
                           OUTPUT INSERTED.ListaID VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (codigo, rotina['id'], rotina['nome'], usuario['id'], usuario.get('nome'), datetime.now(),
                         hoje, dias, rotina['prazo_dias'], ST_PROCESSANDO, contagem_id))
            lista_id = int(cur.fetchone()[0])
        conn.commit()                        # a contagem fica gravada antes do cálculo (que lê o banco)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    encerrar_andamento(codigo)              # [PAINEL DO BALANÇO] terminou: sai do "contando agora"

    if rotina.get('so_contagem'):
        itens = _itens_so_contagem(rotina, contados)
        status = ST_CONTAGEM
    else:
        itens = _calcular_itens(rotina, contados, dias, hoje, contagem_id)
        status = ST_APROVADA if usuario.get('gestor') else ST_AGUARDANDO
    valor = sum((i['QtdPedido'] * i['CustoUnid'] for i in itens if i['CustoUnid'] and i['QtdPedido'] > 0), Decimal('0'))
    conn = _conectar()
    try:
        cur = conn.cursor()
        for i in itens:
            cur.execute("""INSERT INTO CompraListaItens (ListaID, ProdutoID, Ordem, Secao, NomeProduto, Unidade, QtdContada,
                               EstoqueUsado, ConsumoDia, EstoqueMinimo, QtdSugerida, QtdPedido, Fator, FornecedorID,
                               FornecedorNome, CustoUnid, DataPreco, Situacao, Alerta)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)""",
                        (lista_id, i['ProdutoID'], i['Ordem'], i['Secao'] or None, i['NomeProduto'], i['Unidade'],
                         i['QtdContada'], i['EstoqueUsado'], i['ConsumoDia'], i['EstoqueMinimo'], i['QtdSugerida'],
                         i['QtdPedido'], i['Fator'], i['FornecedorID'], i['FornecedorNome'], i['CustoUnid'],
                         i['DataPreco'], i['Alerta']))
        cur.execute("""UPDATE CompraListas SET Status = ?, ValorEstimado = ?, AprovadaPor = ?, AprovadaEm = ?
                       WHERE ListaID = ?""",
                    (status, valor.quantize(Decimal('0.01')), usuario.get('nome') if status == ST_APROVADA else None,
                     datetime.now() if status == ST_APROVADA else None, lista_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obter_lista(codigo)


def _buscar_lista_cabecalho(codigo):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT ListaID, Codigo, RotinaID, NomeRotina, FuncionarioID, NomeFuncionario, CriadaEm, DataContagem,
                              DiasCobertura, PrazoDias, Status, ContagemID, AprovadaPor, AprovadaEm, FinalizadaEm, ValorEstimado
                       FROM CompraListas WHERE Codigo = ?""", (str(codigo),))
        r = cur.fetchone()
        if not r:
            return None
        return {'lista_id': r[0], 'codigo': r[1], 'rotina_id': r[2], 'rotina': r[3], 'funcionario_id': r[4],
                'funcionario': r[5], 'criada_em': _iso(r[6]), 'data_contagem': _iso(_como_data(r[7])),
                'dias_cobertura': int(r[8] or 0), 'prazo_dias': int(r[9] or 0), 'status': r[10],
                'contagem_id': r[11], 'aprovada_por': r[12], 'aprovada_em': _iso(r[13]),
                'finalizada_em': _iso(r[14]), 'valor_estimado': _num(r[15], 2)}
    finally:
        conn.close()


def obter_lista(codigo):
    cab = _buscar_lista_cabecalho(codigo)
    if not cab or cab['status'] == ST_PROCESSANDO:
        raise ErroCompras("Lista não encontrada.")
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT ProdutoID, Ordem, Secao, NomeProduto, Unidade, QtdContada, EstoqueUsado, ConsumoDia,
                              EstoqueMinimo, QtdSugerida, QtdPedido, Fator, FornecedorID, FornecedorNome, CustoUnid,
                              DataPreco, Situacao, Alerta
                       FROM CompraListaItens WHERE ListaID = ? ORDER BY Ordem, ProdutoID""", (cab['lista_id'],))
        itens = []
        for r in cur.fetchall():
            fator = _dec(r[11]) if r[11] is not None else Decimal('1')
            qtd = _dec(r[10])
            itens.append({'produto_id': r[0], 'ordem': r[1], 'secao': r[2] or '', 'nome': r[3], 'unidade': r[4],
                          'qtd_contada': _num(r[5]), 'estoque': _num(r[6]), 'consumo_dia': _num(r[7], 4),
                          'estoque_minimo': _num(r[8]), 'qtd_sugerida': _num(r[9]), 'qtd_pedido': _num(qtd),
                          'fator': _num(fator), 'caixas': _num(qtd / fator) if fator > 1 else None,
                          'fornecedor_id': r[12], 'fornecedor': r[13], 'custo': _num(r[14], 4),
                          'data_preco': _iso(_como_data(r[15])), 'situacao': r[16] or '', 'alerta': r[17]})
    finally:
        conn.close()
    cab.pop('lista_id', None)
    cab['itens'] = itens
    cab['qtd_contados'] = sum(1 for i in itens if i['qtd_contada'] is not None)
    cab['qtd_comprar'] = sum(1 for i in itens if (i['qtd_pedido'] or 0) > 0)
    return cab


def listar_listas(limite=30, dias=45, hoje=None):
    """Listas recentes (as abertas primeiro)."""
    hoje = _como_data(hoje) or date.today()
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT L.Codigo, L.NomeRotina, L.NomeFuncionario, L.CriadaEm, L.DiasCobertura, L.Status, L.ValorEstimado,
                   (SELECT COUNT(*) FROM CompraListaItens I WHERE I.ListaID = L.ListaID AND I.QtdPedido > 0),
                   (SELECT COUNT(*) FROM CompraListaItens I WHERE I.ListaID = L.ListaID AND I.QtdPedido > 0 AND I.Situacao <> ''),
                   L.FuncionarioID, L.RotinaID
            FROM CompraListas L
            WHERE L.Status <> ? AND L.Status <> ?
        """, (ST_PROCESSANDO, ST_CONTAGEM))
        listas = []
        limite_data = hoje - timedelta(days=dias)
        for r in cur.fetchall():
            criada = _como_datahora(r[3])
            if r[5] in (ST_FINALIZADA, ST_CANCELADA) and criada and criada.date() < limite_data:
                continue
            listas.append({'codigo': r[0], 'rotina': r[1], 'funcionario': r[2], 'criada_em': _iso(criada),
                           'dias_cobertura': r[4], 'status': r[5], 'valor_estimado': _num(r[6], 2),
                           'qtd_comprar': int(r[7] or 0), 'qtd_marcados': int(r[8] or 0),
                           'funcionario_id': r[9], 'rotina_id': r[10]})
        ordem = {ST_AGUARDANDO: 0, ST_APROVADA: 1, ST_FINALIZADA: 2, ST_CANCELADA: 3}
        listas.sort(key=lambda l: (ordem.get(l['status'], 9), l['criada_em'] or ''), reverse=False)
        abertas = [l for l in listas if l['status'] in (ST_AGUARDANDO, ST_APROVADA)]
        fechadas = sorted([l for l in listas if l['status'] not in (ST_AGUARDANDO, ST_APROVADA)],
                          key=lambda l: l['criada_em'] or '', reverse=True)
        abertas.sort(key=lambda l: (ordem[l['status']], l['criada_em'] or ''))
        return (abertas + fechadas)[:limite]
    finally:
        conn.close()


def atualizar_itens(codigo, mudancas, usuario):
    """
    Muda itens da lista: quantidade a comprar e/ou situação no carrinho.
      mudancas: [{'produto_id', 'qtd_pedido'?, 'situacao'?}]
    Regras: lista finalizada/cancelada não muda; enquanto AGUARDA aprovação só o gestor
    mexe nas quantidades e ninguém marca o carrinho.
    """
    cab = _buscar_lista_cabecalho(codigo)
    if not cab or cab['status'] == ST_PROCESSANDO:
        raise ErroCompras("Lista não encontrada.")
    if cab['status'] in (ST_FINALIZADA, ST_CANCELADA):
        raise ErroCompras(f"Esta lista já está {cab['status']} e não pode mais mudar.")
    conn = _conectar()
    try:
        cur = conn.cursor()
        for m in mudancas or []:
            try:
                pid = int(m.get('produto_id'))
            except (TypeError, ValueError, AttributeError):
                raise ErroCompras("Item sem produto válido.")
            if 'qtd_pedido' in m:
                if cab['status'] == ST_AGUARDANDO and not usuario.get('gestor'):
                    raise ErroCompras("Só o gestor muda quantidades antes de aprovar a lista.")
                q = _qtd_valida(m.get('qtd_pedido'), "Quantidade a comprar")
                cur.execute("UPDATE CompraListaItens SET QtdPedido = ? WHERE ListaID = ? AND ProdutoID = ?",
                            (q if q is not None else Decimal('0'), cab['lista_id'], pid))
            if 'situacao' in m:
                sit = str(m.get('situacao') or '')
                if sit not in SITUACOES_ITEM:
                    raise ErroCompras("Situação do item inválida.")
                if cab['status'] != ST_APROVADA:
                    raise ErroCompras("A lista ainda não foi aprovada pelo gestor.")
                cur.execute("UPDATE CompraListaItens SET Situacao = ? WHERE ListaID = ? AND ProdutoID = ?",
                            (sit, cab['lista_id'], pid))
        cur.execute("""SELECT QtdPedido, CustoUnid FROM CompraListaItens WHERE ListaID = ?""", (cab['lista_id'],))
        valor = sum((_dec(q) * _dec(c) for q, c in cur.fetchall() if c is not None), Decimal('0'))
        cur.execute("UPDATE CompraListas SET ValorEstimado = ? WHERE ListaID = ?", (valor.quantize(Decimal('0.01')), cab['lista_id']))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obter_lista(codigo)


def _mudar_status(codigo, de, para, campos_extra=None):
    cab = _buscar_lista_cabecalho(codigo)
    if not cab or cab['status'] == ST_PROCESSANDO:
        raise ErroCompras("Lista não encontrada.")
    if cab['status'] not in de:
        nomes = {ST_AGUARDANDO: 'aguardando aprovação', ST_APROVADA: 'aprovada', ST_FINALIZADA: 'finalizada',
                 ST_CANCELADA: 'cancelada'}
        raise ErroCompras(f"Não dá: a lista está {nomes.get(cab['status'], cab['status'])}.")
    sets, valores = ["Status = ?"], [para]
    for coluna, valor in (campos_extra or {}).items():
        sets.append(f"{coluna} = ?")
        valores.append(valor)
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE CompraListas SET {', '.join(sets)} WHERE Codigo = ? AND Status = ?",
                    valores + [codigo, cab['status']])
        if cur.rowcount == 0:
            raise ErroCompras("A lista mudou em outro celular. Atualize a tela.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obter_lista(codigo)


def aprovar_lista(codigo, usuario):
    if not usuario.get('gestor'):
        raise ErroCompras("Só o gestor aprova listas.")
    return _mudar_status(codigo, (ST_AGUARDANDO,), ST_APROVADA,
                         {'AprovadaPor': usuario.get('nome'), 'AprovadaEm': datetime.now()})


def finalizar_lista(codigo, usuario):
    lista = _mudar_status(codigo, (ST_APROVADA,), ST_FINALIZADA, {'FinalizadaEm': datetime.now()})
    comprar = [i for i in lista['itens'] if (i['qtd_pedido'] or 0) > 0]
    lista['resumo'] = {
        'comprados': sum(1 for i in comprar if i['situacao'] == SIT_COMPRADO),
        'faltaram': [i['nome'] for i in comprar if i['situacao'] == SIT_FALTOU],
        'sem_marcar': [i['nome'] for i in comprar if i['situacao'] == ''],
    }
    return lista


def cancelar_lista(codigo, usuario):
    cab = _buscar_lista_cabecalho(codigo)
    if cab and not usuario.get('gestor') and cab['funcionario_id'] != usuario.get('id'):
        raise ErroCompras("Só o gestor ou quem fez a contagem pode cancelar a lista.")
    return _mudar_status(codigo, (ST_AGUARDANDO, ST_APROVADA), ST_CANCELADA)


# ==============================================================================
# == Códigos de barras (bipar no Android) ======================================
# ==============================================================================
# De onde vêm os códigos:
#   1) os vínculos do Gestão de Estoque (EAN que veio no XML de cada compra, com o
#      Qtd/Cx do vínculo: o código da CAIXA já vem com o fator dela);
#   2) códigos ligados pelo gestor no próprio app (tabela CompraCodigos), quando o
#      produto foi bipado e o sistema ainda não conhecia o código.

def normalizar_codigo(codigo):
    """Só números, com zeros à esquerda até 14 (assim EAN-13, UPC-A e GTIN-14 se encontram)."""
    d = re.sub(r'\D', '', str(codigo or ''))
    if not 8 <= len(d) <= 14 or not d.strip('0'):
        return None
    return d.zfill(14)


def _garantir_tabela_codigos(cur):
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraCodigos')
        CREATE TABLE CompraCodigos (
            Codigo VARCHAR(14) NOT NULL PRIMARY KEY,
            ProdutoID INT NOT NULL,
            Fator DECIMAL(18, 4) NOT NULL DEFAULT 1,
            CriadoPor NVARCHAR(150) NULL,
            CriadoEm DATETIME NULL
        )
    """)


def listar_codigos():
    """
    Mapa {codigo14: [{'produto_id', 'fator', 'nome', 'unidade'}]} para o celular guardar
    (bipar funciona sem internet). Um código pode apontar para mais de um produto se os
    vínculos estiverem confusos: o celular pergunta qual é.
    """
    conn = _conectar()
    try:
        cur = conn.cursor()
        _garantir_tabela_codigos(cur)
        conn.commit()
        cur.execute("""SELECT PF.EAN, PF.ProdutoID, PF.FatorConversao FROM ProdutosFornecedor PF
                       WHERE PF.ProdutoID IS NOT NULL AND PF.EAN IS NOT NULL AND PF.EAN <> ''""")
        mapa = {}
        for ean, pid, fator in cur.fetchall():
            cod = normalizar_codigo(ean)
            if not cod:
                continue
            f = _dec(fator) if fator is not None and _dec(fator) > 0 else Decimal('1')
            lista = mapa.setdefault(cod, [])
            if not any(x[0] == pid and x[1] == f for x in lista):
                lista.append((pid, f))
        cur.execute("SELECT Codigo, ProdutoID, Fator FROM CompraCodigos")
        for cod, pid, fator in cur.fetchall():          # ligado pelo gestor: vale mais que o XML
            mapa[str(cod).zfill(14)] = [(pid, _dec(fator) if fator else Decimal('1'))]
        cur.execute("SELECT ProdutoID, NomeProduto, UnidadeMedida FROM ProdutosEstoque")
        nomes = {p: (n or f'Produto {p}', (u or 'UN').strip() or 'UN') for p, n, u in cur.fetchall()}
        resultado = {}
        for cod, lista in mapa.items():
            itens = [{'produto_id': pid, 'fator': _num(f), 'nome': nomes[pid][0], 'unidade': nomes[pid][1]}
                     for pid, f in lista if pid in nomes]
            if itens:
                resultado[cod] = itens
        return resultado
    finally:
        conn.close()


def vincular_codigo(codigo, produto_id, fator, usuario):
    """O gestor diz que um código bipado (desconhecido) é tal produto (e quantas unidades vêm nele)."""
    if not usuario.get('gestor'):
        raise ErroCompras("Só o gestor cadastra códigos de barras.")
    cod = normalizar_codigo(codigo)
    if not cod:
        raise ErroCompras("Código de barras inválido.")
    try:
        produto_id = int(produto_id)
        f = Decimal(str(fator if fator not in (None, '') else 1).replace(',', '.'))
    except (TypeError, ValueError, InvalidOperation):
        raise ErroCompras("Produto ou quantidade inválidos.")
    if not f.is_finite() or f <= 0 or f > 100000:
        raise ErroCompras("A quantidade por embalagem precisa ser maior que zero.")
    conn = _conectar()
    try:
        cur = conn.cursor()
        _garantir_tabela_codigos(cur)
        cur.execute("SELECT 1 FROM ProdutosEstoque WHERE ProdutoID = ?", (produto_id,))
        if not cur.fetchone():
            raise ErroCompras("Produto não encontrado no estoque.")
        cur.execute("DELETE FROM CompraCodigos WHERE Codigo = ?", (cod,))
        cur.execute("INSERT INTO CompraCodigos (Codigo, ProdutoID, Fator, CriadoPor, CriadoEm) VALUES (?, ?, ?, ?, ?)",
                    (cod, produto_id, f, usuario.get('nome'), datetime.now()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"Código {cod} ligado ao produto {produto_id} (fator {f}) por {usuario.get('nome')}")
    return {'codigo': cod, 'itens': listar_codigos().get(cod, [])}


# ==============================================================================
# == Incluir item na lista "na mão" ===========================================
# ==============================================================================

def adicionar_item(codigo, produto_id, qtd, usuario):
    """
    Coloca na lista um produto que o sistema NÃO sugeriu (ainda está aprendendo o consumo,
    ou você quer comprar mesmo assim). Se o produto já está na lista, só muda a quantidade.
    Mesmas regras das quantidades: lista aguardando aprovação = só o gestor mexe.
    """
    cab = _buscar_lista_cabecalho(codigo)
    if not cab or cab['status'] == ST_PROCESSANDO:
        raise ErroCompras("Lista não encontrada.")
    if cab['status'] in (ST_FINALIZADA, ST_CANCELADA):
        raise ErroCompras(f"Esta lista já está {cab['status']} e não pode mais mudar.")
    if cab['status'] == ST_AGUARDANDO and not usuario.get('gestor'):
        raise ErroCompras("Só o gestor mexe na lista antes de aprovar.")
    try:
        produto_id = int(produto_id)
    except (TypeError, ValueError):
        raise ErroCompras("Produto inválido.")
    q = _qtd_valida(qtd, "Quantidade a comprar")
    if q is None or q <= 0:
        raise ErroCompras("Informe quanto comprar.")
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM CompraListaItens WHERE ListaID = ? AND ProdutoID = ?", (cab['lista_id'], produto_id))
        if cur.fetchone():
            cur.execute("UPDATE CompraListaItens SET QtdPedido = ? WHERE ListaID = ? AND ProdutoID = ?",
                        (q, cab['lista_id'], produto_id))
        else:
            cur.execute("SELECT NomeProduto, UnidadeMedida, EstoqueMinimo FROM ProdutosEstoque WHERE ProdutoID = ?", (produto_id,))
            p = cur.fetchone()
            if not p:
                raise ErroCompras("Produto não encontrado no estoque.")
            permitidos = set()
            if cab['rotina_id']:
                cur.execute("SELECT Fornecedores FROM CompraRotinas WHERE RotinaID = ?", (cab['rotina_id'],))
                r = cur.fetchone()
                permitidos = set(_ler_ids(r[0])) if r else set()
            hoje = _como_data(cab['data_contagem']) or date.today()
            preco, _ = escolher_fornecedor(_precos_por_produto(cur, [produto_id], hoje).get(produto_id, []), permitidos)
            fator = _dec(preco['Fator']) if preco and _dec(preco['Fator']) > 1 else Decimal('1')
            cur.execute("SELECT COALESCE(MAX(Ordem), 0) FROM CompraListaItens WHERE ListaID = ?", (cab['lista_id'],))
            ordem = int(cur.fetchone()[0] or 0) + 1
            cur.execute("""INSERT INTO CompraListaItens (ListaID, ProdutoID, Ordem, Secao, NomeProduto, Unidade, QtdContada,
                               EstoqueUsado, ConsumoDia, EstoqueMinimo, QtdSugerida, QtdPedido, Fator, FornecedorID,
                               FornecedorNome, CustoUnid, DataPreco, Situacao, Alerta)
                           VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, 0, ?, ?, ?, ?, ?, ?, '', ?)""",
                        (cab['lista_id'], produto_id, ordem, 'Incluídos na mão', (p[0] or f'Produto {produto_id}')[:255],
                         ((p[1] or 'UN').strip() or 'UN')[:20], _dec(p[2]), q, fator,
                         preco['FornecedorID'] if preco else None, preco['Fornecedor'] if preco else None,
                         preco['CustoUnid'] if preco else None, preco['Data'] if preco else None,
                         f"Incluído na mão por {usuario.get('nome') or 'alguém'}"[:250]))
        cur.execute("SELECT QtdPedido, CustoUnid FROM CompraListaItens WHERE ListaID = ?", (cab['lista_id'],))
        valor = sum((_dec(a) * _dec(b) for a, b in cur.fetchall() if b is not None), Decimal('0'))
        cur.execute("UPDATE CompraListas SET ValorEstimado = ? WHERE ListaID = ?", (valor.quantize(Decimal('0.01')), cab['lista_id']))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"Lista {codigo}: produto {produto_id} incluído/ajustado na mão por {usuario.get('nome')} ({q}).")
    return obter_lista(codigo)


# ==============================================================================
# == [PAINEL DO GESTOR] resumo para a aba "Gestão" do app ======================
# ==============================================================================

# ==============================================================================
# == [PAINEL DO BALANÇO] quem está contando o quê, e o que falta ================
# ==============================================================================
ANDAMENTO_PARADO_MIN = 10        # sem notícia do celular há mais que isso: "parado"
MAX_PRODUTOS_ANDAMENTO = 5000


def registrar_andamento(codigo, rotina_id, usuario, dados, agora=None):
    """
    O celular avisa o que já contou: dados = {'local': local em que está agora,
    'contados': {local: [ProdutoID, ...]}, 'total': nº de linhas que escolheu contar}.
    Grava por cima do aviso anterior do mesmo celular (mesmo código de contagem).
    """
    agora = agora or datetime.now()
    codigo = str(codigo or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9-]{8,40}', codigo):
        raise ErroCompras("Código da contagem inválido.")
    try:
        rotina_id = int(rotina_id)
    except (TypeError, ValueError):
        raise ErroCompras("Rotina inválida.")
    dados = dados if isinstance(dados, dict) else {}
    contados, n = {}, 0
    for local, pids in (dados.get('contados') or {}).items() if isinstance(dados.get('contados'), dict) else []:
        lista = []
        for pid in pids if isinstance(pids, list) else []:
            try:
                lista.append(int(pid))
            except (TypeError, ValueError):
                continue
        n += len(lista)
        if n > MAX_PRODUTOS_ANDAMENTO:
            raise ErroCompras("Contagem grande demais.")
        contados[str(local or '').strip()[:80]] = sorted(set(lista))
    try:
        total = max(0, min(int(dados.get('total') or 0), MAX_PRODUTOS_ANDAMENTO))
    except (TypeError, ValueError):
        total = 0
    texto = json.dumps({'local': str(dados.get('local') or '').strip()[:80], 'contados': contados, 'total': total})
    garantir_tabelas()
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM CompraListas WHERE Codigo = ?", (codigo,))
        if cur.fetchone()[0]:
            return {'ok': True, 'ja_salva': True}   # chegou depois de salvar (internet lenta): ignora
        cur.execute("DELETE FROM CompraContagemAndamento WHERE Codigo = ? OR Dia < ?", (codigo, agora.date()))
        cur.execute("""INSERT INTO CompraContagemAndamento (Codigo, RotinaID, Dia, FuncionarioID, Usuario, Dados, Atualizado)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (codigo, rotina_id, agora.date(), usuario.get('id'), (usuario.get('nome') or '')[:150], texto, agora))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'ok': True}


def encerrar_andamento(codigo):
    """A contagem foi salva ou descartada: some do painel. Nunca atrapalha quem chamou."""
    try:
        garantir_tabelas()
        conn = _conectar()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM CompraContagemAndamento WHERE Codigo = ?", (str(codigo or '')[:40],))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"App de compras: não deu para tirar a contagem {codigo} do painel: {e}")
    return {'ok': True}


def painel_balanco(rotina_id, agora=None):
    """
    Para o gestor acompanhar o balanço AO VIVO: em cada local, quantos itens já têm número
    (salvos hoje + o que os celulares estão contando agora), quem está lá e o que falta.
    """
    agora = agora or datetime.now()
    hoje = agora.date()
    rotina = obter_rotina(rotina_id)
    garantir_tabelas()
    conn = _conectar()
    try:
        cur = conn.cursor()
        anteriores = _contagens_substituidas(cur, rotina_id, hoje)
        salvos_locais = _locais_contados_hoje(cur, anteriores)          # {pid: {local: {qtd, por}}}
        salvos = set()
        for _, cid, _ in anteriores:
            cur.execute("SELECT ProdutoID FROM ItensContagemEstoque WHERE ContagemID = ? AND ProdutoID IS NOT NULL", (cid,))
            salvos.update(r[0] for r in cur.fetchall())
        cur.execute("SELECT Codigo, Usuario, Dados, Atualizado FROM CompraContagemAndamento WHERE RotinaID = ? AND Dia = ?",
                    (int(rotina_id), hoje))
        andamento = []
        for cod, nome, texto, quando in cur.fetchall():
            try:
                d = json.loads(texto or '{}')
            except ValueError:
                d = {}
            quando = _como_datahora(quando) or agora
            andamento.append({'codigo': cod, 'nome': nome or '?', 'local': d.get('local') or '', 'total': d.get('total') or 0,
                              'contados': {l: set(v) for l, v in (d.get('contados') or {}).items()},
                              'minutos': max(0, int((agora - quando).total_seconds() // 60))})
    finally:
        conn.close()

    locais = {}       # local -> {'itens': [(pid, nome)]}
    for it in rotina['itens']:
        if not it['existe']:
            continue
        for local in (it.get('locais') or [it.get('secao') or SEM_LOCAL]):
            locais.setdefault(local, []).append((it['produto_id'], it['nome']))
    resultado = []
    for local, itens in locais.items():
        feitos, quem = set(), {}
        for pid, _ in itens:
            no_local = (salvos_locais.get(pid) or {}).get(local)
            if no_local:
                feitos.add(pid)
                quem[no_local['por']] = quem.get(no_local['por'], 0) + 1
            elif pid in salvos and not salvos_locais.get(pid):
                feitos.add(pid)                # salvo sem o detalhe por local (versão antiga do app)
        agora_aqui = []
        for a in andamento:
            meus = a['contados'].get(local, set()) & {pid for pid, _ in itens}
            if meus:
                quem[a['nome']] = quem.get(a['nome'], 0) + len(meus - feitos)
            feitos |= meus
            if a['local'] == local and a['minutos'] < ANDAMENTO_PARADO_MIN:
                agora_aqui.append(a['nome'])
        pendentes = [nome for pid, nome in itens if pid not in feitos]
        resultado.append({'local': local, 'total': len(itens), 'feitos': len(itens) - len(pendentes),
                          'pendentes': pendentes[:40], 'mais_pendentes': max(0, len(pendentes) - 40),
                          'contando_agora': sorted(set(agora_aqui)),
                          'quem': [{'nome': n, 'itens': q} for n, q in sorted(quem.items(), key=lambda x: -x[1]) if q]})
    total = sum(l['total'] for l in resultado)
    feitos = sum(l['feitos'] for l in resultado)
    return {'rotina': {'id': rotina['id'], 'nome': rotina['nome']}, 'dia': _iso(hoje), 'atualizado': _iso(agora),
            'total': total, 'feitos': feitos, 'locais': resultado,
            'pessoas': [{'nome': a['nome'], 'local': a['local'], 'feitos': sum(len(v) for v in a['contados'].values()),
                         'total': a['total'], 'minutos': a['minutos'], 'parado': a['minutos'] >= ANDAMENTO_PARADO_MIN}
                        for a in sorted(andamento, key=lambda a: a['nome'])],
            'salvas': len(anteriores)}


# ==============================================================================
# == [DIFERENÇAS EM R$] contado x esperado no balanço ===========================
# ==============================================================================
# "Esperado" = última contagem ANTES do balanço + o que entrou de nota desde então
#              − consumo médio por dia × dias. Não há registro de vendas por produto,
# então o esperado é uma ESTIMATA: diferença pequena é normal (o consumo varia).
TOLERANCIA_DIF = Decimal('0.05')       # até 5% (ou meia unidade) conta como "bateu"


def diferencas_balanco(rotina_id, dia=None):
    rotina = obter_rotina(rotina_id)
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DataContagem, ContagemID FROM CompraListas WHERE RotinaID = ? AND ContagemID IS NOT NULL",
                    (int(rotina_id),))
        por_dia = {}
        for d, cid in cur.fetchall():
            d = _como_data(d)
            if d:
                por_dia.setdefault(d, set()).add(cid)
        if not por_dia:
            raise ErroCompras("Esta rotina ainda não tem contagem salva.")
        dia = _como_data(dia) or max(por_dia)
        if dia not in por_dia:
            raise ErroCompras(f"Não há contagem desta rotina em {dia.strftime('%d/%m/%Y')}.")
        cur.execute("SELECT ContagemID, DataContagem FROM ContagensEstoque")
        datas = {cid: _como_data(d) for cid, d in cur.fetchall()}
        do_dia = [cid for cid, d in datas.items() if d == dia]
        cur.execute(f"""SELECT ProdutoID FROM ItensContagemEstoque WHERE ProdutoID IS NOT NULL
                        AND ContagemID IN ({','.join('?' * len(por_dia[dia]))})""", list(por_dia[dia]))
        pids = sorted({r[0] for r in cur.fetchall()})
        contado = {}
        if pids and do_dia:
            # o estoque soma todas as contagens do mesmo dia (igual ao Gestão de Estoque)
            cur.execute(f"""SELECT ProdutoID, QuantidadeContada FROM ItensContagemEstoque
                            WHERE ContagemID IN ({','.join('?' * len(do_dia))}) AND {_em('ProdutoID', pids)[0]}""",
                        do_dia + _em('ProdutoID', pids)[1])
            for pid, q in cur.fetchall():
                contado[pid] = contado.get(pid, Decimal('0')) + _dec(q)
        antes = [(d, cid) for cid, d in datas.items() if d and d < dia]
        compras = _compras_recentes(cur, pids, dia)
        nomes = {}
        if pids:
            filtro, params = _em('ProdutoID', pids)
            cur.execute(f"SELECT ProdutoID, NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE {filtro}", params)
            nomes = {pid: (nome or f'Produto {pid}', (un or 'UN').strip() or 'UN') for pid, nome, un in cur.fetchall()}
    finally:
        conn.close()
    sug = _sugestao_por_produto(max(antes)[1], dia) if antes else {}

    perdas, sobras, bateu, sem_base = [], [], [], []
    for pid in pids:
        nome, un = nomes.get(pid, (f'Produto {pid}', 'UN'))
        info = sug.get(pid) or {}
        lista = compras.get(pid, [])
        pagas = [c for c in lista if c[2] > 0]
        custo = pagas[-1][2] if pagas else None
        linha = {'produto_id': pid, 'nome': nome, 'unidade': un, 'contado': _num(contado.get(pid, Decimal('0'))),
                 'custo': _num(custo, 4) if custo is not None else None}
        d_l = _como_data(info.get('DataUltimaContagem'))
        if not info.get('Contado') or not d_l or info.get('ConsumoNegativo') or info.get('MetodoConsumo') == 'sem_dados':
            linha['motivo'] = 'nunca tinha sido contado' if not info.get('Contado') else 'ainda sem consumo médio confiável'
            sem_base.append(linha)
            continue
        entrou = sum((c[1] for c in lista if d_l < c[0] <= dia), Decimal('0'))
        uso = _dec(info.get('UsoMedioDiario'))
        dias = (dia - d_l).days
        esperado = max(_dec(info.get('QtdUltimaContagem')) + entrou - uso * dias, Decimal('0'))
        dif = contado.get(pid, Decimal('0')) - esperado
        linha.update({'esperado': _num(esperado), 'diferenca': _num(dif),
                      'valor': _num(dif * custo, 2) if custo is not None else None,
                      'base': {'tinha': _num(info.get('QtdUltimaContagem')), 'em': _iso(d_l), 'entrou': _num(entrou),
                               'consumo_dia': _num(uso, 3), 'dias': dias}})
        if abs(dif) <= max(Decimal('0.5'), esperado * TOLERANCIA_DIF):
            bateu.append(linha)
        elif dif < 0:
            perdas.append(linha)
        else:
            sobras.append(linha)
    perdas.sort(key=lambda l: (l['valor'] if l['valor'] is not None else 0, l['diferenca']))
    sobras.sort(key=lambda l: (-(l['valor'] or 0), -l['diferenca']))
    soma = lambda ls: _num(sum((_dec(l['valor']) for l in ls if l['valor'] is not None), Decimal('0')), 2)
    return {'rotina': {'id': rotina['id'], 'nome': rotina['nome']}, 'dia': _iso(dia),
            'dias': [_iso(d) for d in sorted(por_dia, reverse=True)[:12]],
            'perdas': perdas, 'sobras': sobras, 'bateu': bateu, 'sem_base': sem_base,
            'total_perdas': soma(perdas), 'total_sobras': soma(sobras),
            'saldo': _num(_dec(soma(perdas)) + _dec(soma(sobras)), 2),
            'sem_custo': sum(1 for l in perdas + sobras if l['valor'] is None)}

def painel_gestor(hoje=None):
    """
    Números para o gestor (o operacional não vê): listas por situação, compras do mês pelas
    notas de entrada, itens acabando / abaixo do mínimo, preços que subiram e listas esquecidas.
    Cada bloco é independente: se um falhar, os outros aparecem (o erro vai em 'avisos').
    """
    hoje = _como_data(hoje) or date.today()
    painel = {'gerado_em': _iso(datetime.now()), 'avisos': []}

    try:
        conn = _conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT Status, COUNT(*), SUM(ValorEstimado) FROM CompraListas GROUP BY Status")
            por_status = {r[0]: {'qtd': int(r[1] or 0), 'valor': _num(r[2] or 0, 2)} for r in cur.fetchall()}
        finally:
            conn.close()
        painel['listas'] = {st: por_status.get(st, {'qtd': 0, 'valor': 0}) for st in (ST_AGUARDANDO, ST_APROVADA)}
    except Exception as e:
        logger.error(f"Painel: listas: {e}", exc_info=True)
        painel['avisos'].append("Listas: não deu para ler agora.")

    try:
        inicio_mes = hoje.replace(day=1)
        inicio_ant = (inicio_mes - timedelta(days=1)).replace(day=1)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT NF.DataEmissao, NF.ValorTotalNF, F.NomeFantasia, F.CNPJ
                           FROM NotasFiscaisEntrada NF LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
                           WHERE NF.DataEmissao >= ?""", (inicio_ant,))
            linhas = cur.fetchall()
        finally:
            conn.close()
        mes, ant, por_forn = Decimal('0'), Decimal('0'), {}
        for d, valor, nome, cnpj in linhas:
            d = _como_data(d)
            if not d or (cnpj or '').strip() == database.CNPJ_FORNECEDOR_INTERNO:
                continue
            if d >= inicio_mes:
                mes += _dec(valor)
                chave = nome or cnpj or 'Fornecedor'
                por_forn[chave] = por_forn.get(chave, Decimal('0')) + _dec(valor)
            elif d >= inicio_ant:
                ant += _dec(valor)
        painel['compras'] = {'mes': _num(mes, 2), 'mes_anterior': _num(ant, 2), 'nome_mes': inicio_mes.strftime('%m/%Y'),
                             'fornecedores': [{'nome': n, 'valor': _num(v, 2)}
                                              for n, v in sorted(por_forn.items(), key=lambda x: -x[1])[:5]]}
    except Exception as e:
        logger.error(f"Painel: compras do mês: {e}", exc_info=True)
        painel['avisos'].append("Compras do mês: não deu para ler agora.")

    try:
        import alertas_estoque
        abaixo, acabando = alertas_estoque.situacao_do_estoque(hoje)
        def linha(a):
            return {'produto': a['produto'], 'unidade': a['unidade'], 'estoque': _num(a['estoque'], 1),
                    'minimo': _num(a['minimo']), 'dias': _num(a['dias'], 1) if a['dias'] is not None else None}
        painel['estoque'] = {'acabando': [linha(a) for a in acabando[:12]], 'qtd_acabando': len(acabando),
                             'abaixo': [linha(a) for a in abaixo[:12]], 'qtd_abaixo': len(abaixo)}
        painel['listas_esquecidas'] = [{'rotina': l['rotina'], 'funcionario': l['funcionario'], 'dias': l['dias']}
                                       for l in alertas_estoque.listas_esquecidas()]
    except Exception as e:
        logger.error(f"Painel: estoque: {e}", exc_info=True)
        painel['avisos'].append("Estoque: não deu para calcular agora.")

    try:
        aumentos = database.aumentos_de_preco(desde_data=hoje - timedelta(days=30))
        vistos, lista = set(), []
        for a in aumentos:
            if a['produto_id'] not in vistos:
                vistos.add(a['produto_id'])
                lista.append(database.texto_aumento_preco(a))
        painel['aumentos'] = lista[:10]
    except Exception as e:
        logger.error(f"Painel: aumentos de preço: {e}", exc_info=True)
        painel['avisos'].append("Preços: não deu para ler agora.")
    return painel


# ==============================================================================
# == [PREÇOS] histórico de preço de um produto (aba Gestão do app) =============
# ==============================================================================
def historico_precos(produto_id, meses=12, hoje=None):
    """
    Compras do produto nos últimos 'meses' (todos os fornecedores), com o custo por unidade
    do ESTOQUE, e um resumo: último preço, menor, maior, média e variação no período,
    e o último/menor preço de cada fornecedor. Bonificação (custo 0) aparece, mas fica
    fora das contas de preço.
    """
    hoje = _como_data(hoje) or date.today()
    meses = max(1, min(int(meses or 12), 36))
    produto_id = int(produto_id)
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT NomeProduto, UnidadeMedida, Categoria FROM ProdutosEstoque WHERE ProdutoID = ?", (produto_id,))
        p = cur.fetchone()
        if not p:
            raise ErroCompras("Produto não encontrado.")
        compras = _compras_recentes(cur, [produto_id], hoje, dias=meses * 31).get(produto_id, [])
    finally:
        conn.close()
    lista = [{'data': _iso(d), 'custo': _num(c, 4), 'qtd': _num(q), 'fornecedor': forn, 'descricao': desc, 'nf': nf,
              'bonificacao': c <= 0} for d, q, c, forn, desc, nf, _vid in compras]
    pagas = [(d, c, forn) for d, q, c, forn, desc, nf, _vid in compras if c > 0]
    resumo = None
    if pagas:
        ultimo, menor, maior = pagas[-1], min(pagas, key=lambda x: x[1]), max(pagas, key=lambda x: x[1])
        qtd_total = sum((q for d, q, c, *_ in compras if c > 0), Decimal('0'))
        valor_total = sum((q * c for d, q, c, *_ in compras if c > 0), Decimal('0'))
        resumo = {'ultimo': {'custo': _num(ultimo[1], 4), 'data': _iso(ultimo[0]), 'fornecedor': ultimo[2]},
                  'menor': {'custo': _num(menor[1], 4), 'data': _iso(menor[0]), 'fornecedor': menor[2]},
                  'maior': {'custo': _num(maior[1], 4), 'data': _iso(maior[0]), 'fornecedor': maior[2]},
                  'media': _num(valor_total / qtd_total, 4) if qtd_total else None,
                  'variacao_pct': _num((ultimo[1] / pagas[0][1] - 1) * 100, 1) if len(pagas) > 1 else None,
                  'compras': len(pagas), 'qtd_total': _num(qtd_total)}
    por_forn = {}
    for d, c, forn in pagas:
        f = por_forn.setdefault(forn, {'fornecedor': forn, 'ultimo': None, 'ultima_data': None, 'menor': None, 'compras': 0})
        f['compras'] += 1
        f['ultimo'], f['ultima_data'] = _num(c, 4), _iso(d)
        f['menor'] = _num(c, 4) if f['menor'] is None else min(f['menor'], _num(c, 4))
    return {'produto_id': produto_id, 'nome': p[0], 'unidade': (p[1] or 'UN').strip() or 'UN', 'categoria': p[2] or '',
            'meses': meses, 'compras': lista, 'resumo': resumo,
            'fornecedores': sorted(por_forn.values(), key=lambda f: (f['ultimo'] or 0))}

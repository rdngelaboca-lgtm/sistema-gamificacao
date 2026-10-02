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
        conn.commit()
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


def listar_rotinas(incluir_inativas=False, hoje=None):
    hoje = _como_data(hoje) or date.today()
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT R.RotinaID, R.Nome, R.DiasSemana, R.DiasCobertura, R.PrazoDias, R.Fornecedores, R.Ativa,
                   (SELECT COUNT(*) FROM CompraRotinaItens I WHERE I.RotinaID = R.RotinaID) AS QtdItens
            FROM CompraRotinas R
            ORDER BY R.Nome
        """)
        rotinas = []
        for r in cur.fetchall():
            if not r[6] and not incluir_inativas:
                continue
            dias = _ler_dias_semana(r[2])
            prox = _proxima_data(dias, hoje)
            rotinas.append({'id': r[0], 'nome': r[1], 'dias_semana': dias, 'dias_cobertura': int(r[3] or 7),
                            'prazo_dias': int(r[4] or 0), 'fornecedores': _ler_ids(r[5]), 'ativa': bool(r[6]),
                            'qtd_itens': int(r[7] or 0), 'hoje': prox == hoje, 'proxima': _iso(prox)})
        rotinas.sort(key=lambda x: (not x['hoje'], x['proxima'] or '9999', x['nome']))
        return rotinas
    finally:
        conn.close()


def obter_rotina(rotina_id):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT RotinaID, Nome, DiasSemana, DiasCobertura, PrazoDias, Fornecedores, Ativa
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
        itens = [{'produto_id': i[0], 'ordem': i[1], 'secao': i[2] or '',
                  'nome': i[3] or f'Produto {i[0]} (apagado do estoque)', 'unidade': (i[4] or 'UN').strip() or 'UN',
                  'categoria': i[5] or '', 'existe': i[3] is not None}
                 for i in cur.fetchall()]
        return {'id': r[0], 'nome': r[1], 'dias_semana': _ler_dias_semana(r[2]), 'dias_cobertura': int(r[3] or 7),
                'prazo_dias': int(r[4] or 0), 'fornecedores': _ler_ids(r[5]), 'ativa': bool(r[6]), 'itens': itens}
    finally:
        conn.close()


def salvar_rotina(dados):
    """
    Cria (sem 'id') ou altera (com 'id') uma rotina e a lista de itens, na ordem recebida.
    dados = {'id'?, 'nome', 'dias_semana': [1..7], 'dias_cobertura', 'prazo_dias',
             'fornecedores': [ids], 'itens': [{'produto_id', 'secao'}]}
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
    itens, vistos = [], set()
    for it in dados.get('itens') or []:
        try:
            pid = int(it.get('produto_id'))
        except (TypeError, ValueError, AttributeError):
            raise ErroCompras("Item da rotina sem produto válido.")
        if pid in vistos:
            continue
        vistos.add(pid)
        itens.append((pid, str(it.get('secao') or '').strip()[:80]))
    if not itens:
        raise ErroCompras("Coloque pelo menos um produto na rotina.")

    conn = _conectar()
    try:
        cur = conn.cursor()
        marcas = ','.join('?' * len(itens))
        cur.execute(f"SELECT ProdutoID FROM ProdutosEstoque WHERE ProdutoID IN ({marcas})", [p for p, _ in itens])
        existentes = {r[0] for r in cur.fetchall()}
        faltando = [p for p, _ in itens if p not in existentes]
        if faltando:
            raise ErroCompras(f"Produto(s) não encontrado(s) no estoque: {faltando}")
        rotina_id = dados.get('id')
        valores = (nome, ','.join(map(str, dias)), cobertura, prazo, ','.join(map(str, fornecedores)))
        if rotina_id:
            cur.execute("""UPDATE CompraRotinas SET Nome = ?, DiasSemana = ?, DiasCobertura = ?, PrazoDias = ?,
                           Fornecedores = ?, Ativa = 1 WHERE RotinaID = ?""", valores + (int(rotina_id),))
            if cur.rowcount == 0:
                raise ErroCompras("Rotina não encontrada (pode ter sido apagada).")
            rotina_id = int(rotina_id)
        else:
            cur.execute("""INSERT INTO CompraRotinas (Nome, DiasSemana, DiasCobertura, PrazoDias, Fornecedores, Ativa, CriadaEm)
                           OUTPUT INSERTED.RotinaID VALUES (?, ?, ?, ?, ?, 1, ?)""", valores + (datetime.now(),))
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
    marcas = ','.join('?' * len(produtos))
    cur.execute(f"""
        SELECT PF.ProdutoID, NF.DataEmissao, INI.ItemNotaID, INI.PrecoCustoUnitario, PF.FatorConversao,
               F.FornecedorID, F.NomeFantasia, F.CNPJ
        FROM ItensNotaFiscalEntrada INI
        JOIN NotasFiscaisEntrada NF ON INI.NotaID = NF.NotaID
        JOIN ProdutosFornecedor PF ON INI.ProdutoFornecedorID = PF.ProdutoFornecedorID
        LEFT JOIN Fornecedores F ON NF.FornecedorID = F.FornecedorID
        WHERE INI.Quantidade > 0 AND INI.PrecoCustoUnitario > 0 AND PF.ProdutoID IN ({marcas})
    """, list(produtos))
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
    cur.execute(f"SELECT ProdutoID, EstoqueMinimo FROM ProdutosEstoque WHERE ProdutoID IN ({','.join('?' * len(pids))})",
                list(pids))
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
    return {i['ProdutoID']: i for i in resultado['itens']}


def _alerta_consumo(info):
    if not info or not info.get('Contado'):
        return "Nunca contado antes: o consumo ainda não é conhecido"
    if info.get('ConsumoNegativo'):
        return "Conferir: a conta do consumo não fecha (contagem ou nota)"
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
                    WHERE ContagemID IN ({marcas_c}) AND ProdutoID IN ({marcas_p})""",
                list(de_hoje) + list(produtos))
    resultado = {}
    for cid, pid, q in cur.fetchall():
        r = resultado.setdefault(pid, {'qtd': Decimal('0'), 'contagens': []})
        r['qtd'] += _dec(q)
        if de_hoje[cid] not in r['contagens']:
            r['contagens'].append(de_hoje[cid] or f'Contagem {cid}')
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
        substituidas = {cid for _, cid, _ in _contagens_substituidas(cur, rotina_id, hoje)}
        hoje_outras = _contagens_de_hoje(cur, pids, hoje, substituidas)
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


def registrar_lista(codigo, rotina_id, usuario, dias, contagens, hoje=None):
    """
    Grava a contagem feita no celular e cria a lista de compras.
      codigo: identificador criado pelo celular (se o celular reenviar por causa de internet
              ruim, a mesma lista é devolvida, sem duplicar nada);
      usuario: {'id', 'nome', 'gestor'} de quem contou;
      contagens: [{'produto_id', 'qtd'}] (qtd None = item pulado).
    Gestor: a lista já sai APROVADA. Funcionário: fica AGUARDANDO o gestor.
    Se a mesma rotina já foi contada HOJE pelo app, a contagem anterior é trocada pela nova
    (senão as duas seriam somadas no estoque) e a lista anterior, se aberta, é cancelada.
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
    da_rotina = {i['produto_id'] for i in rotina['itens'] if i['existe']}
    contados = {}
    for c in contagens or []:
        try:
            pid = int(c.get('produto_id'))
        except (TypeError, ValueError, AttributeError):
            raise ErroCompras("Item contado sem produto válido.")
        if pid not in da_rotina:
            continue                         # produto saiu da rotina enquanto contava: ignora
        q = _qtd_valida(c.get('qtd'))
        if q is not None:
            contados[pid] = q

    conn = _conectar()
    try:
        cur = conn.cursor()
        if existente:                        # tentativa anterior parou no meio: refaz
            lista_id, contagem_id = existente['lista_id'], existente['contagem_id']
            cur.execute("DELETE FROM CompraListaItens WHERE ListaID = ?", (lista_id,))
        else:
            fechadas = database.listar_valores_estoque_fechados(levantar_erro=True)
            for cod_ant, cid_ant, st_ant in _contagens_substituidas(cur, rotina_id, hoje, codigo):
                if st_ant not in (ST_FINALIZADA, ST_CANCELADA):
                    cur.execute("UPDATE CompraListas SET Status = ? WHERE Codigo = ?", (ST_CANCELADA, cod_ant))
                if cid_ant in fechadas:
                    continue                 # valor do estoque já fechado: não mexe
                cur.execute("DELETE FROM ItensContagemEstoque WHERE ContagemID = ?", (cid_ant,))
                cur.execute("DELETE FROM ContagensEstoque WHERE ContagemID = ?", (cid_ant,))
                cur.execute("UPDATE CompraListas SET ContagemID = NULL WHERE Codigo = ?", (cod_ant,))
            contagem_id = None
            if contados:
                cur.execute("""INSERT INTO ContagensEstoque (DataContagem, FuncionarioID, NomeContagem)
                               OUTPUT INSERTED.ContagemID VALUES (?, ?, ?)""",
                            (hoje, usuario['id'], f"App compras: {rotina['nome']}"[:100]))
                contagem_id = int(cur.fetchone()[0])
                for pid, q in contados.items():
                    cur.execute("""INSERT INTO ItensContagemEstoque (ContagemID, ProdutoID, QuantidadeContada, NomeAvulso, EANAvulso)
                                   VALUES (?, ?, ?, NULL, NULL)""", (contagem_id, pid, q))
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

    itens = _calcular_itens(rotina, contados, dias, hoje, contagem_id)
    valor = sum((i['QtdPedido'] * i['CustoUnid'] for i in itens if i['CustoUnid'] and i['QtdPedido'] > 0), Decimal('0'))
    status = ST_APROVADA if usuario.get('gestor') else ST_AGUARDANDO
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
            WHERE L.Status <> ?
        """, (ST_PROCESSANDO,))
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

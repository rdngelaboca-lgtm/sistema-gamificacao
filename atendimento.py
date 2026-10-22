# ==============================================================================
# == atendimento.py - 💬 Central de Atendimento do WhatsApp ======================
# ==============================================================================
# A Central (página /atendimento, no computador da loja) atende os clientes pelo NÚMERO DOS CLIENTES
# (o mesmo das campanhas: 2ª instância da Z-API, nunca o número da loja):
#   - as mensagens chegam pelo webhook "Ao receber" que já existe (clientes.processar_webhook chama
#     do_webhook) e ficam guardadas aqui, uma conversa por WhatsApp;
#   - o atendente entra com o PRÓPRIO nome e PIN (não é gestor: não vê o resto da Gestão) e tudo o que ele
#     manda fica com o nome dele; quem abre uma conversa esperando assume o atendimento;
#   - botões prontos (🍧 Açaí, Complementos...) mandam a foto e os itens com os preços da tabela (os mesmos
#     do 99Food): no texto do botão, [Monte seu Açaí] vira a lista da categoria, só com o que tem hoje;
#   - a gestão vê as conversas, quem atendeu e o tempo de resposta; cliente esperando resposta há mais de
#     X minutos gera um aviso no grupo da gestão (tipo 💬 Atendimento em 📣 Avisos).
# O PIN usa a mesma conta (e o mesmo bloqueio depois de erros) do app de compras.
# ==============================================================================
import hmac
import logging
import math
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import database
import escala_regras as R

logger = logging.getLogger(__name__)

ST_ESPERANDO, ST_ATENDENDO, ST_ENCERRADA = 'esperando', 'atendendo', 'encerrada'
DE_CLIENTE, DE_LOJA, DE_SISTEMA = 'cliente', 'loja', 'sistema'
M_ENVIANDO, M_ENVIADA, M_ENTREGUE, M_LIDA, M_FALHOU = 'enviando', 'enviada', 'entregue', 'lida', 'falhou'
POR_AGENDA = '📅 Agenda'          # [AGENDA] confirmação, lembrete e pós-venda que a agenda mandou pelo número dos clientes
GRUPOS = [('produtos', 'Produtos (foto + preços)'), ('entrega', 'Entrega e pagamento'), ('andamento', 'Andamento do pedido')]
MAX_TEXTO = 1500                  # o que o atendente digita
MAX_TEXTO_BOTAO = 4000            # o botão já com a lista de itens
MAX_CONVERSAS = 300
MAX_MENSAGENS = 300
DIAS_ENCERRADAS = 7               # encerradas há mais tempo só aparecem na busca
ONLINE_SEG = 120                  # com a central aberta (ela pergunta a cada poucos segundos)
AVISO_MINUTOS_PADRAO = 5
MAX_PRECO = Decimal('10000')
SEGUNDO_PLANO = True              # os testes desligam para conferir na hora

# Respostas que o 📢 Clientes já respondeu sozinho: entram na conversa, mas ninguém precisa responder
AUTOMATICAS = {
    'saiu': "Pediu para SAIR da lista de ofertas (a resposta automática já foi).",
    'voltou': "Voltou para a lista de ofertas (a resposta automática já foi).",
    'ja_recebe': "Pediu para voltar, mas já recebe as ofertas.",
    'reserva': "Reserva pela mensagem de oferta (a resposta automática com a posição na fila já foi).",
}

PRODUTOS_INICIAIS = (
    [('Monte seu Açaí', 'Açaí Cremoso 300ml + 2 Adicionais', '26.09', False),
     ('Monte seu Açaí', 'Açaí Cremoso 500ml + 3 Adicionais', '33.50', False),
     ('Monte seu Açaí', 'Açaí Cremoso 700ml + 3 Adicionais', '38.99', False)]
    + [('Complementos', n, p, True) for n, p in (
        ('Amendoim Triturado', '0'), ('Banana', '0'), ('Bombom Ouro Branco', '0'), ('Bombom Sonho de Valsa', '0'),
        ('Castanha de Cajú', '0'), ('Cereja Original', '0'), ('Choco Ball', '0'), ('Confete', '0'),
        ('Creme de Amendoim', '0'), ('Creme de avelã', '0'), ('Creme de Leitinho', '0'), ('Creme de morango', '0'),
        ('Gotas de Chocolate', '0'), ('Granola', '0'), ('Kiwi', '0'), ('Leite condensado', '0'), ('Leite em pó', '0'),
        ('Morango', '0'), ('Nutella', '6.00'), ('Negresco', '0'), ('Ovomaltine', '0'), ('Paçoca', '0'), ('Uva', '0'),
        ('Whey Baunilha 30gr (23g Proteína)', '9.80'))])

BOTOES_INICIAIS = [
    ('Açaí', 'produtos', "Olá, {nome}! 🍧 Escolha o tamanho do seu açaí:\n[Monte seu Açaí]\n\n"
                         "No de 300 ml você escolhe 2 complementos; no de 500 ml e no de 700 ml, 3."),
    ('Complementos', 'produtos', "Complementos (no de 300 ml escolha 2; no de 500 ml e no de 700 ml, 3):\n[Complementos]"),
    ('Endereço', 'entrega', "Para a entrega, me mande o endereço completo (rua, número, bairro e um ponto de referência) "
                            "ou a sua localização pelo clipe 📎 › Localização.\nSe preferir, pode retirar no balcão."),
    ('Pagamento', 'entrega', "Como você prefere pagar: Pix, cartão (a maquininha vai junto) ou dinheiro? "
                             "Se for dinheiro, precisa de troco para quanto?"),
    ('Pedido confirmado', 'andamento', "Pedido confirmado, {nome}! ✅ Já foi para o preparo."),
    ('Saiu para entrega', 'andamento', "Seu pedido saiu para entrega! 🛵"),
    ('Agradecer', 'andamento', "Obrigado pelo pedido, {nome}! Bom açaí! 💜"),
]
# [CENTRAL v2] botão que fica DENTRO de outro, como um "+" (Complementos dentro do Açaí)
DENTRO_INICIAIS = [('Complementos', 'Açaí')]

_tabelas_ok = False
_trava = threading.Lock()
_vistos = {}                      # {chave do usuário: (monotonic, datetime)}: "online" sem gravar a cada pergunta


class ErroAtendimento(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def _conexao():
    conn = database.get_db_connection()
    if not conn:
        raise ErroAtendimento("Sem conexão com o banco de dados.", 503)
    return conn


def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AtendimentoConversas')
            CREATE TABLE AtendimentoConversas (
                ConversaID INT IDENTITY(1,1) PRIMARY KEY,
                Telefone VARCHAR(20) NOT NULL UNIQUE,
                Nome NVARCHAR(150) NULL,
                ClienteID INT NULL,
                Status VARCHAR(12) NOT NULL,
                AtendenteID INT NULL,
                AtendenteNome NVARCHAR(60) NULL,
                EsperandoDesde DATETIME NULL,
                AvisadoEm DATETIME NULL,
                NaoLidas INT NOT NULL DEFAULT 0,
                UltimaEm DATETIME NULL,
                UltimaPrevia NVARCHAR(200) NULL,
                CriadaEm DATETIME NOT NULL,
                EncerradaEm DATETIME NULL,
                Lid VARCHAR(30) NULL,
                LidConferidoEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AtendimentoMensagens')
            CREATE TABLE AtendimentoMensagens (
                MensagemID INT IDENTITY(1,1) PRIMARY KEY,
                ConversaID INT NOT NULL,
                De VARCHAR(8) NOT NULL,
                Tipo VARCHAR(12) NOT NULL,
                Texto NVARCHAR(4000) NULL,
                MidiaUrl NVARCHAR(600) NULL,
                Foto VARCHAR(60) NULL,
                PorID INT NULL,
                PorNome NVARCHAR(60) NULL,
                BotaoID INT NULL,
                ZapiID VARCHAR(80) NULL,
                Status VARCHAR(12) NULL,
                Erro NVARCHAR(200) NULL,
                CriadaEm DATETIME NOT NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AtendimentoAtendentes')
            CREATE TABLE AtendimentoAtendentes (
                FuncionarioID INT NOT NULL PRIMARY KEY,
                PinHash VARCHAR(64) NOT NULL,
                PinSalt VARCHAR(32) NOT NULL,
                Ativo BIT NOT NULL DEFAULT 1,
                VerTodas BIT NOT NULL DEFAULT 1,
                EditarBotoes BIT NOT NULL DEFAULT 0,
                VerGestao BIT NOT NULL DEFAULT 0,
                ErrosSeguidos INT NOT NULL DEFAULT 0,
                BloqueadoAte DATETIME NULL,
                VistoEm DATETIME NULL,
                CriadoEm DATETIME NULL,
                AtualizadoEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AtendimentoProdutos')
            CREATE TABLE AtendimentoProdutos (
                ProdutoID INT IDENTITY(1,1) PRIMARY KEY,
                Categoria NVARCHAR(60) NOT NULL,
                Nome NVARCHAR(120) NOT NULL,
                Preco DECIMAL(10, 2) NOT NULL,
                Adicional BIT NOT NULL DEFAULT 0,
                TemHoje BIT NOT NULL DEFAULT 1,
                Ordem INT NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AtendimentoBotoes')
            CREATE TABLE AtendimentoBotoes (
                BotaoID INT IDENTITY(1,1) PRIMARY KEY,
                Nome NVARCHAR(40) NOT NULL,
                Grupo VARCHAR(12) NOT NULL,
                Texto NVARCHAR(1500) NOT NULL,
                Foto VARCHAR(60) NULL,
                Ordem INT NOT NULL DEFAULT 0,
                Ativo BIT NOT NULL DEFAULT 1,
                PaiID INT NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ParametrosAtendimento')
            CREATE TABLE ParametrosAtendimento (
                Chave VARCHAR(40) NOT NULL PRIMARY KEY,
                Valor NVARCHAR(400) NULL
            )
        """)
        cur.execute("SELECT Valor FROM ParametrosAtendimento WHERE Chave = 'iniciado'")
        if not cur.fetchone():                    # uma vez só: a tabela do 99Food (açaís) e os botões
            for k, (cat, nome, preco, adic) in enumerate(PRODUTOS_INICIAIS):
                cur.execute("INSERT INTO AtendimentoProdutos (Categoria, Nome, Preco, Adicional, TemHoje, Ordem) VALUES (?, ?, ?, ?, 1, ?)",
                            cat, nome, Decimal(preco), 1 if adic else 0, k)
            for k, (nome, grupo, texto) in enumerate(BOTOES_INICIAIS):
                cur.execute("INSERT INTO AtendimentoBotoes (Nome, Grupo, Texto, Foto, Ordem, Ativo) VALUES (?, ?, ?, NULL, ?, 1)",
                            nome, grupo, texto, k)
            cur.execute("INSERT INTO ParametrosAtendimento (Chave, Valor) VALUES ('iniciado', ?)", _agora().isoformat())
        # [CENTRAL v2] botão dentro de outro (o "+ Complementos" no Açaí)
        cur.execute("IF COL_LENGTH('AtendimentoBotoes', 'PaiID') IS NULL ALTER TABLE AtendimentoBotoes ADD PaiID INT NULL")
        # [CELULAR] o código @lid da conversa: a mensagem mandada pelo celular às vezes vem com ele no lugar do número
        cur.execute("IF COL_LENGTH('AtendimentoConversas', 'Lid') IS NULL ALTER TABLE AtendimentoConversas ADD Lid VARCHAR(30) NULL")
        cur.execute("IF COL_LENGTH('AtendimentoConversas', 'LidConferidoEm') IS NULL "
                    "ALTER TABLE AtendimentoConversas ADD LidConferidoEm DATETIME NULL")
        cur.execute("SELECT Valor FROM ParametrosAtendimento WHERE Chave = 'botoes_v2'")
        if not cur.fetchone():                    # uma vez só: Complementos vai para dentro do Açaí; "Em preparo" sai
            for filho, pai in DENTRO_INICIAIS:
                cur.execute("SELECT BotaoID, Grupo FROM AtendimentoBotoes WHERE Nome = ? AND PaiID IS NULL", pai)
                r = cur.fetchone()
                if r:
                    cur.execute("UPDATE AtendimentoBotoes SET PaiID = ? WHERE Nome = ? AND Grupo = ? AND PaiID IS NULL AND BotaoID <> ?",
                                r[0], filho, r[1], r[0])
            cur.execute("DELETE FROM AtendimentoBotoes WHERE Nome = 'Em preparo' AND Grupo = 'andamento' AND Texto = ?",
                        "Seu pedido está sendo preparado 🍧")
            cur.execute("INSERT INTO ParametrosAtendimento (Chave, Valor) VALUES ('botoes_v2', ?)", _agora().isoformat())
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def _param(chave, padrao=None):
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Valor FROM ParametrosAtendimento WHERE Chave = ?", chave)
        r = cur.fetchone()
        return r[0] if r and r[0] is not None else padrao
    finally:
        conn.close()


def _params_todos():
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Chave, Valor FROM ParametrosAtendimento")
        return {c: v for c, v in cur.fetchall()}
    finally:
        conn.close()


def _salvar_params(valores):
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        for chave, valor in valores.items():
            cur.execute("DELETE FROM ParametrosAtendimento WHERE Chave = ?", chave)
            cur.execute("INSERT INTO ParametrosAtendimento (Chave, Valor) VALUES (?, ?)", chave, str(valor)[:400])
        conn.commit()
    finally:
        conn.close()


def _salvar_param(chave, valor):
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM ParametrosAtendimento WHERE Chave = ?", chave)
        cur.execute("INSERT INTO ParametrosAtendimento (Chave, Valor) VALUES (?, ?)", chave, str(valor)[:400])
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# Ajudantes
# ------------------------------------------------------------------------------
def _agora():
    return datetime.now().replace(microsecond=0)


def _dt(v):
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return None


def _quando(v, agora):
    v = _dt(v)
    if not v:
        return ''
    return f"{v:%H:%M}" if v.date() == agora.date() else f"{v:%d/%m %H:%M}"


def _minutos(desde, agora):
    desde = _dt(desde)
    return max(0, int((agora - desde).total_seconds() // 60)) if desde else None


def _primeiro(nome):
    p = str(nome or '').strip().split(' ')[0]
    return p[:1].upper() + p[1:].lower() if p else ''


def _sem_acento(t):
    return ''.join(c for c in unicodedata.normalize('NFD', str(t or '')) if unicodedata.category(c) != 'Mn')


def _chave_cat(t):
    return ' '.join(_sem_acento(t).lower().split())


def _texto_limpo(texto, tamanho):
    linhas = [re.sub(r'[ \t]+', ' ', l).rstrip() for l in str(texto or '').replace('\r\n', '\n').split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(linhas)).strip()[:tamanho]


def _previa(texto):
    return (str(texto or '').strip().split('\n')[0])[:120]


def _id(valor, nome="a conversa"):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ErroAtendimento(f"Escolha {nome} de novo. Atualize a página.")
    if n <= 0:
        raise ErroAtendimento(f"Escolha {nome} de novo. Atualize a página.")
    return n


def _rodar(funcao, *args):
    if SEGUNDO_PLANO:
        threading.Thread(target=funcao, args=args, daemon=True).start()
    else:
        funcao(*args)


# ------------------------------------------------------------------------------
# Quem usa a central: atendentes (PIN próprio) e gestores (o login da Gestão)
# ------------------------------------------------------------------------------
def _perfil_atendente(fid, nome, ver_todas, editar, ver_gestao):
    return {'tipo': 'atendente', 'id': int(fid), 'nome': _primeiro(nome) or f"Atendente {fid}", 'gestor': False,
            'ver_todas': bool(ver_todas), 'editar': bool(editar), 'ver_gestao': bool(ver_gestao)}


def _perfil_gestor(fid, nome):
    return {'tipo': 'gestor', 'id': int(fid), 'nome': _primeiro(nome) or f"Gestor {fid}", 'gestor': True,
            'ver_todas': True, 'editar': True, 'ver_gestao': True}


def usuarios_login():
    """A lista da tela de entrar: os atendentes e os gestores (com o PIN do app de compras)."""
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT A.FuncionarioID, F.NomeCompleto FROM AtendimentoAtendentes A
                       JOIN Funcionarios F ON F.FuncionarioID = A.FuncionarioID WHERE A.Ativo = 1""")
        atendentes = [{'chave': f"a{r[0]}", 'nome': _primeiro(r[1]) or f"Atendente {r[0]}", 'completo': r[1] or ''}
                      for r in cur.fetchall()]
        gestores = []
        try:
            cur.execute("""SELECT U.FuncionarioID, F.NomeCompleto FROM CompraUsuariosApp U
                           JOIN Funcionarios F ON F.FuncionarioID = U.FuncionarioID WHERE U.Ativo = 1 AND U.EhGestor = 1""")
            gestores = [{'chave': f"g{r[0]}", 'nome': f"{_primeiro(r[1]) or f'Gestor {r[0]}'} (gestão)", 'completo': r[1] or ''}
                        for r in cur.fetchall()]
        except Exception as e:                    # app de compras ainda sem a tabela: só os atendentes
            logger.warning(f"[ATENDIMENTO] Gestores para o login indisponíveis: {e}")
    finally:
        conn.close()
    atendentes.sort(key=lambda u: u['completo'].lower())
    gestores.sort(key=lambda u: u['completo'].lower())
    return [{'chave': u['chave'], 'nome': u['nome']} for u in atendentes + gestores]


def login(chave, pin, agora=None):
    """'a10' (atendente) ou 'g2' (gestor) + PIN -> o usuário com as permissões. ErroAtendimento se não der."""
    import compras_database as CD
    agora = agora or datetime.now()
    m = re.fullmatch(r'([ag])(\d{1,9})', str(chave or ''))
    if not m:
        raise ErroAtendimento("Escolha o seu nome na lista.")
    fid = int(m.group(2))
    if m.group(1) == 'g':
        try:
            u = CD.verificar_pin(fid, pin)
        except CD.ErroCompras as e:
            raise ErroAtendimento(str(e), 401)
        if not u['gestor']:
            raise ErroAtendimento("Esse nome não é de gestor. Escolha o seu nome de atendente.", 403)
        return _perfil_gestor(fid, u.get('nome_completo') or u['nome'])
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT A.PinHash, A.PinSalt, A.Ativo, A.ErrosSeguidos, A.BloqueadoAte, F.NomeCompleto, A.VerTodas,
                              A.EditarBotoes, A.VerGestao
                       FROM AtendimentoAtendentes A JOIN Funcionarios F ON F.FuncionarioID = A.FuncionarioID
                       WHERE A.FuncionarioID = ?""", fid)
        r = cur.fetchone()
        if not r or not r[2]:
            raise ErroAtendimento("Sem acesso à central. Peça para a gestão cadastrar o seu PIN.", 401)
        bloqueado = _dt(r[4])
        if bloqueado and bloqueado > agora:
            minutos = max(1, math.ceil((bloqueado - agora).total_seconds() / 60))
            raise ErroAtendimento(f"Muitas tentativas erradas. Tente de novo em {minutos} min.", 401)
        pin = str(pin or '').strip()
        certo = bool(re.fullmatch(r'\d+', pin)) and hmac.compare_digest(CD._hash_pin(pin, r[1]), r[0])
        if certo:
            cur.execute("UPDATE AtendimentoAtendentes SET ErrosSeguidos = 0, BloqueadoAte = NULL WHERE FuncionarioID = ?", fid)
            conn.commit()
            return _perfil_atendente(fid, r[5], r[6], r[7], r[8])
        erros = int(r[3] or 0) + 1
        if erros >= CD.PIN_MAX_ERROS:
            cur.execute("UPDATE AtendimentoAtendentes SET ErrosSeguidos = 0, BloqueadoAte = ? WHERE FuncionarioID = ?",
                        agora + timedelta(minutes=CD.PIN_BLOQUEIO_MINUTOS), fid)
            conn.commit()
            raise ErroAtendimento(f"PIN errado {CD.PIN_MAX_ERROS} vezes. Acesso bloqueado por {CD.PIN_BLOQUEIO_MINUTOS} minutos.", 401)
        cur.execute("UPDATE AtendimentoAtendentes SET ErrosSeguidos = ? WHERE FuncionarioID = ?", erros, fid)
        conn.commit()
        raise ErroAtendimento(f"PIN errado. Restam {CD.PIN_MAX_ERROS - erros} tentativa(s).", 401)
    finally:
        conn.close()


def usuario_da_sessao(atendente, gestor):
    """
    A cada pedido: o usuário com as permissões de AGORA (o gestor pode ter mudado), ou None se o acesso caiu.
    atendente = session['atendente'], gestor = session['compras_usuario'] (o login da Gestão também vale aqui).
    """
    if atendente:
        garantir_tabelas()
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT A.Ativo, A.VerTodas, A.EditarBotoes, A.VerGestao, F.NomeCompleto
                           FROM AtendimentoAtendentes A JOIN Funcionarios F ON F.FuncionarioID = A.FuncionarioID
                           WHERE A.FuncionarioID = ?""", int(atendente['id']))
            r = cur.fetchone()
        finally:
            conn.close()
        return _perfil_atendente(atendente['id'], r[4], r[1], r[2], r[3]) if r and r[0] else None
    if gestor:
        import compras_database as CD
        atual = CD.usuario_ainda_ativo(gestor['id'])
        if atual and atual['gestor']:
            return _perfil_gestor(gestor['id'], gestor.get('nome'))
    return None


def _visto(usuario, agora):
    """'Com a central aberta': grava no máximo uma vez por minuto."""
    chave = (usuario['tipo'], usuario['id'])
    antes = _vistos.get(chave)
    _vistos[chave] = (time.monotonic(), agora)
    if usuario['tipo'] != 'atendente' or (antes and time.monotonic() - antes[0] < 60):
        return
    try:
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE AtendimentoAtendentes SET VistoEm = ? WHERE FuncionarioID = ?", agora, usuario['id'])
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[ATENDIMENTO] 'Online' de {usuario['nome']} não gravado: {e}")


def _online(tipo, fid, visto_em, agora):
    v = _vistos.get((tipo, fid))
    if v and (agora - v[1]).total_seconds() <= ONLINE_SEG:
        return True
    v = _dt(visto_em)
    return bool(v and (agora - v).total_seconds() <= ONLINE_SEG)


# ------------------------------------------------------------------------------
# Tabela de preços e botões
# ------------------------------------------------------------------------------
def _produtos(cur, so_hoje=False):
    cur.execute("SELECT ProdutoID, Categoria, Nome, Preco, Adicional, TemHoje, Ordem FROM AtendimentoProdutos")
    linhas = sorted(cur.fetchall(), key=lambda r: (int(r[6] or 0), r[0]))
    return [{'id': r[0], 'categoria': r[1], 'nome': r[2], 'preco': Decimal(str(r[3] or 0)), 'adicional': bool(r[4]),
             'tem_hoje': bool(r[5])} for r in linhas if r[5] or not so_hoje]


def _linha_item(p):
    if p['adicional']:
        return f"• {p['nome']}" + (f" (+{R.fmt_reais(p['preco'])})" if p['preco'] > 0 else '')
    return f"• {p['nome']} — {R.fmt_reais(p['preco'])}"


def renderizar(texto, nome_cliente, produtos):
    """{nome} vira o primeiro nome do cliente; [Categoria] vira a lista dos itens dela que tem hoje, com o preço."""
    pn = _primeiro(nome_cliente)
    t = re.sub(r'\{\s*nome\s*\}', pn, str(texto or ''), flags=re.I)
    if not pn:                                          # "Olá, !" -> "Olá!"
        t = re.sub(r'[ \t]+([,!?.])', r'\1', t)
        t = re.sub(r',\s*([!?.])', r'\1', t)
    por_cat = {}
    for p in produtos:
        por_cat.setdefault(_chave_cat(p['categoria']), []).append(p)

    def trocar(m):
        chave = _chave_cat(m.group(1))
        if chave not in por_cat:
            return m.group(0)                           # não é uma categoria: fica como está
        itens = [p for p in por_cat[chave] if p['tem_hoje']]
        return "\n".join(_linha_item(p) for p in itens) if itens else "(nenhum item disponível hoje)"
    return re.sub(r'\[([^\[\]\n]{1,60})\]', trocar, t).strip()


def _botao_json(r):
    return {'id': r[0], 'nome': r[1], 'grupo': r[2], 'texto': r[3], 'foto': r[4] or '', 'ordem': int(r[5] or 0),
            'ativo': bool(r[6]), 'foto_url': f"/api/atendimento/foto/{r[4]}" if r[4] else '', 'pai_id': r[7]}


def _botoes(cur, so_ativos=False):
    cur.execute("SELECT BotaoID, Nome, Grupo, Texto, Foto, Ordem, Ativo, PaiID FROM AtendimentoBotoes")
    linhas = sorted(cur.fetchall(), key=lambda r: ([g for g, _ in GRUPOS].index(r[2]) if r[2] in dict(GRUPOS) else 9,
                                                   int(r[5] or 0), r[0]))
    return [_botao_json(r) for r in linhas if r[6] or not so_ativos]


def _produto_json(p):
    return {'id': p['id'], 'categoria': p['categoria'], 'nome': p['nome'], 'preco': f"{p['preco']:.2f}".replace('.', ','),
            'preco_txt': R.fmt_reais(p['preco']), 'adicional': p['adicional'], 'tem_hoje': p['tem_hoje']}


def _categorias(produtos):
    vistas = []
    for p in produtos:
        if p['categoria'] not in vistas:
            vistas.append(p['categoria'])
    return vistas


def cardapio(usuario):
    """Para a tela 🍧 Botões e preços: a tabela, as categorias (os [marcadores]) e os botões."""
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        produtos, botoes = _produtos(cur), _botoes(cur)
    finally:
        conn.close()
    return {'produtos': [_produto_json(p) for p in produtos], 'categorias': _categorias(produtos), 'botoes': botoes,
            'grupos': [{'chave': g, 'nome': n} for g, n in GRUPOS], 'pode_editar': bool(usuario['editar'])}


def _exigir(usuario, permissao, mensagem):
    if not usuario.get(permissao):
        raise ErroAtendimento(mensagem, 403)


def salvar_produtos(dados, usuario):
    """A tabela inteira de uma vez (a ordem da lista vale). Item sem id = novo; item que sumiu da lista = apagado."""
    _exigir(usuario, 'editar', "Você não pode mudar os preços. Peça para a gestão.")
    itens = dados.get('produtos')
    if not isinstance(itens, list) or len(itens) > 500:
        raise ErroAtendimento("Tabela inválida. Atualize a página.")
    lidos = []
    for it in itens:
        if not isinstance(it, dict):
            raise ErroAtendimento("Tabela inválida. Atualize a página.")
        nome = ' '.join(str(it.get('nome') or '').split())[:120]
        cat = ' '.join(str(it.get('categoria') or '').split())[:60]
        if not nome:
            raise ErroAtendimento("Tem item sem nome na tabela.")
        if not cat:
            raise ErroAtendimento(f"{nome}: escolha a categoria.")
        if '[' in cat or ']' in cat:
            raise ErroAtendimento(f"{cat}: a categoria não pode ter [ ].")
        try:
            preco = R.para_decimal_br(it.get('preco'), f"o preço de {nome}")
        except ValueError as e:
            raise ErroAtendimento(str(e))
        if preco > MAX_PRECO:
            raise ErroAtendimento(f"{nome}: preço alto demais ({R.fmt_reais(preco)}). Confira o número.")
        pid = it.get('id')
        pid = _id(pid, "o item") if pid not in (None, '') else None
        lidos.append((pid, cat, nome, preco.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), bool(it.get('adicional')),
                      bool(it.get('tem_hoje', True))))
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        existentes = {p['id'] for p in _produtos(cur)}
        if any(pid and pid not in existentes for pid, *_ in lidos):
            raise ErroAtendimento("A tabela mudou em outro computador. Atualize a página.", 409)
        manter = {pid for pid, *_ in lidos if pid}
        for pid in existentes - manter:
            cur.execute("DELETE FROM AtendimentoProdutos WHERE ProdutoID = ?", pid)
        for ordem, (pid, cat, nome, preco, adic, hoje) in enumerate(lidos):
            if pid:
                cur.execute("UPDATE AtendimentoProdutos SET Categoria = ?, Nome = ?, Preco = ?, Adicional = ?, TemHoje = ?, Ordem = ? "
                            "WHERE ProdutoID = ?", cat, nome, preco, 1 if adic else 0, 1 if hoje else 0, ordem, pid)
            else:
                cur.execute("INSERT INTO AtendimentoProdutos (Categoria, Nome, Preco, Adicional, TemHoje, Ordem) VALUES (?, ?, ?, ?, ?, ?)",
                            cat, nome, preco, 1 if adic else 0, 1 if hoje else 0, ordem)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[ATENDIMENTO] {usuario['nome']}: tabela de preços salva ({len(lidos)} itens).")
    r = cardapio(usuario)
    r['mensagem'] = f"Tabela salva: {len(lidos)} itens. Os botões já mandam os preços novos."
    return r


def _ler_foto(nome):
    """Nome de uma foto já enviada (📢 Clientes guarda as fotos) ou None."""
    import clientes
    nome = str(nome or '').strip()
    if not nome:
        return None
    try:
        clientes.caminho_foto(nome)
    except clientes.ErroClientes as e:
        raise ErroAtendimento(str(e), e.status)
    return nome


def salvar_botao(botao_id, dados, usuario):
    _exigir(usuario, 'editar', "Você não pode mudar os botões. Peça para a gestão.")
    nome = ' '.join(str(dados.get('nome') or '').split())[:30]
    grupo = dados.get('grupo') if dados.get('grupo') in dict(GRUPOS) else None
    texto = _texto_limpo(dados.get('texto'), 1500)
    if not nome:
        raise ErroAtendimento("Escreva o nome do botão.")
    if not grupo:
        raise ErroAtendimento("Escolha o grupo do botão.")
    if not texto:
        raise ErroAtendimento("Escreva o texto da mensagem.")
    foto = _ler_foto(dados.get('foto'))
    ativo = bool(dados.get('ativo', True))
    pai_id = dados.get('pai_id')
    pai_id = _id(pai_id, "o botão de fora") if pai_id not in (None, '', 0, '0') else None
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        if pai_id:                                  # [CENTRAL v2] fica dentro de outro botão (um nível só)
            todos = _botoes(cur)
            pai = next((x for x in todos if x['id'] == pai_id), None)
            if not pai or pai_id == botao_id:
                raise ErroAtendimento("O botão de fora não existe mais. Atualize a página.", 409)
            if pai['pai_id']:
                raise ErroAtendimento(f"{pai['nome']} já fica dentro de outro botão. Escolha um botão principal.")
            if botao_id and any(x['pai_id'] == botao_id for x in todos):
                raise ErroAtendimento(f"{nome} tem botões dentro dele: ele não pode ficar dentro de outro.")
            grupo = pai['grupo']                    # aparece junto com o de fora
        if botao_id:
            cur.execute("UPDATE AtendimentoBotoes SET Nome = ?, Grupo = ?, Texto = ?, Foto = ?, Ativo = ?, PaiID = ? WHERE BotaoID = ?",
                        nome, grupo, texto, foto, 1 if ativo else 0, pai_id, botao_id)
            if cur.rowcount != 1:
                raise ErroAtendimento("Botão não encontrado. Atualize a página.", 404)
            cur.execute("UPDATE AtendimentoBotoes SET Grupo = ? WHERE PaiID = ?", grupo, botao_id)   # os de dentro vão junto
        else:
            cur.execute("SELECT MAX(Ordem) FROM AtendimentoBotoes")
            r = cur.fetchone()
            cur.execute("INSERT INTO AtendimentoBotoes (Nome, Grupo, Texto, Foto, Ordem, Ativo, PaiID) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        nome, grupo, texto, foto, int((r[0] if r else 0) or 0) + 1, 1 if ativo else 0, pai_id)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[ATENDIMENTO] {usuario['nome']}: botão {nome} {'alterado' if botao_id else 'criado'}.")
    r = cardapio(usuario)
    r['mensagem'] = f"Botão {nome} salvo."
    return r


def excluir_botao(botao_id, usuario):
    _exigir(usuario, 'editar', "Você não pode mudar os botões. Peça para a gestão.")
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM AtendimentoBotoes WHERE BotaoID = ?", botao_id)
        apagou = cur.rowcount == 1
        if apagou:
            cur.execute("UPDATE AtendimentoBotoes SET PaiID = NULL WHERE PaiID = ?", botao_id)
        conn.commit()
    finally:
        conn.close()
    if not apagou:
        raise ErroAtendimento("Botão não encontrado. Atualize a página.", 404)
    r = cardapio(usuario)
    r['mensagem'] = "Botão apagado."
    return r


def mover_botao(botao_id, dados, usuario):
    """Sobe ou desce o botão dentro do grupo dele."""
    _exigir(usuario, 'editar', "Você não pode mudar os botões. Peça para a gestão.")
    passo = -1 if dados.get('direcao') == 'cima' else 1
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        todos = _botoes(cur)
        b = next((x for x in todos if x['id'] == botao_id), None)
        if not b:
            raise ErroAtendimento("Botão não encontrado. Atualize a página.", 404)
        grupo = [x for x in todos if x['grupo'] == b['grupo'] and x['pai_id'] == b['pai_id']]   # mesmo lugar
        i = grupo.index(b)
        j = i + passo
        if 0 <= j < len(grupo):
            grupo[i], grupo[j] = grupo[j], grupo[i]
            for ordem, x in enumerate(grupo):
                cur.execute("UPDATE AtendimentoBotoes SET Ordem = ? WHERE BotaoID = ?", ordem, x['id'])
            conn.commit()
    finally:
        conn.close()
    return cardapio(usuario)


def previa(dados):
    """Como o cliente recebe o texto do botão (com 'Maria' no lugar do {nome})."""
    garantir_tabelas()
    conn = _conexao()
    try:
        produtos = _produtos(conn.cursor())
    finally:
        conn.close()
    return {'texto': renderizar(_texto_limpo(dados.get('texto'), 1500), dados.get('nome') or 'Maria', produtos)}


# ------------------------------------------------------------------------------
# Atendentes (só a gestão cadastra)
# ------------------------------------------------------------------------------
def atendentes(usuario, agora=None):
    _exigir(usuario, 'gestor', "Só a gestão cadastra atendentes.")
    agora = agora or _agora()
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT A.FuncionarioID, F.NomeCompleto, A.Ativo, A.VerTodas, A.EditarBotoes, A.VerGestao, A.BloqueadoAte,
                              A.VistoEm
                       FROM AtendimentoAtendentes A JOIN Funcionarios F ON F.FuncionarioID = A.FuncionarioID""")
        lista = [{'id': r[0], 'nome': r[1] or f"Funcionário {r[0]}", 'ativo': bool(r[2]), 'ver_todas': bool(r[3]),
                  'editar': bool(r[4]), 'ver_gestao': bool(r[5]),
                  'bloqueado': bool(_dt(r[6]) and _dt(r[6]) > agora), 'online': _online('atendente', r[0], r[7], agora)}
                 for r in cur.fetchall()]
        cur.execute("SELECT FuncionarioID, NomeCompleto FROM Funcionarios")
        ja = {a['id'] for a in lista}
        funcionarios = [{'id': r[0], 'nome': r[1] or f"Funcionário {r[0]}"} for r in cur.fetchall() if r[0] not in ja]
    finally:
        conn.close()
    lista.sort(key=lambda a: a['nome'].lower())
    funcionarios.sort(key=lambda f: f['nome'].lower())
    return {'atendentes': lista, 'funcionarios': funcionarios}


def salvar_atendente(funcionario_id, dados, usuario, novo=False):
    """Cria (novo=True, com PIN) ou muda as permissões; PIN preenchido = troca o PIN (e desbloqueia)."""
    import compras_database as CD
    _exigir(usuario, 'gestor', "Só a gestão cadastra atendentes.")
    pin = str(dados.get('pin') or '').strip()
    if pin or novo:
        try:
            pin = CD.validar_formato_pin(pin)
        except CD.ErroCompras as e:
            raise ErroAtendimento(str(e))
    agora = _agora()
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT NomeCompleto FROM Funcionarios WHERE FuncionarioID = ?", funcionario_id)
        f = cur.fetchone()
        if not f:
            raise ErroAtendimento("Funcionário não encontrado no cadastro. Atualize a página.", 404)
        cur.execute("SELECT 1 FROM AtendimentoAtendentes WHERE FuncionarioID = ?", funcionario_id)
        existe = bool(cur.fetchone())
        if novo and existe:
            raise ErroAtendimento(f"{f[0]} já é atendente.", 409)
        if not novo and not existe:
            raise ErroAtendimento("Atendente não encontrado. Atualize a página.", 404)
        perms = [1 if dados.get(k, padrao) else 0 for k, padrao in
                 (('ativo', True), ('ver_todas', True), ('editar', False), ('ver_gestao', False))]
        if novo:
            salt = secrets.token_hex(16)
            cur.execute("""INSERT INTO AtendimentoAtendentes (FuncionarioID, PinHash, PinSalt, Ativo, VerTodas, EditarBotoes, VerGestao,
                                                              ErrosSeguidos, BloqueadoAte, CriadoEm, AtualizadoEm)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)""",
                        funcionario_id, CD._hash_pin(pin, salt), salt, *perms, agora, agora)
        else:
            cur.execute("UPDATE AtendimentoAtendentes SET Ativo = ?, VerTodas = ?, EditarBotoes = ?, VerGestao = ?, AtualizadoEm = ? "
                        "WHERE FuncionarioID = ?", *perms, agora, funcionario_id)
            if pin:
                salt = secrets.token_hex(16)
                cur.execute("UPDATE AtendimentoAtendentes SET PinHash = ?, PinSalt = ?, ErrosSeguidos = 0, BloqueadoAte = NULL "
                            "WHERE FuncionarioID = ?", CD._hash_pin(pin, salt), salt, funcionario_id)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[ATENDIMENTO] {usuario['nome']}: atendente {f[0]} {'cadastrado' if novo else 'alterado'}"
                f"{' (PIN novo)' if pin and not novo else ''}.")
    r = atendentes(usuario)
    r['mensagem'] = (f"{_primeiro(f[0])} já pode entrar na central com o PIN." if novo
                     else f"{_primeiro(f[0])}: salvo" + (" (PIN novo)." if pin else "."))
    return r


def excluir_atendente(funcionario_id, usuario):
    _exigir(usuario, 'gestor', "Só a gestão cadastra atendentes.")
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM AtendimentoAtendentes WHERE FuncionarioID = ?", funcionario_id)
        apagou = cur.rowcount == 1
        conn.commit()
    finally:
        conn.close()
    if not apagou:
        raise ErroAtendimento("Atendente não encontrado. Atualize a página.", 404)
    r = atendentes(usuario)
    r['mensagem'] = "Atendente removido: não entra mais na central (as mensagens dele continuam no histórico)."
    return r


# ------------------------------------------------------------------------------
# Mensagens que chegam (webhook do número dos clientes)
# ------------------------------------------------------------------------------
def _midia(p, tipo):
    """O link da foto/áudio/vídeo/arquivo que a Z-API guarda (só https), ou o mapa da localização."""
    if tipo == 'local':
        loc = p.get('location') if isinstance(p.get('location'), dict) else {}
        try:
            return f"https://www.google.com/maps?q={float(loc.get('latitude')):.6f},{float(loc.get('longitude')):.6f}"
        except (TypeError, ValueError):
            return None
    chaves = {'foto': ('image', ('imageUrl', 'url')), 'video': ('video', ('videoUrl', 'url')),
              'audio': ('audio', ('audioUrl', 'url')), 'documento': ('document', ('documentUrl', 'url')),
              'figurinha': ('sticker', ('stickerUrl', 'url'))}
    if tipo not in chaves:
        return None
    obj = p.get(chaves[tipo][0]) if isinstance(p.get(chaves[tipo][0]), dict) else {}
    for k in chaves[tipo][1]:
        u = str(obj.get(k) or '').strip()
        if re.fullmatch(r'https://[^\s"<>\'`]+', u) and len(u) <= 600:
            return u
    return None


def _texto_recebido(p, texto, tipo):
    if tipo == 'local':
        loc = p.get('location') if isinstance(p.get('location'), dict) else {}
        end = ' '.join(str(loc.get('address') or loc.get('name') or '').split())
        return f"📍 localização{': ' + end if end else ''}"
    if tipo == 'documento':
        doc = p.get('document') if isinstance(p.get('document'), dict) else {}
        nome = ' '.join(str(doc.get('fileName') or '').split())
        if nome and nome not in texto:
            return f"{texto} ({nome})"
    return texto


def do_webhook(p, acao=None):
    """Chamado pelo clientes.processar_webhook (o segredo já foi conferido). Nunca atrapalha o 📢 Clientes."""
    try:
        if _do_webhook(p if isinstance(p, dict) else {}, acao) == PROCURAR_LID:
            _rodar(_procurar_lid, dict(p))
    except Exception as e:
        logger.error(f"[ATENDIMENTO] Mensagem do webhook não entrou na central: {e}", exc_info=True)
        # [DEPURAÇÃO CENTRAL] antes ficava só no log: a gestão via a central vazia sem saber por quê
        try:
            _salvar_params({'erro_em': _agora().isoformat(), 'erro_txt': str(e)[:300]})
        except Exception as e2:
            logger.error(f"[ATENDIMENTO] Nem o erro foi gravado: {e2}")
        if isinstance(p, dict) and p.get('fromMe'):
            _anotar_celular(f"não entrou: erro ao gravar ({str(e)[:120]})", p)


def _telefone(p):
    """O WhatsApp do cliente; [DEPURAÇÃO CENTRAL] número oculto pelo WhatsApp ('...@lid') também vale (antes a mensagem sumia)."""
    import clientes
    fone = str(p.get('phone') or '').strip()
    if '@' not in fone:                     # [CELULAR] '5544...@lid' é código, não número (antes virava um telefone falso)
        try:
            return clientes.normalizar_telefone(fone)
        except clientes.ErroClientes:
            pass
    for v in (fone, p.get('chatLid')):
        v = str(v or '').strip()
        if _LID.fullmatch(v):
            return v
    return None


_LID = re.compile(r'\d{6,20}@lid')


def _lid_do_chat(p, tel):
    """[CELULAR] O código @lid da conversa (o WhatsApp usa no lugar do número). Na mensagem que a LOJA mandou,
    só o chatLid é do cliente (o senderLid é o da própria loja)."""
    for v in ((tel, p.get('chatLid')) if p.get('fromMe') else (tel, p.get('chatLid'), p.get('senderLid'))):
        v = str(v or '').strip()
        if _LID.fullmatch(v):
            return v
    return None


def _achar_conversa(cur, tel, p):
    """[CELULAR] A conversa da mensagem que a loja mandou pelo celular: o número igual; senão o mesmo celular com
    ou sem o 9 (o WhatsApp manda dos dois jeitos); senão pelo código @lid. (ConversaID, Status, EsperandoDesde, Nome, Telefone)"""
    cols = "ConversaID, Status, EsperandoDesde, Nome, Telefone"
    cur.execute(f"SELECT {cols} FROM AtendimentoConversas WHERE Telefone = ?", tel)
    c = cur.fetchone()
    if not c and '@lid' not in tel and len(tel) >= 12:
        cur.execute(f"SELECT {cols} FROM AtendimentoConversas WHERE Telefone LIKE ?", tel[:4] + '%' + tel[-8:])
        achadas = [x for x in cur.fetchall() if '@lid' not in x[4] and x[4][:4] == tel[:4] and x[4][-8:] == tel[-8:]]
        c = achadas[0] if len(achadas) == 1 else None
    lid = _lid_do_chat(p, tel)
    if not c and lid:
        cur.execute(f"SELECT TOP 1 {cols} FROM AtendimentoConversas WHERE Lid = ? ORDER BY UltimaEm DESC", lid)
        c = cur.fetchone()
    return c


def _do_sistema(cur, tel, mid, texto, agora):
    """[CELULAR] A cópia marcada 'fromApi' é de algo que o sistema mandou? (campanha ou resposta automática do 📢 Clientes)
    O que não for reconhecido é tratado como mandado pelo celular: antes TUDO com 'fromApi' era jogado fora."""
    import clientes
    if texto in (_texto_limpo(clientes.TEXTO_SAIU, MAX_TEXTO_BOTAO), _texto_limpo(clientes.TEXTO_VOLTOU, MAX_TEXTO_BOTAO)):
        return True
    cur.execute("SELECT 1 FROM AtendimentoMensagens WHERE PorNome = ? AND Texto = ? AND CriadaEm >= ?",   # [AGENDA]
                POR_AGENDA, texto, agora - timedelta(minutes=10))
    if cur.fetchone():
        return True
    try:
        cur.execute("SELECT 1 FROM CampanhaEnvios WHERE MensagemID = ? OR (Telefone = ? AND EnviadoEm >= ?)",
                    mid or '-', tel, agora - timedelta(minutes=10))
        return bool(cur.fetchone())
    except Exception as e:
        logger.warning(f"[ATENDIMENTO] Campanhas indisponíveis para conferir a cópia: {e}")
        return False


def _fim_tel(tel):
    t = str(tel or '')
    return f"código @lid …{t.split('@')[0][-4:]} (sem o número)" if '@lid' in t else f"…{t[-4:]}"


PROCURAR_LID, LID_DE_NOVO = 'procurar_lid', 'lid_de_novo'


def _guardar_lid(cur, cid, lid):
    cur.execute("UPDATE AtendimentoConversas SET Lid = ? WHERE ConversaID = ? AND (Lid IS NULL OR Lid <> ?)", lid, cid, lid)


def _lid_por_telefone(tel):
    """[CELULAR] O código @lid deste WhatsApp, perguntando à Z-API (o 'phone-exists' devolve o 'lid'). None se não deu."""
    import clientes
    ok, r = clientes._zapi('GET', f"phone-exists/{tel}", timeout=8)
    lid = str((r.get('lid') if ok and isinstance(r, dict) else '') or '').strip()
    if re.fullmatch(r'\d{6,20}', lid):
        lid += '@lid'
    return lid if _LID.fullmatch(lid) else None


def completar_lids(limite=10, agora=None):
    """[CELULAR] Conversas (últimos 30 dias) que ainda não sabem o próprio @lid: pergunta à Z-API, no máximo uma vez
    por dia cada uma. Devolve quantas aprenderam."""
    agora = agora or _agora()
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT TOP {int(limite)} ConversaID, Telefone FROM AtendimentoConversas WHERE Lid IS NULL "
                    "AND Telefone NOT LIKE ? AND UltimaEm >= ? AND (LidConferidoEm IS NULL OR LidConferidoEm < ?) "
                    "ORDER BY UltimaEm DESC", '%@lid', agora - timedelta(days=30), agora - timedelta(days=1))
        lista = cur.fetchall()
    finally:
        conn.close()
    aprendeu = 0
    for cid, tel in lista:
        lid = _lid_por_telefone(tel)
        conn = _conexao()
        try:
            conn.cursor().execute("UPDATE AtendimentoConversas SET Lid = COALESCE(?, Lid), LidConferidoEm = ? WHERE ConversaID = ?",
                                  lid, agora, cid)
            conn.commit()
        finally:
            conn.close()
        aprendeu += bool(lid)
    return aprendeu


def _procurar_lid(p):
    """[CELULAR] A resposta do celular veio só com o @lid e nenhuma conversa conhece esse código: pergunta à Z-API o
    @lid das conversas que ainda não têm e tenta de novo (uma vez). Em segundo plano: o webhook responde na hora."""
    try:
        n = completar_lids()
        logger.info(f"[ATENDIMENTO] @lid de {n} conversa(s) aprendido(s) para achar a resposta do celular.")
    except Exception as e:
        logger.error(f"[ATENDIMENTO] Não deu para perguntar o @lid das conversas: {e}")
    do_webhook(p, LID_DE_NOVO)


def _conferir_lid(cid, tel):
    """[CELULAR] Conversa nova sem o @lid na mensagem do cliente: pergunta à Z-API (para casar a resposta do celular)."""
    try:
        lid = _lid_por_telefone(tel)
        conn = _conexao()
        try:
            conn.cursor().execute("UPDATE AtendimentoConversas SET Lid = COALESCE(?, Lid), LidConferidoEm = ? WHERE ConversaID = ?",
                                  lid, _agora(), cid)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[ATENDIMENTO] @lid da conversa {cid} não conferido: {e}")


def _anotar_celular(resultado, p):
    """[CELULAR] O que aconteceu com a última mensagem que a loja mandou pelo celular (a gestão vê no 📡; vai no log)."""
    p = p if isinstance(p, dict) else {}
    logger.info(f"[ATENDIMENTO] Mandada pelo celular: {resultado} (fromApi={bool(p.get('fromApi'))}, "
                f"phone={'@lid' if '@lid' in str(p.get('phone') or '') else 'número'}, chatLid={'sim' if p.get('chatLid') else 'não'})")
    try:
        _salvar_params({'celular_em': _agora().isoformat(), 'celular_res': str(resultado)[:200]})
    except Exception as e:
        logger.error(f"[ATENDIMENTO] Diagnóstico do celular não gravado: {e}")


def _tel_txt(tel):
    import clientes
    return "número oculto pelo WhatsApp" if '@lid' in str(tel or '') else clientes.fmt_telefone(tel)


def anotar_webhook(p, motivo, agora=None):
    """[DEPURAÇÃO CENTRAL] O que chegou da Z-API por último: a central mostra para a gestão (diagnóstico)."""
    agora = agora or _agora()
    p = p if isinstance(p, dict) else {}
    valores = {'webhook_em': agora.isoformat(), 'webhook_motivo': str(motivo or '')[:40]}
    if motivo == 'outra_instancia':
        valores.update(outra_instancia_em=agora.isoformat(), outra_instancia_fim=str(p.get('instanceId') or '')[-4:])
    elif (p.get('type') in (None, 'ReceivedCallback') and not p.get('fromMe') and not p.get('isGroup')
          and not (p.get('ids') and p.get('status'))):
        valores['webhook_msg_em'] = agora.isoformat()
    _salvar_params(valores)


def diagnostico(agora=None):
    """Para a gestão: chegou mensagem? de qual instância? deu erro ao gravar?"""
    agora = agora or _agora()
    p = _params_todos()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(CriadaEm) FROM AtendimentoMensagens WHERE De = ?", DE_CLIENTE)
        r = cur.fetchone()
    finally:
        conn.close()
    # [CENTRAL v2] vale também a mensagem de cliente que já está na central (chegou antes desta versão, ou o aviso
    # da Z-API veio diferente): antes a tela dizia "nenhuma mensagem chegou" com as conversas ali na lista
    datas = [x for x in (_dt(p.get('webhook_msg_em')), _dt(p.get('central_ok_em')), _dt(r[0] if r else None)) if x]
    msg_em, ult_em = (max(datas) if datas else None), _dt(p.get('webhook_em'))
    erro_em, ok_em, outra_em = _dt(p.get('erro_em')), _dt(p.get('central_ok_em')), _dt(p.get('outra_instancia_em'))
    d = {'nunca': not msg_em, 'so_status': bool(ult_em and not msg_em), 'msg': _quando(msg_em, agora) if msg_em else ''}
    if erro_em and (not ok_em or erro_em > ok_em) and agora - erro_em < timedelta(days=1):
        d['erro'], d['erro_em'] = p.get('erro_txt') or '?', _quando(erro_em, agora)
    if outra_em and (not msg_em or outra_em >= msg_em) and agora - outra_em < timedelta(days=1):
        d['outra_instancia'] = p.get('outra_instancia_fim') or '?'
    cel_em = _dt(p.get('celular_em'))                # [CELULAR] a última mandada pelo celular: entrou? por que não?
    d['celular'] = {'quando': _quando(cel_em, agora), 'res': p.get('celular_res') or ''} if cel_em else None
    return d


def _do_webhook(p, acao):
    if p.get('type') == 'MessageStatusCallback' or (p.get('ids') and p.get('status') and 'text' not in p):
        return _status_entrega(p)
    if p.get('isGroup') or p.get('isNewsletter') or p.get('broadcast') or p.get('isStatusReply'):
        return
    if p.get('type') and p.get('type') != 'ReceivedCallback':
        return
    if acao == 'repetida':
        return
    import clientes
    texto, tipo = clientes._conteudo(p)
    if not tipo:
        return
    tel = _telefone(p)
    if not tel:
        if p.get('fromMe'):
            _anotar_celular("não entrou: a Z-API não mandou o número do cliente", p)
        return
    texto = _texto_limpo(_texto_recebido(p, texto, tipo), MAX_TEXTO_BOTAO)
    midia = _midia(p, tipo)
    mid = str(p.get('messageId') or '')[:80] or None
    agora = _agora()
    garantir_tabelas()
    with _trava:
        conn = _conexao()
        try:
            cur = conn.cursor()
            if mid:
                cur.execute("SELECT ConversaID FROM AtendimentoMensagens WHERE ZapiID = ?", mid)
                ja = cur.fetchone()
                if ja:                              # já está (a mesma mensagem duas vezes, ou foi a central que mandou)
                    lid = _lid_do_chat(p, tel) if p.get('fromMe') else None
                    if lid:                         # [CELULAR] a cópia do que a central mandou ensina o @lid da conversa
                        _guardar_lid(cur, ja[0], lid)
                        conn.commit()
                    return
            if p.get('fromMe'):
                # Mandada pelo celular: entra numa conversa que já existe. Nunca cria conversa nova (senão cada
                # mensagem das campanhas viraria uma conversa). [CELULAR] Antes, tudo o que vinha marcado 'fromApi'
                # era jogado fora e a conversa só era achada pelo número exato: as respostas do celular sumiam.
                # Agora só fica de fora o que é do próprio sistema (a cópia da central, campanha, resposta automática).
                c = _achar_conversa(cur, tel, p)
                if not c:
                    if p.get('fromApi') and _do_sistema(cur, tel, mid, texto, agora):
                        return
                    if _lid_do_chat(p, tel) and acao != LID_DE_NOVO:
                        return PROCURAR_LID         # só o @lid: pergunta à Z-API de quem é e tenta de novo (fora da trava)
                    _anotar_celular(f"não entrou: nenhuma conversa na central com {_fim_tel(tel)}"
                                    + (" (a Z-API não disse de qual conversa é esse código)" if acao == LID_DE_NOVO else ''), p)
                    return
                img = p.get('image') if isinstance(p.get('image'), dict) else {}
                ecos = [texto, _texto_limpo(img.get('caption'), MAX_TEXTO_BOTAO)] if img else [texto]
                cur.execute(f"SELECT 1 FROM AtendimentoMensagens WHERE ConversaID = ? AND De = ? AND (PorID IS NOT NULL OR PorNome = ?) "
                            f"AND CriadaEm >= ? AND Texto IN ({','.join('?' * len(ecos))})",
                            c[0], DE_LOJA, POR_AGENDA, agora - timedelta(minutes=2), *ecos)
                if cur.fetchone():
                    return                          # a cópia do que a central (ou a 📅 agenda) acabou de mandar
                sistema = bool(p.get('fromApi')) and _do_sistema(cur, tel, mid, texto, agora)
                cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, MidiaUrl, PorNome, ZapiID, Status, CriadaEm) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", c[0], DE_LOJA, tipo, texto, midia,
                            'Automática' if sistema else 'Pelo celular', mid, M_ENVIADA, agora)
                if sistema:                         # campanha / resposta automática: não é alguém respondendo
                    cur.execute("UPDATE AtendimentoConversas SET UltimaEm = ?, UltimaPrevia = ? WHERE ConversaID = ?",
                                agora, _previa(texto), c[0])
                else:                               # alguém respondeu pelo celular: o cliente não está mais esperando
                    cur.execute("UPDATE AtendimentoConversas SET UltimaEm = ?, UltimaPrevia = ?, EsperandoDesde = NULL, "
                                "AvisadoEm = NULL WHERE ConversaID = ?", agora, _previa(texto), c[0])
                    cur.execute("UPDATE AtendimentoConversas SET Status = ?, AtendenteNome = ? WHERE ConversaID = ? AND Status = ?",
                                ST_ATENDENDO, 'Celular', c[0], ST_ESPERANDO)
                conn.commit()
                if not sistema:
                    _anotar_celular(f"entrou na conversa de {c[3] or _tel_txt(c[4])}", p)
                return
            cur.execute("SELECT ConversaID, Status, EsperandoDesde, Nome, AtendenteID FROM AtendimentoConversas WHERE Telefone = ?", tel)
            c = cur.fetchone()
            cli = clientes._achar_cliente(cur, tel) if '@lid' not in tel else None
            perfil = clientes._limpo(p.get('senderName') or p.get('chatName'), 150) or None
            nome = (cli[1] if cli else None) or (c[3] if c else None) or perfil    # o cadastro vale; senão, o 1º nome visto
            auto = acao in AUTOMATICAS
            if not c:
                cur.execute("INSERT INTO AtendimentoConversas (Telefone, Nome, ClienteID, Status, EsperandoDesde, NaoLidas, UltimaEm, "
                            "UltimaPrevia, CriadaEm) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?); SELECT SCOPE_IDENTITY();",
                            tel, nome, cli[0] if cli else None, ST_ENCERRADA if auto else ST_ESPERANDO,
                            None if auto else agora, agora, _previa(texto), agora)
                cur.nextset()
                cid = int(cur.fetchone()[0])
            else:
                cid, st, desde = c[0], c[1], c[2]
                # voltou a falar depois de encerrada (ou depois da resposta pelo celular, que ninguém da central
                # assumiu): espera alguém de novo
                if not auto and (st == ST_ENCERRADA or (st == ST_ATENDENDO and c[4] is None)):
                    cur.execute("UPDATE AtendimentoConversas SET Status = ?, AtendenteID = NULL, AtendenteNome = NULL, EsperandoDesde = ?, "
                                "AvisadoEm = NULL, EncerradaEm = NULL, NaoLidas = NaoLidas + 1, UltimaEm = ?, UltimaPrevia = ?, "
                                "Nome = ?, ClienteID = ? WHERE ConversaID = ?",
                                ST_ESPERANDO, agora, agora, _previa(texto), nome, cli[0] if cli else None, cid)
                else:
                    cur.execute("UPDATE AtendimentoConversas SET EsperandoDesde = ?, NaoLidas = NaoLidas + 1, UltimaEm = ?, "
                                "UltimaPrevia = ?, Nome = ?, ClienteID = ? WHERE ConversaID = ?",
                                desde if (auto or desde) else agora, agora, _previa(texto), nome, cli[0] if cli else None, cid)
            cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, MidiaUrl, ZapiID, CriadaEm) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", cid, DE_CLIENTE, tipo, texto, midia, mid, agora)
            lid = _lid_do_chat(p, tel)               # [CELULAR] para achar a conversa quando a resposta vier com o @lid
            conferir_lid = False
            if lid:
                _guardar_lid(cur, cid, lid)
            elif '@lid' not in tel:                 # a mensagem não trouxe o @lid: pergunta à Z-API (depois de gravar)
                cur.execute("SELECT 1 FROM AtendimentoConversas WHERE ConversaID = ? AND Lid IS NULL "
                            "AND (LidConferidoEm IS NULL OR LidConferidoEm < ?)", cid, agora - timedelta(days=1))
                conferir_lid = bool(cur.fetchone())
            if auto:
                cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, CriadaEm) VALUES (?, ?, 'texto', ?, ?)",
                            cid, DE_SISTEMA, AUTOMATICAS[acao], agora)
            conn.commit()
            cur.execute("DELETE FROM ParametrosAtendimento WHERE Chave = 'central_ok_em'")
            cur.execute("INSERT INTO ParametrosAtendimento (Chave, Valor) VALUES ('central_ok_em', ?)", agora.isoformat())
            conn.commit()
            if conferir_lid:
                _rodar(_conferir_lid, cid, tel)
        finally:
            conn.close()


def _status_entrega(p):
    """✔️✔️: a Z-API avisa quando a mensagem foi entregue e lida."""
    st = str(p.get('status') or '').upper()
    novo = {'RECEIVED': M_ENTREGUE, 'READ': M_LIDA, 'PLAYED': M_LIDA}.get(st)
    ids = p.get('ids') if isinstance(p.get('ids'), list) else ([p.get('messageId')] if p.get('messageId') else [])
    ids = [str(i)[:80] for i in ids if i][:50]
    if not novo or not ids:
        return
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        antes = (M_ENVIADA,) if novo == M_ENTREGUE else (M_ENVIADA, M_ENTREGUE)
        for i in ids:
            cur.execute(f"UPDATE AtendimentoMensagens SET Status = ? WHERE ZapiID = ? AND Status IN ({','.join('?' * len(antes))})",
                        novo, i, *antes)
        lid = _lid_do_chat({'fromMe': True, 'chatLid': p.get('chatLid')}, str(p.get('phone') or '').strip())
        if lid:                                     # [CELULAR] o aviso de entregue/lida também ensina o @lid da conversa
            cur.execute(f"SELECT ConversaID FROM AtendimentoMensagens WHERE De = ? AND ZapiID IN ({','.join('?' * len(ids))})",
                        DE_LOJA, *ids)
            r = cur.fetchone()
            if r:
                _guardar_lid(cur, r[0], lid)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# A lista de conversas e uma conversa
# ------------------------------------------------------------------------------
_COLS_CONV = ("ConversaID, Telefone, Nome, ClienteID, Status, AtendenteID, AtendenteNome, EsperandoDesde, NaoLidas, UltimaEm, "
              "UltimaPrevia, CriadaEm, EncerradaEm")


def _conv(r):
    return {'id': r[0], 'telefone': r[1], 'nome': r[2], 'cliente_id': r[3], 'status': r[4], 'atendente_id': r[5],
            'atendente': r[6] or '', 'esperando_desde': _dt(r[7]), 'nao_lidas': int(r[8] or 0), 'ultima': _dt(r[9]),
            'previa': r[10] or '', 'criada': _dt(r[11]), 'encerrada': _dt(r[12])}


def _conversa(cur, cid):
    cur.execute(f"SELECT {_COLS_CONV} FROM AtendimentoConversas WHERE ConversaID = ?", cid)
    r = cur.fetchone()
    if not r:
        raise ErroAtendimento("Conversa não encontrada. Atualize a página.", 404)
    return _conv(r)


def _pode_ver(c, usuario):
    return usuario['ver_todas'] or c['status'] == ST_ESPERANDO or c['atendente_id'] == usuario['id']


def _conv_json(c, usuario, agora):
    import clientes
    return {'id': c['id'], 'nome': c['nome'] or _tel_txt(c['telefone']), 'telefone': _tel_txt(c['telefone']),
            'status': c['status'], 'atendente': c['atendente'], 'minha': c['atendente_id'] == usuario['id'],
            'aguardando_min': _minutos(c['esperando_desde'], agora) if c['status'] != ST_ENCERRADA else None,
            'nao_lidas': c['nao_lidas'], 'hora': _quando(c['ultima'], agora), 'previa': c['previa'],
            'oculto': '@lid' in str(c['telefone'] or ''),
            'cadastrado': bool(c['cliente_id'])}


def painel(usuario, busca='', agora=None):
    """A coluna da esquerda: esperando (o mais antigo primeiro), em atendimento e encerradas (mais novas primeiro)."""
    agora = agora or _agora()
    garantir_tabelas()
    _visto(usuario, agora)
    busca = ' '.join(str(busca or '').split())[:60]
    conn = _conexao()
    try:
        cur = conn.cursor()
        if busca:
            digitos = re.sub(r'\D', '', busca)
            if len(digitos) >= 4:
                cur.execute(f"SELECT {_COLS_CONV} FROM AtendimentoConversas WHERE Telefone LIKE ?", f"%{digitos}%")
            else:
                cur.execute(f"SELECT {_COLS_CONV} FROM AtendimentoConversas")
        else:
            cur.execute(f"SELECT {_COLS_CONV} FROM AtendimentoConversas WHERE Status <> ? OR UltimaEm >= ?",
                        ST_ENCERRADA, agora - timedelta(days=DIAS_ENCERRADAS))
        lista = [_conv(r) for r in cur.fetchall()]
        cur.execute("""SELECT A.FuncionarioID, F.NomeCompleto, A.VistoEm FROM AtendimentoAtendentes A
                       JOIN Funcionarios F ON F.FuncionarioID = A.FuncionarioID WHERE A.Ativo = 1""")
        equipe = [{'chave': f"a{r[0]}", 'nome': _primeiro(r[1]), 'online': _online('atendente', r[0], r[2], agora)}
                  for r in cur.fetchall()]
    finally:
        conn.close()
    if busca and not re.sub(r'\D', '', busca)[3:]:
        alvo = _sem_acento(busca).lower()
        lista = [c for c in lista if alvo in _sem_acento(c['nome'] or '').lower()]
    lista = [c for c in lista if _pode_ver(c, usuario)]
    ordem = {ST_ESPERANDO: 0, ST_ATENDENDO: 1, ST_ENCERRADA: 2}
    lista.sort(key=lambda c: (ordem.get(c['status'], 3),
                              (c['esperando_desde'] or agora).timestamp() if c['status'] == ST_ESPERANDO
                              else -(c['ultima'] or c['criada'] or agora).timestamp()))
    return {'conversas': [_conv_json(c, usuario, agora) for c in lista[:MAX_CONVERSAS]],
            'esperando': sum(1 for c in lista if c['status'] == ST_ESPERANDO),
            'aguardando': sum(1 for c in lista if c['status'] != ST_ENCERRADA and c['esperando_desde']),
            'minhas': sum(1 for c in lista if c['status'] == ST_ATENDENDO and c['atendente_id'] == usuario['id']),
            'equipe': [e for e in equipe if e['chave'] != f"a{usuario['id']}" or usuario['tipo'] != 'atendente'],
            'eu': usuario, 'hora': f"{agora:%H:%M}", 'diagnostico': diagnostico(agora) if usuario['gestor'] else None}


def _msg_json(r, agora):
    mid, de, tipo, texto, midia, foto, por, status, erro, criada = r
    return {'id': mid, 'de': de, 'tipo': tipo, 'texto': texto or '', 'midia': midia or '',
            'foto': f"/api/atendimento/foto/{foto}" if foto else '', 'por': por or '', 'status': status or '',
            'erro': erro or '', 'hora': _quando(criada, agora)}


def _cliente_info(cur, cid):
    if not cid:
        return {'cadastrado': False}
    try:
        cur.execute("SELECT Nome, AniversarioDia, AniversarioMes, Aceite, SaiuEm FROM Clientes WHERE ClienteID = ?", cid)
        r = cur.fetchone()
        if not r:
            return {'cadastrado': False}
        cur.execute("SELECT Etiqueta FROM ClienteEtiquetas WHERE ClienteID = ?", cid)
        etiquetas = sorted(x[0] for x in cur.fetchall())
    except Exception as e:
        logger.warning(f"[ATENDIMENTO] Cadastro do cliente {cid} indisponível: {e}")
        return {'cadastrado': False}
    return {'cadastrado': True, 'nome': r[0] or '', 'aniversario': f"{int(r[1]):02d}/{int(r[2]):02d}" if r[1] and r[2] else '',
            'recebe_ofertas': bool(r[3]) and not r[4], 'etiquetas': etiquetas}


def conversa(cid, usuario, abrir=False, agora=None):
    """
    Uma conversa com as últimas mensagens. abrir=True (o atendente clicou nela): se estava esperando, ele assume;
    as não lidas zeram para quem está atendendo. A página pergunta de novo a cada poucos segundos (abrir=False).
    """
    agora = agora or _agora()
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        c = _conversa(cur, cid)
        if not _pode_ver(c, usuario):
            raise ErroAtendimento(f"Esta conversa está com {c['atendente'] or 'outro atendente'}.", 403)
        if abrir and c['status'] == ST_ESPERANDO and usuario['tipo'] == 'atendente':
            cur.execute("UPDATE AtendimentoConversas SET Status = ?, AtendenteID = ?, AtendenteNome = ? WHERE ConversaID = ? AND Status = ?",
                        ST_ATENDENDO, usuario['id'], usuario['nome'], cid, ST_ESPERANDO)
            if cur.rowcount == 1:
                cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, PorID, PorNome, CriadaEm) "
                            "VALUES (?, ?, 'texto', ?, ?, ?, ?)", cid, DE_SISTEMA, f"{usuario['nome']} assumiu a conversa.",
                            usuario['id'], usuario['nome'], agora)
                c.update(status=ST_ATENDENDO, atendente_id=usuario['id'], atendente=usuario['nome'])
        if c['nao_lidas'] and c['atendente_id'] == usuario['id']:
            cur.execute("UPDATE AtendimentoConversas SET NaoLidas = 0 WHERE ConversaID = ?", cid)
            c['nao_lidas'] = 0
        cur.execute(f"SELECT TOP {MAX_MENSAGENS} MensagemID, De, Tipo, Texto, MidiaUrl, Foto, PorNome, Status, Erro, CriadaEm "
                    "FROM AtendimentoMensagens WHERE ConversaID = ? ORDER BY MensagemID DESC", cid)
        mensagens = [_msg_json(r, agora) for r in reversed(cur.fetchall())]
        import clientes
        cli = clientes._achar_cliente(cur, c['telefone']) if '@lid' not in c['telefone'] else None
        if cli and cli[0] != c['cliente_id']:          # cadastrou depois (QR do balcão): a conversa passa a saber
            cur.execute("UPDATE AtendimentoConversas SET ClienteID = ?, Nome = ? WHERE ConversaID = ?", cli[0], cli[1], cid)
            c.update(cliente_id=cli[0], nome=cli[1])
        info = _cliente_info(cur, c['cliente_id'])
        conn.commit()
    finally:
        conn.close()
    return {'conversa': _conv_json(c, usuario, agora), 'mensagens': mensagens, 'cliente': info,
            'de_outro': c['status'] == ST_ATENDENDO and c['atendente_id'] != usuario['id']}


# ------------------------------------------------------------------------------
# Mandar (texto, foto ou botão) e ações da conversa
# ------------------------------------------------------------------------------
def _mandar(msg_id, telefone, texto, foto):
    import clientes
    try:
        ok, r = clientes.enviar_para(telefone, texto, foto)
    except clientes.ErroClientes as e:
        ok, r = False, str(e)
    except Exception as e:
        ok, r = False, f"erro no envio ({e})"
    try:
        conn = _conexao()
        try:
            cur = conn.cursor()
            if ok:
                cur.execute("UPDATE AtendimentoMensagens SET Status = ?, ZapiID = ?, Erro = NULL WHERE MensagemID = ?",
                            M_ENVIADA, (str(r or '')[:80] or None), msg_id)
            else:
                cur.execute("UPDATE AtendimentoMensagens SET Status = ?, Erro = ? WHERE MensagemID = ?",
                            M_FALHOU, clientes._sem_segredo(r)[:200], msg_id)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[ATENDIMENTO] Situação da mensagem {msg_id} não gravada: {e}", exc_info=True)
    if not ok:
        logger.error(f"[ATENDIMENTO] Mensagem {msg_id} não foi: {clientes._sem_segredo(r)}")


# ------------------------------------------------------------------------------
# [AGENDA] Confirmação, lembrete e pós-venda da agenda (mandados pelo agenda_whatsapp.py)
# ------------------------------------------------------------------------------
def agenda_antes(telefone, texto, nome=None, agora=None):
    """
    Antes de mandar: a mensagem entra na conversa do cliente como "📅 Agenda" (sem conversa, cria uma já encerrada:
    ninguém fica esperando). Assim a cópia que a Z-API devolve não vira "respondida pelo celular" e, quando o cliente
    responder, quem atender já vê o que foi mandado. Devolve o MensagemID.
    """
    import clientes
    agora = agora or _agora()
    texto = _texto_limpo(texto, MAX_TEXTO_BOTAO)
    garantir_tabelas()
    with _trava:
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("SELECT ConversaID FROM AtendimentoConversas WHERE Telefone = ?", telefone)
            c = cur.fetchone()
            if c:
                cid = int(c[0])
                cur.execute("UPDATE AtendimentoConversas SET UltimaEm = ?, UltimaPrevia = ? WHERE ConversaID = ?",
                            agora, _previa(texto), cid)
            else:
                cli = clientes._achar_cliente(cur, telefone)
                nome = (cli[1] if cli else None) or clientes._limpo(nome, 150) or None
                cur.execute("INSERT INTO AtendimentoConversas (Telefone, Nome, ClienteID, Status, NaoLidas, UltimaEm, UltimaPrevia, "
                            "CriadaEm, EncerradaEm) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?); SELECT SCOPE_IDENTITY();",
                            telefone, nome, cli[0] if cli else None, ST_ENCERRADA, agora, _previa(texto), agora, agora)
                cur.nextset()
                cid = int(cur.fetchone()[0])
            cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, PorNome, Status, CriadaEm) "
                        "VALUES (?, ?, 'texto', ?, ?, ?, ?); SELECT SCOPE_IDENTITY();",
                        cid, DE_LOJA, texto, POR_AGENDA, M_ENVIANDO, agora)
            cur.nextset()
            msg_id = int(cur.fetchone()[0])
            conn.commit()
            return msg_id
        finally:
            conn.close()


def agenda_depois(msg_id, ok, zapi_id=None):
    """Depois de mandar: guarda o número da mensagem (para o ✔️✔️ entregue/lida). Se não foi, tira a mensagem (e a
    conversa criada só para ela): o robô da agenda tenta de novo mais tarde."""
    with _trava:
        conn = _conexao()
        try:
            cur = conn.cursor()
            if ok:
                cur.execute("UPDATE AtendimentoMensagens SET Status = ?, ZapiID = ? WHERE MensagemID = ?",
                            M_ENVIADA, str(zapi_id or '')[:80] or None, int(msg_id))
            else:
                cur.execute("SELECT ConversaID FROM AtendimentoMensagens WHERE MensagemID = ?", int(msg_id))
                c = cur.fetchone()
                cur.execute("DELETE FROM AtendimentoMensagens WHERE MensagemID = ?", int(msg_id))
                if c:
                    cur.execute("DELETE FROM AtendimentoConversas WHERE ConversaID = ? AND NOT EXISTS "
                                "(SELECT 1 FROM AtendimentoMensagens WHERE ConversaID = ?)", c[0], c[0])
            conn.commit()
        finally:
            conn.close()


def _exigir_numero():
    import clientes
    if not clientes.configurado():
        raise ErroAtendimento("O número dos clientes (Z-API) não está configurado: Gestão › 📢 Clientes › ⚙️ Ajustes.", 409)


def enviar(cid, dados, usuario, agora=None):
    """Manda pelo número dos clientes. Quem manda assume a conversa (e para de contar o tempo de espera)."""
    agora = agora or _agora()
    _exigir_numero()
    garantir_tabelas()
    botao_id = dados.get('botao_id')
    botao_id = _id(botao_id, "o botão") if botao_id not in (None, '', 0) else None
    conn = _conexao()
    try:
        cur = conn.cursor()
        c = _conversa(cur, cid)
        if not _pode_ver(c, usuario):
            raise ErroAtendimento(f"Esta conversa está com {c['atendente'] or 'outro atendente'}.", 403)
        if botao_id:
            b = next((x for x in _botoes(cur) if x['id'] == botao_id), None)
            if not b or not b['ativo']:
                raise ErroAtendimento("Esse botão não existe mais. Atualize a página.", 409)
            texto = renderizar(b['texto'], c['nome'], _produtos(cur))[:MAX_TEXTO_BOTAO]
            foto = b['foto'] or None
        else:
            texto = _texto_limpo(dados.get('texto'), MAX_TEXTO + 1)
            if len(texto) > MAX_TEXTO:
                raise ErroAtendimento(f"Mensagem grande demais (máximo {MAX_TEXTO} letras).")
            foto = _ler_foto(dados.get('foto'))
            if not texto and not foto:
                raise ErroAtendimento("Escreva a mensagem.")
        cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, Foto, PorID, PorNome, BotaoID, Status, CriadaEm) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?); SELECT SCOPE_IDENTITY();",
                    cid, DE_LOJA, 'foto' if foto else 'texto', texto, foto, usuario['id'], usuario['nome'], botao_id,
                    M_ENVIANDO, agora)
        cur.nextset()
        msg_id = int(cur.fetchone()[0])
        assumiu = c['status'] == ST_ATENDENDO and c['atendente_id'] not in (None, usuario['id'])
        cur.execute("UPDATE AtendimentoConversas SET Status = ?, AtendenteID = ?, AtendenteNome = ?, EsperandoDesde = NULL, "
                    "AvisadoEm = NULL, EncerradaEm = NULL, NaoLidas = 0, UltimaEm = ?, UltimaPrevia = ? WHERE ConversaID = ?",
                    ST_ATENDENDO, usuario['id'], usuario['nome'], agora, _previa(texto or '📷 foto'), cid)
        if assumiu:
            cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, PorID, PorNome, CriadaEm) "
                        "VALUES (?, ?, 'texto', ?, ?, ?, ?)", cid, DE_SISTEMA,
                        f"{usuario['nome']} assumiu a conversa (estava com {c['atendente']}).", usuario['id'], usuario['nome'], agora)
        conn.commit()
    finally:
        conn.close()
    _rodar(_mandar, msg_id, c['telefone'], texto, foto)
    return {'ok': True, 'id': msg_id}


def reenviar(cid, msg_id, usuario):
    """⚠️ não foi: manda de novo a mesma mensagem."""
    _exigir_numero()
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        c = _conversa(cur, cid)
        if not _pode_ver(c, usuario):
            raise ErroAtendimento(f"Esta conversa está com {c['atendente'] or 'outro atendente'}.", 403)
        cur.execute("SELECT Texto, Foto, Status FROM AtendimentoMensagens WHERE MensagemID = ? AND ConversaID = ? AND De = ?",
                    msg_id, cid, DE_LOJA)
        r = cur.fetchone()
        if not r or r[2] != M_FALHOU:
            raise ErroAtendimento("Só dá para mandar de novo a mensagem que não foi.", 409)
        cur.execute("UPDATE AtendimentoMensagens SET Status = ?, Erro = NULL WHERE MensagemID = ?", M_ENVIANDO, msg_id)
        conn.commit()
    finally:
        conn.close()
    _rodar(_mandar, msg_id, c['telefone'], r[0] or '', r[1] or None)
    return {'ok': True}


def acao(cid, nome_acao, dados, usuario, agora=None):
    """assumir · encerrar · transferir (para outro atendente ou gestor)."""
    agora = agora or _agora()
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        c = _conversa(cur, cid)
        if not _pode_ver(c, usuario):
            raise ErroAtendimento(f"Esta conversa está com {c['atendente'] or 'outro atendente'}.", 403)
        if nome_acao == 'assumir':
            if c['status'] == ST_ATENDENDO and c['atendente_id'] == usuario['id']:
                return {'ok': True, 'mensagem': "A conversa já está com você."}
            nota = f"{usuario['nome']} assumiu a conversa" + (f" (estava com {c['atendente']})." if c['atendente'] and
                                                               c['status'] == ST_ATENDENDO else ".")
            cur.execute("UPDATE AtendimentoConversas SET Status = ?, AtendenteID = ?, AtendenteNome = ?, EncerradaEm = NULL, NaoLidas = 0 "
                        "WHERE ConversaID = ?", ST_ATENDENDO, usuario['id'], usuario['nome'], cid)
            mensagem = "Agora a conversa é sua."
        elif nome_acao == 'encerrar':
            if c['status'] == ST_ENCERRADA:
                return {'ok': True, 'mensagem': "A conversa já estava encerrada."}
            nota = f"Conversa encerrada por {usuario['nome']}."
            cur.execute("UPDATE AtendimentoConversas SET Status = ?, EsperandoDesde = NULL, AvisadoEm = NULL, NaoLidas = 0, "
                        "EncerradaEm = ?, AtendenteNome = CASE WHEN AtendenteID IS NULL THEN ? ELSE AtendenteNome END, "
                        "AtendenteID = COALESCE(AtendenteID, ?) WHERE ConversaID = ?",          # [CELULAR] 'Celular' vira quem encerrou
                        ST_ENCERRADA, agora, usuario['nome'], usuario['id'], cid)
            mensagem = "Conversa encerrada. Se o cliente escrever de novo, ela volta para 'esperando'."
        elif nome_acao == 'transferir':
            m = re.fullmatch(r'([ag])(\d{1,9})', str(dados.get('para') or ''))
            alvo = next((u for u in usuarios_login() if m and u['chave'] == m.group(0)), None)
            if not alvo:
                raise ErroAtendimento("Escolha para quem passar a conversa.")
            para_id, para_nome = int(m.group(2)), alvo['nome'].replace(' (gestão)', '')
            if para_id == usuario['id']:
                raise ErroAtendimento("Escolha outra pessoa.")
            nota = f"{usuario['nome']} passou a conversa para {para_nome}."
            cur.execute("UPDATE AtendimentoConversas SET Status = ?, AtendenteID = ?, AtendenteNome = ?, EncerradaEm = NULL "
                        "WHERE ConversaID = ?", ST_ATENDENDO, para_id, para_nome, cid)
            mensagem = f"Conversa passada para {para_nome}."
        else:
            raise ErroAtendimento("Ação desconhecida.", 404)
        cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, PorID, PorNome, CriadaEm) "
                    "VALUES (?, ?, 'texto', ?, ?, ?, ?)", cid, DE_SISTEMA, nota, usuario['id'], usuario['nome'], agora)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[ATENDIMENTO] {nota} (conversa {cid})")
    return {'ok': True, 'mensagem': mensagem}


# ------------------------------------------------------------------------------
# [CENTRAL v2] 💾 Salvar o contato: no cadastro do 📢 Clientes e na agenda do celular dos clientes
# ------------------------------------------------------------------------------
def _agenda_celular(telefone, nome):
    """Põe o contato na agenda do celular do número dos clientes (com os dois salvos, o cliente vê o status da loja).
    (True, '') ou (False, motivo). Se a Z-API não aceitar, o cadastro vale do mesmo jeito."""
    import clientes
    primeiro, _, resto = nome.partition(' ')
    ok, r = clientes._zapi('POST', 'contacts/add', [{'firstName': primeiro, 'lastName': resto, 'phone': telefone}], timeout=15)
    if ok and isinstance(r, dict) and r.get('success') is False:
        ok, r = False, '; '.join(str(e) for e in (r.get('errors') or [])[:3]) or "a Z-API não confirmou"
    return ok, ('' if ok else clientes._sem_segredo(str(r or ''))[:150])


def salvar_contato(cid, dados, usuario, agora=None):
    """O cliente da conversa entra no cadastro de clientes (nome e WhatsApp já preenchidos) e, se marcado, na agenda
    do celular. Receber as ofertas só com a autorização dele (a caixinha)."""
    agora = agora or _agora()
    import clientes
    garantir_tabelas()
    clientes.garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        c = _conversa(cur, cid)
        if not _pode_ver(c, usuario):
            raise ErroAtendimento(f"Esta conversa está com {c['atendente'] or 'outro atendente'}.", 403)
        if '@lid' in c['telefone']:
            raise ErroAtendimento("O WhatsApp escondeu o número deste cliente: peça o número a ele para salvar o contato.", 409)
        ja = clientes._achar_cliente(cur, c['telefone'])
    finally:
        conn.close()
    if ja:
        raise ErroAtendimento(f"Já está no cadastro de clientes como {ja[1]}. Atualize a página.", 409)
    nome = clientes._limpo(dados.get('nome'), 120) or clientes._limpo(c['nome'], 120)
    aceite = bool(dados.get('aceite'))
    r = clientes.salvar(None, {'nome': nome, 'telefone': c['telefone'], 'aniversario': dados.get('aniversario'),
                               'aceite': aceite}, usuario)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE Clientes SET Origem = 'whatsapp' WHERE ClienteID = ?", r['id'])
        cur.execute("UPDATE AtendimentoConversas SET ClienteID = ?, Nome = ? WHERE ConversaID = ?", r['id'], nome, cid)
        cur.execute("INSERT INTO AtendimentoMensagens (ConversaID, De, Tipo, Texto, PorID, PorNome, CriadaEm) "
                    "VALUES (?, ?, 'texto', ?, ?, ?, ?)", cid, DE_SISTEMA, f"{usuario['nome']} salvou o contato.",
                    usuario['id'], usuario['nome'], agora)
        conn.commit()
    finally:
        conn.close()
    agenda, motivo = _agenda_celular(c['telefone'], nome) if dados.get('agenda', True) else (None, '')
    logger.info(f"[ATENDIMENTO] {usuario['nome']}: salvou o contato da conversa {cid} (cliente {r['id']}; "
                f"agenda: {'sim' if agenda else 'não' if agenda is False else 'não pediu'}).")
    mensagem = f"{nome} salvo no cadastro de clientes" + (" e na agenda do celular." if agenda else ".")
    if agenda is False:
        mensagem += f" Na agenda do celular não deu ({motivo}): salve pelo celular, se quiser."
    if not aceite:
        mensagem += " Ainda não recebe as ofertas (não autorizou)."
    return {'ok': True, 'mensagem': mensagem, 'agenda': agenda, 'cliente_id': r['id']}


# ------------------------------------------------------------------------------
# 📊 Visão da gestão e o aviso de cliente esperando
# ------------------------------------------------------------------------------
PERIODOS = {'hoje': 0, '7': 6, 'mes': None}


def _inicio(periodo, agora):
    hoje = agora.replace(hour=0, minute=0, second=0)
    if periodo == 'mes':
        return hoje.replace(day=1)
    return hoje - timedelta(days=PERIODOS.get(periodo, 0))


def _fmt_min(segundos):
    if segundos is None:
        return '—'
    m = int(round(segundos / 60))
    return "menos de 1 min" if m < 1 else (f"{m} min" if m < 60 else f"{m // 60}h{m % 60:02d}")


def visao(usuario, periodo='hoje', agora=None):
    _exigir(usuario, 'ver_gestao', "Só a gestão vê este resumo.")
    agora = agora or _agora()
    periodo = periodo if periodo in PERIODOS else 'hoje'
    ini = _inicio(periodo, agora)
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ConversaID, De, PorID, PorNome, CriadaEm FROM AtendimentoMensagens WHERE CriadaEm >= ?", ini)
        msgs = sorted(cur.fetchall(), key=lambda r: (r[0], _dt(r[4]) or agora))
        cur.execute(f"SELECT {_COLS_CONV} FROM AtendimentoConversas WHERE Status <> ?", ST_ENCERRADA)
        abertas = [_conv(r) for r in cur.fetchall()]
        cur.execute("""SELECT A.FuncionarioID, F.NomeCompleto, A.VistoEm, A.Ativo FROM AtendimentoAtendentes A
                       JOIN Funcionarios F ON F.FuncionarioID = A.FuncionarioID""")
        cadastro = {r[0]: (_primeiro(r[1]), r[2], bool(r[3])) for r in cur.fetchall()}
    finally:
        conn.close()
    pessoas = {fid: {'nome': nome, 'mensagens': 0, 'conversas': set(), 'tempos': [],
                     'online': _online('atendente', fid, visto, agora), 'atendente': True}
               for fid, (nome, visto, ativo) in cadastro.items() if ativo}
    conversas, tempos, pend, atual = set(), [], None, None
    for conv_id, de, por_id, por_nome, criada in msgs:
        if conv_id != atual:
            atual, pend = conv_id, None
        criada = _dt(criada)
        if de == DE_CLIENTE:
            conversas.add(conv_id)
            pend = pend or criada
        elif de == DE_LOJA and por_nome == POR_AGENDA:
            continue                                     # [AGENDA] mensagem automática da agenda: ninguém respondeu
        elif de == DE_LOJA and not por_id:
            pend = None                                  # respondeu pelo celular (ou automática): o cliente foi atendido
        elif de == DE_LOJA:
            p = pessoas.setdefault(por_id, {'nome': por_nome or '?', 'mensagens': 0, 'conversas': set(), 'tempos': [],
                                            'online': _online('gestor', por_id, None, agora), 'atendente': False})
            p['mensagens'] += 1
            p['conversas'].add(conv_id)
            if pend and criada:
                seg = max(0, (criada - pend).total_seconds())
                tempos.append(seg)
                p['tempos'].append(seg)
            pend = None
    media = (sum(tempos) / len(tempos)) if tempos else None
    import clientes
    abertas.sort(key=lambda c: (c['status'] != ST_ESPERANDO, -(_minutos(c['esperando_desde'], agora) or -1)))
    return {
        'periodo': periodo,
        'numeros': {'conversas': len(conversas), 'aguardando': sum(1 for c in abertas if c['esperando_desde']),
                    'resposta_media': _fmt_min(media), 'mensagens': sum(p['mensagens'] for p in pessoas.values())},
        'agora': [{'id': c['id'], 'nome': c['nome'] or _tel_txt(c['telefone']), 'status': c['status'],
                   'atendente': c['atendente'], 'aguardando_min': _minutos(c['esperando_desde'], agora), 'previa': c['previa']}
                  for c in abertas[:100]],
        'pessoas': sorted(({'nome': p['nome'], 'mensagens': p['mensagens'], 'conversas': len(p['conversas']),
                            'resposta_media': _fmt_min(sum(p['tempos']) / len(p['tempos']) if p['tempos'] else None),
                            'online': p['online'], 'atendente': p['atendente']} for p in pessoas.values()),
                          key=lambda p: (-p['mensagens'], p['nome'].lower())),
        'aviso_minutos': aviso_minutos()}


def aviso_minutos():
    try:
        return max(0, int(_param('aviso_minutos', AVISO_MINUTOS_PADRAO)))
    except (TypeError, ValueError):
        return AVISO_MINUTOS_PADRAO


def salvar_aviso(dados, usuario):
    _exigir(usuario, 'ver_gestao', "Só a gestão muda o aviso.")
    try:
        minutos = int(str(dados.get('minutos')).strip())
    except (TypeError, ValueError):
        raise ErroAtendimento("Minutos: use um número (0 desliga o aviso).")
    if not 0 <= minutos <= 240:
        raise ErroAtendimento("Minutos: de 0 (desligado) a 240.")
    _salvar_param('aviso_minutos', minutos)
    logger.info(f"[ATENDIMENTO] {usuario['nome']}: aviso de cliente esperando = {minutos} min.")
    return {'ok': True, 'aviso_minutos': minutos,
            'mensagem': f"Aviso no grupo da gestão depois de {minutos} min sem resposta." if minutos else "Aviso desligado."}


def _esc(t):
    import html
    return html.escape(str(t or ''), quote=False)


def avisar_esperando(agora=None, enviar=None):
    """
    [AGENDADOR] De minuto em minuto: cliente esperando resposta há mais de X minutos vai num aviso só para o grupo da
    gestão (tipo 💬 Atendimento em 📣 Avisos). Cada espera avisa uma vez. Devolve quantos entraram no aviso.
    """
    agora = agora or _agora()
    minutos = aviso_minutos()
    if not minutos:
        return 0
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLS_CONV}, AvisadoEm FROM AtendimentoConversas WHERE Status <> ? AND EsperandoDesde IS NOT NULL "
                    "AND EsperandoDesde <= ?", ST_ENCERRADA, agora - timedelta(minutes=minutos))
        linhas = [tuple(r) for r in cur.fetchall()]
        novos = [(_conv(r[:-1]), _dt(r[-1])) for r in linhas]
        novos = [c for c, avisado in novos if not avisado or avisado < c['esperando_desde']]
        for c in novos:
            cur.execute("UPDATE AtendimentoConversas SET AvisadoEm = ? WHERE ConversaID = ?", agora, c['id'])
        conn.commit()
    finally:
        conn.close()
    if not novos:
        return 0
    import clientes
    novos.sort(key=lambda c: c['esperando_desde'])
    texto = ("💬 <b>Cliente esperando resposta no WhatsApp</b>\n"
             + "\n".join(f"• {_esc(c['nome'] or _tel_txt(c['telefone']))} — há {_minutos(c['esperando_desde'], agora)} min "
                         f"({_esc(c['atendente']) if c['status'] == ST_ATENDENDO and c['atendente'] else 'ninguém atendendo'})"
                         for c in novos[:15])
             + (f"\n… e mais {len(novos) - 15}." if len(novos) > 15 else '')
             + "\n<i>Abra a 💬 Central de Atendimento.</i>")
    try:
        if enviar:
            enviar(texto)
        else:
            import alertas_estoque
            if alertas_estoque.aviso_ligado('atendimento'):
                alertas_estoque.enviar(texto)
    except Exception as e:
        logger.error(f"[ATENDIMENTO] Aviso de cliente esperando não foi: {e}")
    logger.info(f"[ATENDIMENTO] Aviso: {len(novos)} cliente(s) esperando há mais de {minutos} min.")
    return len(novos)

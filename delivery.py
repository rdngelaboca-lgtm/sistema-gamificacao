# ==============================================================================
# == delivery.py - 🛵 Página de PEDIDOS da Gela Boca (link da bio e dos posts) ====
# ==============================================================================
# Uma página PÚBLICA (/pedir) com a identidade da Gela Boca: as marcas do delivery, cada uma com os botões
# dos apps (iFood, 99Food...), o WhatsApp com a mensagem pronta, como chegar, Instagram e "receba novidades".
# É o link que vai na bio e nos posts do Instagram.
#
#   - O gestor monta tudo em Gestão Web › 🛵 Delivery: logo, capa, cores, frase, horários (aberto agora /
#     abre às...), aviso do dia, WhatsApp, endereço e as marcas com os links de cada app.
#   - Cliques: a página conta visitas e cliques (por marca, por app, por dia e por "link de post"), SEM guardar
#     nada de quem clicou (nem IP, nem telefone): só o número do dia.
#   - Links de post (?de=reels-acai): cada post pode ter o seu link para saber qual post trouxe mais pedidos.
#     Só contam os links criados na Gestão (ninguém de fora enche a tabela com nomes inventados).
#   - Segurança: a página só MOSTRA links; não tem formulário, não manda WhatsApp, não mostra nada do sistema.
# ==============================================================================
import base64
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import quote

import database

logger = logging.getLogger(__name__)

PASTA_FOTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fotos_delivery')
MAX_FOTO_BYTES = 3 * 1024 * 1024
MAX_MARCAS = 12
MAX_LINKS = 8
MAX_ORIGENS = 60
DIAS_SEMANA = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']   # 0 = segunda (weekday)
APPS = {                                  # cor do botão, cor do texto (contraste) e nome que aparece
    'ifood': {'nome': 'iFood', 'fundo': '#EA1D2C', 'texto': '#FFFFFF'},
    '99food': {'nome': '99Food', 'fundo': '#FFDD00', 'texto': '#1A1A1A'},
    'keeta': {'nome': 'Keeta', 'fundo': '#FFD23F', 'texto': '#1A1A1A'},
    'site': {'nome': 'Cardápio', 'fundo': '', 'texto': ''},          # cor da marca/da página
    'outro': {'nome': 'Outro', 'fundo': '', 'texto': ''},
}
TIPOS_CLIQUE = {'visita', 'link', 'whatsapp', 'maps', 'instagram', 'novidades'}
CONFIG_PADRAO = {
    'titulo': 'Gela Boca', 'frase': 'Peça agora pelo app que você preferir 🍦', 'logo': '', 'capa': '',
    'cor': '#0E6B63', 'cor2': '#F2A93B', 'whatsapp': '', 'whatsapp_msg': 'Olá! Vim pela página de pedidos e quero fazer um pedido.',
    'whatsapp_texto': 'Pedir pelo WhatsApp', 'endereco': '', 'maps': '', 'instagram': '', 'novidades': '1', 'aviso': '',
    'horarios': '',
}

_tabelas_ok = False
_cliques_recentes = {}                    # (ip, tipo, link, marca) -> hora: o mesmo clique repetido em 20 s conta 1 vez
_trava_cliques = threading.Lock()


class ErroDelivery(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = database.get_db_connection()
    if not conn:
        raise ErroDelivery("Sem conexão com o banco de dados.", 503)
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'DeliveryMarcas')
            CREATE TABLE DeliveryMarcas (
                MarcaID INT IDENTITY(1,1) PRIMARY KEY,
                Nome NVARCHAR(60) NOT NULL,
                Descricao NVARCHAR(160) NULL,
                Logo VARCHAR(40) NULL,
                Cor VARCHAR(7) NULL,
                Ordem INT NOT NULL DEFAULT 0,
                Ativo BIT NOT NULL DEFAULT 1,
                WhatsApp BIT NOT NULL DEFAULT 1,
                Excluida BIT NOT NULL DEFAULT 0,
                CriadoEm DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'DeliveryLinks')
            CREATE TABLE DeliveryLinks (
                LinkID INT IDENTITY(1,1) PRIMARY KEY,
                MarcaID INT NOT NULL,
                App VARCHAR(12) NOT NULL,
                Rotulo NVARCHAR(40) NULL,
                Url NVARCHAR(600) NOT NULL,
                Ordem INT NOT NULL DEFAULT 0,
                Excluido BIT NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'DeliveryConfig')
            CREATE TABLE DeliveryConfig (
                Chave VARCHAR(30) NOT NULL PRIMARY KEY,
                Valor NVARCHAR(1500) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'DeliveryOrigens')
            CREATE TABLE DeliveryOrigens (
                Slug VARCHAR(40) NOT NULL PRIMARY KEY,
                Nome NVARCHAR(80) NOT NULL,
                CriadoEm DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'DeliveryCliques')
            CREATE TABLE DeliveryCliques (
                Dia DATE NOT NULL,
                Tipo VARCHAR(12) NOT NULL,
                MarcaID INT NOT NULL DEFAULT 0,
                LinkID INT NOT NULL DEFAULT 0,
                Origem VARCHAR(40) NOT NULL DEFAULT '',
                Qtd INT NOT NULL DEFAULT 0,
                PRIMARY KEY (Dia, Tipo, MarcaID, LinkID, Origem)
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def _conexao():
    garantir_tabelas()
    conn = database.get_db_connection()
    if not conn:
        raise ErroDelivery("Sem conexão com o banco de dados.", 503)
    return conn


# ------------------------------------------------------------------------------
# Pequenos ajudantes
# ------------------------------------------------------------------------------
def _texto(v, n):
    return ' '.join(str(v or '').split())[:n]


def _int(v, padrao=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return padrao


def _cor(v, padrao):
    v = str(v or '').strip()
    return v.upper() if re.fullmatch(r'#[0-9A-Fa-f]{6}', v) else padrao


def texto_sobre(cor):
    """Branco ou quase preto, o que se lê melhor em cima da cor (contraste WCAG)."""
    cor = _cor(cor, '#0E6B63')
    r, g, b = (int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return '#FFFFFF' if (1.05 / (lum + 0.05)) >= ((lum + 0.05) / 0.05) else '#16201F'


def _url(v, nome="o link"):
    u = str(v or '').strip()
    if not u:
        return ''
    if not re.match(r'^https?://', u, re.I):
        u = 'https://' + u
    if len(u) > 600 or not re.fullmatch(r'https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:\d+)?(/[^\s<>"]*)?', u):
        raise ErroDelivery(f"{nome[0].upper() + nome[1:]} não parece um endereço de internet. Copie o link inteiro do app (começa com https://).")
    return u


def _telefone(v):
    dig = re.sub(r'\D', '', str(v or ''))
    if not dig:
        return ''
    if len(dig) in (10, 11):
        dig = '55' + dig
    if not (12 <= len(dig) <= 13 and dig.startswith('55')):
        raise ErroDelivery("WhatsApp: digite o número com DDD, ex.: (66) 99999-1234.")
    return dig


def _hora(v):
    v = str(v or '').strip()
    if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', v):
        raise ErroDelivery(f"Horário inválido: {v or '(vazio)'}. Use HH:MM, ex.: 13:00.")
    return v


def _min(h):
    return int(h[:2]) * 60 + int(h[3:5])


def _slug(v):
    t = unicodedata.normalize('NFKD', str(v or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'-{2,}', '-', re.sub(r'[^a-z0-9]+', '-', t)).strip('-')[:40]


def _hora_txt(h):
    return 'meia-noite' if h == '00:00' else h.replace(':00', 'h') if h.endswith(':00') else h


# ------------------------------------------------------------------------------
# Configuração (identidade, contato, horários)
# ------------------------------------------------------------------------------
def config():
    cfg = dict(CONFIG_PADRAO)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Chave, Valor FROM DeliveryConfig")
        for k, v in cur.fetchall():
            if k in cfg and v is not None:
                cfg[k] = v
    finally:
        conn.close()
    try:
        h = json.loads(cfg['horarios']) if cfg['horarios'] else None
    except ValueError:
        h = None
    cfg['horarios'] = h if isinstance(h, list) and len(h) == 7 else [None] * 7
    cfg['novidades'] = cfg['novidades'] == '1'
    return cfg


def salvar_config(dados, usuario):
    novos = {
        'titulo': _texto(dados.get('titulo'), 60) or CONFIG_PADRAO['titulo'],
        'frase': _texto(dados.get('frase'), 140),
        'cor': _cor(dados.get('cor'), CONFIG_PADRAO['cor']),
        'cor2': _cor(dados.get('cor2'), CONFIG_PADRAO['cor2']),
        'whatsapp': _telefone(dados.get('whatsapp')),
        'whatsapp_msg': _texto(dados.get('whatsapp_msg'), 300) or CONFIG_PADRAO['whatsapp_msg'],
        'whatsapp_texto': _texto(dados.get('whatsapp_texto'), 40) or CONFIG_PADRAO['whatsapp_texto'],
        'endereco': _texto(dados.get('endereco'), 160),
        'maps': _url(dados.get('maps'), "o link do Google Maps"),
        'novidades': '1' if dados.get('novidades') else '0',
        'aviso': _texto(dados.get('aviso'), 200),
    }
    insta = str(dados.get('instagram') or '').strip()
    if insta.startswith('@') or re.fullmatch(r'[A-Za-z0-9._]{1,30}', insta):
        insta = 'https://www.instagram.com/' + insta.lstrip('@')
    novos['instagram'] = _url(insta, "o link do Instagram")
    for k in ('logo', 'capa'):
        v = str(dados.get(k) or '')
        if v and not re.fullmatch(r'[0-9a-f]{32}\.(jpg|png|webp)', v):
            raise ErroDelivery("Foto inválida. Escolha a foto de novo.")
        novos[k] = v
    horarios = dados.get('horarios')
    if not isinstance(horarios, list) or len(horarios) != 7:
        raise ErroDelivery("Horários inválidos. Atualize a página.")
    hs = []
    for i, h in enumerate(horarios):
        if not h:
            hs.append(None)
            continue
        abre, fecha = _hora(h.get('abre')), _hora(h.get('fecha'))
        if abre == fecha:
            raise ErroDelivery(f"{DIAS_SEMANA[i].capitalize()}: a hora de abrir e de fechar são iguais.")
        hs.append({'abre': abre, 'fecha': fecha})
    novos['horarios'] = json.dumps(hs) if any(hs) else ''
    conn = _conexao()
    try:
        cur = conn.cursor()
        for k, v in novos.items():
            cur.execute("DELETE FROM DeliveryConfig WHERE Chave = ?", k)
            cur.execute("INSERT INTO DeliveryConfig (Chave, Valor) VALUES (?, ?)", k, v)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[DELIVERY] {(usuario or {}).get('nome')}: página de pedidos salva.")
    return {'ok': True, 'mensagem': "🛵 Página de pedidos salva."}


def situacao_horario(horarios, agora=None):
    """{'aberto': bool, 'texto'} pelo horário da semana; None se não tem horário cadastrado. Fecha depois da
    meia-noite (ex.: 13:00 às 00:30) vale: a parte depois da meia-noite conta no dia seguinte."""
    if not horarios or not any(horarios):
        return None
    agora = agora or datetime.now()
    wd, m = agora.weekday(), agora.hour * 60 + agora.minute
    ontem, hoje = horarios[(wd - 1) % 7], horarios[wd]
    if ontem and _min(ontem['fecha']) < _min(ontem['abre']) and m < _min(ontem['fecha']):
        return {'aberto': True, 'texto': f"Aberto agora · fecha às {_hora_txt(ontem['fecha'])}"}
    if hoje:
        a, f = _min(hoje['abre']), _min(hoje['fecha'])
        if (a <= m < f) if f > a else (m >= a):
            return {'aberto': True, 'texto': f"Aberto agora · fecha às {_hora_txt(hoje['fecha'])}"}
        if m < a:
            return {'aberto': False, 'texto': f"Fechado agora · abre hoje às {_hora_txt(hoje['abre'])}"}
    for d in range(1, 8):
        h = horarios[(wd + d) % 7]
        if h:
            quando = 'amanhã' if d == 1 else DIAS_SEMANA[(wd + d) % 7]
            return {'aberto': False, 'texto': f"Fechado agora · abre {quando} às {_hora_txt(h['abre'])}"}
    return None


def _horarios_txt(horarios):
    """[('segunda', '13h às 23h'), ...] para o rodapé da página."""
    saida = []
    for i, h in enumerate(horarios):
        saida.append((DIAS_SEMANA[i].capitalize(), f"{_hora_txt(h['abre'])} às {_hora_txt(h['fecha'])}" if h else 'fechado'))
    return saida


def _link_whatsapp(numero, mensagem):
    return f"https://wa.me/{numero}?text={quote(mensagem)}" if numero else ''


# ------------------------------------------------------------------------------
# Marcas e links
# ------------------------------------------------------------------------------
def _marcas(cur, so_ativas=False):
    cur.execute("SELECT MarcaID, Nome, Descricao, Logo, Cor, Ordem, Ativo, WhatsApp FROM DeliveryMarcas WHERE Excluida = 0"
                + (" AND Ativo = 1" if so_ativas else "") + " ORDER BY Ordem, MarcaID")
    marcas = [{'id': int(r[0]), 'nome': r[1] or '', 'descricao': r[2] or '', 'logo': r[3] or '', 'cor': r[4] or '',
               'ordem': _int(r[5]), 'ativo': bool(r[6]), 'whatsapp': bool(r[7]), 'links': []} for r in cur.fetchall()]
    por_id = {m['id']: m for m in marcas}
    cur.execute("SELECT LinkID, MarcaID, App, Rotulo, Url FROM DeliveryLinks WHERE Excluido = 0 ORDER BY MarcaID, Ordem, LinkID")
    for lid, mid, app, rot, url in cur.fetchall():
        if int(mid) in por_id:
            por_id[int(mid)]['links'].append({'id': int(lid), 'app': app, 'rotulo': rot or '', 'url': url})
    return marcas


def _ler_links(lista):
    if not isinstance(lista, list) or len(lista) > MAX_LINKS:
        raise ErroDelivery(f"No máximo {MAX_LINKS} links por marca.")
    saida = []
    for k, ln in enumerate(lista):
        ln = ln or {}
        app = ln.get('app') if ln.get('app') in APPS else 'outro'
        url = _url(ln.get('url'), f"o link {k + 1}")
        if not url:
            continue                                   # linha vazia: ignora
        rot = _texto(ln.get('rotulo'), 40)
        if app in ('outro', 'site') and not rot:
            rot = APPS[app]['nome']
        saida.append({'id': _int(ln.get('id')) or None, 'app': app, 'rotulo': rot, 'url': url})
    return saida


def salvar_marca(marca_id, dados, usuario):
    nome = _texto(dados.get('nome'), 60)
    if not nome:
        raise ErroDelivery("Dê o nome da marca (como aparece no iFood).")
    descricao = _texto(dados.get('descricao'), 160)
    logo = str(dados.get('logo') or '')
    if logo and not re.fullmatch(r'[0-9a-f]{32}\.(jpg|png|webp)', logo):
        raise ErroDelivery("Logo inválido. Escolha a foto de novo.")
    cor = _cor(dados.get('cor'), '') if dados.get('cor') else ''
    links = _ler_links(dados.get('links'))
    ativo = 1 if dados.get('ativo', True) else 0
    wpp = 1 if dados.get('whatsapp', True) else 0
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MarcaID FROM DeliveryMarcas WHERE Nome = ? AND Excluida = 0" + (" AND MarcaID <> ?" if marca_id else ""),
                    *([nome, marca_id] if marca_id else [nome]))
        if cur.fetchone():
            raise ErroDelivery(f"Já existe uma marca chamada {nome}.")
        if marca_id:
            cur.execute("UPDATE DeliveryMarcas SET Nome = ?, Descricao = ?, Logo = ?, Cor = ?, Ativo = ?, WhatsApp = ? "
                        "WHERE MarcaID = ? AND Excluida = 0", nome, descricao, logo or None, cor or None, ativo, wpp, marca_id)
            if cur.rowcount == 0:
                raise ErroDelivery("Marca não encontrada. Atualize a página.", 409)
        else:
            cur.execute("SELECT COUNT(1) FROM DeliveryMarcas WHERE Excluida = 0")
            if int(cur.fetchone()[0] or 0) >= MAX_MARCAS:
                raise ErroDelivery(f"No máximo {MAX_MARCAS} marcas.")
            cur.execute("SELECT ISNULL(MAX(Ordem), 0) FROM DeliveryMarcas")
            ordem = int(cur.fetchone()[0] or 0) + 1
            cur.execute("INSERT INTO DeliveryMarcas (Nome, Descricao, Logo, Cor, Ordem, Ativo, WhatsApp) VALUES (?, ?, ?, ?, ?, ?, ?); "
                        "SELECT SCOPE_IDENTITY();", nome, descricao, logo or None, cor or None, ordem, ativo, wpp)
            cur.nextset()                     # SQL Server: o 1º resultado é o do INSERT; o ID vem no seguinte
            marca_id = int(cur.fetchone()[0])
        # links: os que vieram com id são atualizados; os novos entram; os que sumiram ficam marcados como excluídos
        # (os cliques antigos continuam com o nome certo nos números)
        cur.execute("SELECT LinkID FROM DeliveryLinks WHERE MarcaID = ? AND Excluido = 0", marca_id)
        existentes = {int(r[0]) for r in cur.fetchall()}
        mantidos = set()
        for k, ln in enumerate(links, start=1):
            if ln['id'] in existentes:
                cur.execute("UPDATE DeliveryLinks SET App = ?, Rotulo = ?, Url = ?, Ordem = ? WHERE LinkID = ?",
                            ln['app'], ln['rotulo'] or None, ln['url'], k, ln['id'])
                mantidos.add(ln['id'])
            else:
                cur.execute("INSERT INTO DeliveryLinks (MarcaID, App, Rotulo, Url, Ordem) VALUES (?, ?, ?, ?, ?)",
                            marca_id, ln['app'], ln['rotulo'] or None, ln['url'], k)
        for lid in existentes - mantidos:
            cur.execute("UPDATE DeliveryLinks SET Excluido = 1 WHERE LinkID = ?", lid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"[DELIVERY] {(usuario or {}).get('nome')}: marca {nome} salva ({len(links)} link(s)).")
    return {'ok': True, 'id': marca_id, 'mensagem': f"🛵 {nome}: salva."}


def excluir_marca(marca_id, usuario):
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Nome FROM DeliveryMarcas WHERE MarcaID = ? AND Excluida = 0", marca_id)
        r = cur.fetchone()
        if not r:
            raise ErroDelivery("Marca não encontrada. Atualize a página.", 409)
        cur.execute("UPDATE DeliveryMarcas SET Excluida = 1, Ativo = 0 WHERE MarcaID = ?", marca_id)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[DELIVERY] {(usuario or {}).get('nome')}: tirou a marca {r[0]}.")
    return {'ok': True, 'mensagem': f"{r[0]} saiu da página (os números antigos continuam)."}


def ordenar_marcas(dados, usuario):
    ids = dados.get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > 100:
        raise ErroDelivery("Ordem inválida. Atualize a página.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        for k, mid in enumerate(ids, start=1):
            cur.execute("UPDATE DeliveryMarcas SET Ordem = ? WHERE MarcaID = ?", k, _int(mid))
        conn.commit()
    finally:
        conn.close()
    return {'ok': True, 'mensagem': "Ordem das marcas salva."}


# ------------------------------------------------------------------------------
# Fotos (logo, capa, logo das marcas): ficam no servidor, nunca no GitHub
# ------------------------------------------------------------------------------
def salvar_foto(dados, usuario):
    m = re.fullmatch(r'data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\s]+)', str((dados or {}).get('foto') or '').strip())
    if not m:
        raise ErroDelivery("Foto inválida. Escolha a foto de novo.")
    try:
        conteudo = base64.b64decode(m.group(2), validate=False)
    except (ValueError, TypeError):
        raise ErroDelivery("Foto inválida. Escolha a foto de novo.")
    if len(conteudo) > MAX_FOTO_BYTES:
        raise ErroDelivery("Foto grande demais (máximo 3 MB).")
    if conteudo[:3] == b'\xff\xd8\xff':
        ext = 'jpg'
    elif conteudo[:8] == b'\x89PNG\r\n\x1a\n':
        ext = 'png'
    elif conteudo[:4] == b'RIFF' and conteudo[8:12] == b'WEBP':
        ext = 'webp'
    else:
        raise ErroDelivery("O arquivo não é uma foto (JPG, PNG ou WEBP).")
    os.makedirs(PASTA_FOTOS, exist_ok=True)
    nome = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(PASTA_FOTOS, nome), 'wb') as f:
        f.write(conteudo)
    logger.info(f"[DELIVERY] {(usuario or {}).get('nome')}: foto {nome} ({len(conteudo) // 1024} KB).")
    return {'ok': True, 'foto': nome}


def caminho_foto(nome):
    if not re.fullmatch(r'[0-9a-f]{32}\.(jpg|png|webp)', str(nome or '')):
        raise ErroDelivery("Foto não encontrada.", 404)
    caminho = os.path.join(PASTA_FOTOS, nome)
    if not os.path.isfile(caminho):
        raise ErroDelivery("Foto não encontrada.", 404)
    return caminho


# ------------------------------------------------------------------------------
# Links de post (?de=...)
# ------------------------------------------------------------------------------
def _origens(cur):
    cur.execute("SELECT Slug, Nome, CriadoEm FROM DeliveryOrigens ORDER BY CriadoEm DESC, Slug")
    return [{'slug': r[0], 'nome': r[1], 'criado': r[2].strftime('%d/%m/%Y') if hasattr(r[2], 'strftime') else str(r[2] or '')[:10]}
            for r in cur.fetchall()]


def salvar_origem(dados, usuario):
    nome = _texto(dados.get('nome'), 80)
    slug = _slug(dados.get('slug') or nome)
    if len(slug) < 2:
        raise ErroDelivery("Dê um nome ao post, ex.: Reels açaí de novembro.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM DeliveryOrigens")
        if int(cur.fetchone()[0] or 0) >= MAX_ORIGENS:
            raise ErroDelivery(f"No máximo {MAX_ORIGENS} links de post: apague os antigos.")
        cur.execute("SELECT 1 FROM DeliveryOrigens WHERE Slug = ?", slug)
        if cur.fetchone():
            raise ErroDelivery(f"Já existe um link de post chamado {slug}.")
        cur.execute("INSERT INTO DeliveryOrigens (Slug, Nome) VALUES (?, ?)", slug, nome or slug)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[DELIVERY] {(usuario or {}).get('nome')}: link de post {slug}.")
    return {'ok': True, 'slug': slug, 'mensagem': "Link do post criado: copie e cole no post."}


def excluir_origem(slug, usuario):
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM DeliveryOrigens WHERE Slug = ?", str(slug or '')[:40])
        conn.commit()
    finally:
        conn.close()
    return {'ok': True, 'mensagem': "Link do post apagado (os cliques dele continuam somados no total)."}


# ------------------------------------------------------------------------------
# Página pública
# ------------------------------------------------------------------------------
def pagina(agora=None):
    """Tudo o que a página /pedir precisa (só o que é para mostrar ao público)."""
    cfg = config()
    conn = _conexao()
    try:
        cur = conn.cursor()
        marcas = _marcas(cur, so_ativas=True)
    finally:
        conn.close()
    numero = cfg['whatsapp']
    for m in marcas:
        m['cor'] = m['cor'] or cfg['cor']
        m['texto_cor'] = texto_sobre(m['cor'])
        for ln in m['links']:
            ap = APPS.get(ln['app'], APPS['outro'])
            ln['nome'] = ln['rotulo'] if ln['app'] in ('outro', 'site') else ap['nome']
            ln['fundo'] = ap['fundo'] or m['cor']
            ln['texto'] = ap['texto'] or m['texto_cor']
        m['wa'] = _link_whatsapp(numero, f"{cfg['whatsapp_msg']}\nMarca: {m['nome']}") if numero and m['whatsapp'] else ''
    maps = cfg['maps'] or (f"https://www.google.com/maps/search/?api=1&query={quote(cfg['endereco'])}" if cfg['endereco'] else '')
    return {'titulo': cfg['titulo'], 'frase': cfg['frase'], 'logo': cfg['logo'], 'capa': cfg['capa'],
            'cor': cfg['cor'], 'cor_texto': texto_sobre(cfg['cor']), 'cor2': cfg['cor2'], 'cor2_texto': texto_sobre(cfg['cor2']),
            'aviso': cfg['aviso'], 'marcas': marcas, 'whatsapp': _link_whatsapp(numero, cfg['whatsapp_msg']),
            'whatsapp_texto': cfg['whatsapp_texto'], 'endereco': cfg['endereco'], 'maps': maps, 'instagram': cfg['instagram'],
            'novidades': cfg['novidades'], 'horario': situacao_horario(cfg['horarios'], agora),
            'horarios': _horarios_txt(cfg['horarios']) if any(cfg['horarios']) else []}


def registrar_clique(dados, ip, agora=None):
    """Conta 1 visita/clique do dia. Não guarda nada de quem clicou; o mesmo clique repetido em 20 s conta 1 vez."""
    dados = dados or {}
    tipo = dados.get('tipo')
    if tipo not in TIPOS_CLIQUE:
        return {'ok': False}
    link, marca = _int(dados.get('link')), _int(dados.get('marca'))
    agora = agora or datetime.now()
    chave = (str(ip or '')[:64], tipo, link, marca)
    t = time.time()
    with _trava_cliques:
        if t - _cliques_recentes.get(chave, 0) < 20:
            return {'ok': True, 'repetido': True}
        _cliques_recentes[chave] = t
        if len(_cliques_recentes) > 5000:
            for k in [k for k, v in _cliques_recentes.items() if t - v > 60]:
                _cliques_recentes.pop(k, None)
    origem = _slug(dados.get('de'))
    conn = _conexao()
    try:
        cur = conn.cursor()
        if origem:
            cur.execute("SELECT 1 FROM DeliveryOrigens WHERE Slug = ?", origem)
            if not cur.fetchone():
                origem = ''                         # nome inventado: conta, mas sem origem
        if tipo == 'link':
            cur.execute("SELECT MarcaID FROM DeliveryLinks WHERE LinkID = ?", link)
            r = cur.fetchone()
            if not r:
                return {'ok': False}
            marca = int(r[0])
        elif tipo == 'whatsapp' and marca:
            cur.execute("SELECT 1 FROM DeliveryMarcas WHERE MarcaID = ?", marca)
            if not cur.fetchone():
                marca = 0
            link = 0
        else:
            link, marca = 0, 0
        dia = agora.date()
        cur.execute("UPDATE DeliveryCliques SET Qtd = Qtd + 1 WHERE Dia = ? AND Tipo = ? AND MarcaID = ? AND LinkID = ? AND Origem = ?",
                    dia, tipo, marca, link, origem)
        if cur.rowcount == 0:
            try:
                cur.execute("INSERT INTO DeliveryCliques (Dia, Tipo, MarcaID, LinkID, Origem, Qtd) VALUES (?, ?, ?, ?, ?, 1)",
                            dia, tipo, marca, link, origem)
            except Exception:                       # 2 cliques ao mesmo tempo: o outro já criou a linha
                conn.rollback()
                cur.execute("UPDATE DeliveryCliques SET Qtd = Qtd + 1 WHERE Dia = ? AND Tipo = ? AND MarcaID = ? AND LinkID = ? "
                            "AND Origem = ?", dia, tipo, marca, link, origem)
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}


# ------------------------------------------------------------------------------
# Gestão
# ------------------------------------------------------------------------------
def estatisticas(dias=30, hoje=None):
    hoje = hoje or date.today()
    dias = max(1, min(_int(dias, 30), 366))
    desde = hoje - timedelta(days=dias - 1)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Dia, Tipo, MarcaID, LinkID, Origem, Qtd FROM DeliveryCliques WHERE Dia >= ? AND Dia <= ?", desde, hoje)
        linhas = cur.fetchall()
        cur.execute("SELECT MarcaID, Nome FROM DeliveryMarcas")
        nomes_marca = {int(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT LinkID, App, Rotulo FROM DeliveryLinks")
        nomes_link = {int(r[0]): (r[2] if r[1] in ('outro', 'site') and r[2] else APPS.get(r[1], APPS['outro'])['nome']) for r in cur.fetchall()}
        origens = {o['slug']: o['nome'] for o in _origens(cur)}
    finally:
        conn.close()
    por_dia = {(desde + timedelta(days=k)).isoformat(): {'visitas': 0, 'cliques': 0} for k in range(dias)}
    tipos = {t: 0 for t in TIPOS_CLIQUE}
    por_link, por_origem = {}, {}
    for dia, tipo, mid, lid, org, qtd in linhas:
        qtd = int(qtd or 0)
        d = dia.isoformat() if hasattr(dia, 'isoformat') else str(dia)[:10]
        tipos[tipo] = tipos.get(tipo, 0) + qtd
        if d in por_dia:
            por_dia[d]['visitas' if tipo == 'visita' else 'cliques'] += qtd
        if tipo in ('link', 'whatsapp') and int(mid or 0):
            k = (int(mid), int(lid or 0), tipo)
            por_link[k] = por_link.get(k, 0) + qtd
        o = org or ''
        po = por_origem.setdefault(o, {'visitas': 0, 'cliques': 0})
        po['visitas' if tipo == 'visita' else 'cliques'] += qtd
    detalhes = sorted(({'marca': nomes_marca.get(m, '(marca removida)'),
                        'app': 'WhatsApp' if t == 'whatsapp' else nomes_link.get(l, '(link removido)'), 'qtd': q}
                       for (m, l, t), q in por_link.items()), key=lambda x: (-x['qtd'], x['marca'], x['app']))
    origem_lista = sorted(({'slug': o, 'nome': origens.get(o, o) if o else 'Sem link de post (bio, direto)', **v}
                           for o, v in por_origem.items()), key=lambda x: (-x['cliques'], -x['visitas']))
    return {'dias': dias, 'desde': desde.strftime('%d/%m'), 'visitas': tipos['visita'],
            'cliques_apps': tipos['link'], 'whatsapp': tipos['whatsapp'], 'maps': tipos['maps'], 'instagram': tipos['instagram'],
            'novidades': tipos['novidades'], 'por_marca_app': detalhes, 'por_origem': origem_lista,
            'por_dia': [{'dia': d, **v} for d, v in por_dia.items()]}


def painel(host_url=None, dias=30):
    cfg = config()
    conn = _conexao()
    try:
        cur = conn.cursor()
        marcas = _marcas(cur)
        origens = _origens(cur)
    finally:
        conn.close()
    base, local = endereco(host_url)
    return {'config': cfg, 'marcas': marcas, 'origens': origens, 'apps': {k: v['nome'] for k, v in APPS.items()},
            'link': base + '/pedir', 'link_local': local, 'estatisticas': estatisticas(dias),
            'horario': situacao_horario(cfg['horarios'])}


def endereco(host_url):
    """(endereço da internet da página, True se é só da rede da loja) — o mesmo gravado em 📢 Clientes › ⚙️."""
    try:
        import confirmacoes
        return confirmacoes.endereco_publico(host_url)
    except Exception as e:
        logger.warning(f"[DELIVERY] endereço público indisponível: {e}")
        base = str(host_url or '').rstrip('/')
        return base, True


def qr_svg(url):
    try:
        import clientes
        return clientes.qr_svg(url)
    except Exception as e:
        logger.warning(f"[DELIVERY] QR indisponível: {e}")
        return None

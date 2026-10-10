# ==============================================================================
# == alertas_estoque.py  -  Avisos do estoque no Telegram =====================
# ==============================================================================
# Usado pelo agendador.py (robô que roda o dia todo no servidor):
#   • todo dia: produtos abaixo do estoque mínimo, produtos que devem acabar em
#     até 2 dias (pelo consumo médio) e listas do app aprovadas e não finalizadas
#     há mais de 2 dias;
#   • toda segunda-feira: resumo dos maiores aumentos de preço das notas
#     importadas desde o último resumo.
#
# Para testar à mão (mostra o texto e NÃO envia):   python alertas_estoque.py
# Para testar enviando de verdade:                  python alertas_estoque.py enviar
#
# [WHATSAPP GRUPO] enviar() é a porta de saída de TODOS os avisos da gestão do robô
# (estoque, preços, notas da SEFAZ, orçamentos, clima/previsão, faturamento e folha).
# O canal é escolhido em Gestão › 📣 Avisos (tabela ConfigAvisos): Telegram, WhatsApp
# (grupo, pela Z-API) ou os dois. Se o WhatsApp falhar, o aviso vai para o Telegram
# com um alerta (nada se perde).
# ==============================================================================
import html
import logging
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import config
import database

logger = logging.getLogger(__name__)

DIAS_PARA_ACABAR = 2              # avisa quem deve acabar em até 2 dias
DIAS_LISTA_ABERTA = 2             # lista aprovada e não finalizada há mais de 2 dias
DIAS_CONTAGEM_CONFIAVEL = 60      # estimativa de estoque com contagem mais velha que isso não entra
MAX_LINHAS = 25                   # por bloco (o resto vira "… e mais N")
# [AVISOS LIMPOS] o aviso diário do grupo traz só o que ENTROU na lista desde o último aviso
MAX_LINHAS_NOVOS = 8              # por bloco no aviso diário (os mais usados primeiro)
CONSUMO_MINIMO_ACABANDO = Decimal('0.1')   # gasta menos que isso por dia: não é "acaba em 2 dias" (era o "0,0/dia → acabou")

# [AVISOS LIMPOS] cada tipo de aviso do grupo pode ser desligado na página 📣 Avisos (erros e certificado: sempre)
TIPOS_AVISO = [
    ('estoque', '📦 Estoque', '08:30', 'O que entrou hoje em "acaba em 2 dias" e "abaixo do mínimo"; listas esquecidas'),
    ('precos', '📈 Preços que subiram', 'Segunda 08:35', 'Resumo da semana dos aumentos de preço nas notas'),
    ('lembrete', '⏰ Faturamento que faltou lançar', '09:15', 'Lembrete dos dias sem faturamento lançado'),
    ('previsao', '🌤️ Previsão e escala', '10:00', 'Hoje e os próximos 3 dias: clima, freelancers × escalados'),
    ('notas', '📥 Notas novas da SEFAZ', '12:00 e 18:00', 'Resumo das notas baixadas e produtos novos para a franquia'),
    ('danfe', '📄 DANFE das notas novas', 'junto', 'O PDF de cada nota nova vai junto com o resumo (até 5)'),
    ('orcamentos', '📋 Orçamentos', 'junto', 'Nota que chegou para um orçamento (o que veio diferente), no resumo das notas'),
    ('faturamento', '📊 Faturamento e folha', 'Ao lançar · dia 1', 'Resumo do dia quando o faturamento é lançado e o fechamento do mês'),
]
CHAVES_AVISO = [t[0] for t in TIPOS_AVISO]


def esc(t):
    return html.escape(str(t if t is not None else ''), quote=False)


def _qtd(v):
    v = Decimal(str(v or 0))
    txt = f"{v:,.1f}" if v != v.to_integral_value() else f"{v:,.0f}"
    return txt.replace(',', 'X').replace('.', ',').replace('X', '.')


def chat_dos_avisos():
    """Para onde vão os avisos (config.py): ESTOQUE_CHAT_ID_AVISOS, senão o do app de compras, senão o grupo do gestor."""
    for nome in ('ESTOQUE_CHAT_ID_AVISOS', 'COMPRAS_CHAT_ID_AVISOS', 'GESTOR_GROUP_CHAT_ID'):
        valor = getattr(config, nome, None)
        if valor:
            return valor
    return None


# ------------------------------------------------------------------------------
# Estoque: abaixo do mínimo e acabando
# ------------------------------------------------------------------------------
def situacao_do_estoque(hoje=None):
    """
    Devolve (abaixo_minimo, acabando), cada um uma lista de dicts com
    produto, unidade, estoque, minimo, consumo_dia e dias (quanto ainda dura).
    Usa a mesma conta do Gestão de Estoque / app de compras (última contagem +
    notas depois dela - consumo médio por dia).
    """
    hoje = hoje or date.today()
    import compras_database           # só quando precisa (o app de compras pode não estar instalado)
    conn = database.get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        ultima = compras_database._ultima_contagem_id(conn.cursor())
    finally:
        conn.close()
    if not ultima:
        return [], []
    itens = compras_database._sugestao_por_produto(ultima, hoje)

    abaixo, acabando = [], []
    for i in itens.values():
        if not i.get('Contado') or i.get('EstoqueHoje') is None:
            continue
        if int(i.get('DiasDesdeContagem') or 0) > DIAS_CONTAGEM_CONFIAVEL:
            continue
        estoque = Decimal(str(i['EstoqueHoje']))
        minimo = Decimal(str(i.get('EstoqueMinimo') or 0))
        uso = Decimal(str(i.get('UsoMedioDiario') or 0))
        dias = (estoque / uso) if uso > 0 else None
        linha = {'produto_id': i['ProdutoID'], 'produto': i['NomeProduto'], 'unidade': i.get('Unidade') or 'UN',
                 'estoque': estoque, 'minimo': minimo, 'consumo_dia': uso, 'dias': dias}
        if (dias is not None and dias <= DIAS_PARA_ACABAR and not i.get('ConsumoNegativo')
                and uso >= CONSUMO_MINIMO_ACABANDO):
            acabando.append(linha)
        elif minimo > 0 and estoque < minimo:
            abaixo.append(linha)
    acabando.sort(key=lambda x: (x['dias'], x['produto']))
    abaixo.sort(key=lambda x: (x['estoque'] / x['minimo'], x['produto']))
    return abaixo, acabando


# ------------------------------------------------------------------------------
# App de compras: listas aprovadas e esquecidas
# ------------------------------------------------------------------------------
def listas_esquecidas(agora=None):
    """Listas APROVADAS há mais de DIAS_LISTA_ABERTA dias e ainda não finalizadas."""
    agora = agora or datetime.now()
    try:
        import compras_database
    except Exception:
        return []
    conn = database.get_db_connection()
    if not conn:
        raise Exception("Falha de conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        if not database._tabela_existe(cur, 'CompraListas'):
            return []
        cur.execute("""SELECT Codigo, NomeRotina, NomeFuncionario, AprovadaEm, CriadaEm FROM CompraListas
                       WHERE Status = ?""", (compras_database.ST_APROVADA,))
        linhas = cur.fetchall()
    finally:
        conn.close()
    limite = agora - timedelta(days=DIAS_LISTA_ABERTA)
    resultado = []
    for cod, rotina, func, aprovada, criada in linhas:
        quando = compras_database._como_datahora(aprovada) or compras_database._como_datahora(criada)
        if quando and quando <= limite:
            resultado.append({'codigo': cod, 'rotina': rotina, 'funcionario': func, 'aprovada_em': quando,
                              'dias': (agora - quando).days})
    resultado.sort(key=lambda x: x['aprovada_em'])
    return resultado


# ------------------------------------------------------------------------------
# Textos das mensagens
# ------------------------------------------------------------------------------
def _bloco(titulo, linhas):
    if not linhas:
        return []
    corpo = linhas[:MAX_LINHAS]
    if len(linhas) > MAX_LINHAS:
        corpo.append(f"<i>… e mais {len(linhas) - MAX_LINHAS}</i>")
    return ['', titulo] + corpo


def montar_avisos_diarios(hoje=None, agora=None):
    """Texto (HTML do Telegram) dos avisos do dia, ou None se não há nada para avisar."""
    hoje = hoje or date.today()
    abaixo, acabando = situacao_do_estoque(hoje)
    listas = listas_esquecidas(agora)
    if not (abaixo or acabando or listas):
        return None
    partes = [f"📦 <b>Avisos do estoque · {hoje.strftime('%d/%m')}</b>"]
    partes += _bloco(f"⏳ <b>Devem acabar em até {DIAS_PARA_ACABAR} dias</b> (pelo consumo médio):", [
        f"• {esc(a['produto'])}: tem ≈ {_qtd(a['estoque'])} {esc(a['unidade'])}, gasta {_qtd(a['consumo_dia'])}/dia"
        f" → {'acabou' if a['dias'] < Decimal('0.5') else 'dura ~' + _qtd(a['dias']) + ' dia(s)'}" for a in acabando])
    partes += _bloco("🔻 <b>Abaixo do estoque mínimo:</b>", [
        f"• {esc(a['produto'])}: tem ≈ {_qtd(a['estoque'])} de mínimo {_qtd(a['minimo'])} {esc(a['unidade'])}" for a in abaixo])
    partes += _bloco(f"🛒 <b>Listas aprovadas e não finalizadas há mais de {DIAS_LISTA_ABERTA} dias:</b>", [
        f"• {esc(l['rotina'])} de {esc(l['funcionario'] or '?')} · aprovada em {l['aprovada_em'].strftime('%d/%m')}"
        f" ({l['dias']} dias). Finalize ou cancele no app." for l in listas])
    partes += ['', '<i>Estoque estimado: última contagem + notas importadas − consumo médio.</i>']
    return "\n".join(partes)


def montar_avisos_do_dia(ja_avisados=None, hoje=None, agora=None):
    """
    [AVISOS LIMPOS] O aviso das 8:30 para o grupo: só o que ENTROU na lista desde o último aviso (no máximo
    MAX_LINHAS_NOVOS por bloco, os mais usados primeiro) e uma linha com quantos continuam. Na segunda, mesmo
    sem nada novo, uma linha lembra os que continuam. Nada novo nos outros dias: nenhuma mensagem.
    Devolve (texto ou None, avisados) — avisados = o que está na lista hoje (guarde para amanhã).
    """
    hoje = hoje or date.today()
    ja = ja_avisados or {}
    ja_prod = set(ja.get('produtos') or [])
    ja_listas = set(ja.get('listas') or [])
    abaixo, acabando = situacao_do_estoque(hoje)
    listas = listas_esquecidas(agora)
    avisados = {'produtos': sorted({a['produto_id'] for a in abaixo + acabando}),
                'listas': sorted(l['codigo'] for l in listas)}
    novos_acab = sorted((a for a in acabando if a['produto_id'] not in ja_prod), key=lambda a: (-a['consumo_dia'], a['produto']))
    novos_abaixo = [a for a in abaixo if a['produto_id'] not in ja_prod]
    novas_listas = [l for l in listas if l['codigo'] not in ja_listas]
    continuam = len(abaixo) + len(acabando) - len(novos_acab) - len(novos_abaixo)
    segunda = hoje.weekday() == 0
    if not (novos_acab or novos_abaixo or novas_listas) and not (segunda and (continuam or listas)):
        return None, avisados

    def bloco(titulo, linhas):
        if not linhas:
            return []
        corpo = linhas[:MAX_LINHAS_NOVOS]
        if len(linhas) > MAX_LINHAS_NOVOS:
            corpo.append(f"<i>… e mais {len(linhas) - MAX_LINHAS_NOVOS}</i>")
        return ['', titulo] + corpo
    partes = [f"📦 <b>Estoque · {hoje.strftime('%d/%m')}</b>"]
    partes += bloco(f"⏳ <b>Novos: acabam em até {DIAS_PARA_ACABAR} dias</b>", [
        f"• {esc(a['produto'])}: ≈ {_qtd(a['estoque'])} {esc(a['unidade'])} · gasta {_qtd(a['consumo_dia'])}/dia"
        + ((" → <b>acabou</b>" if a['estoque'] <= 0 else " → <b>acaba hoje</b>") if a['dias'] < Decimal('0.5')
           else f" → ~{_qtd(a['dias'])} dia(s)") for a in novos_acab])
    partes += bloco("🔻 <b>Novos abaixo do mínimo</b>", [
        f"• {esc(a['produto'])}: ≈ {_qtd(a['estoque'])} de {_qtd(a['minimo'])} {esc(a['unidade'])}" for a in novos_abaixo])
    lista_aviso = listas if segunda else novas_listas          # segunda: lembra todas as esquecidas
    partes += bloco(f"🛒 <b>Listas aprovadas há mais de {DIAS_LISTA_ABERTA} dias</b> (finalize ou cancele no app)", [
        f"• {esc(l['rotina'])} de {esc(l['funcionario'] or '?')} · {l['dias']} dias" for l in lista_aviso])
    if continuam:
        partes += ['', f"➕ {continuam} que já estavam na lista (acabados ou abaixo do mínimo): veja no app › Gestão › Estoque."]
    return "\n".join(partes), avisados


def montar_resumo_precos(desde_nota_id=None, desde_data=None):
    """
    Resumo dos maiores aumentos (um por produto, o maior). Devolve (texto ou None, maior NotaID visto).
    """
    aumentos = database.aumentos_de_preco(desde_nota_id=desde_nota_id, desde_data=desde_data)
    maior = max([a['nota_id'] for a in aumentos] + [maior_nota_id() or 0, int(desde_nota_id or 0)])
    por_produto = {}
    for a in aumentos:
        if a['produto_id'] not in por_produto or a['pct'] > por_produto[a['produto_id']]['pct']:
            por_produto[a['produto_id']] = a
    lista = sorted(por_produto.values(), key=lambda a: -a['pct'])
    if not lista:
        return None, maior
    partes = ["📈 <b>Resumo semanal: preços que subiram</b>",
              f"<i>{len(lista)} produto(s) com aumento de {database.LIMITE_AUMENTO_PRECO_PCT:.0f}% ou mais "
              "em relação à compra anterior (notas importadas na semana):</i>"]
    linhas = [f"• {esc(database.texto_aumento_preco(a))} · NF {esc(a['numero_nf'])}, {esc(a['fornecedor'])}"
              for a in lista[:MAX_LINHAS]]
    if len(lista) > MAX_LINHAS:
        linhas.append(f"<i>… e mais {len(lista) - MAX_LINHAS}</i>")
    return "\n".join(partes + [''] + linhas), maior


def maior_nota_id():
    conn = database.get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(NotaID) FROM NotasFiscaisEntrada")
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else None
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# [WHATSAPP GRUPO] canal dos avisos
# ------------------------------------------------------------------------------
CANAIS = ('telegram', 'whatsapp', 'ambos')
_tabela_cfg_ok = False


def _garantir_config():
    global _tabela_cfg_ok
    if _tabela_cfg_ok:
        return
    conn = database.get_db_connection()
    if not conn:
        raise RuntimeError("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ConfigAvisos')
            CREATE TABLE ConfigAvisos (
                Chave VARCHAR(40) NOT NULL PRIMARY KEY,
                Valor NVARCHAR(300) NULL
            )
        """)
        conn.commit()
        _tabela_cfg_ok = True
    finally:
        conn.close()


def config_avisos():
    """{'canal', 'grupo_id', 'grupo_nome', 'atualizado'}. Sem banco / nunca configurado: Telegram."""
    cfg = {'canal': 'telegram', 'grupo_id': '', 'grupo_nome': '', 'atualizado': '', 'desligados': ''}
    try:
        _garantir_config()
        conn = database.get_db_connection()
        if not conn:
            return cfg
        try:
            cur = conn.cursor()
            cur.execute("SELECT Chave, Valor FROM ConfigAvisos")
            for chave, valor in cur.fetchall():
                if chave in cfg:
                    cfg[chave] = valor or ''
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Avisos: não consegui ler o canal (vai pelo Telegram): {e}")
    if cfg['canal'] not in CANAIS:
        cfg['canal'] = 'telegram'
    cfg['desligados'] = [c for c in str(cfg['desligados'] or '').split(',') if c in CHAVES_AVISO]   # [AVISOS LIMPOS]
    return cfg


def aviso_ligado(tipo):
    """[AVISOS LIMPOS] False se o gestor desligou este tipo de aviso na página 📣 Avisos."""
    return tipo not in config_avisos()['desligados']


def salvar_config_avisos(canal, grupo_id, grupo_nome, usuario, desligados=None):
    canal = str(canal or '').strip()
    if canal not in CANAIS:
        raise ValueError("Escolha Telegram, WhatsApp ou os dois.")
    grupo_id = str(grupo_id or '').strip()[:120]
    if canal != 'telegram' and not grupo_id:
        raise ValueError("Escolha o grupo do WhatsApp.")
    _garantir_config()
    valores = {'canal': canal, 'grupo_id': grupo_id, 'grupo_nome': str(grupo_nome or '').strip()[:150],
               'atualizado': f"{datetime.now():%d/%m/%Y %H:%M} por {(usuario or {}).get('nome', '?')}"}
    if desligados is not None:          # [AVISOS LIMPOS] None = não mexe nos interruptores
        if not isinstance(desligados, (list, tuple, set)):
            raise ValueError("Lista de avisos desligados inválida.")
        desconhecidos = [c for c in desligados if c not in CHAVES_AVISO]
        if desconhecidos:
            raise ValueError(f"Tipo de aviso desconhecido: {', '.join(map(str, desconhecidos))}")
        valores['desligados'] = ",".join(c for c in CHAVES_AVISO if c in desligados)
    conn = database.get_db_connection()
    if not conn:
        raise RuntimeError("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        for chave, valor in valores.items():
            cur.execute("DELETE FROM ConfigAvisos WHERE Chave = ?", chave)
            cur.execute("INSERT INTO ConfigAvisos (Chave, Valor) VALUES (?, ?)", chave, valor)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Avisos da gestão: canal {canal} ({valores['grupo_nome'] or grupo_id or 'Telegram'}) — {valores['atualizado']}"
                + (f" · desligados: {valores['desligados'] or 'nenhum'}" if 'desligados' in valores else "") + ".")
    return config_avisos()


def enviar_detalhado(texto):
    """Manda pelo canal escolhido. Devolve {'ok', 'whatsapp' (None/True/False), 'telegram' (None/True/False), 'erro'}."""
    cfg = config_avisos()
    r = {'ok': False, 'whatsapp': None, 'telegram': None, 'erro': '', 'canal': cfg['canal']}
    if cfg['canal'] in ('whatsapp', 'ambos') and cfg['grupo_id']:
        import notificador_whatsapp
        ok, motivo = notificador_whatsapp.enviar_para_grupo(cfg['grupo_id'], notificador_whatsapp.html_para_whatsapp(texto))
        r['whatsapp'] = ok
        if not ok:
            r['erro'] = motivo
        if cfg['canal'] == 'whatsapp':
            if ok:
                r['ok'] = True
                return r
            logger.error(f"Avisos: o WhatsApp falhou ({motivo}); vai pelo Telegram.")
            texto = f"⚠️ <i>O WhatsApp não aceitou este aviso ({esc(motivo)}). Enviado aqui para não perder.</i>\n\n" + texto
    r['telegram'] = _enviar_telegram(texto)
    r['ok'] = bool(r['whatsapp']) or r['telegram']
    return r


def enviar(texto):
    """Porta de saída dos avisos da gestão. True se chegou em algum canal."""
    return enviar_detalhado(texto)['ok']


def enviar_arquivo(caminho, nome_arquivo, legenda=''):
    """
    [DANFE] Manda um arquivo (PDF) pelo mesmo canal dos avisos. Se o WhatsApp falhar (só WhatsApp),
    vai pelo Telegram. True se chegou em algum canal.
    """
    cfg = config_avisos()
    whats = None
    if cfg['canal'] in ('whatsapp', 'ambos') and cfg['grupo_id']:
        import notificador_whatsapp
        whats, motivo = notificador_whatsapp.enviar_documento_para_grupo(
            cfg['grupo_id'], caminho, nome_arquivo, notificador_whatsapp.html_para_whatsapp(legenda))
        if whats and cfg['canal'] == 'whatsapp':
            return True
        if not whats:
            logger.error(f"Avisos: o WhatsApp não aceitou o arquivo {nome_arquivo} ({motivo}); vai pelo Telegram.")
    chat = chat_dos_avisos()
    if not chat:
        return bool(whats)
    import notificador_telegram
    resposta = notificador_telegram.enviar_documento(chat, caminho, legenda, parse_mode='HTML')
    return bool(whats) or bool(resposta and resposta.get('ok'))


def _enviar_telegram(texto):
    """Envia em partes (o Telegram recusa mensagens muito grandes). True se tudo foi aceito."""
    chat = chat_dos_avisos()
    if not chat:
        logger.warning("Avisos do estoque: nenhum chat configurado (ESTOQUE_CHAT_ID_AVISOS / GESTOR_GROUP_CHAT_ID).")
        return False
    import notificador_telegram
    partes, atual = [], ""
    for linha in texto.split("\n"):
        if len(atual) + len(linha) + 1 > 3900 and atual:
            partes.append(atual)
            atual = ""
        atual += linha + "\n"
    if atual.strip():
        partes.append(atual)
    tudo_ok = True
    for parte in partes:
        resposta = notificador_telegram.enviar_mensagem(chat, parte)
        if not (resposta and resposta.get('ok')):
            logger.error(f"Avisos do estoque: o Telegram recusou uma parte: {resposta}")
            tudo_ok = False
    return tudo_ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mandar = len(sys.argv) > 1 and sys.argv[1] == 'enviar'
    texto = montar_avisos_diarios()
    print(texto or "Avisos do dia: nada para avisar.")
    resumo, _ = montar_resumo_precos(desde_data=date.today() - timedelta(days=7))
    print()
    print(resumo or "Resumo de preços: nenhum aumento nos últimos 7 dias.")
    if mandar:
        for t in (texto, resumo):
            if t:
                print("Enviado:" if enviar(t) else "FALHOU o envio (veja o log).")

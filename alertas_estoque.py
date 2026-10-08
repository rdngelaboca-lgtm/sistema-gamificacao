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
        if dias is not None and dias <= DIAS_PARA_ACABAR and not i.get('ConsumoNegativo'):
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


def enviar(texto):
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

# ==============================================================================
# == confirmacoes.py - ✅ Confirmar presença (escala e vagas de freelancer) ======
# ==============================================================================
# 1) Confirmação da escala: a mensagem do WhatsApp (📱 Confirmar escala) leva um LINK. Um toque abre
#    uma página com ✅ Confirmo / ❌ Não posso. No painel da Escala aparece ✅ / ❌ / ⏳ ao lado do nome.
# 2) 🙋 Vagas: a gestão cria uma vaga (dia, posição, horário, valor, quantas pessoas) e manda no GRUPO
#    dos freelancers (um link para todos: a pessoa se identifica pelo WhatsApp) e/ou no INDIVIDUAL
#    (cada um com o seu link e o seu nome). Quem confirma entra numa lista; a gestão escolhe e toca em
#    "📌 Colocar na escala" (o valor combinado vira o ajuste do turno). Ao encerrar, quem não foi
#    escolhido recebe um "desta vez não deu".
# Link, e não botão do WhatsApp: pela Z-API o botão não aparece em todo celular; o link sempre funciona.
# As mensagens saem pelo número da LOJA (o mesmo da confirmação de escala). Quem não vai poder vir e quem
# quer uma vaga geram um aviso no grupo da gestão (tipo ✅ Presença e vagas em 📣 Avisos).
# ==============================================================================
import logging
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import config
import database
import escala_regras as R

logger = logging.getLogger(__name__)

PENDENTE, CONFIRMADO, RECUSADO = 'pendente', 'confirmado', 'recusado'
V_ABERTA, V_PREENCHIDA, V_ENCERRADA, V_CANCELADA = 'aberta', 'preenchida', 'encerrada', 'cancelada'
R_CONVIDADO, R_CONFIRMOU, R_RECUSOU, R_ESCALADO, R_DISPENSADO = 'convidado', 'confirmou', 'recusou', 'escalado', 'dispensado'
DIAS_SEMANA_CURTO = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
INTERVALO_ENVIO_SEG = 2.5            # entre uma mensagem individual e outra
MAX_VAGAS = 20
IDENTIFICACOES_POR_IP = (12, 3600)   # link do grupo: no máximo 12 tentativas de WhatsApp por hora no mesmo aparelho
TEXTO_DISPENSA = ("Oi, *{nome}*! 🍦 A vaga de {dia} já foi preenchida. Obrigado pela disponibilidade: "
                  "na próxima a gente chama você!")

SEGUNDO_PLANO = True                 # os testes desligam para conferir as mensagens na hora

_tabelas_ok = False
_trava = threading.Lock()
_ident_por_ip = {}


class ErroPresenca(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def _conexao():
    conn = database.get_db_connection()
    if not conn:
        raise ErroPresenca("Sem conexão com o banco de dados.", 503)
    return conn


def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ConfirmacoesEscala')
            CREATE TABLE ConfirmacoesEscala (
                EscalaID INT NOT NULL PRIMARY KEY,
                Token VARCHAR(24) NOT NULL UNIQUE,
                DataEscala DATE NOT NULL,
                Nome NVARCHAR(150) NULL,
                Telefone VARCHAR(20) NULL,
                Posicao NVARCHAR(100) NULL,
                Entrada VARCHAR(5) NULL,
                Saida VARCHAR(5) NULL,
                Status VARCHAR(12) NOT NULL,
                Motivo NVARCHAR(200) NULL,
                EnviadoEm DATETIME NULL,
                RespondidoEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'VagasFreelancer')
            CREATE TABLE VagasFreelancer (
                VagaID INT IDENTITY(1,1) PRIMARY KEY,
                DataVaga DATE NOT NULL,
                PosicaoID INT NOT NULL,
                Posicao NVARCHAR(100) NULL,
                Entrada VARCHAR(5) NOT NULL,
                Saida VARCHAR(5) NOT NULL,
                Valor DECIMAL(10, 2) NOT NULL,
                ValorCalculado DECIMAL(10, 2) NULL,
                Quantidade INT NOT NULL,
                Observacao NVARCHAR(300) NULL,
                Status VARCHAR(12) NOT NULL,
                TokenGrupo VARCHAR(24) NOT NULL UNIQUE,
                EnviadaGrupoEm DATETIME NULL,
                CriadaEm DATETIME NOT NULL,
                CriadaPor NVARCHAR(150) NULL,
                EncerradaEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'VagaRespostas')
            CREATE TABLE VagaRespostas (
                VagaID INT NOT NULL,
                FreelancerID INT NOT NULL,
                Nome NVARCHAR(150) NULL,
                Telefone VARCHAR(20) NULL,
                Token VARCHAR(24) NOT NULL UNIQUE,
                Status VARCHAR(12) NOT NULL,
                Origem VARCHAR(12) NULL,
                Erro NVARCHAR(150) NULL,
                EnviadoEm DATETIME NULL,
                RespondidoEm DATETIME NULL,
                EscalaID INT NULL,
                PRIMARY KEY (VagaID, FreelancerID)
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ParametrosVagas')
            CREATE TABLE ParametrosVagas (
                Chave VARCHAR(40) NOT NULL PRIMARY KEY,
                Valor NVARCHAR(300) NULL
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def _params():
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Chave, Valor FROM ParametrosVagas")
        return {c: v for c, v in cur.fetchall()}
    finally:
        conn.close()


def _token():
    return secrets.token_urlsafe(9)          # 12 letras: impossível de adivinhar


def _agora():
    return datetime.now().replace(microsecond=0)


def _dt(v):
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return None


def _hm(v):
    return R.formatar_hora_curta(v) if v else ''


def _dia_txt(d):
    d = database._como_data(d)
    return f"{DIAS_SEMANA_CURTO[d.weekday()]} {d:%d/%m}" if d else ''


def _mesmo_telefone(a, b):
    na, nb = R.numero_whatsapp(a), R.numero_whatsapp(b)
    if not na or not nb:
        return False
    # celular com e sem o 9 na frente (55 66 9xxxx-xxxx × 55 66 xxxx-xxxx) é a mesma pessoa
    return na == nb or (na[:4] == nb[:4] and na[-8:] == nb[-8:])


def endereco_publico(host_url):
    """(endereço que vai nos links, True se é só da rede da loja). Usa o endereço da internet gravado em 📢 Clientes."""
    base = ''
    try:
        import clientes
        base = (clientes._params('url_publica').get('url_publica') or '').strip()
    except Exception as e:
        logger.warning(f"Presença: endereço da internet (📢 Clientes) indisponível: {e}")
    base = (base or getattr(config, 'URL_PUBLICA', '') or str(host_url or '')).rstrip('/')
    host = re.sub(r'^https?://', '', base).split('/')[0].split(':')[0]
    local = host in ('localhost', '127.0.0.1') or bool(re.fullmatch(r'[\d.]+', host)) or host.endswith('.local')
    return base, local


def _avisar_gestao(texto):
    """Aviso no grupo da gestão (sem travar quem respondeu). Desliga em 📣 Avisos (✅ Presença e vagas)."""
    def mandar():
        try:
            import alertas_estoque
            if alertas_estoque.aviso_ligado('presenca'):
                alertas_estoque.enviar(texto)
        except Exception as e:
            logger.error(f"Presença: aviso para a gestão falhou: {e}")
    _rodar(mandar)


def _rodar(funcao):
    if SEGUNDO_PLANO:
        threading.Thread(target=funcao, daemon=True).start()
    else:
        funcao()


def _enviar_whatsapp(telefone, texto):
    import notificador_whatsapp
    return notificador_whatsapp.enviar_mensagem_whatsapp(telefone, texto)


def _esc(t):
    import html
    return html.escape(str(t or ''), quote=False)


# ------------------------------------------------------------------------------
# 1) Confirmação da escala
# ------------------------------------------------------------------------------
def preparar_escala(data, lista, host_url, so_internet=False):
    """
    Antes de mandar a 📱 Confirmação de escala: um link para cada turno da lista ({EscalaID: url}).
    O mesmo turno mantém o mesmo link; se a pessoa ou o horário mudou, volta a ⏳ (precisa confirmar de novo).
    so_internet (programa do PC): sem o endereço da internet gravado, não põe link (o do PC não abre no celular).
    """
    garantir_tabelas()
    base, local = endereco_publico(host_url)
    if not base or (so_internet and local):
        return {}
    agora = _agora()
    links = {}
    conn = _conexao()
    try:
        cur = conn.cursor()
        for item in lista:
            eid = item.get('escala_id')
            if not eid:
                continue
            ent, sai = _hm(item['entrada']), _hm(item['saida'])
            cur.execute("SELECT Token, Telefone, Entrada, Saida, Status FROM ConfirmacoesEscala WHERE EscalaID = ?", eid)
            r = cur.fetchone()
            if r:
                token = r[0]
                mudou = not _mesmo_telefone(r[1], item['telefone']) or _hm(r[2]) != ent or _hm(r[3]) != sai
                cur.execute("UPDATE ConfirmacoesEscala SET DataEscala = ?, Nome = ?, Telefone = ?, Posicao = ?, Entrada = ?, "
                            "Saida = ?, EnviadoEm = ?" + (", Status = ?, Motivo = NULL, RespondidoEm = NULL" if mudou else "")
                            + " WHERE EscalaID = ?",
                            *([str(data), item['nome'], item['telefone'], item['posicao'], ent, sai, agora]
                              + ([PENDENTE] if mudou else []) + [eid]))
            else:
                token = _token()
                cur.execute("INSERT INTO ConfirmacoesEscala (EscalaID, Token, DataEscala, Nome, Telefone, Posicao, Entrada, Saida, "
                            "Status, EnviadoEm) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            eid, token, str(data), item['nome'], item['telefone'], item['posicao'], ent, sai, PENDENTE, agora)
            links[eid] = f"{base}/confirmar/{token}"
        conn.commit()
    finally:
        conn.close()
    return links


def _turno_atual(cur, escala_id):
    """(nome, telefone, entrada, saida) do turno como está AGORA na escala, ou None se foi excluído."""
    cur.execute("SELECT ISNULL(F.NomeCompleto, FR.Nome), ISNULL(FR.Telefone, F.TelefoneWhatsApp), E.HorarioEntrada, E.HorarioSaida "
                "FROM EscalaDiaria E LEFT JOIN Funcionarios F ON E.FuncionarioID = F.FuncionarioID "
                "LEFT JOIN Freelancers FR ON E.FreelancerID = FR.FreelancerID WHERE E.EscalaID = ?", escala_id)
    r = cur.fetchone()
    return (r[0], r[1], _hm(r[2]), _hm(r[3])) if r else None


def _conf_por_token(cur, token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,24}', str(token or '')):
        return None
    cur.execute("SELECT EscalaID, DataEscala, Nome, Telefone, Posicao, Entrada, Saida, Status, Motivo, RespondidoEm "
                "FROM ConfirmacoesEscala WHERE Token = ?", token)
    return cur.fetchone()


def ver_confirmacao(token):
    """Para a página do link: o turno e se já respondeu."""
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        r = _conf_por_token(cur, token)
        if not r:
            raise ErroPresenca("Link inválido. Peça um novo para a loja.", 404)
        atual = _turno_atual(cur, r[0])
    finally:
        conn.close()
    eid, d, nome, tel, pos, ent, sai, st, motivo, quando = r
    d, ent, sai = database._como_data(d), _hm(ent), _hm(sai)
    mudou = atual is None or not _mesmo_telefone(atual[1], tel) or atual[2] != ent or atual[3] != sai
    return {'tipo': 'escala', 'nome': (nome or '').split(' ')[0],
            'dia': f"{R.DIAS_SEMANA[d.weekday()]}, {d:%d/%m}", 'posicao': pos or '', 'entrada': ent, 'saida': sai,
            'status': st, 'motivo': motivo or '', 'respondido': _dt(quando).strftime('%d/%m às %H:%M') if quando else '',
            'passou': d < date.today(), 'mudou': mudou}


def responder_confirmacao(token, resposta, motivo=''):
    """✅ Confirmo / ❌ Não posso (dá para mudar de ideia até o dia passar)."""
    if resposta not in ('sim', 'nao'):
        raise ErroPresenca("Escolha ✅ Confirmo ou ❌ Não posso.")
    motivo = re.sub(r'\s+', ' ', str(motivo or '')).strip()[:200]
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        r = _conf_por_token(cur, token)
        if not r:
            raise ErroPresenca("Link inválido. Peça um novo para a loja.", 404)
        eid, d, nome, tel, pos, ent, sai, st_antes = r[:8]
        d, ent, sai = database._como_data(d), _hm(ent), _hm(sai)
        if d < date.today():
            raise ErroPresenca("Essa escala já passou.", 409)
        atual = _turno_atual(cur, eid)
        if atual is None or not _mesmo_telefone(atual[1], tel) or atual[2] != ent or atual[3] != sai:
            raise ErroPresenca("A sua escala mudou depois desta mensagem. Fale com a loja para receber a nova.", 409)
        novo = CONFIRMADO if resposta == 'sim' else RECUSADO
        cur.execute("UPDATE ConfirmacoesEscala SET Status = ?, Motivo = ?, RespondidoEm = ? WHERE EscalaID = ?",
                    novo, (motivo or None) if novo == RECUSADO else None, _agora(), eid)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[PRESENÇA] {nome} {'confirmou' if novo == CONFIRMADO else 'NÃO vai'} ({_dia_txt(d)} {ent}–{sai}).")
    if novo == RECUSADO and st_antes != RECUSADO:
        _avisar_gestao(f"❌ <b>{_esc(nome)} não vai poder vir</b> {_dia_txt(d)} ({ent}–{sai}, {_esc(pos)})"
                       + (f"\nMotivo: {_esc(motivo)}" if motivo else '') + "\n<i>Troque na Gestão › 🗓️ Escala.</i>")
    elif novo == CONFIRMADO and st_antes == RECUSADO:
        _avisar_gestao(f"✅ {_esc(nome)} mudou de ideia: <b>vai vir</b> {_dia_txt(d)} ({ent}–{sai}, {_esc(pos)}).")
    return {'ok': True, 'status': novo}


def status_do_dia(data, turnos):
    """{EscalaID: {'status', 'quando', 'motivo'}} só de quem recebeu o link E continua com a mesma pessoa e horário."""
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT EscalaID, Telefone, Entrada, Saida, Status, Motivo, RespondidoEm FROM ConfirmacoesEscala "
                    "WHERE DataEscala = ?", str(data))
        linhas = {r[0]: r for r in cur.fetchall()}
    finally:
        conn.close()
    saida = {}
    for t in turnos:
        r = linhas.get(t.EscalaID)
        if not r:
            continue
        tel = getattr(t, 'TelefonePessoa', None)
        if not _mesmo_telefone(tel, r[1]) or _hm(t.HorarioEntrada) != _hm(r[2]) or _hm(t.HorarioSaida) != _hm(r[3]):
            continue                          # trocou a pessoa ou o horário: a resposta antiga não vale
        saida[t.EscalaID] = {'status': r[4], 'motivo': r[5] or '',
                             'quando': _dt(r[6]).strftime('%d/%m %H:%M') if r[6] else ''}
    return saida


ICONES = {CONFIRMADO: '✅', RECUSADO: '❌', PENDENTE: '⏳'}


# ------------------------------------------------------------------------------
# 2) 🙋 Vagas para freelancers
# ------------------------------------------------------------------------------
def _cfg_pag():
    try:
        return database.buscar_config_pagamento_freelancer()
    except Exception:
        return dict(database.CONFIG_PAGAMENTO_PADRAO)


def valor_sugerido(data_txt, entrada, saida):
    """A diária que o sistema calcularia para esse horário (longa/curta, semana ou domingo/feriado)."""
    d = database._como_data(data_txt)
    try:
        ent, sai = R.hora_ou_none(entrada), R.hora_ou_none(saida)
    except ValueError:
        ent = sai = None
    if not d or not ent or not sai:
        return None
    calc = database.calcular_pagamento_turno(ent, sai, _cfg_pag(), 0, d, None, ent, sai, database.nome_feriado(d))
    return calc['Total'].quantize(Decimal('0.01')) if calc else None


def previa_vaga(dados):
    v = valor_sugerido(dados.get('data'), dados.get('entrada'), dados.get('saida'))
    return {'valor': float(v) if v is not None else None, 'valor_txt': R.fmt_reais(v) if v is not None else ''}


def _ler_vaga(dados):
    d = database._como_data(dados.get('data'))
    if not d:
        raise ErroPresenca("Escolha o dia da vaga.")
    if d < date.today():
        raise ErroPresenca("Esse dia já passou.")
    try:
        pos_id = int(dados.get('posicao_id'))
    except (TypeError, ValueError):
        raise ErroPresenca("Escolha a posição (onde a pessoa vai trabalhar).")
    posicoes = {p[0]: p[1] for p in database.listar_posicoes_loja()}
    if pos_id not in posicoes:
        raise ErroPresenca("Essa posição não está mais no mapa. Atualize a página.", 409)
    try:
        ent, sai = R.hora_ou_none(dados.get('entrada')), R.hora_ou_none(dados.get('saida'))
    except ValueError as e:
        raise ErroPresenca(str(e))
    if not ent or not sai:
        raise ErroPresenca("Preencha o horário de entrada e de saída.")
    if ent == sai:
        raise ErroPresenca("Entrada e saída não podem ser iguais.")
    try:
        q = dados.get('quantidade')
        qtd = 1 if q is None or str(q).strip() == '' else int(q)
    except (TypeError, ValueError):
        raise ErroPresenca("Quantas pessoas: use um número.")
    if not 1 <= qtd <= MAX_VAGAS:
        raise ErroPresenca(f"Quantas pessoas: de 1 a {MAX_VAGAS}.")
    calc = valor_sugerido(d, ent, sai)
    try:
        valor = R.para_decimal_br(dados.get('valor'), "o valor") if str(dados.get('valor') or '').strip() else calc
    except ValueError as e:
        raise ErroPresenca(str(e))
    if valor is None or valor <= 0:
        raise ErroPresenca("Digite o valor da diária.")
    obs = re.sub(r'\s+', ' ', str(dados.get('observacao') or '')).strip()[:300]
    return d, pos_id, posicoes[pos_id], _hm(ent), _hm(sai), qtd, valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), calc, obs


def criar_vaga(dados, usuario):
    d, pos_id, pos, ent, sai, qtd, valor, calc, obs = _ler_vaga(dados)
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO VagasFreelancer (DataVaga, PosicaoID, Posicao, Entrada, Saida, Valor, ValorCalculado, Quantidade, "
                    "Observacao, Status, TokenGrupo, CriadaEm, CriadaPor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?); "
                    "SELECT SCOPE_IDENTITY();", str(d), pos_id, pos, ent, sai, valor, calc, qtd, obs or None, V_ABERTA,
                    _token(), _agora(), (usuario or {}).get('nome'))
        cur.nextset()
        vid = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[VAGAS] {(usuario or {}).get('nome')}: vaga {vid} {d} {ent}-{sai} {pos} ({qtd}x {valor}).")
    return {'ok': True, 'id': vid}


def _vaga(cur, vid):
    cur.execute("SELECT VagaID, DataVaga, PosicaoID, Posicao, Entrada, Saida, Valor, ValorCalculado, Quantidade, Observacao, "
                "Status, TokenGrupo, EnviadaGrupoEm, CriadaEm, CriadaPor FROM VagasFreelancer WHERE VagaID = ?", vid)
    r = cur.fetchone()
    if not r:
        raise ErroPresenca("Vaga não encontrada. Atualize a página.", 404)
    return {'id': r[0], 'data': database._como_data(r[1]), 'posicao_id': r[2], 'posicao': r[3] or '', 'entrada': _hm(r[4]),
            'saida': _hm(r[5]), 'valor': Decimal(str(r[6])), 'valor_calculado': Decimal(str(r[7])) if r[7] is not None else None,
            'quantidade': r[8], 'observacao': r[9] or '', 'status': r[10], 'token_grupo': r[11], 'enviada_grupo': r[12],
            'criada': r[13], 'criada_por': r[14] or ''}


def _respostas(cur, vid):
    cur.execute("SELECT FreelancerID, Nome, Telefone, Token, Status, Origem, Erro, EnviadoEm, RespondidoEm, EscalaID "
                "FROM VagaRespostas WHERE VagaID = ?", vid)
    return [{'freelancer_id': r[0], 'nome': r[1] or '', 'telefone': r[2] or '', 'token': r[3], 'status': r[4],
             'origem': r[5] or '', 'erro': r[6] or '', 'enviado': _dt(r[7]), 'respondido': _dt(r[8]), 'escala_id': r[9]}
            for r in cur.fetchall()]


def _texto_vaga(v, nome=None, link=''):
    linhas = [f"Oi, *{nome}*! 👋 Temos uma vaga para você:" if nome else "🆕 *Vaga de freelancer no Gela Boca*",
              f"📅 *{R.DIAS_SEMANA[v['data'].weekday()]}, {v['data']:%d/%m}*",
              f"⏰ *{v['entrada']} às {v['saida']}*",
              f"📍 {v['posicao']}",
              f"💰 *{R.fmt_reais(v['valor'])}*"]
    if not nome and v['quantidade'] > 1:
        linhas.append(f"👥 {v['quantidade']} vagas")
    if v['observacao']:
        linhas.append(f"📝 {v['observacao']}")
    linhas += ['', f"👉 *Toque para confirmar:* {link}" if nome else f"👉 *Quer? Toque e confirme:* {link}"]
    return "\n".join(linhas)


def _json_vaga(v, resp):
    conta = lambda *st: sum(1 for x in resp if x['status'] in st)
    ordem = {R_ESCALADO: 0, R_CONFIRMOU: 1, R_RECUSOU: 3, R_DISPENSADO: 4, R_CONVIDADO: 2}
    resp = sorted(resp, key=lambda x: (ordem.get(x['status'], 9), x['respondido'] or datetime.max, x['nome'].lower()))
    return {'id': v['id'], 'data': v['data'].isoformat(), 'dia': _dia_txt(v['data']), 'posicao': v['posicao'],
            'posicao_id': v['posicao_id'], 'entrada': v['entrada'], 'saida': v['saida'], 'valor': float(v['valor']),
            'valor_txt': R.fmt_reais(v['valor']),
            'valor_calculado_txt': R.fmt_reais(v['valor_calculado']) if v['valor_calculado'] is not None else '',
            'quantidade': v['quantidade'], 'observacao': v['observacao'], 'status': v['status'],
            'enviada_grupo': _dt(v['enviada_grupo']).strftime('%d/%m %H:%M') if v['enviada_grupo'] else '',
            'escalados': conta(R_ESCALADO), 'confirmaram': conta(R_CONFIRMOU), 'recusaram': conta(R_RECUSOU),
            'convidados': len(resp),
            'respostas': [{'freelancer_id': x['freelancer_id'], 'nome': x['nome'], 'status': x['status'], 'origem': x['origem'], 'erro': x['erro'],
                           'enviado': x['enviado'].strftime('%d/%m %H:%M') if x['enviado'] else '',
                           'respondido': x['respondido'].strftime('%d/%m %H:%M') if x['respondido'] else ''} for x in resp]}


def listar_vagas(desde=None, host_url=None):
    """Vagas de hoje em diante (e as dos últimos 7 dias), com as respostas."""
    garantir_tabelas()
    desde = database._como_data(desde) or (date.today() - timedelta(days=7))
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT VagaID FROM VagasFreelancer WHERE DataVaga >= ?", str(desde))
        ids = [r[0] for r in cur.fetchall()]
        vagas = [_json_vaga(_vaga(cur, i), _respostas(cur, i)) for i in ids]
    finally:
        conn.close()
    vagas.sort(key=lambda v: (v['status'] not in (V_ABERTA, V_PREENCHIDA), v['data'], v['entrada'], -v['id']))
    p = _params()
    base, local = endereco_publico(host_url)
    return {'vagas': vagas, 'grupo': {'id': p.get('grupo_id') or '', 'nome': p.get('grupo_nome') or ''},
            'link_local': local or not base, 'endereco': base}


def vaga(vid):
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        return _json_vaga(_vaga(cur, int(vid)), _respostas(cur, int(vid)))
    finally:
        conn.close()


def freelancers_para_vaga(data_txt):
    """Freelancers com WhatsApp, avisando quem já está na escala desse dia (e onde)."""
    d = database._como_data(data_txt) or date.today()
    escala = database.buscar_escala_do_dia(d.isoformat())
    ocupado = {}
    for ts in escala.values():
        for t in ts:
            if getattr(t, 'FreelancerID', None):
                ocupado.setdefault(t.FreelancerID, []).append(f"{_hm(t.HorarioEntrada)}–{_hm(t.HorarioSaida)}")
    lista = []
    for f in database.listar_freelancers():
        tel = R.numero_whatsapp(getattr(f, 'Telefone', None))
        lista.append({'id': f.FreelancerID, 'nome': f.Nome, 'whatsapp': bool(tel),
                      'ocupado': ', '.join(ocupado.get(f.FreelancerID, []))})
    lista.sort(key=lambda x: x['nome'].lower())
    return {'freelancers': lista}


def salvar_grupo(dados, usuario):
    gid = str(dados.get('grupo_id') or '').strip()[:120]
    nome = str(dados.get('grupo_nome') or '').strip()[:150]
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM ParametrosVagas WHERE Chave IN ('grupo_id', 'grupo_nome')")
        if gid:
            cur.execute("INSERT INTO ParametrosVagas (Chave, Valor) VALUES ('grupo_id', ?), ('grupo_nome', ?)", gid, nome or gid)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[VAGAS] {(usuario or {}).get('nome')}: grupo dos freelancers = {nome or gid or '(nenhum)'}.")
    return {'ok': True, 'mensagem': f"Grupo dos freelancers: {nome or gid}." if gid else "Grupo dos freelancers removido."}


def enviar_vaga(vid, dados, usuario, host_url):
    """Manda no grupo (um link para todos) e/ou no individual de cada freelancer escolhido (um link para cada)."""
    garantir_tabelas()
    no_grupo = bool(dados.get('grupo'))
    ids = []
    for x in dados.get('freelancers') or []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            raise ErroPresenca("Seleção de freelancers inválida. Atualize a página.")
    ids = list(dict.fromkeys(ids))
    if not no_grupo and not ids:
        raise ErroPresenca("Escolha mandar no grupo e/ou marque os freelancers.")
    base, local = endereco_publico(host_url)
    if local or not base:
        # [DEPURAÇÃO] ia "http://localhost:5000/vaga/…": no celular não abre (o WhatsApp nem deixa clicar)
        raise ErroPresenca(f"O link da vaga ficaria «{base or '(sem endereço)'}», que não abre no celular dos freelancers. "
                           "Grave antes o endereço da internet em 📢 Clientes › ⚙️ Ajustes › QR Code do balcão "
                           "(o mesmo que você usa para abrir o app fora da loja) e mande de novo.", 409)
    p = _params()
    if no_grupo and not p.get('grupo_id'):
        raise ErroPresenca("Escolha antes o grupo dos freelancers (⚙️ na janela de vagas).")
    frees = {f.FreelancerID: f for f in database.listar_freelancers()}
    conn = _conexao()
    try:
        cur = conn.cursor()
        v = _vaga(cur, int(vid))
        if v['status'] not in (V_ABERTA,):
            raise ErroPresenca("Essa vaga não está mais aberta.", 409)
        if v['data'] < date.today():
            raise ErroPresenca("Essa vaga é de um dia que já passou.", 409)
        ja = {x['freelancer_id']: x for x in _respostas(cur, v['id'])}
        individuais = []
        for fid in ids:
            f = frees.get(fid)
            if not f:
                raise ErroPresenca("Um dos freelancers não existe mais. Atualize a página.", 409)
            tel = R.numero_whatsapp(getattr(f, 'Telefone', None))
            if not tel:
                continue
            if fid in ja:
                token = ja[fid]['token']
                if ja[fid]['status'] in (R_ESCALADO, R_CONFIRMOU, R_RECUSOU):
                    continue                  # já respondeu: não incomoda de novo
            else:
                token = _token()
                cur.execute("INSERT INTO VagaRespostas (VagaID, FreelancerID, Nome, Telefone, Token, Status, Origem) "
                            "VALUES (?, ?, ?, ?, ?, ?, 'individual')", v['id'], fid, f.Nome, tel, token, R_CONVIDADO)
            individuais.append((fid, f.Nome, tel, f"{base}/vaga/{token}"))
        conn.commit()
    finally:
        conn.close()

    erro_grupo = None
    if no_grupo:                             # o grupo vai na hora (uma mensagem só): se falhar, a tela fica sabendo
        import notificador_whatsapp
        ok, motivo = notificador_whatsapp.enviar_para_grupo(p['grupo_id'], _texto_vaga(v, link=f"{base}/vaga/{v['token_grupo']}"))
        if ok:
            c = _conexao()
            try:
                c.cursor().execute("UPDATE VagasFreelancer SET EnviadaGrupoEm = ? WHERE VagaID = ?", _agora(), v['id'])
                c.commit()
            finally:
                c.close()
        else:
            erro_grupo = str(motivo)[:150]
            logger.error(f"[VAGAS] Vaga {v['id']}: o grupo não recebeu ({erro_grupo}).")
            if not individuais:
                raise ErroPresenca(f"O grupo não recebeu a vaga: {erro_grupo}", 502)

    def mandar():
        for i, (fid, nome, tel, link) in enumerate(individuais):
            if i:
                time.sleep(INTERVALO_ENVIO_SEG)
            try:
                ok, resp = _enviar_whatsapp(tel, _texto_vaga(v, nome=(nome or '').split(' ')[0], link=link))
            except Exception as e:
                ok, resp = False, str(e)
            c = _conexao()
            try:
                cc = c.cursor()
                cc.execute("UPDATE VagaRespostas SET EnviadoEm = ?, Erro = ? WHERE VagaID = ? AND FreelancerID = ?",
                           _agora() if ok else None, None if ok else str(resp)[:150], v['id'], fid)
                c.commit()
            finally:
                c.close()
    if individuais:
        _rodar(mandar)
    partes = (["no grupo " + (p.get('grupo_nome') or '')] if no_grupo and not erro_grupo else []) + \
             ([f"{len(individuais)} no individual"] if individuais else [])
    logger.info(f"[VAGAS] {(usuario or {}).get('nome')}: vaga {v['id']} enviada ({', '.join(partes) or 'ninguém novo'}).")
    if erro_grupo:
        return {'ok': True, 'aviso': True, 'mensagem': f"⚠️ O grupo NÃO recebeu ({erro_grupo}). Enviando {len(individuais)} no individual."}
    if not partes:
        return {'ok': True, 'mensagem': "Ninguém novo para mandar: os marcados já responderam ou não têm WhatsApp."}
    return {'ok': True, 'mensagem': "Vaga enviada " + " e ".join(partes) + "."}


def _resposta_por_token(cur, token):
    """('individual', vaga, resposta) ou ('grupo', vaga, None)."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,24}', str(token or '')):
        raise ErroPresenca("Link inválido. Peça um novo para a loja.", 404)
    cur.execute("SELECT VagaID, FreelancerID FROM VagaRespostas WHERE Token = ?", token)
    r = cur.fetchone()
    if r:
        resp = next(x for x in _respostas(cur, r[0]) if x['freelancer_id'] == r[1])
        return 'individual', _vaga(cur, r[0]), resp
    cur.execute("SELECT VagaID FROM VagasFreelancer WHERE TokenGrupo = ?", token)
    r = cur.fetchone()
    if not r:
        raise ErroPresenca("Link inválido. Peça um novo para a loja.", 404)
    return 'grupo', _vaga(cur, r[0]), None


def _vaga_publica(v, resp, tipo):
    fechada = v['status'] != V_ABERTA or v['data'] < date.today()
    return {'tipo': 'vaga', 'link': tipo, 'nome': (resp['nome'].split(' ')[0] if resp else ''),
            'dia': f"{R.DIAS_SEMANA[v['data'].weekday()]}, {v['data']:%d/%m}", 'posicao': v['posicao'],
            'entrada': v['entrada'], 'saida': v['saida'], 'valor_txt': R.fmt_reais(v['valor']), 'observacao': v['observacao'],
            'status': resp['status'] if resp else '', 'fechada': fechada,
            'fechada_txt': ("Essa vaga já foi preenchida." if v['status'] in (V_PREENCHIDA, V_ENCERRADA)
                            else "Essa vaga foi cancelada." if v['status'] == V_CANCELADA else "Essa vaga já passou.")
            if fechada else ''}


def ver_vaga(token):
    garantir_tabelas()
    conn = _conexao()
    try:
        tipo, v, resp = _resposta_por_token(conn.cursor(), token)
    finally:
        conn.close()
    return _vaga_publica(v, resp, tipo)


def _limite_ip(ip):
    agora = time.time()
    with _trava:
        tent = [t for t in _ident_por_ip.get(ip, []) if agora - t < IDENTIFICACOES_POR_IP[1]]
        if len(tent) >= IDENTIFICACOES_POR_IP[0]:
            _ident_por_ip[ip] = tent
            return False
        tent.append(agora)
        _ident_por_ip[ip] = tent
        if len(_ident_por_ip) > 5000:
            _ident_por_ip.clear()
        return True


def responder_vaga(token, resposta, telefone=None, ip=None):
    """✅ Quero a vaga / ❌ Não posso. Pelo link do grupo, a pessoa se identifica pelo WhatsApp do cadastro."""
    if resposta not in ('sim', 'nao'):
        raise ErroPresenca("Escolha ✅ Quero a vaga ou ❌ Não posso.")
    garantir_tabelas()
    agora = _agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        tipo, v, resp = _resposta_por_token(cur, token)
        pub = _vaga_publica(v, resp, tipo)
        if pub['fechada']:
            raise ErroPresenca(pub['fechada_txt'], 409)
        if tipo == 'grupo':
            if not R.numero_whatsapp(telefone):
                raise ErroPresenca("Digite o seu WhatsApp com o DDD (o mesmo do cadastro de freelancer).")
            if not _limite_ip(ip or '?'):
                raise ErroPresenca("Muitas tentativas. Espere um pouco ou fale com a loja.", 429)
            f = next((f for f in database.listar_freelancers() if _mesmo_telefone(getattr(f, 'Telefone', None), telefone)), None)
            if not f:
                raise ErroPresenca("Não encontrei esse WhatsApp no cadastro de freelancers. Fale com a loja.", 404)
            resp = next((x for x in _respostas(cur, v['id']) if x['freelancer_id'] == f.FreelancerID), None)
            if not resp:
                cur.execute("INSERT INTO VagaRespostas (VagaID, FreelancerID, Nome, Telefone, Token, Status, Origem) "
                            "VALUES (?, ?, ?, ?, ?, ?, 'grupo')", v['id'], f.FreelancerID, f.Nome,
                            R.numero_whatsapp(f.Telefone), _token(), R_CONVIDADO)
                resp = {'freelancer_id': f.FreelancerID, 'nome': f.Nome, 'status': R_CONVIDADO}
        if resp['status'] in (R_ESCALADO, R_DISPENSADO):
            raise ErroPresenca("Você já está na escala dessa vaga. 👍" if resp['status'] == R_ESCALADO
                               else "Essa vaga já foi preenchida. Obrigado!", 409)
        novo = R_CONFIRMOU if resposta == 'sim' else R_RECUSOU
        cur.execute("UPDATE VagaRespostas SET Status = ?, RespondidoEm = ? WHERE VagaID = ? AND FreelancerID = ?",
                    novo, agora, v['id'], resp['freelancer_id'])
        conn.commit()
        antes = resp['status']
    finally:
        conn.close()
    logger.info(f"[VAGAS] {resp['nome']} {'QUER' if novo == R_CONFIRMOU else 'não quer'} a vaga {v['id']}.")
    if novo == R_CONFIRMOU and antes != R_CONFIRMOU:
        _avisar_gestao(f"🙋 <b>{_esc(resp['nome'])} quer a vaga</b> de {_dia_txt(v['data'])} ({v['entrada']}–{v['saida']}, "
                       f"{_esc(v['posicao'])}, {R.fmt_reais(v['valor'])})\n<i>Escolha em Gestão › 🗓️ Escala › 🙋 Vagas.</i>")
    return {'ok': True, 'status': novo, 'nome': resp['nome'].split(' ')[0]}


def colocar_na_escala(vid, freelancer_id, dados, usuario):
    """📌 A gestão escolheu: o freelancer entra na escala (mesmo dia, posição e horário) e recebe a confirmação."""
    import gestao_escala
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        v = _vaga(cur, int(vid))
        resp = next((x for x in _respostas(cur, v['id']) if x['freelancer_id'] == int(freelancer_id)), None)
    finally:
        conn.close()
    if not resp:
        raise ErroPresenca("Esse freelancer não respondeu a vaga. Atualize a página.", 409)
    if resp['status'] == R_ESCALADO:
        raise ErroPresenca(f"{resp['nome']} já está na escala dessa vaga.", 409)
    if v['status'] == V_CANCELADA:
        raise ErroPresenca("Essa vaga foi cancelada.", 409)
    pos_id, pos_nome, trocou = _posicao_livre(v, dados.get('posicao_id'))
    if pos_id is None:                       # a posição da vaga (e as do mesmo setor) já tem gente: a gestão escolhe outra
        if not pos_nome:
            raise ErroPresenca(f"Nenhuma posição está livre das {v['entrada']} às {v['saida']}. Mude a escala antes.", 409)
        return {'posicoes': pos_nome, 'mensagem': f"{v['posicao']} já tem gente das {v['entrada']} às {v['saida']}. "
                                                  f"Em qual posição fica {resp['nome']}?"}
    try:
        r = gestao_escala.salvar_turno({'data': v['data'].isoformat(), 'posicao_id': pos_id,
                                        'pessoa': f"free:{resp['freelancer_id']}", 'entrada': v['entrada'], 'saida': v['saida'],
                                        'confirmar': dados.get('confirmar') or []}, usuario)
    except gestao_escala.ErroEscala as e:
        raise ErroPresenca(str(e), getattr(e, 'status', 409) or 409)
    if r.get('perguntas'):
        return r
    eid = next((t.EscalaID for t in database.buscar_escala_do_dia(v['data'].isoformat()).get(pos_id, [])
                if getattr(t, 'FreelancerID', None) == resp['freelancer_id'] and _hm(t.HorarioEntrada) == v['entrada']), None)
    agora = _agora()
    extra = f" Em {pos_nome}: {v['posicao']} já estava ocupada nesse horário." if trocou else ''
    if eid and v['valor_calculado'] is not None and v['valor'] != v['valor_calculado']:
        ajuste = v['valor'] - v['valor_calculado']          # o valor combinado na vaga vale nos 💰 Pagamentos
        ok, msg = database.salvar_correcao_pagamento(eid, None, None, ajuste, f"Vaga: valor combinado {R.fmt_reais(v['valor'])}", None)
        extra += (f" Valor combinado {R.fmt_reais(v['valor'])} (ajuste {'+' if ajuste > 0 else ''}{R.fmt_reais(ajuste)})."
                  if ok else f" ⚠️ O valor combinado não foi gravado ({msg}): confira em 💰 Pagamentos.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE VagaRespostas SET Status = ?, EscalaID = ? WHERE VagaID = ? AND FreelancerID = ?",
                    R_ESCALADO, eid, v['id'], resp['freelancer_id'])
        if eid:                                               # já disse que vem: entra ✅ no painel
            cur.execute("DELETE FROM ConfirmacoesEscala WHERE EscalaID = ?", eid)
            cur.execute("INSERT INTO ConfirmacoesEscala (EscalaID, Token, DataEscala, Nome, Telefone, Posicao, Entrada, Saida, Status, "
                        "EnviadoEm, RespondidoEm) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", eid, _token(), v['data'].isoformat(),
                        resp['nome'], resp['telefone'], pos_nome, v['entrada'], v['saida'], CONFIRMADO, agora,
                        resp['respondido'] or agora)
        todas = _respostas(cur, v['id'])
        escalados = sum(1 for x in todas if x['status'] == R_ESCALADO)
        sobram = sum(1 for x in todas if x['status'] == R_CONFIRMOU)
        preenchida = escalados >= v['quantidade']
        if preenchida and v['status'] == V_ABERTA:
            cur.execute("UPDATE VagasFreelancer SET Status = ? WHERE VagaID = ?", V_PREENCHIDA, v['id'])
        conn.commit()
    finally:
        conn.close()
    if resp['telefone']:
        texto = (f"✅ Oi, *{resp['nome'].split(' ')[0]}*! Você está na escala do Gela Boca:\n"
                 f"📅 *{R.DIAS_SEMANA[v['data'].weekday()]}, {v['data']:%d/%m}*\n⏰ *{v['entrada']} às {v['saida']}*\n"
                 f"📍 {pos_nome}\n💰 {R.fmt_reais(v['valor'])}\n\nTe esperamos! 🍦")
        _rodar(lambda: _enviar_whatsapp(resp['telefone'], texto))
    logger.info(f"[VAGAS] {(usuario or {}).get('nome')}: {resp['nome']} na escala pela vaga {v['id']}.")
    return {'ok': True, 'preenchida': preenchida,
            'mensagem': f"{resp['nome']} está na escala ({v['entrada']}–{v['saida']}) e recebeu a confirmação.{extra}"
                        + ((f" Vaga preenchida: toque em ✔️ Encerrar para avisar {sobram} que também quis(eram)." if sobram
                            else " Vaga preenchida.") if preenchida else '')}


def _posicao_livre(v, pedida=None):
    """
    (PosicaoID, nome, trocou): numa posição só cabe uma pessoa por horário. Vaga para 2+ pessoas (ou posição já
    ocupada): vai para outra posição LIVRE do mesmo setor (Caixa 1 → Caixa 2). Sem nenhuma livre no setor:
    (None, [posições livres de qualquer setor], True) e a gestão escolhe.
    """
    posicoes = database.listar_posicoes_loja()
    nomes = {p[0]: p[1] for p in posicoes}
    try:
        pedida = int(pedida) if pedida else None
    except (TypeError, ValueError):
        pedida = None
    if pedida in nomes:
        return pedida, nomes[pedida], pedida != v['posicao_id']
    escala = database.buscar_escala_do_dia(v['data'].isoformat())
    setor = next((p[5] for p in posicoes if p[0] == v['posicao_id']), None)
    candidatas = [v['posicao_id']] + [p[0] for p in posicoes if setor and p[5] == setor and p[0] != v['posicao_id']]
    for pid in candidatas:
        if pid in nomes and not R.conflito_na_posicao(escala, pid, None, v['entrada'], v['saida']):
            return pid, nomes[pid], pid != v['posicao_id']
    livres = [{'id': p[0], 'nome': p[1], 'setor': p[5] or ''} for p in posicoes
              if not R.conflito_na_posicao(escala, p[0], None, v['entrada'], v['saida'])]
    return None, livres, True


def encerrar_vaga(vid, dados, usuario):
    """Encerra (ou cancela) a vaga; quem confirmou e não foi escolhido recebe um "desta vez não deu" (se marcado)."""
    cancelar = bool(dados.get('cancelar'))
    avisar = dados.get('avisar', True)
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        v = _vaga(cur, int(vid))
        if v['status'] in (V_ENCERRADA, V_CANCELADA):
            raise ErroPresenca("Essa vaga já foi encerrada.", 409)
        sobram = [x for x in _respostas(cur, v['id']) if x['status'] == R_CONFIRMOU]
        cur.execute("UPDATE VagaRespostas SET Status = ? WHERE VagaID = ? AND Status = ?", R_DISPENSADO, v['id'], R_CONFIRMOU)
        cur.execute("UPDATE VagasFreelancer SET Status = ?, EncerradaEm = ? WHERE VagaID = ?",
                    V_CANCELADA if cancelar else V_ENCERRADA, _agora(), v['id'])
        conn.commit()
    finally:
        conn.close()
    avisados = [x for x in sobram if x['telefone']] if avisar else []

    def mandar():
        for i, x in enumerate(avisados):
            if i:
                time.sleep(INTERVALO_ENVIO_SEG)
            texto = TEXTO_DISPENSA.format(nome=x['nome'].split(' ')[0], dia=_dia_txt(v['data']))
            if cancelar:
                texto = (f"Oi, *{x['nome'].split(' ')[0]}*! A vaga de {_dia_txt(v['data'])} ({v['entrada']}–{v['saida']}) "
                         "foi cancelada. Obrigado pela disponibilidade! 🍦")
            try:
                _enviar_whatsapp(x['telefone'], texto)
            except Exception as e:
                logger.error(f"[VAGAS] Aviso para {x['nome']} falhou: {e}")
    if avisados:
        _rodar(mandar)
    logger.info(f"[VAGAS] {(usuario or {}).get('nome')}: vaga {v['id']} {'cancelada' if cancelar else 'encerrada'} "
                f"({len(avisados)} avisado(s)).")
    return {'ok': True, 'mensagem': f"Vaga {'cancelada' if cancelar else 'encerrada'}."
                                    + (f" {len(avisados)} freelancer(s) avisado(s) de que não foram escolhidos." if avisados else '')}

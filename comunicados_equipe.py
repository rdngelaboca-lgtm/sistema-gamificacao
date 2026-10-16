# ==============================================================================
# == comunicados_equipe.py - 📨 Comunicados para a equipe (fixos e freelancers) ==
# ==============================================================================
# A gestão escreve um comunicado na Gestão Web (📨 Comunicados) e escolhe quem recebe (fixos e/ou
# freelancers). Cada pessoa recebe no WhatsApp (número da LOJA) SÓ DURANTE O TURNO DELA, pela escala
# do dia: quem está de folga (ou sem turno) recebe no próximo turno. Fora do turno o comunicado fica
# guardado ("⏳ espera o turno").
# No WhatsApp vai SÓ uma chamada curta ("Segue comunicado sobre…") e um LINK: o comunicado em si a pessoa
# lê ao abrir o link, que tem o botão "✅ Li e estou ciente". O painel mostra quem leu (e quando), quem
# abriu, quem recebeu e ainda não abriu e quem espera o turno.
# Link, e não as ✔✔ azuis do WhatsApp: a pessoa pode desligar a confirmação de leitura do WhatsApp,
# e o link é uma confirmação de verdade ("li e estou ciente").
# O robô (agendador) confere a cada 2 minutos quem está trabalhando agora.
# Não mexe nos comunicados antigos do Telegram (Painel do Gestor): são outra tabela.
# ==============================================================================
import logging
import secrets
import threading
import time
from datetime import date, datetime, timedelta

import config
import database
import escala_regras as R

logger = logging.getLogger(__name__)

# situação de cada pessoa num comunicado
ST_AGUARDANDO, ST_ENVIANDO, ST_ENVIADO, ST_LIDO = 'aguardando', 'enviando', 'enviado', 'lido'
ST_FALHOU, ST_EXPIRADO, ST_SEM_TEL, ST_ENCERRADO = 'falhou', 'expirado', 'sem_telefone', 'encerrado'
TIPOS = {'func': 'Fixo', 'free': 'Freelancer'}

MARGEM_INICIO_MIN = 5          # manda 5 min depois da entrada (a pessoa já chegou)
MARGEM_FIM_MIN = 10            # e não nos últimos 10 min do turno (está indo embora)
VALIDADE_PADRAO_DIAS = 7       # quem não trabalhar nesse tempo: ⌛ expirou
VALIDADE_MAX_DIAS = 60
DIAS_ATIVO = 30                # "pessoa ativa": tem turno na escala de 30 dias atrás a 30 dias para frente
MAX_TENTATIVAS = 3             # WhatsApp falhou: tenta de novo na próxima rodada (até 3 vezes)
ENVIANDO_PRESO_MIN = 30        # 'enviando' há mais que isso (robô caiu no meio): volta para a fila
INTERVALO_ENVIO_SEG = 2.5      # entre uma mensagem e outra (o WhatsApp não gosta de rajada)
LIMITE_TITULO, LIMITE_TEXTO, LIMITE_CHAMADA = 120, 2000, 200

SEGUNDO_PLANO = True           # os testes desligam para conferir na hora

_tabelas_ok = False
_trava = threading.Lock()


class ErroComunicado(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def _conexao():
    conn = database.get_db_connection()
    if not conn:
        raise ErroComunicado("Sem conexão com o banco de dados.", 503)
    return conn


def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ComunicadosEquipe')
            CREATE TABLE ComunicadosEquipe (
                ComunicadoID INT IDENTITY(1,1) PRIMARY KEY,
                Titulo NVARCHAR(150) NOT NULL,
                Texto NVARCHAR(2500) NOT NULL,
                ValidoAte DATE NOT NULL,
                Pontos INT NOT NULL DEFAULT 0,
                CriadoPor NVARCHAR(150) NULL,
                CriadoEm DATETIME NOT NULL,
                EncerradoEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ComunicadosEquipeDestinos')
            CREATE TABLE ComunicadosEquipeDestinos (
                DestinoID INT IDENTITY(1,1) PRIMARY KEY,
                ComunicadoID INT NOT NULL,
                Tipo VARCHAR(4) NOT NULL,
                PessoaID INT NOT NULL,
                Nome NVARCHAR(150) NULL,
                Telefone VARCHAR(30) NULL,
                Token VARCHAR(24) NOT NULL UNIQUE,
                Status VARCHAR(14) NOT NULL,
                Tentativas INT NOT NULL DEFAULT 0,
                Lembretes INT NOT NULL DEFAULT 0,
                EnviadoEm DATETIME NULL,
                AbertoEm DATETIME NULL,
                LidoEm DATETIME NULL,
                Erro NVARCHAR(300) NULL
            )
        """)
        # a chamada curta que vai no WhatsApp (o texto completo fica no link)
        cur.execute("IF COL_LENGTH('ComunicadosEquipe', 'Chamada') IS NULL ALTER TABLE ComunicadosEquipe ADD Chamada NVARCHAR(300) NULL")
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def _token():
    return secrets.token_urlsafe(9)


def _agora():
    return datetime.now().replace(microsecond=0)


def _dt(v):
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return None


def _quando(v):
    """'sex 16/10 14:05' (para o painel)."""
    v = _dt(v)
    return f"{R.DIAS_CURTOS[v.weekday()]} {v:%d/%m %H:%M}" if v else ''


def _empresa():
    return getattr(config, 'NOME_EMPRESA', '') or 'Gela Boca'


def _endereco():
    """(base dos links, só da rede da loja?) — o mesmo endereço da internet da ✅ presença (📢 Clientes)."""
    import confirmacoes
    return confirmacoes.endereco_publico(None)


# ------------------------------------------------------------------------------
# Escala: quem está trabalhando agora e quando é o próximo turno de cada um
# ------------------------------------------------------------------------------
def _turnos(de, ate):
    """Turnos da escala (com pessoa e horário) entre duas datas: [{'chave', 'inicio', 'fim', 'intervalo'}]."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT DataEscala, FuncionarioID, FreelancerID, HorarioEntrada, HorarioSaida, InicioIntervalo, FimIntervalo
                       FROM EscalaDiaria WHERE DataEscala >= ? AND DataEscala <= ?""", str(de), str(ate))
        linhas = cur.fetchall()
    finally:
        conn.close()
    turnos = []
    for d, fid, frid, ent, sai, ini, fim in linhas:
        chave = ('func', int(fid)) if fid else (('free', int(frid)) if frid else None)
        dia, h_ent, h_sai = database._como_data(d), R.parse_horario(ent), R.parse_horario(sai)
        if not (chave and dia and h_ent and h_sai):
            continue
        inicio, fim_t = datetime.combine(dia, h_ent), datetime.combine(dia, h_sai)
        if fim_t <= inicio:
            fim_t += timedelta(days=1)                 # turno que vira a meia-noite
        intervalo = None
        h_ini, h_fim = R.parse_horario(ini), R.parse_horario(fim)
        if h_ini and h_fim:
            a = datetime.combine(dia, h_ini)
            if a < inicio:
                a += timedelta(days=1)
            b = datetime.combine(a.date(), h_fim)
            if b <= a:
                b += timedelta(days=1)
            intervalo = (a, b)
        turnos.append({'chave': chave, 'inicio': inicio, 'fim': fim_t, 'intervalo': intervalo})
    return turnos


def _pode_receber(t, agora):
    """No turno (5 min depois de chegar, até 10 min antes de sair) e fora do intervalo."""
    if not (t['inicio'] + timedelta(minutes=MARGEM_INICIO_MIN) <= agora < t['fim'] - timedelta(minutes=MARGEM_FIM_MIN)):
        return False
    return not (t['intervalo'] and t['intervalo'][0] <= agora < t['intervalo'][1])


def _quem_trabalha_agora(agora):
    ontem = agora.date() - timedelta(days=1)       # turno de ontem que vira a meia-noite
    return {t['chave'] for t in _turnos(ontem, agora.date()) if _pode_receber(t, agora)}


def _proximos_turnos(agora, dias=VALIDADE_MAX_DIAS):
    """{chave: início do turno atual (se ainda vai receber) ou do próximo}."""
    prox = {}
    for t in _turnos(agora.date() - timedelta(days=1), agora.date() + timedelta(days=dias)):
        if t['fim'] - timedelta(minutes=MARGEM_FIM_MIN) <= agora:
            continue
        quando = max(t['inicio'], agora)
        if t['chave'] not in prox or quando < prox[t['chave']]:
            prox[t['chave']] = quando
    return prox


# ------------------------------------------------------------------------------
# Quem pode receber
# ------------------------------------------------------------------------------
def pessoas(agora=None):
    """
    Fixos (funcionários) e freelancers para escolher. 'ativo' = tem turno na escala de 30 dias atrás até
    30 dias para frente (os outros ficam escondidos na lista, mas dá para escolher). Sem telefone: não recebe.
    """
    garantir_tabelas()
    agora = agora or _agora()
    recentes = {t['chave'] for t in _turnos(agora.date() - timedelta(days=DIAS_ATIVO), agora.date() + timedelta(days=DIAS_ATIVO))}
    prox = _proximos_turnos(agora)
    agora_set = _quem_trabalha_agora(agora)
    lista = []
    for f in database.listar_funcionarios():
        lista.append(('func', f.FuncionarioID, f.NomeCompleto, getattr(f, 'TelefoneWhatsApp', None)))
    for f in database.listar_freelancers():
        lista.append(('free', f.FreelancerID, f.Nome, getattr(f, 'Telefone', None)))
    saida = []
    for tipo, pid, nome, tel in lista:
        chave = (tipo, int(pid))
        p = prox.get(chave)
        saida.append({'id': f"{tipo}:{pid}", 'tipo': tipo, 'tipo_nome': TIPOS[tipo], 'nome': nome or '?',
                      'whatsapp': bool(R.numero_whatsapp(tel)), 'ativo': chave in recentes,
                      'agora': chave in agora_set, 'proximo': _quando(p) if p and chave not in agora_set else ''})
    saida.sort(key=lambda x: (x['tipo'] != 'func', (x['nome'] or '').lower()))
    return {'pessoas': saida, 'empresa': _empresa(), 'validade_padrao': (agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)).isoformat(),
            'validade_max': (agora.date() + timedelta(days=VALIDADE_MAX_DIAS)).isoformat(), 'link_local': _endereco()[1]}


# ------------------------------------------------------------------------------
# Criar e mandar
# ------------------------------------------------------------------------------
def _primeiro_nome(nome):
    p = (nome or '').split()
    return (p[0].capitalize() if p[0].isupper() or p[0].islower() else p[0]) if p else ''


def chamada_ou_padrao(titulo, chamada):
    """A frase do WhatsApp. Em branco: 'Tem um comunicado novo para você: *título*.'"""
    chamada = ' '.join(str(chamada or '').split())
    return chamada[0].upper() + chamada[1:] if chamada else f"Tem um comunicado novo para você: *{titulo}*."


def texto_mensagem(titulo, chamada, link, nome='', lembrete=False):
    """Só a chamada e o link: o comunicado em si a pessoa lê (e confirma) no link."""
    primeiro = _primeiro_nome(nome)
    return ((f"🔔 *Lembrete:* você ainda não confirmou a leitura deste comunicado.\n\n" if lembrete else "")
            + f"📢 *Comunicado — {_empresa()}*\n\n"
            + (f"Olá, {primeiro}!\n" if primeiro else "Olá!\n") + f"{chamada_ou_padrao(titulo, chamada)}\n\n"
            + f"👉 *Toque no link para ler o comunicado e confirmar a leitura:*\n{link}")


def _ler_dados(dados, agora):
    titulo = ' '.join(str(dados.get('titulo') or '').split())
    chamada = ' '.join(str(dados.get('chamada') or '').split())
    texto = str(dados.get('texto') or '').strip()
    if not titulo:
        raise ErroComunicado("Escreva o título do comunicado.")
    if len(titulo) > LIMITE_TITULO:
        raise ErroComunicado(f"Título grande demais (máximo {LIMITE_TITULO} letras).")
    if len(chamada) > LIMITE_CHAMADA:
        raise ErroComunicado(f"A chamada do WhatsApp é grande demais (máximo {LIMITE_CHAMADA} letras): o texto completo vai no link.")
    if not texto:
        raise ErroComunicado("Escreva o texto do comunicado.")
    if len(texto) > LIMITE_TEXTO:
        raise ErroComunicado(f"Texto grande demais (máximo {LIMITE_TEXTO} letras).")
    try:
        valido = date.fromisoformat(str(dados.get('valido_ate') or '')) if dados.get('valido_ate') else \
            agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)
    except ValueError:
        raise ErroComunicado("Data de validade inválida.")
    if valido < agora.date() or valido > agora.date() + timedelta(days=VALIDADE_MAX_DIAS):
        raise ErroComunicado(f"A validade vai de hoje até {VALIDADE_MAX_DIAS} dias para frente.")
    try:
        pontos = int(dados.get('pontos') or 0)
    except (TypeError, ValueError):
        raise ErroComunicado("Pontos inválidos.")
    if not 0 <= pontos <= 100:
        raise ErroComunicado("Os pontos vão de 0 a 100.")
    ids = dados.get('pessoas') or []
    if not isinstance(ids, list) or not ids:
        raise ErroComunicado("Escolha quem vai receber.")
    escolhidos = []
    for i in ids:
        tipo, _, pid = str(i).partition(':')
        if tipo not in TIPOS or not pid.isdigit():
            raise ErroComunicado("Pessoa inválida na lista. Atualize a página.")
        if (tipo, int(pid)) not in escolhidos:
            escolhidos.append((tipo, int(pid)))
    if len(escolhidos) > 500:
        raise ErroComunicado("Gente demais num comunicado só.")
    return titulo, chamada, texto, valido, pontos, escolhidos


def criar(dados, usuario, agora=None):
    """Grava o comunicado e uma linha por pessoa; quem já está no turno recebe na hora (em segundo plano)."""
    garantir_tabelas()
    agora = agora or _agora()
    titulo, chamada, texto, valido, pontos, escolhidos = _ler_dados(dados, agora)
    base, local = _endereco()
    if not base or local:
        raise ErroComunicado("Falta o endereço da internet (📢 Clientes › ⚙️ Ajustes › QR do balcão): sem ele o link de "
                             "confirmação de leitura não abre no celular.", 409)
    cadastro = {('func', f.FuncionarioID): (f.NomeCompleto, getattr(f, 'TelefoneWhatsApp', None)) for f in database.listar_funcionarios()}
    cadastro.update({('free', f.FreelancerID): (f.Nome, getattr(f, 'Telefone', None)) for f in database.listar_freelancers()})
    faltam = [c for c in escolhidos if c not in cadastro]
    if faltam:
        raise ErroComunicado("Alguém da lista não está mais no cadastro. Atualize a página.", 409)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO ComunicadosEquipe (Titulo, Chamada, Texto, ValidoAte, Pontos, CriadoPor, CriadoEm)
                       VALUES (?, ?, ?, ?, ?, ?, ?); SELECT SCOPE_IDENTITY();""",
                    titulo, chamada or None, texto, valido, pontos, usuario.get('nome'), agora)
        cur.nextset()
        cid = int(cur.fetchone()[0])
        for tipo, pid in escolhidos:
            nome, tel = cadastro[(tipo, pid)]
            cur.execute("""INSERT INTO ComunicadosEquipeDestinos (ComunicadoID, Tipo, PessoaID, Nome, Telefone, Token, Status)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        cid, tipo, pid, nome, tel, _token(), ST_AGUARDANDO if R.numero_whatsapp(tel) else ST_SEM_TEL)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"[COMUNICADOS] {usuario.get('nome')} criou o comunicado {cid} ('{titulo}') para {len(escolhidos)} pessoa(s).")
    agora_set = _quem_trabalha_agora(agora)
    ja = [c for c in escolhidos if c in agora_set and R.numero_whatsapp(cadastro[c][1])]
    _rodar(lambda: processar(agora=agora, comunicado_id=cid))
    sem_tel = sum(1 for c in escolhidos if not R.numero_whatsapp(cadastro[c][1]))
    depois = len(escolhidos) - len(ja) - sem_tel
    partes = [f"📨 Comunicado criado para {len(escolhidos)} pessoa(s)."]
    if ja:
        partes.append(f"{len(ja)} está(ão) no turno agora: recebe(m) em instantes.")
    if depois:
        partes.append(f"{depois} recebe(m) no próximo turno.")
    if sem_tel:
        partes.append(f"📵 {sem_tel} sem WhatsApp no cadastro.")
    return {'ok': True, 'id': cid, 'mensagem': ' '.join(partes)}


def _rodar(funcao):
    if SEGUNDO_PLANO:
        threading.Thread(target=funcao, daemon=True).start()
    else:
        funcao()


def processar(agora=None, comunicado_id=None, forcar_ids=None):
    """
    Uma rodada (o robô chama a cada 2 minutos): expira o que passou da validade, devolve à fila o que ficou
    preso, e manda para quem está no turno agora. forcar_ids: [DestinoID] para mandar já, sem olhar o turno.
    Devolve quantas mensagens saíram.
    """
    garantir_tabelas()
    agora = agora or _agora()
    base, local = _endereco()
    with _trava:
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("""UPDATE ComunicadosEquipeDestinos SET Status = ? WHERE Status IN (?, ?)
                           AND ComunicadoID IN (SELECT ComunicadoID FROM ComunicadosEquipe WHERE ValidoAte < ?)""",
                        ST_EXPIRADO, ST_AGUARDANDO, ST_FALHOU, agora.date())
            cur.execute("UPDATE ComunicadosEquipeDestinos SET Status = ? WHERE Status = ? AND EnviadoEm < ?",
                        ST_AGUARDANDO, ST_ENVIANDO, agora - timedelta(minutes=ENVIANDO_PRESO_MIN))
            sql = """SELECT D.DestinoID, D.Tipo, D.PessoaID, D.Nome, D.Telefone, D.Token, D.Lembretes, C.Titulo, C.Chamada
                     FROM ComunicadosEquipeDestinos D JOIN ComunicadosEquipe C ON C.ComunicadoID = D.ComunicadoID
                     WHERE C.EncerradoEm IS NULL AND (D.Status = ? OR (D.Status = ? AND D.Tentativas < ?))"""
            args = [ST_AGUARDANDO, ST_FALHOU, MAX_TENTATIVAS]
            if comunicado_id:
                sql += " AND D.ComunicadoID = ?"
                args.append(int(comunicado_id))
            cur.execute(sql, *args)
            fila = cur.fetchall()
            conn.commit()
        finally:
            conn.close()
        if not fila:
            return 0
        if not base or local:
            logger.warning("[COMUNICADOS] Sem o endereço da internet: os comunicados esperam (o link não abriria no celular).")
            return 0
        forcar = {int(i) for i in (forcar_ids or [])}
        no_turno = _quem_trabalha_agora(agora) if len(forcar) < len(fila) else set()
        enviados = 0
        for did, tipo, pid, nome, tel, token, lembretes, titulo, chamada in fila:
            if did not in forcar and (tipo, int(pid)) not in no_turno:
                continue
            if not _pegar(did, agora):                  # outra rodada (ou o outro programa) já pegou
                continue
            if enviados:
                time.sleep(INTERVALO_ENVIO_SEG)
            ok, resp = _mandar(tel, texto_mensagem(titulo, chamada, f"{base}/comunicado/{token}", nome, lembrete=bool(lembretes)))
            _depois_de_mandar(did, ok, resp, agora)
            if ok:
                enviados += 1
            else:
                logger.error(f"[COMUNICADOS] Não foi para {nome}: {resp}")
        if enviados:
            logger.info(f"[COMUNICADOS] {enviados} comunicado(s) entregue(s) no turno.")
        return enviados


def _mandar(tel, texto):
    import notificador_whatsapp
    try:
        return notificador_whatsapp.enviar_mensagem_whatsapp(tel, texto)
    except Exception as e:
        return False, str(e)


def _pegar(did, agora):
    """Marca 'enviando' só se ainda estava na fila (o agendador e o servidor podem rodar juntos)."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE ComunicadosEquipeDestinos SET Status = ?, EnviadoEm = ? WHERE DestinoID = ? AND Status IN (?, ?)",
                    ST_ENVIANDO, agora, did, ST_AGUARDANDO, ST_FALHOU)
        pegou = cur.rowcount == 1
        conn.commit()
        return pegou
    finally:
        conn.close()


def _depois_de_mandar(did, ok, resp, agora):
    conn = _conexao()
    try:
        cur = conn.cursor()
        if ok:
            cur.execute("UPDATE ComunicadosEquipeDestinos SET Status = ?, EnviadoEm = ?, Erro = NULL WHERE DestinoID = ? AND Status = ?",
                        ST_ENVIADO, agora, did, ST_ENVIANDO)
        else:
            cur.execute("""UPDATE ComunicadosEquipeDestinos SET Status = ?, Tentativas = Tentativas + 1, Erro = ?
                           WHERE DestinoID = ? AND Status = ?""", ST_FALHOU, str(resp)[:300], did, ST_ENVIANDO)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# Painel da gestão
# ------------------------------------------------------------------------------
def _contar(status):
    c = {k: 0 for k in ('total', 'lido', 'enviado', 'aguardando', 'expirado', 'sem_telefone', 'falhou', 'encerrado', 'aberto')}
    for st, aberto in status:
        c['total'] += 1
        if st in (ST_ENVIANDO,):
            st = ST_AGUARDANDO
        c[st if st in c else 'aguardando'] += 1
        if aberto and st == ST_ENVIADO:
            c['aberto'] += 1
    return c


def listar(agora=None):
    garantir_tabelas()
    agora = agora or _agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT ComunicadoID, Titulo, ValidoAte, Pontos, CriadoPor, CriadoEm, EncerradoEm
                       FROM ComunicadosEquipe ORDER BY ComunicadoID DESC""")
        cabs = cur.fetchall()
        cur.execute("SELECT ComunicadoID, Status, AbertoEm FROM ComunicadosEquipeDestinos")
        por = {}
        for cid, st, aberto in cur.fetchall():
            por.setdefault(cid, []).append((st, aberto))
    finally:
        conn.close()
    saida = []
    for cid, titulo, valido, pontos, por_quem, em, encerrado in cabs[:100]:
        valido = database._como_data(valido)
        c = _contar(por.get(cid, []))
        saida.append({'id': cid, 'titulo': titulo, 'criado': _quando(em), 'por': por_quem or '', 'pontos': pontos or 0,
                      'valido_ate': valido.strftime('%d/%m') if valido else '', 'encerrado': bool(encerrado),
                      'vencido': bool(valido and valido < agora.date()), 'contagem': c})
    return {'comunicados': saida}


def _situacao(st, enviado, aberto, lido, lembretes, prox, no_turno, erro, tentativas):
    if st == ST_LIDO:
        return '✅', f"Leu {_quando(lido)}"
    if st in (ST_ENVIADO,):
        return ('👀', f"Abriu {_quando(aberto)}, não confirmou") if aberto else ('📤', f"Recebeu {_quando(enviado)}, não abriu ainda")
    if st in (ST_AGUARDANDO, ST_ENVIANDO):
        extra = ' (lembrete)' if lembretes else ''
        if no_turno:
            return '⏳', f"No turno agora: recebe em instantes{extra}"
        return '⏳', (f"Espera o turno: {prox}{extra}" if prox else f"Espera o turno (sem turno na escala ainda){extra}")
    if st == ST_FALHOU:
        return '⚠️', f"WhatsApp falhou ({tentativas}x): {erro or '?'}" + (" · tenta de novo no turno" if tentativas < MAX_TENTATIVAS else "")
    if st == ST_EXPIRADO:
        return '⌛', "Expirou: não trabalhou até o fim da validade"
    if st == ST_SEM_TEL:
        return '📵', "Sem WhatsApp no cadastro"
    if st == ST_ENCERRADO:
        return '⛔', "Não foi (comunicado encerrado)"
    return '', st


def detalhe(cid, agora=None):
    garantir_tabelas()
    agora = agora or _agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT ComunicadoID, Titulo, Texto, ValidoAte, Pontos, CriadoPor, CriadoEm, EncerradoEm, Chamada
                       FROM ComunicadosEquipe WHERE ComunicadoID = ?""", int(cid))
        cab = cur.fetchone()
        if not cab:
            raise ErroComunicado("Comunicado não encontrado.", 404)
        cur.execute("""SELECT DestinoID, Tipo, PessoaID, Nome, Status, EnviadoEm, AbertoEm, LidoEm, Lembretes, Erro, Tentativas
                       FROM ComunicadosEquipeDestinos WHERE ComunicadoID = ?""", int(cid))
        destinos = cur.fetchall()
    finally:
        conn.close()
    prox = _proximos_turnos(agora)
    agora_set = _quem_trabalha_agora(agora)
    pessoas_ = []
    ordem = {ST_LIDO: 4, ST_ENVIADO: 2, ST_AGUARDANDO: 1, ST_ENVIANDO: 1, ST_FALHOU: 0, ST_EXPIRADO: 5, ST_SEM_TEL: 6, ST_ENCERRADO: 7}
    for did, tipo, pid, nome, st, env, ab, lido, lemb, erro, tent in destinos:
        chave = (tipo, int(pid))
        p = prox.get(chave)
        ic, txt = _situacao(st, env, ab, lido, lemb, _quando(p) if p else '', chave in agora_set, erro, tent or 0)
        pessoas_.append({'id': did, 'nome': nome or '?', 'tipo': tipo, 'tipo_nome': TIPOS.get(tipo, tipo), 'status': st,
                         'icone': ic, 'situacao': txt, 'lembretes': lemb or 0,
                         'pode_agora': st in (ST_AGUARDANDO, ST_FALHOU, ST_EXPIRADO) and not cab[7]})
    pessoas_.sort(key=lambda x: (ordem.get(x['status'], 9), x['nome'].lower()))
    valido = database._como_data(cab[3])
    return {'id': cab[0], 'titulo': cab[1], 'texto': cab[2], 'chamada': chamada_ou_padrao(cab[1], cab[8]),
            'valido_ate': valido.strftime('%d/%m/%Y') if valido else '',
            'pontos': cab[4] or 0, 'por': cab[5] or '', 'criado': _quando(cab[6]), 'encerrado': bool(cab[7]),
            'contagem': _contar([(x['status'], x['status'] == ST_ENVIADO and x['icone'] == '👀') for x in pessoas_]),
            'pessoas': pessoas_, 'exemplo': texto_mensagem(cab[1], cab[8], f"{_endereco()[0]}/comunicado/…")}


def acao(cid, nome_acao, dados, usuario, agora=None):
    """🔔 lembrar quem não leu · 📤 mandar agora (sem esperar o turno) · ⛔ encerrar."""
    garantir_tabelas()
    agora = agora or _agora()
    cid = int(cid)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Titulo, EncerradoEm, ValidoAte FROM ComunicadosEquipe WHERE ComunicadoID = ?", cid)
        cab = cur.fetchone()
        if not cab:
            raise ErroComunicado("Comunicado não encontrado.", 404)
        if cab[1] and nome_acao != 'reabrir':
            raise ErroComunicado("Este comunicado já foi encerrado.", 409)
        if nome_acao == 'lembrar':
            # quem recebeu e não confirmou volta para a fila: recebe de novo (com "🔔 Lembrete") no próximo turno
            cur.execute("""UPDATE ComunicadosEquipeDestinos SET Status = ?, Lembretes = Lembretes + 1, Tentativas = 0
                           WHERE ComunicadoID = ? AND Status = ?""", ST_AGUARDANDO, cid, ST_ENVIADO)
            n = cur.rowcount
            if n and database._como_data(cab[2]) < agora.date() + timedelta(days=1):
                cur.execute("UPDATE ComunicadosEquipe SET ValidoAte = ? WHERE ComunicadoID = ?",
                            agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS), cid)     # o lembrete também tem prazo
            conn.commit()
            if not n:
                return {'ok': True, 'mensagem': "Ninguém para lembrar: quem recebeu já confirmou a leitura."}
            _rodar(lambda: processar(agora=agora, comunicado_id=cid))
            logger.info(f"[COMUNICADOS] {usuario.get('nome')}: lembrete do comunicado {cid} para {n} pessoa(s).")
            return {'ok': True, 'mensagem': f"🔔 {n} pessoa(s) recebe(m) o lembrete no próximo turno (quem estiver trabalhando agora, em instantes)."}
        if nome_acao == 'agora':
            ids = [int(i) for i in (dados.get('ids') or []) if str(i).isdigit()]
            sql = "SELECT DestinoID FROM ComunicadosEquipeDestinos WHERE ComunicadoID = ? AND Status IN (?, ?, ?)"
            cur.execute(sql, cid, ST_AGUARDANDO, ST_FALHOU, ST_EXPIRADO)
            podem = [r[0] for r in cur.fetchall()]
            alvo = [i for i in podem if not ids or i in ids]
            if not alvo:
                raise ErroComunicado("Ninguém esperando para receber.", 409)
            cur.execute(f"""UPDATE ComunicadosEquipeDestinos SET Status = ?, Tentativas = 0
                            WHERE DestinoID IN ({','.join('?' * len(alvo))}) AND Status IN (?, ?)""",
                        ST_AGUARDANDO, *alvo, ST_FALHOU, ST_EXPIRADO)
            if database._como_data(cab[2]) < agora.date():
                cur.execute("UPDATE ComunicadosEquipe SET ValidoAte = ? WHERE ComunicadoID = ?", agora.date(), cid)
            conn.commit()
            _rodar(lambda: processar(agora=agora, comunicado_id=cid, forcar_ids=alvo))
            logger.info(f"[COMUNICADOS] {usuario.get('nome')}: comunicado {cid} mandado agora (fora do turno) para {len(alvo)} pessoa(s).")
            return {'ok': True, 'mensagem': f"📤 Mandando agora para {len(alvo)} pessoa(s), sem esperar o turno."}
        if nome_acao == 'encerrar':
            cur.execute("UPDATE ComunicadosEquipeDestinos SET Status = ? WHERE ComunicadoID = ? AND Status IN (?, ?)",
                        ST_ENCERRADO, cid, ST_AGUARDANDO, ST_FALHOU)
            n = cur.rowcount
            cur.execute("UPDATE ComunicadosEquipe SET EncerradoEm = ? WHERE ComunicadoID = ?", agora, cid)
            conn.commit()
            logger.info(f"[COMUNICADOS] {usuario.get('nome')} encerrou o comunicado {cid}.")
            return {'ok': True, 'mensagem': "⛔ Comunicado encerrado." + (f" {n} pessoa(s) que esperavam o turno não vão receber." if n else "")}
        raise ErroComunicado("Ação desconhecida.", 404)
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# Página do link (pública: o código do link é a chave)
# ------------------------------------------------------------------------------
def _destino_do_token(cur, token):
    if not token or len(str(token)) > 40:
        return None
    cur.execute("""SELECT D.DestinoID, D.Nome, D.Status, D.LidoEm, D.Tipo, D.PessoaID, D.AbertoEm,
                          C.Titulo, C.Texto, C.Pontos, C.CriadoEm
                   FROM ComunicadosEquipeDestinos D JOIN ComunicadosEquipe C ON C.ComunicadoID = D.ComunicadoID
                   WHERE D.Token = ?""", str(token))
    return cur.fetchone()


def ver(token, agora=None):
    """O que a página do link mostra (e marca 👀 abriu, na primeira vez)."""
    garantir_tabelas()
    agora = agora or _agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        d = _destino_do_token(cur, token)
        if not d:
            raise ErroComunicado("Link inválido ou antigo. Peça para a gestão mandar de novo.", 404)
        if not d[6]:
            cur.execute("UPDATE ComunicadosEquipeDestinos SET AbertoEm = ? WHERE DestinoID = ? AND AbertoEm IS NULL", agora, d[0])
            conn.commit()
    finally:
        conn.close()
    nome = (d[1] or '').split()
    return {'nome': nome[0] if nome else '', 'titulo': d[7], 'texto': d[8], 'empresa': _empresa(), 'data': _quando(d[10]),
            'lido': d[2] == ST_LIDO, 'lido_em': _quando(d[3]), 'pontos': d[9] if d[4] == 'func' else 0}


def confirmar_leitura(token, agora=None):
    """✅ Li e estou ciente. Fixo com pontos no comunicado: ganha os pontos na gamificação (uma vez só)."""
    garantir_tabelas()
    agora = agora or _agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        d = _destino_do_token(cur, token)
        if not d:
            raise ErroComunicado("Link inválido ou antigo. Peça para a gestão mandar de novo.", 404)
        cur.execute("""UPDATE ComunicadosEquipeDestinos SET Status = ?, LidoEm = ?, AbertoEm = ISNULL(AbertoEm, ?)
                       WHERE DestinoID = ? AND Status <> ?""", ST_LIDO, agora, agora, d[0], ST_LIDO)
        novo = cur.rowcount == 1
        conn.commit()
    finally:
        conn.close()
    if novo:
        logger.info(f"[COMUNICADOS] {d[1]} confirmou a leitura de '{d[7]}'.")
        if d[9] and d[4] == 'func':
            try:
                database.registrar_pontos_por_leitura(int(d[5]), int(d[9]), d[7])
            except Exception as e:
                logger.error(f"[COMUNICADOS] Pontos da leitura de {d[1]} não registrados: {e}")
    return ver(token, agora)

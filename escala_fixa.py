# ==============================================================================
# == escala_fixa.py  -  Funcionário FIXO na escala (todo dia, menos na folga) ====
# ==============================================================================
# O gestor marca um funcionário como FIXO numa posição e num horário. O sistema escala
# ele sozinho nos dias marcados (padrão: todos), MENOS quando ele não pode trabalhar:
# folga fixa da semana, domingo de folga do mês, férias/afastamento (o cadastro dele).
#
# Os turnos são gravados de verdade na EscalaDiaria — aparecem no programa do PC, no
# Telegram, na confirmação pelo WhatsApp e na Folha × Faturamento. Só de HOJE em diante
# (o passado nunca muda). Quando:
#   - ao abrir um dia na Escala Web;
#   - pelo robô (agendador), todo dia, para os próximos DIAS_A_FRENTE dias;
#   - ao salvar ou tirar um fixo, ou mudar a folga dele (acerta os dias que ninguém mexeu).
#
# Cada (dia, funcionário) entra UMA vez (tabela EscalaFixaAplicada). Se o gestor tirar ou
# mudar o turno de um dia, o sistema respeita e não põe de volta. A linha da tabela também
# serve de "trava" entre o robô e o servidor (a chave não deixa os dois gravarem o mesmo dia).
# ==============================================================================
import logging
from datetime import date, datetime, timedelta

import database
import escala_regras as R

logger = logging.getLogger(__name__)

DIAS_A_FRENTE = 14
DIAS_NOME = {1: 'domingo', 2: 'segunda', 3: 'terça', 4: 'quarta', 5: 'quinta', 6: 'sexta', 7: 'sábado'}
DIAS_CURTO = {1: 'Dom', 2: 'Seg', 3: 'Ter', 4: 'Qua', 5: 'Qui', 6: 'Sex', 7: 'Sáb'}
TODOS_OS_DIAS = [1, 2, 3, 4, 5, 6, 7]

_tabelas_ok = False


class ErroFixo(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ------------------------------------------------------------------------------
# Tabelas
# ------------------------------------------------------------------------------
def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = database.get_db_connection()
    if not conn:
        raise ErroFixo("Sem conexão com o banco de dados. Tente de novo em alguns segundos.", 503)
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'EscalaFixa')
            CREATE TABLE EscalaFixa (
                FuncionarioID INT NOT NULL PRIMARY KEY,
                PosicaoID INT NOT NULL,
                HorarioEntrada VARCHAR(5) NOT NULL,
                HorarioSaida VARCHAR(5) NOT NULL,
                InicioIntervalo VARCHAR(5) NULL,
                FimIntervalo VARCHAR(5) NULL,
                DiasSemana VARCHAR(20) NOT NULL,
                AtualizadoEm DATETIME NULL,
                AtualizadoPor NVARCHAR(80) NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'EscalaFixaAplicada')
            CREATE TABLE EscalaFixaAplicada (
                DataEscala DATE NOT NULL,
                FuncionarioID INT NOT NULL,
                Situacao VARCHAR(12) NOT NULL,
                EscalaID INT NULL,
                PosicaoID INT NULL,
                HorarioEntrada VARCHAR(5) NULL,
                HorarioSaida VARCHAR(5) NULL,
                PRIMARY KEY (DataEscala, FuncionarioID)
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
        raise ErroFixo("Sem conexão com o banco de dados. Tente de novo em alguns segundos.", 503)
    return conn


def _txt_data(valor):
    return str(valor)[:10] if valor is not None else None


def _dias(texto):
    dias = []
    for parte in str(texto or '').split(','):
        try:
            n = int(parte)
        except ValueError:
            continue
        if 1 <= n <= 7 and n not in dias:
            dias.append(n)
    return sorted(dias)


# ------------------------------------------------------------------------------
# Leitura
# ------------------------------------------------------------------------------
def _ler_fixos(cur, funcionario_id=None):
    sql = ("SELECT FuncionarioID, PosicaoID, HorarioEntrada, HorarioSaida, InicioIntervalo, FimIntervalo, DiasSemana, "
           "AtualizadoEm, AtualizadoPor FROM EscalaFixa")
    if funcionario_id is not None:
        cur.execute(sql + " WHERE FuncionarioID = ?", funcionario_id)
    else:
        cur.execute(sql)
    return {r[0]: {'funcionario_id': r[0], 'posicao_id': r[1], 'entrada': R.formatar_hora_curta(r[2]),
                   'saida': R.formatar_hora_curta(r[3]), 'int_ini': R.formatar_hora_curta(r[4]) or '',
                   'int_fim': R.formatar_hora_curta(r[5]) or '', 'dias': _dias(r[6]),
                   'atualizado': _quando(r[7]) + (f" por {r[8]}" if r[8] else '')} for r in cur.fetchall()}


def _quando(valor):
    if valor and not hasattr(valor, 'strftime'):
        try:
            valor = datetime.fromisoformat(str(valor)[:19])
        except ValueError:
            return str(valor)[:16]
    return f"{valor:%d/%m/%Y %H:%M}" if valor else ""


def fixos():
    """{FuncionarioID: config} de todos os fixos."""
    conn = _conexao()
    try:
        return _ler_fixos(conn.cursor())
    finally:
        conn.close()


def texto_folga(func):
    """'segunda' / 'segunda e 2º domingo do mês' / '' (do cadastro do funcionário)."""
    partes = []
    folga = R.folga_do_funcionario(func)
    if folga:
        partes.append(DIAS_NOME.get(folga, ''))
    try:
        dom = int(getattr(func, 'DomingoFolgaMensal', None) or 0)
    except (TypeError, ValueError):
        dom = 0
    if dom > 0:
        partes.append(f"{dom}º domingo do mês")
    return " e ".join(p for p in partes if p)


def _resumo_dias(dias):
    if sorted(dias) == TODOS_OS_DIAS:
        return "todo dia"
    if sorted(dias) == [2, 3, 4, 5, 6]:
        return "seg a sex"
    if sorted(dias) == [2, 3, 4, 5, 6, 7]:
        return "seg a sáb"
    return ", ".join(DIAS_CURTO[d] for d in dias)


def listar():
    """Os fixos para a tela: nome, posição, horário, dias e folga (do cadastro)."""
    cfgs = fixos()
    funcs = {f.FuncionarioID: f for f in database.listar_funcionarios()}
    nomes_pos = database.nomes_posicoes_loja(list({c['posicao_id'] for c in cfgs.values()})) if cfgs else {}
    ativas = {p[0] for p in database.listar_posicoes_loja()}
    lista = []
    for fid, c in cfgs.items():
        f = funcs.get(fid)
        lista.append(dict(c, nome=f.NomeCompleto if f else f"Funcionário {fid} (excluído)",
                          posicao=nomes_pos.get(c['posicao_id']) or f"Posição {c['posicao_id']}",
                          posicao_ativa=c['posicao_id'] in ativas, existe=bool(f),
                          folga=texto_folga(f) if f else '', dia_folga=R.folga_do_funcionario(f) if f else None,
                          dias_texto=_resumo_dias(c['dias'])))
    lista.sort(key=lambda x: x['nome'].lower())
    return lista


# ------------------------------------------------------------------------------
# Aplicar na escala
# ------------------------------------------------------------------------------
def _motivo(func, d):
    return database.motivo_indisponibilidade(
        getattr(func, 'DiaDeFolga', None), getattr(func, 'DomingoFolgaMensal', None),
        getattr(func, 'DataInicioAfastamento', None), getattr(func, 'DataFimAfastamento', None), d)


def _reservar(cur, conn, data, fid):
    """Grava a linha do dia (a chave impede que o robô e o servidor escalem o mesmo dia duas vezes)."""
    try:
        cur.execute("INSERT INTO EscalaFixaAplicada (DataEscala, FuncionarioID, Situacao) VALUES (?, ?, 'reservado')",
                    data, fid)
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def aplicar(datas, funcionario_id=None, hoje=None):
    """
    Escala os fixos nas datas (só de hoje em diante). Pula quem está de folga/férias (sem marcar: se a folga
    mudar, ele entra), quem já está na escala do dia (marca 'ja_estava': o gestor escalou à mão) e posição
    ocupada no horário. Devolve quantos turnos gravou.
    """
    hoje = hoje or date.today()
    datas = sorted({d for d in datas if d >= hoje})
    if not datas:
        return 0
    conn = _conexao()
    gravados = 0
    try:
        cur = conn.cursor()
        cfgs = _ler_fixos(cur, funcionario_id)
        if not cfgs:
            return 0
        funcs = {f.FuncionarioID: f for f in database.listar_funcionarios()}
        nomes_pos = {p[0]: p[1] for p in database.listar_posicoes_loja()}
        for d in datas:
            data = d.isoformat()
            dia_db = R.dia_semana_banco(d)
            cur.execute("SELECT FuncionarioID FROM EscalaFixaAplicada WHERE DataEscala = ?", data)
            ja = {r[0] for r in cur.fetchall()}
            candidatos = [c for c in cfgs.values() if c['funcionario_id'] not in ja and dia_db in c['dias']
                          and c['funcionario_id'] in funcs and c['posicao_id'] in nomes_pos
                          and not _motivo(funcs[c['funcionario_id']], d)]
            if not candidatos:
                continue
            escala = database.buscar_escala_do_dia(data)
            no_dia = {t.FuncionarioID for ts in escala.values() for t in ts if t.FuncionarioID}
            for c in candidatos:
                fid = c['funcionario_id']
                if not _reservar(cur, conn, data, fid):
                    continue                                   # outro processo está escalando este dia
                if fid in no_dia:
                    cur.execute("UPDATE EscalaFixaAplicada SET Situacao = 'ja_estava' WHERE DataEscala = ? AND FuncionarioID = ?",
                                data, fid)
                    conn.commit()
                    continue
                outro = R.conflito_na_posicao(escala, c['posicao_id'], None, c['entrada'], c['saida'])
                if outro or not database.salvar_escala_dia_v3(None, data, c['posicao_id'], fid, None, c['entrada'],
                                                              c['saida'], c['int_ini'] or None, c['int_fim'] or None, ''):
                    # posição ocupada: tenta de novo na próxima vez (o gestor pode liberar a posição)
                    cur.execute("DELETE FROM EscalaFixaAplicada WHERE DataEscala = ? AND FuncionarioID = ?", data, fid)
                    conn.commit()
                    logger.warning(f"Escala fixa: {funcs[fid].NomeCompleto} não entrou em {nomes_pos[c['posicao_id']]} "
                                   f"no dia {data}: posição ocupada no horário"
                                   + (f" ({outro.NomePessoa})" if outro else "") + ".")
                    continue
                escala = database.buscar_escala_do_dia(data)
                eid = next((t.EscalaID for t in escala.get(c['posicao_id'], []) if t.FuncionarioID == fid), None)
                cur.execute("UPDATE EscalaFixaAplicada SET Situacao = 'escalado', EscalaID = ?, PosicaoID = ?, "
                            "HorarioEntrada = ?, HorarioSaida = ? WHERE DataEscala = ? AND FuncionarioID = ?",
                            eid, c['posicao_id'], c['entrada'], c['saida'], data, fid)
                conn.commit()
                no_dia.add(fid)
                gravados += 1
    finally:
        conn.close()
    if gravados:
        logger.info(f"Escala fixa: {gravados} turno(s) de fixo(s) gravado(s) ({datas[0]} a {datas[-1]}).")
    return gravados


def aplicar_proximos(dias=DIAS_A_FRENTE, hoje=None):
    """Robô: hoje e os próximos dias."""
    hoje = hoje or date.today()
    return aplicar([hoje + timedelta(days=i) for i in range(dias)], hoje=hoje)


def esquecer_dia(data_txt):
    """Depois de copiar outra escala por cima do dia: os fixos são conferidos de novo nele."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM EscalaFixaAplicada WHERE DataEscala = ?", data_txt)
        conn.commit()
    finally:
        conn.close()


def ids_fixos_aplicados(data_txt):
    """{EscalaID} dos turnos deste dia que vieram do fixo (para o 📌 na tela)."""
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT EscalaID FROM EscalaFixaAplicada WHERE DataEscala = ? AND Situacao = 'escalado' "
                    "AND EscalaID IS NOT NULL", data_txt)
        return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def ressincronizar(funcionario_id, desde=None, hoje=None):
    """
    Depois de mudar o fixo (ou a folga): acerta os turnos AUTOMÁTICOS dos próximos dias que ninguém mexeu
    (mesma posição e horário de quando o sistema gravou). Dia que deixou de valer (folga nova, dia desmarcado,
    deixou de ser fixo): o turno sai. Mudou posição/horário: o turno muda. Depois escala os dias que faltam.
    Começa AMANHÃ (hoje a pessoa pode já estar trabalhando; hoje se ajusta na tela).
    Devolve {'mudados', 'removidos', 'novos'}.
    """
    hoje = hoje or date.today()
    desde = desde or (hoje + timedelta(days=1))
    conn = _conexao()
    mudados = removidos = 0
    try:
        cur = conn.cursor()
        cfg = _ler_fixos(cur, funcionario_id).get(funcionario_id)
        func = next((f for f in database.listar_funcionarios() if f.FuncionarioID == funcionario_id), None)
        cur.execute("SELECT DataEscala, EscalaID, PosicaoID, HorarioEntrada, HorarioSaida FROM EscalaFixaAplicada "
                    "WHERE FuncionarioID = ? AND Situacao = 'escalado' AND DataEscala >= ?", funcionario_id, desde.isoformat())
        for data_v, eid, pos_snap, ent_snap, sai_snap in cur.fetchall():
            data = _txt_data(data_v)
            d = datetime.strptime(data, '%Y-%m-%d').date()
            escala = database.buscar_escala_do_dia(data)
            turno = next((t for ts in escala.values() for t in ts if t.EscalaID == eid), None)
            if (turno is None or turno.FuncionarioID != funcionario_id or turno.PosicaoID != pos_snap
                    or R.formatar_hora_curta(turno.HorarioEntrada) != R.formatar_hora_curta(ent_snap)
                    or R.formatar_hora_curta(turno.HorarioSaida) != R.formatar_hora_curta(sai_snap)):
                continue                                       # o gestor mexeu neste dia: fica como ele deixou
            vale = bool(cfg and func and R.dia_semana_banco(d) in cfg['dias'] and not _motivo(func, d))
            if not vale:
                database.excluir_turno_escala(eid)
                cur.execute("DELETE FROM EscalaFixaAplicada WHERE DataEscala = ? AND FuncionarioID = ?", data, funcionario_id)
                conn.commit()
                removidos += 1
                continue
            iguais = (turno.PosicaoID == cfg['posicao_id'] and R.formatar_hora_curta(turno.HorarioEntrada) == cfg['entrada']
                      and R.formatar_hora_curta(turno.HorarioSaida) == cfg['saida']
                      and (R.formatar_hora_curta(turno.InicioIntervalo) or '') == cfg['int_ini']
                      and (R.formatar_hora_curta(turno.FimIntervalo) or '') == cfg['int_fim'])
            if iguais:
                continue
            if R.conflito_na_posicao(escala, cfg['posicao_id'], eid, cfg['entrada'], cfg['saida']):
                continue
            if database.salvar_escala_dia_v3(eid, data, cfg['posicao_id'], funcionario_id, None, cfg['entrada'], cfg['saida'],
                                             cfg['int_ini'] or None, cfg['int_fim'] or None, turno.FocoDoDia or ''):
                if turno.PosicaoID != cfg['posicao_id']:
                    _mudar_posicao(cur, eid, cfg['posicao_id'])
                cur.execute("UPDATE EscalaFixaAplicada SET PosicaoID = ?, HorarioEntrada = ?, HorarioSaida = ? "
                            "WHERE DataEscala = ? AND FuncionarioID = ?", cfg['posicao_id'], cfg['entrada'], cfg['saida'],
                            data, funcionario_id)
                conn.commit()
                mudados += 1
    finally:
        conn.close()
    novos = aplicar([desde + timedelta(days=i) for i in range(DIAS_A_FRENTE)], funcionario_id, hoje=hoje) if cfg else 0
    return {'mudados': mudados, 'removidos': removidos, 'novos': novos}


def _mudar_posicao(cur, escala_id, posicao_id):
    """salvar_escala_dia_v3 não muda a posição de um turno que já existe."""
    cur.execute("UPDATE EscalaDiaria SET PosicaoID = ? WHERE EscalaID = ?", posicao_id, escala_id)


# ------------------------------------------------------------------------------
# Salvar / tirar / folga
# ------------------------------------------------------------------------------
def _hora(valor, nome, obrigatoria=True):
    try:
        h = R.hora_ou_none(valor)
    except ValueError:
        raise ErroFixo(f"'{valor}' não é um horário válido para {nome}. Use HH:MM (ex.: 08:00).")
    if obrigatoria and not h:
        raise ErroFixo(f"Preencha {nome}.")
    return h


def _funcionario(funcionario_id):
    try:
        funcionario_id = int(funcionario_id)
    except (TypeError, ValueError):
        raise ErroFixo("Escolha o funcionário.")
    func = next((f for f in database.listar_funcionarios() if f.FuncionarioID == funcionario_id), None)
    if not func:
        raise ErroFixo("Funcionário não encontrado (foi excluído?). Atualize a página.", 409)
    return func


def salvar(dados, usuario):
    """
    dados: funcionario_id, posicao_id, entrada, saida, int_ini, int_fim, dias ([1..7], 1=Dom; vazio = mantém/todos).
    Grava o fixo e acerta os próximos dias. Freelancer não pode ser fixo.
    """
    func = _funcionario(dados.get('funcionario_id'))
    try:
        pos_id = int(dados.get('posicao_id'))
    except (TypeError, ValueError):
        raise ErroFixo("Escolha a posição.")
    nomes_pos = {p[0]: p[1] for p in database.listar_posicoes_loja()}
    if pos_id not in nomes_pos:
        raise ErroFixo("Esta posição não está mais no mapa. Atualize a página.", 409)
    ent = _hora(dados.get('entrada'), "a entrada")
    sai = _hora(dados.get('saida'), "a saída")
    ini = _hora(dados.get('int_ini'), "o início do intervalo", False)
    fim = _hora(dados.get('int_fim'), "o fim do intervalo", False)
    if ent == sai:
        raise ErroFixo("Entrada e saída não podem ser iguais.")
    if bool(ini) != bool(fim):
        raise ErroFixo("Preencha o início E o fim do intervalo (ou deixe os dois vazios).")
    prob = R.problema_intervalo(ent, sai, ini, fim)
    if prob:
        raise ErroFixo(f"O {prob} ({ent} às {sai}).")
    conn = _conexao()
    try:
        cur = conn.cursor()
        antes = _ler_fixos(cur, func.FuncionarioID).get(func.FuncionarioID)
        dias = dados.get('dias')
        if dias is None:
            dias = antes['dias'] if antes else TODOS_OS_DIAS
        if not isinstance(dias, (list, tuple)):
            raise ErroFixo("Dias da semana inválidos.")
        dias = _dias(",".join(map(str, dias)))
        if not dias:
            raise ErroFixo("Marque pelo menos um dia da semana.")
        # outro fixo na MESMA posição e horário cruzando: avisa (não dá para os dois ocuparem)
        for c in _ler_fixos(cur).values():
            if c['funcionario_id'] != func.FuncionarioID and c['posicao_id'] == pos_id and set(c['dias']) & set(dias):
                a, b = R.faixa_turno(ent, sai), R.faixa_turno(c['entrada'], c['saida'])
                if a and b and R.sobrepoe(a, b):
                    outro = next((f.NomeCompleto for f in database.listar_funcionarios()
                                  if f.FuncionarioID == c['funcionario_id']), '?')
                    raise ErroFixo(f"{outro} já é fixo em {nomes_pos[pos_id]} das {c['entrada']} às {c['saida']}: "
                                   "os horários se cruzam. Mude o horário ou escolha outra posição.", 409)
        quem = str((usuario or {}).get('nome') or '?')[:80]
        cur.execute("DELETE FROM EscalaFixa WHERE FuncionarioID = ?", func.FuncionarioID)
        cur.execute("INSERT INTO EscalaFixa (FuncionarioID, PosicaoID, HorarioEntrada, HorarioSaida, InicioIntervalo, "
                    "FimIntervalo, DiasSemana, AtualizadoEm, AtualizadoPor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    func.FuncionarioID, pos_id, ent, sai, ini, fim, ",".join(map(str, dias)), datetime.now(), quem)
        conn.commit()
    finally:
        conn.close()
    hoje = date.today()
    _comeca_amanha(func.FuncionarioID, hoje)
    r = ressincronizar(func.FuncionarioID, hoje=hoje)
    logger.info(f"[GESTÃO] {quem}: {func.NomeCompleto} fixo em {nomes_pos[pos_id]} {ent}-{sai} ({_resumo_dias(dias)}) — {r}.")
    folga = texto_folga(func)
    msg = (f"📌 {func.NomeCompleto} é fixo em {nomes_pos[pos_id]} ({ent}–{sai}, {_resumo_dias(dias)}"
           + (f", menos na folga: {folga}" if folga else ", sem folga fixa no cadastro") + ").")
    if r['novos'] or r['mudados'] or r['removidos']:
        msg += f" A partir de amanhã: {r['novos']} dia(s) escalado(s)" \
               + (f", {r['mudados']} ajustado(s)" if r['mudados'] else "") \
               + (f", {r['removidos']} retirado(s)" if r['removidos'] else "") + "."
    return {'ok': True, 'mensagem': msg, 'sem_folga': not folga}


def _comeca_amanha(funcionario_id, hoje):
    """
    O fixo vale a partir de AMANHÃ: hoje fica como está na tela (sem isto, abrir a escala de hoje
    colocaria a pessoa no dia em que ela talvez nem tenha vindo).
    """
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM EscalaFixaAplicada WHERE DataEscala = ? AND FuncionarioID = ?", hoje.isoformat(), funcionario_id)
        if not cur.fetchone():
            cur.execute("INSERT INTO EscalaFixaAplicada (DataEscala, FuncionarioID, Situacao) VALUES (?, ?, 'antes')",
                        hoje.isoformat(), funcionario_id)
            conn.commit()
    finally:
        conn.close()


def remover(funcionario_id, usuario):
    """Deixa de ser fixo: sai dos próximos dias que ninguém mexeu (a partir de amanhã)."""
    func = _funcionario(funcionario_id)
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM EscalaFixa WHERE FuncionarioID = ?", func.FuncionarioID)
        conn.commit()
    finally:
        conn.close()
    r = ressincronizar(func.FuncionarioID)
    logger.info(f"[GESTÃO] {(usuario or {}).get('nome')}: {func.NomeCompleto} deixou de ser fixo — {r}.")
    return {'ok': True, 'mensagem': f"{func.NomeCompleto} não é mais fixo"
            + (f" ({r['removidos']} turno(s) automático(s) dos próximos dias retirado(s))." if r['removidos'] else ".")}


def definir_folga(funcionario_id, dia_folga, usuario):
    """Muda a folga fixa da semana no cadastro (1=Dom..7=Sáb; 0/None = sem folga) e acerta os próximos dias."""
    func = _funcionario(funcionario_id)
    try:
        dia = int(dia_folga or 0)
    except (TypeError, ValueError):
        raise ErroFixo("Dia de folga inválido.")
    if not 0 <= dia <= 7:
        raise ErroFixo("Dia de folga inválido.")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE Funcionarios SET DiaDeFolga = ? WHERE FuncionarioID = ?", dia or None, func.FuncionarioID)
        conn.commit()
    finally:
        conn.close()
    r = ressincronizar(func.FuncionarioID)
    logger.info(f"[GESTÃO] {(usuario or {}).get('nome')}: folga de {func.NomeCompleto} = {DIAS_NOME.get(dia, 'sem folga')} — {r}.")
    return {'ok': True, 'mensagem': f"Folga de {func.NomeCompleto}: " + (DIAS_NOME[dia] if dia else "sem folga fixa") + "."}

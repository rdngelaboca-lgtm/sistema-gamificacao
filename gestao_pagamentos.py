# ==============================================================================
# == gestao_pagamentos.py - Freelancers e pagamentos na Web (Gestão) ============
# ==============================================================================
# O que o escala_loja_main.py (PC) faz em "👤 Gerenciar Freelancers" e em
# "💰 Pagamentos Freelancers", agora pelo navegador:
#   - cadastro dos freelancers (novo, editar, excluir, quanto falta pagar);
#   - lista dos turnos com o valor (filtros, resumo por freelancer, totais);
#   - corrigir horário real / ajuste / diária, marcar como pago, desfazer;
#   - recibo para o WhatsApp, planilha do Excel;
#   - valores das diárias e feriados.
#
# As contas e os textos são os MESMOS do PC (database.py + escala_regras.py).
# Perguntas ("Excluir mesmo assim?") voltam como {'perguntas': [...]}, igual à Escala.
# ==============================================================================
import io
import logging
import re
import threading
import time
import zipfile
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote
from xml.sax.saxutils import escape

import config
import database
import escala_regras as R
from gestao_escala import ErroEscala, _data, _exigir_banco, _hora, _id

logger = logging.getLogger(__name__)

STATUS = ('pendentes', 'pagos', 'todos')
VEZES_DIFERENTE = 2          # [VALOR NA HORA DE PAGAR] mais que o dobro (ou menos da metade) do calculado: pergunta antes
INTERVALO_RECIBO_SEG = 2.5   # [RECIBO AUTOMÁTICO] entre um recibo e outro (o WhatsApp não gosta de rajada)
SEGUNDO_PLANO = True         # os testes desligam para conferir na hora
_recibos_ok = False


# ------------------------------------------------------------------------------
# Ajudantes
# ------------------------------------------------------------------------------
def _confirmados(dados):
    return set(dados.get('confirmar') or [])


def _centavos(valor):
    return int((Decimal(str(valor or 0)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _lista_ids(valores, nome):
    """Lista de números vinda da página (sem repetidos)."""
    if not isinstance(valores, list) or len(valores) > 1000:
        raise ErroEscala(f"Seleção inválida de {nome}. Atualize a página.")
    ids = []
    for v in valores:
        n = _id(v, nome)
        if n not in ids:
            ids.append(n)
    return ids


def _dinheiro(texto, nome="o ajuste"):
    try:
        return R.para_decimal_br(texto, nome, permitir_negativo=True)
    except ValueError as e:
        raise ErroEscala(str(e))


def _config():
    try:
        return database.buscar_config_pagamento_freelancer()
    except Exception as e:
        logger.warning(f"Valores dos freelancers não lidos (usando o padrão): {e}")
        return dict(database.CONFIG_PAGAMENTO_PADRAO)


def _iid(it):
    """Identificação da linha na página: P = pagamento já feito, E = turno pendente."""
    return f"P{it['PagamentoID']}" if it['Pago'] else f"E{it['EscalaID']}"


def _item_json(it, recibos=None):
    ajuste = it['Ajuste'] or Decimal('0')
    return dict(R.colunas_pagamento(it), iid=_iid(it), pagamento_id=it['PagamentoID'], escala_id=it['EscalaID'],
                data_iso=it['Data'].isoformat() if it['Data'] else None, data_curta=R.fmt_data_br(it['Data'], True),
                feriado=it.get('Feriado') or '', freelancer_id=it['FreelancerID'], pago=bool(it['Pago']),
                sem_horario=bool(it['SemHorario']), total_centavos=_centavos(it['Total']),
                entrada_escala=it['EntradaEscala'] or '', saida_escala=it['SaidaEscala'] or '',
                entrada_real=it['EntradaReal'] or '', saida_real=it['SaidaReal'] or '',
                ajuste_txt=f"{ajuste:.2f}".replace('.', ',') if ajuste else '', ajuste_centavos=_centavos(ajuste),
                observacao=it['Observacao'] or '',
                tipo_forcado=it.get('TipoForcado') or '', tipo_escala=it.get('TipoEscala') or '',
                recibo=(recibos or {}).get(it['PagamentoID']) if it['Pago'] else None)


def _filtros(dados):
    """(de, ate, freelancer_id, status) dos filtros da página ('periodo' = atalho)."""
    periodo = dados.get('periodo')
    if periodo in dict(R.PERIODOS_PAGAMENTO):
        de, ate = R.periodo_rapido(periodo)
    else:
        de, ate = _data(dados.get('de'))[1], _data(dados.get('ate'))[1]
    if de > ate:
        raise ErroEscala("A data inicial está depois da data final.")
    fid = dados.get('freelancer')
    fid = _id(fid, "o freelancer") if fid not in (None, '', 'todos') else None
    status = dados.get('status') if dados.get('status') in STATUS else 'pendentes'
    return de, ate, fid, status


def _itens(dados):
    de, ate, fid, status = _filtros(dados)
    return (de, ate, fid, status), database.listar_pagamentos_freelancers(de, ate, fid, status)


def _escolhidos(itens, ids):
    """Os itens que a pessoa selecionou na página (todos, se não selecionou nenhum)."""
    if not ids:
        return itens
    if not isinstance(ids, list) or len(ids) > 2000:
        raise ErroEscala("Seleção inválida. Atualize a página.")
    ids = set(str(i) for i in ids)
    sel = [i for i in itens if _iid(i) in ids]
    if len(sel) != len(ids):
        raise ErroEscala("A lista mudou desde que você selecionou (alguém pagou ou corrigiu um turno). "
                         "Atualize e selecione de novo.", 409)
    return sel


def _freelancer(fid):
    return next((f for f in database.listar_freelancers() if f.FreelancerID == fid), None)


# ------------------------------------------------------------------------------
# Cadastro dos freelancers
# ------------------------------------------------------------------------------
def _pendentes_por_freelancer():
    """
    {FreelancerID: {'qtd', 'total', 'sem_horario'}} do que falta pagar até hoje (a mesma soma do PC).
    Turno SEM HORÁRIO fica à parte: não tem valor e não dá para pagar antes de corrigir a escala.
    """
    pendentes = {}
    for i in database.listar_pagamentos_freelancers(date(2000, 1, 1), date.today(), status='pendentes'):
        p = pendentes.setdefault(i['FreelancerID'], {'qtd': 0, 'total': Decimal('0'), 'sem_horario': 0})
        if i['SemHorario']:
            p['sem_horario'] += 1
        else:
            p['qtd'] += 1
            p['total'] += i['Total']
    return pendentes


_NADA = {'qtd': 0, 'total': Decimal('0'), 'sem_horario': 0}


def listar_freelancers():
    _exigir_banco()
    pendentes, aviso = {}, None
    try:
        pendentes = _pendentes_por_freelancer()
    except Exception as e:
        logger.warning(f"Não foi possível somar o que falta pagar: {e}")
        aviso = "Não consegui somar o que falta pagar (veja o log)."
    lista = []
    for f in database.listar_freelancers():
        p = pendentes.get(f.FreelancerID, _NADA)
        lista.append({'id': f.FreelancerID, 'nome': f.Nome or '', 'telefone': f.Telefone or '',
                      'whatsapp': R.numero_whatsapp(f.Telefone) or '', 'pendente_qtd': p['qtd'],
                      'pendente': R.fmt_reais(p['total']) if p['qtd'] else '', 'sem_horario': p['sem_horario']})
    total = sum((p['total'] for p in pendentes.values()), Decimal('0'))
    return {'freelancers': lista, 'total_pendente': R.fmt_reais(total), 'aviso': aviso}


def salvar_freelancer(freelancer_id, dados, usuario):
    """Novo (freelancer_id=None) ou editar."""
    nome = ' '.join(str(dados.get('nome') or '').split())[:100]
    tel = str(dados.get('telefone') or '').strip()[:30]
    if not nome:
        raise ErroEscala("Preencha o nome do freelancer.")
    if not tel:
        raise ErroEscala("Preencha o telefone (WhatsApp) com DDD.")
    _exigir_banco()
    frees = list(database.listar_freelancers())
    atual = next((f for f in frees if f.FreelancerID == freelancer_id), None) if freelancer_id is not None else None
    if freelancer_id is not None and not atual:
        raise ErroEscala("Freelancer não encontrado (foi excluído?). Atualize a página.", 409)
    # Telefone novo ou trocado precisa estar num formato que o WhatsApp entenda
    if (not atual or (atual.Telefone or '').strip() != tel) and not R.numero_whatsapp(tel):
        raise ErroEscala(f"'{tel}' não parece um telefone com DDD (ex.: 44 99999-8888).")
    igual = next((f for f in frees if f.FreelancerID != freelancer_id
                  and ' '.join(str(f.Nome or '').split()).lower() == nome.lower()), None)
    if igual and 'duplicado' not in _confirmados(dados):
        return {'perguntas': [{'chave': 'duplicado', 'titulo': "Nome repetido", 'texto': (
            f"Já existe um freelancer chamado {igual.Nome} (telefone {igual.Telefone or '—'}).\n\n"
            "Salvar mesmo assim, com o mesmo nome?")}]}
    try:
        if atual:
            ok = database.atualizar_freelancer(freelancer_id, nome, tel)
        else:
            ok = database.criar_freelancer(nome, tel)
    except Exception as e:
        logger.exception(f"Erro ao salvar freelancer: {e}")
        ok = False
    if not ok:
        raise ErroEscala("Não foi possível salvar o freelancer no banco.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: freelancer {nome} {'atualizado' if atual else 'cadastrado'}.")
    return {'ok': True, 'mensagem': f"{nome}: {'dados atualizados' if atual else 'cadastrado(a)'}."}


def excluir_freelancer(freelancer_id, dados, usuario):
    _exigir_banco()
    f = _freelancer(freelancer_id)
    if not f:
        raise ErroEscala("Freelancer não encontrado (já foi excluído?). Atualize a página.", 409)
    if 'excluir' not in _confirmados(dados):
        try:
            p = _pendentes_por_freelancer().get(freelancer_id, _NADA)
        except Exception:
            p = _NADA
        qtd, sem = p['qtd'], p['sem_horario']
        aviso = (f"\n\n⚠️ Ainda falta pagar {R.fmt_reais(p['total'])} ({qtd} turno{'s' if qtd != 1 else ''}) a este "
                 "freelancer! Excluindo, esses turnos somem da lista de pagamentos (os já PAGOS continuam "
                 "registrados).") if qtd else ""
        if sem:
            aviso += f"\n\n⚠️ Ele também tem {sem} turno{'s' if sem != 1 else ''} SEM HORÁRIO na escala (ainda sem valor)."
        return {'perguntas': [{'chave': 'excluir', 'titulo': "Excluir freelancer", 'texto': (
            f"Tem certeza que deseja excluir o freelancer {f.Nome}?\n\n"
            f"Os turnos dele na escala ficam SEM PESSOA (amarelo no mapa).{aviso}")}]}
    if not database.excluir_freelancer(freelancer_id):
        raise ErroEscala("Falha ao excluir no banco.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: excluiu o freelancer {f.Nome} (ID {freelancer_id}).")
    return {'ok': True, 'mensagem': f"Freelancer {f.Nome} excluído."}


# ------------------------------------------------------------------------------
# Pagamentos
# ------------------------------------------------------------------------------
def listar(dados):
    _exigir_banco()
    (de, ate, fid, status), itens = _itens(dados)
    linhas, totais = R.resumo_pagamentos(itens)
    frees = [{'id': f.FreelancerID, 'nome': f.Nome or '', 'whatsapp': bool(R.numero_whatsapp(getattr(f, 'Telefone', None)))}
             for f in database.listar_freelancers()]
    try:
        recibos = _status_recibos([i['PagamentoID'] for i in itens if i['Pago']])
    except Exception as e:
        logger.warning(f"Pagamentos: situação dos recibos indisponível ({e})")
        recibos = {}
    return {'de': de.isoformat(), 'ate': ate.isoformat(), 'freelancer': fid, 'status': status,
            'periodo': dados.get('periodo') if dados.get('periodo') in dict(R.PERIODOS_PAGAMENTO) else None,
            'itens': [_item_json(i, recibos) for i in itens],
            'resumo': [{'freelancer_id': f, 'nome': n, 'turnos': q, 'pendente': R.fmt_reais(pe), 'pago': R.fmt_reais(pa)}
                       for f, n, q, pe, pa in linhas],
            'totais': {'pendente': R.fmt_reais(totais['pendente']), 'pendente_qtd': totais['pendente_qtd'],
                       'pago': R.fmt_reais(totais['pago']), 'pago_qtd': totais['pago_qtd']},
            'valores': R.texto_valores_pagamento(_config()), 'freelancers': frees,
            'formas': R.FORMAS_PAGAMENTO, 'hoje': date.today().isoformat()}


def _turno(dados):
    eid = _id(dados.get('escala_id'))
    t = database.turno_de_freelancer(eid)
    if not t:
        raise ErroEscala("Turno de freelancer não encontrado (foi excluído da escala?). Atualize a página.", 409)
    return eid, t


def _ler_correcao(dados):
    ent = _hora(dados.get('entrada'), "a entrada real")
    sai = _hora(dados.get('saida'), "a saída real")
    aj = _dinheiro(dados.get('ajuste'))
    tipo = dados.get('tipo') if dados.get('tipo') in ('longa', 'curta') else None
    return ent, sai, aj, tipo


def previa_correcao(dados):
    """O valor do turno com o que está digitado (não grava)."""
    eid, t = _turno(dados)
    try:
        ent, sai, aj, tipo = _ler_correcao(dados)
    except ErroEscala as e:
        return {'ok': False, 'texto': f"⚠️ {e}"}
    calc = database.calcular_pagamento_turno(ent or t['EntradaEscala'], sai or t['SaidaEscala'], _config(), aj, t['Data'],
                                             tipo or t['TipoEscala'], t['EntradaEscala'], t['SaidaEscala'],
                                             database.nome_feriado(t['Data']))
    if not calc:
        return {'ok': False, 'texto': "⚠️ Preencha entrada e saída."}
    return {'ok': True, 'texto': R.texto_calculo(calc)}


def corrigir(dados, usuario):
    _exigir_banco()
    eid, t = _turno(dados)
    ent, sai, aj, tipo = _ler_correcao(dados)
    if bool(ent) != bool(sai):
        raise ErroEscala("Preencha a entrada E a saída reais (ou deixe as duas vazias para usar a escala).")
    if ent and ent == sai:
        raise ErroEscala("Entrada e saída não podem ser iguais.")
    if ent == t['EntradaEscala'] and sai == t['SaidaEscala']:
        ent = sai = None                 # igual à escala: não precisa guardar como "corrigido"
    ok, msg = database.salvar_correcao_pagamento(eid, ent, sai, aj, str(dados.get('observacao') or ''), tipo)
    if not ok:
        raise ErroEscala(msg, 409)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: corrigiu o pagamento do turno {eid} de {t['Nome']} "
                f"({ent or '-'}–{sai or '-'}, ajuste {aj}, diária {tipo or 'automática'}).")
    return {'ok': True, 'mensagem': f"Turno de {t['Nome']} em {R.fmt_data_br(t['Data'])}: {msg.lower()}"}


def _valor_a_pagar(texto):
    """'150' / '150,00' / 'R$ 1.300' (ponto de milhar, como no Brasil) -> Decimal. Vazio ou negativo: erro."""
    t = str(texto if texto is not None else '').replace('R$', '').replace(' ', '').strip()
    if not t:
        raise ErroEscala("Digite o valor a pagar de cada turno.")
    if ',' not in t and re.fullmatch(r'\d{1,3}(\.\d{3})+', t):
        t = t.replace('.', '')                   # '1.300' = mil e trezentos (não R$ 1,30)
    try:
        v = R.para_decimal_br(t, "o valor a pagar")
    except ValueError as e:
        raise ErroEscala(str(e))
    if v > Decimal('100000'):
        raise ErroEscala(f"Valor a pagar alto demais: {R.fmt_reais(v)}. Confira o número digitado.")
    return v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _novos_valores(dados, ids):
    """[VALOR NA HORA DE PAGAR] {EscalaID: valor} dos turnos cujo valor o gestor mudou na janela de pagar."""
    brutos = dados.get('valores') or {}
    if not isinstance(brutos, dict) or len(brutos) > 1000:
        raise ErroEscala("Valores inválidos. Atualize a página.")
    novos = {}
    for chave, texto in brutos.items():
        eid = _id(chave, "o turno")
        if eid not in ids:
            raise ErroEscala("Há valor de um turno que não está na seleção. Atualize a página e tente de novo.", 409)
        novos[eid] = _valor_a_pagar(texto)
    return novos


def _calculados(ids):
    """{EscalaID: (nome, data, valor calculado SEM ajuste)} dos turnos pendentes (o que o sistema calcula)."""
    datas = [t['Data'] for t in (database.turno_de_freelancer(e) for e in ids) if t]
    if not datas:
        return {}
    itens = database.listar_pagamentos_freelancers(min(datas), max(datas), None, 'pendentes')
    return {i['EscalaID']: (i['Nome'], i['Data'], i['Total'] - (i['Ajuste'] or Decimal('0')))
            for i in itens if i['EscalaID'] in ids}


def pagar(dados, usuario):
    _exigir_banco()
    ids = _lista_ids(dados.get('escala_ids'), "os turnos")
    if not ids:
        raise ErroEscala("Selecione os turnos PENDENTES que você pagou.")
    _txt, dia = _data(dados.get('data') or date.today().isoformat())
    forma = str(dados.get('forma') or '').strip()[:30]
    novos = _novos_valores(dados, ids)
    motivo = str(dados.get('motivo') or '').strip()[:150]
    perguntas = []
    if dia > date.today() and 'futuro' not in _confirmados(dados):
        perguntas.append({'chave': 'futuro', 'titulo': "Data no futuro", 'texto': (
            f"A data do pagamento ({R.fmt_data_br(dia, True)}) ainda não chegou.\n\n"
            "Marcar como pago nessa data mesmo assim?")})
    calculados = _calculados(list(novos)) if novos else {}
    if novos and 'valor_diferente' not in _confirmados(dados):
        estranhos = [(eid, v) for eid, v in novos.items() if eid in calculados and (
            v == 0 or v > calculados[eid][2] * VEZES_DIFERENTE or v * VEZES_DIFERENTE < calculados[eid][2])]
        if estranhos:
            perguntas.append({'chave': 'valor_diferente', 'titulo': "Valor bem diferente do calculado", 'texto': (
                "\n".join(f"• {calculados[e][0]} {R.fmt_data_br(calculados[e][1], True)}: calculado "
                          f"{R.fmt_reais(calculados[e][2])} → pagar {R.fmt_reais(v)}" for e, v in estranhos)
                + "\n\nConfira o número digitado. Pagar esses valores mesmo assim?")})
    if perguntas:
        return {'perguntas': perguntas}
    ok, msg, total = database.marcar_pagamentos_pagos(ids, dia, forma, novos_totais=novos, motivo=motivo)
    if not ok:
        raise ErroEscala(msg, 409)
    mudou = ''
    if novos:
        dif = sum((v - calculados[e][2] for e, v in novos.items() if e in calculados), Decimal('0'))
        mudou = (f" ({len(novos)} com valor mudado na hora: {'+' if dif > 0 else ''}{R.fmt_reais(dif)}"
                 f"{' · ' + motivo if motivo else ''})")
    logger.info(f"[GESTÃO] {usuario.get('nome')}: pagou {len(ids)} turno(s) de freelancer "
                f"({R.fmt_reais(total)}, {R.fmt_data_br(dia)}, {forma or 'sem forma'}){mudou}.")
    mensagem = f"{msg} Total {R.fmt_reais(total)}{mudou}."
    recibos = None
    if dados.get('enviar_recibo'):            # [RECIBO AUTOMÁTICO] cada freelancer recebe o dele no WhatsApp
        try:
            recibos = enviar_recibos(ids, dia, forma)
            if recibos['enviando']:
                mensagem += f"\n📱 Recibo indo para o WhatsApp de {len(recibos['enviando'])} freelancer(s)."
            if recibos['sem_whatsapp']:
                mensagem += f"\n📵 Sem WhatsApp no cadastro (mande pelo 📋 Recibo): {', '.join(recibos['sem_whatsapp'])}."
        except Exception as e:                # o pagamento já foi gravado: só o recibo não saiu
            logger.error(f"[GESTÃO] Recibos automáticos falharam: {e}", exc_info=True)
            mensagem += "\n⚠️ O pagamento foi salvo, mas os recibos não saíram. Mande pelo 📋 Recibo."
    return {'ok': True, 'mensagem': mensagem, 'recibos': recibos}


# ------------------------------------------------------------------------------
# [RECIBO AUTOMÁTICO] Ao marcar como PAGO, cada freelancer recebe o recibo (só os turnos pagos agora)
# pelo WhatsApp da loja (Z-API), um de cada vez. A lista mostra 📱 enviado / ⚠️ não foi / 📵 sem WhatsApp.
# ------------------------------------------------------------------------------
def _garantir_recibos():
    global _recibos_ok
    if _recibos_ok:
        return
    conn = database.get_db_connection()
    if not conn:
        raise ErroEscala("Sem conexão com o banco de dados.", 503)
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'RecibosFreelancer')
            CREATE TABLE RecibosFreelancer (
                PagamentoID INT NOT NULL PRIMARY KEY,
                FreelancerID INT NULL,
                Status VARCHAR(12) NOT NULL,
                Erro NVARCHAR(150) NULL,
                EnviadoEm DATETIME NULL
            )
        """)
        conn.commit()
        _recibos_ok = True
    finally:
        conn.close()


def _gravar_recibo(pagamento_ids, freelancer_id, status, erro=None):
    _garantir_recibos()
    conn = database.get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        agora = datetime.now().replace(microsecond=0)
        for pid in pagamento_ids:
            cur.execute("DELETE FROM RecibosFreelancer WHERE PagamentoID = ?", pid)
            cur.execute("INSERT INTO RecibosFreelancer (PagamentoID, FreelancerID, Status, Erro, EnviadoEm) VALUES (?, ?, ?, ?, ?)",
                        pid, freelancer_id, status, (erro or None) and str(erro)[:150], agora)
        conn.commit()
    finally:
        conn.close()


def _status_recibos(pagamento_ids):
    """{PagamentoID: {'status', 'quando', 'erro'}}."""
    pagamento_ids = [p for p in pagamento_ids if p]
    if not pagamento_ids:
        return {}
    _garantir_recibos()
    conn = database.get_db_connection()
    if not conn:
        return {}
    saida = {}
    try:
        cur = conn.cursor()
        for k in range(0, len(pagamento_ids), 500):
            parte = pagamento_ids[k:k + 500]
            cur.execute(f"SELECT PagamentoID, Status, Erro, EnviadoEm FROM RecibosFreelancer WHERE PagamentoID IN "
                        f"({','.join('?' * len(parte))})", *parte)
            for pid, st, erro, quando in cur.fetchall():
                q = quando if isinstance(quando, datetime) else (datetime.fromisoformat(str(quando)[:19]) if quando else None)
                saida[pid] = {'status': st, 'erro': erro or '', 'quando': q.strftime('%d/%m %H:%M') if q else ''}
    finally:
        conn.close()
    return saida


def _texto_recibo_pago(itens, dia, forma):
    total = sum((i['Total'] for i in itens), Decimal('0'))
    cabeca = f"💰 *Pagamento feito: {R.fmt_reais(total)}* · {R.fmt_data_br(dia)}" + (f" · {forma}" if forma else '')
    return cabeca + "\n\n" + R.texto_recibo_freelancer(itens, getattr(config, 'NOME_EMPRESA', '') or '')


def enviar_recibos(escala_ids, dia, forma):
    """Recibo dos turnos pagos agora para cada freelancer. {'enviando': [nomes], 'sem_whatsapp': [nomes]}."""
    _garantir_recibos()
    turnos = [database.turno_de_freelancer(e) for e in escala_ids]
    datas = [t['Data'] for t in turnos if t and t['Data']]
    if not datas:
        return {'enviando': [], 'sem_whatsapp': []}
    ids = set(escala_ids)
    por = {}
    for i in database.listar_pagamentos_freelancers(min(datas), max(datas), None, 'pagos'):
        if i['EscalaID'] in ids:
            por.setdefault(i['FreelancerID'], []).append(i)
    frees = {f.FreelancerID: f for f in database.listar_freelancers()}
    fila, sem = [], []
    for fid, itens in sorted(por.items(), key=lambda kv: str(kv[1][0]['Nome'] or '').lower()):
        f = frees.get(fid)
        tel = R.numero_whatsapp(getattr(f, 'Telefone', None) if f else None)
        pags = [i['PagamentoID'] for i in itens]
        nome = itens[0]['Nome'] or '?'
        if not tel:
            sem.append(nome)
            _gravar_recibo(pags, fid, 'sem_whatsapp')
            continue
        _gravar_recibo(pags, fid, 'enviando')
        fila.append((fid, nome, tel, pags, _texto_recibo_pago(itens, dia, forma)))

    def mandar():
        import notificador_whatsapp
        for k, (fid, nome, tel, pags, texto) in enumerate(fila):
            if k:
                time.sleep(INTERVALO_RECIBO_SEG)
            try:
                ok, resp = notificador_whatsapp.enviar_mensagem_whatsapp(tel, texto)
            except Exception as e:
                ok, resp = False, str(e)
            _gravar_recibo(pags, fid, 'enviado' if ok else 'falhou', None if ok else resp)
            if not ok:
                logger.error(f"[GESTÃO] Recibo de {nome} não foi: {resp}")
        if fila:
            logger.info(f"[GESTÃO] Recibos de pagamento: {len(fila)} freelancer(s).")
    if fila:
        if SEGUNDO_PLANO:
            threading.Thread(target=mandar, daemon=True).start()
        else:
            mandar()
    return {'enviando': [x[1] for x in fila], 'sem_whatsapp': sem}


def desfazer(dados, usuario):
    _exigir_banco()
    ids = _lista_ids(dados.get('pagamento_ids'), "os pagamentos")
    if not ids:
        raise ErroEscala("Selecione os turnos PAGOS que quer voltar para pendente.")
    ok, msg = database.desfazer_pagamentos(ids)
    if not ok:
        raise ErroEscala(msg, 409)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: desfez {len(ids)} pagamento(s) de freelancer {ids}.")
    return {'ok': True, 'mensagem': msg}


def recibo(dados):
    _exigir_banco()
    _filtro, itens = _itens(dados)
    sel = _escolhidos(itens, dados.get('ids'))
    if not sel:
        raise ErroEscala("Não há turnos na lista.")
    if len({i['FreelancerID'] for i in sel}) != 1:
        raise ErroEscala("O recibo é de UM freelancer: escolha o freelancer no filtro ou selecione só os turnos dele.")
    texto = R.texto_recibo_freelancer(sel, getattr(config, 'NOME_EMPRESA', '') or '')
    f = _freelancer(sel[0]['FreelancerID'])
    numero = R.numero_whatsapp(f.Telefone if f else None)
    return {'texto': texto, 'nome': sel[0]['Nome'], 'telefone': (f.Telefone if f else '') or '',
            'whatsapp': f"https://wa.me/{numero}?text={quote(texto)}" if numero else None}


def enviar_recibo_agora(dados, usuario):
    """[RECIBO AUTOMÁTICO] 📱 Manda o recibo da janela 📋 Recibo pelo WhatsApp da loja (sem abrir o celular)."""
    import notificador_whatsapp
    r = recibo(dados)
    _filtro, itens = _itens(dados)
    sel = _escolhidos(itens, dados.get('ids'))
    numero = R.numero_whatsapp(r['telefone'])
    if not numero:
        raise ErroEscala(f"{r['nome']} está sem WhatsApp válido no cadastro (👤 Freelancers).")
    ok, resp = notificador_whatsapp.enviar_mensagem_whatsapp(numero, r['texto'])
    pags = [i['PagamentoID'] for i in sel if i['Pago']]
    if pags:
        _gravar_recibo(pags, sel[0]['FreelancerID'], 'enviado' if ok else 'falhou', None if ok else resp)
    if not ok:
        raise ErroEscala(f"O WhatsApp não mandou: {resp}", 502)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: mandou o recibo de {r['nome']} pelo WhatsApp da loja.")
    return {'ok': True, 'mensagem': f"📱 Recibo enviado para {r['nome']} ({r['telefone']})."}


def planilha(dados):
    """(conteúdo do .xlsx, nome do arquivo) com os turnos da lista (ou só os selecionados)."""
    _exigir_banco()
    _filtro, itens = _itens(dados)
    ids = [i for i in str(dados.get('ids') or '').split(',') if i]
    sel = _escolhidos(itens, ids)
    if not sel:
        raise ErroEscala("Não há turnos na lista para exportar.")
    return _xlsx(R.linhas_planilha_pagamentos(sel)), f"Pagamentos_Freelancers_{datetime.now():%d-%m-%Y}.xlsx"


# ------------------------------------------------------------------------------
# Valores das diárias e feriados
# ------------------------------------------------------------------------------
def valores():
    _exigir_banco()
    cfg = _config()
    return {'campos': R.campos_valores_pagamento(cfg), 'regras': R.REGRAS_VALORES_PAGAMENTO,
            'exemplos': R.exemplos_valores_pagamento(cfg, database.calcular_pagamento_turno)}


def _ler_campos(dados):
    campos = dados.get('campos') if isinstance(dados.get('campos'), dict) else {}
    faltando = [k for k in database.CONFIG_PAGAMENTO_PADRAO if k not in campos]
    if faltando:
        raise ErroEscala("Faltam campos dos valores. Atualize a página.")
    try:
        return R.ler_valores_pagamento({k: campos[k] for k in database.CONFIG_PAGAMENTO_PADRAO})
    except ValueError as e:
        raise ErroEscala(str(e))


def exemplos_valores(dados):
    try:
        novo = _ler_campos(dados)
    except ErroEscala as e:
        return {'ok': False, 'linhas': [f"⚠️ {e}"]}
    return {'ok': True, 'linhas': R.exemplos_valores_pagamento(novo, database.calcular_pagamento_turno)}


def salvar_valores(dados, usuario):
    _exigir_banco()
    novo = _ler_campos(dados)
    ok, msg = database.salvar_config_pagamento_freelancer(novo)
    if not ok:
        raise ErroEscala(msg)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: alterou os valores dos freelancers: {novo}.")
    return {'ok': True, 'mensagem': "Valores dos freelancers salvos."}


def _ano(valor):
    try:
        ano = int(valor)
    except (TypeError, ValueError):
        ano = date.today().year
    if not 2000 <= ano <= 2100:
        raise ErroEscala("Ano inválido.")
    return ano


def feriados(ano_txt):
    _exigir_banco()
    ano = _ano(ano_txt)
    return {'ano': ano, 'feriados': [{'data': d.isoformat(), 'data_txt': R.fmt_data_br(d, True), 'nome': n or 'Feriado'}
                                     for d, n in database.listar_feriados(ano)]}


def adicionar_feriado(dados, usuario):
    _exigir_banco()
    _txt, d = _data(dados.get('data'))
    nome = ' '.join(str(dados.get('nome') or '').split())[:100] or "Feriado"
    ok, msg = database.salvar_feriados([(d, nome)])
    if not ok:
        raise ErroEscala(msg)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: feriado {d} '{nome}' cadastrado.")
    return {'ok': True, 'mensagem': f"Feriado {R.fmt_data_br(d)} ({nome}) salvo.", 'ano': d.year}


def feriados_nacionais(dados, usuario):
    _exigir_banco()
    ano = _ano(dados.get('ano'))
    lista = database.feriados_nacionais(ano)
    if 'nacionais' not in _confirmados(dados):
        return {'perguntas': [{'chave': 'nacionais', 'titulo': "Feriados nacionais", 'texto': (
            f"Cadastrar os {len(lista)} feriados nacionais de {ano}?\n\n"
            + "\n".join(f"{R.fmt_data_br(d, True)} - {n}" for d, n in lista)
            + "\n\nFeriados do estado e da cidade (ex: aniversário da cidade) cadastre à mão.")}]}
    ok, msg = database.salvar_feriados(lista)
    if not ok:
        raise ErroEscala(msg)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: feriados nacionais de {ano}: {msg}")
    return {'ok': True, 'mensagem': msg}


def remover_feriados(dados, usuario):
    _exigir_banco()
    datas = dados.get('datas')
    if not isinstance(datas, list) or not datas:
        raise ErroEscala("Selecione o(s) feriado(s) na lista.")
    dias = [_data(d)[1] for d in datas[:400]]
    falhas = [d for d in dias if not database.excluir_feriado(d)]
    if falhas:
        raise ErroEscala(f"Não consegui remover {len(falhas)} feriado(s). Veja o log.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: removeu {len(dias)} feriado(s): {[str(d) for d in dias]}.")
    return {'ok': True, 'mensagem': f"{len(dias)} feriado(s) removido(s)."}


# ------------------------------------------------------------------------------
# Planilha .xlsx (feita aqui mesmo: não depende de pandas/openpyxl no servidor)
# ------------------------------------------------------------------------------
_PROIBIDOS_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _coluna(n):
    letras = ''
    while n:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _xlsx(linhas, aba='Pagamentos'):
    cab = list(linhas[0])
    tabela = [cab] + [[linha.get(k) for k in cab] for linha in linhas]

    def celula(ref, valor, negrito):
        estilo = ' s="1"' if negrito else ''
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return f'<c r="{ref}"{estilo}><v>{valor}</v></c>'
        texto = escape(_PROIBIDOS_XML.sub('', '' if valor is None else str(valor)))
        return f'<c r="{ref}"{estilo} t="inlineStr"><is><t xml:space="preserve">{texto}</t></is></c>'

    linhas_xml = []
    for r, valores in enumerate(tabela, start=1):
        celulas = ''.join(celula(f"{_coluna(c)}{r}", v, r == 1) for c, v in enumerate(valores, start=1))
        linhas_xml.append(f'<row r="{r}">{celulas}</row>')
    larguras = ''.join(f'<col min="{c}" max="{c}" width="{max(10, min(40, len(str(t)) + 4))}" customWidth="1"/>'
                       for c, t in enumerate(cab, start=1))
    planilha_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
                    'state="frozen"/></sheetView></sheetViews>'
                    f'<cols>{larguras}</cols><sheetData>{"".join(linhas_xml)}</sheetData></worksheet>')
    arquivos = {
        '[Content_Types].xml': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'),
        '_rels/.rels': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        'xl/workbook.xml': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{escape(aba)}" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        'xl/_rels/workbook.xml.rels': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'styles" Target="styles.xml"/></Relationships>'),
        'xl/styles.xml': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>'),
        'xl/worksheets/sheet1.xml': planilha_xml,
    }
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, 'w', zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return saida.getvalue()

# ==============================================================================
# == gestao_equipe.py - Funcionários FIXOS na Web (Gestão › 👥 Equipe) ==========
# ==============================================================================
# O que o main.py (PC) faz na aba "Funcionários Cadastrados", agora pelo navegador:
#   - lista, novo, editar (Telegram, WhatsApp, cargo, horário, folgas, férias/afastamento, verificador);
#   - tarefas ativas, pendências de hoje e histórico completo;
#   - 🔁 transferir (ou copiar) as tarefas fixas para outro funcionário;
#   - 📢 lançar as tarefas de hoje no grupo (falta/atestado);
#   - zerar os pontos do mês e excluir o funcionário (as duas com pergunta antes).
#
# As regras e as funções do banco são as MESMAS do PC (database.py / agendador.py).
# Segurança: o CPF e o verificador (3 primeiros dígitos do CPF) NUNCA vão para a página nem para o log;
# a página só fica sabendo se o verificador está cadastrado.
# Perguntas ("Excluir mesmo assim?") voltam como {'perguntas': [...]}, igual à Escala.
# ==============================================================================
import logging
import re
from datetime import date, datetime

import database
import escala_regras as R
from gestao_escala import ErroEscala, _data, _exigir_banco, _hora, _id

logger = logging.getLogger(__name__)

# Mesmos números do PC (main.py: dias_semana_mapa / domingos_mapa)
DIAS_FOLGA = [(0, 'Sem folga definida'), (1, 'Domingo'), (2, 'Segunda-feira'), (3, 'Terça-feira'), (4, 'Quarta-feira'),
              (5, 'Quinta-feira'), (6, 'Sexta-feira'), (7, 'Sábado')]
DOMINGOS = [(0, 'Nenhum / folga fixa'), (1, '1º domingo do mês'), (2, '2º domingo do mês'), (3, '3º domingo do mês'),
            (4, '4º domingo do mês'), (5, '5º domingo do mês')]
LIMITE_HISTORICO = 400
SQL_ENTREGAS_DO_MES = ("SELECT COUNT(1) FROM Entregas WHERE FuncionarioID = ? "
                       "AND MONTH(DataEnvio) = MONTH(GETDATE()) AND YEAR(DataEnvio) = YEAR(GETDATE())")


# ------------------------------------------------------------------------------
# Ajudantes
# ------------------------------------------------------------------------------
def _confirmados(dados):
    return set(dados.get('confirmar') or [])


def _txt(v):
    return '' if v is None else str(v).strip()


def _int(v, padrao=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return padrao


def _como_data(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _quando(v, formato='%d/%m/%Y'):
    if not v:
        return ''
    if not hasattr(v, 'strftime'):
        try:
            v = datetime.fromisoformat(str(v)[:19])
        except ValueError:
            return str(v)[:16]
    return v.strftime(formato)


def _nome_folga(n):
    return dict(DIAS_FOLGA).get(_int(n), 'Sem folga definida')


def _texto_afastamento(ini, fim, hoje=None):
    """'🏖️ Afastado até 20/11' / '🏖️ Férias de 01/12 a 15/12' / '' (já passou ou não tem)."""
    hoje = hoje or date.today()
    if not ini or not fim or fim < hoje:
        return ''
    if ini <= hoje:
        return f"🏖️ De férias/afastado até {fim:%d/%m}"
    return f"🏖️ Férias/afastamento de {ini:%d/%m} a {fim:%d/%m}"


def _funcionario(fid):
    f = database.buscar_funcionario_por_id(fid)
    if not f:
        raise ErroEscala("Funcionário não encontrado (foi excluído?). Atualize a página.", 409)
    return f


def _padrao_txt(f, hoje):
    """[5x2] '5x2: seg e ter' / 'Rodízio de 3 semanas: ...' se o padrão de folgas de hoje é 5x2 (senão '')."""
    try:
        import folgas
        p = folgas.padrao_no_dia(f.FuncionarioID, hoje or date.today())
        return folgas.descrever_ciclo(p[1]) if p and p[1] else ''
    except Exception as e:
        logger.warning(f"Equipe: padrão de folgas indisponível ({e})")
        return ''


def _json_fixo(f, hoje=None):
    """Um funcionário para a página (SEM CPF e SEM o verificador: só se ele está cadastrado)."""
    ini, fim = _como_data(getattr(f, 'DataInicioAfastamento', None)), _como_data(getattr(f, 'DataFimAfastamento', None))
    tel = _txt(getattr(f, 'TelefoneWhatsApp', None))
    folga, dom = _int(getattr(f, 'DiaDeFolga', 0)), _int(getattr(f, 'DomingoFolgaMensal', 0))
    return {'id': int(f.FuncionarioID), 'nome': _txt(f.NomeCompleto), 'cargo': _txt(getattr(f, 'Cargo', None)),
            'telegram': _txt(getattr(f, 'ChatIDTelegram', None)), 'telefone': tel, 'whatsapp': R.numero_whatsapp(tel) or '',
            'horario': R.formatar_hora_curta(getattr(f, 'HorarioNotificacao', None)),
            'folga': folga, 'folga_txt': _nome_folga(folga), 'domingo': dom,
            'domingo_txt': dict(DOMINGOS).get(dom, '') if dom else '',
            'afast_ini': ini.isoformat() if ini else '', 'afast_fim': fim.isoformat() if fim else '',
            'afast_txt': _texto_afastamento(ini, fim, hoje), 'padrao_txt': _padrao_txt(f, hoje),
            'tem_verificador': bool(_txt(getattr(f, 'VerificadorCPF', None)))}


# ------------------------------------------------------------------------------
# Lista e cadastro
# ------------------------------------------------------------------------------
def listar_fixos():
    _exigir_banco()
    hoje = date.today()
    lista = [_json_fixo(f, hoje) for f in database.listar_funcionarios()]
    lista.sort(key=lambda x: x['nome'].lower())
    return {'fixos': lista, 'dias': DIAS_FOLGA, 'domingos': DOMINGOS}


def _ler_cadastro(dados, novo):
    """Os campos do formulário já conferidos (as MESMAS regras do PC)."""
    nome = ' '.join(_txt(dados.get('nome')).split())[:150]
    chat = _txt(dados.get('telegram')).replace(' ', '')[:30]
    cargo = ' '.join(_txt(dados.get('cargo')).split())[:100]
    tel = _txt(dados.get('telefone'))[:30]
    verif = _txt(dados.get('verificador'))
    horario = _hora(dados.get('horario'), "o horário de notificação")
    if not nome:
        raise ErroEscala("Preencha o nome do funcionário.")
    if novo and not chat:
        raise ErroEscala("Preencha o ID do chat do Telegram (o bot reconhece a pessoa por ele).")
    if chat and not re.fullmatch(r'-?\d{3,20}', chat):
        raise ErroEscala("O ID do chat do Telegram deve ter só números (ex.: 123456789).")
    if novo and not cargo:
        raise ErroEscala("Preencha o cargo.")
    if not horario:
        raise ErroEscala("Preencha o horário de notificação (HH:MM, ex.: 08:00).")
    if verif and not re.fullmatch(r'\d{3}', verif):
        raise ErroEscala("O verificador deve ter exatamente 3 números (os 3 primeiros dígitos do CPF).")
    folga, dom = _int(dados.get('folga'), -1), _int(dados.get('domingo'), -1)
    if folga not in dict(DIAS_FOLGA):
        raise ErroEscala("Escolha o dia da folga semanal.")
    if dom not in dict(DOMINGOS):
        raise ErroEscala("Escolha o domingo de folga (ou 'Nenhum').")
    ini = _data(dados['afast_ini'])[1] if _txt(dados.get('afast_ini')) else None
    fim = _data(dados['afast_fim'])[1] if _txt(dados.get('afast_fim')) else None
    if bool(ini) != bool(fim):
        raise ErroEscala("Para férias/afastamento, preencha a data inicial E a final (ou deixe as duas vazias).")
    if ini and fim < ini:
        raise ErroEscala("A data final do afastamento não pode ser antes da inicial.")
    return {'nome': nome, 'chat': chat, 'cargo': cargo, 'telefone': tel, 'verificador': verif, 'horario': horario,
            'folga': folga, 'domingo': dom, 'ini': ini, 'fim': fim, 'apagar_verificador': bool(dados.get('apagar_verificador'))}


def salvar_fixo(funcionario_id, dados, usuario):
    """Novo (funcionario_id=None) ou editar."""
    novo = funcionario_id is None
    c = _ler_cadastro(dados, novo)
    _exigir_banco()
    atual = None if novo else _funcionario(funcionario_id)
    todos = list(database.listar_funcionarios())
    outros = [f for f in todos if novo or int(f.FuncionarioID) != int(funcionario_id)]
    if c['chat']:
        dono = next((f for f in outros if _txt(getattr(f, 'ChatIDTelegram', None)) == c['chat']), None)
        if dono:
            raise ErroEscala(f"Este ID do Telegram já é de {_txt(dono.NomeCompleto)} (ID {dono.FuncionarioID}). "
                             "Cada pessoa precisa do seu.")
    tel_antes = _txt(getattr(atual, 'TelefoneWhatsApp', None)) if atual else ''
    if c['telefone'] and c['telefone'] != tel_antes and not R.numero_whatsapp(c['telefone']):
        raise ErroEscala(f"'{c['telefone']}' não parece um telefone com DDD (ex.: 66 99999-8888).")
    igual = next((f for f in outros if ' '.join(_txt(f.NomeCompleto).split()).lower() == c['nome'].lower()), None)
    if igual and 'duplicado' not in _confirmados(dados):
        return {'perguntas': [{'chave': 'duplicado', 'titulo': "Nome repetido", 'texto': (
            f"Já existe um funcionário chamado {_txt(igual.NomeCompleto)} (ID {igual.FuncionarioID}).\n\n"
            "Salvar mesmo assim, com o mesmo nome?")}]}

    if c['apagar_verificador']:
        verif = ''
    elif c['verificador']:
        verif = c['verificador']
    else:                                   # vazio = manter o que já estava (a página nunca recebe o valor)
        verif = _txt(getattr(atual, 'VerificadorCPF', None)) if atual else ''
    if novo:
        try:
            database.adicionar_funcionario(c['nome'], c['chat'], c['cargo'], c['horario'], c['folga'])
        except Exception as e:
            logger.exception(f"Erro ao cadastrar funcionário: {e}")
            raise ErroEscala("Não foi possível cadastrar o funcionário no banco. Veja o log.", 500)
        criado = database.buscar_funcionario_por_chat_id(c['chat'])
        if not criado:
            raise ErroEscala("O banco não confirmou o cadastro. Atualize a página para conferir.", 500)
        funcionario_id = int(criado.FuncionarioID)
    try:
        database.atualizar_funcionario(funcionario_id, c['nome'], c['chat'], c['cargo'], c['horario'], c['folga'], verif,
                                       telefone=c['telefone'], domingo_folga=c['domingo'],
                                       inicio_afastamento=c['ini'], fim_afastamento=c['fim'])
    except Exception as e:
        logger.exception(f"Erro ao salvar o funcionário {funcionario_id}: {e}")
        if novo:
            raise ErroEscala(f"{c['nome']} foi cadastrado(a), mas o telefone/folgas/verificador não foram gravados. "
                             "Abra ✏️ Editar e salve de novo.", 500)
        raise ErroEscala("Não foi possível salvar no banco. Nada foi alterado. Veja o log.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: funcionário {c['nome']} (ID {funcionario_id}) "
                f"{'cadastrado' if novo else 'atualizado'}.")
    return {'ok': True, 'id': funcionario_id,
            'mensagem': f"{c['nome']}: {'cadastrado(a)' if novo else 'dados atualizados'}."}


# ------------------------------------------------------------------------------
# Tarefas, pendências e histórico
# ------------------------------------------------------------------------------
def detalhe(funcionario_id):
    """Cadastro + tarefas ativas + pendências de hoje (a janela do funcionário)."""
    _exigir_banco()
    f = _funcionario(funcionario_id)
    tarefas = [{'id': int(t[0]), 'titulo': _txt(t[1]), 'frequencia': _txt(t[2])}
               for t in database.listar_atribuicoes_ativas_por_funcionario(funcionario_id)]
    pendentes = [{'id': int(t.AtribuicaoID), 'titulo': _txt(t.Titulo), 'pontos': _int(t.Pontos), 'tipo': _txt(t.Tipo)}
                 for t in database.listar_tarefas_do_dia_por_funcionario(funcionario_id)]
    return {'fixo': _json_fixo(f), 'tarefas': tarefas, 'pendentes': pendentes, 'hoje': R.fmt_data_br(date.today(), True)}


def historico(funcionario_id):
    _exigir_banco()
    f = _funcionario(funcionario_id)
    linhas = list(database.obter_historico_funcionario(funcionario_id))
    itens = [{'tarefa': _txt(h.Titulo), 'atribuido': _quando(h.DataAtribuicao), 'enviado': _quando(h.DataEnvio, '%d/%m/%Y %H:%M'),
              'status': _txt(h.Status), 'pontos': _int(h.PontosGanhos), 'obs': _txt(h.MotivoRecusa)}
             for h in linhas[:LIMITE_HISTORICO]]
    return {'nome': _txt(f.NomeCompleto), 'itens': itens, 'total': len(linhas), 'limite': LIMITE_HISTORICO}


def tarefas_fixas(funcionario_id):
    """🔁 O que dá para transferir (as fixas) e para quem."""
    _exigir_banco()
    f = _funcionario(funcionario_id)
    fixas, unicas = database.listar_tarefas_fixas(funcionario_id)
    destinos = sorted(({'id': int(x.FuncionarioID), 'nome': _txt(x.NomeCompleto)} for x in database.listar_funcionarios()
                       if int(x.FuncionarioID) != int(funcionario_id)), key=lambda d: d['nome'].lower())
    return {'nome': _txt(f.NomeCompleto), 'fixas': [{k: t[k] for k in ('id', 'titulo', 'frequencia')} for t in fixas],
            'unicas': unicas, 'destinos': destinos}


def transferir(funcionario_id, dados, usuario):
    _exigir_banco()
    origem = _funcionario(funcionario_id)
    destino_id = _id(dados.get('destino'), "quem recebe")
    if destino_id == int(funcionario_id):
        raise ErroEscala("Escolha OUTRO funcionário para receber as tarefas.")
    destino = _funcionario(destino_id)
    ids = dados.get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise ErroEscala("Marque pelo menos uma tarefa.")
    ids = [_id(i, "a tarefa") for i in ids]
    copiar = bool(dados.get('copiar'))
    try:
        r = database.transferir_tarefas_fixas(funcionario_id, destino_id, ids, manter_na_origem=copiar)
    except ValueError as e:
        raise ErroEscala(str(e), 409)
    except Exception as e:
        logger.exception(f"Erro ao transferir tarefas de {funcionario_id} para {destino_id}: {e}")
        raise ErroEscala("Não foi possível transferir. Nada foi alterado. Veja o log.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: {'copiou' if copiar else 'transferiu'} {len(r['transferidas'])} tarefa(s) "
                f"de {_txt(origem.NomeCompleto)} para {_txt(destino.NomeCompleto)}.")
    msg = (f"🔁 {len(r['transferidas'])} tarefa(s) {'copiada(s)' if copiar else 'transferida(s)'} para "
           f"{_txt(destino.NomeCompleto)}.")
    if r['ja_tinha']:
        msg += f"\n{_txt(destino.NomeCompleto)} já tinha {len(r['ja_tinha'])} delas (não duplicou)."
    return {'ok': True, 'mensagem': msg, 'ja_tinha': r['ja_tinha']}


# ------------------------------------------------------------------------------
# Ações com pergunta antes
# ------------------------------------------------------------------------------
def lancar_no_grupo(funcionario_id, dados, usuario):
    """📢 Faltou / atestado: as tarefas de HOJE vão para o grupo do Telegram (o mesmo botão do PC)."""
    _exigir_banco()
    f = _funcionario(funcionario_id)
    nome = _txt(f.NomeCompleto)
    if 'lancar' not in _confirmados(dados):
        return {'perguntas': [{'chave': 'lancar', 'titulo': "Lançar tarefas no grupo", 'texto': (
            f"Você confirma que {nome} NÃO vem hoje?\n\n"
            f"Todas as tarefas de hoje de {nome} vão AGORA para o grupo do Telegram, para outra pessoa assumir.")}]}
    try:
        import agendador
    except Exception as e:
        logger.error(f"Gestão › Equipe: não consegui carregar o agendador ({e})")
        raise ErroEscala("O envio para o grupo não está disponível neste servidor (agendador.py). Use o programa do PC.", 503)
    ok, msg = agendador.forcar_drop_funcionario_especifico(int(funcionario_id))
    if not ok:
        raise ErroEscala(msg, 409)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: lançou no grupo as tarefas de hoje de {nome} (falta/atestado).")
    return {'ok': True, 'mensagem': f"📢 Tarefas de hoje de {nome} lançadas no grupo do Telegram."}


def _entregas_do_mes(funcionario_id):
    conn = database.get_db_connection()
    if not conn:
        raise ErroEscala("Sem conexão com o banco de dados.", 503)
    try:
        cur = conn.cursor()
        cur.execute(SQL_ENTREGAS_DO_MES, int(funcionario_id))
        r = cur.fetchone()
        return int(r[0] or 0) if r else 0
    finally:
        conn.close()


def zerar_pontos(funcionario_id, dados, usuario):
    """Apaga as entregas do MÊS ATUAL do funcionário (a 'bomba atômica' do PC). Não tem volta."""
    _exigir_banco()
    f = _funcionario(funcionario_id)
    nome = _txt(f.NomeCompleto)
    antes = _entregas_do_mes(funcionario_id)
    if not antes:
        return {'ok': True, 'mensagem': f"{nome} não tem entregas neste mês: nada para zerar."}
    if 'zerar' not in _confirmados(dados):
        return {'perguntas': [{'chave': 'zerar', 'titulo': "!! AÇÃO QUE NÃO TEM VOLTA !!", 'texto': (
            f"Apagar PERMANENTEMENTE as {antes} entrega(s) de {nome} deste mês ({date.today():%m/%Y})?\n\n"
            f"Isso zera o desempenho de {nome} no ranking atual.\n\nEsta ação NÃO PODE SER DESFEITA.")}]}
    database.limpar_entregas_do_mes_por_funcionario(int(funcionario_id))
    depois = _entregas_do_mes(funcionario_id)
    if depois:
        raise ErroEscala(f"Não consegui apagar as entregas de {nome} ({depois} continuam). Veja o log.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: zerou os pontos do mês de {nome} (ID {funcionario_id}, {antes} entrega(s)).")
    return {'ok': True, 'mensagem': f"{antes} entrega(s) de {nome} deste mês apagada(s): os pontos do mês foram zerados."}


def excluir_fixo(funcionario_id, dados, usuario):
    _exigir_banco()
    f = _funcionario(funcionario_id)
    nome = _txt(f.NomeCompleto)
    if int(funcionario_id) == _int((usuario or {}).get('id'), -1):
        raise ErroEscala("Você não pode excluir o seu próprio cadastro por aqui.")
    if 'excluir' not in _confirmados(dados):
        return {'perguntas': [{'chave': 'excluir', 'titulo': "Excluir funcionário", 'texto': (
            f"Excluir {nome} (ID {funcionario_id})?\n\n"
            f"TODAS as tarefas, entregas, pontos, documentos e feedbacks de {nome} serão APAGADOS para sempre. "
            "Os turnos na escala ficam sem pessoa.\n\nEsta ação NÃO PODE SER DESFEITA.")}]}
    try:
        database.excluir_funcionario(int(funcionario_id))
    except Exception as e:
        logger.exception(f"Erro ao excluir o funcionário {funcionario_id}: {e}")
        raise ErroEscala(f"Não foi possível excluir {nome}. Nada foi apagado. Veja o log.", 500)
    logger.info(f"[GESTÃO] {usuario.get('nome')}: excluiu o funcionário {nome} (ID {funcionario_id}).")
    return {'ok': True, 'mensagem': f"Funcionário {nome} excluído."}

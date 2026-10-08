# ==============================================================================
# == escala_regras.py  -  Regras da escala da loja (usadas pelo PC E pela Web) ==
# ==============================================================================
# Antes estas regras ficavam dentro do escala_loja_main.py (programa do PC). Com a
# migração para a Web (Gestão › Escala) elas vieram para cá, para as DUAS versões
# conferirem exatamente igual: conflitos, folga, jornada, intervalo, cores do mapa,
# gráfico do fluxo, mensagens do WhatsApp e o texto do valor do freelancer.
# Nada aqui usa a tela; só as funções marcadas "(banco)" usam o banco de dados.
# ==============================================================================
import re
import logging
from datetime import datetime, date, timedelta, time as dt_time
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# [DEPURAÇÃO] Padrão de horário aceito nos campos (00:00 até 23:59)
PADRAO_HORA = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def hora_ou_none(texto):
    """
    Devolve 'HH:MM' válido ou None se o campo estiver vazio.
    Lança ValueError se o texto estiver preenchido com formato errado.

    [DEPURAÇÃO] Antes o texto vazio '' ia direto para o banco. No SQL Server,
    '' convertido para TIME vira 00:00 (MEIA-NOITE): um intervalo apagado virava
    "intervalo de 00:00 às 00:00" e bagunçava o gráfico e as mensagens.
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    if not PADRAO_HORA.match(texto):
        raise ValueError(texto)
    return texto


def normalizar_folga(valor):
    """Converte o dia de folga (1=Dom..7=Sáb) para número. None/0/texto inválido = sem folga."""
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        return None
    return valor if valor > 0 else None  # 0 = "sem folga definida"


def folga_do_funcionario(func):
    """
    [DEPURAÇÃO] O código procurava o campo 'DiaFolga', mas a coluna do banco se chama
    'DiaDeFolga'. Resultado: o aviso "[FOLGA]" no mapa NUNCA aparecia. Esta função
    lê o nome certo (e aceita o antigo, por segurança).
    """
    valor = getattr(func, 'DiaDeFolga', None)
    if valor is None:
        valor = getattr(func, 'DiaFolga', None)
    return normalizar_folga(valor)


def formatar_hora_curta(v):
    """HH:MM a partir de time/datetime/texto; '' se vazio."""
    if not v:
        return ""
    return v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5]


# ------------------------------------------------------------------------------
# [AUDITORIA ESCALA] Regras do dia (conflitos, folga, jornada, intervalo)
# Funções "puras" (não usam a tela nem o banco): dá para testar sozinhas.
# ------------------------------------------------------------------------------
SETOR_TODOS = "Todos os setores"
LIMITE_JORNADA_DIA_MIN = 10 * 60      # CLT: 8h normais + no máximo 2h extras por dia
TURNO_EXIGE_INTERVALO_MIN = 6 * 60    # CLT art. 71: acima de 6h precisa de intervalo


def minutos_do_horario(v):
    """time / datetime / timedelta / 'HH:MM[:SS[.fração]]' -> minutos desde 00:00 (ou None)."""
    if v is None or v == "":
        return None
    if isinstance(v, timedelta):
        return int(v.total_seconds() // 60) % 1440
    if hasattr(v, 'hour') and hasattr(v, 'minute'):
        return v.hour * 60 + v.minute
    m = re.match(r'^\s*(\d{1,2}):(\d{2})', str(v))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def faixa_turno(ent, sai):
    """(início, fim) em minutos; turno que vira a meia-noite ganha +24h no fim. None se faltar horário."""
    a, b = minutos_do_horario(ent), minutos_do_horario(sai)
    if a is None or b is None:
        return None
    if b <= a:
        b += 1440
    return a, b


def sobrepoe(f1, f2):
    return f1[0] < f2[1] and f2[0] < f1[1]


def hm(minutos):
    """570 -> '9h30'."""
    return fmt_horas(minutos=minutos)


def problema_intervalo(ent, sai, ini, fim):
    """Texto do problema do intervalo (fora do turno / fim antes do início) ou None se estiver certo/vazio."""
    if not ini and not fim:
        return None
    if not ini or not fim:
        return "intervalo só com início ou só com fim"
    turno = faixa_turno(ent, sai)
    if turno is None:
        return None
    a, b = minutos_do_horario(ini), minutos_do_horario(fim)
    if a is None or b is None:
        return "intervalo com horário inválido"
    # coloca o intervalo dentro da régua do turno (pode ter virado a meia-noite)
    if a < turno[0]:
        a += 1440
    if b < a:
        b += 1440
    if b == a:
        return "intervalo com início igual ao fim"
    if a < turno[0] or b > turno[1]:
        return "intervalo fora do horário do turno"
    return None


def chave_pessoa(turno):
    """Identifica a pessoa do turno: ('func', id) / ('free', id) / None (turno sem ninguém)."""
    if getattr(turno, 'FuncionarioID', None):
        return ('func', turno.FuncionarioID)
    if getattr(turno, 'FreelancerID', None):
        return ('free', turno.FreelancerID)
    return None


def analisar_escala_do_dia(escala, posicoes, indisponivel=None):
    """
    Confere a escala do dia e devolve a lista de alertas [(nivel, texto)], nivel = 'erro' | 'aviso' | 'info'.
      escala: {PosicaoID: [turnos]}  (como database.buscar_escala_do_dia)
      posicoes: linhas (PosicaoID, Nome, X, Y, Ativo, Setor) das posições ATIVAS do mapa
      indisponivel: função(funcionario_id) -> motivo (texto) ou None
    """
    nomes_pos = {p[0]: p[1] for p in posicoes}
    alertas = []
    por_pessoa = {}
    sem_intervalo = []
    for pos_id, turnos in escala.items():
        nome_pos = nomes_pos.get(pos_id)
        for t in turnos:
            pessoa = chave_pessoa(t)
            nome = t.NomePessoa or "?"
            ent, sai = formatar_hora_curta(t.HorarioEntrada), formatar_hora_curta(t.HorarioSaida)
            onde = f"{nome_pos or 'posição removida do mapa'} {ent}-{sai}"
            if nome_pos is None:
                alertas.append(('aviso', f"{nome} está numa posição que foi REMOVIDA do mapa ({ent}-{sai}): "
                                         "não aparece no mapa, mas vai no Telegram/WhatsApp."))
            if pessoa is None:
                alertas.append(('aviso', f"Turno SEM pessoa em {onde} (freelancer excluído?). Exclua ou escale alguém."))
                continue
            faixa = faixa_turno(t.HorarioEntrada, t.HorarioSaida)
            if faixa is None:
                alertas.append(('aviso', f"{nome} está sem horário de entrada/saída ({nome_pos or 'posição removida'})."))
                continue
            por_pessoa.setdefault(pessoa, []).append((faixa, nome, onde))
            prob = problema_intervalo(t.HorarioEntrada, t.HorarioSaida, t.InicioIntervalo, t.FimIntervalo)
            if prob:
                alertas.append(('erro', f"{nome}: {prob} ({onde}, intervalo "
                                        f"{formatar_hora_curta(t.InicioIntervalo) or '?'}-{formatar_hora_curta(t.FimIntervalo) or '?'})."))
            elif faixa[1] - faixa[0] > TURNO_EXIGE_INTERVALO_MIN and not (t.InicioIntervalo and t.FimIntervalo):
                sem_intervalo.append(nome)
            if pessoa[0] == 'func' and indisponivel:
                motivo = indisponivel(pessoa[1])
                if motivo:
                    motivo = str(motivo).replace('⚠️', '').strip().rstrip('!')
                    alertas.append(('erro', f"{nome} está escalado(a) mas está de FOLGA/AFASTADO(A) ({motivo}) – {onde}."))

    for pessoa, lista in por_pessoa.items():
        lista.sort()
        nome = lista[0][1]
        for i in range(len(lista)):
            for j in range(i + 1, len(lista)):
                if sobrepoe(lista[i][0], lista[j][0]):
                    alertas.append(('erro', f"{nome} está em DOIS lugares ao mesmo tempo: {lista[i][2]} e {lista[j][2]}."))
        total = sum(f[1] - f[0] for f, _, _ in lista)
        if total > LIMITE_JORNADA_DIA_MIN:
            alertas.append(('aviso', f"{nome} soma {hm(total)} no dia ({' + '.join(o for _, _, o in lista)}): "
                                     f"passa do limite de {hm(LIMITE_JORNADA_DIA_MIN)} (8h + 2h extras)."))
    if sem_intervalo:
        nomes = sorted(set(sem_intervalo))
        alertas.append(('info', f"☕ Turno com mais de 6h ainda SEM intervalo ({len(nomes)} pessoa(s)): {', '.join(nomes)}. "
                                "Use '🪄 Gerar Intervalos Automáticos' ou '⏱️ Gerenciar Intervalos'."))
    ordem = {'erro': 0, 'aviso': 1, 'info': 2}
    alertas.sort(key=lambda a: ordem.get(a[0], 3))
    return alertas


def conflitos_ao_salvar(escala, escala_id, pessoa, ent, sai, nome_pessoa="Esta pessoa", nomes_pos=None):
    """
    Antes de salvar um turno: (erros, avisos).
      erros  = impedem salvar (pessoa em dois lugares ao mesmo tempo)
      avisos = pedem confirmação (jornada do dia acima de 10h)
    """
    nomes_pos = nomes_pos or {}
    faixa = faixa_turno(ent, sai)
    erros, avisos = [], []
    if faixa is None or pessoa is None:
        return erros, avisos
    total = faixa[1] - faixa[0]
    for pos_id, turnos in escala.items():
        for t in turnos:
            if escala_id and str(t.EscalaID) == str(escala_id):
                continue          # é o próprio turno que está sendo editado
            if chave_pessoa(t) != pessoa:
                continue
            f2 = faixa_turno(t.HorarioEntrada, t.HorarioSaida)
            if f2 is None:
                continue
            total += f2[1] - f2[0]
            if sobrepoe(faixa, f2):
                erros.append(f"{nome_pessoa} já está escalado(a) em {nomes_pos.get(pos_id, 'outra posição')} "
                             f"das {formatar_hora_curta(t.HorarioEntrada)} às {formatar_hora_curta(t.HorarioSaida)}.")
    if total > LIMITE_JORNADA_DIA_MIN:
        avisos.append(f"{nome_pessoa} vai somar {hm(total)} de trabalho neste dia "
                      f"(limite: {hm(LIMITE_JORNADA_DIA_MIN)} = 8h + 2h extras).")
    return erros, avisos


def conflito_na_posicao(escala, pos_id, escala_id, ent, sai):
    """
    [DEPURAÇÃO WEB] Outro turno da MESMA posição, no mesmo dia, que cruza o horário. A conferência
    do banco compara as horas direto e não enxergava turno que passa da meia-noite: deixava salvar
    23:00–02:00 em cima de 22:00–06:00, ou 15:00–01:00 em cima de 08:00–16:00.
    (01:00–05:00 e 22:00–06:00 do MESMO dia não se cruzam: um é de madrugada, o outro à noite.)
    Devolve o turno que atrapalha ou None.
    """
    faixa = faixa_turno(ent, sai)
    if faixa is None:
        return None
    for t in escala.get(pos_id, []):
        if escala_id and str(t.EscalaID) == str(escala_id):
            continue
        f2 = faixa_turno(t.HorarioEntrada, t.HorarioSaida)
        if f2 is not None and sobrepoe(faixa, f2):
            return t
    return None


# ------------------------------------------------------------------------------
# [MELHORIA ESCALA] Formatação de dinheiro / horas / datas
# ------------------------------------------------------------------------------
DIAS_SEMANA = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
DIAS_CURTOS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']


def fmt_reais(valor):
    """1234.5 -> 'R$ 1.234,50' (e '-R$ 10,00' para negativos)."""
    try:
        v = Decimal(str(valor or 0))
    except (InvalidOperation, ValueError):
        v = Decimal('0')
    texto = f"{abs(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return ("-R$ " if v < 0 else "R$ ") + texto


def para_decimal_br(texto, nome_campo="valor", permitir_negativo=False):
    """'120' / '120,50' / 'R$ 1.200,50' / '-10' -> Decimal. ValueError com mensagem clara."""
    bruto = str(texto or '').replace('R$', '').replace(' ', '').strip()
    if not bruto:
        return Decimal('0')
    if ',' in bruto:
        bruto = bruto.replace('.', '').replace(',', '.')
    try:
        v = Decimal(bruto)
    except InvalidOperation:
        raise ValueError(f"'{texto}' não é um valor válido para {nome_campo} (ex: 120,00).")
    if not v.is_finite() or (v < 0 and not permitir_negativo):
        raise ValueError(f"{nome_campo} não pode ser negativo.")
    return v


def fmt_horas(horas=None, minutos=None):
    """9.5 h (ou 570 min) -> '9h30'; 8 -> '8h'."""
    if minutos is None:
        minutos = int((Decimal(str(horas or 0)) * 60).to_integral_value())
    minutos = int(minutos)
    h, m = divmod(abs(minutos), 60)
    return f"{'-' if minutos < 0 else ''}{h}h{m:02d}" if m else f"{'-' if minutos < 0 else ''}{h}h"


def fmt_data_br(d, com_dia=False):
    if not d:
        return "--"
    if isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], '%Y-%m-%d').date()
        except ValueError:
            return d
    texto = d.strftime('%d/%m/%Y')
    return f"{texto} ({DIAS_CURTOS[d.weekday()]})" if com_dia else texto


def nome_tipo_dia(calc):
    """'longa de domingo' / 'curta (seg a sáb)' / 'longa de feriado'."""
    tipo = calc.get('Tipo') or ''
    dia = calc.get('Dia') or ''
    sufixo = {'Domingo': ' de domingo', 'Feriado': ' de feriado'}.get(dia, ' (seg a sáb)' if dia else '')
    return f"{tipo}{sufixo}"


def texto_calculo(calc):
    """Explica o valor de um turno numa linha (usado no painel, na correção e no recibo)."""
    if not calc:
        return ""
    if calc.get('Proporcional'):
        texto = (f"{fmt_horas(minutos=calc['Minutos'])} de {fmt_horas(minutos=calc['MinutosDiaria'])} da diária "
                 f"{nome_tipo_dia(calc)} ({fmt_reais(calc['DiariaCheia'])}) = {fmt_reais(calc['ValorDiaria'])} (proporcional)")
    else:
        texto = f"{fmt_horas(minutos=calc['Minutos'])}: diária {nome_tipo_dia(calc)} {fmt_reais(calc['ValorDiaria'])}"
        if calc.get('MinutosExtras'):
            texto += f" + {fmt_horas(minutos=calc['MinutosExtras'])} extra {fmt_reais(calc['ValorExtras'])}"
        sobra = (calc.get('MinutosExtrasBrutos') or 0) - (calc.get('MinutosExtras') or 0)
        if sobra:
            texto += f" ({sobra} min não fecham bloco de {calc['BlocoMinutos']})"
    if calc.get('Ajuste'):
        texto += f" {'+' if calc['Ajuste'] > 0 else ''}{fmt_reais(calc['Ajuste'])} ajuste"
    elif calc.get('Proporcional'):
        return texto      # [DEPURAÇÃO WEB] já termina com "= valor (proporcional)": não repete o total
    return f"{texto} = {fmt_reais(calc['Total'])}"


# ------------------------------------------------------------------------------
# [GESTÃO WEB] Partes que antes ficavam dentro da tela do PC
# ------------------------------------------------------------------------------
SETORES_MAPA = ["Varanda", "Frente Loja", "Salão", "Caixa", "Buffet", "Cozinha", "Limpeza", "Camara Fria"]

# Cores das bolinhas do mapa (as mesmas do programa do PC)
COR_VAZIO = "#ff4444"       # vermelho: ninguém escalado
COR_ESCALADO = "#00C851"    # verde
COR_FOLGA = "#FF8800"       # laranja: escalado, mas de folga/férias/afastado
COR_SEM_PESSOA = "#FFBB33"  # amarelo: turno sem pessoa (freelancer excluído?)
COR_FIXO = "#33b5e5"        # azul: vazio, mas o funcionário fixo da posição está disponível

# Tamanho em que a imagem do mapa é desenhada no PC (o fundo fica sempre assim)
MAPA_IMAGEM_LARGURA = 1180
MAPA_IMAGEM_ALTURA = 600

# Quem está numa posição destes setores recebe a diretriz de outro setor no WhatsApp
MAPA_FUNCAO_DIRETRIZ = {
    'Frente Loja': 'Atendimento',
    'Recepção': 'Atendimento',
}


def parse_horario(valor):
    """string / datetime / time / timedelta -> datetime.time (ou None)."""
    if valor is None:
        return None
    if isinstance(valor, timedelta):
        total = int(valor.total_seconds())
        return (datetime.min + timedelta(hours=total // 3600, minutes=(total % 3600) // 60)).time()
    if isinstance(valor, datetime):
        return valor.time()
    if isinstance(valor, dt_time):
        return valor
    if isinstance(valor, str):
        try:
            v = valor.strip().split('.')[0]
            fmt = "%H:%M:%S" if len(v.split(':')) == 3 else "%H:%M"
            return datetime.strptime(v, fmt).time()
        except ValueError:
            return None
    return None


def dia_semana_banco(dia):
    """date -> dia da semana no padrão do banco: 1=Dom, 2=Seg ... 7=Sáb."""
    return (dia.isoweekday() % 7) + 1


def rotulo_e_cor_posicao(nome_pos, turnos, folgas, indisponivel, dia_db, fixo=None, modo_edicao=False,
                         escalados=None):
    """
    Cor da bolinha e texto embaixo dela (o mesmo do PC).
      turnos: lista de turnos da posição (linhas do buscar_escala_do_dia)
      folgas: {FuncionarioID: dia de folga fixa (1=Dom..7=Sáb) ou None}
      indisponivel: função(funcionario_id) -> motivo (texto) ou None
      fixo: (FuncionarioID, Nome, DiaDeFolga) do funcionário fixo da posição, ou None
      escalados: FuncionarioIDs já escalados no dia (o fixo que está em OUTRA posição não fica azul)
    Devolve (cor, [linhas]); a 1ª linha é o nome da posição.
    """
    linhas = [nome_pos]
    cor = COR_VAZIO
    if turnos:
        cor = COR_ESCALADO
        for t in turnos:
            nome_p = t.NomePessoa if t.NomePessoa else "?"
            if t.FuncionarioID:
                if folgas.get(t.FuncionarioID) == dia_db or indisponivel(t.FuncionarioID):
                    nome_p = f"⚠️ {nome_p} [FOLGA]"
                    cor = COR_FOLGA
            h_ent = str(formatar_hora_curta(t.HorarioEntrada))[:5]
            h_sai = str(formatar_hora_curta(t.HorarioSaida))[:5]
            if not t.NomePessoa:
                cor = COR_SEM_PESSOA
            tipo_d = getattr(t, 'TipoDiaria', None) if getattr(t, 'FreelancerID', None) else None
            linhas.append(f"{nome_p} ({h_ent}-{h_sai})" + (f" [{tipo_d}]" if tipo_d in ('curta', 'longa') else ""))
    elif not modo_edicao and fixo:
        f_id, f_nome, f_folga = fixo[0], fixo[1], fixo[2]
        if escalados and f_id in escalados:
            # [DEPURAÇÃO WEB] o fixo já trabalha em outra posição hoje: não está "disponível" aqui
            linhas.append("(Vazio)")
        elif not indisponivel(f_id) and normalizar_folga(f_folga) != dia_db:
            linhas.append(f"{f_nome} (Fixo)")
            cor = COR_FIXO
        else:
            linhas.append("(Vazio)")
    else:
        linhas.append("(Vazio)")
    return cor, linhas


HORAS_FLUXO = list(range(7, 24))     # 07:00 às 23:00


def fluxo_por_hora(horarios, setor_filtro=SETOR_TODOS):
    """
    Pessoas trabalhando em cada hora cheia (7h..23h), sem contar quem está no intervalo.
    horarios: linhas (Entrada, Saída, InícioIntervalo, FimIntervalo, Setor).
    """
    contagem = []
    for h in HORAS_FLUXO:
        momento = dt_time(h, 0)
        qtd = 0
        for row in horarios:
            ent, sai = parse_horario(row[0]), parse_horario(row[1])
            ini, fim = parse_horario(row[2]), parse_horario(row[3])
            if setor_filtro and setor_filtro != SETOR_TODOS and row[4] != setor_filtro:
                continue
            if not ent or not sai:
                continue
            no_turno = (ent <= momento < sai) if ent <= sai else (momento >= ent or momento < sai)
            if not no_turno:
                continue
            no_intervalo = False
            if ini and fim:
                no_intervalo = (ini <= momento < fim) if ini <= fim else (momento >= ini or momento < fim)
            if not no_intervalo:
                qtd += 1
        contagem.append(qtd)
    return contagem


def pessoas_para_intervalos(escala, posicoes, dia):
    """
    Monta a entrada da calculadora de intervalos (calculadora_logica) a partir da escala do dia.
    Devolve (pessoas, dados_por_turno). Cada pessoa é identificada pelo ID do TURNO (EscalaID).
    """
    pessoas, dados_por_turno = [], {}
    for pos_id, turnos in escala.items():
        setor = next((p[5] for p in posicoes if p[0] == pos_id), "Geral")
        for dados in turnos:
            if not (dados.HorarioEntrada and dados.HorarioSaida and dados.NomePessoa):
                continue
            t_ent, t_sai = parse_horario(dados.HorarioEntrada), parse_horario(dados.HorarioSaida)
            if not (t_ent and t_sai):
                logger.warning(f"Horário inválido ignorado na posição {pos_id}: {dados.NomePessoa}")
                continue
            dt_entrada = datetime.combine(dia, t_ent)
            dt_saida = datetime.combine(dia, t_sai)
            if dt_saida <= dt_entrada:
                dt_saida += timedelta(days=1)      # turno que vira a meia-noite
            pessoas.append({'id_posicao': dados.EscalaID, 'nome': dados.NomePessoa, 'setor': setor,
                            'entrada': dt_entrada, 'saida': dt_saida})
            dados_por_turno[dados.EscalaID] = dados
    return pessoas, dados_por_turno


def gravar_intervalos(sugestoes):
    """(banco) Grava {EscalaID: (inicio, fim)} numa única transação. True/False."""
    import database
    conn = database.get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        for escala_id, (ini, fim) in sugestoes.items():
            cursor.execute("UPDATE EscalaDiaria SET InicioIntervalo = ?, FimIntervalo = ? WHERE EscalaID = ?",
                           ini.strftime('%H:%M'), fim.strftime('%H:%M'), escala_id)
        conn.commit()
        logger.info(f"{len(sugestoes)} intervalo(s) gravado(s).")
        return True
    except Exception as e:
        logger.error(f"Erro ao gravar intervalos em lote: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        conn.close()


def setor_da_diretriz(setor):
    """Setor cuja diretriz vai no WhatsApp (Frente Loja/Recepção recebem a de Atendimento)."""
    return MAPA_FUNCAO_DIRETRIZ.get(setor, setor)


def mensagem_confirmacao_escala(nome, data_escala, posicao, entrada, saida, int_ini=None, int_fim=None):
    """Mensagem de confirmação de escala para o WhatsApp de uma pessoa."""
    fmt = lambda v: v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)[:5]
    data_fmt = datetime.strptime(str(data_escala)[:10], '%Y-%m-%d').strftime('%d/%m')
    intervalo = f"\n☕ Intervalo: *{fmt(int_ini)} às {fmt(int_fim)}*" if int_ini and int_fim else ""
    return (f"Olá, *{nome}*! 👋\n"
            f"Confirmação de Escala:\n"
            f"📅 Data: *{data_fmt}*\n"
            f"📍 Posição: *{posicao}*\n"
            f"⏰ Horário: *{fmt(entrada)} às {fmt(saida)}*{intervalo}\n\n"
            f"Bom trabalho!")


def mensagem_diretriz(setor, descricao):
    return f"🎯 *Diretrizes do Setor ({setor}):*\n\n{descricao}"


def lista_envio_whatsapp(escala, posicoes):
    """Pessoas da escala do dia com telefone: [{'nome','telefone','posicao','setor','entrada','saida','int_ini','int_fim'}]."""
    lista = []
    for pos_id, turnos in escala.items():
        pos = next((p for p in posicoes if p[0] == pos_id), None)
        for t in turnos:
            if t.NomePessoa and getattr(t, 'TelefonePessoa', None):
                if not (t.HorarioEntrada and t.HorarioSaida):
                    # [DEPURAÇÃO WEB] mandava "Horário: None às None"
                    logger.warning(f"[WPP] {t.NomePessoa} está sem horário na escala: confirmação não enviada.")
                    continue
                lista.append({'nome': t.NomePessoa, 'telefone': t.TelefonePessoa,
                              'posicao': pos[1] if pos else "Posição", 'setor': pos[5] if pos else None,
                              'entrada': t.HorarioEntrada, 'saida': t.HorarioSaida,
                              'int_ini': t.InicioIntervalo, 'int_fim': t.FimIntervalo})
    return lista


def enviar_confirmacoes_whatsapp(lista, data_escala, enviar, buscar_diretriz, esperar=None, progresso=None):
    """
    Manda a confirmação de escala e a diretriz do setor para cada pessoa da lista.
      enviar(telefone, texto) -> (ok, resposta); buscar_diretriz(setor) -> texto ou None
      esperar(segundos): pausa entre mensagens (anti-spam); progresso(enviados, erros): a cada pessoa
    Devolve (enviados, erros).
    """
    import time
    esperar = esperar or time.sleep
    enviados = erros = 0
    for item in lista:
        try:
            ok, resp = enviar(item['telefone'], mensagem_confirmacao_escala(
                item['nome'], data_escala, item['posicao'], item['entrada'], item['saida'], item['int_ini'], item['int_fim']))
            if ok:
                enviados += 1
                if item['setor']:
                    setor_busca = setor_da_diretriz(item['setor'])
                    try:
                        descricao = buscar_diretriz(setor_busca)
                        if descricao and descricao.strip():
                            esperar(2)          # a diretriz chega DEPOIS da confirmação
                            ok_d, resp_d = enviar(item['telefone'], mensagem_diretriz(setor_busca, descricao))
                            if not ok_d:
                                logger.error(f"[WPP] Falha ao enviar diretriz para {item['nome']}: {resp_d}")
                        else:
                            logger.warning(f"[WPP] Sem diretriz cadastrada para '{setor_busca}'.")
                    except Exception as e_d:
                        logger.error(f"[WPP] Erro na diretriz de {item['nome']}: {e_d}")
            else:
                logger.error(f"[WPP] Falha ao enviar para {item['nome']}: {resp}")
                erros += 1
            esperar(1.5)
        except Exception as e:
            logger.error(f"[WPP] Erro ao processar envio para {item['nome']}: {e}", exc_info=True)
            erros += 1
        if progresso:
            progresso(enviados, erros)
    return enviados, erros

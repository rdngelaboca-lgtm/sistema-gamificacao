# ==============================================================================
# == perfil_disc.py - 🧭 Avaliação de perfil comportamental (DISC) dos fixos ==
# ==============================================================================
# A gestão envia pela Gestão Web (🧭 Perfil) e cada FIXO recebe um LINK no WhatsApp no mesmo horário dos
# 📨 comunicados: a partir de 30 min antes do turno dele (pela escala), fora do intervalo; na folga espera
# o próximo turno.
# No link: 24 grupos de 4 palavras; em cada grupo a pessoa toca na que MAIS e na que MENOS parece com ela.
# O sistema soma D (Dominante), I (Influente), S (Estável) e C (Conforme) e monta:
#   - o relatório da gestão: o que motiva, o que desmotiva, como conversar, como dar feedback, onde rende
#     mais na loja (pelos setores da escala), pontos de atenção e como liderar;
#   - um resumo POSITIVO para a pessoa (só o perfil e os pontos fortes).
# Questionário NOSSO, baseado na teoria DISC (William Marston, pública). É para conhecer e orientar a
# equipe, não um teste certificado: não serve sozinho para contratar ou demitir.
# Dado pessoal (LGPD): só a gestão vê o relatório; a página do link explica para que serve.
# ==============================================================================
import html
import json
import logging
import threading
import time
from datetime import date, timedelta

import config
import database
import comunicados_equipe as CE      # mesmo horário de entrega e mesmos ajudantes (endereço, nome, WhatsApp)

logger = logging.getLogger(__name__)

VERSAO = 1
DIMS = 'DISC'
NOMES = {'D': 'Dominante', 'I': 'Influente', 'S': 'Estável', 'C': 'Conforme'}
EMOJI = {'D': '🔴', 'I': '🟡', 'S': '🟢', 'C': '🔵'}

# situação de cada avaliação
ST_AGUARDANDO, ST_ENVIANDO, ST_ENVIADO, ST_RESPONDIDO = 'aguardando', 'enviando', 'enviado', 'respondido'
ST_FALHOU, ST_EXPIRADO, ST_SEM_TEL, ST_CANCELADO = 'falhou', 'expirado', 'sem_telefone', 'cancelado'
VALIDADE_PADRAO_DIAS, VALIDADE_MAX_DIAS = 7, 30
SEGUNDO_PLANO = True           # os testes desligam para conferir na hora

# Palavras de cada fator (24 cada). Cada grupo do questionário tem uma de cada, numa ordem diferente.
PALAVRAS = {
    'D': ['Decidido', 'Competitivo', 'Direto', 'Ousado', 'Determinado', 'Exigente', 'Independente', 'Enérgico',
          'Objetivo', 'Corajoso', 'Firme', 'Ambicioso', 'Persistente', 'Ágil', 'Desafiador', 'Autoconfiante',
          'Assertivo', 'Arrojado', 'Empreendedor', 'Franco', 'Dinâmico', 'Destemido', 'Prático', 'Audacioso'],
    'I': ['Comunicativo', 'Animado', 'Otimista', 'Persuasivo', 'Sociável', 'Entusiasmado', 'Expressivo', 'Divertido',
          'Inspirador', 'Espontâneo', 'Convincente', 'Extrovertido', 'Alegre', 'Falante', 'Carismático', 'Brincalhão',
          'Popular', 'Criativo', 'Simpático', 'Empolgado', 'Encantador', 'Contagiante', 'Festeiro', 'Motivador'],
    'S': ['Paciente', 'Calmo', 'Leal', 'Prestativo', 'Constante', 'Tranquilo', 'Bom ouvinte', 'Cooperativo',
          'Gentil', 'Previsível', 'Compreensivo', 'Estável', 'Sereno', 'Amigável', 'Acolhedor', 'Dedicado',
          'Pacífico', 'Confiável', 'Solidário', 'Moderado', 'Atencioso', 'Equilibrado', 'Tolerante', 'Companheiro'],
    'C': ['Cuidadoso', 'Organizado', 'Preciso', 'Detalhista', 'Analítico', 'Caprichoso', 'Disciplinado', 'Cauteloso',
          'Perfeccionista', 'Metódico', 'Lógico', 'Criterioso', 'Exato', 'Sistemático', 'Reservado', 'Correto',
          'Pontual', 'Planejador', 'Observador', 'Rigoroso', 'Minucioso', 'Prudente', 'Formal', 'Zeloso'],
}
# ordem das 4 palavras em cada grupo (as 24 combinações de DISC, misturadas): ninguém "acha o padrão"
ORDENS = ['DISC', 'IDCS', 'SCID', 'CSDI', 'DCSI', 'ISDC', 'SDIC', 'CIDS', 'DSIC', 'ICSD', 'SICD', 'CDSI',
          'DICS', 'IDSC', 'SCDI', 'CISD', 'DSCI', 'ICDS', 'SDCI', 'CSID', 'DCIS', 'ISCD', 'SIDC', 'CDIS']
BLOCOS = [[(PALAVRAS[d][k], d) for d in ordem] for k, ordem in enumerate(ORDENS)]
N_BLOCOS = len(BLOCOS)

# O que cada fator significa no dia a dia da loja (textos do relatório)
TEXTOS = {
    'D': {
        'curto': 'foco em resultado e decisão rápida',
        'resumo': 'Gosta de desafio, de resolver na hora e de ver resultado. Fala direto, decide rápido e se incomoda '
                  'com lentidão e enrolação.',
        'fortes': ['Resolve problemas rápido, principalmente no pico', 'Assume a frente quando falta alguém',
                   'Não tem medo de desafio nem de meta', 'Fala o que pensa, sem rodeio'],
        'motiva': ['Metas claras e desafios (ex.: bater a venda do dia)', 'Autonomia para decidir no turno',
                   'Reconhecimento pelo resultado que trouxe', 'Chance de crescer e liderar'],
        'desmotiva': ['Rotina sem desafio e tarefa repetitiva demais', 'Ser controlado em cada detalhe',
                      'Gente lenta ou indecisa em volta', 'Regras sem explicação'],
        'comunicar': ['Vá direto ao ponto: o quê, para quando e qual resultado', 'Dê opções e deixe ele escolher como fazer',
                      'Fale de resultado, sem detalhe demais', 'Evite rodeios e conversas longas'],
        'feedback': ['Seja curto e objetivo, com fatos', 'Mostre o impacto no resultado da loja',
                     'Faça em particular: ele não gosta de ser exposto', 'Peça que ele mesmo proponha a solução'],
        'atencao': ['Pode atropelar colegas e parecer grosso quando está com pressa',
                    'Pode pular etapas (checklist, higiene, conferência)', 'Tende a querer fazer tudo do jeito dele'],
        'pressao': 'Sob pressão fica mandão e impaciente.',
        'liderar': ['Dê metas e responsabilidade (ex.: cuidar do turno, abrir ou fechar a loja)',
                    'Combine o que é regra e o que ele pode decidir sozinho',
                    'Ajude a desenvolver a paciência e o jeito de falar com a equipe'],
        'funcoes': ['Líder de turno, abrir e fechar a loja', 'Horários de pico e reposição rápida',
                    'Resolver problema com cliente'],
        'pessoa': 'Você é movido a desafios! Resolve rápido, não foge de problema e ajuda a equipe a andar no horário de pico.',
        'pessoa_fortes': ['Resolve as coisas rápido', 'Encara desafios e metas', 'Assume a frente quando precisa'],
    },
    'I': {
        'curto': 'comunicação e entusiasmo',
        'resumo': 'Gosta de gente, de conversar e de ambiente animado. Convence com facilidade, cria clima bom e '
                  'desanima com isolamento e rotina parada.',
        'fortes': ['Recebe o cliente com simpatia e cria conexão', 'Sugere sabores e acompanhamentos: vende mais',
                   'Anima a equipe e melhora o clima', 'Se adapta bem a novidades'],
        'motiva': ['Contato com clientes e colegas', 'Elogio em público e reconhecimento',
                   'Ambiente alegre e participativo', 'Novidades: lançamentos, campanhas e eventos'],
        'desmotiva': ['Trabalhar isolado por muito tempo (ex.: câmara fria, estoque)', 'Ambiente frio e crítica em público',
                      'Excesso de detalhe e papelada', 'Não ser ouvido'],
        'comunicar': ['Seja simpático e converse um pouco antes de ir ao assunto', 'Mostre a ideia com entusiasmo e exemplos',
                      'Deixe espaço para ele falar e dar ideias', 'Confirme o combinado por escrito (ele pode esquecer detalhes)'],
        'feedback': ['Comece pelo que ele faz bem', 'Seja leve, mas claro no que precisa mudar',
                     'Combine um próximo passo simples e acompanhe', 'Elogie em público, corrija em particular'],
        'atencao': ['Pode conversar demais e perder o foco ou o tempo', 'Pode esquecer detalhes (troco, validade, anotações)',
                    'Promete muito e às vezes não cumpre tudo'],
        'pressao': 'Sob pressão fica desorganizado e fala demais.',
        'liderar': ['Dê metas de venda e de atendimento, com acompanhamento', 'Use checklists curtos para os detalhes',
                    'Deixe perto do cliente e reconheça as conquistas'],
        'funcoes': ['Receber o cliente e explicar o buffet', 'Sugerir sabores e produtos novos (vendas)',
                    'Eventos, degustações e campanhas'],
        'pessoa': 'Você tem o dom de encantar! Sua simpatia deixa o cliente à vontade e anima a equipe.',
        'pessoa_fortes': ['Comunica bem e conquista as pessoas', 'Deixa o ambiente mais alegre', 'Tem ideias e entusiasmo'],
    },
    'S': {
        'curto': 'constância e cooperação',
        'resumo': 'Calmo, paciente e leal. Gosta de rotina conhecida, de ajudar e de ambiente tranquilo. Se incomoda '
                  'com mudança de repente e com conflito.',
        'fortes': ['Constante: faz bem feito todo dia, do mesmo jeito', 'Paciente com cliente difícil e com criança',
                   'Ajuda os colegas e mantém a equipe unida', 'Bom para ensinar quem está chegando'],
        'motiva': ['Rotina clara e segurança no que vai fazer', 'Ambiente de respeito e harmonia',
                   'Ser valorizado pela dedicação, mesmo sem aparecer', 'Saber das mudanças com antecedência'],
        'desmotiva': ['Mudança de última hora (escala, função, regra)', 'Conflito, gritaria e pressão o tempo todo',
                      'Ser apressado sem parar', 'Falta de reconhecimento pelo esforço silencioso'],
        'comunicar': ['Fale com calma e gentileza', 'Explique o porquê e o passo a passo',
                      'Avise as mudanças antes e dê tempo para se adaptar', 'Pergunte a opinião: ele pode não falar sozinho'],
        'feedback': ['Em particular e com tom tranquilo', 'Valorize a dedicação antes de pedir a mudança',
                     'Seja específico e mostre como fazer', 'Deixe claro que é para ajudar'],
        'atencao': ['Pode guardar insatisfação e não falar', 'Resiste a mudanças e novidades',
                    'Pode ficar lento quando o ritmo aperta muito'],
        'pressao': 'Sob pressão se cala e cede para evitar conflito.',
        'liderar': ['Dê uma função com rotina bem definida', 'Prepare as mudanças antes e explique',
                    'Peça que ele treine os novatos', 'Pergunte como ele está: ele não costuma reclamar'],
        'funcoes': ['Funções de rotina bem definida', 'Treinar quem está chegando',
                    'Atender com calma famílias e clientes difíceis'],
        'pessoa': 'Você é o porto seguro da equipe! Paciente, constante e sempre pronto para ajudar.',
        'pessoa_fortes': ['É constante e confiável', 'Tem paciência com clientes e colegas', 'Ajuda a equipe a ficar unida'],
    },
    'C': {
        'curto': 'qualidade e precisão',
        'resumo': 'Caprichoso, organizado e atento aos detalhes. Gosta de fazer certo, seguindo padrão e regra. Se '
                  'incomoda com bagunça, erro e improviso.',
        'fortes': ['Segue padrão de qualidade, receita e higiene', 'Cuidadoso com dinheiro, troco e conferência',
                   'Percebe erros que os outros não veem', 'Organiza estoque, validade e etiquetas'],
        'motiva': ['Regras e padrões claros', 'Tempo para fazer bem feito', 'Ser reconhecido pela qualidade e precisão',
                   'Ter as informações e o treinamento completos'],
        'desmotiva': ['Bagunça e falta de padrão', 'Pressa que obriga a fazer malfeito', 'Crítica sem fundamento',
                      'Mudança sem explicação lógica'],
        'comunicar': ['Seja claro e organizado, com fatos e detalhes', 'Explique o motivo das regras e dos números',
                      'Dê tempo para ele pensar antes de responder', 'Combine por escrito (checklist, procedimento)'],
        'feedback': ['Use fatos e exemplos concretos', 'Seja preciso no que precisa mudar e mostre o padrão',
                     'Não critique na frente dos outros', 'Reconheça a qualidade do trabalho'],
        'atencao': ['Pode ficar lento por querer tudo perfeito', 'Pode ser crítico demais com os colegas',
                    'Tem dificuldade com improviso e mudança rápida'],
        'pressao': 'Sob pressão se fecha e fica crítico demais.',
        'liderar': ['Dê processos claros (checklist, conferência, validade)',
                    'Combine o nível de detalhe certo para o tempo que tem', 'Ajude a priorizar quando a loja está cheia'],
        'funcoes': ['Conferência de notas e mercadorias', 'Controle de estoque e validade', 'Padrão de qualidade e higiene'],
        'pessoa': 'Você é sinônimo de qualidade! Seu capricho e sua atenção aos detalhes fazem a diferença.',
        'pessoa_fortes': ['Faz as coisas com capricho', 'É organizado e atento aos detalhes', 'Segue o padrão certinho'],
    },
}

# Onde cada perfil rende mais na loja: peso de cada fator por setor (nomes dos setores da escala)
SETORES = [
    ('Caixa', {'C': .5, 'I': .25, 'S': .25}, 'atenção com dinheiro e cupom, e simpatia no fim do atendimento'),
    ('Frente Loja', {'I': .6, 'S': .25, 'D': .15}, 'receber o cliente, explicar o buffet e sugerir sabores'),
    ('Salão', {'S': .45, 'I': .35, 'C': .2}, 'manter o salão em ordem e atender as mesas com calma'),
    ('Varanda', {'I': .5, 'S': .3, 'D': .2}, 'contato com o cliente e movimento'),
    ('Buffet', {'S': .4, 'C': .4, 'D': .2}, 'repor no ritmo certo e manter a apresentação no padrão'),
    ('Cozinha', {'C': .5, 'S': .4, 'D': .1}, 'seguir receita e higiene, sempre do mesmo jeito'),
    ('Limpeza', {'S': .5, 'C': .5}, 'rotina caprichada, sem pular etapa'),
    ('Camara Fria', {'C': .6, 'S': .3, 'D': .1}, 'organização, validade e contagem do estoque'),
    ('Liderança de turno', {'D': .5, 'I': .3, 'C': .2}, 'decidir rápido no pico e puxar a equipe'),
]
FALTA_NA_EQUIPE = {
    'D': 'Ninguém com D forte: no pico, combine antes quem decide (líder do turno) para a equipe não travar.',
    'I': 'Ninguém com I forte: treine a recepção e as sugestões de sabores, senão o atendimento fica frio.',
    'S': 'Ninguém com S forte: cuide da rotina e do treinamento dos novatos, senão a equipe fica instável.',
    'C': 'Ninguém com C forte: reforce os checklists de caixa, validade e conferência, senão os detalhes escapam.',
}

_tabelas_ok = False
_trava = threading.Lock()


class ErroPerfil(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


def _esc(t):
    return html.escape(str(t if t is not None else ''), quote=False)


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def _conexao():
    conn = database.get_db_connection()
    if not conn:
        raise ErroPerfil("Sem conexão com o banco de dados.", 503)
    return conn


def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AvaliacoesDisc')
            CREATE TABLE AvaliacoesDisc (
                AvaliacaoID INT IDENTITY(1,1) PRIMARY KEY,
                FuncionarioID INT NOT NULL,
                Nome NVARCHAR(150) NULL,
                Telefone VARCHAR(30) NULL,
                Token VARCHAR(24) NOT NULL UNIQUE,
                Status VARCHAR(14) NOT NULL,
                Pontos INT NOT NULL DEFAULT 0,
                Tentativas INT NOT NULL DEFAULT 0,
                Lembretes INT NOT NULL DEFAULT 0,
                CriadoPor NVARCHAR(150) NULL,
                CriadoEm DATETIME NOT NULL,
                ValidoAte DATE NOT NULL,
                EnviadoEm DATETIME NULL,
                AbertoEm DATETIME NULL,
                RespondidoEm DATETIME NULL,
                CanceladoEm DATETIME NULL,
                Respostas NVARCHAR(MAX) NULL,
                Versao INT NULL,
                PctD INT NULL, PctI INT NULL, PctS INT NULL, PctC INT NULL,
                Perfil VARCHAR(4) NULL,
                Erro NVARCHAR(300) NULL
            )
        """)
        conn.commit()
        _tabelas_ok = True
    finally:
        conn.close()


def _rodar(funcao):
    if SEGUNDO_PLANO:
        threading.Thread(target=funcao, daemon=True).start()
    else:
        funcao()


# ------------------------------------------------------------------------------
# Cálculo do perfil
# ------------------------------------------------------------------------------
def calcular(escolhas):
    """
    escolhas: [(fator MAIS, fator MENOS)] dos 24 grupos. Mais = +1, menos = −1; cada fator vai de −24 a +24.
    Somando 24 em cada um (0 a 48) o total dá sempre 96: vira porcentagem que soma 100 (a média é 25%).
    """
    bruto = {d: 0 for d in DIMS}
    for mais, menos in escolhas:
        bruto[mais] += 1
        bruto[menos] -= 1
    pos = {d: bruto[d] + N_BLOCOS for d in DIMS}
    total = sum(pos.values()) or 1
    pct = {d: int(round(100 * pos[d] / total)) for d in DIMS}
    sobra = 100 - sum(pct.values())                       # arredondamento: o maior fica com a diferença
    if sobra:
        pct[max(DIMS, key=lambda d: (pct[d], -DIMS.index(d)))] += sobra
    ordem = sorted(DIMS, key=lambda d: (-pct[d], DIMS.index(d)))
    perfil = ordem[0]
    if pct[ordem[1]] >= 27 and pct[ordem[0]] - pct[ordem[1]] <= 10:
        perfil += ordem[1]                                 # dois fatores fortes e perto: perfil combinado (ex.: IS)
    return pct, perfil


def nome_perfil(perfil):
    return ' + '.join(f"{EMOJI[d]} {NOMES[d]}" for d in perfil)


def intensidade(p):
    return 'alto' if p >= 35 else ('médio' if p >= 25 else 'baixo')


def setores_da_pessoa(pct, n=3):
    """Os setores (e a liderança de turno) que mais combinam com o perfil, com o motivo."""
    notas = [(sum(peso * pct[d] for d, peso in pesos.items()), nome, motivo) for nome, pesos, motivo in SETORES]
    notas.sort(key=lambda x: -x[0])
    return [{'setor': nome, 'motivo': motivo} for _, nome, motivo in notas[:n]]


def relatorio(pct, perfil):
    """O relatório completo da gestão (perfil principal + traços do segundo, se for combinado)."""
    p, seg = perfil[0], (perfil[1] if len(perfil) > 1 else None)
    t, t2 = TEXTOS[p], TEXTOS[seg] if seg else None
    resumo = t['resumo'] + (f" Também tem traços fortes de {NOMES[seg]} ({t2['curto']})." if seg else '')
    junta = lambda chave, n1=3, n2=2: t[chave][:n1] + ([x for x in t2[chave][:n2] if x not in t[chave]] if t2 else [])
    return {
        'perfil': perfil, 'nome': nome_perfil(perfil), 'pct': pct,
        'fatores': [{'d': d, 'nome': NOMES[d], 'emoji': EMOJI[d], 'pct': pct[d], 'intensidade': intensidade(pct[d])} for d in DIMS],
        'resumo': resumo,
        'fortes': junta('fortes', 4), 'motiva': junta('motiva'), 'desmotiva': junta('desmotiva'),
        'comunicar': junta('comunicar'), 'feedback': junta('feedback'), 'atencao': junta('atencao', 3, 1),
        'pressao': t['pressao'], 'liderar': junta('liderar', 3, 1), 'funcoes': junta('funcoes', 3, 1),
        'setores': setores_da_pessoa(pct),
    }


def resumo_pessoa(pct, perfil):
    """O que a própria pessoa vê ao terminar: só o lado positivo."""
    p, seg = perfil[0], (perfil[1] if len(perfil) > 1 else None)
    fortes = TEXTOS[p]['pessoa_fortes'] + ([TEXTOS[seg]['pessoa_fortes'][0]] if seg else [])
    return {'perfil': perfil, 'nome': nome_perfil(perfil), 'texto': TEXTOS[p]['pessoa'], 'fortes': fortes,
            'fatores': [{'d': d, 'nome': NOMES[d], 'emoji': EMOJI[d], 'pct': pct[d]} for d in DIMS]}


# ------------------------------------------------------------------------------
# Quem pode receber (só fixos)
# ------------------------------------------------------------------------------
def _ultimas_por_pessoa(cur):
    """{FuncionarioID: linha da avaliação mais recente}."""
    cur.execute("""SELECT AvaliacaoID, FuncionarioID, Status, RespondidoEm, Perfil, PctD, PctI, PctS, PctC, CriadoEm
                   FROM AvaliacoesDisc ORDER BY AvaliacaoID""")
    ult, resp = {}, {}
    for r in cur.fetchall():
        ult[int(r[1])] = r
        if r[2] == ST_RESPONDIDO:
            resp[int(r[1])] = r
    return ult, resp


def pessoas(agora=None):
    garantir_tabelas()
    agora = agora or CE._agora()
    base = CE.pessoas(agora)                               # mesma lista dos comunicados (turno, WhatsApp, dias)
    conn = _conexao()
    try:
        ult, resp = _ultimas_por_pessoa(conn.cursor())
    finally:
        conn.close()
    saida = []
    for p in base['pessoas']:
        if p['tipo'] != 'func':
            continue
        fid = int(p['id'].split(':')[1])
        u, r = ult.get(fid), resp.get(fid)
        p = dict(p, id=fid,
                 perfil=(r[4] if r else ''), perfil_nome=(nome_perfil(r[4]) if r else ''),
                 respondido_em=(CE._quando(r[3]) if r else ''),
                 pendente=bool(u and u[2] in (ST_AGUARDANDO, ST_ENVIANDO, ST_ENVIADO, ST_FALHOU)))
        saida.append(p)
    return {'pessoas': saida, 'hoje': base['hoje'], 'antecedencia': base['antecedencia'], 'empresa': base['empresa'],
            'dias_escalados_max': base['dias_escalados_max'], 'link_local': base['link_local'],
            'validade_padrao': (agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)).isoformat(),
            'validade_max': (agora.date() + timedelta(days=VALIDADE_MAX_DIAS)).isoformat()}


# ------------------------------------------------------------------------------
# Enviar
# ------------------------------------------------------------------------------
def texto_mensagem(nome, link, pontos=0, lembrete=False):
    primeiro = CE._primeiro_nome(nome)
    return ((f"🔔 *Lembrete:* sua avaliação de perfil ainda está esperando você.\n\n" if lembrete else "")
            + f"🧭 *Avaliação de perfil — {CE._empresa()}*\n\n"
            + (f"Olá, {primeiro}!\n" if primeiro else "Olá!\n")
            + "Queremos te conhecer melhor para organizar a equipe do jeito que combina com você. São "
            + f"{N_BLOCOS} perguntas rápidas (uns 10 minutos) e não existe resposta certa ou errada.\n\n"
            + (f"⭐ Respondendo você ganha *{pontos} pontos* na gamificação!\n\n" if pontos else "")
            + f"👉 *Toque no link para responder:*\n{link}")


def enviar(dados, usuario, agora=None):
    """Uma avaliação por fixo escolhido; quem está no horário recebe na hora (em segundo plano)."""
    garantir_tabelas()
    agora = agora or CE._agora()
    ids = dados.get('pessoas') or []
    if not isinstance(ids, list) or not ids:
        raise ErroPerfil("Escolha quem vai receber.")
    try:
        ids = list(dict.fromkeys(int(str(i).split(':')[-1]) for i in ids))
    except ValueError:
        raise ErroPerfil("Pessoa inválida na lista. Atualize a página.")
    try:
        pontos = int(dados.get('pontos') or 0)
    except (TypeError, ValueError):
        raise ErroPerfil("Pontos inválidos.")
    if not 0 <= pontos <= 100:
        raise ErroPerfil("Os pontos vão de 0 a 100.")
    try:
        valido = date.fromisoformat(str(dados['valido_ate'])) if dados.get('valido_ate') else \
            agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)
    except ValueError:
        raise ErroPerfil("Data de validade inválida.")
    if valido < agora.date() or valido > agora.date() + timedelta(days=VALIDADE_MAX_DIAS):
        raise ErroPerfil(f"A validade vai de hoje até {VALIDADE_MAX_DIAS} dias para frente.")
    base, local = CE._endereco()
    if not base or local:
        raise ErroPerfil("Falta o endereço da internet (📢 Clientes › ⚙️ Ajustes › QR do balcão): sem ele o link da "
                         "avaliação não abre no celular.", 409)
    cadastro = {int(f.FuncionarioID): (f.NomeCompleto, getattr(f, 'TelefoneWhatsApp', None)) for f in database.listar_funcionarios()}
    if any(i not in cadastro for i in ids):
        raise ErroPerfil("Alguém da lista não está mais no cadastro. Atualize a página.", 409)
    conn = _conexao()
    try:
        cur = conn.cursor()
        ult, _ = _ultimas_por_pessoa(cur)
        repetidos = [cadastro[i][0] for i in ids if ult.get(i) and ult[i][2] in (ST_AGUARDANDO, ST_ENVIANDO, ST_ENVIADO, ST_FALHOU)]
        if repetidos:
            raise ErroPerfil(f"Já tem avaliação esperando resposta de: {', '.join(repetidos)}. Use 🔔 Lembrar ou ⛔ Cancelar "
                             "a anterior.", 409)
        for i in ids:
            nome, tel = cadastro[i]
            cur.execute("""INSERT INTO AvaliacoesDisc (FuncionarioID, Nome, Telefone, Token, Status, Pontos, CriadoPor, CriadoEm,
                                                       ValidoAte, Versao)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        i, nome, tel, CE._token(), ST_AGUARDANDO if CE.R.numero_whatsapp(tel) else ST_SEM_TEL,
                        pontos, usuario.get('nome'), agora, valido, VERSAO)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"[PERFIL DISC] {usuario.get('nome')} enviou a avaliação para {len(ids)} pessoa(s).")
    no_turno = CE._quem_trabalha_agora(agora)
    ja = [i for i in ids if ('func', i) in no_turno and CE.R.numero_whatsapp(cadastro[i][1])]
    sem_tel = sum(1 for i in ids if not CE.R.numero_whatsapp(cadastro[i][1]))
    _rodar(lambda: processar(agora=agora))
    partes = [f"🧭 Avaliação enviada para {len(ids)} pessoa(s)."]
    if ja:
        partes.append(f"{len(ja)} recebe(m) em instantes.")
    if len(ids) - len(ja) - sem_tel:
        partes.append(f"{len(ids) - len(ja) - sem_tel} recebe(m) {CE.ANTECEDENCIA_MIN} min antes do próximo turno.")
    if sem_tel:
        partes.append(f"📵 {sem_tel} sem WhatsApp no cadastro.")
    return {'ok': True, 'mensagem': ' '.join(partes)}


def processar(agora=None, forcar_ids=None):
    """Uma rodada (o robô chama a cada 2 minutos): expira, devolve à fila o que travou e manda para quem está no horário."""
    garantir_tabelas()
    agora = agora or CE._agora()
    base, local = CE._endereco()
    with _trava:
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE AvaliacoesDisc SET Status = ? WHERE Status IN (?, ?) AND ValidoAte < ?",
                        ST_EXPIRADO, ST_AGUARDANDO, ST_FALHOU, agora.date())
            cur.execute("UPDATE AvaliacoesDisc SET Status = ? WHERE Status = ? AND EnviadoEm < ?",
                        ST_AGUARDANDO, ST_ENVIANDO, agora - timedelta(minutes=CE.ENVIANDO_PRESO_MIN))
            cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Telefone, Token, Pontos, Lembretes FROM AvaliacoesDisc
                           WHERE Status = ? OR (Status = ? AND Tentativas < ?)""", ST_AGUARDANDO, ST_FALHOU, CE.MAX_TENTATIVAS)
            fila = cur.fetchall()
            conn.commit()
        finally:
            conn.close()
        if not fila:
            return 0
        if not base or local:
            logger.warning("[PERFIL DISC] Sem o endereço da internet: as avaliações esperam (o link não abriria no celular).")
            return 0
        forcar = {int(i) for i in (forcar_ids or [])}
        no_turno = CE._quem_trabalha_agora(agora) if len(forcar) < len(fila) else set()
        enviados = 0
        for aid, fid, nome, tel, token, pontos, lembretes in fila:
            if aid not in forcar and ('func', int(fid)) not in no_turno:
                continue
            if not _mudar(aid, (ST_AGUARDANDO, ST_FALHOU), ST_ENVIANDO, EnviadoEm=agora):
                continue                                  # outra rodada (ou o outro programa) já pegou
            if enviados:
                time.sleep(CE.INTERVALO_ENVIO_SEG)
            ok, resp = CE._mandar(tel, texto_mensagem(nome, f"{base}/perfil/{token}", pontos or 0, lembrete=bool(lembretes)))
            if ok:
                _mudar(aid, (ST_ENVIANDO,), ST_ENVIADO, EnviadoEm=agora, Erro=None)
                enviados += 1
            else:
                _mudar(aid, (ST_ENVIANDO,), ST_FALHOU, Erro=str(resp)[:300], soma_tentativa=True)
                logger.error(f"[PERFIL DISC] Não foi para {nome}: {resp}")
        if enviados:
            logger.info(f"[PERFIL DISC] {enviados} avaliação(ões) entregue(s).")
        return enviados


def _mudar(aid, de, para, soma_tentativa=False, **campos):
    """Muda a situação só se ainda estava em 'de' (o agendador e o servidor podem rodar juntos)."""
    sets, args = ["Status = ?"], [para]
    for k, v in campos.items():
        sets.append(f"{k} = ?")
        args.append(v)
    if soma_tentativa:
        sets.append("Tentativas = Tentativas + 1")
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE AvaliacoesDisc SET {', '.join(sets)} WHERE AvaliacaoID = ? AND Status IN ({','.join('?' * len(de))})",
                    *args, int(aid), *de)
        mudou = cur.rowcount == 1
        conn.commit()
        return mudou
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# Painel da gestão
# ------------------------------------------------------------------------------
def _situacao(st, env, ab, resp, lemb, prox, no_turno, erro, tent):
    if st == ST_RESPONDIDO:
        return '✅', f"Respondeu {CE._quando(resp)}"
    if st == ST_ENVIADO:
        return ('👀', f"Abriu {CE._quando(ab)}, ainda não terminou") if ab else ('📤', f"Recebeu {CE._quando(env)}, não abriu ainda")
    if st in (ST_AGUARDANDO, ST_ENVIANDO):
        extra = ' (lembrete)' if lemb else ''
        if no_turno:
            return '⏳', f"Recebe em instantes{extra}"
        return '⏳', (f"Espera o turno: {prox}{extra}" if prox else f"Espera o turno (sem turno na escala ainda){extra}")
    if st == ST_FALHOU:
        return '⚠️', f"WhatsApp falhou ({tent}x): {erro or '?'}" + (" · tenta de novo no turno" if tent < CE.MAX_TENTATIVAS else "")
    if st == ST_EXPIRADO:
        return '⌛', "Expirou sem resposta"
    if st == ST_SEM_TEL:
        return '📵', "Sem WhatsApp no cadastro"
    if st == ST_CANCELADO:
        return '⛔', "Cancelada"
    return '', st


def _pct(linha_pd, linha_pi, linha_ps, linha_pc):
    return {'D': linha_pd or 0, 'I': linha_pi or 0, 'S': linha_ps or 0, 'C': linha_pc or 0}


def painel(agora=None):
    """Envios (todas as avaliações) e a visão da equipe (a última resposta de cada fixo)."""
    garantir_tabelas()
    agora = agora or CE._agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Status, EnviadoEm, AbertoEm, RespondidoEm, Lembretes, Erro,
                              Tentativas, Perfil, PctD, PctI, PctS, PctC, CriadoEm, Pontos, ValidoAte
                       FROM AvaliacoesDisc ORDER BY AvaliacaoID DESC""")
        linhas = cur.fetchall()
    finally:
        conn.close()
    ativos = {int(f.FuncionarioID) for f in database.listar_funcionarios()}
    prox = CE._proximos_turnos(agora)
    no_turno = CE._quem_trabalha_agora(agora)
    envios, equipe, vistos = [], [], set()
    for (aid, fid, nome, st, env, ab, resp, lemb, erro, tent, perfil, pd, pi, ps, pc, criado, pontos, valido) in linhas:
        fid = int(fid)
        ic, txt = _situacao(st, env, ab, resp, lemb, CE._texto_espera(prox.get(('func', fid))), ('func', fid) in no_turno,
                            erro, tent or 0)
        envios.append({'id': aid, 'funcionario_id': fid, 'nome': nome or '?', 'status': st, 'icone': ic, 'situacao': txt,
                       'criado': CE._quando(criado), 'perfil': perfil or '', 'perfil_nome': nome_perfil(perfil) if perfil else '',
                       'pontos': pontos or 0, 'pode_agora': st in (ST_AGUARDANDO, ST_FALHOU, ST_EXPIRADO),
                       'pendente': st in (ST_AGUARDANDO, ST_ENVIANDO, ST_ENVIADO, ST_FALHOU)})
        if st == ST_RESPONDIDO and fid not in vistos and fid in ativos:
            vistos.add(fid)
            pct = _pct(pd, pi, ps, pc)
            equipe.append({'id': aid, 'funcionario_id': fid, 'nome': nome or '?', 'perfil': perfil, 'perfil_nome': nome_perfil(perfil),
                           'pct': pct, 'respondido': CE._quando(resp), 'setores': [s['setor'] for s in setores_da_pessoa(pct)]})
    equipe.sort(key=lambda x: x['nome'].lower())
    return {'envios': envios[:300], 'equipe': equipe, 'resumo_equipe': _resumo_equipe(equipe),
            'pendentes': sum(1 for e in envios if e['pendente'])}


def _resumo_equipe(equipe):
    if not equipe:
        return {'contagem': {d: 0 for d in DIMS}, 'dicas': [], 'por_setor': []}
    contagem = {d: sum(1 for p in equipe if p['perfil'][0] == d) for d in DIMS}
    dicas = [FALTA_NA_EQUIPE[d] for d in DIMS if not any(p['pct'][d] >= 30 for p in equipe)]
    maior = max(DIMS, key=lambda d: contagem[d])
    if len(equipe) >= 3 and contagem[maior] / len(equipe) > .5:
        dicas.append(f"Mais da metade da equipe é {EMOJI[maior]} {NOMES[maior]} ({TEXTOS[maior]['curto']}). "
                     f"Atenção ao que esse perfil tem de ponto fraco: {TEXTOS[maior]['atencao'][0].lower()}.")
    por_setor = []
    for nome, pesos, motivo in SETORES:
        notas = sorted(equipe, key=lambda p: -sum(w * p['pct'][d] for d, w in pesos.items()))
        por_setor.append({'setor': nome, 'motivo': motivo,
                          'pessoas': [{'nome': p['nome'], 'perfil': p['perfil']} for p in notas[:3]]})
    return {'contagem': contagem, 'dicas': dicas, 'por_setor': por_setor}


def detalhe(aid, agora=None):
    """O relatório completo de uma avaliação respondida (e as anteriores da mesma pessoa)."""
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Status, RespondidoEm, Perfil, PctD, PctI, PctS, PctC, CriadoPor
                       FROM AvaliacoesDisc WHERE AvaliacaoID = ?""", int(aid))
        a = cur.fetchone()
        if not a:
            raise ErroPerfil("Avaliação não encontrada.", 404)
        cur.execute("""SELECT AvaliacaoID, RespondidoEm, Perfil FROM AvaliacoesDisc
                       WHERE FuncionarioID = ? AND Status = ? AND AvaliacaoID <> ? ORDER BY AvaliacaoID DESC""",
                    int(a[1]), ST_RESPONDIDO, int(aid))
        antes = cur.fetchall()
    finally:
        conn.close()
    if a[3] != ST_RESPONDIDO:
        raise ErroPerfil("Esta avaliação ainda não foi respondida.", 409)
    pct = _pct(a[6], a[7], a[8], a[9])
    r = relatorio(pct, a[5])
    r.update({'id': a[0], 'nome': a[2] or '?', 'respondido': CE._quando(a[4]), 'perfil_nome': nome_perfil(a[5]),
              'anteriores': [{'id': x[0], 'respondido': CE._quando(x[1]), 'perfil_nome': nome_perfil(x[2])} for x in antes]})
    return r


def acao(aid, nome_acao, usuario, agora=None):
    """🔔 lembrar · 📤 mandar agora (sem esperar o turno) · ⛔ cancelar."""
    garantir_tabelas()
    agora = agora or CE._agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Status, ValidoAte, Nome FROM AvaliacoesDisc WHERE AvaliacaoID = ?", int(aid))
        a = cur.fetchone()
    finally:
        conn.close()
    if not a:
        raise ErroPerfil("Avaliação não encontrada.", 404)
    st, valido, nome = a[0], database._como_data(a[1]), a[2]
    novo_prazo = max(valido, agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)) if valido else agora.date()
    if nome_acao == 'lembrar':
        if st != ST_ENVIADO:
            raise ErroPerfil("Só dá para lembrar quem já recebeu e ainda não respondeu.", 409)
        _mudar(aid, (ST_ENVIADO,), ST_AGUARDANDO, ValidoAte=novo_prazo, Tentativas=0)
        _somar_lembrete(aid)
        _rodar(lambda: processar(agora=agora))
        logger.info(f"[PERFIL DISC] {usuario.get('nome')}: lembrete da avaliação {aid} ({nome}).")
        return {'ok': True, 'mensagem': f"🔔 {nome} recebe o lembrete {CE.ANTECEDENCIA_MIN} min antes do próximo turno "
                                         "(ou em instantes, se já estiver no horário)."}
    if nome_acao == 'agora':
        if st not in (ST_AGUARDANDO, ST_FALHOU, ST_EXPIRADO):
            raise ErroPerfil("Esta avaliação não está esperando envio.", 409)
        _mudar(aid, (ST_AGUARDANDO, ST_FALHOU, ST_EXPIRADO), ST_AGUARDANDO, Tentativas=0,
               ValidoAte=max(valido, agora.date()) if valido else agora.date())
        _rodar(lambda: processar(agora=agora, forcar_ids=[int(aid)]))
        logger.info(f"[PERFIL DISC] {usuario.get('nome')}: avaliação {aid} ({nome}) mandada agora.")
        return {'ok': True, 'mensagem': f"📤 Mandando agora para {nome}, sem esperar o turno."}
    if nome_acao == 'cancelar':
        if not _mudar(aid, (ST_AGUARDANDO, ST_FALHOU, ST_ENVIADO, ST_EXPIRADO, ST_SEM_TEL), ST_CANCELADO, CanceladoEm=agora):
            raise ErroPerfil("Esta avaliação não pode mais ser cancelada.", 409)
        logger.info(f"[PERFIL DISC] {usuario.get('nome')} cancelou a avaliação {aid} ({nome}).")
        return {'ok': True, 'mensagem': f"⛔ Avaliação de {nome} cancelada (o link deixa de funcionar)."}
    raise ErroPerfil("Ação desconhecida.", 404)


def _somar_lembrete(aid):
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE AvaliacoesDisc SET Lembretes = Lembretes + 1 WHERE AvaliacaoID = ?", int(aid))
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# Página do link (pública: o código do link é a chave)
# ------------------------------------------------------------------------------
def _por_token(cur, token):
    if not token or len(str(token)) > 40:
        return None
    cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Status, AbertoEm, Pontos, Perfil, PctD, PctI, PctS, PctC, RespondidoEm
                   FROM AvaliacoesDisc WHERE Token = ?""", str(token))
    return cur.fetchone()


def ver(token, agora=None):
    """O questionário (só as palavras, sem dizer qual é de qual fator) ou, se já respondeu, o resumo da pessoa."""
    garantir_tabelas()
    agora = agora or CE._agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        a = _por_token(cur, token)
        if not a or a[3] in (ST_CANCELADO,):
            raise ErroPerfil("Link inválido ou cancelado. Peça para a gestão mandar de novo.", 404)
        if a[3] == ST_EXPIRADO:
            raise ErroPerfil("O prazo desta avaliação acabou. Peça para a gestão mandar de novo.", 410)
        if not a[4] and a[3] != ST_RESPONDIDO:
            cur.execute("UPDATE AvaliacoesDisc SET AbertoEm = ? WHERE AvaliacaoID = ? AND AbertoEm IS NULL", agora, a[0])
            conn.commit()
    finally:
        conn.close()
    nome = CE._primeiro_nome(a[2])
    if a[3] == ST_RESPONDIDO:
        return {'nome': nome, 'empresa': CE._empresa(), 'respondido': True, 'respondido_em': CE._quando(a[11]),
                'pontos': a[5] or 0, 'resultado': resumo_pessoa(_pct(a[7], a[8], a[9], a[10]), a[6])}
    return {'nome': nome, 'empresa': CE._empresa(), 'respondido': False, 'pontos': a[5] or 0,
            'blocos': [[palavra for palavra, _ in bloco] for bloco in BLOCOS]}


def responder(token, dados, agora=None):
    """Recebe as 24 escolhas [[índice MAIS, índice MENOS], …], calcula, guarda e dá os pontos (uma vez só)."""
    garantir_tabelas()
    agora = agora or CE._agora()
    respostas = (dados or {}).get('respostas')
    if not isinstance(respostas, list) or len(respostas) != N_BLOCOS:
        raise ErroPerfil(f"Responda os {N_BLOCOS} grupos antes de enviar.")
    escolhas = []
    for k, r in enumerate(respostas):
        try:
            mais, menos = int(r[0]), int(r[1])
        except (TypeError, ValueError, IndexError):
            raise ErroPerfil(f"Grupo {k + 1} incompleto: escolha a palavra que MAIS e a que MENOS parece com você.")
        if not (0 <= mais < 4 and 0 <= menos < 4) or mais == menos:
            raise ErroPerfil(f"Grupo {k + 1}: a palavra do MAIS e a do MENOS precisam ser diferentes.")
        escolhas.append((BLOCOS[k][mais][1], BLOCOS[k][menos][1]))
    pct, perfil = calcular(escolhas)
    novo = False
    conn = _conexao()
    try:
        cur = conn.cursor()
        a = _por_token(cur, token)
        if not a or a[3] in (ST_CANCELADO,):
            raise ErroPerfil("Link inválido ou cancelado. Peça para a gestão mandar de novo.", 404)
        if a[3] == ST_EXPIRADO:
            raise ErroPerfil("O prazo desta avaliação acabou. Peça para a gestão mandar de novo.", 410)
        if a[3] != ST_RESPONDIDO:                         # já respondeu (ex.: tocou duas vezes): fica a primeira resposta
            cur.execute("""UPDATE AvaliacoesDisc SET Status = ?, RespondidoEm = ?, AbertoEm = ISNULL(AbertoEm, ?), Respostas = ?,
                                  Versao = ?, PctD = ?, PctI = ?, PctS = ?, PctC = ?, Perfil = ?
                           WHERE AvaliacaoID = ? AND Status <> ?""",
                        ST_RESPONDIDO, agora, agora, json.dumps(escolhas), VERSAO, pct['D'], pct['I'], pct['S'], pct['C'],
                        perfil, a[0], ST_RESPONDIDO)
            novo = cur.rowcount == 1
            conn.commit()
    finally:
        conn.close()
    if novo:
        logger.info(f"[PERFIL DISC] {a[2]} respondeu: {perfil} {pct}.")
        if a[5]:
            try:
                database.registrar_pontos_de_bonus(int(a[1]), int(a[5]), "Avaliação de perfil (DISC) respondida",
                                                   getattr(config, 'TAREFA_ID_LEITURA', 38))
            except Exception as e:
                logger.error(f"[PERFIL DISC] Pontos de {a[2]} não registrados: {e}")
        _avisar_gestao(f"🧭 <b>{_esc(a[2])}</b> respondeu a avaliação de perfil: <b>{_esc(nome_perfil(perfil))}</b> "
                       f"({' · '.join(f'{d} {pct[d]}%' for d in DIMS)}).\n<i>Veja o relatório na Gestão › 🧭 Perfil.</i>")
    return ver(token, agora)


def _avisar_gestao(texto):
    """Aviso no grupo da gestão (desliga em 📣 Avisos › 🧭 Equipe)."""
    def mandar():
        try:
            import alertas_estoque
            if alertas_estoque.aviso_ligado('equipe'):
                alertas_estoque.enviar(texto)
        except Exception as e:
            logger.error(f"[PERFIL DISC] Aviso para a gestão falhou: {e}")
    _rodar(mandar)

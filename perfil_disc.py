# ==============================================================================
# == perfil_disc.py - 🧭 Avaliação de perfil comportamental (DISC) dos fixos ==
# ==============================================================================
# A gestão envia pela Gestão Web (🧭 Perfil) e cada FIXO recebe um LINK no WhatsApp no mesmo horário dos
# 📨 comunicados: a partir de 30 min antes do turno dele (pela escala), fora do intervalo; na folga espera
# o próximo turno. 🧑‍💼 CANDIDATOS do processo seletivo (não estão no cadastro) recebem na hora, sem pontos.
# No link: 24 grupos de 4 palavras; a pessoa toca na que MAIS e na que MENOS combina com ela, em 2 passos
# (antes uma pergunta de treino, que não conta).
# O sistema soma D (Dominante), I (Influente), S (Estável) e C (Conforme) e monta:
#   - o relatório da gestão: o que motiva, o que desmotiva, como conversar, como dar feedback, onde rende
#     mais na loja (pelos setores da escala), pontos de atenção e como liderar;
#   - um resumo POSITIVO para a pessoa (só o perfil e os pontos fortes).
# Questionário NOSSO, baseado na teoria DISC (William Marston, pública). É para conhecer e orientar a
# equipe, não um teste certificado: não serve sozinho para contratar ou demitir.
# Dado pessoal (LGPD): só a gestão vê o relatório; a página do link explica para que serve.
# 🪪 CPF e data de nascimento do candidato: só aparecem num botão da gestão (nunca no aviso do grupo nem no log).
# ==============================================================================
import html
import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta

import config
import database
import comunicados_equipe as CE      # mesmo horário de entrega e mesmos ajudantes (endereço, nome, WhatsApp)

logger = logging.getLogger(__name__)

VERSAO = 3                     # 1: palavras · 2: perguntas do dia a dia · 3: palavras de novo, com a tela nova
DIMS = 'DISC'
NOMES = {'D': 'Dominante', 'I': 'Influente', 'S': 'Estável', 'C': 'Conforme'}
EMOJI = {'D': '🔴', 'I': '🟡', 'S': '🟢', 'C': '🔵'}

# situação de cada avaliação
ST_AGUARDANDO, ST_ENVIANDO, ST_ENVIADO, ST_RESPONDIDO = 'aguardando', 'enviando', 'enviado', 'respondido'
ST_FALHOU, ST_EXPIRADO, ST_SEM_TEL, ST_CANCELADO = 'falhou', 'expirado', 'sem_telefone', 'cancelado'
VALIDADE_PADRAO_DIAS, VALIDADE_MAX_DIAS = 7, 30
SEGUNDO_PLANO = True           # os testes desligam para conferir na hora
TIPO_FUNC, TIPO_CAND = 'func', 'candidato'   # fixo do cadastro · candidato do processo seletivo

# 📸 Trabalhe conosco (página pública do Instagram): áreas, disponibilidade e etapas do candidato
AREAS = [('atendimento', '🍦 Atendimento'), ('cozinha', '👩‍🍳 Cozinha'), ('zeladoria', '🧹 Zeladoria (limpeza)'),
         ('camara', '❄️ Câmara Fria / Repositor'), ('freelancer', '📅 Freelancer (diárias)')]
AREAS_FORM = [a for a in AREAS if a[0] != 'freelancer']   # "freelancer" virou o tipo de vaga (fica só para cadastros antigos)
TIPOS_VAGA = [('fixa', '💼 Vaga fixa'), ('freela', '📅 Freelancer (diárias)'), ('ambos', '🔁 Fixa ou freelancer')]
DISPONIBILIDADE = [('manha', 'Manhã'), ('tarde', 'Tarde'), ('noite', 'Noite'), ('fds', 'Fins de semana e feriados')]
ETAPAS = [('novo', '🆕 Novo'), ('entrevista', '📞 Entrevista'), ('contratado', '✅ Contratado'), ('nao', '❌ Não seguiu')]
ORIGEM_SITE, ORIGEM_GESTAO = 'site', 'gestao'
CADASTROS_POR_IP = (5, 3600)   # no máximo 5 cadastros por hora no mesmo aparelho
CADASTROS_POR_DIA = 300
DIAS_MESMO_CADASTRO = 60       # o mesmo WhatsApp (ou CPF) de novo em até 60 dias: atualiza o cadastro em vez de criar outro
IDADE_MIN, IDADE_MAX = 14, 80
_trava_cadastro = threading.Lock()
_cadastros_por_ip, _cadastros_do_dia = {}, {'dia': None, 'n': 0}

# Palavras de cada fator (24 cada). Cada grupo do questionário tem uma de cada, numa ordem diferente.
# (v3: voltaram as palavras da v1, com a tela nova: passos 👍/👎, treino e 🔊 Ouvir)
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
ENUNCIADOS = ['No trabalho, eu sou…'] * len(BLOCOS)
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
    ('Recepção', {'I': .6, 'S': .3, 'D': .1}, 'receber quem chega com simpatia e explicar como funciona o buffet'),
    ('Frente Loja', {'I': .5, 'S': .25, 'D': .25}, 'atender no balcão, sugerir sabores e vender mais'),
    ('Salão', {'S': .45, 'I': .35, 'C': .2}, 'manter o salão em ordem e atender as mesas com calma'),
    ('Varanda', {'I': .5, 'S': .3, 'D': .2}, 'contato com o cliente e movimento'),
    ('Buffet', {'S': .4, 'C': .4, 'D': .2}, 'repor no ritmo certo e manter a apresentação no padrão'),
    ('Cozinha', {'C': .5, 'S': .4, 'D': .1}, 'seguir receita e higiene, sempre do mesmo jeito'),
    ('Limpeza', {'S': .5, 'C': .5}, 'rotina caprichada, sem pular etapa'),
    ('Camara Fria', {'C': .6, 'S': .3, 'D': .1}, 'organização, validade e contagem do estoque'),
    ('Liderança de turno', {'D': .5, 'I': .3, 'C': .2}, 'decidir rápido no pico e puxar a equipe'),
]
# O que cada fator traz para cada função (para explicar o PORQUÊ de combinar ou não)
NECESSIDADES = {
    'Caixa': {'C': 'atenção com dinheiro, troco e cupom', 'I': 'simpatia no fim do atendimento', 'S': 'calma com a fila'},
    'Recepção': {'I': 'conversar e receber quem chega com simpatia', 'S': 'paciência para explicar o buffet muitas vezes',
                 'D': 'agilidade quando chega muita gente junto'},
    'Frente Loja': {'I': 'puxar conversa e sugerir sabores (vender mais)', 'S': 'paciência com o cliente indeciso',
                    'D': 'agilidade no horário de pico'},
    'Salão': {'S': 'calma e constância para cuidar do salão', 'I': 'simpatia com as mesas', 'C': 'capricho com a organização'},
    'Varanda': {'I': 'contato o tempo todo com o cliente', 'S': 'paciência com o movimento', 'D': 'agilidade quando enche'},
    'Buffet': {'S': 'ritmo constante de reposição', 'C': 'padrão de apresentação e validade', 'D': 'rapidez para repor no pico'},
    'Cozinha': {'C': 'seguir receita e higiene à risca', 'S': 'constância, sempre do mesmo jeito', 'D': 'agilidade quando aperta'},
    'Limpeza': {'S': 'rotina sem pular etapa', 'C': 'capricho nos detalhes'},
    'Camara Fria': {'C': 'organização, validade e contagem do estoque', 'S': 'rotina e paciência (é um trabalho mais sozinho)',
                    'D': 'agilidade para repor'},
    'Liderança de turno': {'D': 'decidir rápido e assumir a frente', 'I': 'puxar e animar a equipe', 'C': 'cobrar o padrão'},
}
# Quando um fator MUITO forte atrapalha a função (mesmo combinando no resto)
CONFLITOS = {
    'Camara Fria': {'I': 'é um trabalho mais sozinho, e quem é muito 🟡 Influente desanima sem gente para conversar'},
    'Limpeza': {'D': 'é rotina repetitiva, e quem é muito 🔴 Dominante perde o interesse sem desafio',
                'I': 'é um trabalho mais sozinho, e quem é muito 🟡 Influente desanima sem gente para conversar'},
    'Caixa': {'D': 'pede conferir tudo com paciência, e quem é muito 🔴 Dominante pode querer pular etapa'},
    'Cozinha': {'I': 'fica longe do cliente, e quem é muito 🟡 Influente sente falta de conversar'},
}
NIVEIS = {'combina': '✅ Combina muito', 'pode': '🟡 Pode funcionar', 'menos': '⚠️ Menos indicado'}

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
        # 🧑‍💼 processo seletivo: candidato (fora do cadastro, FuncionarioID 0) e a vaga
        cur.execute("IF COL_LENGTH('AvaliacoesDisc', 'Tipo') IS NULL ALTER TABLE AvaliacoesDisc ADD Tipo VARCHAR(10) NULL")
        cur.execute("IF COL_LENGTH('AvaliacoesDisc', 'Vaga') IS NULL ALTER TABLE AvaliacoesDisc ADD Vaga NVARCHAR(100) NULL")
        # pontos que já foram para o SALDO da pessoa (o que ela troca por prêmios); vazio = ainda falta pôr
        cur.execute("IF COL_LENGTH('AvaliacoesDisc', 'SaldoOk') IS NULL ALTER TABLE AvaliacoesDisc ADD SaldoOk BIT NULL")
        # 📸 Trabalhe conosco: os dados que o candidato preenche e a etapa dele no processo seletivo
        for coluna, tipo in (('Origem', 'VARCHAR(10)'), ('Areas', 'VARCHAR(100)'), ('Idade', 'INT'), ('Bairro', 'NVARCHAR(100)'),
                             ('Disponibilidade', 'VARCHAR(60)'), ('Experiencia', 'NVARCHAR(600)'), ('Etapa', 'VARCHAR(12)'),
                             ('AceiteEm', 'DATETIME'), ('TipoVaga', 'VARCHAR(10)'), ('Cpf', 'VARCHAR(11)'), ('Nascimento', 'DATE')):
            cur.execute(f"IF COL_LENGTH('AvaliacoesDisc', '{coluna}') IS NULL ALTER TABLE AvaliacoesDisc ADD {coluna} {tipo} NULL")
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
    escolhas: [(fator MAIS, fator MENOS)] dos grupos. Mais = +1, menos = −1; com 24 grupos cada fator vai de −24 a +24.
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


def funcoes_da_pessoa(pct):
    """
    TODAS as funções da loja para esta pessoa, da que mais combina para a que menos, com o nível e o PORQUÊ:
    ✅ combina muito · 🟡 pode funcionar (com treino) · ⚠️ menos indicado (diz qual fator falta).
    """
    saida = []
    for nome, pesos, motivo in SETORES:
        nota = sum(peso * pct[d] for d, peso in pesos.items())
        nec, ordem = NECESSIDADES.get(nome, {}), sorted(pesos, key=lambda d: -pesos[d])
        forte = max(ordem, key=lambda d: pesos[d] * pct[d])            # o fator dela que mais ajuda nesta função
        falta = max(ordem, key=lambda d: pesos[d] * (25 - pct[d]))     # o fator que a função pede e ela tem pouco
        fator = lambda d: f"{EMOJI[d]} {NOMES[d]} {pct[d]}%"
        nivel = 'combina' if nota >= 30 else ('pode' if nota >= 22 else 'menos')
        if nivel == 'combina':
            porque = f"Pede {nec.get(forte, motivo)}, e isso é um ponto forte do perfil ({fator(forte)})."
        elif nivel == 'menos':
            porque = f"Pede {nec.get(falta, motivo)}, e esse é um fator baixo no perfil ({fator(falta)})."
        elif pct[falta] < 25 and falta != forte:
            porque = (f"A favor: {nec.get(forte, motivo)} ({fator(forte)}). Vai precisar de treino em: {nec.get(falta, '')} "
                      f"({fator(falta)}).")
        else:
            porque = f"Dá para fazer: pede {nec.get(forte, motivo)} ({fator(forte)}), sem ser o ponto mais forte do perfil."
        for d, aviso in CONFLITOS.get(nome, {}).items():
            if pct[d] >= 40:                                            # fator muito forte que atrapalha: desce um nível
                nivel = {'combina': 'pode', 'pode': 'menos'}.get(nivel, nivel)
                porque += f" Atenção: {aviso}."
        saida.append({'setor': nome, 'nivel': nivel, 'nivel_nome': NIVEIS[nivel], 'porque': porque, 'nota': round(nota, 1)})
    ordem_nivel = {'combina': 0, 'pode': 1, 'menos': 2}
    saida.sort(key=lambda x: (ordem_nivel[x['nivel']], -x['nota']))
    return saida


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
        'setores': setores_da_pessoa(pct), 'funcoes_loja': funcoes_da_pessoa(pct),
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
                   FROM AvaliacoesDisc WHERE ISNULL(Tipo, ?) = ? ORDER BY AvaliacaoID""", TIPO_FUNC, TIPO_FUNC)
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
            'perguntas': N_BLOCOS,
            'dias_escalados_max': base['dias_escalados_max'], 'link_local': base['link_local'],
            'validade_padrao': (agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)).isoformat(),
            'validade_max': (agora.date() + timedelta(days=VALIDADE_MAX_DIAS)).isoformat()}


# ------------------------------------------------------------------------------
# Enviar
# ------------------------------------------------------------------------------
def texto_mensagem(nome, link, pontos=0, lembrete=False, candidato=False):
    primeiro = CE._primeiro_nome(nome)
    return ((f"🔔 *Lembrete:* sua avaliação de perfil ainda está esperando você.\n\n" if lembrete else "")
            + f"🧭 *Avaliação de perfil — {CE._empresa()}*\n\n"
            + (f"Olá, {primeiro}!\n" if primeiro else "Olá!\n")
            + ("Obrigado pelo interesse em trabalhar com a gente! Como parte do processo seletivo, queremos conhecer o "
               "seu jeito de trabalhar. São " if candidato else
               "Queremos te conhecer melhor para organizar a equipe do jeito que combina com você. São ")
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
    if pontos < 0:
        raise ErroPerfil("Os pontos não podem ser negativos.")
    if pontos > CE.PONTOS_MAX:
        raise ErroPerfil(f"Pontos demais (máximo {CE.PONTOS_MAX:,}).".replace(',', '.'))
    valido = _validade(dados, agora)
    _exigir_endereco()
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
                                                       ValidoAte, Versao, Tipo)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        i, nome, tel, CE._token(), ST_AGUARDANDO if CE.R.numero_whatsapp(tel) else ST_SEM_TEL,
                        pontos, usuario.get('nome'), agora, valido, VERSAO, TIPO_FUNC)
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


def _validade(dados, agora):
    try:
        valido = date.fromisoformat(str(dados['valido_ate'])) if dados.get('valido_ate') else \
            agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)
    except ValueError:
        raise ErroPerfil("Data de validade inválida.")
    if valido < agora.date() or valido > agora.date() + timedelta(days=VALIDADE_MAX_DIAS):
        raise ErroPerfil(f"A validade vai de hoje até {VALIDADE_MAX_DIAS} dias para frente.")
    return valido


def _exigir_endereco():
    base, local = CE._endereco()
    if not base or local:
        raise ErroPerfil("Falta o endereço da internet (📢 Clientes › ⚙️ Ajustes › QR do balcão): sem ele o link da "
                         "avaliação não abre no celular.", 409)
    return base


def candidato_criar(dados, usuario, agora=None):
    """🧑‍💼 Processo seletivo: candidato (fora do cadastro) recebe o link na hora no WhatsApp, sem pontos.
    Sem WhatsApp: a gestão copia o link e manda como quiser."""
    garantir_tabelas()
    agora = agora or CE._agora()
    nome = ' '.join(str(dados.get('nome') or '').split())
    vaga = ' '.join(str(dados.get('vaga') or '').split())
    tipo_vaga = str(dados.get('tipo_vaga') or '').strip() or None
    if tipo_vaga and tipo_vaga not in dict(TIPOS_VAGA):
        raise ErroPerfil("Tipo de vaga inválido.")
    tel_txt = str(dados.get('telefone') or '').strip()
    if not nome:
        raise ErroPerfil("Escreva o nome do candidato.")
    if len(nome) > 150 or len(vaga) > 100:
        raise ErroPerfil("Nome ou vaga grande demais.")
    tel = CE.R.numero_whatsapp(tel_txt) if tel_txt else ''
    if tel_txt and not tel:
        raise ErroPerfil(f"WhatsApp inválido: '{tel_txt}'. Use o DDD + o número (ex.: 66 99999-1234).")
    valido = _validade(dados, agora)
    cpf, nasc, idade = _documentos(dados, agora)
    base = _exigir_endereco()
    token = CE._token()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO AvaliacoesDisc (FuncionarioID, Nome, Telefone, Token, Status, Pontos, CriadoPor, CriadoEm,
                                                   ValidoAte, Versao, Tipo, Vaga, Origem, Etapa, TipoVaga, Cpf, Nascimento, Idade)
                       VALUES (0, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?); SELECT SCOPE_IDENTITY();""",
                    nome, tel or None, token, ST_AGUARDANDO if tel else ST_SEM_TEL, usuario.get('nome'), agora, valido,
                    VERSAO, TIPO_CAND, vaga or None, ORIGEM_GESTAO, 'novo', tipo_vaga, cpf, nasc, idade)
        cur.nextset()
        aid = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[PERFIL DISC] {usuario.get('nome')} mandou a avaliação para o candidato {aid}.")
    if tel:
        _rodar(lambda: processar(agora=agora, forcar_ids=[aid]))
    return {'ok': True, 'id': aid, 'link': f"{base}/perfil/{token}",
            'mensagem': f"🧑‍💼 Avaliação de {nome} criada." + (" O link vai no WhatsApp agora." if tel else
                                                               " Sem WhatsApp: copie o link e mande você mesmo.")}


def processar(agora=None, forcar_ids=None):
    """Uma rodada (o robô chama a cada 2 minutos): expira, devolve à fila o que travou e manda para quem está no horário."""
    garantir_tabelas()
    agora = agora or CE._agora()
    base, local = CE._endereco()
    if not forcar_ids:                                    # rodada do robô: acerta o saldo de quem ainda não recebeu
        try:
            creditar_saldo()
        except Exception as e:
            logger.error(f"[PERFIL DISC] Acerto do saldo de pontos falhou: {e}")
    with _trava:
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE AvaliacoesDisc SET Status = ? WHERE Status IN (?, ?) AND ValidoAte < ?",
                        ST_EXPIRADO, ST_AGUARDANDO, ST_FALHOU, agora.date())
            cur.execute("UPDATE AvaliacoesDisc SET Status = ? WHERE Status = ? AND EnviadoEm < ?",
                        ST_AGUARDANDO, ST_ENVIANDO, agora - timedelta(minutes=CE.ENVIANDO_PRESO_MIN))
            cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Telefone, Token, Pontos, Lembretes, Tipo FROM AvaliacoesDisc
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
        for aid, fid, nome, tel, token, pontos, lembretes, tipo in fila:
            candidato = tipo == TIPO_CAND                 # candidato não tem escala: vai na hora
            if not candidato and aid not in forcar and ('func', int(fid)) not in no_turno:
                continue
            if not _mudar(aid, (ST_AGUARDANDO, ST_FALHOU), ST_ENVIANDO, EnviadoEm=agora):
                continue                                  # outra rodada (ou o outro programa) já pegou
            if enviados:
                time.sleep(CE.INTERVALO_ENVIO_SEG)
            ok, resp = CE._mandar(tel, texto_mensagem(nome, f"{base}/perfil/{token}", 0 if candidato else (pontos or 0),
                                                      lembrete=bool(lembretes), candidato=candidato))
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
def _situacao(st, env, ab, resp, lemb, prox, no_turno, erro, tent, candidato=False):
    if candidato and st in (ST_AGUARDANDO, ST_ENVIANDO):
        return '⏳', "Enviando no WhatsApp…"
    if candidato and st == ST_SEM_TEL:
        return '🔗', "Sem WhatsApp: copie o link e mande você mesmo"
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
    """Envios dos fixos, a visão da equipe (a última resposta de cada fixo) e os 🧑‍💼 candidatos do processo seletivo."""
    garantir_tabelas()
    agora = agora or CE._agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Status, EnviadoEm, AbertoEm, RespondidoEm, Lembretes, Erro,
                              Tentativas, Perfil, PctD, PctI, PctS, PctC, CriadoEm, Pontos, ValidoAte, Tipo, Vaga, Telefone, Token,
                              Origem, Areas, Idade, Bairro, Disponibilidade, Experiencia, Etapa, TipoVaga, Cpf, Nascimento
                       FROM AvaliacoesDisc ORDER BY AvaliacaoID DESC""")
        linhas = cur.fetchall()
    finally:
        conn.close()
    ativos = {int(f.FuncionarioID) for f in database.listar_funcionarios()}
    prox = CE._proximos_turnos(agora)
    no_turno = CE._quem_trabalha_agora(agora)
    base = CE._endereco()[0]
    envios, equipe, candidatos, vistos = [], [], [], set()
    for (aid, fid, nome, st, env, ab, resp, lemb, erro, tent, perfil, pd, pi, ps, pc, criado, pontos, valido,
         tipo, vaga, tel, token, origem, areas, idade, bairro, dispon, exper, etapa, tipo_vaga, cpf, nasc) in linhas:
        fid, candidato = int(fid), tipo == TIPO_CAND
        ic, txt = _situacao(st, env, ab, resp, lemb, CE._texto_espera(prox.get(('func', fid))), ('func', fid) in no_turno,
                            erro, tent or 0, candidato)
        item = {'id': aid, 'funcionario_id': fid, 'nome': nome or '?', 'status': st, 'icone': ic, 'situacao': txt,
                'criado': CE._quando(criado), 'perfil': perfil or '', 'perfil_nome': nome_perfil(perfil) if perfil else '',
                'pontos': pontos or 0, 'pode_agora': st in (ST_AGUARDANDO, ST_FALHOU, ST_EXPIRADO) and (not candidato or bool(tel)),
                'pendente': st in (ST_AGUARDANDO, ST_ENVIANDO, ST_ENVIADO, ST_FALHOU) or (candidato and st == ST_SEM_TEL),
                'link': f"{base}/perfil/{token}" if st not in (ST_RESPONDIDO, ST_CANCELADO, ST_EXPIRADO) else ''}
        if candidato:
            site = origem == ORIGEM_SITE
            if site and st == ST_ENVIADO:                 # cadastrou pelo Instagram e ainda está no questionário
                item.update(icone='⏳', situacao=f"Ainda não terminou o questionário (cadastro {CE._quando(criado)})")
            item.update(origem=origem or ORIGEM_GESTAO, areas=_rotulos(AREAS, areas), idade=_idade_hoje(nasc, idade, agora),
                        documentos=bool(cpf) and bool(nasc), bairro=bairro or '',
                        disponibilidade=_rotulos(DISPONIBILIDADE, dispon), experiencia=exper or '',
                        etapa=etapa or 'novo', etapa_nome=dict(ETAPAS).get(etapa or 'novo', ''), **_tipo_vaga(tipo_vaga, areas),
                        whatsapp=f"https://wa.me/{tel}" if tel else '')
            item.update(vaga=vaga or '', telefone=tel or '',
                        pct=_pct(pd, pi, ps, pc) if st == ST_RESPONDIDO else None,
                        setores=[x['setor'] for x in setores_da_pessoa(_pct(pd, pi, ps, pc))] if st == ST_RESPONDIDO else [])
            candidatos.append(item)
            continue
        envios.append(item)
        if st == ST_RESPONDIDO and fid not in vistos and fid in ativos:
            vistos.add(fid)
            pct = _pct(pd, pi, ps, pc)
            equipe.append({'id': aid, 'funcionario_id': fid, 'nome': nome or '?', 'perfil': perfil, 'perfil_nome': nome_perfil(perfil),
                           'pct': pct, 'respondido': CE._quando(resp), 'setores': [s['setor'] for s in setores_da_pessoa(pct)]})
    equipe.sort(key=lambda x: x['nome'].lower())
    for c in candidatos:
        c['completa'] = _o_que_completa(c['pct'], equipe) if c['pct'] else []
    return {'envios': envios[:300], 'equipe': equipe, 'resumo_equipe': _resumo_equipe(equipe),
            'pendentes': sum(1 for e in envios if e['pendente']), 'candidatos': candidatos[:500],
            'areas': [{'chave': c, 'nome': n} for c, n in AREAS_FORM], 'etapas': [{'chave': c, 'nome': n} for c, n in ETAPAS],
            'tipos_vaga': [{'chave': c, 'nome': n} for c, n in TIPOS_VAGA],
            'link_trabalhe': f"{base}/trabalhe-conosco" if base else ''}


def _tipo_vaga(guardado, areas):
    """Fixa, freelancer ou os dois. Cadastro antigo (antes da pergunta): quem marcou a área Freelancer conta como freelancer."""
    tv = guardado if guardado in dict(TIPOS_VAGA) else ('freela' if 'freelancer' in str(areas or '').split(',') else '')
    return {'tipo_vaga': tv, 'tipo_vaga_nome': dict(TIPOS_VAGA).get(tv, '❔ Não informou'),
            'tipo_vaga_informado': guardado in dict(TIPOS_VAGA)}


def _rotulos(opcoes, guardado):
    nomes = dict(opcoes)
    return [{'chave': c, 'nome': nomes[c]} for c in str(guardado or '').split(',') if c in nomes]


def _o_que_completa(pct, equipe):
    """Os fatores fortes do candidato (30% ou mais) que ninguém da equipe tem forte: o que ele traz de novo."""
    if not equipe:
        return []
    return [{'d': d, 'nome': NOMES[d], 'emoji': EMOJI[d], 'curto': TEXTOS[d]['curto']}
            for d in DIMS if pct[d] >= 30 and not any(p['pct'][d] >= 30 for p in equipe)]


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
    agora = agora or CE._agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Status, RespondidoEm, Perfil, PctD, PctI, PctS, PctC, CriadoPor,
                              Tipo, Vaga, Origem, Areas, Idade, Bairro, Disponibilidade, Experiencia, Telefone, TipoVaga,
                              Nascimento
                       FROM AvaliacoesDisc WHERE AvaliacaoID = ?""", int(aid))
        a = cur.fetchone()
        if not a:
            raise ErroPerfil("Avaliação não encontrada.", 404)
        antes = []
        if a[11] != TIPO_CAND:
            cur.execute("""SELECT AvaliacaoID, RespondidoEm, Perfil FROM AvaliacoesDisc
                           WHERE FuncionarioID = ? AND Status = ? AND AvaliacaoID <> ? AND ISNULL(Tipo, ?) = ?
                           ORDER BY AvaliacaoID DESC""", int(a[1]), ST_RESPONDIDO, int(aid), TIPO_FUNC, TIPO_FUNC)
            antes = cur.fetchall()
    finally:
        conn.close()
    if a[3] != ST_RESPONDIDO:
        raise ErroPerfil("Esta avaliação ainda não foi respondida.", 409)
    pct = _pct(a[6], a[7], a[8], a[9])
    r = relatorio(pct, a[5])
    candidato = a[11] == TIPO_CAND
    r.update({'id': a[0], 'nome': a[2] or '?', 'respondido': CE._quando(a[4]), 'perfil_nome': nome_perfil(a[5]),
              'candidato': candidato, 'vaga': a[12] or '',
              'anteriores': [{'id': x[0], 'respondido': CE._quando(x[1]), 'perfil_nome': nome_perfil(x[2])} for x in antes]})
    if candidato:
        r['completa'] = _o_que_completa(pct, painel(agora)['equipe'])
        r.update(origem=a[13] or ORIGEM_GESTAO, areas=_rotulos(AREAS, a[14]), idade=_idade_hoje(a[21], a[15], agora),
                 bairro=a[16] or '',
                 disponibilidade=_rotulos(DISPONIBILIDADE, a[17]), experiencia=a[18] or '',
                 whatsapp=f"https://wa.me/{a[19]}" if a[19] else '', **_tipo_vaga(a[20], a[14]))
    return r


def acao(aid, nome_acao, usuario, agora=None):
    """🔔 lembrar · 📤 mandar agora (sem esperar o turno) · ⛔ cancelar."""
    garantir_tabelas()
    agora = agora or CE._agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Status, ValidoAte, Nome, Tipo, Telefone FROM AvaliacoesDisc WHERE AvaliacaoID = ?", int(aid))
        a = cur.fetchone()
    finally:
        conn.close()
    if not a:
        raise ErroPerfil("Avaliação não encontrada.", 404)
    st, valido, nome, candidato = a[0], database._como_data(a[1]), a[2], a[3] == TIPO_CAND
    if nome_acao == 'apagar':
        if not candidato:
            raise ErroPerfil("Só dá para apagar avaliação de candidato.", 409)
        conn = _conexao()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM AvaliacoesDisc WHERE AvaliacaoID = ? AND Tipo = ?", int(aid), TIPO_CAND)
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[PERFIL DISC] {usuario.get('nome')} apagou a avaliação do candidato {aid}.")
        return {'ok': True, 'mensagem': f"🗑️ Candidato {nome} apagado (nome, WhatsApp, CPF, nascimento e respostas)."}
    if candidato and nome_acao in ('lembrar', 'agora') and not a[4]:
        raise ErroPerfil("Candidato sem WhatsApp: copie o link e mande você mesmo.", 409)
    novo_prazo = max(valido, agora.date() + timedelta(days=VALIDADE_PADRAO_DIAS)) if valido else agora.date()
    if nome_acao == 'lembrar':
        if st != ST_ENVIADO:
            raise ErroPerfil("Só dá para lembrar quem já recebeu e ainda não respondeu.", 409)
        _mudar(aid, (ST_ENVIADO,), ST_AGUARDANDO, ValidoAte=novo_prazo, Tentativas=0)
        _somar_lembrete(aid)
        _rodar(lambda: processar(agora=agora))
        logger.info(f"[PERFIL DISC] {usuario.get('nome')}: lembrete da avaliação {aid} ({nome}).")
        return {'ok': True, 'mensagem': f"🔔 {nome} recebe o lembrete " + ("agora." if candidato else
                f"{CE.ANTECEDENCIA_MIN} min antes do próximo turno (ou em instantes, se já estiver no horário).")}
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
    cur.execute("""SELECT AvaliacaoID, FuncionarioID, Nome, Status, AbertoEm, Pontos, Perfil, PctD, PctI, PctS, PctC, RespondidoEm,
                          Tipo, Vaga, Origem, TipoVaga
                   FROM AvaliacoesDisc WHERE Token = ?""", str(token))
    return cur.fetchone()


def ver(token, agora=None):
    """O questionário (só os textos, sem dizer qual resposta é de qual fator) ou, se já respondeu, o resumo da pessoa."""
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
    nome, candidato = CE._primeiro_nome(a[2]), a[12] == TIPO_CAND
    if a[3] == ST_RESPONDIDO:
        if candidato:                                     # candidato: só o obrigado (o resultado fica com a gestão)
            return {'nome': nome, 'empresa': CE._empresa(), 'respondido': True, 'respondido_em': CE._quando(a[11]),
                    'candidato': True, 'pontos': 0}
        return {'nome': nome, 'empresa': CE._empresa(), 'respondido': True, 'respondido_em': CE._quando(a[11]),
                'pontos': a[5] or 0, 'resultado': resumo_pessoa(_pct(a[7], a[8], a[9], a[10]), a[6])}
    return {'nome': nome, 'empresa': CE._empresa(), 'respondido': False, 'pontos': 0 if candidato else (a[5] or 0),
            'candidato': candidato,
            'blocos': [{'pergunta': ENUNCIADOS[k], 'opcoes': [texto for texto, _ in bloco]} for k, bloco in enumerate(BLOCOS)]}


def responder(token, dados, agora=None):
    """Recebe as escolhas [[índice MAIS, índice MENOS], …] de cada pergunta, calcula, guarda e dá os pontos (uma vez só)."""
    garantir_tabelas()
    agora = agora or CE._agora()
    respostas = (dados or {}).get('respostas')
    if not isinstance(respostas, list) or len(respostas) != N_BLOCOS:
        raise ErroPerfil(f"Responda as {N_BLOCOS} perguntas antes de enviar.")
    escolhas = []
    for k, r in enumerate(respostas):
        try:
            mais, menos = int(r[0]), int(r[1])
        except (TypeError, ValueError, IndexError):
            raise ErroPerfil(f"Pergunta {k + 1} incompleta: escolha a resposta que MAIS e a que MENOS combina com você.")
        if not (0 <= mais < 4 and 0 <= menos < 4) or mais == menos:
            raise ErroPerfil(f"Pergunta {k + 1}: a resposta do MAIS e a do MENOS precisam ser diferentes.")
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
        if a[5] and a[12] != TIPO_CAND:
            try:                                          # igual aos comunicados do Telegram: histórico/ranking + saldo
                database.registrar_pontos_de_bonus(int(a[1]), int(a[5]), "Avaliação de perfil (DISC) respondida",
                                                   getattr(config, 'TAREFA_ID_LEITURA', 38))
            except Exception as e:
                logger.error(f"[PERFIL DISC] Pontos de {a[2]} não registrados: {e}")
            creditar_saldo(a[0])
        quem = (("📸 Trabalhe conosco: " if a[14] == ORIGEM_SITE else "🧑‍💼 Candidato ") + f"<b>{_esc(a[2])}</b>"
                + (f" ({_esc(a[13])})" if a[13] else '')
                + (f" · {dict(TIPOS_VAGA)[a[15]]}" if a[15] in dict(TIPOS_VAGA) else '')) if a[12] == TIPO_CAND \
            else f"🧭 <b>{_esc(a[2])}</b>"
        _avisar_gestao(f"{quem} respondeu a avaliação de perfil: <b>{_esc(nome_perfil(perfil))}</b> "
                       f"({' · '.join(f'{d} {pct[d]}%' for d in DIMS)}).\n<i>Veja o relatório na Gestão › 🧭 Perfil.</i>")
    return ver(token, agora)


def creditar_saldo(avaliacao_id=None):
    """
    Põe no SALDO de pontos (o que a pessoa troca por prêmios) os pontos de quem respondeu e ainda não recebeu.
    Uma vez só: marca SaldoOk antes de somar. Sem avaliacao_id: acerta todos os que faltam (o robô chama a cada rodada;
    assim quem respondeu antes desta correção também recebe). Candidato não ganha pontos.
    """
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        sql = """SELECT AvaliacaoID, FuncionarioID, Pontos, Nome FROM AvaliacoesDisc
                 WHERE Status = ? AND ISNULL(Tipo, ?) = ? AND Pontos > 0 AND SaldoOk IS NULL"""
        args = [ST_RESPONDIDO, TIPO_FUNC, TIPO_FUNC]
        if avaliacao_id:
            sql += " AND AvaliacaoID = ?"
            args.append(int(avaliacao_id))
        cur.execute(sql, *args)
        faltam = cur.fetchall()
    finally:
        conn.close()
    feitos = 0
    for aid, fid, pontos, nome in faltam:
        if not _marcar_saldo(aid, 1):
            continue                                      # outro programa já pôs
        try:
            if database.adicionar_pontos_ao_saldo(int(fid), int(pontos)) is False:
                raise RuntimeError("sem conexão")
            feitos += 1
            logger.info(f"[PERFIL DISC] +{pontos} pontos no saldo de {nome}.")
        except Exception as e:
            _marcar_saldo(aid, None)                      # tenta de novo na próxima rodada
            logger.error(f"[PERFIL DISC] Pontos de {nome} não foram para o saldo: {e}")
    return feitos


def _marcar_saldo(aid, valor):
    conn = _conexao()
    try:
        cur = conn.cursor()
        if valor:
            cur.execute("UPDATE AvaliacoesDisc SET SaldoOk = 1 WHERE AvaliacaoID = ? AND SaldoOk IS NULL", int(aid))
        else:
            cur.execute("UPDATE AvaliacoesDisc SET SaldoOk = NULL WHERE AvaliacaoID = ?", int(aid))
        ok = cur.rowcount == 1
        conn.commit()
        return ok
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# 📸 Trabalhe conosco: página pública (link da bio do Instagram) — a pessoa se cadastra e faz o questionário
# ------------------------------------------------------------------------------
def trabalhe_dados():
    """O que a página pública precisa (sem nenhum dado de ninguém)."""
    return {'empresa': CE._empresa(), 'areas': [{'chave': c, 'nome': n} for c, n in AREAS_FORM],
            'tipos_vaga': [{'chave': c, 'nome': n} for c, n in TIPOS_VAGA],
            'disponibilidade': [{'chave': c, 'nome': n} for c, n in DISPONIBILIDADE], 'grupos': N_BLOCOS}


def _limite_ip(ip):
    agora = time.time()
    with _trava_cadastro:
        hoje = date.today()
        if _cadastros_do_dia['dia'] != hoje:
            _cadastros_do_dia.update(dia=hoje, n=0)
        if _cadastros_do_dia['n'] >= CADASTROS_POR_DIA:
            return False
        tentativas = [t for t in _cadastros_por_ip.get(ip, []) if agora - t < CADASTROS_POR_IP[1]]
        if len(tentativas) >= CADASTROS_POR_IP[0]:
            _cadastros_por_ip[ip] = tentativas
            return False
        tentativas.append(agora)
        _cadastros_por_ip[ip] = tentativas
        _cadastros_do_dia['n'] += 1
        if len(_cadastros_por_ip) > 5000:
            _cadastros_por_ip.clear()
        return True


def _cpf(valor):
    """Os 11 números do CPF, se os 2 dígitos verificadores batem; senão ''."""
    n = re.sub(r'\D', '', str(valor or ''))
    if len(n) != 11 or n == n[0] * 11:
        return ''
    for tam in (9, 10):
        soma = sum(int(n[i]) * (tam + 1 - i) for i in range(tam))
        if soma * 10 % 11 % 10 != int(n[tam]):
            return ''
    return n


def _cpf_formatado(n):
    return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}" if n and len(n) == 11 else ''


def _anos(nasc, hoje):
    return hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))


def _data_nascimento(valor):
    """DD/MM/AAAA (o que a pessoa digita) ou AAAA-MM-DD → date; inválida: None."""
    t = str(valor or '').strip()
    for formato in ('%d/%m/%Y', '%Y-%m-%d', '%d%m%Y'):
        try:
            return datetime.strptime(t, formato).date()
        except ValueError:
            pass
    return None


def _documentos(dados, agora):
    """🪪 CPF e data de nascimento (vazios valem: a gestão completa depois) → (cpf, nascimento, idade)."""
    cpf_txt, nasc_txt = str(dados.get('cpf') or '').strip(), str(dados.get('nascimento') or '').strip()
    cpf = _cpf(cpf_txt) or None
    if cpf_txt and not cpf:
        raise ErroPerfil("CPF inválido. Confira os 11 números.")
    nasc = _data_nascimento(nasc_txt)
    if nasc_txt and not nasc:
        raise ErroPerfil("Data de nascimento inválida. Escreva assim: 25/03/2004.")
    idade = _anos(nasc, agora.date()) if nasc else None
    if nasc and not IDADE_MIN <= idade <= IDADE_MAX:
        raise ErroPerfil("Confira a data de nascimento.")
    return cpf, nasc, idade


def _idade_hoje(nasc, idade_guardada, agora):
    """Pela data de nascimento (sempre certa); cadastro antigo só tem a idade que a pessoa escreveu."""
    nasc = database._como_data(nasc)
    return _anos(nasc, agora.date()) if nasc else idade_guardada


def documentos(aid, usuario, agora=None):
    """🪪 CPF e data de nascimento do candidato (só a gestão; o log guarda quem abriu, nunca o número)."""
    garantir_tabelas()
    agora = agora or CE._agora()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Nome, Cpf, Nascimento, Idade FROM AvaliacoesDisc WHERE AvaliacaoID = ? AND Tipo = ?", int(aid), TIPO_CAND)
        a = cur.fetchone()
    finally:
        conn.close()
    if not a:
        raise ErroPerfil("Candidato não encontrado.", 404)
    nasc = database._como_data(a[2])
    logger.info(f"[PERFIL DISC] {usuario.get('nome')} abriu o CPF e o nascimento do candidato {aid}.")
    return {'id': int(aid), 'nome': a[0] or '', 'cpf': _cpf_formatado(a[1]),
            'nascimento': nasc.strftime('%d/%m/%Y') if nasc else '', 'idade': _idade_hoje(nasc, a[3], agora)}


def definir_documentos(aid, dados, usuario, agora=None):
    """A gestão põe ou corrige o CPF e a data de nascimento (ex.: cadastro antigo). Campo vazio apaga."""
    agora = agora or CE._agora()
    cpf, nasc, idade = _documentos(dados if isinstance(dados, dict) else {}, agora)
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        if idade is None:                                 # sem a data: a idade que a pessoa escreveu antes continua
            cur.execute("UPDATE AvaliacoesDisc SET Cpf = ?, Nascimento = ? WHERE AvaliacaoID = ? AND Tipo = ?",
                        cpf, nasc, int(aid), TIPO_CAND)
        else:
            cur.execute("UPDATE AvaliacoesDisc SET Cpf = ?, Nascimento = ?, Idade = ? WHERE AvaliacaoID = ? AND Tipo = ?",
                        cpf, nasc, idade, int(aid), TIPO_CAND)
        ok = cur.rowcount == 1
        conn.commit()
    finally:
        conn.close()
    if not ok:
        raise ErroPerfil("Candidato não encontrado.", 404)
    logger.info(f"[PERFIL DISC] {usuario.get('nome')} gravou o CPF e o nascimento do candidato {aid}.")
    return {'ok': True, 'mensagem': "🪪 CPF e data de nascimento gravados."}


def _limpo(v, n):
    return ' '.join(str(v or '').split())[:n]


def _escolhas(valor, opcoes):
    if isinstance(valor, str):
        valor = valor.split(',')
    validas = [c for c, _ in opcoes]
    return [c for c in validas if c in {str(x).strip() for x in (valor or [])}]


def trabalhe_cadastrar(dados, ip, agora=None):
    """
    Cadastro pelo link do Instagram. Cria o candidato (origem 'site') e devolve o código do questionário, que abre na
    hora (não manda WhatsApp: o número foi digitado por quem quiser, e o número da loja não pode virar spam).
    O mesmo WhatsApp (ou o mesmo CPF) de novo em até 60 dias: atualiza o cadastro e continua o mesmo questionário.
    """
    dados = dados if isinstance(dados, dict) else {}
    agora = agora or CE._agora()
    if dados.get('site'):                                 # campo escondido: só robô de spam preenche
        return {'ok': True, 'token': '', 'robo': True}
    nome = _limpo(dados.get('nome'), 150)
    if len(nome) < 3 or ' ' not in nome:
        raise ErroPerfil("Escreva o seu nome completo.")
    tel = CE.R.numero_whatsapp(str(dados.get('telefone') or ''))
    if not tel:
        raise ErroPerfil("WhatsApp inválido. Use o DDD + o número (ex.: 66 99999-1234).")
    if not str(dados.get('cpf') or '').strip():
        raise ErroPerfil("Escreva o seu CPF.")
    if not str(dados.get('nascimento') or '').strip():
        raise ErroPerfil("Escreva a sua data de nascimento (ex.: 25/03/2004).")
    cpf, nasc, idade = _documentos(dados, agora)
    bairro = _limpo(dados.get('bairro'), 100)
    if len(bairro) < 2:
        raise ErroPerfil("Escreva o seu bairro (e a cidade, se não for Rondonópolis).")
    tipo_vaga = str(dados.get('tipo_vaga') or '').strip()
    if tipo_vaga not in dict(TIPOS_VAGA):
        raise ErroPerfil("Escolha que tipo de vaga você procura: fixa, freelancer ou tanto faz.")
    areas = _escolhas(dados.get('areas'), AREAS_FORM)
    if not areas:
        raise ErroPerfil("Escolha pelo menos uma área que você tem interesse.")
    dispon = _escolhas(dados.get('disponibilidade'), DISPONIBILIDADE)
    if not dispon:
        raise ErroPerfil("Escolha quando você pode trabalhar.")
    exper = str(dados.get('experiencia') or '').strip()[:600]
    if not dados.get('aceite'):
        raise ErroPerfil("Marque que você autoriza guardar os seus dados para o processo seletivo.")
    if not _limite_ip(ip or '?'):
        logger.warning(f"[TRABALHE CONOSCO] Cadastro recusado (limite): IP {ip}.")
        raise ErroPerfil("Muitos cadastros agora. Tente de novo mais tarde.", 429)
    garantir_tabelas()
    vaga = ', '.join(re.sub(r'^\W+\s*', '', dict(AREAS)[c]) for c in areas)[:100]
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT AvaliacaoID, Token, Status FROM AvaliacoesDisc
                       WHERE Tipo = ? AND Origem = ? AND (Telefone = ? OR Cpf = ?) AND CriadoEm >= ? AND Status NOT IN (?, ?)
                       ORDER BY AvaliacaoID DESC""", TIPO_CAND, ORIGEM_SITE, tel, cpf,
                    agora - timedelta(days=DIAS_MESMO_CADASTRO), ST_CANCELADO, ST_EXPIRADO)
        r = cur.fetchone()
        campos = (nome, vaga, ','.join(areas), idade, bairro, ','.join(dispon), exper or None, agora, tipo_vaga, cpf, nasc, tel)
        if r:
            aid, token, st = r
            cur.execute("""UPDATE AvaliacoesDisc SET Nome = ?, Vaga = ?, Areas = ?, Idade = ?, Bairro = ?, Disponibilidade = ?,
                                  Experiencia = ?, AceiteEm = ?, TipoVaga = ?, Cpf = ?, Nascimento = ?, Telefone = ?
                           WHERE AvaliacaoID = ?""", *campos, aid)
        else:
            token, st = CE._token(), ST_ENVIADO
            cur.execute("""INSERT INTO AvaliacoesDisc (FuncionarioID, Nome, Vaga, Areas, Idade, Bairro, Disponibilidade, Experiencia,
                                                       AceiteEm, TipoVaga, Cpf, Nascimento, Telefone, Token, Status, Pontos,
                                                       CriadoPor, CriadoEm, EnviadoEm, ValidoAte, Versao, Tipo, Origem, Etapa)
                           VALUES (0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?); SELECT SCOPE_IDENTITY();""",
                        *campos, token, ST_ENVIADO, '📸 Trabalhe conosco', agora, agora,
                        agora.date() + timedelta(days=VALIDADE_MAX_DIAS), VERSAO, TIPO_CAND, ORIGEM_SITE, 'novo')
            cur.nextset()
            aid = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[TRABALHE CONOSCO] Cadastro {'atualizado' if r else 'novo'}: candidato {aid} ({vaga}).")
    return {'ok': True, 'token': token, 'nome': CE._primeiro_nome(nome), 'ja_respondeu': st == ST_RESPONDIDO}


def definir_tipo_vaga(aid, tipo_vaga, usuario):
    """A gestão marca o tipo de vaga (ex.: cadastro antigo, depois de perguntar no WhatsApp)."""
    if tipo_vaga not in dict(TIPOS_VAGA):
        raise ErroPerfil("Tipo de vaga inválido.")
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE AvaliacoesDisc SET TipoVaga = ? WHERE AvaliacaoID = ? AND Tipo = ?", tipo_vaga, int(aid), TIPO_CAND)
        ok = cur.rowcount == 1
        conn.commit()
    finally:
        conn.close()
    if not ok:
        raise ErroPerfil("Candidato não encontrado.", 404)
    logger.info(f"[PERFIL DISC] {usuario.get('nome')}: candidato {aid} → tipo de vaga {tipo_vaga}.")
    return {'ok': True, 'mensagem': f"Tipo de vaga: {dict(TIPOS_VAGA)[tipo_vaga]}."}


def definir_etapa(aid, etapa, usuario):
    """Etapa do candidato no processo seletivo: 🆕 novo · 📞 entrevista · ✅ contratado · ❌ não seguiu."""
    if etapa not in dict(ETAPAS):
        raise ErroPerfil("Etapa inválida.")
    garantir_tabelas()
    conn = _conexao()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE AvaliacoesDisc SET Etapa = ? WHERE AvaliacaoID = ? AND Tipo = ?", etapa, int(aid), TIPO_CAND)
        ok = cur.rowcount == 1
        conn.commit()
    finally:
        conn.close()
    if not ok:
        raise ErroPerfil("Candidato não encontrado.", 404)
    logger.info(f"[PERFIL DISC] {usuario.get('nome')}: candidato {aid} → etapa {etapa}.")
    return {'ok': True, 'mensagem': f"Etapa: {dict(ETAPAS)[etapa]}."}


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

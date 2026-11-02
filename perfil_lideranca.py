# ==============================================================================
# == perfil_lideranca.py - 👔 Avaliação de perfil de LIDERANÇA (sócios e líderes) ==
# ==============================================================================
# Separada do 🧭 Perfil da equipe (perfil_disc.py), que continua IGUAL: tabela própria (AvaliacoesLideranca),
# perguntas próprias (24 situações da GESTÃO, não da operação), página própria (/lideranca/<código>) e um
# relatório de gestão: estilo de liderança, como decide, sob pressão, como delega, como se comunica, conflitos,
# as ÁREAS DA GESTÃO (finanças, pessoas, operação, marketing, compras, expansão, crises e gerência da loja) com
# o porquê, quem precisa ao lado e o que desenvolver.
# Na página da gestão: o 👥 time de gestão (o que está coberto e o que falta), 🤝 os sócios juntos (como se
# complementam + divisão sugerida das áreas) e, para o 🎯 candidato a líder, o que ele traz para a gestão e
# como combina com cada sócio.
# Papéis: 👑 sócio(a) · 🧑‍💼 líder da equipe · 🎯 candidato(a) a líder. Sem pontos.
# 🔒 Privacidade: nada vai para o grupo de avisos; "quem pode ver" fica no banco (vazio = qualquer gestor).
# Mesma base do DISC (William Marston, teoria pública): questionário NOSSO, para orientar, não é teste certificado.
# 🔋🧠 [LIDERANÇA+] O link pode ter 3 partes, como o 🧭 Perfil: o perfil de liderança, 🔋 o que motiva (as mesmas 28
# perguntas de perfil_motivacao.py) e 🧠 como aprende (as mesmas 12 de perfil_aprendizado.py). O relatório usa textos de
# GESTÃO (o que move na gestão, como manter motivado(a), como apresentar propostas e combinar, como se desenvolver).
# As partes da mesma pessoa (mesmo nome) se juntam; "📤 Mandar o que falta" cria um link só com o que ela não respondeu.
# ==============================================================================
import json
import logging
import threading
from datetime import timedelta

import database
import comunicados_equipe as CE      # endereço, empresa, nome, WhatsApp, código do link
import perfil_disc as P              # cálculo do DISC, nomes e situações (o módulo do perfil da equipe não muda)
import perfil_motivacao as PM        # [LIDERANÇA+] 🔋 as perguntas e o cálculo de "o que te motiva"
import perfil_aprendizado as PA      # [LIDERANÇA+] 🧠 as perguntas e o cálculo de "como você aprende"

logger = logging.getLogger(__name__)

VERSAO = 1
DIMS, NOMES, EMOJI = P.DIMS, P.NOMES, P.EMOJI
ErroPerfil = P.ErroPerfil            # o servidor já trata este erro (mensagem + status)
SEGUNDO_PLANO = True                 # os testes desligam para conferir na hora
PAPEIS = [('socio', '👑 Sócio(a) / dono(a)'), ('lider', '🧑‍💼 Líder da equipe'), ('candidato', '🎯 Candidato(a) a líder')]
PAPEL_CANDIDATO = 'candidato'
FORTE = 30                           # fator "forte" (a média é 25%)
ERRO_INTERROMPIDO = "o envio foi interrompido no meio (o servidor reiniciou)"

# As 24 situações da gestão: o que a pessoa faria (uma frase de cada fator, a ordem muda em cada uma)
SITUACOES = [
    ("Quando preciso tomar uma decisão importante na empresa, eu…",
     {'D': 'Decido rápido e assumo o risco', 'I': 'Converso com as pessoas e busco apoio para a ideia',
      'S': 'Penso com calma no impacto em todos antes de decidir', 'C': 'Levanto números e informações antes de decidir'}),
    ("Quando o faturamento cai, a primeira coisa que eu faço é…",
     {'D': 'Cobrar ação imediata e mudar o que não funciona', 'I': 'Criar promoção e movimento para atrair clientes',
      'S': 'Conversar com a equipe e manter todos tranquilos', 'C': 'Analisar os números para achar a causa'}),
    ("Ao contratar alguém, eu valorizo mais…",
     {'D': 'Garra e foco em resultado', 'I': 'Simpatia e facilidade para se comunicar',
      'S': 'Lealdade e vontade de ficar muito tempo', 'C': 'Capricho e respeito às regras'}),
    ("Numa reunião com a equipe, eu costumo…",
     {'D': 'Ir direto ao ponto e definir quem faz o quê', 'I': 'Animar o grupo e puxar ideias de todos',
      'S': 'Ouvir todo mundo e buscar um acordo', 'C': 'Seguir uma pauta e mostrar os dados'}),
    ("Quando um funcionário erra, eu…",
     {'D': 'Corrijo na hora, de forma direta', 'I': 'Converso de um jeito leve e motivo a melhorar',
      'S': 'Entendo o motivo e ajudo com paciência', 'C': 'Mostro o padrão certo e como evitar o erro'}),
    ("Ao passar uma tarefa para alguém, eu…",
     {'D': 'Digo o resultado que quero e cobro o prazo', 'I': 'Explico o porquê e animo a pessoa',
      'S': 'Acompanho de perto e fico disponível para ajudar', 'C': 'Passo o passo a passo detalhado'}),
    ("Numa mudança grande na loja (sistema, cardápio, processo), eu…",
     {'D': 'Implanto rápido, mesmo com resistência', 'I': 'Apresento com entusiasmo para todos comprarem a ideia',
      'S': 'Faço aos poucos, para a equipe se adaptar', 'C': 'Testo e planejo cada detalhe antes'}),
    ("Num conflito entre funcionários, eu…",
     {'D': 'Resolvo na hora e decido quem tem razão', 'I': 'Converso com os dois e tento reaproximar',
      'S': 'Escuto com calma e busco a paz no grupo', 'C': 'Olho os fatos e a regra para decidir'}),
    ("Quando penso no futuro da empresa, eu…",
     {'D': 'Quero crescer rápido: novas lojas e metas altas', 'I': 'Imagino a marca conhecida e amada na cidade',
      'S': 'Quero uma empresa sólida, com equipe estável', 'C': 'Quero tudo organizado, com controle e lucro certo'}),
    ("O que mais me incomoda na gestão é…",
     {'D': 'Lentidão e falta de resultado', 'I': 'Ambiente frio e sem conversa',
      'S': 'Conflito e mudança o tempo todo', 'C': 'Bagunça, erro e falta de controle'}),
    ("Com o dinheiro e os custos da empresa, eu…",
     {'D': 'Invisto com coragem quando vejo oportunidade', 'I': 'Invisto no que dá visibilidade para a marca',
      'S': 'Prefiro segurança e evito riscos', 'C': 'Controlo cada gasto e comparo os números'}),
    ("Quando um cliente reclama, eu…",
     {'D': 'Resolvo rápido e sigo em frente', 'I': 'Converso, encanto e transformo em fã',
      'S': 'Escuto com paciência e acalmo a situação', 'C': 'Investigo o que deu errado para não repetir'}),
    ("O meu jeito de cobrar a equipe é…",
     {'D': 'Firme, com metas e prazos claros', 'I': 'Motivando com desafios e reconhecimento',
      'S': 'Com conversa e confiança, sem pressão', 'C': 'Com checklists, indicadores e conferência'}),
    ("Quando a empresa tem muita coisa para resolver ao mesmo tempo, eu…",
     {'D': 'Priorizo o que dá mais resultado e corto o resto', 'I': 'Falo com várias pessoas e resolvo no improviso',
      'S': 'Faço uma coisa de cada vez, com constância', 'C': 'Organizo uma lista e sigo a ordem'}),
    ("Numa negociação com fornecedor, eu…",
     {'D': 'Pressiono por preço e condições', 'I': 'Crio relacionamento e consigo vantagens na conversa',
      'S': 'Valorizo a parceria de longo prazo', 'C': 'Comparo as propostas e analiso cada detalhe'}),
    ("Quando a equipe está desmotivada, eu…",
     {'D': 'Lanço um desafio com meta e prêmio', 'I': 'Faço algo divertido para levantar o clima',
      'S': 'Converso um a um para entender o que está acontecendo', 'C': 'Reviso os processos e o que atrapalha o trabalho'}),
    ("Para mim, um bom líder é aquele que…",
     {'D': 'Entrega resultado', 'I': 'Inspira as pessoas', 'S': 'Cuida das pessoas', 'C': 'Faz as coisas do jeito certo'}),
    ("Quando um sócio ou líder discorda de mim, eu…",
     {'D': 'Defendo a minha posição com firmeza', 'I': 'Tento convencer com bons argumentos e simpatia',
      'S': 'Cedo um pouco para manter a harmonia', 'C': 'Peço os dados e analiso quem tem razão'}),
    ("Na rotina da empresa, eu prefiro…",
     {'D': 'Resolver problemas e tomar decisões', 'I': 'Estar com clientes, equipe e parceiros',
      'S': 'Manter tudo funcionando bem, todo dia', 'C': 'Cuidar de controles, planilhas e qualidade'}),
    ("Quando uma decisão minha dá errado, eu…",
     {'D': 'Assumo e já parto para a solução', 'I': 'Explico o que aconteceu e mantenho o clima bom',
      'S': 'Fico chateado(a) e me esforço para não repetir', 'C': 'Analiso o que falhou e crio uma regra para evitar'}),
    ("Ao planejar o mês da empresa, eu…",
     {'D': 'Defino metas desafiadoras', 'I': 'Penso em campanhas e eventos',
      'S': 'Garanto uma escala e uma rotina tranquilas', 'C': 'Monto o orçamento e acompanho cada número'}),
    ("A equipe me descreve como…",
     {'D': 'Decidido(a) e exigente', 'I': 'Comunicativo(a) e animado(a)', 'S': 'Calmo(a) e confiável',
      'C': 'Organizado(a) e detalhista'}),
    ("Quando preciso dar uma notícia ruim para a equipe, eu…",
     {'D': 'Falo direto, sem rodeios', 'I': 'Falo de forma positiva, mostrando o lado bom',
      'S': 'Falo com cuidado, um a um se for preciso', 'C': 'Explico os motivos com fatos e números'}),
    ("O que mais me dá satisfação na gestão é…",
     {'D': 'Bater metas e vencer desafios', 'I': 'Ser reconhecido(a) e ver a equipe animada',
      'S': 'Ver a equipe unida e estável', 'C': 'Ver tudo organizado e funcionando sem erro'}),
]
BLOCOS = [[(SITUACOES[k][1][d], d) for d in ordem] for k, ordem in enumerate(P.ORDENS)]
N_BLOCOS = len(BLOCOS)
assert N_BLOCOS == P.N_BLOCOS                # o cálculo do DISC conta com 24 grupos
TREINO = {'pergunta': 'No fim de semana de folga, eu prefiro…', 'opcoes': ['🏃 Fazer algo ativo', '🎉 Encontrar os amigos',
          '🏠 Ficar em casa com a família', '📚 Organizar ou estudar algo']}

# O estilo de cada fator na GESTÃO (textos do relatório)
TEXTOS = {
    'D': {
        'estilo': '🔴 Líder executor', 'curto': 'resultado, decisão e velocidade',
        'resumo': 'Lidera pela ação: define metas, decide rápido e cobra resultado. Enxerga oportunidades, aceita riscos e '
                  'não tem medo de mudar o que não funciona. Rende muito no crescimento e nas crises; o desafio é não '
                  'atropelar as pessoas nem os processos.',
        'fortes': ['Toma decisões difíceis sem travar', 'Define metas claras e cobra resultado',
                   'Age rápido nas crises e nos problemas', 'Enxerga oportunidades de crescimento e expansão'],
        'riscos': ['Pode decidir sem ouvir a equipe e perder o engajamento', 'Pode centralizar tudo e não formar novos líderes',
                   'Pode parecer duro(a) e gerar medo em vez de respeito', 'Tende a deixar de lado processos, controles e detalhes'],
        'decide': 'Decide rápido, pela experiência e pela intuição, e gosta de ter a palavra final.',
        'pressao': 'Sob pressão fica mais autoritário(a) e impaciente, e tende a assumir tudo sozinho(a).',
        'delega': ['Delega o resultado e cobra o prazo', 'Cuidado: pode pegar a tarefa de volta se achar que está lento',
                   'Combine pontos de acompanhamento em vez de interferir a toda hora'],
        'comunica': ['Direto(a) e objetivo(a): vai ao ponto', 'Lembre de explicar o porquê das decisões para a equipe',
                     'Equilibre a cobrança com reconhecimento'],
        'conflito': 'Enfrenta o conflito de frente e resolve rápido, mas pode ser visto(a) como duro(a). Ouvir os dois '
                    'lados antes de decidir faz diferença.',
        'precisa': 'Precisa ao lado de alguém 🟢 Estável ou 🔵 Conforme, para cuidar das pessoas, da rotina e dos controles '
                   'que costuma deixar de lado.',
        'desenvolver': ['Antes de decidir algo que afeta a equipe, ouvir pelo menos uma pessoa',
                        'Delegar de verdade: um responsável por área, sem interferir no meio do caminho',
                        'Separar um momento por semana para reconhecer quem se destacou'],
        'trabalhar': ['Leve propostas prontas, com o resultado esperado', 'Seja objetivo(a) e não leve a franqueza para o pessoal',
                      'Combine as metas e deixe a cobrança ser pelo resultado'],
        'pessoa': 'Você é um(a) líder de ação: decide, assume riscos e faz a empresa andar.',
        'pessoa_fortes': ['Coragem para decidir', 'Foco em metas e resultado', 'Força nos momentos difíceis'],
    },
    'I': {
        'estilo': '🟡 Líder inspirador', 'curto': 'pessoas, comunicação e entusiasmo',
        'resumo': 'Lidera pelo entusiasmo: comunica a visão, cria um ambiente animado e convence as pessoas. Forte em '
                  'marketing, vendas, relacionamento e cultura da equipe; o desafio é manter a disciplina, o '
                  'acompanhamento e o controle dos números.',
        'fortes': ['Motiva a equipe e cria um clima bom', 'Vende a visão e as ideias para a equipe, clientes e parceiros',
                   'Forte em marketing, campanhas e relacionamento com os clientes', 'Faz contatos e abre portas'],
        'riscos': ['Pode prometer mais do que dá para cumprir', 'Pode perder o foco e deixar coisas pela metade',
                   'Evita conversas difíceis e cobrança para não desagradar', 'Pode decidir pela emoção e deixar os números de lado'],
        'decide': 'Decide pela intuição e pela opinião das pessoas, e se empolga com novidades.',
        'pressao': 'Sob pressão fala muito, se dispersa e pode ficar desorganizado(a); busca apoio nas pessoas.',
        'delega': ['Delega com entusiasmo e explica o propósito', 'Cuidado: pode esquecer de acompanhar o que delegou',
                   'Use uma lista de responsáveis e prazos, sem depender da memória'],
        'comunica': ['Comunicação calorosa e motivadora', 'Bom(boa) em reuniões, treinamentos e apresentações',
                     'Cuide para ser claro(a) também nas cobranças e nos combinados'],
        'conflito': 'Tenta amenizar o conflito e manter todos bem, e pode adiar decisões duras. Deixar o combinado por '
                    'escrito ajuda.',
        'precisa': 'Precisa ao lado de alguém 🔵 Conforme ou 🔴 Dominante, para cuidar dos números, do acompanhamento e da '
                   'execução.',
        'desenvolver': ['Acompanhar 3 números fixos por semana (ex.: faturamento, custo e ticket médio)',
                        'Terminar uma iniciativa antes de começar outra', 'Ter as conversas difíceis no dia, sem adiar'],
        'trabalhar': ['Dê espaço para as ideias e reconheça em público', 'Transforme as ideias em plano, com responsável e prazo',
                      'Reuniões curtas e animadas funcionam melhor'],
        'pessoa': 'Você é um(a) líder que inspira: comunica, anima e faz as pessoas acreditarem.',
        'pessoa_fortes': ['Inspira e motiva a equipe', 'Comunicação e relacionamento', 'Energia para criar e vender ideias'],
    },
    'S': {
        'estilo': '🟢 Líder agregador', 'curto': 'pessoas, estabilidade e confiança',
        'resumo': 'Lidera pela confiança: cuida das pessoas, mantém a equipe unida e a rotina estável. Forte em segurar '
                  'bons funcionários, formar equipe e manter a qualidade do dia a dia; o desafio é tomar decisões duras, '
                  'mudar rápido e cobrar quando precisa.',
        'fortes': ['Equipe leal, que fica muito tempo', 'Ambiente de confiança e respeito',
                   'Rotina estável e previsível, sem sustos', 'Escuta e apoia as pessoas'],
        'riscos': ['Pode demorar para cobrar ou desligar quem não rende', 'Resiste a mudanças e novidades necessárias',
                   'Evita conflitos e guarda a insatisfação', 'Pode fazer o trabalho dos outros para não incomodar'],
        'decide': 'Decide com calma, pensando no impacto nas pessoas, e prefere o consenso.',
        'pressao': 'Sob pressão fica mais quieto(a) e cede para evitar briga; pode guardar o estresse.',
        'delega': ['Delega para quem confia e acompanha de perto', 'Cuidado: pode acabar fazendo o trabalho no lugar da pessoa',
                   'Combine o padrão e deixe a pessoa errar e aprender'],
        'comunica': ['Paciente e respeitoso(a), bom(boa) ouvinte', 'Prefere a conversa individual à reunião grande',
                     'Cuide para dizer com clareza o que não está bom'],
        'conflito': 'Evita o conflito e busca a paz, e pode demorar para agir. Marcar a conversa difícil com dia e hora ajuda.',
        'precisa': 'Precisa ao lado de alguém 🔴 Dominante ou 🟡 Influente, para puxar mudanças, metas mais ousadas e '
                   'decisões rápidas.',
        'desenvolver': ['Dar um prazo para as decisões difíceis (ex.: até sexta)', 'Testar uma mudança pequena por mês',
                        'Dar feedback de melhoria toda semana, não só elogio'],
        'trabalhar': ['Explique as mudanças com antecedência e o porquê', 'Valorize a dedicação e a lealdade',
                      'Peça a opinião em particular, não só na reunião'],
        'pessoa': 'Você é um(a) líder que une: cuida das pessoas e dá estabilidade à empresa.',
        'pessoa_fortes': ['Confiança e lealdade da equipe', 'Estabilidade e constância', 'Escuta e apoio às pessoas'],
    },
    'C': {
        'estilo': '🔵 Líder analítico', 'curto': 'processos, números e qualidade',
        'resumo': 'Lidera pela organização: cria processos, controla os números e garante a qualidade e o padrão. Forte em '
                  'finanças, custos, estoque e regras; o desafio é decidir com informação incompleta, ser flexível e se '
                  'aproximar das pessoas.',
        'fortes': ['Controle de custos, margens e números', 'Processos claros, padrões e checklists',
                   'Decisões bem pensadas, com menos erro', 'Qualidade e cumprimento das regras (vigilância, fiscal e trabalhista)'],
        'riscos': ['Pode demorar demais para decidir (análise sem fim)', 'Pode ser visto(a) como frio(a) ou crítico(a) demais',
                   'Pode querer controlar cada detalhe e travar a equipe', 'Resiste a improvisos e a oportunidades rápidas'],
        'decide': 'Decide com dados e análise, e prefere ter certeza antes de agir.',
        'pressao': 'Sob pressão fica mais crítico(a) e perfeccionista, se fecha e pode travar a decisão.',
        'delega': ['Delega com instruções claras e padrões', 'Cuidado: pode refazer o trabalho dos outros para ficar perfeito',
                   'Defina o que é "bom o bastante" e confie no padrão'],
        'comunica': ['Claro(a), lógico(a) e baseado(a) em fatos', 'Prefere comunicar por escrito e com dados',
                     'Cuide do lado humano: elogie e converse além do trabalho'],
        'conflito': 'Resolve o conflito pelos fatos e pelas regras, mas pode parecer distante. Reconhecer também os '
                    'sentimentos das pessoas ajuda.',
        'precisa': 'Precisa ao lado de alguém 🟡 Influente ou 🔴 Dominante, para dar velocidade, energia e proximidade com as '
                   'pessoas.',
        'desenvolver': ['Ter um prazo máximo para cada decisão', 'Aceitar decidir com 80% da informação quando o risco é baixo',
                        'Uma conversa informal por semana com a equipe'],
        'trabalhar': ['Leve dados e a proposta por escrito', 'Dê tempo para a análise nas decisões grandes',
                      'Respeite os processos e combine as exceções antes'],
        'pessoa': 'Você é um(a) líder que organiza: cria processos, controla os números e garante a qualidade.',
        'pessoa_fortes': ['Organização e controle', 'Decisões bem pensadas', 'Qualidade e padrão'],
    },
}

# As áreas da gestão: o peso de cada fator, o que a área pede de cada um e o fator que, muito forte, atrapalha
AREAS = [
    {'nome': '💰 Finanças, custos e preços', 'pesos': {'C': .7, 'D': .3},
     'pede': {'C': 'controle dos números, da margem e dos custos', 'D': 'coragem nas decisões de preço e investimento'},
     'atrapalha': {'I': 'muito Influente tende a decidir gastos pela emoção e pelo entusiasmo'}},
    {'nome': '👥 Pessoas, cultura e treinamento', 'pesos': {'S': .5, 'I': .4, 'C': .1},
     'pede': {'S': 'paciência para formar e segurar a equipe', 'I': 'motivar e comunicar a cultura da empresa',
              'C': 'organizar treinamentos e padrões'},
     'atrapalha': {'D': 'muito Dominante pode ser duro(a) demais e aumentar a troca de funcionários'}},
    {'nome': '⚙️ Operação e padrão da loja', 'pesos': {'C': .4, 'S': .4, 'D': .2},
     'pede': {'C': 'padrões, checklists e qualidade', 'S': 'constância no dia a dia', 'D': 'resolver os problemas na hora'},
     'atrapalha': {'I': 'muito Influente tende a se dispersar da rotina e dos checklists'}},
    {'nome': '📣 Marketing, vendas e clientes', 'pesos': {'I': .7, 'D': .3},
     'pede': {'I': 'comunicação, criatividade e relacionamento', 'D': 'metas de venda e iniciativa'},
     'atrapalha': {'C': 'muito Conforme tende a analisar demais e perder o tempo da campanha'}},
    {'nome': '📦 Compras, fornecedores e estoque', 'pesos': {'C': .5, 'D': .3, 'S': .2},
     'pede': {'C': 'comparar preços e controlar o estoque e a validade', 'D': 'negociar com firmeza',
              'S': 'manter parcerias de longo prazo'},
     'atrapalha': {}},
    {'nome': '🚀 Estratégia e expansão (novas lojas)', 'pesos': {'D': .6, 'I': .2, 'C': .2},
     'pede': {'D': 'visão de crescimento e coragem para arriscar', 'I': 'vender a ideia para sócios, bancos e parceiros',
              'C': 'planejar e calcular o retorno'},
     'atrapalha': {'S': 'muito Estável tende a evitar riscos e adiar a expansão'}},
    {'nome': '🔥 Crises e decisões difíceis', 'pesos': {'D': .6, 'C': .3, 'S': .1},
     'pede': {'D': 'decidir rápido e assumir a responsabilidade', 'C': 'analisar o problema com frieza',
              'S': 'manter a equipe calma'},
     'atrapalha': {'S': 'muito Estável tende a adiar a decisão dura para evitar conflito'}},
    {'nome': '🧑‍🤝‍🧑 Gerência da loja (liderar a equipe no dia a dia)', 'pesos': {'D': .35, 'S': .35, 'I': .3},
     'pede': {'D': 'cobrar e decidir no turno', 'S': 'cuidar e manter a equipe unida', 'I': 'motivar e comunicar'},
     'atrapalha': {}},
]
NIVEIS = P.NIVEIS

# 🛠️ [DETALHES] Em cada área: o que o responsável ENTREGA e COMO cada perfil pode ajudar na prática (pelo fator que a área pede)
AJUDA_AREAS = {
    '💰 Finanças, custos e preços': {
        'entrega': "Fechamento do mês até o dia 5 (faturamento, custos, folha e lucro) e a revisão dos preços a cada 3 meses.",
        'ajuda': {
            'C': ["Montar e conferir o fechamento do mês (faturamento, custos, folha e lucro)",
                  "Acompanhar a margem dos produtos e o custo do quilo do buffet",
                  "Definir um orçamento por área e conferir o que foi gasto"],
            'D': ["Decidir os reajustes de preço quando os custos sobem", "Cortar rápido o gasto que não traz retorno",
                  "Negociar prazos e condições com bancos e fornecedores grandes"]}},
    '👥 Pessoas, cultura e treinamento': {
        'entrega': "Equipe completa e treinada: integração dos novatos, conversa individual todo mês e a troca de funcionários "
                   "acompanhada.",
        'ajuda': {
            'S': ["Fazer a integração dos novatos e acompanhar as primeiras semanas",
                  "Conversas individuais com a equipe (como está, o que precisa)", "Cuidar do clima e resolver cedo os atritos"],
            'I': ["Comunicar a cultura e os valores da loja nas reuniões",
                  "Criar reconhecimentos e campanhas internas (destaque do mês, metas da equipe)",
                  "Conduzir treinamentos animados e reuniões de equipe"],
            'C': ["Organizar o manual da loja, as receitas e os checklists de treinamento", "Montar a trilha de treinamento por função",
                  "Acompanhar os indicadores da equipe (faltas, atrasos, troca de funcionários)"]}},
    '⚙️ Operação e padrão da loja': {
        'entrega': "Loja no padrão todos os dias: checklists de abertura e fechamento, higiene, validade e qualidade dos produtos.",
        'ajuda': {
            'C': ["Criar e revisar os checklists de abertura, fechamento e higiene",
                  "Conferir o padrão (porções, apresentação do buffet, validade)", "Deixar a loja pronta para a vigilância sanitária"],
            'S': ["Manter a rotina da loja funcionando, todo dia do mesmo jeito", "Acompanhar de perto a escala e as trocas de turno",
                  "Garantir que os combinados virem hábito na equipe"],
            'D': ["Resolver na hora os problemas do dia (equipamento, falta de produto, cliente)",
                  "Tomar decisões rápidas nos dias de movimento forte", "Cobrar a correção quando o padrão não é seguido"]}},
    '📣 Marketing, vendas e clientes': {
        'entrega': "Calendário de campanhas do mês, redes sociais ativas e o retorno de cada ação (quanto vendeu).",
        'ajuda': {
            'I': ["Planejar as campanhas e os lançamentos de sabores", "Cuidar do Instagram, das parcerias e dos eventos",
                  "Ouvir os clientes e transformar elogios e reclamações em ações"],
            'D': ["Definir metas de venda e acompanhar o resultado de cada campanha",
                  "Testar promoções novas e cortar as que não dão resultado",
                  "Buscar novos canais de venda (delivery, empresas, eventos)"]}},
    '📦 Compras, fornecedores e estoque': {
        'entrega': "Estoque sem falta e sem perda: lista de compras, comparação de preços e controle da validade.",
        'ajuda': {
            'C': ["Comparar os preços e conferir as notas e as quantidades", "Controlar o estoque mínimo e a validade",
                  "Acompanhar o custo das compras mês a mês"],
            'D': ["Negociar preço, prazo e bonificação com os fornecedores",
                  "Trocar de fornecedor quando o preço ou a qualidade não servem", "Decidir as compras grandes nas oportunidades"],
            'S': ["Manter boas parcerias de longo prazo com os fornecedores", "Cuidar da rotina de pedidos e recebimentos",
                  "Garantir a entrega no prazo para não faltar produto"]}},
    '🚀 Estratégia e expansão (novas lojas)': {
        'entrega': "Plano do ano com metas, investimentos e o estudo de cada oportunidade nova (loja, canal ou produto).",
        'ajuda': {
            'D': ["Definir as metas do ano e puxar o crescimento",
                  "Avaliar e decidir as oportunidades (nova loja, novo ponto, novo canal)",
                  "Liderar os projetos de expansão do começo ao fim"],
            'I': ["Apresentar as ideias para sócios, bancos e parceiros", "Construir a marca na cidade e criar relacionamentos",
                  "Pesquisar o que os clientes querem para os produtos novos"],
            'C': ["Calcular o investimento, o retorno e o prazo de cada projeto", "Montar o plano de negócio e os cenários",
                  "Acompanhar se o projeto está dando o retorno previsto"]}},
    '🔥 Crises e decisões difíceis': {
        'entrega': "Um plano para os imprevistos (equipamento quebrado, falta de pessoal, queda de vendas) e quem decide em "
                   "cada caso.",
        'ajuda': {
            'D': ["Assumir a frente e decidir quando algo grave acontece",
                  "Ter as conversas difíceis (desligamento, cobrança, fornecedor)", "Agir rápido para conter o prejuízo"],
            'C': ["Analisar a causa do problema com os números", "Montar o plano para não repetir (regra, processo)",
                  "Avaliar os riscos antes das decisões grandes"],
            'S': ["Manter a equipe calma e informada durante a crise", "Cuidar das pessoas afetadas pela decisão",
                  "Garantir que a rotina continue funcionando"]}},
    '🧑‍🤝‍🧑 Gerência da loja (liderar a equipe no dia a dia)': {
        'entrega': "Turnos cobertos, equipe alinhada e as metas do dia acompanhadas, com uma conversa rápida no começo do turno.",
        'ajuda': {
            'D': ["Cobrar as metas do dia e a execução das tarefas", "Decidir no turno sem depender dos sócios",
                  "Corrigir na hora o que está fora do padrão"],
            'S': ["Cuidar da equipe no dia a dia e apoiar quem tem dificuldade", "Manter a escala organizada e os combinados",
                  "Ser a referência de confiança para a equipe"],
            'I': ["Motivar a equipe no começo do turno", "Reconhecer quem se destacou no dia",
                  "Criar um clima bom com a equipe e os clientes"]}},
}
for _area in AREAS:                                       # cada área ganha o que entrega e como cada fator ajuda
    _area.update(AJUDA_AREAS[_area['nome']])

# O que falta quando ninguém da gestão tem o fator forte
FALTA_NA_GESTAO = {
    'D': 'Ninguém na gestão com 🔴 Dominante forte: falta quem puxe metas, decisões rápidas e crescimento. Combinem metas '
         'mensais e um dono para cada decisão.',
    'I': 'Ninguém na gestão com 🟡 Influente forte: falta quem comunique, motive e cuide do marketing. Definam quem cuida '
         'das campanhas e do clima da equipe.',
    'S': 'Ninguém na gestão com 🟢 Estável forte: falta quem cuide das pessoas e da estabilidade. Atenção à troca de '
         'funcionários e ao clima: façam conversas individuais.',
    'C': 'Ninguém na gestão com 🔵 Conforme forte: falta controle de números, custos e processos. Usem indicadores '
         'semanais e checklists, ou tenham um apoio financeiro (contador).',
}
# Duas pessoas juntas na gestão, pelo fator principal de cada uma ({D}, {I}, {S}, {C} = o nome de quem tem o fator)
DUPLAS = {
    'DI': '{D} puxa metas e decisões, {I} puxa pessoas, vendas e marketing: dupla de crescimento. Cuidado com os números '
          'e a rotina: definam quem cuida do financeiro e dos controles.',
    'DS': '{D} acelera e {S} dá estabilidade: combinam bem, com {D} nas metas e decisões e {S} nas pessoas e na rotina. '
          'Cuidado: {S} tende a ceder para evitar briga; combinem um espaço para discordar antes de decidir.',
    'DC': '{D} traz velocidade e {C} traz controle: {D} decide, {C} confere os números e os riscos. Cuidado com o atrito '
          'entre pressa e perfeição: combinem um prazo para a análise antes de cada decisão grande.',
    'IS': '{I} anima e comunica, {S} cuida e dá constância: ótimo clima e equipe unida. Cuidado: os dois evitam cobrar e '
          'decidir o que é duro. Definam metas claras e quem cobra.',
    'IC': '{I} traz criatividade e relacionamento, {C} traz organização e números. Cuidado: {I} pode achar {C} '
          'travado(a), e {C} pode achar {I} bagunçado(a). Respeitem a área de cada um.',
    'SC': '{S} e {C} dão estabilidade, qualidade e controle. Cuidado: pouca ousadia e lentidão para mudar. Coloquem metas '
          'de crescimento e alguém para puxar as vendas e o marketing.',
}
IGUAIS = {
    'D': 'Os dois são 🔴 Dominantes: muita força para crescer, mas risco de disputa pela palavra final. Dividam bem as '
         'áreas (cada um decide na sua) e combinem como desempatar quando discordarem.',
    'I': 'Os dois são 🟡 Influentes: muita energia, ideias e relacionamento. Risco: pouco controle e acompanhamento. '
         'Usem indicadores semanais e um responsável pelos números.',
    'S': 'Os dois são 🟢 Estáveis: empresa tranquila e equipe leal. Risco: crescer devagar e adiar decisões difíceis. '
         'Marquem metas de crescimento e prazos para decidir.',
    'C': 'Os dois são 🔵 Conformes: muito controle e qualidade. Risco: análise demais e pouca ação comercial. Definam '
         'prazos para decidir e invistam em marketing e relacionamento.',
}

# 🔋 [LIDERANÇA+] O que cada motivação significa NA GESTÃO: como aparece, o cuidado e como manter motivado(a)
MOTIV_GESTAO = {
    'dinheiro': {
        'gestao': "Na gestão, se move pelo resultado financeiro: lucro, retorno do que investe e a empresa garantindo os planos.",
        'cuidado': "Pode cortar custos que pesam na equipe ou no padrão para melhorar o resultado do mês.",
        'manter': ["Acompanhar o lucro e o caixa do mês com números claros", "Metas financeiras com participação no resultado",
                   "Mostrar o retorno de cada investimento (quanto voltou)"]},
    'reconhecimento': {
        'gestao': "Se move por ver o trabalho reconhecido: elogio da equipe, dos clientes e dos sócios, e a marca bem falada.",
        'cuidado': "Pode se magoar quando o esforço não é notado e evitar decisões que desagradam.",
        'manter': ["Reconhecer em voz alta as conquistas dele(a) na gestão", "Dar crédito pelas ideias que deram certo",
                   "Compartilhar os elogios de clientes e da equipe"]},
    'crescimento': {
        'gestao': "Se move por aprender e evoluir: ideias novas, cursos, conhecer outras empresas e ver a gestão melhorar.",
        'cuidado': "Pode começar muitas novidades ao mesmo tempo e se entediar com a rotina da gestão.",
        'manter': ["Cursos, eventos e visitas a outras lojas", "Projetos novos para conduzir (cardápio, sistema, processo)",
                   "Conversas sobre o futuro e os próximos passos da empresa"]},
    'equipe': {
        'gestao': "Se move pelas pessoas: equipe unida, sócios alinhados e um clima bom de trabalho.",
        'cuidado': "Pode evitar conflitos e demorar para cobrar ou desligar quem não rende, para não estragar o clima.",
        'manter': ["Momentos com a equipe (reuniões leves, confraternizações)", "Decisões importantes tomadas junto com os sócios",
                   "Cuidar do clima: resolver logo os atritos"]},
    'seguranca': {
        'gestao': "Se move pela segurança: empresa sólida, caixa organizado, regras claras e pouco risco.",
        'cuidado': "Pode adiar investimentos e mudanças necessárias por receio do risco.",
        'manter': ["Reserva de caixa e planejamento financeiro", "Mudanças combinadas com antecedência e em etapas",
                   "Papéis claros: quem decide o quê"]},
    'autonomia': {
        'gestao': "Se move pela liberdade: decidir na própria área, testar ideias e não depender de aprovação para tudo.",
        'cuidado': "Pode decidir sozinho(a) sem avisar os sócios e gerar atrito.",
        'manter': ["Uma área da gestão sob a responsabilidade dele(a)", "Combinar o limite: até onde decide sozinho(a)",
                   "Espaço para testar ideias novas"]},
    'desafio': {
        'gestao': "Se move por desafios: metas ousadas, crescer, abrir novas frentes e resolver problemas difíceis.",
        'cuidado': "Pode desanimar quando a empresa entra numa fase de rotina e manutenção.",
        'manter': ["Metas desafiadoras com o placar à vista", "Projetos de crescimento (nova loja, novo canal, delivery)",
                   "Problemas difíceis para resolver"]},
    'proposito': {
        'gestao': "Se move pelo sentido: fazer diferença para clientes, equipe e cidade, numa empresa que trata bem as pessoas.",
        'cuidado': "Pode sofrer com decisões que parecem frias, mesmo quando são necessárias para a empresa.",
        'manter': ["Mostrar o impacto da empresa (clientes felizes, equipe crescendo)", "Ações sociais e projetos com a comunidade",
                   "Explicar o porquê das decisões difíceis"]},
}
# 🧠 [LIDERANÇA+] Como aprende NA GESTÃO: como apresentar uma proposta, como combinar e como se desenvolver como gestor(a)
APR_GESTAO = {
    'visual': {
        'apresentar': "Apresente propostas e números com gráficos, painéis e imagens (ex.: o gráfico do mês).",
        'combinar': "Nas reuniões, mostre os pontos num quadro ou na tela; depois mande um resumo visual.",
        'desenvolver': ["Vídeos e aulas online sobre gestão", "Visitar outras lojas para ver como fazem",
                        "Painéis e gráficos para acompanhar a empresa"]},
    'auditivo': {
        'apresentar': "Apresente conversando: explique o raciocínio e deixe espaço para perguntas.",
        'combinar': "Prefere resolver numa conversa ou ligação; mande áudio em vez de texto longo.",
        'desenvolver': ["Podcasts e palestras sobre gestão", "Mentoria e conversa com outros empresários",
                        "Grupos de troca de experiência"]},
    'leitura': {
        'apresentar': "Mande a proposta por escrito antes (tópicos ou planilha) e dê tempo para ler.",
        'combinar': "Registre os combinados por escrito (um resumo curto no WhatsApp ou e-mail).",
        'desenvolver': ["Livros e artigos sobre gestão", "Relatórios e planilhas para acompanhar a empresa",
                        "Cursos com material escrito"]},
    'pratico': {
        'apresentar': "Mostre na prática: um teste pequeno, uma amostra ou um piloto antes de decidir.",
        'combinar': "Combine o próximo passo concreto: quem faz o quê e até quando.",
        'desenvolver': ["Testar ideias em pequena escala (piloto)", "Aprender com quem faz: visitas e imersões",
                        "Cursos práticos, com exercício"]},
}
DICA_APR_GESTAO = ("Entre sócios e líderes: passe a informação no jeito de cada um e confirme o combinado de mais de um jeito "
                   "(falado e por escrito).")
# As partes do link (os mesmos códigos do 🧭 Perfil: perfil_disc.CONJUNTOS)
NOMES_PARTES = {'disc': '👔 Perfil de liderança', 'motiv': '🔋 O que motiva', 'apr': '🧠 Como aprende'}

_tabelas_ok = False
_trava = threading.Lock()


# ------------------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------------------
def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    conn = P._conexao()
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AvaliacoesLideranca')
            CREATE TABLE AvaliacoesLideranca (
                AvaliacaoID INT IDENTITY(1,1) PRIMARY KEY,
                Nome NVARCHAR(150) NOT NULL,
                Telefone VARCHAR(30) NULL,
                Papel VARCHAR(10) NOT NULL,
                Token VARCHAR(24) NOT NULL UNIQUE,
                Status VARCHAR(14) NOT NULL,
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
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ConfigLideranca')
            CREATE TABLE ConfigLideranca (
                Chave VARCHAR(40) NOT NULL PRIMARY KEY,
                Valor NVARCHAR(300) NULL
            )
        """)
        # 🔋🧠 [LIDERANÇA+] as partes do link, o que motiva e como aprende
        for coluna, tipo in (('Partes', 'VARCHAR(12)'), ('Motivos', 'NVARCHAR(300)'), ('MotivoRespostas', 'NVARCHAR(1000)'),
                             ('MotivoEm', 'DATETIME'), ('Aprendizado', 'NVARCHAR(200)'), ('AprendizadoRespostas', 'NVARCHAR(400)'),
                             ('AprendizadoEm', 'DATETIME')):
            cur.execute(f"IF COL_LENGTH('AvaliacoesLideranca', '{coluna}') IS NULL ALTER TABLE AvaliacoesLideranca ADD {coluna} {tipo} NULL")
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
# 🔒 Quem pode ver (vazio = qualquer gestor; depois de escolher, só quem está na lista)
# ------------------------------------------------------------------------------
def _ler_acesso():
    garantir_tabelas()
    conn = P._conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Valor FROM ConfigLideranca WHERE Chave = 'acesso'")
        r = cur.fetchone()
    finally:
        conn.close()
    return {int(x) for x in str((r[0] if r else '') or '').split(',') if x.strip().isdigit()}


def pode_ver(usuario):
    ids = _ler_acesso()
    return not ids or int(usuario.get('id') or 0) in ids


def exigir_acesso(usuario):
    if not pode_ver(usuario):
        raise ErroPerfil("🔒 A 👔 Liderança é só de quem os sócios liberaram. Peça para um sócio liberar você.", 403)


def gestores():
    """Quem entra na Gestão como gestor (para escolher quem pode ver)."""
    conn = P._conexao()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT U.FuncionarioID, F.NomeCompleto FROM CompraUsuariosApp U
                       JOIN Funcionarios F ON F.FuncionarioID = U.FuncionarioID
                       WHERE U.Ativo = 1 AND U.EhGestor = 1 ORDER BY F.NomeCompleto""")
        return [{'id': int(r[0]), 'nome': r[1] or f'Funcionário {r[0]}'} for r in cur.fetchall()]
    finally:
        conn.close()


def salvar_acesso(ids, usuario):
    exigir_acesso(usuario)
    if not isinstance(ids, list):
        raise ErroPerfil("Lista inválida.")
    validos = {g['id'] for g in gestores()}
    try:
        ids = sorted({int(i) for i in ids})
    except (TypeError, ValueError):
        raise ErroPerfil("Lista inválida.")
    if any(i not in validos for i in ids):
        raise ErroPerfil("Alguém da lista não é mais gestor. Atualize a página.", 409)
    if ids and int(usuario.get('id') or 0) not in ids:
        raise ErroPerfil("Marque você também: senão você perde o acesso a esta página.")
    conn = P._conexao()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM ConfigLideranca WHERE Chave = 'acesso'")
        cur.execute("INSERT INTO ConfigLideranca (Chave, Valor) VALUES ('acesso', ?)", ','.join(map(str, ids)))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[LIDERANÇA] {usuario.get('nome')} mudou quem pode ver: {len(ids) or 'todos os gestores'}.")
    return {'ok': True, 'mensagem': f"🔒 Agora só {len(ids)} pessoa(s) veem a 👔 Liderança." if ids else
            "🔓 Qualquer gestor vê a 👔 Liderança."}


# ------------------------------------------------------------------------------
# Relatório da gestão
# ------------------------------------------------------------------------------
def _fator(pct, d):
    return f"{EMOJI[d]} {NOMES[d]} {pct[d]}%"


def _nota(area, pct):
    return sum(peso * pct[d] for d, peso in area['pesos'].items())


def areas_da_pessoa(pct):
    """TODAS as áreas da gestão, da que mais combina para a que menos, com o nível e o PORQUÊ."""
    saida = []
    for area in AREAS:
        nota, pesos, pede = _nota(area, pct), area['pesos'], area['pede']
        forte = max(pesos, key=lambda d: pesos[d] * pct[d])            # o fator dela que mais ajuda nesta área
        falta = max(pesos, key=lambda d: pesos[d] * (25 - pct[d]))     # o fator que a área pede e ela tem pouco
        nivel = 'combina' if nota >= 30 else ('pode' if nota >= 22 else 'menos')
        if nivel == 'combina':
            porque = f"Pede {pede[forte]}, e isso é um ponto forte do perfil ({_fator(pct, forte)})."
        elif nivel == 'menos':
            porque = f"Pede {pede[falta]}, e esse é um fator baixo no perfil ({_fator(pct, falta)})."
        elif pct[falta] < 25 and falta != forte:
            porque = (f"A favor: {pede[forte]} ({_fator(pct, forte)}). Vai precisar de apoio em: {pede[falta]} "
                      f"({_fator(pct, falta)}).")
        else:
            porque = f"Dá para conduzir: pede {pede[forte]} ({_fator(pct, forte)}), sem ser o ponto mais forte do perfil."
        for d, aviso in area['atrapalha'].items():
            if pct[d] >= 40:                                            # fator muito forte que atrapalha: desce um nível
                nivel = {'combina': 'pode', 'pode': 'menos'}.get(nivel, nivel)
                porque += f" Atenção: {aviso}."
        saida.append({'area': area['nome'], 'nivel': nivel, 'nivel_nome': NIVEIS[nivel], 'porque': porque, 'nota': round(nota, 1),
                      **_como_ajuda(area, pct, nivel, forte, falta)})
    ordem = {'combina': 0, 'pode': 1, 'menos': 2}
    saida.sort(key=lambda x: (ordem[x['nivel']], -x['nota']))
    return saida


def _como_ajuda(area, pct, nivel, forte, falta):
    """🛠️ [DETALHES] Como a pessoa pode ajudar na área (pelo fator dela que a área mais aproveita, + um pouco do 2º fator
    que a área pede, se for forte) ou, se a área é menos indicada, quem chamar para apoiar."""
    if nivel == 'menos':
        return {'ajuda': [], 'apoio': f"Chame quem é forte em {EMOJI[falta]} {NOMES[falta]} para apoiar em: {area['pede'][falta]}. "
                                      f"Aqui, ajuda mais em: {area['pede'][forte]}."}
    seg = next((d for d in sorted(area['pesos'], key=lambda d: -area['pesos'][d] * pct[d]) if d != forte and pct[d] >= 25), None)
    return {'ajuda': area['ajuda'][forte][:3] + (area['ajuda'][seg][:1] if seg else []), 'apoio': ''}


def estilo(perfil):
    return ' + '.join(TEXTOS[d]['estilo'] for d in perfil)


def relatorio(pct, perfil):
    """O relatório de gestão (perfil principal + traços do segundo, se for combinado)."""
    p, seg = perfil[0], (perfil[1] if len(perfil) > 1 else None)
    t, t2 = TEXTOS[p], TEXTOS[seg] if seg else None
    junta = lambda chave, n1=3, n2=1: t[chave][:n1] + ([x for x in t2[chave][:n2] if x not in t[chave]] if t2 else [])
    return {
        'perfil': perfil, 'nome': P.nome_perfil(perfil), 'estilo': estilo(perfil), 'pct': pct,
        'fatores': [{'d': d, 'nome': NOMES[d], 'emoji': EMOJI[d], 'pct': pct[d], 'intensidade': P.intensidade(pct[d])} for d in DIMS],
        'resumo': t['resumo'] + (f" Também tem traços fortes de {t2['estilo']} ({t2['curto']})." if seg else ''),
        'fortes': junta('fortes', 4, 2), 'riscos': junta('riscos', 3, 1), 'decide': t['decide'], 'pressao': t['pressao'],
        'delega': junta('delega', 3, 0), 'comunica': junta('comunica', 3, 0), 'conflito': t['conflito'],
        'precisa': t['precisa'], 'desenvolver': junta('desenvolver', 3, 1), 'trabalhar': junta('trabalhar', 3, 0),
        'areas': areas_da_pessoa(pct),
    }


def resumo_pessoa(pct, perfil):
    """O que a própria pessoa vê ao terminar (sócio e líder): só o lado positivo."""
    p, seg = perfil[0], (perfil[1] if len(perfil) > 1 else None)
    fortes = TEXTOS[p]['pessoa_fortes'] + ([TEXTOS[seg]['pessoa_fortes'][0]] if seg else [])
    return {'perfil': perfil, 'nome': estilo(perfil), 'texto': TEXTOS[p]['pessoa'], 'fortes': fortes,
            'fatores': [{'d': d, 'nome': NOMES[d], 'emoji': EMOJI[d], 'pct': pct[d]} for d in DIMS]}


def nome_partes(partes):
    return ' + '.join(NOMES_PARTES[p] for p in P._partes_de(partes))


def motivacao_gestao(pontos):
    """🔋 [LIDERANÇA+] O que move a pessoa NA GESTÃO, como manter motivado(a), o cuidado e o que pesa menos."""
    top = PM.principais(pontos)[:2]
    o = PM._ordem(pontos)
    return {'nome': PM.nome(pontos), 'fatores': PM.fatores(pontos),
            'principais': [{'chave': k, 'emoji': PM.EMOJI[k], 'nome': PM.NOMES[k]} for k in top],
            'oque': [MOTIV_GESTAO[k]['gestao'] for k in top],
            'manter': MOTIV_GESTAO[top[0]]['manter'] + [x for k in top[1:] for x in MOTIV_GESTAO[k]['manter'][:1]],
            'cuidado': [MOTIV_GESTAO[k]['cuidado'] for k in top],
            'menos': [{'chave': k, 'emoji': PM.EMOJI[k], 'nome': PM.NOMES[k], 'curto': PM.CURTO[k]} for k in o[-2:]]}


def aprendizado_gestao(pontos):
    """🧠 [LIDERANÇA+] Como a pessoa aprende NA GESTÃO: como apresentar uma proposta, como combinar e como se desenvolver."""
    varios = PA.varios(pontos)
    top = PA._ordem(pontos)[:2] if varios else PA.principais(pontos)
    return {'nome': PA.nome(pontos), 'varios': varios, 'canais': PA.canais(pontos),
            'principais': [{'chave': k, 'emoji': PA.EMOJI[k], 'nome': PA.NOMES[k]} for k in top],
            'oque': ([f"Aprende bem de vários jeitos; um pouco mais {PA.CURTO[top[0]].split(':')[0]}."] if varios
                     else [PA.TEXTOS[k]['oque'] for k in top]),
            'apresentar': [APR_GESTAO[k]['apresentar'] for k in top], 'combinar': [APR_GESTAO[k]['combinar'] for k in top],
            'desenvolver': APR_GESTAO[top[0]]['desenvolver'] + [x for k in top[1:] for x in APR_GESTAO[k]['desenvolver'][:1]],
            'dica': DICA_APR_GESTAO}


def _dupla(a, b):
    """Como duas pessoas combinam na gestão, pelo fator principal de cada uma."""
    fa, fb = a['perfil'][0], b['perfil'][0]
    na, nb = CE._primeiro_nome(a['nome']), CE._primeiro_nome(b['nome'])
    if fa == fb:
        texto = IGUAIS[fa]
    else:
        chave = ''.join(sorted((fa, fb), key=DIMS.index))
        texto = DUPLAS[chave].format(**{fa: na, fb: nb})
    return {'nomes': f"{na} × {nb}", 'texto': texto}


def _divisao(socios):
    """Divisão sugerida das áreas entre os sócios: quem tem o perfil que a área mais pede."""
    saida = []
    forte_de = lambda area, s: max(area['pesos'], key=lambda d: area['pesos'][d] * s['pct'][d])
    for area in AREAS:
        notas = sorted(((_nota(area, s['pct']), s) for s in socios), key=lambda x: -x[0])
        melhor, nota = notas[0][1], notas[0][0]
        forte = forte_de(area, melhor)
        apoio, como_titulo = '', 'Como pode ajudar'
        if nota < 22:                                     # nem o melhor tem o perfil que a área pede
            principal = max(area['pesos'], key=area['pesos'].get)
            quem = 'Nenhum dos dois' if len(socios) == 2 else 'Ninguém'
            porque = (f"a área pede {area['pede'][principal]} e nenhum perfil é forte nisso: vale um apoio de fora "
                      f"(ex.: contador, consultor) ou um líder com esse perfil")
            como, como_titulo = area['ajuda'][principal][:3], 'O que o apoio de fora precisa fazer'
            apoio = f"Enquanto isso, {CE._primeiro_nome(melhor['nome'])} acompanha em: {area['pede'][forte]}."
        elif len(notas) > 1 and nota - notas[1][0] < 2:
            quem, porque = 'Os dois (dividam)' if len(socios) == 2 else 'Dividam', 'perfis parecidos para esta área'
            fortes = [(CE._primeiro_nome(s['nome']), forte_de(area, s)) for _, s in notas]
            if len({f for _, f in fortes}) > 1:           # cada um puxa um lado da área
                como = [f"{n}: {area['ajuda'][f][0].lower()[0] + area['ajuda'][f][0][1:]}" for n, f in fortes]
                apoio = "Cada um puxa um lado: " + ' · '.join(f"{n} — {area['pede'][f]}" for n, f in fortes) + '.'
            else:
                como = area['ajuda'][forte][:3]
                apoio = "Os dois têm o mesmo ponto forte aqui: dividam as tarefas e combinem quem dá a palavra final."
        else:
            quem, porque = CE._primeiro_nome(melhor['nome']), f"{area['pede'][forte]} ({_fator(melhor['pct'], forte)})"
            como = area['ajuda'][forte][:3]
            outros = [s for _, s in notas[1:]]
            if outros:
                o = outros[0]
                # o outro sócio apoia pelo fator dele que a área pede e que o responsável não cobre (se tiver um razoável)
                fo = next((d for d in sorted(area['pesos'], key=lambda d: -area['pesos'][d] * o['pct'][d])
                           if d != forte and o['pct'][d] >= 22), None)
                apoio = (f"{CE._primeiro_nome(o['nome'])} apoia em: {area['pede'][fo]} ({_fator(o['pct'], fo)})." if fo else
                         f"{CE._primeiro_nome(o['nome'])} ajuda no que {CE._primeiro_nome(melhor['nome'])} pedir, sem fazer em "
                         f"dobro: combinem quem dá a palavra final.")
        saida.append({'area': area['nome'], 'quem': quem, 'porque': porque, 'como': como, 'como_titulo': como_titulo,
                      'entrega': area['entrega'], 'apoio': apoio})
    return saida


def _chave(i):
    """A mesma pessoa: o mesmo nome (sem diferença de maiúscula e espaço); o candidato fica à parte do time."""
    return (i['papel'] == PAPEL_CANDIDATO, ' '.join(i['nome'].lower().split()))


def _juntar(lista):
    """[LIDERANÇA+] As respondidas da mesma pessoa (a mais nova primeiro) → a última com o perfil, com a motivação e com
    como aprende (podem vir de links diferentes)."""
    return (next((i for i in lista if i['pct']), None), next((i for i in lista if i['motivos']), None),
            next((i for i in lista if i['aprende']), None))


def _pessoas(respondidas):
    """[LIDERANÇA+] Uma linha por pessoa, com as 3 partes juntas. 'id' é a avaliação mais nova (o 📄 Relatório junta o resto)."""
    grupos = {}
    for i in respondidas:                                 # já vem da mais nova para a mais antiga
        grupos.setdefault(_chave(i), []).append(i)
    saida = []
    for lista in grupos.values():
        disc, motiv, apr = _juntar(lista)
        falta = [p for p, tem in (('disc', disc), ('motiv', motiv), ('apr', apr)) if not tem]
        tel = next((i['telefone'] for i in lista if i['telefone']), '')
        saida.append(dict(lista[0], pct=disc['pct'] if disc else None, perfil=disc['perfil'] if disc else '',
                          estilo=disc['estilo'] if disc else '', perfil_nome=disc['perfil_nome'] if disc else '',
                          motivos=motiv['motivos'] if motiv else None, aprende=apr['aprende'] if apr else None,
                          motiva=PM.nome(motiv['motivos']) if motiv else '', aprende_nome=PA.nome(apr['aprende']) if apr else '',
                          falta=falta, falta_nome=' + '.join(NOMES_PARTES[p] for p in falta), tem_telefone=bool(tel)))
    return saida


def _time(respondidas):
    """O time de gestão: cada sócio e líder (candidato não entra), com as partes juntas. [LIDERANÇA+] Quem ainda não fez o
    perfil de liderança aparece, mas não entra na cobertura nem nos sócios juntos."""
    return [p for p in _pessoas(respondidas) if p['papel'] != PAPEL_CANDIDATO]


def _cobertura(time_):
    time_ = [p for p in time_ if p['pct']]
    if not time_:
        return {'fatores': [], 'faltam': []}
    fatores = [{'d': d, 'nome': NOMES[d], 'emoji': EMOJI[d],
                'quem': [CE._primeiro_nome(p['nome']) for p in time_ if _forte(p, d)]} for d in DIMS]
    return {'fatores': fatores, 'faltam': [FALTA_NA_GESTAO[f['d']] for f in fatores if not f['quem']]}


def _traz(pct, time_):
    """Os fatores fortes do candidato que ninguém do time de gestão tem forte: o que ele traz de novo."""
    time_ = [p for p in time_ if p['pct']]
    if not time_ or not pct:
        return []
    return [{'d': d, 'nome': NOMES[d], 'emoji': EMOJI[d], 'curto': TEXTOS[d]['curto']}
            for d in DIMS if pct[d] >= FORTE and not any(_forte(p, d) for p in time_)]


def _forte(p, d):
    """[DEPURAÇÃO 3] Forte = FORTE% ou mais, ou parte do perfil (o '+ 🔵 Conforme' do cartão entra a partir de 27%)."""
    return p['pct'][d] >= FORTE or d in (p.get('perfil') or '')


# ------------------------------------------------------------------------------
# Criar e mandar
# ------------------------------------------------------------------------------
def _quanto(partes):
    """[LIDERANÇA+] O tamanho do questionário no texto do WhatsApp."""
    ps = P._partes_de(partes)
    info = {'disc': ("o seu estilo de liderança", f"{N_BLOCOS} situações", 12), 'motiv': ("o que te motiva", f"{PM.N_PARES} perguntas", 3),
            'apr': ("como você aprende melhor", f"{PA.N_PERGUNTAS} perguntas", 3)}
    if ps == ('disc',):
        return f"{N_BLOCOS} situações do dia a dia da gestão (uns 10 a 15 minutos)"
    if len(ps) == 1:
        return f"{info[ps[0]][1]} rápidas sobre {info[ps[0]][0]} (uns 3 minutos)"
    itens = [f"{info[p][0]} ({info[p][1]})" for p in ps]
    return f"{len(ps)} partes: {', '.join(itens[:-1])} e {itens[-1]} (uns {sum(info[p][2] for p in ps)} minutos no total)"


def texto_mensagem(nome, link, papel, lembrete=False, partes=None):
    primeiro = CE._primeiro_nome(nome)
    tem_disc = P._tem_disc(partes)
    return ((f"🔔 *Lembrete:* sua avaliação de liderança ainda está esperando você.\n\n" if lembrete else "")
            + f"👔 *Avaliação de perfil de liderança — {CE._empresa()}*\n\n"
            + (f"Olá, {primeiro}!\n" if primeiro else "Olá!\n")
            + ("Obrigado pelo interesse em fazer parte da nossa liderança! Como parte do processo, queremos conhecer o "
               "seu estilo de gestão. " if papel == PAPEL_CANDIDATO else
               "Queremos conhecer o seu estilo de gestão: como você decide, lidera e se comunica. " if tem_disc else
               "Queremos completar a sua avaliação de liderança. ")
            + f"São {_quanto(partes)} e não existe resposta certa ou errada.\n\n"
            + f"👉 *Toque no link para responder:*\n{link}")


def _validade(dados, agora):
    return P._validade(dados, agora)


def criar(dados, usuario, agora=None):
    """Nova avaliação: com WhatsApp o link vai na hora; sem WhatsApp a gestão copia o link (ou abre ali mesmo)."""
    exigir_acesso(usuario)
    agora = agora or CE._agora()
    dados = dados if isinstance(dados, dict) else {}
    nome = ' '.join(str(dados.get('nome') or '').split())
    papel = str(dados.get('papel') or '').strip()
    tel_txt = str(dados.get('telefone') or '').strip()
    if not nome:
        raise ErroPerfil("Escreva o nome.")
    if len(nome) > 150:
        raise ErroPerfil("Nome grande demais.")
    if papel not in dict(PAPEIS):
        raise ErroPerfil("Escolha o papel: sócio(a), líder da equipe ou candidato(a) a líder.")
    tel = CE.R.numero_whatsapp(tel_txt) if tel_txt else ''
    if tel_txt and not tel:
        raise ErroPerfil(f"WhatsApp inválido: '{tel_txt}'. Use o DDD + o número (ex.: 66 99999-1234).")
    # 🔋🧠 [LIDERANÇA+] o que o link pede (sem dizer: só o perfil de liderança, como era antes)
    partes = P._codigo_partes(dados['partes']) if dados.get('partes') is not None else P.P_DISC
    if not partes:
        raise ErroPerfil("Escolha o que enviar: o perfil de liderança, o que motiva e/ou como aprende.")
    valido = _validade(dados, agora)
    aid, link = _inserir(nome, tel, papel, partes, valido, usuario, agora)
    logger.info(f"[LIDERANÇA] {usuario.get('nome')} criou a avaliação {aid} ({papel}, {partes}).")
    return {'ok': True, 'id': aid, 'link': link,
            'mensagem': f"👔 Avaliação de {nome} criada ({nome_partes(partes)})." + (" O link vai no WhatsApp agora." if tel else
                        " Sem WhatsApp: copie o link (ou abra aqui mesmo para responder).")}


def _inserir(nome, tel, papel, partes, valido, usuario, agora):
    """Grava a avaliação e, com WhatsApp, manda o link na hora. Devolve (id, link)."""
    base = P._exigir_endereco()
    token = CE._token()
    conn = P._conexao()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO AvaliacoesLideranca (Nome, Telefone, Papel, Token, Status, CriadoPor, CriadoEm, ValidoAte, Versao,
                                                        Partes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?); SELECT SCOPE_IDENTITY();""",
                    nome, tel or None, papel, token, P.ST_AGUARDANDO if tel else P.ST_SEM_TEL, usuario.get('nome'), agora,
                    valido, VERSAO, partes)
        cur.nextset()
        aid = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    if tel:
        _rodar(lambda: _enviar(aid, agora))
    return aid, f"{base}/lideranca/{token}"


def _mudar(aid, de, para, soma_tentativa=False, **campos):
    """Muda a situação só se ainda estava em 'de' (duas abas ou dois cliques não mandam duas vezes)."""
    sets, args = ["Status = ?"], [para]
    for k, v in campos.items():
        sets.append(f"{k} = ?")
        args.append(v)
    if soma_tentativa:
        sets.append("Tentativas = Tentativas + 1")
    conn = P._conexao()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE AvaliacoesLideranca SET {', '.join(sets)} WHERE AvaliacaoID = ? "
                    f"AND Status IN ({','.join('?' * len(de))})", *args, int(aid), *de)
        mudou = cur.rowcount == 1
        conn.commit()
        return mudou
    finally:
        conn.close()


def _enviar(aid, agora=None):
    """Manda o link de uma avaliação no WhatsApp (na hora: liderança não espera turno)."""
    agora = agora or CE._agora()
    base, local = CE._endereco()
    with _trava:
        conn = P._conexao()
        try:
            cur = conn.cursor()
            cur.execute("SELECT Nome, Telefone, Token, Papel, Lembretes, Partes FROM AvaliacoesLideranca WHERE AvaliacaoID = ?",
                        int(aid))
            a = cur.fetchone()
        finally:
            conn.close()
        if not a or not base or local:
            return False
        if not _mudar(aid, (P.ST_AGUARDANDO, P.ST_FALHOU), P.ST_ENVIANDO, EnviadoEm=agora):
            return False
        ok, resp = CE._mandar(a[1], texto_mensagem(a[0], f"{base}/lideranca/{a[2]}", a[3], lembrete=bool(a[4]), partes=a[5]))
        if ok:
            _mudar(aid, (P.ST_ENVIANDO,), P.ST_ENVIADO, EnviadoEm=agora, Erro=None)
        else:
            _mudar(aid, (P.ST_ENVIANDO,), P.ST_FALHOU, Erro=str(resp)[:300], soma_tentativa=True)
            logger.error(f"[LIDERANÇA] Não foi para {a[0]}: {resp}")
        return bool(ok)


def _acertar(cur, agora):
    """Expira o que passou do prazo sem ser enviado e devolve à fila o envio que travou."""
    cur.execute("UPDATE AvaliacoesLideranca SET Status = ? WHERE Status IN (?, ?) AND ValidoAte < ?",
                P.ST_EXPIRADO, P.ST_AGUARDANDO, P.ST_FALHOU, agora.date())
    # [DEPURAÇÃO 3] com o motivo: antes ficava 'WhatsApp falhou: ?' (ou o erro de uma tentativa antiga)
    cur.execute("UPDATE AvaliacoesLideranca SET Status = ?, Erro = ? WHERE Status = ? AND EnviadoEm < ?",
                P.ST_FALHOU, ERRO_INTERROMPIDO, P.ST_ENVIANDO, agora - timedelta(minutes=CE.ENVIANDO_PRESO_MIN))


# ------------------------------------------------------------------------------
# Página da gestão
# ------------------------------------------------------------------------------
_COLUNAS = """AvaliacaoID, Nome, Telefone, Papel, Token, Status, Tentativas, Lembretes, CriadoEm, ValidoAte, EnviadoEm,
              AbertoEm, RespondidoEm, Perfil, PctD, PctI, PctS, PctC, Erro, Partes, Motivos, Aprendizado"""


def _item(r, base):
    (aid, nome, tel, papel, token, st, tent, lemb, criado, valido, env, ab, resp, perfil, pd, pi, ps, pc, erro,
     partes, motivos, aprende) = r
    if st in (P.ST_AGUARDANDO, P.ST_ENVIANDO):
        ic, txt = '⏳', "Enviando no WhatsApp…"
    elif st == P.ST_SEM_TEL:
        ic, txt = '🔗', "Sem WhatsApp: copie o link (ou abra aqui para responder)"
    elif st == P.ST_FALHOU:
        ic, txt = '⚠️', f"WhatsApp falhou: {erro or '?'} · use 📤 Mandar de novo"
    else:
        ic, txt = P._situacao(st, env, ab, resp, lemb, '', False, erro, tent or 0, True)
    respondido = st == P.ST_RESPONDIDO
    pct = P._pct(pd, pi, ps, pc) if respondido and perfil else None      # [LIDERANÇA+] link sem o perfil: sem barras
    motivos = P._motivos(motivos) if respondido else None
    aprende = P._aprende(aprende) if respondido else None
    return {'id': int(aid), 'nome': nome or '?', 'papel': papel, 'papel_nome': dict(PAPEIS).get(papel, papel), 'status': st,
            'icone': ic, 'situacao': txt, 'criado': CE._quando(criado), 'telefone': tel or '',
            'whatsapp': f"https://wa.me/{tel}" if tel else '',
            'link': f"{base}/lideranca/{token}" if base and st not in (P.ST_RESPONDIDO, P.ST_CANCELADO, P.ST_EXPIRADO) else '',
            'pode_agora': bool(tel) and st in (P.ST_AGUARDANDO, P.ST_FALHOU, P.ST_EXPIRADO),
            'pode_lembrar': bool(tel) and st == P.ST_ENVIADO,
            'pendente': st in (P.ST_AGUARDANDO, P.ST_ENVIANDO, P.ST_ENVIADO, P.ST_FALHOU, P.ST_SEM_TEL),
            'perfil': perfil or '', 'perfil_nome': P.nome_perfil(perfil) if pct else '',
            'estilo': estilo(perfil) if pct else '', 'pct': pct, 'respondido': CE._quando(resp),
            'partes': partes or P.P_DISC, 'partes_nome': nome_partes(partes),
            'motivos': motivos, 'aprende': aprende, 'motiva': PM.nome(motivos) if motivos else '',
            'aprende_nome': PA.nome(aprende) if aprende else ''}


def _linhas(agora):
    garantir_tabelas()
    conn = P._conexao()
    try:
        cur = conn.cursor()
        _acertar(cur, agora)
        conn.commit()
        cur.execute(f"SELECT {_COLUNAS} FROM AvaliacoesLideranca ORDER BY AvaliacaoID DESC")
        return cur.fetchall()
    finally:
        conn.close()


def painel(usuario, agora=None):
    if not pode_ver(usuario):                             # a página mostra o cadeado (um 403 levaria para o login)
        return {'bloqueado': True, 'mensagem': "🔒 A 👔 Liderança é só de quem os sócios liberaram. Peça para um sócio liberar você."}
    agora = agora or CE._agora()
    base, local = CE._endereco()
    itens = [_item(r, base) for r in _linhas(agora)]
    respondidas = [i for i in itens if i['status'] == P.ST_RESPONDIDO]
    time_ = _time(respondidas)
    socios = [p for p in time_ if p['papel'] == 'socio' and p['pct']]
    for i in itens:
        if i['papel'] == PAPEL_CANDIDATO and i['pct']:
            i['traz'] = _traz(i['pct'], time_)
    ids = _ler_acesso()
    try:
        lista_gestores = gestores()
    except Exception as e:
        logger.error(f"[LIDERANÇA] Não listei os gestores: {e}")
        lista_gestores = []
    return {'avaliacoes': [_publico(i) for i in itens[:300]], 'papeis': [{'chave': c, 'nome': n} for c, n in PAPEIS],
            'time': [{'id': p['id'], 'nome': p['nome'], 'papel_nome': p['papel_nome'], 'estilo': p['estilo'],
                      'perfil_nome': p['perfil_nome'], 'pct': p['pct'], 'motiva': p['motiva'], 'aprende': p['aprende_nome'],
                      'falta': p['falta'], 'falta_nome': p['falta_nome'], 'tem_telefone': p['tem_telefone'],
                      'pendente': _pendente(itens, p)} for p in time_],
            'cobertura': _cobertura(time_),
            'socios': {'duplas': [_dupla(socios[i], socios[j]) for i in range(len(socios)) for j in range(i + 1, len(socios))],
                       'divisao': _divisao(socios) if len(socios) >= 2 else []},
            'como_cada_um': _como_cada_um(time_),
            'partes': [{'chave': p, 'nome': NOMES_PARTES[p]} for p in ('disc', 'motiv', 'apr')],
            'acesso': {'restrito': bool(ids), 'ids': sorted(ids), 'gestores': lista_gestores},
            'perguntas': N_BLOCOS, 'link_local': bool(local or not base), 'hoje': agora.date().isoformat(),
            'validade_padrao': (agora.date() + timedelta(days=P.VALIDADE_PADRAO_DIAS)).isoformat(),
            'validade_max': (agora.date() + timedelta(days=P.VALIDADE_MAX_DIAS)).isoformat()}


def _publico(i):
    """O cartão da avaliação na tela (sem as notas cruas da motivação e do aprendizado)."""
    return {k: v for k, v in i.items() if k not in ('motivos', 'aprende')}


def _pendente(itens, pessoa):
    """[LIDERANÇA+] Um link da mesma pessoa ainda esperando resposta (para não mandar o que falta duas vezes)."""
    return next(({'id': i['id'], 'partes_nome': i['partes_nome'], 'link': i['link']} for i in itens
                 if i['pendente'] and _chave(i) == _chave(pessoa)), None)


def _como_cada_um(time_):
    """🔋🧠 [LIDERANÇA+] O que move cada um e como passar uma informação para cada um (sócios e líderes)."""
    saida = []
    for p in time_:
        if not p['motivos'] and not p['aprende']:
            continue
        m = motivacao_gestao(p['motivos']) if p['motivos'] else None
        a = aprendizado_gestao(p['aprende']) if p['aprende'] else None
        saida.append({'nome': CE._primeiro_nome(p['nome']) or p['nome'], 'motiva': m['nome'] if m else '',
                      'move': m['oque'][0] if m else '', 'aprende': a['nome'] if a else '',
                      'apresentar': a['apresentar'][0] if a else ''})
    return saida


def detalhe(aid, usuario, agora=None):
    """O relatório de gestão de uma avaliação respondida (e, se for candidato, como combina com o time)."""
    exigir_acesso(usuario)
    agora = agora or CE._agora()
    base = CE._endereco()[0]
    itens = [_item(r, base) for r in _linhas(agora)]
    a = next((i for i in itens if i['id'] == int(aid)), None)
    if not a:
        raise ErroPerfil("Avaliação não encontrada.", 404)
    if a['status'] != P.ST_RESPONDIDO:
        raise ErroPerfil("Esta avaliação ainda não foi respondida.", 409)
    respondidas = [i for i in itens if i['status'] == P.ST_RESPONDIDO]
    mesma = [i for i in respondidas if _chave(i) == _chave(a)]
    # [LIDERANÇA+] cada parte: deste link ou a última resposta da mesma pessoa
    disc = a if a['pct'] else _juntar(mesma)[0]
    motiv = a if a['motivos'] else _juntar(mesma)[1]
    apr = a if a['aprende'] else _juntar(mesma)[2]
    if disc:
        r = relatorio(disc['pct'], disc['perfil'])
        r['perfil_de'] = '' if disc is a else disc['respondido']
    else:
        r = {'perfil': '', 'nome': '', 'estilo': '', 'pct': None, 'sem_perfil': True}
    time_ = [p for p in _time(respondidas) if _chave(p) != _chave(a) and p['pct']]
    eu = dict(a, pct=disc['pct'], perfil=disc['perfil']) if disc else None
    falta = [p for p, tem in (('disc', disc), ('motiv', motiv), ('apr', apr)) if not tem]
    r.update({'id': a['id'], 'nome': a['nome'], 'perfil_nome': disc['perfil_nome'] if disc else '', 'papel': a['papel'],
              'papel_nome': a['papel_nome'], 'respondido': a['respondido'], 'candidato': a['papel'] == PAPEL_CANDIDATO,
              'com_time': [dict(_dupla(eu, p), papel_nome=p['papel_nome']) for p in time_] if eu else [],
              'anteriores': [{'id': i['id'], 'respondido': i['respondido'], 'estilo': i['estilo']} for i in mesma
                             if i['pct'] and i['id'] != a['id'] and i is not disc],
              'motivacao': motivacao_gestao(motiv['motivos']) if motiv else None,
              'motivacao_de': '' if not motiv or motiv is a else motiv['respondido'],
              'aprendizado': aprendizado_gestao(apr['aprende']) if apr else None,
              'aprendizado_de': '' if not apr or apr is a else apr['respondido'],
              'falta': falta, 'falta_nome': ' + '.join(NOMES_PARTES[p] for p in falta),
              'pendente': _pendente(itens, a)})
    if r['candidato'] and disc:
        r['traz'] = _traz(disc['pct'], time_)
    return r


def mandar_falta(aid, usuario, agora=None):
    """🔋🧠 [LIDERANÇA+] Um link novo só com o que a pessoa ainda não respondeu (ex.: quem já fez o perfil de liderança
    recebe só 🔋 o que motiva e 🧠 como aprende). Com WhatsApp vai na hora; sem, a gestão copia o link."""
    exigir_acesso(usuario)
    agora = agora or CE._agora()
    itens = [_item(r, CE._endereco()[0]) for r in _linhas(agora)]
    a = next((i for i in itens if i['id'] == int(aid)), None)
    if not a:
        raise ErroPerfil("Avaliação não encontrada.", 404)
    mesma = [i for i in itens if _chave(i) == _chave(a)]
    disc, motiv, apr = _juntar([i for i in mesma if i['status'] == P.ST_RESPONDIDO])
    falta = [p for p, tem in (('disc', disc), ('motiv', motiv), ('apr', apr)) if not tem]
    if not falta:
        raise ErroPerfil(f"{a['nome']} já respondeu as 3 partes.", 409)
    pendente = _pendente(itens, a)
    if pendente:
        raise ErroPerfil(f"{a['nome']} já tem um link esperando resposta ({pendente['partes_nome']}). Use 🔔 Lembrar ou "
                         f"🔗 Copiar link em 📋 Avaliações (ou ⛔ cancele esse link e mande de novo).", 409)
    partes = P._codigo_partes(falta)
    tel = next((i['telefone'] for i in mesma if i['telefone']), '')
    novo, link = _inserir(a['nome'], tel, a['papel'], partes, agora.date() + timedelta(days=P.VALIDADE_PADRAO_DIAS), usuario, agora)
    logger.info(f"[LIDERANÇA] {usuario.get('nome')} mandou o que falta ({partes}) para a avaliação {aid} → {novo}.")
    return {'ok': True, 'id': novo, 'link': link, 'whatsapp': bool(tel),
            'mensagem': f"📤 {nome_partes(partes)} para {CE._primeiro_nome(a['nome']) or a['nome']}: "
                        + ("o link vai no WhatsApp agora." if tel else "sem WhatsApp, copie o link (ou responda aqui mesmo).")}


def acao(aid, nome_acao, usuario, agora=None):
    """🔔 lembrar · 📤 mandar agora · ⛔ cancelar · 🗑️ apagar · 🔋🧠 mandar o que falta."""
    exigir_acesso(usuario)
    garantir_tabelas()
    agora = agora or CE._agora()
    if nome_acao == 'falta':
        return mandar_falta(aid, usuario, agora)
    conn = P._conexao()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Status, ValidoAte, Nome, Telefone FROM AvaliacoesLideranca WHERE AvaliacaoID = ?", int(aid))
        a = cur.fetchone()
    finally:
        conn.close()
    if not a:
        raise ErroPerfil("Avaliação não encontrada.", 404)
    st, valido, nome, tel = a[0], database._como_data(a[1]), a[2], a[3]
    if nome_acao == 'apagar':
        conn = P._conexao()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM AvaliacoesLideranca WHERE AvaliacaoID = ?", int(aid))
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[LIDERANÇA] {usuario.get('nome')} apagou a avaliação {aid}.")
        return {'ok': True, 'mensagem': f"🗑️ Avaliação de {nome} apagada (nome, WhatsApp e respostas)."}
    if nome_acao in ('lembrar', 'agora') and not tel:
        raise ErroPerfil("Sem WhatsApp: copie o link e mande você mesmo.", 409)
    novo_prazo = max(valido, agora.date() + timedelta(days=P.VALIDADE_PADRAO_DIAS)) if valido else agora.date()
    if nome_acao == 'lembrar':
        if st != P.ST_ENVIADO:
            raise ErroPerfil("Só dá para lembrar quem já recebeu e ainda não respondeu.", 409)
        _mudar(aid, (P.ST_ENVIADO,), P.ST_AGUARDANDO, ValidoAte=novo_prazo, Tentativas=0)
        conn = P._conexao()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE AvaliacoesLideranca SET Lembretes = Lembretes + 1 WHERE AvaliacaoID = ?", int(aid))
            conn.commit()
        finally:
            conn.close()
        _rodar(lambda: _enviar(aid, agora))
        return {'ok': True, 'mensagem': f"🔔 {nome} recebe o lembrete agora."}
    if nome_acao == 'agora':
        if st not in (P.ST_AGUARDANDO, P.ST_FALHOU, P.ST_EXPIRADO):
            raise ErroPerfil("Esta avaliação não está esperando envio.", 409)
        _mudar(aid, (P.ST_AGUARDANDO, P.ST_FALHOU, P.ST_EXPIRADO), P.ST_AGUARDANDO, Tentativas=0, ValidoAte=novo_prazo)
        _rodar(lambda: _enviar(aid, agora))
        return {'ok': True, 'mensagem': f"📤 Mandando agora para {nome}."}
    if nome_acao == 'cancelar':
        if not _mudar(aid, (P.ST_AGUARDANDO, P.ST_FALHOU, P.ST_ENVIADO, P.ST_EXPIRADO, P.ST_SEM_TEL), P.ST_CANCELADO,
                      CanceladoEm=agora):
            raise ErroPerfil("Esta avaliação não pode mais ser cancelada.", 409)
        logger.info(f"[LIDERANÇA] {usuario.get('nome')} cancelou a avaliação {aid}.")
        return {'ok': True, 'mensagem': f"⛔ Avaliação de {nome} cancelada (o link deixa de funcionar)."}
    raise ErroPerfil("Ação desconhecida.", 404)


# ------------------------------------------------------------------------------
# Página pública do link (/lideranca/<código>)
# ------------------------------------------------------------------------------
def _por_token(cur, token):
    if not token or len(str(token)) > 40:
        return None
    cur.execute("""SELECT AvaliacaoID, Nome, Papel, Status, AbertoEm, Perfil, PctD, PctI, PctS, PctC, RespondidoEm,
                          Partes, Motivos, Aprendizado
                   FROM AvaliacoesLideranca WHERE Token = ?""", str(token))
    return cur.fetchone()


def ver(token, agora=None):
    """As situações (sem dizer qual frase é de qual fator) ou, se já respondeu, o resumo da pessoa."""
    garantir_tabelas()
    agora = agora or CE._agora()
    conn = P._conexao()
    try:
        cur = conn.cursor()
        a = _por_token(cur, token)
        if not a or a[3] == P.ST_CANCELADO:
            raise ErroPerfil("Link inválido ou cancelado. Peça um link novo.", 404)
        if a[3] == P.ST_EXPIRADO:
            raise ErroPerfil("O prazo desta avaliação acabou. Peça um link novo.", 410)
        if not a[4] and a[3] != P.ST_RESPONDIDO:
            cur.execute("UPDATE AvaliacoesLideranca SET AbertoEm = ? WHERE AvaliacaoID = ? AND AbertoEm IS NULL", agora, a[0])
            conn.commit()
    finally:
        conn.close()
    nome, candidato, partes = CE._primeiro_nome(a[1]), a[2] == PAPEL_CANDIDATO, a[11] or P.P_DISC
    comum = {'nome': nome, 'empresa': CE._empresa(), 'candidato': candidato, 'papel_nome': dict(PAPEIS).get(a[2], ''),
             'partes': partes}
    if a[3] == P.ST_RESPONDIDO:
        if candidato:                                     # candidato: só o obrigado (o resultado fica com os sócios)
            return dict(comum, respondido=True, respondido_em=CE._quando(a[10]))
        motivos, aprende = P._motivos(a[12]), P._aprende(a[13])
        return dict(comum, respondido=True, respondido_em=CE._quando(a[10]),
                    resultado=resumo_pessoa(P._pct(a[6], a[7], a[8], a[9]), a[5]) if a[5] else None,
                    motivacao=PM.resumo_pessoa(motivos) if motivos else None,       # [LIDERANÇA+] o lado positivo
                    aprendizado=PA.resumo_pessoa(aprende) if aprende else None)
    tem_disc = P._tem_disc(partes)
    return dict(comum, respondido=False, treino=TREINO if tem_disc else None,
                blocos=[{'pergunta': SITUACOES[k][0], 'opcoes': [texto for texto, _ in bloco]} for k, bloco in enumerate(BLOCOS)]
                if tem_disc else [],
                pares=PM.perguntas() if P._tem_motiv(partes) else [],          # [LIDERANÇA+] 🔋 parte 2 (ou a única)
                aprende=PA.perguntas() if P._tem_apr(partes) else [])          # [LIDERANÇA+] 🧠 parte 3 (ou a única)


def responder(token, dados, agora=None):
    """Recebe as respostas das partes do link (perfil: [[MAIS, MENOS], …] de cada situação; [LIDERANÇA+] 🔋 o lado escolhido
    em cada pergunta; 🧠 a resposta de cada situação), calcula e guarda (uma vez só)."""
    garantir_tabelas()
    agora = agora or CE._agora()
    dados = dados if isinstance(dados, dict) else {}
    conn = P._conexao()
    try:
        a = _por_token(conn.cursor(), token)
    finally:
        conn.close()
    if not a or a[3] == P.ST_CANCELADO:
        raise ErroPerfil("Link inválido ou cancelado. Peça um link novo.", 404)
    if a[3] == P.ST_EXPIRADO:
        raise ErroPerfil("O prazo desta avaliação acabou. Peça um link novo.", 410)
    partes = a[11] or P.P_DISC
    escolhas = pct = perfil = motivos = escolhidas = aprende = aprende_escolhas = None
    if P._tem_disc(partes):
        respostas = dados.get('respostas')
        if not isinstance(respostas, list) or len(respostas) != N_BLOCOS:
            raise ErroPerfil(f"Responda as {N_BLOCOS} situações antes de enviar.")
        escolhas = []
        for k, r in enumerate(respostas):
            try:
                mais, menos = int(r[0]), int(r[1])
            except (TypeError, ValueError, IndexError):
                raise ErroPerfil(f"Situação {k + 1} incompleta: escolha a frase que MAIS e a que MENOS parece com você.")
            if not (0 <= mais < 4 and 0 <= menos < 4) or mais == menos:
                raise ErroPerfil(f"Situação {k + 1}: a frase do MAIS e a do MENOS precisam ser diferentes.")
            escolhas.append((BLOCOS[k][mais][1], BLOCOS[k][menos][1]))
        pct, perfil = P.calcular(escolhas)
    if P._tem_motiv(partes):
        try:
            motivos, escolhidas = PM.calcular(dados.get('motivos'))
        except PM.ErroMotivacao as e:
            raise ErroPerfil(str(e))
    if P._tem_apr(partes):
        try:
            aprende, aprende_escolhas = PA.calcular(dados.get('aprendizado'))
        except PA.ErroAprendizado as e:
            raise ErroPerfil(str(e))
    conn = P._conexao()
    try:
        cur = conn.cursor()
        if a[3] != P.ST_RESPONDIDO:                       # já respondeu (ex.: tocou duas vezes): fica a primeira resposta
            cur.execute("""UPDATE AvaliacoesLideranca SET Status = ?, RespondidoEm = ?, AbertoEm = ISNULL(AbertoEm, ?),
                                  Respostas = ?, Versao = ?, PctD = ?, PctI = ?, PctS = ?, PctC = ?, Perfil = ?,
                                  Motivos = ?, MotivoRespostas = ?, MotivoEm = ?,
                                  Aprendizado = ?, AprendizadoRespostas = ?, AprendizadoEm = ?
                           WHERE AvaliacaoID = ? AND Status <> ?""",
                        P.ST_RESPONDIDO, agora, agora, json.dumps(escolhas) if escolhas else None, VERSAO,
                        *((pct['D'], pct['I'], pct['S'], pct['C']) if pct else (None,) * 4), perfil,
                        json.dumps(motivos) if motivos else None, json.dumps(escolhidas) if escolhidas else None,
                        agora if motivos else None,
                        json.dumps(aprende) if aprende else None, json.dumps(aprende_escolhas) if aprende_escolhas else None,
                        agora if aprende else None, a[0], P.ST_RESPONDIDO)
            if cur.rowcount == 1:
                logger.info(f"[LIDERANÇA] Avaliação {a[0]} respondida ({partes}).")
            conn.commit()
    finally:
        conn.close()
    return ver(token, agora)

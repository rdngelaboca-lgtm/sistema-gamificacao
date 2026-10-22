# ==============================================================================
# == perfil_motivacao.py - 🔋 "O que te motiva": a 2ª parte da avaliação de perfil ==
# ==============================================================================
# 8 motivações do dia a dia na loja: 💰 Financeiro, 🏆 Reconhecimento, 📚 Aprendizado, 🤝 Equipe, 🛡️ Estabilidade,
# 🗽 Autonomia, 🎯 Desafio e 💜 Propósito.
# 28 perguntas de "qual frase combina mais com você" (todas as duplas, cada motivação aparece 7 vezes, com uma frase
# diferente em cada vez). Escolher entre duas é mais honesto que dar nota de 1 a 5 (na nota, todo mundo marca "tudo importa").
# As frases DESCREVEM a pessoa ("Gosto de aprender coisas novas"); não são coisas que a loja daria (bônus, aumento,
# folga, curso…): assim ninguém escolhe pensando no que vai ganhar, e o dinheiro não vence sempre.
# Cada escolha dá 1 ponto à motivação: cada uma vai de 0 a 7 e o total é sempre 28.
# O relatório da gestão diz o que move a pessoa, como motivar, que prêmios funcionam (para a gamificação) e o que
# evitar; a pessoa vê só o lado positivo. Questionário NOSSO: serve para conhecer e motivar a equipe, não para
# contratar ou demitir sozinho.
# ==============================================================================

# (chave, emoji, nome, curto)
MOTIVOS = [
    ('dinheiro', '💰', 'Financeiro', 'conquistas e independência financeira'),
    ('reconhecimento', '🏆', 'Reconhecimento', 'ser notado e valorizado'),
    ('crescimento', '📚', 'Aprendizado', 'aprender e evoluir'),
    ('equipe', '🤝', 'Equipe', 'ambiente e amizade'),
    ('seguranca', '🛡️', 'Estabilidade', 'rotina, regras claras e tranquilidade'),
    ('autonomia', '🗽', 'Autonomia', 'liberdade e confiança'),
    ('desafio', '🎯', 'Desafio', 'metas e superação'),
    ('proposito', '💜', 'Propósito', 'fazer diferença para as pessoas'),
]
CHAVES = [m[0] for m in MOTIVOS]
EMOJI = {m[0]: m[1] for m in MOTIVOS}
NOMES = {m[0]: m[2] for m in MOTIVOS}
CURTO = {m[0]: m[3] for m in MOTIVOS}
MAXIMO = len(MOTIVOS) - 1                       # cada motivação disputa com as outras 7
ENUNCIADO = 'Qual frase combina mais com você?'

# Uma frase por vez que a motivação aparece (a 1ª frase na 1ª rodada, a 2ª na 2ª…)
FRASES = {
    'dinheiro': ["Trabalho pensando nas coisas que quero conquistar", "Fico de olho em como fazer o meu dinheiro render",
                 "Ter o meu próprio dinheiro é muito importante para mim", "Gosto de juntar dinheiro para um objetivo",
                 "Vejo o trabalho como o caminho para melhorar de vida", "Me orgulho de pagar as minhas coisas com o meu esforço",
                 "Tenho planos que dependem do que eu ganho"],
    'reconhecimento': ["Me sinto bem quando percebem o meu capricho", "Um elogio sincero faz o meu dia",
                       "Gosto quando o meu esforço é notado", "Gosto de ser lembrado(a) como alguém que faz bem feito",
                       "Fico feliz quando alguém comenta o meu trabalho", "Gosto que saibam quando fui eu quem fez",
                       "Me importa que valorizem o que eu faço"],
    'crescimento': ["Gosto de aprender coisas novas", "Gosto de perceber que estou melhor do que antes",
                    "Quando vejo alguém fazer diferente, quero aprender", "Penso onde quero chegar daqui a alguns anos",
                    "Gosto quando alguém me ensina um jeito melhor", "Fico curioso(a) para entender como as coisas funcionam",
                    "Para mim, todo trabalho é uma chance de aprender"],
    'equipe': ["Trabalhar com quem eu gosto faz toda a diferença", "Gosto de um ambiente onde todo mundo se ajuda",
               "Gosto de conversar e dar risada com os colegas", "Me sinto bem quando faço parte de um time unido",
               "Gosto de ajudar um colega que está apertado", "Um clima bom me dá mais vontade de trabalhar",
               "Gosto de ter amigos no trabalho"],
    'seguranca': ["Gosto de saber com antecedência o que vou fazer", "Me sinto bem com uma rotina organizada",
                  "Gosto de ter tranquilidade sobre o meu futuro", "Gosto quando as regras são claras e não mudam toda hora",
                  "Prefiro saber exatamente o que esperam de mim", "Gosto de ficar bastante tempo no mesmo lugar",
                  "Prefiro um dia a dia previsível, sem surpresas"],
    'autonomia': ["Gosto de fazer as coisas do meu jeito", "Me sinto bem quando confiam em mim sem ficar conferindo",
                  "Gosto de resolver as coisas sozinho(a)", "Gosto de organizar a minha própria tarefa",
                  "Gosto de dar ideias e colocar em prática", "Prefiro saber o objetivo e escolher o caminho",
                  "Gosto de cuidar de uma parte do trabalho como se fosse minha"],
    'desafio': ["Gosto de dias corridos, com muita coisa acontecendo", "Me animo quando tenho uma meta para bater",
                "Gosto de tentar fazer melhor que da última vez", "Gosto de tarefas difíceis",
                "Gosto de resolver o problema que ninguém resolveu", "Gosto de competir, nem que seja comigo mesmo(a)",
                "Gosto de mostrar do que sou capaz"],
    'proposito': ["Gosto de ver o cliente saindo feliz", "Gosto de saber que o meu trabalho faz diferença para alguém",
                  "Gosto de deixar o dia das pessoas melhor", "Gosto de ver uma criança feliz com o sorvete",
                  "Me importa trabalhar num lugar que trata bem as pessoas", "Gosto que o meu trabalho tenha um sentido",
                  "Gosto de fazer o cliente se sentir bem recebido"],
}


def _rodadas():
    """As 28 duplas em 7 rodadas (método do círculo): em cada rodada cada motivação aparece uma vez só, então nunca
    vem a mesma em duas perguntas seguidas. Lado esquerdo/direito equilibrado (cada uma fica 3 ou 4 vezes em cima):
    quem está na dúvida tende a tocar na primeira opção."""
    n, saida, em_cima = len(CHAVES), [], [0] * len(CHAVES)
    for r in range(n - 1):
        duplas = [(n - 1, r)] + [((r + i) % (n - 1), (r - i) % (n - 1)) for i in range(1, n // 2)]
        for k, (a, b) in enumerate(duplas):
            if em_cima[a] > em_cima[b] or (em_cima[a] == em_cima[b] and (r + k) % 2):
                a, b = b, a
            em_cima[a] += 1
            saida.append((r, (a, b)))
    return saida


PARES = [(CHAVES[a], CHAVES[b], FRASES[CHAVES[a]][r], FRASES[CHAVES[b]][r]) for r, (a, b) in _rodadas()]
N_PARES = len(PARES)

# Para a gestão (o que move · como motivar · prêmios que funcionam · o que evitar) e o resumo positivo da pessoa
TEXTOS = {
    'dinheiro': {
        'oque': "Se move pelas conquistas: ter o próprio dinheiro, juntar para os planos e melhorar de vida.",
        'como': ["Converse sobre os planos dele(a) e mostre como o trabalho ajuda a chegar lá.",
                 "Deixe claro como funcionam o pagamento, as diárias e as metas (sem surpresa).",
                 "Quando tiver hora extra, diária a mais ou meta com prêmio, ofereça: ele(a) costuma topar."],
        'premios': ["Prêmio em dinheiro ou Pix", "Vale-compras", "Hora extra ou diária a mais"],
        'evite': ["Atrasar ou errar o pagamento", "Prometer prêmio e não cumprir"],
        'pessoa': "Você se motiva pelas suas conquistas: o trabalho é o caminho para os seus planos.",
        'equipe': "deixe o pagamento sempre claro e em dia e, quando der, use metas com prêmio em dinheiro ou vale."},
    'reconhecimento': {
        'oque': "Se move por ser visto(a) e valorizado(a): elogio, destaque e ter o esforço notado.",
        'como': ["Elogie na hora e na frente da equipe quando fizer bem feito.",
                 "Dê destaque no grupo do WhatsApp e no \"destaque do mês\".",
                 "Agradeça pelo nome: \"Fulano, obrigado pelo capricho hoje\"."],
        'premios': ["Destaque do mês (foto no mural ou no grupo)", "Medalha ou certificado", "Elogio da gestão em público"],
        'evite': ["Trabalho bem feito passar em branco", "Crítica na frente dos outros"],
        'pessoa': "Você dá o seu melhor quando sente que o seu trabalho é notado e valorizado.",
        'equipe': "invista em elogio em público, destaque do mês e agradecimento pelo nome."},
    'crescimento': {
        'oque': "Se move por aprender e evoluir: coisas novas, ficar melhor no que faz e pensar no futuro.",
        'como': ["Ensine uma função nova a cada mês (caixa, montagem, câmara fria…).",
                 "Mostre o caminho: o que precisa para virar líder ou subir.",
                 "Dê feedback com dicas práticas para melhorar."],
        'premios': ["Curso ou treinamento", "Chance de aprender uma função nova", "Ser o líder do turno por um dia"],
        'evite': ["Fazer sempre a mesma coisa, sem aprender nada novo", "Não ver futuro na empresa"],
        'pessoa': "Você se motiva aprendendo: gosta de coisas novas e de ver que está evoluindo.",
        'equipe': "ofereça treinamentos, rodízio de funções e mostre o caminho para crescer."},
    'equipe': {
        'oque': "Se move pelo ambiente: colegas unidos, clima leve e sentir que faz parte do time.",
        'como': ["Cuide do clima: resolva rápido as brigas e as fofocas.",
                 "Faça metas de equipe (todo mundo ganha junto) e confraternizações.",
                 "Escale junto com quem ele(a) se dá bem."],
        'premios': ["Confraternização da equipe (pizza, açaí)", "Meta coletiva com prêmio para todos",
                    "Turno junto com os amigos"],
        'evite': ["Clima pesado, brigas e fofoca", "Trabalhar isolado(a), sem ajuda"],
        'pessoa': "Você se motiva com gente: dá o seu melhor num time unido, onde todo mundo se ajuda.",
        'equipe': "invista em metas coletivas, confraternizações e no clima da equipe."},
    'seguranca': {
        'oque': "Se move pela estabilidade: rotina organizada, regras claras e tranquilidade sobre o futuro.",
        'como': ["Mantenha a escala organizada e avise as mudanças com antecedência.",
                 "Deixe claro o que se espera em cada função (passo a passo).",
                 "Pague sempre em dia e explique os direitos e benefícios."],
        'premios': ["Escala fixa ou folga combinada", "Benefício fixo (vale, cesta)", "Contrato e direitos em dia"],
        'evite': ["Mudança de última hora na escala", "Regra que muda toda hora ou vale diferente para cada um"],
        'pessoa': "Você se motiva com organização: rende mais quando sabe o que esperar e tem uma rotina segura.",
        'equipe': "invista em escala organizada com antecedência, regras claras e pagamento em dia."},
    'autonomia': {
        'oque': "Se move pela liberdade: confiança, fazer do próprio jeito e colocar as ideias em prática.",
        'como': ["Combine o resultado e deixe que ele(a) escolha como fazer.",
                 "Peça ideias e use as boas (e diga que a ideia foi dele(a)).",
                 "Dê uma parte do trabalho para ele(a) cuidar (um setor, uma tarefa do dia)."],
        'premios': ["Escolher a folga ou o horário", "Cuidar do próprio setor do jeito dele(a)",
                    "Ver uma ideia sua colocada em prática"],
        'evite': ["Ficar vigiando o tempo todo", "Regra rígida sem explicação"],
        'pessoa': "Você se motiva com confiança: gosta de ter espaço para fazer do seu jeito e dar ideias.",
        'equipe': "dê mais confiança, peça ideias e deixe cada um cuidar de uma parte do trabalho."},
    'desafio': {
        'oque': "Se move por metas e superação: bater meta, fazer melhor que da última vez e dar conta do difícil.",
        'como': ["Dê metas claras e difíceis (mas possíveis) e mostre o placar.",
                 "Use o ranking da gamificação e disputas saudáveis.",
                 "Escale nos dias de mais movimento: ele(a) gosta do desafio."],
        'premios': ["1º lugar no ranking com prêmio", "Troféu ou medalha de recorde", "Missões especiais com pontos extras"],
        'evite': ["Trabalho sem meta nem placar", "Tarefa fácil e repetitiva por muito tempo"],
        'pessoa': "Você se motiva com desafios: gosta de metas, de se superar e de mostrar do que é capaz.",
        'equipe': "use o ranking da gamificação, metas com placar e disputas saudáveis."},
    'proposito': {
        'oque': "Se move por fazer diferença: deixar o cliente feliz e sentir que o trabalho tem sentido.",
        'como': ["Mostre os elogios de clientes que ele(a) recebeu.",
                 "Explique o porquê das tarefas (como ajuda o cliente).",
                 "Chame para as ações do bem e os eventos da loja."],
        'premios': ["Elogio de cliente compartilhado com a equipe", "Participar das ações sociais da loja",
                    "Ser quem recebe os clientes especiais"],
        'evite': ["Ver o cliente mal atendido e não poder fazer nada", "Tarefa sem sentido, sem saber para que serve"],
        'pessoa': "Você se motiva fazendo o bem: adora ver o cliente feliz e ter orgulho do que faz.",
        'equipe': "compartilhe os elogios dos clientes e mostre o impacto do trabalho de cada um."},
}


class ErroMotivacao(ValueError):
    pass


def perguntas():
    """O que a página mostra: as duas frases de cada pergunta (sem dizer de qual motivação é cada uma)."""
    return [{'pergunta': ENUNCIADO, 'opcoes': [fa, fb]} for _, _, fa, fb in PARES]


def calcular(escolhas):
    """escolhas: o lado escolhido em cada pergunta (0 ou 1). Devolve ({motivação: pontos de 0 a 7}, [motivações escolhidas])."""
    if not isinstance(escolhas, list) or len(escolhas) != N_PARES:
        raise ErroMotivacao(f"Responda as {N_PARES} perguntas da parte 2 antes de enviar.")
    pontos, escolhidas = {k: 0 for k in CHAVES}, []
    for i, e in enumerate(escolhas):
        if e not in (0, 1) or isinstance(e, bool):
            raise ErroMotivacao(f"Parte 2, pergunta {i + 1}: escolha uma das duas opções.")
        k = PARES[i][e]
        pontos[k] += 1
        escolhidas.append(k)
    return pontos, escolhidas


def _ordem(pontos):
    return sorted(CHAVES, key=lambda k: (-int(pontos.get(k) or 0), CHAVES.index(k)))


def principais(pontos):
    """As que mais movem: as 2 primeiras (até 3 se a 3ª empatar com a 2ª)."""
    o = _ordem(pontos)
    seg = int(pontos.get(o[1]) or 0)
    return [k for k in o[:3] if int(pontos.get(k) or 0) >= seg][:3]


def nome(pontos):
    """'🏆 Reconhecimento · 📈 Crescimento'"""
    return ' · '.join(f"{EMOJI[k]} {NOMES[k]}" for k in principais(pontos)[:2]) if pontos else ''


def fatores(pontos):
    return [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k], 'curto': CURTO[k], 'pontos': int(pontos.get(k) or 0),
             'pct': round(100 * int(pontos.get(k) or 0) / MAXIMO)} for k in _ordem(pontos)]


def relatorio(pontos):
    """O relatório da gestão: o que move, como motivar, prêmios que funcionam, o que evitar e o que pesa menos."""
    top = principais(pontos)
    o = _ordem(pontos)
    junta = lambda campo, n1, n2: TEXTOS[top[0]][campo][:n1] + [x for k in top[1:2] for x in TEXTOS[k][campo][:n2]]
    return {'nome': nome(pontos), 'principais': [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k]} for k in top],
            'fatores': fatores(pontos),
            'oque': [TEXTOS[k]['oque'] for k in top[:2]],
            'como': junta('como', 3, 2), 'premios': junta('premios', 3, 2), 'evite': junta('evite', 2, 1),
            'menos': [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k], 'curto': CURTO[k]} for k in o[-2:]]}


def resumo_pessoa(pontos):
    """O que a própria pessoa vê: só o lado positivo (as 2 que mais movem)."""
    top = principais(pontos)[:2]
    return {'nome': nome(pontos), 'textos': [TEXTOS[k]['pessoa'] for k in top],
            'principais': [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k], 'curto': CURTO[k]} for k in top]}


def resumo_equipe(lista):
    """lista: os pontos de cada pessoa que respondeu. Quantas pessoas cada motivação move mais e as dicas para a equipe."""
    lista = [p for p in lista if p]
    if not lista:
        return {'contagem': [], 'dicas': [], 'premios': []}
    conta = {k: 0 for k in CHAVES}
    for p in lista:
        for k in principais(p)[:2]:
            conta[k] += 1
    ordem = sorted(CHAVES, key=lambda k: (-conta[k], CHAVES.index(k)))
    dicas = []
    for k in ordem[:2]:
        if conta[k] and (len(lista) < 3 or conta[k] / len(lista) >= .4):
            verbo = "é movido(a)" if conta[k] == 1 else "são movidos"
            dicas.append(f"{conta[k]} de {len(lista)} {verbo} por {EMOJI[k]} {NOMES[k]} ({CURTO[k]}): {TEXTOS[k]['equipe']}")
    premios = []
    for k in ordem[:3]:
        if conta[k]:
            premios += [x for x in TEXTOS[k]['premios'][:2] if x not in premios]
    return {'contagem': [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k], 'pessoas': conta[k]} for k in ordem if conta[k]],
            'dicas': dicas, 'premios': premios[:5]}

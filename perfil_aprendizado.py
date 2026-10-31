# ==============================================================================
# == perfil_aprendizado.py - 🧠 "Como você aprende": a 3ª parte da avaliação de perfil ==
# ==============================================================================
# 4 jeitos de aprender (o modelo VAK/VARK): 👀 Visual (ver), 👂 Auditivo (ouvir), ✍️ Leitura e escrita (ler/anotar)
# e 🖐️ Prático (fazer). 12 situações do dia a dia da loja; em cada uma a pessoa escolhe UMA das 4 respostas
# (a que mais combina com ela). Cada jeito aparece 3 vezes em cada posição (ninguém escolhe "a de cima" por acaso).
# Cada escolha dá 1 ponto: cada jeito vai de 0 a 12 e o total é sempre 12.
# É PREFERÊNCIA, não capacidade: todo mundo aprende melhor com mais de um jeito (mostrar + explicar + deixar fazer).
# O relatório diz por onde começar a ensinar cada um e como mandar os recados. Questionário NOSSO, para orientar o
# treinamento; não é teste certificado.
# ==============================================================================

# (chave, emoji, nome, curto)
CANAIS = [
    ('visual', '👀', 'Visual', 'vendo: demonstração, foto e vídeo'),
    ('auditivo', '👂', 'Auditivo', 'ouvindo: explicação falada e conversa'),
    ('leitura', '✍️', 'Leitura e escrita', 'lendo e anotando: passo a passo escrito'),
    ('pratico', '🖐️', 'Prático', 'fazendo: mão na massa'),
]
CHAVES = [c[0] for c in CANAIS]
EMOJI = {c[0]: c[1] for c in CANAIS}
NOMES = {c[0]: c[2] for c in CANAIS}
CURTO = {c[0]: c[3] for c in CANAIS}

# Cada situação: o enunciado e uma resposta de cada jeito (visual, auditivo, leitura, prático)
SITUACOES = [
    ("Para aprender uma receita nova de sobremesa, eu prefiro…",
     ["Ver alguém fazendo ou ver um vídeo", "Que alguém me explique, passo a passo",
      "Ler a receita escrita, com as quantidades", "Fazer junto, com a mão na massa"]),
    ("Quando chega um produto novo na loja, eu aprendo melhor…",
     ["Olhando a foto e a embalagem", "Ouvindo alguém contar como é",
      "Lendo a descrição e a etiqueta", "Provando e pegando na mão"]),
    ("Para chegar num lugar que eu não conheço, eu…",
     ["Olho o mapa", "Peço para alguém me explicar o caminho",
      "Anoto as ruas e as referências", "Vou uma vez e depois já sei"]),
    ("Quando explico algo para um colega, eu costumo…",
     ["Mostrar ou desenhar", "Falar e explicar com calma",
      "Escrever ou mandar por mensagem", "Fazer junto com ele"]),
    ("Num treinamento, o que mais me ajuda é…",
     ["Fotos, vídeos e coisas para ver", "A conversa e poder perguntar",
      "Um resumo escrito para ler depois", "Praticar na hora"]),
    ("Para usar uma máquina nova (caixa, máquina de açaí…), eu…",
     ["Vejo alguém usando primeiro", "Peço para me explicarem",
      "Leio as instruções", "Vou testando até aprender"]),
    ("Para decorar os preços e os sabores, eu…",
     ["Olho a tabela várias vezes", "Repito em voz alta",
      "Escrevo numa folha", "Aprendo atendendo, no dia a dia"]),
    ("No celular, para aprender algo novo eu prefiro…",
     ["Um vídeo", "Um áudio", "Um texto para ler", "Ir mexendo até descobrir"]),
    ("Um recado da gestão fica mais claro para mim quando vem…",
     ["Com foto ou imagem", "Por áudio ou falado",
      "Por escrito", "Mostrado na prática, no lugar"]),
    ("O que me ajuda a não esquecer uma tarefa?",
     ["Um cartaz ou checklist colorido no lugar", "Alguém me lembrar falando",
      "Uma lista escrita para eu marcar", "Já ter feito algumas vezes"]),
    ("Quando algo é difícil de entender, eu…",
     ["Imagino ou desenho como funciona", "Converso sobre isso com alguém",
      "Leio de novo com calma", "Faço de novo até sair certo"]),
    ("Numa reunião, eu presto mais atenção quando…",
     ["Tem coisa para ver (quadro, tela, foto)", "As pessoas conversam e explicam",
      "Tem a pauta ou anotações por escrito", "Tem uma atividade prática"]),
]
N_PERGUNTAS = len(SITUACOES)
MAXIMO = N_PERGUNTAS
# A ordem das 4 respostas muda a cada pergunta (rodízio): cada jeito fica 3 vezes em cada posição
ORDENS = [[CHAVES[(k + i) % 4] for k in range(4)] for i in range(N_PERGUNTAS)]

TEXTOS = {
    'visual': {
        'oque': "Aprende melhor vendo: demonstração, foto, vídeo, cor e esquema.",
        'ensinar': ["Mostre fazendo antes de pedir para fazer.",
                    "Mande um vídeo curto ou a foto do jeito certo (ex.: a montagem do açaí).",
                    "Use checklists com fotos e cores no setor."],
        'recados': ["Recado com foto, print ou imagem.", "Cartaz visual no lugar da tarefa."],
        'evite': ["Explicar só falando, sem mostrar", "Texto longo sem nenhuma imagem"],
        'pessoa': "Você aprende melhor vendo: com um exemplo, uma foto ou um vídeo você já pega o jeito.",
        'equipe': "use vídeos curtos, fotos do padrão certo e cartazes visuais nos setores."},
    'auditivo': {
        'oque': "Aprende melhor ouvindo e conversando: explicação falada, áudio e troca de ideias.",
        'ensinar': ["Explique falando, passo a passo, e peça para repetir com as palavras dele(a).",
                    "Mande áudio no WhatsApp em vez de texto longo.",
                    "Deixe espaço para perguntas e conversa."],
        'recados': ["Áudio curto ou conversa rápida no começo do turno.", "Reunião falada, com tempo para perguntas."],
        'evite': ["Só mandar texto ou manual para ler", "Treinar no barulho, sem conversar"],
        'pessoa': "Você aprende melhor ouvindo: uma boa explicação e uma conversa deixam tudo claro.",
        'equipe': "explique falando no começo do turno, use áudios e deixe tempo para perguntas."},
    'leitura': {
        'oque': "Aprende melhor lendo e escrevendo: receita escrita, lista, procedimento e anotação.",
        'ensinar': ["Entregue o passo a passo escrito (receita, checklist, procedimento).",
                    "Deixe anotar durante o treinamento.",
                    "Mande depois um resumo por escrito no WhatsApp."],
        'recados': ["Recado por escrito, em tópicos.", "Lista ou checklist para marcar."],
        'evite': ["Explicar uma vez só, de boca, sem nada escrito", "Mudar o procedimento sem atualizar o papel"],
        'pessoa': "Você aprende melhor lendo e anotando: com o passo a passo escrito, você não esquece.",
        'equipe': "deixe receitas, checklists e procedimentos escritos e mande os recados também por escrito."},
    'pratico': {
        'oque': "Aprende melhor fazendo: mão na massa, testar e repetir.",
        'ensinar': ["Treine na prática, no próprio setor, com alguém do lado no começo.",
                    "Explique pouco e deixe fazer logo; corrija na hora, com calma.",
                    "Repita a tarefa algumas vezes até ficar automático."],
        'recados': ["Mostre no lugar, na prática.", "Explicação curta e direto para a ação."],
        'evite': ["Treinamento longo só de teoria", "Ficar muito tempo só olhando, sem fazer"],
        'pessoa': "Você aprende melhor fazendo: colocando a mão na massa, você aprende rápido.",
        'equipe': "treine no turno, mão na massa, com alguém experiente do lado nos primeiros dias."},
}
DICA_GERAL = ("Para todo mundo: mostre, explique e deixe fazer. Usar mais de um jeito ajuda qualquer pessoa a "
              "aprender; comece pelo jeito preferido dela.")
VARIOS = ('varios', '🔄', 'Vários jeitos')


class ErroAprendizado(ValueError):
    pass


def perguntas():
    """O que a página mostra: a situação e as 4 respostas (sem dizer qual é de qual jeito)."""
    return [{'pergunta': enunciado, 'opcoes': [respostas[CHAVES.index(k)] for k in ORDENS[i]]}
            for i, (enunciado, respostas) in enumerate(SITUACOES)]


def calcular(escolhas):
    """escolhas: a resposta escolhida em cada pergunta (0 a 3, na ordem da tela).
    Devolve ({jeito: pontos de 0 a 12}, [jeito escolhido em cada pergunta])."""
    if not isinstance(escolhas, list) or len(escolhas) != N_PERGUNTAS:
        raise ErroAprendizado(f"Responda as {N_PERGUNTAS} perguntas de como você aprende antes de enviar.")
    pontos, escolhidos = {k: 0 for k in CHAVES}, []
    for i, e in enumerate(escolhas):
        if isinstance(e, bool) or e not in (0, 1, 2, 3):
            raise ErroAprendizado(f"Como você aprende, pergunta {i + 1}: escolha uma das respostas.")
        k = ORDENS[i][e]
        pontos[k] += 1
        escolhidos.append(k)
    return pontos, escolhidos


def _ordem(pontos):
    return sorted(CHAVES, key=lambda k: (-int(pontos.get(k) or 0), CHAVES.index(k)))


def varios(pontos):
    """Os 4 jeitos quase iguais (diferença de até 2 pontos): aprende bem de vários jeitos."""
    v = [int(pontos.get(k) or 0) for k in CHAVES]
    return max(v) - min(v) <= 2


def principais(pontos):
    """O jeito preferido e o 2º, se estiver colado (até 1 ponto de diferença)."""
    o = _ordem(pontos)
    p1 = int(pontos.get(o[0]) or 0)
    return [o[0]] + [k for k in o[1:2] if int(pontos.get(k) or 0) >= max(1, p1 - 1)]


def nome(pontos):
    """'👀 Visual' · '👀 Visual + 🖐️ Prático' · '🔄 Vários jeitos'"""
    if not pontos:
        return ''
    if varios(pontos):
        return f"{VARIOS[1]} {VARIOS[2]}"
    return ' + '.join(f"{EMOJI[k]} {NOMES[k]}" for k in principais(pontos))


def canais(pontos):
    return [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k], 'curto': CURTO[k], 'pontos': int(pontos.get(k) or 0),
             'pct': round(100 * int(pontos.get(k) or 0) / MAXIMO)} for k in _ordem(pontos)]


def relatorio(pontos):
    """O relatório da gestão: por onde começar a ensinar, como mandar recados e o que evitar."""
    top = principais(pontos) if not varios(pontos) else _ordem(pontos)[:2]
    junta = lambda campo, n1, n2: TEXTOS[top[0]][campo][:n1] + [x for k in top[1:2] for x in TEXTOS[k][campo][:n2]]
    return {'nome': nome(pontos), 'varios': varios(pontos),
            'principais': [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k]} for k in top],
            'canais': canais(pontos),
            'oque': ([f"Aprende bem de vários jeitos; um pouco mais {CURTO[top[0]].split(':')[0]}."] if varios(pontos)
                     else [TEXTOS[k]['oque'] for k in top]),
            'ensinar': junta('ensinar', 3, 2), 'recados': junta('recados', 2, 1), 'evite': junta('evite', 2, 1),
            'dica': DICA_GERAL}


def resumo_pessoa(pontos):
    """O que a própria pessoa vê (só o lado positivo)."""
    if varios(pontos):
        return {'nome': nome(pontos), 'principais': [],
                'textos': ["Você aprende bem de vários jeitos: vendo, ouvindo, lendo e fazendo. Isso ajuda muito!"]}
    top = principais(pontos)
    return {'nome': nome(pontos), 'textos': [TEXTOS[k]['pessoa'] for k in top],
            'principais': [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k], 'curto': CURTO[k]} for k in top]}


def resumo_equipe(lista):
    """lista: os pontos de cada pessoa que respondeu. Quantos aprendem melhor de cada jeito e as dicas de treinamento."""
    lista = [p for p in lista if p]
    if not lista:
        return {'contagem': [], 'dicas': [], 'dica': DICA_GERAL}
    conta = {k: 0 for k in CHAVES}
    n_varios = 0
    for p in lista:
        if varios(p):
            n_varios += 1
            continue
        for k in principais(p):
            conta[k] += 1
    ordem = sorted(CHAVES, key=lambda k: (-conta[k], CHAVES.index(k)))
    dicas = []
    for k in ordem[:2]:
        if conta[k] and (len(lista) < 3 or conta[k] / len(lista) >= .4):
            verbo = "aprende" if conta[k] == 1 else "aprendem"
            dicas.append(f"{conta[k]} de {len(lista)} {verbo} melhor {CURTO[k].split(':')[0]} ({EMOJI[k]} {NOMES[k]}): "
                         f"{TEXTOS[k]['equipe']}")
    contagem = [{'chave': k, 'emoji': EMOJI[k], 'nome': NOMES[k], 'pessoas': conta[k]} for k in ordem if conta[k]]
    if n_varios:
        contagem.append({'chave': VARIOS[0], 'emoji': VARIOS[1], 'nome': VARIOS[2], 'pessoas': n_varios})
    return {'contagem': contagem, 'dicas': dicas, 'dica': DICA_GERAL}

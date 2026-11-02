# ==============================================================================
# == perfil_relatorios.py - 📘 Os dois relatórios da avaliação de perfil ===========
# ==============================================================================
# Junta as 3 partes (🧭 perfil DISC, 🔋 o que motiva, 🧠 como aprende) em:
#   • o relatório da PESSOA (autoconhecimento): pontos fortes, pontos para desenvolver e como desenvolver, onde rende
#     mais, quando aperta, conflitos, como trabalhar com colegas de outros jeitos, o que motiva, como aprende e um
#     desafio do mês. Só aparece no link dela quando a gestão manda (📤 Enviar relatório para a pessoa);
#   • os blocos que faltavam no relatório da GESTÃO: como cuidar (e os sinais de que não está bem), conflitos (como
#     reage e como lidar) e como ensinar pelo perfil.
# Textos NOSSOS, em linguagem simples: orientam a conversa, não são rótulo nem servem sozinhos para contratar ou demitir.
# ==============================================================================

EXTRA = {
    'D': {
        # para a pessoa
        'desenvolver': ["Na pressa, você pode atropelar os colegas sem perceber",
                        "Às vezes pula etapas (checklist, higiene, conferência) para ganhar tempo",
                        "Esperar o ritmo dos outros pode ser difícil para você"],
        'dicas': ["Antes de decidir, pergunte a opinião de um colega",
                  "Use o checklist mesmo correndo: ele te protege de erro",
                  "Troque a ordem por um pedido: \"pode me ajudar com…?\""],
        'ambiente': "Você rende mais com metas claras, autonomia e movimento; dias parados te desanimam.",
        'pressao': "Quando aperta, você tende a ficar impaciente e mandar. Respire, fale mais devagar e lembre que a "
                   "equipe está no mesmo barco.",
        'conflito': "Num conflito, você tende a ir para o confronto e querer resolver na hora. Ouça o outro lado até o "
                    "fim antes de responder.",
        'desafio': "Este mês: antes de corrigir um colega, faça uma pergunta primeiro.",
        # para a gestão
        'conflito_reage': "Vai para o confronto direto e quer resolver na hora; pode subir o tom.",
        'conflito_lidar': ["Converse em particular, com fatos e sem plateia",
                           "Deixe ele(a) falar primeiro e depois mostre o impacto na equipe",
                           "Feche com uma regra clara e cobre o combinado"],
        'cuidar': ["Dê desafios novos para não cair no tédio", "Reconheça o resultado que ele(a) trouxe",
                   "Dê espaço para decidir, sem controlar cada detalhe"],
        'sinais': ["Fica impaciente e grosso(a) com os colegas", "Começa a fazer tudo sozinho(a) e reclamar dos outros",
                   "Perde o interesse quando a rotina fica parada"],
        'ensinar': ["Explique o porquê e o resultado esperado: ele(a) quer ir direto",
                    "Ensine rápido e deixe fazer; corrija o essencial",
                    "Deixe claro o que NÃO pode ser pulado (higiene, conferência)"],
        # como lidar com quem é assim (a pessoa lê sobre os colegas)
        'com_quem': "seja direto(a) e objetivo(a), fale do resultado e não leve a pressa dele(a) para o lado pessoal.",
    },
    'I': {
        'desenvolver': ["Você pode se distrair conversando e perder o foco na tarefa",
                        "Às vezes promete mais do que dá conta",
                        "Detalhes e rotina repetitiva podem ficar para trás"],
        'dicas': ["Use uma lista curta das tarefas do turno e marque o que terminou",
                  "Antes de dizer \"sim\", veja se dá tempo",
                  "Termine uma tarefa antes de começar outra"],
        'ambiente': "Você rende mais com gente por perto, clima leve e contato com o cliente; ficar isolado(a) te apaga.",
        'pressao': "Quando aperta, você tende a se desorganizar ou falar demais. Pare um minuto, veja o que é mais "
                   "urgente e vá por partes.",
        'conflito': "Num conflito, você tende a evitar o assunto ou levar para o lado emocional. Fale do fato, com calma, "
                    "e ouça sem levar para o pessoal.",
        'desafio': "Este mês: termine cada tarefa antes de começar a próxima e marque no checklist.",
        'conflito_reage': "Fica chateado(a), pode levar para o lado pessoal ou comentar com os colegas.",
        'conflito_lidar': ["Comece pelo que ele(a) faz bem e pelo clima da equipe",
                           "Converse em tom amigável, olhando nos olhos, sem frieza",
                           "Feche com um combinado simples e mostre que a relação continua boa"],
        'cuidar': ["Elogie em público e dê espaço para falar", "Coloque perto do cliente e da equipe, não sozinho(a)",
                   "Conte as novidades da loja e peça ideias"],
        'sinais': ["Fica calado(a), sem o brilho de sempre", "Reclama do clima ou dos colegas",
                   "Atrasos e distração aumentam"],
        'ensinar': ["Ensine conversando, com exemplos reais de clientes", "Deixe perguntar e repetir em voz alta",
                    "Dê o checklist por escrito para os detalhes não escaparem"],
        'com_quem': "puxe conversa, seja simpático(a) e elogie: eles(as) rendem mais num clima leve.",
    },
    'S': {
        'desenvolver': ["Você pode ter dificuldade de dizer \"não\" e acabar sobrecarregado(a)",
                        "Mudanças de última hora te deixam inseguro(a)",
                        "Às vezes guarda o incômodo em vez de falar"],
        'dicas': ["Quando algo te incomodar, fale cedo e com calma",
                  "Peça para entender o porquê de uma mudança: fica mais fácil se adaptar",
                  "Tudo bem pedir ajuda quando estiver com muita coisa"],
        'ambiente': "Você rende mais com rotina organizada, equipe unida e tempo para fazer bem feito; correria e "
                    "mudança toda hora te cansam.",
        'pressao': "Quando aperta, você tende a se calar e aguentar sozinho(a). Avise o líder cedo quando estiver "
                   "sobrecarregado(a).",
        'conflito': "Num conflito, você tende a evitar e ceder para manter a paz. Sua opinião também importa: fale, com calma.",
        'desafio': "Este mês: dê uma ideia ou opinião numa conversa da equipe.",
        'conflito_reage': "Evita o conflito e cede, mas pode guardar mágoa em silêncio.",
        'conflito_lidar': ["Pergunte com calma, em particular, como ele(a) está",
                           "Dê tempo para pensar antes de pedir uma resposta",
                           "Garanta que ele(a) se sinta seguro(a) para discordar"],
        'cuidar': ["Avise as mudanças com antecedência e explique o porquê", "Mantenha escala e função estáveis quando der",
                   "Agradeça a constância: ele(a) segura a loja no dia a dia"],
        'sinais': ["Fica mais quieto(a) que o normal", "Aceita tudo sem reclamar (e se sobrecarrega)",
                   "Fica inseguro(a) e erra mais quando a rotina muda"],
        'ensinar': ["Ensine passo a passo, com calma e sem pressa", "Mostre e acompanhe as primeiras vezes",
                    "Avise antes de mudar o jeito de fazer"],
        'com_quem': "tenha paciência, avise as mudanças com antecedência e ofereça ajuda.",
    },
    'C': {
        'desenvolver': ["Você pode demorar por querer fazer tudo perfeito",
                        "Às vezes fica preso(a) nos detalhes no horário de pico",
                        "Pode parecer crítico(a) ou distante para os colegas"],
        'dicas': ["No pico, pergunte-se: \"o que é essencial agora?\"",
                  "Combine com o líder o que pode ser \"bom o bastante\"",
                  "Quando apontar um erro, comece pelo que está certo"],
        'ambiente': "Você rende mais com regras claras, organização e tempo para fazer certo; bagunça e improviso te incomodam.",
        'pressao': "Quando aperta, você tende a ficar tenso(a) e crítico(a). Foque no essencial e deixe o detalhe para "
                   "depois do pico.",
        'conflito': "Num conflito, você tende a se fechar e se apoiar nas regras. Explique seu ponto com calma e escute o "
                    "lado do outro.",
        'desafio': "Este mês: elogie um colega antes de apontar uma melhoria.",
        'conflito_reage': "Se fecha, fica na defensiva e se apoia nas regras e nos fatos.",
        'conflito_lidar': ["Traga fatos e exemplos concretos, não opiniões", "Dê tempo para ele(a) analisar e responder",
                           "Combine por escrito o que ficou decidido"],
        'cuidar': ["Dê regras claras e o padrão certo por escrito", "Reconheça a qualidade e o capricho",
                   "Evite mudança sem explicação e cobrança na frente dos outros"],
        'sinais': ["Fica mais crítico(a) e irritado(a) com o erro dos outros", "Se isola e fala menos",
                   "O perfeccionismo trava e atrasa o trabalho"],
        'ensinar': ["Explique o padrão e o porquê de cada etapa", "Entregue o procedimento por escrito (receita, checklist)",
                    "Dê tempo para praticar até fazer certo"],
        'com_quem': "seja claro(a) e organizado(a), siga o padrão e explique o porquê das coisas.",
    },
}
LEMBRETE_PESSOA = ("Este relatório é para você se conhecer melhor. Todo mundo tem um pouco de cada jeito, e todo jeito "
                   "tem pontos fortes e pontos para crescer. Não é nota nem rótulo: é um começo de conversa.")


def _junta(perfil, chave, n1=3, n2=1):
    """O texto do fator principal e, se o perfil for combinado, um pouco do segundo (sem repetir)."""
    p, seg = perfil[0], (perfil[1] if len(perfil) > 1 else None)
    base = EXTRA[p][chave][:n1]
    return base + ([x for x in EXTRA[seg][chave][:n2] if x not in base] if seg else [])


def para_gestao(perfil):
    """Os blocos novos do relatório da gestão (o resto já vem do perfil_disc.relatorio)."""
    if not perfil:
        return None
    p = perfil[0]
    return {'cuidar': _junta(perfil, 'cuidar'), 'sinais': _junta(perfil, 'sinais'),
            'conflito_reage': EXTRA[p]['conflito_reage'], 'conflito_lidar': _junta(perfil, 'conflito_lidar'),
            'ensinar': _junta(perfil, 'ensinar')}


def para_pessoa(nome, pct, perfil, motivos=None, aprende=None):
    """O relatório de autoconhecimento da pessoa (só as partes que ela respondeu)."""
    import perfil_disc as P
    import perfil_motivacao as PM
    import perfil_aprendizado as PA
    r = {'nome': nome or '', 'lembrete': LEMBRETE_PESSOA}
    if perfil and pct:
        p = perfil[0]
        rel = P.relatorio(pct, perfil)
        r['perfil'] = {
            'nome': P.nome_perfil(perfil), 'texto': P.TEXTOS[p]['pessoa'],
            'fatores': [{'d': d, 'nome': P.NOMES[d], 'emoji': P.EMOJI[d], 'pct': pct[d]} for d in P.DIMS],
            'fortes': rel['fortes'], 'desenvolver': _junta(perfil, 'desenvolver'), 'dicas': _junta(perfil, 'dicas'),
            'ambiente': EXTRA[p]['ambiente'], 'pressao': EXTRA[p]['pressao'], 'conflito': EXTRA[p]['conflito'],
            'desafio': EXTRA[p]['desafio'],
            # onde rende mais: só o que combina (ou, se nada combinar muito, o que pode funcionar) — nunca o "menos indicado"
            'funcoes': [{'setor': f['setor'], 'porque': f['porque'], 'ajuda': f['ajuda']} for f in
                        ([f for f in rel['funcoes_loja'] if f['nivel'] == 'combina'][:4]
                         or [f for f in rel['funcoes_loja'] if f['nivel'] == 'pode'][:2])],
            'colegas': [{'d': d, 'emoji': P.EMOJI[d], 'nome': P.NOMES[d], 'texto': EXTRA[d]['com_quem']} for d in P.DIMS],
        }
    if motivos:
        m = PM.resumo_pessoa(motivos)
        r['motivacao'] = {'nome': m['nome'], 'textos': m['textos'],
                          'fatores': PM.fatores(motivos)}
    if aprende:
        a = PA.resumo_pessoa(aprende)
        chaves = PA.principais(aprende) if not PA.varios(aprende) else PA.CHAVES
        r['aprendizado'] = {'nome': a['nome'], 'textos': a['textos'],
                            'dicas': [x for k in chaves[:2] for x in PA.TEXTOS[k]['aprender'][:2]],
                            'canais': PA.canais(aprende)}
    return r

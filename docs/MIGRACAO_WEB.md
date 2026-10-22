# Migração para a Web — inventário e checklist

Objetivo: usar o sistema **só pelo navegador**, sem perder nenhuma função dos programas do PC.
Este arquivo é o checklist: cada linha é uma função do PC e onde ela vai ficar na Web.
Uma tela do PC só é desligada quando **todas** as linhas dela estiverem ✅ e vocês tiverem
usado a versão Web em paralelo por alguns dias.

## Decisões (08/10/2026)

- Quem usa os programas do PC: **Rodrigo e esposa** → 2 contas de gestor, as duas com acesso a tudo.
- O servidor fica **na loja** → a área de Gestão começa abrindo **só na rede da loja** (como o
  painel hoje). Pela internet, só depois da etapa de segurança e se vocês quiserem.
- A área nova se chama **Gestão** (`/gestao`), feita para tela de computador (larga). O app de
  compras (`/compras`, celular) continua como está.
- Os programas do PC continuam funcionando durante toda a migração.

Legenda: ✅ já existe na Web/app (só conferir) · 🧪 pronto na Web, falta vocês usarem e aprovarem · 🟡 existe em parte · ⬜ falta fazer

---

## 1. Gestão de Estoque (`gestao_estoque_main.py` — 7.900 linhas, 94 botões, 23 janelas)

### 1.1 Catálogo Mestre
| Função | Na Web | Status |
|---|---|---|
| Cadastrar / editar / excluir produto (nome, unidade, categoria, mínimo, custo manual) | Gestão › Catálogo | ⬜ |
| Lista com busca, custo atual, mais barato (12m), situação | Gestão › Catálogo (app tem só a busca) | 🟡 |
| Categorias (⚙️) e % de custo adicional (royalties) | Gestão › Catálogo › Categorias (app só lista) | 🟡 |
| Editar vários produtos de uma vez | Gestão › Catálogo | ⬜ |
| Sugerir nomes limpos | Gestão › Catálogo | ⬜ |
| Juntar produtos duplicados | Gestão › Catálogo | ⬜ |
| Gráfico de preço do produto | Gestão › Catálogo (app tem o histórico) | 🟡 |
| Vínculos do produto | Gestão › Vínculos (filtrado no produto) | ⬜ |

### 1.2 Fornecedores
| Função | Na Web | Status |
|---|---|---|
| Cadastrar / editar / excluir fornecedor | Gestão › Fornecedores (app só lista) | 🟡 |

### 1.3 Notas fiscais (XML) e vínculos
| Função | Na Web | Status |
|---|---|---|
| Notas baixadas da SEFAZ: lista, abrir, "buscar na SEFAZ agora" | App › Receber | ✅ |
| Vincular item / criar produto e vincular | App › Receber | ✅ |
| Lançar no estoque (com a quantidade conferida) | App › Receber | ✅ |
| "Já está no estoque: tirar da lista" | App › Receber (dispensar) | ✅ |
| Importar XML de outra pasta (e-mail, download) | Gestão › Notas › **Enviar arquivo XML** | ⬜ |
| Conferir Qtd/Cx pelo custo anterior ao vincular | Gestão › Notas | 🟡 |
| Aviso de aumento de preço ao salvar | já sai no Telegram / app | ✅ |
| Recalcular custos de notas já salvas (ST/frete) | Gestão › Notas | ⬜ |
| Ajustar notas antigas pelo valor total (sem XML) | Gestão › Notas | ⬜ |
| Vínculos e auditoria de cadastros (filtros de problema, editar produto/Qtd/Cx/EAN/NCM) | Gestão › Vínculos | ⬜ |
| ✏️ Corrigir quantidade / preço das compras (com XML e sugestão) | Gestão › Vínculos | ⬜ |
| Juntar vínculos duplicados | Gestão › Vínculos | ⬜ |
| Histórico e correção de compras do produto / corrigir NF | Gestão › Vínculos / Consultas | ⬜ |

### 1.4 Contagem física e valor do estoque
| Função | Na Web | Status |
|---|---|---|
| Fazer contagem (busca, embalagem, somar locais, rascunho) | App › Início / Estoque | ✅ |
| Painel do balanço e diferenças em R$ | App › Estoque | ✅ |
| Histórico de contagens (ver itens) | Gestão › Contagens | ⬜ |
| Editar contagem (inserir, mudar qtd, remover) | Gestão › Contagens | ⬜ |
| Consolidar contagens | Gestão › Contagens | ⬜ |
| Resolver itens avulsos (produto normal / desmembrar caixa) | Gestão › Contagens | ⬜ |
| Exportar folha de contagem (Excel) | Gestão › Contagens (baixar) | ⬜ |
| 💰 Valor do Estoque: recalcular, fechar/reabrir valor, copiar total, Excel | Gestão › Valor do Estoque | ⬜ |

### 1.5 Sugestão de compra
| Função | Na Web | Status |
|---|---|---|
| Gerar sugestão (pontos A/B, janela de dias), ver o cálculo | Gestão › Sugestão (app usa o automático na lista) | 🟡 |
| Exportar sugestão (Excel) | Gestão › Sugestão (baixar) | ⬜ |
| Pedido por fornecedor + mensagem WhatsApp + Excel | App › Orçar faz o pedido por fornecedor | 🟡 |
| 🍦 Buffet: top sabores e seleção de sabores | Gestão › Sugestão › Buffet | ⬜ |

### 1.6 Solicitações dos líderes
| Função | Na Web | Status |
|---|---|---|
| Ver solicitações, foto, aprovar / recusar | Gestão › Solicitações | ⬜ |

### 1.7 Consultas
| Função | Na Web | Status |
|---|---|---|
| Consulta por produto (compras, exportar) | Gestão › Consultas (app tem histórico de preços) | 🟡 |
| Consulta por nota fiscal (itens + resumo do valor por categoria, com royalties) | Gestão › Consultas | ⬜ |
| Relatórios: gasto por categoria, inflação, mais barato | App › Gestão | ✅ |

### 1.8 Administração
| Função | Na Web | Status |
|---|---|---|
| Excluir notas / excluir contagens | Gestão › Administração (com confirmação dupla) | ⬜ |
| Backup do estoque em Excel | Gestão › Administração (baixar) | ⬜ |
| ☢️ Apagar tudo e recomeçar o estoque | **Decidir**: manter só no servidor (comando), não na Web | ⬜ |

---

## 2. Painel do Gestor — gamificação (`main.py` — 3.800 linhas, 14 abas)

O painel Web de hoje (`/`) **mostra** tarefas, validação, feed, resgates, metas e lucro (tela de TV),
mas não deixa **mexer**. Os funcionários usam o bot do Telegram (continua igual).

| Função | Na Web | Status |
|---|---|---|
| Dashboard (gráfico do ranking) | Gestão › Equipe › Dashboard (painel mostra pódio) | 🟡 |
| Funcionários: cadastrar, editar dados completos, excluir | Gestão › Equipe › Funcionários | ⬜ |
| Histórico e pendências de hoje do funcionário | Gestão › Equipe › Funcionários | ⬜ |
| Zerar pontos do mês | Gestão › Equipe › Funcionários | ⬜ |
| 📢 Lançar tarefas no grupo (falta/atestado) | Gestão › Equipe › Funcionários | ⬜ |
| 🔁 Transferir as tarefas fixas (diárias, semanais e mensais) para outro funcionário — ou copiar (os dois ficam); escolhe quais; não duplica o que o outro já tem; quem entrega mantém o histórico (no PC desde 10/2026: Funcionários › Tarefas Ativas ou Ações) | Gestão › Equipe › Funcionários | ⬜ |
| Grupos: criar, editar, excluir, membros | Gestão › Equipe › Grupos | ⬜ |
| Catálogo de tarefas (modelos) | Gestão › Equipe › Tarefas | ⬜ |
| Atribuir tarefas (com recorrência), desatribuir | Gestão › Equipe › Atribuir | ⬜ |
| Validar entregas (foto, aprovar, recusar) | Gestão › Equipe › Validar (painel só mostra) | 🟡 |
| Ranking | Gestão › Equipe › Ranking (painel mostra) | 🟡 |
| Relatórios: pendências, análise de tarefas + justificativas, resgates | Gestão › Equipe › Relatórios | ⬜ |
| Feedbacks (filtros) | Gestão › Equipe › Feedbacks | ⬜ |
| Agenda semanal do funcionário | Gestão › Equipe › Agenda | ⬜ |
| Loja: produtos (criar/editar), aprovar / recusar resgate | Gestão › Equipe › Loja (painel mostra resgates) | 🟡 |
| Metas: meta principal, modelos de metas diárias, apuração diária, lucro mensal | Gestão › Metas (painel mostra) | 🟡 |
| Conquistas: criar / excluir | Gestão › Equipe › Conquistas | ⬜ |
| Consultar NFs (lançadas pela equipe): filtros, foto, recriar botões no Telegram | Gestão › Equipe › NFs | ⬜ |

## 3. Escala da Loja (`escala_loja_main.py` — 3.000 linhas) — **1º módulo a migrar**

Levantamento completo do programa (10/10/2026): 43 funções. O painel da TV mostra só o mapa,
o fluxo e as pausas de **hoje**, sem deixar mexer. Na Web fica em **Gestão › Escala**.

### Entrega 1 — Escala do dia (instalada em 10/2026: Gestão › Escala)
| Função | Status |
|---|---|
| 1. Data: calendário, ◀ ▶, Hoje; dia da semana, "(hoje)" e 🎉 feriado | 🧪 |
| 2. Mapa da loja (imagem) com as posições no mesmo lugar do PC; cores: verde escalado, vermelho vazio, azul fixo sugerido, laranja de folga, amarelo turno sem pessoa | 🧪 |
| 3. Em cada posição: nomes e horários, [curta]/[longa] do freelancer, [FOLGA], (Fixo), setor | 🧪 |
| 4. Resumo do dia: pessoas, posições vazias, custo dos freelancers e quantos já pagos | 🧪 |
| 5. Alertas do dia: 2 lugares ao mesmo tempo, folga/férias/afastamento, sem horário, turno sem pessoa, posição removida, mais de 10h no dia, intervalo errado, mais de 6h sem intervalo | 🧪 |
| 6. Gráfico do fluxo: pessoas por hora (7h–23h) sem quem está no intervalo, filtro por setor, vermelho com menos de 3 | 🧪 |
| 7. Clicar na posição abre o painel com os turnos dela (vários turnos por posição) | 🧪 |
| 8. Escolher funcionário (com [FOLGA] marcado) ou freelancer | 🧪 |
| 9. Entrada, saída (preenchida pela jornada padrão) e intervalo, com máscara HH:MM | 🧪 |
| 10. Freelancer: diária Curta/Longa (sugerida pela duração, dá para trocar) e prévia do valor (✅ já pago) | 🧪 |
| 11. Foco do dia (texto do turno) | 🧪 |
| 12. Salvar / atualizar / limpar / excluir turno; Enter salva | 🧪 |
| 13. Conferências ao salvar: horário válido, entrada ≠ saída, intervalo completo e dentro do turno, mesma pessoa em 2 lugares (bloqueia), funcionário de folga/férias (pergunta), mais de 10h (pergunta), turno de freelancer já pago (avisa) | 🧪 |
| 14. Excluir turno já pago: avisa que o pagamento continua registrado | 🧪 |
| 15. 📋 Copiar escala de ontem / da semana passada (avisa que substitui a do dia) | 🧪 |
| 16. 🪄 Gerar intervalos automáticos (pergunta antes de substituir os feitos à mão, mostra conflitos) | 🧪 |
| 17. ⏱️ Gerenciar intervalos: lista do dia por setor e horário, verde/vermelho, Enter salva e passa para o próximo | 🧪 |
| 18. 📢 Enviar a escala no grupo do Telegram (com confirmação) | 🧪 |
| 19. 📱 Confirmar escala no WhatsApp: mensagem a cada pessoa (data com o dia da semana, posição, horário, intervalo) + diretriz do setor; antes de enviar pergunta **para quem**: 👥 todos, 👔 só os fixos (funcionários) ou 🧑‍🍳 só os freelancers (com quantos e quem em cada opção; igual no PC); resumo enviados/falhas | 🧪 |
| 20. Mensagens rápidas de status | 🧪 |
| 21. ☕ Intervalos no WhatsApp (só na Web): cada escalado recebe só o horário do intervalo dele + um aviso de que não seguir o horário prejudica a operação (aviso editável, com prévia); todos / só fixos / só freelancers; avisa quem fica de fora (sem intervalo ou sem telefone). Também na janela ⏱️ Gerenciar intervalos | 🧪 |
| 22. 🖨️ Imprimir escala (só na Web; substitui o Word do mural): folha A4 com a escala do dia por setor (entrada, saída, intervalo), a ordem dos intervalos e o aviso; escolhe o que sai no papel (lembra a escolha); imprime ou salva em PDF. **Cabe em 1 folha A4:** a letra se ajusta sozinha (14pt com pouca gente, até 7,5pt com dia cheio — 32 pessoas cabem), a escala é uma tabela só com o setor numa linha, e a ordem dos intervalos vai em 2 colunas com o nome curto (sem repetir); a janela avisa antes se cabe | 🧪 |

**Depuração da Entrega 1 (10/2026) — 17 correções:** turno que passa da meia-noite agora é conferido
contra os outros da mesma posição; turnos em posição removida do mapa aparecem (lista "Removidas do
mapa") e podem ser excluídos; banco fora do ar avisa em vez de mostrar o dia vazio; o fixo já escalado
em outra posição não aparece mais como "disponível" (também no PC); "830" digitado vira 08:30; trocar
de dia rápido não mostra mais a escala do dia errado; falha ao carregar limpa a tela e trava os botões;
clique duplo no Copiar não duplica; WhatsApp não manda "None às None" e o acompanhamento tenta de novo
quando a rede cai; trocar freelancer por funcionário apaga a diária curta/longa; a página se atualiza
ao voltar para a aba.

**Depuração 3 (19/10/2026) — Escala, freelancers, pagamentos, folha, avisos, clientes, comunicados, perfil e
liderança.** Robô passou nas 120 rotas da Gestão e das páginas públicas com dados certos, vazios e errados.
- Trocar o **freelancer** de um turno (Web, PC e escala fixa): o que já foi PAGO fica registrado para quem recebeu
  (💰 Pagamentos: "turno excluído") e quem entrou fica A PAGAR; a correção pendente (horário real, ajuste) do
  anterior não passa para o novo; ao pagar, o pagamento fica com o freelancer que está no turno (o recibo vai
  para o WhatsApp certo). A pergunta "Turno já pago" da Web diz quem fica a pagar.
- 🧭 Perfil e 👔 Liderança: fator "forte" = 30% ou mais **ou** parte do perfil do cartão (o "+ 🔵 Conforme" entra
  com 27%): a dica "Ninguém com C forte" não aparece mais com alguém 🟢 Estável + 🔵 Conforme na equipe; o
  "Traz para a equipe" do candidato segue a mesma regra. Vincular com cadastro inválido responde em vez de erro 500.
- 👔 Liderança: envio de WhatsApp interrompido no meio mostra o motivo (antes "WhatsApp falhou: ?").
- Folha: lançar o faturamento atualiza na hora a dica de dias parecidos da Escala (antes até 10 minutos depois).

**Depuração do mapa (13/10/2026) — posições encavaladas / fora da planta.** As posições eram guardadas em
proporção da *área do mapa da janela do programa do PC*, mas a planta tem tamanho fixo (1180 × 600). Abrir
o programa maximizado regravava esse tamanho e todas as bolinhas saíam do lugar (na Web e no PC). Correção:
- **📐 Arrumar mapa** (Web, só gestor): barras de largura/altura levam todas as bolinhas de volta de uma
  vez; depois dá para arrastar uma a uma (mouse ou dedo) e 💾 Salvar. Ao salvar, as posições passam a ser
  proporção da **planta** e o mapa fica **fixo** (`ConfiguracoesEscala.MapaFixo = 1`).
- Mapa fixo: o PC desenha e cria posições em proporção da planta e não regrava mais o tamanho da janela; a
  Web ignora o tamanho gravado (um PC com o programa antigo não tira mais nada do lugar).
- Avisos 📐 nos alertas do dia: "ainda depende da janela do PC", "fora da planta" e "uma em cima da outra".
- Textos de posições vizinhas não ficam mais um em cima do outro (Web e PC): o texto desce até ficar livre
  (fio tracejado até a bolinha na Web) e o [setor] repetido aparece uma vez só.

### Entrega 2 — Cadastros e configurações
(Os freelancers — itens 25 a 27 — foram junto com a Entrega 3: **Gestão › 👤 Freelancers**.)

| Função | Status |
|---|---|
| 21. 🔧 Modo "configurar mapa": clicar num lugar vazio cria posição (nome + setor) | ⬜ |
| 22. Clicar numa posição: mudar nome e setor | ⬜ |
| 23. Remover posição do mapa (as escalas antigas continuam guardadas) | ⬜ |
| 24. Etiqueta do setor em cada posição ([Sem Setor] no modo configurar) | ⬜ |
| 25. 👤 Freelancers: lista com telefone e "a pagar até hoje" | 🧪 |
| 26. Freelancer: novo, editar, excluir (avisa se ainda falta pagar) | 🧪 |
| 27. Freelancer: botão Pagamentos (abre tudo o que está pendente dele) | 🧪 |
| 28. 📝 Diretrizes por setor (texto do WhatsApp, *negrito*) | ⬜ |
| 29. ⚙️ Automação: máx. horas sem pausa, duração do intervalo, jornada padrão | ⬜ |
| 30. Horários de pico por dia da semana | ⬜ |

### Entrega 3 — Pagamentos de freelancers (instalada em 10/2026: Gestão › 💰 Pagamentos)
No celular cada turno vira um cartão; toque marca, ✏️ corrige. Recibo: copia **e** abre a conversa do
WhatsApp com o texto pronto. Excel: baixa o .xlsx (feito pelo próprio servidor, sem precisar de programa extra).
As contas, os textos da lista, do recibo e do Excel são os MESMOS do PC (escala_regras.py).
**Recibo automático (10/2026):** ao ✅ Marcar como PAGO (opção "📱 Mandar o recibo no WhatsApp de cada freelancer",
lembrada no aparelho), cada freelancer recebe pelo número da loja o recibo SÓ dos turnos pagos agora, com o cabeçalho
"💰 Pagamento feito: R$ … · data · forma" (um de cada vez, a cada 2,5 s). A lista mostra em cada turno pago 📱 recibo
enviado / ⚠️ não foi (motivo) / 📵 sem WhatsApp; na janela 📋 Recibo, **📱 Mandar agora** reenvia. Se o WhatsApp
falhar, o pagamento continua salvo. Tabela `RecibosFreelancer`. Com turnos de **vários freelancers** marcados (ou a
lista toda), o 📋 Recibo abre "📱 Recibos de N freelancers": um recibo para cada um (ver o texto, quem já recebeu vem
desmarcado, quem não tem WhatsApp não dá para marcar) e **📱 Mandar para N**.

| Função | Status |
|---|---|
| 31. Filtros: período + atalhos (esta semana, semana passada, este mês, tudo até hoje), freelancer, pendentes/pagos/todos | 🧪 |
| 32. Linha com os valores atuais (diárias, hora extra, blocos) | 🧪 |
| 33. Tabela dos turnos: data (🎉), freelancer, posição, escala, real, horas, diária, extras, ajuste, total, situação (cores) | 🧪 |
| 34. Resumo por freelancer (turnos, pendente, pago); clicar filtra | 🧪 |
| 35. Totais: a pagar, pago, selecionados | 🧪 |
| 36. Selecionar vários turnos | 🧪 |
| 37. ✏️ Corrigir horário real, ajuste (+/-), observação e diária, com prévia do cálculo | 🧪 |
| 38. ✅ Marcar como pago: data e forma (Pix, Dinheiro, Transferência, Outro; lembra a última); bloqueia turno sem horário | 🧪 |
| 39. ↩️ Desfazer pagamento | 🧪 |
| 40. 📋 Recibo do freelancer para o WhatsApp (na Web: copiar **e** abrir a conversa) | 🧪 |
| 41. 📊 Exportar Excel (baixar) | 🧪 |
| 42. ⚙️ Valores: diárias longa/curta (tempo e valor seg-sáb / dom-feriado), hora extra, bloco, limite da curta, exemplos | 🧪 |
| 43. 📅 Feriados: lista por ano, adicionar, nacionais do ano, remover | 🧪 |
| 44. Recibo com a conta separada para quem teve ajuste **positivo** (PC e Web): "📅 dia · das X às Y / • Diária: R$ / • Hora extra: + R$ / • 🎁 Presente: + R$ (motivo) / Total pago". O valor combinado na 🙋 Vaga aparece como "💬 Valor combinado" (e o que for dado a mais na hora de pagar, como presente). Sem ajuste ou com desconto: a linha de sempre | 🧪 |

**Como fica por dentro:** as regras da escala (conflitos, folga, jornada, intervalo, valor do
freelancer, recibo) passam para um arquivo só, usado **pelo PC e pela Web** — as duas versões
conferem igual. Na Web, as conferências são refeitas no servidor com os dados do banco na hora
de salvar (se o PC e a Web mexerem no mesmo dia, a última gravação confere de novo).

### Novo (só na Web) — 📊 Folha × Faturamento × Clima (10/2026: Gestão › 📊 Folha)
Meta: folha (fixos + freelancers) em até **18% do faturamento** (a meta muda na tela). Para cada dia:
- **Faturamento** = o lançado na Gamificação (Metas → Lançar Apuração Diária). Só há uma meta por vez;
  se o mesmo dia aparecer em duas, vale o maior (não soma duas vezes).
- **Fixos** = folha do mês (salários + encargos + benefícios), informada em ⚙️ Folha fixa e meta e
  dividida pelos dias do mês (custa igual com o funcionário de folga ou a loja fechada). Mês sem valor
  usa o mês informado mais perto (marcado com *).
- **Freelancers** = o valor de cada turno, o mesmo da tela de Pagamentos.
- **Pessoas e horas** = a escala do dia (sem o intervalo).
- **Clima** = máxima, mínima e chuva de Rondonópolis - MT (`clima.py`, Open-Meteo: gratuito, sem cadastro).
  O robô busca de 3 em 3 horas a previsão e os últimos 14 dias, e completa o histórico de todos os dias
  que têm faturamento (o cruzamento já começa com o passado). Outra cidade: `CLIMA_CIDADE`,
  `CLIMA_LATITUDE`, `CLIMA_LONGITUDE` no config.py.

Na tela: mês até o último dia lançado (fixo de todos os dias até ali + freelancers ÷ faturamento, com
aviso dos dias sem faturamento lançado), último dia lançado, **próximos dias** (previsão + média dos
"dias parecidos": mesmo tipo de dia e máxima até 1,5° de diferença), dia a dia do mês e **calor × vendas**
(faturamento, freelancers, pessoas e folha por faixa de temperatura; dias de chuva × sem chuva; filtro
semana × sáb/dom/feriado). Também aparece:
- na **Escala** (linha do clima do dia + "em dias parecidos: ~R$ X, N freelancers");
- no **app** (Gestão › Resumo: card com o último dia lançado e a previsão de hoje);
- no **Telegram**: quando o faturamento do dia é lançado, o robô manda o resumo (dias lançados
  atrasados vão juntos; o de hoje só depois das 21h; no fim, a previsão do próximo dia).

**Melhorias (10/2026):**
- **Chuva por horário**: guarda também a chuva da tarde/noite (12h–22h) e as horas de chuva; só ela conta como
  "dia de chuva" (chuva de madrugada quase não muda a venda). Dias antigos sem o horário usam 5 mm no dia.
- **📌 Dia atípico** (feriado prolongado, evento, loja fechada, sistema parado…): botão na tabela do dia a dia;
  o dia sai das médias de calor × vendas, dos "dias parecidos" e do "falta lançar" (os números continuam na folha).
- **"Dias parecidos"** = mesmo tipo de dia + máxima até 1,5° + o mesmo tempo (chuva à tarde × seco).
- **Comparar** com o mesmo dia da semana passada (7 dias antes) e do ano passado (364 dias: mesmo dia da semana):
  coluna na tabela, cartão do último dia e resumo do Telegram; cartão do mês compara com o mês anterior no mesmo período.
- **📈 Gráfico do mês**: três painéis no mesmo eixo de dias (faturamento; máxima com os dias de chuva à tarde;
  folha do dia × meta), com dica ao passar o dedo/mouse.
- **💰 Lançar faturamento** pela Gestão (e pelo app, que abre a mesma janela): MESMA regra da Gamificação e do
  `/lancar` do Telegram — `database.lancar_apuracao_diaria` + `verificar_e_premiar_meta_diaria` (pontos da meta,
  com estorno se corrigir para menos). Meta: a do lançamento que já existe no dia; senão a meta cujo período tem o
  dia; senão a ativa hoje. Lançar de novo o mesmo dia substitui o valor.
- **Telegram** (agendador): 09:15 lembrete de faturamento não lançado (últimos 7 dias, sem os atípicos); 09:20 do
  dia 1 ao 5 o fechamento do mês anterior (espera os atrasados até o dia 5); 10:00 **boletim de previsão e escala**
  (todo dia): hoje e os próximos 3 dias com clima, faturamento e freelancers de dias parecidos × escalados; alertas de
  escala com menos freelancers do que costuma (dia seco) e de chuva à tarde quando nesses dias a venda cai 15% ou mais.

Arquivos: `folha_faturamento.py`, `clima.py`, `templates/gestao_folha.html`; tabelas `ClimaDiario`,
`FolhaFixaMensal`, `ParametrosFolha`, `DiasAtipicos` (criadas sozinhas).

### Novo (só na Web) — 📣 Avisos da gestão: Telegram ou grupo do WhatsApp (10/2026: Gestão › 📣 Avisos)
Todos os avisos da gestão que o robô manda (estoque, preços, notas da SEFAZ/XML, produtos novos para a franquia,
orçamentos, boletim de previsão e escala, resumo do faturamento e folha, lembrete e fechamento do mês) saem por
`alertas_estoque.enviar()`. Na tela se escolhe o canal: **Telegram**, **WhatsApp (grupo)** ou **os dois**, e o grupo
(lista dos grupos em que o número da Z-API participa; ou o ID à mão). Fica no banco (`ConfigAvisos`), então o robô e o
servidor usam a mesma escolha sem reiniciar. No WhatsApp a formatação do Telegram (`<b>`, `<i>`) vira `*` e `_`.
Se o WhatsApp falhar, o aviso vai pelo Telegram com um alerta (nada se perde). Os avisos da Gamificação (tarefas,
comunicados, pontos) e os comandos do grupo (`/lancar`…) continuam no Telegram. Arquivos: `notificador_whatsapp.py`
(`enviar_para_grupo`, `listar_grupos`, `html_para_whatsapp`), `alertas_estoque.py`, `templates/gestao_avisos.html`.

### Novo (só na Web) — 📢 Clientes: cadastro e mensagens no WhatsApp (10/2026: Gestão › 📢 Clientes)
Cadastro dos clientes (nome, WhatsApp, aniversário, etiquetas como "VIP", "Delivery", e se **autorizou** receber) e
mensagens como uma lista de transmissão: texto com `{nome}` (vira o primeiro nome), **foto tirada no celular**
(a página diminui para 1280 px antes de subir), para "Todos" ou uma ou mais etiquetas, **agora ou agendada**.
Saem por um **número só dos clientes** (2ª instância da Z-API; ID e token gravados no banco pela aba ⚙️ Ajustes,
nunca no config.py; recusa a instância da loja), para que um bloqueio não pare a escala e os avisos. O robô
(`agendador.py`, de minuto em minuto) manda em fila: 1 mensagem a cada 6–15 s, só das 8h às 21h, no máximo 300 por dia,
pula quem pediu para sair e **pausa sozinho** após 5 falhas seguidas (avisa no grupo; tipo 📢 em 📣 Avisos).
Toda mensagem termina com "responda SAIR": o webhook da Z-API (`/webhook/zapi-clientes/<segredo>`, "Ao receber") tira
a pessoa da lista e confirma; "VOLTAR" coloca de volta. Extras: 🎂 aniversário automático às 10h (texto e foto
configuráveis), **QR do balcão** (página pública `/clientes/cadastro`: o cliente se cadastra e autoriza, ganha a
etiqueta "Balcão" e uma mensagem de boas-vindas; limite por aparelho e por dia), importar planilha (.xlsx/.csv) ou a
agenda do celular (Android/Chrome), teste para o próprio número, histórico de cada envio (quem recebeu, falhou ou
pulou; cancelar, continuar, reenviar para quem falhou). Pela internet só ficam abertos o formulário do QR e o webhook.
Arquivos: `clientes.py`, `templates/gestao_clientes.html`, `templates/clientes_cadastro.html`; tabelas `Clientes`,
`ClienteEtiquetas`, `CampanhasClientes`, `CampanhaEnvios`, `ParametrosClientes`; fotos em `fotos_clientes/`.
O QR precisa de `pip install qrcode` no servidor (sem ele, o resto funciona e a tela avisa).
**Clientes+ (10/2026):** 💬 aba **Respostas** (tudo o que os clientes respondem, ligado à mensagem; quem não está
cadastrado vira cliente com um toque); 🏎️ **reserva por resposta** na mensagem (palavra, ex. QUERO, unidades e o que
é: quem responde entra numa fila, "QUERO 2" pede 2, resposta automática com a posição; quem não cabe fica na espera e
sobe sozinho — avisado — se alguém desistir; a gestão marca 📦 retirou / ❌ cancela / muda as unidades / 🔒 encerra
e pode avisar a espera que esgotou; aviso "Reservas esgotadas" no grupo da gestão); ✔️✔️ **entregue e lida** por
mensagem e por cliente (webhook "Status da mensagem"); 📵 **tem WhatsApp?** (o robô confere antes de mandar e pula
quem não tem, sem contar como falha; botão 🔎 Conferir números; vale 30 dias); 📋 **ficha do cliente** (mensagens,
leitura, respostas, reservas, 💬 Abrir no WhatsApp, ✉️ mensagem só para ele); ☑️ **seleção** (pôr/tirar etiqueta,
excluir, mensagem só para os marcados); ⭐ **filtros prontos** (aniversário no mês, novos, QR, responderam, sem
mensagem há 30 dias, nunca receberam, sem WhatsApp) e 🏷️ renomear/juntar/apagar etiquetas. Os dois webhooks da
instância dos clientes (Ao receber e Status da mensagem) usam o mesmo endereço de ⚙️ Ajustes. Tabelas novas:
`ClienteRespostas`, `CampanhaReservas` (+ colunas em `Clientes`, `CampanhaEnvios` e `CampanhasClientes`).

### Novo (só na Web) — ✅ Confirmar presença e 🙋 Vagas para freelancers (10/2026: Gestão › 🗓️ Escala)
**Confirmar presença:** a mensagem do 📱 Confirmar escala (WhatsApp) termina com um **link** de cada pessoa
(`/confirmar/<código>`): a página tem **✅ Confirmo** e **❌ Não posso** (com motivo opcional). No mapa, na lista e no
painel aparece ✅ / ⏳ / ❌ antes do nome, e o resumo do dia mostra "📲 Presença: ✅ n · ⏳ n · ❌ n". Quem avisa que não
vem gera aviso no grupo da gestão (tipo ✅ Presença e vagas em 📣 Avisos). Se a pessoa ou o horário mudar depois da
mensagem, a resposta antiga deixa de valer (volta a ⏳ quando a confirmação for mandada de novo; o link é o mesmo).
O pagamento continua com o 💰 (antes era ✅ no painel). Link e não botão do WhatsApp: pela Z-API o botão não aparece
em todo celular. O programa do PC também manda o link, mas só se o endereço da internet estiver gravado.
**🙋 Vagas:** a gestão cria a vaga (dia, posição, horário, **valor da diária** — o sistema sugere, dá para mudar —,
quantas pessoas, observação) e manda **no grupo dos freelancers** (um link para todos; a pessoa confirma com o WhatsApp
do cadastro, com limite de tentativas por aparelho) e/ou **no individual** (nome, horário, valor e o link de cada um; a
lista avisa quem já está na escala no dia e quem não tem WhatsApp). Quem quer aparece na janela e gera aviso no grupo
da gestão; **📌 Colocar na escala** escala o freelancer (mesmas conferências da escala; se a posição já tem gente, vai
para outra livre do mesmo setor ou a tela pergunta qual), grava o valor combinado como ajuste nos 💰 Pagamentos, marca
✅ e manda a confirmação. **✔️ Encerrar** avisa quem quis e não foi escolhido ("desta vez não deu"); **🗑️ Cancelar**
avisa que foi cancelada. Os links usam o endereço da internet gravado em 📢 Clientes › ⚙️ Ajustes (sem ele, só abrem
no Wi-Fi da loja e a tela avisa); pela internet só ficam abertos `/confirmar/`, `/vaga/` e `/api/presenca/`.
Arquivos: `confirmacoes.py`, `templates/presenca.html`, `templates/gestao.html`; tabelas `ConfirmacoesEscala`,
`VagasFreelancer`, `VagaRespostas`, `ParametrosVagas`.

### Novo (só na Web) — 📨 Comunicados para a equipe (10/2026: Gestão › 📨 Comunicados)
A gestão escreve o comunicado (título, chamada do WhatsApp, texto, **para quem**: todos, só fixos, só freelancers ou escolhendo um a um;
**vale até** — padrão 7 dias — e ⭐ pontos opcionais na gamificação para os fixos que confirmarem a leitura; a
mensagem do WhatsApp e a página do link avisam o fixo dos pontos antes, e o painel mostra "⭐ ganhou N pontos").
**Entrega só no horário de trabalho de cada um, pela escala do dia** (os fixos também: a escala fixa já preenche a
escala do dia): a mensagem sai de **30 min antes da entrada** até 10 min antes da saída, nunca no intervalo.
**📅 Escalados no dia** (em "Para quem?"): marca só quem tem turno na data escolhida (hoje até 14 dias para frente). Quem está de
folga ou não tem turno fica com o comunicado **guardado** e recebe no próximo turno; se não trabalhar até o "vale até",
fica ⌛ expirado. O robô (agendador) olha a fila a cada 2 minutos; quem já está no turno recebe na hora da criação.
No WhatsApp vai **só a chamada** (frase curta opcional, ex.: "Segue comunicado sobre um feedback positivo de uma
cliente"; em branco: "Tem um comunicado novo para você: *título*") com "Olá, <nome>!" e um **link**
(`/comunicado/<código>`): o comunicado completo a pessoa lê ao abrir o link, que tem o botão **✅ Li e estou ciente**
(os "tiques azuis" do WhatsApp não chegam ao sistema pela Z-API). **Controle de leitura** no detalhe de cada comunicado: ✅ leu (data/hora),
👀 abriu e não confirmou, 📤 recebeu e não abriu, ⏳ espera o turno (mostra quando), ⚠️ falhou, ⌛ expirou, 📵 sem
WhatsApp, ⛔ encerrado; filtros Todos / Leram / Faltam. Ações: **🔔 Lembrar quem não leu** (vai de novo no próximo
turno com "Lembrete"), **📤 Agora** (manda já, fora do turno — para uma pessoa ou para todos que esperam) e
**⛔ Encerrar** (para de mandar). O link usa o endereço da internet gravado em 📢 Clientes › ⚙️ Ajustes (sem ele a
tela não deixa criar); pela internet só ficam abertos `/comunicado/` e `/api/comunicado/`. Os comunicados antigos do
Telegram (Painel do Gestor) continuam como estavam.
Arquivos: `comunicados_equipe.py`, `templates/gestao_comunicados.html`, `templates/comunicado.html`; tabelas
`ComunicadosEquipe`, `ComunicadosEquipeDestinos` (criadas sozinhas na primeira vez).

### Novo (só na Web) — 🧭 Perfil da equipe (DISC) (10/2026: Gestão › 🧭 Perfil)
Avaliação de perfil comportamental **só para os fixos**. A gestão escolhe quem recebe (🆕 quem ainda não fez, 👥 todos,
📅 escalados no dia ou um a um), a validade e ⭐ pontos opcionais. O link vai no WhatsApp **no mesmo horário dos
📨 comunicados** (a partir de 30 min antes do turno, fora do intervalo; 📤 Agora manda na hora). No link (`/perfil/<código>`):
**24 grupos de 4 palavras** ("No trabalho, eu sou…": Decidido, Comunicativo, Paciente, Cuidadoso…) — em 2 passos com
cor, a pessoa toca na que 👍 MAIS e na que 👎 MENOS combina com ela. Antes vem uma **pergunta de treino** que não conta
("Qual sabor de sorvete…"), o selo **⭐ N pontos** aparece em todas as telas e o botão **🔊 Ouvir** lê em voz alta. O
andamento fica no celular: dá para fechar e continuar (a v2, com frases do dia a dia, voltou para as palavras a pedido).
**🧑‍💼 Processo seletivo** (aba própria): a gestão cadastra o candidato (nome, WhatsApp opcional, vaga) e o link vai **na
hora**, sem pontos e sem escala (sem WhatsApp: 🔗 copiar link). O candidato vê só um "obrigado"; a gestão vê o relatório, onde
ele combina na loja e **✨ o que ele traz que falta na equipe**. Use junto com a entrevista; 🗑️ Apagar remove nome, WhatsApp,
CPF, nascimento e respostas (LGPD). Candidatos não entram na equipe nem nos envios dos fixos (colunas `Tipo` e `Vaga` em `AvaliacoesDisc`).
**📸 Trabalhe conosco** (link da bio do Instagram: `/trabalhe-conosco`, público): a pessoa preenche nome, WhatsApp,
**CPF** (confere os dígitos) e **data de nascimento** (no lugar da idade; a idade é calculada e fica certa com o tempo), bairro, **tipo de vaga** (💼 fixa · 📅 freelancer · 🔁 os dois — pergunta própria, obrigatória), **áreas** (🍦 Atendimento,
👩‍🍳 Cozinha, 🧹 Zeladoria, ❄️ Câmara Fria/Repositor), disponibilidade,
experiência e autoriza guardar os dados; segue direto para o questionário. Não manda WhatsApp (o número foi digitado por
quem quis; o número da loja não pode virar spam). Proteções: campo escondido contra robô, até 5 cadastros por hora no mesmo
aparelho, e o mesmo WhatsApp (ou o mesmo CPF) em até 60 dias atualiza o cadastro em vez de duplicar. Na aba 🧑‍💼 Processo seletivo: o link
(🔗 copiar e 🔲 QR para imprimir), filtros por **tipo de vaga** (a fixa mostra também quem topa os dois), área e **etapa** (🆕 Novo · 📞 Entrevista · ✅ Contratado · ❌ Não seguiu),
💬 WhatsApp do candidato e os dados no relatório. **🪪 CPF e nascimento**: só aparecem num botão do card (não vão no
painel, no aviso do grupo nem no log; o log registra só quem abriu), com 📋 copiar nome + CPF + nascimento; a gestão grava ou
corrige ali (cadastro antigo ou criado pelo ➕, onde também são opcionais) — rota `/api/gestao/perfil/<id>/documentos`. Colunas novas em `AvaliacoesDisc`: `Origem`, `Areas`, `Idade`, `Bairro`,
`Disponibilidade`, `Experiencia`, `Etapa`, `AceiteEm`, `Cpf` (só os 11 números), `Nascimento`, `TipoVaga` (cadastro antigo: quem marcou a área Freelancer conta como
freelancer; quem não marcou fica "❔ Não informou" e a gestão marca no card); pela internet ficam abertos só `/trabalhe-conosco` e `/api/trabalhe-conosco`. O sistema soma 🔴 D Dominante, 🟡 I Influente, 🟢 S Estável e 🔵 C Conforme
(porcentagens que somam 100; dois fatores fortes e próximos viram perfil combinado, ex.: IS) e monta o **relatório da
gestão**: pontos fortes, o que motiva, o que desmotiva, como conversar, como dar feedback, como liderar, **onde rende
mais na loja** — TODAS as funções (Caixa, Recepção, Frente Loja, Salão, Varanda, Buffet, Cozinha, Limpeza, Câmara Fria e
liderança de turno) em ✅ combina muito / 🟡 pode funcionar / ⚠️ menos indicado, cada uma com o **porquê** (qual fator do
perfil ajuda ou falta, e avisos como "trabalho mais sozinho" para quem é muito Influente) — e pontos de atenção. A pessoa vê só um **resumo positivo** (perfil e pontos fortes) e ganha os pontos
uma vez. Aba 👥 Equipe: quantos de cada perfil, dicas do que falta na equipe e **sugestões para a escala** (quem combina
mais com cada setor); aba 📋 Envios: situação de cada link (🔔 Lembrar, 📤 Agora, ⛔ Cancelar). Aviso no grupo da gestão
quando alguém responde (desliga em 📣 Avisos › 🧭 Perfil da equipe). Questionário próprio, baseado na teoria DISC
(pública): ferramenta de orientação, não teste certificado — não serve sozinho para contratar ou demitir. Dado pessoal
(LGPD): só a gestão vê o relatório. Pela internet só ficam abertos `/perfil/` e `/api/perfil/`.
Arquivos: `perfil_disc.py`, `templates/gestao_perfil.html`, `templates/perfil_disc.html`; tabela `AvaliacoesDisc`
(criada sozinha na primeira vez; guarda os fatores escolhidos em cada grupo).

**🔗 Contratado → cadastro do fixo:** no card do candidato em ✅ Contratado aparece "Vincular ao cadastro do fixo" (já vem
sugerido o fixo do mesmo WhatsApp ou do mesmo nome). A avaliação dele passa a valer como o perfil do fixo em 👥 Equipe e no
📤 envio (não entra em "quem ainda não fez"), sem responder de novo e sem apagar o processo seletivo (coluna
`VinculoFuncionarioID`; "desfazer" no card). Se o fixo responder outra avaliação depois, vale a mais nova.
**📅 Freelancers escolhidos:** a janela 📤 Enviar avaliação tem 👥 Fixos e 📅 Freelancers (nenhum freelancer vem marcado: você
escolhe). O link vai no turno do freelancer (igual aos comunicados; 📤 Agora manda na hora), **sem pontos** (não está na
gamificação). Na 👥 Equipe aparecem os "📅 Freelancers avaliados" (fora da contagem dos fixos) e uma coluna 📅 Freelancers nas
sugestões para a escala (colunas `Tipo = 'free'` e `FreelancerID`).

**🔋 O que motiva (10/2026, parte 2 do link):** depois das 24 palavras vem a **parte 2: 28 perguntas de "Qual frase combina
mais com você?"** ("Gosto de ver o cliente saindo feliz" **ou** "Trabalho pensando nas coisas que quero conquistar"…). As frases
**descrevem a pessoa** — não são coisas que a loja daria (bônus, aumento, comissão, folga, curso) —, e a tela avisa que nada muda
no pagamento, na escala ou nas folgas por causa das respostas: assim ninguém responde pensando no que vai ganhar. São 8
motivações — 💰 Financeiro, 🏆 Reconhecimento, 📚 Aprendizado, 🤝 Equipe, 🛡️ Estabilidade, 🗽 Autonomia, 🎯 Desafio e 💜 Propósito
—, cada uma disputa uma vez com cada outra (28 duplas, frases diferentes, metade das vezes em cima) e ganha uma nota de 0 a 7. A pessoa vê as 2 que mais a movem; a gestão vê as 8 barras, **💡 como motivar**, **🎁 prêmios que funcionam**,
**🚫 evite** e o que pesa menos. Na 👥 Equipe: "🔋 Motiva: …" em cada card e o bloco **🔋 O que move a equipe** (quantos de cada,
dicas e os prêmios que mais motivam a equipe toda — bom para escolher a premiação da gamificação). O candidato também
responde (só a gestão vê). O link novo tem as 2 partes (uns 12 min); quem já fez o perfil recebe **🔋 Só a motivação** (uns
3 min): na janela 📤 Enviar avaliação › "O que enviar?" ou no botão 📤 Mandar só a motivação do relatório de quem ainda não respondeu. O relatório junta as 2 partes da mesma
pessoa (se vieram em links diferentes, diz de quando é cada uma); vale a mais nova. Links antigos (só o perfil) continuam
funcionando. Colunas novas em `AvaliacoesDisc`: `Partes` (`disc` antigo · `disc_motiv` · `motiv`), `Motivos` (as notas),
`MotivoRespostas` (o que escolheu em cada dupla) e `MotivoEm`. Arquivo novo: `perfil_motivacao.py`.
**Tela do 🧑‍💼 Processo seletivo reorganizada:** barra com ➕ Avaliar um candidato, 📸 Trabalhe conosco (🔗 copiar e 🔲 QR) e
ℹ️ Como funciona; abas de etapa com a contagem (Todos · 🆕 Novo · 📞 Entrevista · ✅ Contratado · ❌ Não seguiu); Vaga e Área
em listas e 🔎 busca pelo nome. Cada card mostra só o essencial (nome, idade, etapa, tipo de vaga, áreas, bairro, perfil com a
barra DISC, 🔋 o que motiva e onde combina) e os botões 📄 Relatório, 💬 WhatsApp e **⋯** (🪪 CPF e nascimento, 🔗 copiar link,
📤 mandar agora, tipo de vaga, vincular ao fixo, cancelar e 🗑️ apagar).

### Novo (só na Web) — 👔 Liderança: sócios e líderes (10/2026: Gestão › 👔 Liderança)

Avaliação de perfil no nível da **gestão**, **à parte** do 🧭 Perfil da equipe (que não mudou em nada): módulo
`perfil_lideranca.py`, tabela própria `AvaliacoesLideranca` (+ `ConfigLideranca` para o acesso), página da gestão
`/gestao/lideranca` e link público `/lideranca/<código>` (liberado na internet só ele e `/api/lideranca/`).
- **Papéis:** 👑 sócio(a)/dono(a) · 🧑‍💼 líder da equipe · 🎯 candidato(a) a líder. Sem pontos. Com WhatsApp o link vai na
  hora (não espera turno); sem WhatsApp: 🔗 copiar o link ou **↗️ Responder aqui** (para o próprio sócio responder).
- **Questionário:** 24 **situações da gestão** (decisão importante, faturamento caindo, contratar, reunião, erro de
  funcionário, delegar, mudança grande, conflito, futuro da empresa, dinheiro e custos, cliente reclamando, cobrar a
  equipe, fornecedor, equipe desmotivada, sócio que discorda, notícia ruim…), cada uma com 4 frases (uma de cada fator,
  a ordem muda); a pessoa toca na que MAIS e na que MENOS parece com ela. Mesmo cálculo do DISC.
- **Relatório de gestão:** estilo (🔴 Líder executor · 🟡 inspirador · 🟢 agregador · 🔵 analítico), pontos fortes na gestão,
  riscos e pontos cegos, como decide, sob pressão, como delega, como se comunica, conflitos, quem precisa ao lado, para se
  desenvolver, como trabalhar com a pessoa e **as 8 áreas da gestão** (finanças, pessoas, operação, marketing, compras,
  expansão, crises, gerência da loja) em ✅/🟡/⚠️ com o **porquê**; 🖨️ imprimir.
- **👥 Time de gestão** (última resposta de cada sócio e líder): quem é forte em cada fator e o que falta na gestão.
  **🤝 Os sócios juntos:** como se complementam (pelo fator principal de cada um) e a **divisão sugerida das áreas**
  (quando nenhum dos dois tem o perfil da área, diz isso e sugere apoio de fora). **🎯 Candidato:** o que traz que falta
  na gestão e como combina com cada sócio; ele vê só o obrigado (sócio e líder veem o estilo e os pontos fortes).
- **🔒 Quem pode ver:** lista no banco (vazia = qualquer gestor). Depois de escolher, quem está fora vê só um cadeado e as
  rotas respondem 403. Não dá para se tirar da lista. **Nada vai para o grupo de avisos** (privacidade).

### Novo (só na Web) — 💬 Central de Atendimento do WhatsApp (10/2026: `/atendimento`, menu Gestão › 💬 Atendimento)

Atendimento e vendas pelo **número dos clientes** (o mesmo das campanhas: 2ª instância da Z-API, nunca o da loja), num
computador. Módulo `atendimento.py`, página `templates/atendimento.html`; tabelas `AtendimentoConversas`,
`AtendimentoMensagens`, `AtendimentoAtendentes`, `AtendimentoProdutos`, `AtendimentoBotoes`, `ParametrosAtendimento`.
- **As mensagens chegam** pelo webhook "Ao receber" que o 📢 Clientes já usa (`clientes.processar_webhook` chama
  `atendimento.do_webhook`; se a central falhar, o SAIR/VOLTAR/reservas seguem iguais). Uma conversa por WhatsApp:
  🔴 esperando (o mais antigo primeiro) · em atendimento · encerrada (volta para "esperando" se o cliente escrever).
  Foto, áudio, vídeo, arquivo e localização (link do mapa) aparecem na conversa. Resposta automática do 📢 Clientes
  (SAIR, VOLTAR, reserva) entra na conversa sem deixá-la esperando. ✔️✔️ entregue/lida pelo webhook "Status".
  Mandada pelo celular entra na conversa que já existe (precisa ligar "notificar as enviadas por mim" na Z-API);
  mensagem de campanha nunca cria conversa. A conversa é achada pelo número igual, com/sem o 9, ou pelo código
  `@lid` (coluna `Lid`, guardada quando o cliente escreve). Não confiar só no `fromApi`: fica de fora apenas o que o
  sistema reconhece como dele (cópia da central — número da mensagem ou mesmo texto em 2 min —, campanha em
  `CampanhaEnvios`, SAIR/VOLTAR → "Automática"); o resto é "Pelo celular", tira o cliente da espera e a conversa fica
  com "Celular" (se o cliente escrever de novo, volta para esperando). O 📡 mostra o que houve com a última mandada
  pelo celular (entrou / sem conversa com …1234 / erro).
  **@lid:** a resposta do celular costuma vir com o código `@lid` no lugar do número (a Z-API diz que não dá para
  converter o código em número; o `chatLid` é o identificador estável). A conversa aprende o próprio `@lid` por:
  `chatLid`/`senderLid` da mensagem do cliente; a cópia (`fromMe`) e o aviso de entregue/lida das mensagens da central;
  e o `phone-exists` da Z-API (devolve o `lid`; uma vez por dia por conversa, coluna `LidConferidoEm`). Chegou um
  `@lid` que ninguém conhece: pergunta o das conversas dos últimos 30 dias (até 10) em segundo plano e tenta de novo
  uma vez. Código `@lid` nunca é lido como telefone (antes `5544…@lid` virava um número falso).
- **Login:** atendente com o **próprio PIN** (cadastrado pela gestão a partir do cadastro de funcionários; 5 erros =
  15 min bloqueado, igual ao app), sem acesso ao resto da Gestão. Gestor entra com o PIN do app (ou já logado na
  Gestão). Entrar como atendente tira o login de gestor daquele navegador. Permissões por atendente: ver as conversas
  dos outros · mudar botões e preços · ver a visão da gestão.
- **Atender:** abrir uma conversa esperando = assumir (fica registrado); responder a de outro = assumir; ➡️ passar para
  outra pessoa; encerrar. Tudo o que vai fica com o nome de quem mandou. Texto, foto (o computador diminui), Enter manda.
  ⚠️ não foi → "Mandar de novo". Plim e contador no título quando chega mensagem (a página pergunta a cada 3 s).
- **Botões prontos** em 3 grupos (🍧 Produtos com foto + preços · Entrega e pagamento · Andamento do pedido): um clique
  manda para o cliente. Os **produtos ficam na lateral direita** (cartão com a foto), embaixo do cliente; entrega e
  andamento no rodapé. Um botão pode ficar **dentro de outro** (coluna `PaiID`, um nível só, mesmo grupo do de fora):
  aparece como "+ nome" no cartão (ex.: "+ Complementos" dentro do Açaí). Apagar o de fora solta os de dentro.
  Ajuste único (`botoes_v2`): Complementos entrou no Açaí e o "Em preparo" (texto original) saiu. No texto, `{nome}` = primeiro nome do cliente e `[Categoria]` = a lista dos itens da tabela
  dessa categoria que **tem hoje**, com o preço (complemento grátis sem preço, pago com "+R$").
- **Tabela de preços** (a mesma do 99Food; começou com os 3 açaís e os 24 complementos): categoria, nome, preço,
  complemento, "tem hoje". Mudou aqui, todos os botões mandam o preço novo. **Ordem dos itens** (é a ordem das
  listas nas mensagens): 🔤 A–Z por categoria (entende números: 300, 500, 700), arrastar pela alça ⠿ (só dentro da
  categoria; perto da borda a página rola) ou alça + setas ↑ ↓. Aviso "mudança sem salvar" e pergunta antes de sair da
  aba; o 💾 Salvar fica sempre à vista. O servidor já grava na ordem da lista (nada mudou nele).
- **📊 Visão da gestão:** conversas, esperando resposta agora, tempo médio até a 1ª resposta, mensagens, por pessoa
  (com quem está com a central aberta) e as conversas abertas. **Aviso no grupo da gestão** quando um cliente espera mais
  de X minutos (padrão 5; 0 desliga; tipo 💬 Atendimento no WhatsApp em 📣 Avisos), uma vez por espera (agendador, 1 min).
- Liberado na internet junto com a Gestão (`/atendimento`, `/api/atendimento`), sempre com login.
- **App próprio no computador** (`static/atendimento/manifest.webmanifest`, escopo `/atendimento`, ícone de balão): instalado
  pelo Chrome abre em janela própria, sem a faixa do endereço que aparecia quando a central abria dentro do app de
  compras (escopo `/compras/`); com `window-controls-overlay` o topo verde ocupa a barra de título. "Gestão" abre em
  outra janela. Tela compacta para 1280 × ~650 (Windows em 150%): topo e rodapé numa linha, filtros numa linha,
  conversa da lista em 2 linhas, ações curtas ("➡️ Passar", "✔️ Encerrar") — a área da conversa foi de 311 para 451 px.
  Botão "⬇️ Instalar app" (evento `beforeinstallprompt`: só aparece no Chrome quando dá para instalar). O app de compras
  passou a abranger o sistema todo (`scope: "/"`, `id: "/compras/"` — mesma identidade): Gestão e central abertas por
  dentro dele também ficam sem a faixa do endereço (o Chrome aplica ao fechar todas as janelas do app).
- **💾 Salvar contato** (lateral do cliente, quem pode ver a conversa): põe no cadastro do 📢 Clientes com o nome e o
  WhatsApp da conversa (origem "conversa no WhatsApp"), aniversário opcional, ofertas só marcando que o cliente
  autorizou; e, se marcado, na **agenda do celular** dos clientes (Z-API `contacts/add`; se recusar, o cadastro vale e a
  mensagem diz o motivo). Número oculto (`@lid`) não salva. Já cadastrado: avisa, não duplica.
- **📡 Diagnóstico (só a gestão vê, embaixo da busca):** quando chegou a última mensagem de cliente da Z-API (vale
  também a última mensagem de cliente já gravada na central); avisa se
  nunca chegou nenhuma (ou só avisos de entregue/lida), se o webhook é de **outra instância** (final do ID) e se uma
  mensagem chegou mas deu erro ao gravar (o motivo). A Web precisa repetir: ID da instância comparado sem diferenciar
  maiúsculas; corpo lido mesmo sem `Content-Type: application/json`; cliente com número oculto (`...@lid`) entra como
  "número oculto pelo WhatsApp"; a cópia do que o próprio sistema mandou (`fromApi`) não entra de novo (e, sem esse
  campo, texto igual mandado pela central nos últimos 2 min também não).
- **Próxima fase:** pedido na lateral (itens, total, Pix copia e cola, comanda) e vendas WhatsApp × 99Food.

**📅 Agenda pelo número dos clientes (10/2026):** a confirmação do agendamento (na hora em que é criado), o lembrete do
dia anterior (D-1, 10h) e o pós-venda (D+1) saem pelo **número dos clientes** em vez do número da loja. A mensagem entra na
💬 Central como "📅 Agenda" (cliente sem conversa: cria uma já encerrada, ninguém fica esperando); quando o cliente
responde, a conversa abre com a confirmação junto. A cópia que a Z-API devolve não vira "respondida pelo celular", não
conta como resposta de atendente e o ✔️✔️ entregue/lida aparece. Se o envio falha, a mensagem sai da central e o robô tenta
de novo. Chave em 📢 Clientes › ⚙️ Ajustes › **📅 Mensagens da agenda** (número dos clientes · número da loja); sem o número
dos clientes configurado, sai pelo da loja. Arquivo novo `agenda_whatsapp.py` (usado pelo `api_server.py` na rota
`/agendamentos/novo` e pelo `agendador_lembretes.py`); a escolha fica em `ParametrosClientes` (`agenda_numero`).

### App de compras — aba Gestão em 3 áreas (10/2026)
A aba **Gestão** do app (só o gestor vê) foi dividida em **🏪 Loja · 🛒 Compras · 📦 Estoque**, com o número de
pendências de cada área no botão (Loja: dias sem faturamento lançado; Compras: listas para aprovar + cupons para
conferir; Estoque: produtos que acabam em até 2 dias). A Gestão abre na última área usada.
- **🏪 Loja**: cartão da Folha × Faturamento (último dia, mês × meta, falta lançar, previsão de hoje e de amanhã),
  **💰 Lançar faturamento do dia** e a lista **Gestão da loja** com as páginas da Web (Escala, Folha, Pagamentos,
  Freelancers, 📣 Avisos, 📢 Clientes, 📨 Comunicados, 🧭 Perfil da equipe).
- **🛒 Compras**: Resumo (listas, compras em andamento, cupons, compras do mês, listas esquecidas, maiores
  fornecedores) e os relatórios Categorias, Inflação, Mais barato, Preços e Cupons.
- **📦 Estoque**: Resumo (acabam em até 2 dias, abaixo do mínimo, preços que subiram) e Consumo.

## 4. Gestão de Pessoas — RH (`gestao_pessoas_main.py` — 1.800 linhas)

Dados sensíveis: fica **por último**, com a segurança já testada.

| Função | Na Web | Status |
|---|---|---|
| Onboarding: lista, documentos enviados, dados cadastrais | Gestão › RH › Admissão | ⬜ |
| Aprovar exame admissional, reiniciar processo, excluir cadastro | Gestão › RH › Admissão | ⬜ |
| 🖨️ PDF completo (dados + fotos) | Gestão › RH › Admissão (baixar) | ⬜ |
| Solicitar documentos (onboarding) | Gestão › RH › Documentos | ⬜ |
| Documentos pessoais: enviar, editar, excluir, baixar/ver | Gestão › RH › Documentos (o servidor já tem a parte de arquivos) | 🟡 |
| Comunicados: criar (com imagem), enviar no Telegram, destinatários | Gestão › RH › Comunicados | ⬜ |
| Comunicados: ver quem deu ciência, excluir, filtrar | Gestão › RH › Comunicados | ⬜ |
| Recibo PDF do comunicado | Gestão › RH › Comunicados (baixar) | ⬜ |

## 5. Agendamentos (`agendamentos_main.py` — 740 linhas)

| Função | Na Web | Status |
|---|---|---|
| Listar agendamentos | Painel › Agenda & Reservas | ✅ |
| Criar / editar / excluir | Painel › Agenda & Reservas | ✅ |
| Status do pagamento (Pago / Pendente) | Painel › Agenda & Reservas | ✅ |
| 📢 Enviar lembrete geral no Telegram | o servidor já faz; falta o **botão** na página | 🟡 |
| Login | passa a ser o login da Gestão | ⬜ |

---

## O que muda de jeito (sem perder a função)

| No PC | Na Web |
|---|---|
| Escolher arquivo/pasta no computador (XML, imagem, documento) | Botão **Enviar arquivo** (os XMLs da SEFAZ já estão no servidor) |
| Salvar Excel / PDF numa pasta | O navegador **baixa** o arquivo |
| Gráficos (matplotlib) | Gráficos desenhados na página |
| Fotos (PIL) | Fotos na página, com zoom |
| Imprimir | Imprimir pelo navegador |
| Programa conecta direto no banco (com a senha) | Só o servidor conecta no banco |
| Copiar arquivos para o PC a cada atualização | Atualiza só o servidor |

## Etapas (ordem combinada — atualizada em 10/10/2026)

0. ✅ Inventário (este arquivo).
1. 🧪 **Base** — área `/gestao` (só rede da loja; a internet continua só com `/compras`), login
   das 2 contas (senha guardada de forma segura, sessão que expira, bloqueio após tentativas
   erradas, registro de quem fez o quê). Vai junto com a Entrega 1 da Escala.
2. **Escala da Loja** — Entrega 1 (escala do dia) → Entrega 2 (cadastros e configurações) →
   Entrega 3 (pagamentos de freelancers) → uso em paralelo → desliga `escala_loja_main.py`.
3. **Agendamentos**: botão do lembrete + login → desliga `agendamentos_main.py`.
4. **Gestão de Estoque**: Catálogo → Fornecedores → Notas/Vínculos → Contagens/Valor do
   Estoque → Sugestão/Buffet → Solicitações → Consultas → Administração.
5. **Painel do Gestor** (gamificação).
6. **Gestão de Pessoas (RH)**.

Antes de abrir qualquer parte da Gestão **pela internet**: projeto privado no GitHub, senhas
fora do GitHub e trocadas, código pelo Telegram no login.

Cada etapa: construir → testar → usar em paralelo com o PC → marcar ✅ aqui → desligar a tela do PC.

## Como acessar a Gestão

- No computador do servidor: `http://localhost:5000/gestao`
- Nos outros computadores/celulares da loja (mesma rede): `http://IP-DO-SERVIDOR:5000/gestao`
  (o mesmo endereço do painel da TV, trocando o final por `/gestao`).
- Pelo app de compras: aba **Gestão › 🏪 Loja › Gestão da loja** (Escala, Folha, Pagamentos, Freelancers, Avisos,
  Clientes, Comunicados e Perfil da equipe;
  abrem direto, sem pedir o PIN de novo).
- Menu no alto de toda página da Gestão: **🗓️ Escala · 👤 Freelancers · 💰 Pagamentos · 📊 Folha · 📣 Avisos · 📢 Clientes
  · 📨 Comunicados · 🧭 Perfil** (`/gestao/escala`, `/gestao/freelancers`, `/gestao/pagamentos`, `/gestao/folha`,
  `/gestao/avisos`, `/gestao/clientes`, `/gestao/comunicados`, `/gestao/perfil`).
- Pela internet (fora da loja): liberado para a Gestão desde 10/2026, a pedido do Rodrigo — só gestor,
  com o login do app (nome + PIN, bloqueio após erros). Para fechar: `GESTAO_PELA_INTERNET = False` no config.py.
- Login: o mesmo do app de compras (nome + PIN); só quem é gestor no app entra.

## Resumo da contagem

| Programa | Funções | ✅ | 🧪 | 🟡 | ⬜ |
|---|---|---|---|---|---|
| Gestão de Estoque | 41 | 8 | 0 | 8 | 25 |
| Painel do Gestor | 17 | 0 | 0 | 5 | 12 |
| Escala da Loja | 43 | 0 | 36 | 0 | 7 |
| Gestão de Pessoas | 8 | 0 | 0 | 1 | 7 |
| Agendamentos | 5 | 3 | 0 | 1 | 1 |
| **Total** | **114** | **11** | **36** | **15** | **52** |

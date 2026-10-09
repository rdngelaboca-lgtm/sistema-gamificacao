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
| 19. 📱 Confirmar escala no WhatsApp: mensagem a cada pessoa (data, posição, horário, intervalo) + diretriz do setor; resumo enviados/falhas | 🧪 |
| 20. Mensagens rápidas de status | 🧪 |

**Depuração da Entrega 1 (10/2026) — 17 correções:** turno que passa da meia-noite agora é conferido
contra os outros da mesma posição; turnos em posição removida do mapa aparecem (lista "Removidas do
mapa") e podem ser excluídos; banco fora do ar avisa em vez de mostrar o dia vazio; o fixo já escalado
em outra posição não aparece mais como "disponível" (também no PC); "830" digitado vira 08:30; trocar
de dia rápido não mostra mais a escala do dia errado; falha ao carregar limpa a tela e trava os botões;
clique duplo no Copiar não duplica; WhatsApp não manda "None às None" e o acompanhamento tenta de novo
quando a rede cai; trocar freelancer por funcionário apaga a diária curta/longa; a página se atualiza
ao voltar para a aba.

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

### App de compras — aba Gestão em 3 áreas (10/2026)
A aba **Gestão** do app (só o gestor vê) foi dividida em **🏪 Loja · 🛒 Compras · 📦 Estoque**, com o número de
pendências de cada área no botão (Loja: dias sem faturamento lançado; Compras: listas para aprovar + cupons para
conferir; Estoque: produtos que acabam em até 2 dias). A Gestão abre na última área usada.
- **🏪 Loja**: cartão da Folha × Faturamento (último dia, mês × meta, falta lançar, previsão de hoje e de amanhã),
  **💰 Lançar faturamento do dia** e a lista **Gestão da loja** com as páginas da Web (Escala, Folha, Pagamentos,
  Freelancers, 📣 Avisos).
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
- Pelo app de compras: aba **Gestão › 🏪 Loja › Gestão da loja** (Escala, Folha, Pagamentos, Freelancers e Avisos;
  abrem direto, sem pedir o PIN de novo).
- Menu no alto de toda página da Gestão: **🗓️ Escala · 👤 Freelancers · 💰 Pagamentos · 📊 Folha · 📣 Avisos**
  (`/gestao/escala`, `/gestao/freelancers`, `/gestao/pagamentos`, `/gestao/folha`, `/gestao/avisos`).
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

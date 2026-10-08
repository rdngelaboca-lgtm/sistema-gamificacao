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

Legenda: ✅ já existe na Web/app (só conferir) · 🟡 existe em parte · ⬜ falta fazer

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

## 3. Escala da Loja (`escala_loja_main.py` — 3.000 linhas)

O painel Web mostra o mapa, o fluxo e as pausas do dia (só leitura).

| Função | Na Web | Status |
|---|---|---|
| Mapa da loja com as posições, ◀ Hoje ▶, resumo e alertas do dia | Gestão › Escala (painel só mostra hoje) | 🟡 |
| Escalar pessoa na posição (clique no mapa) | Gestão › Escala | ⬜ |
| Copiar escala (ontem / semana passada) | Gestão › Escala | ⬜ |
| Gerar intervalos automáticos / gerenciar intervalos | Gestão › Escala | ⬜ |
| Enviar escala no Telegram / confirmar escala no WhatsApp | Gestão › Escala | ⬜ |
| Configurar mapa (posições/setores), diretrizes por setor | Gestão › Escala › Configurar | ⬜ |
| Configurações de automação e horários de pico | Gestão › Escala › Configurar | ⬜ |
| Gráfico de fluxo da equipe | Gestão › Escala (painel tem) | 🟡 |
| Freelancers: cadastrar, editar, excluir | Gestão › Escala › Freelancers | ⬜ |
| 💰 Pagamentos: confirmar pago, corrigir horário/ajuste, recibo WhatsApp, Excel | Gestão › Escala › Pagamentos | ⬜ |
| Valores das diárias / hora extra, feriados (nacionais do ano) | Gestão › Escala › Pagamentos | ⬜ |

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

## Etapas (ordem combinada)

0. ✅ Inventário (este arquivo).
1. **Base e segurança** — área `/gestao` (só rede da loja), login das 2 contas com senha forte
   (e código pelo Telegram se um dia abrir pela internet), sessão que expira, bloqueio após
   tentativas erradas, registro de quem fez o quê; senhas fora do GitHub e trocadas.
2. **Agendamentos** (piloto): botão do lembrete + login → desliga `agendamentos_main.py`.
3. **Gestão de Estoque**: Catálogo → Fornecedores → Notas/Vínculos → Contagens/Valor do
   Estoque → Sugestão/Buffet → Solicitações → Consultas → Administração.
4. **Painel do Gestor** (gamificação).
5. **Escala da Loja** e pagamentos de freelancers.
6. **Gestão de Pessoas (RH)**.

Cada etapa: construir → testar → usar em paralelo com o PC → marcar ✅ aqui → desligar a tela do PC.

## Resumo da contagem

| Programa | Funções | ✅ | 🟡 | ⬜ |
|---|---|---|---|---|
| Gestão de Estoque | 41 | 8 | 8 | 25 |
| Painel do Gestor | 17 | 0 | 5 | 12 |
| Escala da Loja | 11 | 0 | 2 | 9 |
| Gestão de Pessoas | 8 | 0 | 1 | 7 |
| Agendamentos | 5 | 3 | 1 | 1 |
| **Total** | **82** | **11** | **17** | **54** |

# Gestão de Estoque — Engenharia Reversa (dissecação completa)

> **Para que serve este documento:** é o mapa do módulo de Estoque *como ele é hoje*, antes de qualquer
> refatoração. Ele descreve o comportamento e não julga se está certo ou errado. Os pontos frágeis
> estão listados na seção 4.
>
> **Base analisada:** commit `ae494e3` (branch `claude/gela-boca-handoff-oi3df2`).
>
> | Arquivo | Linhas | Papel |
> |---|---:|---|
> | `gestao_estoque_main.py` | 8.016 | Programa do PC (Tkinter): as 8 abas, as janelas e as regras de tela |
> | `database.py` (parte do Estoque) | ~3.300 de 12.822 | Camada de dados: ~95 funções usadas pelo Estoque |
> | `nota_xml.py` | 203 | Leitura do XML da NF-e e regras fiscais (CFOP, rateio de ST/frete) |
> | `nfe_distribuicao.py` | 634 | Download dos XMLs na SEFAZ (certificado A1) |
> | `file_utils.py` | 38 | Abrir um arquivo no visualizador do sistema |
>
> **Convenções:**
> - `arquivo:linha` aponta a linha onde a função começa.
> - **E/S** = entradas e saídas.
> - **Banco** = tabelas lidas e gravadas.
> - **Arquivo** = arquivo físico no disco.
> - **⚠ Dívida** = constatação de dívida técnica, sem julgamento.
> - Nenhum valor do `config.py` aparece aqui, só os *nomes* das configurações.

---

## 1. Visão Geral do Módulo

O **Gestão de Estoque** é um programa de computador (Tkinter, `python gestao_estoque_main.py`). Ele
transforma as **notas fiscais de compra** em custo e quantidade por produto e as cruza com as
**contagens físicas** do estoque, para responder a quatro perguntas:
- quanto vale o estoque;
- quanto se consome por dia;
- o que comprar, de quem e em que quantidade;
- onde está o erro de cadastro.

A peça central é o **Catálogo Mestre** (`ProdutosEstoque`): uma lista única de produtos do jeito que a
loja os chama. Cada fornecedor descreve o mesmo produto de um jeito diferente no XML. A ponte entre os
dois é o **vínculo DE/PARA** (`ProdutosFornecedor`), que guarda:
- a descrição do XML, o código e o EAN do fornecedor;
- o **Qtd/Cx** (`FatorConversao`): quantas unidades do estoque vêm em 1 unidade comprada.

Na importação, cada item da nota vira uma linha em `ItensNotaFiscalEntrada`, **já convertida para a
unidade do estoque**. O custo de cada item já inclui ST, FCP-ST, IPI, frete, seguro e outras despesas,
menos o desconto. As contagens (`ContagensEstoque` / `ItensContagemEstoque`) vêm do próprio PC ou do
app de celular.

Desses dados saem:
- o **Valor do Estoque**: média ponderada de 90 dias mais o percentual de royalties da categoria. Pode
  ser "fechado" num retrato que não muda mais;
- a **Sugestão de Compra**: consumo medido entre duas contagens, estoque projetado até hoje e pedido
  arredondado em caixas, com texto pronto para o WhatsApp;
- as **Consultas**: histórico de preços e notas;
- as ferramentas de **auditoria**: fator suspeito, duplicados, compra mais cara que a nota, desmembrar
  caixa em unidades.

Na arquitetura geral do sistema Gela Boca, o Estoque é um **cliente "gordo" do SQL Server**. A tela
chama o `database.py` direto, sem passar pela API Flask. Ele compartilha banco, regras e arquivos com
o resto do sistema:
- **App de compras / PWA `/compras`** (`api_server.py`, `compras_database.py`, `recebimento.py`,
  `orcamentos.py`, `compras_cupom.py`): grava contagens, itens avulsos bipados sem cadastro e as
  conferências de recebimento que o Estoque usa na importação. Também lê sugestão, vínculos e alertas
  de preço.
- **Agendador** (`agendador.py`, `alertas_estoque.py`): baixa os XMLs da SEFAZ de hora em hora para a
  pasta que a aba 3 lê, e manda no Telegram os alertas de aumento de preço calculados por
  `database.aumentos_de_preco`.
- **Bot do Telegram** (`telegram_bot.py`): cria as Solicitações Internas que a aba 7 aprova ou recusa.
- **Programa de RH/gamificação**: a tabela `Funcionarios` dá o nome do responsável pela contagem.

O módulo cresceu por camadas. Os marcadores `[MELHORIA]`, `[AUDITORIA ESTOQUE]`, `[DEPURAÇÃO 2]`,
`[ROYALTIES]`, `[NCM]` etc. ficaram nos comentários, e convivem nele:
- código novo e versões antigas ainda presentes;
- migrações de schema feitas em tempo de execução;
- estado guardado em atributos da janela e em arquivos JSON locais;
- muitas decisões tomadas pelo **texto** exibido na tela.

---

## 2. Análise Detalhada (Função por Função / Bloco por Bloco)

A análise segue a ordem do arquivo principal. As funções do `database.py` estão agrupadas por
assunto na seção 2.15, e cada aba indica quais delas usa.

### 2.1 `gestao_estoque_main.py` — cabeçalho (linhas 1–65)

**Logging (L4–43).** Monta `logs/gamificacao_sistema.log` ao lado do arquivo (`RotatingFileHandler`,
10 MB × 5 arquivos) e também escreve no console.
- Se não conseguir criar a pasta `logs`, usa a pasta do programa e avisa no `stderr`.
- `logging.getLogger('').handlers = []` (L37) **apaga os handlers do logger raiz** antes do
  `basicConfig`. Ou seja, reconfigura o log do processo inteiro.
- Logo depois, `import database` (L47) faz **exatamente a mesma coisa** de novo: `database.py:58`
  zera os handlers e cria um segundo `RotatingFileHandler` para o *mesmo* arquivo.
- ⚠ Dívida: o primeiro handler sai do logger, mas não é fechado (o arquivo continua aberto). Ver F-20.

**Imports (L45–65).**
- `tkinter`/`ttk`/`messagebox`/`filedialog`/`simpledialog`, `tkcalendar.DateEntry` (obrigatório), `database`,
  `config`, `json`, `re`, `datetime`, `Decimal`.
- `lxml` é tentado e, se faltar, cai em `xml.etree` (`USANDO_LXML`, `ET`). ⚠ Os dois **nunca são
  usados**: a leitura do XML foi para `nota_xml.py`.
- `file_utils` é importado na L7, antes da configuração do log.
- Mais imports no meio do arquivo:
  - `unicodedata`, `math`, `collections`, `threading` (L165–168);
  - `from nota_xml import ...` e `import nota_xml` (L493–494, com `# noqa: E402`).
- Imports tardios dentro das funções:
  - `matplotlib` (gráfico);
  - `nfe_distribuicao` (SEFAZ);
  - `pandas` (exportações);
  - `shutil`.

**`PASTA_DO_PROGRAMA`.** Base de todos os arquivos locais da seção 3.5.

### 2.2 Funções auxiliares do módulo (fora da classe)

| Função | O que faz, passo a passo | E/S e observações |
|---|---|---|
| `para_decimal(texto, nome_campo, permitir_zero, permitir_negativo)` `:71` | 1. Tira `R$` e espaços. 2. Se tem `,` **e** `.`, o **último** dos dois é o separador decimal e o outro é apagado. 3. Se só tem `,`, ela vira `.`. 4. Converte para `Decimal`. 5. Recusa NaN/Infinito. 6. Recusa zero ou negativo conforme as flags. | Entra texto e sai `Decimal`. Erro vira `ValueError` com o nome do campo. ⚠ Vazio é erro (o `escala_regras.para_decimal_br` devolve 0). ⚠ `"1.234"` (só ponto) vira **1,234**: o ponto de milhar brasileiro não é reconhecido. |
| `fmt_num(valor, casas, vazio)` `:101` | Formata com N casas usando ponto. `None` vira `vazio`. Se der erro, devolve `str(valor)`. | É o que a tela mostra. Várias rotinas **releem** esse texto com `para_decimal` (ver F-26). |
| `fmt_data(valor, formato, vazio)` `:111` | `date`/`datetime` passa por `strftime`. Texto passa por `fromisoformat(texto[:19])`; se falhar, devolve `texto[:10]`. | |
| `data_de_texto_br(t)` `:124` | Converte `dd/mm/aaaa` em `date`, ou devolve `None`. | |
| `chave_ordenacao(texto)` `:132` | Datas `dd/mm/aaaa` viram ordinal. Tira `R$`, `meses`, `>`, `📏`, `≈`. Número no formato brasileiro vira `(0, número, '')`; o resto vira `(1, 0, texto)`. | É a chave do `ordenar_coluna_treeview`. ⚠ A lista de símbolos está fixa no código. |
| `nome_arquivo_seguro`, `so_digitos` `:153/158` | Limpeza de texto. | ⚠ `so_digitos` também existe em `nota_xml.py`. |
| `sem_acento(t)` `:175` | NFKD, sem marcas, minúsculas. | |
| `linha_do_clique(tree, event)` `:181` | `identify_row(y)`, foca a linha; se não achar, usa `tree.focus()`. | Usada nos duplos-cliques. |
| `buscar_nomes(termo, nomes)` `:199` | Todas as palavras do termo (sem acento) precisam estar no nome. Os nomes que **começam** com o termo vêm primeiro. | Busca padrão das abas 4, 5 e 8 e do gestor de vínculos. |
| `fmt_qtd` `:214`, `fmt_reais` `:224` | 3 casas sem zeros à direita, com vírgula. `R$ 1.234,50` com `ROUND_HALF_UP`. | ⚠ Negativo sai `R$ -5,00`. |
| `UNIDADES_FRACIONADAS` + `qtd_para_pedido` `:237` | Para `KG, G, GR, L, LT, ML, M`, 3 casas. Para as outras unidades, arredonda para cima (`ceil`). | Lista de unidades fixa no código. A unidade do produto é texto livre (F-28). |
| `calcular_qtd_contagem(texto, fator, unidade)` `:251` | 1. Troca `×`/`*` por `x`. 2. Separa por `+`. 3. Um termo `a x b` vale `a·b` **unidades**. 4. Um número simples: o **1º** termo é multiplicado pelo fator (se fator > 1) e os demais termos são unidades soltas. Ex.: `3+5` com caixa de 12 = 41. 5. Devolve `(total, detalhe)`. O detalhe é `None` quando é só um número e o fator ≤ 1. | Regra de digitação da contagem (aba 4, editar contagem, avulsos). |
| `sugerir_unidade_contagem(total, fator_usado, fatores, anterior, digitado_simples)` `:290` | 1. Usa distância em log (`distancia` `:304`). 2. Se o total está a até 3× da última contagem, devolve `None`. 3. Senão testa `total·f` (contou caixas como unidades) ou `total/fator` (o contrário). 4. Aceita o candidato se ficar a até 2× da contagem anterior. | Gera o "Você contou em caixa?". |
| `calcular_linha_sugestao(item, dias_cobertura, prazo_dias, data_ref, preferir)` `:324` | **Núcleo da Sugestão** (detalhado em 2.9). Recebe o dicionário de `database.calcular_sugestao_compra` e devolve a linha pronta. | ⚠ Dicionário de ~30 chaves sem tipo. Cálculo e textos de tela misturados (ex.: `colunas` é uma tupla de 10 textos na ordem exata da Treeview). |
| `linhas_do_banco_para_dicts(rows)` `:461` | `Row` do pyodbc (via `cursor_description`), dict ou objeto viram dict. `Decimal` vira `float`. | Usado nas exportações para o Excel. |
| `nome_aba_excel(nome, usados)` `:480` | Até 31 caracteres, sem `[]:*?/\`, único sem diferenciar maiúsculas. | |
| `sugerir_nome_limpo(nome)` `:502` | 1. Corta `%AGR:`, `CXA:`, `CX.:`. 2. Tira `***` e `...`. 3. Tira o código numérico do início (2+ dígitos seguidos de `-` ou espaço). 4. Coloca em Title Case, mas palavras com dígitos ficam como estão, siglas ficam em maiúsculas e preposições em minúsculas (menos a 1ª palavra). | Listas fixas `_PALAVRAS_MINUSCULAS` e `_SIGLAS_MAIUSCULAS`. |
| `criar_tree_zebrada(pai, **kw)` `:532` | Cria uma `Treeview` e **substitui `tree.insert`** (`insert_zebrado` `:540`) para pôr `zebra_par`/`zebra_impar` conforme o número de filhos *no momento da inserção*. | ⚠ É um monkeypatch. A zebra não se refaz depois de ordenar ou remover linhas (F-39). |

### 2.3 Classe `AppGestaoEstoque` — infraestrutura

**`__init__` `:557`.**
- Janela 1200×700. A barra de status (rodapé) é criada **antes** do `Notebook`.
- O `Notebook` tem **8 abas**, cada uma um `Frame`:
  1. Catálogo Mestre;
  2. Fornecedores;
  3. Importar XMLs (DE/PARA);
  4. Lançar Contagem Física;
  5. Sugestão de Compra;
  6. Administração / Reset;
  7. Solicitações (Líderes);
  8. 🔎 Consultas;
  9. 🏷️ Cadastro Franquia (seção 6).
- ⚠ A **ordem de criação importa**: `criar_aba_solicitacoes()` roda **antes** das variáveis de estado e
  das outras abas.
- Estado da instância criado aqui (lista completa na seção 3.4):
  - `produto_selecionado_id`, `custo_carregado_texto`, `fornecedor_selecionado_id`;
  - `itens_xml_nao_vinculados`, `dados_notas_processadas`, `ultima_pasta_xml`, `filtro_arquivos_xml`;
  - `mapa_produtos_mestre`, `lista_mestre_produtos_nomes`, `mapa_produtos_mestre_contagem`;
  - `lista_itens_para_salvar_contagem`, `lista_mestre_contagem_nomes`;
  - `cache_relatorio_posicao`, `mapa_contagens_historico`, `mapa_contagens_sugestao`.
- Liga `<<NotebookTabChanged>>` a `on_tab_changed`.
- Cria as abas 1, 2, 3, 4, 5, 6 e 8 e carrega as listas iniciais: produtos, fornecedores, combo do
  mestre, histórico de contagens, combos da sugestão, categorias e solicitações. **São ~7 consultas
  ao banco na abertura, todas na thread da tela** (a janela congela se o banco demorar).
- Depois: `configurar_atalhos()` e `aplicar_preferencias()`.
- `WM_DELETE_WINDOW` chama `ao_fechar_janela`.
- `after(400)` chama `verificar_rascunho_contagem`.

**`status(msg, tipo, segundos)` `:646`.**
- Mostra a mensagem no rodapé com ícone e cor, e a apaga depois de N segundos (`after`).
- Guarda em `self.ultimo_status` (⚠ ninguém lê) e grava `[status] ...` no log. ⚠ A busca da
  Sugestão chama essa função **a cada tecla**, o que enche o log.

**`aba_atual()` `:664`.**
- Devolve o **texto** da aba selecionada. ⚠ `on_tab_changed`, `atalho_buscar` e outras rotinas
  decidem pelo **texto/prefixo** da aba (`'5. Sugestão de Compra'`, `'8.'`…). Renomear uma aba muda
  o comportamento.

**`configurar_atalhos()` `:670`.**
- `bind_all` para Ctrl+F e Ctrl+Shift+F (`atalho_buscar`).
- F5: `on_tab_changed(None)` e uma mensagem.
- Delete em 5 `Treeview`: produtos, fornecedores, contagem atual, notas da Administração, contagens
  da Administração.
- ⚠ `bind_all` vale também para **todas as janelas filhas**: apertar F5 numa janela aberta recarrega
  a aba que está atrás.

**`atalho_buscar` `:685`.** Mapa *prefixo da aba → campo de busca* (`'1.'`, `'3.'`, `'4.'`, `'5.'`,
`'8.'`). Foca e seleciona o texto e devolve `"break"`.

**Preferências `:699–736`.**
- **Arquivo** `estoque_preferencias.json`.
- `ler_preferencias` devolve um dict, ou `{}` se der qualquer erro.
- `aplicar_preferencias` valida a geometria contra o tamanho da tela e a aba (inteiro de 0 a 7).
- `salvar_preferencias` lê o arquivo, junta com o que mudou e grava. Nunca falha.
- O mesmo arquivo guarda as chaves `sugestao` (aba 5) e `embalagem_contagem` (aba 4).

**`ao_fechar_janela` `:737`.**
1. Se a contagem em edição tem itens, pergunta se quer guardar o rascunho.
2. Se a resposta for sim, grava o rascunho.
3. Salva as preferências.
4. Fecha a janela (`destroy`).

**`carregar_categorias_do_banco` `:753`.**
- Usa `database.listar_categorias_produto()`; se der erro, usa `["Geral"]`.
- Atualiza até 4 combos, cada um só se já existir (`hasattr`): categoria do produto, filtro do
  catálogo (+ "Todas"), categoria na importação e categoria da sugestão (+ "Todas").

**`on_tab_changed(event)` `:793`.** Recarrega conforme o texto da aba:

| Aba | O que recarrega |
|---|---|
| 1 | Produtos |
| 2 | Fornecedores |
| 4 | Histórico de contagens |
| 5 | Combos da sugestão |
| 6 | Notas e contagens da Administração |
| 7 | Solicitações |
| 8 | Consultas |
| 9 | Cadastro na Franquia (lê também os XMLs da pasta da SEFAZ) |
| 3 | **Nada** (o estado da importação fica em memória) |

### 2.4 Aba 1 — Catálogo Mestre (`:821–1945`)

> **Atualização 10/2026 — produto inativo** ("não trabalho mais com ele"): `ProdutosEstoque.Ativo = 0`
> (+ `InativadoEm`; NULL = ativo; colunas criadas em `_garantir_colunas_estoque`). Botão **💤 Inativar /
> ✅ Reativar** para os selecionados e o filtro **Mostrar › 💤 Inativos**. O inativo some do Catálogo, da
> contagem (combos, leitor, contar por lista), dos combos de vínculo (o nome do vinculado continua no
> `mapa_produtos_mestre`), da sugestão de compra e avisos (`calcular_sugestao_compra`), da folha de contagem,
> do "não contado" do Valor do Estoque, do App de Compras (busca, rotinas: `existe=False` + "(💤 inativo)" no
> editor, estoque completo) e do cadastro da franquia (a não ser que esteja chegando numa nota). O histórico
> continua. **Chegou nota** com ele (quantidade > 0): volta sozinho (`_reativar_comprados`, em
> `salvar_nota_fiscal_completa` e ao completar nota). Criar produto com o nome de um inativo oferece reativar.

**Montagem (`criar_aba_catalogo_produtos` `:821`).**
- Formulário (LabelFrame "Modo: NOVO CADASTRO"):
  - nome;
  - unidade (**texto livre**);
  - categoria (combo readonly) + botão ⚙️ (gestor de categorias);
  - estoque mínimo (`"0.0"`);
  - custo (`"0.00"`) + rótulo explicando a origem do custo;
  - botões Salvar / Limpar / Excluir (Excluir começa desabilitado).
- Lista:
  - filtros: texto (`KeyRelease`), categoria e "situação" (`FILTROS_CATALOGO`, atributo de classe `:1481`);
  - botões: Editar selecionados, Sugerir nomes limpos, Juntar duplicados, Gráfico, Vínculos;
  - `tree_produtos` (seleção múltipla) com 10 colunas: ID, Nome, Unidade, Categoria, Estoque Mínimo,
    Custo atual, Última compra, Mais barato (12m), Última contagem, Situação;
  - cabeçalhos → `ordenar_coluna_treeview`;
  - seleção → `selecionar_produto_para_edicao`;
  - duplo-clique → **gráfico** (⚠ o texto do quadro ainda diz "Duplo-clique para ver vínculos").
- Padrão que se repete no arquivo todo: cada janela grava `self._janela_xxx = {widgets e funções
  internas}`. São **ganchos para os testes automáticos**; a tela não os usa.
- Outro padrão: as janelas são *closures* (funções internas), e o estado delas fica em variáveis
  locais ou num dict `estado`.

**Funções da aba:**

- **`_carregar_cache_catalogo` `:1490`.** Lê
  - `self._cache_produtos = database.listar_produtos_estoque()`;
  - `self._cache_resumo_catalogo = database.resumo_catalogo()`, que devolve
    `{ProdutoID: {CustoAtual, OrigemCusto, TemNota, UltimaCompra, FornecedorUltimo,
    MaisBaratoFornecedor, MaisBaratoCusto, QtdFornecedores, UltContagemData, UltContagemQtd}}`.

- **`situacao_produto(p, r)` `:1498`.** Devolve uma lista de códigos:
  - `sem_custo` (sem custo ou ≤ 0) **ou** `custo_manual` (custo > 0 sem nota);
  - `nunca_comprado` **ou** `sem_compra_90` (última compra há mais de 90 dias, por `date.today()`);
  - `minimo_zero`.

- **`atualizar_lista_produtos(event=None)` `:1516`.**
  - `event=None` (chamada do programa) ou cache vazio → relê o banco. Com `event` (tecla ou filtro)
    usa só o cache.
  - Guarda a seleção e limpa a árvore.
  - Filtra por categoria, palavras sem acento em "nome + ID" e situação.
  - "Mais barato": mostra o mais barato se `QtdFornecedores > 1`; senão o último fornecedor.
  - Zebra própria e restaura a seleção (o que dispara `<<TreeviewSelect>>`).
  - Erros só vão para o log: **a lista pode ficar vazia sem aviso**.

- **`selecionar_produto_para_edicao` `:1570`.**
  - Mais de um selecionado → formulário vazio e "N PRODUTOS SELECIONADOS".
  - Um selecionado: se já é o produto carregado (`_form_produto_id`), não recarrega (preserva o que
    está sendo digitado).
  - ⚠ Lê nome, unidade, categoria e mínimo **do texto da linha da árvore**. O estoque mínimo chega
    formatado (`"0.000"`) e não é relido do banco.
  - Custo:
    - se `TemNota` e `CustoAtual > 0` → campo **somente leitura** com o custo do Valor do Estoque
      (média de 90 dias + royalties) e a `OrigemCusto`;
    - senão → `database.buscar_ultimo_custo_por_produto(id)` em campo **editável**. Esse é o "custo
      manual", que cobre o produto sem nota ou que só veio de bonificação.
  - Grava `_form_produto_id`, `produto_tem_nota` e `custo_carregado_texto`. ⚠ Esses atributos são
    criados **fora do `__init__`**.

- **`salvar_produto` `:1419`.**
  - Nome e unidade são obrigatórios; a unidade vai para maiúsculas.
  - Mínimo: `para_decimal`, vazio vira 0. Custo: `para_decimal`, vazio vira 0.
  - **Editando:** `database.atualizar_produto_estoque(id, nome, un, min, cat)`. Se não tem nota, o
    custo foi preenchido e mudou (`_custo_mudou` `:1473`), chama também
    `database.atualizar_custo_manual_produto(id, custo)`, que grava a **nota fantasma** (ver 2.15-M).
  - **Novo:** `database.criar_produto_manual_com_custo(nome, un, min, cat, custo)`. Se o custo é > 0,
    cria fornecedor interno, vínculo e nota fantasma.
  - Depois limpa o formulário e recarrega a lista e o combo do mestre.
  - ⚠ Não verifica nome duplicado.

- **`limpar_formulario_produto` `:1239`.** Zera os campos, volta a categoria para "Geral", custo
  editável `"0.00"`, `produto_selecionado_id=None`, Excluir desabilitado.

- **`excluir_produto_selecionado` `:1642`.**
  - `database.excluir_produto_estoque(id)`.
  - `ProdutoComHistorico` (subclasse de `ValueError`) mostra a mensagem do banco.

- **`abrir_edicao_em_massa` `:962`.**
  - Checkboxes de categoria, unidade e mínimo (a caixa se marca sozinha quando se digita).
  - Campo vazio não grava 0. Mudar a unidade pede confirmação (alerta sobre o Qtd/Cx).
  - Chama `database.atualizar_produtos_em_massa(ids, categoria, unidade, estoque_min)` → `(ok, msg)`.

- **`abrir_sugestao_nomes` `:1028`.**
  - Base: os selecionados ou, se não houver, os **visíveis** (`_cache_produtos` + filtros).
  - `sugerir_nome_limpo` em cada um.
  - Duplo-clique na coluna "Sugerido" edita; nas outras, alterna o ✔.
  - Aplicar chama `database.renomear_produtos([(id, nome)])` → `(n, erros)`; o banco recusa nomes
    repetidos.

- **`abrir_juntar_produtos` `:1118`.**
  - Com 2+ selecionados forma um grupo manual (manter = menor ID).
  - Senão usa `database.listar_produtos_duplicados()` (mesmo nome normalizado ou mesmo EAN).
  - Duplo-clique define o "MANTER". Unidades diferentes geram um aviso.
  - Chama `database.juntar_produtos(manter, outros)`.
  - `_atualizar_buffet_apos_juntar` `:1219` troca os IDs no **arquivo** `config_sabores_buffet.json`.

- **`abrir_gestor_categorias` `:1272`.** Janela modal (`grab_set`):
  - Nova: `criar_categoria_produto`.
  - Renomear: `atualizar_categoria_produto`, que renomeia **em todos os produtos**.
  - Excluir: `excluir_categoria_produto`, bloqueado se algum produto usa.
  - **% de custo adicional (royalties):** `custos_adicionais_categorias()` e
    `definir_custo_adicional_categoria(nome, texto)`. A conversão do texto é feita no banco.
  - Cada ação recarrega os combos.

- **Gráfico (`abrir_grafico_produto` `:1695`).**
  - `matplotlib` é importado na hora; se faltar, mostra mensagem amigável.
  - Combo de 6, 12 ou 24 meses.
  - Usa `database.historico_grafico_produto(id, meses)` (2.15-G) e desenha 3 gráficos:
    1. preço pago por fornecedor, **sem bonificação** (6 cores fixas);
    2. contagens + linha do estoque mínimo;
    3. barras de comprado × consumido por mês.
  - Resumo em texto: último preço, menor preço, variação, consumo médio mensal e total comprado.

- **Vínculos do produto.** `_abrir_vinculos` `:1689` abre `abrir_gestor_vinculos(produto_id, ...)`
  (2.12). Só cai na versão antiga `_popup_vinculos_antigo` `:1816` se o banco não tiver
  `listar_vinculos_com_resumo`, o que nunca acontece (**código morto**).

### 2.5 Aba 2 — Fornecedores (`:1946–2056`)

- **Tela:** nome, CNPJ, Salvar/Limpar, árvore zebrada (ID / Nome / CNPJ) e Excluir.
- **`salvar_fornecedor` `:1993`.**
  - O CNPJ é limpo por `so_digitos` e precisa ter 11 ou 14 dígitos (**sem conferir o dígito
    verificador**).
  - Chama `database.atualizar_fornecedor(id, cnpj, nome)` ou `database.criar_fornecedor(cnpj, nome)`.
    ⚠ A ordem é *cnpj, nome*.
  - Qualquer exceção (ex.: CNPJ repetido) vira uma mensagem genérica.
- **`selecionar_fornecedor_para_edicao` `:2029`.** Lê os valores **da linha** da árvore.
- **`excluir_fornecedor_selecionado` `:2041`.** `database.excluir_fornecedor(id)`; o erro de chave
  estrangeira (fornecedor com notas) vira mensagem.
- **O que não existe:**
  - busca;
  - campo de prazo de entrega (o prazo da Sugestão é um só para todos);
  - proteção do fornecedor interno `00000000000000`, que aparece na lista e pode ser editado.

### 2.6 Aba 3 — Importar XMLs (DE/PARA) (`:2061–3480`)

#### 2.6.1 Tela (`criar_aba_importacao_xml` `:2061`)
- **Botões:**
  1. "1. Selecionar Pasta";
  2. 🔄 Reprocessar;
  3. "Notas baixadas da SEFAZ";
  4. "Buscar na SEFAZ agora";
  5. 🧾 Recalcular custos de notas já salvas;
  6. 🧮 Ajustar notas antigas (sem XML);
  7. placar `lbl_resumo_importacao`.
- **`tree_vincular` (pendentes):** Fornecedor / Produto no XML / EAN / Qtd / Custo unit. / Custo total.
  A seleção chama `sugerir_mestre_por_ean`.
- **Ferramenta de vínculo:**
  - filtro (filtra o **combo**, não a lista);
  - combo do mestre (`"Nome (ID: n)"`);
  - Qtd/Cx (`"1"`);
  - EAN;
  - categoria para "Criar e Vincular";
  - botões Vincular e Criar e Vincular.
- **`tree_prontos`:** NF / Fornecedor / Produto Mestre / Qtd / Custo unit. / Custo total.
- **Botões finais:** "4. Salvar Todas…" (desabilitado até haver nota pronta) e "🛠️ Gerenciar /
  Corrigir Vínculos Salvos".

#### 2.6.2 Fluxo completo de uma nota (do arquivo ao banco)

```
 XML (pasta escolhida, ou notas_xml_sefaz/ baixada pelo agendador)
   │  processar_arquivos_xml (:2901) ─ arquivo por arquivo, com try próprio
   ├─ nota_xml.ler_xml_nota_fiscal → (cab, itens)  [custo do item já com ST/FCP/IPI/frete/seg/outras − desc]
   ├─ sem CNPJ ou sem itens → falha (contada)       │ Finalidade 4 (devolução) → ignorada
   ├─ por item: tipo_item_por_cfop → 'ignorar' (comodato/remessa: soma em valor_fora, sai)
   │                                → 'bonificacao' (910/911: soma em valor_fora, custo = 0)
   ├─ conferência do APP (recebimento): database.conferencias_recebimento → nota_xml.aplicar_conferencia
   │      (quantidade = a que CHEGOU; item que não chegou sai; nada chegou → nota ignorada)
   ├─ cab['ValorForaDoEstoque'] = valor_fora
   ├─ dedup na sessão por ChaveAcesso ou "cnpj-série-número" (.xml e .txt da mesma nota)
   ├─ fornecedor por CNPJ → não existe? database.criar_fornecedor  ⚠ GRAVA no banco durante a leitura
   ├─ database.verificar_nota_fiscal_existente → já importada? pula
   └─ por item: database.buscar_vinculo_inteligente(forn, desc, cProd, EAN)
          achou → qtd = nota_xml.qtd_estoque(item, fator) (= qtd×fator) ; custo = custo/fator
                  → item "pronto" (NomeMestre por busca reversa no mapa do combo)
          não achou → "pendente" (uma linha por descrição+fornecedor, mesmo que apareça em várias notas)
 Usuário vincula pendentes (Vincular / Criar e Vincular) → database.criar_vinculo_produto_fornecedor
 "4. Salvar Todas" → relê a pasta se ainda houver pendentes → database.salvar_nota_fiscal_completa
   → NotasFiscaisEntrada + ItensNotaFiscalEntrada (+ NCM no vínculo/produto)  → XML copiado p/ importadas/
   → alerta de aumento de preço (database.aumentos_de_preco)
```

#### 2.6.3 Funções, uma a uma

- **`_pendente_da_linha(iid, valores)` `:2156`.** O iid `pend_<uid>` encontra o pendente pelo `_uid`.
  Se não achar, procura por (descrição, fornecedor), o que fica ambíguo entre filiais.

- **`sugerir_mestre_por_ean` `:2170`.**
  - Usa o **foco** (não a seleção).
  - Ao trocar de item, limpa EAN e Qtd/Cx.
  - `database.descobrir_produto_mestre_por_ean(ean)` → `(nome, id)`; se o produto estiver no combo,
    seleciona `"nome (ID: id)"`.

- **`popular_combobox_produtos_mestre` `:2214`.** Lê `listar_produtos_estoque()` (a 2ª leitura igual
  à do catálogo) e monta:
  - `mapa_produtos_mestre {"Nome (ID: n)": id}`;
  - `lista_mestre_produtos_nomes`;
  - `_unidade_por_id`;
  - `mapa_produtos_mestre_contagem` (nome simples, ou "nome (ID: n)" se o nome se repete);
  - `lista_mestre_contagem_nomes`;
  - `embalagens_contagem`, via `getattr(database, 'embalagens_por_produto')`.

  ⚠ **Reatribui** as listas em vez de alterá-las. Quem guardou a referência antiga (ex.: o combo de
  uma janela aberta) continua com a lista velha.

- **`filtrar_combo_importacao` `:2264`.** Busca por substring **com acento** (diferente das outras
  buscas) e **seleciona sozinha o 1º resultado**.

- **SEFAZ: `carregar_notas_sefaz(buscar)` `:2281`.**
  - Com `buscar=True`:
    1. `nd.configurado()`;
    2. uma *thread* daemon roda `nd.buscar_notas()`;
    3. `root.after(300)` verifica até a thread terminar;
    4. mostra `nd.texto_resumo` e reabre a lista.
  - Com `buscar=False`:
    1. lista `nd.pasta_xml()/*.xml` (o nome do arquivo é a **chave de acesso**);
    2. `database.chaves_ja_importadas(chaves)` move as já importadas para `importadas/`;
    3. se não sobrou nenhuma, mostra o estado (`nd.ler_estado()`);
    4. senão abre a lista.

- **`abrir_lista_notas_sefaz` `:2362`.**
  - Lê **cada** XML.
  - `database.notas_ja_lancadas([(chave, cnpj, número, série)])` acha as notas lançadas antes, sem
    chave gravada, e as arquiva.
  - Conta os itens sem vínculo com `buscar_vinculo_inteligente` (cache local).
  - Mostra a conferência do app (`conferencias_recebimento`).
  - Abrir grava `self.filtro_arquivos_xml` e chama `_carregar_pasta_xml`.
  - "Tirar da lista" arquiva o XML **sem lançar**.

- **`abrir_seletor_pasta_xml` `:2499` / `reprocessar_pasta_xml` `:2506`.**
  - O seletor zera o filtro.
  - ⚠ O reprocessar **mantém** o `filtro_arquivos_xml` atual.

- **`montar_recalculo_custos(pasta)` `:2513`.** Não grava nada.
  1. Para cada XML (pula devolução), acha a nota salva (`buscar_nota_importada`) e lê os itens
     gravados (`itens_nota_para_recalculo`).
  2. Para cada item do XML (pula "ignorar"):
     - acha o vínculo;
     - `total_xml` = 0 se bonificação, senão preço × quantidade;
     - casa com o item gravado **do mesmo vínculo e quantidade mais próxima**;
     - custo novo = `total_xml / quantidade gravada`.
  3. Devolve as alterações e os contadores (não importadas, sem vínculo, falhas).

- **`recalcular_custos_notas_salvas` `:2571`.** Mostra a prévia e, ao aplicar, chama
  `database.atualizar_custos_itens([(ItemNotaID, custo)])` numa transação. As contagens com valor
  fechado não mudam (é um retrato).

- **`abrir_ajuste_por_valor_da_nota` `:2639`.**
  - Usa `database.listar_notas_com_diferenca()` (valor da nota > soma dos itens).
  - `LIMITE_ALERTA = 40%` fixo. Notas acima do limite, ou com bonificação importadas antes, ficam
    laranja e não entram no "Marcar todas".
  - A seleção mostra `previa_rateio_nota`.
  - Aplicar chama `ratear_diferenca_nas_notas(ids)`.

- **`atualizar_resumo_importacao` `:2834`.** Placar de pendentes, prontos e notas completas. ⚠ Libera
  o Salvar se **alguma** nota tem item vinculado, mesmo incompleta.

- **`_apos_vincular` `:2856`.** Seleciona o próximo pendente; quando acabam, relê a pasta sozinho.

- **`_carregar_pasta_xml` `:2879`.** Zera as árvores e o estado (`itens_xml_nao_vinculados`,
  `dados_notas_processadas`) e chama `processar_arquivos_xml`.

- **`processar_arquivos_xml` `:2901`.** É o fluxo de 2.6.2.
  - O estado intermediário fica em atributos da instância. `_seq_pendente` é criado sob demanda.
  - Só registra a nota depois de ler o arquivo inteiro (evita meia nota).
  - No fim mostra um resumo: pendentes, NFs, completas, repetidas, já importadas, ignoradas,
    comodato, bonificação, rateio, conferidas, reconhecidas por código.
  - ⚠ Dívida: ~240 linhas misturando arquivo, regra fiscal, cadastro automático de fornecedor,
    consultas N+1, conversão de unidade e montagem da tela.

- **`vincular_produto_selecionado` `:3171`.**
  1. Valida o produto e o Qtd/Cx (> 0).
  2. `conferir_fator_com_custo_anterior` `:3239`: compara `CustoXML/fator` com o último custo pago
     (`ultimo_custo_real_produto`; se não existir, `buscar_ultimo_custo_por_produto`). A faixa aceita
     é **0,34× a 3×** (fixa); fora dela pergunta e sugere um fator.
  3. `database.criar_vinculo_produto_fornecedor(...)`.
  4. Remove o pendente da lista e chama `_apos_vincular`.

  ⚠ A nota em `dados_notas_processadas` **não é atualizada**: o item continua pendente nela até a
  pasta ser relida.

- **`criar_mestre_e_vincular` `:3398`.**
  - O nome do produto novo é a `DescricaoXML` **crua** (não passa por `sugerir_nome_limpo`).
  - `buscar_produto_mestre_por_nome` faz busca exata.
  - Se não existe, `criar_produto_estoque(..., unidade="UN", estoque_min=0, categoria=combo)`.
    ⚠ A unidade é **sempre "UN"**, mesmo para KG.
  - Depois cria o vínculo.

- **`salvar_notas_processadas` `:3272`.**
  1. Se há pendentes, relê a pasta em silêncio (seleção e rolagem se perdem).
  2. Separa as notas completas das incompletas e pergunta sobre as incompletas. ⚠ Os itens pendentes
     de uma nota salva incompleta **ficam de fora para sempre**: a nota passa a contar como
     importada.
  3. Para cada nota:
     - `database.salvar_nota_fiscal_completa(cab, itens)`;
     - o banco **escreve `cab['NotaID']` no dict** da tela;
     - `_guardar_xml_para_conferencia` `:3142` copia o XML para `importadas/<chave>.xml`, usando a
       função privada `nd._ja_temos_xml`, para o app de compras conseguir conferir depois.
  4. ⚠ Duplicidade é reconhecida pelo **texto** "já foi importada" da mensagem.
  5. No fim: `avisar_aumentos_de_preco(notas_salvas)` `:3378`, com `database.aumentos_de_preco`,
     `texto_aumento_preco` e `LIMITE_AUMENTO_PRECO_PCT`; mostra até 15 linhas.

### 2.7 Aba 4 — Lançar Contagem Física (`:3481–4910`)

> **Atualização 10/2026 — contagem com valor** (os números de linha abaixo são de antes dela):
> - **Custo un. e Total** em cada item e o **Total da contagem** embaixo; a prévia mostra
>   `= 36 UN × R$ 6,90 = R$ 248,40`. É o mesmo custo real do 💰 Valor do Estoque **na data da contagem**
>   (`database.referencias_contagem(data)` → `_custos_por_produto`; a conta é `valor_item_estoque`, a mesma
>   do `calcular_valor_estoque`).
> - **Antes e Diferença**: última contagem ANTES da data (contagens do mesmo dia somadas) e o que entrou
>   por nota desde então. `avaliar_diferenca_contagem`: ⚠ quando contou mais do que tinha + comprou
>   (+10%) ou menos de 1/10 disso. A linha cinza embaixo da busca mostra a última contagem, as compras e o custo.
> - **Leitor de código de barras**: 8–14 dígitos + Enter na busca (ou na quantidade, por engano) procura
>   em `codigos_barras_produtos()` (CompraCodigos do app + EAN/EANUnidade dos vínculos). Código da CAIXA já
>   escolhe "CX de N".
> - **📋 Contar por lista**: rotina do app (`rotinas_para_contar`/`produtos_da_rotina`, na ordem dos
>   locais), categoria(s) ou uma contagem anterior. A fila (`fila_contagem`) aparece em cinza no fim da
>   lista; Enter grava e vai para o próximo, ↓ pula, ↑ volta. O rascunho guarda a fila.
> - **✅ Conferir e Salvar**: janela com o valor por categoria e os pontos para conferir (já contado na
>   data, diferença grande, sem custo, custo suspeito, ficou sem contar da lista, comprado por nota e não
>   contado das mesmas categorias). Duplo clique leva até o produto. Substitui a pergunta "Salvar?".

**Tela (`criar_aba_contagem_estoque` `:3481`).**
- **Esquerda (lançamento):**
  - busca com ↑/↓/Enter;
  - combo do produto;
  - quantidade (Enter adiciona; Esc volta para a busca; prévia a cada tecla);
  - combo "Contado em" (embalagem) e prévia da conversão;
  - ⚠ `lbl_contagem_unidade` é criado "por compatibilidade" mas **não está no grid** (é invisível);
  - `tree_contagem_atual` (iid = ProdutoID; duplo-clique edita);
  - data (`DateEntry` pt_BR), nome ("Geral") e Salvar.
  - `self.id_funcionario_contagem = getattr(config, 'ID_GESTOR_PADRAO', 2)` (`:3558`): **toda
    contagem do PC é gravada nesse funcionário**, e o padrão fixo no código é o ID 2.
- **Direita (histórico):**
  - `tree_hist_contagens` (ID / Data / Nome / Responsável / Valor fechado 🔒) e itens da contagem;
  - botões Resolver Avulsos, Editar Contagem, Consolidar Selecionadas e 💰 Valor do Estoque.

**Lançamento:**

- **`filtrar_combo_contagem` `:3605`** usa `buscar_nomes` e seleciona sozinha o 1º resultado.
  `contagem_navegar_resultados` `:3629` é circular; `contagem_enter_na_busca` `:3643` foca a
  quantidade.

- **`_preencher_embalagens_contagem` `:3671`.** Monta as opções:
  - `"{UN} (unidade do estoque)" → 1`;
  - as caixas conhecidas (`embalagens_por_produto`, fatores > 1);
  - as caixas digitadas na sessão (`_embalagens_extras`, **só em memória**);
  - `TEXTO_OUTRA_EMBALAGEM` (`:3665`).

  O fator escolhido da última vez vem de `estoque_preferencias.json['embalagem_contagem'][id]`,
  **lido do disco a cada troca de produto**.

- **`ao_escolher_embalagem_contagem` `:3702`.** "Outra embalagem" pede o fator (> 1).

- **`atualizar_previa_contagem` `:3722`.** Mostra `calcular_qtd_contagem` em tempo real.

- **`_lembrar_embalagem_contagem` `:3746`.** Lê, altera e grava **o arquivo de preferências inteiro**
  a cada item contado em caixa.

- **`adicionar_item_contagem` `:3799`.**
  1. O produto precisa estar no mapa.
  2. Calcula com `calcular_qtd_contagem`.
  3. `sugerir_unidade_contagem` pode perguntar "Você contou em caixa?" (Sim / Não / Cancelar).
  4. Lembra a embalagem.
  5. Se o produto já está na lista: **SOMAR / SUBSTITUIR** / cancelar.
  6. O item fica `{'ProdutoID', 'NomeProduto' (texto do combo), 'QuantidadeContada' Decimal,
     'Unidade', 'Detalhe'}`.
  7. Grava o **rascunho a cada item**.

- **`editar_item_contagem` `:3891`.** Recalcula com fator 1 (sempre em unidades) e **perde o detalhe**
  de caixas.

- **`remover_item_contagem` `:3914`.** Remove e atualiza o rascunho.

- **`salvar_contagem_completa` `:3931`.**
  1. Data `YYYY-MM-DD`.
  2. `database.contagens_do_dia_por_produto(data, ids)`: se o produto já foi contado no mesmo dia,
     avisa que vai **dobrar**, porque contagens do mesmo dia são **somadas** pela Sugestão.
  3. `database.salvar_contagem_estoque(data, funcionário, itens, nome)`.
  4. Se deu certo: limpa a tela, apaga o rascunho, zera `_ultimas_contagens` e recarrega o histórico.

- **Rascunho `:3994–4077`.**
  - **Arquivo** `rascunho_contagem.json` (`salvo_em`, data, nome, itens). Gravação atômica: `.tmp`
    seguido de `os.replace`.
  - `verificar_rascunho_contagem` (400 ms depois de abrir) oferece continuar. Se a resposta for não,
    o arquivo vai para `backups_estoque/rascunho_descartado_<ts>.json`.
  - ⚠ O rascunho é **deste computador** e **não confere** se os ProdutoID ainda existem.

**Histórico, edição, avulsos, consolidação:**

- **`atualizar_lista_contagens_historico` `:4078`.** Usa `listar_contagens_cabecalho()` +
  `listar_valores_estoque_fechados()`, **todas** as contagens, sem paginação. Preenche
  `mapa_contagens_historico`, que **ninguém lê**.

- **`carregar_itens_contagem_historico` `:4111`.** Pelo foco, chama `buscar_itens_contagem(id)`.

- **`contagem_bloqueada(id, ação, janela)` `:4315`.** Usa
  `listar_valores_estoque_fechados(levantar_erro=True)`; se der `TypeError`, chama sem o parâmetro
  (compatibilidade com uma versão antiga). **Se o banco falhar, bloqueia** (fail-closed).

- **`abrir_edicao_contagem` `:4346`.**
  - Verifica o bloqueio ao abrir.
  - Adicionar um produto já presente: SOMAR (`adicionar_item_contagem_existente`) ou SUBSTITUIR
    (`atualizar_qtd_item_contagem`).
  - Duplo-clique num item: Salvar quantidade ou Remover (`remover_item_contagem`).
  - ⚠ **Não confere o bloqueio de novo ao gravar.** Se o valor foi fechado em outro PC com a janela
    já aberta, a edição passa.

- **`abrir_gerenciador_avulsos` `:4126`.** "Avulso" é um item bipado no app **sem produto**
  (`NomeAvulso`/`EANAvulso`).
  - Usa `listar_itens_avulsos_pendentes()` e agrupa por (contagem, nome).
  - Duplo-clique verifica o bloqueio e abre duas opções:
    - **A) Produto normal:** escolhe o produto e a quantidade e marca ou não "aprender o EAN".
      Chama `vincular_item_avulso_inteligente`.
    - **B) Desmembrar caixa:** acha o vínculo da caixa (`buscar_produtos_mobile_por_nome`), pede o
      fator da caixa, a quantidade e o EAN, mostra `previa_desmembrar_caixa` e chama
      `resolver_avulso_fracionando_caixa`. ⚠ **Efeito em cascata no histórico inteiro do produto**
      (2.15-L).
  - ⚠ As quantidades vêm do texto da árvore (3 casas) e são relidas com `para_decimal`.

- **`consolidar_contagens_selecionadas` `:4492`.**
  - Precisa de 2+ contagens. Verifica o bloqueio de cada uma.
  - A data é a **maior** (lida do texto `dd/mm/aaaa` da árvore), com aviso se as datas forem
    diferentes. O nome é perguntado.
  - Chama `database.consolidar_contagens(...)`, que **apaga as originais** numa transação.

- **`exportar_folha_contagem_manual` `:4847`.**
  - Usa `buscar_produtos_para_folha_contagem()`.
  - Colunas: Categoria, ID, Nome, UN, Custo (c/ imposto), até 3 "Caixa de", e campos ____ para
    preencher.
  - Grava em Excel com pandas + openpyxl.

### 2.8 Valor do Estoque (`abrir_relatorio_valoracao` `:4548`)

- **Origem:** foco no histórico da aba 4. Janela de 1050×720 com `estado{'dados'}`.

- **`recarregar()`.** Chama `database.calcular_valor_estoque(contagem_id)` (regra completa em
  2.15-J) e preenche:
  - os itens;
  - as categorias com %;
  - o total;
  - os avisos (`nao_contados`, `avulsos`, `sem_custo`, `custo_suspeito`).

  Se a contagem estiver **fechada**, esconde os avisos e troca o botão Fechar por Reabrir
  (`pack`/`pack_forget`). Os botões são definidos *depois* da função interna; funciona porque a
  closure resolve os nomes na hora de rodar.

- **`resolver_aviso` (duplo-clique num aviso):**

  | Aviso | O que faz |
  |---|---|
  | Não contado | Pergunta a quantidade e chama `adicionar_item_contagem_existente` |
  | Sem custo | Pergunta o custo e chama `atualizar_custo_manual_produto` |
  | Avulso | Abre o gerenciador de avulsos (não recarrega sozinho) |
  | Custo suspeito | Abre `abrir_gestor_vinculos(produto, ao_salvar=recarregar)` |

  Não verifica o bloqueio, mas os avisos só aparecem com a contagem aberta.

- **Botões:**
  - **Fechar:** lista os avisos e confirma; chama `database.fechar_valor_estoque(id)`, que grava um
    **retrato**.
  - **Reabrir:** `reabrir_valor_estoque`.
  - **Copiar total:** área de transferência no formato `1234,56`.
  - **Exportar:** pandas com abas Resumo, Itens (+ TOTAL) e Avisos.

### 2.9 Aba 5 — Sugestão de Compra (`:4911–5751`)

**Atributos de classe.**
- `OPCAO_A_AUTOMATICO`, `OPCAO_A_PRIMEIRA_COMPRA`, `OPCAO_A_HISTORICO` (`:4911–4913`): **textos** das
  opções do combo Ponto A.
- `MOSTRAR_SUGESTAO`: ativos, comprar, conferir, nunca contados recentes, parados, todos.

**Tela (`criar_aba_sugestao_compra` `:4923`).**
- Preferências salvas: `estoque_preferencias.json['sugestao']` = {janela, cobertura, prazo, mostrar,
  modo_a}.
- Ponto B: `combo_contagem_fim`.
- Ponto A: `combo_contagem_inicio` + "últimos N dias" (14–365, padrão 90, só no automático).
- Dias a cobrir (1–365, padrão 30) e prazo de entrega (0–60, padrão 2). ⚠ O prazo é **um só para
  todos os fornecedores**.
- Botão Gerar.
- Filtros que não vão ao banco: busca, "Mostrar", categoria, fornecedor.
- Botões: Buffet, Exportar Excel, Montar Pedido.
- `tree_sugestao` (colunas = tupla `colunas` de `calcular_linha_sugestao`; cores: crítico, comprar,
  ok, conferir, nunca, sem giro) e quadro "Como calculei".
- Mudar os campos numéricos chama `recalcular_sugestao_na_tela` (**sem ir ao banco**).

**`popular_combos_contagem_sugestao` `:5419`** (roda toda vez que se entra na aba 5).
- Monta `mapa_contagens_sugestao` com os valores do Ponto A:

  | Opção do combo (texto) | Valor passado ao banco |
  |---|---|
  | AUTOMÁTICO | `None` |
  | DESDE A PRIMEIRA COMPRA | `-2` |
  | TODO O HISTÓRICO | `-1` |
  | `"ID: n - dd/mm/aaaa - nome (resp)"` | `n` (ID da contagem) |

  ⚠ São **valores mágicos**.
- Se o Ponto B estava na contagem mais nova, ele **acompanha** quando uma contagem nova é salva. Isso
  depende da **ordem** em que o banco devolve as contagens (data decrescente).
- Combo de fornecedores no formato `"Nome (ID: n)"`.

**`gerar_sugestao_compra` `:5074`.**
1. `id_fim` e `id_ini` vêm do mapa, pelo **texto** dos combos.
2. `database.calcular_sugestao_compra(id_fim, id_ini, janela)` (2.15-K).
3. Salva as preferências e zera `self.__dict__['_cache_ids_forn']`.
4. Chama `recalcular_sugestao_na_tela` `:5100`, que para cada item:
   - roda `calcular_linha_sugestao(item, cobertura, prazo, DataReferencia)` (sempre com
     `preferir='ultimo'`);
   - guarda o resultado em `self.linhas_sugestao[pid]`;
   - guarda o item em `self.cache_relatorio_posicao[pid]` (usado pelo histórico de compras).

**`calcular_linha_sugestao` `:324` — a decisão de compra, passo a passo.**
1. **Fornecedor de referência:**
   - `('fornecedor', id)` → a última compra *daquele* fornecedor, ou então `FornecedorUltimo` (pode
     cair em outro fornecedor);
   - `'barato'` → `FornecedorBarato`, ou então o último;
   - senão `FornecedorUltimo`.

   O `fator` é o Qtd/Cx desse fornecedor (≤ 0 vira 1).
2. **Nunca contado** → situação "❔ NUNCA CONTADO", colunas próprias e `return` antecipado (não há
   sugestão).
3. **Explicação do estoque de hoje:** contado em L, mais o comprado depois, menos o consumo desde L.
   A marca 📏 indica que o produto **não foi contado no Ponto B**.
4. **Explicação do consumo** conforme `MetodoConsumo`:
   - `contagens` (com a variante `InicioPrimeiraCompra`);
   - `compras` (aproximado, porque só há 1 contagem);
   - sem dados (consumo zero).

   `ConsumoNegativo` gera o alerta "A CONTA NÃO FECHA" com as causas prováveis. Nesse caso o banco
   deixa `UsoMedioDiario = 0`.
5. **Necessidade:** `consumo/dia × (prazo + cobertura) + mínimo − estoque_hoje`, e
   `sugestão = max(necessidade, 0)`.
6. **Arredondamento:**
   - fator > 1 → `ceil(sugestão/fator)` caixas e `qtd = caixas × fator`;
   - senão `qtd_para_pedido` (3 casas para unidades fracionadas, senão `ceil`).

   `custo_total = qtd × CustoUnid` (o custo já inclui royalties).
7. **Situação**, nesta ordem de prioridade:

   | Situação | Condição |
   |---|---|
   | CONFERIR | Consumo negativo |
   | SEM GIRO | Consumo ≤ 0 e sugestão ≤ 0 |
   | CRÍTICO | Estoque ≤ mínimo (> 0), ou dias restantes < max(7, prazo) |
   | COMPRAR | Sugestão > 0 |
   | OK | Nenhuma das anteriores |

   `acaba_em` só é preenchido se dura no máximo 3.650 dias. `parado` = sem giro, estoque ≤ 0 e não
   comprado recentemente.
8. **`colunas`:** 10 textos na ordem da árvore.

**Filtros e tela:**
- `_filtro_mostrar_sugestao` `:5126` identifica a opção pelo **prefixo** do texto (os rótulos ganham
  contadores "(n)").
- `_passa_no_mostrar` `:5133` aplica o filtro.
- **`renderizar_sugestao` `:5146`:**
  - categoria;
  - fornecedor, via `database.buscar_ids_produtos_por_fornecedor(fid)`: são os **vínculos**, não as
    compras. O resultado fica em cache em `self.__dict__['_cache_ids_forn']`;
  - texto;
  - ordena por gravidade e nome;
  - `self.dados_sugestao_tela[pid]` = o que está **visível** (é a base do pedido);
  - resumo e avisos.
- `_fornecedor_filtro_sugestao` `:5213` tira o `(ID: n)` do texto com regex.
- `mostrar_calculo_sugestao` `:5219` mostra a explicação da linha em foco.

**Saídas:**
- `exportar_sugestao_excel` `:5228`: as linhas visíveis.
- `montar_pedido_por_fornecedor(preferir)` `:5268`: recalcula com o fornecedor preferido e agrupa por
  **nome** de fornecedor.
- `texto_pedido_whatsapp` `:5298`: usa `config.NOME_EMPRESA`.
- `abrir_pedido_compra` `:5310`: opções filtro / último / mais barato; texto editável; Copiar e Excel
  (`exportar_pedido_excel` `:5383`). `self.ultimo_pedido` **ninguém lê**.

**Buffet (`abrir_gestor_buffet` `:5456`).**
- **Arquivo** `config_sabores_buffet.json`, uma lista de ProdutoIDs. Se não existir na pasta do
  programa, tenta o arquivo antigo na pasta **atual**.
- Dias (90) e **vagas = 36 fixas** no código.
- `database.gerar_ranking_sabores_buffet(dias, ids)` mede o consumo pelas **compras**, não pelas
  contagens.
- Classificação: posição ≤ vagas e UMD > 0 → ⭐ FIXO; senão 🔄 ROTATIVO.
- Seletor manual: Listbox com **todos** os produtos, sem busca.

**Histórico de compras (`abrir_popup_historico_compras` `:5630`).**
- Duplo-clique na sugestão. Exige ter gerado antes (`cache_relatorio_posicao`).
- Usa `database.buscar_historico_compras_produto(pid)` e esconde:
  - as linhas com quantidade ≤ 0;
  - as do fornecedor cujo **nome contém 'PRODUÇÃO INTERNA'** (`:5680`). ⚠ O fornecedor interno é
    reconhecido pelo **nome** aqui e pelo **CNPJ** no banco.
- Editar uma linha relê os valores antigos **do texto da árvore** e chama
  `database.atualizar_item_historico_compra(item, qtd, custo)`. ⚠ É um **2º caminho de correção de
  compra**, diferente do `corrigir_compra` (F-07).

### 2.10 Aba 6 — Administração / Reset (`:5898–6235`)

**Tela.**
- Esquerda: `tree_admin_nfs` (ID, Número, Fornecedor, Data, Valor, Itens) + Excluir notas.
- Direita: `tree_admin_cont` (ID, Data, Nome, Responsável) + Excluir contagens.
- "🔍 Auditoria Completa" (o gestor de vínculos em modo auditoria).
- **Zona de perigo:** um checkbox libera o reset. O estilo `Danger.TButton` é criado aqui e vale
  para o programa inteiro (`ttk.Style` é global).

**`atualizar_lista_nfs_admin` `:5982`.** `listar_notas_fiscais_entrada_completa()`: **todas** as
notas, incluindo as **notas fantasmas** do custo manual.

**`excluir_nfs_selecionadas` `:6008`.**
- Avisa se a nota é do fornecedor "PRODUÇÃO INTERNA" (reconhecido pelo **nome**).
- Confirma e chama `database.excluir_nota_fiscal_entrada(id)` **uma por vez**, sem transação entre
  elas.
- Depois chama `_invalidar_sugestao`.
- ⚠ O que **não** faz:
  - não devolve o XML para a lista da SEFAZ (ele continua em `importadas/`, então a nota não volta
    para ser lançada de novo);
  - não atualiza o catálogo nem as consultas.

**`excluir_contagens_selecionadas` `:6036`.**
- Bloqueia se o banco falhar.
- Avisa que os valores fechados **serão apagados**.
- `database.excluir_contagem_estoque(id)` uma por vez.
- Recarrega admin, histórico e combos, zera `_ultimas_contagens` e invalida a sugestão.

**`resetar_sistema_estoque` `:6080`** (indentada com 12 espaços, estilo diferente do resto do
arquivo):
1. `askyesno`;
2. digitar "DELETAR";
3. `backup_estoque_excel()` `:6173`, que usa `database.exportar_tabelas_estoque()` (uma aba por
   tabela, nomes em `backups_estoque/`). Se o banco não tiver essa função, usa um fallback antigo com
   `listar_*`. Se o backup falhar, pergunta se apaga sem backup;
4. `database.resetar_dados_estoque_completo()`;
5. recarrega tudo;
6. `_limpar_estado_apos_reset` `:6153`: zera sugestão, consultas e formulário e move
   `config_sabores_buffet.json` e o rascunho para `backups_estoque/<ts>_antes_reset_*`.

**`_invalidar_sugestao` `:6138`.** Zera resultado, linhas, cache e árvore.

### 2.11 Aba 7 — Solicitações (Líderes) (`:5752–5897`)

- **Origem:** é a tela "transplantada do `main.py`". As solicitações nascem no **bot do Telegram**
  (`telegram_bot.py` chama `database.criar_solicitacao_interna`), com foto opcional salva no disco
  pelo bot.
- **`carregar_solicitacoes` `:5793`.** `database.listar_solicitacoes_pendentes()` devolve linhas
  lidas por **índice**: `[0]` ID, `[1]` nome, `[2]` tipo, `[3]` categoria, `[4]` descrição, `[5]` qtd,
  `[6]` foto, `[7]` data. Cache em `cache_solicitacoes`.
- **`on_solicitacao_selecionada` `:5817`.** Pelo foco, mostra o texto e habilita o botão da foto.
- **`ver_foto_solicitacao` `:5845`.** Caminho relativo a `PASTA_DO_PROGRAMA`; abre com
  `file_utils.abrir_arquivo`.
- **`_mudar_status_solicitacao` `:5855`.**
  `database.atualizar_status_solicitacao(id, status, motivo, status_esperado='Pendente')`. Se der
  `TypeError`, chama sem o último parâmetro (versão antiga).
- **Aprovar / Recusar** `:5867/:5881`. Recusar exige motivo.
- ⚠ Ninguém avisa o solicitante: nenhum outro código chama `atualizar_status_solicitacao`.

### 2.12 Gestor de Vínculos, Corrigir Compras e Juntar Duplicados (`:6236–7481`)

**Constantes.**
- `FILTROS_PROBLEMA`: todos, qualquer, duplicado, suspeito, custo_errado, sem_ean, sem_compras,
  órfão.
- `PROBLEMAS_GRAVES`.
- `problemas_do_vinculo(v)` `:6252` transforma as flags do banco em chaves.

**`abrir_gestor_vinculos(produto_id, nome_produto, ao_salvar, modo_auditoria)` `:6271`.** É a maior
função do arquivo (~630 linhas).
- **Janela:** quase tela cheia, com `estado` = {`dados` (str(ID) → vínculo), `produto_id`,
  `mestre_novo`, `produtos`, `ids_lista`, `opcoes`, `filtro_problema`}.
- **Topo:**
  - busca (fornecedor, XML, produto, EAN, código, ID);
  - fornecedor;
  - problema (rótulos com contagem);
  - Limpar;
  - Juntar duplicados;
  - "Mostrar todos" quando filtrado por produto.
- **Árvore:** ID, Fornecedor, Descrição no XML, Produto, EAN, Qtd/Cx, Custo/Unid., Custo Emb.,
  Compras, Última compra, Problemas. Cores para órfão, duplicado e suspeito.
- **Editor:**
  - busca do produto + Listbox de resultados ou sugestões;
  - Qtd/Cx, EAN, NCM;
  - botões Salvar / Criar produto novo / Excluir vínculo / ✏️ Corrigir quantidade e preço;
  - prévia.
  - ⚠ `combo_mestre_edit = None` é resto da versão antiga.
- **`carregar_dados`:**
  - `database.listar_vinculos_com_resumo()` (2.15-E);
  - `listar_produtos_estoque()`, a 3ª cópia do catálogo em memória;
  - contagem por problema;
  - no modo auditoria, o filtro inicial é "qualquer problema".
- **`mostrar`:**
  - filtra;
  - o custo mostrado é o da **última compra paga**, ou o texto "bonificação" se só houve bonificação;
  - custo da embalagem = custo × `UltimoFator`;
  - mantém o foco; se sobrar uma linha, seleciona.
- **Escolha do produto:**
  - sugestões: o mesmo EAN em outro vínculo + até 8 produtos por palavras em comum com o nome limpo
    do XML;
  - busca por dígitos: ID exato ou EAN (sufixo, 8+ dígitos);
  - busca por nome: todas as palavras;
  - limite de 200 resultados;
  - escolher só grava em `estado['mestre_novo']`; o banco só muda ao **Salvar**.
- **`criar_produto_novo`:**
  1. Nome sugerido por `sugerir_nome_limpo`; recusa nome igual (sem acento).
  2. `criar_produto_estoque(..., estoque_min=0)` com a mesma unidade e categoria.
  3. `atualizar_vinculo_existente(v.ID, novo_id, fator, recalcular_compras=False, ...)`.

  ⚠ São **duas operações sem transação**: se a 2ª falhar, o produto novo fica órfão (a mensagem
  avisa). As compras vão junto com o vínculo; as **contagens ficam** no produto antigo.
- **`atualizar_previa`:** última compra paga em embalagens e o custo da embalagem com o fator atual e
  com o novo; "normal" (`CustoReferencia`); alertas.
- **`salvar_alteracao`** (Enter nos campos):
  1. Produto obrigatório.
  2. Confirma a troca de produto se o vínculo tem compras.
  3. Fator > 0.
  4. Se o fator mudou e há compras: `previa_recalculo_vinculo(id, fator)` e a pergunta: **SIM**
     recalcula as compras antigas / **NÃO** só as próximas / cancelar.
  5. `atualizar_vinculo_existente(id, produto, fator, recalcular_compras, novo_ean, novo_ncm)`.

  EAN e NCM não são validados.
- **`excluir_vinculo`** (Delete): `vinculo_tem_itens` (via `getattr`). Bloqueia se tem compras ou se
  tem o custo manual; senão confirma e chama `excluir_vinculo_existente`.

**`_item_da_compra_no_xml(v, compra)` `:6899`.**
1. Chave de 44 dígitos → procura `<chave>.xml` em `nd.pasta_xml()` (ou em `config.NFE_PASTA_XML`, ou
   em `notas_xml_sefaz/`) e em `importadas/`.
2. Lê com `nota_xml` e pontua os itens: descrição 4, cProd 2, EAN 1.
3. Desempata pelo tipo (bonificação) e pelo total mais próximo.
4. Aplica a conferência do app.
5. Devolve {Quantidade, QuantidadeNota, Preco, Bonificacao, Conferida}.

**`abrir_compras_do_vinculo(v, janela_pai, ao_mudar)` `:6954`** ("Corrigir quantidade e preço").
- **Árvore:** NF, Data, Embalagens (= Qtd/fator), Qtd/Cx, Preço emb. (= Custo × fator), No estoque,
  Custo/UN, Total do item, Total da nota, Alerta.
- **`fator_de(c)`:** o Qtd/Cx **com que a compra entrou** (`FatorConversaoUsado`), ou o do vínculo.
- **Alertas:** mais cara que a nota inteira / bonificação / fora do normal (× vezes) / fator
  diferente do vínculo.
- **Dados:** `database.listar_compras_do_vinculo(id)`. Seleciona a 1ª compra com problema.
- **Dica automática:**
  - item > nota → preço = (TotalNota − SomaOutrosItens)/embalagens;
  - `Multiplicador` k → qtd × k, custo ÷ k.
- **"Usar valores do XML":** usa `_item_da_compra_no_xml`.
- **Precisão:** os campos não editados guardam o **valor exato** (`estado['exatos']`) para não
  perder precisão com o arredondamento da tela.
- **`atualizar_resultado`:** qtd = emb × f, custo = preço/f, total = emb × preço. Avisa se continua
  fora do normal, usando `database._fora_do_normal` (⚠ uma função **privada** do banco usada pela
  tela).
- **`salvar`:**
  1. `database.corrigir_compra(item, qtd, custo, fator)`.
  2. Se o fator é diferente do vínculo, oferece usá-lo nas **próximas** notas
     (`atualizar_vinculo_existente(..., False)`).
  3. Depois oferece passar as **outras** compras (`previa_recalculo_vinculo` +
     `atualizar_vinculo_existente(..., True)`).
  4. Altera `v['Fator']` no dict **compartilhado** com a janela de vínculos.
- **`aplicar_em_todas`:** usa o mesmo Qtd/Cx em todas as compras.

**`abrir_juntar_duplicados(janela_pai, ao_mudar)` `:7325`.**
- `database.listar_grupos_duplicados()`; duplo-clique define o MANTER.
- `juntar_vinculos(manter, outros)`.
- "Juntar todos com fatores iguais" roda em laço, **sem transação** entre grupos.
- Grupos com fatores diferentes: só aviso (as compras gravadas não mudam).

### 2.13 Aba 8 — Consultas (`:7482–7991`)

**Constantes.** `PERIODOS_CONSULTA` = 90 / 183 / 365 dias / tudo. `_campo_busca_consultas` `:7484`
diz qual campo o Ctrl+F foca.

**Sub-aba Produto.**
- Busca e lista de até 500 produtos.
- `listar_produtos_consulta` `:7684` usa a **lista da aba 4** (`mapa_produtos_mestre_contagem`).
- Cartões: último preço pago, menor, média ponderada, comprado no período.
- Árvore por fornecedor e árvore do histórico (duplo-clique abre a nota).
- **`mostrar_consulta_produto` `:7710`:**
  - `database.historico_compras_detalhado(pid)` (sem notas fantasmas, sem royalties);
  - `database.resumo_precos_por_fornecedor(historico, desde)` (função **pura** guardada no módulo do
    banco).
- `exportar_consulta_produto` `:7959`: Excel com abas Por fornecedor e Histórico.

**Sub-aba Nota.**
- `atualizar_consultas` `:7675` chama `database.listar_notas_para_consulta()`: **todas as notas**, com
  o texto de todos os itens para a busca "que nota tinha X?".
- `listar_notas_consulta` `:7799` filtra em memória (período + palavras).
- `mostrar_itens_nota_consulta` `:7818` usa `database.itens_da_nota(id)`.
- Resumo por categoria: `custos_adicionais_categorias()` + `resumo_categorias_nota(itens, pct)`
  (função pura). Barra de 20 blocos; a coluna "Com royalties" fica escondida se nenhuma categoria tem
  royalties.
- Avisa se `ValorNF` e a soma dos itens diferem em R$ 0,05 ou mais.

**Navegação.** `abrir_nota_na_consulta` `:7920` e `abrir_produto_na_consulta` `:7946` trocam de
sub-aba e selecionam a nota ou o produto.

### 2.14 `ordenar_coluna_treeview` `:7992` e `__main__`

- Ordena pelo **texto exibido** (`chave_ordenacao`), move as linhas e troca o comando do cabeçalho
  para inverter a ordem. ⚠ A zebra fica bagunçada, e na Sugestão a ordem por gravidade só volta na
  próxima renderização.
- `__main__`: `Tk()`, `AppGestaoEstoque(root)`, `mainloop()`. **Nenhum outro módulo importa
  `gestao_estoque_main`.**

### 2.15 `database.py` — camada de dados do Estoque

Valem para todas as funções desta seção:
- **Conexão:** `get_db_connection()` abre **uma conexão nova por função**
  (`pyodbc.connect(CONNECTION_STRING, timeout=10)`) e devolve `None` se falhar. Cada função trata o
  `None` do seu jeito (F-15).
- **Conversões:**
  - `_dec(v)` converte em `Decimal` e devolve **0** para `None` ou para lixo;
  - `_como_data(v)` aceita date, datetime ou `'AAAA-MM-DD'` e devolve `None` se não reconhecer;
  - `_br(v, casas)` formata no padrão brasileiro.
- **Constantes** (`:7689–7693`):
  - `CNPJ_FORNECEDOR_INTERNO = "00000000000000"`;
  - `JANELA_CUSTO_MEDIO_DIAS = 90`;
  - `DIAS_VERIFICACAO_SUSPEITO = 365`;
  - `FATOR_CUSTO_SUSPEITO = 3`;
  - `LIMITE_AUMENTO_PRECO_PCT = 10`;
  - `SUGESTAO_JANELA_PADRAO = 90`, `SUGESTAO_DIAS_MINIMOS = 7`;
  - `TABELAS_BACKUP_ESTOQUE`.

#### A) Infraestrutura e migrações em tempo de execução
- **`verificar_migracao_categorias_estoque()` `:6135`, chamada no import (`:6166`).**
  - Cria `CategoriasProduto (CategoriaID, NomeCategoria UNIQUE)`.
  - Se a tabela estiver vazia, insere 11 categorias padrão (Geral, Sorvetes, Brinquedos, …).
- **`verificar_migracao_custo_adicional()` `:6169`, chamada no import (`:6184`).** Garante a coluna
  `CustoAdicionalPct` em `CategoriasProduto`.
- **`verificar_migracao_itens_avulsos()` `:7260`, chamada no import (`:7280`).**
  - Se não existir `ItensContagemEstoque.NomeAvulso`: `ProdutoID` passa a aceitar NULL e são criados
    `NomeAvulso VARCHAR(255)` e `EANAvulso VARCHAR(50)`.
  - Erros só vão para o log.
- **`_garantir_colunas_estoque()` `:6690`.** Roda uma vez por processo (flag global
  `_colunas_estoque_ok`), com COMMIT próprio:
  - `ItensNotaFiscalEntrada.FatorConversaoUsado DECIMAL(18,4)`, preenchida com o Qtd/Cx **atual** do
    vínculo;
  - `NotasFiscaisEntrada.ValorForaDoEstoque DECIMAL(18,2)`, `Serie VARCHAR(5)`,
    `ChaveAcesso VARCHAR(44)`;
  - `ProdutosEstoque.NCM VARCHAR(10)`, preenchida por `_preencher_ncm_dos_produtos` `:6752` com o NCM
    mais frequente nos vínculos.

  A detecção é feita por `cursor.description` de um `SELECT * … WHERE 1 = 0`. Erro → rollback e
  `raise`.
- **`_garantir_tabelas_valor_estoque(cursor=None)` `:7727`.** O parâmetro é **ignorado**. Usa conexão
  própria e cria `ValorEstoqueFechamento` (PK `ContagemID`) e `ValorEstoqueFechamentoItens`, sem chave
  estrangeira para `ContagensEstoque`. Flag global `_tabelas_valor_ok`.
- **`_tabela_existe(cursor, nome)` `:10496`.** Consulta `sys.tables`.
- ⚠ As **tabelas-base** do estoque (`ProdutosEstoque`, `Fornecedores`, `ProdutosFornecedor`,
  `NotasFiscaisEntrada`, `ItensNotaFiscalEntrada`, `ContagensEstoque`, `ItensContagemEstoque`) **não
  são criadas por nenhum código do repositório**. O schema delas só existe no banco.

#### B) Categorias e royalties (`:6190–6330`)
- **`_fatores_custo_adicional(cursor)`** → `{ProdutoID: 1 + pct/100}`, ligando o produto à categoria
  **pelo nome**. `fatores_custo_adicional()` é a versão com conexão própria.
- **`custos_adicionais_categorias()`** → `{nome: pct}`.
- **`definir_custo_adicional_categoria(nome, texto)`** → `(ok, msg)`:
  - aceita vírgula e `%`;
  - faixa de 0 a 500;
  - **0 grava NULL**;
  - `rowcount = 0` → "não encontrada".
- **`listar_categorias_produto()`** → nomes em ordem. ⚠ Não tem `except`.
- **`criar_categoria_produto(nome)`** → `(ok, msg)`. O nome repetido é detectado pelo **texto** do erro
  de UNIQUE.
- **`atualizar_categoria_produto(antigo, novo)`.** Atualiza `CategoriasProduto` **e**
  `ProdutosEstoque.Categoria` na mesma transação. A categoria do produto é um **texto**, sem chave
  estrangeira.
- **`excluir_categoria_produto(nome)`.** Bloqueia se algum produto usa a categoria.

#### C) Produtos (`:6330–6474`)
- **`criar_produto_estoque(nome, unidade, estoque_min, categoria='Geral')`.**
  - `INSERT` + `SCOPE_IDENTITY()` via `nextset()` → o ID vem como **`Decimal`** (não `int`).
  - Erro → `raise`; sem conexão → `None`.
  - Não verifica nome duplicado.
- **`listar_produtos_estoque()`.** `SELECT * … ORDER BY NomeProduto`. ⚠ Erro → `[]`.
- **`atualizar_produto_estoque(id, nome, un, min, cat)`.** `UPDATE`; erro → `raise`.
- **`excluir_produto_estoque(id)`.**
  - Se o produto tem compras com quantidade > 0 ou contagens → `raise ProdutoComHistorico`.
  - Senão, numa transação, apaga:
    1. os itens dos vínculos (o custo manual);
    2. as notas internas vazias do fornecedor interno;
    3. os vínculos;
    4. as referências no app de compras (`_trocar_produto_no_app_compras(cursor, [id], None)`);
    5. o produto.

#### D) Fornecedores (`:6475–6560`)
- **`criar_fornecedor(cnpj, nome)`.** Não devolve nada: quem chama busca o ID depois com
  `buscar_fornecedor_por_cnpj`. Erro → `raise`.
- **`listar_fornecedores()`**, **`atualizar_fornecedor`**, **`excluir_fornecedor`.** Os dois últimos
  levantam exceção em caso de erro.
- **`buscar_fornecedor_por_cnpj(cnpj)` → ID | `None`.** Compara o texto **exato** gravado.

#### E) Vínculos DE/PARA (`:6560–6690`, `:9345–9900`, `:10582–10660`)

**Reconhecimento e criação.**
- `_ean_valido` (8 a 14 dígitos, não só zeros) e `_codigo_valido`.
- **`buscar_vinculo_inteligente(forn, desc, cProd, EAN)` `:6611`** → `{ProdutoFornecedorID, ProdutoID,
  Fator, Como}` | `None`. Procura sempre dentro do mesmo fornecedor:
  1. **descrição exata**. ⚠ Aqui não exige `ProdutoID` preenchido e usa `fetchone()` sem `ORDER BY`;
  2. **código do fornecedor**;
  3. **EAN**.

  Nos casos 2 e 3, só aceita se todos os vínculos achados apontam para o mesmo produto **e** o mesmo
  fator; nesse caso devolve o mais novo. Erro ou sem conexão → `None` (o item vira "pendente").
- **`criar_vinculo_produto_fornecedor(produto, fornecedor, descricao, cProd, cEAN, NCM, fator=1.0)`
  → id | `None`.** Não verifica duplicidade.
- **`buscar_vinculo_produto_fornecedor`.** Legado.

**Leitura.**
- **`buscar_ids_produtos_por_fornecedor(forn)` `:9345`** → conjunto de ProdutoID **dos vínculos**.
- **`buscar_vinculos_por_produto_mestre(pid)` `:9360`.** Usado só pela tela antiga.
- **`atualizar_vinculo_simples` `:9384`.** Legado; não recalcula compras.
- **`listar_todos_vinculos_detalhado` `:9402`.** Põe textos-sentinela no lugar de NULL.

**`atualizar_vinculo_existente(id, produto, fator, recalcular_compras=False, novo_ean=None,
novo_ncm=None)` `:9433`.**
1. Com `recalcular_compras` e fator novo > 0, para cada item com quantidade > 0:
   - fator antigo = `FatorConversaoUsado`, ou o fator do vínculo;
   - `qtd × novo/antigo` (3 casas);
   - `custo × antigo/novo` (4 casas);
   - grava o fator usado = novo.

   O valor de cada compra se mantém, salvo arredondamento.
2. `UPDATE` de produto e fator.
3. EAN e NCM só mudam se não forem `None`. Uma string vazia **apaga**.
4. Tudo numa transação; erro → `False`.

**`listar_vinculos_com_resumo()` `:9490`.** Carrega **todos** os vínculos e **todas** as compras com
quantidade > 0. Para cada vínculo devolve:
- `ID`, `Fornecedor`, `DescricaoXML`, `ProdutoID`, `NomeMestre`, `Fator`, `EAN`, `Interno`, `NCM`,
  `Codigo`, `FornecedorID`;
- `Orfao`, `SemProduto`;
- `QtdCompras`, `UltimaData`, `UltimaQtd` e `UltimoCustoUnid` (da **última compra paga**),
  `UltimoFator`;
- `SoBonificacao`, `ComprasOutroFator`, `CustoMin`/`CustoMax`;
- `VariacaoPropria` (max ≥ 3 × min);
- `CustoErrado` (`_item_maior_que_nota` `:9655`: item > nota × 1,05 + R$ 1).

Depois calcula:
- a **referência** por produto: **mediana ponderada pela quantidade** das compras pagas de todos os
  vínculos não internos;
- `Suspeito` (variação própria, ou último custo ≥ 3× ou ≤ ⅓ da referência), `CustoReferencia`,
  `ComprasForaDoNormal`, `MotivoSuspeito` (`_motivo_suspeito`);
- os grupos de duplicados (`_agrupar_duplicados`: *union-find* por fornecedor + produto + código ou
  EAN): `Grupo` (renumerado a cada chamada), `Duplicado`, `SemEAN`, `SemCompras`.

⚠ Custos **sem royalties**. Erro → `[]`.

**Funções de apoio:**
- **`_fora_do_normal(custo, ref)` `:9610`:** ≥ 3× ou ≤ ⅓ (usada também pela tela).
- **`sugestao_qtd_cx(custo, ref, tol=12%)`:** devolve o multiplicador k ≥ 2, ou 1/m, ou `None`.
- **`listar_compras_do_vinculo(id)` `:9665`:** compras com quantidade > 0 e todos os campos da janela
  "Corrigir". ⚠ **1 SELECT por item** para somar os outros itens da nota.
- **`_custo_referencia_produto(cursor, pid)` `:9719`:** a mesma mediana ponderada.
- **`listar_grupos_duplicados()` `:9827`:** chama `listar_vinculos_com_resumo()` **inteira**.
  `ManterID` = compra mais recente, depois mais compras, depois maior ID.

**`corrigir_compra(item, qtd, custo, fator)` `:9744`** → `(ok, msg)`.
- Valida qtd > 0, custo ≥ 0, fator > 0. Texto inválido vira 0 por causa do `_dec`, e então cai em
  "precisa ser maior que zero".
- Recusa o item do custo manual (quantidade antiga ≤ 0).
- Grava qtd (3 casas), custo (4 casas) e o fator usado. O valor anterior **só fica no log**.

**`juntar_vinculos(manter, remover)` `:9843`.**
1. Exige o mesmo (fornecedor, produto).
2. O mantido herda EAN, código e NCM dos removidos se não tiver.
3. Congela o `FatorConversaoUsado` dos itens dos removidos.
4. Move os itens e apaga os removidos.

Tudo numa transação. ⚠ Chama `_garantir_colunas_estoque()` (outra conexão) com a transação já
aberta (F-22).

**Prévia e exclusão.**
- **`previa_recalculo_vinculo(id, fator)` `:10582`** → `(fator_vinculo, [{NF, Data, QtdAtual,
  CustoAtual, FatorAntigo, QtdNova, CustoNovo}])`. Pula os itens que já estão no fator novo.
- **`vinculo_tem_itens(id)`** → quantidade de itens, incluindo o custo manual.
- **`excluir_vinculo_existente(id)` `:10635`.** Recusa se há itens. ⚠ Devolve `False` tanto para
  "recusado" quanto para erro.

#### F) Notas fiscais (`:6779–6912`, `:7217–7258`, `:10086–10270`)
- **Identificação da nota:**
  - `_serie_normalizada`: `'001'` vira `'1'`;
  - `_chave_normalizada`: 44 dígitos;
  - **`_nota_ja_salva(cursor, número, fornecedor, série, chave)` `:6793`:**
    1. chave igual → é a mesma nota;
    2. senão, mesmo número e fornecedor, pulando os casos em que **as duas** têm chave (ou série) e
       elas diferem;
    3. uma nota antiga sem série conta como "já importada".
  - `_fator_item(usado, vínculo)` devolve o primeiro > 0, ou 1.
- **`salvar_nota_fiscal_completa(cab, itens)` `:6836`** → `(ok, msg)`:
  1. garante as colunas;
  2. confere a duplicidade e devolve a mensagem "…já foi importada…";
  3. `INSERT` do cabeçalho (`ValorForaDoEstoque`, `Serie`, `ChaveAcesso`) + `SCOPE_IDENTITY`;
  4. `executemany` dos itens (`FatorConversaoUsado = item['FatorUsado']`);
  5. `_guardar_ncm_dos_itens` `:6767`: o NCM sobrescreve o do vínculo e só preenche o do produto se
     estiver vazio;
  6. COMMIT;
  7. **escreve `cab['NotaID']`** no dict de quem chamou.
- **`verificar_nota_fiscal_existente(...)` `:8611`.** ⚠ Em caso de erro ou sem conexão devolve
  **True** ("já existe").
- **`buscar_nota_importada(...)` `:10086`.** Mesma regra, mas em caso de erro devolve **`None`**.
- **`chaves_ja_importadas(chaves)` `:6996`** e **`notas_ja_lancadas(notas)` `:7054`.**
  - A primeira consulta em lotes de 500 (limite de parâmetros do SQL Server).
  - A segunda carrega **todas** as notas e compara pela chave ou pelo (CNPJ só com dígitos, número
    sem zeros), respeitando série e chave diferentes.
- **`conferencias_recebimento(chaves)` `:7017`** → `{chave: {status, por, itens{NItem: qtd}}}`.
  - Lê `RecebimentoNotas`/`RecebimentoItens`, tabelas criadas por `recebimento.py` (aba Receber do
    app).
  - Só considera os status `'conferida'`/`'divergencia'`.
  - ⚠ Se a tabela não existir ou der erro → `{}` (a importação segue com as quantidades da nota).
- **`listar_notas_fiscais_entrada_completa()` `:7217`.** Faz `JOIN` (não LEFT) com Fornecedores;
  inclui as notas fantasmas. Erro → `[]`.
- **`excluir_nota_fiscal_entrada(id)` `:7239`.** Apaga itens e cabeçalho; nada mais.
- **Recalcular com o XML:**
  - `itens_nota_para_recalculo(id)` `:10100`;
  - `atualizar_custos_itens([(item, custo)])` `:10118`: só o custo, numa transação.
- **Ajustar notas antigas sem XML:**
  - `listar_notas_com_diferenca(min=0,05)` `:10144`: compara o valor líquido da nota (`ValorTotalNF −
    ValorForaDoEstoque`) com a soma dos itens; `ImportadaAntes` = `ValorForaDoEstoque IS NULL`;
  - `_itens_rateio` faz o rateio **proporcional ao valor de cada item**. Se a diferença for negativa,
    o fator é 1 (não reduz);
  - `previa_rateio_nota`;
  - `ratear_diferenca_nas_notas(ids)`: uma transação, idempotente.

#### G) Alerta de preço e gráfico (`:6914–7215`)
- **`aumentos_de_preco(nota_ids|desde_nota_id|desde_data, limite_pct)` `:6920`.**
  1. Lê **todos** os itens de **todas** as notas e aplica os royalties.
  2. Descarta o fornecedor interno, custo ≤ 0 e quantidade ≤ 0.
  3. Para cada compra-alvo, compara com a compra paga anterior de **outra** nota do mesmo produto, de
     qualquer fornecedor.
  4. Se o aumento é ≥ limite, guarda um achado por (nota, produto), mantendo o maior %.
  5. Ordena por −%.

  Usada por: a tela (depois de salvar), `alertas_estoque.py` (Telegram diário),
  `compras_database.py`, `recebimento.py`, `compras_cupom.py`.
- **`texto_aumento_preco(a)` `:7114`.** Frase em português. Tem a **sua própria** formatação de
  dinheiro.
- **`historico_grafico_produto(pid, meses, hoje)` `:7142`.**
  - Compras: sem o fornecedor interno, quantidade > 0, com royalties, bonificação marcada.
  - Contagens: as **do mesmo dia são somadas**.
  - Consumo entre contagens consecutivas A → B = `A + compras em (A, B] − B`. Se for negativo é
    descartado; senão é repartido pelos dias e meses (`_somar_por_mes` `:7127`).
  - O início é aproximado com 31 dias por mês.

#### H) Contagens (`:7282–7675`)
- **`salvar_contagem_estoque(data, funcionário, itens, nome)` `:7282`.**
  - `INSERT … OUTPUT INSERTED.ContagemID` + `executemany`.
  - Itens repetidos na lista viram **linhas repetidas**. Também é usada pela API do app.
- **`listar_contagens_cabecalho()` `:7320`.** `LEFT JOIN Funcionarios`, ordem decrescente de data.
  **`buscar_itens_contagem(id)` `:7342`** marca o nome do avulso com `[AVULSO]`.
- **`consolidar_contagens(ids, data, funcionário, nome)` `:7370`** → `(ok, msg, novo_id)`.
  - Recusa se alguma contagem está fechada.
  - Agrupa por produto ou por nome do avulso (maiúsculas e sem espaços nas pontas), somando.
  - Cria a nova contagem e apaga as originais, numa transação.
- **`excluir_contagem_estoque(id)` `:7422`.** Apaga também o valor fechado.
- **`listar_itens_avulsos_pendentes()` `:7446`.** ⚠ Sem `except`.
- **`_resolver_avulso_na_contagem(cursor, cid, nome, pid, qtd)` `:7496`.**
  1. Soma as linhas que já existiam do produto.
  2. Apaga as linhas do produto e do avulso.
  3. Insere **uma** linha com `existente + qtd`. A `qtd` é a digitada pelo gestor, não a do avulso.
- **`vincular_item_avulso_inteligente(..., salvar_permanente)` `:7554`.**
  - `_resolver_avulso_na_contagem`.
  - Se pedido e se o EAN não existe em **nenhum** vínculo, copia o vínculo mais recente do produto
    com a descrição `… (EAN APRENDIDO)` e fator 1. Se o produto não tem nenhum vínculo, **não
    aprende** e não avisa.
- **`contagens_do_dia_por_produto(data, ids, ignorar)` `:7514`.** Lê **todos** os cabeçalhos e
  filtra a data em Python.
- **`atualizar_qtd_item_contagem` `:7606`.** Linhas duplicadas viram uma.
  **`remover_item_contagem` `:7642`** (sem `except`).
- **`adicionar_item_contagem_existente` `:7657`.** ⚠ `+=` em **todas** as linhas duplicadas e sem
  rollback no `except`.
- **`vincular_item_avulso_contagem` `:7465`.** Legado, **não é chamado**.

#### I) Ponte para o app de compras
- **`_trocar_produto_no_app_compras(cursor, remover, manter=None)` `:10501`.** Trata **apenas**
  `CompraRotinaItens` (sem duplicar na mesma rotina) e `CompraCodigos`.
- ⚠ Não trata, embora todas tenham `ProdutoID`:
  - `CompraListaItens` e `CompraContagemLocais` (`compras_database.py`);
  - `CompraOrcamentoItens` (`orcamentos.py`);
  - `CompraCupomItens` (`compras_cupom.py`).
- (As tabelas `Recebimento*` guardam a chave da nota e o código do fornecedor, **não** o produto.)

#### J) Valor do Estoque (`:7677–8064`)
**`_custos_por_produto(cursor, data)` `:7780`** → `(resultado, compras)`.
1. **Compras reais** com `DataEmissao < data + 1 dia`, sem o fornecedor interno e com quantidade > 0,
   × royalties.
2. **Custos manuais**: a nota do fornecedor interno mais recente.
3. Por produto:
   - **suspeito** se, nas compras pagas de 365 dias, max ≥ 3 × min;
   - **custo:**
     - se a janela de 90 dias tem valor > 0 → média ponderada;
     - senão → a **última compra paga** (com textos diferentes conforme o caso de bonificação);
     - senão → o custo manual;
     - se o custo ficou ≤ 0 e há custo manual > 0 → o custo manual;
   - o texto de `origem` recebe "+ N% … (royalties)".

**`calcular_valor_estoque(id)` `:7865`.**
- **Fechada:** devolve o que está gravado, sem avisos.
- **Aberta:**
  - lê o catálogo inteiro;
  - soma os itens por produto e lista os avulsos sem valor;
  - produto excluído aparece como "Produto N (excluído do catálogo)";
  - sem custo → "SEM CUSTO";
  - custo com 4 casas, valor com 2;
  - **não contados** = produtos com quantidade > 0 na contagem **anterior** (a de data menor mais
    recente), ou comprados desde ela (ou nos últimos 60 dias), que não estão nesta contagem.
- Devolve `{contagem, itens, total, por_categoria, avisos, fechado}`.

**Fechamento.**
- **`fechar_valor_estoque(id)`** → `(ok, msg, total)`: recalcula e grava cabeçalho + itens. A PK
  impede fechar duas vezes.
- **`reabrir_valor_estoque(id)`** → `bool`.
- **`listar_valores_estoque_fechados(levantar_erro=False)`:** ⚠ sem a flag, um erro devolve `{}`.
- **`contagem_esta_fechada(id)`:** usa o modo silencioso; **ninguém chama**.
- **`gerar_relatorio_valoracao_contagem` `:8065`:** média das 3 últimas compras; **ninguém chama**.

#### K) Sugestão de compra (`:8090–8530`)
**`calcular_sugestao_compra(fim, inicio=None, janela=90, hoje=None)` `:8314`.**
1. **Validação:** janela ≥ 7. O Ponto B precisa existir. No modo fixo, A precisa existir, ser
   diferente de B e não ser posterior a B.
2. **Modo** pelo valor: `None` auto, `-1` histórico, `-2` primeira compra, ID fixo.
3. **`data_ref`:** `max(hoje, B)` se B é a contagem mais recente, senão B.
4. **Carga em memória:**
   - catálogo inteiro;
   - **todos** os itens de contagem (filtrados em Python até B, somando o mesmo dia e guardando o
     conjunto de IDs);
   - **todas** as compras com quantidade > 0, sem o fornecedor interno (a bonificação entra), × royalties,
     com o `FatorConversao` **atual** do vínculo.
5. **Por produto:**
   - `UltimaCompra`;
   - `FornecedorUltimo` (última paga, senão a última);
   - `FornecedorBarato` (menor custo em 365 dias; empate fica com o mais recente);
   - `PorFornecedor`;
   - `ComprasJanela`.
6. **Se contado:**
   - última contagem L;
   - candidatos = contagens com 7+ dias antes de L;
   - escolha do início:

     | Modo | Início |
     |---|---|
     | primeira compra | contagem antes da 1ª nota; senão **estoque zero** no dia anterior à 1ª nota |
     | histórico | 1º candidato |
     | fixo | último candidato ≤ A; senão o 1º |
     | auto | candidato mais perto de L − janela |

   - consumo = `qtd_início + compras (início, L] − qtd_L`. Se for negativo, `ConsumoNegativo` e
     `UsoMedioDiario` = 0; senão UMD = consumo / dias;
   - sem início mas com compras na janela → método `compras` (UMD = compras / janela);
   - `EstoqueHoje = max(qtd_L + compras (L, ref] − UMD × dias, 0)`.
7. **Nunca contado:** `EstoqueHoje = None` e `MetodoConsumo = 'sem_dados'`.

Exceções vão para o log e são relançadas. Também é usada por `compras_database.py` (app).

**Outras funções da sugestão:**
- **`embalagens_por_produto()` `:8485`:** fatores > 1 por produto, a embalagem mais usada primeiro.
  Erro → `{}`.
- **`ultimas_contagens_por_produto()`:** soma o mesmo dia. Erro → `{}`.
- **`ultimo_custo_real_produto(pid)`:** última compra paga, **sem royalties**.
- **`buscar_historico_compras_produto(pid)` `:8625`:** inclui fantasma e bonificação, sem royalties.
- **`atualizar_item_historico_compra(item, qtd, custo)` `:8655`:** `UPDATE` direto, sem validar e sem
  o fator usado. `rowcount = 0` → `False`.
- **`gerar_ranking_sabores_buffet(dias, ids)` `:8756`:** `SUM(Quantidade)/dias` com
  `DataEmissao >= GETDATE() − dias` (**relógio do servidor SQL**). A bonificação entra. ⚠ Sem lote de
  500, então pode passar do limite de 2.100 parâmetros.

#### L) Desmembrar caixa — "máquina do tempo" (`:12197–12340`)
- **`previa_desmembrar_caixa(id_origem, qtd_na_caixa)`.** ⚠ Chama `listar_valores_estoque_fechados()`
  **para cada contagem** dentro da list comprehension.
- **`desmembrar_caixa(id_origem, ean, qtd_na_caixa, contagem_id=None, nome_avulso=None,
  qtd_contada=None)` `:12229`.** Uma transação. `M = qtd_na_caixa / fator do vínculo de ORIGEM`.
  - Se M ≠ 1:
    1. o produto recebe o sufixo " (UNIDADE)" (se ainda não tem) e `UnidadeMedida='UN'`;
    2. em **todos os vínculos** do produto:
       - itens: quantidade × M, preço ÷ M, `FatorConversaoUsado = COALESCE(usado, fator) × M`
         (inclui o custo manual);
       - `FatorConversao × M`, exceto no vínculo interno;
    3. contagens **não fechadas**: quantidade × M.
  - Cria o vínculo "… (VINCULO UNIDADE)", com fator 1, para o EAN, se ainda não existe no produto.
  - Resolve o avulso.
  - ⚠ **Não** converte `EstoqueMinimo` nem nada do app de compras.
- **`resolver_avulso_fracionando_caixa(...)`** e **`criar_unidade_a_partir_de_caixa(...)`** (app):
  delegam para `desmembrar_caixa`.

#### M) Custo manual — "nota fantasma" (`:12563–12733`)
**`criar_produto_manual_com_custo(nome, un, min, cat, custo)`.**
- Cria o produto. Se custo > 0, acha ou cria:
  - o fornecedor `"PRODUÇÃO INTERNA / AVULSO"` com CNPJ `"00000000000000"` (⚠ **literal repetido**, não
    usa a constante);
  - o vínculo `"<nome> (CADASTRO MANUAL)"` (EAN `'SEM EAN'`, NCM `'00000000'`, fator 1);
  - a nota `MANUAL-<id>` (`DataEmissao = GETDATE()`, valor 0, sem série/chave/valor fora);
  - um item com **quantidade 0** e o preço digitado.
- Devolve o ID (`Decimal`).

**`atualizar_custo_manual_produto(pid, custo)`.**
- Já tem vínculo interno → atualiza o **preço** do item da nota fantasma mais recente. A **data não
  muda**.
- Não tem a nota → cria `MANUAL-UPD-<pid>`.
- Não tem vínculo → cria `"(CUSTO ATUALIZADO MANUAL - ID n)"` + nota + item.

**Leituras de "último custo".**
- **`buscar_ultimo_custo_por_produto(pid)`.** `TOP 1` por data em **todas** as entradas: inclui a
  nota fantasma, cuja data é a do cadastro, e a bonificação (0). Devolve `Decimal` ou o `float`
  `0.00`.
- **`buscar_produtos_para_folha_contagem()`.** A mesma regra de `TOP 1`, sem royalties.

#### N) Catálogo: resumo, massa, nomes, duplicados (`:10272–10495`, `:10527`)
- **`resumo_catalogo()` `:10272`.**
  - Usa `_custos_por_produto(cursor, HOJE)`.
  - "Mais barato" por **nome** de fornecedor (média ponderada de 365 dias, com royalties).
  - Última contagem = maior (data, ContagemID). ⚠ **Não soma** contagens do mesmo dia, ao contrário
    da Sugestão.
- **`atualizar_produtos_em_massa(ids, categoria, unidade, estoque_min)`.** Não valida se a categoria
  existe.
- **`renomear_produtos([(id, nome)])`.** Recusa um nome igual a outro (sem diferenciar maiúsculas; os
  acentos contam).
- **`listar_produtos_duplicados()`.** *Union-find* por nome normalizado (sem acento, pontuação e
  espaço) **ou** EAN igual em produtos diferentes. `ManterID` = mais compras, depois mais vínculos,
  depois menor ID.
- **`juntar_produtos(manter, remover)` `:10527`.** Uma transação:
  1. move os vínculos (as compras vão junto);
  2. em cada contagem que tem algum removido, soma tudo numa linha do mantido;
  3. `_trocar_produto_no_app_compras`;
  4. apaga os removidos.

  ⚠ Não converte unidade e não mexe no valor fechado (que guarda o nome).

#### O) Consultas (`:9901–10085`)
- **`historico_compras_detalhado(pid)`.** Só quantidade > 0 e fora o fornecedor interno, sem
  royalties. Fator = `COALESCE(usado, vínculo)`; calcula Embalagens e CustoEmbalagem.
- **`resumo_precos_por_fornecedor(hist, desde)`.** Função pura. ⚠ Em `CustoMedio = valor/qtd`, a
  bonificação entra na quantidade e **puxa a média para baixo**.
- **`listar_notas_para_consulta()`.** Todas as notas (fora as internas) + texto dos itens.
- **`itens_da_nota(id)`.** Itens da nota com categoria e fator.
- **`resumo_categorias_nota(itens, pct)`.** Função pura.
- **`sem_acento_simples`.** Faz `import unicodedata` dentro da função.

#### P) Reset e backup (`:9279–9344`)
- **`resetar_dados_estoque_completo()`.**
  - Apaga o valor fechado e as 6 tabelas do estoque.
  - Faz `DBCC CHECKIDENT RESEED 0` **só nas que tinham linhas**, então o próximo ID é 1.
  - Mantém fornecedores, categorias, funcionários e **todas as tabelas do app de compras** (F-01).
- **`exportar_tabelas_estoque()`.** `SELECT *` das 9 tabelas de `TABELAS_BACKUP_ESTOQUE`. Não inclui
  `CategoriasProduto` nem as tabelas do app.

#### Q) Solicitações e busca de vínculos (`:11816–11860`, `:12161`, `:12441`)
- **`listar_solicitacoes_pendentes()`.** `SolicitacoesInternas` JOIN `Funcionarios` com
  `Status='Pendente'`. ⚠ Sem `except`.
- **`atualizar_status_solicitacao(id, status, motivo, status_esperado)`.**
  - Concorrência otimista: só muda se o status ainda for o esperado.
  - `DataConclusao = GETDATE()`.
  - ⚠ Sem `except`.
- **`buscar_produtos_mobile_por_nome(termo)`.**
  - `TOP 20` **vínculos** com `LIKE %termo%` (os curingas `%` e `_` digitados passam direto).
  - `UltimoCusto` = `TOP 1` por vínculo (pode ser a bonificação 0).
  - O nome diz "mobile", mas é usado pelo PC (avulsos) e pela API.
- **`descobrir_produto_mestre_por_ean(ean)`.**
  - Ignora `'SEM GTIN'`, `'SEM EAN'` e `''`. ⚠ A comparação diferencia maiúsculas, e a tela usa
    `"Sem EAN"` em outros pontos.
  - `TOP 1` sem `ORDER BY`.

### 2.16 `nota_xml.py` (compartilhado com o recebimento do app)
- **Parser:** `lxml` com `resolve_entities=False` (proteção contra XXE); se faltar, usa
  `ElementTree`.
- **CFOPs** (pelos 3 últimos dígitos):
  - `CFOP_BONIFICACAO` = {910, 911};
  - `CFOP_IGNORAR` = {908, 909, 912, 913, 915, 916, 920, 921, 201, 202, 410, 411}.
- **`tipo_item_por_cfop`** → `'compra' | 'bonificacao' | 'ignorar'`.
- **`ler_xml_nota_fiscal(caminho)`** → `(cab, itens)`.
  - Tira os namespaces e exige `ide`, `emit` e `total/ICMSTot`.
  - Chave = `infNFe@Id` sem o prefixo "NFe".
  - `DataEmissao = dhEmi | dEmi`. ⚠ **Se faltar, usa a data de hoje.**
  - CNPJ ou CPF; `Finalidade = finNFe`.
  - Custo do item = `vProd + vICMSST + vFCPST + vIPI + vFrete + vSeg + vOutro − vDesc`;
    `PrecoCustoUnitario = total/qCom`.
  - **Rateio:** para cada tributo ou despesa, a diferença entre o total da nota e a soma dos itens,
    se ≥ R$ 0,01, é repartida em proporção ao `vProd` **só entre os itens de compra**. O desconto
    entra subtraindo. Diferença negativa é ignorada.
  - ⚠ Não lê `uCom`/`qTrib`/`uTrib`: a **única conversão** de unidade é o Qtd/Cx do vínculo.
  - Qualquer erro vira `Exception("Falha estrutural no XML: …")`.
- **`aplicar_conferencia(itens, {NItem: qtd})`** → `(itens com a quantidade que chegou, valor a
  menos)`.
- **`qtd_estoque(item, fator)`** = `qtd × fator`. Arredonda para 3 casas se veio da conferência.

### 2.17 `nfe_distribuicao.py` (como o Estoque usa)
- **Serviço:** "Distribuição de DF-e" da SEFAZ com certificado A1.
- **Configurações** (só os nomes): `NFE_CERTIFICADO_PFX`, `NFE_CERTIFICADO_SENHA`, `NFE_CNPJ`,
  `NFE_AMBIENTE`, `NFE_PASTA_XML`, `NFE_MANIFESTAR_CIENCIA`, `NFE_VERIFICAR_SSL`, `NFE_SSL_ESTRITO`.
- **Arquivos:** estado em `nfe_distribuicao_estado.json` (último NSU, próxima consulta, última busca,
  `aguardando_xml`); XMLs em `notas_xml_sefaz/<chave>.xml` e `importadas/`.
- **`buscar_notas()`:**
  - trava em memória + `flock` num arquivo `.lock` (o **agendador** busca de hora em hora);
  - respeita a espera de 1 h quando não há novidade;
  - até 20 lotes de 50 documentos;
  - `procNFe` → salva o XML;
  - `resNFe` → entra na fila e recebe a **Ciência da Operação** (evento 210210 assinado);
  - esquece pendências depois de 30 dias;
  - fuso fixo UTC−4.
- **Funções usadas pela tela:** `configurado`, `pasta_xml`, `ler_estado`, `texto_resumo` e
  `_ja_temos_xml` (privada).

### 2.18 `file_utils.py`
- **`abrir_arquivo(caminho)`:** usa `os.startfile`, `open` ou `xdg-open` conforme o sistema. Erros só
  vão para o `print`.
- **`excluir_arquivo_seguro`:** não é usada pelo Estoque.

---

## 3. Mapeamento de Dependências e Estado

### 3.1 Módulos importados e por quê

| Módulo | Quando carrega | Para quê | Se faltar |
|---|---|---|---|
| `tkinter` / `ttk` / `messagebox` / `filedialog` / `simpledialog` | início | toda a tela | o programa não abre |
| `tkcalendar.DateEntry` | início | data da contagem | o programa não abre |
| `database` | início (L47) | **toda** leitura e gravação; ao ser importado roda ~10 migrações e reconfigura o log | o programa não abre |
| `config` | início | `ID_GESTOR_PADRAO`, `NOME_EMPRESA`, `NFE_PASTA_XML` (sempre com `getattr` e valor padrão) | o programa não abre |
| `file_utils` | início (L7) | abrir a foto da solicitação | o programa não abre |
| `nota_xml` | L493–494 | leitura do XML, CFOP, conferência, `qtd_estoque` | o programa não abre |
| `lxml` → `xml.etree` | início | **não usado** (sobra) | — |
| `unicodedata`, `math`, `collections`, `threading` | L165–168 | busca sem acento, `ceil`, agrupamentos, *thread* da SEFAZ | — |
| `matplotlib` | dentro do gráfico | gráfico do produto | mensagem amigável; só o gráfico deixa de funcionar |
| `pandas` (+ `openpyxl`) | dentro das exportações | Excel: valor, folha, sugestão, pedido, consultas, backup | mensagem; **o backup do reset falha** (aí pergunta se apaga sem backup) |
| `nfe_distribuicao` | dentro das funções da SEFAZ | baixar e listar XMLs; pasta `importadas/` | erro na hora do clique |
| `shutil` | dentro de `_guardar_xml_para_conferencia` | copiar o XML | — |

**Dependências indiretas que chegam pelo `database.py`:**
- `pyodbc`, que exige o **driver ODBC** do SQL Server instalado;
- `notificador_telegram`, importado pelo `database` na carga, mesmo sem o Estoque usá-lo diretamente.

### 3.2 Banco de dados (SQL Server) — o que o Estoque toca

| Tabela | Quem cria | Estoque grava em… | Também usada por |
|---|---|---|---|
| `ProdutosEstoque` | **ninguém no repo** (+ `NCM` via ALTER) | catálogo, juntar, renomear, massa, desmembrar, custo manual, reset | app compras, API, recebimento, orçamentos |
| `CategoriasProduto` | `verificar_migracao_categorias_estoque` (import) | gestor de categorias | `compras_cupom.py`; royalties em todos os cálculos de custo do `database.py` |
| `Fornecedores` | **ninguém no repo** | aba 2, importação (**auto-cadastro**), custo manual (fornecedor interno) | app compras, recebimento, orçamentos |
| `ProdutosFornecedor` (vínculo) | **ninguém no repo** | vincular, gestor de vínculos, juntar, desmembrar, aprender EAN, custo manual | recebimento, orçamentos, cupom (`buscar_vinculo_inteligente`) |
| `NotasFiscaisEntrada` | **ninguém no repo** (+ `Serie`, `ChaveAcesso`, `ValorForaDoEstoque` via ALTER) | salvar nota, nota fantasma, excluir, reset | app (alertas), recebimento |
| `ItensNotaFiscalEntrada` | **ninguém no repo** (+ `FatorConversaoUsado` via ALTER) | salvar nota, corrigir, recalcular, ratear, desmembrar, juntar | app (sugestão, alertas), Telegram |
| `ContagensEstoque` / `ItensContagemEstoque` | **ninguém no repo** (+ colunas de avulso via ALTER no import) | contagem do PC, editar, consolidar, avulsos, juntar, desmembrar, reset | **app de compras grava contagens** (rotinas, contagem geral, vários locais) |
| `ValorEstoqueFechamento` / `…Itens` | `_garantir_tabelas_valor_estoque` | fechar, reabrir, excluir contagem, reset | app (respeita as contagens fechadas) |
| `Funcionarios` | sistema de RH | — (só lê o nome do responsável) | todo o sistema |
| `SolicitacoesInternas` | `verificar_migracao_solicitacoes` (import) | aprovar/recusar | **bot do Telegram cria** |
| `RecebimentoNotas` / `RecebimentoItens` | `recebimento.py` | — (só lê a conferência) | app (aba Receber) |
| `CompraRotinaItens`, `CompraCodigos` | `compras_database.py` | juntar/excluir produto (`_trocar_produto_no_app_compras`) | app |
| `CompraListas`, `CompraListaItens`, `CompraContagemLocais`, `CompraOrcamentoItens`, `CompraCupomItens` | app / orçamentos / cupom | **não toca** (ver F-01, F-02) | app |
| `CadastroFranquia` (+ `CategoriasProduto.MarkupPadrao`, `ProdutosFornecedor.EANUnidade`) | `cadastro_franquia.garantir_tabelas` | aba 9 | Telegram (só conta produtos novos) |

**Valores especiais gravados no banco:**
- fornecedor interno com CNPJ `00000000000000`, nome `PRODUÇÃO INTERNA / AVULSO`;
- notas `MANUAL-<id>` e `MANUAL-UPD-<id>`;
- item de **quantidade 0** = custo manual;
- EAN `'SEM EAN'` e NCM `'00000000'` nos vínculos fantasmas;
- sufixos de descrição: `(CADASTRO MANUAL)`, `(CUSTO ATUALIZADO MANUAL - ID n)`, `(EAN APRENDIDO)`,
  `(VINCULO UNIDADE)`;
- sufixo de produto: `(UNIDADE)`;
- `ItensContagemEstoque.ProdutoID NULL` + `NomeAvulso` = item avulso;
- status de solicitação `'Pendente'`, `'Aprovado'`, `'Recusado'`;
- status de conferência `'conferida'`, `'divergencia'`.

### 3.3 Estado global (nível de módulo)

**`gestao_estoque_main.py`:**
- `PASTA_DO_PROGRAMA`, `USANDO_LXML`/`ET` (sem uso), `UNIDADES_FRACIONADAS`;
- listas de `sugerir_nome_limpo`;
- **atributos de classe** usados como constantes: `FILTROS_CATALOGO`, `TEXTO_OUTRA_EMBALAGEM`,
  `OPCAO_A_*`, `MOSTRAR_SUGESTAO`, `FILTROS_PROBLEMA`, `PROBLEMAS_GRAVES`, `PERIODOS_CONSULTA`;
- configuração do **logger raiz** do processo.

**`database.py`:**
- **flags globais** `_colunas_estoque_ok` e `_tabelas_valor_ok`: as migrações rodam 1× por processo,
  e cada programa (PC, API, agendador, bot) roda a sua;
- as constantes da seção 2.15;
- a reconfiguração do logger raiz;
- as **migrações executadas no import** (linhas 177, 337, 382, 416, 460, 5702, 5741, 6166, 6184,
  7280).

**`nfe_distribuicao.py`:** trava `_trava` em memória + arquivo `.lock`.

### 3.4 Estado da janela (`self.*`) — onde nasce, quem muda, quem lê

| Atributo | Nasce em | Quem muda | Quem lê |
|---|---|---|---|
| `produto_selecionado_id`, `_form_produto_id`¹, `produto_tem_nota`¹, `custo_carregado_texto` | `__init__` / seleção | seleção, limpar, reset | salvar/excluir produto |
| `_cache_produtos`¹, `_cache_resumo_catalogo`¹ | `_carregar_cache_catalogo` | F5, salvar, trocar de aba | filtros do catálogo, nomes limpos |
| `mapa_produtos_mestre`, `lista_mestre_produtos_nomes`, `_unidade_por_id`¹, `mapa_produtos_mestre_contagem`, `lista_mestre_contagem_nomes`, `embalagens_contagem`¹ | `popular_combobox_produtos_mestre` | **reatribuídos** a cada recarga | importação, contagem, avulsos, edição de contagem, consultas, buffet |
| `itens_xml_nao_vinculados`, `dados_notas_processadas`, `ultima_pasta_xml`, `filtro_arquivos_xml`, `_seq_pendente`¹, `_ultimo_pendente_clicado`¹, `_notas_ja_importadas`¹ | `__init__` / processar | processar, vincular, salvar | aba 3 |
| `lista_itens_para_salvar_contagem` | `__init__` | adicionar/editar/remover/rascunho | salvar contagem, fechar a janela |
| `id_funcionario_contagem`¹ | criação da aba 4 | — | salvar e consolidar contagem |
| `_opcoes_embalagem`¹, `_embalagens_extras`¹, `_ultimas_contagens`¹ | aba 4 | troca de produto, salvar | prévia, "contou em caixa?" |
| `mapa_contagens_historico` | aba 4 | recarga | **ninguém** |
| `mapa_contagens_sugestao`, `resultado_sugestao`¹, `linhas_sugestao`¹, `dados_sugestao_tela`¹, `cache_relatorio_posicao`, `_mostrar_sug_atual`¹, `_cache_ids_forn`¹ (gravado via `self.__dict__`) | aba 5 | gerar, recalcular, renderizar, invalidar | tela, pedido, Excel, histórico |
| `solicitacao_atual_id`¹, `solicitacao_atual_foto`¹, `cache_solicitacoes`¹ | aba 7 | seleção | aprovar/recusar/foto |
| `cache_consulta_notas`¹, `historico_consulta`¹, `produto_consulta`¹, `nome_produto_consulta`¹, `itens_nota_consulta`¹, `nota_consulta_atual`¹, `destacar_nota_consulta`¹, `filtro_categoria_nota`¹, `resumo_categorias_nota`¹, `cartoes_consulta`¹ | aba 8 | navegação | aba 8 |
| `ultimo_status`¹, `ultimo_pedido`¹, `_status_job` | status / pedido | — | **ninguém** (só `_status_job`) |
| `_janela_*`¹ (ajuste_nota, compras, juntar, juntar_produtos, massa, nomes, pedido, recalculo, valor, vinculos) | cada janela | — | **só os testes automatizados** |

¹ Criado **fora do `__init__`**: o atributo só existe depois que a função que o cria rodou. Por isso
o código usa `getattr(self, ..., None)` ou `hasattr` em vários pontos.

### 3.5 Arquivos físicos

| Arquivo / pasta | Onde | Conteúdo | Escrito por | Lido por |
|---|---|---|---|---|
| `logs/gamificacao_sistema.log` (+ .1…5) | ao lado do programa | log de **todos** os módulos do processo | logger raiz | pessoas |
| `estoque_preferencias.json` | pasta do programa | geometria, aba, `sugestao{…}`, `embalagem_contagem{id: fator}` | `salvar_preferencias`, `_lembrar_embalagem_contagem` | abertura, aba 4 (a cada troca de produto), aba 5 |
| `rascunho_contagem.json` | pasta do programa | contagem não salva | cada item adicionado/removido, data/nome | abertura (400 ms) |
| `config_sabores_buffet.json` | pasta do programa (ou o antigo na pasta **atual**) | lista de ProdutoID dos sabores | gestor do buffet, juntar produtos | buffet |
| `backups_estoque/` | pasta do programa | Excel do backup, rascunhos descartados, JSONs "antes do reset" | reset, rascunho | pessoas |
| pasta de XML escolhida | qualquer | XMLs e TXTs de notas | — | importação, recálculo |
| `notas_xml_sefaz/` e `importadas/` (`NFE_PASTA_XML`) | config | XMLs baixados (nome = chave) | `nfe_distribuicao` (agendador/PC), arquivamento | aba 3, "XML da compra", app |
| `nfe_distribuicao_estado.json` + `.lock` | pasta da SEFAZ | NSU, fila de ciência | `nfe_distribuicao` | aba 3 |
| fotos de solicitação | caminho relativo gravado pelo bot | imagem | bot do Telegram | aba 7 |
| Excel exportados | escolhidos pelo usuário | valor, folha, sugestão, pedido, consultas | pandas | — |

⚠ Esses arquivos são **de cada computador**. O Buffet, a embalagem lembrada e o rascunho não
aparecem em outro PC nem na Web.

### 3.6 Configurações usadas (só os nomes — os valores ficam no `config.py`)
- **Estoque:** `ID_GESTOR_PADRAO` (padrão no código: 2), `NOME_EMPRESA`, `NFE_PASTA_XML`.
- **Banco:** `CONNECTION_STRING`.
- **SEFAZ:** `NFE_CERTIFICADO_PFX`, `NFE_CERTIFICADO_SENHA`, `NFE_CNPJ`, `NFE_AMBIENTE`,
  `NFE_MANIFESTAR_CIENCIA`, `NFE_VERIFICAR_SSL`, `NFE_SSL_ESTRITO`.

### 3.7 Rastreamento de dados — onde nascem e onde morrem

**Compra (item de nota).**
1. **Nasce** no XML: arquivo escolhido, ou baixado da SEFAZ pelo agendador ou pelo botão.
2. `nota_xml` calcula o custo real do item (com tributos e rateios) e classifica o CFOP.
3. A conferência do app pode reduzir a quantidade.
4. **Na tela**, `qtd × Qtd/Cx` e `custo ÷ Qtd/Cx`.
5. **Persiste** em `ItensNotaFiscalEntrada`: `Quantidade` e `PrecoCustoUnitario` já na unidade do
   estoque, mais o `FatorConversaoUsado`.
6. **Pode ser reescrita** por:
   - `corrigir_compra` / `atualizar_item_historico_compra`;
   - recálculo pelo XML (`atualizar_custos_itens`);
   - rateio (`ratear_diferenca_nas_notas`);
   - troca de Qtd/Cx com recálculo (`atualizar_vinculo_existente`);
   - `desmembrar_caixa`;
   - `juntar_vinculos` (troca o vínculo).
7. **Consumida** por:
   - valor do estoque, sugestão, catálogo, gráfico, consultas, alertas de preço;
   - app (sugestão, alertas, orçamentos).
8. **Morre** em `excluir_nota_fiscal_entrada` ou no reset. O XML continua no disco.

**Custo manual.**
1. **Nasce** no Catálogo, no aviso "Sem custo" do Valor do Estoque ou ao cadastrar um produto com
   custo.
2. Vira o trio fornecedor interno, vínculo fantasma e nota `MANUAL-*` com item de quantidade 0.
3. **Lido** como último recurso pelo Valor do Estoque e como "último custo" pelo Catálogo e pela
   folha.
4. **Morre** quando se exclui a nota fantasma (Administração), o produto ou faz o reset.

**Contagem.**
1. **Nasce** de três fontes:
   - aba 4 (rascunho JSON → `salvar_contagem_estoque`);
   - app de compras (rotinas, contagem geral, vários locais, com `CompraContagemLocais`);
   - consolidação.
2. **Muda** em: editar contagem, resolver avulso, juntar produtos, desmembrar caixa, "não contado"
   no Valor do Estoque.
3. **Congelada** pelo fechamento do valor (`ValorEstoqueFechamento*`, um retrato com nome, categoria
   e custo).
4. **Morre** em excluir contagem, consolidar (as originais) ou reset.

**Vínculo.**
1. **Nasce** de:
   - Vincular ou Criar e Vincular (aba 3);
   - aprender EAN (avulso);
   - vínculo UNIDADE (desmembrar);
   - vínculo fantasma (custo manual).
2. **Muda** no gestor de vínculos (produto, Qtd/Cx, EAN, NCM) e ao salvar uma nota (NCM).
3. **Morre** em excluir vínculo (só sem itens), juntar vínculos, excluir produto ou reset.

**Produto.**
1. **Nasce** de:
   - Catálogo;
   - Criar e Vincular (nome do XML, unidade UN);
   - gestor de vínculos;
   - custo manual.
2. **Muda** em: edição, massa, nomes limpos, categoria renomeada, desmembrar.
3. **Morre** em excluir (só sem histórico), juntar ou reset.

**Valor do estoque, sugestão e pedido.**
- São **calculados na hora**, a partir das compras e contagens. Não ficam gravados, exceto o
  fechamento.
- O pedido **morre** no texto copiado para o WhatsApp ou no Excel.

**Alerta de preço.**
- **Calculado** depois de salvar as notas (tela) e diariamente (`alertas_estoque.py`, Telegram).
- Não é gravado.

**Solicitação.**
1. **Nasce** no bot do Telegram.
2. A aba 7 **muda o status**.
3. Ninguém avisa o solicitante.

---

## 4. Pontos de Atenção Imediata (Forensics)

Cada ponto diz o que acontece e onde. Nenhuma correção foi feita.

### 4.1 Integridade de dados

- **F-01 — O reset recomeça os IDs, mas o app de compras continua apontando para os IDs antigos.** ✅ *Corrigido — ver seção 5.*
  - `resetar_dados_estoque_completo` (`database.py:9279`) apaga produtos, notas e contagens e faz
    `RESEED 0`.
  - Ficam intactas: `CompraRotinaItens`, `CompraCodigos`, `CompraListaItens`, `CompraListas.ContagemID`,
    `CompraContagemLocais`, `CompraOrcamentoItens` e `CompraCupomItens`.
  - O novo produto **ID 1** "herda" rotinas, códigos de barras, orçamentos e locais do antigo ID 1. A
    nova contagem ID 1 herda a divisão por locais da antiga.

- **F-02 — Juntar e excluir produto só corrigem 2 tabelas do app.** ✅ *Corrigido — ver seção 5.*
  - `_trocar_produto_no_app_compras` trata `CompraRotinaItens` e `CompraCodigos`.
  - Listas, locais de contagem, orçamentos e cupons ficam com o `ProdutoID` de um produto apagado.
  - Excluir ou consolidar contagens no PC também não limpa `CompraContagemLocais` nem
    `CompraListas.ContagemID`.

- **F-03 — Juntar produtos com unidades diferentes soma as contagens sem converter.**
  `juntar_produtos` `:10527`; a tela só avisa.

- **F-04 — "Desmembrar caixa" reescreve o histórico inteiro do produto, mas não tudo.** ✅ *Corrigido — ver seção 5.*
  - Converte compras, vínculos e contagens não fechadas.
  - **Não** converte `EstoqueMinimo` (que passa a valer M vezes menos) nem nada do app.
  - Acrescenta "(UNIDADE)" ao nome.
  - O M é calculado pelo Qtd/Cx do vínculo de **origem** e aplicado a todos (`:12229`).

- **F-05 — Excluir nota fiscal deixa o XML "importado".** ✅ *Corrigido — ver seção 5.*
  - O arquivo fica em `importadas/`, então a nota some do estoque e não volta para a lista da SEFAZ.
  - A nota fantasma do custo manual também pode ser excluída por aqui: o aviso depende do **nome** do
    fornecedor.
  - Excluir várias notas não é transacional.

- **F-06 — Salvar nota incompleta perde os itens pendentes para sempre.** ✅ *Corrigido — ver seção 5.* A nota fica marcada como
  importada (`salvar_notas_processadas` `:3272`). Só a correção manual da compra resolve.

- **F-07 — Dois caminhos diferentes para corrigir uma compra.** ✅ *Corrigido — ver seção 5.*

  | Caminho | Validação | Fator usado | Valor antigo no log |
  |---|---|---|---|
  | Aba 5 → `atualizar_item_historico_compra` | não | não grava | não |
  | Vínculos → `corrigir_compra` | sim | grava | sim |

- **F-08 — Categoria é texto, não chave.**
  - Renomear faz cascata pelo nome.
  - `atualizar_produtos_em_massa` aceita uma categoria que não existe.
  - Os royalties são ligados pelo nome da categoria.
  - O valor fechado guarda o nome antigo.

- **F-09 — O reconhecimento pela descrição exata aceita vínculo sem produto e escolhe ao acaso entre
  repetidos.** `buscar_vinculo_inteligente` `:6611`: o 1º passo não exige `ProdutoID` e usa
  `fetchone()` sem `ORDER BY`. A compra é gravada num vínculo órfão e **some** de todos os relatórios
  por produto.

- **F-10 — `criar_vinculo_produto_fornecedor` não impede duplicados.** Dois PCs vinculando a mesma
  nota ao mesmo tempo criam vínculos repetidos. Existe ferramenta para juntar depois.

- **F-11 — Responsável e rascunho da contagem.**
  - Toda contagem do PC é gravada no funcionário `ID_GESTOR_PADRAO`, com **2 fixo** como padrão
    (`:3558`).
  - O rascunho local não confere se os produtos ainda existem.

- **F-12 — "Duas contagens no mesmo dia" tem regras diferentes em cada tela.** ✅ *Corrigido — ver seção 5.*

  | Tela / função | Regra |
  |---|---|
  | Sugestão, gráfico, `ultimas_contagens_por_produto` | **soma** |
  | `resumo_catalogo` | pega só a de **maior ID** |
  | Valor do Estoque | usa só a contagem escolhida |
  | `calcular_valor_estoque` | "contagem anterior" = data menor (ignora a outra do mesmo dia) |

- **F-13 — Bloqueio de contagem fechada é conferido só na abertura.**
  - `abrir_edicao_contagem` não confere de novo ao gravar.
  - `contagem_esta_fechada` (não usada) é *fail-open*.
  - O banco **não impede** gravar em contagem fechada: a proteção existe só na tela do PC e no app.

- **F-14 — Linhas repetidas do mesmo produto na contagem.**
  - `salvar_contagem_estoque` grava repetidos como linhas separadas.
  - `adicionar_item_contagem_existente` faz `+=` em **todas** as linhas e não tem rollback.
  - `remover_item_contagem` e `listar_itens_avulsos_pendentes` não têm `except`.

### 4.2 Falhas silenciosas e respostas enganosas

- **F-15 — Banco fora do ar não é tratado do mesmo jeito.** ✅ *Corrigido — ver seção 5.*

  | Função | Resultado quando o banco falha |
  |---|---|
  | `listar_produtos_estoque`, `listar_vinculos_com_resumo`, `listar_compras_do_vinculo`, `historico_compras_detalhado`, `listar_notas_*` | `[]` (parece "não há dados") |
  | `resumo_catalogo`, `embalagens_por_produto`, `conferencias_recebimento` | `{}` (**importa as quantidades da nota em vez das conferidas**) |
  | `verificar_nota_fiscal_existente` | `True`: a tela diz "já importada" |
  | `buscar_nota_importada` | `None` |
  | `listar_valores_estoque_fechados()` sem flag | `{}` |
  | Outras funções | Levantam exceção |

  As listas da tela só registram o erro no log.

- **F-16 — Item vira "pendente" sem aviso quando o reconhecimento falha.**
  `buscar_vinculo_inteligente` devolve `None` em erro ou sem conexão.

- **F-17 — `_dec()` transforma qualquer valor inválido em 0.** Em `corrigir_compra`, um texto
  inválido vira a mensagem "precisa ser maior que zero".

- **F-18 — `excluir_vinculo_existente` responde `False` para "recusado" e para "erro".** A tela só
  evita a confusão porque consulta `vinculo_tem_itens` antes.

- **F-19 — XML sem data de emissão ganha a data de hoje** (`nota_xml.ler_xml_nota_fiscal`).

### 4.3 Efeitos colaterais e infraestrutura

- **F-20 — Log configurado duas vezes no mesmo processo.** ✅ *Corrigido — ver seção 5.*
  - `gestao_estoque_main.py:37` e `database.py:58` zeram os handlers do logger raiz e criam **dois**
    `RotatingFileHandler` para o mesmo arquivo.
  - O 1º sai do logger mas não é fechado, e o arquivo fica aberto.
  - No Windows, a rotação de 10 MB pode falhar (arquivo em uso).
  - Quem importar esses módulos perde a configuração de log que tinha.

- **F-21 — Importar `database.py` mexe no banco.**
  - Roda ~10 migrações e consultas **na carga do módulo** (inclusive `ALTER TABLE`).
  - As tabelas-base do estoque **não são criadas por nenhum código**: o schema só existe no banco.
  - As colunas novas aparecem por `ALTER` em tempo de execução, controladas por flags globais em
    cada processo.

- **F-22 — Migração com transação aberta.** `juntar_vinculos` chama `_garantir_colunas_estoque()`,
  que abre **outra conexão** e pode fazer `ALTER`/`UPDATE`, no meio da sua própria transação. Só
  importa na 1ª execução histórica (coluna ainda inexistente), mas pode travar as duas conexões.

- **F-23 — Ler a pasta de XMLs grava fornecedores.** A importação **cadastra o fornecedor** durante a
  leitura, antes de o usuário salvar qualquer coisa (`processar_arquivos_xml`).

- **F-24 — Contrato informal entre `salvar_nota_fiscal_completa` e a tela.**
  - A função escreve `NotaID` dentro do dict recebido.
  - A tela reconhece duplicidade pelo **texto** "já foi importada".
  - IDs novos chegam como `Decimal` (via `SCOPE_IDENTITY`) em `criar_produto_estoque` e
    `criar_produto_manual_com_custo`.
  - `buscar_ultimo_custo_por_produto` devolve `Decimal` ou `float`.

### 4.4 Acoplamento por texto e valores mágicos

- **F-25 — Decisões tomadas por texto.** ✅ *Corrigido — ver seção 5.*
  - Nome da aba (`aba_atual`, `on_tab_changed`, atalhos).
  - Opções do Ponto A, convertidas nos números mágicos `None`/`-1`/`-2` que o banco interpreta.
  - Prefixo do combo "Mostrar".
  - `"(ID: n)"` tirado do texto com regex.
  - Fornecedor interno pelo **nome** `'PRODUÇÃO INTERNA'` na tela (`:5680`, `:6016`) e pelo **CNPJ** no
    banco. O literal `"00000000000000"` aparece repetido em 3 funções além da constante.
  - `"Sem EAN"` (tela) × `'SEM EAN'`/`'SEM GTIN'` (banco), com diferença de maiúsculas.
  - Os sufixos de descrição e de nome da seção 3.2.
  - A `OrigemCusto` é texto livre gravado no retrato do fechamento.

- **F-26 — Valores relidos da tela.** Formatados com 3 ou 4 casas e depois relidos com
  `para_decimal`:
  - estoque mínimo na seleção do produto;
  - quantidades dos avulsos;
  - quantidade e custo antigos no histórico de compras;
  - data da consolidação (`dd/mm/aaaa`).

- **F-27 — Linhas do banco lidas por posição.** Solicitações `[0..7]` e `listar_todos_vinculos_detalhado`.
  Mudar a ordem das colunas no SQL quebra a tela sem dar erro.

- **F-28 — Unidade de medida é texto livre.**
  - "Criar e Vincular" usa `"UN"` fixo.
  - `UNIDADES_FRACIONADAS` é uma lista fixa.
  - A conversão é feita **só** pelo Qtd/Cx: `nota_xml` não lê `uCom`/`uTrib`. Se o fornecedor mudar
    a embalagem sem mudar o vínculo, as quantidades ficam erradas até a auditoria "fator?" pegar.

### 4.5 Regras de custo que divergem entre telas

- **F-29 — "Último custo" tem pelo menos 6 definições.** ✅ *Corrigido — ver seção 5.*

  | Função / tela | O que entende por "último custo" |
  |---|---|
  | `buscar_ultimo_custo_por_produto` (catálogo, conferência de fator) | `TOP 1` por data: **inclui** a nota fantasma e a bonificação 0; sem royalties |
  | `buscar_produtos_para_folha_contagem` (folha de contagem) | a mesma regra |
  | `ultimo_custo_real_produto` | última compra paga, sem royalties |
  | `_custos_por_produto` (valor, catálogo) | média de 90 dias **com** royalties |
  | Sugestão (`FornecedorUltimo`) | última paga, **com** royalties e o Qtd/Cx **atual** do vínculo |
  | `listar_vinculos_com_resumo` | última paga, **sem** royalties |
  | `buscar_produtos_mobile_por_nome` | `TOP 1` por vínculo, pode ser a bonificação 0 |

  Os royalties entram no valor, na sugestão, no gráfico e no alerta; ficam de fora dos vínculos, das
  consultas e do histórico.

- **F-30 — Data da nota fantasma.** É a do **cadastro** do custo manual e não muda quando o custo é
  atualizado. `TOP 1 por data` pode preferir o custo manual a uma compra real mais antiga.

- **F-31 — Bonificação baixa a "média" por fornecedor.** `resumo_precos_por_fornecedor` divide pelo
  total que inclui as unidades bonificadas.

- **F-32 — "Ajustar notas antigas" pode jogar valores errados no custo.** Uma nota importada antes de
  `ValorForaDoEstoque` existir pode ter comodato ou bonificação no total. A tela só alerta acima de
  40% ou quando há item com custo zero.

- **F-33 — Ranking do Buffet usa outra medida e outro relógio.** Mede o consumo pelas **compras** (com
  bonificação), não pelas contagens. Usa o relógio do **servidor SQL** (`GETDATE()`). Tem 36 vagas
  fixas no código.

### 4.6 Desempenho (tudo na thread da tela, exceto a busca na SEFAZ)

- **F-34 — Leitura de tabelas inteiras em memória, a cada uso.**
  - `aumentos_de_preco`, `notas_ja_lancadas`;
  - `listar_vinculos_com_resumo` (e `listar_grupos_duplicados`, que a chama inteira);
  - `calcular_sugestao_compra`, `_custos_por_produto` / `resumo_catalogo`;
  - `listar_notas_para_consulta` (com o texto de todos os itens);
  - `contagens_do_dia_por_produto`.

- **F-35 — Consultas N+1 e conexão nova por chamada.**
  - `processar_arquivos_xml`: 1 `buscar_vinculo_inteligente` por item.
  - `abrir_lista_notas_sefaz`: lê todos os XMLs.
  - `listar_compras_do_vinculo`: 1 SELECT por compra.
  - `previa_desmembrar_caixa`: 1 conexão por contagem.
  - O catálogo é lido 3 vezes (catálogo, combo, gestor de vínculos).
  - `_lembrar_embalagem_contagem` reescreve o JSON a cada item.

- **F-36 — Limite de 2.100 parâmetros do SQL Server.**
  - Tratado com lotes de 500 em `chaves_ja_importadas`, `conferencias_recebimento` e
    `contagens_do_dia_por_produto`.
  - **Não** tratado em `gerar_ranking_sabores_buffet`, `consolidar_contagens` e `juntar_*`.

### 4.7 Concorrência (vários PCs + app + agendador)

- **F-37 — Sem trava entre usuários.**
  - Dois PCs na mesma pasta: o 2º recebe "já importada", mas podem nascer vínculos repetidos.
  - Edição de contagem enquanto o app regrava a contagem da rotina.
  - Fechamento do valor feito em outro PC com a janela de edição aberta (F-13).
  - As Solicitações usam concorrência otimista (`status_esperado`), e essa parte funciona.

- **F-38 — Estado que só existe em um computador.** Buffet, embalagem lembrada, preferências e
  rascunho.

### 4.8 Tela

- **F-39 — Zebra e ordem das árvores.** A zebra (monkeypatch de `insert`) não se refaz depois de
  ordenar ou remover. Ordenar a sugestão desfaz a ordem por gravidade.
- **F-40 — `bind_all` vale para todas as janelas.** F5, Delete e Ctrl+F agem também nas janelas
  filhas (F5 numa janela recarrega a aba de trás).
- **F-41 — Seleção automática de resultado.**
  - O combo da importação seleciona sozinho o 1º resultado; a busca é **com acento**.
  - A busca da contagem também seleciona sozinha o 1º resultado.
- **F-42 — Texto desatualizado no catálogo.** Diz "duplo-clique para ver vínculos", mas abre o
  gráfico.
- **F-43 — Listas reatribuídas.** `popular_combobox_produtos_mestre` troca as listas por novas;
  janelas abertas ficam com as antigas.
- **F-44 — Vincular não atualiza a nota em memória.** Salvar relê a pasta inteira, e a seleção e a
  rolagem se perdem.
- **F-45 — Foco × seleção.** Várias ações usam o **foco** da árvore, não a seleção: histórico de
  contagens, Valor do Estoque, editar contagem, solicitações, sugestão de EAN. A linha com foco pode
  não ser a que está destacada.

### 4.9 Código morto e sobras (seguro remover, mas confirmar com testes)

- **F-46 — Lista de sobras.**
  - **Na tela:**
    - `ET`/`USANDO_LXML`, `mapa_contagens_historico`;
    - `ultimo_pedido`, `_notas_ja_importadas`, `ultimo_status`;
    - `abrir_popup_vinculos_produto`, `_popup_vinculos_antigo` e o *fallback* de
      `buscar_vinculo_produto_fornecedor`;
    - `var_ocultar_zeros`, `lbl_contagem_unidade` (fora do grid), `combo_mestre_edit = None`;
    - os `getattr`/`hasattr`/`TypeError` de compatibilidade com versões antigas do `database.py`
      (`embalagens_por_produto`, `previa_desmembrar_caixa`, `vinculo_tem_itens`, `levantar_erro`,
      `status_esperado`, `exportar_tabelas_estoque`, `listar_produtos_duplicados`, `resumo_catalogo`).
  - **No banco:** `gerar_relatorio_valoracao_contagem`, `gerar_sugestao_por_periodo`,
    `_somar_compras_no_periodo`, `vincular_item_avulso_contagem`, `contagem_esta_fechada`,
    `buscar_vinculos_por_produto_mestre` / `atualizar_vinculo_simples` (só a tela antiga).
  - **Bloco de teste:** o `if __name__ == '__main__'` no fim do `database.py` cria um comunicado **de
    verdade** no banco.

---

## 5. Correções aplicadas (F-01, F-02, F-04, F-05, F-06, F-07, F-12, F-15, F-20, F-25, F-29)

As seções 2 a 4 descrevem o código **antes** destas correções. O que mudou está aqui.

### F-01 — Reset
- `resetar_dados_estoque_completo` **não faz mais `DBCC CHECKIDENT RESEED`**. Os IDs continuam de onde
  pararam, então um produto ou contagem novo nunca reaproveita o número de um antigo.
- Na mesma transação, limpa o App de Compras:
  - apaga `CompraRotinaItens`, `CompraCodigos`, `CompraContagemLocais` e `CompraContagemAndamento`;
  - zera `CompraListas.ContagemID`;
  - **cancela** as listas (`aguardando`/`aprovada`/`processando`) e os orçamentos (`rascunho`/`enviado`)
    em andamento;
  - desvincula os itens de cupom.
- Listas, orçamentos e cupons já fechados ficam como histórico (guardam o nome do produto).
- `TABELAS_BACKUP_ESTOQUE` passou a incluir `CategoriasProduto` e as tabelas do app que o reset mexe.
  `exportar_tabelas_estoque` pula as que não existem.
- A confirmação na tela explica tudo isso.

### F-02 — Juntar, excluir e contagens × App de Compras
- `_trocar_produto_no_app_compras` cobre as **6** tabelas com `ProdutoID`: `CompraRotinaItens`,
  `CompraCodigos`, `CompraListaItens`, `CompraContagemLocais`, `CompraOrcamentoItens` e
  `CompraCupomItens`.
  - **Juntar:** passa as linhas para o produto mantido. Se ele já está na mesma
    lista/orçamento/local/rotina, soma as quantidades numa linha só (`_mover_linha_do_produto`).
  - **Excluir:** apaga rotina, código e local, e desvincula o cupom.
- `excluir_produto_estoque` recusa (`ProdutoComHistorico`) quando o produto está numa lista ou orçamento
  **em andamento** (`_uso_aberto_no_app`) e cita qual.
- Contagens:
  - `consolidar_contagens` leva a divisão por local e a `CompraListas.ContagemID` para a contagem nova
    (`_mover_contagem_no_app`);
  - `excluir_contagem_estoque` limpa as duas;
  - editar, somar, remover ou resolver avulso no PC descarta a divisão por local daquele produto
    (`_descartar_locais_da_contagem`), porque ela não somaria mais o total;
  - `_conferir_locais` é a rede de segurança: só mantém a divisão que bate com o total.
- `adicionar_item_contagem_existente` junta linhas repetidas do produto numa só (antes somava a
  quantidade em todas).

### F-04 — Desmembrar caixa
- Converte também:
  - `EstoqueMinimo` (× M);
  - `CompraCodigos.Fator` do produto (o bip da caixa passa a valer M unidades);
  - `CompraContagemLocais.Qtd` das contagens não fechadas.
- `previa_desmembrar_caixa` mostra o mínimo e os códigos do app. Lê os valores fechados uma vez só
  (antes: uma conexão por contagem).

### F-05 — Excluir nota fiscal
- Ao excluir pela Administração, `nfe_distribuicao.devolver_para_lista(chave)` move
  `importadas/<chave>.xml` de volta para a pasta. A nota reaparece em "Notas baixadas da SEFAZ" e no
  app para ser lançada de novo.
- `listar_notas_fiscais_entrada_completa` traz `ChaveAcesso`, `CNPJ` e `ItensPendentes` no fim (LEFT
  JOIN: nota de fornecedor apagado também aparece).

### F-06 — Nota salva incompleta
- Colunas novas (criadas por `_garantir_colunas_estoque`):
  - `ItensNotaFiscalEntrada.NItem`: o número do item no XML;
  - `NotasFiscaisEntrada.ItensPendentes`: quantos itens ficaram de fora.
  - O PC e o app (`recebimento.py`) gravam o `NItem`.
- **Ao ler a pasta**, uma nota já salva passa por `_itens_que_faltam_na_nota`:
  - se tem `NItem`, a conta é exata;
  - se é uma nota antiga, só completa quando cada item gravado casa com um item do XML e sobra
    exatamente a diferença (senão fica como "já importada").
  - Só os itens que faltam aparecem, marcados "NF (completar)".
- **Ao salvar**, `completar_nota_fiscal(nota_id, itens, pendentes)` grava os itens na **mesma** nota,
  sem duplicar (`NItem`).
- **Lista da SEFAZ:**
  - mostra "salva INCOMPLETA: faltam N item(ns)" (`notas_incompletas()`);
  - `chaves_ja_importadas` ignora as notas incompletas, então o XML continua na lista;
  - nota incompleta vinda de outra pasta tem a cópia guardada na pasta principal, não em `importadas`.

### F-07 — Um caminho só para corrigir compra
- `atualizar_item_historico_compra` virou um atalho para `corrigir_compra`: valida, mantém o Qtd/Cx com
  que a compra entrou, recusa o custo manual e deixa o valor antigo no log.
- A janela de histórico da Sugestão chama `corrigir_compra` com os valores **exatos** do banco (não o
  texto da tabela).
- `buscar_historico_compras_produto` traz `FatorUsado` e `CNPJ`.

### F-12 — Contagens do mesmo dia
- `resumo_catalogo` soma as contagens do dia (`UltContagemVarias` = quantas).
- `calcular_valor_estoque`:
  - a "contagem anterior" soma todas as contagens daquele dia;
  - o produto contado só na **outra** contagem do mesmo dia vira o aviso `outra_contagem_do_dia` (não é
    "não contado");
  - `outras_do_dia` lista as outras contagens.
- A tela explica e sugere Consolidar.

### F-15 — Banco fora do ar
- **Novo parâmetro `levantar_erro=False`** (sem ele o comportamento é o de antes, para o app e a API) em:
  - `listar_produtos_estoque`, `listar_fornecedores`, `listar_categorias_produto`;
  - `listar_contagens_cabecalho`, `buscar_itens_contagem`, `resumo_catalogo`;
  - `listar_vinculos_com_resumo`, `listar_grupos_duplicados`, `listar_compras_do_vinculo`,
    `listar_produtos_duplicados`;
  - `historico_compras_detalhado`, `listar_notas_para_consulta`, `itens_da_nota`,
    `listar_notas_com_diferenca`;
  - `buscar_ids_produtos_por_fornecedor`, `conferencias_recebimento`, `buscar_vinculo_inteligente`;
  - `buscar_nota_importada`, `buscar_historico_compras_produto`,
    `listar_notas_fiscais_entrada_completa`, `buscar_produtos_para_folha_contagem`.
- `verificar_nota_fiscal_existente` **levanta erro** (antes respondia "já existe").
- Na tela, `falha_banco(onde, erro)` põe uma mensagem vermelha no rodapé e abre no máximo uma janela por
  minuto.
- **Na importação**, a falha do banco (verificar nota, vínculo, conferência do app) faz o arquivo contar
  como "falha" e ser lido de novo depois. Antes a nota podia entrar com a quantidade errada ou ser dada
  como "já importada".

### F-20 — Log
- Novo `log_config.py` com `configurar_log()`:
  - se já existe um handler gravando em `logs/gamificacao_sistema.log` (de qualquer módulo), não faz
    nada;
  - senão fecha os antigos e cria um só.
- `database.py` e `gestao_estoque_main.py` usam essa função. Os outros programas que configuram antes
  de importar o `database` também deixam de ter 2 arquivos abertos.

### F-25 — Decisões pelo texto
- **Abas:** `frame_da_aba_atual()`. `on_tab_changed` e `atalho_buscar` comparam o **Frame**, não o
  texto.
- **Fornecedor interno:** `e_fornecedor_interno(cnpj)` (pelo CNPJ) em todo lugar.
  - Constante `NOME_FORNECEDOR_INTERNO`.
  - O literal `"00000000000000"` só aparece na constante.
- **EAN:** `ean_valido(ean)` em vez de comparar com `"Sem EAN"` / `"SEM GTIN"`. Vale para
  `descobrir_produto_mestre_por_ean`, `vincular_item_avulso_inteligente`, `desmembrar_caixa` e a janela
  de avulsos, que guarda os valores exatos por linha.

### F-29 — Custos: a regra única
- **Custo real (nota + % de royalties da categoria)** é o padrão em todas as telas de custo do produto:
  - Valor do Estoque;
  - Catálogo ("Custo real" e "Mais barato", agora por ID do fornecedor);
  - **Folha de contagem** (antes: a entrada mais recente de qualquer tipo);
  - Sugestão/Pedido (a explicação mostra o %);
  - Gráfico, Alerta de aumento;
  - **Consultas > Produto** (`historico_compras_detalhado(..., com_royalties=True)`, guarda `PrecoNota`);
  - App de Compras.
- **Preço da nota (sem royalties)** só onde se mostra ou corrige a própria nota, ou se compara com o
  XML: conferência do Qtd/Cx, Vínculos, "Corrigir quantidade e preço", histórico da Sugestão, Consultas >
  Nota, orçamento enviado ao fornecedor.
- **"Último preço pago"** tem uma definição só, `ultimos_precos_pagos(ids, com_royalties)`: a última
  compra **paga**, sem bonificação nem custo manual. Usada por:
  - `ultimo_custo_real_produto`;
  - `buscar_ultimo_custo_por_produto` (que cai para `custo_manual_produto` se nunca houve compra paga e
    devolve sempre `Decimal`);
  - `buscar_produtos_mobile_por_nome` (por vínculo).
- `custos_atuais(data)` é o custo real para quem está fora do `database`.

### Testes
- `repro_forensics.py` reproduziu 12 falhas antes e 0 depois.
- `teste_forensics_banco.py` (banco) e `teste_forensics_tela.py` (Tkinter) cobrem cada ponto.
- Toda a suíte anterior passou: banco, telas do PC, app de compras e Gestão Web no navegador.

---

## 6. Cadastro na Franquia (aba 9)

Produto novo precisa ser cadastrado na Franquia antes de vender. A franquia pede, por produto: nome
limpo, código de barras, NCM, preço de custo e preço de venda. As regras ficam em
`cadastro_franquia.py`; a aba 9 só mostra e chama.

**Decisões do gestor:**
- envio por **planilha do Excel** (5 colunas; código de barras e NCM gravados como texto);
- markup **multiplicador** (2,5 = custo × 2,5), com um padrão por categoria;
- preço de venda arredondado **para cima terminando em ,90** (R$ 24,37 → R$ 24,90; R$ 24,95 → R$ 25,90);
- custo = **preço da nota** por unidade do estoque (com impostos e frete, **sem royalties**).

**De onde vem cada campo (sugestão; o que o gestor digita tem prioridade):**
- **Nome:** `texto_produto.sugerir_nome_limpo` (a mesma regra da criação de produto pelo XML).
- **Código de barras da UNIDADE**, nesta ordem:
  1. código do app com fator 1;
  2. EAN do vínculo com fator 1;
  3. `EANUnidade` do vínculo;
  4. nota nova;
  5. EAN da caixa (com aviso "confira o da unidade").

  Na caixa, o XML traz o código da caixa em `cEAN` e o da unidade em `cEANTrib`. O
  `nota_xml.py` agora lê `cEANTrib`/`uTrib`/`qTrib`, e o `database` guarda o `cEANTrib` em
  `ProdutosFornecedor.EANUnidade` a cada nota salva (pelo PC e pelo app: `recebimento.py` passa o
  `cEANTrib` adiante). O botão "Códigos de barras das notas antigas"
  (`aprender_codigos_das_notas`) faz o mesmo com os XMLs já guardados.
- **NCM:** produto → vínculo → nota nova.
- **Custo:** nota que está **chegando** (XML na pasta da SEFAZ, ainda não lançado; preço ÷ Qtd/Cx do
  vínculo) se for mais nova que a última compra; senão `ultimos_precos_pagos(com_royalties=False)`;
  senão custo manual.

**Situações:**
- `pendente` (📝 para enviar);
- `enviado` (📤 aguardando a franquia; os valores mandados ficam **congelados**);
- `cadastrado` (✅);
- `nao_vende` (🚫 insumos, embalagens).

Markup em massa e "voltar à sugestão" não mexem em enviado/cadastrado.

**Fluxo do produto novo:**
1. O robô baixa o XML.
2. O Telegram avisa "N produto(s) novo(s) nestas notas".
3. O gestor cria/vincula o produto na aba 3, e o status lembra da aba 9.
4. Na aba 9 o produto aparece em "🚚 Chegando", com custo, código e NCM da nota.
5. O gestor gera a planilha e marca como enviado.
6. Quando a franquia confirmar, marca "✅ Já cadastrado".

Itens das notas novas **sem produto** aparecem numa faixa no topo da aba, com um botão para a aba 3.

**Desempenho:** as notas novas são reconhecidas em memória (`_Reconhecedor`). É a mesma regra do
`buscar_vinculo_inteligente`, com uma consulta só, em vez de uma conexão por item. Medido com 1.200
produtos e 20 notas de 40 itens: 3 conexões e 0,13 s.

**Correção junto:** a janela "Corrigir quantidade e preço" usava um nome inexistente (`janela`) no aviso
de falha do banco (F-15), o que dava NameError só quando o banco caía. Agora usa a própria janela.

**Testes:**
- `teste_franquia_banco.py`: contas, fontes de dados, notas chegando, gravação, planilha, situações,
  códigos antigos, reconhecimento igual ao do `database`, aviso do Telegram;
- `teste_franquia_tela.py`: aba 9 inteira, criação de produto pela aba 3 e preferência da aba.

---

*Documento gerado por leitura integral do código. Para mudar qualquer ponto acima, peça a correção
pelo número (ex.: "corrigir F-03").*

# 🔎 Auditoria da Sugestão de Compra (aba 5 do Gestão de Estoque) — 11/2026

**Escopo:** todo o caminho da sugestão:
1. a conta no banco (`database.calcular_sugestao_compra`);
2. a linha de cada produto (`calcular_linha_sugestao`);
3. a tela da aba 5 (gerar, filtros, ordenação, resumo, avisos);
4. o pedido por fornecedor, o Excel e o 🖨️ PDF;
5. quem usa a mesma conta fora da aba 5 (app de compras e avisos do Telegram/WhatsApp).

**Método:** análise de fluxo (intenção × implementação, rastreio dos dados entre as funções, condições e tratamento de
erros). Cada suspeita foi **reproduzida antes** com um banco de teste (SQLite) e a tela de verdade (Tk). Só depois veio a
correção, e o mesmo teste foi rodado de novo. Testes: `teste_auditoria_sugestao.py` (conta) e
`teste_auditoria_sugestao_tk.py` (tela). Resultado: **14 falhas reproduzidas antes → 0 depois.**

Resumo:

| # | Gravidade | Onde | Problema |
|---|-----------|------|----------|
| 1 | 🔴 Alta | `database.calcular_sugestao_compra` | Modo "desde a 1ª compra": produto comprado há poucos dias pedia 8 a 20 vezes demais |
| 2 | 🔴 Alta | aba 5 (`popular_combos…`, salvar contagem, importar nota, corrigir compra) | Tabela velha sem aviso; o Ponto B pula para a contagem nova sem refazer a conta |
| 3 | 🟠 Média | `sugestao_pdf` / `_dados_impressao_sugestao` | PDF com o Ponto B da lista (novo) e os números da conta antiga |
| 4 | 🟠 Média | `_inteiro_do_campo` | Campo de dias em branco ou errado voltava para 30/2 sem avisar |
| 5 | 🟠 Média | `renderizar_sugestao` | Ponto B antigo: a posição é do passado e nada avisava |
| 6 | 🟡 Baixa | `renderizar_sugestao` | Ponto A fixo a menos de 7 dias do B: o consumo usa outra contagem, sem aviso |
| 7 | 🟡 Baixa | `ordenar_coluna_treeview` | Coluna "Pedir" ordenava como texto (11 cx, 15 cx, 3 cx…) |
| 8 | 🟡 Baixa | `renderizar_sugestao` | O resumo não contava os "nunca contados" (15 produtos, a soma dava 11) |
| 9 | 🟡 Baixa | `database.listar_contagens_cabecalho` | Duas contagens no mesmo dia: ordem ao acaso |

---

## 1. 🔴 Modo "DESDE A PRIMEIRA COMPRA": produto novo recebia sugestão absurda

**Localização:** `database.py` → `calcular_sugestao_compra`, bloco `if modo == 'primeira_compra' …`.

**Causa raiz:**
- Nesse modo, o estoque é considerado **zero no dia anterior à 1ª nota** e o consumo é medido daí até a última contagem.
- O código só exigia que a 1ª compra fosse antes (ou no dia) da contagem: `(d_l - primeira).days >= 0`.
- Não havia o mínimo de 7 dias (`SUGESTAO_DIAS_MINIMOS`) que o resto da conta respeita.
- Com a 1ª compra 2 dias antes, o "período" tinha 3 dias. Comprou 78, contou 70: 8 em 3 dias = 80 por mês.
- Com a 1ª compra **no dia da contagem**, o período era de 1 dia. Comprou 60, contou 55: 5 por dia = 150 por mês.
- Isso acontece com todo produto novo no cardápio, ou com produto cuja 1ª nota importada é recente.

**Reproduzido (antes → depois):**
- Sopa Nova (1ª compra 2 dias antes): pedia **39 cx (234 UN)** → agora **5 cx (30 UN)**.
- Caldo Novo (1ª compra no dia): pedia **85 cx (510 UN)** → agora **4 cx (24 UN)**.
- Produto com 1ª compra antiga: **igual** (controle).

**Solução (implementada):** com menos de 7 dias, o produto fica sem "início" e cai no consumo pelas compras (≈), como
quem tem uma contagem só. A tela já explica isso no "Como calculei".
```python
                if modo == 'primeira_compra' and primeira and primeira <= d_l:
                    contados_antes = [c for c in candidatos if c[0] < primeira]
                    if contados_antes:
                        inicio = contados_antes[0]
                    elif (d_l - primeira).days + 1 >= SUGESTAO_DIAS_MINIMOS:
                        inicio = (primeira - timedelta(days=1), Decimal('0'))
                        item['InicioPrimeiraCompra'] = True
                    # 1ª compra há menos de 7 dias: sem início → consumo pelas compras (≈)
```

## 2. 🔴 Tabela velha sem aviso (e o Ponto B mudando sozinho)

**Localização:** `gestao_estoque_main.py` → `popular_combos_contagem_sugestao` (roda toda vez que se entra na aba 5),
`salvar_contagem_completa`, salvar notas (aba 3) e as duas telas de "corrigir compra".

**Causa raiz:**
- A tabela da aba 5 é uma **foto** da conta feita em "🔄 Gerar".
- Ao salvar uma contagem nova e voltar para a aba 5, a lista do Ponto B **pulava sozinha para a contagem nova**, mas a
  tabela continuava com a conta da anterior. A tela mostrava um Ponto B e números de outro.
- Importar notas ou corrigir uma compra também não avisava. Só a correção pelo duplo clique mostrava uma mensagem.
- Trocar o Ponto A/B à mão também não avisava.
- O "📤 Montar Pedido", o Excel e o PDF saíam com o estoque de antes.
- (Só a **exclusão** de notas/contagens limpava a tabela, em `_invalidar_sugestao`.)

**Solução (implementada):**
- Ao gerar, fica guardado com que Ponto A/B e janela a tabela foi feita.
- Se o Ponto A/B mudar (à mão ou porque chegou contagem nova), ou se salvar contagem / importar nota / corrigir compra,
  aparece **"⚠️ A TABELA É DE ANTES (motivo). Clique em 🔄 Gerar…"**. Ao gerar de novo, o aviso some.
```python
    def _marcar_sugestao_velha(self, motivo):
        if getattr(self, 'resultado_sugestao', None):
            self._sugestao_velha = motivo
            self._atualizar_aviso_sugestao()
    # em gerar_sugestao_compra, depois de calcular:
        self._sugestao_gerada = {'fim': str_fim, 'ini': str_ini, 'janela': params['janela'], 'dia': date.today()}
        self._sugestao_velha = None
    # chamado depois de salvar contagem, importar nota e corrigir compra:
        self._marcar_sugestao_velha("uma contagem nova foi salva")
```
`_avisos_gerais_sugestao()` junta todos os avisos sobre a tabela inteira: este (velha) e os dos itens 5 e 6. Ele é
chamado ao gerar, ao trocar o Ponto A/B, ao mudar os "últimos N dias" e ao entrar na aba.

## 3. 🟠 PDF com o Ponto B errado no cabeçalho

**Localização:** `gestao_estoque_main.py` → `_dados_impressao_sugestao`.

**Causa raiz:** o cabeçalho lia o que estava escrito **na lista na hora de imprimir**, não com o que a tabela foi gerada.
Depois do item 2, o PDF mostrava "Ponto B: 31/10" com os números de 30/10.

**Solução (implementada):** o cabeçalho usa `self._sugestao_gerada`. Se a tabela estiver velha, o aviso também sai no PDF.
```python
        g = getattr(self, '_sugestao_gerada', None) or {}
        ponto_a = g.get('ini', self.combo_contagem_inicio.get())
        ... f"Contagem final (Ponto B): {g.get('fim', self.combo_contagem_fim.get())}"
```

## 4. 🟠 Campo de dias em branco ou errado mudava a conta sem avisar

**Localização:** `gestao_estoque_main.py` → `_inteiro_do_campo` (chamado por `_parametros_sugestao`).

**Causa raiz:**
- Texto inválido (vazio, "2o", 500) voltava para o **padrão do código**: 30 dias a cobrir e **2 dias de prazo**.
- Não voltava para o que a pessoa estava usando, e não avisava.
- Exemplo: com 90 a cobrir e 20 de prazo, apagar sem querer o campo de prazo (ou digitar "2o") recalculava tudo com
  2 dias de prazo, e os "críticos" sumiam.

**Solução (implementada):** volta para o **último valor bom daquele campo** (no começo, o das preferências) e avisa no
rodapé.
```python
    def _inteiro_do_campo(self, campo, padrao, minimo, maximo):
        ultimos = self.__dict__.setdefault('_ultimos_validos', {})
        texto = str(campo.get()).strip()
        if not texto.isdigit() or not (minimo <= int(texto) <= maximo):
            valor = ultimos.get(str(campo), padrao)
            campo.set(str(valor))
            self.status(f"Valor de dias inválido ('{texto}'): voltou para {valor} (vale de {minimo} a {maximo}).", 'aviso')
            return valor
        ultimos[str(campo)] = int(texto)
        return int(texto)
```

## 5. 🟠 Ponto B antigo: a posição é do passado e nada avisava

**Localização:** `database.calcular_sugestao_compra` (`data_ref`) + `renderizar_sugestao` (avisos).

**Causa raiz:**
- Se existe uma contagem mais nova que o Ponto B, a conta fica **na data do Ponto B**, de propósito (para comparar com
  o passado). As notas e o consumo depois dela não entram.
- Isso é comum: depois de uma contagem só de sorvete, a pessoa escolhe a contagem geral anterior "para ver as sopas".
- A tela só avisava o caso contrário ("posição projetada para hoje"). A tabela parecia ser a de hoje, com "acaba em"
  contado a partir de uma data antiga.

**Solução (implementada, sem mudar a conta):** aviso "📅 Posição em dd/mm (a data deste Ponto B), NÃO a de hoje… Para a
posição de hoje, escolha a contagem mais recente como Ponto B (quem não está nela usa a última contagem dele 📏)". Usa o
dia em que a tabela foi gerada, para não dar alarme falso se o programa ficar aberto de um dia para o outro.

## 6. 🟡 Ponto A fixo colado no Ponto B

**Causa raiz:**
- Com o Ponto A a menos de 7 dias do B, nenhum produto pode medir o consumo entre os dois (é o mínimo da conta).
- Cada produto usava, sem avisar, uma contagem **mais antiga** que a escolhida, ou o consumo pelas compras.

**Solução (implementada):** aviso "⚠️ O Ponto A (dd/mm) está a menos de 7 dias do Ponto B… veja o 'Como calculei'".

## 7. 🟡 Ordenar a coluna "Pedir"

**Causa raiz:** "15 cx de 6 (90 UN)" não é número, então a ordem era alfabética: 11 cx, 15 cx, 3 cx, 6 UN.

**Solução (implementada):** `chave_ordenacao_coluna('Pedir', …)` ordena pelo total entre parênteses (ou pelo número do
começo). Vazio conta como 0. As outras colunas e tabelas continuam com a `chave_ordenacao` de sempre.

## 8. 🟡 O resumo não contava os "nunca contados"

Na tela de 15 produtos: 5 críticos + 2 comprar + 4 ok = 11. Os 4 "nunca contados" não apareciam no resumo. Agora aparece
"❔ 4 nunca contado(s)".

## 9. 🟡 Duas contagens no mesmo dia: ordem ao acaso

`ORDER BY C.DataContagem DESC` sem desempate. Agora é `ORDER BY C.DataContagem DESC, C.ContagemID DESC`: a mais nova
vem primeiro e é a escolhida como Ponto B. A conta já somava as contagens do mesmo dia, então os números não mudam.

---

## Conferido e correto (sem mudança)
- **Unidades:** a nota entra no estoque já convertida (quantidade × Qtd/Cx; custo ÷ Qtd/Cx), e a conta soma na mesma
  unidade da contagem. A caixa do pedido vem do vínculo do fornecedor escolhido.
- **Compras no dia da contagem:** contam como "dentro da contagem", de forma igual no início e no fim do período.
- **Consumo negativo** (sobrou mais do que tinha + comprou) vira "⚠️ Conferir", e não zero escondido.
- **Bonificação** (custo zero) não vira o preço do pedido.
- **Fornecedor interno** (CNPJ 000…) fica fora.
- **Produto inativo** fica fora.
- **Royalties** entram no custo.
- Estoque nunca negativo. "Já acabou" e "> 1 ano" corretos. Arredondamento para caixas para cima.
- Excluir notas/contagens limpa a tabela (`_invalidar_sugestao`).
- O app de compras e os avisos usam a mesma conta do banco (modo automático, na contagem mais recente).

## Observações (não são defeito, mas valem saber)
1. **Data da nota = data de emissão.** Uma nota emitida no dia da contagem e entregue depois entra como se já estivesse na
   contagem. O banco não guarda a data de chegada das notas do estoque. Com a conferência do app de compras, dá para
   passar a usar a data conferida (mudança maior, fica como sugestão).
2. **Produto com 1 contagem só:** no app de compras e nos avisos, o consumo usa o MAIOR entre os últimos 90 dias e os
   últimos 12 meses ("aprendendo"). Na aba 5 usa só os 90 dias. Por isso o aviso "acabando" pode não bater exatamente
   com a aba 5 para esses produtos. É intencional (`[MELHORIA APRENDIZADO]`).
3. **Filtro de fornecedor + "Montar Pedido" (fornecedor do filtro):** produto que só tem o vínculo, sem compra desse
   fornecedor, vai para o fornecedor da última compra.
4. **Pedidos já feitos e ainda não entregues** não entram na conta: depois de pedir, a sugestão continua pedindo até a
   nota chegar.
5. `database.gerar_sugestao_por_periodo` é código antigo que ninguém chama (sem efeito).

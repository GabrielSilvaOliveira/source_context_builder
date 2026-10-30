# Emenda 01 ao pré-registro

Data: 2026-10-30. Escrita e commitada **antes de rodar** B, B2 e GPT-4o. Já existem, no momento da emenda, os
resultados da variante A (Llama, 4 condições), obtidos exatamente como pré-registrados; esta emenda não os altera.

## 1. O que motiva a emenda (diagnóstico, fora dos resultados)

Em `diagnostico_B/` (script `diag_B.py`, saída `diagnostico_B.json`), Floor, Llama 3.2 3B, `temperature=0`:

- **Confirmado:** com o schema exato do pré-registro (array sem limite), Q01 não termina. Com `num_predict=512` a
  geração parou por tamanho (`done_reason=length`), com 54 IDs e 15 distintos: o loop é de **fontes distintas
  repetidas em ciclo**, não de espaços em branco (3% de espaços). Q02 termina em 100 tokens com 11 fontes distintas.
- **Confirmado:** o Ollama 0.32.11 **não impõe `uniqueItems`** (enum de 2 IDs, `minItems: 4`, `uniqueItems: true`
  gerou `sql.materiais` repetido até o limite) e **impõe `maxItems`** (`maxItems: 2` devolveu 2 fontes).
- **Confirmado:** com `maxItems: 16` e `uniqueItems: true`, Q01 termina (151 tokens, JSON válido), com 16 IDs e 15
  distintos.
- A variante A (sem schema) também expirou em Q01 no Floor (timeout de 120 s), ou seja, o loop não é exclusivo da B.

Observação de honestidade: a variante A já tinha sido rodada nas 4 condições antes desta emenda; o diagnóstico de B foi
feito antes de qualquer F1 de B, e a decisão sobre B2 e GPT-4o foi tomada sem ver F1 de B.

## 2. Alterações

1. **Variante B (`no_examples_schema`) passa a ter `maxItems: 16` e `uniqueItems: true`** (substitui o schema
   original do pré-registro, que era um array sem limite). `uniqueItems` é declarado, **não imposto** pelo Ollama:
   repetições serão contadas e reportadas. **Sem `num_predict`**, porque o loop não é de espaços em branco. O parser
   fica inalterado. `maxItems 16` é o número de fontes do catálogo (16 nas 4 condições); em Q01 ele apenas interrompe o
   loop, a resposta continua sendo "quase todas as fontes". Não se usa `maxItems 3`.
2. **Variante B2 (`no_examples_schema_cap3`)**: igual à B, com `maxItems: 3`. **Comparação B2 − A**, por condição,
   família própria de 4 testes, Holm, **exploratória, fora da regra de decisão do artigo**. Justificativa: alinhar com o
   teto de 3 fontes dos métodos de pontuação (top-k 3). Decidida após o diagnóstico de 3 consultas e antes de qualquer F1
   de B nas 80.
3. **GPT-4o (Azure), variante A, apenas Curated e Floor**: comparação A − original, família de 2 testes, Holm,
   **descritiva, fora da regra de decisão**. Gasto estimado e autorizado: cerca de US$ 0,40. Ressalva registrada de
   antemão: GPT-4o a `temperature=0` não é totalmente determinístico, então parte de qualquer diferença pode ser
   variação da API; o original não será reexecutado (sem autorização para esse gasto).
4. **Teste primário de A, sem alteração:** exatamente como pré-registrado, com a Q01 de Floor (timeout, seleção vazia)
   contada como vazia. Uma versão sem a Q01 (79 consultas, nos dois lados do par) será reportada **apenas como
   descritiva e declarada como tal**.

## 3. Famílias de teste após a emenda

| Família | Comparação | Testes | Papel |
|---|---|---|---|
| primaria_A_menos_original | A − original, Llama, 4 condições | 4 | decide a regra do artigo |
| secundaria_B_menos_A | B − A, Llama | 4 | dissertação |
| exploratoria_B2_menos_A | B2 − A, Llama | 4 | exploratória |
| descritiva_gpt4o_A_menos_original | A − original, GPT-4o, Curated e Floor | 2 | descritiva |

B − original e B2 − original são apenas descritivos. A regra de decisão do artigo (seção 5 do pré-registro) continua
valendo só para a primeira linha.

## 4. Arquivos desta emenda

`run_llm_benchmark.py` (schema da B com `maxItems`/`uniqueItems`, nova variante `no_examples_schema_cap3`; `original` e
`no_examples` inalteradas, `source_schema` sem argumentos devolve o schema antigo), `diagnostico_B/diag_B.py`,
`diagnostico_B/diagnostico_B.json`, `audit_integridade.py`, `run_variant.sh`.

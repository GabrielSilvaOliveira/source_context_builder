# Pré-registro: ablação do bloco `EXEMPLOS:` no prompt dos seletores generativos

Data de redação: 2026-10-30. Escrito antes de qualquer execução das variantes A e B sobre as 80 consultas.

## 0. Natureza da análise

Esta é uma **análise de sensibilidade feita depois da aceitação** do artigo (ACDSA 2027), **não prevista no desenho
original**. Ela não substitui os números publicados; mede o efeito de um componente do prompt que não foi isolado no
desenho original.

## 1. Motivação (confirmado por leitura do código)

`build_system_prompt` em `benchmark/runners/run_llm_benchmark.py` contém um bloco `EXEMPLOS:` com duas demonstrações
(uma correta e uma errada cada):

- "Qual a situação dos terminais Starlink?" com resposta `api.monitoramento_starlink_list`;
- "Quais contratos estão vigentes?" com resposta `spreadsheets.contratos`.

Elas são paráfrases quase literais das consultas Q07 e Q03 do benchmark (Q08 e Q39 também tratam de Starlink). O bloco
vai para os formatos `full` e `compressed`. O artigo reporta `compressed`.

## 2. Escopo fixo

- Modelo: Llama 3.2 3B (`llama3.2:latest`, id `a80c4f17acd5`), Ollama 0.32.11, `temperature=0`, sem semente
  adicional (igual ao original).
- Formato do catálogo: `compressed`. 80 consultas, 5 dobras, semente 42 (as dobras só agregam `cv_metrics`; o teste usa
  a métrica por consulta).
- Condições e catálogos:

| Condição no artigo | Catálogo |
|---|---|
| Curated | `catalogs/v3/catalog_v3.json` |
| Curated-synth. | `catalogs/v3_doc/catalog_v3_doc_norm.json` |
| Generated | `catalogs/v4/catalog_v4_gen_norm.json` |
| Floor | `catalogs/v4/catalog_v4_min.json` |

- Linha de base ("original"): reproduzida em 2026-10-30, 80/80 seleções idênticas e F1 idêntico por consulta nas quatro
  condições (F1 0,7605 / 0,6506 / 0,6467 / 0,6452). Os arquivos publicados em `results/current/` são a referência e não
  serão reexecutados nem alterados.

## 3. Variantes

- **original:** prompt atual, sem mudança.
- **Variante A (`no_examples`, relevante para o artigo):** o mesmo prompt sem o bloco que vai de `EXEMPLOS:` até a
  linha em branco anterior a `Responda APENAS com o JSON.`. Todo o resto fica byte a byte igual e a decodificação é a
  mesma. Muda uma única coisa.
- **Variante B (`no_examples_schema`, relevante para a dissertação):** variante A mais saída estruturada do Ollama
  (`format` com JSON Schema, `enum` com os 16 `source_id` do catálogo). Muda duas coisas em relação ao original; **não
  serve como verificação dos números do artigo**, serve como desenho futuro do SCB.

**Conteúdo que permanece em A e B (registrado de propósito):** a regra 2 do prompt continua citando IDs reais como
exemplo de formato (`sql.materiais`, `api.distribuicao_list`, `spreadsheets.contratos`). `spreadsheets.contratos` é a
fonte esperada de Q03; essa pista residual não é removida. A frase "Prefira MENOS fontes" e as regras 3 e 4 também
permanecem.

Schema da variante B:
`{"type":"object","properties":{"sources":{"type":"array","items":{"type":"string","enum":[<16 IDs>]}}},"required":["sources"]}`.
Os IDs são gerados do catálogo com a mesma lógica de nomes de `serialize_compressed`.

## 4. Comparações e testes

Ferramenta: `analysis/stat_compare.py`, modo `pairs` (diferença = a − b, bootstrap pareado por id de consulta, 10^4
reamostragens, semente 42, IC 95% percentil, p bicaudal bruto, Holm dentro de cada `familia`, alfa 0,05). Não se
reimplementa nada.

- **Primária (artigo): A − original**, por condição. Família de 4 testes, Holm. Métrica: F1 por consulta.
- **Secundária (dissertação): B − A**, por condição. Família de 4 testes, Holm, **separada** da primária.
- **Descritiva:** B − original (diferença, IC; sem inferência e sem correção, não é um teste da regra de decisão).
- **Métricas secundárias** (exploratórias, mesmo procedimento, uma família de 4 por métrica, sem uso na regra de
  decisão): precisão, recall das primárias, número de fontes por consulta (descritivo), taxa de seleção vazia, taxa de
  `source_id` fora do catálogo, taxa de `must_NOT_include` (`error_rate` do runner).
- **Consultas pré-especificadas para inspeção:** Q03, Q07, Q08, Q39; mais a lista de consultas cuja seleção muda entre
  original e A, por condição e por tipo de dificuldade.
- **Decomposição da Tabela IV sob A** (forma, procedência, total): procedimento e script do artigo a localizar no
  repositório; se o script não existir, para-se e pergunta-se, sem reconstruir.

Tratamento de falhas: se uma chamada ao Ollama falhar ou expirar (120 s), o runner grava seleção vazia (comportamento
do original). Essas consultas são contadas e listadas por arquivo (`error` e `raw_output` por consulta) e reportadas à
parte; as seleções não são corrigidas e o parser não é alterado.

## 5. Regra de decisão para o artigo

Se **nenhuma** diferença A − original for significativa após Holm (p_holm < 0,05) **e** todas tiverem |Δ| < 0,05, o
artigo declara a existência dos exemplos em uma oração, com o Δ. **Caso contrário, o resultado vai para o autor antes
de qualquer texto.** A regra vale só para a comparação primária; B não entra nela.

Leitura prévia dos resultados: p > 0,05 não será descrito como equivalência, e "melhora" ou "piora" só será escrito
com o teste correspondente.

## 6. Divulgação de verificações já feitas

- Fase 0: reprodução da linha de base (80/80 nas quatro condições), sem relação com A ou B.
- Teste do código da Fase 1: `--prompt-variant original` reproduz o sha256 do prompt e as 80 seleções de Floor.
- Teste de fumaça da variante B em Floor com 3 consultas (Q02, Q03, Q01): o schema é aceito pelo Ollama 0.32.11. Q02
  retornou 11 fontes e **Q01 expirou (timeout de 120 s) de forma reprodutível**. Nenhum F1 de A ou B sobre as 80
  consultas foi calculado.

## 7. Pontos em aberto antes da execução

- **Variante B e Q01:** com o schema exato do pedido (array sem limite), Q01 expirou em duas tentativas, o que sugere
  geração sem fim. A decisão sobre limitar a geração (por exemplo `uniqueItems`, `maxItems`, ou `num_predict`) é do
  autor; qualquer alteração do schema será registrada como emenda datada, em commit próprio, antes de rodar B. A
  variante A não é afetada.
- Contadores de tokens: o Ollama devolve `prompt_eval_count` e `eval_count`; o runner passa a gravá-los em campos
  novos. Os campos antigos `prompt_tokens`, `completion_tokens` e `total_tokens` continuam zerados no Ollama, como no
  original, para não alterar o comportamento padrão.

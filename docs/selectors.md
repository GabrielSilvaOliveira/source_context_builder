# Source selectors: configuration

Everything below was read from the code in `src/` and `benchmark/runners/`, or from the result files, and is
labelled where it is not recorded in the repository.

## Common setup

- Benchmark: `benchmark/benchmark_queries_final_v2.json`, 80 queries, 16 sources per catalog.
- Conditions (catalogs): Curated = `catalogs/v3/catalog_v3.json`; Curated-synth. = `catalogs/v3_doc/catalog_v3_doc_norm.json`;
  Generated = `catalogs/v4/catalog_v4_gen_norm.json`; Floor = `catalogs/v4/catalog_v4_min.json`.
- Evaluation: 5-fold cross-validation stratified by difficulty. `random.Random(42)` shuffles the query indices inside
  each difficulty level, and the indices are dealt round-robin into the 5 folds
  (`make_stratified_folds` in `benchmark/runners/run_benchmark_v2.py`; `stratified_folds` in `run_llm_benchmark.py`,
  same procedure). Reported metrics are the mean over folds.
- Top-k = 3 for BM25 and the dense encoders.

## Lexical and dense selectors (`src/bm25_context_builder.py`, `src/semantic_context_builder_v2.py`)

| | BM25 | MiniLM | BGE-M3 |
|---|---|---|---|
| Model / library | `rank_bm25.BM25Okapi` (default parameters; version 0.2.2 in the rerun of Phase 3) | `sentence-transformers/all-MiniLM-L6-v2` | `BAAI/bge-m3` |
| Query and document prefixes | none | none | none |
| Embeddings | none | L2-normalized, cosine = dot product | L2-normalized, cosine = dot product |
| Tokenization | `re.findall(r"\w+", text.lower())` | model tokenizer | model tokenizer |
| Score | `get_scores(query tokens)`, divided by the maximum score of the query (maximum 0 is replaced by 1) | cosine | cosine |
| Default minimum score (registry) | 0.30 | 0.30 | 0.50 |

**Indexed document.** For each source, `name + "\n" + embedding_hint`, where `name` is `Tabela SQL: <table>`,
`API endpoint: <key> (<METHOD> <path>)` or `Planilha: <filename>`. The queries are used as they are. If a source had no
`embedding_hint` (or still had a `[MANUAL]` marker) the code builds the document from `description`, `business_role` and
the first 8 non-generic columns; in the four catalogs of the paper all 16 sources have a hint, so this branch is not used.

**Selection (strategy `score_gap`, no reranker).**
1. Rank the sources by score.
2. Take the first `top_k + 1` = 4 candidates and cut after the largest gap between consecutive scores; keep at most 3
   (at least 1).
3. Drop candidates whose score is below the minimum score of the fold (below).
4. If nothing is left, fall back to all 16 sources.
5. The reranker is disabled (`--reranker` is not passed; `reranker_name=None`).
6. The returned list is ordered by source type (SQL, then API, then spreadsheets), not by score. The `top1_acc` metric
   of the runners therefore looks at the first source of that list.

**Minimum score per fold (calibration).** For each of the 5 folds, the minimum score is chosen on the other 4 folds:
the grid is 0.20, 0.25, …, 0.95 (16 values); for each value the mean per-query F1 over the training queries is
computed; the value with the highest mean F1 wins, and the first one in the grid wins a tie (strict `>`). The chosen
value is then applied to the held-out fold. The chosen values are in `results/thresholds/thresholds_by_fold.csv`
(60 rows) with the grid and the training F1 of every grid point in the JSON files of `results/thresholds/`.
Rerunning with `--log-thresholds` reproduces the published selections: 80/80 identical selections and the same F1
per query in the 12 files (see the root `README.md`).

## Generative selectors (`benchmark/runners/run_llm_benchmark.py`)

Both receive the system prompt below with the catalog serialized in it; the user message is the query text. They have
no threshold, no top-k cap in the original variant, and no calibration; the folds are used only to aggregate the
metrics. The model answer is parsed by `parse_sources` (JSON first; then a regular expression for the JSON object; then
any `sql.`, `api.` or `spreadsheets.` identifiers found in the text). A request error counts as an empty selection.

**Serialization `compressed`** (the one used in the paper's main tables). Header `# FONTES DISPONÍVEIS`, then one line
per source: ``- `<id>` — <hint[:130]>``, where `hint` is `embedding_hint` (or `description` if there is none), cut at
130 characters. Sources whose hint contains `[MANUAL]` are skipped. The serialization `full` (header
`# CATÁLOGO DE FONTES DE DADOS`, with description, role, hint and, for SQL, when-to-use, plus endpoint path and file
name) is also implemented and was run for the supplementary results.

**System prompt, original variant (verbatim from the code):**

```text
Você é um assistente especializado em seleção de fontes de dados logísticos.

Fontes disponíveis:
{catalog_text}

TAREFA: Identifique APENAS as fontes estritamente necessárias para responder à pergunta.

REGRAS OBRIGATÓRIAS:
1. Responda SOMENTE com JSON no formato exato: {"sources": ["source_id"]}
2. Use EXATAMENTE os source_ids listados acima (ex: "sql.materiais", "api.distribuicao_list", "spreadsheets.contratos")
3. Prefira MENOS fontes — inclua uma fonte APENAS se ela for indispensável
4. NÃO adicione fontes "por precaução" ou "podem ser úteis"

EXEMPLOS:
Pergunta: "Qual a situação dos terminais Starlink?"
Correto: {"sources": ["api.monitoramento_starlink_list"]}
Errado:  {"sources": ["api.monitoramento_starlink_list", "sql.materiais"]}

Pergunta: "Quais contratos estão vigentes?"
Correto: {"sources": ["spreadsheets.contratos"]}
Errado:  {"sources": ["spreadsheets.contratos", "api.distribuicao_list"]}

Responda APENAS com o JSON. Nenhum texto adicional.
```

(`{catalog_text}` is the serialization above.) The `EXEMPLOS:` block contains the two examples with a correct and a
wrong answer. The ablation of this block (`--prompt-variant no_examples`, and the variants with structured output) is in
`results/ablation_examples/`: `no_examples` removes the text from `EXEMPLOS:` up to the line `Responda APENAS com o JSON.`,
and the rest of the prompt is byte for byte the same; `no_examples_schema` and `no_examples_schema_cap3` also pass a JSON
schema to Ollama (`maxItems` 16 or 3).

| | Llama 3.2 3B | GPT-4o |
|---|---|---|
| Access | Ollama, model `llama3.2:latest`, `POST /api/chat`, `stream: false` | Azure OpenAI through the `openai` client, model `gpt-4o`, `chat.completions.create` |
| Endpoint | `http://localhost:11434` | `{AZURE_OPENAI_ENDPOINT}/openai/v1` (the unified v1 route) |
| `api_version` | not applicable | **none is sent**: the code uses the v1 route without `api-version` |
| Decoding | `options: {"temperature": 0}`; other options left at the Ollama defaults (no `num_ctx`, no seed) | `temperature=0`, `max_tokens=200` |
| Quantization | Q4_K_M (confirmed with `ollama show llama3.2:latest` on 2026-11-02) | n/a |
| Version | Ollama 0.32.11 and model digest `a80c4f17acd5…` (recorded in the `META` of the ablation runs, in `results/ablation_examples/runs/`) | model snapshot not recorded in the result files |
| Timeout | 120 s per request | client default |

Notes:
- The result files of the original variant (`results/current/`) do not carry the `META` block (prompt hash, Ollama
  version, digest); the ablation runs do. The `NOTA_ARTEFATOS.md` gives the same model id for the published runs.
- The machine is not recorded in any result file. Latency and, for the local model, a few selections can differ between
  machines.
- On Windows run with `PYTHONUTF8=1` (the runner prints non-ASCII characters; without it the console encoding can
  stop the run).
- Credentials are read from `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY` (environment or a git-ignored `.env`).

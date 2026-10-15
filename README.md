# Source Context Builder (SCB)

SCB performs zero-shot semantic pre-selection of heterogeneous data sources — SQL tables/views,
REST API endpoints, and spreadsheets — for a query in natural language, before any call to a
downstream LLM. It is evaluated against a lexical baseline (BM25) and several dense encoders on a
80-query Brazilian-Portuguese logistics benchmark, with stratified 5-fold cross-validation and
paired-bootstrap + Holm-Bonferroni significance testing.

This repository accompanies the paper *"Semantic Context Builder"* (Gabriel Silva de Oliveira,
Ricardo Stracianni Puttini), submitted to ACDSA 2027.

## Repository structure

```
source_context_builder/
├── src/                        # the context builders (selectors)
│   ├── semantic_context_builder.py      # v1
│   ├── semantic_context_builder_v2.py   # v2 (current) — dense encoders + optional reranker
│   ├── bm25_context_builder.py          # lexical baseline, subclasses v2
│   └── context_builder.py               # v1 keyword-routing builder (not used in published results)
├── catalog_generation/         # pipeline that produces the catalogs in catalogs/
│   ├── build_catalog.py / build_catalog_v2.py     # structural extraction (SQL + API + spreadsheets)
│   ├── build_catalog_v4.py / build_catalog_v4_gen.py  # auto-generated catalog (no manual curation)
│   ├── build_catalog_v3_doc.py          # LLM-synthesized descriptors from the v3 manual docs
│   ├── normalizar_preambulo.py          # deterministic cleanup of generated descriptors
│   ├── build_config.example.json        # template — copy to build_config.json with your own credentials
│   └── extractors/                      # SQL / REST API / spreadsheet extractors (v1 + v2)
├── catalogs/                   # the catalogs themselves (data), one directory per version
│   ├── v1/, v2/                         # early iterations
│   ├── v3/                              # reference catalog (manually curated) + truncation variants
│   ├── v3_doc/                          # v3 content, LLM-synthesized descriptors
│   ├── v4/                              # fully auto-generated (base / min / gen)
│   └── verifica_consistencia_catalogos.py
├── benchmark/
│   ├── benchmark_queries_final_v2.json  # the 80-query benchmark (current)
│   ├── previous_versions/               # earlier query set, superseded
│   └── runners/                         # run_benchmark.py, run_benchmark_v2.py, run_benchmark_bm25.py,
│                                         # run_llm_benchmark.py
├── analysis/
│   ├── stat_compare.py                  # paired bootstrap + Holm-Bonferroni
│   └── lexical_overlap.py               # query×catalog lexical-overlap segmentation and interaction test
├── results/
│   ├── current/                         # results reported in the paper
│   └── archive/                         # exploratory/intermediate runs, kept for provenance
└── requirements.txt
```

## Requirements

Python 3.10+. Install dependencies with:

```bash
pip install -r requirements.txt
```

`catalog_generation/build_catalog_v4_gen.py`, `build_catalog_v3_doc.py`, and
`run_llm_benchmark.py --provider ollama` additionally require a local [Ollama](https://ollama.com)
instance with the target model pulled (e.g. `ollama pull qwen2.5:7b`, `ollama pull llama3.2:3b`).
`run_llm_benchmark.py --provider azure` requires `AZURE_OPENAI_ENDPOINT` and
`AZURE_OPENAI_API_KEY` in the environment (or a `.env` file, loaded automatically if
`python-dotenv` is installed).

## Usage

### 1. Building a catalog

`catalog_generation/build_config.example.json` is a template describing the SQL/API/spreadsheet
sources to extract. Copy it to `build_config.json` in the same directory and fill in your own
connection details — that file is git-ignored so credentials are never committed.

```bash
cd catalog_generation
cp build_config.example.json build_config.json   # then edit with your real credentials

# Structural extraction (SQL + API + spreadsheets) → ../catalogs/v1/catalog.json
python build_catalog_v2.py --config build_config.json
python build_catalog_v2.py --config build_config.json --force   # re-extract everything

# Fully automatic catalog (no manual curation)
python build_catalog_v4.py base --config build_config.json --outdir ../catalogs/v4/
python build_catalog_v4.py render-min --base ../catalogs/v4/catalog_v4_base.json \
    --out ../catalogs/v4/catalog_v4_min.json

# LLM-generated descriptors from the neutral base (local Ollama model)
python build_catalog_v4_gen.py --base ../catalogs/v4/catalog_v4_base.json \
    --model qwen2.5:7b --out ../catalogs/v4/catalog_v4_gen.json

# v3-doc: same generator, fed the full manual documentation of catalogs/v3/catalog_v3.json
python build_catalog_v3_doc.py --v3 ../catalogs/v3/catalog_v3.json \
    --model qwen2.5:7b --out ../catalogs/v3_doc/catalog_v3_doc.json

# Deterministic cleanup of scaffolding phrases in generated descriptors
python normalizar_preambulo.py --catalogos ../catalogs/v3_doc/catalog_v3_doc.json \
    ../catalogs/v4/catalog_v4_gen.json
```

`catalogs/v3/catalog_v3.json` itself is not produced by a script — it is `catalog_v2.json` after
manual curation (descriptions, business rules, column-level documentation) and is the reference
catalog for the paper's results.

### 2. Running the benchmark

```bash
cd benchmark/runners

# Dense encoders (minilm, e5-base, e5-large, bge-m3, e5-large-instruct — see MODEL_REGISTRY
# in src/semantic_context_builder_v2.py for the full list and HF model ids)
python run_benchmark_v2.py \
    --catalog   ../../catalogs/v3/catalog_v3.json \
    --benchmark ../benchmark_queries_final_v2.json \
    --models    minilm e5-base e5-large bge-m3 \
    --output    ../../results/current/my_run/ \
    --folds 5 --top-k 3

# BM25 baseline
python run_benchmark_bm25.py \
    --catalog   ../../catalogs/v3/catalog_v3.json \
    --benchmark ../benchmark_queries_final_v2.json \
    --output    ../../results/current/my_run/

# LLM/SLM as selector (Azure GPT-4o or local Ollama model)
python run_llm_benchmark.py \
    --catalog ../../catalogs/v3/catalog_v3.json --benchmark ../benchmark_queries_final_v2.json \
    --provider azure --model gpt-4o --catalog-format both \
    --output ../../results/current/my_run/
```

Each run performs stratified 5-fold cross-validation and writes one `results_<model>.json` per
model to `--output`, in the schema consumed by `analysis/stat_compare.py`.

### 3. Statistical analysis

```bash
cd analysis

# Rank all strategies within one results directory
python stat_compare.py ranking --dir ../results/current/comparativo_resultados \
    --metric f1 --output ranking.csv

# Compare the same strategy across catalog versions
python stat_compare.py ablation \
    --dir v3=../results/current/comparativo_resultados \
    --dir v4-gen=../results/current/resultados_consolidados_fase_e \
    --metric f1 --output ablation.csv

# Lexical-overlap × model interaction test (the paper's central result)
python lexical_overlap.py interaction \
    --results bm25=../results/current/comparativo_resultados/results_bm25_v3.json \
    --results bge-m3=../results/current/comparativo_resultados/results_bge-m3.json \
    --baseline bm25 --catalog ../catalogs/v3/catalog_v3.json --output interaction.csv
```

`stat_compare.py` applies paired bootstrap (10,000 resamples) with Holm-Bonferroni correction
within each family of tests it generates. `lexical_overlap.py` additionally segments queries by
containment between query and gold-source vocabulary and reruns the same test within each band.

## Citation

```
@inproceedings{oliveira2027scb,
  title     = {Semantic Context Builder},
  author    = {Silva de Oliveira, Gabriel and Stracianni Puttini, Ricardo},
  booktitle = {Proceedings of ACDSA 2027},
  year      = {2027}
}
```

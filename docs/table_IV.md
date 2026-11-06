# Reproducing Table IV (decomposition of the curation effect)

Table IV of the paper is generated from the raw `results_*.json` files, with no value typed by hand, and
checked cell by cell against the published values.

```bash
python analysis/reproduzir_tabela_IV.py \
    --input results/current/resultados_consolidados_fase_e \
    --stat-compare analysis/stat_compare.py \
    --out analysis/table_IV_output
```

Exit code 0 if all 20 checks match the published table (15 effects with their significance marks, and
5 latencies), 1 otherwise. Runs in a few seconds. Requires `numpy` and `statsmodels`. The script reuses
`load_per_query_metric`, `paired_bootstrap` and `apply_holm` from `analysis/stat_compare.py` and does not
reimplement any statistic. The checked-in output is in `analysis/table_IV_output/`.

## What the table is

| Column | Definition |
|---|---|
| Form | F1(v3) − F1(v3-doc), paired bootstrap over per-query F1 (n = 80) |
| Provenance | F1(v3-doc) − F1(v4-gen), same test |
| Total | F1(v3) − F1(v4-gen), same test |
| `*` | p_Holm < 0.05, one single Holm family of 15 tests (5 methods × 3 contrasts) |
| Lat. (ms) | arithmetic mean over the 4 conditions of `cv_metrics.latency_ms`; no test |

Sign convention: more curated condition minus less curated condition. A positive value is a loss of F1 when
curation is removed. Bootstrap: 10,000 resamples, seed 42, percentile CI, two-sided p.

## Input files (20)

| Method | v3 | v3-doc | v4-gen | v4-min (latency only) |
|---|---|---|---|---|
| BM25 | `results_bm25_catalog_v3` | `results_bm25_v3_doc_norm` | `results_bm25_v4_gen_norm` | `results_bm25_v4_min` |
| MiniLM | `results_minilm_catalog_v3` | `results_minilm_v3_doc_norm` | `results_minilm_v4_gen_norm` | `results_minilm_v4_min` |
| BGE-M3 | `results_bge-m3_catalog_v3` | `results_bge-m3_v3_doc_norm` | `results_bge-m3_v4_gen_norm` | `results_bge-m3_v4_min` |
| Llama 3.2 3B (`latest`, **compressed**) | `results_ollama_llama3.2_latest_compressed_catalog_v3` | `…_compressed_v3_doc_norm` | `…_compressed_v4_gen_norm` | `…_compressed_v4_min` |
| GPT-4o (**compressed**) | `results_azure_gpt-4o_compressed_catalog_v3` | `…_compressed_catalog_v3_doc_norm` | `…_compressed_v4_gen_norm` | `…_compressed_v4_min` |

All with the `.json` extension, in `results/current/resultados_consolidados_fase_e/`. The script aborts with an
explicit message if a file is missing or ambiguous. `analysis/table_IV_output/manifest.json` records the SHA-256 of
each file used, of `analysis/stat_compare.py`, the Python, numpy and statsmodels versions, and the cell-by-cell check.

## Outputs

| File | Content |
|---|---|
| `tab_IV_final.csv` | the table as it appears in the paper |
| `tab_IV_linhas.tex` | LaTeX rows |
| `tab_IV_auditoria.csv` | the 15 comparisons with difference, 95% CI, raw p, Holm p and significance |
| `tab_IV_latencia.csv` | latency per method and condition, and the mean of the 4 |
| `manifest.json` | traceability (hashes, versions, parameters, check) |

The outputs are identical, byte for byte, to those of the earlier run that produced the published table.
`results/ablation_examples/tabela_IV/saida_llama_A/` holds the same table computed with the Llama outputs of prompt
variant A (examples block removed) in place of the original Llama files.

## Caveats

- **Serialization.** Table IV reproduces only with Llama and GPT-4o in the `compressed` serialization
  (`--variant-llama` and `--variant-gpt`, default `compressed`). With Llama in `full` the row changes
  (Form −0.020, Provenance −0.298\*, Total −0.318\*, latency 2413.0 ms), because Llama `full` collapses on the
  long catalog (F1 0.308 on v3 and 0.328 on v3-doc, against 0.760 and 0.651 with `compressed`). The statement that
  the local generative model loses only by form holds for the `compressed` serialization. The same choice sets the
  "4.6 times" latency ratio (935.4 / 202.6). Whether and where the paper declares the serialization is the author's
  decision (open).
- **Machine.** The result files do not record the machine. Latency comparisons across methods are therefore not
  verifiable from the files alone, and the local model's latency and about 6 of 80 selections are known to differ
  between machines (open).
- **Latency** is a mean of means over heterogeneous conditions (for Llama, 796 to 1175 ms): an order of magnitude,
  not a fixed property of the model. No CI is computed.
- **Edge case.** BM25 Form has p_Holm = 0.0504. Whether it is starred depends on the family being exactly the 15
  tests defined here.

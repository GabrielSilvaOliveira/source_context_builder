#!/bin/bash
# uso: run_variant.sh <variante>
export PYTHONUTF8=1
cd /c/Users/Usuario/Documents/GitHub/source_context_builder
V=$1
for c in catalogs/v3/catalog_v3.json catalogs/v3_doc/catalog_v3_doc_norm.json catalogs/v4/catalog_v4_gen_norm.json catalogs/v4/catalog_v4_min.json; do
  python benchmark/runners/run_llm_benchmark.py --catalog $c --benchmark benchmark/benchmark_queries_final_v2.json --provider ollama --model llama3.2:latest --catalog-format compressed --prompt-variant $V --output results/ablation_examples/runs/$V
done
echo done > results/ablation_examples/runs/$V.DONE

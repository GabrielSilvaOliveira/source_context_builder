#!/bin/bash
# GPT-4o (Azure), variante A, Curated e Floor (autorizado pelo autor; Emenda 01, item 2)
export PYTHONUTF8=1
cd "$(dirname "$0")/../.."
for c in catalogs/v3/catalog_v3.json catalogs/v4/catalog_v4_min.json; do
  python benchmark/runners/run_llm_benchmark.py --catalog $c --benchmark benchmark/benchmark_queries_final_v2.json --provider azure --model gpt-4o --catalog-format compressed --prompt-variant no_examples --output results/ablation_examples/runs/azure_no_examples
done
echo done > results/ablation_examples/runs/azure_no_examples.DONE

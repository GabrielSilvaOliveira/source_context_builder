#!/bin/bash
# Regenera os CSVs de banda e interação sobre o texto consumido (Fig. 1 do artigo) a partir dos
# catálogos e dos resultados de results/current. Uso: bash analysis/reproduzir_bandas.sh <pasta_de_saida>
# Compare com results/overlap_bands/: os 8 arquivos saem idênticos (cmp).
set -e
export PYTHONUTF8=1
OUT=$(realpath -m "${1:-overlap_bands_regen}")
mkdir -p "$OUT"
cd "$(dirname "$0")"
R=../results/current/resultados_consolidados_fase_e
run() {  # apelido  catálogo  sufixo_dos_resultados  [sufixo_do_GPT-4o]
  al=$1; cat=$2; s=$3; g=${4:-$3}
  args=( --baseline bm25
         --results bm25=$R/results_bm25_$s.json
         --results bge-m3=$R/results_bge-m3_$s.json
         --results minilm=$R/results_minilm_$s.json
         --results llama=$R/results_ollama_llama3.2_latest_compressed_$s.json
         --results gpt4o=$R/results_azure_gpt-4o_compressed_$g.json
         --catalog ../catalogs/$cat )
  python inter_consumido.py compare     "${args[@]}" --output "$OUT/tab_bandas_${al}_consumido.csv" > /dev/null
  python inter_consumido.py interaction "${args[@]}" --output "$OUT/tab_inter_${al}_consumido.csv"  > /dev/null
}
run v3        v3/catalog_v3.json            catalog_v3
run v3docnorm v3_doc/catalog_v3_doc_norm.json v3_doc_norm catalog_v3_doc_norm
run v4gen     v4/catalog_v4_gen_norm.json   v4_gen_norm
run v4min     v4/catalog_v4_min.json        v4_min
echo "CSVs em $OUT"

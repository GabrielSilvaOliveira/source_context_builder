#!/usr/bin/env python3
"""
run_benchmark_bm25.py
─────────────────────────────────────────────────────────────────────────────
Runner isolado para o BM25ContextBuilder.

Por que este script existe em vez de estender run_benchmark_v2.py:
  O dispatch de modelo em run_benchmark_v2.py (`main()`) instancia
  SemanticContextBuilderV2 diretamente e resolve hiperparâmetros via
  MODEL_REGISTRY, que não tem entrada para "bm25" (BM25ContextBuilder é uma
  classe à parte, embora compatível por herança). Não achei, nos arquivos do
  projeto, o script que gerou o results_bm25_v3.json original — se você tiver
  o script original, prefira rodá-lo, para manter a metodologia idêntica ao
  v3. Este runner é a reconstrução mais fiel que consigo fazer a partir do
  que está disponível: reusa make_stratified_folds, calibrate_threshold,
  evaluate_fold, aggregate e aggregate_folds de run_benchmark_v2.py sem
  reimplementar nada, e troca só a classe instanciada.

  NÃO modifica run_benchmark_v2.py. Script isolado, não-destrutivo.

Uso
───
  python run_benchmark_bm25.py \
      --catalog ./catalog_v4/catalog_v4_gen.json \
      --benchmark benchmark_queries_final_v2.json \
      --output ./results/

  python run_benchmark_bm25.py \
      --catalog ./catalog_v4/catalog_v4_min.json \
      --benchmark benchmark_queries_final_v2.json \
      --output ./results/
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

try:
    from bm25_context_builder import BM25ContextBuilder
except ImportError as e:
    raise SystemExit(
        "Não foi possível importar BM25ContextBuilder.\n"
        "Este script assume a MESMA estrutura de pastas que run_benchmark_v2.py "
        "já usa (catalog/ como pacote, um nível acima). Coloque "
        "run_benchmark_bm25.py na MESMA pasta onde run_benchmark_v2.py já roda "
        "com sucesso. Se ainda falhar, ajuste o sys.path acima conforme sua "
        f"estrutura real.\nErro original: {e}"
    )

from run_benchmark_v2 import (
    make_stratified_folds, calibrate_threshold, evaluate_fold,
    aggregate, aggregate_folds,
)


def main():
    ap = argparse.ArgumentParser(description="Benchmark BM25 — Stratified K-Fold")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--output", default="./results/")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--strategy", default="score_gap", choices=["score_gap", "threshold"])
    ap.add_argument("--min-similarity", type=float, default=0.30,
                    help="Threshold inicial (padrão do BM25ContextBuilder: 0.30)")
    ap.add_argument("--log-thresholds", action="store_true",
                    help="Grava a grade, o limiar escolhido e o F1 de treino de cada fold "
                         "(chave threshold_by_fold). Não altera a seleção.")
    ap.add_argument("--tag", default="bm25",
                    help="Sufixo do arquivo de saída, ex.: bm25_v4gen, bm25_v4min")
    args = ap.parse_args()

    Path(args.output).mkdir(parents=True, exist_ok=True)

    with open(args.benchmark, encoding="utf-8") as f:
        queries = json.load(f)["queries"]

    folds = make_stratified_folds(queries, n_folds=args.folds, seed=args.seed)

    print(f"\n{'='*65}")
    print(f"  BENCHMARK — BM25ContextBuilder (Stratified {args.folds}-Fold CV)")
    print(f"  Catálogo    : {args.catalog}")
    print(f"  Queries     : {len(queries)}")
    print(f"  Estratégia  : {args.strategy}")
    print(f"{'='*65}")

    cb = BM25ContextBuilder(
        catalog_path=args.catalog, top_k=args.top_k,
        min_similarity=args.min_similarity, selection_strategy=args.strategy,
    )
    cb.rebuild_index(verbose=True)

    fold_metrics_list, all_test_results, threshold_log = [], [], []

    for fold_i, test_idx in enumerate(folds):
        train_idx = [i for f, idxs in enumerate(folds) for i in idxs if f != fold_i]
        train_queries = [queries[i] for i in train_idx]
        test_queries = [queries[i] for i in test_idx]

        _trace = {} if args.log_thresholds else None
        threshold = calibrate_threshold(cb, train_queries, trace=_trace)
        if _trace is not None:
            threshold_log.append({"fold": fold_i + 1, **_trace})
        fold_results = evaluate_fold(cb, test_queries, threshold)
        fold_agg = aggregate(fold_results)

        print(f"  Fold {fold_i+1}: threshold={threshold:.2f}  "
              f"F1={fold_agg['f1']:.3f}  P={fold_agg['precision']:.3f}  "
              f"R={fold_agg['recall']:.3f}")

        fold_metrics_list.append(fold_agg)
        all_test_results.extend(fold_results)

    summary = aggregate_folds(fold_metrics_list)
    print(f"\n  MÉDIA (±dp entre folds): F1={summary['f1']:.3f}±{summary['f1_std']:.3f}  "
          f"P={summary['precision']:.3f}±{summary['precision_std']:.3f}  "
          f"R={summary['recall']:.3f}±{summary['recall_std']:.3f}")

    out = {
        "model": "bm25", "catalog": args.catalog, "strategy": args.strategy,
        "folds": args.folds, "seed": args.seed, "top_k": args.top_k,
        "summary": summary,
        "per_query": all_test_results,
    }
    if args.log_thresholds:
        out["threshold_by_fold"] = threshold_log
    out_path = Path(args.output) / f"results_{args.tag}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[✓] Resultados: {out_path}")


if __name__ == "__main__":
    main()

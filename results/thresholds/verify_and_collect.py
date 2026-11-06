#!/usr/bin/env python3
"""Confere que a rerodada com registro de limiares reproduz os resultados publicados
(mesmas seleções, na mesma ordem, e mesmo F1 por consulta) e reúne os limiares por fold.

Uso (da raiz do repositório):
    python results/thresholds/verify_and_collect.py
Saídas: results/thresholds/thresholds_by_fold.csv e results/thresholds/reproduction_check.csv
Código de saída 0 se os 12 arquivos reproduzem, 1 caso contrário.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUB = ROOT / "results/current/resultados_consolidados_fase_e"
NEW = ROOT / "results/thresholds"

# condição -> sufixo do arquivo publicado (BM25, MiniLM, BGE-M3 usam estes nomes)
CONDITIONS = {"v3": "catalog_v3", "v3_doc_norm": "v3_doc_norm",
              "v4_gen_norm": "v4_gen_norm", "v4_min": "v4_min"}
METHODS = {"BM25": ("bm25", "bm25"), "MiniLM": ("minilm", "minilm"), "BGE-M3": ("bge-m3", "bge-m3")}


def per_query(j):
    return j.get("all_results") or j["per_query"]


check_rows, thr_rows, ok_all = [], [], True
for cond, suf in CONDITIONS.items():
    for label, (new_name, pub_prefix) in METHODS.items():
        pub = json.loads((PUB / f"results_{pub_prefix}_{suf}.json").read_text(encoding="utf-8"))
        new = json.loads((NEW / cond / f"results_{new_name}.json").read_text(encoding="utf-8"))
        a = {r["id"]: r for r in per_query(pub)}
        b = {r["id"]: r for r in per_query(new)}
        same_ids = set(a) == set(b)
        same_sel = sum(1 for q in a if q in b and a[q]["selected"] == b[q]["selected"])
        same_set = sum(1 for q in a if q in b and set(a[q]["selected"]) == set(b[q]["selected"]))
        same_f1 = sum(1 for q in a if q in b and abs(a[q]["f1"] - b[q]["f1"]) < 1e-9)
        ok = same_ids and same_sel == len(a) == 80 and same_f1 == 80
        ok_all &= ok
        check_rows.append({"method": label, "condition": cond, "n": len(a),
                           "same_selection_and_order": same_sel, "same_selected_set": same_set,
                           "same_f1_per_query": same_f1,
                           "cv_f1_published": pub["cv_metrics"]["f1"] if "cv_metrics" in pub else pub["summary"]["f1"],
                           "cv_f1_new": new["cv_metrics"]["f1"] if "cv_metrics" in new else new["summary"]["f1"],
                           "reproduces": ok})
        for rec in new.get("threshold_by_fold", []):
            thr_rows.append({"method": label, "condition": cond, "fold": rec["fold"],
                             "threshold": rec["chosen_threshold"],
                             "train_f1": round(rec["train_f1"], 4)})

with open(NEW / "reproduction_check.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(check_rows[0]))
    w.writeheader(); w.writerows(check_rows)
with open(NEW / "thresholds_by_fold.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["method", "condition", "fold", "threshold", "train_f1"])
    w.writeheader(); w.writerows(thr_rows)

print(f"{'method':8s} {'condition':12s} {'sel+ordem':>9s} {'conjunto':>9s} {'F1/consulta':>11s} {'F1 pub':>7s} {'F1 novo':>7s}")
for r in check_rows:
    print(f"{r['method']:8s} {r['condition']:12s} {r['same_selection_and_order']:>6d}/80 {r['same_selected_set']:>6d}/80 "
          f"{r['same_f1_per_query']:>8d}/80 {r['cv_f1_published']:>7.4f} {r['cv_f1_new']:>7.4f}  {'OK' if r['reproduces'] else 'FALHA'}")
print(f"\n{len(thr_rows)} limiares gravados; reproduz tudo: {ok_all}")
sys.exit(0 if ok_all else 1)

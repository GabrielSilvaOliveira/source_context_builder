#!/usr/bin/env python3
"""Recall das fontes primárias do gabarito, por anotador.

Uma primária do gabarito (expected_primary) conta como recuperada se o anotador a marcou
como P ou C (variante principal) ou só como P (variante estrita). Para cada consulta o recall
é (primárias recuperadas) / (primárias do gabarito); o valor reportado é a média simples
(macro) sobre as consultas anotadas.

Uso:
    python recall_primarias.py --labels labels.csv --benchmark ../benchmark/benchmark_queries_final_v2.json
"""
import argparse
import csv
import json
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--labels", default="labels.csv")
ap.add_argument("--benchmark", default="../benchmark/benchmark_queries_final_v2.json")
ap.add_argument("--saida", default=None, help="JSON opcional")
args = ap.parse_args()

gold = {q["id"]: set(q["expected_primary"])
        for q in json.load(open(args.benchmark, encoding="utf-8"))["queries"]}

lab = defaultdict(dict)  # annotator -> (q, s) -> label
for r in csv.DictReader(open(args.labels, encoding="utf-8")):
    lab[r["annotator"]][(r["query_id"], r["source_id"])] = r["label"]


def recall(a, aceitos):
    qids = sorted({q for q, _ in lab[a]})
    vals = []
    for q in qids:
        prim = gold[q]
        ok = sum(1 for s in prim if lab[a].get((q, s), "N") in aceitos)
        vals.append(ok / len(prim))
    return sum(vals) / len(vals), len(qids)


res = {}
print(f"{'anotador':9s} {'consultas':>9s} {'recall P ou C':>14s} {'recall só P':>12s}")
for a in sorted(lab):
    rpc, n = recall(a, ("P", "C"))
    rp, _ = recall(a, ("P",))
    res[a] = {"n_consultas": n, "recall_P_ou_C": round(rpc, 4), "recall_so_P": round(rp, 4)}
    print(f"{a:9s} {n:9d} {rpc:14.3f} {rp:12.3f}")
if args.saida:
    json.dump(res, open(args.saida, "w", encoding="utf-8"), indent=2)

"""Auditoria de integridade dos arquivos de resultado da ablação (só conta; não corrige o parser).

uso: python audit_integridade.py <variante> [<variante> ...]   (rodar da raiz do repositório)
"""
import json, sys
from pathlib import Path

sys.path.insert(0, "benchmark/runners")
import run_llm_benchmark as r

CATS = {"Curated": ("catalog_v3", "catalogs/v3/catalog_v3.json", "catalog_v3"),
        "Curated-synth.": ("v3_doc_norm", "catalogs/v3_doc/catalog_v3_doc_norm.json", "catalog_v3_doc_norm"),
        "Generated": ("v4_gen_norm", "catalogs/v4/catalog_v4_gen_norm.json", "catalog_v4_gen_norm"),
        "Floor": ("v4_min", "catalogs/v4/catalog_v4_min.json", "catalog_v4_min")}
PUB = "results/current/resultados_consolidados_fase_e/results_ollama_llama3.2_latest_compressed_%s.json"
bench_ids = [q["id"] for q in json.load(open("benchmark/benchmark_queries_final_v2.json", encoding="utf-8"))["queries"]]

print("variante | condição | n | ids alinhados | vazias | fora do catálogo (consultas / IDs) | repetidas | erros | F1 cv | F1 média por consulta | F1 original publicado")
for variant in sys.argv[1:]:
    for cond, (pub_key, cpath, stem) in CATS.items():
        f = Path(f"results/ablation_examples/runs/{variant}/results_ollama_llama3.2_latest_compressed_{stem}__{variant}.json")
        d = json.load(open(f, encoding="utf-8"))
        valid = set(r.compressed_source_ids(json.load(open(cpath, encoding="utf-8"))))
        res = d["all_results"]
        pub = json.load(open(PUB % pub_key, encoding="utf-8"))
        ids_ok = sorted(x["id"] for x in res) == sorted(bench_ids) and len(res) == 80
        empty = sum(1 for x in res if not x["selected"])
        bad_q = sum(1 for x in res if any(s not in valid for s in x["selected"]))
        bad_n = sum(1 for x in res for s in x["selected"] if s not in valid)
        dup = sum(1 for x in res if len(set(x["selected"])) != len(x["selected"]))
        err = sum(1 for x in res if x.get("error"))
        mean_f1 = sum(x["f1"] for x in res) / len(res)
        m = d["META"]
        assert m["prompt_variant"] == variant and m["git_dirty"] is False, (f, m["git_dirty"])
        print(f"{variant} | {cond} | {len(res)} | {ids_ok} | {empty} | {bad_q}/{bad_n} | {dup} | {err} | "
              f"{d['cv_metrics']['f1']:.4f} | {mean_f1:.4f} | {pub['cv_metrics']['f1']:.4f}")

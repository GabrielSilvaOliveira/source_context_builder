"""Fase 3: análise da ablação dos exemplos. Usa analysis/stat_compare.py (modo pairs) para todo teste.

Rodar da raiz do repositório:  PYTHONUTF8=1 python results/ablation_examples/analise_ablacao.py
Saídas: results/ablation_examples/tabelas/*.csv e results/ablation_examples/tabelas/resumo.json
"""
import csv, json, subprocess, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "benchmark/runners")
import run_llm_benchmark as rl

ROOT = Path("results/ablation_examples")
RUNS, TAB, DER = ROOT / "runs", ROOT / "tabelas", ROOT / "derivados"
for d in (TAB, DER):
    d.mkdir(exist_ok=True)
PUB = Path("results/current/resultados_consolidados_fase_e")
COND = {  # nome no artigo: (chave publicada, stem do catálogo, caminho do catálogo)
    "Curated": ("catalog_v3", "catalog_v3", "catalogs/v3/catalog_v3.json"),
    "Curated-synth.": ("v3_doc_norm", "catalog_v3_doc_norm", "catalogs/v3_doc/catalog_v3_doc_norm.json"),
    "Generated": ("v4_gen_norm", "catalog_v4_gen_norm", "catalogs/v4/catalog_v4_gen_norm.json"),
    "Floor": ("v4_min", "catalog_v4_min", "catalogs/v4/catalog_v4_min.json"),
}


def path(var, cond):
    pub, stem, _ = COND[cond]
    if var == "original":
        return PUB / f"results_ollama_llama3.2_latest_compressed_{pub}.json"
    if var == "gpt4o_original":
        return PUB / f"results_azure_gpt-4o_compressed_{pub}.json"
    if var == "gpt4o_A":
        return RUNS / "azure_no_examples" / f"results_azure_gpt-4o_compressed_{stem}__no_examples.json"
    return RUNS / var / f"results_ollama_llama3.2_latest_compressed_{stem}__{var}.json"


def load(var, cond):
    p = path(var, cond)
    return json.load(open(p, encoding="utf-8")) if p.exists() else None


def per_query(var, cond):
    d = load(var, cond)
    return {x["id"]: x for x in d["all_results"]} if d else None


def stat_pairs(familia, entries, metric, out_name):
    """entries: [(nome, path_a, path_b)] -> chama stat_compare.py pairs; devolve linhas."""
    cfg = TAB / f"_cfg_{out_name}.json"
    json.dump([{"nome": n, "familia": familia, "a": str(a), "b": str(b)} for n, a, b in entries],
              open(cfg, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out = TAB / f"{out_name}.csv"
    subprocess.run([sys.executable, "analysis/stat_compare.py", "pairs", "--config", str(cfg),
                    "--metric", metric, "--output", str(out)], check=True, capture_output=True)
    cfg.unlink()
    return list(csv.DictReader(open(out, encoding="utf-8")))


def derive_without(var, cond, qid):
    """Cópia derivada (não altera o original) sem a consulta qid, só para a análise descritiva."""
    d = load(var, cond)
    d["all_results"] = [x for x in d["all_results"] if x["id"] != qid]
    p = DER / f"{path(var, cond).stem}__sem_{qid}.json"
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return p


def fmt(rows, cols=("comparacao", "n_queries", "diff", "ci_low", "ci_high", "p_raw", "p_holm", "significativo_holm")):
    return [{c: r[c] for c in cols} for r in rows]


summary = {}
for metric in ("f1", "precision", "recall", "error_rate"):
    tag = "" if metric == "f1" else f"_{metric}"
    # primária (e as mesmas métricas secundárias, exploratórias): A - original
    ents = [(f"{c}: A - original", path("no_examples", c), path("original", c)) for c in COND]
    summary[f"primaria_A_menos_original{tag}"] = fmt(stat_pairs("primaria_A_menos_original", ents, metric,
                                                                 f"primaria_A_menos_original{tag}"))
    for var, fam in (("no_examples_schema", "B"), ("no_examples_schema_cap3", "B2")):
        if all(path(var, c).exists() for c in COND):
            ents = [(f"{c}: {fam} - A", path(var, c), path("no_examples", c)) for c in COND]
            summary[f"{'secundaria' if fam == 'B' else 'exploratoria'}_{fam}_menos_A{tag}"] = fmt(
                stat_pairs(f"{'secundaria' if fam == 'B' else 'exploratoria'}_{fam}_menos_A", ents, metric,
                           f"{'secundaria' if fam == 'B' else 'exploratoria'}_{fam}_menos_A{tag}"))
            ents = [(f"{c}: {fam} - original", path(var, c), path("original", c)) for c in COND]
            summary[f"descritiva_{fam}_menos_original{tag}"] = fmt(
                stat_pairs(f"descritiva_{fam}_menos_original", ents, metric, f"descritiva_{fam}_menos_original{tag}"))
    # GPT-4o (Curated, Floor)
    g = [c for c in ("Curated", "Floor") if path("gpt4o_A", c).exists()]
    if g:
        ents = [(f"GPT-4o {c}: A - original", path("gpt4o_A", c), path("gpt4o_original", c)) for c in g]
        summary[f"descritiva_gpt4o_A_menos_original{tag}"] = fmt(
            stat_pairs("descritiva_gpt4o_A_menos_original", ents, metric, f"descritiva_gpt4o_A_menos_original{tag}"))

# sem Q01 (descritiva, declarada): Floor A - original em 79 consultas
a79, o79 = derive_without("no_examples", "Floor", "Q01"), derive_without("original", "Floor", "Q01")
summary["descritiva_Floor_A_menos_original_sem_Q01"] = fmt(
    stat_pairs("descritiva_sem_Q01", [("Floor sem Q01: A - original", a79, o79)], "f1", "descritiva_Floor_sem_Q01"))

# decomposição da Tabela IV (forma, procedência, total): sem Holm, ver relatório (família do artigo não verificada)
for var, nome in (("original", "original"), ("no_examples", "A")):
    ents = [(f"Llama {nome}: forma (Curated - Curated-synth.)", path(var, "Curated"), path(var, "Curated-synth.")),
            (f"Llama {nome}: procedencia (Curated-synth. - Generated)", path(var, "Curated-synth."), path(var, "Generated")),
            (f"Llama {nome}: total (Curated - Generated)", path(var, "Curated"), path(var, "Generated"))]
    summary[f"decomposicao_tabelaIV_{nome}"] = fmt(stat_pairs(f"decomp_{nome}", ents, "f1", f"decomposicao_tabelaIV_{nome}"))

# descritivos por variante: médias, taxas
valid = {c: set(rl.compressed_source_ids(json.load(open(COND[c][2], encoding="utf-8")))) for c in COND}
desc = []
for var in ("original", "no_examples", "no_examples_schema", "no_examples_schema_cap3"):
    for c in COND:
        pq = per_query(var, c)
        if not pq:
            continue
        R = list(pq.values())
        n = len(R)
        desc.append({
            "variante": var, "condicao": c, "n": n,
            "f1": round(sum(x["f1"] for x in R) / n, 4),
            "precisao": round(sum(x["precision"] for x in R) / n, 4),
            "recall_primarias": round(sum(x["recall"] for x in R) / n, 4),
            "fontes_por_consulta": round(sum(len(x["selected"]) for x in R) / n, 3),
            "vazias": sum(1 for x in R if not x["selected"]),
            "id_invalido_consultas": sum(1 for x in R if any(s not in valid[c] for s in x["selected"])),
            "com_repetidas": sum(1 for x in R if len(set(x["selected"])) != len(x["selected"])),
            "must_NOT_include_taxa": round(sum(x["error_rate"] for x in R) / n, 4),
            "erros_timeout": sum(1 for x in R if x.get("error")),
        })
w = csv.DictWriter(open(TAB / "descritivos_por_variante.csv", "w", newline="", encoding="utf-8"), fieldnames=list(desc[0]))
w.writeheader(); w.writerows(desc)
summary["descritivos_por_variante"] = desc

# por consulta: seleções que mudaram entre original e A, por condição e dificuldade
chg, by_diff = {}, {}
for c in COND:
    o, a = per_query("original", c), per_query("no_examples", c)
    rows, dd = [], defaultdict(lambda: {"n": 0, "mudou": 0, "dF1_soma": 0.0})
    for q in o:
        dd[o[q]["difficulty"]]["n"] += 1
        dd[o[q]["difficulty"]]["dF1_soma"] += a[q]["f1"] - o[q]["f1"]
        if o[q]["selected"] != a[q]["selected"]:
            dd[o[q]["difficulty"]]["mudou"] += 1
            rows.append({"id": q, "dificuldade": o[q]["difficulty"], "f1_orig": o[q]["f1"], "f1_A": a[q]["f1"],
                         "orig": o[q]["selected"], "A": a[q]["selected"], "esperado": o[q]["expected_primary"]})
    chg[c] = rows
    by_diff[c] = {k: {"n": v["n"], "mudou": v["mudou"], "dF1_medio": round(v["dF1_soma"] / v["n"], 4)} for k, v in dd.items()}
summary["selecoes_que_mudaram"] = chg
summary["por_dificuldade"] = by_diff
summary["consultas_foco"] = {
    q: {c: {"orig": per_query("original", c)[q]["selected"], "A": per_query("no_examples", c)[q]["selected"],
            "esperado": per_query("original", c)[q]["expected_primary"],
            "f1_orig": per_query("original", c)[q]["f1"], "f1_A": per_query("no_examples", c)[q]["f1"]} for c in COND}
    for q in ("Q03", "Q07", "Q08", "Q39")}
json.dump(summary, open(TAB / "resumo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok", sorted(summary))

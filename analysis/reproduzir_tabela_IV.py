#!/usr/bin/env python3
"""
reproduzir_tabela_IV.py
────────────────────────────────────────────────────────────────────────
Reproduz a Tabela IV (tab:decomp) do artigo SCB/ACDSA 2027 a partir dos
results_*.json brutos, sem nenhum número digitado à mão:

  Form        = F1(v3)     - F1(v3-doc)     (efeito de FORMA)
  Provenance  = F1(v3-doc) - F1(v4-gen)     (efeito de PROCEDÊNCIA)
  Total       = F1(v3)     - F1(v4-gen)
  Lat. (ms)   = média aritmética, sobre as 4 condições, de
                cv_metrics.latency_ms de cada método

Convenção de sinal: diferença = condição mais curada MENOS condição menos
curada. Valor positivo = perda de F1 ao remover curadoria.

Estatística: reusa, SEM reimplementar, as funções do stat_compare.py do
projeto (load_per_query_metric, paired_bootstrap, apply_holm). Bootstrap
pareado de 10.000 reamostras, seed 42, IC percentílico; Holm numa ÚNICA
família de 15 comparações (5 métodos x 3 contrastes), como no artigo.

Uso
───
  python reproduzir_tabela_IV.py --input Resultados_finais_dos_catalogos.zip \
         --stat-compare ./stat_compare.py --out ./saida_tabela_IV

  (--input aceita .zip ou diretório; --stat-compare default = ao lado deste
   script. As variantes dos geradores são --variant-llama e --variant-gpt,
   default 'compressed', que é a que reproduz o artigo.)

Código de saída: 0 se todas as células conferem com o publicado; 1 se não.
Requisitos: pip install numpy statsmodels
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import platform
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ─────────────────────────────────────────────────────────────────────────
# DEFINIÇÃO DO DESENHO (isto É o desenho declarado no artigo)
# ─────────────────────────────────────────────────────────────────────────

# Ordem de linhas = ordem da Tabela IV publicada.
# prefixo do arquivo results_<prefixo>[_<variante>]_<sufixo>.json
MODELS = [
    # rótulo,        prefixo,                  usa_variante
    ("BM25",         "bm25",                   None),
    ("Llama 3.2 3B", "ollama_llama3.2_latest", "llama"),
    ("BGE-M3",       "bge-m3",                 None),
    ("GPT-4o",       "azure_gpt-4o",           "gpt"),
    ("MiniLM",       "minilm",                 None),
]

# Condição -> sufixos aceitos no nome do arquivo (os nomes não são uniformes
# entre métodos: GPT-4o e MiniLM/BM25 usam 'catalog_v3_doc_norm' ou 'v3_doc_norm').
CONDITIONS = {
    "v3":     ["catalog_v3"],
    "v3-doc": ["v3_doc_norm", "catalog_v3_doc_norm"],
    "v4-gen": ["v4_gen_norm"],
    "v4-min": ["v4_min"],   # só entra na latência, não na decomposição
}

# Contrastes da decomposição: (nome, condição_a, condição_b), diff = a - b
CONTRASTS = [
    ("Form",       "v3",     "v3-doc"),
    ("Provenance", "v3-doc", "v4-gen"),
    ("Total",      "v3",     "v4-gen"),
]

# Valores PUBLICADOS no .tex (scb_acdsa_2027_vf_publicada.tex, tab:decomp).
# Usados só para conferência (--check); nunca entram no cálculo.
PUBLISHED = {
    "BM25":         dict(Form=0.146,  Provenance=0.156,  Total=0.301,  Lat=0.1,
                         stars=dict(Form=False, Provenance=False, Total=True)),
    "Llama 3.2 3B": dict(Form=0.110,  Provenance=0.004,  Total=0.114,  Lat=935.4,
                         stars=dict(Form=True,  Provenance=False, Total=True)),
    "BGE-M3":       dict(Form=0.062,  Provenance=0.070,  Total=0.131,  Lat=202.6,
                         stars=dict(Form=False, Provenance=False, Total=False)),
    "GPT-4o":       dict(Form=0.014,  Provenance=0.080,  Total=0.094,  Lat=1305.0,
                         stars=dict(Form=False, Provenance=False, Total=False)),
    "MiniLM":       dict(Form=-0.027, Provenance=-0.052, Total=-0.079, Lat=13.9,
                         stars=dict(Form=False, Provenance=False, Total=False)),
}

N_BOOT = 10_000
SEED = 42
ALPHA = 0.05


# ─────────────────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────────────────────────────────

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_stat_compare(path: Path):
    """Importa o stat_compare.py do projeto pelo caminho (funciona com python -I)."""
    if not path.exists():
        sys.exit(f"[!] stat_compare.py não encontrado em {path}. "
                 f"Passe --stat-compare <caminho>.")
    spec = importlib.util.spec_from_file_location("stat_compare", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("load_per_query_metric", "paired_bootstrap", "apply_holm"):
        if not hasattr(mod, fn):
            sys.exit(f"[!] {path} não expõe {fn}(); versão incompatível.")
    return mod


def index_results(input_path: Path, workdir: Path) -> dict[str, Path]:
    """Mapeia nome-de-arquivo -> caminho para todo results_*.json (zip ou diretório)."""
    found: dict[str, Path] = {}
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(input_path) as z:
            for info in z.infolist():
                base = Path(info.filename).name        # só o basename (sem zip-slip)
                if not re.fullmatch(r"results_.*\.json", base):
                    continue
                if base in found:
                    sys.exit(f"[!] Nome duplicado no ZIP: {base}")
                dest = workdir / base
                dest.write_bytes(z.read(info))
                found[base] = dest
    elif input_path.is_dir():
        for p in sorted(input_path.rglob("results_*.json")):
            if p.name in found:
                sys.exit(f"[!] Nome duplicado em {input_path}: {p.name}")
            found[p.name] = p
    else:
        sys.exit(f"[!] --input deve ser um .zip ou um diretório: {input_path}")
    if not found:
        sys.exit("[!] Nenhum results_*.json encontrado na entrada.")
    return found


def resolve(files: dict[str, Path], prefix: str, variant: str | None, cond: str) -> Path:
    cands = []
    for suf in CONDITIONS[cond]:
        mid = f"_{variant}" if variant else ""
        cands.append(f"results_{prefix}{mid}_{suf}.json")
    hits = [c for c in cands if c in files]
    if len(hits) != 1:
        sys.exit(f"[!] Esperava exatamente 1 arquivo para {prefix}/{variant}/{cond}; "
                 f"candidatos={cands}; encontrados={hits}")
    return files[hits[0]]


# ─────────────────────────────────────────────────────────────────────────
# NÚCLEO
# ─────────────────────────────────────────────────────────────────────────

def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help=".zip ou diretório com results_*.json")
    ap.add_argument("--stat-compare", default=str(here / "stat_compare.py"))
    ap.add_argument("--out", default="./saida_tabela_IV")
    ap.add_argument("--variant-llama", default="compressed", choices=["compressed", "full"])
    ap.add_argument("--variant-gpt", default="compressed", choices=["compressed", "full"])
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--no-check", action="store_true",
                    help="não compara com os valores publicados no .tex")
    args = ap.parse_args()

    sc = load_stat_compare(Path(args.stat_compare))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    variants = {"llama": args.variant_llama, "gpt": args.variant_gpt}

    with tempfile.TemporaryDirectory() as tmp:
        files = index_results(Path(args.input), Path(tmp))

        # 1) Resolve os 5 x 4 arquivos de entrada
        paths: dict[tuple[str, str], Path] = {}
        for label, prefix, vkey in MODELS:
            variant = variants[vkey] if vkey else None
            for cond in CONDITIONS:
                paths[(label, cond)] = resolve(files, prefix, variant, cond)

        # 2) F1 por consulta -> contrastes (família única de 15)
        rows = []
        for label, _, _ in MODELS:
            f1 = {c: sc.load_per_query_metric(paths[(label, c)], "f1")
                  for c in ("v3", "v3-doc", "v4-gen")}
            for name, ca, cb in CONTRASTS:
                r = sc.paired_bootstrap(f1[ca], f1[cb], n_boot=args.n_boot, seed=args.seed)
                rows.append({"modelo": label, "contraste": name,
                             "comparacao": f"{label}: {name} ({ca} - {cb})",
                             "familia": "decomposicao_15", **r})
        assert len(rows) == 15, "a família declarada tem 15 comparações"
        rows = sc.apply_holm(rows, alpha=ALPHA)

        # 3) Latência: cv_metrics.latency_ms por condição, média das 4
        lat_rows = []
        lat_mean = {}
        for label, _, _ in MODELS:
            vals = {}
            for c in CONDITIONS:
                j = json.loads(paths[(label, c)].read_text(encoding="utf-8"))
                vals[c] = float(j["cv_metrics"]["latency_ms"])
            lat_mean[label] = sum(vals.values()) / len(vals)
            lat_rows.append({"modelo": label, **{c: round(v, 4) for c, v in vals.items()},
                             "media_4_condicoes": round(lat_mean[label], 4)})

        # 4) Manifesto de rastreabilidade (hash de cada entrada usada)
        used = sorted({p.name: p for p in paths.values()}.items())
        manifest = {
            "gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "statsmodels": __import__("statsmodels").__version__,
            "stat_compare": {"path": Path(args.stat_compare).as_posix(),
                             "sha256": sha256(Path(args.stat_compare))},
            "input": {"path": Path(args.input).as_posix(),
                      "sha256": sha256(Path(args.input)) if Path(args.input).is_file() else None},
            "parametros": {"n_boot": args.n_boot, "seed": args.seed, "alpha": ALPHA,
                           "holm": "uma familia de 15", "metrica": "f1 por consulta (n=80)",
                           "variantes": variants},
            "arquivos_usados": [{"nome": n, "sha256": sha256(p)} for n, p in used],
        }

    # ─────────────────────────────────────────────────────────────────────
    # SAÍDAS
    # ─────────────────────────────────────────────────────────────────────
    cell = {(r["modelo"], r["contraste"]): r for r in rows}

    # (a) auditoria completa (IC, p bruto, p Holm)
    fields = ["comparacao", "familia", "n_queries", "diff", "ci_low", "ci_high",
              "p_raw", "p_holm", "significativo_holm"]
    with open(out / "tab_IV_auditoria.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in fields})

    # (b) latência por condição
    with open(out / "tab_IV_latencia.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["modelo", *CONDITIONS, "media_4_condicoes"])
        w.writeheader()
        w.writerows(lat_rows)

    # (c) tabela como aparece no artigo + conferência com o publicado
    check = []
    ok_all = True
    with open(out / "tab_IV_final.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Model", "Form", "Provenance", "Total", "Lat_ms"])
        for label, _, _ in MODELS:
            vals = [cell[(label, n)]["diff"] for n, _, _ in CONTRASTS]
            w.writerow([label, *[f"{v:+.3f}" for v in vals], f"{lat_mean[label]:.1f}"])
            pub = PUBLISHED[label]
            for (n, _, _), v in zip(CONTRASTS, vals):
                r = cell[(label, n)]
                ok_v = abs(round(v, 3) - pub[n]) < 1e-9
                ok_s = bool(r["significativo_holm"]) == pub["stars"][n]
                check.append({"modelo": label, "celula": n, "calculado": round(v, 3),
                              "publicado": pub[n], "valor_ok": ok_v,
                              "asterisco_calculado": bool(r["significativo_holm"]),
                              "asterisco_publicado": pub["stars"][n], "asterisco_ok": ok_s})
                ok_all &= ok_v and ok_s
            ok_l = abs(round(lat_mean[label], 1) - pub["Lat"]) < 1e-9
            check.append({"modelo": label, "celula": "Lat_ms",
                          "calculado": round(lat_mean[label], 1), "publicado": pub["Lat"],
                          "valor_ok": ok_l, "asterisco_calculado": "", "asterisco_publicado": "",
                          "asterisco_ok": True})
            ok_all &= ok_l

    # (d) linhas LaTeX prontas para comparar com o .tex
    with open(out / "tab_IV_linhas.tex", "w", encoding="utf-8") as f:
        for label, _, _ in MODELS:
            parts = []
            for n, _, _ in CONTRASTS:
                r = cell[(label, n)]
                star = "^{*}" if r["significativo_holm"] else ""
                parts.append(f"${r['diff']:+.3f}{star}$")
            f.write(f"{label} & " + " & ".join(parts) + f" & {lat_mean[label]:.1f} \\\\\n")

    manifest["conferencia_com_publicado"] = {"todas_as_celulas_conferem": ok_all, "celulas": check}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                       encoding="utf-8")

    # console
    print(f"\nTabela IV reproduzida (diff = mais curado - menos curado; * = p_Holm<{ALPHA}, família de 15)\n")
    print(f"{'Modelo':<14}{'Form':>10}{'Provenance':>13}{'Total':>10}{'Lat(ms)':>10}")
    for label, _, _ in MODELS:
        c = [cell[(label, n)] for n, _, _ in CONTRASTS]
        s = [f"{x['diff']:+.3f}{'*' if x['significativo_holm'] else ' '}" for x in c]
        print(f"{label:<14}{s[0]:>10}{s[1]:>13}{s[2]:>10}{lat_mean[label]:>10.1f}")
    bad = [c for c in check if not (c["valor_ok"] and c["asterisco_ok"])]
    if args.no_check:
        print("\n[i] Conferência com o publicado desligada (--no-check).")
        sys.exit(0)
    if bad:
        print(f"\n[FALHA] {len(bad)} célula(s) divergem do .tex:")
        for c in bad:
            print("   ", c)
        sys.exit(1)
    print(f"\n[OK] As {len(check)} conferências (15 efeitos, 5 latências e asteriscos) "
          f"batem com o .tex publicado.")
    print(f"[✓] Saídas em: {out.as_posix()}")


if __name__ == "__main__":
    main()

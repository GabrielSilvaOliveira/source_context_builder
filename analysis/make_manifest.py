#!/usr/bin/env python3
"""Gera MANIFEST.sha256 (formato do sha256sum) com os arquivos que sustentam o artigo:
catálogos, benchmark, os 20 resultados da Tabela III e os demais resultados usados, rótulos do IAA,
scripts de análise e anotação, limiares e saídas derivadas. Rodar da raiz do repositório:
    python analysis/make_manifest.py
Para conferir: sha256sum -c MANIFEST.sha256
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = [
    "catalogs/**/*.json",
    "benchmark/benchmark_queries_final_v2.json",
    "benchmark/runners/*.py",
    "src/*.py",
    "analysis/*.py",
    "analysis/*.sh",
    "analysis/table_IV_output/*",
    "annotation/*",
    "results/current/resultados_consolidados_fase_e/*.json",
    "results/current/comparativo_resultados/*",
    "results/current/tabelas_soltas/*",
    "results/overlap_bands/*",
    "results/thresholds/**/*.json",
    "results/thresholds/*.csv",
    "results/thresholds/*.py",
    "results/ablation_examples/**/*",
    "docs/*.md",
    "NOTA_ARTEFATOS.md",
]
files = sorted({p for pat in INCLUDE for p in ROOT.glob(pat) if p.is_file()
                and "__pycache__" not in p.parts and p.name != "MANIFEST.sha256"})
lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}" for p in files]
(ROOT / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"{len(lines)} arquivos em MANIFEST.sha256")

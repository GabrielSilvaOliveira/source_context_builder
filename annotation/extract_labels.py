#!/usr/bin/env python3
"""Extrai os rótulos das planilhas de anotação para um CSV longo.

Uso (as planilhas preenchidas NÃO fazem parte do repositório):
    python extract_labels.py --planilha A=/caminho/IAA_Anotador_A.xlsx \
        --planilha B=... --planilha C=... --planilha D=... --saida labels.csv

Colunas: annotator, query_id, source_id, label (P, C ou N; N = célula em branco).
Só os rótulos são lidos; metadados e a aba «Fontes» das planilhas não são copiados.
"""
import argparse
import csv

from calcular_iaa import ler_planilha

ap = argparse.ArgumentParser()
ap.add_argument("--planilha", action="append", required=True, help="LETRA=caminho.xlsx")
ap.add_argument("--saida", default="labels.csv")
args = ap.parse_args()

linhas = []
ordem_fontes = None
for item in args.planilha:
    letra, caminho = item.split("=", 1)
    anot, sids, _, _ = ler_planilha(caminho)
    if ordem_fontes is None:
        ordem_fontes = sids
    assert sids == ordem_fontes, f"ordem de fontes divergente em {letra}"
    for qid in sorted({q for q, _ in anot}):
        for sid in sids:
            linhas.append((letra, qid, sid, anot[(qid, sid)]))

with open(args.saida, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["annotator", "query_id", "source_id", "label"])
    w.writerows(linhas)
print(f"{len(linhas)} linhas -> {args.saida}")

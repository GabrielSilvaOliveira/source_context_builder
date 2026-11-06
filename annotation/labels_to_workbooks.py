#!/usr/bin/env python3
"""Reconstrói, a partir de labels.csv, planilhas mínimas no layout que calcular_iaa.py lê.

Permite rodar calcular_iaa.py (sem alteração) a partir dos rótulos publicados.
As planilhas geradas têm só a aba «Anotação» (cabeçalho na linha 4, dados a partir da 6)
e a coluna «Revisado» vazia; não são as planilhas entregues aos anotadores.

Uso:
    python labels_to_workbooks.py --labels labels.csv --saida-dir tmp_planilhas --anotadores A B C
Gera tmp_planilhas/IAA_<letra>.xlsx.
"""
import argparse
import csv
from pathlib import Path

from openpyxl import Workbook

ap = argparse.ArgumentParser()
ap.add_argument("--labels", default="labels.csv")
ap.add_argument("--saida-dir", required=True)
ap.add_argument("--anotadores", nargs="+", required=True)
args = ap.parse_args()

rows = list(csv.DictReader(open(args.labels, encoding="utf-8")))
out = Path(args.saida_dir)
out.mkdir(parents=True, exist_ok=True)

for a in args.anotadores:
    sel = [r for r in rows if r["annotator"] == a]
    if not sel:
        raise SystemExit(f"anotador {a} ausente em {args.labels}")
    sids, qids = [], []
    for r in sel:
        if r["source_id"] not in sids:
            sids.append(r["source_id"])
        if r["query_id"] not in qids:
            qids.append(r["query_id"])
    lab = {(r["query_id"], r["source_id"]): r["label"] for r in sel}
    wb = Workbook()
    ws = wb.active
    ws.title = "Anotação"
    ws.cell(row=4, column=1, value="ID")
    ws.cell(row=4, column=2, value="Pergunta")
    for k, sid in enumerate(sids):
        ws.cell(row=4, column=3 + k, value=sid)
    ws.cell(row=4, column=3 + len(sids), value="Revisado")
    for i, q in enumerate(qids):
        r = 6 + i
        ws.cell(row=r, column=1, value=q)
        for k, sid in enumerate(sids):
            v = lab[(q, sid)]
            if v in ("P", "C"):
                ws.cell(row=r, column=3 + k, value=v)
    wb.save(out / f"IAA_{a}.xlsx")
print("ok")

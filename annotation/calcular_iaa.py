#!/usr/bin/env python3
"""
calcular_iaa.py
─────────────────────────────────────────────────────────────────────────────
Calcula a concordância entre anotadores a partir das planilhas preenchidas.

Reporta DUAS coisas diferentes, que respondem a perguntas diferentes:

  (A) Concordância ENTRE os anotadores independentes  -> a tarefa é bem
      definida? É o número que vai na Metodologia como "IAA".
  (B) Concordância de cada anotador COM o gabarito     -> o gabarito é
      idiossincrático do autor, ou reproduzível? Valida o gold standard.

Métricas:
  - Kappa de Fleiss (3 classes P/C/N e binária relevante/não) entre anotadores
  - Kappa de Cohen par a par, incluindo cada anotador contra o gabarito
  - Concordância bruta
  - F1 médio par a par entre CONJUNTOS de fontes selecionadas

Por que o F1 de conjuntos também: com 16 fontes e ~2 relevantes por consulta,
a classe "não usar" domina (~87%). Nessa prevalência extrema o kappa sofre do
chamado paradoxo do kappa, podendo sair baixo mesmo com concordância alta. O
F1 de conjuntos ignora as concordâncias triviais em "não usar" e é diretamente
comparável à métrica do próprio benchmark. Reportar os dois é o honesto.

Uso:
  python calcular_iaa.py --planilhas material_iaa/IAA_*.xlsx \
                         --benchmark benchmark_queries_final_v2.json
"""

import argparse
import glob
import itertools
import json
from collections import Counter

from openpyxl import load_workbook

LIN_CAB = 4
PRIM_DADOS = 6          # linha 5 é o EXEMPLO
CLASSES = ("P", "C", "N")


def ler_planilha(caminho):
    """Devolve {(query_id, source_id): 'P'|'C'|'N'} e a lista de revisadas."""
    wb = load_workbook(caminho, data_only=True)
    ws = wb["Anotação"]

    fontes, col_rev = [], None
    for c in range(3, ws.max_column + 1):
        v = ws.cell(row=LIN_CAB, column=c).value
        if v == "Revisado":
            col_rev = c
            break
        if v:
            fontes.append((c, v))

    anot, revisadas, sem_primaria = {}, [], []
    for r in range(PRIM_DADOS, ws.max_row + 1):
        qid = ws.cell(row=r, column=1).value
        if not qid or not str(qid).startswith("Q"):
            continue
        if col_rev and ws.cell(row=r, column=col_rev).value == "Sim":
            revisadas.append(qid)
        tem_p = False
        for c, sid in fontes:
            v = (ws.cell(row=r, column=c).value or "").strip().upper()
            v = v if v in ("P", "C") else "N"
            if v == "P":
                tem_p = True
            anot[(qid, sid)] = v
        if not tem_p:
            sem_primaria.append(qid)

    return anot, [s for _, s in fontes], revisadas, sem_primaria


def ler_gabarito(caminho, qids, sids):
    q = {x["id"]: x for x in json.load(open(caminho, encoding="utf-8"))["queries"]}
    gab = {}
    for qid in qids:
        prim = set(q[qid].get("expected_primary", []))
        comp = set(q[qid].get("expected_complement", []))
        for sid in sids:
            gab[(qid, sid)] = "P" if sid in prim else ("C" if sid in comp else "N")
    return gab


# ── estatísticas ─────────────────────────────────────────────────────────────

def kappa_cohen(a, b, chaves):
    n = len(chaves)
    if n == 0:
        return float("nan")
    po = sum(1 for k in chaves if a[k] == b[k]) / n
    ca, cb = Counter(a[k] for k in chaves), Counter(b[k] for k in chaves)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in set(ca) | set(cb))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def kappa_fleiss(anotacoes, chaves, classes=CLASSES):
    """anotacoes: lista de dicts (um por anotador)."""
    n_rat = len(anotacoes)
    N = len(chaves)
    if n_rat < 2 or N == 0:
        return float("nan")
    P_i, p_j = [], Counter()
    for k in chaves:
        cont = Counter(a[k] for a in anotacoes)
        for c in classes:
            p_j[c] += cont[c]
        soma = sum(cont[c] * (cont[c] - 1) for c in classes)
        P_i.append(soma / (n_rat * (n_rat - 1)))
    P_barra = sum(P_i) / N
    pj = {c: p_j[c] / (N * n_rat) for c in classes}
    Pe = sum(v * v for v in pj.values())
    return (P_barra - Pe) / (1 - Pe) if Pe < 1 else float("nan")


def binarizar(d):
    return {k: ("R" if v in ("P", "C") else "N") for k, v in d.items()}


def f1_conjuntos(a, b, qids, sids, apenas_primaria=False):
    """F1 médio por consulta entre os CONJUNTOS de fontes marcadas."""
    alvo = ("P",) if apenas_primaria else ("P", "C")
    f1s = []
    for qid in qids:
        sa = {s for s in sids if a[(qid, s)] in alvo}
        sb = {s for s in sids if b[(qid, s)] in alvo}
        if not sa and not sb:
            f1s.append(1.0)
            continue
        inter = len(sa & sb)
        p = inter / len(sa) if sa else 0.0
        r = inter / len(sb) if sb else 0.0
        f1s.append(2 * p * r / (p + r) if (p + r) else 0.0)
    return sum(f1s) / len(f1s) if f1s else float("nan")


def interpretar(k):
    if k != k:
        return "indefinido"
    for lim, txt in ((0.0, "pobre"), (0.20, "leve"), (0.40, "razoável"),
                     (0.60, "moderada"), (0.80, "substancial"), (1.01, "quase perfeita")):
        if k < lim:
            return txt
    return "quase perfeita"


# ── principal ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planilhas", nargs="+", required=True)
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--saida", default="resultado_iaa.json")
    args = ap.parse_args()

    caminhos = []
    for p in args.planilhas:
        caminhos.extend(sorted(glob.glob(p)))
    if len(caminhos) < 2:
        raise SystemExit("[X] São necessárias ao menos 2 planilhas preenchidas.")

    anot, nomes, sids_ref = {}, [], None
    print("=" * 66)
    print("AUDITORIA DE COMPLETUDE")
    print("=" * 66)
    for c in caminhos:
        nome = c.split("IAA_")[-1].replace(".xlsx", "")
        d, sids, rev, sem_p = ler_planilha(c)
        sids_ref = sids_ref or sids
        if sids != sids_ref:
            raise SystemExit(f"[X] {nome}: ordem de fontes divergente. Planilha alterada?")
        qids_local = sorted({q for q, _ in d})
        print(f"  {nome:16s} {len(qids_local)} consultas · {len(rev)} revisadas"
              + (f" · ⚠ {len(sem_p)} sem primária: {sem_p}" if sem_p else ""))
        anot[nome] = d
        nomes.append(nome)

    qids = sorted({q for d in anot.values() for q, _ in d})
    chaves = [(q, s) for q in qids for s in sids_ref]
    print(f"\n  {len(qids)} consultas × {len(sids_ref)} fontes = {len(chaves)} julgamentos/anotador")

    prev = Counter(anot[nomes[0]][k] for k in chaves)
    tot = sum(prev.values())
    print(f"  Prevalência (anotador {nomes[0]}): "
          + " · ".join(f"{c}={prev[c]} ({100*prev[c]/tot:.0f}%)" for c in CLASSES))

    res = {"n_consultas": len(qids), "n_fontes": len(sids_ref), "anotadores": nomes}

    print("\n" + "=" * 66)
    print("(A) CONCORDÂNCIA ENTRE ANOTADORES  — a tarefa é bem definida?")
    print("=" * 66)
    kf3 = kappa_fleiss([anot[n] for n in nomes], chaves)
    kf2 = kappa_fleiss([binarizar(anot[n]) for n in nomes], chaves, classes=("R", "N"))
    print(f"  Kappa de Fleiss, 3 classes (P/C/N) : {kf3:.3f}  ({interpretar(kf3)})")
    print(f"  Kappa de Fleiss, binária (rel./não): {kf2:.3f}  ({interpretar(kf2)})")
    res["fleiss_3classes"], res["fleiss_binaria"] = round(kf3, 4), round(kf2, 4)

    print("\n  Par a par (Cohen / concordância bruta / F1 de conjuntos):")
    pares = []
    for a, b in itertools.combinations(nomes, 2):
        k = kappa_cohen(anot[a], anot[b], chaves)
        po = sum(1 for x in chaves if anot[a][x] == anot[b][x]) / len(chaves)
        f1 = f1_conjuntos(anot[a], anot[b], qids, sids_ref)
        f1p = f1_conjuntos(anot[a], anot[b], qids, sids_ref, apenas_primaria=True)
        print(f"    {a} × {b}: κ={k:.3f} · bruta={po:.3f} · F1={f1:.3f} · F1(prim.)={f1p:.3f}")
        pares.append({"par": f"{a}×{b}", "kappa": round(k, 4),
                      "bruta": round(po, 4), "f1": round(f1, 4), "f1_primaria": round(f1p, 4)})
    res["pares_anotadores"] = pares
    if pares:
        res["f1_medio_anotadores"] = round(sum(p["f1"] for p in pares) / len(pares), 4)

    print("\n" + "=" * 66)
    print("(B) CADA ANOTADOR × GABARITO  — o gabarito é reproduzível?")
    print("=" * 66)
    gab = ler_gabarito(args.benchmark, qids, sids_ref)
    vs = []
    for n in nomes:
        k = kappa_cohen(anot[n], gab, chaves)
        po = sum(1 for x in chaves if anot[n][x] == gab[x]) / len(chaves)
        f1 = f1_conjuntos(anot[n], gab, qids, sids_ref)
        f1p = f1_conjuntos(anot[n], gab, qids, sids_ref, apenas_primaria=True)
        print(f"  {n:16s} κ={k:.3f} ({interpretar(k)}) · bruta={po:.3f} · "
              f"F1={f1:.3f} · F1(prim.)={f1p:.3f}")
        vs.append({"anotador": n, "kappa": round(k, 4), "bruta": round(po, 4),
                   "f1": round(f1, 4), "f1_primaria": round(f1p, 4)})
    res["vs_gabarito"] = vs
    res["f1_medio_vs_gabarito"] = round(sum(v["f1"] for v in vs) / len(vs), 4)

    print("\n" + "=" * 66)
    print("CONSULTAS COM MAIOR DISCORDÂNCIA (revisar manualmente)")
    print("=" * 66)
    disc = []
    for qid in qids:
        d = sum(1 for s in sids_ref
                if len({anot[n][(qid, s)] for n in nomes}) > 1)
        disc.append((d, qid))
    for d, qid in sorted(disc, reverse=True)[:5]:
        print(f"  {qid}: {d} fonte(s) com divergência entre anotadores")
    res["discordancia_por_consulta"] = {q: d for d, q in sorted(disc, reverse=True)}

    json.dump(res, open(args.saida, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\n[✓] Resultado salvo em {args.saida}")
    print("\nPara o artigo: reportar o kappa de Fleiss (A) como IAA, e o F1 médio")
    print("contra o gabarito (B) como evidência de que o gold standard não é")
    print("idiossincrático. Se o kappa vier baixo mas a concordância bruta e o F1")
    print("altos, reportar os três e citar o paradoxo do kappa por prevalência.")


if __name__ == "__main__":
    main()

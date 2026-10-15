#!/usr/bin/env python3
"""
verifica_consistencia_catalogos.py

Checkpoint de consistência entre versões de catálogo (v3, v3-doc-norm,
v4-gen-norm, v4-min). Empacota as três verificações feitas manualmente na
investigação do descasamento de colunas em spreadsheets.fornecimento
(v3 mascarado x v4 nao-mascarado).

Uso:
    # Verificacao 1 + 3: compara nomes de coluna e varre o hint por termos
    python verifica_consistencia_catalogos.py \
        --catalogo-referencia catalog_v3.json \
        --catalogo catalog_v4_gen_norm.json \
        --catalogo catalog_v4_min.json \
        --termos-suspeitos OM RM SIGELOG TREM ODF Diex

    # Verificacao 2: impacto no benchmark de uma fonte especifica
    python verifica_consistencia_catalogos.py \
        --benchmark benchmark_queries_final_v2.json \
        --fonte-afetada spreadsheets.fornecimento \
        --fonte-afetada sql.materiais

Sem argumentos de termo, usa a lista default relevante a este projeto.
Saida: relatorio em texto no stdout. Codigo de saida 1 se alguma
divergencia estrutural for encontrada (para uso em pipeline/CI).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_TERMOS_SUSPEITOS = [
    "OM de", "RM de", "SIGELOG", "TREM", "ODF", "Diex",
    "Retifica a OF", "Escalão", "Batalhão", "Brigada", "Regimento",
    "Companhia", "Pelotão", "Quartel", "militar", "SISCOFIS",
]


# --------------------------------------------------------------------------
# Carregamento e navegação do catalogo
# --------------------------------------------------------------------------

def carregar_catalogo(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def iter_fontes(catalogo: dict):
    """Itera (chave_fonte, meta_dict) para todas as fontes de um catalogo,
    independente da modalidade (sql/api/spreadsheets)."""
    src = catalogo.get("sources", {})
    for modalidade, payload in src.items():
        if not isinstance(payload, dict):
            continue
        for grupo, itens in payload.items():
            if not isinstance(itens, dict):
                continue
            for nome, meta in itens.items():
                if isinstance(meta, dict):
                    yield f"{modalidade}.{nome}", meta


def extrair_colunas(meta: dict) -> list[str]:
    """Extrai nomes de coluna/campo de uma fonte, cobrindo os tres formatos
    encontrados no projeto: sql.columns, api.response_schema.result_object_fields,
    spreadsheets.sheets[*].columns."""
    sheets = meta.get("sheets")
    if isinstance(sheets, dict):
        acc: list[str] = []
        for aba in sheets.values():
            cols = aba.get("columns") if isinstance(aba, dict) else None
            if isinstance(cols, dict):
                acc += list(cols.keys())
            elif isinstance(cols, list):
                acc += list(cols)
        return acc

    cols = meta.get("columns")
    if isinstance(cols, dict):
        return list(cols.keys())
    if isinstance(cols, list):
        return list(cols)

    rof = (meta.get("response_schema") or {}).get("result_object_fields")
    if isinstance(rof, dict):
        return list(rof.keys())

    return []


def extrair_hint(meta: dict) -> str:
    return str(meta.get("embedding_hint") or "")


# --------------------------------------------------------------------------
# Verificacao 1: divergencia estrutural de nomes de coluna
# --------------------------------------------------------------------------

def verificar_estrutura(ref_path: Path, alvo_path: Path) -> tuple[bool, list[str]]:
    """Compara nomes de coluna fonte a fonte entre um catalogo de
    referencia e um catalogo alvo. Retorna (ok, linhas_de_relatorio)."""
    ref = dict(iter_fontes(carregar_catalogo(ref_path)))
    alvo = dict(iter_fontes(carregar_catalogo(alvo_path)))

    linhas = []
    ok = True
    todas_chaves = sorted(set(ref) | set(alvo))

    for chave in todas_chaves:
        if chave not in ref:
            linhas.append(f"  [!] fonte '{chave}' existe em {alvo_path.name} mas nao em {ref_path.name}")
            ok = False
            continue
        if chave not in alvo:
            linhas.append(f"  [!] fonte '{chave}' existe em {ref_path.name} mas nao em {alvo_path.name}")
            ok = False
            continue

        cols_ref = extrair_colunas(ref[chave])
        cols_alvo = extrair_colunas(alvo[chave])

        # colunas nao aplicavel (ex.: fonte sem coluna declarada nos dois lados)
        if not cols_ref and not cols_alvo:
            continue

        if set(cols_ref) != set(cols_alvo):
            ok = False
            so_ref = sorted(set(cols_ref) - set(cols_alvo))
            so_alvo = sorted(set(cols_alvo) - set(cols_ref))
            linhas.append(f"  [DIVERGE] {chave}  ({len(cols_ref)} vs {len(cols_alvo)} colunas)")
            if so_ref:
                linhas.append(f"       so em {ref_path.name}: {so_ref}")
            if so_alvo:
                linhas.append(f"       so em {alvo_path.name}: {so_alvo}")

    if ok:
        linhas.append(f"  [OK] {len(todas_chaves)} fontes, nomes de coluna identicos.")

    return ok, linhas


# --------------------------------------------------------------------------
# Verificacao 3: contaminacao do texto consumido (embedding_hint)
# --------------------------------------------------------------------------

def verificar_hints(catalogo_path: Path, termos: list[str]) -> tuple[bool, list[str]]:
    """Varre o embedding_hint de cada fonte por termos suspeitos (siglas
    institucionais, nomenclatura militar, etc). Retorna (ok, linhas)."""
    catalogo = carregar_catalogo(catalogo_path)
    linhas = []
    ok = True

    for chave, meta in iter_fontes(catalogo):
        hint = extrair_hint(meta)
        if not hint:
            continue
        achados = [
            t for t in termos
            if re.search(r"(?<![A-Za-zÀ-ÿ])" + re.escape(t) + r"(?![A-Za-zÀ-ÿ])", hint, re.IGNORECASE)
        ]
        if achados:
            ok = False
            linhas.append(f"  [CONTAMINADO] {chave}  ({len(hint)} ch)  termos: {achados}")
            trecho = hint[:200] + ("..." if len(hint) > 200 else "")
            linhas.append(f"       hint: {trecho}")

    if ok:
        linhas.append(f"  [OK] nenhum termo suspeito encontrado no embedding_hint de nenhuma fonte.")

    return ok, linhas


# --------------------------------------------------------------------------
# Verificacao 2: impacto no benchmark de fontes afetadas
# --------------------------------------------------------------------------

def verificar_impacto_benchmark(bench_path: Path, fontes_afetadas: list[str]) -> list[str]:
    with open(bench_path, encoding="utf-8") as f:
        raw = json.load(f)
    queries = raw if isinstance(raw, list) else (raw.get("queries") or raw.get("benchmark") or [])

    linhas = [f"  total de consultas no benchmark: {len(queries)}"]
    uniao_positivo: set[str] = set()

    for fonte in fontes_afetadas:
        prim, comp, proib = [], [], []
        for q in queries:
            qid = q.get("id")
            if any(fonte in s for s in (q.get("expected_primary") or [])):
                prim.append(qid)
            if any(fonte in s for s in (q.get("expected_complement") or [])):
                comp.append(qid)
            if any(fonte in s for s in (q.get("must_NOT_include") or [])):
                proib.append(qid)

        positivo = set(prim) | set(comp)
        uniao_positivo |= positivo

        linhas.append(f"\n  fonte: {fonte}")
        linhas.append(f"    primaria     : {len(prim)}  {prim}")
        linhas.append(f"    complementar : {len(comp)}  {comp}")
        linhas.append(f"    proibida     : {len(proib)}  {proib}")
        linhas.append(f"    gabarito positivo (primaria uniao complementar): {len(positivo)} consultas")

    linhas.append(
        f"\n  UNIAO de todas as fontes informadas, no gabarito positivo: "
        f"{len(uniao_positivo)} de {len(queries)} consultas "
        f"({len(uniao_positivo) / len(queries) * 100:.0f}%)"
    )
    return linhas


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalogo-referencia", type=Path, default=None,
                     help="Catalogo tomado como correto (ex.: catalog_v3.json). "
                          "Se informado, roda a Verificacao 1 (estrutura) contra cada --catalogo.")
    ap.add_argument("--catalogo", type=Path, action="append", default=[],
                     help="Catalogo(s) a verificar contra a referencia e/ou varrer por termos suspeitos. "
                          "Pode repetir a flag para varios arquivos.")
    ap.add_argument("--termos-suspeitos", nargs="*", default=None,
                     help="Termos a buscar no embedding_hint (Verificacao 3). "
                          "Default: lista pre-definida do projeto.")
    ap.add_argument("--pular-verificacao-hints", action="store_true",
                     help="Nao roda a Verificacao 3 (contaminacao de hint).")
    ap.add_argument("--benchmark", type=Path, default=None,
                     help="Caminho do benchmark_queries_final_v2.json. "
                          "Se informado, roda a Verificacao 2 (impacto).")
    ap.add_argument("--fonte-afetada", action="append", default=[],
                     help="Chave de fonte (ex.: spreadsheets.fornecimento) para medir impacto no benchmark. "
                          "Pode repetir a flag para varias fontes.")
    args = ap.parse_args()

    termos = args.termos_suspeitos if args.termos_suspeitos is not None else DEFAULT_TERMOS_SUSPEITOS

    algum_problema = False
    rodou_algo = False

    if args.catalogo_referencia and args.catalogo:
        rodou_algo = True
        print("=" * 78)
        print("VERIFICACAO 1 — divergencia estrutural de nomes de coluna")
        print(f"referencia: {args.catalogo_referencia}")
        print("=" * 78)
        for alvo in args.catalogo:
            print(f"\n--- {args.catalogo_referencia.name}  vs  {alvo.name} ---")
            ok, linhas = verificar_estrutura(args.catalogo_referencia, alvo)
            print("\n".join(linhas))
            algum_problema = algum_problema or not ok

    if args.catalogo and not args.pular_verificacao_hints:
        rodou_algo = True
        print("\n" + "=" * 78)
        print("VERIFICACAO 3 — contaminacao do texto consumido (embedding_hint)")
        print(f"termos buscados: {termos}")
        print("=" * 78)
        for cat in args.catalogo:
            print(f"\n--- {cat.name} ---")
            ok, linhas = verificar_hints(cat, termos)
            print("\n".join(linhas))
            algum_problema = algum_problema or not ok

    if args.benchmark:
        rodou_algo = True
        print("\n" + "=" * 78)
        print("VERIFICACAO 2 — impacto no benchmark das fontes informadas")
        print("=" * 78)
        if not args.fonte_afetada:
            print("  [!] nenhuma --fonte-afetada informada, nada a medir.")
        else:
            linhas = verificar_impacto_benchmark(args.benchmark, args.fonte_afetada)
            print("\n".join(linhas))

    if not rodou_algo:
        ap.print_help()
        return 2

    print("\n" + "=" * 78)
    if algum_problema:
        print("RESULTADO: PROBLEMAS ENCONTRADOS. Ver detalhes acima antes de prosseguir.")
    else:
        print("RESULTADO: OK. Nenhuma divergencia ou contaminacao encontrada.")
    print("=" * 78)

    return 1 if algum_problema else 0


if __name__ == "__main__":
    sys.exit(main())

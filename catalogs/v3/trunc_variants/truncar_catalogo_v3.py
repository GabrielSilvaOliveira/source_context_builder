#!/usr/bin/env python3
"""
Gera variantes do catalog_v3.json para separar duas explicações concorrentes
do colapso do Llama 3.2 3B no formato `full` do v3 (F1=0,308):

  (H1) TAMANHO   — 2710 palavras excedem o contexto efetivo do SLM.
  (H2) ANDAIME   — o prompt carrega resíduo de template dirigido ao redator
                   do catálogo ("Descreva em linguagem de negócio o que este
                   endpoint retorna - ", "Ex: Quando o agente deve consultar
                   esta tabela?"), que compete com a tarefa.

Fatos medidos que motivam o teste (ver FASE_E_consolidacao_catalog_v4.md):
  - Llama `full`:  477 pal -> 0,671 | 699 -> 0,620 | 2650 -> 0,328 | 2710 -> 0,308
  - Llama `compressed` (~330 pal em todas as condições): não colapsa
  - GPT-4o no MESMO prompt de 2650 palavras: 0,900 (não colapsa)
  => descarta "conteúdo ruim"; restam H1 e H2, hoje confundidas.

CONDIÇÕES GERADAS
  LIMPO  — filtro de andaime, SEM truncar. Isola H2: se recuperar aqui, o
           problema era o andaime, não o tamanho.
  A      — filtro de andaime + truncamento proporcional por fonte, alvo de
           699 palavras (mesmo tamanho do `full` do v4-gen). Isola H1 com
           conteúdo e estrutura preservados; introduz disfluência no corte.
  B      — apenas embedding_hint, íntegro. Isola H1 com texto fluente, sem
           truncamento e sem andaime por construção; muda qual conteúdo entra.

FILTRO DE ANDAIME
  Reusa `limpar()` de build_catalog_v3_doc.py (cobre "Ex:", "Quando o agente
  deve consultar esta...?" e prefixos de coluna) e ACRESCENTA os prefixos de
  nível de fonte que aquele script não cobria, por ter sido desenhado para
  descrições de coluna. Impacto medido: 17 de 64 campos, 139 palavras (5,1%),
  todas verificadas manualmente como andaime, nenhum conteúdo real removido.

CRITÉRIO DE DECISÃO (fixado antes de rodar, não reinterpretar depois)
  Recuperação confirmada : F1 >= 0,60 e diferença vs. `full` original (0,308)
                           significativa após Holm.
  Recuperação parcial    : F1 entre 0,40 e 0,60, com significância.
  Sem recuperação        : F1 < 0,40 ou diferença não significativa.
  Família declarada: 6 comparações (3 condições x {full original, compressed v3}).

Uso:
    python truncar_catalogo_v3.py --catalog catalog_v3.json \
        --builder build_catalog_v3_doc.py --runner run_llm_benchmark.py \
        --outdir output/trunc/
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

CAMPOS_FULL = ["description", "business_role", "embedding_hint", "when_to_use"]
CAMPOS_SECUNDARIOS = ["description", "business_role", "when_to_use"]
GRUPOS = [("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")]

# Andaime de NÍVEL DE FONTE. O build_catalog_v3_doc.py cobre o de nível de
# COLUNA e os prefixos "Ex:"/"Quando o agente deve consultar esta...?".
# ATENÇÃO: o hífen dentro das classes precisa estar escapado (\-), senão vira
# operador de intervalo e a classe passa a excluir quase todo o alfabeto.
ANDAIME_FONTE = [
    re.compile(r"^\s*Descreva (em linguagem de negócio )?o que (esta|este)[^\-–.?']{0,60}[\-–.?]\s*", re.I),
    re.compile(r"^\s*Descreva o propósito d[aeo][^'\-–?]{0,40}('[^']*')?\s*[\-–.:]\s*", re.I),
    re.compile(r"^\s*Qual o papel d[aeo][^\-–?']{0,60}[\-–.?]\s*", re.I),
    re.compile(r"^\s*O que esta (tabela|planilha|API|fonte)[^\-–.?']{0,60}[\-–.?]\s*", re.I),
]
SEPARADOR_ORFAO = re.compile(r"^\s*[\-–:.]\s*")


def carrega_limpar(caminho_builder: Path):
    """Extrai `limpar()` de build_catalog_v3_doc.py sem executar o módulo."""
    codigo = caminho_builder.read_text(encoding="utf-8")
    try:
        inicio = codigo.index("PREF_COLUNA")
        fim = codigo.index("def _redundante")
    except ValueError:
        sys.exit("[erro] bloco PREF_COLUNA.._redundante não encontrado no builder")
    ns: dict = {}
    exec("import re\n" + codigo[inicio:fim], ns)
    return ns["limpar"]


def preenchido(meta: dict, campo: str) -> bool:
    v = meta.get(campo, "")
    return bool(v) and "[MANUAL]" not in str(v)


def limpa_campo(texto: str, limpar) -> str:
    t = limpar(texto)
    for rx in ANDAIME_FONTE:
        t = rx.sub("", t)
    return SEPARADOR_ORFAO.sub("", t).strip()


def trunc_palavras(texto: str, n: int) -> str:
    p = str(texto).split()
    return texto if len(p) <= n else " ".join(p[:n]) + "..."


def cond_limpo(catalogo: dict, limpar) -> dict:
    novo = copy.deepcopy(catalogo)
    for g, k in GRUPOS:
        for _, meta in novo["sources"].get(g, {}).get(k, {}).items():
            for c in CAMPOS_FULL:
                if preenchido(meta, c):
                    meta[c] = limpa_campo(meta[c], limpar)
    novo.setdefault("metadata", {})["variante"] = "LIMPO_sem_andaime"
    return novo


def cond_A(catalogo: dict, limpar, cap: int) -> dict:
    novo = cond_limpo(catalogo, limpar)
    for g, k in GRUPOS:
        for _, meta in novo["sources"].get(g, {}).get(k, {}).items():
            campos = [c for c in CAMPOS_FULL if preenchido(meta, c)]
            total = sum(len(str(meta[c]).split()) for c in campos)
            if total <= cap:
                continue
            fator = cap / total
            for c in campos:
                meta[c] = trunc_palavras(meta[c], max(3, int(len(str(meta[c]).split()) * fator)))
    novo["metadata"]["variante"] = f"A_limpo_truncado_cap{cap}"
    return novo


def cond_B(catalogo: dict) -> dict:
    novo = copy.deepcopy(catalogo)
    for g, k in GRUPOS:
        for _, meta in novo["sources"].get(g, {}).get(k, {}).items():
            for c in CAMPOS_SECUNDARIOS:
                if c in meta:
                    meta[c] = ""
    novo.setdefault("metadata", {})["variante"] = "B_apenas_embedding_hint"
    return novo


def carrega_serializadores(caminho_runner: Path):
    codigo = caminho_runner.read_text(encoding="utf-8")
    ns: dict = {}
    exec(codigo.split("if __name__")[0], ns)
    return ns["serialize_full"], ns["serialize_compressed"]


def conta_fontes(catalogo: dict) -> int:
    return sum(len(catalogo["sources"].get(g, {}).get(k, {})) for g, k in GRUPOS)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--builder", default="build_catalog_v3_doc.py")
    ap.add_argument("--runner", default="run_llm_benchmark.py")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--cap", type=int, default=39,
                    help="Teto de palavras/fonte na variante A (39 -> ~699 palavras)")
    args = ap.parse_args()

    for p, rot in [(args.catalog, "catálogo"), (args.builder, "builder"), (args.runner, "runner")]:
        if not Path(p).exists():
            sys.exit(f"[erro] {rot} não encontrado: {p}")

    limpar = carrega_limpar(Path(args.builder))
    serialize_full, serialize_compressed = carrega_serializadores(Path(args.runner))
    catalogo = json.loads(Path(args.catalog).read_text(encoding="utf-8"))

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    variantes = {
        "catalog_v3_limpo.json": cond_limpo(catalogo, limpar),
        "catalog_v3_truncA.json": cond_A(catalogo, limpar, args.cap),
        "catalog_v3_truncB.json": cond_B(catalogo),
    }
    for nome, cat in variantes.items():
        (outdir / nome).write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("VERIFICAÇÃO")
    print("=" * 72)
    print(f"{'condição':<38}{'fontes':>8}{'palavras':>11}{'chars':>9}")
    print("-" * 72)
    linhas = [
        ("v3 compressed (referência, F1=0,775)", catalogo, serialize_compressed),
        ("v3 full ORIGINAL (F1=0,308)", catalogo, serialize_full),
        ("v3 full LIMPO (isola andaime)", variantes["catalog_v3_limpo.json"], serialize_full),
        (f"v3 full VARIANTE A (cap={args.cap})", variantes["catalog_v3_truncA.json"], serialize_full),
        ("v3 full VARIANTE B (só hint)", variantes["catalog_v3_truncB.json"], serialize_full),
    ]
    falhou = False
    for rot, cat, ser in linhas:
        txt = ser(cat)
        nf = conta_fontes(cat)
        print(f"{rot:<38}{nf:>8}{len(txt.split()):>11}{len(txt):>9}")
        if nf != 16:
            falhou = True
    print("-" * 72)
    print("[FALHA] alguma variante não tem 16 fontes" if falhou
          else "[ok] as 16 fontes preservadas em todas as variantes")
    print("[i] referência: full do v4-gen = 699 palavras (Llama F1=0,620)")
    print(f"[i] gravados em {outdir}/")


if __name__ == "__main__":
    main()

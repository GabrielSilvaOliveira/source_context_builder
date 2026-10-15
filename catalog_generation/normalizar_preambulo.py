#!/usr/bin/env python3
"""
normalizar_preambulo.py
─────────────────────────────────────────────────────────────────────────────
Remove frases de andaime (regra 3 do prompt de geração: "não comece com
'esta fonte contém'...") que sobreviveram em parte dos descritores.

Por que este script existe, e por que é seguro
────────────────────────────────────────────────────────────────────────────
O validador embutido em build_catalog_v4_gen.py / build_catalog_v3_doc.py só
verificava a abertura "este/esta/esse/essa fonte/tabela/catálogo/conjunto".
Ele não cobria "Esta API retorna...", "Este endpoint retorna..." nem
"A planilha 'X.xlsx' detalha...", que são a MESMA violação da mesma regra,
só com substantivo diferente. 6 de 16 descritores do v3-doc caíram nessa
lacuna; 0 de 16 do v4-gen.

Isto é normalização MECÂNICA, não reformulação de conteúdo: remove só a
cláusula de abertura redundante e recapitaliza a primeira letra do que sobra.
Nenhuma palavra de conteúdo é adicionada, removida ou reescrita. Por isso não
reabre a circularidade que o desenho evita — não é iterar o prompt olhando
F1, é aplicar a MESMA regra determinística às DUAS condições por igual,
antes de qualquer benchmark ter rodado sobre a versão final.

Uso
───
  python normalizar_preambulo.py --dry-run \
      --catalogos catalog_v3_doc.json catalog_v4_gen.json

  python normalizar_preambulo.py \
      --catalogos catalog_v3_doc.json catalog_v4_gen.json
"""

import argparse
import copy
import json
import re
from pathlib import Path

# Cada padrão casa a cláusula de abertura inteira, incluindo o verbo e o
# complemento genérico ("retorna uma lista com/de", "detalha"), preservando
# tudo que vem depois. Ordem importa: padrões mais específicos primeiro.
PADROES = [
    re.compile(r"^(Esta|Este)\s+(API|api|endpoint)\s+retorna\s+(uma\s+lista\s+)?"
              r"(com|de)\s*", re.I),
    re.compile(r"^A\s+planilha\s+'[^']+'\s+detalha\s*", re.I),
    re.compile(r"^(Esta|Este|Essa|Esse)\s+(API|endpoint|planilha|tabela|view)\s+"
              r"(retorna|traz|apresenta|contém|lista)\s*", re.I),
]


def _iter_sources(catalog):
    src = catalog.get("sources", {})
    for tipo, sub in (("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")):
        for nome, meta in (src.get(tipo, {}).get(sub, {}) or {}).items():
            yield tipo, nome, meta


def normalizar(texto):
    """Remove a cláusula de abertura redundante, se houver, e recapitaliza."""
    for pad in PADROES:
        novo = pad.sub("", texto, count=1)
        if novo != texto:
            novo = novo.strip()
            if novo:
                novo = novo[0].upper() + novo[1:]
            return novo, True
    return texto, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogos", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sufixo", default="_norm",
                    help="Sufixo do arquivo de saída (padrão: _norm)")
    args = ap.parse_args()

    for caminho in args.catalogos:
        p = Path(caminho)
        cat = json.load(open(p, encoding="utf-8"))
        alterados = []

        for tipo, nome, meta in _iter_sources(cat):
            hint = meta.get("embedding_hint", "")
            if not hint:
                continue
            novo, mudou = normalizar(hint)
            if mudou:
                alterados.append((f"{tipo}.{nome}", hint, novo))
                if not args.dry_run:
                    meta["embedding_hint"] = novo

        print("=" * 70)
        print(f"{p.name}: {len(alterados)} descritor(es) alterado(s) de "
              f"{sum(1 for _ in _iter_sources(cat))}")
        print("=" * 70)
        for sid, antes, depois in alterados:
            print(f"\n[{sid}]")
            print(f"  ANTES : {antes[:90]}...")
            print(f"  DEPOIS: {depois[:90]}...")

        if args.dry_run:
            print(f"\n[dry-run] Nenhum arquivo escrito para {p.name}.")
            continue

        cat.setdefault("metadata", {})["post_normalizacao_preambulo"] = {
            "script": "normalizar_preambulo.py",
            "n_alterados": len(alterados),
            "fontes_alteradas": [sid for sid, _, _ in alterados],
            "nota": ("remoção mecânica de cláusula de abertura redundante "
                    "(regra 3 do prompt), aplicada identicamente a todos os "
                    "catálogos gerados listados nesta execução; nenhum "
                    "conteúdo substantivo alterado"),
        }

        saida = p.with_name(p.stem + args.sufixo + p.suffix)
        json.dump(cat, open(saida, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print(f"\n[✓] Escrito: {saida}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
gerar_figuras_scb.py

Gera a Figura 1 (F1 por metodo x condicao) e a Figura 2 (interacao por faixa
de sobreposicao) do artigo SCB, em PDF vetorial, estilo IEEEtran.

Uso:
    python gerar_figuras_scb.py --results-dir /caminho/para/sua/pasta/results \
                                  --bandas-dir /caminho/para/tab_bandas_e_inter \
                                  --out-dir .

    python gerar_figuras_scb.py --results-dir ./results --chart2 line

============================== POR QUE DESCOBERTA, NAO LEITURA CEGA ==============================
Ao inspecionar /mnt/project foram encontrados tres problemas que uma leitura
ingenua de "todo arquivo results_*.json" teria propagado sem aviso:
  1. results_bm25_v4norm.json tem F1=0.3107, valor PRE-correcao do descasamento
     de spreadsheets.fornecimento (o correto, pos-correcao, e 0.293).
  2. Nao existe nenhum results_*_v4min.json distinto de v4norm -- o nome
     "v4norm" e usado tanto para catalog_v4_gen_norm quanto (supostamente)
     para catalog_v4_min, sem se distinguirem no nome do arquivo.
  3. Nao existe results_minilm.json (sem sufixo) para a condicao curada nessa
     pasta, e nao existe versao "compressed" com a tag "latest" do Llama
     isolada para v3 (so existe a tag antiga "3b", ja sabidamente
     desatualizada pelo ADENDO_III).

Por isso este script:
  - varre a pasta e tenta casar cada arquivo contra REGRAS, que voce ajusta
    para o seu padrao de nomes real;
  - se duas ou mais regras casarem o MESMO (modelo, condicao), o script PARA
    com erro listando os arquivos conflitantes, em vez de escolher um;
  - antes de plotar, imprime um MANIFESTO (modelo, condicao, arquivo, F1)
    para voce conferir;
  - se faltar qualquer uma das 20 celulas (5 modelos x 4 condicoes), lista
    exatamente o que falta em vez de gerar figura parcial.

Dependencias: matplotlib (pip install matplotlib --break-system-packages)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt

# --------------------------------------------------------------------------
# REGRAS DE DESCOBERTA -- AJUSTE PARA O PADRAO DE NOMES DA SUA PASTA
# --------------------------------------------------------------------------
REGRAS: list[tuple[str, str, str]] = [
    (r"^results_bm25_(catalog_)?v3\.json$",                       "bm25",   "curado"),
    (r"^results_bm25_v3_doc_norm\.json$",                         "bm25",   "curado_sint"),
    (r"^results_bm25_v4_gen_norm\.json$",                         "bm25",   "gerado"),
    (r"^results_bm25_v4_min\.json$",                              "bm25",   "piso"),

    (r"^results_minilm_(catalog_)?v3\.json$",                     "minilm", "curado"),
    (r"^results_minilm_v3_doc_norm\.json$",                       "minilm", "curado_sint"),
    (r"^results_minilm_v4_gen_norm\.json$",                       "minilm", "gerado"),
    (r"^results_minilm_v4_min\.json$",                            "minilm", "piso"),

    (r"^results_bge-m3_(catalog_)?v3\.json$",                     "bge-m3", "curado"),
    (r"^results_bge-m3_v3_doc_norm\.json$",                       "bge-m3", "curado_sint"),
    (r"^results_bge-m3_v4_gen_norm\.json$",                       "bge-m3", "gerado"),
    (r"^results_bge-m3_v4_min\.json$",                            "bge-m3", "piso"),

    # Llama: 'llama3.2' com PONTO no nome real (nao underscore). So a
    # variante 'compressed', tag 'latest' (pos-ADENDO_III).
    (r"^results_ollama_llama3\.2_latest_compressed_(catalog_)?v3\.json$",
                                                                    "llama",  "curado"),
    (r"^results_ollama_llama3\.2_latest_compressed_v3_doc_norm\.json$",
                                                                    "llama",  "curado_sint"),
    (r"^results_ollama_llama3\.2_latest_compressed_v4_gen_norm\.json$",
                                                                    "llama",  "gerado"),
    (r"^results_ollama_llama3\.2_latest_compressed_v4_min\.json$",
                                                                    "llama",  "piso"),

    # GPT-4o: so a variante 'compressed'. Curado embute 'catalog_', as
    # demais nao -- os dois formatos sao aceitos.
    (r"^results_azure_gpt-4o_compressed_(catalog_)?v3\.json$",     "gpt4o",  "curado"),
    (r"^results_azure_gpt-4o_compressed_(catalog_)?v3_doc_norm\.json$",
                                                                    "gpt4o",  "curado_sint"),
    (r"^results_azure_gpt-4o_compressed_(catalog_)?v4_gen_norm\.json$",
                                                                    "gpt4o",  "gerado"),
    (r"^results_azure_gpt-4o_compressed_(catalog_)?v4_min\.json$", "gpt4o",  "piso"),
]

EXCLUIR_SEMPRE = [
    r"e5[-_]?base", r"serafim", r"_full", r"trunc_", r"_3b_compressed", r"qwen",
    r"^results_bm25_v4min\.json$",   # rodada OBSOLETA pre-correcao (F1=0.2218);
                                      # a valida e results_bm25_v4_min.json (F1=0.1946)
]

CONDICOES = ["curado", "curado_sint", "gerado", "piso"]
ROTULOS_CONDICAO = ["Curated", "Curated-\nsynth.", "Generated", "Floor"]
MODELOS_FIG1 = ["bm25", "minilm", "bge-m3", "llama", "gpt4o"]
ROTULO_MODELO = {
    "bm25": "BM25", "minilm": "MiniLM", "bge-m3": "BGE-M3",
    "llama": "Llama 3.2 3B", "gpt4o": "GPT-4o",
}
MODELOS_FIG2 = ["bge-m3", "llama", "gpt4o", "minilm"]

ESTILO = {
    "bm25":    dict(color="#2a78d6", marker="o"),
    "minilm":  dict(color="#898781", marker="s"),
    "bge-m3":  dict(color="#eb6834", marker="^"),
    "llama":   dict(color="#6250d6", marker="D"),
    "gpt4o":   dict(color="#008300", marker="*"),
}

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 8, "axes.labelsize": 8,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 7,
    "axes.linewidth": 0.6, "lines.linewidth": 1.5, "lines.markersize": 5,
    "pdf.fonttype": 42, "ps.fonttype": 42,
})


def descobrir_arquivos(results_dir: Path) -> dict[tuple[str, str], Path]:
    achados: dict[tuple[str, str], list[Path]] = {}
    nao_casados: list[str] = []

    for f in sorted(results_dir.glob("*.json")):
        nome = f.name
        if any(re.search(p, nome, re.I) for p in EXCLUIR_SEMPRE):
            continue
        casou = False
        for pattern, modelo, condicao in REGRAS:
            if re.match(pattern, nome, re.I):
                achados.setdefault((modelo, condicao), []).append(f)
                casou = True
        if not casou:
            nao_casados.append(nome)

    conflitos = {k: v for k, v in achados.items() if len(v) > 1}
    if conflitos:
        msg = ["Mais de um arquivo casou com a mesma (modelo, condicao):"]
        for (modelo, condicao), arquivos in conflitos.items():
            msg.append(f"  {modelo}/{condicao}:")
            for a in arquivos:
                msg.append(f"    - {a.name}")
        msg.append("\nAjuste REGRAS no topo do script, ou renomeie um dos arquivos.")
        raise SystemExit("\n".join(msg))

    faltando = [(m, c) for m in MODELOS_FIG1 for c in CONDICOES if (m, c) not in achados]
    if faltando:
        print("[!] Nao encontrados (modelo, condicao) para:")
        for m, c in faltando:
            print(f"    - {m} / {c}")
        print("    Confira REGRAS, ou esses resultados nao existem ainda nessa pasta.")

    if nao_casados:
        print(f"[i] {len(nao_casados)} arquivo(s) nao casaram com nenhuma regra "
              f"(ignorados): {nao_casados[:5]}" + (" ..." if len(nao_casados) > 5 else ""))

    return {k: v[0] for k, v in achados.items()}


def ler_metricas(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    cv = d["cv_metrics"]
    n_fontes = sum(len(r.get("selected", [])) for r in d.get("all_results", []))
    n_queries = len(d.get("all_results", [])) or 1
    return dict(f1=cv["f1"], top1=cv.get("top1_acc"), ndcg=cv.get("ndcg"),
                n_fontes=n_fontes / n_queries)


def montar_matriz(mapa: dict[tuple[str, str], Path]) -> dict[tuple[str, str], dict]:
    matriz = {}
    print("\n=== MANIFESTO: confira antes de confiar na figura ===")
    print(f"{'modelo':10} {'condicao':13} {'F1':>6}   arquivo")
    for m in MODELOS_FIG1:
        for c in CONDICOES:
            path = mapa.get((m, c))
            if path is None:
                continue
            met = ler_metricas(path)
            matriz[(m, c)] = met
            print(f"{m:10} {c:13} {met['f1']:.4f}   {path.name}")
    print("=" * 55)
    return matriz


def gerar_figura1(matriz: dict[tuple[str, str], dict], out: Path) -> None:
    if any((m, c) not in matriz for m in MODELOS_FIG1 for c in CONDICOES):
        print("[!] Figura 1 NAO gerada: faltam celulas na matriz (ver acima).")
        return

    fig, ax = plt.subplots(figsize=(3.45, 2.6))
    for modelo in MODELOS_FIG1:
        y = [matriz[(modelo, c)]["f1"] for c in CONDICOES]
        st = ESTILO[modelo]
        ax.plot(range(len(CONDICOES)), y, label=ROTULO_MODELO[modelo],
                 color=st["color"], marker=st["marker"], markersize=5)
        ax.annotate(f"{y[0]:.2f}", (0, y[0]), textcoords="offset points",
                    xytext=(-10, 5), fontsize=6, ha="right", color=st["color"])
        ax.annotate(f"{y[-1]:.2f}", (len(CONDICOES) - 1, y[-1]),
                    textcoords="offset points", xytext=(4, 5), fontsize=6,
                    ha="left", color=st["color"])

    ax.set_xticks(range(len(CONDICOES)))
    ax.set_xticklabels(ROTULOS_CONDICAO)
    ax.set_xlim(-0.55, len(CONDICOES) - 1 + 0.25)
    ax.set_ylabel("F1")
    ax.set_ylim(0.10, 0.95)
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3,
               frameon=False, columnspacing=1.0, handletextpad=0.4)
    fig.tight_layout()
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[ok] {out}")


ALIAS_CONDICAO = {
    "curado": ["curado", "v3"],
    "curado_sint": ["curado_sint", "v3docnorm", "v3_doc_norm"],
    "gerado": ["gerado", "v4gen", "v4_gen_norm", "v4gennorm"],
    "piso": ["piso", "v4min", "v4_min"],
}


def _achar_csv(bandas_dir: Path, prefixo: str, condicao: str) -> Path:
    """Tenta o nome canonico (curado/gerado/...) e, se nao existir, os
    apelidos v3/v3docnorm/v4gen/v4min que ja sao a convencao usada em
    outras partes deste projeto."""
    for apelido in ALIAS_CONDICAO[condicao]:
        p = bandas_dir / f"{prefixo}_{apelido}_consumido.csv"
        if p.exists():
            return p
    raise FileNotFoundError(
        f"Nenhum arquivo {prefixo}_<{'|'.join(ALIAS_CONDICAO[condicao])}>_consumido.csv "
        f"encontrado em {bandas_dir}"
    )


def carregar_bandas(bandas_dir: Path, condicao: str) -> dict[str, list[float]]:
    path = _achar_csv(bandas_dir, "tab_bandas", condicao)
    dados: dict[str, dict[str, float]] = {m: {} for m in MODELOS_FIG2}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            comp = row["comparacao"]
            faixa = comp.split("]")[0].strip("[")
            modelo = comp.split("]")[1].split(" vs ")[0].strip()
            if modelo in dados:
                dados[modelo][faixa] = float(row["diff"])
    faltando = [m for m in MODELOS_FIG2 if len(dados[m]) != 3]
    if faltando:
        raise ValueError(f"Faixas incompletas em {path.name} para: {faltando}")
    return {m: [dados[m]["baixa"], dados[m]["media"], dados[m]["alta"]] for m in dados}


def carregar_significancia(bandas_dir: Path, condicao: str) -> dict[str, bool]:
    path = _achar_csv(bandas_dir, "tab_inter", condicao)
    sig: dict[str, bool] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["teste"] == "did_baixa_vs_alta":
                sig[row["modelo"]] = row["significativo_holm"].strip().lower() == "true"
    faltando = [m for m in MODELOS_FIG2 if m not in sig]
    if faltando:
        raise ValueError(f"Significancia ausente em {path.name} para: {faltando}")
    return sig


def gerar_figura2_barras(bandas_dir: Path, out: Path) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(7.16, 2.1), sharey=True)
    largura = 0.2
    offsets = [-1.5, -0.5, 0.5, 1.5]

    for ax, condicao, rotulo in zip(axes, CONDICOES, ROTULOS_CONDICAO):
        bandas = carregar_bandas(bandas_dir, condicao)
        sig = carregar_significancia(bandas_dir, condicao)
        for modelo, off in zip(MODELOS_FIG2, offsets):
            st = ESTILO[modelo]
            y = bandas[modelo]
            x = [i + off * largura for i in range(3)]
            hatch = None if sig[modelo] else "///"
            alpha = 1.0 if sig[modelo] else 0.55
            ax.bar(x, y, width=largura, color=st["color"], hatch=hatch,
                   alpha=alpha, edgecolor="white", linewidth=0.4)
        ax.set_title(rotulo.replace("\n", " "), fontsize=8)
        ax.set_xticks(range(3))
        ax.set_xticklabels(["Baixa", "Média", "Alta"], fontsize=7)
        ax.axhline(0, color="#5f5e5a", linewidth=0.6)
        ax.grid(axis="y", linewidth=0.4, alpha=0.5)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

    axes[0].set_ylabel("Vantagem sobre BM25 (F1)")
    axes[0].set_ylim(-0.25, 0.85)

    from matplotlib.patches import Patch
    handles = [Patch(facecolor=ESTILO[m]["color"], label=ROTULO_MODELO[m]) for m in MODELOS_FIG2]
    handles += [Patch(facecolor="white", edgecolor="black", label="Significativo (Holm)"),
                Patch(facecolor="white", edgecolor="black", hatch="///", alpha=0.55,
                      label="Não significativo")]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, -0.12), fontsize=7)
    fig.tight_layout(rect=[0, 0.14, 1, 1])
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[ok] {out}  (barras; textura = nao significativo)")


# Rotulos de painel para a Fig. 2 (uma linha so; a versao com "\n" de
# ROTULOS_CONDICAO existe para o eixo x estreito da Fig. 1 e, se reusada
# aqui via .replace("\n", " "), produz "Curated- synt." com espaco e corte
# indevidos -- por isso uma lista dedicada, sem esse problema).
ROTULOS_CONDICAO_FIG2 = ["Curated", "Curated-synth.", "Generated", "Floor"]


def gerar_figura2_linha(bandas_dir: Path, out: Path) -> None:
    """Versao final acordada: linha (nao barra), sem barra de erro (o
    IC por banda nao tem apoio na prosa da secao 4.3, que so discute os
    dois testes de robustez -- inclinacao e contraste baixa-alta -- entao
    fica de fora para nao introduzir informacao que o texto nao usa).
    Solido/tracejado codifica SOMENTE o teste de contraste baixa-alta
    (did_baixa_vs_alta), aplicado a linha inteira do modelo naquele
    painel -- e por isso a legenda diz isso explicitamente, em vez de
    deixar implicito por barra a barra como na versao anterior."""
    fig, axes = plt.subplots(1, 4, figsize=(7.16, 2.1), sharey=True)
    handles_legenda = {}
    for ax, condicao, rotulo in zip(axes, CONDICOES, ROTULOS_CONDICAO_FIG2):
        bandas = carregar_bandas(bandas_dir, condicao)
        sig = carregar_significancia(bandas_dir, condicao)
        for modelo in MODELOS_FIG2:
            st = ESTILO[modelo]
            y = bandas[modelo]
            estilo_linha = "-" if sig[modelo] else (0, (3, 2))
            alpha = 1.0 if sig[modelo] else 0.55
            (linha,) = ax.plot([0, 1, 2], y, linestyle=estilo_linha, color=st["color"],
                                marker=st["marker"], markersize=5, alpha=alpha,
                                linewidth=1.3)
            handles_legenda[modelo] = linha
        ax.set_title(rotulo, fontsize=8)
        ax.set_xticks([0, 1, 2])
        ax.set_xticklabels(["Low", "Medium", "High"], fontsize=7)
        ax.set_xlim(-0.25, 2.25)
        ax.axhline(0, color="#5f5e5a", linewidth=0.6)
        ax.grid(axis="y", linewidth=0.4, alpha=0.5)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
    axes[0].set_ylabel("Advantage over BM25 (F1)")
    axes[0].set_ylim(-0.25, 0.85)

    from matplotlib.lines import Line2D
    ordem = ["bge-m3", "llama", "gpt4o", "minilm"]
    handles = [handles_legenda[m] for m in ordem]
    labels = [ROTULO_MODELO[m] for m in ordem]
    handles += [Line2D([0], [0], color="black", linestyle="-",
                        label="Significant low-high contrast (Holm)"),
                Line2D([0], [0], color="black", linestyle=(0, (3, 2)), alpha=0.55,
                        label="Not significant")]
    labels += ["Significant low-high contrast (Holm)", "Not significant"]
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, -0.16), fontsize=7)
    fig.tight_layout(rect=[0, 0.16, 1, 1])
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[ok] {out}  (linha; tracejado = contraste baixa-alta nao significativo)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, required=True,
                     help="Pasta com os results_*.json")
    ap.add_argument("--bandas-dir", type=Path, default=None,
                     help="Pasta com tab_bandas_*_consumido.csv e tab_inter_*_consumido.csv "
                          "(default: mesma de --results-dir)")
    ap.add_argument("--out-dir", type=Path, default=Path("."))
    ap.add_argument("--chart2", choices=["bar", "line"], default="line",
                     help="Tipo de grafico da Figura 2 (default: line, a versao "
                          "final acordada -- solido/tracejado por linha, sem "
                          "barra de erro; 'bar' fica so para comparacao/arquivo)")
    args = ap.parse_args()

    bandas_dir = args.bandas_dir or args.results_dir
    args.out_dir.mkdir(parents=True, exist_ok=True)

    mapa = descobrir_arquivos(args.results_dir)
    if mapa:
        matriz = montar_matriz(mapa)
        gerar_figura1(matriz, args.out_dir / "fig1_f1_por_condicao.pdf")
    else:
        print("[!] Nenhum arquivo casou com as REGRAS. Ajuste-as e rode de novo.")

    def _existe(prefixo, c):
        return any((bandas_dir / f"{prefixo}_{a}_consumido.csv").exists()
                   for a in ALIAS_CONDICAO[c])
    faltando = [c for c in CONDICOES
                if not _existe("tab_bandas", c) or not _existe("tab_inter", c)]
    if faltando:
        print(f"[!] Figura 2 NAO gerada: faltam CSVs de banda/interacao para {faltando} em {bandas_dir}")
        return

    out2 = args.out_dir / "fig2_interacao_bandas.pdf"
    if args.chart2 == "bar":
        gerar_figura2_barras(bandas_dir, out2)
    else:
        gerar_figura2_linha(bandas_dir, out2)


if __name__ == "__main__":
    main()

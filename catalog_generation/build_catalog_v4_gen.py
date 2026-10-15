#!/usr/bin/env python3
"""
build_catalog_v4_gen.py
─────────────────────────────────────────────────────────────────────────────
Fase C + D: gera a variante v4-gen do catálogo, descritores escritos por um
LLM local (Qwen2.5 7B via Ollama) a partir SÓ de metadados estruturais.

Contrato metodológico (não alterar sem reabrir a decisão com o orientando):
  - UMA chamada por fonte. O modelo NUNCA vê as outras 15 fontes na mesma
    chamada. Evita curadoria contrastiva pela porta dos fundos.
  - ZERO contato com o benchmark. Nenhuma consulta, cluster ou rótulo de
    dificuldade entra no prompt.
  - Prompt de sistema É FIXO (ver PROMPT_SISTEMA abaixo). Se você mudar uma
    vírgula dele depois de rodar, isso deixa de ser "prompt escrito uma vez"
    e vira iteração sobre o F1, o que recria a circularidade que o v4 existe
    para eliminar. Mude o prompt SÓ se ainda não rodou o benchmark sobre o
    resultado anterior.
  - temperature=0: geração determinística, para que outra pessoa rodando
    este script sobre o mesmo catalog_v4_base.json obtenha o mesmo
    catalog_v4_gen.json (replicabilidade).

Entrada: catalog_v4_base.json (o artefato neutro já auditado)
Saída  : catalog_v4_gen.json  (mesmo schema do v3, embedding_hint = gerado)
         + catalog_v4_gen_transcript.json (prompt e resposta crus, por fonte,
           para auditoria — publicável, não contém dado de linha, só schema)

Uso
───
  # Teste seco: monta os prompts e mostra, sem chamar o Ollama
  python build_catalog_v4_gen.py \
      --base ./catalog_v4/catalog_v4_base.json \
      --dry-run

  # Geração de verdade (precisa do Ollama rodando com qwen2.5:7b baixado)
  python build_catalog_v4_gen.py \
      --base ./catalog_v4/catalog_v4_base.json \
      --model qwen2.5:7b \
      --out ./catalog_v4/catalog_v4_gen.json
"""

import argparse
import copy
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT — CONGELADO. Ver contrato metodológico no docstring do módulo.
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_SISTEMA = """Você é um gerador de descritores técnicos e objetivos para um catálogo de
fontes de dados. Sua tarefa é escrever UM parágrafo curto (250 a 350
caracteres) descrevendo o conteúdo de UMA fonte de dados, com base
ESTRITAMENTE nos metadados estruturais fornecidos.

REGRAS OBRIGATÓRIAS:
1. Use apenas as informações fornecidas (nome, colunas, tipos, valores de
   exemplo). Não invente informação que não esteja nos metadados.
2. Você não tem acesso a nenhuma outra fonte de dados além desta. Não
   mencione nem pressuponha relação com outras fontes.
3. Escreva em português, registro técnico, direto ao conteúdo. Não comece
   com frases de preenchimento como "esta fonte contém" ou "este catálogo
   apresenta".
4. Responda APENAS com o parágrafo descritivo. Sem explicações, sem aspas,
   sem markdown, sem título.
5. Alvo de comprimento: aproximadamente 300 caracteres. Não ultrapasse 400.

EXEMPLO (domínio diferente, só para ilustrar o formato esperado):

Entrada:
  TIPO: sql
  NOME: livros
  COLUNAS:
    titulo (varchar) [texto]
    autor (varchar) [texto]
    genero (varchar) [categórico]: Ficção, Não-Ficção, Poesia, Biografia
    ano_publicacao (int) [numérico]: faixa 1950–2024
    isbn (varchar) [identificador]

Saída esperada:
  Registro do acervo com título, autor e gênero (ficção, não-ficção, poesia,
  biografia) de cada obra, incluindo ano de publicação entre 1950 e 2024.
  Permite consultas por autor, gênero ou período de publicação."""

# Parâmetros de geração. Alterar exige justificar na Metodologia.
TEMPERATURE = 0
MAX_TOKENS = 200
TARGET_LEN = 300
HARD_CAP_LEN = 420          # acima disso, trunca e sinaliza no transcript
MIN_LEN_WARN = 120          # abaixo disso, sinaliza (pode ter vindo vazio/curto)
MAX_VALUES_IN_PROMPT = 15   # cap de valores listados por coluna no PROMPT
                            # (o catálogo guarda até 25; aqui é só para manter
                            # o prompt enxuto, não afeta o que fica no catálogo)

EMPTY_VALUE_TOKENS = {"", "0", "0.0", "none", "null", "nan", "-"}

KIND_LABEL_PT = {
    "categorical": "categórico", "numeric": "numérico",
    "identifier": "identificador", "text": "texto",
    "empty": "vazio", "categorical_blocked": "bloqueado",
}


def _log(msg=""):
    print(msg, flush=True)


def _ts():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUÇÃO DO BLOCO DE ENTRADA POR FONTE
# ─────────────────────────────────────────────────────────────────────────────

def _iter_sources(catalog):
    src = catalog.get("sources", {})
    for kind, sub in (("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")):
        for name, meta in (src.get(kind, {}).get(sub, {}) or {}).items():
            yield kind, name, meta


def build_source_block(kind, name, meta):
    """
    Monta o texto 'TIPO/NOME/COLUNAS' que vai no prompt de usuário.
    Aplica os filtros combinados: tokens vazios fora, cap de valores,
    colunas bloqueadas/vazias aparecem só como nome+tipo.
    """
    lines = [f"TIPO: {kind}", f"NOME: {name}", "COLUNAS:"]
    profile = meta.get("value_profile") or {}

    for col, v in profile.items():
        vkind = v.get("kind", "?")
        ctype = v.get("type", "?")
        label = KIND_LABEL_PT.get(vkind, vkind)

        if vkind == "categorical":
            vals = [str(x) for x in (v.get("values") or [])
                    if str(x).strip().lower() not in EMPTY_VALUE_TOKENS]
            if not vals:
                lines.append(f"  {col} ({ctype}) [{label}]")
                continue
            shown = vals[:MAX_VALUES_IN_PROMPT]
            suffix = f", +{len(vals) - len(shown)} outros" if len(vals) > len(shown) else ""
            lines.append(f"  {col} ({ctype}) [{label}]: {', '.join(shown)}{suffix}")
        elif vkind == "numeric":
            rng = v.get("range")
            rng_s = f"faixa {rng[0]}–{rng[1]}" if rng else ""
            lines.append(f"  {col} ({ctype}) [{label}]: {rng_s}".rstrip(": "))
        else:  # identifier, text, empty, categorical_blocked
            lines.append(f"  {col} ({ctype}) [{label}]")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLIENTE OLLAMA — mesma interface do run_llm_benchmark.py, para consistência
# ─────────────────────────────────────────────────────────────────────────────

class OllamaClient:
    def __init__(self, model, base_url="http://localhost:11434"):
        self.model, self.base_url = model, base_url.rstrip("/")
        try:
            urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=3)
        except Exception as e:
            raise ConnectionError(
                f"Ollama não acessível em {self.base_url}.\n"
                f"Inicie com: ollama serve\nConfira o modelo com: ollama list\nErro: {e}")

    def query(self, user_msg, system_prompt):
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg}],
            "stream": False,
            "options": {"temperature": TEMPERATURE, "num_predict": MAX_TOKENS,
                       "num_ctx": 4096},
        }).encode("utf-8")
        t0 = time.monotonic()
        req = urllib.request.Request(
            f"{self.base_url}/api/chat", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            result = json.loads(r.read().decode("utf-8"))
        ms = (time.monotonic() - t0) * 1000
        content = result.get("message", {}).get("content", "").strip()
        return content, round(ms, 2)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDAÇÃO DO DESCRITOR GERADO
# ─────────────────────────────────────────────────────────────────────────────

def clean_output(text):
    """Remove aspas/markdown acidental que o modelo às vezes adiciona."""
    t = text.strip()
    t = re.sub(r"^```.*?\n|```$", "", t, flags=re.S).strip()
    if len(t) >= 2 and t[0] in "\"'" and t[-1] in "\"'":
        t = t[1:-1].strip()
    return t


def validate(text, all_source_names, this_source_name):
    """Retorna lista de avisos (não bloqueia, só sinaliza no transcript)."""
    warns = []
    if len(text) < MIN_LEN_WARN:
        warns.append(f"descritor curto ({len(text)} chars, mínimo esperado {MIN_LEN_WARN})")
    if len(text) > HARD_CAP_LEN:
        warns.append(f"descritor longo ({len(text)} chars), será truncado em {HARD_CAP_LEN}")
    leaked = [s for s in all_source_names
              if s != this_source_name and s.split(".", 1)[-1].lower() in text.lower()]
    if leaked:
        warns.append(f"menção possível a outra fonte (isolamento pode ter vazado): {leaked}")
    if re.match(r"^\s*(este|esta|esse|essa)\s+(catálogo|fonte|tabela|conjunto)", text, re.I):
        warns.append("começa com frase de preenchimento proibida pela regra 3 do prompt")
    return warns


# ─────────────────────────────────────────────────────────────────────────────
# ORQUESTRADOR
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Fase C+D: gera catalog_v4_gen.json via Qwen local.")
    ap.add_argument("--base", required=True, help="catalog_v4_base.json (artefato neutro)")
    ap.add_argument("--out", default=None, help="saída (padrão: ao lado do --base)")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--dry-run", action="store_true",
                    help="Monta e mostra os prompts, não chama o Ollama.")
    args = ap.parse_args()

    base_path = Path(args.base)
    with open(base_path, encoding="utf-8") as f:
        catalog = json.load(f)

    sources = list(_iter_sources(catalog))
    all_names = [f"{k}.{n}" for k, n, _ in sources]
    _log(f"[i] {len(sources)} fontes carregadas de {base_path}\n")

    if args.dry_run:
        for kind, name, meta in sources:
            block = build_source_block(kind, name, meta)
            _log("═" * 70)
            _log(f"FONTE: {kind}.{name}")
            _log("─" * 70)
            _log(block)
            _log(f"\n[tamanho do bloco: {len(block)} chars]\n")
        _log("[dry-run] Nenhuma chamada ao Ollama foi feita.")
        return

    client = OllamaClient(args.model, args.ollama_url)
    _log(f"[✓] Ollama conectado, modelo: {args.model}\n")

    out_catalog = copy.deepcopy(catalog)
    transcript = []
    lens = []

    for i, (kind, name, meta) in enumerate(sources, 1):
        sid = f"{kind}.{name}"
        block = build_source_block(kind, name, meta)
        _log(f"[{i:>2}/{len(sources)}] gerando {sid} ...")

        try:
            raw, latency_ms = client.query(block, PROMPT_SISTEMA)
        except Exception as e:
            _log(f"    [X] falha: {e}")
            transcript.append({"source": sid, "error": str(e)})
            continue

        descriptor = clean_output(raw)
        warns = validate(descriptor, all_names, sid)
        truncated = False
        if len(descriptor) > HARD_CAP_LEN:
            descriptor = descriptor[:HARD_CAP_LEN].rsplit(" ", 1)[0] + "…"
            truncated = True

        lens.append(len(descriptor))

        # Emite no MESMO campo que o v3/v4-min usam, para os consumidores
        # (SCB, BM25, benchmark de LLM) funcionarem sem alteração de código.
        for kk, sub in (("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")):
            if kk == kind and name in out_catalog["sources"][kk][sub]:
                out_catalog["sources"][kk][sub][name]["embedding_hint"] = descriptor

        transcript.append({
            "source": sid, "prompt_user": block, "raw_output": raw,
            "descriptor_final": descriptor, "len_chars": len(descriptor),
            "truncated": truncated, "latency_ms": latency_ms, "warnings": warns,
        })

        flag = "  ⚠ " + "; ".join(warns) if warns else ""
        _log(f"    [✓] {len(descriptor)} chars, {latency_ms:.0f} ms{flag}")

    out_catalog["metadata"] = {
        "catalog_version": "4.0.0-gen",
        "generated_at": _ts(),
        "generator": f"build_catalog_v4_gen.py :: {args.model} (Ollama local)",
        "provenance": ("descritor gerado por LLM local a partir SÓ de metadados "
                      "estruturais; uma chamada isolada por fonte; ZERO contato "
                      "com o benchmark; temperature=0; prompt de sistema fixo "
                      "(ver transcript para o texto exato usado)"),
        "generation_params": {
            "model": args.model, "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS, "target_len_chars": TARGET_LEN,
            "hard_cap_len_chars": HARD_CAP_LEN,
        },
        "descriptor_len": {
            "n": len(lens),
            "mean": round(sum(lens) / max(len(lens), 1), 1),
            "min": min(lens) if lens else 0,
            "max": max(lens) if lens else 0,
        },
        "reference_v3_mean_chars": 333.9,   # medido nos hints curados, para comparação
    }

    out_path = Path(args.out) if args.out else base_path.with_name("catalog_v4_gen.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_catalog, f, indent=2, ensure_ascii=False)
    _log(f"\n[✓] Catálogo escrito: {out_path}")

    transcript_path = out_path.with_name(out_path.stem + "_transcript.json")
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump({"prompt_sistema": PROMPT_SISTEMA, "por_fonte": transcript},
                  f, indent=2, ensure_ascii=False)
    _log(f"[✓] Transcript (auditável, publicável): {transcript_path}")

    n_warn = sum(1 for t in transcript if t.get("warnings"))
    _log(f"\n[RESUMO] {len(lens)} descritores gerados, "
         f"média {out_catalog['metadata']['descriptor_len']['mean']} chars "
         f"(referência v3 curado: 333,9 chars), {n_warn} com avisos.")
    if n_warn:
        _log("[CHECKPOINT] Audite os avisos no transcript antes de rodar o benchmark.")


if __name__ == "__main__":
    main()

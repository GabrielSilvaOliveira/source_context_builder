#!/usr/bin/env python3
"""
build_catalog_v3_doc.py
─────────────────────────────────────────────────────────────────────────────
Gera a variante **v3-doc** do catálogo: descritores sintetizados pelo MESMO
gerador, no MESMO formato e com o MESMO teto de comprimento do v4-gen, porém
alimentados pela DOCUMENTAÇÃO MANUAL COMPLETA do catálogo v3 em vez do
esquema bruto.

Por que esta variante existe
────────────────────────────
O catálogo v3 contém uma camada de curadoria manual bem mais rica do que a
que os modelos efetivamente consomem: `description`, `business_role`,
`when_to_use`, `when_NOT_to_use` e 152 descrições de coluna preenchidas à
mão. Mas `_doc_from_source()` usa o `embedding_hint` EXCLUSIVAMENTE quando
ele está presente, e ele está presente nas 16 fontes. Resultado: toda essa
documentação nunca chegou a nenhum modelo.

Consequências, ambas corrigidas por esta variante:
  1. A condição "catálogo curado" do experimento media, na prática, apenas
     "hint curado", não a curadoria disponível. Um revisor que abrir o
     catálogo vê a documentação e pergunta por que ela não foi usada.
  2. O `lexical_overlap.py` indexa description/business_role/when_to_use +
     colunas (≈369 palavras/fonte em v3), enquanto os modelos consomem só o
     hint (≈44). Fator 8,4× entre régua e instrumento, contra 1,26× no
     v4-gen. Com o v3-doc, medição e consumo voltam a coincidir.

Desenho experimental
────────────────────
Isola UMA variável. Em relação ao v4-gen ficam constantes: o gerador
(Qwen2.5 7B local), temperature=0, o teto de caracteres, as 5 regras do
prompt de sistema e o formato de saída. Muda apenas a PROCEDÊNCIA do
conteúdo: conhecimento humano documentado (v3-doc) contra esquema bruto
extraído da base (v4-gen).

Ressalva a declarar na Metodologia, não esconder: o prompt de sistema NÃO é
byte a byte idêntico ao do v4-gen. Duas alterações mínimas foram necessárias
porque o insumo mudou de esquema para prosa — a cláusula que descreve o
insumo, e o exemplo ilustrativo. As 5 regras e o alvo de comprimento são
literalmente os mesmos. O exemplo usa o mesmo domínio fictício (livros) do
v4-gen, para não contaminar o gerador com vocabulário do domínio logístico.

Uso
───
  python build_catalog_v3_doc.py --v3 catalog_v3.json --dry-run
  python build_catalog_v3_doc.py --v3 catalog_v3.json --model qwen2.5:7b \
      --out ./catalog_v4/catalog_v3_doc.json
"""

import argparse
import copy
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT — paralelo ao de build_catalog_v4_gen.py. Ver ressalva no docstring.
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_SISTEMA = """Você é um gerador de descritores técnicos e objetivos para um catálogo de
fontes de dados. Sua tarefa é escrever UM parágrafo curto (250 a 350
caracteres) descrevendo o conteúdo de UMA fonte de dados, com base
ESTRITAMENTE na documentação fornecida.

REGRAS OBRIGATÓRIAS:
1. Use apenas as informações fornecidas (documentação, papel, orientações de
   uso, campos e seus significados). Não invente informação que não esteja
   na documentação.
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
  DOCUMENTAÇÃO: Cadastro do acervo da biblioteca, com uma linha por obra.
  PAPEL: Fonte de consulta bibliográfica para o catálogo público.
  QUANDO USAR: Para localizar obras por autor, gênero ou período.
  CAMPOS E SIGNIFICADOS:
    titulo: Título da obra conforme folha de rosto.
    autor: Nome do autor principal.
    genero: Classificação temática (ficção, não-ficção, poesia, biografia).
    ano_publicacao: Ano de publicação, entre 1950 e 2024.
    isbn: Código identificador internacional da obra.

Saída esperada:
  Registro do acervo com título, autor e gênero (ficção, não-ficção, poesia,
  biografia) de cada obra, incluindo ano de publicação entre 1950 e 2024.
  Permite consultas por autor, gênero ou período de publicação."""

TEMPERATURE = 0
MAX_TOKENS = 200
HARD_CAP_LEN = 420
MIN_LEN_WARN = 120
NUM_CTX = 8192          # maior que no v4-gen: o insumo aqui é bem mais longo

# Resíduos de template embutidos nos próprios valores do catálogo v3.
# Duas variantes existem na base real (verificado no catalog_v3.json):
#   "Descreva o significado de 'X' no contexto logístico - ..."  (tabelas SQL)
#   "Descreva o significado de 'X' - ..."                        (API/planilhas)
# E o separador varia entre traço e ponto final. Cobrir tudo, senão o
# prefixo sobrevive à limpeza em parte dos campos e entra no prompt.
PREF_COLUNA = re.compile(
    r"^\s*Descreva o significado de\s*'[^']*'\s*(no contexto logístico)?\s*[-–.:]\s*(Ex:)?\s*",
    re.I)
PREF_GENERICO = re.compile(
    r"^\s*(Ex:|Exemplo:)\s*", re.I)
# Prefixo "nu": o valor é só a instrução do template, sem conteúdo depois.
PREF_NU = re.compile(
    r"^\s*Descreva o significado de\s*'[^']*'\s*(no contexto logístico)?\s*[-–.:]?\s*$", re.I)
PREF_QUANDO = re.compile(
    r"^\s*(Ex:\s*)?Quando o agente (deve|não deve) consultar (esta|este)[^?]*\?\s*", re.I)

ROTULO_TIPO = {"sql": "Tabela SQL", "api": "Endpoint REST", "spreadsheets": "Planilha"}


def _log(m=""):
    print(m, flush=True)


def _ts():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def limpar(txt, coluna=False):
    """Remove resíduo de template do valor, preservando o conteúdo escrito à mão."""
    if not txt:
        return ""
    t = str(txt).strip()
    if coluna:
        # Caso 1: prefixo seguido de conteúdo real -> remove só o prefixo.
        t = PREF_COLUNA.sub("", t)
        # Caso 2: prefixo NU, sem nada depois (coluna de fato não preenchida
        # na base: verificado em 2 de 152). Vira vazio, e o chamador emite
        # apenas o nome da coluna, sem inventar significado.
        if PREF_NU.match(t):
            return ""
    t = PREF_QUANDO.sub("", t)
    t = PREF_GENERICO.sub("", t)
    return t.strip()


def _redundante(a, b):
    """True se b não acrescenta nada a a (contido, ou quase idêntico)."""
    if not b:
        return True
    na, nb = re.sub(r"\W+", " ", a.lower()).strip(), re.sub(r"\W+", " ", b.lower()).strip()
    return nb in na or na in nb


def _iter_sources(catalog):
    src = catalog.get("sources", {})
    for tipo, sub in (("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")):
        for nome, meta in (src.get(tipo, {}).get(sub, {}) or {}).items():
            yield tipo, nome, meta


def colunas_de(tipo, meta):
    """Devolve {campo: significado} conforme a modalidade da fonte."""
    if tipo == "sql":
        return meta.get("columns") or {}
    if tipo == "api":
        params = (meta.get("parameters") or {}).get("query_params") or {}
        campos = (meta.get("response_schema") or {}).get("result_object_fields") or {}
        return {**params, **campos}
    cols = {}
    for aba in (meta.get("sheets") or {}).values():
        if isinstance(aba, dict):
            cols.update(aba.get("columns") or {})
    return cols or (meta.get("columns") or {})


def montar_bloco(tipo, nome, meta):
    """Monta o insumo de UMA fonte a partir da documentação manual do v3."""
    linhas = [f"TIPO: {tipo}", f"NOME: {nome}"]

    desc = limpar(meta.get("description"))
    papel = limpar(meta.get("business_role"))
    usar = limpar(meta.get("when_to_use"))
    nao_usar = limpar(meta.get("when_NOT_to_use"))

    if desc:
        linhas.append(f"DOCUMENTAÇÃO: {desc}")
    # business_role costuma repetir description no v3 — só entra se acrescentar
    if papel and not _redundante(desc, papel):
        linhas.append(f"PAPEL: {papel}")
    if usar:
        linhas.append(f"QUANDO USAR: {usar}")
    if nao_usar:
        linhas.append(f"QUANDO NÃO USAR: {nao_usar}")

    cols = colunas_de(tipo, meta)
    if cols:
        linhas.append("CAMPOS E SIGNIFICADOS:")
        for c, cm in cols.items():
            sig = ""
            if isinstance(cm, dict):
                sig = limpar(cm.get("description"), coluna=True)
                if not sig and cm.get("type"):
                    sig = f"({cm['type']})"
            linhas.append(f"  {c}: {sig}" if sig else f"  {c}")

    return "\n".join(linhas)


class OllamaClient:
    def __init__(self, model, base_url="http://localhost:11434"):
        self.model, self.base_url = model, base_url.rstrip("/")
        try:
            urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=3)
        except Exception as e:
            raise ConnectionError(
                f"Ollama não acessível em {self.base_url}.\n"
                f"Inicie com: ollama serve\nConfira com: ollama list\nErro: {e}")

    def query(self, user_msg, system_prompt):
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg}],
            "stream": False,
            "options": {"temperature": TEMPERATURE, "num_predict": MAX_TOKENS,
                       "num_ctx": NUM_CTX},
        }).encode("utf-8")
        t0 = time.monotonic()
        req = urllib.request.Request(f"{self.base_url}/api/chat", data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            res = json.loads(r.read().decode("utf-8"))
        return (res.get("message", {}).get("content", "").strip(),
                round((time.monotonic() - t0) * 1000, 2))


def limpar_saida(t):
    t = t.strip()
    t = re.sub(r"^```.*?\n|```$", "", t, flags=re.S).strip()
    if len(t) >= 2 and t[0] in "\"'" and t[-1] in "\"'":
        t = t[1:-1].strip()
    return t


def validar(texto, todos_ids, este_id):
    w = []
    if len(texto) < MIN_LEN_WARN:
        w.append(f"descritor curto ({len(texto)} chars)")
    if len(texto) > HARD_CAP_LEN:
        w.append(f"descritor longo ({len(texto)} chars), será truncado")
    vaz = [s for s in todos_ids
           if s != este_id and s.split(".", 1)[-1].lower() in texto.lower()]
    if vaz:
        w.append(f"menção possível a outra fonte: {vaz}")
    if re.match(r"^\s*(este|esta|esse|essa)\s+(catálogo|fonte|tabela|conjunto)", texto, re.I):
        w.append("começa com frase de preenchimento proibida pela regra 3")
    return w


def main():
    ap = argparse.ArgumentParser(
        description="Gera catalog_v3_doc.json: descritor sintetizado da documentação manual do v3.")
    ap.add_argument("--v3", required=True, help="catalog_v3.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    v3_path = Path(args.v3)
    catalog = json.load(open(v3_path, encoding="utf-8"))
    fontes = list(_iter_sources(catalog))
    todos_ids = [f"{t}.{n}" for t, n, _ in fontes]
    _log(f"[i] {len(fontes)} fontes carregadas de {v3_path}\n")

    if args.dry_run:
        tamanhos = []
        for tipo, nome, meta in fontes:
            bloco = montar_bloco(tipo, nome, meta)
            tamanhos.append(len(bloco))
            _log("═" * 70)
            _log(f"FONTE: {tipo}.{nome}")
            _log("─" * 70)
            _log(bloco)
            _log(f"\n[bloco: {len(bloco)} chars]\n")
        _log(f"[dry-run] Nenhuma chamada ao Ollama. "
             f"Bloco médio {sum(tamanhos)//len(tamanhos)} chars, "
             f"máx {max(tamanhos)} (num_ctx={NUM_CTX}).")
        return

    cli = OllamaClient(args.model, args.ollama_url)
    _log(f"[✓] Ollama conectado, modelo: {args.model}\n")

    saida = copy.deepcopy(catalog)
    transcript, lens = [], []

    for i, (tipo, nome, meta) in enumerate(fontes, 1):
        sid = f"{tipo}.{nome}"
        bloco = montar_bloco(tipo, nome, meta)
        _log(f"[{i:>2}/{len(fontes)}] gerando {sid} ...")
        try:
            bruto, ms = cli.query(bloco, PROMPT_SISTEMA)
        except Exception as e:
            _log(f"    [X] falha: {e}")
            transcript.append({"source": sid, "error": str(e)})
            continue

        desc = limpar_saida(bruto)
        avisos = validar(desc, todos_ids, sid)
        truncado = False
        if len(desc) > HARD_CAP_LEN:
            desc = desc[:HARD_CAP_LEN].rsplit(" ", 1)[0] + "…"
            truncado = True
        lens.append(len(desc))

        for kk, sub in (("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")):
            if kk == tipo and nome in saida["sources"][kk][sub]:
                saida["sources"][kk][sub][nome]["embedding_hint"] = desc

        transcript.append({"source": sid, "prompt_user": bloco, "raw_output": bruto,
                           "descriptor_final": desc, "len_chars": len(desc),
                           "truncated": truncado, "latency_ms": ms, "warnings": avisos})
        _log(f"    [✓] {len(desc)} chars, {ms:.0f} ms"
             + ("  ⚠ " + "; ".join(avisos) if avisos else ""))

    saida["metadata"] = {
        "catalog_version": "3.1.0-doc",
        "generated_at": _ts(),
        "generator": f"build_catalog_v3_doc.py :: {args.model} (Ollama local)",
        "provenance": ("descritor sintetizado por LLM local a partir da DOCUMENTAÇÃO "
                      "MANUAL do catálogo v3 (description, business_role, when_to_use, "
                      "when_NOT_to_use e descrições de coluna); uma chamada isolada por "
                      "fonte; temperature=0; mesmo gerador, formato e teto do v4-gen, "
                      "variando apenas a procedência do conteúdo"),
        "generation_params": {"model": args.model, "temperature": TEMPERATURE,
                              "max_tokens": MAX_TOKENS, "num_ctx": NUM_CTX,
                              "hard_cap_len_chars": HARD_CAP_LEN},
        "descriptor_len": {"n": len(lens),
                           "mean": round(sum(lens) / max(len(lens), 1), 1),
                           "min": min(lens) if lens else 0,
                           "max": max(lens) if lens else 0},
        "reference_v3_hint_mean_chars": 333.9,
        "prompt_divergence_note": ("o prompt de sistema difere do v4-gen apenas na cláusula "
                                   "que descreve o insumo e no exemplo ilustrativo, pois o "
                                   "insumo é prosa e não esquema; as 5 regras e o alvo de "
                                   "comprimento são idênticos"),
    }

    out = Path(args.out) if args.out else v3_path.with_name("catalog_v3_doc.json")
    json.dump(saida, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    _log(f"\n[✓] Catálogo escrito: {out}")

    tp = out.with_name(out.stem + "_transcript.json")
    json.dump({"prompt_sistema": PROMPT_SISTEMA, "por_fonte": transcript},
              open(tp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    _log(f"[✓] Transcript: {tp}")

    nw = sum(1 for t in transcript if t.get("warnings"))
    _log(f"\n[RESUMO] {len(lens)} descritores, média "
         f"{saida['metadata']['descriptor_len']['mean']} chars "
         f"(v4-gen: 267,6 · hint v3 original: 333,9), {nw} com avisos.")


if __name__ == "__main__":
    main()

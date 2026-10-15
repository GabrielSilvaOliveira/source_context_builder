#!/usr/bin/env python3
"""
build_catalog_v4.py
─────────────────────────────────────────────────────────────────────────────
Geração AUTOMÁTICA de catálogo para o SCB, sem curadoria manual de descritores.

Motivação
─────────
O catálogo v3 tem `embedding_hint` escritos à mão e iterados olhando o
desempenho por cluster do benchmark (ver `_doc` de embedding_hints_v3.json).
Isso (a) cria circularidade metodológica e (b) infla a sobreposição léxica
query×catálogo, o que favorece o BM25 tanto quanto os modelos semânticos.

Este script produz catálogos cujo descritor deriva APENAS de metadados
estruturais extraídos das fontes, sem qualquer texto escrito à mão e sem
qualquer contato com as consultas do benchmark.

Pipeline
────────
  [base]        extração estrutural (reusa build_catalog_v2) + perfilamento
                de valores  ->  catalog_v4_base.json   (artefato NEUTRO)
  [render-min]  base -> catalog_v4_min.json   (nome + nomes de colunas)

A variante v4-gen (descritor gerado por LLM local a partir do base) fica em
script separado, para manter o artefato neutro congelado e auditável.

GARANTIA: este script NUNCA escreve em catalog_v3.json nem em qualquer
caminho declarado como `output` no build_config.json. Todos os artefatos vão
para --outdir (padrão: ./catalog_v4/).

Revisão 2 (pós-auditoria do catalog_v4_base.json v1)
─────────────────────────────────────────────────────────────────────────────
Correções aplicadas nesta versão, todas motivadas por achados da auditoria:

  [FIX 1] Paginação real na API. O perfilamento anterior lia só a primeira
          página (25 registros) e classificava quase tudo como categórico
          por tabela pequena demais. Agora pagina até PROFILE_API_MAX_RECORDS.

  [FIX 2] Colunas categóricas sem nenhum valor informativo (só vazio/zero)
          passam a ser marcadas kind="empty" em vez de "categorical", para
          a Fase C/D saber ignorá-las e não gastar orçamento de descritor
          com ruído.

  [FIX 3] Valores categóricos longos são truncados em VALUE_TRUNCATE_CHARS,
          decisão do usuário para não estourar o orçamento do descritor com
          texto livre longo (ex.: laudos técnicos, referências de portaria).

  [FIX 4] Lista de bloqueio de perfilamento (BLOCKLIST_VALUE_PROFILE): colunas
          cujos valores NÃO são listados, mesmo sendo estruturalmente
          categóricas, enquanto o mascaramento completo (fora do escopo deste
          script) não é aplicado à base. A coluna continua aparecendo no
          catálogo (nome + tipo), só sem amostra de valor. Hoje contém
          ESTADOMATERIAL e DESTINOMATERIAL por decisão do usuário
          (13/08/2026) — ajuste a lista livremente conforme a auditoria.

Uso
───
  # Fase A — extrai e perfila (precisa de MySQL + API + planilhas acessíveis)
  python build_catalog_v4.py base \
      --config build_config.json \
      --outdir ./catalog_v4/

  # Fase B — renderiza a variante mínima (offline, determinística)
  python build_catalog_v4.py render-min \
      --base ./catalog_v4/catalog_v4_base.json \
      --out  ./catalog_v4/catalog_v4_min.json
"""

import argparse
import copy
import json
import os
import sys
import getpass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES DE DESENHO
# ─────────────────────────────────────────────────────────────────────────────

# Campos escritos à mão. São REMOVIDOS do catálogo-base: o objetivo do v4 é
# justamente medir o SCB sem curadoria humana de descritor.
MANUAL_FIELDS = (
    "description", "business_role", "when_to_use", "when_NOT_to_use",
    "embedding_hint", "reasoning", "_doc",
)

# Coluna é tratada como CATEGÓRICA (valores listáveis) até este nº de distintos.
MAX_CATEGORICAL_CARDINALITY = 25

# Teto de valores efetivamente listados por coluna categórica.
MAX_VALUES_LISTED = 25

# Colunas com mais distintos que isto são tratadas como identificador/texto
# livre: só nome e tipo, sem amostra de valor.
HIGH_CARDINALITY_HINT = 0.9   # razão distintos/linhas acima da qual é ID

# [FIX 1] Teto de registros lidos por endpoint de API para perfilamento.
# Antes só a 1ª página (25) era lida, o que distorcia cardinalidade e valores.
PROFILE_API_MAX_RECORDS = 1000
PROFILE_API_PAGE_SIZE = 200

# [FIX 3] Comprimento máximo de um valor categórico individual. Acima disso,
# o valor é truncado com marcador "…". Decisão do usuário (13/08/2026):
# preserva categorias curtas ("Autorizar descarga") e corta frases longas
# (laudos técnicos, referências de portaria com data e unidade).
VALUE_TRUNCATE_CHARS = 40

# [FIX 4] Colunas cujos VALORES não são listados no perfil, mesmo sendo
# estruturalmente categóricas. A coluna continua aparecendo (nome + tipo).
# Motivo: contêm referência a unidades/portarias ainda não mascaradas na
# base (mascaramento completo fica para a camera-ready). Comparação
# case-insensitive, por nome de coluna, em qualquer fonte.
BLOCKLIST_VALUE_PROFILE = {
    "estadomaterial", "destinomaterial",
    "local_hoje",              # nomes de unidade militar completos
    "localidade_da_entrega",   # idem, achado no mesmo endpoint
                                 # (api.monitoramento_sistema_satelital_list),
                                 # auditoria do dry-run da Fase C (14/08/2026)
}

# [FIX 5] Redação cirúrgica de VALORES individuais que vazam informação
# sensível dentro de colunas majoritariamente úteis (ao contrário da
# BLOCKLIST acima, que bloqueia a coluna inteira). Usar quando só uma
# fração dos valores é problemática e o resto é vocabulário de domínio
# genuíno que vale preservar. Chave: nome da coluna (case-insensitive).
# Valor: conjunto de strings a remover, comparação exata pós-strip.
# Os valores a remover NÃO ficam no código (repositório público): são lidos de
# catalog_generation/value_redaction.local.json (no .gitignore). Formato em
# value_redaction.example.json: {"<coluna>": ["<valor exato>", ...]}.
VALUE_REDACTION_FILE = Path(__file__).resolve().parent / "value_redaction.local.json"
_VALUE_REDACTION_CACHE = None


def _load_value_redaction() -> dict:
    global _VALUE_REDACTION_CACHE
    if _VALUE_REDACTION_CACHE is None:
        if not VALUE_REDACTION_FILE.exists():
            sys.exit(
                f"[!] Arquivo de redação de valores não encontrado: {VALUE_REDACTION_FILE}\n"
                f"    Crie-o a partir de value_redaction.example.json (formato "
                f'{{"coluna": ["valor exato a remover"]}}); ele não é versionado.'
            )
        with open(VALUE_REDACTION_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        _VALUE_REDACTION_CACHE = {k: set(v) for k, v in raw.items()}
    return _VALUE_REDACTION_CACHE


def _redact_values(col_name: str, values: list) -> list:
    table = _load_value_redaction()
    redact = table.get(col_name.strip().lower()) or table.get(col_name.strip())
    if not redact:
        return values
    return [v for v in values if str(v).strip() not in redact]

# Valores considerados "vazios" para fins de kind="empty" (FIX 2).
EMPTY_VALUE_TOKENS = {"", "0", "0.0", "none", "null", "nan", "-"}

TS = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_blocked(col_name: str) -> bool:
    return col_name.strip().lower() in BLOCKLIST_VALUE_PROFILE


def _truncate(value: str) -> str:
    s = str(value)
    if len(s) <= VALUE_TRUNCATE_CHARS:
        return s
    return s[:VALUE_TRUNCATE_CHARS].rstrip() + "…"


def _is_informative(values) -> bool:
    """True se ao menos um valor sobra depois de filtrar tokens vazios."""
    return any(str(v).strip().lower() not in EMPTY_VALUE_TOKENS for v in values)


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def _log(msg=""):
    print(msg, flush=True)


def _strip_manual(node):
    """Remove recursivamente todo campo escrito à mão."""
    if isinstance(node, dict):
        return {k: _strip_manual(v) for k, v in node.items()
                if k not in MANUAL_FIELDS}
    if isinstance(node, list):
        return [_strip_manual(x) for x in node]
    return node


def _save(obj, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    _log(f"[✓] Escrito: {path}")


def _classify_column(col_name, col_meta, n_rows):
    """
    Decide como a coluna deve ser perfilada.
    Retorna: 'categorical' | 'numeric' | 'identifier' | 'text'
    """
    ctype = str(col_meta.get("type", "")).upper()
    card = col_meta.get("cardinality")
    is_pk = bool(col_meta.get("is_pk"))

    if is_pk:
        return "identifier"

    if card is not None and n_rows:
        if card <= MAX_CATEGORICAL_CARDINALITY:
            return "categorical"
        if card / max(n_rows, 1) >= HIGH_CARDINALITY_HINT:
            return "identifier"

    if any(t in ctype for t in ("INT", "DECIMAL", "FLOAT", "DOUBLE", "NUMERIC")):
        return "numeric"
    if any(t in ctype for t in ("DATE", "TIME", "YEAR")):
        return "numeric"     # perfilado por faixa min/max

    if card is not None and card <= MAX_CATEGORICAL_CARDINALITY:
        return "categorical"
    return "text"


# ─────────────────────────────────────────────────────────────────────────────
# FASE A.1 — EXTRAÇÃO ESTRUTURAL (reuso do build_catalog_v2)
# ─────────────────────────────────────────────────────────────────────────────

def extract_structural(config, outdir, force=True):
    """
    Chama o orquestrador do build_catalog_v2 com o `output` REDIRECIONADO
    para dentro de outdir, de modo que o catálogo v3 nunca seja tocado.
    """
    from build_catalog_v2 import build_catalog as v2_build

    raw_path = os.path.join(outdir, "_raw_extracted.json")
    cfg = copy.deepcopy(config)
    cfg["output"] = raw_path

    # Se sobrou execução anterior, remove para forçar extração limpa a partir
    # do template (o v2 usa o arquivo existente como base, se houver).
    if os.path.exists(raw_path):
        os.remove(raw_path)
        _log(f"[i] Extração anterior removida: {raw_path}")

    _log("─" * 60)
    _log("[FASE A.1] Extração estrutural (build_catalog_v2, output redirecionado)")
    _log("─" * 60)

    v2_build(cfg, force=force)

    with open(raw_path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# FASE A.2 — PERFILAMENTO DE VALORES
# ─────────────────────────────────────────────────────────────────────────────

def profile_sql(catalog, sql_cfg):
    """Perfila valores reais das colunas SQL via consultas de leitura."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        _log("[!] sqlalchemy ausente. Perfilamento SQL PULADO.")
        return catalog

    tables = catalog.get("sources", {}).get("sql", {}).get("tables", {})
    if not tables:
        return catalog

    password = sql_cfg.get("password") or os.environ.get("MYSQL_PASSWORD") \
        or getpass.getpass(f"Senha MySQL ({sql_cfg['user']}@{sql_cfg['host']}) [perfilamento]: ")
    url = (f"mysql+pymysql://{sql_cfg['user']}:{password}"
           f"@{sql_cfg['host']}:{sql_cfg.get('port', 3306)}"
           f"/{sql_cfg['database']}?charset=utf8mb4")
    engine = create_engine(url)

    _log("─" * 60)
    _log("[FASE A.2] Perfilamento de valores — SQL")
    _log("─" * 60)

    with engine.connect() as conn:
        for tname, tmeta in tables.items():
            n_rows = tmeta.get("row_count") or 0
            profile = {}
            for cname, cmeta in (tmeta.get("columns") or {}).items():
                if not isinstance(cmeta, dict):
                    continue
                kind = _classify_column(cname, cmeta, n_rows)
                entry = {"type": cmeta.get("type"), "kind": kind}

                if kind == "categorical" and _is_blocked(cname):
                    # [FIX 4] estruturalmente categórica, mas na lista de
                    # bloqueio: mantém a coluna visível, sem amostra de valor.
                    entry["kind"] = "categorical_blocked"
                    entry["note"] = ("valores não listados: coluna na "
                                      "BLOCKLIST_VALUE_PROFILE (aguardando "
                                      "mascaramento completo)")
                    profile[cname] = entry
                    continue

                try:
                    if kind == "categorical":
                        q = text(f"SELECT DISTINCT `{cname}` FROM `{tname}` "
                                 f"WHERE `{cname}` IS NOT NULL LIMIT {MAX_VALUES_LISTED}")
                        vals = [str(r[0]) for r in conn.execute(q).fetchall()]
                        vals = _redact_values(cname, vals)              # [FIX 5]
                        if _is_informative(vals):
                            # [FIX 3] trunca valores individuais longos
                            entry["values"] = [_truncate(v) for v in vals]
                        else:
                            # [FIX 2] só ruído (vazio/zero): marca como tal
                            entry["kind"] = "empty"
                    elif kind == "numeric":
                        q = text(f"SELECT MIN(`{cname}`), MAX(`{cname}`) FROM `{tname}`")
                        lo, hi = conn.execute(q).fetchone()
                        entry["range"] = [str(lo), str(hi)]
                    # identifier / text: só nome e tipo
                except Exception as e:            # coluna problemática não derruba o run
                    entry["profile_error"] = str(e)[:120]
                profile[cname] = entry

            tmeta["value_profile"] = profile
            n_cat = sum(1 for v in profile.values() if v["kind"] == "categorical")
            n_empty = sum(1 for v in profile.values() if v["kind"] == "empty")
            n_blocked = sum(1 for v in profile.values() if v["kind"] == "categorical_blocked")
            extra = f", {n_empty} vazias" if n_empty else ""
            extra += f", {n_blocked} bloqueadas" if n_blocked else ""
            _log(f"  sql.{tname:42s} {len(profile):>3} col  ({n_cat} categóricas{extra})")

    return catalog


def profile_spreadsheets(catalog, sheets_cfg):
    """Perfila valores das planilhas com pandas."""
    try:
        import pandas as pd
    except ImportError:
        _log("[!] pandas ausente. Perfilamento de planilhas PULADO.")
        return catalog

    files = catalog.get("sources", {}).get("spreadsheets", {}).get("files", {})
    if not files:
        return catalog

    by_key = {s["key"]: s for s in (sheets_cfg or [])}

    _log("─" * 60)
    _log("[FASE A.2] Perfilamento de valores — Planilhas")
    _log("─" * 60)

    for fkey, fmeta in files.items():
        cfg = by_key.get(fkey)
        path = (cfg or {}).get("file") or fmeta.get("path") or fmeta.get("file")
        if not path or not os.path.exists(str(path)):
            _log(f"  [!] spreadsheets.{fkey}: arquivo não localizado, perfil pulado")
            continue
        try:
            df = pd.read_excel(path) if str(path).lower().endswith((".xlsx", ".xls")) \
                else pd.read_csv(path)
        except Exception as e:
            _log(f"  [!] spreadsheets.{fkey}: falha ao ler ({str(e)[:80]})")
            continue

        n_rows = len(df)
        profile = {}
        for col in df.columns:
            cname = str(col)
            s = df[col].dropna()
            card = int(s.nunique())
            entry = {"type": str(df[col].dtype), "cardinality": card}

            if card <= MAX_CATEGORICAL_CARDINALITY and card > 0 and _is_blocked(cname):
                entry["kind"] = "categorical_blocked"
                entry["note"] = ("valores não listados: coluna na "
                                  "BLOCKLIST_VALUE_PROFILE (aguardando "
                                  "mascaramento completo)")
            elif card <= MAX_CATEGORICAL_CARDINALITY and card > 0:
                vals = [str(v) for v in s.unique()[:MAX_VALUES_LISTED]]
                vals = _redact_values(cname, vals)                       # [FIX 5]
                if _is_informative(vals):
                    entry["kind"] = "categorical"
                    entry["values"] = [_truncate(v) for v in vals]      # [FIX 3]
                else:
                    entry["kind"] = "empty"                              # [FIX 2]
            elif card / max(n_rows, 1) >= HIGH_CARDINALITY_HINT:
                entry["kind"] = "identifier"
            elif str(df[col].dtype).startswith(("int", "float", "datetime")):
                entry["kind"] = "numeric"
                if len(s):
                    entry["range"] = [str(s.min()), str(s.max())]
            else:
                entry["kind"] = "text"
            profile[cname] = entry

        fmeta["value_profile"] = profile
        fmeta.setdefault("row_count", n_rows)
        n_cat = sum(1 for v in profile.values() if v.get("kind") == "categorical")
        n_empty = sum(1 for v in profile.values() if v.get("kind") == "empty")
        n_blocked = sum(1 for v in profile.values() if v.get("kind") == "categorical_blocked")
        extra = f", {n_empty} vazias" if n_empty else ""
        extra += f", {n_blocked} bloqueadas" if n_blocked else ""
        _log(f"  spreadsheets.{fkey:34s} {len(profile):>3} col  ({n_cat} categóricas{extra})")

    return catalog


def _fetch_paginated(requests, url, headers, max_records, page_size):
    """
    [FIX 1, revisão 3] Híbrido: segue `next` quando o endpoint o fornece
    (resolve o caso `distribuicao_list`, que pagina por `page` e ignora
    `offset`), e cai para incremento manual de `offset` quando o endpoint
    não declara `next` (caso de `manutencao_ap_direto_list` e
    `monitoramento_starlink_list`, que já funcionavam por offset puro).

    A distinção crucial é entre "a chave `next` existe no corpo da resposta"
    (ainda que seu valor seja None, o que sinaliza fim de dados de forma
    autoritativa) e "a chave não existe" (o endpoint não usa essa convenção,
    e o único sinal disponível é o tamanho da página).
    """
    records, offset, next_url = [], 0, None

    while len(records) < max_records:
        try:
            if next_url:
                resp = requests.get(next_url, headers=headers, timeout=20, params=None)
            else:
                resp = requests.get(url, headers=headers, timeout=20,
                                    params={"limit": page_size, "offset": offset})
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            if records:
                _log(f"      [!] paginação interrompida após {len(records)} "
                     f"registros ({str(e)[:70]})")
            else:
                raise
            break

        page = data
        has_next_key = False
        next_val = None
        if isinstance(data, dict):
            has_next_key = "next" in data
            next_val = data.get("next")
            for k in ("results", "data", "items", "content"):
                if isinstance(data.get(k), list):
                    page = data[k]
                    break
            else:
                page = [data]

        if not isinstance(page, list) or not page:
            break

        records.extend(r for r in page if isinstance(r, dict))

        if has_next_key:
            # Endpoint declara paginação por `next`: é a fonte de verdade.
            if not next_val:
                break
            next_url = next_val
        else:
            # Sem convenção de `next`: só sabemos continuar por offset
            # enquanto a página vier cheia. Página curta = fim.
            if len(page) < page_size:
                break
            offset += page_size

    return records[:max_records]


def profile_api(catalog, api_cfg):
    """
    Perfila campos de endpoints REST paginando até PROFILE_API_MAX_RECORDS.
    Degrada graciosamente: se o endpoint não responder ou não paginar,
    usa o que conseguir buscar (mesmo que seja só a 1ª página) em vez de
    abortar, mas registra o tamanho real da amostra no artefato para que
    a limitação fique auditável, não escondida.
    """
    try:
        import requests
    except ImportError:
        _log("[!] requests ausente. Perfilamento de API PULADO.")
        return catalog

    endpoints = catalog.get("sources", {}).get("api", {}).get("endpoints", {})
    if not endpoints or not api_cfg:
        return catalog

    base_url = api_cfg.get("base_url") or catalog["sources"]["api"].get("base_url", "")
    token = api_cfg.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    by_key = {ep["key"]: ep for ep in api_cfg.get("endpoints", [])}

    _log("─" * 60)
    _log("[FASE A.2] Perfilamento de valores — API REST")
    _log(f"  (paginando até {PROFILE_API_MAX_RECORDS} registros/endpoint, "
         f"páginas de {PROFILE_API_PAGE_SIZE})")
    _log("─" * 60)

    for ekey, emeta in endpoints.items():
        path = (by_key.get(ekey) or {}).get("path") or emeta.get("path")
        if not path:
            _log(f"  [!] api.{ekey}: path desconhecido, perfil pulado")
            continue
        url = base_url.rstrip("/") + "/" + str(path).lstrip("/")

        try:
            sample = _fetch_paginated(requests, url, headers,
                                       PROFILE_API_MAX_RECORDS, PROFILE_API_PAGE_SIZE)
        except Exception as e:
            _log(f"  [!] api.{ekey}: falha na chamada ({str(e)[:80]})")
            continue

        if not sample:
            _log(f"  [!] api.{ekey}: resposta sem registros tabulares")
            continue

        profile = {}
        for field in {k for r in sample for k in r}:
            vals = [r.get(field) for r in sample if r.get(field) is not None]
            distinct = {str(v) for v in vals if not isinstance(v, (dict, list))}
            entry = {"cardinality": len(distinct)}

            if field.strip().lower() in BLOCKLIST_VALUE_PROFILE:
                entry["kind"] = "categorical_blocked"
                entry["note"] = ("valores não listados: campo na "
                                  "BLOCKLIST_VALUE_PROFILE (aguardando "
                                  "mascaramento completo)")
            elif 0 < len(distinct) <= MAX_CATEGORICAL_CARDINALITY:
                distinct = set(_redact_values(field, sorted(distinct)))   # [FIX 5]
                if _is_informative(distinct):
                    entry["kind"] = "categorical"
                    entry["values"] = sorted(_truncate(v) for v in distinct)[:MAX_VALUES_LISTED]
                else:
                    entry["kind"] = "empty"                              # [FIX 2]
            elif vals and isinstance(vals[0], (int, float)):
                entry["kind"] = "numeric"
                nums = [v for v in vals if isinstance(v, (int, float))]
                if nums:
                    entry["range"] = [str(min(nums)), str(max(nums))]
            else:
                entry["kind"] = "text"
            profile[field] = entry

        emeta["value_profile"] = profile
        emeta["sample_size"] = len(sample)
        if len(sample) < PROFILE_API_MAX_RECORDS:
            emeta["sample_note"] = ("amostra menor que o teto: endpoint sinalizou fim "
                                     "dos dados (sem `next`) ou não respondeu paginação")
        n_cat = sum(1 for v in profile.values() if v.get("kind") == "categorical")
        n_empty = sum(1 for v in profile.values() if v.get("kind") == "empty")
        n_blocked = sum(1 for v in profile.values() if v.get("kind") == "categorical_blocked")
        extra = f", {n_empty} vazios" if n_empty else ""
        extra += f", {n_blocked} bloqueados" if n_blocked else ""
        _log(f"  api.{ekey:42s} {len(profile):>3} campos ({n_cat} categóricos{extra}) "
             f"[amostra={len(sample)}]")

    return catalog


# ─────────────────────────────────────────────────────────────────────────────
# FASE A — ORQUESTRADOR DO CATÁLOGO-BASE NEUTRO
# ─────────────────────────────────────────────────────────────────────────────

def cmd_base(args):
    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)

    os.makedirs(args.outdir, exist_ok=True)

    catalog = extract_structural(config, args.outdir, force=True)

    # Remove TODO campo manual antes de qualquer outra coisa.
    before = json.dumps(catalog, ensure_ascii=False)
    catalog = _strip_manual(catalog)
    catalog.pop("context_hints", None)          # regras manuais de roteamento
    after = json.dumps(catalog, ensure_ascii=False)
    _log(f"\n[i] Campos manuais removidos: {len(before) - len(after)} caracteres de texto curado")

    # Perfilamento de valores
    if config.get("sql"):
        catalog = profile_sql(catalog, config["sql"])
    if config.get("spreadsheets"):
        catalog = profile_spreadsheets(catalog, config["spreadsheets"])
    if config.get("api"):
        catalog = profile_api(catalog, config["api"])

    catalog["metadata"] = {
        "catalog_version": "4.0.0-base",
        "generated_at": TS(),
        "generator": "build_catalog_v4.py :: base",
        "provenance": "extração estrutural + perfilamento de valores; "
                      "ZERO texto escrito à mão; sem contato com o benchmark",
        "manual_fields_removed": list(MANUAL_FIELDS),
        "params": {
            "max_categorical_cardinality": MAX_CATEGORICAL_CARDINALITY,
            "max_values_listed": MAX_VALUES_LISTED,
            "high_cardinality_hint": HIGH_CARDINALITY_HINT,
        },
    }

    out = os.path.join(args.outdir, "catalog_v4_base.json")
    _save(catalog, out)

    _resumo(catalog)
    _log("\n[CHECKPOINT] Audite catalog_v4_base.json antes da Fase C/D.")
    _log("             Confira: nenhum descritor curado sobreviveu; os valores")
    _log("             categóricos fazem sentido; nada sigiloso foi amostrado.")


def _resumo(catalog):
    src = catalog.get("sources", {})
    _log("\n" + "─" * 60)
    _log("RESUMO DO CATÁLOGO-BASE")
    _log("─" * 60)
    total = 0
    tot_blocked = tot_empty = 0
    for kind, sub in (("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")):
        for name, meta in (src.get(kind, {}).get(sub, {}) or {}).items():
            prof = meta.get("value_profile", {})
            cats = [c for c, v in prof.items() if v.get("kind") == "categorical"]
            blocked = [c for c, v in prof.items() if v.get("kind") == "categorical_blocked"]
            empty = [c for c, v in prof.items() if v.get("kind") == "empty"]
            tot_blocked += len(blocked)
            tot_empty += len(empty)
            total += 1
            extra = f"  bloqueadas={len(blocked)}" if blocked else ""
            extra += f"  vazias={len(empty)}" if empty else ""
            _log(f"  {kind}.{name:38s} campos={len(prof):>3}  categóricos={len(cats):>2}{extra}")
    _log(f"\n  TOTAL DE FONTES: {total}")
    if tot_blocked:
        _log(f"  [i] {tot_blocked} coluna(s) com valor bloqueado (BLOCKLIST_VALUE_PROFILE): "
             f"{', '.join(sorted(BLOCKLIST_VALUE_PROFILE))}")
    if tot_empty:
        _log(f"  [i] {tot_empty} coluna(s) categórica(s) sem valor informativo, marcadas 'empty'")


# ─────────────────────────────────────────────────────────────────────────────
# FASE B — RENDERIZAÇÃO v4-min
# ─────────────────────────────────────────────────────────────────────────────

def _iter_sources(catalog):
    """Itera (tipo, nome, meta) sobre as três modalidades."""
    src = catalog.get("sources", {})
    for kind, sub in (("sql", "tables"), ("api", "endpoints"), ("spreadsheets", "files")):
        for name, meta in (src.get(kind, {}).get(sub, {}) or {}).items():
            yield kind, name, meta


def render_min(meta, kind, name):
    """
    v4-min: nome da fonte + nomes das colunas. Nada mais.
    É o PISO: o mínimo recuperável sem qualquer trabalho humano.
    """
    cols = list((meta.get("value_profile") or meta.get("columns") or {}).keys())
    return f"{kind}.{name}: " + ", ".join(cols)


def cmd_render_min(args):
    with open(args.base, encoding="utf-8") as f:
        catalog = json.load(f)

    catalog = copy.deepcopy(catalog)
    lens = []
    for kind, name, meta in _iter_sources(catalog):
        desc = render_min(meta, kind, name)
        meta["embedding_hint"] = desc      # campo que o SCB/BM25/LLM consomem
        lens.append(len(desc))
        _log(f"  {kind}.{name:38s} {len(desc):>5} chars")

    catalog["metadata"] = {
        "catalog_version": "4.0.0-min",
        "generated_at": TS(),
        "generator": "build_catalog_v4.py :: render-min",
        "descriptor_recipe": "nome_da_fonte + nomes_das_colunas",
        "provenance": "determinístico; sem LLM; sem texto humano; "
                      "sem contato com o benchmark",
        "descriptor_len": {
            "n": len(lens),
            "mean": round(sum(lens) / max(len(lens), 1), 1),
            "min": min(lens) if lens else 0,
            "max": max(lens) if lens else 0,
        },
    }
    _save(catalog, args.out)
    _log(f"\n[i] Descritor médio: {catalog['metadata']['descriptor_len']['mean']} chars "
         f"(v3 curado, para referência: ~330 chars)")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Catálogo v4: descritores derivados só de metadados estruturais.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("base", help="Fase A: extrai + perfila -> catalog_v4_base.json")
    pb.add_argument("--config", required=True, help="build_config.json (o mesmo do v2)")
    pb.add_argument("--outdir", default="./catalog_v4/")
    pb.set_defaults(func=cmd_base)

    pm = sub.add_parser("render-min", help="Fase B: base -> catalog_v4_min.json")
    pm.add_argument("--base", required=True)
    pm.add_argument("--out", default="./catalog_v4/catalog_v4_min.json")
    pm.set_defaults(func=cmd_render_min)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

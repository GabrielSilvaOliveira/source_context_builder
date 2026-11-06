"""Índice do texto REALMENTE consumido pelos modelos (espelha _doc_from_source)."""
import json
from pathlib import Path
_GENERIC_COLUMNS = frozenset({"CODIGO","ID","id","ULTIMAATUALIZACAO","created_at","updated_at","DATAINCLUSAOCARGA","usuario_decisao_id"})
_MAX_EMBEDDING_COLS = 8

def _clean(value, field_name):
    if not value or "[MANUAL]" in value:
        return field_name.replace("_"," ")
    return value.strip()

def _doc(name, meta, columns):
    hint = meta.get("embedding_hint","")
    if hint and "[MANUAL]" not in hint:
        return f"{name}\n{hint.strip()}"
    parts=[name]
    for field in ("description","business_role"):
        c=_clean(meta.get(field,""), field)
        if c: parts.append(c)
    if columns:
        cp=[]
        for cn, cm in columns.items():
            if cn in _GENERIC_COLUMNS: continue
            if isinstance(cm, dict):
                cp.append(f"{cn}: {_clean(cm.get('description',''), cn)}")
            else:
                cp.append(cn)
            if len(cp) >= _MAX_EMBEDDING_COLS: break
        if cp: parts.append("Campos: " + "; ".join(cp))
    return "\n".join(parts)

def build_consumed_index(catalog_path):
    cat=json.loads(Path(catalog_path).read_text(encoding='utf-8'))
    src=cat["sources"]; idx={}
    for n,meta in src.get("sql",{}).get("tables",{}).items():
        idx[f"sql.{n}"]=_doc(f"Tabela SQL: {n}", meta, meta.get("columns",{}))
    for n,meta in src.get("api",{}).get("endpoints",{}).items():
        params=meta.get("parameters",{}).get("query_params",{})
        rf=meta.get("response_schema",{}).get("result_object_fields",{})
        idx[f"api.{n}"]=_doc(f"API endpoint: {n} ({meta.get('method','GET')} {meta.get('path','')})", meta, {**params,**rf})
    for n,meta in src.get("spreadsheets",{}).get("files",{}).items():
        allc={}
        for sm in meta.get("sheets",{}).values(): allc.update(sm.get("columns",{}))
        t=_doc(f"Planilha: {meta.get('filename',n)}", meta, allc)
        idx[f"spreadsheets.{n}"]=t; idx[f"xlsx.{n}"]=t
    return idx

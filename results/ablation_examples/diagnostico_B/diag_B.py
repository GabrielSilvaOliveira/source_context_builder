import json, sys, urllib.request, time, collections
sys.path.insert(0, "benchmark/runners")
import run_llm_benchmark as r

OUT = sys.argv[1]
cat = json.load(open("catalogs/v4/catalog_v4_min.json", encoding="utf-8"))
bench = {q["id"]: q for q in json.load(open("benchmark/benchmark_queries_final_v2.json", encoding="utf-8"))["queries"]}
sysp = r.build_system_prompt(r.serialize_compressed(cat), "no_examples_schema")
ids = r.compressed_source_ids(cat)


def call(query, schema, num_predict=None, timeout=300):
    opts = {"temperature": 0}
    if num_predict:
        opts["num_predict"] = num_predict
    body = {"model": "llama3.2:latest", "stream": False, "options": opts, "format": schema,
            "messages": [{"role": "system", "content": sysp}, {"role": "user", "content": query}]}
    req = urllib.request.Request("http://localhost:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as f:
        res = json.loads(f.read().decode())
    return {"content": res["message"]["content"], "done_reason": res.get("done_reason"),
            "eval_count": res.get("eval_count"), "prompt_eval_count": res.get("prompt_eval_count"),
            "s": round(time.monotonic() - t, 1)}


def describe(c):
    items = [x for x in __import__("re").findall(r'"((?:sql|api|spreadsheets)\.[a-zA-Z_]+)"', c)]
    cnt = collections.Counter(items)
    ws = sum(ch in " \n\t\r" for ch in c)
    return {"len_chars": len(c), "n_ids": len(items), "n_distintos": len(cnt),
            "mais_repetido": cnt.most_common(2), "frac_espaco": round(ws / max(len(c), 1), 3),
            "termina_json_valido": _valid(c)}


def _valid(c):
    try:
        json.loads(c); return True
    except Exception:
        return False


res = {}
base = r.source_schema(ids)
for qid in ("Q01", "Q02"):
    q = bench[qid]["query"]
    out = call(q, base, num_predict=512)
    res[f"schema_exato__{qid}"] = {"query": q, **out, "analise": describe(out["content"])}
    print(qid, "schema exato", out["done_reason"], out["eval_count"], out["s"], describe(out["content"]))

# uniqueItems / maxItems impostos?
one = {"type": "object", "properties": {"sources": {"type": "array", "minItems": 4,
       "uniqueItems": True, "items": {"type": "string", "enum": ["sql.materiais", "sql.unidades"]}}},
       "required": ["sources"]}
out = call(bench["Q02"]["query"], one, num_predict=256)
res["teste_uniqueItems__enum2_minItems4"] = {**out, "analise": describe(out["content"])}
print("uniqueItems (enum 2, minItems 4):", out["done_reason"], out["content"][:200])

mx = {"type": "object", "properties": {"sources": {"type": "array", "maxItems": 2,
      "items": {"type": "string", "enum": ids}}}, "required": ["sources"]}
out = call(bench["Q02"]["query"], mx, num_predict=256)
res["teste_maxItems2__Q02"] = {**out, "analise": describe(out["content"])}
print("maxItems=2:", out["done_reason"], out["content"][:200])

prop = {"type": "object", "properties": {"sources": {"type": "array", "maxItems": 16, "uniqueItems": True,
        "items": {"type": "string", "enum": ids}}}, "required": ["sources"]}
for qid in ("Q01", "Q02"):
    out = call(bench[qid]["query"], prop, num_predict=512)
    res[f"proposta_maxItems16_unique__{qid}"] = {**out, "analise": describe(out["content"])}
    print(qid, "proposta (maxItems16+unique)", out["done_reason"], out["eval_count"], out["s"], describe(out["content"]))

json.dump(res, open(OUT + "/diagnostico_B.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

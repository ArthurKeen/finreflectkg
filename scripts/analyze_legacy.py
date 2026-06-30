"""Analyze the schema of the legacy financial-kg-2025-08-26 graph, to learn how
nodes/edges/types are modeled after the 'Entity' label was dropped."""

import json
from arango import req

DB = "financial-kg-2025-08-26"


def aql(q, b=None):
    _, r = req("POST", "/_api/cursor", {"query": q, "bindVars": b or {}}, db=DB, timeout=120)
    return r.get("result", []), r.get("errorMessage")


# collections
_, c = req("GET", "/_api/collection?excludeSystem=true", db=DB)
cols = [(x["name"], x["type"]) for x in c.get("result", [])]
print("== collections (type 2=doc, 3=edge) ==")
for n, t in sorted(cols):
    _, cnt = req("GET", f"/_api/collection/{n}/count", db=DB)
    print(f"  {n:30} type={t}  count={cnt.get('count'):,}")

# pick the doc + edge collections
doc_cols = [n for n, t in cols if t == 2]
edge_cols = [n for n, t in cols if t == 3]

print("\n== sample vertex documents ==")
for dc in doc_cols[:5]:
    res, err = aql(f"FOR d IN `{dc}` LIMIT 2 RETURN d")
    print(f"  [{dc}]")
    for d in res:
        print("   ", json.dumps(d)[:400])

print("\n== sample edge documents ==")
for ec in edge_cols[:5]:
    res, err = aql(f"FOR e IN `{ec}` LIMIT 2 RETURN e")
    print(f"  [{ec}]")
    for e in res:
        print("   ", json.dumps(e)[:400])

# how is node type represented? distinct types if a `type` field exists
print("\n== node 'type' field distribution (first doc collection) ==")
if doc_cols:
    res, err = aql(f"FOR d IN `{doc_cols[0]}` COLLECT t = d.type WITH COUNT INTO c SORT c DESC LIMIT 15 RETURN {{t, c}}")
    print("  ", res, err)

# relationship representation: one edge collection with type prop, or many?
print("\n== edge 'type' / label representation ==")
for ec in edge_cols[:3]:
    res, err = aql(f"FOR e IN `{ec}` COLLECT t = e.type WITH COUNT INTO c SORT c DESC LIMIT 10 RETURN {{t, c}}")
    print(f"  [{ec}] type field:", res, err)

# indexes on the main collections
print("\n== indexes ==")
for n, t in cols:
    _, idx = req("GET", f"/_api/index?collection={n}", db=DB)
    for i in idx.get("indexes", []):
        if i.get("type") != "primary":
            print(f"  {n}: {i.get('type')} {i.get('fields')} (name={i.get('name')})")

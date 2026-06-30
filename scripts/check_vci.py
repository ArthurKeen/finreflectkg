"""Investigate whether the vertex-centric indexes are actually used, and
measure the supernode case with vs. without type pruning."""

import json

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")


def explain(query, bind):
    _, ex = req("POST", "/_api/explain", {"query": query, "bindVars": bind}, db=DB)
    out = []
    for n in ex.get("plan", {}).get("nodes", []):
        if n.get("type") in ("IndexNode", "TraversalNode"):
            entry = {"node": n["type"]}
            if n.get("type") == "IndexNode":
                entry["indexes"] = [i["name"] for i in n.get("indexes", [])]
            else:
                base = n.get("indexes", {}).get("base", [])
                lvls = n.get("indexes", {}).get("levels", {})
                entry["base"] = [i.get("name") for i in base]
                entry["levels"] = {k: [i.get("name") for i in v] for k, v in lvls.items()}
            out.append(entry)
    rules = ex.get("plan", {}).get("rules", [])
    return out, [r for r in rules if "traversal" in r or "index" in r]


def profile(query, bind):
    _, r = req("POST", "/_api/cursor",
               {"query": query, "bindVars": bind, "options": {"profile": 2}},
               db=DB, timeout=600)
    prof = r.get("extra", {}).get("profile", {})
    stats = r.get("extra", {}).get("stats", {})
    return {
        "ms": round(prof.get("executing", 0) * 1000, 1),
        "scanned": stats.get("scannedIndex", 0),
        "filtered": stats.get("filtered", 0),
        "results": len(r.get("result", [])),
    }


# net income FIN_METRIC node id
_, b = req("POST", "/_api/cursor",
           {"query": "FOR n IN Node FILTER n.name=='net income' AND n.type=='FIN_METRIC' LIMIT 1 RETURN n._id"},
           db=DB)
net_income = b["result"][0]
print("net income node:", net_income, "\n")

# 1) direct edge-collection query with full key prefix -> should pick VCI
q_direct = """FOR e IN relations
  FILTER e._to == @n AND e.type == 'discloses' AND e._fromType == 'ORG'
  RETURN e._key"""
idx, rules = explain(q_direct, {"n": net_income})
print("[1] direct edge query (_to,type,_fromType):")
print("    indexes:", json.dumps(idx))

# 2) traversal WITH type pruning  (cluster requires `WITH Node`)
q_trav_filtered = """WITH Node
  FOR v,e IN 1..1 INBOUND @n relations
  FILTER e.type == 'discloses' AND e._fromType == 'ORG'
  RETURN v._key"""
idx2, _ = explain(q_trav_filtered, {"n": net_income})
print("\n[2] traversal INBOUND + FILTER type/_fromType:")
print("    indexes:", json.dumps(idx2))

# 3) traversal WITHOUT filter (baseline supernode expansion)
q_trav_all = """WITH Node FOR v,e IN 1..1 INBOUND @n relations RETURN v._key"""
idx3, _ = explain(q_trav_all, {"n": net_income})
print("\n[3] traversal INBOUND no filter:")
print("    indexes:", json.dumps(idx3))

print("\n== timing (profile) ==")
print("  [1] direct edge query   :", profile(q_direct, {"n": net_income}))
print("  [2] traversal + filter  :", profile(q_trav_filtered, {"n": net_income}))
print("  [3] traversal no filter :", profile(q_trav_all, {"n": net_income}))

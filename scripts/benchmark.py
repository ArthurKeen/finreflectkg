"""Benchmark suite for the FinReflectKG graph (PRD §6), cross-distribution capable.

Latency on the shared remote cluster is noisy (same query observed 0.2-20 s), so
each query is run with a warmup + N timed iterations and we report min / median
(min ~= best-case server time, least contended). The DETERMINISTIC signals are:

  - profile counters: scannedIndex / scannedFull / filtered  (index effectiveness)
  - explain locality: RemoteNode / ScatterNode / GatherNode counts + TraversalNode
    isLocalGraphNode  (cross-DBServer hops -- the G7 placement comparison)

Typed 1-hop queries are written as DIRECT edge-collection queries because that is
the access path that uses the vertex-centric indexes (pattern traversals use the
generic edge index -- see load-report.md).

Usage:
  .venv/bin/python scripts/benchmark.py                 # all existing target dbs
  .venv/bin/python scripts/benchmark.py --dbs FinReflectKG   # one db (legacy mode)
  .venv/bin/python scripts/benchmark.py --iters 11 --out data/bench.json

Per §6, running against FinReflectKG (flexible 1-shard), FinReflectKgOneShard
(OneShard) and FinReflectKgSmart (Disjoint SmartGraph) quantifies the effect of
placement -- especially OneShard/SmartGraph eliminating the RemoteNode hops the
baseline pays on multi-hop traversals.
"""

import argparse
import json
import pathlib
import statistics

from arango import ENV, req

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET_DBS = ["FinReflectKG", "FinReflectKgOneShard", "FinReflectKgSmart"]
DEFAULT_ITERS = 7


def run(db, query, bind=None):
    """Execute a query with profiling; return latency + deterministic counters."""
    body = {"query": query, "bindVars": bind or {}, "options": {"profile": 2},
            "batchSize": 1000}
    _, r = req("POST", "/_api/cursor", body, db=db, timeout=600)
    prof = r.get("extra", {}).get("profile", {})
    stats = r.get("extra", {}).get("stats", {})
    return {
        "ms": prof.get("executing", 0) * 1000,
        "scannedIndex": stats.get("scannedIndex", 0),
        "scannedFull": stats.get("scannedFull", 0),
        "filtered": stats.get("filtered", 0),
        "results": r.get("count") if r.get("count") is not None else len(r.get("result", [])),
        "error": r.get("errorMessage"),
    }


def explain(db, query, bind=None):
    """Explain a query and summarize cluster placement from the plan node types."""
    body = {"query": query, "bindVars": bind or {}}
    _, r = req("POST", "/_api/explain", body, db=db, timeout=120)
    plan = r.get("plan", {})
    counts = {}
    traversal_local = None
    for n in plan.get("nodes", []):
        t = n.get("type")
        counts[t] = counts.get(t, 0) + 1
        if t == "TraversalNode" and "isLocalGraphNode" in n:
            traversal_local = n["isLocalGraphNode"]
    return {
        "remote": counts.get("RemoteNode", 0),
        "scatter": counts.get("ScatterNode", 0),
        "gather": counts.get("GatherNode", 0),
        "distribute": counts.get("DistributeNode", 0),
        "traversalLocal": traversal_local,
        "error": r.get("errorMessage"),
    }


def first(db, query, bind=None):
    _, r = req("POST", "/_api/cursor", {"query": query, "bindVars": bind or {}},
               db=db, timeout=120)
    res = r.get("result", [])
    return res[0] if res else None


def discover(db):
    """Find real entities to query in THIS db (smart keys differ per db)."""
    return {
        "company": first(db, """FOR e IN relations
            FILTER e.type=='operates_in' AND e._toType=='GPE'
            COLLECT f=e._from WITH COUNT INTO c FILTER c>=5 SORT c DESC LIMIT 1 RETURN f"""),
        "net_income": first(db, """FOR n IN Node
            FILTER n.name=='net income' AND n.type=='FIN_METRIC' LIMIT 1 RETURN n._id"""),
        "ticker": first(db, "FOR e IN relations LIMIT 1 RETURN e.ticker"),
        "stake_target": first(db, """FOR e IN relations FILTER e.type=='has_stake_in'
            COLLECT t=e._to WITH COUNT INTO c SORT c DESC LIMIT 1 RETURN t"""),
    }


def build_suite(ent):
    """The PRD §6 query classes, bound to discovered entities."""
    c, n, tk, t = ent["company"], ent["net_income"], ent["ticker"], ent["stake_target"]
    return [
        {"name": "1. node point lookup (name)", "bind": {}, "note": "node_name index",
         "query": "FOR n IN Node FILTER n.name=='net income' RETURN n._key"},
        {"name": "2. 1-hop typed OUT (operates_in->GPE)", "bind": {"c": c},
         "note": "VCI vci_from_type_totype",
         "query": """FOR e IN relations
            FILTER e._from==@c AND e.type=='operates_in' AND e._toType=='GPE' RETURN e._to"""},
        {"name": "3. reverse typed IN (has_stake_in)", "bind": {"t": t},
         "note": "VCI vci_to_type_fromtype",
         "query": """FOR e IN relations
            FILTER e._to==@t AND e.type=='has_stake_in' AND e._fromType=='ORG' RETURN e._from"""},
        {"name": "4a. supernode pruned (net income, VCI)", "bind": {"n": n},
         "note": "VCI; scans only matches",
         "query": """FOR e IN relations
            FILTER e._to==@n AND e.type=='discloses' AND e._fromType=='ORG' RETURN e._from"""},
        {"name": "4b. supernode unpruned (traversal)", "bind": {"n": n},
         "note": "edge index; scans ALL inbound",
         "query": "WITH Node FOR v,e IN 1..1 INBOUND @n relations RETURN e._key"},
        {"name": "5. 2-hop (company->metric->peers)", "bind": {"c": c},
         "note": "multi-hop traversal",
         "query": """WITH Node FOR v1,e1 IN 1..1 OUTBOUND @c relations
             FILTER e1.type=='discloses' AND e1._toType=='FIN_METRIC' LIMIT 25
           FOR v2,e2 IN 1..1 INBOUND v1 relations
             FILTER e2.type=='discloses' LIMIT 50 RETURN DISTINCT e2._from"""},
        {"name": "6. temporal slice (ticker+year)", "bind": {"tk": tk},
         "note": "rel_ticker_year index",
         "query": """FOR e IN relations
            FILTER e.ticker==@tk AND e.year>=2022 AND e.year<=2024 RETURN e._key"""},
        {"name": "7. NL-grounding (edge->chunk text)", "bind": {"c": c},
         "note": "edge -> chunks join",
         "query": """FOR e IN relations FILTER e._from==@c AND e.type=='operates_in' LIMIT 20
             LET ch = DOCUMENT('chunks', e.chunkKey)
           RETURN {rel:e.type, to:e._to, text: ch.text ? SUBSTRING(ch.text,0,80) : null}"""},
        # --- Class 8: label-rooted aggregations (no bound start node) --------- #
        # "all :ORG that ..." — the access pattern the node-anchored VCIs cannot
        # serve (no bound _from/_to). Engaged by the type-leading indexes
        # vci_type_{fromtype_totype,totype_fromtype} added 2026-07-22; without them
        # the label-wide filter has no selective index and scans the full edge
        # collection (times out). Not entity-bound — fixed type filters.
        {"name": "8a. label agg: orgs by #GPE (operates_in)", "bind": {},
         "note": "vci_type_fromtype_totype (from-anchored)",
         "query": """FOR e IN relations
            FILTER e.type=='operates_in' AND e._fromType=='ORG' AND e._toType=='GPE'
            COLLECT org=e._from WITH COUNT INTO c FILTER c>3
            SORT c DESC LIMIT 25 RETURN {org, c}"""},
        {"name": "8b. label agg: GPEs by #ORG (operates_in rev)", "bind": {},
         "note": "vci_type_totype_fromtype (to-anchored)",
         "query": """FOR e IN relations
            FILTER e.type=='operates_in' AND e._toType=='GPE' AND e._fromType=='ORG'
            COLLECT gpe=e._to WITH COUNT INTO c
            SORT c DESC LIMIT 25 RETURN {gpe, c}"""},
        {"name": "8c. label agg: orgs in litigation (involved_in)", "bind": {},
         "note": "vci_type_fromtype_totype (small slice)",
         "query": """FOR e IN relations
            FILTER e.type=='involved_in' AND e._fromType=='ORG' AND e._toType=='LITIGATION'
            COLLECT org=e._from WITH COUNT INTO c
            SORT c DESC LIMIT 25 RETURN {org, c}"""},
    ]


def bench(db, spec, iters):
    run(db, spec["query"], spec["bind"])  # warmup
    samples = [run(db, spec["query"], spec["bind"]) for _ in range(iters)]
    ms = sorted(s["ms"] for s in samples)
    s0 = samples[-1]
    loc = explain(db, spec["query"], spec["bind"])
    row = {
        "name": spec["name"], "note": spec["note"],
        "ms_min": round(ms[0], 1), "ms_median": round(statistics.median(ms), 1),
        "ms_max": round(ms[-1], 1),
        "scannedIndex": s0["scannedIndex"], "scannedFull": s0["scannedFull"],
        "filtered": s0["filtered"], "results": s0["results"],
        "remote": loc["remote"], "gather": loc["gather"], "scatter": loc["scatter"],
        "traversalLocal": loc["traversalLocal"],
        "error": s0["error"] or loc["error"],
    }
    print(f"  {row['name']:38} min={row['ms_min']:>8} med={row['ms_median']:>8} "
          f"scanIdx={row['scannedIndex']:>8} remote={row['remote']:>2} gather={row['gather']:>2}"
          f" -> {row['results']} rows" + (f"  [{row['error']}]" if row['error'] else ""))
    return row


def run_db(db, iters):
    print(f"\n########## {db} ##########")
    ent = discover(db)
    print(f"entities: company={ent['company']} net_income={ent['net_income']} "
          f"ticker={ent['ticker']} stake_target={ent['stake_target']}")
    rows = [bench(db, s, iters) for s in build_suite(ent)]
    return {"db": db, "entities": ent, "rows": rows}


def print_comparison(results):
    names = [r["name"] for r in results[0]["rows"]]
    dbs = [r["db"] for r in results]
    print("\n== cross-distribution comparison (median ms / remoteNodes) ==")
    header = "query".ljust(40) + "".join(d[:16].ljust(18) for d in dbs)
    print(header)
    for i, name in enumerate(names):
        line = name.ljust(40)
        for r in results:
            row = r["rows"][i]
            cell = f"{row['ms_median']}ms r{row['remote']}"
            line += cell.ljust(18)
        print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbs", nargs="*", help="databases to benchmark (default: existing target dbs)")
    ap.add_argument("--iters", type=int, default=DEFAULT_ITERS, help="timed iterations per query")
    ap.add_argument("--out", default=None, help="output json path")
    args = ap.parse_args()

    if args.dbs:
        dbs = args.dbs
    else:
        _, b = req("GET", "/_api/database")
        existing = set(b.get("result", []))
        dbs = [d for d in TARGET_DBS if d in existing] or [ENV.get("ARANGO_DB", "FinReflectKG")]

    results = [run_db(db, args.iters) for db in dbs]

    if args.out:
        out = pathlib.Path(args.out)
    else:
        out = ROOT / "data" / ("benchmark_cross.json" if len(dbs) > 1 else "benchmark_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"dbs": dbs, "results": results}, indent=2))
    print(f"\nwrote {out}")

    if len(results) > 1:
        print_comparison(results)


if __name__ == "__main__":
    main()

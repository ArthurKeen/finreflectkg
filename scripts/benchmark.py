"""Benchmark suite for the FinReflectKG graph (PRD §6).

Latency on the shared remote cluster is noisy (same query observed 0.2–20 s), so
each query is run with a warmup + N timed iterations; we report min / median
(min ≈ best-case server time, least contended) alongside the DETERMINISTIC
profile counters (scannedIndex / scannedFull / filtered), which are the stable
signal for index effectiveness.

Typed 1-hop queries are written as DIRECT edge-collection queries because that
is the access path that uses the vertex-centric indexes (pattern traversals use
the generic edge index — see load-report.md).
"""

import json
import statistics
import pathlib

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")
ITERS = 7
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "benchmark_results.json"


def run(query, bind=None):
    body = {"query": query, "bindVars": bind or {}, "options": {"profile": 2},
            "batchSize": 1000}
    _, r = req("POST", "/_api/cursor", body, db=DB, timeout=600)
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


def bench(name, query, bind=None, note=""):
    run(query, bind)  # warmup
    samples = [run(query, bind) for _ in range(ITERS)]
    ms = sorted(s["ms"] for s in samples)
    s0 = samples[-1]
    row = {
        "name": name, "note": note,
        "ms_min": round(ms[0], 1), "ms_median": round(statistics.median(ms), 1),
        "ms_max": round(ms[-1], 1),
        "scannedIndex": s0["scannedIndex"], "scannedFull": s0["scannedFull"],
        "filtered": s0["filtered"], "results": s0["results"], "error": s0["error"],
    }
    print(f"  {name:38} min={row['ms_min']:>8} med={row['ms_median']:>8} "
          f"scanIdx={row['scannedIndex']:>8} scanFull={row['scannedFull']:>7} "
          f"filt={row['filtered']:>7} -> {row['results']} rows"
          + (f"  [{row['error']}]" if row['error'] else ""))
    return row


def first(query, bind=None):
    _, r = req("POST", "/_api/cursor", {"query": query, "bindVars": bind or {}}, db=DB, timeout=120)
    res = r.get("result", [])
    return res[0] if res else None


def main():
    # --- discover real entities to query ---
    company = first("""FOR e IN relations FILTER e.type=='operates_in' AND e._toType=='GPE'
        COLLECT f=e._from WITH COUNT INTO c FILTER c>=5 SORT c DESC LIMIT 1 RETURN f""")
    net_income = first("FOR n IN Node FILTER n.name=='net income' AND n.type=='FIN_METRIC' LIMIT 1 RETURN n._id")
    ticker = first("FOR e IN relations LIMIT 1 RETURN e.ticker")
    stake_target = first("""FOR e IN relations FILTER e.type=='has_stake_in'
        COLLECT t=e._to WITH COUNT INTO c SORT c DESC LIMIT 1 RETURN t""")
    print(f"entities: company={company} net_income={net_income} ticker={ticker} stake_target={stake_target}\n")

    rows = []
    print("== benchmark suite ==")

    # 1. point lookup by name (Node.node_name index)
    rows.append(bench("1. node point lookup (name)",
        "FOR n IN Node FILTER n.name=='net income' RETURN n._key",
        note="uses node_name index"))

    # 2. 1-hop typed outbound — VCI 1 (_from,type,_toType)
    rows.append(bench("2. 1-hop typed OUT (operates_in->GPE)",
        """FOR e IN relations FILTER e._from==@c AND e.type=='operates_in' AND e._toType=='GPE'
           RETURN e._to""", {"c": company}, note="VCI vci_from_type_totype"))

    # 3. reverse typed inbound — VCI 2 (_to,type,_fromType)
    rows.append(bench("3. reverse typed IN (who has_stake_in X)",
        """FOR e IN relations FILTER e._to==@t AND e.type=='has_stake_in' AND e._fromType=='ORG'
           RETURN e._from""", {"t": stake_target}, note="VCI vci_to_type_fromtype"))

    # 4a. supernode WITH type pruning (VCI) — direct edge query
    rows.append(bench("4a. supernode pruned (net income, VCI)",
        """FOR e IN relations FILTER e._to==@n AND e.type=='discloses' AND e._fromType=='ORG'
           RETURN e._from""", {"n": net_income}, note="VCI; scans only matches"))

    # 4b. supernode WITHOUT pruning (full inbound) — pattern traversal, edge index
    rows.append(bench("4b. supernode unpruned (traversal)",
        "WITH Node FOR v,e IN 1..1 INBOUND @n relations RETURN e._key", {"n": net_income},
        note="edge index; scans ALL inbound"))

    # 5. 2-hop path (company -> concept -> other companies disclosing same concept)
    rows.append(bench("5. 2-hop (company->metric->peers)",
        """WITH Node FOR v1,e1 IN 1..1 OUTBOUND @c relations
             FILTER e1.type=='discloses' AND e1._toType=='FIN_METRIC' LIMIT 25
           FOR v2,e2 IN 1..1 INBOUND v1 relations
             FILTER e2.type=='discloses' LIMIT 50 RETURN DISTINCT e2._from""",
        {"c": company}, note="multi-hop traversal"))

    # 6. temporal/company slice — rel_ticker_year index
    rows.append(bench("6. temporal slice (ticker+year range)",
        """FOR e IN relations FILTER e.ticker==@tk AND e.year>=2022 AND e.year<=2024
           RETURN e._key""", {"tk": ticker}, note="rel_ticker_year index"))

    # 7. NL-grounding join: typed edges -> source chunk text
    rows.append(bench("7. NL-grounding (edge->chunk text)",
        """FOR e IN relations FILTER e._from==@c AND e.type=='operates_in' LIMIT 20
             LET ch = DOCUMENT('chunks', e.chunkKey)
           RETURN {rel:e.type, to:e._to, text: ch.text ? SUBSTRING(ch.text,0,80) : null}""",
        {"c": company}, note="edge -> chunks join"))

    OUT.write_text(json.dumps({"entities": {"company": company, "net_income": net_income,
        "ticker": ticker, "stake_target": stake_target}, "rows": rows}, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

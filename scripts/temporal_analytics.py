"""P4 — temporal analytics over the time-travel DB (§4.8): how influence and topics
shift across the 10 fiscal years.

Pregel is unavailable on this managed cluster (/_api/control_pregel -> 404) and GAE
(scripts/analytics.py) runs on whole collections, so per-as-of-year PageRank would need
materialized snapshot collections. This script instead computes reliable, cheap AQL
signals directly over the as-of edge sets:

  1. per-anchor-year CENTRALITY — top targets by as-of in-degree (weighted degree
     centrality; a robust proxy — the true PageRank-per-year is an optional GAE extension)
  2. TOPIC SHIFT — share of edges by target node type per year (what companies increasingly
     talk about)
  3. RISERS — specific concepts whose as-of in-degree grew most from the first to last year

Read-only. Usage: .venv/bin/python scripts/temporal_analytics.py [--db FinReflectKgTemporal]
"""

import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from arango import req  # scripts/arango.py

YEARS = [2014, 2017, 2020, 2024]


def aql(db, query, bind=None):
    st, b = req("POST", "/_api/cursor", {"query": query, "bindVars": bind or {}}, db=db, timeout=300)
    if st not in (200, 201):
        raise SystemExit(f"AQL error {st}: {b.get('errorMessage')}\n{query[:200]}")
    return b.get("result")


def asof(y):
    return y * 100 + 6   # mid-year YYYYMM


def top_central(db, y, n=10):
    return aql(db, """
        FOR e IN relations FILTER e.validFrom <= @t AND e.validTo > @t
          COLLECT tgt = e._to WITH COUNT INTO deg
          SORT deg DESC LIMIT @n
          LET d = DOCUMENT(tgt)
          RETURN {name: d.name, type: d.type, deg: deg}""", {"t": asof(y), "n": n})


def type_share(db, y):
    rows = aql(db, """
        FOR e IN relations FILTER e.validFrom <= @t AND e.validTo > @t
          COLLECT ty = e._toType WITH COUNT INTO c RETURN {ty: ty, c: c}""", {"t": asof(y)})
    tot = sum(r["c"] for r in rows) or 1
    return {r["ty"]: r["c"] / tot for r in rows}, tot


def indegree_map(db, y, limit=800):
    rows = aql(db, """
        FOR e IN relations FILTER e.validFrom <= @t AND e.validTo > @t
          COLLECT tgt = e._to WITH COUNT INTO deg
          SORT deg DESC LIMIT @n
          LET d = DOCUMENT(tgt)
          RETURN {key: tgt, name: d.name, type: d.type, deg: deg}""", {"t": asof(y), "n": limit})
    return {r["key"]: r for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="FinReflectKgTemporal")
    a = ap.parse_args()
    db = a.db

    print(f"=== temporal centrality — top targets by as-of in-degree ({db}) ===")
    for y in YEARS:
        print(f"\n  as of mid-{y}:")
        for r in top_central(db, y, 10):
            print(f"    {r['deg']:>7,}  {r['name']}  ({r['type']})")

    print("\n=== topic shift — share of edges by target type, by year ===")
    shares = {y: type_share(db, y)[0] for y in YEARS}
    types = sorted({t for y in YEARS for t in shares[y]},
                   key=lambda t: -shares[YEARS[-1]].get(t, 0))[:12]
    hdr = "  {:<22}".format("type") + "".join(f"{y:>9}" for y in YEARS) + "     Δ(first→last)"
    print(hdr)
    for t in types:
        cells = "".join(f"{shares[y].get(t,0)*100:>8.1f}%" for y in YEARS)
        delta = (shares[YEARS[-1]].get(t, 0) - shares[YEARS[0]].get(t, 0)) * 100
        print(f"  {t:<22}{cells}     {delta:+.1f} pts")

    print(f"\n=== risers — concepts with the biggest as-of in-degree gain {YEARS[0]}→{YEARS[-1]} ===")
    first, last = indegree_map(db, YEARS[0]), indegree_map(db, YEARS[-1])
    gains = []
    for k, r in last.items():
        base = first.get(k, {}).get("deg", 0)
        gains.append((r["deg"] - base, base, r))
    gains.sort(key=lambda x: -x[0])
    for delta, base, r in gains[:12]:
        print(f"    +{delta:>6,}  ({base:>5,}→{r['deg']:>6,})  {r['name']}  ({r['type']})")


if __name__ == "__main__":
    main()

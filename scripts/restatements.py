"""P3 — bitemporal / backward-looking-assertion analysis over the time-travel DB (§4.8).

Two time axes already live on every `relations` edge:
  * VALID time      — `startDate`/`endDate` (fiscal period the fact is about) -> validFrom/validTo
  * TRANSACTION time — `year` (the 10-K filing that asserted it)

A **backward-looking assertion** is a fact a filing asserts about a fiscal period that
predates the filing by >= LAG years (`year - startYear >= LAG`). Formal financial
*restatements* are a subset; most are legitimate historical references (acquisitions,
prior-period impacts). This script quantifies them and demonstrates a **bitemporal
"as-known-as-of" slice** (what we would have known about period P using only filings up to
year K). Read-only. Uses the REST helper (scripts/arango.py); no MCP dependency.

Usage: .venv/bin/python scripts/restatements.py [--db FinReflectKgTemporal] [--lag 2]
"""

import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from arango import req  # scripts/arango.py


def aql(db, query, bind=None):
    st, b = req("POST", "/_api/cursor", {"query": query, "bindVars": bind or {}}, db=db, timeout=300)
    if st not in (200, 201):
        return f"ERR {st} {b.get('errorMessage')}"
    return b.get("result")


def one(db, query, bind=None):
    r = aql(db, query, bind)
    return r[0] if isinstance(r, list) and r else r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="FinReflectKgTemporal")
    ap.add_argument("--lag", type=int, default=2, help="min years (filing - period) to count as backward-looking")
    a = ap.parse_args()
    db, LAG = a.db, a.lag
    # lag in years, from the untouched parsed startDate (validFrom is clamped; startDate is not)
    LAGEXPR = "(e.year - TO_NUMBER(SUBSTRING(e.startDate,0,4)))"

    total = one(db, "RETURN LENGTH(relations)")
    dated = one(db, "RETURN LENGTH(FOR e IN relations FILTER e.startDate != null RETURN 1)")
    bw = one(db, f"RETURN LENGTH(FOR e IN relations FILTER e.startDate!=null AND {LAGEXPR} >= @l RETURN 1)", {"l": LAG})
    print(f"=== backward-looking assertions on {db} (lag >= {LAG}y) ===")
    print(f"total edges         : {total}")
    print(f"with parsed period  : {dated}")
    print(f"backward-looking    : {bw}  ({round(100*bw/dated,2)}% of dated)")

    print("\nlag distribution (filing year - period start year):")
    dist = aql(db, f"""FOR e IN relations FILTER e.startDate!=null AND {LAGEXPR} >= 1
        COLLECT bucket = ({LAGEXPR} >= 10 ? 10 : {LAGEXPR}) WITH COUNT INTO c
        SORT bucket RETURN {{lag: bucket, count: c}}""")
    for d in (dist or []):
        if isinstance(d, dict):
            lbl = f"{d['lag']}y" + ("+" if d['lag'] == 10 else "")
            print(f"  {lbl:>4}: {d['count']:>9,}")

    print(f"\ntop 15 companies by backward-looking assertion count (lag >= {LAG}y):")
    for d in (aql(db, f"""FOR e IN relations FILTER e.startDate!=null AND {LAGEXPR} >= @l
            COLLECT t = e.ticker WITH COUNT INTO c SORT c DESC LIMIT 15
            RETURN {{ticker: t, count: c}}""", {"l": LAG}) or []):
        if isinstance(d, dict):
            print(f"  {d['ticker']:<8} {d['count']:>8,}")

    print(f"\nsample backward-looking facts (lag >= {max(LAG,3)}y, with names):")
    for d in (aql(db, f"""FOR e IN relations FILTER e.startDate!=null AND {LAGEXPR} >= @l
            SORT RAND() LIMIT 6
            RETURN {{ticker:e.ticker, filed:e.year, period:e.startDate, rel:e.type,
                     from:DOCUMENT(e._from).name, to:DOCUMENT(e._to).name}}""", {"l": max(LAG, 3)}) or []):
        if isinstance(d, dict):
            print(f"  [{d['ticker']}] filed {d['filed']} about {d['period']}: "
                  f"{d['from']} -{d['rel']}-> {d['to']}")

    # Bitemporal "as-known-as-of": facts about a period visible only in LATER filings.
    print("\nbitemporal demo — facts about fiscal 2020 (period), by earliest filing year that reported them:")
    for d in (aql(db, """FOR e IN relations
            FILTER e.startDate != null AND SUBSTRING(e.startDate,0,4) == "2020"
            COLLECT filed = e.year WITH COUNT INTO c SORT filed RETURN {filedYear: filed, facts: c}""") or []):
        if isinstance(d, dict):
            print(f"  first knowable from FY{d['filedYear']} filings: {d['facts']:>8,} facts about 2020")


if __name__ == "__main__":
    main()

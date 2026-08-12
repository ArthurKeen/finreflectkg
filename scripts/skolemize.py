"""Phase 2 of the generic-mention fix (docs/generic-mention-conflation.md).

Skolemizes the flagged generic-mention hubs into per-(company, role) BLANK NODES. For every
distinct (ticker, roleLemma) that touches a flagged hub, mint one anonymous node in the
`bnodes` collection:  _key = bn_<ticker>_<roleLemma>,  type = <ROLE> (normalized).

This does NOT mutate `relations` — the source stays intact. The rewiring (redirecting the
flagged hubs' edges to these bnodes) happens at analytics-input time (temporal_pagerank.py's
snapshot materialization reads role_by_hub and rewrites endpoints), so we never copy the
17.5M-edge collection just to change ~35K edges. Idempotent.

Run AFTER flag_generic_mentions.py.
Usage: .venv/bin/python scripts/skolemize.py [--db FinReflectKgTemporal]
"""

import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from arango import req  # scripts/arango.py


def aql(db, query, bind=None, t=300):
    st, b = req("POST", "/_api/cursor", {"query": query, "bindVars": bind or {}}, db=db, timeout=t)
    if st not in (200, 201):
        raise SystemExit(f"AQL {st}: {b.get('errorMessage')}")
    return b.get("result")


def ensure_collection(db, name):
    st, b = req("POST", "/_api/collection", {"name": name, "type": 2}, db=db)
    if st in (200, 201):
        print(f"collection {name}: created")
    elif b.get("errorNum") == 1207:
        print(f"collection {name}: exists")
    else:
        raise SystemExit(f"create {name}: {st} {b}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="FinReflectKgTemporal")
    a = ap.parse_args()
    db = a.db

    role_by_hub = {r["id"]: r["role"] for r in
                   aql(db, "FOR n IN Node FILTER n.isGenericMention == true RETURN {id:n._id, role:n.roleLemma}")}
    if not role_by_hub:
        raise SystemExit("no flagged hubs found — run flag_generic_mentions.py first")

    # distinct (ticker, role) over every edge touching a flagged hub (both directions)
    pairs = set()
    for hub_id, role in role_by_hub.items():
        for tk in aql(db, "FOR e IN relations FILTER e._to == @h OR e._from == @h "
                          "COLLECT t = e.ticker RETURN t", {"h": hub_id}):
            if tk:
                pairs.add((tk, role))

    docs = [{"_key": f"bn_{tk}_{role}", "name": role, "type": role.upper(),
             "isBlankNode": True, "ticker": tk, "roleLemma": role} for (tk, role) in sorted(pairs)]

    ensure_collection(db, "bnodes")
    aql(db, "FOR d IN @docs INSERT d INTO bnodes OPTIONS {overwriteMode:'replace'}", {"docs": docs})

    roles = sorted({r for _, r in pairs})
    tickers = {t for t, _ in pairs}
    print(f"=== Phase 2: skolemized {len(role_by_hub)} hubs -> {len(docs)} blank nodes on {db} ===")
    print(f"  distinct companies: {len(tickers)}   distinct roles: {len(roles)}")
    print(f"  roles: {', '.join(roles)}")
    print(f"  (bnodes carry _key=bn_<ticker>_<role>, type=<ROLE>, isBlankNode=true; "
          f"rewiring happens at snapshot-materialization time)")


if __name__ == "__main__":
    main()

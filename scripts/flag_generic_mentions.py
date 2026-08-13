"""Phase 1 of the generic-mention fix (docs/generic-mention-conflation.md).

Detects and FLAGS the spurious generic-mention super-hubs — anonymous indefinite mentions
('a supplier', 'our customers', 'a third party') that collapsed onto one shared node because
node identity is hash(name|type). Detection = curated role lexicon AND high cross-company
fan-in (distinct tickers). Legitimate shared referents (net income, china, gdp) are NOT in
the lexicon, so they are never flagged.

Non-destructive: stamps `isGenericMention: true`, `roleLemma`, `genericFanIn` on the matching
Node docs. Reversible (clear those fields). Idempotent. Read/updates Node only; no edges touched.

Usage: .venv/bin/python scripts/flag_generic_mentions.py [--db FinReflectKgTemporal] [--min-fan 10] [--clear]
"""

import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from arango import req  # scripts/arango.py

# variant surface form -> canonical role lemma (singular). Only common-noun *roles* — never
# proper names or legitimate shared concepts. Tune here; re-run is idempotent.
ROLE_MAP = {
    "supplier": "supplier", "suppliers": "supplier",
    "customer": "customer", "customers": "customer",
    "competitor": "competitor", "competitors": "competitor",
    "vendor": "vendor", "vendors": "vendor",
    "client": "client", "clients": "client",
    "distributor": "distributor", "distributors": "distributor",
    "subsidiary": "subsidiary", "subsidiaries": "subsidiary",
    "partner": "partner", "partners": "partner",
    "contractor": "contractor", "contractors": "contractor",
    "reseller": "reseller", "resellers": "reseller",
    "borrower": "borrower", "borrowers": "borrower",
    "lender": "lender", "lenders": "lender",
    "counterparty": "counterparty", "counterparties": "counterparty",
    "auditor": "auditor", "auditors": "auditor",
    "shareholder": "shareholder", "shareholders": "shareholder",
    "third party": "third_party", "third parties": "third_party",
    "affiliate": "affiliate", "affiliates": "affiliate",
    "licensee": "licensee", "licensor": "licensor",
    "franchisee": "franchisee", "franchisees": "franchisee",
}

# Junk / placeholder tokens — NON-entities (extraction noise / catch-all buckets). Unlike role
# nouns these are not anonymous real entities, so they are EXCLUDED (edges dropped) at analytics
# time, not skolemized. Surfaced by GAE PageRank ('default' ranked #1 in 2024, 'other' near top).
# NB: a pure fan-in detector is deliberately NOT used — calibration showed the highest-fan-in
# unflagged nodes are legitimate shared concepts (common stock 716 cos, dividend, long-term debt,
# derivatives...) that MUST stay shared. Only the curated lexicon/stoplist can separate those from
# spurious hubs; extend these lists by hand after reviewing --candidates.
JUNK_PLACEHOLDERS = {"default", "other", "various", "misc", "general",
                     "n/a", "none", "unknown", "not applicable", "certain", ""}


def aql(db, query, bind=None, t=300):
    st, b = req("POST", "/_api/cursor", {"query": query, "bindVars": bind or {}}, db=db, timeout=t)
    if st not in (200, 201):
        raise SystemExit(f"AQL {st}: {b.get('errorMessage')}")
    return b.get("result")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="FinReflectKgTemporal")
    ap.add_argument("--min-fan", type=int, default=10, help="min distinct companies (fan-in) to flag")
    ap.add_argument("--clear", action="store_true", help="unflag (remove the fields) and exit")
    ap.add_argument("--candidates", action="store_true",
                    help="also print high-fan-in UNFLAGGED nodes for manual review (not auto-flagged)")
    a = ap.parse_args()
    db = a.db

    if a.clear:
        n = aql(db, "FOR n IN Node FILTER n.isGenericMention == true OR n.isJunkPlaceholder == true "
                    "UPDATE n WITH {isGenericMention:null, roleLemma:null, genericFanIn:null, isJunkPlaceholder:null} "
                    "IN Node OPTIONS {keepNull:false} COLLECT WITH COUNT INTO c RETURN c")
        print(f"cleared {n[0] if n else 0} flags on {db}")
        return

    variants = list(ROLE_MAP.keys())
    # role lemma per matched name, high cross-company fan-in -> flag.
    flagged = aql(db, """
        LET rolemap = @rolemap
        FOR n IN Node FILTER n.name IN @variants
          LET fan = LENGTH(FOR e IN relations FILTER e._to == n._id OR e._from == n._id
                             COLLECT t = e.ticker RETURN t)
          FILTER fan >= @minfan
          LET role = rolemap[n.name]
          UPDATE n WITH {isGenericMention: true, roleLemma: role, genericFanIn: fan} IN Node
          RETURN {name: n.name, type: n.type, role: role, fan: fan}""",
        {"rolemap": ROLE_MAP, "variants": variants, "minfan": a.min_fan})

    flagged.sort(key=lambda r: -r["fan"])
    total_fan_edges = aql(db, """LET ids=(FOR n IN Node FILTER n.isGenericMention==true RETURN n._id)
        RETURN LENGTH(FOR e IN relations FILTER e._to IN ids OR e._from IN ids RETURN 1)""")[0]
    print(f"=== Phase 1: flagged {len(flagged)} generic-mention hubs on {db} "
          f"(min fan-in {a.min_fan}) ===")
    print(f"edges touching a flagged hub: {total_fan_edges:,}\n")
    print(f"  {'name':<20}{'type':<14}{'role':<14}{'fan-in':>7}")
    for r in flagged:
        print(f"  {r['name']:<20}{r['type']:<14}{r['role']:<14}{r['fan']:>7}")

    # --- junk placeholders -> isJunkPlaceholder (EXCLUDE class: edges dropped, NOT skolemized) ---
    junk = aql(db, """
        FOR n IN Node FILTER n.name IN @junk
          LET fan = LENGTH(FOR e IN relations FILTER e._to==n._id OR e._from==n._id COLLECT t=e.ticker RETURN t)
          FILTER fan >= 5
          UPDATE n WITH {isJunkPlaceholder: true, genericFanIn: fan} IN Node
          RETURN {name:n.name, type:n.type, fan:fan}""", {"junk": list(JUNK_PLACEHOLDERS)})
    junk.sort(key=lambda r: -r["fan"])
    print(f"\n=== flagged {len(junk)} junk-placeholder hubs (EXCLUDE class) ===")
    for r in junk:
        print(f"  {r['name']!r:<12}{r['type']:<14}companies={r['fan']:>5}")

    if a.candidates:
        print("\n=== high-fan-in UNFLAGGED nodes (review only — NOT auto-flagged; "
              "most are legitimate shared concepts) ===")
        for r in aql(db, """
            FOR e IN relations FILTER e._toType IN ["ORG","COMP","PERSON","SEGMENT","FIN_INST","PRODUCT","LOGISTICS"]
              COLLECT to=e._to WITH COUNT INTO indeg SORT indeg DESC LIMIT 60
              LET d=DOCUMENT(to)
              FILTER d.isGenericMention != true AND d.isJunkPlaceholder != true
              LET fan=LENGTH(FOR e2 IN relations FILTER e2._to==to COLLECT t=e2.ticker RETURN t)
              FILTER fan >= 50 SORT fan DESC
              RETURN {name:d.name, type:d.type, fan:fan}"""):
            if isinstance(r, dict):
                print(f"  {r['name']!r:<28}{r['type']:<12}companies={r['fan']:>4}")


if __name__ == "__main__":
    main()

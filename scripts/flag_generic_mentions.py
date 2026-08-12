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
    a = ap.parse_args()
    db = a.db

    if a.clear:
        n = aql(db, "FOR n IN Node FILTER n.isGenericMention == true "
                    "UPDATE n WITH {isGenericMention:null, roleLemma:null, genericFanIn:null} "
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


if __name__ == "__main__":
    main()

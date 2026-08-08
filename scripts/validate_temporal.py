"""Validate the FinReflectKgTemporal build (G9/M8, §4.8) — read-only.

Checks: collection counts, temporal-field coverage + range, that the direct as-of
query engages the MDI (via explain), and an as-of spot check on a known fact
(AAPL operates_in over time). Prints a summary; non-zero exit on a hard failure.
"""

import sys

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKgTemporal")
NEVER_EXPIRES = 999912
EXPECTED_RELATIONS = 17_513_372


def aql(q, bind=None):
    st, body = req("POST", "/_api/cursor", {"query": q, "bindVars": bind or {}}, db=DB, timeout=600)
    if st not in (200, 201):
        return f"ERR {st} {body.get('errorMessage')}"
    return body.get("result")


def one(q, bind=None):
    r = aql(q, bind)
    return r[0] if isinstance(r, list) and r else r


def main():
    ok = True
    nodes = one("RETURN LENGTH(Node)")
    rels = one("RETURN LENGTH(relations)")
    print(f"Node count       : {nodes}")
    print(f"relations count  : {rels}  (expected {EXPECTED_RELATIONS})")
    if rels != EXPECTED_RELATIONS:
        print("  ! relations count != expected"); ok = False

    missing = one("RETURN LENGTH(FOR e IN relations FILTER e.validFrom == null OR e.validTo == null LIMIT 1 RETURN 1)")
    print(f"edges missing validFrom/validTo: {missing}")
    if missing:
        print("  ! some edges lack temporal fields"); ok = False

    rng = one("FOR e IN relations COLLECT AGGREGATE lo = MIN(e.validFrom), hi = MAX(e.validFrom) RETURN {lo, hi}")
    openn = one("RETURN LENGTH(FOR e IN relations FILTER e.validTo == @n RETURN 1)", {"n": NEVER_EXPIRES})
    print(f"validFrom range  : {rng}")
    print(f"open-ended edges (validTo == {NEVER_EXPIRES}): {openn}")

    # MDI engagement on the direct as-of form
    st, body = req("POST", "/_api/explain",
                   {"query": "FOR e IN relations FILTER e.validFrom <= @t AND e.validTo > @t LIMIT 10 RETURN e",
                    "bindVars": {"t": 201806}}, db=DB, timeout=120)
    plan_nodes = body.get("plan", {}).get("nodes", []) if st in (200, 201) else []
    mdi = any(ix.get("type") == "mdi" for n in plan_nodes if n.get("type") == "IndexNode" for ix in n.get("indexes", []))
    print(f"direct as-of uses MDI: {mdi}")
    if not mdi:
        print("  ! direct as-of did not engage the MDI"); ok = False

    print("as-of spot check — AAPL operates_in edges valid at t:")
    for t in (201406, 201806, 202406):
        c = one("FOR e IN relations FILTER e.type == 'operates_in' AND e.ticker == 'aapl' "
                "AND e.validFrom <= @t AND e.validTo > @t COLLECT WITH COUNT INTO c RETURN c", {"t": t})
        print(f"    @ {t}: {c}")

    print("\nVALIDATION:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

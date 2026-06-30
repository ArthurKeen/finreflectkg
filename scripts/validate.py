"""Validate & reconcile the loaded graph against expected counts, and confirm
the vertex-centric indexes are actually used by typed traversals.
"""

import json

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")

EXPECTED = {"Node": 3_099_773, "relations": 17_513_372, "chunks": 1_384_513}


def count(coll):
    _, b = req("GET", f"/_api/collection/{coll}/count", db=DB)
    return b.get("count")


def aql(query, bind=None, options=None):
    body = {"query": query, "batchSize": 100}
    if bind:
        body["bindVars"] = bind
    if options:
        body["options"] = options
    return req("POST", "/_api/cursor", body, db=DB)


def main():
    print("== count reconciliation ==")
    ok = True
    for coll, exp in EXPECTED.items():
        got = count(coll)
        flag = "OK" if got == exp else "MISMATCH"
        ok &= got == exp
        print(f"  {coll:10} expected {exp:>11,}  got {got:>11,}  [{flag}]")

    print("\n== referential integrity (sampled 1000 edges) ==")
    _, b = aql(
        """
        FOR e IN relations LIMIT 1000
          LET f = DOCUMENT(e._from) LET t = DOCUMENT(e._to)
          COLLECT AGGREGATE bad_from = SUM(f == null ? 1 : 0),
                            bad_to   = SUM(t == null ? 1 : 0)
          RETURN {bad_from, bad_to}
        """
    )
    print(" ", b.get("result"))

    print("\n== VCI usage check ==")
    # The VCIs are used by DIRECT edge-collection queries (the access path that
    # exploits (_from|_to, type, far-type)). Pattern traversals on this 3.12
    # cluster use the generic `edge` index + in-enumeration filter instead — so
    # 1-hop typed neighborhood queries should be written as direct edge queries.
    _, b = aql("FOR n IN Node FILTER n.type=='ORG' LIMIT 1 RETURN n._id")
    start = b["result"][0]
    direct = """
        FOR e IN relations
          FILTER e._from == @start AND e.type == 'operates_in' AND e._toType == 'GPE'
          RETURN e._to
    """
    _, ex = req("POST", "/_api/explain",
                {"query": direct, "bindVars": {"start": start}}, db=DB)
    idxs = [i["name"] for n in ex.get("plan", {}).get("nodes", [])
            if n.get("type") == "IndexNode" for i in n.get("indexes", [])]
    used_vci = "vci_from_type_totype" in idxs
    print(f"  direct edge query indexes: {idxs}  [{'VCI OK' if used_vci else 'NOT VCI'}]")

    print("\n== smoke: supernode reverse query (net income), VCI direct edge ==")
    q2 = """
        FOR n IN Node FILTER n.name=='net income' AND n.type=='FIN_METRIC' LIMIT 1
          LET disclosers = LENGTH(
            FOR e IN relations
              FILTER e._to == n._id AND e.type=='discloses' AND e._fromType=='ORG'
              RETURN 1)
          RETURN {node: n._id, org_disclosers: disclosers}
    """
    _, b2 = aql(q2)
    print(" ", b2.get("result"))

    print("\nVALIDATION", "PASSED" if ok else "FAILED (count mismatch)")


if __name__ == "__main__":
    main()

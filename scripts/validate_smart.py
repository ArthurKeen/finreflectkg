"""Validate the Disjoint SmartGraph build `FinReflectKgSmart`.

Differs from scripts/validate.py: the smart build duplicates shared concepts
per company, so the `Node` count grows (~6.66 M expected, exact value depends on
the data) while `relations` (edges not duplicated) and `chunks` are unchanged.
Adds the SmartGraph-specific assertions the brief requires:
  - graph: smartGraphAttribute == ticker, isDisjoint == true
  - collections Node/relations/chunks: isSmart, sharded by ticker
  - shard locality: a per-company query (subgraph + its chunks) has NO RemoteNode
    in its execution plan (text co-located with the subgraph)

Latency on the shared cluster is noisy, so locality (explain) + integrity are the
deterministic signals — not wall-clock.
"""

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKgSmart")
GRAPH = ENV.get("ARANGO_GRAPH", DB)
SMART_ATTR = ENV.get("ARANGO_SMART_ATTRIBUTE", "ticker")

# Edges are not duplicated; chunk identity already includes ticker -> both exact.
EXPECT_RELATIONS = 17_513_372
EXPECT_CHUNKS = 1_384_513
# Node grows via per-company concept duplication; sanity band, not an equality.
NODE_MIN, NODE_MAX = 3_099_773, 9_000_000


def count(coll):
    _, b = req("GET", f"/_api/collection/{coll}/count", db=DB)
    return b.get("count")


def aql(query, bind=None):
    body = {"query": query, "batchSize": 100}
    if bind:
        body["bindVars"] = bind
    return req("POST", "/_api/cursor", body, db=DB)


def explain(query, bind=None):
    body = {"query": query}
    if bind:
        body["bindVars"] = bind
    _, ex = req("POST", "/_api/explain", body, db=DB)
    return ex


def main():
    ok = True

    print("== count reconciliation ==")
    n_node = count("Node")
    n_rel = count("relations")
    n_chunk = count("chunks")
    node_ok = n_node is not None and NODE_MIN <= n_node <= NODE_MAX
    rel_ok = n_rel == EXPECT_RELATIONS
    chunk_ok = n_chunk == EXPECT_CHUNKS
    ok &= node_ok and rel_ok and chunk_ok
    print(f"  Node      got {n_node:>11,}  [in {NODE_MIN:,}..{NODE_MAX:,}? "
          f"{'OK' if node_ok else 'OUT OF RANGE'}]  (≈6.66M expected)")
    print(f"  relations got {n_rel:>11,}  expected {EXPECT_RELATIONS:,}  "
          f"[{'OK' if rel_ok else 'MISMATCH'}]")
    print(f"  chunks    got {n_chunk:>11,}  expected {EXPECT_CHUNKS:,}  "
          f"[{'OK' if chunk_ok else 'MISMATCH'}]")

    print("\n== referential integrity (sampled 1000 edges) ==")
    _, b = aql("""
        FOR e IN relations LIMIT 1000
          LET f = DOCUMENT(e._from) LET t = DOCUMENT(e._to)
          LET ch = e.chunkKey == null ? null : DOCUMENT('chunks', e.chunkKey)
          COLLECT AGGREGATE bad_from = SUM(f == null ? 1 : 0),
                            bad_to   = SUM(t == null ? 1 : 0),
                            with_ctx = SUM(e.chunkKey == null ? 0 : 1),
                            bad_chunk = SUM(e.chunkKey != null AND ch == null ? 1 : 0)
          RETURN {bad_from, bad_to, with_ctx, bad_chunk}
    """)
    ri = (b.get("result") or [{}])[0]
    ri_ok = ri.get("bad_from") == 0 and ri.get("bad_to") == 0 and ri.get("bad_chunk") == 0
    ok &= ri_ok
    print(f"  {ri}  [{'OK' if ri_ok else 'DANGLING REFS'}]")

    print("\n== smart graph attributes ==")
    _, gbody = req("GET", f"/_api/gharial/{GRAPH}", db=DB)
    g = gbody.get("graph", {})
    g_ok = g.get("smartGraphAttribute") == SMART_ATTR and g.get("isDisjoint") is True
    ok &= g_ok
    print(f"  smartGraphAttribute={g.get('smartGraphAttribute')!r}  "
          f"isDisjoint={g.get('isDisjoint')}  numberOfShards={g.get('numberOfShards')}  "
          f"[{'OK' if g_ok else 'WRONG'}]")
    # SmartGraph collections shard by the smart value embedded in _key, so
    # shardKeys is reported as the sentinel ['_key:'] (NOT ['ticker']); isSmart
    # is the real signal. Vertex collections also expose smartGraphAttribute.
    for c in ["Node", "relations", "chunks"]:
        _, p = req("GET", f"/_api/collection/{c}/properties", db=DB)
        c_ok = bool(p.get("isSmart")) and p.get("shardKeys") == ["_key:"]
        ok &= c_ok
        print(f"  {c:9} isSmart={p.get('isSmart')}  shardKeys={p.get('shardKeys')}  "
              f"smartGraphAttribute={p.get('smartGraphAttribute')!r}  "
              f"[{'OK' if c_ok else 'NOT SMART-SHARDED'}]")

    print("\n== shard locality (per-company traversal: subgraph + chunks) ==")
    # The disjoint-SmartGraph win shows up in TRAVERSALS from a smart start
    # vertex, not in collection scans: a company's subgraph (and its chunks,
    # co-located by ticker) lives on one shard, so the optimizer marks the
    # TraversalNode `isLocalGraphNode` and applies the
    # `cluster-lift-constant-for-disjoint-graph-nodes` rule — the traversal runs
    # on the single owning DBServer. (A lone coordinator->DBServer RemoteNode is
    # normal in a cluster and is NOT scatter-gather, so node types alone don't
    # decide locality; `isLocalGraphNode` is the real signal.)
    _, sb = aql("FOR e IN relations LIMIT 1 RETURN e._from")  # guaranteed-connected start
    start = (sb.get("result") or [None])[0]
    locality_q = """
        FOR v, e, p IN 1..2 OUTBOUND @s GRAPH @g
          LET ch = e.chunkKey == null ? null : DOCUMENT('chunks', e.chunkKey)
          LIMIT 200
          RETURN {v: v._key, hasText: ch != null}
    """
    ex = explain(locality_q, {"s": start, "g": GRAPH})
    rules = ex.get("plan", {}).get("rules", [])
    trav = next((n for n in ex.get("plan", {}).get("nodes", [])
                 if n.get("type") == "TraversalNode"), {})
    local = bool(trav.get("isLocalGraphNode")) and bool(trav.get("isDisjoint"))
    disjoint_rule = "cluster-lift-constant-for-disjoint-graph-nodes" in rules
    loc_ok = local and disjoint_rule
    ok &= loc_ok
    # confirm the co-located text actually resolves through the traversal
    _, rb = aql(locality_q, {"s": start, "g": GRAPH})
    rows = rb.get("result") or []
    with_text = sum(1 for r in rows if r.get("hasText"))
    print(f"  start={start!r}")
    print(f"  TraversalNode isLocalGraphNode={trav.get('isLocalGraphNode')} "
          f"isDisjoint={trav.get('isDisjoint')}; disjoint-lift rule={disjoint_rule}")
    print(f"  traversal rows={len(rows)} with co-located text={with_text}")
    print(f"  [{'OK — shard-local disjoint traversal' if loc_ok else 'NOT LOCAL'}]")

    print("\nSMART VALIDATION", "PASSED" if ok else "FAILED")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""P4 (real algorithm) — GAE PageRank per as-of year on the time-travel DB (§4.8).

Pregel is deprecated on this cluster, so per-year influence is computed with the ArangoDB
Graph Analytics Engine (GAE), which runs over whole collections. For each anchor year we
materialize an as-of snapshot edge collection (edges valid mid-year) and run GAE PageRank
over {Node, tt_snap_<Y>}, then compare the top-ranked entities across the decade.

MUST run under .venv311 (python-arango + graph_analytics_ai), like scripts/analytics.py:
  .venv311/bin/python scripts/temporal_pagerank.py
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

# `import arango` must resolve to python-arango (not scripts/arango.py) — drop the
# script dir / cwd from the path before any arango import happens.
_SELF = str(pathlib.Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", ".", _SELF)]

YEARS = [2014, 2019, 2020, 2024]
DB_NAME = "FinReflectKgTemporal"
TOP = 15


def _load_env():
    from graph_analytics_ai.config import load_env_vars
    load_env_vars()
    os.environ["ARANGO_DATABASE"] = DB_NAME


def _db():
    from arango import ArangoClient
    endpoint = os.environ["ARANGO_ENDPOINT"].rstrip("/")
    verify = os.environ.get("ARANGO_VERIFY_SSL", "true").lower() == "true"
    client = ArangoClient(hosts=endpoint, verify_override=verify, request_timeout=600)
    return client.db(DB_NAME, username=os.environ.get("ARANGO_USER", "root"),
                     password=os.environ.get("ARANGO_PASSWORD", ""), verify=True)


def _flagged_count(db):
    return next(db.aql.execute("RETURN LENGTH(FOR n IN Node FILTER n.isGenericMention==true RETURN 1)"))


def ensure_snapshot(db, year):
    """Materialize tt_snap_<year> = edges valid as-of mid-year, REWIRING any flagged
    generic-mention endpoint to its per-company blank node (bnodes/bn_<ticker>_<role>) so the
    CLEANED topology feeds GAE (docs/generic-mention-conflation.md, Phase 2). We never copy the
    17.5M relations collection — the rewrite happens here on the per-year subset. Idempotent:
    re-materializes if the snapshot is stale OR not yet rewired.

    Returns (name, rebuilt). `rebuilt` is True when the snapshot was (re)materialized, which
    invalidates any PageRank previously computed from it — see main()."""
    t = year * 100 + 6
    name = f"tt_snap_{year}"
    want = next(db.aql.execute(
        "LET junk = (FOR n IN Node FILTER n.isJunkPlaceholder == true RETURN n._id) "
        "RETURN LENGTH(FOR e IN relations FILTER e.validFrom<=@t AND e.validTo>@t "
        "  AND e._from NOT IN junk AND e._to NOT IN junk RETURN 1)",
        bind_vars={"t": t}))
    if not db.has_collection(name):
        db.create_collection(name, edge=True)
    coll = db.collection(name)
    rewired = coll.count() and next(db.aql.execute(
        f"RETURN LENGTH(FOR e IN {name} FILTER STARTS_WITH(e._to,'bnodes/') "
        f"OR STARTS_WITH(e._from,'bnodes/') LIMIT 1 RETURN 1)"))
    if coll.count() == want and rewired:
        print(f"  {name}: up-to-date & rewired ({want:,} edges)", flush=True)
        return name, False
    if coll.count():
        coll.truncate()
    tickers = list(db.aql.execute(
        "FOR e IN relations FILTER e.validFrom<=@t AND e.validTo>@t COLLECT tk=e.ticker RETURN tk",
        bind_vars={"t": t}))
    for tk in tickers:
        db.aql.execute(
            "FOR e IN relations FILTER e.ticker==@tk AND e.validFrom<=@t AND e.validTo>@t "
            "  LET df = DOCUMENT(e._from)  LET dt = DOCUMENT(e._to) "
            "  FILTER df.isJunkPlaceholder != true AND dt.isJunkPlaceholder != true "  # drop junk-placeholder edges
            "  LET nf = df.isGenericMention == true ? CONCAT('bnodes/bn_', e.ticker, '_', df.roleLemma) : e._from "
            "  LET nt = dt.isGenericMention == true ? CONCAT('bnodes/bn_', e.ticker, '_', dt.roleLemma) : e._to "
            "  INSERT {_key:e._key, _from:nf, _to:nt} INTO @@snap OPTIONS {ignoreErrors:true}",
            bind_vars={"tk": tk, "t": t, "@snap": name})
    print(f"  {name}: materialized {coll.count():,} edges, flagged endpoints rewired to bnodes "
          f"(target {want:,}, {len(tickers)} tickers)", flush=True)
    if coll.count() != want:
        raise SystemExit(
            f"  {name}: FAILED to materialize completely — {coll.count():,} of {want:,} edges. "
            f"Refusing to run PageRank on a partial snapshot (this is exactly the defect that "
            f"produced the incomparable 2019 column).")
    return name, True


def run_pagerank(db, year, snap):
    from graph_analytics_ai import GAEOrchestrator, AnalysisConfig
    target = f"gae_pr_{year}"
    # graph_analytics_ai pre-creates the result collection via
    # create_collection(shard_keys=...) — a kwarg the installed python-arango
    # rejects, so its pre-creation silently fails and GAE's store step 404s
    # (ERR 1203). Create it ourselves so the store lands.
    if not db.has_collection(target):
        db.create_collection(target)
    config = AnalysisConfig(
        name=f"finreflectkg_temporal_{year}",
        description=f"pagerank as-of {year} over Node/{snap}",
        vertex_collections=["Node", "bnodes"], edge_collections=[snap],
        database=DB_NAME, algorithm="pagerank", algorithm_params={},
        target_collection=target, auto_cleanup=True, timeout_seconds=3600,
    )
    result = GAEOrchestrator().run_analysis(config)
    status = getattr(result.status, "value", str(result.status))
    return target, config.result_field, status, getattr(result, "error", None)


def top_scores(db, target, field, top=TOP):
    # r.id is a full document id ('Node/<key>' or 'bnodes/bn_<ticker>_<role>'); only a bare
    # key needs the Node/ prefix. Getting this wrong renders skolemized bnodes as null.
    aql = f"""FOR r IN @@c SORT r.`{field}` DESC LIMIT @top
      LET n = DOCUMENT(CONTAINS(r.id, '/') ? r.id : CONCAT('Node/', r.id))
      RETURN {{score: r.`{field}`, name: n.name, type: n.type,
               collection: FIRST(SPLIT(r.id, '/'))}}"""
    return list(db.aql.execute(aql, bind_vars={"@c": target, "top": top}))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true",
                    help="force re-materialization of every snapshot and re-run PageRank")
    ap.add_argument("--recompute", action="store_true",
                    help="re-run PageRank on the EXISTING snapshots (keeps materialization). Use "
                         "when the snapshots are known-good but the ranks may predate a snapshot "
                         "revision — guarantees every year is scored off the same rules.")
    args = ap.parse_args()

    _load_env()
    db = _db()
    print(f"(cleaning: {_flagged_count(db)} flagged generic-mention hubs -> per-company bnodes at snapshot time)", flush=True)
    results = {}
    for y in YEARS:
        print(f"\n=== as-of {y} ===", flush=True)
        done = f"gae_pr_{y}"
        # The snapshot is validated FIRST. Reusing a cached PageRank without checking the
        # collection it came from is what left 2019 ranked off a 8.5%-complete snapshot and
        # 2024 ranked off un-rewired (dirty) topology — three incomparable columns.
        if args.rebuild and db.has_collection(f"tt_snap_{y}"):
            db.collection(f"tt_snap_{y}").truncate()
        snap, rebuilt = ensure_snapshot(db, y)
        if (not rebuilt and not args.rebuild and not args.recompute
                and db.has_collection(done) and db.collection(done).count() > 0):
            print(f"  {done} already computed ({db.collection(done).count():,} ranks) "
                  f"from an up-to-date snapshot — reusing", flush=True)
            results[y] = top_scores(db, done, "rank")
            continue
        if db.has_collection(done):
            print(f"  dropping stale {done} (snapshot changed)", flush=True)
            db.delete_collection(done)
        target, field, status, err = run_pagerank(db, y, snap)
        print(f"  GAE pagerank status={status} -> {target}.{field}"
              + (f"  ERROR: {err}" if status == "failed" else ""), flush=True)
        if status != "failed":
            try:
                results[y] = top_scores(db, target, field)
            except Exception as e:  # noqa: BLE001
                print(f"  (could not read {target}: {e})", flush=True)

    print("\n=== PageRank influence over time (top by year) ===", flush=True)
    for y in YEARS:
        print(f"\n  as-of {y}:")
        for r in results.get(y, []):
            tag = "  [bnode]" if r.get("collection") == "bnodes" else ""
            print(f"    {r['score']:.6f}  {r['name']}  ({r['type']}){tag}")


if __name__ == "__main__":
    main()

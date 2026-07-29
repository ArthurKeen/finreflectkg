"""Graph-analytics jobs over FinReflectKG via the ArangoDB Graph Analytics Engine (GAE).

Deterministic base layer for graph analytics (PRD §4.7 / G8), via **agentic-graph-analytics**
(`import graph_analytics_ai`) — its GAE client is ACP-ready: it polls for engine readiness
and retries the transient GRAL-ingress `unknown path '/gral/..'` 404 that the standalone
`graph-analytics-orchestrator` could not get past. Drives `GAEOrchestrator.run_analysis`
(deploy → load → analyze → store → cleanup) and records results the way the benchmark
harness does. The agentic NL→insights mode of the *same* package is the top layer,
analogous to how the `nl2cypher` front-end sits on the `arango-cypher-py` transpiler.

FinReflectKG is a labeled property graph: one vertex collection `Node` and one edge
collection `relations`, so every algorithm runs on `vertex_collections=["Node"]`,
`edge_collections=["relations"]`. Results are written to a SEPARATE `gae_<algorithm>`
collection (keyed by vertex id) — the `Node` collection is never mutated.

Deployment: **self-managed GAE** (GenAI Suite) — reuses the ArangoDB endpoint + JWT
(same `.env` connection); no extra credentials. Config: `GAE_DEPLOYMENT_MODE=self_managed`,
`ARANGO_DATABASE` (the orchestrator's name for the target db).

Usage (runs under .venv311 — graph-analytics-ai requires py3.10+; has python-arango):
  .venv311/bin/python scripts/analytics.py                        # PageRank on FinReflectKG
  .venv311/bin/python scripts/analytics.py --algorithm wcc
  .venv311/bin/python scripts/analytics.py --algorithm pagerank --db FinReflectKgSmart --top 25
  .venv311/bin/python scripts/analytics.py --algorithm label_propagation --keep-engine

NOTE: like cypher_eval.py, this must import python-arango's `arango` package (pulled in
by the orchestrator), which shares its name with scripts/arango.py. We drop the scripts
dir from sys.path so the installed package wins.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
# Ensure `import arango` resolves to python-arango (orchestrator dep), not scripts/arango.py.
sys.path = [p for p in sys.path if p not in ("", str(_SCRIPTS))]

# Supported GAE algorithms and whether they produce a per-vertex numeric score we can
# rank (pagerank/betweenness) vs. a component/community label (wcc/scc/label_propagation).
SCORED = {"pagerank", "betweenness"}
LABELED = {"wcc", "scc", "label_propagation"}


def _load_env():
    from graph_analytics_ai.config import load_env_vars
    load_env_vars()
    # The orchestrator reads ARANGO_DATABASE; our .env historically used ARANGO_DB.
    if not os.environ.get("ARANGO_DATABASE") and os.environ.get("ARANGO_DB"):
        os.environ["ARANGO_DATABASE"] = os.environ["ARANGO_DB"]


def _db():
    """python-arango handle for the post-run join (reads the same env)."""
    from arango import ArangoClient
    endpoint = os.environ["ARANGO_ENDPOINT"].rstrip("/")
    verify = os.environ.get("ARANGO_VERIFY_SSL", "true").lower() == "true"
    client = ArangoClient(hosts=endpoint, verify_override=verify, request_timeout=120)
    return client.db(os.environ.get("ARANGO_DATABASE", "FinReflectKG"),
                     username=os.environ.get("ARANGO_USER", "root"),
                     password=os.environ.get("ARANGO_PASSWORD", ""), verify=True)


def summarize(db, target_collection, result_field, algorithm, top):
    """Read the stored GAE results back and produce a human-readable summary.

    Results land in `target_collection` as {id: <vertex key/id>, <result_field>: value}.
    `id` may be a bare `_key` or a full `_id`; resolve the Node either way.
    """
    if algorithm in SCORED:
        aql = f"""
        FOR r IN @@c SORT r.`{result_field}` DESC LIMIT @top
          LET n = DOCUMENT(STARTS_WITH(r.id, 'Node/') ? r.id : CONCAT('Node/', r.id))
          RETURN {{id: r.id, score: r.`{result_field}`, name: n.name, type: n.type}}"""
        rows = list(db.aql.execute(aql, bind_vars={"@c": target_collection, "top": top}))
        return {"kind": "scored", "top": rows}
    # component/community label: report the largest groups by member count
    aql = f"""
    FOR r IN @@c COLLECT label = r.`{result_field}` WITH COUNT INTO members
      SORT members DESC LIMIT @top
      RETURN {{label: label, members: members}}"""
    groups = list(db.aql.execute(aql, bind_vars={"@c": target_collection, "top": top}))
    total = db.aql.execute("RETURN LENGTH(FOR r IN @@c COLLECT l = r.`%s` RETURN 1)"
                           % result_field, bind_vars={"@c": target_collection})
    return {"kind": "labeled", "distinct_labels": next(total, None), "largest": groups}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--algorithm", default="pagerank",
                    choices=sorted(SCORED | LABELED), help="GAE algorithm (default: pagerank)")
    ap.add_argument("--db", default=None, help="target db (default: ARANGO_DATABASE/ARANGO_DB)")
    ap.add_argument("--top", type=int, default=20, help="top-N results to summarize")
    ap.add_argument("--keep-engine", action="store_true",
                    help="skip auto-cleanup of the GAE engine (for iterating)")
    args = ap.parse_args()

    _load_env()
    if args.db:
        os.environ["ARANGO_DATABASE"] = args.db
    db_name = os.environ.get("ARANGO_DATABASE", "FinReflectKG")

    from graph_analytics_ai import GAEOrchestrator, AnalysisConfig

    target = f"gae_{args.algorithm}"
    config = AnalysisConfig(
        name="finreflectkg",
        description=f"{args.algorithm} over FinReflectKG ({db_name})",
        vertex_collections=["Node"],
        edge_collections=["relations"],
        database=db_name,
        algorithm=args.algorithm,
        algorithm_params={},              # orchestrator fills algorithm defaults
        target_collection=target,
        auto_cleanup=not args.keep_engine,
        timeout_seconds=3600,
    )
    print(f"db={db_name}  algorithm={args.algorithm}  graph=Node/relations  "
          f"target={target}  cleanup={not args.keep_engine}")

    orch = GAEOrchestrator()
    result = orch.run_analysis(config)

    status = getattr(result.status, "value", str(result.status))
    # With auto_cleanup, a successful run ends in 'cleaning_up' (COMPLETED -> CLEANING_UP
    # on teardown); only 'failed' is a real failure.
    ok = status != "failed"
    print(f"\nstatus={status} ({'ok' if ok else 'FAILED'})  "
          f"duration={getattr(result, 'duration_seconds', None)}s  "
          f"engine={getattr(result, 'engine_id', None)}  result_field={config.result_field}")
    if not ok:
        print(f"analysis FAILED: {getattr(result, 'error', None)}")

    summary = {}
    try:
        summary = summarize(_db(), target, config.result_field, args.algorithm, args.top)
        print("\n=== summary ===")
        if summary.get("kind") == "scored":
            for r in summary["top"]:
                print(f"  {r.get('score'):>12}  {str(r.get('name'))[:40]:40} [{r.get('type')}]")
        else:
            print(f"  distinct {args.algorithm} groups: {summary.get('distinct_labels')}")
            for g in summary["largest"]:
                print(f"  label={g['label']}  members={g['members']:,}")
    except Exception as e:  # noqa: BLE001
        print(f"(could not summarize {target}: {e})")

    out = ROOT / "data" / f"analytics_{args.algorithm}_{db_name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "db": db_name, "algorithm": args.algorithm, "target_collection": target,
        "result_field": config.result_field, "status": status, "ok": ok,
        "duration_seconds": getattr(result, "duration_seconds", None),
        "summary": summary,
    }, indent=2, default=str))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

"""Graph-analytics jobs over FinReflectKG via the ArangoDB Graph Analytics Engine (GAE).

⚠️ DRAFT — DEFERRED (2026-07-29). This scaffold targets `graph-analytics-orchestrator`,
which does NOT work against this cluster's GAE: FinReflectKG runs on the ArangoDB
Platform (ACP), where the GAE engine deploys fine (`/gen-ai/v1/graphanalytics`) but its
per-engine compute route (`/gral/<id>/v1/loaddata`) is only live ~30–60 s after deploy
while the GRAL ingress rolls out. This orchestrator retries only ~3×/~12 s (by
re-deploying), so `loaddata` 404s ("unknown path '/gral/..'"). The chosen path is
`agentic-graph-analytics` (`graph_analytics_ai`), whose GAE client is ACP-ready
(readiness polling + retry on that transient signature) and ships both a deterministic
orchestrator mode and the agentic mode. See PRD §4.7. Re-point this at `graph_analytics_ai`
when implementing; the AnalysisConfig (Node/relations LPG) and result-summary logic below
carry over. The GAE itself IS available on the cluster.

Intended design (both layers via `graph_analytics_ai`): a deterministic base (deploy →
load → analyze → store → cleanup) that records results like the benchmark harness, with
the agentic NL→insights mode on top — analogous to how the `nl2cypher` front-end sits on
the `arango-cypher-py` transpiler.

FinReflectKG is a labeled property graph: one vertex collection `Node` and one edge
collection `relations`, so every algorithm runs on `vertex_collections=["Node"]`,
`edge_collections=["relations"]`. Results are written to a SEPARATE `gae_<algorithm>`
collection (keyed by vertex id) — the `Node` collection is never mutated.

Deployment: **self-managed GAE** (GenAI Suite) — reuses the ArangoDB endpoint + JWT
(same `.env` connection); no extra credentials. Config: `GAE_DEPLOYMENT_MODE=self_managed`,
`ARANGO_DATABASE` (the orchestrator's name for the target db).

Usage (runs under .venv, which has graph-analytics-orchestrator + python-arango):
  .venv/bin/python scripts/analytics.py                        # PageRank on FinReflectKG
  .venv/bin/python scripts/analytics.py --algorithm wcc
  .venv/bin/python scripts/analytics.py --algorithm pagerank --db FinReflectKgSmart --top 25
  .venv/bin/python scripts/analytics.py --algorithm label_propagation --keep-engine

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
    from graph_analytics_orchestrator.config import load_env_vars
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

    from graph_analytics_orchestrator import GAEOrchestrator, AnalysisConfig

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
    print(f"\nstatus={status}  duration={getattr(result, 'duration_seconds', None)}s  "
          f"engine={getattr(result, 'engine_id', None)}  result_field={config.result_field}")
    if status not in ("completed", "success", "COMPLETED"):
        print(f"analysis did not complete cleanly: {getattr(result, 'error', None)}")
        # still try to summarize whatever landed

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
        "result_field": config.result_field, "status": status,
        "duration_seconds": getattr(result, "duration_seconds", None),
        "summary": summary,
    }, indent=2, default=str))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

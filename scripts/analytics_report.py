"""Generate the agentic-graph-analytics HTML report (with Plotly charts) from stored GAE results.

This closes the last gap in G8/§4.7: the deterministic GAE orchestrator returns an
`AnalysisResult`, while `graph_analytics_ai.ai.reporting.ReportGenerator` consumes an
`ExecutionResult`. No adapter existed, so the package's report layer -- insights,
recommendations, and interactive Plotly charts -- was never invoked by this project.

This script is that adapter. It reads a already-computed `gae_*` result collection back
out of ArangoDB, wraps it as an `ExecutionResult`, and runs the package's own
`ReportGenerator` + `HTMLReportFormatter`. No GAE engine is deployed and no analysis is
re-run -- it reports on results that already exist.

MUST run under .venv311 (python-arango + graph_analytics_ai + plotly):
  .venv311/bin/python scripts/analytics_report.py --collection gae_pr_2024 --year 2024
  .venv311/bin/python scripts/analytics_report.py --collection gae_pagerank --db FinReflectKG

Charts require plotly (`pip install plotly`). Without it the package silently emits a
chartless report -- the script fails loudly instead.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import datetime, timedelta

# `import arango` must resolve to python-arango (not scripts/arango.py) -- drop the
# script dir / cwd from the path before any arango import happens.
_SELF = str(pathlib.Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", ".", _SELF)]

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DB = "FinReflectKgTemporal"


def _load_env(db_name: str) -> None:
    from graph_analytics_ai.config import load_env_vars
    load_env_vars()
    os.environ["ARANGO_DATABASE"] = db_name


def _db(db_name: str):
    from arango import ArangoClient
    endpoint = os.environ["ARANGO_ENDPOINT"].rstrip("/")
    verify = os.environ.get("ARANGO_VERIFY_SSL", "true").lower() == "true"
    client = ArangoClient(hosts=endpoint, verify_override=verify, request_timeout=600)
    return client.db(db_name, username=os.environ.get("ARANGO_USER", "root"),
                     password=os.environ.get("ARANGO_PASSWORD", ""), verify=True)


def fetch_results(db, collection: str, top_n: int, rank_field: str = "rank"):
    """Pull the top-N ranked results plus the total count.

    The report only needs the head of the distribution (charts show top-20, insights
    reason over the leaders), so we sort server-side rather than dragging 3.1M rows
    across the wire -- the mistake that made a 215K-row Cypher query take 32s.
    """
    total = next(db.aql.execute(f"RETURN LENGTH({collection})"))
    rows = list(db.aql.execute(
        f"""FOR r IN {collection}
              SORT r.`{rank_field}` DESC
              LIMIT @n
              LET n = DOCUMENT(CONTAINS(r.id, '/') ? r.id : CONCAT('Node/', r.id))
              RETURN {{ id: r.id, `{rank_field}`: r.`{rank_field}`,
                        name: n.name, type: n.type }}""",
        bind_vars={"n": top_n}))
    return rows, total


def as_execution_result(rows, total, *, collection, algorithm, db_name, elapsed_s):
    """Adapt stored GAE output into the ExecutionResult the report layer expects.

    This is the missing seam between the two halves of the package: the orchestrator's
    AnalysisResult and the reporting layer's ExecutionResult.
    """
    from graph_analytics_ai.ai.execution.models import (
        AnalysisJob, ExecutionResult, ExecutionStatus,
    )
    now = datetime.now()
    job = AnalysisJob(
        job_id=f"{db_name}:{collection}",
        template_name=f"FinReflectKG {algorithm} — {collection}",
        algorithm=algorithm,
        status=ExecutionStatus.COMPLETED,
        submitted_at=now - timedelta(seconds=elapsed_s),
        started_at=now - timedelta(seconds=elapsed_s),
        completed_at=now,
        result_collection=collection,
        result_count=total,
        execution_time_seconds=elapsed_s,
        metadata={"database": db_name, "source": "stored GAE result collection"},
    )
    return ExecutionResult(job=job, success=True, results=rows,
                           metrics={"result_count": total,
                                    "reported_rows": len(rows)})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collection", default="gae_pr_2024",
                    help="stored GAE result collection (default: gae_pr_2024)")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"database (default: {DEFAULT_DB})")
    ap.add_argument("--algorithm", default="pagerank", help="algorithm that produced it")
    ap.add_argument("--year", help="as-of year, used in the report title")
    ap.add_argument("--top", type=int, default=20, help="rows to feed the report/charts")
    ap.add_argument("--elapsed", type=float, default=114.0,
                    help="measured GAE runtime in seconds, for the metrics section")
    ap.add_argument("--no-llm", action="store_true",
                    help="heuristic insights only (skips the LLM interpretation pass)")
    ap.add_argument("--out", help="output HTML path (default: data/analytics_report_<collection>.html)")
    args = ap.parse_args()

    _load_env(args.db)

    from graph_analytics_ai.ai.reporting import (
        ReportGenerator, HTMLReportFormatter, ChartGenerator, is_plotly_available,
    )
    if not is_plotly_available():
        raise SystemExit(
            "plotly is not installed, so the report would be silently chartless.\n"
            "  fix: .venv311/bin/pip install plotly"
        )

    db = _db(args.db)
    print(f"reading {args.db}.{args.collection} …", flush=True)
    rows, total = fetch_results(db, args.collection, args.top)
    if not rows:
        raise SystemExit(f"{args.collection} is empty — nothing to report on.")
    print(f"  {total:,} ranked entities; feeding top {len(rows)} to the report", flush=True)

    execution_result = as_execution_result(
        rows, total, collection=args.collection, algorithm=args.algorithm,
        db_name=args.db, elapsed_s=args.elapsed,
    )

    context = {
        "dataset": "FinReflectKG — S&P 500 10-K filings, 2014–2024 (published by Domyn)",
        "graph": "3,099,773 nodes / 17,513,372 edges; Node + relations (LPG)",
    }
    if args.year:
        context["as_of_year"] = args.year
        context["note"] = (
            f"Point-in-time snapshot as of {args.year}, materialized from the "
            "bitemporal time-travel layer with generic-mention hubs rewired to "
            "per-company blank nodes and placeholder tokens excluded."
        )

    print(f"generating report (llm={'off' if args.no_llm else 'on'}) …", flush=True)
    generator = ReportGenerator(
        use_llm_interpretation=not args.no_llm,
        enable_charts=True,
        industry="generic",
    )
    report = generator.generate_report(execution_result, context=context)
    if args.year:
        report.title = f"FinReflectKG PageRank — as of {args.year}"

    print("generating Plotly charts …", flush=True)
    charts = ChartGenerator().generate_pagerank_charts(rows, top_n=args.top) \
        if args.algorithm == "pagerank" else {}
    print(f"  {len(charts)} chart(s): {sorted(charts) or '(none)'}", flush=True)

    html = HTMLReportFormatter(theme="modern").format_report(
        report, charts=charts, include_raw_data=True,
    )

    out = pathlib.Path(args.out) if args.out else \
        ROOT / "data" / f"analytics_report_{args.collection}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\nwrote {out}  ({len(html):,} bytes)")
    print(f"  insights: {len(report.insights)}  recommendations: {len(report.recommendations)}")
    print(f"  open: file://{out}")


if __name__ == "__main__":
    main()

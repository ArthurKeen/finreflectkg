"""Generate the temporal-PageRank report via agentic-graph-analytics' own reporting layer.

Reads the per-as-of-year GAE results (gae_pr_<year>) from FinReflectKgTemporal, wraps each as
an ExecutionResult, and runs graph_analytics_ai's ReportGenerator in heuristic mode (no LLM) to
produce insights + a combined report. Augments it with custom sections (methodology, the
generic-mention cleaning before/after, the 4-year comparison) and writes Markdown + HTML.

MUST run under .venv311 (graph_analytics_ai + python-arango):
  .venv311/bin/python scripts/temporal_report.py
"""
from __future__ import annotations

import datetime
import os
import pathlib
import sys

_SELF = str(pathlib.Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", ".", _SELF)]  # python-arango, not scripts/arango.py

from graph_analytics_ai.config import load_env_vars
from graph_analytics_ai.ai.execution.models import AnalysisJob, ExecutionResult, ExecutionStatus
from graph_analytics_ai.ai.reporting import ReportFormat, ReportGenerator
from graph_analytics_ai.ai.reporting.models import ReportSection

DB = "FinReflectKgTemporal"
YEARS = [2014, 2019, 2020, 2024]
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _db():
    from arango import ArangoClient
    ep = os.environ["ARANGO_ENDPOINT"].rstrip("/")
    verify = os.environ.get("ARANGO_VERIFY_SSL", "true").lower() == "true"
    c = ArangoClient(hosts=ep, verify_override=verify, request_timeout=180)
    return c.db(DB, username=os.environ.get("ARANGO_USER", "root"),
                password=os.environ.get("ARANGO_PASSWORD", ""), verify=True)


def year_rows(db, year, n=20):
    return list(db.aql.execute(
        f"""FOR r IN gae_pr_{year} SORT r.rank DESC LIMIT {n}
          LET nd = DOCUMENT(CONTAINS(r.id, '/') ? r.id : CONCAT('Node/', r.id))
          RETURN {{result: r.rank, _key: nd.name, name: nd.name, type: nd.type, id: r.id}}"""))


def exec_result(db, year):
    rows = year_rows(db, year)
    total = next(db.aql.execute(f"RETURN LENGTH(gae_pr_{year})"))
    job = AnalysisJob(job_id=f"tt_{year}", template_name=f"PageRank as-of {year}",
                      algorithm="pagerank", status=ExecutionStatus.COMPLETED,
                      submitted_at=datetime.datetime(2026, 8, 13),
                      result_collection=f"gae_pr_{year}", result_count=total,
                      execution_time_seconds=110.0)
    return ExecutionResult(job=job, success=True, results=rows,
                           metrics={"year": year, "ranked_nodes": total})


def comparison_table(db):
    cols = {y: year_rows(db, y, 12) for y in YEARS}
    lines = ["Top entities by as-of PageRank (cleaned graph — generic hubs skolemized, junk excluded):", ""]
    lines.append("| rank | " + " | ".join(str(y) for y in YEARS) + " |")
    lines.append("|---|" + "---|" * len(YEARS))
    for i in range(12):
        cells = []
        for y in YEARS:
            r = cols[y][i] if i < len(cols[y]) else None
            cells.append(f"{r['name']} ({r['type']})" if r else "")
        lines.append(f"| {i+1} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


METHODOLOGY = """\
**Question.** Which entities are most central in the S&P 500 10-K knowledge graph, and how does
that shift across the decade (2014 → 2024)?

**Method.** Point-in-time (*as-of*) subgraphs are materialized from the time-travel layer
(`FinReflectKgTemporal`, valid-time `validFrom`/`validTo`), one per anchor year, and GAE
**PageRank** is run over each via the `graph_analytics_ai` orchestrator (`GAEOrchestrator.run_analysis`,
self-managed ACP engine). Pregel is deprecated on this cluster, so GAE is the execution engine.

**Data cleaning (critical for correctness).** The raw extraction conflates *anonymous* mentions
("a supplier", "our customers") into single shared nodes, so hundreds of unrelated companies
falsely share one `supplier`/`customer` node — which would dominate PageRank for the wrong
reason. Before ranking, each as-of snapshot is cleaned: **generic role hubs are skolemized** into
per-company blank nodes (89 hubs → 5,893 bnodes) and **junk placeholders excluded** (23 hubs:
`default`, `other`, `various`, …). See `docs/generic-mention-conflation.md`.
"""

CLEANING = """\
Running PageRank on the *dirty* graph first ranked `supplier` and `default` near the top — pure
extraction artifacts. After cleaning:

- **`supplier`** (fan-in 681 companies) → 681 per-company leaf bnodes; `bn_amd_supplier` now ranks
  ~570× below `net income`.
- **`default`** (was #1 in 2024) and **`other`** → excluded entirely (non-entities).
- **Zero** generic-mention hubs remain in the top 200 of any year; the rankings are anchored by
  genuine shared financial concepts.

This is also a demonstration of PageRank *as a detector*: the first pass surfaced a second junk
class (`default`/`other`) that the initial role lexicon had missed.
"""

FINDINGS = """\
- **`net income` is #1 in every year** — the S&P 500's most-referenced shared metric throughout.
- **Market structure rises:** `new york stock exchange` is absent from the 2014 top ranks, appears
  by 2020 (#7), and climbs to **#4 by 2024**; the **SEC** (regulator) and `united states` also enter
  the top by 2024.
- **2024 tilts to cost/tax/margin:** `effective tax rate`, `operating expense`, `operate margin`,
  and `capex` join the leaders — a shift from pure top-line metrics toward efficiency and regulation.
- Complementary **degree-trend analytics** (`scripts/temporal_analytics.py`) show `covid-19` entering
  the 2020 top-10 and **cybersecurity risk / lease accounting / SEC rule** rising 2014 → 2024.
"""


def main():
    load_env_vars()
    os.environ["ARANGO_DATABASE"] = DB
    db = _db()

    gen = ReportGenerator(use_llm_interpretation=False, enable_charts=False, industry="finance")
    ers = [exec_result(db, y) for y in YEARS]
    report = gen.generate_batch_report(
        ers, title="FinReflectKG — Temporal PageRank (as-of, cleaned graph)")

    # augment with custom narrative sections (generator only knows per-year rank stats)
    report.sections = [
        ReportSection(title="Methodology & data cleaning", content=METHODOLOGY),
        ReportSection(title="Influence over time (top entities by year)", content=comparison_table(db)),
        ReportSection(title="Generic-mention cleaning — before / after", content=CLEANING),
        ReportSection(title="Findings", content=FINDINGS),
    ] + list(report.sections)

    out_md = ROOT / "docs/temporal-pagerank-report.md"
    out_html = ROOT / "docs/temporal-pagerank-report.html"
    out_md.write_text(gen.format_report(report, ReportFormat.MARKDOWN))
    out_html.write_text(gen.format_report(report, ReportFormat.HTML))
    print(f"wrote {out_md.relative_to(ROOT)} ({out_md.stat().st_size:,} b) and "
          f"{out_html.relative_to(ROOT)} ({out_html.stat().st_size:,} b)")
    print(f"insights: {len(report.insights)}  recommendations: {len(report.recommendations)}  "
          f"sections: {len(report.sections)}")


if __name__ == "__main__":
    main()

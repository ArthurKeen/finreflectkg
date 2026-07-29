"""Agentic graph-analytics over FinReflectKG (PRD §4.7 / G8, top layer).

The **agentic NL→insights layer** on top of the deterministic base (scripts/analytics.py).
Drives `agentic-graph-analytics`'s `WorkflowOrchestrator.run_complete_workflow`: it reads a
business-requirements document, inspects the FinReflectKG schema, generates graph-analytics
use cases (LLM), selects + runs GAE algorithms, and produces an intelligence report —
analogous to how `nl2cypher` is the NL front-end over the `arango-cypher-py` transpiler.

LLM: resolved from the environment via the package's factory (`LLM_PROVIDER`, default
`openrouter`, using `OPENROUTER_API_KEY` — already in `.env`; requests-based, no extra SDK).
GAE: self-managed on the ArangoDB Platform (ACP), same `.env` connection as the base layer.

Usage (runs under .venv311; requires OPENROUTER_API_KEY + the GAE self-managed config):
  .venv311/bin/python scripts/analytics_agentic.py
  .venv311/bin/python scripts/analytics_agentic.py --requirements docs/analytics-requirements.md
  .venv311/bin/python scripts/analytics_agentic.py --db FinReflectKG --out data/analytics_agentic

NOTE: drops the scripts dir from sys.path so `import arango` resolves to python-arango
(a dependency), not scripts/arango.py.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
sys.path = [p for p in sys.path if p not in ("", str(_SCRIPTS))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirements", default=str(ROOT / "docs" / "analytics-requirements.md"),
                    help="business-requirements document (text/markdown)")
    ap.add_argument("--db", default=None, help="target db (default: ARANGO_DATABASE/ARANGO_DB)")
    ap.add_argument("--out", default=str(ROOT / "data" / "analytics_agentic"),
                    help="output directory for workflow artifacts")
    args = ap.parse_args()

    from graph_analytics_ai.config import load_env_vars
    load_env_vars()
    if not os.environ.get("ARANGO_DATABASE") and os.environ.get("ARANGO_DB"):
        os.environ["ARANGO_DATABASE"] = os.environ["ARANGO_DB"]
    if args.db:
        os.environ["ARANGO_DATABASE"] = args.db

    endpoint = os.environ["ARANGO_ENDPOINT"]
    db_name = os.environ.get("ARANGO_DATABASE", "FinReflectKG")
    user = os.environ.get("ARANGO_USER", "root")
    password = os.environ.get("ARANGO_PASSWORD", "")

    req_path = pathlib.Path(args.requirements)
    if not req_path.exists():
        raise SystemExit(f"requirements file not found: {req_path}")

    from graph_analytics_ai.ai.workflow.orchestrator import WorkflowOrchestrator
    from graph_analytics_ai.ai.llm.factory import get_default_provider

    provider = get_default_provider()
    print(f"db={db_name}  llm={getattr(provider, 'name', '?')}:"
          f"{getattr(provider, 'model', '?')}  requirements={req_path.name}  out={args.out}")

    orch = WorkflowOrchestrator(output_dir=args.out, llm_provider=provider,
                                enable_checkpoints=True)
    result = orch.run_complete_workflow(
        business_requirements=[str(req_path)],
        database_endpoint=endpoint,
        database_name=db_name,
        database_username=user,
        database_password=password,
        product_name="FinReflectKG Graph Analytics",
        resume_from_checkpoint=False,
    )

    print(f"\nstatus={result.status}  workflow_id={result.workflow_id}")
    if getattr(result, "completed_steps", None):
        print(f"completed steps ({len(result.completed_steps)}): {result.completed_steps}")
    if getattr(result, "total_duration_seconds", None):
        print(f"duration: {result.total_duration_seconds:.1f}s")
    print(f"output dir: {getattr(result, 'output_dir', args.out)}")
    for attr in ("requirements_path", "use_cases_path", "report_path", "report_html_path"):
        p = getattr(result, attr, None)
        if p:
            print(f"  {attr}: {p}")


if __name__ == "__main__":
    main()

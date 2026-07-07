"""NL-query gold-set runner (G6/M5).

Parses the 22 curated NL -> Cypher -> AQL triplets straight from
docs/cypher-queries.md (single source of truth -- no separate gold file to drift)
and executes each reference AQL against a target database, recording whether it
runs, how long it takes, and how many rows it returns. This is the reproducible
"NL-query readiness" harness: it proves the hand-written gold answers still
execute on the live graph, and it is the reference set the LLM NL->AQL translator
(scripts/nl2aql.py) is scored against.

The reference AQL is written for the baseline `FinReflectKG` (see the conversion
notes in cypher-queries.md), so that is the default target; use --db to run it
elsewhere (results will differ on the SmartGraph because concepts are duplicated
per company).

Usage:
  .venv/bin/python scripts/nl_eval.py                 # all 22 vs FinReflectKG
  .venv/bin/python scripts/nl_eval.py --db FinReflectKgSmart
  .venv/bin/python scripts/nl_eval.py --only 5 9 20   # subset by number
  .venv/bin/python scripts/nl_eval.py --max-runtime 90
"""

import argparse
import json
import pathlib

from arango import ENV, req
from gold import DOC, parse_gold

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "nl_eval_results.json"


def run_aql(db, aql, max_runtime):
    body = {"query": aql, "batchSize": 100,
            "options": {"maxRuntime": max_runtime, "profile": 1}}
    status, r = req("POST", "/_api/cursor", body, db=db, timeout=max_runtime + 15)
    if status not in (200, 201):
        return {"ok": False, "rows": 0, "ms": None, "hasMore": False,
                "error": r.get("errorMessage", f"HTTP {status}")}
    prof = r.get("extra", {}).get("profile", {})
    return {"ok": True, "rows": len(r.get("result", [])),
            "ms": round(prof.get("executing", 0) * 1000, 1),
            "hasMore": r.get("hasMore", False), "error": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=ENV.get("ARANGO_DB", "FinReflectKG"))
    ap.add_argument("--only", nargs="*", type=int, help="run only these query numbers")
    ap.add_argument("--max-runtime", type=int, default=90, help="per-query abort (s)")
    args = ap.parse_args()

    gold = parse_gold()
    if args.only:
        gold = [g for g in gold if g["n"] in set(args.only)]
    print(f"parsed {len(gold)} gold queries from {DOC.name}; target db: {args.db}\n")

    rows, ok_count = [], 0
    for g in gold:
        if not g["aql"]:
            print(f"  {g['n']:>2}. [no AQL block] {g['title']}")
            continue
        res = run_aql(args.db, g["aql"], args.max_runtime)
        ok_count += 1 if res["ok"] else 0
        flag = "ok " if res["ok"] else "ERR"
        ms = f"{res['ms']:>8}" if res["ms"] is not None else "     n/a"
        more = "+" if res["hasMore"] else " "
        print(f"  {g['n']:>2}. [{flag}] {ms}ms  rows={res['rows']:>4}{more}  {g['title'][:52]}"
              + (f"\n        -> {res['error']}" if res["error"] else ""))
        rows.append({**{k: g[k] for k in ("n", "title", "nl")}, **res})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"db": args.db, "results": rows}, indent=2))
    print(f"\n{ok_count}/{len(rows)} executed without error; wrote {OUT}")


if __name__ == "__main__":
    main()

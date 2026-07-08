"""Cypher->AQL evaluation via arango-cypher-py (PRD §4.6 / M5).

Transpiles the **Cypher** column of the gold set (docs/cypher-queries.md) with the
arango-solutions transpiler and executes the resulting AQL against the target db,
recording transpile success, execution success, and row counts. This is the
required NL/Cypher query layer for G6/M5 — FinReflectKG as a workload for
arango-cypher-py.

Vocabulary bridging is arango-cypher-py's responsibility, not this project's:
MappingResolver resolves labels/relationship types by EXACT key match (no case-fold /
lemma / alias) and the analyzer export renames labels lossily (FIN_METRIC -> FINMETRIC)
and caps entities to top-N. Transpile failures below are therefore expected and are
tracked upstream — see arango-cypher-py/docs/finreflectkg-cypher-vocabulary-bug-report.md.
We do NOT rewrite the gold Cypher to work around it.

Runs under the py3.11 venv that has arango-cypher-py installed:
  .venv311/bin/python scripts/cypher_eval.py
  .venv311/bin/python scripts/cypher_eval.py --db FinReflectKG --only 1 5 15
  .venv311/bin/python scripts/cypher_eval.py --graph FinReflectKG --refresh-schema

NOTE: this script must import python-arango's `arango` package, which shares its
name with the REST helper scripts/arango.py. We drop the scripts dir from sys.path
so the package wins, and load the gold parser by file path.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
# Ensure `import arango` resolves to python-arango, not scripts/arango.py.
sys.path = [p for p in sys.path if p not in ("", str(_SCRIPTS))]


def _load_gold():
    spec = importlib.util.spec_from_file_location("gold", _SCRIPTS / "gold.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_gold


def _load_env(path=ROOT / ".env"):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env[k.strip()] = v
    for k, v in os.environ.items():
        if k.startswith("ARANGO_"):
            env[k] = v
    return env


def connect(env, db_name, timeout=180):
    from arango import ArangoClient

    endpoint = env["ARANGO_ENDPOINT"].rstrip("/")
    verify = env.get("ARANGO_VERIFY_SSL", "true").lower() == "true"
    # request_timeout must exceed the AQL maxRuntime, else the HTTP socket read
    # times out (60s default) before the server-side query limit fires.
    client = ArangoClient(hosts=endpoint, verify_override=verify, request_timeout=timeout)
    return client.db(db_name, username=env.get("ARANGO_USER", "root"),
                     password=env.get("ARANGO_PASSWORD", ""), verify=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="target db (default: ARANGO_DB or FinReflectKG)")
    ap.add_argument("--graph", default=None, help="scope schema mapping to a named graph")
    ap.add_argument("--only", nargs="*", type=int)
    ap.add_argument("--max-runtime", type=int, default=90)
    ap.add_argument("--refresh-schema", action="store_true")
    ap.add_argument("--compare-reference", action="store_true",
                    help="also execute the gold reference AQL and compare row counts")
    args = ap.parse_args()

    env = _load_env()
    db_name = args.db or env.get("ARANGO_DB", "FinReflectKG")
    graph = args.graph if args.graph is not None else (
        "FinReflectKG" if db_name in ("FinReflectKG", "FinReflectKgOneShard") else None)

    from arango_cypher import translate
    from arango_cypher.schema_acquire import get_mapping
    from arango_query_core import CoreError

    parse_gold = _load_gold()
    gold = [g for g in parse_gold() if g["cypher"]]
    if args.only:
        gold = [g for g in gold if g["n"] in set(args.only)]

    db = connect(env, db_name, timeout=args.max_runtime + 30)
    print(f"db={db_name}  graph={graph}  transpiler=arango-cypher-py\n"
          f"acquiring schema mapping (analyzer + {get_mapping.__module__})...")
    mapping = get_mapping(db, graph_name=graph, force_refresh=args.refresh_schema)
    pm = mapping.physical_mapping or {}
    print(f"  mapping: {len(pm.get('entities') or {})} entities, "
          f"{len(pm.get('relationships') or {})} relationship types\n")

    rows, n_transpiled, n_exec = [], 0, 0
    for g in gold:
        row = {"n": g["n"], "title": g["title"], "transpiled": False,
               "exec_ok": False, "rows": 0, "transpile_error": None, "exec_error": None}
        try:
            tq = translate(g["cypher"], mapping=mapping)
            row["transpiled"] = True
            row["aql"] = tq.aql
            row["warnings"] = [w.get("message") for w in (tq.warnings or [])]
            n_transpiled += 1
            try:
                cur = db.aql.execute(tq.aql, bind_vars=tq.bind_vars or {},
                                     max_runtime=args.max_runtime, batch_size=100)
                row["rows"] = len(list(cur))
                row["exec_ok"] = True
                n_exec += 1
            except Exception as e:  # noqa: BLE001 - record execution failures
                row["exec_error"] = str(e)[:300]
        except CoreError as e:
            row["transpile_error"] = f"{e.code}: {e}"[:300]
        except Exception as e:  # noqa: BLE001
            row["transpile_error"] = str(e)[:300]

        t = "T" if row["transpiled"] else "-"
        x = "X" if row["exec_ok"] else "-"
        err = row["transpile_error"] or row["exec_error"] or ""
        print(f"  {g['n']:>2}. [{t}{x}] rows={row['rows']:>4}  {g['title'][:48]}"
              + (f"\n        {err}" if err else ""))
        rows.append(row)

    out = ROOT / "data" / "cypher_eval_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"db": db_name, "graph": graph,
                               "transpiled": n_transpiled, "executed": n_exec,
                               "total": len(rows), "results": rows}, indent=2))
    print(f"\ntranspiled {n_transpiled}/{len(rows)} · executed {n_exec}/{len(rows)}; wrote {out}")
    if n_transpiled < len(rows):
        print("note: transpile failures are an arango-cypher-py vocabulary-resolution gap "
              "(exact-match resolver + lossy label normalization), tracked upstream in\n"
              "      arango-cypher-py/docs/finreflectkg-cypher-vocabulary-bug-report.md — "
              "not fixed by rewriting FinReflectKG's gold Cypher.")


if __name__ == "__main__":
    main()

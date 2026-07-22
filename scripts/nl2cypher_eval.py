"""NL->Cypher->AQL evaluation via arango-cypher-py's schema-aware front-end (PRD §4.6 / M5).

This is the front-end counterpart to scripts/cypher_eval.py. Where cypher_eval.py
transpiles the *hand-written* gold Cypher (and so inherits the source-Neo4j vocabulary
that the mapping can't resolve — ORG_REG / :RISK / :METADATA), this runner drives the
**NL question** through arango-cypher-py's `nl_to_cypher` front-end, which is given the
live schema mapping and is expected to emit *mapping-correct* labels. The hypothesis
(nl-graphrag.md "Next step") is that the schema-aware path sidesteps the vocabulary
gap that blocks the direct-Cypher path.

Pipeline per gold query:
  NL --(nl_to_cypher, mapping + LLM provider)--> Cypher
     --(translate, mapping)--> AQL --(execute)--> rows

The LLM step needs a provider. We construct one explicitly rather than relying on
`get_llm_provider()` auto-detect (which prioritizes OpenAI): LLM_PROVIDER/keys come
from .env, mirroring scripts/llm.py, and Anthropic is the configured provider here.

Runs under the py3.11 venv that has arango-cypher-py installed:
  .venv311/bin/python scripts/nl2cypher_eval.py
  .venv311/bin/python scripts/nl2cypher_eval.py --db FinReflectKG --only 1 5 15
  .venv311/bin/python scripts/nl2cypher_eval.py --compare-reference

NOTE: like cypher_eval.py, this must import python-arango's `arango` package, which
shares its name with scripts/arango.py. We drop the scripts dir from sys.path so the
package wins, and load the gold parser by file path.
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
    """Load .env into a dict AND into os.environ (the LLM providers read os.environ)."""
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
            k = k.strip()
            env[k] = v
            # Real env wins; only fill what isn't already set (e.g. exported keys).
            os.environ.setdefault(k, v)
    for k, v in os.environ.items():
        if k.startswith("ARANGO_") or k.startswith("LLM_") or k.endswith("_API_KEY"):
            env[k] = v
    return env


def _make_provider(env):
    """Construct the configured LLM provider (explicit, not auto-detect).

    arango-cypher-py's get_llm_provider() prioritizes OpenAI on auto-detect; this
    deployment uses Anthropic (see scripts/llm.py), so pick by LLM_PROVIDER / key.
    """
    from arango_cypher.nl2cypher import AnthropicProvider, OpenAIProvider, OpenRouterProvider

    prov = (env.get("LLM_PROVIDER") or "").lower()
    if not prov:
        if env.get("OPENAI_API_KEY"):
            prov = "openai"
        elif env.get("OPENROUTER_API_KEY"):
            prov = "openrouter"
        elif env.get("ANTHROPIC_API_KEY"):
            prov = "anthropic"
    if prov == "anthropic":
        return AnthropicProvider(model=env.get("ANTHROPIC_MODEL") or None), "anthropic"
    if prov == "openrouter":
        return OpenRouterProvider(model=env.get("OPENROUTER_MODEL") or None), "openrouter"
    if prov == "openai":
        return OpenAIProvider(model=env.get("OPENAI_MODEL") or None), "openai"
    raise SystemExit("no LLM provider configured; set LLM_PROVIDER + an *_API_KEY in .env")


def connect(env, db_name, timeout=180):
    from arango import ArangoClient

    endpoint = env["ARANGO_ENDPOINT"].rstrip("/")
    verify = env.get("ARANGO_VERIFY_SSL", "true").lower() == "true"
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
    from arango_cypher.nl2cypher import nl_to_cypher
    from arango_cypher.schema_acquire import get_mapping
    from arango_query_core import CoreError

    parse_gold = _load_gold()
    gold = [g for g in parse_gold() if g["nl"]]
    if args.only:
        gold = [g for g in gold if g["n"] in set(args.only)]

    provider, provider_name = _make_provider(env)
    provider_model = getattr(provider, "model", None)
    db = connect(env, db_name, timeout=args.max_runtime + 30)
    print(f"db={db_name}  graph={graph}  front-end=nl_to_cypher  "
          f"llm={provider_name}:{provider_model}\n"
          f"acquiring schema mapping (analyzer + {get_mapping.__module__})...")
    mapping = get_mapping(db, graph_name=graph, force_refresh=args.refresh_schema)
    pm = mapping.physical_mapping or {}
    print(f"  mapping: {len(pm.get('entities') or {})} entities, "
          f"{len(pm.get('relationships') or {})} relationship types\n")

    rows, n_gen, n_transpiled, n_exec = [], 0, 0, 0
    for g in gold:
        row = {"n": g["n"], "title": g["title"], "nl": g["nl"],
               "generated": False, "transpiled": False, "exec_ok": False, "rows": 0,
               "cypher": None, "confidence": None, "method": None,
               "gen_error": None, "transpile_error": None, "exec_error": None}
        try:
            nlres = nl_to_cypher(g["nl"], mapping=mapping, llm_provider=provider, db=db)
            row["cypher"] = nlres.cypher
            row["confidence"] = getattr(nlres, "confidence", None)
            row["method"] = getattr(nlres, "method", None)
            row["generated"] = bool(nlres.cypher)
            if row["generated"]:
                n_gen += 1
        except Exception as e:  # noqa: BLE001 - record generation failures
            row["gen_error"] = str(e)[:300]

        if row["generated"]:
            try:
                tq = translate(row["cypher"], mapping=mapping)
                row["transpiled"] = True
                row["aql"] = tq.aql
                n_transpiled += 1
                try:
                    cur = db.aql.execute(tq.aql, bind_vars=tq.bind_vars or {},
                                         max_runtime=args.max_runtime, batch_size=100)
                    row["rows"] = len(list(cur))
                    row["exec_ok"] = True
                    n_exec += 1
                except Exception as e:  # noqa: BLE001
                    row["exec_error"] = str(e)[:300]
            except CoreError as e:
                row["transpile_error"] = f"{e.code}: {e}"[:300]
            except Exception as e:  # noqa: BLE001
                row["transpile_error"] = str(e)[:300]

        if args.compare_reference and g["aql"]:
            try:
                cur = db.aql.execute(g["aql"], max_runtime=args.max_runtime, batch_size=100)
                row["ref_rows"] = len(list(cur))
            except Exception as e:  # noqa: BLE001
                row["ref_error"] = str(e)[:200]

        gcol = "G" if row["generated"] else "-"
        t = "T" if row["transpiled"] else "-"
        x = "X" if row["exec_ok"] else "-"
        conf = f" conf={row['confidence']:.2f}" if isinstance(row["confidence"], (int, float)) else ""
        err = row["gen_error"] or row["transpile_error"] or row["exec_error"] or ""
        print(f"  {g['n']:>2}. [{gcol}{t}{x}] rows={row['rows']:>4}{conf}  {g['title'][:44]}"
              + (f"\n        {err}" if err else ""))
        rows.append(row)

    out = ROOT / "data" / "nl2cypher_eval_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"db": db_name, "graph": graph, "llm": provider_name,
                               "llm_model": provider_model,
                               "generated": n_gen, "transpiled": n_transpiled,
                               "executed": n_exec, "total": len(rows), "results": rows},
                              indent=2))
    print(f"\ngenerated {n_gen}/{len(rows)} · transpiled {n_transpiled}/{len(rows)} · "
          f"executed {n_exec}/{len(rows)}; wrote {out}")


if __name__ == "__main__":
    main()

# NL-Query & GraphRAG Evaluation (M5 / G6)

**Status:** v0.3 · 2026-07-07 · GraphRAG retrieval/grounding verified; **required
[`arango-cypher-py`](https://github.com/arango-solutions/arango-cypher-py) Cypher→AQL
integration built** ([`scripts/cypher_eval.py`](../scripts/cypher_eval.py)) and run —
the vocabulary gap was filed against the library and an upstream resolver fix took it
from **3/22 → 14/22** transpile (7/22 execute); remaining items are upstream. The
bespoke `nl2aql.py` prototype was **removed**. NL→Cypher and answer synthesis pending.
**Related:** [cypher-queries.md](cypher-queries.md) (the 22-query gold set) ·
[PRD.md](PRD.md) §4.6 · [benchmark-report.md](benchmark-report.md)

> **Required NL/Cypher engine — `arango-cypher-py`.** The query layer uses the
> arango-solutions Cypher→AQL transpiler (`arango_cypher.translate(cypher, mapping=…)`
> / `arango_cypher.execute(cypher, db=…, mapping=…)`), with an `nl2cypher` front-end
> for the NL step. FinReflectKG is a workload for it. The evaluation transpiles the
> **Cypher column** of the 22-query gold set and executes the AQL.

This milestone evaluates two ways of answering natural-language questions over
FinReflectKG, both leveraging the per-triple source text that the model co-locates
with each company's subgraph in the SmartGraph build:

1. **NL → AQL** — translate a question to AQL, execute it, return rows.
2. **GraphRAG** — link entities, retrieve a grounded subgraph + its source text,
   and synthesize a cited answer.

Per the PRD phase-2 non-goal, entity linking uses the **`node_name` index, not
vector search**.

## Components

| Script | Role | Needs LLM? |
|---|---|---|
| [`scripts/nl_eval.py`](../scripts/nl_eval.py) | Parse the 22 curated NL/Cypher/AQL triplets from `cypher-queries.md` and execute each reference AQL against a db (the "gold set" / readiness check). | no |
| [`scripts/llm.py`](../scripts/llm.py) | Pluggable LLM helper — Anthropic or OpenAI via HTTP, provider/keys from env; degrades to dry-run when unset. | — |
| [`scripts/nl2aql.py`](../scripts/nl2aql.py) | **Superseded** (see §4.6): bespoke NL→AQL prompt with live schema + few-shot. Retained only as a schema-prompt experiment; the required path is `arango-cypher-py`. | to generate |
| [`scripts/cypher_eval.py`](../scripts/cypher_eval.py) | **Required integration.** Acquires a `MappingBundle` via `arango_cypher.schema_acquire.get_mapping(db, graph_name=…)`, transpiles the gold-set Cypher with `arango_cypher.translate`, executes, records results. Runs under `.venv311`. | no (transpiler is deterministic) |
| [`scripts/gold.py`](../scripts/gold.py) | Dependency-free parser for the 22-query gold set (shared by `nl_eval.py` and `cypher_eval.py`). | no |
| [`scripts/graphrag.py`](../scripts/graphrag.py) | Entity-link → typed VCI neighborhood → `chunks` grounding → cited answer. | to synthesize |

## Environment

`arango-cypher-py` requires **Python 3.11+**, so the Cypher→AQL path runs in a
dedicated `.venv311` (the main pipeline stays on the 3.9 `.venv`):

```bash
python3.11 -m venv .venv311
.venv311/bin/pip install -e "/path/to/arango-cypher-py[analyzer]"   # local editable
.venv311/bin/python scripts/cypher_eval.py --db FinReflectKG
```

The `[analyzer]` extra pulls `arangodb-schema-analyzer` for accurate LPG mapping.
(`scripts/arango.py` shadows python-arango's `arango` package by name; `cypher_eval.py`
drops the scripts dir from `sys.path` and loads the gold parser by file path to avoid
the clash.)

## Configuration

Copy `.env.example` → `.env` and (optionally) set one LLM provider:

```
LLM_PROVIDER=anthropic         # or openai; auto-detected from whichever key is set
ANTHROPIC_API_KEY=...          # or OPENAI_API_KEY=...
```

Without a key, every script still runs: `nl_eval.py` fully, `nl2aql.py --show-prompt`
prints the assembled prompt, and `graphrag.py` prints the assembled grounded context.

## Usage

```bash
# Gold-set readiness (baseline, where the reference AQL is written)
.venv/bin/python scripts/nl_eval.py

# NL -> AQL (dry-run prompt without a key; generate + execute with one)
.venv/bin/python scripts/nl2aql.py -q "Which orgs operate in over 3 locations?"
.venv/bin/python scripts/nl2aql.py --eval --only 5 12 14      # score vs gold (needs key)

# GraphRAG on the SmartGraph (text co-located per company)
.venv/bin/python scripts/graphrag.py -q "Where does Apple operate?" --entity aapl
```

## Verified results (2026-07-07)

- **Gold set:** 21/22 reference AQL execute against `FinReflectKG`
  (`scripts/nl_eval.py`). The single failure is query 18 — the unbounded
  circular-dependency scan `cypher-queries.md` already flags as too expensive; it is
  killed by the runtime cap. The zero-row results (7, 9, 10, 19, 21, 22) reproduce the
  dataset/vocabulary caveats documented in that file.
- **GraphRAG retrieval:** on `FinReflectKgSmart`, `aapl` links to its ORG subgraph
  root `Node/aapl:…` and returns 24 grounded facts — **all 24 carry co-located source
  text**, confirming the Design-2 text co-location pays off for retrieval.
  - Note: on the SmartGraph a company name resolves to many nodes (its own root plus
    duplicated references inside other companies' subgraphs); `resolve()` ranks the
    ticker-prefixed smart-key root (`aapl:…`) and ORG/COMP types first.

## Cypher→AQL via arango-cypher-py (2026-07-07)

`scripts/cypher_eval.py` against `FinReflectKG` (graph-scoped mapping: 20 entities,
200 relationship types). **The vocabulary resolution is `arango-cypher-py`'s
responsibility, not FinReflectKG's — we do not rewrite the gold Cypher.** That was
filed as a bug report against the library
(`arango-cypher-py/docs/finreflectkg-cypher-vocabulary-bug-report.md`); an upstream fix
followed and was retested here.

| Run | Transpile | Execute |
|---|---|---|
| Initial (exact-match resolver) | 3/22 | 3/22 |
| After upstream resolver fix | **14/22** | **7/22** |

**Fixed upstream** — the resolver now does case/underscore-insensitive matching, so
`Has_Stake_In` → `has_stake_in` and `FIN_METRIC` → `FINMETRIC` resolve (7 more queries
transpile). Remaining failures, by owner:

- **`arango-cypher-py` — still open:**
  - **Invalid AQL generated** (surfaced once vocabulary resolved): #8 →
    `collection or view not found: loc`; #16 (3-hop) →
    `variable 'v' is assigned multiple times` (var-length expansion reassigns the
    traversal variable and references undefined edge vars).
  - **`reduce(...)`** (#22) still returns `CYPHER_SYNTAX_ERROR` in the installed tree
    (an upstream reduce fix is described but its regenerated parser isn't active here).
  - **Efficiency:** #5/#9/#13/#18/#19 transpile to valid but slow AQL (killed at the
    runtime cap; the hand-written equivalents run in ms) — the generated AQL doesn't
    engage the vertex-centric fast path.
- **`arangodb-schema-analyzer` — upstream:** the top-20 entity cap drops `ORG_REG`
  (#12/#14/#17 → `MAPPING_NOT_FOUND: ORG_REG`).
- **Not a library issue (gold-set/data vocabulary):** #10/#11/#20 use `:RISK` and #21
  uses `:METADATA` — labels that do not exist in the FinReflectKG dataset (documented
  caveats in [cypher-queries.md](cypher-queries.md)).

Raw results: `data/cypher_eval_results.json`. Next step: drive the eval through the
schema-aware `nl2cypher` front-end (emits mapping-correct labels) rather than
hand-written Cypher.

## Pending

- **NL→Cypher** via `arango_cypher.nl2cypher` (needs a provider key) — the schema-aware
  front-end that emits mapping-correct Cypher, then transpile+execute via `cypher_eval`.
- **GraphRAG answer synthesis** quality (cited answers) — a small rubric over a handful
  of questions (needs a provider key).
- Re-run `cypher_eval.py` once the upstream invalid-AQL (#8/#16), `reduce()`, and
  entity-cap (`ORG_REG`) items land.

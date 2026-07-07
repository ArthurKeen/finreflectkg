# NL-Query & GraphRAG Evaluation (M5 / G6)

**Status:** v0.3 · 2026-07-07 · GraphRAG retrieval/grounding verified; **required
[`arango-cypher-py`](https://github.com/arango-solutions/arango-cypher-py) Cypher→AQL
integration built** ([`scripts/cypher_eval.py`](../scripts/cypher_eval.py)) and run
(3/22 as-is — vocabulary-alignment finding below). The bespoke `nl2aql.py` prototype
was **removed**. NL→Cypher and answer synthesis remain pending.
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
200 relationship types): **3/22 gold Cypher queries transpile + execute** as written
(#1 entity-type distribution, #2 relationship-type distribution, #15 Apple's related
orgs). The transpiler itself works; the other 19 fail for **schema-vocabulary**
reasons, which is the key integration finding:

- **Relationship case/lemma** — the gold Cypher uses the original Neo4j spelling
  (`Has_Stake_In`, `Operates_In`, `Depends_On`, `Negatively_Impacts`), but the
  schema-derived mapping exposes the graph's actual lowercase-lemmatized values
  (`has_stake_in`, `operates_in`, …). Result: `MAPPING_NOT_FOUND: No relationship
  mapping for: Has_Stake_In`.
- **Entity-label normalization + top-N cap** — labels come back underscore-stripped
  and uppercased (`FIN_METRIC` → `FINMETRIC`, `RISK_FACTOR` → `RISKFACTOR`), and the
  open-vocab mapping keeps the **top 20** entity labels by volume, so `ORG_REG`
  (rank ~24) is absent. Gold queries using `:FIN_METRIC` / `:ORG_REG` miss.
- **Transpiler coverage gap** — query 22 uses `reduce(...)`, unsupported:
  `CYPHER_SYNTAX_ERROR ... no viable alternative at input 'reduce'`.

**Responsibility — this is an `arango-cypher-py` gap, not a FinReflectKG one.** The
transpiler's `MappingResolver` (`arango_query_core/mapping.py`) resolves labels and
relationship types by **exact dict-key match** — no case-fold, no lemma/underscore
normalization, no alias/synonym layer — and the analyzer export **renames** entity
labels lossily (`FIN_METRIC` → `FINMETRIC`) and caps them to the top-20. Bridging the
Cypher vocabulary to the graph's is the transpiler's job, so **FinReflectKG will not
rewrite its gold Cypher to the mapping's internal spellings.** The fix belongs
upstream (resolver normalization + alias + label fidelity) and/or in the schema-aware
`nl2cypher` front-end, which emits mapping-correct labels by construction.

Filed as a bug report / feature request against the library:
`arango-cypher-py/docs/finreflectkg-cypher-vocabulary-bug-report.md`. Raw results:
`data/cypher_eval_results.json`. Next step here is to drive the eval through
`nl2cypher` once available, rather than hand-writing Cypher.

## Pending (needs a provider key)

- NL→AQL generation accuracy (`nl2aql.py --eval`) scored across the gold set.
- GraphRAG answer synthesis quality (cited answers) — a small rubric over a handful
  of questions.

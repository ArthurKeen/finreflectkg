# NL-Query & GraphRAG Evaluation (M5 / G6)

**Status:** v0.4 · 2026-07-22 · **M5 complete.** The schema-aware **NL→Cypher
front-end** was run ([`scripts/nl2cypher_eval.py`](../scripts/nl2cypher_eval.py)):
**19/22 transpile, 9/22 execute**, and the vocabulary gap that capped the
hand-written path is **gone — 0 `MAPPING_NOT_FOUND`** (CINF-stake queries that
returned 0 rows against the foreign vocabulary now return 219). **GraphRAG answer
synthesis** scored **5/5** on a rubric ([`scripts/graphrag_rubric.py`](../scripts/graphrag_rubric.py)),
including a faithful abstention on an out-of-scope question. Root-caused the gold-set
vocabulary mismatch against **live data**: the gold Cypher was authored against a
**sibling schema** (`:RISK` vs this graph's `RISK_FACTOR`), and `ORG_REG` is real in
FinReflectKG (11,193 nodes) but dropped by the analyzer's **top-20 entity cap**. The
direct hand-written-Cypher path holds at **14/22 transpile, 7/22 execute**
([`scripts/cypher_eval.py`](../scripts/cypher_eval.py)). The remaining ceiling is
upstream (transpiler bugs + non-VCI AQL efficiency), not a FinReflectKG concern.
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
| [`scripts/cypher_eval.py`](../scripts/cypher_eval.py) | **Required integration.** Acquires a `MappingBundle` via `arango_cypher.schema_acquire.get_mapping(db, graph_name=…)`, transpiles the **hand-written** gold-set Cypher with `arango_cypher.translate`, executes, records results. Runs under `.venv311`. | no (transpiler is deterministic) |
| [`scripts/nl2cypher_eval.py`](../scripts/nl2cypher_eval.py) | **NL→Cypher front-end.** Drives the **NL question** through `arango_cypher.nl2cypher.nl_to_cypher` (schema mapping + LLM provider) → Cypher → `translate` → AQL → execute. Constructs the provider explicitly (Anthropic/OpenAI/OpenRouter) from `.env`. Records generated Cypher for label-correctness inspection. Runs under `.venv311`. | yes (generation) |
| [`scripts/gold.py`](../scripts/gold.py) | Dependency-free parser for the 22-query gold set (shared by `nl_eval.py`, `cypher_eval.py`, `nl2cypher_eval.py`). | no |
| [`scripts/graphrag.py`](../scripts/graphrag.py) | Entity-link → typed VCI neighborhood → `chunks` grounding → cited answer. Exposes `synthesize(question, context)` (shared with the rubric). | to synthesize |
| [`scripts/graphrag_rubric.py`](../scripts/graphrag_rubric.py) | Runs `graphrag`'s pipeline over a fixed question set and scores each answer on a deterministic rubric (linked / grounded / answered / cited / citations-valid / abstained). | yes (synthesis) |

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

Without a key, `nl_eval.py` and `cypher_eval.py` run fully (both are deterministic —
no LLM), and `graphrag.py` prints the assembled grounded context (dry-run). The
`nl2cypher_eval.py` front-end and `graphrag_rubric.py` need a key (they generate/
synthesize with the LLM).

## Usage

```bash
# Gold-set readiness (baseline, where the reference AQL is written)
.venv/bin/python scripts/nl_eval.py

# Cypher->AQL: transpile the hand-written gold Cypher (deterministic, no key)
.venv311/bin/python scripts/cypher_eval.py --db FinReflectKG --graph FinReflectKG

# NL->Cypher front-end: NL -> nl_to_cypher -> translate -> execute (needs key)
.venv311/bin/python scripts/nl2cypher_eval.py --db FinReflectKG --graph FinReflectKG
.venv311/bin/python scripts/nl2cypher_eval.py --only 5 12 14   # subset

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
- **GraphRAG answer synthesis (2026-07-22):** `scripts/graphrag_rubric.py` on
  `FinReflectKgSmart` with `anthropic:claude-sonnet-4-5` — **5/5 pass** over five
  questions. Each in-scope answer linked its entity, retrieved 60 grounded facts
  (59–60 with source text), produced a `[n]`-cited answer, and **every cited index was
  valid** (no hallucinated citations). Notable behaviours: on "Who does Cincinnati
  Financial hold a stake in?" the model correctly flagged the **inverted premise**
  (other companies hold stakes in CINF, not the reverse) rather than fabricating; on
  the deliberately out-of-scope "deep-sea mining rights" question it **abstained**
  ("cannot find any information") instead of hallucinating. Raw: `data/graphrag_rubric.json`.

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

Raw results: `data/cypher_eval_results.json`.

## NL→Cypher via the schema-aware front-end (2026-07-22)

`scripts/nl2cypher_eval.py` drives the **NL question** through
`arango_cypher.nl2cypher.nl_to_cypher` — which is handed the live mapping and writes
Cypher **in the ontology's own vocabulary** — then transpiles and executes. Against
`FinReflectKG` (graph-scoped mapping, `openai:gpt-4o-mini` — the library default model):

| Path | Transpile | Execute | `MAPPING_NOT_FOUND` (vocabulary) |
|---|---|---|---|
| Hand-written gold Cypher (`cypher_eval.py`) | 14/22 | 7/22 | **7 queries** |
| NL→Cypher front-end (`nl2cypher_eval.py`) | **19/22** | **9/22** | **0 queries** |

The vocabulary gap that dominated the hand-written path **disappears** when the model
emits mapping-correct labels: it produced `:FINMETRIC`, `:RISKFACTOR`, `:ORG`,
`regulates`, and the CINF-stake queries (3, 4) that returned **0 rows** against the
foreign vocabulary now return **219**. It even worked around the capped `ORG_REG` by
expressing "regulator" semantically as `(:ORG)-[:regulates]->(:ORG)`.

The remaining ceiling is **not** vocabulary — it is:
- **Transpiler `variable 'x' is assigned multiple times` (ERR 1511)** on multi-`WITH`
  queries that rebind a node variable across `MATCH` clauses (killed 2 generations
  at the front-end's own EXPLAIN-validation retries; conf 0.00). Same bug class as
  hand-written #16.
- **AQL efficiency:** 10 generated queries transpile but are **killed at the runtime
  cap** — the generated traversals don't engage the vertex-centric fast path (§ see
  the VCI note below / benchmark-report.md).
- **`:METADATA` (#21):** the one gold label with no FinReflectKG equivalent.

`gpt-4o-mini` is the library default, so 19/9 is a **floor** — a stronger model would
likely resolve some multi-`WITH` phrasings. Raw: `data/nl2cypher_eval_results.json`.

## Vocabulary root-cause (live-data evidence, 2026-07-22)

The transpiler acquires its ontology **from the FinReflectKG database** (schema
analyzer, cached in `arango_cypher_schema_cache`), so the ontology *is* the graph's
vocabulary — but with two transforms that explain every failure:

1. **The analyzer normalizes labels** (strips `_`/case) to form the ontology label,
   while keeping the exact DB string in `physical_mapping.typeValue` (used in the
   emitted AQL). Verified from the live mapping: `ACCOUNTINGPOLICY → "ACCOUNTING_POLICY"`,
   `ECONIND → "ECON_IND"`, `FINMETRIC → "FIN_METRIC"`. The round-trip is exact; only the
   label you *write in Cypher* is the normalized form.
2. **The gold Cypher uses a third vocabulary** — the sibling dataset it was authored
   against. Resolving it against this ontology gives three outcomes (live-data probes):

   | Gold label | In this graph? | Resolves? | Why |
   |---|---|---|---|
   | `FIN_METRIC` | yes (`FIN_METRIC`, 1.15 M) | ✅ | cosmetic diff; case/`_`-insensitive resolver bridges → `FINMETRIC` |
   | `:RISK` | **renamed** → `RISK_FACTOR` (164,991) | ❌ | different word; resolver can't bridge `risk`→`riskfactor` |
   | `ORG_REG` | **yes** (`ORG_REG`, 11,193, rank 24) | ❌ | real in the data but **dropped by the analyzer's top-20 entity cap** |
   | `:METADATA` | **absent** | ❌ | no `METADATA`/`META_DATA` type exists in FinReflectKG |

So of the 8 hand-written non-transpiling failures: **3 are the `RISK`→`RISK_FACTOR`
rename**, **3 are `ORG_REG` capped out of the top-20 ontology**, **1 is `:METADATA`
(genuinely absent)**, and **1 is `reduce()`** (parser not regenerated in the installed
tree). Six of eight are naming/cap artifacts of reusing a sibling schema's queries —
not defects in how the transpiler reads the schema. Writing in the ontology's
vocabulary (as the NL front-end does) dissolves them. FinReflectKG does **not** rewrite
its gold Cypher; the fixes are (a) raise the analyzer entity cap upstream so `ORG_REG`
(and ranks 21–24: `ESG_TOPIC`, `FIN_MARKET`, `PROPERTY`) enter the mapping, and (b) rely
on the schema-aware front-end for renamed labels.

## Pending / upstream

FinReflectKG-side M5 work is **complete** (NL→Cypher + GraphRAG synthesis both run and
recorded). Remaining items are upstream `arango-cypher-py` / `arangodb-schema-analyzer`:

- **Transpiler ERR 1511** (`variable assigned multiple times`) on multi-`WITH` /
  reused-variable patterns — invalid AQL; blocks hand-written #16 and 2 front-end
  generations.
- **Non-VCI AQL** — generated typed 1-hop / traversal AQL doesn't hit the
  vertex-centric fast path, so it times out at scale (10 front-end queries). See the
  VCI investigation (in progress) for whether a rewrite or `translate` option helps.
- **Analyzer top-20 entity cap** — make it configurable so `ORG_REG` et al. enter the
  ontology (`DEFAULT_MAX_RELATIONSHIP_TYPES = 200` exists; no entity analog).
- **`reduce()` (#22)** — fix is in the git history but the regenerated parser isn't
  active in the installed tree.
- Re-run both evals once these land.

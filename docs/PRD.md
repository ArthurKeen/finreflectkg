# PRD — FinReflectKG on ArangoDB (Proof of Concept)

**Status:** Draft v0.11 · 2026-07-29 (graph-analytics base implemented & verified — GAE PageRank + WCC end-to-end on all 3.1 M nodes via `agentic-graph-analytics`; agentic NL→insights layer pending — G8/§4.7)
**Authors:** Arthur Keen (ArangoDB)
**Related docs:** [data-analysis.md](data-analysis.md) · [etl-plan.md](etl-plan.md) ·
[load-report.md](load-report.md) · [sharding-analysis.md](sharding-analysis.md) ·
[multi-distribution-plan.md](multi-distribution-plan.md) ·
[schema-mapping.md](schema-mapping.md) · [cypher-queries.md](cypher-queries.md) ·
[nl-graphrag.md](nl-graphrag.md) ·
[data_dictionary.md](data_dictionary.md) · paper: [research/2508.17906v2.pdf](research/2508.17906v2.pdf)

## 0. Changelog

- **v0.11 (2026-07-29):** **Graph-analytics base layer implemented & verified (G8).**
  Resumed via **`agentic-graph-analytics`** (`import graph_analytics_ai`, ACP-ready)
  installed into `.venv311`; re-pointed [scripts/analytics.py](../scripts/analytics.py)
  and ran GAE jobs **end-to-end** on the self-managed ACP engine (deploy → readiness →
  load → analyze → store → cleanup): **PageRank** — top nodes `net income`, `revenue`,
  `net sale`, `operate income`, … (the central `FIN_METRIC` supernodes), ~1.9 min,
  3,099,773 result docs, ≈$0.013 — and **WCC** — 3,322 components, one giant component of
  3,091,396 nodes (99.7%), ~1.5 min. Results land in non-mutating `gae_<algorithm>`
  collections. The GRAL ingress-readiness issue that blocked the standalone orchestrator
  is handled by this client (readiness poll + transient-404 retry). Agentic NL→insights
  layer still pending. G8/M7 → Partial.
- **v0.10 (2026-07-29):** **Graph analytics (GAE) — goal added, availability + approach
  established, implementation deferred (new G8 / §4.7).** Confirmed the ArangoDB Graph
  Analytics Engine is available on this deployment: it's an **ArangoDB Platform (ACP)**
  cluster and a GAE engine **deploys/deletes cleanly** (self-managed, `/gen-ai/v1/graphanalytics`
  lifecycle). Root-caused a compute-load failure: the per-engine route
  (`/gral/<id>/v1/loaddata`) is only live ~30–60 s after deploy while the GRAL ingress
  rolls out; the standalone **`graph-analytics-orchestrator`** retries only ~3×/~12 s (by
  re-deploying) and 404s, whereas **`agentic-graph-analytics`** (`graph_analytics_ai`) is
  ACP-ready (readiness polling + retry on the transient `unknown path '/gral/..'`) and
  ships **both** a deterministic orchestrator mode and an agentic NL→insights mode.
  **Decision:** integrate via **`agentic-graph-analytics`** (both layers — it contains
  the deterministic orchestrator *and* the agentic layer), not the standalone
  orchestrator. A draft scaffold ([scripts/analytics.py](../scripts/analytics.py)) exists,
  to be re-pointed. No further cluster work this pass.
- **v0.9 (2026-07-22):** **M5 complete — NL→Cypher front-end + GraphRAG synthesis.**
  Repaired `.venv311` (installed the newly-extracted `arango-query-core` dependency)
  and ran the schema-aware **NL→Cypher front-end**
  ([scripts/nl2cypher_eval.py](../scripts/nl2cypher_eval.py)): **19/22 transpile,
  9/22 execute** with **0 `MAPPING_NOT_FOUND`** — the vocabulary gap that capped the
  hand-written path disappears when the model writes in the ontology's own labels
  (CINF-stake queries **0 → 219 rows**). **GraphRAG answer synthesis** scored **5/5**
  on a rubric ([scripts/graphrag_rubric.py](../scripts/graphrag_rubric.py)), including
  a faithful abstention on an out-of-scope question and catching an inverted-premise
  question. **Root-caused the gold-set vocabulary mismatch against live data:** the
  gold Cypher was authored against a **sibling schema** (`:RISK` vs this graph's
  `RISK_FACTOR`); `ORG_REG` is real in FinReflectKG (11,193 nodes) but dropped by the
  analyzer's **top-20 entity cap**; `:METADATA` is genuinely absent. Direct
  hand-written Cypher holds at **14/22 · 7/22**
  ([scripts/cypher_eval.py](../scripts/cypher_eval.py)). Remaining ceiling is upstream
  (transpiler ERR 1511 on multi-`WITH`; **non-VCI AQL efficiency**; analyzer entity cap;
  `reduce()`), not a FinReflectKG concern. Corrected the stale "awaits a provider key"
  notes (a key is configured). Details: [nl-graphrag.md](nl-graphrag.md).
- **v0.8 (2026-07-07):** **Upstream vocabulary fix verified.** After the `arango-cypher-py`
  resolver was made case/normalization-insensitive, the Cypher→AQL retest went
  **3/22 → 14/22 transpile (7/22 execute)**. Updated the bug report with the retest and two
  newly-pinpointed upstream transpile-correctness bugs (invalid AQL: `collection not found: loc`;
  `variable 'v' assigned multiple times`), plus that `reduce()` still errors in the installed tree
  and the `ORG_REG` entity-cap remains (analyzer). Added a `request_timeout` to the eval harness.
- **v0.7 (2026-07-07):** **Built the `arango-cypher-py` integration**
  ([scripts/cypher_eval.py](../scripts/cypher_eval.py), in a dedicated py3.11 `.venv311`):
  acquires a live `MappingBundle` (20 entities / 200 relationship types) and transpiles
  the gold-set Cypher. **3/22 transpile+execute as-is;** the rest expose a
  schema-vocabulary gap — the gold Cypher uses source Neo4j spellings (`Has_Stake_In`,
  `FIN_METRIC`) while the mapping exposes the graph's lemmatized/normalized labels
  (`has_stake_in`, `FINMETRIC`), plus one transpiler gap (`reduce()`). Removed the
  bespoke `scripts/nl2aql.py`. **Determined the 19 failures are an upstream
  `arango-cypher-py` vocabulary-resolution gap** (exact-match `MappingResolver` + lossy
  label normalization + top-N entity cap), **not** a FinReflectKG concern — filed a bug
  report/feature request at `arango-cypher-py/docs/finreflectkg-cypher-vocabulary-bug-report.md`.
  FinReflectKG will not rewrite its gold Cypher; the fix is upstream and/or via the
  schema-aware `nl2cypher` front-end.
- **v0.6 (2026-07-07):** **Recorded the `arango-cypher-py` requirement (new §4.6).**
  The NL/Cypher query layer for G6/M5 must use
  [`arango-cypher-py`](https://github.com/arango-solutions/arango-cypher-py) (the
  arango-solutions Cypher→AQL transpiler + `nl2cypher`), with FinReflectKG as a real
  workload for it — this was an implicit requirement missing from the PRD. The
  bespoke `scripts/nl2aql.py` from v0.5 is **superseded** by that integration (still
  pending); GraphRAG retrieval/grounding stands. Corrected the §4.4 note:
  `arango_cypher_schema_cache` is that library's schema cache, not unrelated tooling.
  G6 downgraded Done→Partial accordingly.
- **v0.5 (2026-07-07):** **NL-query harness + GraphRAG pipelines (G6 done, M5 in
  progress).** Added a gold-set runner ([nl-graphrag.md](nl-graphrag.md)) that parses
  the 22 curated queries from [cypher-queries.md](cypher-queries.md) (21/22 execute),
  a pluggable LLM helper, an NL→AQL translator (live-schema + few-shot prompt), and a
  GraphRAG pipeline (name-index entity linking → VCI neighborhood → `chunks`
  grounding). Verified grounded retrieval on `FinReflectKgSmart` (24/24 facts carry
  co-located source text). LLM-dependent generation/answer scoring awaits a provider key.
- **v0.4 (2026-07-05):** **Cross-distribution benchmarks complete (G5/M4 done).**
  Ran the PRD §6 suite against all three distributions with deterministic
  scanned-edge + explain-locality metrics ([benchmark-report.md](benchmark-report.md)).
  Headline: Design 2's per-company concept duplication **decomposes the `net income`
  supernode ~250×** (228.6 ms → 0.9 ms; 59,315 → 35 scanned edges) for company-scoped
  queries, at the predicted cost of costlier global concept roll-ups (name lookup
  returns 873 per-company copies; cross-company 2-hop pays `RemoteNode` hops).
- **v0.3 (2026-07-05):** **SmartGraph build complete.** `FinReflectKgSmart`
  (Design 2, Disjoint SmartGraph by `ticker`) loaded & validated —
  **6,658,668 nodes / 17,513,372 edges / 1,384,513 chunks**, VCIs built,
  referential integrity clean, and a per-company traversal confirmed
  **shard-local** (no `RemoteNode`) with its source text co-located. All three
  distributions (baseline, OneShard, SmartGraph) are now built (G7/M6 done). The
  interim `FinReflectKgSmartPilot` pilot database was retired.
- **v0.2 (2026-06-29):** Full dataset loaded & validated (M3 done); corrected the
  VCI finding (VCIs accelerate **direct edge-collection queries, not pattern
  traversals** on 3.12.x cluster — see [load-report.md](load-report.md)); added the
  **multi-distribution** requirement (OneShard + SmartGraph builds, G7/§4.5) after
  performance-testing requirements changed; corrected loaded chunk count.
  **SmartGraph design locked to Design 2** (Disjoint
  SmartGraph by `ticker`, concepts duplicated, `chunks` co-located by `ticker`).
- **v0.1 (2026-06-12):** Initial POC scope.

## 1. Background

Domyn publishes [FinReflectKG](https://huggingface.co/datasets/domyn/FinReflectKG), a
financial knowledge graph extracted from S&P 500 10-K SEC filings (2014–2024):
**17.51 M triples** over **743 companies**, with entity/target types, normalized
relationship names, temporal validity bounds, and the full source-text chunk for
every triple (paper: [arXiv:2508.17906](https://arxiv.org/abs/2508.17906)).

This is a POC to load that dataset into a managed ArangoDB deployment and evaluate:

1. **Graph query performance** — typed traversals at scale, supported by
   vertex-centric indexes (VCI).
2. **Natural-language query performance** — NL → AQL / GraphRAG-style question
   answering over the graph, leveraging the per-triple source text.

## 2. Goals

| # | Goal | Success criterion | Status |
|---|------|-------------------|--------|
| G1 | Full dataset loaded into the remote ArangoDB instance defined in `.env` (db `FinReflectKG`) | Row counts in ArangoDB reconcile exactly with the source parquet (nodes, relations, chunks) | **Done** — loaded & validated, 0 errors ([load-report.md](load-report.md)) |
| G2 | LPG data model with Neo4j-aligned terminology | One `Node` document collection, one `relations` edge collection; edges carry `type`, `_fromType`, `_toType` | **Done** |
| G3 | Vertex-centric indexes on edges | Persistent indexes on `(_from, type, _toType)` and `(_to, type, _fromType)`; AQL profiles show index use on **direct edge-collection queries** (see §4.2 note) | **Done** (with refined finding) |
| G4 | Repeatable, resumable ETL | Pipeline re-runnable end-to-end; idempotent (deterministic `_key`s, `onDuplicate` handling); single command per stage | **Done** — `scripts/rebuild_all.sh` |
| G5 | Query-performance baseline | A benchmark suite of representative graph queries with recorded latencies (see §6) | **Done** — suite ([scripts/benchmark.py](../scripts/benchmark.py)) run across all three distributions; deterministic scanned-edge + explain-locality metrics recorded ([benchmark-report.md](benchmark-report.md)) |
| G6 | NL-query readiness | Source-text chunks joinable from every edge; **Cypher→AQL / NL→Cypher via `arango-cypher-py`** (§4.6) + GraphRAG grounding | **Done (FinReflectKG-side)** — NL→Cypher **front-end** run ([scripts/nl2cypher_eval.py](../scripts/nl2cypher_eval.py)): **19/22 transpile, 9/22 execute, 0 `MAPPING_NOT_FOUND`** (vocabulary gap closed); hand-written Cypher path 14/22 · 7/22 ([scripts/cypher_eval.py](../scripts/cypher_eval.py)); GraphRAG grounding 24/24 + **answer synthesis 5/5** ([scripts/graphrag.py](../scripts/graphrag.py), [scripts/graphrag_rubric.py](../scripts/graphrag_rubric.py)); gold-set AQL runner 21/22. Remaining ceiling is upstream (transpiler bugs, non-VCI AQL efficiency, analyzer cap) — see [nl-graphrag.md](nl-graphrag.md) |
| G7 | Multiple distributions for comparative scale benchmarking | Same dataset built as a **OneShard** db (`FinReflectKgOneShard`) and a **sharded SmartGraph** db (`FinReflectKgSmart`) alongside the baseline `FinReflectKG`; sharding verified (see §4.5) | **Done** — OneShard and SmartGraph both built & verified ([multi-distribution-plan.md](multi-distribution-plan.md)) |
| G8 | Graph analytics over the graph (GAE): centrality/PageRank, connected components (WCC/SCC), community detection — deterministic jobs + an agentic NL→insights layer | Reproducible GAE jobs on `Node`/`relations` with recorded results (non-mutating result collections), plus an NL/requirements→insights flow (see §4.7) | **Partial** — deterministic base **implemented & verified** ([scripts/analytics.py](../scripts/analytics.py)): PageRank + WCC run end-to-end on all 3.1 M nodes via `agentic-graph-analytics` (self-managed ACP GAE); agentic NL→insights layer pending |

### Non-goals (this phase)

- Entity resolution / deduplication beyond what the dataset already provides
  (e.g. merging `united state` with `united states of america`).
- Embedding generation and vector search over `chunk_text` (natural phase 2;
  the model leaves room for it).
- A production-grade application UI.
- Benchmarking against Neo4j or other engines (model is kept Neo4j-comparable
  so this remains possible later).

## 3. Users & stakeholders

- **ArangoDB (Arthur Keen)** — builds and runs the ETL, designs the model and
  indexes, runs benchmarks.
- **OneShard performance testing** — the `FinReflectKgOneShard` build.
- **Community / cluster graph** — the sharded SmartGraph build (`FinReflectKgSmart`).
- **Domyn** — publisher of the FinReflectKG dataset (CC-BY-NC); credited as the data
  source.

## 4. Requirements

### 4.1 Data model (LPG, Neo4j terminology)

The schema defines **24 canonical entity types** and **~30 canonical
relationship types** (see [data_dictionary.md](data_dictionary.md)), but the
extraction pipeline emitted a long tail of non-canonical relationship strings —
**30,535 distinct values across the full dataset**, 96.6% of which occur fewer
than 100 times (measured; see [data-analysis.md](data-analysis.md) §2). Mapping node
types → document collections and relationship types → edge collections is
unworkable at that cardinality, so the model is a **labeled property graph**
with a single node collection and a single edge collection, mirroring Neo4j's
node/relationship vocabulary:

- **`Node`** (document collection) — one document per distinct
  `(name, type)` pair across entity and target columns.
  - `_key`: deterministic hash of `name|type` (raw names contain `/`, spaces,
    and other characters illegal in ArangoDB keys; 91% of sampled rows have at
    least one such character).
  - `name` (string, normalized as in the dataset), `type` (e.g. `ORG`,
    `FIN_METRIC`, `GPE`).
- **`relations`** (edge collection) — one edge per source row (triple
  occurrence), preserving provenance and temporal bounds rather than
  collapsing duplicates.
  - `_key`: the dataset's `triplet_id` (key-safe, globally unique) → re-imports
    are idempotent.
  - `_from`, `_to`: refs into `Node`.
  - `type`: relationship name (e.g. `discloses`, `operates_in`).
  - `_fromType`, `_toType`: copies of the source/target node types, enabling
    vertex-centric indexes that prune traversals by edge type **and** the type
    of the node at the far end.
  - Temporal & provenance properties: `startDate`, `endDate` (parsed to
    sortable form where possible), `extractionType`, `ticker`, `year`,
    `sourceFile`, `pageId`, `chunkKey`.
- **`chunks`** (document collection) — deduplicated source-text chunks.
  - `_key`: deterministic hash of `(ticker, year, page_id, chunk_id)`.
  - `ticker`, `year`, `pageId`, `chunkId`, `text`.
  - Rationale: `chunk_text` averages ~2.9 KB and is repeated for every triple
    extracted from the same chunk (≈ 12× in sampling). Inlining it on edges
    would store ~50 GB of text; deduplicating stores ~4–5 GB and keeps edges
    small, which matters for traversal performance. Edges reference chunks via
    `chunkKey` (1-hop join when NL/GraphRAG needs source text).

### 4.2 Indexing

- VCI 1: persistent index on `relations(_from, type, _toType)`.
- VCI 2: persistent index on `relations(_to, type, _fromType)`.
- Persistent index on `Node(name)` (exact lookup by entity name; entry point
  for NL queries) and `Node(type)`.
- Optional (benchmark-driven): `relations(ticker, year)` for temporal/company
  slicing.
- **Label-rooted access path (added 2026-07-22, M5/G6):** persistent indexes
  `relations(type, _fromType, _toType)` (`vci_type_fromtype_totype`) and
  `relations(type, _toType, _fromType)` (`vci_type_totype_fromtype`). The two VCIs
  above are **node-anchored** (leading `_from`/`_to`), so **label-wide** aggregations
  ("all `:ORG` operating in > N `:GPE`" — no bound start node) engage no index and scan
  the full edge collection. These `type`-leading indexes prune such filters to the
  matching slice — e.g. `operates_in`/ORG/GPE = 313,407 of 17.5 M edges (1.79%): the
  direct-edge form's estimated cost drops **119,966,595 → 465** and it runs ~1.9 s vs.
  timing out at the 90 s cap. As with the VCIs, only **direct edge-collection queries**
  use them (pattern traversals do not — see the note below); the `arango-cypher-py`
  transpiler must emit direct-edge single-hop AQL to benefit (filed upstream —
  [nl-graphrag.md](nl-graphrag.md) §Pending, and
  `arango-cypher-py/docs/finreflectkg-aql-codegen-and-access-path-report.md`).
- Indexes are created **after** bulk load (faster than maintaining them during
  import).

> **Verified finding (load-report.md):** on the ArangoDB 3.12.x cluster, the VCIs
> are used by **direct edge-collection queries** —
> `FOR e IN relations FILTER e._from == @x AND e.type == … AND e._toType == …` —
> which narrow perfectly (e.g. the `net income` supernode scans only the 59,315
> matching edges). **Pattern traversals** (`FOR v,e IN 1..1 OUTBOUND … relations`)
> do **not** pick up the VCIs here; the optimizer uses the built-in `edge` index
> and applies `type`/`_fromType` as post-filters (an explicit `indexHint` with
> `forceIndexHint:true` did not change this). **Implication:** write 1-hop typed
> neighborhood queries as direct edge-collection queries; reserve pattern
> traversals for variable-depth pathfinding.

### 4.3 ETL

- **Download**: all 103 parquet shards (~1.7 GB) from Hugging Face.
- **Preprocess**: DuckDB-based transform to JSONL (`Node`, `relations`,
  `chunks`), including key hashing, type copying onto edges, and chunk
  dedup. No full-dataset in-memory load (the dataset is ~50 GB decompressed).
- **Import**: `arangoimport` from an `arangodb` CE Docker image (client tools
  only) against the remote endpoint, JSONL input, parallel threads.
  The Rust toolset (`~/code/arango-data-tools-rs`, `arangox`) was evaluated:
  its import library is complete but the CLI is not yet wired, and it lacks
  parquet support and collection/index creation, so `arangoimport` is the
  primary path for this POC. Revisit `arangox` once its CLI lands (this POC is
  a good first real workload for it).
- **Validate**: count reconciliation + spot-check traversals.

Full detail: [etl-plan.md](etl-plan.md).

### 4.4 Environment & constraints

- **Target**: remote ArangoDB **3.12.x Enterprise** cluster (3 Coordinators / 3
  DBServers / 3 Agents; `ARANGO_ENDPOINT` in `.env`). Enterprise is **required** —
  OneShard, SmartGraph, and SatelliteCollections (§4.5) are Enterprise features.
- **Databases** on the endpoint (one dataset, three distributions — see §4.5):
  - `FinReflectKG` — baseline, loaded & validated. (Note: this is a single-shard
    **flexible** db, *not* a true OneShard db, despite earlier informal labelling.)
  - `FinReflectKgOneShard` — OneShard db, built & verified.
  - `FinReflectKgSmart` — Disjoint SmartGraph db (Design 2), built & verified.
  - `arango_cypher_schema_cache` on the endpoint is **not unrelated** — it is the
    schema cache of **`arango-cypher-py`**, the Cypher→AQL / NL→Cypher engine this
    POC's query layer is required to use (see §4.6). The `aga_*` and `benchmark_*`
    collections are unrelated app tooling; the POC builds keep to their own
    databases and the named graph manifest to avoid those.
- **Secrets** stay in `.env` (gitignored); never in code or docs.
- **License**: dataset is **CC-BY-NC-4.0** (non-commercial). Fine for this
  research/POC use; flag to both parties before any commercial repurposing.
- Local workstation: macOS, Docker available; Python venv at `.venv` with
  DuckDB for preprocessing. All 103 source parquet shards + the staging JSONL are
  cached locally, so rebuilds import one-way without re-downloading.

### 4.5 Multi-distribution builds (G7)

Performance-testing requirements changed: the same dataset must exist under
multiple distributions so OneShard, single-server, and cluster-scale SmartGraph
behaviour can be benchmarked head-to-head. The data model (§4.1) and indexes
(§4.2) are identical across all three; only **placement** differs. The pipeline
scripts are parameterized (per-build `ARANGO_DB`/sharding/graph via env) so one
canonical pipeline drives all three. Full design: [multi-distribution-plan.md](multi-distribution-plan.md).

| DB | Distribution | Owner / use | Status |
|---|---|---|---|
| `FinReflectKG` | flexible db, 1 shard/collection (not OneShard) | baseline / NL-query work | loaded |
| `FinReflectKgOneShard` | **OneShard** db (`sharding: "single"`, all collections `distributeShardsLike` `_graphs`, co-located on one DBServer) | OneShard performance testing | **built & verified** (`scripts/build_oneshard.sh`) |
| `FinReflectKgSmart` | **Disjoint SmartGraph** (smart key `ticker`; shared concepts duplicated per company; `chunks` smart-sharded by `ticker` for text co-location) | text-to-graph / cluster graph | **built & verified** (`scripts/build_smart.sh`; 6.66 M nodes / 17.51 M edges, shard-local traversals confirmed) |

**Constraints & decisions:**
- OneShard's `sharding: "single"` can only be set at **database creation**, so each
  distribution is a separate database (cannot be toggled in place).
- The 17.5 M-edge graph is a near-perfect SmartGraph candidate: **0.00% cross-company
  references** (a disjoint union of 743 per-company subgraphs), so the smart key is
  `ticker`. The shared concept layer (17% of nodes; 27.7% concept→concept edges that
  break the naive smart+satellite design) is handled by **Design 2 (locked 2026-06-29):
  duplicate shared concepts per company** — keeps the single `relations` model + VCI
  fast path, naturally decomposes supernodes, ~2.1× nodes (edges not duplicated).
  The requirement is simply a SmartGraph (the text-to-graph tooling needs one) with
  **text co-located with related entities**, so `chunks` is **smart-sharded by `ticker`**
  too (a company's source text lands on its subgraph's shard). Satellites (Design B)
  were considered and rejected — not needed and they'd fragment `relations`. See
  [multi-distribution-plan.md](multi-distribution-plan.md) §5 (incl. §5.7 monitoring).
- OneShard collections inherit `replicationFactor=2` from the `_graphs` leader (vs.
  the baseline's RF1) — immaterial to read-traversal benchmarks, relevant to write/HA.

### 4.6 NL / Cypher query layer (G6, M5)

The natural-language and Cypher query layer **must use
[`arango-cypher-py`](https://github.com/arango-solutions/arango-cypher-py)** — the
arango-solutions Python-native **Cypher→AQL transpiler** (with an `nl2cypher`
module and a schema cache/acquisition layer) — rather than a bespoke NL→AQL
translator. FinReflectKG is a **real workload** for that library (analogous to the
`arangox` framing in §4.3), and the two projects share this cluster: the
`arango_cypher_schema_cache` collection (§4.4) is `arango-cypher-py`'s own schema
cache.

- **Pipeline:** NL →(`arango_cypher.nl2cypher`)→ Cypher →(`arango_cypher.translate`,
  with a `MappingBundle` acquired from the target db)→ AQL → execute. The public API
  is `arango_cypher.translate(cypher, mapping=…) -> TranspiledQuery(aql, bind_vars, …)`
  and `arango_cypher.execute(cypher, db=…, mapping=…)`.
- **Gold set:** the 22 curated NL/**Cypher**/AQL triplets in
  [cypher-queries.md](cypher-queries.md) are the evaluation corpus — the Cypher
  column is transpiled by `arango-cypher-py` and the output compared to (and executed
  alongside) the reference AQL.
- **Scope note:** the bespoke `scripts/nl2aql.py` from the first M5 pass is
  **superseded** by an `arango-cypher-py` integration; the GraphRAG retrieval +
  chunk-grounding pipeline (`scripts/graphrag.py`) remains valid and orthogonal.
- Details & status: [nl-graphrag.md](nl-graphrag.md).

### 4.7 Graph analytics (GAE) — G8, deferred phase 2

Run graph algorithms (PageRank / centrality, WCC / SCC, community detection /
label propagation) over the graph via the ArangoDB **Graph Analytics Engine (GAE)**,
and expose an **agentic NL→insights** layer on top. Two layers, mirroring the query
side (transpiler + NL front-end):

- **Base (deterministic):** GAE jobs on `vertex_collections=["Node"]`,
  `edge_collections=["relations"]` — deploy → load → analyze → store → cleanup — with
  results written to **separate `gae_<algorithm>` collections** (never mutating `Node`)
  and recorded like the benchmark harness. The `create_graph.py` named graph was
  deliberately built to be GAE-targetable.
- **Top (agentic):** a requirements/NL → use-cases → algorithm-selection → execution →
  intelligence-report flow (LLM-driven), reusing the configured provider keys.

**Deployment finding (2026-07-29):** the cluster is an **ArangoDB Platform (ACP)**
deployment. A **self-managed** GAE engine deploys and deletes cleanly
(`/gen-ai/v1/graphanalytics`), so **GAE is available**. The per-engine compute route
(`/gral/<id>/v1/loaddata`) becomes live only ~30–60 s after deploy while the GRAL
ingress rolls out.

**Tooling decision:** integrate via **`agentic-graph-analytics`** — the repo/tool
(pip distribution `graph-analytics-ai`; import package `graph_analytics_ai`) — whose GAE
client is ACP-ready (readiness polling + retry on the transient `unknown path '/gral/..'`
signature) and which provides **both** the deterministic orchestrator
(`graph_analytics_ai/ai/workflow/orchestrator.py`) and the agentic layer
(`graph_analytics_ai/ai/agents/`), so the one tool covers both layers. The standalone **`graph-analytics-orchestrator`**
was evaluated and rejected for this cluster: it retries a failed load only ~3×/~12 s by
re-deploying (never waiting for ingress), so it 404s on ACP. Connection is self-managed
(reuses the `.env` ArangoDB endpoint + JWT; `GAE_DEPLOYMENT_MODE=self_managed`,
`ARANGO_DATABASE`), no extra credentials.

**Status (base — verified 2026-07-29):** the deterministic base is **implemented** in
[scripts/analytics.py](../scripts/analytics.py) (`import graph_analytics_ai`, runs under
`.venv311`) and **verified end-to-end** on the self-managed ACP GAE:

- **PageRank** — 114.8 s (deploy 69.8 s + load 14 s + compute 3.3 s + store/verify),
  3,099,773 result docs in `gae_pagerank` (field `rank`), ≈$0.013. Top-ranked nodes are
  the central financial concepts: `net income`, `revenue`, `net sale`, `operate income`,
  `fair value`, `gross margin`, … plus `new york stock exchange` (FIN_MARKET),
  `united state` (GPE) — `net income` (the biggest supernode) ranks #1.
- **WCC** — 91.5 s, 3,099,773 docs in `gae_wcc` (field `component`): **3,322 components**,
  one giant component of **3,091,396 nodes (99.7%)** with a small-component tail — the
  graph is essentially one connected structure.

Results are written to non-mutating `gae_<algorithm>` collections; raw summaries in
`data/analytics_<algorithm>_<db>.json`. The GRAL ingress-readiness 404 that blocked the
standalone orchestrator is handled here (readiness poll + transient-404 retry).

**Pending:** the **agentic NL→insights** layer (requirements → use-cases → algorithm
selection → execution → report) via the same package's agentic mode
(`graph_analytics_ai/ai/agents/`, `run_agentic_workflow`), and running the base across the
OneShard/Smart distributions.

## 5. Sizing (from data analysis)

See [data-analysis.md](data-analysis.md) for measured numbers, [load-report.md](load-report.md)
for the as-loaded counts. Headline figures: **17,513,372 edges**, **3,099,773 nodes**
(distinct name+type pairs), **1,384,513 chunks loaded** (of 1,403,652 distinct chunk
keys — rows with `has_context = false` carry no chunk); raw parquet 1.67 GB;
ArangoDB footprint dominated by the `relations` collection and its two VCIs
plus ~4 GB of deduplicated chunk text. The SmartGraph "Design 2" build (§4.5) grew
nodes to **6,658,668** (2.1×) via per-company concept duplication.

## 6. Benchmark sketch (G5)

Representative query classes to time once loaded (exact suite to be agreed
later). Per §4.2, typed 1-hop classes are expressed as **direct
edge-collection queries** (the access path that engages the VCIs), not pattern
traversals:

1. **Point lookup**: node by `name`.
2. **1-hop typed (direct edge query)**: all `operates_in` edges from a company
   node → GPE nodes (engages VCI 1, `vci_from_type_totype`).
3. **Reverse typed (direct edge query)**: who `has_stake_in` a given target
   (engages VCI 2, `vci_to_type_fromtype`).
4. **Supernode handling**: high-degree metric nodes (e.g. `net income`, in-degree
   ~10⁵) — direct edge query scans only matching edges (59,315 for `net income`)
   vs. an unpruned pattern traversal scanning all ~10⁵; the core demonstration of
   why the VCI access path matters here.
5. **k-hop path**: company → supplier/competitor chains, depth 2–3 (pattern
   traversal; edge-index + filter cost accepted).
6. **Temporal slice**: edges for a ticker filtered by `year` range.
7. **NL-grounding join**: edge → `chunks` text retrieval latency.

**Cross-distribution comparison (G7):** run the suite against `FinReflectKG`
(flexible 1-shard), `FinReflectKgOneShard` (OneShard), and `FinReflectKgSmart`
(SmartGraph) to quantify the effect of placement — especially OneShard eliminating
the cross-DBServer `RemoteNode` hops seen on the baseline's multi-hop traversals.
Note: latency on the shared remote cluster is noisy (a single query has ranged
203 ms–20 s across runs), so use **scanned-edge counts** and **shard-locality from
`explain`** as the deterministic metrics; reserve wall-clock for a quiescent window.

## 7. Milestones

| M | Deliverable | Notes | Status |
|---|-------------|-------|--------|
| M1 | PRD + data analysis + ETL plan reviewed | this document set | Done |
| M2 | Download + preprocess pipeline producing JSONL | local, repeatable | Done |
| M3 | Bulk load into remote ArangoDB + indexes + reconciliation report | G1–G4 | **Done** ([load-report.md](load-report.md)) |
| M4 | Benchmark suite + results | G5 (+ G7 cross-distribution) | **Done** — cross-distribution suite + results ([benchmark-report.md](benchmark-report.md)); SmartGraph decomposes the `net income` supernode ~250× on per-company queries; latency indicative on the shared cluster |
| M5 | NL-query evaluation (Cypher→AQL / NL→Cypher via `arango-cypher-py` + GraphRAG) | G6, §4.6 | **Done (FinReflectKG-side)** — schema-aware **NL→Cypher front-end** run ([scripts/nl2cypher_eval.py](../scripts/nl2cypher_eval.py)): **19/22 transpile · 9/22 execute · 0 `MAPPING_NOT_FOUND`** (vs 14/22 · 7/22 for hand-written Cypher, [scripts/cypher_eval.py](../scripts/cypher_eval.py)). **GraphRAG answer synthesis 5/5** ([scripts/graphrag_rubric.py](../scripts/graphrag_rubric.py)). Root-caused the gold-set vocabulary mismatch against live data (sibling-schema rename `:RISK`→`RISK_FACTOR`; `ORG_REG` real but capped out of the top-20 ontology; `:METADATA` absent). Remaining upstream: transpiler ERR 1511 (multi-`WITH`), non-VCI AQL efficiency, analyzer entity cap, `reduce()` ([nl-graphrag.md](nl-graphrag.md)) |
| M6 | Multi-distribution builds (OneShard + SmartGraph) | G7 | **Done** — OneShard and SmartGraph both built & verified ([multi-distribution-plan.md](multi-distribution-plan.md)) |
| M7 | Graph analytics via GAE (deterministic jobs + agentic NL→insights) | G8, §4.7 | **Partial** — deterministic base done & verified (PageRank + WCC end-to-end on 3.1 M nodes via `agentic-graph-analytics`, [scripts/analytics.py](../scripts/analytics.py)); agentic NL→insights layer pending |

## 8. Risks & open questions

| Risk / question | Mitigation / decision needed |
|---|---|
| Supernodes (generic `FIN_METRIC` targets like `net income` accumulate in-degree across all companies/years) | **Direct edge-collection queries** prune by `type`+`_toType`/`_fromType` via the VCIs (verified: `net income` scans 59,315 not ~10⁵); benchmark explicitly (§6.4). The SmartGraph "Design 2" build (§4.5) scopes concept copies per ticker, the phase-2 option now in flight |
| **SmartGraph shared-concept modeling** — split concept identity under Design 2 | **Resolved: Design 2** (locked 2026-06-29). Accepted cost = global cross-company concept queries aggregate `BY name`; monitored per [multi-distribution-plan.md](multi-distribution-plan.md) §5.7 — fall back to Design B only if global-concept rollups dominate the workload |
| VCIs do **not** accelerate pattern traversals on 3.12.x cluster (only direct edge queries) | Write typed 1-hop queries as direct edge-collection queries (§4.2); reserve traversals for variable-depth paths |
| Benchmark latency noisy on shared remote cluster (203 ms–20 s for one query) | Use scanned-edge counts + `explain` shard-locality as deterministic metrics; wall-clock only in a quiescent window |
| Same name with multiple types (~14% of names, measured) becomes multiple nodes | Accepted: node identity = `(name, type)`; consistent with edges carrying `_fromType`/`_toType` |
| One edge per occurrence (17.51 M) vs deduplicated facts (8.49 M distinct e/r/t, measured) | Keep per-occurrence edges (provenance + temporal value is the dataset's point); a deduplicated "fact" layer can be derived later if benchmarks need it |
| Remote import throughput (TLS, WAN) | Batch + parallel `arangoimport`; measure on a 1-shard pilot before full run |
| `start_date`/`end_date` are strings (`"January 2014"`, `default_end_timestamp`) | Parse to ISO `yyyy-mm` during preprocessing; keep raw value in a sibling field |
| Dataset license is NC | POC/research use only; revisit before productization |

# PRD — FinReflectKG on ArangoDB (Proof of Concept)

**Status:** Draft v0.3 · 2026-07-05 (all three distributions built & verified)
**Authors:** Arthur Keen (ArangoDB)
**Related docs:** [data-analysis.md](data-analysis.md) · [etl-plan.md](etl-plan.md) ·
[load-report.md](load-report.md) · [sharding-analysis.md](sharding-analysis.md) ·
[multi-distribution-plan.md](multi-distribution-plan.md) ·
[schema-mapping.md](schema-mapping.md) · [cypher-queries.md](cypher-queries.md) ·
[data_dictionary.md](data_dictionary.md) · paper: [research/2508.17906v2.pdf](research/2508.17906v2.pdf)

## 0. Changelog

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
| G5 | Query-performance baseline | A benchmark suite of representative graph queries with recorded latencies (see §6) | Pending (M4) |
| G6 | NL-query readiness | Source-text chunks stored and joinable from every edge, enabling GraphRAG / NL→AQL evaluation | In progress — chunks loaded; NL→AQL/Cypher work underway ([cypher-queries.md](cypher-queries.md)) |
| G7 | Multiple distributions for comparative scale benchmarking | Same dataset built as a **OneShard** db (`FinReflectKgOneShard`) and a **sharded SmartGraph** db (`FinReflectKgSmart`) alongside the baseline `FinReflectKG`; sharding verified (see §4.5) | **Done** — OneShard and SmartGraph both built & verified ([multi-distribution-plan.md](multi-distribution-plan.md)) |

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
  - The endpoint also hosts unrelated app collections (`aga_*`, `benchmark_*`,
    `arango_cypher_schema_cache`) added by other tooling; the POC builds keep to
    their own databases and the named graph manifest to avoid them.
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
| M4 | Benchmark suite + results | G5 (+ G7 cross-distribution) | Pending |
| M5 | NL-query evaluation (NL→AQL and/or GraphRAG) | G6; scoped later | In progress ([cypher-queries.md](cypher-queries.md)) |
| M6 | Multi-distribution builds (OneShard + SmartGraph) | G7 | **Done** — OneShard and SmartGraph both built & verified ([multi-distribution-plan.md](multi-distribution-plan.md)) |

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

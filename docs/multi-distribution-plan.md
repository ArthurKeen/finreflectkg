# Multi-Distribution Plan — OneShard + SmartGraph builds of FinReflectKG

**Status:** v0.3 · 2026-07-05 · **All three distributions built & verified —
baseline, OneShard, and SmartGraph (`FinReflectKgSmart`, Design 2) loaded and
validated (shard-local per-company traversals confirmed).**
**Author:** Arthur Keen (ArangoDB).
**Related:** [sharding-analysis.md](sharding-analysis.md) · [etl-plan.md](etl-plan.md) ·
[load-report.md](load-report.md) · [data-analysis.md](data-analysis.md) ·
[schema-mapping.md](schema-mapping.md)

## 0. What we're building and why

Performance-testing requirements changed. We now need **three** coexisting graphs,
each with a different distribution, so OneShard, single-server, and cluster-scale
SmartGraph behaviour can be benchmarked head-to-head on the same source data:

| DB | Distribution | Owner / use | Status |
|---|---|---|---|
| `FinReflectKG` (existing) | flexible db, 1 shard/collection, **not** OneShard | current POC / NL-query work | loaded, keep as-is |
| **`FinReflectKgOneShard`** | **OneShard database** (`sharding: "single"`) | OneShard performance testing | **built & verified** (`scripts/build_oneshard.sh`) |
| **`FinReflectKgSmart`** | **Disjoint SmartGraph** (Design 2: smart key `ticker`, shared concepts duplicated per company, `chunks` smart-sharded by `ticker`) | community / cluster graph | **built & verified** (`scripts/build_smart.sh`) |

### Recap of the deferred decision (yes, this is the same one)

From `sharding-analysis.md`: we originally intended a SmartGraph, discovered a lot
of shared structure, considered putting the shared part in satellite graphs, found
that **27.7% of edges are concept→concept** (which breaks the naive hybrid
smart+satellite design — satellite→satellite edges are rejected by ArangoDB), and
**chose to stay on the single-shard load and revisit distribution later.** This plan
is that revisit. One correction worth stating up front:

> The existing `FinReflectKG` was described as "OneShard," but we verified live that
> its database `sharding` property is **empty (flexible)**, not `"single"`, and its
> collections have `distributeShardsLike: null`. It is a **single-shard flexible**
> database, not a true OneShard database. `FinReflectKgOneShard` will be the first
> *real* OneShard build.

## 1. Shared facts (verified live 2026-06-24)

- **Source data is fully local:** all 103 parquet shards in `data/raw/data/`
  (`train-*.parquet`), 17,513,372 rows. The existing DuckDB preprocessing
  (`scripts/preprocess.py`) reproduces the whole load in ~14 s.
- **Our collections in `FinReflectKG`** (named graph `FinReflectKG`):
  `Node` (3,099,773 docs), `relations` (17,513,372 edges). `chunks` (1,384,513) is
  ours too but deliberately kept out of the graph (supporting source text).
- **Not ours — do not touch / do not copy:** `aga_*` (Agentic AI Suite app),
  `arango_cypher_schema_cache`, `benchmark_*`, `benchmark_aqlizer_queries_*`. These
  were added by other people's apps in the same database. Both new builds will be
  **separate databases** containing only `Node` / `relations` (+ `chunks`), so we
  inherit none of that.
- **Deployment:** ArangoDB 3.12.x **Enterprise** cluster — 3 Coordinators / 3
  DBServers / 3 Agents (Enterprise is required for OneShard, SmartGraph, and
  SatelliteCollections).
- **Schema (both builds keep the LPG model):** one node collection, one logical edge
  set, relationship semantics in `relations.type`, `_fromType`/`_toType` copied onto
  edges, `ticker`/`year` on every edge, VCIs on `(_from,type,_toType)` and
  `(_to,type,_fromType)`. See `data-analysis.md`.

## 2. Source-of-truth decision for each ETL

Two possible entry points per build:

- **(P) Re-run the parquet pipeline** (DuckDB → JSONL → `arangoimport`) into the new
  DB. Required when keys/structure change.
- **(D) Dump/restore from the live `FinReflectKG`** (`arangodump` the 3 collections,
  `arangorestore` into the new DB). Faster when the data is byte-identical and only
  *placement* changes.

| Build | Entry point | Why |
|---|---|---|
| `FinReflectKgOneShard` | **(D) dump/restore**, fallback (P) | Data is identical to `FinReflectKG`; only DB-level sharding changes. Dump/restore is the fastest path and avoids re-deriving keys. |
| `FinReflectKgSmart` | **(P) re-run pipeline** (new preprocessing) | Smart distribution changes the **key scheme** and (depending on the chosen design) splits collections, so it must be re-derived from source. |

> Note: arangodump/arangorestore are not currently in the repo scripts; §4 adds a
> thin wrapper. The pipeline scripts already exist but hardcode DB/graph names — §3
> parameterizes them.

## 3. Common prerequisite — parameterize the pipeline

Today `scripts/*.py` read `ARANGO_DB` from `.env` and hardcode `GRAPH="FinReflectKG"`,
and `setup_db.py` can't pass database creation options. Minimal, backward-compatible
changes (no behaviour change for the existing build):

1. **`scripts/arango.py`** — allow per-invocation DB override via env var
   `ARANGO_DB` (already supported) and add an optional `create_database(name, options)`
   helper that POSTs `{"name": name, "options": {...}}`.
2. **`setup_db.py`** — read target DB + an optional `ARANGO_DB_SHARDING` (e.g.
   `single`) and pass it as `options.sharding`. Accept per-collection shard options.
3. **`create_indexes.py`, `create_graph.py`, `validate.py`** — take the graph name
   and collection list from constants at the top (already mostly true), parameterized
   by env so a OneShard/Smart run targets the right names.
4. New thin orchestrators: `scripts/build_oneshard.sh`, `scripts/build_smart.sh`
   (mirroring `rebuild_all.sh` but with the per-build settings).

This keeps one canonical pipeline with three configurations rather than three
forks.

---

## 4. Database A — `FinReflectKgOneShard` (OneShard)

### 4.1 What OneShard actually means (and the one hard constraint)

A **OneShard database** is created with `options.sharding = "single"`. Every
collection in it is then forced to a single shard and `distributeShardsLike` a common
leader, so **all data lives on one DBServer** and the query optimizer can run whole
queries (incl. multi-hop traversals and joins) locally with no inter-DBServer hops —
while still getting cluster failover/replication.

**Hard constraint:** the `sharding: "single"` property is set **only at database
creation** and cannot be toggled on an existing database. So this must be a *new*
database (which is exactly what we want) — we cannot convert `FinReflectKG` in place.

### 4.2 Build steps

1. **Create the database as OneShard:**
   ```http
   POST /_api/database
   { "name": "FinReflectKgOneShard",
     "options": { "sharding": "single", "replicationFactor": 2, "writeConcern": 1 } }
   ```
   (`replicationFactor: 2` gives one follower for failover; set to your cluster's
   policy. In a OneShard DB all collections inherit this automatically.)
2. **Populate** — preferred path (D):
   ```bash
   arangodump   --server.database FinReflectKG \
     --collection Node --collection relations --collection chunks --dump-data true
   arangorestore --server.database FinReflectKgOneShard \
     --import-data true            # do NOT pass --number-of-shards; OneShard forces 1
   ```
   Restore creates `Node`/`relations`/`chunks` as single-shard, `distributeShardsLike`
   the leader — i.e. true OneShard placement. Fallback path (P): run the existing
   `preprocess → setup_db (ARANGO_DB=FinReflectKgOneShard) → import_full → ...`.
3. **Indexes:** reuse `create_indexes.py` unchanged (same 5 indexes: 2 VCIs +
   `node_name` + `node_type` + `rel_ticker_year`).
4. **Named graph:** reuse `create_graph.py` (General graph, edgeDefinition
   `relations: Node→Node`). In a OneShard DB a General graph is fine and fully local.
5. **Validate:** reuse `validate.py` (counts reconcile to 3,099,773 / 17,513,372 /
   1,384,513) **plus** a OneShard placement assertion:
   - `GET /_api/database/current` → `sharding == "single"`.
   - each collection: `numberOfShards == 1` and `distributeShardsLike` set.
   - `GET /_api/cluster/shardDistribution` → all shards on the **same** DBServer.

### 4.3 Sharding strategy (summary)

Trivial by construction: **no shard-key choice to make.** OneShard co-locates
everything; the only knobs are `replicationFactor`/`writeConcern`. Expected win vs.
current `FinReflectKG`: eliminates the `RemoteNode` cross-server hops we saw on
17.5 M-edge traversals (the source of the cluster error and the 8 s query in
`cypher-queries.md`).

### 4.4 Effort

Low — ~1–2 h wall-clock (dominated by dump/restore of 17.5 M edges + index rebuild),
mostly reused scripts. No modeling decisions.

---

## 5. Database B — `FinReflectKgSmart` (Disjoint SmartGraph by `ticker`)

**Decision locked (2026-06-29): Design 2** — Disjoint SmartGraph sharded by `ticker`,
shared concepts duplicated per company, `chunks` smart-sharded by `ticker` for text
co-location. Rationale in §5.3; the analysis and the rejected alternative (Design B)
are kept below for the record.

### 5.1 The research question: random distribution vs. a smart key?

**Answer: a smart key, and the key is `ticker` (the filing company).** Random
(hash-by-`_key`) distribution scatters every company's subgraph across all DBServers,
so every traversal becomes a scatter-gather — the worst case for this workload. The
data makes the smart key obvious (all figures measured over the full dataset,
`sharding-analysis.md`):

| Signal | Value | Implication |
|---|---|---|
| **Cross-company references** | **0.00%** | the graph is a *disjoint union of 743 per-company subgraphs* — a near-perfect SmartGraph candidate |
| Edges owned by the filer ORG (`entity` is the filer) | 87.2% | the filing `ticker` is the natural owner of an edge |
| Nodes that are single-ticker | 83% | most nodes belong to exactly one company |
| Nodes that are shared across companies | 17% | the "shared parts" — concepts/metrics |
| Edge endpoint classes | company→company 16.0%, company→concept 46.5%, concept→company 9.9%, **concept→concept 27.7%** | the 27.7% is the problem child for satellites |

So: **shard by `ticker`** (a Disjoint SmartGraph) → each company's subgraph lands on
one shard, company-scoped traversals and the heavy disclosure expansions stay local.
The only thing that doesn't fit cleanly is the **shared concept layer** (17% of nodes,
and especially the 27.7% concept→concept edges).

### 5.2 The research question: satellites for the shared parts?

This is where "SmartGraph **with satellites for shared parts**" hits ArangoDB's rules.
A smart edge collection shards each edge by a smart endpoint value; an edge with
**both** endpoints on satellites (no smart value) **cannot be placed and is rejected**
(we verified this live previously: *"Collection 'CptNode' … is required to be a smart
collection. But would be created as satellites."*). With shared concepts as satellites,
the **27.7% concept→concept edges are exactly those rejected edges.**

There are two real ways to honor "satellites for shared parts." Both are viable;
they trade concept duplication against collection fragmentation:

#### Design 2 — Disjoint SmartGraph, **duplicate** shared concepts per company (no satellites)

- Smart attribute = `ticker`; node `_key = "<ticker>:<md5(name|type)>"`.
- Shared concepts are **duplicated into every referencing company's shard**, so every
  node has an owning ticker and **every edge is intra-shard** (incl. the former
  concept→concept edges). Fully disjoint, maximal locality.
- **Cost:** node count grows to **~6.66 M (2.1×)**; global "this concept across all
  companies" queries must aggregate the ~743 copies **by `name`** (cheap with the
  `name` index). Single `Node` + single `relations` collection preserved → the
  existing direct-edge-query VCI access path is unchanged.
- Strictly this uses **no SatelliteCollections** — it answers "shared parts" by
  replication-via-duplication instead.

#### Design B — Hybrid SmartGraph: shared concepts as a **SatelliteCollection**, split edges

- `Node` = smart vertex collection (the 83% company-owned nodes, sharded by `ticker`).
- `SharedNode` = **SatelliteCollection** (the 17% shared concepts, replicated to every
  DBServer — single global identity, read-local everywhere).
- `relations` = smart edge collection for edges with **≥1 company endpoint**
  (company→company, company→concept, concept→company = **72.4%** of edges), sharded by
  the company endpoint.
- `relations_shared` = **satellite edge collection** for the **27.7% concept→concept**
  edges (replicated everywhere).
- **Pros:** no concept duplication; global concept identity preserved; concept reads
  are local on every DBServer.
- **Cost:** the single `relations` model **fragments into two edge collections.** The
  fast path on this deployment is *direct edge-collection queries* (per `load-report.md`,
  pattern traversals don't use our VCIs) — so any "all edges of node X" direct query
  must now union `relations` + `relations_shared`, and each needs its own VCIs.
  Named-graph *traversals* span both transparently; hand-written direct edge AQL does
  not. ~4.85 M concept→concept edges are replicated to every DBServer.

### 5.3 Decision — Design 2 (locked 2026-06-29)

**Chosen: Design 2 — Disjoint SmartGraph sharded by `ticker`, shared concepts
duplicated per company.**

Clarified requirement (2026-06-29): the downstream consumer needs a SmartGraph because
its **text-to-graph technology requires one**, and the goal is simply to **co-locate the
text-to-graph elements with the entities they relate to**. There is *no* requirement
to use SatelliteCollections specifically, and *no* stated need for global
single-identity concept analytics — so the "satellites for shared parts" phrasing was
a means, not an end. Design 2 satisfies the real requirement and is the better
engineering choice:

- It **is** a SmartGraph (satisfies the text-to-graph tooling requirement).
- It gives the **strongest per-company co-location**: a company's nodes, edges, **and
  its source-text `chunks`** all land on the same shard (see §5.4 step 7) — exactly
  "co-locate the text with what it's related to."
- It preserves the single-`relations` model and therefore the **VCI direct-edge-query
  fast path** that `load-report.md` identified (Design B would fragment it).
- It naturally **decomposes the supernodes** (e.g. `net income` becomes ~743 small,
  shard-local nodes instead of one in-degree-~10⁵ hot node).
- Disjointness is real (0% cross-company refs), so duplication (2.1× nodes, edges not
  duplicated) is the only cost and it's bounded and cheap (nodes ~100 B).

**Accepted trade-off:** concept identity is split across companies, so global
cross-company concept queries ("every company that discloses `net income`") must
`COLLECT ... BY name` (cheap with the `node_name` index). See monitoring (§5.7).

### 5.4 ETL for Design 2 (the recommended build)

New preprocessing (a `--smart` mode on `preprocess.py`, or a sibling
`preprocess_smart.py`), all in DuckDB over the local parquet:

1. **Compute each node's owning ticker(s).** For every distinct `(name,type)`, collect
   the set of tickers whose rows reference it (as `entity` or `target`).
   - single-ticker node → emit one copy with that ticker.
   - multi-ticker (shared) node → emit **one copy per referencing ticker**.
   - `_key = "<ticker>:<md5(name|type)>"`, plus fields `name`, `type`, `ticker`.
2. **Rewrite edges to point at per-ticker copies.** Each row already has `ticker`
   (the filer); set `_from = "Node/<ticker>:<md5(entity|entity_type)>"`,
   `_to = "Node/<ticker>:<md5(target|target_type)>"` using the **edge's own ticker**
   for both endpoints (safe because cross-company refs are 0%). `_key` stays
   `"<ticker>:<triplet_id>"` (smart edges must encode the smart value).
   Keep all existing edge fields (`type`, `_fromType`, `_toType`, dates, `ticker`,
   `year`, `chunkKey`, …).
3. **Create the database as a normal sharded (flexible) DB:**
   ```http
   POST /_api/database
   { "name": "FinReflectKgSmart", "options": { "replicationFactor": 2 } }
   ```
   (NOT `sharding:"single"` — this build is a genuinely sharded cluster graph.)
4. **Create the Disjoint SmartGraph** (this also creates the smart collections with
   the right sharding — do this *before* import):
   ```http
   POST /_api/gharial
   { "name": "FinReflectKgSmart",
     "edgeDefinitions": [ { "collection": "relations", "from": ["Node"], "to": ["Node"] } ],
     "orphanCollections": [],
     "options": { "smartGraphAttribute": "ticker", "isDisjoint": true,
                  "numberOfShards": 9, "replicationFactor": 2 } }
   ```
   (`numberOfShards`: pick to spread 743 tickers across 3 DBServers — 9 is a
   reasonable start; tune in benchmarking.)
5. **Import** `nodes_smart.jsonl` + `relations_smart/*.json` with `arangoimport`
   (reuse `import.sh`/`import_full.sh` pointed at the new DB + files).
6. **Indexes:** same VCIs + lookups (`create_indexes.py`, unchanged field lists).
7. **`chunks` — smart-shard by `ticker` for text co-location (the core need).**
   Each chunk belongs to exactly one ticker (its key already derives from
   `ticker|year|page|chunk`), so shard `chunks` by `ticker` too:
   - `_key = "<ticker>:<md5(ticker|year|page_id|chunk_id)>"`, carry a `ticker` field;
   - rewrite edges' `chunkKey` to the new prefixed key so the join still resolves;
   - create `chunks` aligned to the smart distribution — as a **smart orphan
     collection** in the graph (`smartGraphAttribute: "ticker"`), or equivalently with
     `distributeShardsLike` the smart `Node` — so a company's chunks co-locate on the
     **same shard** as the nodes/edges extracted from them.
   This is preferred over a SatelliteCollection here: satellites *replicate* text to
   every DBServer (1.38 M × ~2.9 KB × N), whereas smart-sharding *co-locates* it with
   the related subgraph, which is exactly the text-to-graph requirement and avoids the
   replication blow-up.
8. **Validate:** counts (expect ~6.66 M nodes, 17.51 M edges, 1.38 M chunks),
   referential integrity (incl. `chunkKey` → `chunks` resolves under the new keys),
   `smartGraphAttribute`/`isDisjoint` on the graph, shard distribution across
   DBServers, and a per-company query (subgraph **and** its chunks) that stays on one
   shard (`explain` shows no/minimal `RemoteNode`).

### 5.7 Monitoring (the "make the best choice and monitor it" part)

Design 2's one accepted risk is split concept identity. Watch these after the build;
if they bite, the fallback is Design B (or a derived global-concept aggregate layer):

- **Duplication ratio:** confirm node count ≈ 6.66 M (2.1×) and that *edges did not
  duplicate* (17.51 M). A much higher ratio means the shared-node fan-out is worse
  than measured and storage/aggregation cost rises.
- **Shard balance:** 743 tickers over `numberOfShards` shards — check no single
  company/shard is a hotspot (the largest filers `etr`/`pru`/`met` have ~90 K
  out-edges). Re-tune `numberOfShards` if skewed.
- **Locality:** periodic `explain` on representative company-scoped queries — they
  should show **no `RemoteNode`**. A regression means something crossed shards.
- **Global-concept aggregation cost:** if the workload turns out to need frequent
  cross-company concept rollups, measure the `COLLECT BY name` cost; if it dominates,
  revisit Design B or materialize a concept-aggregate view.

### 5.5 ETL for Design B (only if chosen)

Same as 5.4 but: (1) classify nodes company-owned vs shared and emit shared ones to
`SharedNode` (satellite, single copy, **no** ticker prefix in key); (2) keep company
nodes single-copy in smart `Node`; (3) split edges by endpoint class into smart
`relations` (≥1 company endpoint, sharded by the company side) and satellite
`relations_shared` (concept→concept); (4) graph has **two** edge definitions; (5)
build VCIs on **both** edge collections. No node duplication.

### 5.6 Effort

Medium–high — the new preprocessing (ticker-ownership aggregation + key rewrite) is
the main new code (~½ day), plus a full re-import (~1.5 h) and validation. Design B
adds the node-classification + edge-split logic and doubles the index build.

---

## 6. Sequencing & risks

1. ~~Parameterize pipeline (§3)~~ — **done** (env-overlay + sharding options + import override).
2. ~~Build `FinReflectKgOneShard` (§4)~~ — **done & verified** (`scripts/build_oneshard.sh`).
3. ~~Decide Design 2 vs B (§5.3)~~ — **done: Design 2.** ~~Build `FinReflectKgSmart`~~ —
   **done & verified 2026-07-05** (`scripts/build_smart.sh`): 6,658,668 nodes /
   17,513,372 edges / 1,384,513 chunks; VCIs built; referential integrity clean;
   disjoint shard-locality confirmed (per-company traversal has no `RemoteNode`, source
   text co-located on the same shard).
4. Re-point/duplicate the Graph Visualizer install + benchmark suite per DB if the
   visual layer is wanted (optional stage 8).

**Risks / watch-items:**
- Cluster disk: Design 2 ≈ +3.5 M duplicated nodes; Design B replicates ~4.85 M
  satellite edges ×N DBServers. Confirm headroom before import.
- Smart-key keys are immutable — getting `_key = "<ticker>:..."` right in preprocessing
  is critical (a wrong prefix can't be fixed in place; it's a re-import).
- `arangoimport` into smart collections must send the smart attribute / pre-encoded
  keys; pilot one company (e.g. shard 0's 8 tickers) before the full run.
- Shared remote cluster latency is noisy (`load-report.md`); use scanned-edge counts +
  shard-locality from `explain` as deterministic metrics, not wall-clock alone.

## 7. Decisions

1. **Smart design:** ✅ **Design 2** (Disjoint SmartGraph by `ticker`, duplicate
   concepts, chunks smart-sharded by `ticker`). Locked 2026-06-29.
2. **OneShard `replicationFactor`/`writeConcern`:** built RF1-at-db / inherited RF2 at
   collections (follows `_graphs` leader) / writeConcern 1. Accepted.
3. **Smart `numberOfShards`** — proposed **9** (re-tune per §5.7 shard-balance
   monitoring); `replicationFactor` **2**. Default chosen unless otherwise specified.
4. **OneShard source:** built via re-import from local staging (one-way upload; faster
   than dump+restore over WAN given staging was present).
5. **Visualizer theme + benchmark suite per DB:** open — default to **data only** for
   `FinReflectKgSmart` unless the visual layer is wanted.

Remaining open item is just #5 (and #3's shard count if there's a preference);
neither blocks the build.

## Appendix — verification scripts added during planning

- `scripts/check_sharding.py` — reports DB `sharding` + per-collection shard topology
  (used to confirm `FinReflectKG` is single-shard-flexible, not OneShard).
- `scripts/inspect_source.py` — inventories which collections belong to the named
  graph vs. app-specific (`aga_*`, `benchmark_*`) collections to avoid.

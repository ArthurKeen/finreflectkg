# Load Report — FinReflectKG → ArangoDB

**Status:** v1.0 · 2026-06-15 · full dataset loaded & validated
**Related:** [PRD.md](PRD.md) · [etl-plan.md](etl-plan.md) · [data-analysis.md](data-analysis.md)

## Outcome

The complete dataset is loaded into the remote ArangoDB database `FinReflectKG`
and validated. **All counts reconcile exactly; zero import errors; zero
dangling edge endpoints.**

| Collection | Documents | Import time | Errors |
|---|---|---|---|
| `Node` | 3,099,773 | 175 s | 0 |
| `chunks` | 1,384,513 | 1,156 s | 0 |
| `relations` (edges) | 17,513,372 | ~63 min (16 split files) | 0 |

Preprocessing (all 103 parquet shards → JSONL): **14 s** with DuckDB.
Import throughput: **3,672 edges/s** at 16 threads / 16 MB batch.

## Indexes

All built post-load, fast:

| Collection | Index | Fields | Build time |
|---|---|---|---|
| `relations` | `vci_from_type_totype` | `_from, type, _toType` | 29.2 s |
| `relations` | `vci_to_type_fromtype` | `_to, type, _fromType` | 43.7 s |
| `Node` | `node_name` | `name` | 8.3 s |
| `Node` | `node_type` | `type` | 5.2 s |
| `relations` | `rel_ticker_year` | `ticker, year` | 10.0 s |

## Key finding: VCIs accelerate direct edge queries, not pattern traversals

This is the most important result for the benchmark phase, and it changes how
typed queries should be written.

- **Direct edge-collection queries use the VCIs with perfect narrowing.** For
  example:
  ```aql
  FOR e IN relations
    FILTER e._from == @company AND e.type == 'operates_in' AND e._toType == 'GPE'
    RETURN e._to
  ```
  uses `vci_from_type_totype`; the inbound form (`_to, type, _fromType`) uses
  `vci_to_type_fromtype`. Verified via `explain`. On the supernode case (`net
  income`, in-degree ~105 K), the direct query scans **only the 59,315 matching
  edges** (`filtered: 0`).

- **Pattern traversals (`FOR v,e IN 1..1 INBOUND/OUTBOUND … relations`) do NOT
  use these VCIs** on this deployment (ArangoDB 3.12.9 cluster). The optimizer
  uses the built-in `edge` index and applies the `type`/`_fromType` conditions
  as in-enumeration filters. On the same supernode case it scans **all 105,691
  inbound edges** and post-filters 39,981. An explicit `indexHint` with
  `forceIndexHint:true` did not change this.

**Implication for benchmarking (PRD §6):** express 1-hop typed neighborhood
queries as **direct edge-collection queries** to exploit the VCIs — this maps
exactly to the intended `(_from, type, _toType)` / `(_to, type, _fromType)`
access pattern. Reserve pattern traversals for variable-depth pathfinding,
where the edge-index + filter cost is acceptable. (Note: query *latency* on the
shared remote cluster is currently too noisy to benchmark — the same query
ranged 203 ms to 20 s across runs — so scanned-edge counts are used here as the
deterministic metric. Latency benchmarking needs a quiescent window.)

## Cluster topology — action needed before scale benchmarking

The target is a real cluster (**3 Coordinators, 3 DBServers, 3 Agents**), but
the collections were created with the deployment default of **1 shard,
replication factor 1** — so the entire graph currently lives on a single
DBServer. That is functionally correct and fine for query-semantics work, but
it does **not** exercise the cluster, so any "performance at scale" numbers
would reflect single-server behavior.

**Recommendation for the benchmark phase:** re-provision the collections with
multiple shards before measuring scale. The trade-off the data forces:

- Sharding `relations` by `_from` gives locality for **outbound** typed queries
  (VCI 1), but **inbound** queries (VCI 2) then scatter-gather across shards.
- Because this is **Enterprise**, a **SmartGraph** (smart attribute on the
  company/`ticker`) is the better fit: it co-locates a company's nodes and
  edges on one shard, so both the heavy outbound disclosures and the
  company-scoped traversals stay local. The supernode metric nodes (shared
  `FIN_METRIC` targets) are the cross-shard exception to plan around.

This is a re-load (~90 min end-to-end, fully scripted) and a modeling decision,
so it is flagged as a modeling decision rather than done automatically.

## Named graph & collection manifest

The dataset's collections are bundled under a **named (General) graph
`FinReflectKG`** so tooling (`arango-cypher-py`, `arango-graph-analytics`) can
target it by name rather than guessing which collections are ours among others
in the database, and so traversals can use `GRAPH 'FinReflectKG'`:

| Belongs to this dataset | Role | In the named graph? |
|---|---|---|
| `Node` | vertices | yes (vertex collection) |
| `relations` | edges (`Node` → `Node`) | yes (edge definition) |
| `chunks` | source-text, referenced via `relations.chunkKey` | no — supporting data, kept out so analytics doesn't treat 1.4 M text docs as vertices |

Created with [scripts/create_graph.py](../scripts/create_graph.py) (metadata-only,
idempotent). To make the graph a full manifest of all three collections, set
`INCLUDE_CHUNKS_AS_ORPHAN = True` to add `chunks` as an orphan collection.

## Graph Visualizer customization

[scripts/install_visualizer.py](../scripts/install_visualizer.py) installs a
custom **theme**, **saved queries**, and **canvas actions** into the ArangoDB
Graph Visualizer's system collections (`_graphThemeStore`, `_queries`,
`_canvasActions`, and the `_viewpoint*` links). It is idempotent (deterministic
keys + replace) and is stage 8 of the rebuild.

**Theme — display by `type`, not by collection.** This is a single-vertex /
single-edge LPG (`Node`, `relations`); the entity & relationship semantics live
in the `type` property. The Visualizer's config maps key on *collection* name, so
per-`type` styling is done with the theme's attribute-based **rules** keyed on
`node.type` / `e.type`:

| Aspect | Mapping |
|---|---|
| Node colour | by **family** — the top ~45 `Node.type` values grouped into 13 semantic families (financial-metric, organization, person/role, risk/legal, geography, …); one shared colour per family |
| Node icon | per `type` (Font Awesome 6), distinguishing types within a family |
| Node label | `name` |
| Edge colour | by **family** — top ~40 `relations.type` values grouped into 7 families (disclosure, +/- impact, dependency, ownership, operational, structural) |
| Edge label | `type` |
| `chunks` | book-page icon (`fa6-solid:book-open`), styled so source-text docs are distinct *if* loaded onto the canvas — `chunks` stays out of the named graph |

`Node.type` has 9,605 distinct values and `relations.type` 30,535 (LLM-extracted,
long-tailed); the family rules cover ~98.6% of nodes / ~91% of edges, and the
rest fall back to a neutral base style. Family→icon/colour taxonomy lives in
`NODE_FAMILIES` / `EDGE_FAMILIES` at the top of the script — edit there to retune.

> **Edge-rule caveat:** the node-rule schema is verified against the live
> Visualizer; the edge-rule shape (`lineStyle` in `condition.config`) mirrors it
> but is not independently verified. If edges render oddly, author one edge rule
> in the Visualizer UI, Save, and read it back from `_graphThemeStore` as the
> authoritative template.

**Saved queries** (Visualizer "Queries" panel) — the path-shaped AQL from
[cypher-queries.md](cypher-queries.md) rewritten to `RETURN p` so each loads a
connected subgraph onto an empty canvas: CINF stakes, CINF holdings → metrics,
Apple's network, 3-hop risk propagation, 3-hop dependency chains, big-tech
dependency cycles, and a company-year disclosure slice. (Also mirrored into the
global AQL editor via `_editor_saved_queries`.)

**Canvas actions** (right-click a node → expand, bound to `@nodes`, `RETURN p`) —
the 1–2 hop relationship motifs those queries traverse: all-neighbors (1 & 2
hop), metrics-this-discloses / who-discloses-this, operates-in, has-stake-in /
who-has-stake-in, depends-on, and negatively-impacted-by.

## How to reproduce / re-run

To recreate the entire database from scratch anywhere (just needs `.env` with
the target ArangoDB connection + the Python venv), run the one orchestrator —
it runs all stages below in order and is safe to re-run:

```bash
THREADS=16 ./scripts/rebuild_all.sh          # full rebuild, end to end
SKIP_DOWNLOAD=1 ./scripts/rebuild_all.sh     # reuse already-downloaded parquet
```

It is equivalent to running these stages by hand:

```bash
.venv/bin/python scripts/download.py                       # 1. fetch parquet
.venv/bin/python scripts/preprocess.py \                   # 2. parquet -> JSONL
    --input "data/raw/data/train-*.parquet" \
    --out data/staging/full --split-bytes 512MB
.venv/bin/python scripts/setup_db.py                       # 3. db + collections
THREADS=16 ./scripts/import_full.sh                        # 4. bulk import
.venv/bin/python scripts/create_indexes.py                 # 5. indexes
.venv/bin/python scripts/validate.py                       # 6. reconcile + VCI check
.venv/bin/python scripts/create_graph.py                   # 7. named graph FinReflectKG
.venv/bin/python scripts/install_visualizer.py             # 8. Visualizer theme + queries + actions
```

All stages are idempotent (deterministic keys + `--on-duplicate ignore` +
exists-checks), so the orchestrator can resume a partial/interrupted run.

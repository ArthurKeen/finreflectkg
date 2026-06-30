# Sharding Analysis & Decision (deferred)

**Status:** v1.0 · 2026-06-15
**Decision:** Stay on the current **single-shard** load for now; benchmark and do
NL-query work first. Revisit cluster sharding only if benchmarks show a clear
need. This document preserves the analysis so the scale phase can resume from it.
**Related:** [load-report.md](load-report.md) · [PRD.md](PRD.md)

## Context

The target is a 3-Coordinator / 3-DBServer / 3-Agent cluster, but the
collections were created with the deployment default (1 shard, replication 1),
so the whole graph sits on one DBServer. To benchmark "at scale" we explored
re-provisioning across shards. The data topology drove the design — and ruled
options out.

## Measured topology (full dataset, DuckDB over local parquet)

| Metric | Value | Why it matters |
|---|---|---|
| Nodes single-ticker / shared | 83% / 17% | most nodes are company-specific |
| Edges → single-ticker target | 26% | …but most edge traffic targets shared concepts |
| **Edge endpoint classes** | | |
| company → company | 16.0% | |
| company → concept | 46.5% | |
| concept → company | 9.9% | |
| **concept → concept** | **27.7%** | **kills the Hybrid-satellite design** |
| **Cross-company references** | **0.00%** | graph is a disjoint union of per-company subgraphs |
| Edges where entity is the filer ORG | 87.2% | the filing company is the natural owner of an edge |
| Nodes if duplicated per company `(name,type,ticker)` | 6,658,668 (2.1×) | cost of a disjoint model |

## Options considered

1. **Hybrid SmartGraph (smart `CompanyNode` + satellite `ConceptNode`).**
   *Infeasible.* A smart edge collection requires a smart value from at least
   one endpoint; the **27.7% concept→concept edges** would be satellite→satellite
   and are rejected by ArangoDB (verified with a live spike:
   *"Collection 'CptNode' … is required to be a smart collection. But would be
   created as satellites."*). Splitting concept→concept into a separate satellite
   edge collection would fragment the single `relations` model and complicate
   every query.

2. **Disjoint SmartGraph sharded by filing `ticker`, concepts duplicated per
   company.** *Best technical fit.* Because cross-company references are 0%, the
   graph is naturally a disjoint union of 743 per-company subgraphs. Smart
   attribute = `ticker`; key = `<ticker>:<md5(name|type)>`; 6.66M nodes (2.1×);
   every edge lives within one company's shard → per-company queries fully local.
   Keeps a single `Node` collection. Cost: concept duplication; global
   cross-company concept queries must aggregate the ~743 copies by `name`
   (cheap with the `name` index).

3. **Plain ticker-sharded, no SmartGraph.** Shard `relations` by `ticker`,
   `Node` by `_key`, N shards. No duplication, preserves global concept identity
   (3.1M nodes). Company edge scans co-locate by ticker (queries must filter on
   `ticker` to hit one shard); endpoint document lookups and inbound supernode
   queries scatter. Simplest reload.

4. **Stay single-shard (CHOSEN for now).** Keep the validated load; benchmark and
   build the NL-query layer. Perf numbers reflect single-server, not cluster
   scale, but the VCI direct-edge-query thesis is fully testable and the
   NL-query half of the POC is unblocked. Reload is ~90 min and fully scripted
   whenever we choose to scale.

## If/when we scale

Recommended path is **Option 2 (Disjoint SmartGraph by ticker)** — it matches the
data and gives the strongest per-company locality. Preprocessing changes:
compute each node's owning ticker (single-ticker → that ticker; the rare shared
node → duplicate under every referencing ticker), emit keys as
`<ticker>:<md5(name|type)>`, and point edge `_from`/`_to` at the per-ticker
copies. Create the graph via `POST /_api/gharial` with
`options.smartGraphAttribute = "ticker"`, `isDisjoint: true`, and a chosen
`numberOfShards`. Re-create the same VCIs afterward.

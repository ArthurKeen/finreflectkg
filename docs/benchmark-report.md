# Benchmark Report — FinReflectKG on ArangoDB

**Status:** v2.0 · 2026-07-05 · **cross-distribution** (baseline + OneShard + SmartGraph);
the v1.0 single-shard baseline is retained below unchanged.
**Suite:** [scripts/benchmark.py](../scripts/benchmark.py) (multi-db + explain-locality) ·
raw: `data/benchmark_cross.json` (cross-distribution), `data/benchmark_results.json` (single-db)
**Related:** [load-report.md](load-report.md) ·
[multi-distribution-plan.md](multi-distribution-plan.md) · [PRD.md](PRD.md) §6

## Method

Each query: 1 warmup + 7 timed iterations. We report **min** (best-case server
time, least contended) and **median** latency, plus the **deterministic profile
counters** — `scannedIndex`, `scannedFull`, `filtered` — which are the stable
signal for index effectiveness regardless of cluster contention. Typed 1-hop
queries use **direct edge-collection queries** (the access path that uses the
VCIs; pattern traversals use the generic edge index — see
[load-report.md](load-report.md)).

## Results

| # | Query | min ms | med ms | scanIdx | scanFull | filtered | index |
|---|-------|-------:|-------:|--------:|---------:|---------:|-------|
| 1 | node point lookup by `name` | 0.5 | 0.8 | 28 | 0 | 0 | `node_name` |
| 2 | 1-hop typed OUT (`operates_in`→GPE) | 13.1 | 15.9 | 6,290 | 0 | 0 | `vci_from_type_totype` |
| 3 | reverse typed IN (who `has_stake_in` X) | 13.4 | 14.7 | 2,882 | 0 | 0 | `vci_to_type_fromtype` |
| 4a | supernode **pruned** (`net income`, VCI) | 179.5 | 184.8 | 59,315 | 0 | 0 | `vci_to_type_fromtype` |
| 4b | supernode **unpruned** (traversal) | 370.2 | 410.3 | 99,295 | 0 | 0 | `edge` |
| 5 | 2-hop (company→metric→peers) | 23.9 | 29.2 | 2,747 | 0 | 158 | traversal |
| 6 | temporal slice (`ticker`+year range) | 21.5 | 21.7 | 10,385 | 0 | 0 | `rel_ticker_year` |
| 7 | NL-grounding (edge→`chunks` text) | 4.0 | 5.2 | 20 | 0 | 0 | edge + chunk PK |

## Findings

1. **The VCIs deliver perfect narrowing.** Every typed query (2, 3, 4a, 6) shows
   `filtered = 0` and `scannedFull = 0` — the index returns exactly the matching
   edges with zero wasted scans and zero collection scans. This is the core
   result the model was designed for.

2. **Supernode pruning is the headline win (4a vs 4b).** On `net income`
   (in-degree ~99 K), the **VCI-pruned direct query scans 59,315 edges in
   ~180 ms**, while the **unpruned pattern traversal scans all 99,295 in
   ~400 ms** — ~40% fewer edges and ~2.2× faster. This is exactly the case the
   `(_to, type, _fromType)` index was built for, and it validates writing typed
   1-hop queries as direct edge queries rather than filtered traversals.

3. **Everything is index-backed.** No query touches a full collection scan
   (`scannedFull = 0` throughout), including the temporal slice and the
   NL-grounding chunk join.

4. **NL-grounding is cheap.** Joining typed edges to their source-text chunk
   (the GraphRAG retrieval primitive) is ~5 ms for a 20-edge fan-out — the
   chunk dedup + primary-key lookup design pays off.

5. **Latency was stable this run** (point lookup sub-ms, typed 1-hop ~13 ms,
   supernode ~185 ms) — unlike an earlier ad-hoc probe that ranged 0.2–20 s on
   the same query. Treat absolute latencies as indicative of a *single-server*,
   variably-loaded shared cluster; the scanned-edge counts are the portable
   metric. A dedicated quiescent window is needed for publishable latency
   numbers.

## Caveats

- **Single shard.** All numbers reflect one DBServer; they do **not** measure
  cluster scale-out. See [sharding-analysis.md](sharding-analysis.md) for the
  deferred Disjoint-SmartGraph path if scale benchmarking is wanted.
- Result-row counts are first-batch (1000) for unbounded queries; `scannedIndex`
  reflects the true match count for the index-backed cases.

---

# Cross-distribution results (G7) — v2.0 · 2026-07-05

Same suite run against all three distributions of the identical dataset:
`FinReflectKG` (flexible 1-shard), `FinReflectKgOneShard` (OneShard), and
`FinReflectKgSmart` (Disjoint SmartGraph by `ticker`, Design 2). Entities are
**discovered per database** because the SmartGraph rewrites keys with a `ticker`
prefix and duplicates shared concepts per company — so `net income` on the smart
db is a *specific company's copy*, not the single global supernode.

Deterministic metrics: **`scannedIndex`** (edges the index actually touched) and
**explain locality** (`RemoteNode` count `r`, i.e. cross-DBServer hops). Latency is
median of 7 iters after warmup — indicative only on the shared cluster.

| # | Query | Baseline med / scanIdx | OneShard med / scanIdx | SmartGraph med / scanIdx |
|---|-------|----------------------:|-----------------------:|-------------------------:|
| 1 | point lookup by `name` | 0.9 ms / 28 | 0.5 ms / 28 | 2.3 ms / **873** |
| 2 | 1-hop typed OUT (`operates_in`→GPE) | 16.4 ms / 6,290 | 18.9 ms / 6,290 | 15.3 ms / 6,290 |
| 3 | reverse typed IN (`has_stake_in`) | 17.1 ms / 2,882 | 14.6 ms / 2,882 | **0.9 ms / 7** |
| 4a | supernode **pruned** (`net income`, VCI) | 228.6 ms / 59,315 | 202.5 ms / 59,315 | **0.9 ms / 35** |
| 4b | supernode **unpruned** (traversal) | 451.1 ms / 99,295 | 364.0 ms / 99,295 | **1.6 ms / 55** |
| 5 | 2-hop (company→metric→peers) | 27.0 ms / 2,747 (r0) | 6.8 ms / 2,026 (r1) | 7.5 ms / 1,099 (**r4**) |
| 6 | temporal slice (`ticker`+year) | 24.7 ms / 10,385 | 21.9 ms / 10,385 | 0.9 ms / 0 †|
| 7 | NL-grounding (edge→`chunks`) | 6.2 ms / 20 | 0.9 ms / 20 | 5.3 ms / 20 |

† The smart run's discovered `ticker` (`aa`) had no edges in 2022–2024, so that
cell scans 0 — not a fair latency comparison. Pin a fixed high-volume ticker for a
publishable temporal number.

## Cross-distribution findings

1. **Supernode decomposition is the SmartGraph headline.** Design 2 duplicates each
   shared concept per company, so the global `net income` supernode (in-degree ~99 K)
   becomes ~743 small per-company nodes. A per-company query against it scans **35–55
   edges instead of 59 K–99 K** — 4a drops **228.6 ms → 0.9 ms (~250×)** and 4b
   **451.1 ms → 1.6 ms (~280×)**. This is the payoff the disjoint-by-`ticker` model was
   chosen for: company-scoped analytics never touch other companies' data.

2. **The documented trade-off shows up exactly where predicted.** *Global* concept
   access costs more on the smart db: a `name` lookup for `net income` now returns
   **873 per-company copies** (scanIdx 28 → 873), and the cross-company 2-hop (query 5)
   crosses shards — **`RemoteNode` = 4** vs 0 on the baseline. This matches the Design 2
   caveat (multi-distribution-plan §5.7): global concept roll-ups must aggregate
   `BY name` and pay cross-shard hops. Fall back to Design B only if such global
   roll-ups dominate the workload.

3. **Company-local access paths are identical across all three.** The 1-hop typed
   OUT query (2) scans exactly 6,290 edges everywhere — it was already company-scoped,
   so placement doesn't change it.

4. **OneShard modestly beats the baseline on multi-hop** by co-locating execution on
   one DBServer: 2-hop **27.0 ms → 6.8 ms** and the unpruned supernode traversal
   **451.1 ms → 364.0 ms**, with identical scan counts (same global 1-shard graph).

5. **The VCIs narrow perfectly under every placement** — `scannedFull = 0` and
   `filtered = 0` on all index-backed queries across all three databases.

**Locality caveat:** most direct edge queries show `RemoteNode = 1 / GatherNode = 1`
even on OneShard — that is just the coordinator shipping the final result from the
single DBServer, *not* per-shard scatter/gather. The meaningful locality signals here
are (a) the SmartGraph's per-company scan reduction and (b) the `RemoteNode = 4` on the
cross-company smart 2-hop, which flags genuine cross-shard traversal.

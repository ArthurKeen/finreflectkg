# Benchmark Report — FinReflectKG on ArangoDB

**Status:** v1.0 · 2026-06-15 · single-shard load (3.1M nodes / 17.5M edges)
**Suite:** [scripts/benchmark.py](../scripts/benchmark.py) · raw: `data/benchmark_results.json`
**Related:** [load-report.md](load-report.md) · [PRD.md](PRD.md) §6

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

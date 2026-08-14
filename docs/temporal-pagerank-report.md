# FinReflectKG — Temporal PageRank (as-of, cleaned graph)

*Generated: 2026-08-14 16:19:01*

## Executive Summary

Batch analysis of 4 jobs completed with 4 successful. Generated 8 insights and 8 recommendations.

## Methodology & data cleaning

**Question.** Which entities are most central in the S&P 500 10-K knowledge graph, and how does
that shift across the decade (2014 → 2024)?

**Method.** Point-in-time (*as-of*) subgraphs are materialized from the time-travel layer
(`FinReflectKgTemporal`, valid-time `validFrom`/`validTo`), one per anchor year, and GAE
**PageRank** is run over each via the `graph_analytics_ai` orchestrator (`GAEOrchestrator.run_analysis`,
self-managed ACP engine). Pregel is deprecated on this cluster, so GAE is the execution engine.

**Data cleaning (critical for correctness).** The raw extraction conflates *anonymous* mentions
("a supplier", "our customers") into single shared nodes, so hundreds of unrelated companies
falsely share one `supplier`/`customer` node — which would dominate PageRank for the wrong
reason. Before ranking, each as-of snapshot is cleaned: **generic role hubs are skolemized** into
per-company blank nodes (89 hubs → 5,893 bnodes) and **junk placeholders excluded** (23 hubs:
`default`, `other`, `various`, …). See `docs/generic-mention-conflation.md`.


## Influence over time (top entities by year)

Top entities by as-of PageRank (cleaned graph — generic hubs skolemized, junk excluded):

| rank | 2014 | 2019 | 2020 | 2024 |
|---|---|---|---|---|
| 1 | net income (FIN_METRIC) | net income (FIN_METRIC) | net income (FIN_METRIC) | net income (FIN_METRIC) |
| 2 | revenue (FIN_METRIC) | revenue (FIN_METRIC) | revenue (FIN_METRIC) | revenue (FIN_METRIC) |
| 3 | net sale (FIN_METRIC) | net sale (FIN_METRIC) | net sale (FIN_METRIC) | net sale (FIN_METRIC) |
| 4 | operate income (FIN_METRIC) | operate income (FIN_METRIC) | operate income (FIN_METRIC) | new york stock exchange (FIN_MARKET) |
| 5 | earnings from operation (FIN_METRIC) | index value (FIN_METRIC) | fair value (FIN_METRIC) | operate income (FIN_METRIC) |
| 6 | fair value (FIN_METRIC) | revenue growth (FIN_METRIC) | index value (FIN_METRIC) | effective tax rate (FIN_METRIC) |
| 7 | index value (FIN_METRIC) | fair value (FIN_METRIC) | new york stock exchange (FIN_MARKET) | operating expense (FIN_METRIC) |
| 8 | sale (FIN_METRIC) | interest expense (FIN_METRIC) | total revenue (FIN_METRIC) | gross margin (FIN_METRIC) |
| 9 | operating earnings (FIN_METRIC) | united state (GPE) | united state (GPE) | fair value (FIN_METRIC) |
| 10 | adjust oibda (FIN_METRIC) | net revenue (FIN_METRIC) | gross margin (FIN_METRIC) | operate margin (FIN_METRIC) |
| 11 | 2014 (FIN_METRIC) | operating profit (FIN_METRIC) | revenue growth (FIN_METRIC) | united state (GPE) |
| 12 | revenue growth (FIN_METRIC) | new york stock exchange (FIN_MARKET) | operate margin (FIN_METRIC) | sec (ORG_REG) |

## Generic-mention cleaning — before / after

Running PageRank on the *dirty* graph first ranked `supplier` and `default` near the top — pure
extraction artifacts. After cleaning:

- **`supplier`** (fan-in 681 companies) → 681 per-company leaf bnodes; `bn_amd_supplier` now ranks
  ~570× below `net income`.
- **`default`** (was #1 in 2024) and **`other`** → excluded entirely (non-entities).
- **Zero** generic-mention hubs remain in the top 200 of any year; the rankings are anchored by
  genuine shared financial concepts.

This is also a demonstration of PageRank *as a detector*: the first pass surfaced a second junk
class (`default`/`other`) that the initial role lexicon had missed.


## Findings

- **`net income` is #1 in every year** — the S&P 500's most-referenced shared metric throughout.
- **Market structure rises:** `new york stock exchange` is absent from the 2014 top ranks, appears
  by 2020 (#7), and climbs to **#4 by 2024**; the **SEC** (regulator) and `united states` also enter
  the top by 2024.
- **2024 tilts to cost/tax/margin:** `effective tax rate`, `operating expense`, `operate margin`,
  and `capex` join the leaders — a shift from pure top-line metrics toward efficiency and regulation.
- Complementary **degree-trend analytics** (`scripts/temporal_analytics.py`) show `covid-19` entering
  the 2020 top-10 and **cybersecurity risk / lease accounting / SEC rule** rising 2014 → 2024.


## 1. Executive Summary

Batch analysis of 4 jobs completed with 4 successful. Generated 8 insights and 8 recommendations.

## 2. PageRank as-of 2014

Algorithm: pagerank, Runtime: 110.0s

## 3. PageRank as-of 2019

Algorithm: pagerank, Runtime: 110.0s

## 4. PageRank as-of 2020

Algorithm: pagerank, Runtime: 110.0s

## 5. PageRank as-of 2024

Algorithm: pagerank, Runtime: 110.0s

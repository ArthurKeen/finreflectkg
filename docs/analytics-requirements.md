# FinReflectKG — Graph Analytics Business Requirements

Input for the agentic graph-analytics workflow (PRD §4.7 / G8, top layer). The agentic
system (`agentic-graph-analytics`) reads these requirements, inspects the FinReflectKG
schema, generates graph-analytics use cases, selects and runs GAE algorithms, and
produces an intelligence report.

## Context

FinReflectKG is a financial knowledge graph extracted from S&P 500 10-K SEC filings
(2014–2024): ~3.1M entities and ~17.5M typed relationships. It is a labeled property
graph with a single `Node` vertex collection (the semantic type is the `type` property —
e.g. `ORG` companies, `FIN_METRIC` financial metrics, `GPE` geographies, `RISK_FACTOR`,
`LITIGATION`, `PRODUCT`, `PERSON`) and a single `relations` edge collection (typed via a
`type` property — e.g. `discloses`, `operates_in`, `has_stake_in`, `depends_on`,
`negatively_impacts`, `competes_with`).

## Questions we want the analytics to answer

1. **Centrality / influence.** Which financial concepts and entities are the most central
   across the corpus (by PageRank / degree)? We expect widely-disclosed metrics (e.g. net
   income, revenue) and highly-connected organizations to surface.
2. **Connectivity.** Is the graph one coherent structure or fragmented? How many weakly
   connected components are there, and how large is the dominant component?
3. **Communities.** What communities of related concepts emerge (label propagation) —
   e.g. clusters of co-disclosed metrics or sector-aligned groupings?
4. **Influential organizations.** Among `ORG` entities specifically, which are the most
   influential hubs by their disclosure and dependency links?

## Constraints

- Read-only analytics: write algorithm outputs to separate result collections; do not
  mutate `Node` or `relations`.
- The graph is an LPG (single `Node` / `relations`); algorithms run over the whole graph.

# Product Requirements Document

## 1. Overview

**Product:** FinReflectKG Graph Analytics
**Domain:** financial analytics
**Documents analyzed:** 1

Project for FinReflectKG to generate graph-analytics use cases, run GAE algorithms, and produce intelligence reports based on financial knowledge graph data from S&P 500 10-K SEC filings. The analytics aim to answer questions about centrality, connectivity, and communities within the graph.

## 2. Objectives

- **OBJ-001 – Understand Centrality and Influence in FinReflectKG** (high)
  - Identify key financial concepts and entities that are most central or influential within the financial knowledge graph.
  - Success criteria: Widely-disclosed metrics (e.g., net income, revenue) are surfaced as central.; Highly-connected organizations are surfaced as central.
  - Related requirements: REQ-006
- **OBJ-002 – Assess Graph Connectivity** (high)
  - Analyze the structural coherence of the FinReflectKG to determine if it forms a single structure or is fragmented.
  - Success criteria: Number of weakly connected components is identified.; Size of the dominant component is determined.
  - Related requirements: REQ-007, REQ-008
- **OBJ-003 – Discover Financial Communities** (high)
  - Uncover natural groupings and relationships between concepts within the financial knowledge graph.
  - Success criteria: Clusters of co-disclosed metrics are identified.; Sector-aligned groupings are identified.
  - Related requirements: REQ-009
- **OBJ-004 – Identify Influential Organizations** (high)
  - Pinpoint organizations that act as significant hubs based on their financial disclosures and dependencies.
  - Success criteria: Most influential `ORG` entities are identified by disclosure links.; Most influential `ORG` entities are identified by dependency links.
  - Related requirements: REQ-010

## 3. Requirements

- **REQ-001** [critical] (functional)
  - The agentic system must read business requirements for graph analytics.
- **REQ-002** [critical] (functional)
  - The agentic system must inspect the FinReflectKG schema.
- **REQ-003** [critical] (functional)
  - The agentic system must generate graph-analytics use cases.
- **REQ-004** [critical] (functional)
  - The agentic system must select and run GAE algorithms.
- **REQ-005** [critical] (functional)
  - The agentic system must produce an intelligence report.
- **REQ-011** [critical] (constraint)
  - Analytics must be read-only on the FinReflectKG: write algorithm outputs to separate result collections; do not mutate `Node` or `relations`.
- **REQ-012** [critical] (technical)
  - Algorithms must run over the whole graph, which is an LPG (single `Node` / `relations`).
- **REQ-006** [high] (functional)
  - Identify the most central financial concepts and entities across the corpus using PageRank/degree.
- **REQ-007** [high] (functional)
  - Determine if the graph is one coherent structure or fragmented.
- **REQ-008** [high] (functional)
  - Identify the number of weakly connected components and the size of the dominant component.
- **REQ-009** [high] (functional)
  - Identify communities of related concepts using label propagation (e.g., clusters of co-disclosed metrics or sector-aligned groupings).
- **REQ-010** [high] (functional)
  - Identify the most influential `ORG` entities by their disclosure and dependency links.

## 4. Stakeholders

_No stakeholders identified._

## 5. Constraints

- Analytics must be read-only; no mutation of `Node` or `relations`.
- Algorithm outputs must be written to separate result collections.
- The graph is a Labeled Property Graph (LPG) with a single `Node` vertex collection and a single `relations` edge collection.
- Algorithms must run over the whole graph.

## 6. Risks

- Agentic system may not accurately generate relevant graph-analytics use cases.
- Selected GAE algorithms may not be optimal for the specific questions.
- Intelligence report may not provide actionable insights.
- Performance issues when running algorithms over the entire graph (~3.1M entities, ~17.5M relationships).

## 7. Graph Schema (Summary)

- Vertex collections: 32 (aga_requirement_versions, benchmark_aqlizer_queries_7, benchmark_aqlizer_queries_9, arango_cypher_schema_cache, gae_pagerank, chunks, Node, aga_graph_profiles, aga_connection_profiles, benchmark_aqlizer_queries_8, aga_report_manifests, benchmark_aqlizer_queries_5, benchmark_aqlizer_queries_6, benchmark_aqlizer_queries_2, aga_product_meta, benchmark_aqlizer_queries_1, aga_report_sections, aga_chart_specs, aga_requirement_interviews, aga_schema_snapshots, aga_workspaces, aga_graph_sets, aga_published_snapshots, gae_wcc, aga_audit_events, benchmark_aqlizer_queries_4, benchmark_queries, aga_documents, benchmark_aqlizer_queries_10, aga_workflow_runs, aga_collection_roles, benchmark_aqlizer_queries_3)
- Edge collections: 1 (relations)
- Total documents: 28,197,310
- Total edges: 17,513,372
- Domain: financial knowledge graph / GraphRAG
- Complexity: 7.0/10
- Key entities: Node, chunks, gae_pagerank, gae_wcc, aga_graph_profiles
- Key relationships: relations
- Suggested analyses: Centrality of Financial Entities and Organizations, Identification of Disconnected Financial Subgraphs, Tracing Financial Dependency Chains, Clustering of Related Financial Concepts, Identifying Highly Connected Financial Nodes

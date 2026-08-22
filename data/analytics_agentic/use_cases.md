# Graph Analytics Use Cases

Generated 10 use cases for graph analytics.


## UC-001: Understand Centrality and Influence in FinReflectKG

**Type:** centrality  
**Priority:** high


### Description
Identify key financial concepts and entities that are most central or influential within the financial knowledge graph.


### Related Requirements

- REQ-006


### Data Requirements

- Domain: financial analytics


### Expected Outputs

- Widely-disclosed metrics (e.g., net income, revenue) are surfaced as central.
- Highly-connected organizations are surfaced as central.


## UC-002: Assess Graph Connectivity

**Type:** pattern  
**Priority:** high


### Description
Analyze the structural coherence of the FinReflectKG to determine if it forms a single structure or is fragmented.


### Related Requirements

- REQ-007
- REQ-008


### Data Requirements

- Domain: financial analytics


### Expected Outputs

- Number of weakly connected components is identified.
- Size of the dominant component is determined.


## UC-003: Discover Financial Communities

**Type:** community  
**Priority:** high


### Description
Uncover natural groupings and relationships between concepts within the financial knowledge graph.


### Related Requirements

- REQ-009


### Data Requirements

- Domain: financial analytics


### Expected Outputs

- Clusters of co-disclosed metrics are identified.
- Sector-aligned groupings are identified.


## UC-004: Identify Influential Organizations

**Type:** centrality  
**Priority:** high


### Description
Pinpoint organizations that act as significant hubs based on their financial disclosures and dependencies.


### Related Requirements

- REQ-010


### Data Requirements

- Domain: financial analytics


### Expected Outputs

- Most influential `ORG` entities are identified by disclosure links.
- Most influential `ORG` entities are identified by dependency links.


## UC-S01: Centrality of Financial Entities and Organizations

**Type:** centrality  
**Priority:** medium


### Description
Identify the most influential or central financial entities (e.g., organizations, metrics, risks) within the knowledge graph, indicating their importance in the overall financial landscape or specific analytical contexts. This leverages the pre-computed 'gae_pagerank' data.


### Suggested Algorithms

- pagerank


### Data Requirements

- Vertex collections: Node, chunks, gae_pagerank, gae_wcc, aga_graph_profiles
- Edge collections: relations


### Expected Outputs

- Centrality of Financial Entities and Organizations results


## UC-S02: Identification of Disconnected Financial Subgraphs

**Type:** centrality  
**Priority:** medium


### Description
Detect isolated or weakly connected components of financial entities, which could represent distinct market segments, unrelated financial events, or data silos. This leverages the pre-computed 'gae_wcc' data.


### Suggested Algorithms

- wcc


### Data Requirements

- Vertex collections: Node, chunks, gae_pagerank, gae_wcc, aga_graph_profiles
- Edge collections: relations


### Expected Outputs

- Identification of Disconnected Financial Subgraphs results


## UC-S03: Tracing Financial Dependency Chains

**Type:** pathfinding  
**Priority:** medium


### Description
Map the shortest paths between key financial entities (e.g., from a risk factor to affected organizations, or between companies with shared holdings) to understand direct and indirect relationships and dependencies, as hinted by benchmark queries like 'Risk -> dependency -> disclosure chains'.


### Suggested Algorithms

- shortest_path


### Data Requirements

- Vertex collections: Node, chunks, gae_pagerank, gae_wcc, aga_graph_profiles
- Edge collections: relations


### Expected Outputs

- Tracing Financial Dependency Chains results


## UC-S04: Clustering of Related Financial Concepts

**Type:** community  
**Priority:** medium


### Description
Group similar financial metrics, organizations, or events based on their interconnections. This can reveal natural groupings of financial concepts, aiding in contextual understanding and targeted analysis, especially given the diverse 'type' attribute of 'Node'.


### Suggested Algorithms

- community_detection


### Data Requirements

- Vertex collections: Node, chunks, gae_pagerank, gae_wcc, aga_graph_profiles
- Edge collections: relations


### Expected Outputs

- Clustering of Related Financial Concepts results


## UC-S05: Identifying Highly Connected Financial Nodes

**Type:** centrality  
**Priority:** medium


### Description
Determine which financial entities have the most direct connections within the graph. High-degree nodes might be critical connectors, popular metrics, or widely discussed organizations, offering insights into data density and potential choke points.


### Suggested Algorithms

- degree_centrality


### Data Requirements

- Vertex collections: Node, chunks, gae_pagerank, gae_wcc, aga_graph_profiles
- Edge collections: relations


### Expected Outputs

- Identifying Highly Connected Financial Nodes results


## UC-R01: Requirement: REQ-001

**Type:** centrality  
**Priority:** critical


### Description
The agentic system must read business requirements for graph analytics.


### Related Requirements

- REQ-001

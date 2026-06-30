# FinReflectKG Queries — NL · Cypher (de-`Entity`-fied) · AQL

**Status:** v2.0 · 2026-06-16
**Sources:** the original Neo4j Cypher (pre-`Entity`-drop) + the legacy AQL written
for the legacy ArangoDB graph `financial-kg-2025-08-26`.
**Related:** [schema-mapping.md](schema-mapping.md) (legacy ↔ FinReflectKG field map) ·
[load-report.md](load-report.md) · [benchmark-report.md](benchmark-report.md)

Each of the 22 entries below has three forms of the same question:
1. **NL** — the reverse-engineered natural-language question.
2. **Cypher** — the original, rewritten to remove the dropped `Entity` label.
3. **FinReflectKG AQL** — the legacy AQL converted to run on `FinReflectKG`.

## Cypher transformation rule (drop `Entity`)

| Original | Rewritten | Why |
|---|---|---|
| `(x:Entity {type:'ORG'})` | `(x:ORG)` | the type value *is* the single remaining label |
| `(x:Entity)` (no type) | `(x)` | `Entity` was the only universal label |
| `n.type` in `RETURN`/`WHERE` | `labels(n)[0]` / label predicate | type is now the label |
| `:Has_Stake_In`, `:Discloses`, … | unchanged | relationship types were never the `Entity` label |

## AQL conversion rules (`financial-kg-2025-08-26` → `FinReflectKG`)

Full field map in [schema-mapping.md](schema-mapping.md). Applied throughout below:

- `entities` → `Node`; `WITH entities` → `WITH Node`; `DOCUMENT(entities, x)` → `DOCUMENT(x)`.
- `e.relation` → `e.type`, **value lowercased**; in path filters `p.edges[*].relation` → `p.edges[*].type`.
- **Relationship values are lemmatized:** `Has_Stake_In`→`has_stake_in`, `Discloses`→`discloses`,
  `Operates_In`→`operates_in`, `Regulates`→`regulates`, `Negatively_Impacts`→`negatively_impacts`,
  `Depends_On`→`depends_on`, **`Supplies`→`supply`** (lemma).
- `e.sourceType` → `e._fromType`; `e.destinationType` → `e._toType`.
- `e.context`→`e.extractionType`; `e.start_date` (`"December 2019"`) → `e.startDate` (`"2019-12"`,
  still lexically sortable); `e.source_file`→`e.sourceFile`; `e.page_id`→`e.pageId`.
- **No ticker keys.** Legacy `entities/CINF` (key = ticker) → resolve by name:
  `FIRST(FOR n IN Node FILTER n.name=='cinf' AND n.type=='ORG' RETURN n._id)`.
  Entity **names are lowercased** (`org._key IN ["AAPL","MSFT"]` → `org.name IN ["aapl","msft"]`;
  `name LIKE "%Revenue%"` → `LIKE "%revenue%"`; company names like `"Apple Inc."` → ticker `"aapl"`).
- **Ticker-detection heuristic** `LENGTH(v._key)<6 AND v._key==UPPER(v._key)` (md5 keys make this
  meaningless) → `e._toType IN ["ORG","COMP"] AND LENGTH(v.name)<6`.

> **Two caveats, verified live.** (a) The datasets differ — FinReflectKG is the full 17.5 M-edge
> set, the legacy graph ≈14.8 M with different extraction — so query *shapes* port but **results
> won't match** (e.g. `cinf has_stake_in …` resolves to accounting-policy items here, so the
> CINF→ticker queries 3/4/6/7 run but return little). (b) Query 2's legacy "fixed-list +
> `COLLECT AGGREGATE LENGTH(subquery)`" pattern triggers a cluster `RemoteNode` error on the
> 17.5 M-edge `relations`; the idiomatic single-pass form is given instead. All other queries
> were executed successfully against `FinReflectKG`.

---

## 1. Entity-type distribution

**NL:** *"What are the 20 most common entity types in the knowledge graph?"*

```cypher
MATCH (n)
RETURN labels(n)[0] AS entity_type, COUNT(n) AS count
ORDER BY count DESC
LIMIT 20
```

```aql
// faithful to the legacy fixed-list form (works for the Node collection):
FOR entity_type IN ["ORG","FIN_METRIC","FIN_INST","ACCOUNTING_POLICY","SEGMENT",
                    "REGULATORY_REQUIREMENT","COMP","RISK_FACTOR","PRODUCT","GPE","PERSON",
                    "MACRO_CONDITION","COMMENTARY","EVENT","CONCEPT","ORG_REG","LITIGATION",
                    "LOGISTICS","ECON_IND","RAW_MATERIAL"]
  COLLECT entityType = entity_type
  AGGREGATE entityCount = LENGTH(FOR entity IN Node FILTER entity.type == entity_type RETURN 1)
  SORT entityCount DESC
  RETURN {type: entityType, count: entityCount}

// idiomatic single-pass equivalent (no hardcoded list):
// FOR n IN Node COLLECT t = n.type WITH COUNT INTO c SORT c DESC LIMIT 20 RETURN {type:t, count:c}
```

## 2. Relationship-type distribution

**NL:** *"What are the 30 most common relationship types in the graph?"*

```cypher
MATCH ()-[r]->()
RETURN type(r) AS relationship_type, COUNT(r) AS count
ORDER BY count DESC
LIMIT 30
```

```aql
// The legacy fixed-list + COLLECT AGGREGATE LENGTH(subquery) pattern triggers a cluster
// RemoteNode error on the 17.5M-edge relations collection. This single-pass form is the
// FinReflectKG equivalent (one scan, faster):
FOR e IN relations
  COLLECT relationType = e.type WITH COUNT INTO relationCount
  SORT relationCount DESC
  LIMIT 30
  RETURN {relation: relationType, count: relationCount}
```

## 3. Companies CINF holds a stake in (as paths)

**NL:** *"Show me, as a graph, the publicly-traded companies that Cincinnati Financial (CINF)
has a stake in."*

```cypher
MATCH p = (a {id: 'CINF'})-[r:Has_Stake_In]->(b)
WHERE b.id IS NOT NULL AND size(b.id) < 6 AND b.id = upper(b.id)
  AND b.id <> 'CINF'
RETURN p
LIMIT 50
```

```aql
WITH Node
LET cinf = FIRST(FOR n IN Node FILTER n.name == "cinf" AND n.type == "ORG" RETURN n._id)
FOR v, e, p IN 1..1 OUTBOUND cinf relations
  FILTER p.edges[*].type ALL == "has_stake_in"
  FILTER e._toType IN ["ORG","COMP"]          // ticker-like company (legacy: short UPPER _key)
  FILTER LENGTH(v.name) < 6
  FILTER v.name != "cinf"
  LIMIT 50
  RETURN {path: [{id: "cinf", type: "ORG"},
                 {relation: e.type},
                 {id: v._key, name: v.name, type: v.type}]}
```

## 4. Companies CINF holds a stake in (ticker + name)

**NL:** *"Which publicly-traded companies does CINF hold a stake in? List their ticker symbols
and company names."*

```cypher
MATCH (a {id: 'CINF'})-[r:Has_Stake_In]->(b)
WHERE b.id IS NOT NULL AND size(b.id) < 6 AND b.id = upper(b.id)
  AND b.id <> 'CINF'
RETURN b.id AS ticker, b.name AS company_name
LIMIT 50
```

```aql
WITH Node
LET cinf = FIRST(FOR n IN Node FILTER n.name == "cinf" AND n.type == "ORG" RETURN n._id)
FOR v, e, p IN 1..1 OUTBOUND cinf relations
  FILTER p.edges[*].type ALL == "has_stake_in"
  FILTER e._toType IN ["ORG","COMP"]
  FILTER LENGTH(v.name) < 6
  FILTER v.name != "cinf"
  LIMIT 50
  RETURN {ticker: v.name, company_name: v.name}   // FinReflectKG has no separate ticker key
```

## 5. Organizations operating in many locations

**NL:** *"Which organizations operate in more than 3 different geographic locations? Show the
count and a few example locations, most widespread first."*

```cypher
MATCH (org:ORG)-[:Operates_In]->(loc:GPE)
WITH org, COUNT(DISTINCT loc) AS location_count,
     COLLECT(DISTINCT loc.name)[0..5] AS sample_locations
WHERE location_count > 3
RETURN org.name AS organization, location_count, sample_locations
ORDER BY location_count DESC
LIMIT 15
```

```aql
WITH Node
FOR org IN Node
  FILTER org.type == "ORG"
  FILTER org.name != null
  LIMIT 1000
  FOR location, op_edge, op_path IN 1..1 OUTBOUND org relations OPTIONS {parallelism: 3}
    FILTER op_path.edges[*].type ALL == "operates_in"
    FILTER op_path.edges[*]._toType ALL == "GPE"
    COLLECT org_id = org._id, org_name = org.name
    AGGREGATE location_names = UNIQUE(location.name), location_count = LENGTH(UNIQUE(location.name))
    FILTER location_count > 3
    SORT location_count DESC
    LIMIT 15
    RETURN {organization: org_name, location_count: location_count,
            sample_locations: SLICE(location_names, 0, 5)}
```

## 6. Financial metrics disclosed by CINF's holdings (paths)

**NL:** *"Show the financial metrics disclosed by the companies that CINF has a stake in, as
connected paths."*

```cypher
MATCH path = (a {id: 'CINF'})
  -[:Has_Stake_In]->(b)
  -[:Discloses]->(c:FIN_METRIC)
WHERE b.id IS NOT NULL AND size(b.id) < 6 AND b.id = upper(b.id)
RETURN path
LIMIT 25
```

```aql
WITH Node
LET cinf = FIRST(FOR n IN Node FILTER n.name == "cinf" AND n.type == "ORG" RETURN n._id)
FOR c, e, p IN 2..2 OUTBOUND cinf relations OPTIONS {uniqueVertices: "global", bfs: true}
  FILTER p.edges[0].type == "has_stake_in"
  FILTER p.edges[1].type == "discloses"
  FILTER p.edges[1]._toType == "FIN_METRIC"
  LIMIT 25
  RETURN {path: [{id: "cinf", type: "ORG"},
                 {relation: p.edges[0].type},
                 {id: p.vertices[1]._key, name: p.vertices[1].name, type: p.vertices[1].type},
                 {relation: p.edges[1].type},
                 {id: c._key, name: c.name, type: c.type}]}
// (legacy used `p.edges[*].destinationType ALL == "FIN_METRIC"`, which also constrains the
//  has_stake_in hop; narrowed here to the discloses hop, the intended target.)
```

## 7. Metrics disclosed by Apple (held by CINF)

**NL:** *"What financial metrics does Apple (AAPL) — a company CINF has a stake in — disclose?"*

```cypher
MATCH ({id: 'CINF'})-[:Has_Stake_In]->({id: 'AAPL'})-[:Discloses]->(m:FIN_METRIC)
RETURN DISTINCT m.name
LIMIT 25
```

```aql
WITH Node
LET cinf = FIRST(FOR n IN Node FILTER n.name == "cinf" AND n.type == "ORG" RETURN n._id)
FOR v, e, p IN 2..2 OUTBOUND cinf relations OPTIONS {uniqueVertices: "global", bfs: true}
  FILTER p.edges[0].type == "has_stake_in"
  FILTER p.edges[0]._toType == "ORG"
  FILTER p.vertices[1].name == "aapl"
  FILTER p.edges[1].type == "discloses"
  FILTER p.edges[1]._toType == "FIN_METRIC"
  LIMIT 25
  RETURN DISTINCT v.name
```

## 8. Risk exposure of widely-operating organizations

**NL:** *"For organizations operating in more than 5 locations, which of those locations are
negatively impacted by risks, and what are those risks?"*

```cypher
MATCH (org:ORG)-[:Operates_In]->(loc1:GPE)
WITH org, COUNT(DISTINCT loc1) AS location_count
WHERE location_count > 5
MATCH (org)-[:Operates_In]->(loc:GPE)<-[:Negatively_Impacts]-(risk)
WITH org.name AS organization, location_count, loc.name AS risky_location,
     COLLECT(DISTINCT risk.name) AS risks
ORDER BY SIZE(risks) DESC
LIMIT 20
RETURN organization, location_count, risky_location, risks
```

```aql
WITH Node, relations
LET high_location_orgs = (
  FOR edge IN relations
    FILTER edge.type == "operates_in"
    FILTER edge._toType == "GPE"
    COLLECT org_id = edge._from WITH COUNT INTO loc_count
    FILTER loc_count > 5
    SORT loc_count DESC
    LIMIT 200
    RETURN {org_id: org_id, count: loc_count}
)
FOR org_info IN high_location_orgs
  LET org = DOCUMENT(org_info.org_id)
  FILTER org.type == "ORG"
  FOR op_edge IN relations
    FILTER op_edge._from == org_info.org_id
    FILTER op_edge.type == "operates_in"
    FILTER op_edge._toType == "GPE"
    LET location = DOCUMENT(op_edge._to)
    FILTER location.type == "GPE"
    LET location_risks = (
      FOR risk_edge IN relations
        FILTER risk_edge._to == location._id
        FILTER risk_edge.type == "negatively_impacts"
        LET risk = DOCUMENT(risk_edge._from)
        FILTER risk.type IN ["RISK","RISK_FACTOR"]
        RETURN risk.name
    )
    FILTER LENGTH(location_risks) > 0
    LIMIT 20
    RETURN {organization: org.name, location_count: org_info.count,
            risky_location: location.name, risks: UNIQUE(location_risks)}
```

## 9. Stakeholders in metric-rich big-tech companies

**NL:** *"For major tech companies (Apple, Microsoft, Google, Amazon, Tesla, Meta, Netflix),
which stakeholders are invested in them, and what financial metrics do those companies disclose
(at least 3)?"*

```cypher
MATCH (stakeholder)-[:Has_Stake_In]->(company:ORG)
WHERE company.name IN ["AAPL","MSFT","GOOGL","AMZN","TSLA","META","NFLX"]
WITH stakeholder, company
MATCH (company)-[:Discloses]->(metric:FIN_METRIC)
WITH company, stakeholder, COLLECT(DISTINCT metric.name)[0..5] AS disclosed_metrics
WHERE SIZE(disclosed_metrics) > 2
RETURN company.name AS organization, stakeholder.name AS stakeholder,
       disclosed_metrics, SIZE(disclosed_metrics) AS metric_count
ORDER BY stakeholder
LIMIT 15
```

```aql
WITH Node
FOR org IN Node
  FILTER org.type == "ORG"
  FILTER org.name != null
  FILTER org.name IN ["aapl","msft","googl","amzn","tsla","meta","nflx"]
  LIMIT 10
  FOR stakeholder, stake_edge, p1 IN 1..1 INBOUND org relations
    OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
    FILTER p1.edges[*].type ALL == "has_stake_in"
    FILTER stake_edge._fromType == "ORG"
    FILTER stakeholder.name != null
    LET metrics = (
      FOR metric, disc_edge, p2 IN 1..1 OUTBOUND org relations
        OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
        FILTER p2.edges[*].type ALL == "discloses"
        FILTER disc_edge._toType == "FIN_METRIC"
        FILTER metric.name != null
        SORT metric.name LIMIT 5 RETURN metric.name)
    FILTER LENGTH(metrics) > 2
    SORT stakeholder.name LIMIT 15
    RETURN {organization: org.name, stakeholder: stakeholder.name,
            disclosed_metrics: metrics, metric_count: LENGTH(metrics)}
```

## 10. Risk → dependency → disclosure chains

**NL:** *"Trace how risks (risk factors or events) negatively impact organizations that in turn
depend on other organizations, and show the financial metrics those dependency partners
disclose."*

```cypher
MATCH (risk)-[:Negatively_Impacts]->(org1:ORG)
  -[:Depends_On]->(org2:ORG)-[:Discloses]->(metric:FIN_METRIC)
WHERE risk:RISK OR risk:RISK_FACTOR OR risk:EVENT
WITH risk.name AS risk_name, org1.name AS impacted_org, org2.name AS dependent_org,
     COLLECT(DISTINCT metric.name)[0..3] AS disclosed_metrics, COUNT(DISTINCT metric) AS metric_count
WHERE metric_count > 0
RETURN risk_name, impacted_org, dependent_org, disclosed_metrics, metric_count
ORDER BY metric_count DESC
LIMIT 10
```

```aql
WITH Node
FOR risk IN Node
  FILTER risk.type IN ["RISK","RISK_FACTOR","EVENT"]
  FILTER risk.name != null
  LIMIT 20
  FOR org1, neg_edge, p1 IN 1..1 OUTBOUND risk relations
    OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
    FILTER p1.edges[*].type ALL == "negatively_impacts"
    FILTER neg_edge._toType == "ORG"
    FOR org2, dep_edge, p2 IN 1..1 OUTBOUND org1 relations
      OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
      FILTER p2.edges[*].type ALL == "depends_on"
      FILTER dep_edge._toType == "ORG"
      LET metric_count = LENGTH(FOR metric, disc_edge IN 1..1 OUTBOUND org2 relations
        FILTER disc_edge.type == "discloses" FILTER disc_edge._toType == "FIN_METRIC" RETURN 1)
      FILTER metric_count > 0
      LET sample_metrics = (FOR metric, disc_edge IN 1..1 OUTBOUND org2 relations
        FILTER disc_edge.type == "discloses" FILTER disc_edge._toType == "FIN_METRIC"
        LIMIT 3 RETURN metric.name)
      SORT metric_count DESC LIMIT 10
      RETURN {risk_name: risk.name, impacted_org: org1.name, dependent_org: org2.name,
              disclosed_metrics: sample_metrics, metric_count: metric_count}
```

## 11. Geographic risk-propagation paths (3-hop)

**NL:** *"Trace 3-hop risk propagation: a risk or event negatively impacts an organization, which
depends on another organization, which operates in some location."*

```cypher
MATCH path = (risk)-[:Negatively_Impacts]->(org1:ORG)
  -[:Depends_On]->(org2:ORG)-[:Operates_In]->(loc:GPE)
WHERE risk:RISK OR risk:RISK_FACTOR OR risk:EVENT
RETURN risk.name AS initial_risk, org1.name AS impacted_org,
       org2.name AS dependent_org, loc.name AS location
LIMIT 20
```

```aql
WITH Node
FOR risk IN Node
  FILTER risk.type IN ["RISK","RISK_FACTOR","EVENT"]
  FOR final_location, final_edge, full_path IN 3..3 OUTBOUND risk relations
    FILTER full_path.edges[0].type == "negatively_impacts"
    FILTER full_path.vertices[1].type == "ORG"
    FILTER full_path.edges[1].type == "depends_on"
    FILTER full_path.vertices[2].type == "ORG"
    FILTER full_path.edges[2].type == "operates_in"
    FILTER final_location.type == "GPE"
    LIMIT 20
    RETURN {initial_risk: risk.name, impacted_org: full_path.vertices[1].name,
            dependent_org: full_path.vertices[2].name, location: final_location.name}
```

## 12. Heavily-regulated, metric-disclosing organizations

**NL:** *"Among organizations that disclose more than 50 financial metrics and are regulated by
more than 3 regulators, which disclose the most?"*

```cypher
MATCH (org:ORG)-[:Discloses]->(metric:FIN_METRIC)
WITH org, COUNT(DISTINCT metric) AS metrics_disclosed
WHERE metrics_disclosed > 50
MATCH (reg:ORG_REG)-[:Regulates]->(org)
WITH org.name AS organization, metrics_disclosed, COUNT(DISTINCT reg) AS regulator_count
WHERE regulator_count > 3
RETURN organization, regulator_count, metrics_disclosed
ORDER BY metrics_disclosed DESC
LIMIT 10
```

```aql
WITH Node
FOR org IN Node
  FILTER org.type == "ORG"
  FILTER org.name != null
  LIMIT 500
  FOR metric, disc_edge, disc_path IN 1..1 OUTBOUND org relations OPTIONS {parallelism: 3}
    FILTER disc_path.edges[*].type ALL == "discloses"
    FILTER disc_path.edges[*]._toType ALL == "FIN_METRIC"
    COLLECT org_id = org._id, org_name = org.name WITH COUNT INTO disclosure_count
    FILTER disclosure_count > 50
    LET regulator_count = LENGTH(
      FOR reg, reg_edge, reg_path IN 1..1 INBOUND org_id relations OPTIONS {parallelism: 3}
        FILTER reg_path.edges[*].type ALL == "regulates"
        FILTER reg_path.edges[*]._fromType ALL == "ORG_REG"
        RETURN 1)
    FILTER regulator_count > 3
    SORT disclosure_count DESC LIMIT 10
    RETURN {organization: org_name, regulator_count: regulator_count, metrics_disclosed: disclosure_count}
```

## 13. Organizations disclosing both revenue and cost metrics

**NL:** *"Which organizations disclose a revenue/income/profit metric and also a cost/expense/loss
metric (revenue-cost correlation)?"*

```cypher
MATCH (org:ORG)-[:Discloses]->(metric1:FIN_METRIC)
WHERE metric1.name =~ '(?i).*(revenue|income|profit).*'
WITH org, metric1 LIMIT 500
MATCH (org)-[:Discloses]->(metric2:FIN_METRIC)
WHERE metric2.name =~ '(?i).*(cost|expense|loss).*' AND metric2 <> metric1
RETURN org.name AS organization, metric1.name AS primary_metric,
       metric2.name AS correlated_metric, "Revenue-Cost" AS correlation_type
ORDER BY org.name
LIMIT 8
```

```aql
WITH Node
FOR metric1 IN Node
  FILTER metric1.type == "FIN_METRIC"
  FILTER metric1.name != null
  FILTER metric1.name LIKE "%revenue%" OR metric1.name LIKE "%income%" OR metric1.name LIKE "%profit%"
  LIMIT 8
  FOR org, disc_edge, p1 IN 1..1 INBOUND metric1 relations
    OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
    FILTER p1.edges[*].type ALL == "discloses"
    FILTER disc_edge._fromType == "ORG"
    FILTER org.name != null
    FOR metric2, disc_edge2, p2 IN 1..1 OUTBOUND org relations
      OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
      FILTER p2.edges[*].type ALL == "discloses"
      FILTER disc_edge2._toType == "FIN_METRIC"
      FILTER metric2._key != metric1._key
      FILTER metric2.name != null
      FILTER metric2.name LIKE "%cost%" OR metric2.name LIKE "%expense%" OR metric2.name LIKE "%loss%"
      SORT org.name LIMIT 8
      RETURN {organization: org.name, primary_metric: metric1.name,
              correlated_metric: metric2.name, correlation_type: "Revenue-Cost"}
```

## 14. Financial regulators and where their regulated organizations operate

**NL:** *"For financial regulators (SEC, Financial*, *Exchange*), which organizations do they
regulate and in which geographic locations do those organizations operate?"*

```cypher
MATCH (regulator:ORG_REG)-[:Regulates]->(org:ORG)-[:Operates_In]->(location:GPE)
WHERE regulator.name CONTAINS "SEC" OR regulator.name CONTAINS "Financial"
   OR regulator.name CONTAINS "Exchange"
RETURN regulator.name AS regulator_name, org.name AS regulated_organization,
       location.name AS geographic_location
ORDER BY regulator.name
LIMIT 10
```

```aql
WITH Node
FOR regulator IN Node
  FILTER regulator.type IN ["ORG_REG","REGULATORY_AGENCY"]
  FILTER regulator.name != null
  FILTER regulator.name LIKE "%sec%" OR regulator.name LIKE "%financial%" OR regulator.name LIKE "%exchange%"
  LIMIT 8
  FOR org, reg_edge, p1 IN 1..1 OUTBOUND regulator relations
    OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
    FILTER p1.edges[*].type ALL == "regulates"
    FILTER reg_edge._toType == "ORG"
    FILTER org.name != null
    FOR location, op_edge, p2 IN 1..1 OUTBOUND org relations
      OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
      FILTER p2.edges[*].type ALL == "operates_in"
      FILTER op_edge._toType IN ["GPE","COUNTRY"]
      FILTER location.name != null
      SORT regulator.name LIMIT 10
      RETURN {regulator_name: regulator.name, regulated_organization: org.name,
              geographic_location: location.name}
```

## 15. Apple's directly-related organizations

**NL:** *"What organizations are directly connected to Apple through supply, stake, or
operating-location relationships?"*

```cypher
MATCH (apple:ORG)
WHERE apple.name CONTAINS "Apple" OR apple.name CONTAINS "AAPL"
MATCH (apple)-[edge]-(related:ORG)
WHERE type(edge) IN ["Supplies","Has_Stake_In","Operates_In"]
RETURN apple.name AS apple_entity, type(edge) AS relationship, related.name AS related_entity
LIMIT 5
```

```aql
WITH Node
FOR apple IN Node
  FILTER apple.name == "aapl" OR apple.name LIKE "%apple%"
  FILTER apple.type == "ORG"
  FOR related, edge IN 1..1 ANY apple relations OPTIONS {parallelism: 4}
    FILTER edge.type IN ["supply","has_stake_in","operates_in"]   // Supplies -> supply (lemma)
    FILTER related.type == "ORG"
    LIMIT 5
    RETURN {apple_entity: apple.name, relationship: edge.type, related_entity: related.name}
```

## 16. Three-hop dependency chains

**NL:** *"Show 3-hop dependency chains starting from an organization (org depends on org depends
on org depends on org)."*

```cypher
MATCH path = (org:ORG)-[:Depends_On]->(:ORG)-[:Depends_On]->(:ORG)-[:Depends_On]->(:ORG)
RETURN org.name AS organization, [n IN nodes(path) | n.name] AS dependency_chain,
       LENGTH(path) + 1 AS chain_length
LIMIT 10
```

```aql
WITH Node
FOR org IN Node
  FILTER org.type == "ORG"
  FILTER org.name != null
  FOR target, edge, path IN 3..3 OUTBOUND org relations
    OPTIONS {parallelism: 4, uniqueVertices: "path", bfs: true}
    FILTER path.edges[*].type ALL == "depends_on"
    FILTER path.edges[*]._toType ALL == "ORG"
    LIMIT 10
    RETURN {organization: org.name, dependency_chain: path.vertices[*].name, chain_length: 4}
```

## 17. Disclosure-regulatory profile of major banks

**NL:** *"For a set of major firms (Apple, Microsoft, JPMorgan, Bank of America, Wells Fargo,
Goldman Sachs) that disclose more than 10 financial metrics, who regulates them and how many
other organizations does each regulator oversee?"*

```cypher
MATCH (org:ORG)
WHERE org.name IN ["AAPL","MSFT","JPM","BAC","WFC","GS"]
MATCH (org)-[:Discloses]->(metric:FIN_METRIC)
WITH org, COUNT(metric) AS disclosure_strength
WHERE disclosure_strength > 10
MATCH (regulator)-[:Regulates]->(org)
WHERE (regulator:ORG_REG OR regulator:REGULATORY_AGENCY) AND regulator.name IS NOT NULL
MATCH (regulator)-[:Regulates]->(other:ORG)
WITH org, disclosure_strength, regulator, COUNT(other) AS regulatory_scope
WHERE regulatory_scope > 0
RETURN org.name AS organization_name, disclosure_strength, regulator.name AS regulator_name,
       regulatory_scope, "Disclosure-Regulatory Chain" AS combined_impact
ORDER BY disclosure_strength DESC
LIMIT 5
```

```aql
WITH Node
FOR org IN Node
  FILTER org.type == "ORG"
  FILTER org.name != null
  FILTER org.name IN ["aapl","msft","jpm","bac","wfc","gs"]
  LET disclosure_strength = LENGTH(
    FOR metric, disc_edge, p1 IN 1..1 OUTBOUND org relations
      OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
      FILTER p1.edges[*].type ALL == "discloses"
      FILTER disc_edge._toType == "FIN_METRIC" RETURN 1)
  FILTER disclosure_strength > 10
  FOR regulator, reg_edge, p2 IN 1..1 INBOUND org relations
    OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
    FILTER p2.edges[*].type ALL == "regulates"
    FILTER reg_edge._fromType IN ["ORG_REG","REGULATORY_AGENCY"]
    FILTER regulator.name != null
    LET regulatory_scope = LENGTH(
      FOR other_org, other_reg_edge IN 1..1 OUTBOUND regulator relations
        FILTER other_reg_edge.type == "regulates" FILTER other_reg_edge._toType == "ORG" RETURN 1)
    FILTER regulatory_scope > 0
    SORT disclosure_strength DESC LIMIT 5
    RETURN {organization_name: org.name, disclosure_strength: disclosure_strength,
            regulator_name: regulator.name, regulatory_scope: regulatory_scope,
            combined_impact: "Disclosure-Regulatory Chain"}
```

## 18. Circular dependencies among organizations

**NL:** *"Are there circular dependency loops among organizations — where an org depends, through
2 to 4 hops, back on itself?"*

> Note: on FinReflectKG this unbounded scan-all-ORGs cycle search is **expensive** (it did not
> complete within 120 s in testing). Constrain the starting set (as in query 22) or add
> `uniqueVertices: "path"` for production use.

```cypher
MATCH path = (org:ORG)-[:Depends_On*2..4]->(org)
RETURN org.name AS organization, LENGTH(path) AS cycle_length,
       [n IN nodes(path) | n.name] AS cycle_participants
LIMIT 10
```

```aql
WITH Node
FOR org IN Node
  FILTER org.type == "ORG"
  FOR v, e, p IN 2..4 OUTBOUND org relations
    FILTER p.edges[*].type ALL == "depends_on"
    FILTER v._key == org._key
    LET cycle_participants = p.vertices[*].name
    LIMIT 10
    RETURN {organization: org.name, cycle_length: LENGTH(p.edges),
            cycle_participants: cycle_participants}
```

## 19. Temporal risk-impact chains

**NL:** *"Trace impact chains in time order: a risk factor negatively impacts an organization,
which then (on or after that date) depends on another organization that discloses a financial
metric."*

```cypher
MATCH (risk:RISK_FACTOR)-[imp:Negatively_Impacts]->(org1:ORG)
  -[dep:Depends_On]->(org2:ORG)-[disc:Discloses]->(metric:FIN_METRIC)
WHERE imp.start_date IS NOT NULL AND dep.start_date IS NOT NULL
  AND imp.start_date <= dep.start_date
RETURN
  risk.name + " -[Negatively_Impacts {" + imp.start_date + "}]-> " +
  org1.name + " -[Depends_On {" + dep.start_date + "}]-> " +
  org2.name + " -[Discloses]-> " + metric.name AS impact_chain,
  imp.context AS risk_context, dep.context AS dependency_context
LIMIT 15
```

```aql
WITH Node
FOR risk IN Node
  FILTER risk.type == "RISK_FACTOR"
  LIMIT 200
  FOR org1, neg_edge, neg_path IN 1..1 OUTBOUND risk relations OPTIONS {parallelism: 3}
    FILTER neg_path.edges[*].type ALL == "negatively_impacts"
    FILTER neg_path.edges[*]._toType ALL == "ORG"
    FILTER neg_edge.startDate != null
    FOR org2, dep_edge, dep_path IN 1..1 OUTBOUND org1 relations
      FILTER dep_path.edges[*].type ALL == "depends_on"
      FILTER dep_path.edges[*]._toType ALL == "ORG"
      FILTER dep_edge.startDate != null
      FILTER neg_edge.startDate <= dep_edge.startDate
      FOR metric, disc_edge, disc_path IN 1..1 OUTBOUND org2 relations
        FILTER disc_path.edges[*].type ALL == "discloses"
        FILTER disc_path.edges[*]._toType ALL == "FIN_METRIC"
        LIMIT 15
        RETURN {
          impact_chain: CONCAT(
            risk.name, " -[negatively_impacts {", neg_edge.startDate, "}]-> ",
            org1.name, " -[depends_on {", dep_edge.startDate, "}]-> ",
            org2.name, " -[discloses]-> ", metric.name),
          risk_context: neg_edge.extractionType,
          dependency_context: dep_edge.extractionType}
```

## 20. Location-based risk and disclosure profile

**NL:** *"For each location, find organizations operating there that are also negatively impacted
by a risk, and the financial metrics those organizations disclose."*

```cypher
MATCH (location:GPE)<-[:Operates_In]-(org:ORG)
MATCH (org)<-[:Negatively_Impacts]-(risk)
WHERE risk:RISK OR risk:RISK_FACTOR
MATCH (org)-[:Discloses]->(metric:FIN_METRIC)
RETURN location.name AS location, org.name AS organization,
       risk.name AS risk_factor, metric.name AS financial_metric
LIMIT 20
```

```aql
WITH Node
FOR location IN Node
  FILTER location.type == "GPE"
  FOR org, op_edge, op_path IN 1..1 INBOUND location relations OPTIONS {parallelism: 3}
    FILTER op_path.edges[*].type ALL == "operates_in"
    FILTER op_path.edges[*]._fromType ALL == "ORG"
    FOR risk, risk_edge, risk_path IN 1..1 INBOUND org relations
      FILTER risk_path.edges[*].type ALL == "negatively_impacts"
      FILTER risk.type IN ["RISK","RISK_FACTOR"]
      FOR metric, disc_edge, disc_path IN 1..1 OUTBOUND org relations
        FILTER disc_path.edges[*].type ALL == "discloses"
        FILTER disc_path.edges[*]._toType ALL == "FIN_METRIC"
        LIMIT 20
        RETURN {location: location.name, organization: org.name,
                risk_factor: risk.name, financial_metric: metric.name}
```

## 21. Two-hop metadata/context exploration

**NL:** *"For major tech firms (Apple, Microsoft, Google, Amazon), explore two hops out: what
entities they disclose/report/associate with, and what those entities in turn associate with or
are categorized under?"*

> Note: the legacy relationship/type vocabulary here (`Reports`, `Associates_With`, `Relates_To`,
> `Categorizes`; types `METADATA`, `ATTRIBUTE`, `CATEGORY`, `CLASSIFICATION`, `CONTEXT`) does
> **not exist in FinReflectKG**, so this faithful conversion returns no rows. A FinReflectKG-native
> version would use real relations (`discloses`, etc.) and types.

```cypher
MATCH (org:ORG)
WHERE org.name IN ["AAPL","MSFT","GOOGL","AMZN"]
MATCH (org)-[meta_edge]->(metadata)
WHERE type(meta_edge) IN ["Discloses","Reports","Associates_With"]
  AND (metadata:FIN_METRIC OR metadata:METADATA OR metadata:ATTRIBUTE)
MATCH (metadata)-[context_edge]->(context)
WHERE type(context_edge) IN ["Associates_With","Relates_To","Categorizes"]
  AND (context:CATEGORY OR context:CLASSIFICATION OR context:CONTEXT)
  AND context <> org AND context <> metadata
RETURN org.name AS organization, metadata.name AS metadata_entity,
       context.name AS contextual_entity,
       labels(metadata)[0] AS metadata_type, labels(context)[0] AS context_type
ORDER BY org.name
LIMIT 8
```

```aql
WITH Node
FOR org IN Node
  FILTER org.type == "ORG"
  FILTER org.name != null
  FILTER org.name IN ["aapl","msft","googl","amzn"]
  LIMIT 5
  FOR metadata, meta_edge, p1 IN 1..1 OUTBOUND org relations
    OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
    FILTER p1.edges[*].type ALL IN ["discloses","reports","associates_with"]
    FILTER meta_edge._toType IN ["FIN_METRIC","METADATA","ATTRIBUTE"]
    FILTER metadata.name != null
    FOR context, context_edge, p2 IN 1..1 OUTBOUND metadata relations
      OPTIONS {parallelism: 4, uniqueVertices: "global", bfs: true}
      FILTER p2.edges[*].type ALL IN ["associates_with","relates_to","categorizes"]
      FILTER context_edge._toType IN ["CATEGORY","CLASSIFICATION","CONTEXT"]
      FILTER context.name != null
      FILTER context._key != org._key
      FILTER context._key != metadata._key
      SORT org.name LIMIT 8
      RETURN {organization: org.name, metadata_entity: metadata.name,
              contextual_entity: context.name,
              metadata_type: metadata.type, context_type: context.type}
```

## 22. Circular dependencies among named big-tech firms

**NL:** *"Are there circular dependency chains of length 2–3 among Apple, Microsoft, Google,
Amazon, or Tesla?"*

```cypher
MATCH path = (org:ORG)-[:Depends_On*2..3]->(org)
WHERE org.name IN ["Apple Inc.", "Microsoft", "Google", "Amazon", "Tesla"]
WITH path, [n IN nodes(path) | n.name] AS organizations
WITH path, organizations, size(organizations) AS total_count,
     reduce(unique = [], name IN organizations |
       CASE WHEN name IN unique THEN unique ELSE unique + name END) AS unique_names
WHERE total_count = size(unique_names) + 1
RETURN
  [i IN range(0, length(path)-1) |
    startNode(relationships(path)[i]).name + " -[Depends_On]-> " +
    endNode(relationships(path)[i]).name
  ] AS circular_chain
LIMIT 5
```

```aql
WITH Node
LET major_companies = ["aapl","msft","googl","amzn","tsla"]   // legacy names -> FinReflectKG tickers
FOR org IN Node
  FILTER org.type == "ORG"
  FILTER org.name IN major_companies
  FOR v, e, p IN 2..3 OUTBOUND org relations
    FILTER p.edges[*].type ALL == "depends_on"
    FILTER v._key == org._key
    LET organizations = p.vertices[*].name
    LET unique_orgs = UNIQUE(organizations)
    FILTER LENGTH(organizations) == LENGTH(unique_orgs) + 1
    LET circular_chain = (FOR i IN 0..(LENGTH(p.edges)-1)
      RETURN CONCAT(p.vertices[i].name, " -[depends_on]-> ", p.vertices[i+1].name))
    LIMIT 5
    RETURN {circular_chain: circular_chain}
```

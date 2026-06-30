---
name: aql-arangodb-mcp
description: Writes and executes ArangoDB AQL using the Arango MCP server with a manual-first workflow (AQL reference + optimization), safe parameterization (bind vars), and a validate-then-scale approach. Use when the user asks for AQL, Arango queries, graph traversals, ArangoSearch queries, or wants to run queries via the Arango MCP server.
---

# AQL with Arango MCP (manual-first, optimized, safe)

This skill standardizes how to explore ArangoDB and write/execute AQL via the **Arango MCP server**.

## Non-negotiable workflow (required by the MCP server)

Before writing or executing any AQL:

1. Fetch `aql_ref` manual.
2. Fetch `optimization` manual.
3. Only then draft AQL (with bind vars) and execute.

## Default safety posture

- Prefer **read-only** queries (`FOR…FILTER…RETURN`) unless the user explicitly requests writes.
- Use **bind variables** instead of string interpolation.
- Start with a small **LIMIT** and widen after validating shape/performance.

## Quick start (what to do when asked for "an AQL query")

1. **Identify target DB** (default is fine if unspecified).
2. **Inventory** (as needed):
   - list databases
   - list collections (document vs edge)
   - list graphs / views / analyzers (if relevant)
3. Fetch manuals (`aql_ref` then `optimization`).
4. Draft the query with:
   - bind vars
   - early FILTERs
   - explicit LIMIT (initially)
   - deterministic SORT (when returning top-N)
5. Execute; if results are wrong/slow:
   - refine query
   - consider indexes / alternative patterns from optimization manual

## Performance checklist (apply from optimization manual)

- **Filter early**: `FILTER` as close to the `FOR` as possible.
- **Avoid full scans** on large collections; rely on selective filters and indexes.
- **Prefer edge-index filtering** for graph patterns (avoid "vertex-centric" scans).
- Use **projections**: return only fields needed (`RETURN {a: doc.a, ...}`).
- Use small `LIMIT` while iterating.

## Common patterns (templates)

### 1) Basic filtered query (parameterized)

```aql
FOR d IN @@col
  FILTER d.type == @type
  SORT d.createdAt DESC
  LIMIT @limit
  RETURN d
```

Bind vars:
- `@col`: collection name
- `type`: string
- `limit`: number

### 2) Existence / counts

```aql
RETURN {
  total: LENGTH(@@col),
}
```

Prefer `COLLECT WITH COUNT INTO` or dedicated count patterns from docs when scaling.

### 3) One-hop traversal (edge collection)

```aql
FOR v, e IN 1..1 OUTBOUND @start @@edgeCol
  LIMIT @limit
  RETURN {v, e}
```

Use bind vars:
- `start`: vertex `_id` (e.g. `"DeviceProxyIn/tenant1:device1"`)
- `@edgeCol`: edge collection name

### 4) Named graph traversal

```aql
FOR v, e, p IN 1..@maxDepth OUTBOUND @start GRAPH @graphName
  LIMIT @limit
  RETURN p
```

## Output expectations

When producing an AQL query, include:
- the AQL string
- the bind vars object
- what it returns (shape)
- any index assumptions / performance notes

---

## Project-specific: time travel queries

This project uses the **immutable-proxy time travel** pattern (see global skill `arangodb-temporal-graph` for full architecture). Key facts for writing AQL:

### Collections

| Role | Collection | Temporal? |
|------|-----------|-----------|
| Device proxy (inbound) | `DeviceProxyIn` | No |
| Device proxy (outbound) | `DeviceProxyOut` | No |
| Device (versioned) | `Device` | Yes (`created`/`expired`) |
| Software proxy (inbound) | `SoftwareProxyIn` | No |
| Software proxy (outbound) | `SoftwareProxyOut` | No |
| Software (versioned) | `Software` | Yes (`created`/`expired`) |
| Version edges | `hasVersion` | Yes (`created`/`expired`) |
| Classification | `Class` (satellite), `type` edges | No |

### Sentinel value

```
NEVER_EXPIRES = 9223372036854775807  (sys.maxsize)
```

- `expired == 9223372036854775807` means "current/active"
- `expired < 9223372036854775807` means "historical/superseded"

### Point-in-time snapshot

```aql
FOR d IN Device
  FILTER d.tenantId == @tenantId
  FILTER d.created <= @timestamp AND d.expired > @timestamp
  RETURN d
```

This leverages the MDI-prefixed index `idx_device_mdi_temporal`.

### Version history traversal

```aql
FOR proxy IN DeviceProxyIn
  FILTER proxy._key == @deviceProxy
  FOR v, e IN 1..1 OUTBOUND proxy hasVersion
    SORT e.created DESC
    RETURN {
      version: v.name,
      created: e.created,
      expired: e.expired,
      isCurrent: e.expired == 9223372036854775807
    }
```

### Temporal overlap (entities active during a window)

```aql
FOR d IN Device
  FILTER d.tenantId == @tenantId
  FILTER d.created <= @endTime AND d.expired >= @startTime
  RETURN d
```

---

## Project-specific: SmartGraph and multi-tenant patterns

### Graph names

- **`network_assets_smartgraph`** -- data graph (SmartGraph, `smart_field="tenantId"`)
- **`taxonomy_satellite_graph`** -- taxonomy hierarchy (`Class` -> `subClassOf` -> `Class`)

### WITH clause (required on cluster)

On clustered deployments, traversals and cross-collection queries require a `WITH` clause. Include all vertex and edge collections that may be accessed:

```aql
WITH Class, Device, DeviceProxyIn, DeviceProxyOut, Location, Software,
     SoftwareProxyIn, SoftwareProxyOut, Alert,
     hasConnection, hasLocation, hasDeviceSoftware, hasVersion, hasAlert, type
FOR node IN @nodes
  FOR v, e IN 1..2 ANY node GRAPH "network_assets_smartgraph"
  LIMIT 100
  RETURN e
```

### Tenant filtering

Always filter by `tenantId` early to leverage SmartGraph sharding:

```aql
FOR d IN Device
  FILTER d.tenantId == @tenantId
  // ... rest of query
```

### Satellite -> SmartGraph traversals (tenant-aware vertex-centric index)

Traversals that **start at a satellite vertex** (e.g. a `Class`) and go INTO the
SmartGraph (e.g. `INBOUND c type` to find tenant entities) **cannot** be pruned
by SmartGraph sharding -- the start vertex has no `tenantId`. Without help,
the engine reads every `type` edge that points at the satellite and
dereferences each target to filter by tenant.

`type` edges anchor at `DeviceProxyOut` / `SoftwareProxyOut` (the stable
per-entity identities), not at versioned `Device` / `Software` documents.
This survives version churn -- a configuration change does not reclassify
the device, and historical-version TTL aging does not orphan the type-edge.

The deployment creates a vertex-centric persistent index `idx_type_to_tenantid`
on `(_to, tenantId)` for exactly this case. To get the planner to use it, the
tenant filter must be expressed on the **path**, not on the edge variable:

```aql
// GOOD -- promotes to idx_type_to_tenantid (single index seek per tenant).
// The traversal lands at DeviceProxyOut / SoftwareProxyOut.
WITH Class, DeviceProxyOut, SoftwareProxyOut, type
FOR c IN Class
  FILTER c.classKey == @classKey
  FOR v, e, p IN 1..1 INBOUND c type
    FILTER p.edges[*].tenantId ALL == @tenantId
    RETURN v   // proxy; INBOUND hasVersion to fetch the current Device/Software
```

```aql
// SUBOPTIMAL -- falls back to the primary edge index, scans every tenant
FOR v, e IN 1..1 INBOUND c type
  FILTER e.tenantId == @tenantId
  RETURN v
```

If the optimizer doesn't pick the index automatically (older builds, depth > 1),
hint it explicitly:

```aql
FOR v, e, p IN 1..1 INBOUND c type
  OPTIONS { indexHint: { type: { inbound: { base: 'idx_type_to_tenantid' } } } }
  FILTER p.edges[*].tenantId ALL == @tenantId
  RETURN v
```

The matching `(_from, tenantId)` index (`idx_type_from_tenantid`) accelerates
`OUTBOUND` traversals from a `DeviceProxyOut` / `SoftwareProxyOut` to its
`Class` (e.g. "what is this device classified as?").

#### Going from `Class` to the live `Device` / `Software` in one step

Because classifications anchor at the proxy, drilling from the satellite all
the way down to the **current** versioned configuration takes two hops:
`type` (satellite -> proxy) and then `hasVersion` (proxy -> versioned doc).

In ArangoDB 3.12.x cluster mode, **do not** express this as two nested
`FOR ... INBOUND` traversals -- the optimizer trips on
`SingleServerEdgeCursor.cpp:227 index conditions ... should not be empty`.
Use a single **multi-edge traversal** instead:

```aql
// GOOD -- one traversal, two edge collections, no chained-FOR bug.
FOR cls IN Class
  FILTER cls.name == @className
  FOR v, e, p IN 2..2 INBOUND cls type, hasVersion
    FILTER LENGTH(p.edges) == 2
    FILTER p.edges[0].tenantId == @tenantId      // engages idx_type_to_tenantid
    FILTER IS_SAME_COLLECTION('Device', v)
    FILTER v.expired == 9223372036854775807       // current version only
    RETURN v
```

```aql
// BAD -- triggers ArangoDB 3.12.x optimizer bug
FOR cls IN Class
  FILTER cls.name == @className
  FOR proxy IN 1..1 INBOUND cls type
    FOR device IN 1..1 INBOUND proxy hasVersion   // <-- engine error here
      RETURN device
```

### IS_SAME_COLLECTION (filtering traversal results)

When traversing a graph and you only want results from a specific collection:

```aql
FOR v, e, p IN 1..2 OUTBOUND @start GRAPH "network_assets_smartgraph"
  FILTER IS_SAME_COLLECTION("Software", v)
  RETURN v
```

### Canvas action pattern (for Graph Visualizer)

Canvas actions receive selected nodes as `@nodes`. Return edges or paths (not just vertices) for the Visualizer to render graph expansions:

```aql
WITH Class, Device, DeviceProxyIn, DeviceProxyOut, Location,
     hasConnection, hasLocation, hasVersion, type
FOR node IN @nodes
  FOR v, e IN 1..2 ANY node GRAPH "network_assets_smartgraph"
  LIMIT 100
  RETURN e
```

---

## Project-specific: MDI index-aware patterns

### Available MDI-prefixed indexes

| Collection | Index name | Fields |
|-----------|-----------|--------|
| `Device` | `idx_device_mdi_temporal` | `[created, expired]` |
| `Software` | `idx_software_mdi_temporal` | `[created, expired]` |
| `hasVersion` | `idx_version_mdi_temporal` | `[created, expired]` |

All use `fieldValueTypes: "double"` and `prefixFields: ["created"]`.

### Writing MDI-friendly filters

For the MDI-prefixed index to be used effectively, include both `created` and `expired` in your FILTER:

```aql
// Good: both fields present -> MDI-prefixed index used
FILTER d.created <= @ts AND d.expired > @ts

// Suboptimal: only one field -> index may not be fully utilized
FILTER d.created <= @ts
```

### Verifying index usage in execution plans

When debugging slow temporal queries, check if the MDI-prefixed index is being used:

```python
plan = db.aql.explain(query, bind_vars=bind_vars)
for node in plan.get('plan', {}).get('nodes', []):
    if node.get('type') == 'IndexNode':
        for idx in node.get('indexes', []):
            # MDI-prefixed indexes appear as type "zkd" in plans
            if idx.get('type') == 'zkd':
                print(f"MDI index used: {idx.get('name')}")
```

---

## Examples

See `examples.md` for the full set of working query examples from this project, including all 10 saved visualizer queries.

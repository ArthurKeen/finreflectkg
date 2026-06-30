# Schema Mapping — `financial-kg-2025-08-26` (legacy) ↔ `FinReflectKG`

**Status:** v1.0 · 2026-06-15
**Purpose:** Reference for transforming AQL that runs on the legacy ArangoDB
graph `financial-kg-2025-08-26` so it runs on `FinReflectKG` (this POC's graph).
A batch of such AQL queries is expected; this is the field-by-field map.
**Related:** [cypher-queries.md](cypher-queries.md) · [load-report.md](load-report.md)

Both graphs are the same single-collection LPG concept (one node collection,
one edge collection, VCIs on `(_from|_to, reltype, far-type)`). They differ in
**collection names, key scheme, field names, and value casing.**

## Collections

| Concept | legacy `financial-kg-2025-08-26` | `FinReflectKG` |
|---|---|---|
| Nodes | `entities` (2,101,910) | `Node` (3,099,773) |
| Edges | `relations` (14,833,474) | `relations` (17,513,372) |
| Source text | `chunks` (1,036,586) | `chunks` (1,384,513) |

> Note the **counts differ** — these are different dataset snapshots (legacy ≈
> S&P 100 / 14.8 M edges; FinReflectKG = full 17.5 M). Query *shapes* port over;
> absolute results will not match exactly.

## Node fields (`entities` → `Node`)

| legacy `entities` | `FinReflectKG` `Node` | Notes |
|---|---|---|
| `_key` (= ticker for ORG, e.g. `CTAS`; else normalized name `Proxy_Statement`) | `_key` = `md5(name`&#124;`type)` | **keys are NOT portable** — never join on `_key` literals across graphs |
| `name` | `name` | legacy ORG `name` is often the ticker; FinReflectKG `name` is the normalized entity (lowercased, e.g. `ctas`) |
| `type` (dominant type) | `type` | same semantics |
| `all_types` (stringified list) | — | dropped in FinReflectKG (one node per `(name,type)`) |
| `type_counts` (stringified dict) | — | dropped |
| `id` (Neo4j ticker; in AQL usually `_key`) | no `id` field | resolve ORGs by `name`/`ticker`, not `id` |

**Casing:** legacy `type` values are UPPER (`ORG`, `FIN_METRIC`); FinReflectKG
types are also UPPER — **same**. But entity **names**: legacy keeps mixed/ticker
case; FinReflectKG names are **lowercased & lemmatized** (`united state`,
`net income`). Filters on `name` must adjust case/lemma.

## Edge fields (`relations` → `relations`)

| legacy `relations` | `FinReflectKG` `relations` | Notes |
|---|---|---|
| `relation` (e.g. `Discloses`, `Has_Stake_In`) | `type` (e.g. `discloses`, `has_stake_in`) | **field renamed AND value lowercased** — the single most common edit |
| `sourceType` (e.g. `ORG`) | `_fromType` | VCI field |
| `destinationType` (e.g. `FIN_METRIC`) | `_toType` | VCI field |
| `start_date` (`"December 2019"`) | `startDate` (`"2019-12"`, sortable) + `startDateRaw` (original) | format changed; use `startDate` for ordering, `startDateRaw` for the original string |
| `end_date` (`"December 2019"`) | `endDate` / `endDateRaw` | same; `null`/`default_end_timestamp` → `endDate` is null |
| `context` (`"extracted"`/`"default"`) | `extractionType` | renamed |
| `chunk_key` | `chunkKey` | renamed (camelCase) |
| `chunk_id`, `page_id`, `source_file` | `pageId`, `sourceFile` (+ `chunkKey`); `chunk_id` folded into `chunkKey` | renamed |
| `timestamp` | — | not carried; use `startDate` |
| `_from`/`_to` → `entities/…` | `_from`/`_to` → `Node/…` | collection in the id string changes |

## Indexes (both have the VCI pattern, different field names)

| legacy | FinReflectKG |
|---|---|
| `[_from, relation, destinationType]` | `[_from, type, _toType]` (`vci_from_type_totype`) |
| `[_to, relation, sourceType]` | `[_to, type, _fromType]` (`vci_to_type_fromtype`) |
| `[name]`, fulltext/inverted on `name` | `[name]` (`node_name`), `[type]` |
| `[start_date]`, `[timestamp]`, `[relation]` | `[ticker, year]`; no standalone `type`/`startDate` index yet |

## AQL transformation checklist (legacy → FinReflectKG)

1. `entities` → `Node`; `_from`/`_to` `entities/X` → `Node/X` (but keys differ —
   don't port literal keys; re-resolve by `name`).
2. `e.relation` → `e.type`; **lowercase the value** (`'Discloses'` → `'discloses'`,
   `'Has_Stake_In'` → `'has_stake_in'`).
3. `e.sourceType` → `e._fromType`; `e.destinationType` → `e._toType`.
4. `e.context` → `e.extractionType`; `e.chunk_key` → `e.chunkKey`;
   `e.source_file` → `e.sourceFile`; `e.page_id` → `e.pageId`.
5. Dates: `e.start_date`/`e.end_date` → `e.startDate`/`e.endDate` (now `YYYY-MM`,
   sortable) — adjust any string-format comparisons; original strings are in
   `*Raw`.
6. Entity name filters: lowercase / lemma-adjust (`'United States'` →
   `'united state'`, `'Net Income'` → `'net income'`); ORG lookups by ticker use
   `name` (FinReflectKG has no `id`).
7. Keep the VCI access pattern: typed 1-hop as **direct edge queries**
   (`FOR e IN relations FILTER e._from==… AND e.type==… AND e._toType==…`), since
   pattern traversals don't use the VCIs here (see load-report.md).

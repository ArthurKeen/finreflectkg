# Build Brief — `FinReflectKgSmart` (Disjoint SmartGraph) · handoff for Claude Code

**Status:** built & verified · 2026-07-05 (`scripts/build_smart.sh`; 6,658,668 nodes /
17,513,372 edges / 1,384,513 chunks; VCIs built; disjoint shard-locality confirmed)
**Design:** locked — **Design 2, Disjoint SmartGraph sharded by `ticker`** (see
[multi-distribution-plan.md](multi-distribution-plan.md) §5, esp. §5.3–§5.7).
**Context docs to read first:** [multi-distribution-plan.md](multi-distribution-plan.md)
(§5 is the design), [etl-plan.md](etl-plan.md) (the existing pipeline you are
extending), [data-analysis.md](data-analysis.md) (data shape), [load-report.md](load-report.md)
(VCI fast-path finding), [schema-mapping.md](schema-mapping.md) (field semantics).
Follow the `aql` skill's manual-first workflow for any AQL.

## 0. Objective

Build a third database, `FinReflectKgSmart`, holding the **same FinReflectKG data**
as the existing `FinReflectKG` / `FinReflectKgOneShard`, but as a **Disjoint
SmartGraph** so the text-to-graph tooling (which requires a SmartGraph) gets
**per-company co-location**: each company's nodes, edges, **and its source-text
`chunks`** live on the same shard.

Do **not** touch the existing `FinReflectKG` or `FinReflectKgOneShard` databases, and
do **not** read/write the unrelated app collections on the endpoint (`aga_*`,
`benchmark_*`, `arango_cypher_schema_cache`). Everything goes in the new database.

## 1. The model (what changes vs. the baseline)

Same LPG schema (`Node` / `relations` / `chunks`, fields per `schema-mapping.md`), but:

- **Smart attribute = `ticker`** (lowercased), on every node, edge, and chunk.
- **Node keys become per-company:** `_key = "<ticker>:<md5(name|type)>"`. A node shared
  by N companies is **duplicated** into N copies, one per referencing ticker. Expected
  node count ≈ **6.66 M (2.1×)**; edges are **not** duplicated (still 17.51 M).
- **Edge endpoints point at the per-ticker copies**, using the **edge's own `ticker`**
  for *both* `_from` and `_to` (safe: cross-company references are 0.00%).
- **`chunks` is smart-sharded by `ticker`** too (key prefixed with `<ticker>:`), and
  edges' `chunkKey` is rewritten to match — so text co-locates with its subgraph.

Rationale, trade-offs, and the rejected alternative (Design B / satellites) are in
`multi-distribution-plan.md` §5.

## 2. Preconditions (already in place)

- `.env` has the cluster connection (`ARANGO_ENDPOINT`, `ARANGO_USER`,
  `ARANGO_PASSWORD`, …). 3.12.x **Enterprise** cluster (SmartGraph needs Enterprise).
- All 103 parquet shards present at `data/raw/data/train-*.parquet`.
- Pipeline is **already parameterized** (done in the OneShard build):
  - `scripts/arango.py` overlays real env vars over `.env`, so `ARANGO_DB=… python …`
    retargets any script.
  - `scripts/setup_db.py` honors `ARANGO_DB_SHARDING`, `ARANGO_REPLICATION_FACTOR`,
    `ARANGO_WRITE_CONCERN`.
  - `scripts/create_graph.py` / `scripts/check_sharding.py` honor `ARANGO_GRAPH`.
  - `scripts/import.sh` honors a pre-set `ARANGO_DB`.
  - `scripts/create_indexes.py` builds the 2 VCIs + `node_name` + `node_type` +
    `rel_ticker_year` from the target db — reuse unchanged.
- Reference: `scripts/build_oneshard.sh` is the orchestrator pattern to copy.

## 3. Build steps

### Step 1 — New preprocessing: `scripts/preprocess_smart.py`

Clone `scripts/preprocess.py` and change the key/duplication logic. All in DuckDB over
`data/raw/data/train-*.parquet`, output to `data/staging/smart/`. Use **`lower(ticker)`
everywhere** for the smart value (must be identical across nodes, edges, chunks).

- **nodes_smart.jsonl** — one row per `(name, type, ticker)`:
  ```sql
  SELECT DISTINCT
    lower(ticker) || ':' || md5(name || '|' || type) AS "_key",
    name, type, lower(ticker) AS ticker
  FROM (
    SELECT entity AS name, COALESCE(NULLIF(entity_type,''),'UNKNOWN') AS type, ticker FROM src
    UNION
    SELECT target, COALESCE(NULLIF(target_type,''),'UNKNOWN'), ticker FROM src
  )
  ```
  (The DISTINCT over `(name,type,ticker)` naturally emits one copy per referencing
  company: single-ticker nodes → 1 row, shared → N rows.)

- **relations_smart/*.json** (split ~512 MB) — endpoints rewritten to per-ticker keys:
  ```sql
  SELECT
    triplet_id AS "_key",                       -- see Step 4 gotcha re: smart edge keys
    'Node/' || lower(ticker) || ':' || md5(entity || '|' || COALESCE(NULLIF(entity_type,''),'UNKNOWN')) AS "_from",
    'Node/' || lower(ticker) || ':' || md5(target || '|' || COALESCE(NULLIF(target_type,''),'UNKNOWN')) AS "_to",
    relationship AS type,
    COALESCE(NULLIF(entity_type,''),'UNKNOWN') AS "_fromType",
    COALESCE(NULLIF(target_type,''),'UNKNOWN') AS "_toType",
    lower(ticker) AS ticker, year,
    strftime(try_strptime(start_date,'%B %Y'),'%Y-%m') AS "startDate",
    strftime(try_strptime(end_date,'%B %Y'),'%Y-%m')   AS "endDate",
    start_date AS "startDateRaw", end_date AS "endDateRaw",
    extraction_type AS "extractionType", source_file AS "sourceFile", page_id AS "pageId",
    CASE WHEN has_context
      THEN lower(ticker) || ':' || md5(ticker || '|' || CAST(year AS VARCHAR) || '|' || page_id || '|' || chunk_id)
      ELSE NULL END AS "chunkKey"
  FROM src
  ```

- **chunks_smart.jsonl** — key prefixed with `<ticker>:`, must match `chunkKey` above:
  ```sql
  SELECT
    lower(ticker) || ':' || md5(ticker || '|' || CAST(year AS VARCHAR) || '|' || page_id || '|' || chunk_id) AS "_key",
    lower(ticker) AS ticker, any_value(year) AS year, any_value(page_id) AS "pageId",
    any_value(chunk_id) AS "chunkId", any_value(source_file) AS "sourceFile",
    any_value(chunk_text) AS text
  FROM src WHERE has_context
  GROUP BY 1, lower(ticker)
  ```
  **Critical:** the inner `md5(ticker|year|page|chunk)` expression must be byte-identical
  between `chunks_smart._key` and `relations_smart.chunkKey` (note `ticker` here is the
  **raw** column inside the md5, only the prefix is lowercased — keep it consistent in
  both queries; simplest is to lowercase ticker in the md5 too, but do it in *both*).

### Step 2 — Create the database (flexible, NOT OneShard)

```bash
ARANGO_DB=FinReflectKgSmart ARANGO_REPLICATION_FACTOR=2 python3 scripts/setup_db.py
```
Do **not** set `ARANGO_DB_SHARDING=single`. `setup_db.py` also creates plain
`Node`/`relations`/`chunks` — for the smart build, **delete those and let the graph
create the smart collections instead** (Step 3), OR adjust `setup_db.py` to skip
collection creation when `ARANGO_SMART=1`. Cleanest: add an env guard so it only
creates the database, then the graph create makes the smart collections.

### Step 3 — Create the Disjoint SmartGraph: `scripts/create_smart_graph.py`

New script (HTTP `POST /_api/gharial`). This creates the smart `Node` + `relations`
with the right sharding. Add `chunks` as a **smart orphan** so it co-locates by ticker.
```jsonc
POST /_api/gharial
{ "name": "FinReflectKgSmart",
  "edgeDefinitions": [ { "collection": "relations", "from": ["Node"], "to": ["Node"] } ],
  "orphanCollections": ["chunks"],
  "options": { "smartGraphAttribute": "ticker", "isDisjoint": true,
               "numberOfShards": 9, "replicationFactor": 2 } }
```
- `numberOfShards`: **9** unless specified otherwise (re-tune per §5.7).
- If gharial won't make `chunks` smart as an orphan in your build, create `chunks`
  separately with `shardKeys:["ticker"]` + `distributeShardsLike:"Node"` so it still
  co-locates by ticker.

### Step 4 — Pilot import (MANDATORY gate before the full run)

⚠️ **Smart edge key handling is the #1 risk.** SmartGraph edge collections may require
edge `_key`s in a specific encoded form and derive the shard from the `_from`/`_to`
smart prefixes. **Before the full import, pilot one source shard** (shard 0 = 8
tickers):
```bash
python3 scripts/preprocess_smart.py --input "data/raw/data/train-00000-of-00103.parquet" --out data/staging/smart_pilot
ARANGO_DB=FinReflectKgSmart ./scripts/import.sh Node   smart_pilot/nodes_smart.jsonl --threads 8
ARANGO_DB=FinReflectKgSmart ./scripts/import.sh chunks smart_pilot/chunks_smart.jsonl --threads 8
ARANGO_DB=FinReflectKgSmart ./scripts/import.sh relations 'smart_pilot/relations_smart/*.json' --threads 8
```
Verify on the pilot: **0 rejected docs**, edges resolve (`_from`/`_to` DOCUMENT lookups
non-null), `chunkKey` resolves, and a one-company query stays on one shard (`explain`
→ no `RemoteNode`). If edges are rejected on `_key`, switch to letting ArangoDB manage
edge keys (drop the provided `_key`, or use the `<from>:<userkey>:<to>` form ArangoDB
expects) and re-pilot. **Only proceed to the full run once the pilot is clean.**

### Step 5 — Full import

```bash
python3 scripts/preprocess_smart.py --input "data/raw/data/train-*.parquet" --out data/staging/smart --split-bytes 512MB
ARANGO_DB=FinReflectKgSmart THREADS=16 ./scripts/import_full.sh   # point its file paths at smart/*
```
(Adjust `import_full.sh` file names to the `smart/` staging dir + `*_smart` files, or
parameterize it.)

### Step 6 — Indexes

```bash
ARANGO_DB=FinReflectKgSmart python3 scripts/create_indexes.py
```
Same 2 VCIs + `node_name` + `node_type` + `rel_ticker_year`, unchanged.

### Step 7 — Validate + monitor (per §5.7)

- Counts: nodes ≈ 6.66 M, relations = 17,513,372, chunks = 1,384,513.
- Referential integrity (sampled): `_from`/`_to`/`chunkKey` all resolve.
- Graph: `GET /_api/gharial/FinReflectKgSmart` → `smartGraphAttribute=="ticker"`,
  `isDisjoint==true`; collections `isSmart==true`, sharded by `ticker`.
- Locality: `explain` a company-scoped query (subgraph **and** its chunks) → **no
  `RemoteNode`**.
- Shard balance: no single shard dominates (watch big filers `etr`/`pru`/`met`).
- Adapt `scripts/validate.py` (the smart node count differs; add the graph-attribute +
  locality assertions).

### Step 8 — Orchestrator

Write `scripts/build_smart.sh` mirroring `scripts/build_oneshard.sh`: preprocess_smart
→ setup_db → create_smart_graph → import_full → create_indexes → validate →
check_sharding. Make it idempotent and resumable.

## 4. Acceptance criteria

1. `FinReflectKgSmart` exists; graph `FinReflectKgSmart` is a **disjoint smart graph**,
   smart attribute `ticker`; `Node`/`relations`/`chunks` are smart, sharded by `ticker`.
2. Counts reconcile (nodes ≈6.66 M, edges 17,513,372, chunks 1,384,513); 0 import errors.
3. A representative per-company query (entities + edges + their `chunks`) executes with
   **no `RemoteNode`** in `explain` — i.e. text is co-located with its subgraph.
4. Existing `FinReflectKG` and `FinReflectKgOneShard` untouched; no `aga_*`/`benchmark_*`
   collections read or written.
5. Build is reproducible via `scripts/build_smart.sh`.

## 5. Watch-outs (don't skip)

- **Smart values must match exactly** across node `_key` prefix, edge `_from`/`_to`
  prefixes, edge/chunk `ticker` field, and chunk `_key` prefix — all `lower(ticker)`.
- **Edge `_key` form** for smart edge collections — validate on the pilot (Step 4).
- **chunkKey ↔ chunks._key** must be byte-identical (Step 1 critical note).
- Keys are immutable; a wrong prefix = full re-import, so the pilot gate matters.
- Latency on the shared cluster is noisy — use scanned-edge counts + `explain`
  shard-locality as the deterministic metrics (per `load-report.md`).
- Update `docs/multi-distribution-plan.md` §5 status and `docs/PRD.md` (G7/M6) to
  "built & verified" when done.

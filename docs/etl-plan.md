# ETL Plan — FinReflectKG → ArangoDB

**Status:** Draft v0.1 · 2026-06-12
**Related docs:** [PRD.md](PRD.md) · [data-analysis.md](data-analysis.md)

> **Executed 2026-06-15 — full dataset loaded & validated.** Results, timings,
> and the VCI / cluster-sharding findings are in [load-report.md](load-report.md).

Pipeline: **Download (Hugging Face) → Preprocess (DuckDB → JSONL) → Provision
(DB/collections) → Bulk import (`arangoimport` in Docker) → Index → Validate.**

All stages are idempotent and re-runnable; every generated document has a
deterministic `_key`, so a re-import is a no-op (`--on-duplicate ignore`) or a
repair (`replace`), never a duplicate.

## Tooling decision

| Option | Verdict |
|---|---|
| `arangoimport` from the official `arangodb` Docker image | **Primary.** Mature, parallel, JSONL-native, supports `--on-duplicate`, runs against the remote TLS endpoint |
| `arangox` (Rust, `~/code/arango-data-tools-rs`) | Import library is complete (async, batched, backpressured) but the CLI is not yet wired, and there is no parquet support or collection/index creation. **Revisit when the CLI lands** — this POC is a good first workload; the preprocessed JSONL produced below will work with it unchanged |
| DuckDB (Python venv `.venv`) | Preprocessing engine — parquet-native, streams larger-than-memory, writes JSONL directly |

Provisioning (database, collections, indexes) is done with small Python
scripts calling the ArangoDB HTTP API, driven by `.env`.

## Stage 1 — Download

Script: `scripts/download.py` (huggingface_hub `snapshot_download`)

- Pulls the 103 parquet shards (~1.67 GB) + `README.md` to `data/raw/`
  (gitignored).
- Resumable; re-run to verify/complete. `max_workers=4` to stay under HF rate
  limits (remote DuckDB scanning hit HTTP 429, which is why we download once
  rather than stream).
- **Exit check:** 103 files present; `SELECT count(*)` over
  `data/raw/data/*.parquet` = **17,513,372**.

## Stage 2 — Preprocess (DuckDB → JSONL)

Script: `scripts/preprocess.py`. Three outputs in `data/staging/`
(gitignored). DuckDB streams; nothing requires the ~50 GB decompressed
dataset in memory.

### 2.1 `nodes.jsonl` — collection `Node`

One document per distinct `(name, type)` over the union of
`(entity, entity_type)` and `(target, target_type)`:

```sql
SELECT DISTINCT
  md5(name || '|' || type) AS _key,
  name, type
FROM (
  SELECT entity AS name, entity_type AS type FROM src
  UNION
  SELECT target, target_type FROM src
);
```

- `_key` is an MD5 hex digest because raw names are not key-safe (91% of rows
  contain `/`, spaces, etc.) and ArangoDB keys must be ASCII-safe. MD5 over
  ~3 M short strings has no practical collision risk and keeps keys
  reproducible across runs.
- Node identity is `(name, type)`: ~14% of names occur with more than one type
  (e.g. as both `ORG` and `COMP`); they become distinct nodes, consistent with
  edges carrying `_fromType`/`_toType`. Expected count: **3,099,773** nodes.
- 58 rows have an empty `target_type` → coalesce to `'UNKNOWN'` (applies to
  node `type` and edge `_toType`).

### 2.2 `chunks.jsonl` — collection `chunks`

`chunk_text` averages ~2.9 KB and is repeated for every triple extracted from
the same chunk (≈12× in sampling). Deduplicate on the natural chunk identity:

```sql
SELECT
  md5(ticker || '|' || year || '|' || page_id || '|' || chunk_id) AS _key,
  any_value(ticker) ticker, any_value(year) year,
  any_value(page_id) pageId, any_value(chunk_id) chunkId,
  any_value(source_file) sourceFile,
  any_value(chunk_text) text
FROM src
WHERE has_context
GROUP BY 1;
```

Expected ~1.4 M chunks ≈ 4–5 GB of text instead of ~50 GB inlined on edges.

### 2.3 `relations-*.jsonl` — collection `relations`

One edge per source row (17.51 M), `_key = triplet_id` (verified key-safe and
unique):

```sql
SELECT
  triplet_id AS _key,
  'Node/' || md5(entity || '|' || entity_type)  AS _from,
  'Node/' || md5(target || '|' || target_type)  AS _to,
  relationship    AS type,
  entity_type     AS _fromType,
  target_type     AS _toType,
  -- parsed to sortable ISO yyyy-mm; NULL when default_*_timestamp
  strftime(try_strptime(start_date, '%B %Y'), '%Y-%m') AS startDate,
  strftime(try_strptime(end_date,   '%B %Y'), '%Y-%m') AS endDate,
  start_date      AS startDateRaw,
  end_date        AS endDateRaw,
  extraction_type AS extractionType,
  lower(ticker)   AS ticker,
  year,
  source_file     AS sourceFile,
  page_id         AS pageId,
  md5(ticker || '|' || year || '|' || page_id || '|' || chunk_id) AS chunkKey
FROM src;
```

- Written as multiple ~512 MB JSONL part files (`COPY ... (FORMAT JSON,
  FILE_SIZE_BYTES '512MB')`) so import parallelizes per file and a failed part
  can be re-run alone.
- `chunk_text` is **not** copied onto edges — NL/GraphRAG retrieves it via
  `chunkKey → chunks/_key` (single indexed join).
- Duplicates by design: ~50% of rows share an `(entity, relationship, target)`
  with another row but differ in provenance/temporal fields. We keep one edge
  per occurrence (the dataset's temporal value); a deduplicated "fact" layer
  can be derived in-database later if benchmarks call for it.

**Exit check:** line counts — nodes ≈ measured distinct `(name,type)`;
relations = 17,513,372 across parts; chunks = measured distinct chunk keys.

## Stage 3 — Provision database & collections

Script: `scripts/setup_db.py` (HTTP API, reads `.env`).

1. `POST /_api/database` → create `FinReflectKG` (it does not exist on the
   target yet; verified the endpoint is reachable, ArangoDB **3.12.9
   Enterprise**).
2. Create collections (before import, so types are right):
   - `Node` — document collection
   - `relations` — **edge** collection
   - `chunks` — document collection
   - If the deployment is a cluster: `numberOfShards` ≥ 3 for `relations` and
     `chunks`, shard `relations` by `_from` (locality for outbound
     traversals); confirm topology via `/_admin/cluster/health` first.
3. **No secondary indexes yet** — build them after bulk load (much faster than
   maintaining them during insert).

## Stage 4 — Bulk import

`arangoimport` from the official Docker image, JSONL input, against the remote
endpoint:

```bash
docker run --rm -v "$PWD/data/staging:/data" arangodb:3.12 \
  arangoimport \
    --server.endpoint ssl://20hin6od.rnd.pilot.arango.ai:443 \
    --server.database FinReflectKG \
    --server.username root --server.password "$ARANGO_PASSWORD" \
    --collection Node --type jsonl --file /data/nodes.jsonl \
    --threads 8 --batch-size 8388608 --on-duplicate ignore
```

Order and options:

| # | Collection | Files | Notes |
|---|-----------|-------|-------|
| 1 | `Node` | `nodes.jsonl` | small; minutes |
| 2 | `chunks` | `chunks.jsonl` | ~4–5 GB payload |
| 3 | `relations` | `relations-*.jsonl` | the long pole: 17.5 M edges; run part files sequentially (each internally parallel with `--threads`), record docs/sec per part |

- **Pilot first:** import the output of a single source shard (~170 K edges)
  end-to-end, measure WAN throughput, and extrapolate before launching the
  full run. Throughput over TLS/WAN is the dominant unknown (LAN reference:
  20–60 K docs/s; budget 1–3 h for edges if WAN-bound).
- `--on-duplicate ignore` + deterministic keys ⇒ safe restart at any point.
- Failure handling: `arangoimport` reports rejected documents; non-zero
  rejects fail the stage and the part is re-run after diagnosis.

## Stage 5 — Indexes (post-load)

Script: `scripts/create_indexes.py` (HTTP `POST /_api/index`), in this order:

| Collection | Type | Fields | Purpose |
|---|---|---|---|
| `relations` | persistent | `["_from", "type", "_toType"]` | **VCI 1** — outbound traversal pruned by relationship type and far-node type |
| `relations` | persistent | `["_to", "type", "_fromType"]` | **VCI 2** — inbound equivalent |
| `Node` | persistent | `["name"]` | entity lookup / NL entry point |
| `Node` | persistent | `["type"]` | type-scoped scans |
| `relations` | persistent (optional) | `["ticker", "year"]` | temporal/company slicing — add if benchmarks need it |

Build with `inBackground: false` (exclusive, fastest) since the POC database
has no live traffic. Record build time for each — index-build duration on
17.5 M edges is itself a useful POC datapoint.

## Stage 6 — Validate & reconcile

Script: `scripts/validate.py`:

1. **Counts**: `LENGTH(Node)`, `LENGTH(relations)`, `LENGTH(chunks)` ==
   staging line counts == source-parquet aggregates.
2. **Referential integrity** (sampled): every edge `_from`/`_to` resolves;
   every `chunkKey` resolves.
3. **Index use**: `db._explain` / AQL `PROFILE` on a typed traversal confirms
   the VCI is chosen, e.g.:

```aql
FOR v, e IN 1..1 OUTBOUND @company relations
  FILTER e.type == 'operates_in' AND e._toType == 'GPE'
  RETURN v.name
```

4. **Smoke queries** from the PRD benchmark sketch (§6), including the
   supernode case (`net income`, `FIN_METRIC`) with and without type pruning.

## Measured runtime (pilot + full run)

| Stage | Estimate | **Measured** |
|---|---|---|
| Download | minutes | done — 1.6 GB, 103 shards |
| Preprocess (full) | 10–30 min | **14 s** (DuckDB, 8 threads); split into 16 × ~490 MB relations files |
| Provision | seconds | seconds |
| Import — pilot relations | — | 1,546 edges/s @ 4 threads; **3,672 edges/s @ 16 threads / 16 MB batch** |
| Import — full | 1–3 h | relations ≈ **80 min** at measured rate (in progress) |
| Indexes | 10–40 min | TBD (recorded by `create_indexes.py`) |
| Validate | minutes | TBD |

Pilot (shards 0–1) imported with **0 errors and 0 dangling endpoints**;
referential integrity verified in preprocessing (every `_from`/`_to`/`chunkKey`
resolves). Full preprocess counts match the data analysis exactly: 3,099,773
nodes, 17,513,372 relations, 1,384,513 chunks (the chunk count is below the
1,403,652 distinct chunk keys because rows with `has_context = false` are
excluded).

## Scripts

| Script | Role |
|---|---|
| `scripts/download.py` | Stage 1 — resumable HF download |
| `scripts/preprocess.py` | Stage 2 — parquet → JSONL (`--input`, `--out`, `--split-bytes`) |
| `scripts/arango.py` | shared `.env`-driven HTTP helper |
| `scripts/setup_db.py` | Stage 3 — create DB + collections (idempotent) |
| `scripts/import.sh` | Stage 4 — `arangoimport` one file via Docker |
| `scripts/import_full.sh` | Stage 4 — drive Node → chunks → all relations parts |
| `scripts/create_indexes.py` | Stage 5 — VCIs + lookup indexes, post-load |
| `scripts/validate.py` | Stage 6 — count reconciliation + VCI-usage explain |

## Open items

- Confirm target topology (single server vs. cluster) → shard counts/keys.
- Agree the benchmark query suite (PRD §6).
- Decide whether a deduplicated "fact" edge layer (distinct
  `entity/relationship/target` with `occurrences` count) should be derived
  in-database for comparison benchmarks.
- Phase 2: embeddings over `chunks.text` + vector index for semantic GraphRAG.

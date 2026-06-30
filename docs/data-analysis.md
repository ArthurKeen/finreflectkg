# Data Analysis — domyn/FinReflectKG

**Status:** v1.0 · 2026-06-12 · all figures measured over the **full dataset**
(103 parquet shards, downloaded to `data/raw/`) with DuckDB
([scripts/profile_full.py](../scripts/profile_full.py); raw results in
`data/profile_full.json`).
**Related docs:** [PRD.md](PRD.md) · [etl-plan.md](etl-plan.md) ·
[data_dictionary.md](data_dictionary.md)

## 1. Shape of the data

One parquet row = one **triple occurrence**: `(entity, relationship, target)`
plus types on both ends, temporal validity, and full provenance down to the
source-text chunk. 18 columns, all scalar. So the dataset is, as suspected,
a row-per-edge representation: *vertex — edge — vertex*, with vertex types
inline on every row.

| Measure | Value |
|---|---|
| Rows (triple occurrences) | **17,513,372** |
| Parquet size / decompressed | 1.67 GB / ~50 GB (chunk text dominates) |
| Shards | 103, partitioned by company (shard 0 contains 8 tickers) |
| Companies (`ticker`) | 743 |
| Filing years | 2014–2024 (11 years, fairly even: 1.19–1.75 M rows/year) |
| Distinct source entities | 152,917 (180,132 typed) |
| Distinct targets | 2,449,250 (3,059,080 typed) |
| **Distinct `(name, type)` nodes (entity ∪ target)** | **3,099,773** |
| Distinct relationship strings | **30,535** |
| Distinct `(entity, relationship, target)` | 8,490,524 (48% of rows — half the rows are repeat observations of the same fact) |
| Distinct text chunks `(ticker, year, page_id, chunk_id)` | **1,403,652** |

### Implications for the graph model

- **~3.1 M nodes, 17.5 M edges** in the LPG model (node identity =
  `(name, type)`).
- The fan-out is asymmetric: 153 K entities (mostly the 743 filer `ORG`s plus
  segments/people) point at 2.4 M mostly-leaf targets. Average target
  in-degree is 5.7.

## 2. Relationship types: confirmed unsuitable for edge collections

The schema ([data_dictionary.md](data_dictionary.md)) defines **~30 canonical
relationship types**, but extraction emitted **30,535 distinct strings**:

- Top 30 strings cover **89.8%** of rows; top 100 cover **95.3%**.
- **29,482 strings (96.6%) occur fewer than 100 times** — a long tail of
  free-text variants (`us`, `include`, `impact`, lemmatization residue, and
  one-off phrases).
- `discloses` alone is 7.80 M rows (**44.6%** of the graph).

| Top relationships | Rows |
|---|---|
| discloses | 7,803,941 |
| depends_on | 959,366 |
| negatively_impacts | 845,892 |
| subject_to | 823,164 |
| has_stake_in | 571,939 |
| impacted_by | 539,537 |
| increase | 483,951 |
| operates_in | 462,905 |

**Conclusion:** mapping relationship type → edge collection is out of the
question (30 K collections; even the canonical 30 would fragment traversals).
A single `relations` edge collection with a `type` property — the LPG model —
is the right fit, with vertex-centric indexes making typed traversals cheap.

## 3. Entity types

**25 observed types** — the 24 documented in the data dictionary **plus an
undocumented `POSITION`** (26,816 occurrences; job titles). Usage across both
ends of the edges:

| Type | Occurrences (entity+target) | | Type | Occurrences |
|---|---|---|---|---|
| ORG | 16,127,661 | | EVENT | 260,313 |
| FIN_METRIC | 8,602,405 | | CONCEPT | 255,886 |
| FIN_INST | 1,739,542 | | ORG_REG | 227,833 |
| ACCOUNTING_POLICY | 1,170,379 | | LITIGATION | 212,162 |
| SEGMENT | 869,122 | | LOGISTICS | 177,705 |
| REGULATORY_REQUIREMENT | 811,475 | | ECON_IND | 156,405 |
| COMP | 758,809 | | RAW_MATERIAL | 116,718 |
| RISK_FACTOR | 753,363 | | FIN_MARKET | 102,070 |
| PRODUCT | 718,338 | | SECTOR | 91,303 |
| GPE | 412,013 | | ESG_TOPIC | 82,970 |
| PERSON | 410,599 | | ORG_GOV | 31,599 |
| MACRO_CONDITION | 357,791 | | POSITION | 26,816 |
| COMMENTARY | 336,621 | | | |

- `ORG` dominates the **source** side (filer companies); `FIN_METRIC`
  dominates the **target** side (78 K of 170 K targets in shard-0 sampling).
- **350,446 names (~14%) occur with more than one type** (e.g. a company as
  both `ORG` and `COMP`). Node identity = `(name, type)` keeps these distinct,
  which is exactly why edges need `_fromType`/`_toType` copied on — the
  traversal can prune by far-node type without fetching the node.

## 4. Supernodes — the case for vertex-centric indexes

Generic financial-metric targets accumulate in-degree across all 743 companies
× 11 years:

| Node (in-degree) | | Node (out-degree) | |
|---|---|---|---|
| `net income` (FIN_METRIC) | **99,295** | `etr` (ORG) | 95,713 |
| `revenue` (FIN_METRIC) | 51,948 | `pru` (ORG) | 93,612 |
| `long-term debt` (FIN_METRIC) | 32,042 | `met` (ORG) | 88,430 |
| `total revenue` (FIN_METRIC) | 29,016 | `so` (ORG) | 88,391 |
| `interest expense` (FIN_METRIC) | 29,010 | `aig` (ORG) | 82,580 |

- **56 nodes have degree > 10,000; 1,414 have degree > 1,000.** Heaviest
  out-degrees are financials/utilities (dense disclosures).
- An unindexed/unpruned expansion from `net income` touches ~100 K edges; with
  VCI `(_to, type, _fromType)` a query like "which ORGs disclose net income"
  becomes a tight index range scan. This is the headline benchmark for the POC
  (PRD §6.4).

## 5. Temporal fields

- `start_date` parses as `"%B %Y"` for **98.73%** of rows; `end_date` for
  95.61%, with **4.05%** `default_end_timestamp` (open-ended validity).
  Matches the card's "99.08% clean dates" claim.
- `extraction_type` should be binary (`default`/`extracted`) and is for
  **17,382,092 rows, but 131,279 rows (0.75%) carry garbage** (free-text
  fragments leaked from LLM extraction, e.g. `"due_to COVID-19"`, full triple
  sentences). ETL keeps the raw value but queries should not trust it as an
  enum.
- Year distribution is even enough that per-year benchmark slices are
  comparable (≈1.6 M rows/year).

## 6. Keys, nulls, and quality notes for ETL

| Check | Result | ETL consequence |
|---|---|---|
| `triplet_id` uniqueness | **17,513,372 distinct = row count** | use as `relations._key` (idempotent re-import) |
| `triplet_id` key safety | 0 rows with non-`[a-zA-Z0-9_.-]` chars | usable as-is |
| `entity`/`target` key safety | **91% of rows contain `/` or whitespace** in names | node `_key` must be derived → `md5(name\|type)` |
| Null/empty `entity`, `target`, `relationship` | 0 | no row drops |
| Null/empty `target_type` | **58 rows** | map to type `UNKNOWN` (keeps the edge; `_toType: "UNKNOWN"`) |
| `has_context = false` | 256,130 rows (1.5%) | edge gets no `chunkKey`; chunk row skipped |
| `chunk_text` duplication | ~12.5× (17.5 M rows ↦ 1.40 M chunks, avg 2.9 KB, max 13.5 KB) | dedup into `chunks` collection: ~4 GB instead of ~50 GB on edges |
| Ticker case | `ticker` is uppercase in data, lowercase in `entity` names | normalize to lowercase in ETL for joinability |

## 7. Resulting target sizing

| Collection | Documents | Notes |
|---|---|---|
| `Node` | ~3.10 M | name + type, ~100 B/doc |
| `relations` | 17.51 M | ~15 properties/edge, no chunk text |
| `chunks` | ~1.40 M | ~2.9 KB avg text |
| VCI 1 + VCI 2 | 2 × 17.51 M entries | built post-load |

These figures drive the staging-file layout and import ordering in
[etl-plan.md](etl-plan.md).

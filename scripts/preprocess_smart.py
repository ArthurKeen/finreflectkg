"""Preprocess FinReflectKG parquet → JSONL for the **Disjoint SmartGraph** build.

Same dataset as scripts/preprocess.py, but keyed for per-company co-location
(Design 2, locked — see docs/multi-distribution-plan.md §5 and
docs/smartgraph-build-brief.md). The smart attribute is `ticker` (lowercased),
present on every node, edge, and chunk:

  nodes_smart.jsonl        — `Node`      _key = "<ticker>:md5(name|type)"
                             one row per (name, type, ticker): a concept shared
                             by N companies is duplicated into N per-company
                             copies (≈2.1× nodes). Edges are NOT duplicated.
  chunks_smart.jsonl       — `chunks`    _key = "<ticker>:md5(ticker|year|page|chunk)"
  relations_smart/*.json   — `relations` _key = triplet_id; _from/_to point at the
                             per-ticker node copies using the EDGE's own ticker
                             (safe: 0.00% cross-company references), and chunkKey
                             is rewritten to match chunks_smart._key.

`lower(ticker)` is used **everywhere** the smart value appears — the node-key
prefix, the edge endpoint prefixes, the edge/chunk `ticker` field, and the chunk
key prefix — so a company's nodes, edges, and source text all hash to the same
shard.

CRITICAL invariant: the chunk-key expression (SMART_CHUNK_KEY) must be
byte-identical between relations_smart.chunkKey and chunks_smart._key, or the
edge→chunk join breaks. It is defined once below and reused in both places.

Usage:
  # pilot — one source shard (8 tickers)
  .venv/bin/python scripts/preprocess_smart.py \
      --input "data/raw/data/train-00000-of-00103.parquet" --out data/staging/smart_pilot
  # full — all shards, split relations for parallel import
  .venv/bin/python scripts/preprocess_smart.py \
      --input "data/raw/data/train-*.parquet" --out data/staging/smart --split-bytes 512MB
"""

import argparse
import pathlib
import shutil

import duckdb

SEP = "|"

# Per-company node key: "<ticker>:md5(name|type)". The md5 half is identical to
# the baseline node key, so the same (name,type) maps to the same hash within
# each company.
SMART_NODE_KEY = (
    "lower({ticker}) || ':' || "
    "md5({name} || '{sep}' || COALESCE(NULLIF({type}, ''), 'UNKNOWN'))"
)

# Chunk key (and the edge's chunkKey) — lower(ticker) used BOTH in the prefix and
# inside the md5 so the two expressions are textually identical wherever used.
SMART_CHUNK_KEY = (
    "lower(ticker) || ':' || md5("
    "lower(ticker) || '{sep}' || CAST(year AS VARCHAR) || '{sep}' || "
    "page_id || '{sep}' || chunk_id)"
).format(sep=SEP)


def node_key(ticker, name, typ):
    return SMART_NODE_KEY.format(ticker=ticker, name=name, type=typ, sep=SEP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="parquet glob")
    ap.add_argument("--out", required=True, help="staging output dir")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument(
        "--split-bytes",
        default=None,
        help="if set (e.g. 512MB), relations is written as multiple files in a dir",
    )
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"CREATE VIEW src AS SELECT * FROM read_parquet('{args.input}')")

    # --- nodes — DISTINCT (name, type, ticker) => one copy per referencing company
    nodes_path = out / "nodes_smart.jsonl"
    con.execute(
        f"""
        COPY (
          SELECT DISTINCT
            {node_key('ticker', 'name', 'type')} AS "_key",
            name, type, lower(ticker) AS ticker
          FROM (
            SELECT entity AS name, COALESCE(NULLIF(entity_type,''),'UNKNOWN') AS type, ticker FROM src
            UNION
            SELECT target, COALESCE(NULLIF(target_type,''),'UNKNOWN'), ticker FROM src
          )
        ) TO '{nodes_path}' (FORMAT JSON)
        """
    )
    n_nodes = con.execute(
        f"SELECT count(*) FROM read_json_auto('{nodes_path}')"
    ).fetchone()[0]

    # --- chunks — smart-sharded by ticker; key prefixed with "<ticker>:"
    chunks_path = out / "chunks_smart.jsonl"
    con.execute(
        f"""
        COPY (
          SELECT
            {SMART_CHUNK_KEY} AS "_key",
            lower(any_value(ticker)) AS ticker,
            any_value(year) AS year,
            any_value(page_id) AS "pageId",
            any_value(chunk_id) AS "chunkId",
            any_value(source_file) AS "sourceFile",
            any_value(chunk_text) AS text
          FROM src
          WHERE has_context
          GROUP BY {SMART_CHUNK_KEY}
        ) TO '{chunks_path}' (FORMAT JSON)
        """
    )
    n_chunks = con.execute(
        f"SELECT count(*) FROM read_json_auto('{chunks_path}')"
    ).fetchone()[0]

    # --- relations — endpoints rewritten to per-ticker node copies (edge's ticker)
    # SmartGraph edge collections reject a plain custom _key ("must not specify
    # _key for this collection") — the key must be the composite
    # "<fromSmartValue>:<userKey>:<toSmartValue>". Cross-company refs are 0.00%,
    # so both smart values are the edge's own ticker. Keeping triplet_id in the
    # middle preserves a deterministic key → idempotent re-import (PRD G4).
    rel_select = f"""
        SELECT
          lower(ticker) || ':' || triplet_id || ':' || lower(ticker) AS "_key",
          'Node/' || {node_key('ticker', 'entity', 'entity_type')}  AS "_from",
          'Node/' || {node_key('ticker', 'target', 'target_type')}  AS "_to",
          relationship AS type,
          COALESCE(NULLIF(entity_type,''),'UNKNOWN') AS "_fromType",
          COALESCE(NULLIF(target_type,''),'UNKNOWN') AS "_toType",
          strftime(try_strptime(start_date, '%B %Y'), '%Y-%m') AS "startDate",
          strftime(try_strptime(end_date,   '%B %Y'), '%Y-%m') AS "endDate",
          start_date AS "startDateRaw",
          end_date   AS "endDateRaw",
          extraction_type AS "extractionType",
          lower(ticker) AS ticker,
          year,
          source_file AS "sourceFile",
          page_id AS "pageId",
          CASE WHEN has_context THEN {SMART_CHUNK_KEY} ELSE NULL END AS "chunkKey"
        FROM src
    """
    if args.split_bytes:
        rel_dir = out / "relations_smart"
        if rel_dir.exists():
            shutil.rmtree(rel_dir)
        con.execute(
            f"COPY ({rel_select}) TO '{rel_dir}' "
            f"(FORMAT JSON, FILE_SIZE_BYTES '{args.split_bytes}')"
        )
        n_rel = con.execute(
            f"SELECT count(*) FROM read_json_auto('{rel_dir}/*.json')"
        ).fetchone()[0]
        rel_loc = f"{rel_dir}/ (split @ {args.split_bytes})"
    else:
        rel_path = out / "relations_smart.jsonl"
        con.execute(f"COPY ({rel_select}) TO '{rel_path}' (FORMAT JSON)")
        n_rel = con.execute(
            f"SELECT count(*) FROM read_json_auto('{rel_path}')"
        ).fetchone()[0]
        rel_loc = str(rel_path)

    print(f"nodes_smart : {n_nodes:>10,}  -> {nodes_path}")
    print(f"chunks_smart: {n_chunks:>10,}  -> {chunks_path}")
    print(f"relations   : {n_rel:>10,}  -> {rel_loc}")


if __name__ == "__main__":
    main()

"""Preprocess FinReflectKG parquet → JSONL for ArangoDB import.

Produces three outputs in the staging dir:
  nodes.jsonl       — collection `Node`      (_key = md5(name|type))
  chunks.jsonl      — collection `chunks`    (_key = md5(ticker|year|page|chunk))
  relations/*.json  — collection `relations` (_key = triplet_id), edge docs

DuckDB streams the parquet; nothing loads the full dataset into memory.

Usage:
  # pilot — one shard
  .venv/bin/python scripts/preprocess.py --input "data/raw/data/train-00000-of-00103.parquet" --out data/staging/pilot
  # full — all shards
  .venv/bin/python scripts/preprocess.py --input "data/raw/data/train-*.parquet" --out data/staging/full
"""

import argparse
import pathlib
import shutil

import duckdb

# Node-key separator. Entity/target types come from a fixed vocabulary that
# never contains '|', so md5(name || '|' || type) is unambiguous.
SEP = "|"

# Shared so the edge endpoints reference exactly the keys emitted for nodes.
NODE_KEY = "md5({name} || '{sep}' || COALESCE(NULLIF({type}, ''), 'UNKNOWN'))"
CHUNK_KEY = (
    "md5(ticker || '{sep}' || CAST(year AS VARCHAR) || '{sep}' || "
    "page_id || '{sep}' || chunk_id)"
).format(sep=SEP)


def k(name, typ):
    return NODE_KEY.format(name=name, type=typ, sep=SEP)


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
    con.execute(
        f"CREATE VIEW src AS SELECT * FROM read_parquet('{args.input}')"
    )

    # --- nodes -------------------------------------------------------------
    nodes_path = out / "nodes.jsonl"
    con.execute(
        f"""
        COPY (
          SELECT DISTINCT
            {NODE_KEY.format(name='name', type='type', sep=SEP)} AS "_key",
            name, type
          FROM (
            SELECT entity AS name, COALESCE(NULLIF(entity_type,''),'UNKNOWN') AS type FROM src
            UNION
            SELECT target, COALESCE(NULLIF(target_type,''),'UNKNOWN') FROM src
          )
        ) TO '{nodes_path}' (FORMAT JSON)
        """
    )
    n_nodes = con.execute(
        f"SELECT count(*) FROM read_json_auto('{nodes_path}')"
    ).fetchone()[0]

    # --- chunks ------------------------------------------------------------
    chunks_path = out / "chunks.jsonl"
    con.execute(
        f"""
        COPY (
          SELECT
            {CHUNK_KEY} AS "_key",
            lower(any_value(ticker)) AS ticker,
            any_value(year) AS year,
            any_value(page_id) AS "pageId",
            any_value(chunk_id) AS "chunkId",
            any_value(source_file) AS "sourceFile",
            any_value(chunk_text) AS text
          FROM src
          WHERE has_context
          GROUP BY {CHUNK_KEY}
        ) TO '{chunks_path}' (FORMAT JSON)
        """
    )
    n_chunks = con.execute(
        f"SELECT count(*) FROM read_json_auto('{chunks_path}')"
    ).fetchone()[0]

    # --- relations (edges) -------------------------------------------------
    rel_select = f"""
        SELECT
          triplet_id AS "_key",
          'Node/' || {k('entity', 'entity_type')}  AS "_from",
          'Node/' || {k('target', 'target_type')}  AS "_to",
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
          CASE WHEN has_context THEN {CHUNK_KEY} ELSE NULL END AS "chunkKey"
        FROM src
    """
    if args.split_bytes:
        rel_dir = out / "relations"
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
        rel_path = out / "relations.jsonl"
        con.execute(f"COPY ({rel_select}) TO '{rel_path}' (FORMAT JSON)")
        n_rel = con.execute(
            f"SELECT count(*) FROM read_json_auto('{rel_path}')"
        ).fetchone()[0]
        rel_loc = str(rel_path)

    print(f"nodes     : {n_nodes:>10,}  -> {nodes_path}")
    print(f"chunks    : {n_chunks:>10,}  -> {chunks_path}")
    print(f"relations : {n_rel:>10,}  -> {rel_loc}")


if __name__ == "__main__":
    main()

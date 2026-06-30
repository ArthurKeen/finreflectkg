"""Full-dataset profile of domyn/FinReflectKG via DuckDB remote parquet scan.

Scans all 103 shards over HTTP with column pruning (skips chunk_text).
Writes results to data/profile_full.json.
"""

import json
import pathlib

import duckdb

URL = str(
    pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "data" / "train-*.parquet"
)
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "profile_full.json"
OUT.parent.mkdir(exist_ok=True)

con = duckdb.connect()
con.execute("SET threads=8")
con.execute(
    f"""CREATE VIEW t AS SELECT entity, entity_type, relationship, target,
        target_type, ticker, year, start_date, end_date, extraction_type,
        page_id, chunk_id, has_context
        FROM read_parquet('{URL}')"""
)

results = {}


def q(name, sql):
    cols = None
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    results[name] = [dict(zip(cols, r)) for r in rows]
    print(f"== {name} ==")
    for r in results[name][:25]:
        print(r)


q(
    "cardinalities",
    """SELECT count(*) AS n_rows,
       count(DISTINCT ticker) n_tickers,
       count(DISTINCT year) n_years,
       count(DISTINCT entity) ents,
       count(DISTINCT target) tgts,
       count(DISTINCT relationship) rels,
       count(DISTINCT (entity, entity_type)) ent_typed,
       count(DISTINCT (target, target_type)) tgt_typed,
       count(DISTINCT (entity, relationship, target)) distinct_ert,
       count(DISTINCT (ticker, year, page_id, chunk_id)) distinct_chunks
       FROM t""",
)

q(
    "node_estimate",
    """SELECT count(*) n_nodes FROM (
         SELECT entity AS name, entity_type AS type FROM t
         UNION
         SELECT target, target_type FROM t)""",
)

q(
    "entity_type_dist",
    """SELECT type, sum(c) c FROM (
         SELECT entity_type AS type, count(*) c FROM t GROUP BY 1
         UNION ALL
         SELECT target_type, count(*) FROM t GROUP BY 1)
       GROUP BY 1 ORDER BY c DESC""",
)

q(
    "relationship_top50",
    "SELECT relationship, count(*) c FROM t GROUP BY 1 ORDER BY c DESC LIMIT 50",
)

q(
    "relationship_tail",
    """SELECT count(*) n_rel_types_lt_100 FROM (
         SELECT relationship FROM t GROUP BY 1 HAVING count(*) < 100)""",
)

q(
    "supernodes_in",
    """SELECT target, target_type, count(*) in_deg
       FROM t GROUP BY 1,2 ORDER BY in_deg DESC LIMIT 20""",
)

q(
    "supernodes_out",
    """SELECT entity, entity_type, count(*) out_deg
       FROM t GROUP BY 1,2 ORDER BY out_deg DESC LIMIT 20""",
)

q(
    "year_dist",
    "SELECT year, count(*) c FROM t GROUP BY 1 ORDER BY 1",
)

q(
    "extraction_type_dist",
    "SELECT extraction_type, count(*) c FROM t GROUP BY 1",
)

q(
    "multi_type_names",
    """SELECT count(*) n_names_multi_type FROM (
         SELECT name FROM (
           SELECT entity AS name, entity_type AS type FROM t
           UNION SELECT target, target_type FROM t)
         GROUP BY name HAVING count(DISTINCT type) > 1)""",
)

q(
    "nulls",
    """SELECT
       sum(CASE WHEN entity IS NULL OR entity = '' THEN 1 ELSE 0 END) e_null,
       sum(CASE WHEN target IS NULL OR target = '' THEN 1 ELSE 0 END) t_null,
       sum(CASE WHEN relationship IS NULL OR relationship = '' THEN 1 ELSE 0 END) r_null,
       sum(CASE WHEN entity_type IS NULL OR entity_type = '' THEN 1 ELSE 0 END) et_null,
       sum(CASE WHEN target_type IS NULL OR target_type = '' THEN 1 ELSE 0 END) tt_null,
       sum(CASE WHEN NOT has_context THEN 1 ELSE 0 END) no_ctx
       FROM t""",
)

OUT.write_text(json.dumps(results, indent=2, default=str))
print(f"\nwrote {OUT}")

"""Create the Disjoint SmartGraph `FinReflectKgSmart` (smart attribute `ticker`).

Creating the SmartGraph via gharial is what makes `Node` + `relations`
smart-sharded by `ticker`; `chunks` is added as an orphan so a company's source
text co-locates on the same shard as its subgraph. Requires ArangoDB Enterprise.
Metadata + collection creation only (no data moved). Idempotent.

Run AFTER setup_db.py (ARANGO_SMART=1, database only) and BEFORE the import.

Env (overlaid over .env by arango.py):
  ARANGO_DB                target database (e.g. FinReflectKgSmart)
  ARANGO_GRAPH             smart graph name (default = ARANGO_DB)
  ARANGO_SMART_ATTRIBUTE   smart attribute      (default "ticker")
  ARANGO_NUM_SHARDS        numberOfShards       (default 9)
  ARANGO_REPLICATION_FACTOR replicationFactor   (default 2)
"""

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKgSmart")
GRAPH = ENV.get("ARANGO_GRAPH", DB)
SMART_ATTR = ENV.get("ARANGO_SMART_ATTRIBUTE", "ticker")
NUM_SHARDS = int(ENV.get("ARANGO_NUM_SHARDS", "9"))
REPLICATION = int(ENV.get("ARANGO_REPLICATION_FACTOR", "2"))

BODY = {
    "name": GRAPH,
    "edgeDefinitions": [
        {"collection": "relations", "from": ["Node"], "to": ["Node"]}
    ],
    "orphanCollections": ["chunks"],
    "options": {
        "smartGraphAttribute": SMART_ATTR,
        "isDisjoint": True,
        "numberOfShards": NUM_SHARDS,
        "replicationFactor": REPLICATION,
    },
}

SMART_COLLECTIONS = ["Node", "relations", "chunks"]


def report_collection(coll):
    status, p = req("GET", f"/_api/collection/{coll}/properties", db=DB)
    if status != 200:
        print(f"  {coll}: properties -> {status} {p}")
        return None
    print(f"  {coll:9} isSmart={p.get('isSmart')}  "
          f"shardKeys={p.get('shardKeys')}  "
          f"numberOfShards={p.get('numberOfShards')}  "
          f"smartGraphAttribute={p.get('smartGraphAttribute')!r}  "
          f"distributeShardsLike={p.get('distributeShardsLike')!r}")
    return p


def ensure_chunks_smart():
    """Belt-and-suspenders: if `chunks` did not come out smart-sharded by the
    smart attribute (some builds don't make orphans smart), create it explicitly
    co-located with Node. Only acts when chunks is missing or non-smart."""
    status, p = req("GET", f"/_api/collection/chunks/properties", db=DB)
    if status == 200 and p.get("isSmart") and p.get("shardKeys") == [SMART_ATTR]:
        return  # already correct
    if status == 200:
        print(f"  note: chunks exists but isSmart={p.get('isSmart')} "
              f"shardKeys={p.get('shardKeys')} — leaving as-is (added as graph orphan)")
        return
    body = {
        "name": "chunks", "type": 2,
        "numberOfShards": NUM_SHARDS, "replicationFactor": REPLICATION,
        "shardKeys": [SMART_ATTR], "distributeShardsLike": "Node",
    }
    status, resp = req("POST", "/_api/collection", body, db=DB)
    if status in (200, 201):
        print("  chunks: created smart-sharded (shardKeys=[ticker], distributeShardsLike=Node)")
    elif resp.get("errorNum") != 1207:
        raise SystemExit(f"failed to create chunks: {status} {resp}")


def main():
    status, body = req("GET", f"/_api/gharial/{GRAPH}", db=DB)
    if status == 200:
        g = body.get("graph", {})
        print(f"smart graph '{GRAPH}': already exists")
        print(f"  smartGraphAttribute: {g.get('smartGraphAttribute')!r}  "
              f"isDisjoint: {g.get('isDisjoint')}  "
              f"numberOfShards: {g.get('numberOfShards')}")
    else:
        status, body = req("POST", "/_api/gharial", BODY, db=DB)
        if status in (201, 202):
            g = body.get("graph", {})
            print(f"smart graph '{GRAPH}': created")
            print(f"  smartGraphAttribute: {g.get('smartGraphAttribute')!r}  "
                  f"isDisjoint: {g.get('isDisjoint')}  "
                  f"numberOfShards: {g.get('numberOfShards')}")
        else:
            raise SystemExit(f"failed to create smart graph: {status} {body}")

    ensure_chunks_smart()
    print("collection sharding:")
    for c in SMART_COLLECTIONS:
        report_collection(c)


if __name__ == "__main__":
    main()

"""Verify whether FinReflectKG is a OneShard database and inspect graph collection sharding."""

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")
GRAPH = ENV.get("ARANGO_GRAPH", "FinReflectKG")


def main():
    print(f"endpoint: {ENV['ARANGO_ENDPOINT']}  db: {DB}\n")

    status, body = req("GET", "/_api/database/current", db=DB)
    res = body.get("result", {})
    print(f"GET /_api/database/current -> {status}")
    print(f"  name:        {res.get('name')}")
    print(f"  sharding:    {res.get('sharding')!r}   (\"single\" == OneShard database)")
    print(f"  replicationFactor: {res.get('replicationFactor')}")
    print(f"  writeConcern:      {res.get('writeConcern')}")
    print()

    status, gbody = req("GET", f"/_api/gharial/{GRAPH}", db=DB)
    g = gbody.get("graph", {})
    edge_defs = g.get("edgeDefinitions", [])
    cols = set()
    for ed in edge_defs:
        cols.add(ed["collection"])
        cols.update(ed.get("from", []))
        cols.update(ed.get("to", []))
    cols.update(g.get("orphanCollections", []))
    print(f"graph '{GRAPH}' collections: {sorted(cols)}\n")

    for c in sorted(cols):
        status, p = req("GET", f"/_api/collection/{c}/properties", db=DB)
        if status != 200:
            print(f"  {c}: properties -> {status} {p}")
            continue
        print(f"  {c} (type={'edge' if p.get('type') == 3 else 'document'}):")
        print(f"    numberOfShards:     {p.get('numberOfShards')}")
        print(f"    replicationFactor:  {p.get('replicationFactor')}")
        print(f"    writeConcern:       {p.get('writeConcern')}")
        print(f"    shardingStrategy:   {p.get('shardingStrategy')!r}")
        print(f"    shardKeys:          {p.get('shardKeys')}")
        print(f"    distributeShardsLike: {p.get('distributeShardsLike')!r}")
        print(f"    isSmart:            {p.get('isSmart')}")
        print(f"    smartGraphAttribute:{p.get('smartGraphAttribute')!r}")
        print()


if __name__ == "__main__":
    main()

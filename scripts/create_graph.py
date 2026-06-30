"""Create the named graph `FinReflectKG` over the already-loaded collections.

A General (non-smart) graph bundling the vertex + edge collections under one
name that arango-cypher-py / arango-graph-analytics can target, and that serves
as a manifest of which collections belong to this dataset. Metadata-only — no
data is moved or modified. Idempotent.

  Node       (vertices)  --[ relations ]-->  Node
  chunks     supporting source-text collection (NOT part of the graph by default;
             set INCLUDE_CHUNKS_AS_ORPHAN = True to add it as an orphan collection)
"""

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")
GRAPH = ENV.get("ARANGO_GRAPH", "FinReflectKG")
INCLUDE_CHUNKS_AS_ORPHAN = False

BODY = {
    "name": GRAPH,
    "edgeDefinitions": [
        {"collection": "relations", "from": ["Node"], "to": ["Node"]}
    ],
    "orphanCollections": (["chunks"] if INCLUDE_CHUNKS_AS_ORPHAN else []),
}


def main():
    status, body = req("GET", f"/_api/gharial/{GRAPH}", db=DB)
    if status == 200:
        g = body.get("graph", {})
        print(f"graph '{GRAPH}': already exists")
        print(f"  edgeDefinitions: {g.get('edgeDefinitions')}")
        print(f"  orphanCollections: {g.get('orphanCollections')}")
        return

    status, body = req("POST", "/_api/gharial", BODY, db=DB)
    if status in (201, 202):
        g = body.get("graph", {})
        print(f"graph '{GRAPH}': created")
        print(f"  edgeDefinitions: {g.get('edgeDefinitions')}")
        print(f"  orphanCollections: {g.get('orphanCollections')}")
    else:
        raise SystemExit(f"failed to create graph: {status} {body}")


if __name__ == "__main__":
    main()

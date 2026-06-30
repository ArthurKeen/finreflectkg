"""Inventory the FinReflectKG database: which collections exist, which belong to
the named graph (ours) vs. app-specific ones added by others, plus quick sizing.
Read-only."""

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")
GRAPH = "FinReflectKG"


def aql(q, b=None):
    _, r = req("POST", "/_api/cursor", {"query": q, "bindVars": b or {}}, db=DB, timeout=300)
    return r.get("result", []), r.get("errorMessage")


def main():
    print(f"db: {DB}\n")

    _, g = req("GET", f"/_api/gharial/{GRAPH}", db=DB)
    graph = g.get("graph", {})
    graph_cols = set()
    for ed in graph.get("edgeDefinitions", []):
        graph_cols.add(ed["collection"])
        graph_cols.update(ed.get("from", []))
        graph_cols.update(ed.get("to", []))
    graph_cols.update(graph.get("orphanCollections", []))
    print(f"named graph '{GRAPH}' edgeDefinitions: {graph.get('edgeDefinitions')}")
    print(f"named graph '{GRAPH}' orphans:         {graph.get('orphanCollections')}")
    print(f"=> OUR collections (in graph): {sorted(graph_cols)}\n")

    _, c = req("GET", "/_api/collection?excludeSystem=true", db=DB)
    print("== all non-system collections in db ==")
    for x in sorted(c.get("result", []), key=lambda x: x["name"]):
        n, t = x["name"], x["type"]
        _, cnt = req("GET", f"/_api/collection/{n}/count", db=DB)
        ours = "OURS" if n in graph_cols else "app-specific?"
        print(f"  {n:28} type={'edge' if t==3 else 'doc'}  count={cnt.get('count'):>12,}  [{ours}]")


if __name__ == "__main__":
    main()

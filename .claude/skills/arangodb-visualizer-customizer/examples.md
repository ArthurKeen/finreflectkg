## Ready-to-copy Python installer skeleton

Idempotent installer for all Graph Visualizer assets: themes, canvas actions, saved queries (both editor sidebar and Visualizer Queries panel).

**Default**: all metadata (saved queries, canvas actions) goes into the **target DB**. This is correct for ArangoGraph managed / cloud deployments. For self-hosted ArangoDB with shared saved queries, pass `meta_db=sys_db`.

### Helper functions

```python
#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Set

from arango import ArangoClient


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def ensure_collection(db, name: str, *, edge: bool = False) -> None:
    if not db.has_collection(name):
        db.create_collection(name, edge=edge, system=name.startswith("_"))


def _slugify(s: str) -> str:
    """Derive a stable document _key from a human-readable string."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def get_graph_schema(db, graph_name: str, exclude_vertex: Set[str] = None):
    """Return (vertex_colls, edge_colls) or (None, None) if graph not found.

    Uses g.edge_definitions() (python-arango SDK) which returns dicts with
    key 'edge_collection'. Do NOT mix with AQL on _graphs — that returns 'collection'.
    """
    if not db.has_graph(graph_name):
        return None, None
    g = db.graph(graph_name)
    vertex_colls = set(g.vertex_collections())
    edge_colls = set(ed["edge_collection"] for ed in g.edge_definitions())
    if exclude_vertex:
        vertex_colls -= exclude_vertex
    return vertex_colls, edge_colls


# ---------------------------------------------------------------------------
# Viewpoints
# ---------------------------------------------------------------------------

def ensure_default_viewpoint(db, graph_name: str) -> str:
    """Return _id of the Default viewpoint, creating it programmatically if absent."""
    ensure_collection(db, "_viewpoints")
    vp_col = db.collection("_viewpoints")
    for query in [{"graphId": graph_name, "name": "Default"}, {"graphId": graph_name}]:
        existing = list(vp_col.find(query))
        if existing:
            return existing[0]["_id"]
    now = now_iso()
    res = vp_col.insert({
        "graphId": graph_name, "name": "Default",
        "description": f"Default viewpoint for {graph_name}",
        "createdAt": now, "updatedAt": now,
    })
    return res["_id"]


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

def prune_theme(theme_raw: dict, vertex_colls: Set[str], edge_colls: Set[str]) -> dict:
    theme = copy.deepcopy(theme_raw)
    if "nodeConfigMap" in theme:
        theme["nodeConfigMap"] = {k: v for k, v in theme["nodeConfigMap"].items() if k in vertex_colls}
    if "edgeConfigMap" in theme:
        theme["edgeConfigMap"] = {k: v for k, v in theme["edgeConfigMap"].items() if k in edge_colls}
    return theme


def ensure_visualizer_shape(theme: dict) -> None:
    for node_cfg in theme.get("nodeConfigMap", {}).values():
        node_cfg.setdefault("rules", [])
        node_cfg.setdefault("hoverInfoAttributes", [])
    for edge_cfg in theme.get("edgeConfigMap", {}).values():
        edge_cfg.setdefault("rules", [])
        edge_cfg.setdefault("hoverInfoAttributes", [])
        edge_cfg.setdefault("arrowStyle", {"sourceArrowShape": "none", "targetArrowShape": "triangle"})
        edge_cfg.setdefault("labelStyle", {"color": "#1d2531"})


def install_theme(db, graph_name: str, theme_raw: dict, *, is_default: bool = True) -> str:
    """Upsert a theme. Preserves createdAt on update. Returns the theme _id."""
    ensure_collection(db, "_graphThemeStore")
    col = db.collection("_graphThemeStore")

    vertex_colls, edge_colls = get_graph_schema(db, graph_name)
    if vertex_colls is None:
        raise ValueError(f"Graph '{graph_name}' not found")

    theme = prune_theme(theme_raw, vertex_colls, edge_colls)
    theme["graphId"] = graph_name
    theme["isDefault"] = is_default
    theme["updatedAt"] = now_iso()
    ensure_visualizer_shape(theme)

    existing = list(col.find({"name": theme["name"], "graphId": graph_name}))
    if existing:
        theme["_key"] = existing[0]["_key"]
        theme["_id"] = existing[0]["_id"]
        theme["createdAt"] = existing[0].get("createdAt", theme["updatedAt"])
        col.replace(theme, check_rev=False)
        return existing[0]["_id"]
    else:
        theme["createdAt"] = theme["updatedAt"]
        return col.insert(theme)["_id"]


# ---------------------------------------------------------------------------
# Canvas actions
# ---------------------------------------------------------------------------

def _upsert_canvas_action(canvas_col, vp_act_col, vp_id: str, graph_name: str,
                           name: str, description: str, query_text: str,
                           bind_vars: dict, now: str) -> str:
    existing = sorted(canvas_col.find({"name": name, "graphId": graph_name}),
                      key=lambda d: d.get("_key", ""))
    if existing:
        for orphan in existing[1:]:  # dedup orphans from before stable keys
            for e in vp_act_col.find({"_to": orphan["_id"]}):
                vp_act_col.delete(e["_key"])
            canvas_col.delete(orphan["_key"])
        doc = {
            "_key": existing[0]["_key"], "_id": existing[0]["_id"],
            "graphId": graph_name, "name": name, "description": description,
            "queryText": query_text, "bindVariables": bind_vars,
            "createdAt": existing[0].get("createdAt", now), "updatedAt": now,
        }
        canvas_col.replace(doc, check_rev=False)
        action_id = existing[0]["_id"]
    else:
        doc = {
            "_key": _slugify(f"{graph_name}_{name}"),
            "graphId": graph_name, "name": name, "description": description,
            "queryText": query_text, "bindVariables": bind_vars,
            "createdAt": now, "updatedAt": now,
        }
        action_id = canvas_col.insert(doc)["_id"]

    if not list(vp_act_col.find({"_from": vp_id, "_to": action_id})):
        vp_act_col.insert({"_from": vp_id, "_to": action_id, "createdAt": now, "updatedAt": now})
    return action_id


def install_canvas_actions(db, graph_name: str, exclude_vertex: Set[str] = None) -> None:
    """Install schema-driven canvas actions: 2-hop explorer + per-collection expand."""
    ensure_collection(db, "_canvasActions")
    ensure_collection(db, "_viewpointActions", edge=True)  # never assume auto-creation

    canvas_col = db.collection("_canvasActions")
    vp_act_col = db.collection("_viewpointActions")
    vp_id = ensure_default_viewpoint(db, graph_name)
    vertex_colls, edge_colls = get_graph_schema(db, graph_name, exclude_vertex=exclude_vertex)
    if vertex_colls is None:
        return

    edge_list_str = ", ".join(sorted(edge_colls))
    with_clause = "WITH " + ", ".join(sorted(vertex_colls | edge_colls))
    now = now_iso()

    # General 2-hop explorer — RETURN e (edges; Visualizer resolves vertices)
    _upsert_canvas_action(
        canvas_col, vp_act_col, vp_id, graph_name,
        "Find 2-hop neighbors",
        "Expand 2 hops in any direction from selected nodes",
        f"""{with_clause}
FOR node IN @nodes
  FOR v, e IN 1..2 ANY node GRAPH "{graph_name}"
  LIMIT 100
  RETURN e""",
        {"nodes": []}, now,
    )

    # Per-collection 1-hop expand — RETURN p (full path including start node)
    for v_coll in sorted(vertex_colls):
        _upsert_canvas_action(
            canvas_col, vp_act_col, vp_id, graph_name,
            f"[{v_coll}] Expand Relationships",
            f"1-hop expand for {v_coll} nodes",
            f"""{with_clause}
FOR node IN @nodes
  FILTER IS_SAME_COLLECTION("{v_coll}", node)
  FOR v, e, p IN 1..1 ANY node {edge_list_str}
  LIMIT 20
  RETURN p""",
            {"nodes": []}, now,
        )


# ---------------------------------------------------------------------------
# Saved queries — editor sidebar (_editor_saved_queries)
# ---------------------------------------------------------------------------

def install_editor_saved_query(db, key: str, name: str, aql: str, database_name: str) -> str:
    """Upsert into _editor_saved_queries. Sets both content AND value for cross-version compat."""
    ensure_collection(db, "_editor_saved_queries")
    col = db.collection("_editor_saved_queries")
    now = now_iso()
    doc = {
        "_key": key, "name": name, "title": name,
        "content": aql,   # newer ArangoDB UI versions
        "value": aql,     # older ArangoDB UI versions
        "bindVariables": {}, "databaseName": database_name,
        "updatedAt": now,
    }
    if col.has(key):
        existing = col.get(key)
        doc["createdAt"] = existing.get("createdAt", now)
        col.replace(doc, check_rev=False)
    else:
        doc["createdAt"] = now
        col.insert(doc)
    return f"_editor_saved_queries/{key}"


# ---------------------------------------------------------------------------
# Saved queries — Graph Visualizer Queries panel (_queries + _viewpointQueries)
# ---------------------------------------------------------------------------

def install_visualizer_query(db, graph_name: str, key: str, name: str, aql: str) -> str:
    """Upsert into _queries and link via _viewpointQueries for the Visualizer panel."""
    ensure_collection(db, "_queries")
    ensure_collection(db, "_viewpointQueries", edge=True)  # never assume auto-creation

    col = db.collection("_queries")
    vp_q_col = db.collection("_viewpointQueries")
    vp_id = ensure_default_viewpoint(db, graph_name)
    now = now_iso()

    doc = {
        "_key": key, "name": name, "title": name,
        "graphId": graph_name,
        "queryText": aql,   # _queries uses queryText (not content/value)
        "bindVariables": {}, "updatedAt": now,
    }
    if col.has(key):
        existing = col.get(key)
        doc["createdAt"] = existing.get("createdAt", now)
        col.replace(doc, check_rev=False)
        query_id = f"_queries/{key}"
    else:
        doc["createdAt"] = now
        query_id = col.insert(doc)["_id"]

    if not list(vp_q_col.find({"_from": vp_id, "_to": query_id})):
        vp_q_col.insert({"_from": vp_id, "_to": query_id, "createdAt": now, "updatedAt": now})
    return query_id


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import os
    endpoint = os.environ["ARANGO_ENDPOINT"]
    username = os.environ.get("ARANGO_USERNAME", "root")
    password = os.environ.get("ARANGO_PASSWORD", "")
    database = os.environ["ARANGO_DATABASE"]

    client = ArangoClient(hosts=endpoint)
    db = client.db(database, username=username, password=password)

    graph_name = os.environ.get("VIS_GRAPH_ID", "DataGraph")
    theme_raw = json.loads(Path("docs/theme.json").read_text(encoding="utf-8"))

    # Install theme (is_default=True makes it auto-apply when graph is opened)
    install_theme(db, graph_name, theme_raw, is_default=True)

    # Install schema-driven canvas actions
    install_canvas_actions(db, graph_name)

    # Install starter query in global AQL editor sidebar
    MY_QUERY = "FOR d IN Person LIMIT 10 RETURN d"
    install_editor_saved_query(db, "starter_persons", "Starter: Persons", MY_QUERY, database)

    # Install same query in Graph Visualizer Queries panel
    install_visualizer_query(db, graph_name, f"starter_persons_{_slugify(graph_name)}",
                             "Starter: Persons", MY_QUERY)

    print("Done. Refresh the Visualizer (theme in Legend; Queries panel; right-click actions).")


if __name__ == "__main__":
    main()
```

### Key decisions to adjust for your project

- **`graph_name`**: must match the ArangoDB graph name exactly.
- **`is_default=True`**: set to `True` on the theme that should auto-apply; `False` for alternative themes.
- **Rule order in theme JSON**: High → Low → Medium (narrowest bounds first, general-fallback last).
- **`exclude_vertex`**: pass a set of collection names to skip (e.g. RDF artifacts like `OntologyGraph_UnknownResource`).
- **Meta DB**: all helpers default to the target DB — correct for cloud. For self-hosted shared queries, pass `sys_db` instead.

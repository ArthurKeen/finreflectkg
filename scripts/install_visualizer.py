"""Install ArangoDB Graph Visualizer customizations for the FinReflectKG graph.

This is an LPG: there is ONE vertex collection (`Node`) and ONE edge collection
(`relations`); the entity/relationship semantics live in the `type` property, not
in collection names. The Visualizer's `nodeConfigMap`/`edgeConfigMap` key on
*collection* name, so per-`type` styling is expressed through the theme's
attribute-based **rules** (keyed on `node.type` / `e.type`) rather than the
config map. That is the core of the design below.

What it installs (all idempotent — safe to re-run):

  * **Theme** `FinReflectKG` in `_graphThemeStore` — colour + icon + label mapped
    to `Node.type` (grouped into semantic families) and line colour mapped to
    `relations.type`. `chunks` gets a book-page icon so source-text docs render
    distinctly *if* loaded onto the canvas (chunks is intentionally NOT in the
    named graph — see load-report.md).
  * **Saved queries** in `_queries` (Visualizer "Queries" panel) — the repo's
    path-shaped AQL (docs/cypher-queries.md) rewritten to `RETURN p` so each
    loads a connected subgraph onto an empty canvas.
  * **Canvas actions** in `_canvasActions` — right-click-a-node expansions for
    the relationship motifs those queries traverse (discloses, operates_in,
    has_stake_in, depends_on, negatively_impacts), plus generic N-hop explorers.

Connection comes from `.env` via the shared `scripts/arango.py` helper (same as
every other script here — no python-arango dependency).

Schema reference (verified against the live data):
  Node      : { _key, name, type }
  relations : { _key, _from, _to, type, _fromType, _toType, ticker, year,
                startDate, endDate, sourceFile, pageId, chunkKey, ... }
  chunks    : { _key, ticker, year, pageId, chunkId, sourceFile, text }
"""

import uuid
from datetime import datetime, timezone

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")
GRAPH = "FinReflectKG"
THEME_NAME = "FinReflectKG"

# Stable namespace for deriving deterministic rule UUIDs (so re-runs produce
# identical theme documents — the Visualizer keys rules by `id`).
_UUID_NS = uuid.UUID("5f1d2c3b-4a59-4e6f-8b7c-f1392ee87a01")

# Whitespace-only / unknown types fall back to this base style.
NODE_BASE_COLOR = "#a0aec0"   # neutral gray
EDGE_BASE_COLOR = "#cbd5e0"   # light gray

# --------------------------------------------------------------------------- #
# Node type families: family -> (color, {TYPE: fa6-icon}). Color is shared per
# family; the icon distinguishes types within it. Covers ~98.6% of nodes; the
# long tail (9,605 distinct types total) falls back to the base style.
# --------------------------------------------------------------------------- #
NODE_FAMILIES = {
    "financial_metric": ("#2b6cb0", {
        "FIN_METRIC": "fa6-solid:chart-line",
        "OPERATIONAL_METRIC": "fa6-solid:gauge-high",
        "ECON_IND": "fa6-solid:chart-column",
        "FIN_MARKET": "fa6-solid:arrow-trend-up",
        "MARKET": "fa6-solid:store",
    }),
    "financial_instrument": ("#2c7a7b", {
        "FIN_INST": "fa6-solid:building-columns",
        "FIN_ASSET": "fa6-solid:money-bill-trend-up",
        "ASSET": "fa6-solid:sack-dollar",
        "PROPERTY": "fa6-solid:building",
        "INFRASTRUCTURE": "fa6-solid:tower-broadcast",
        "FACILITY": "fa6-solid:industry",
    }),
    "organization": ("#4c51bf", {
        "ORG": "fa6-solid:building",
        "COMP": "fa6-solid:building-user",
        "ORG_REG": "fa6-solid:building-shield",
        "ORG_GOV": "fa6-solid:landmark",
        "SECTOR": "fa6-solid:layer-group",
    }),
    "person_role": ("#6b46c1", {
        "PERSON": "fa6-solid:user",
        "ROLE": "fa6-solid:user-tag",
        "POSITION": "fa6-solid:user-tie",
    }),
    "product_service": ("#c05621", {
        "PRODUCT": "fa6-solid:box",
        "SERVICE": "fa6-solid:concierge-bell",
        "BRAND": "fa6-solid:tag",
        "RAW_MATERIAL": "fa6-solid:cubes",
        "TECHNOLOGY": "fa6-solid:microchip",
    }),
    "risk_legal": ("#c53030", {
        "RISK_FACTOR": "fa6-solid:triangle-exclamation",
        "LITIGATION": "fa6-solid:gavel",
        "LEGAL_DOCUMENT": "fa6-solid:file-contract",
        "LEGAL_DOC": "fa6-solid:file-contract",
        "LEGAL_ACTION": "fa6-solid:scale-balanced",
        "CONTRACT": "fa6-solid:file-signature",
    }),
    "regulatory_policy": ("#b7791f", {
        "REGULATORY_REQUIREMENT": "fa6-solid:clipboard-check",
        "REGULATIVE_REQUIREMENT": "fa6-solid:clipboard-check",
        "ACCOUNTING_POLICY": "fa6-solid:book",
        "POLICY": "fa6-solid:file-shield",
        "FIN_POLICY": "fa6-solid:file-invoice-dollar",
    }),
    "macro_concept": ("#0987a0", {
        "MACRO_CONDITION": "fa6-solid:earth-americas",
        "CONCEPT": "fa6-solid:lightbulb",
        "COMMENTARY": "fa6-solid:comment-dots",
    }),
    "geography": ("#2f855a", {
        "GPE": "fa6-solid:location-dot",
        "LOCATION": "fa6-solid:map-location-dot",
    }),
    "event_action": ("#b83280", {
        "EVENT": "fa6-solid:calendar-day",
        "ACTION": "fa6-solid:bolt",
        "ACTIVITY": "fa6-solid:person-running",
        "OPERATION": "fa6-solid:gears",
        "STRATEGIC_ACTION": "fa6-solid:chess-knight",
        "BUSINESS_ACTIVITY": "fa6-solid:briefcase",
    }),
    "segment_strategy": ("#4a5568", {
        "SEGMENT": "fa6-solid:chart-pie",
        "PROJECT": "fa6-solid:diagram-project",
        "PROGRAM": "fa6-solid:list-check",
        "STRATEGY": "fa6-solid:chess",
        "GOAL": "fa6-solid:bullseye",
    }),
    "esg": ("#38a169", {
        "ESG_TOPIC": "fa6-solid:leaf",
    }),
    "document_data": ("#718096", {
        "DOCUMENT": "fa6-solid:file-lines",
        "DATA": "fa6-solid:database",
        "PROCESS": "fa6-solid:diagram-next",
        "LOGISTICS": "fa6-solid:truck",
        "BENEFIT": "fa6-solid:hand-holding-dollar",
        "TIMESTAMP": "fa6-solid:clock",
        "TIME_PERIOD": "fa6-solid:calendar-days",
    }),
}

# --------------------------------------------------------------------------- #
# Edge type families: family -> (color, [TYPE, ...]). Line colour is shared per
# family. Covers ~91% of edges; the long tail (30,535 distinct types) falls back
# to the base line colour.
# --------------------------------------------------------------------------- #
EDGE_FAMILIES = {
    "disclosure": ("#718096", [
        "discloses", "report", "recognizes", "record", "file", "announces",
        "guides_on", "estimate", "review", "considers", "evaluates", "maintains",
        "include", "have", "serves_as", "served_as", "holds_position",
    ]),
    "negative_impact": ("#c53030", [
        "negatively_impacts", "decrease", "reduces", "impacted_by", "face", "incurs",
    ]),
    "positive_impact": ("#2f855a", [
        "positively_impacts", "increase", "contributes_to", "grant", "receives",
    ]),
    "dependency": ("#c05621", [
        "depends_on", "subject_to", "impact", "affects_stock",
    ]),
    "ownership_investment": ("#2c7a7b", [
        "has_stake_in", "invests_in", "acquires", "hold", "own", "hedge",
    ]),
    "operational": ("#4c51bf", [
        "operates_in", "produce", "supply", "introduces", "develops", "manages",
        "enters_into", "sell", "issue", "pay", "offer", "provide",
    ]),
    "structural": ("#6b46c1", [
        "competes_with", "member_of", "related_to", "involved_in",
        "complies_with", "regulates", "adopts", "amends", "partners_with",
    ]),
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def rule_uuid(kind, type_value):
    """Deterministic per-rule UUID so re-installs produce identical documents."""
    return str(uuid.uuid5(_UUID_NS, f"{kind}:{type_value}"))


# --------------------------------------------------------------------------- #
# REST helpers (idempotent upserts via deterministic _key + overwriteMode)
# --------------------------------------------------------------------------- #
def ensure_collection(name, edge=False):
    """Create a collection if absent. `_`-prefixed collections are system ones."""
    status, _ = req("GET", f"/_api/collection/{name}", db=DB)
    if status == 200:
        return
    body = {"name": name, "type": 3 if edge else 2, "isSystem": name.startswith("_")}
    status, resp = req("POST", "/_api/collection", body, db=DB)
    if status not in (200, 201) and resp.get("errorNum") != 1207:  # 1207 = duplicate
        raise SystemExit(f"failed to create collection {name}: {status} {resp}")


def doc_get(coll, key):
    status, body = req("GET", f"/_api/document/{coll}/{key}", db=DB)
    return body if status == 200 else None


def upsert_doc(coll, key, body, preserve=("createdAt",)):
    """Insert-or-replace by _key, preserving selected fields (e.g. createdAt)."""
    now = now_iso()
    body = dict(body)
    body["_key"] = key
    existing = doc_get(coll, key)
    if existing:
        for f in preserve:
            if f in existing:
                body[f] = existing[f]
        body.setdefault("createdAt", now)
        body["updatedAt"] = now
        status, resp = req("PUT", f"/_api/document/{coll}/{key}", body, db=DB)
    else:
        body["createdAt"] = now
        body["updatedAt"] = now
        status, resp = req("POST", f"/_api/document/{coll}", body, db=DB)
    if status not in (200, 201, 202):
        raise SystemExit(f"upsert {coll}/{key} failed: {status} {resp}")
    return f"{coll}/{key}"


def upsert_edge(coll, key, from_id, to_id):
    return upsert_doc(coll, key, {"_from": from_id, "_to": to_id})


def slug(s):
    out = "".join(c if c.isalnum() else "_" for c in s.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


# --------------------------------------------------------------------------- #
# Viewpoint — canvas actions and saved queries only surface once linked to one.
# --------------------------------------------------------------------------- #
def ensure_viewpoint():
    """Return the _id of the graph's Default viewpoint, reusing one if present."""
    ensure_collection("_viewpoints")
    q = """FOR v IN _viewpoints FILTER v.graphId == @g
             SORT v.name == 'Default' DESC RETURN v"""
    status, body = req("POST", "/_api/cursor", {"query": q, "bindVars": {"g": GRAPH}}, db=DB)
    existing = body.get("result", []) if status in (200, 201) else []
    if existing:
        return existing[0]["_id"]
    key = slug(f"{GRAPH}_default")
    return upsert_doc("_viewpoints", key,
                      {"graphId": GRAPH, "name": "Default",
                       "description": f"Default viewpoint for {GRAPH}"})


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #
def _node_rule(type_value, color, icon):
    """One attribute-based node rule: WHEN type == <value> THEN colour + icon."""
    return {
        "id": rule_uuid("node", type_value),
        "attributePath": "type",
        "attributeType": "string",
        "conditionType": "singleValue",
        "condition": {
            "op": "==",
            "right": {"type": "literal", "value": type_value},
            "config": {
                "background": {"color": color, "iconName": icon},
                "labelAttribute": "name",
                "hoverInfoAttributes": ["name", "type"],
                "rules": [],
            },
            "enabledFields": {"color": True, "icon": True,
                              "labelAttribute": False, "hoverInfoAttributes": False},
        },
    }


def _edge_rule(type_value, color):
    """One attribute-based edge rule: WHEN type == <value> THEN line colour.

    NOTE: the node-rule schema is verified; the edge-rule shape (lineStyle in
    condition.config) mirrors it but is not independently verified by the skill.
    If edges render oddly in the UI, author one edge rule in the Visualizer,
    Save, and read it back from _graphThemeStore as the authoritative template.
    """
    return {
        "id": rule_uuid("edge", type_value),
        "attributePath": "type",
        "attributeType": "string",
        "conditionType": "singleValue",
        "condition": {
            "op": "==",
            "right": {"type": "literal", "value": type_value},
            "config": {
                "lineStyle": {"color": color, "thickness": 1.0},
                "labelAttribute": "type",
                "hoverInfoAttributes": [],
                "rules": [],
            },
            "enabledFields": {"color": True, "icon": False,
                              "labelAttribute": False, "hoverInfoAttributes": False},
        },
    }


def build_theme():
    node_rules = []
    for color, members in NODE_FAMILIES.values():
        for type_value, icon in members.items():
            node_rules.append(_node_rule(type_value, color, icon))

    edge_rules = []
    for color, members in EDGE_FAMILIES.values():
        for type_value in members:
            edge_rules.append(_edge_rule(type_value, color))

    node_config_map = {
        # Base style for any Node whose type matches no rule.
        "Node": {
            "background": {"color": NODE_BASE_COLOR, "iconName": "fa6-solid:circle-nodes"},
            "labelAttribute": "name",
            "hoverInfoAttributes": ["name", "type"],
            "rules": node_rules,
        },
        # chunks is not in the named graph, but style it so source-text docs are
        # visually distinct (a book page) if pulled onto the canvas via a query.
        "chunks": {
            "background": {"color": "#8b6f47", "iconName": "fa6-solid:book-open"},
            "labelAttribute": "pageId",
            "hoverInfoAttributes": ["sourceFile", "pageId", "year", "ticker"],
            "rules": [],
        },
    }
    edge_config_map = {
        "relations": {
            "lineStyle": {"color": EDGE_BASE_COLOR, "thickness": 1.0},
            "labelAttribute": "type",
            "arrowStyle": {"sourceArrowShape": "none", "targetArrowShape": "triangle"},
            "labelStyle": {"color": "#1d2531"},
            "hoverInfoAttributes": ["type", "ticker", "year", "sourceFile"],
            "rules": edge_rules,
        },
    }
    return {
        "name": THEME_NAME,
        "graphId": GRAPH,
        "isDefault": False,   # opt-in via Legend; custom defaults can't be edited in the UI
        "nodeConfigMap": node_config_map,
        "edgeConfigMap": edge_config_map,
    }, len(node_rules), len(edge_rules)


def install_theme():
    ensure_collection("_graphThemeStore")
    theme, n_node, n_edge = build_theme()
    key = slug(f"{GRAPH}_{THEME_NAME}")
    upsert_doc("_graphThemeStore", key, theme)
    print(f"theme '{THEME_NAME}': {n_node} node rules, {n_edge} edge rules")

    # Ensure *some* theme is the auto-applied default so the graph never opens
    # unstyled, without making our (editable) custom theme the default.
    q = "FOR t IN _graphThemeStore FILTER t.graphId == @g AND t.isDefault == true RETURN 1"
    status, body = req("POST", "/_api/cursor", {"query": q, "bindVars": {"g": GRAPH}}, db=DB)
    if status in (200, 201) and not body.get("result"):
        upsert_doc("_graphThemeStore", slug(f"{GRAPH}_Default"), {
            "name": "Default", "graphId": GRAPH, "isDefault": True,
            "nodeConfigMap": {"Node": {"background": {"color": NODE_BASE_COLOR,
                              "iconName": "fa6-solid:circle-nodes"},
                              "labelAttribute": "name", "hoverInfoAttributes": ["name", "type"],
                              "rules": []}},
            "edgeConfigMap": {"relations": {"lineStyle": {"color": EDGE_BASE_COLOR, "thickness": 1.0},
                              "labelAttribute": "type",
                              "arrowStyle": {"sourceArrowShape": "none", "targetArrowShape": "triangle"},
                              "labelStyle": {"color": "#1d2531"}, "hoverInfoAttributes": [], "rules": []}},
        })
        print("theme 'Default': created (isDefault=true baseline)")


# --------------------------------------------------------------------------- #
# Saved queries (Visualizer "Queries" panel) — standalone, self-anchoring,
# RETURN p. Derived from docs/cypher-queries.md, rewritten to load a subgraph.
# Each is keyed by a stable id and linked to the viewpoint via _viewpointQueries.
# --------------------------------------------------------------------------- #
SAVED_QUERIES = [
    {
        "key": "cinf_stakes",
        "name": "CINF — companies it holds a stake in",
        "aql": """WITH Node
LET cinf = FIRST(FOR n IN Node FILTER n.name == "cinf" AND n.type == "ORG" RETURN n._id)
FOR v, e, p IN 1..1 OUTBOUND cinf relations
  FILTER e.type == "has_stake_in"
  LIMIT 50
  RETURN p""",
    },
    {
        "key": "cinf_holdings_metrics",
        "name": "CINF holdings → disclosed financial metrics",
        "aql": """WITH Node
LET cinf = FIRST(FOR n IN Node FILTER n.name == "cinf" AND n.type == "ORG" RETURN n._id)
FOR c, e, p IN 2..2 OUTBOUND cinf relations OPTIONS {uniqueVertices: "global", bfs: true}
  FILTER p.edges[0].type == "has_stake_in"
  FILTER p.edges[1].type == "discloses"
  FILTER p.edges[1]._toType == "FIN_METRIC"
  LIMIT 25
  RETURN p""",
    },
    {
        "key": "apple_network",
        "name": "Apple — supply / stake / operating network",
        "aql": """WITH Node
FOR apple IN Node
  FILTER apple.type == "ORG" AND (apple.name == "aapl" OR apple.name LIKE "%apple%")
  LIMIT 1
  FOR related, e, p IN 1..1 ANY apple relations
    FILTER e.type IN ["supply", "has_stake_in", "operates_in"]
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "risk_propagation_3hop",
        "name": "Risk → org → org → location (3-hop propagation)",
        "aql": """WITH Node
FOR risk IN Node
  FILTER risk.type IN ["RISK", "RISK_FACTOR", "EVENT"]
  LIMIT 50
  FOR loc, e, p IN 3..3 OUTBOUND risk relations OPTIONS {bfs: true, uniqueVertices: "path"}
    FILTER p.edges[0].type == "negatively_impacts" AND p.vertices[1].type == "ORG"
    FILTER p.edges[1].type == "depends_on" AND p.vertices[2].type == "ORG"
    FILTER p.edges[2].type == "operates_in" AND loc.type == "GPE"
    LIMIT 20
    RETURN p""",
    },
    {
        "key": "dependency_chains_3hop",
        "name": "3-hop dependency chains (org → org → org → org)",
        "aql": """WITH Node
FOR org IN Node
  FILTER org.type == "ORG" AND org.name != null
  FOR v, e, p IN 3..3 OUTBOUND org relations OPTIONS {bfs: true, uniqueVertices: "path"}
    FILTER p.edges[*].type ALL == "depends_on"
    FILTER p.edges[*]._toType ALL == "ORG"
    LIMIT 15
    RETURN p""",
    },
    {
        "key": "circular_dependencies_bigtech",
        "name": "Circular dependencies among big-tech firms",
        "aql": """WITH Node
LET majors = ["aapl", "msft", "googl", "amzn", "tsla"]
FOR org IN Node
  FILTER org.type == "ORG" AND org.name IN majors
  FOR v, e, p IN 2..3 OUTBOUND org relations OPTIONS {uniqueVertices: "path"}
    FILTER p.edges[*].type ALL == "depends_on"
    FILTER v._key == org._key
    LIMIT 10
    RETURN p""",
    },
    {
        "key": "company_year_slice",
        "name": "Company-year disclosure slice (edit ticker/year)",
        "aql": """// Loads one company's edges for a year window (uses the rel_ticker_year index).
// Edit @ticker / @y_from / @y_to, or replace with literals.
LET ticker = "well"
LET y_from = 2021
LET y_to = 2021
FOR e IN relations
  FILTER e.ticker == ticker AND e.year >= y_from AND e.year <= y_to
  LIMIT 200
  RETURN e""",
    },
]


def install_saved_queries(vp_id):
    ensure_collection("_queries")
    ensure_collection("_viewpointQueries", edge=True)
    ensure_collection("_editor_saved_queries")
    for q in SAVED_QUERIES:
        qkey = slug(f"{GRAPH}_{q['key']}")
        qid = upsert_doc("_queries", qkey, {
            "name": q["name"], "title": q["name"], "graphId": GRAPH,
            "queryText": q["aql"], "bindVariables": {},
        })
        upsert_edge("_viewpointQueries", slug(f"{vp_id}_{qkey}"), vp_id, qid)
        # Also expose in the global AQL editor sidebar (different collection/fields).
        upsert_doc("_editor_saved_queries", slug(f"finreflectkg_{q['key']}"), {
            "name": q["name"], "title": q["name"],
            "content": q["aql"], "value": q["aql"],
            "bindVariables": {}, "databaseName": DB,
        })
    print(f"saved queries: {len(SAVED_QUERIES)} in _queries + _editor_saved_queries")


# --------------------------------------------------------------------------- #
# Canvas actions — right-click a selected node to expand. Bind @nodes. RETURN p
# (full path) so the start node, edge, and neighbour all render. Derived from the
# relationship motifs in the saved queries above.
# --------------------------------------------------------------------------- #
CANVAS_ACTIONS = [
    {
        "key": "expand_all_1hop",
        "name": "Expand: all neighbors (1 hop)",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 ANY node relations
  LIMIT 50
  RETURN p""",
    },
    {
        "key": "expand_all_2hop",
        "name": "Expand: 2-hop neighborhood",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e IN 1..2 ANY node relations
  LIMIT 100
  RETURN e""",
    },
    {
        "key": "expand_discloses_out",
        "name": "Expand: metrics this discloses",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "discloses" AND e._toType == "FIN_METRIC"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_discloses_in",
        "name": "Expand: who discloses this",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 INBOUND node relations
    FILTER e.type == "discloses" AND e._fromType == "ORG"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_operates_in",
        "name": "Expand: operates in (geographies)",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "operates_in" AND e._toType == "GPE"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_has_stake_in",
        "name": "Expand: companies this has a stake in",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "has_stake_in"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_stakeholders_in",
        "name": "Expand: who has a stake in this",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 INBOUND node relations
    FILTER e.type == "has_stake_in"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_depends_on",
        "name": "Expand: depends on",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "depends_on" AND e._toType == "ORG"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_negatively_impacted_by",
        "name": "Expand: negatively impacted by",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 INBOUND node relations
    FILTER e.type == "negatively_impacts"
    LIMIT 50
    RETURN p""",
    },
]


def install_canvas_actions(vp_id):
    ensure_collection("_canvasActions")
    ensure_collection("_viewpointActions", edge=True)
    for a in CANVAS_ACTIONS:
        akey = slug(f"{GRAPH}_{a['key']}")
        aid = upsert_doc("_canvasActions", akey, {
            "name": a["name"], "description": a["name"], "graphId": GRAPH,
            "queryText": a["aql"], "bindVariables": {"nodes": []},
        })
        upsert_edge("_viewpointActions", slug(f"{vp_id}_{akey}"), vp_id, aid)
    print(f"canvas actions: {len(CANVAS_ACTIONS)} in _canvasActions")


def main():
    status, _ = req("GET", f"/_api/gharial/{GRAPH}", db=DB)
    if status != 200:
        raise SystemExit(
            f"graph '{GRAPH}' not found in db '{DB}' — run scripts/create_graph.py first")

    install_theme()
    vp_id = ensure_viewpoint()
    print(f"viewpoint: {vp_id}")
    install_saved_queries(vp_id)
    install_canvas_actions(vp_id)
    print("visualizer customization complete")


if __name__ == "__main__":
    main()

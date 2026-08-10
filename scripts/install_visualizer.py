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
THEME_NAME = "FinReflectKG"
# ARANGO_TEMPORAL=1 -> also install the time-travel demo assets (§4.8): as-of / diff /
# currently-valid saved queries + a "current vs historical" edge theme. Set by the
# FinReflectKgTemporal build; the non-temporal distributions leave it unset (skipped).
TEMPORAL = ENV.get("ARANGO_TEMPORAL")
NEVER_EXPIRES = 999912   # open-ended sentinel, mirrors scripts/augment_temporal.py


def _detect_graph():
    """The user graph in this DB (excludes the Visualizer's own `_viewpointGraph`).

    Graph names differ per distribution: the baseline and OneShard DBs both name
    their graph `FinReflectKG`, while the SmartGraph DB names it `FinReflectKgSmart`.
    Detecting it (rather than hard-coding) lets one installer serve all three.
    """
    from arango import req as _req  # local import: module-level req already available
    status, body = _req("POST", "/_api/cursor", {
        "query": "FOR g IN _graphs FILTER g._key != '_viewpointGraph' "
                 "AND NOT STARTS_WITH(g._key, '_') LIMIT 1 RETURN g._key"}, db=DB)
    names = body.get("result", []) if status in (200, 201) else []
    return names[0] if names else "FinReflectKG"


# Explicit override wins (build scripts can export ARANGO_GRAPH); else auto-detect.
GRAPH = ENV.get("ARANGO_GRAPH") or _detect_graph()

# Whether the type-based theme auto-applies (is the graph's default). Default ON so the
# LPG per-`type` styling shows without a Legend click. Trade-off: a theme that IS the
# UI default cannot be edited/saved in the Visualizer UI — edit it here and re-run.
# Set ARANGO_THEME_DEFAULT=0 to keep it opt-in (plain "Default" auto-applies instead).
THEME_AS_DEFAULT = ENV.get("ARANGO_THEME_DEFAULT", "1").lower() in ("1", "true", "yes")

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
# Icons are Material Design Icons (`mdi:`) — the set this ArangoDB Graph Visualizer
# resolves (its built-in Default theme uses `mdi:table`). `fa6-solid:` names do NOT
# resolve here: the whole rule config is rejected and nodes fall back to the generic
# glyph (uniform, no per-type colour/icon).
NODE_FAMILIES = {
    "financial_metric": ("#2b6cb0", {
        "FIN_METRIC": "mdi:chart-line",
        "OPERATIONAL_METRIC": "mdi:speedometer",
        "ECON_IND": "mdi:chart-bar",
        "FIN_MARKET": "mdi:trending-up",
        "MARKET": "mdi:store",
    }),
    "financial_instrument": ("#2c7a7b", {
        "FIN_INST": "mdi:bank",
        "FIN_ASSET": "mdi:cash-multiple",
        "ASSET": "mdi:currency-usd",
        "PROPERTY": "mdi:office-building",
        "INFRASTRUCTURE": "mdi:radio-tower",
        "FACILITY": "mdi:factory",
    }),
    "organization": ("#4c51bf", {
        "ORG": "mdi:domain",
        "COMP": "mdi:office-building",
        "ORG_REG": "mdi:shield-account",
        "ORG_GOV": "mdi:bank",
        "SECTOR": "mdi:layers",
    }),
    "person_role": ("#6b46c1", {
        "PERSON": "mdi:account",
        "ROLE": "mdi:account-tag",
        "POSITION": "mdi:account-tie",
    }),
    "product_service": ("#c05621", {
        "PRODUCT": "mdi:package-variant",
        "SERVICE": "mdi:room-service",
        "BRAND": "mdi:tag",
        "RAW_MATERIAL": "mdi:cube-outline",
        "TECHNOLOGY": "mdi:chip",
    }),
    "risk_legal": ("#c53030", {
        "RISK_FACTOR": "mdi:alert",
        "LITIGATION": "mdi:gavel",
        "LEGAL_DOCUMENT": "mdi:file-document",
        "LEGAL_DOC": "mdi:file-document",
        "LEGAL_ACTION": "mdi:scale-balance",
        "CONTRACT": "mdi:file-document-edit",
    }),
    "regulatory_policy": ("#b7791f", {
        "REGULATORY_REQUIREMENT": "mdi:clipboard-check",
        "REGULATIVE_REQUIREMENT": "mdi:clipboard-check",
        "ACCOUNTING_POLICY": "mdi:book-open-variant",
        "POLICY": "mdi:file-lock",
        "FIN_POLICY": "mdi:file-document-outline",
    }),
    "macro_concept": ("#0987a0", {
        "MACRO_CONDITION": "mdi:earth",
        "CONCEPT": "mdi:lightbulb",
        "COMMENTARY": "mdi:comment-text",
    }),
    "geography": ("#2f855a", {
        "GPE": "mdi:map-marker",
        "LOCATION": "mdi:map-marker-radius",
    }),
    "event_action": ("#b83280", {
        "EVENT": "mdi:calendar",
        "ACTION": "mdi:lightning-bolt",
        "ACTIVITY": "mdi:run",
        "OPERATION": "mdi:cog",
        "STRATEGIC_ACTION": "mdi:flag",
        "BUSINESS_ACTIVITY": "mdi:briefcase",
    }),
    "segment_strategy": ("#4a5568", {
        "SEGMENT": "mdi:chart-pie",
        "PROJECT": "mdi:sitemap",
        "PROGRAM": "mdi:format-list-checks",
        "STRATEGY": "mdi:flag-variant",
        "GOAL": "mdi:target",
    }),
    "esg": ("#38a169", {
        "ESG_TOPIC": "mdi:leaf",
    }),
    "document_data": ("#718096", {
        "DOCUMENT": "mdi:text-box",
        "DATA": "mdi:database",
        "PROCESS": "mdi:cog-outline",
        "LOGISTICS": "mdi:truck",
        "BENEFIT": "mdi:hand-coin",
        "TIMESTAMP": "mdi:clock",
        "TIME_PERIOD": "mdi:calendar-month",
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


def _cursor(query, bind_vars=None):
    """Run a read-only AQL query and return its result list (empty on error)."""
    status, body = req("POST", "/_api/cursor",
                       {"query": query, "bindVars": bind_vars or {}}, db=DB)
    return body.get("result", []) if status in (200, 201) else []


# --------------------------------------------------------------------------- #
# Reconciliation — the installer upserts, so a query/action REMOVED from the
# lists below would otherwise orphan its documents (and viewpoint edges) forever.
# These helpers delete our own stale docs on re-run, scoped by key namespace so
# the Visualizer's own built-in docs (numeric keys) are never touched.
# --------------------------------------------------------------------------- #
def reconcile_namespace(coll, keep_keys, edge_coll=None):
    """Drop docs in `coll` under this graph's key prefix that weren't installed
    this run, plus any `edge_coll` viewpoint edges pointing at them."""
    ns = slug(GRAPH) + "_"
    for k in _cursor("FOR d IN @@c FILTER STARTS_WITH(d._key, @ns) RETURN d._key",
                     {"@c": coll, "ns": ns}):
        if k in keep_keys:
            continue
        if edge_coll:
            for e in _cursor("FOR e IN @@e FILTER e._to == @to RETURN e._key",
                             {"@e": edge_coll, "to": f"{coll}/{k}"}):
                req("DELETE", f"/_api/document/{edge_coll}/{e}", db=DB)
        req("DELETE", f"/_api/document/{coll}/{k}", db=DB)
        print(f"reconcile: removed stale {coll}/{k}")


def reconcile_editor_queries(keep_keys):
    """`_editor_saved_queries` has no graphId and uses a fixed 'finreflectkg_'
    key prefix across all distributions; reconcile within that namespace only."""
    for k in _cursor("FOR d IN _editor_saved_queries "
                     "FILTER STARTS_WITH(d._key, 'finreflectkg_') RETURN d._key"):
        if k not in keep_keys:
            req("DELETE", f"/_api/document/_editor_saved_queries/{k}", db=DB)
            print(f"reconcile: removed stale _editor_saved_queries/{k}")


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
            "op": "=",  # single '=' is the Visualizer equality op; '==' renders as an empty condition (inert rule)
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
            "op": "=",  # single '=' is the Visualizer equality op; '==' renders as an empty condition (inert rule)
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
            "background": {"color": NODE_BASE_COLOR, "iconName": "mdi:circle-outline"},
            "labelAttribute": "name",
            "hoverInfoAttributes": ["name", "type"],
            "rules": node_rules,
        },
        # chunks is not in the named graph, but style it so source-text docs are
        # visually distinct (a book page) if pulled onto the canvas via a query.
        "chunks": {
            "background": {"color": "#8b6f47", "iconName": "mdi:book-open-page-variant"},
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
        "isDefault": THEME_AS_DEFAULT,   # auto-apply the type styling (see THEME_AS_DEFAULT)
        "nodeConfigMap": node_config_map,
        "edgeConfigMap": edge_config_map,
    }, len(node_rules), len(edge_rules)


def _currency_edge_rule():
    """Temporal 'currency' edge rule: colour still-current facts
    (validTo == NEVER_EXPIRES) distinctly; historical edges fall back to the muted
    base line colour. Keyed on the numeric validTo (equality op is a single '=')."""
    return {
        "id": rule_uuid("edge", "currency_current"),
        "attributePath": "validTo",
        "attributeType": "number",
        "conditionType": "singleValue",
        "condition": {
            "op": "=",
            "right": {"type": "literal", "value": NEVER_EXPIRES},
            "config": {
                "lineStyle": {"color": "#2f855a", "thickness": 1.8},  # current = bold green
                "labelAttribute": "type",
                "hoverInfoAttributes": ["type", "validFrom", "validTo", "ticker"],
                "rules": [],
            },
            "enabledFields": {"color": True, "icon": False,
                              "labelAttribute": False, "hoverInfoAttributes": False},
        },
    }


def build_currency_theme(base_theme):
    """Second, non-default theme for the time-travel DB: nodes keep their type
    styling (reused from the type theme); edges are coloured by currency — bold
    green if still valid, muted grey if historical."""
    return {
        "name": "FinReflectKG-currency", "graphId": GRAPH, "isDefault": False,
        "nodeConfigMap": base_theme["nodeConfigMap"],
        "edgeConfigMap": {"relations": {
            "lineStyle": {"color": EDGE_BASE_COLOR, "thickness": 1.0},   # historical = grey
            "labelAttribute": "type",
            "arrowStyle": {"sourceArrowShape": "none", "targetArrowShape": "triangle"},
            "labelStyle": {"color": "#1d2531"},
            "hoverInfoAttributes": ["type", "validFrom", "validTo", "ticker"],
            "rules": [_currency_edge_rule()],
        }},
    }


def install_theme():
    ensure_collection("_graphThemeStore")
    theme, n_node, n_edge = build_theme()
    type_key = slug(f"{GRAPH}_{THEME_NAME}")
    upsert_doc("_graphThemeStore", type_key, theme)
    print(f"theme '{THEME_NAME}': {n_node} node rules, {n_edge} edge rules "
          f"(isDefault={THEME_AS_DEFAULT})")

    # Plain fallback default theme. The Visualizer AUTO-CREATES its own "Default"
    # theme (name "Default", description "Default graph theme") the first time the
    # graph is opened in the UI, so blindly adding our own leaves TWO "Default"
    # entries in the Legend. Reuse an existing "Default" if present (prefer the
    # built-in, identified by its description), dedupe any extras, and only create
    # our own when none exists yet.
    dup = _cursor(
        "FOR t IN _graphThemeStore FILTER t.graphId == @g AND t.name == 'Default' "
        "SORT t.description == 'Default graph theme' DESC, t._key RETURN t._key",
        {"g": GRAPH})
    if dup:
        default_key = dup[0]                       # keep the built-in if one exists
        for extra in dup[1:]:                      # drop redundant duplicate Defaults
            req("DELETE", f"/_api/document/_graphThemeStore/{extra}", db=DB)
            print(f"reconcile: removed duplicate Default theme {extra}")
    else:
        default_key = slug(f"{GRAPH}_Default")
        upsert_doc("_graphThemeStore", default_key, {
            "name": "Default", "graphId": GRAPH, "isDefault": not THEME_AS_DEFAULT,
            "nodeConfigMap": {"Node": {"background": {"color": NODE_BASE_COLOR,
                              "iconName": "mdi:circle-outline"},
                              "labelAttribute": "name", "hoverInfoAttributes": ["name", "type"],
                              "rules": []}},
            "edgeConfigMap": {"relations": {"lineStyle": {"color": EDGE_BASE_COLOR, "thickness": 1.0},
                              "labelAttribute": "type",
                              "arrowStyle": {"sourceArrowShape": "none", "targetArrowShape": "triangle"},
                              "labelStyle": {"color": "#1d2531"}, "hoverInfoAttributes": [], "rules": []}},
        })

    # Temporal 'currency' theme (non-default) — only on the time-travel DB. Installed
    # before the enforcement loop below so it is included in the one-default check.
    if TEMPORAL:
        curr_key = slug(f"{GRAPH}_currency")
        upsert_doc("_graphThemeStore", curr_key, build_currency_theme(theme))
        print(f"temporal currency theme installed (non-default): {curr_key}")

    # Enforce exactly one isDefault:true for this graph (Visualizer corrupts with
    # zero or multiple). The intended default is the type theme, or the plain
    # fallback when THEME_AS_DEFAULT is off.
    want = type_key if THEME_AS_DEFAULT else default_key
    q = "FOR t IN _graphThemeStore FILTER t.graphId == @g RETURN t._key"
    status, body = req("POST", "/_api/cursor", {"query": q, "bindVars": {"g": GRAPH}}, db=DB)
    for k in (body.get("result", []) if status in (200, 201) else []):
        doc = doc_get("_graphThemeStore", k)
        if doc and bool(doc.get("isDefault")) != (k == want):
            doc["isDefault"] = (k == want)
            req("PUT", f"/_api/document/_graphThemeStore/{k}", doc, db=DB)
    print(f"default theme for '{GRAPH}': {want}")


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
        # Seed from `depends_on` ORG→ORG edges (bounded, index-backed via the
        # type-leading VCI) rather than scanning EVERY ORG node — the original
        # unbounded `FOR org IN Node FILTER type=="ORG"` outer loop timed out
        # (query killed) on the baseline/OneShard cluster.
        "aql": """WITH Node
FOR seed IN relations
  FILTER seed.type == "depends_on" AND seed._fromType == "ORG" AND seed._toType == "ORG"
  LIMIT 3000
  FOR v, e, p IN 3..3 OUTBOUND seed._from relations OPTIONS {bfs: true, uniqueVertices: "path"}
    FILTER p.edges[*].type ALL == "depends_on"
    FILTER p.edges[*]._toType ALL == "ORG"
    LIMIT 15
    RETURN p""",
    },
    # NOTE: a "circular dependencies among big-tech firms" query was removed —
    # the dataset contains no `depends_on` cycles among aapl/msft/googl/amzn/tsla
    # (verified), and a global cycle search is prohibitively expensive here, so
    # the query could only ever return empty. Reinstate only if the data changes.
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

# Time-travel saved queries (§4.8) — installed only when ARANGO_TEMPORAL=1 (the
# FinReflectKgTemporal DB), keyed on the numeric validFrom/validTo fields. Half-open
# as-of predicate `validFrom <= asof AND validTo > asof`; asof is a YYYYMM literal.
TEMPORAL_SAVED_QUERIES = [
    {
        "key": "tt_asof_company",
        "name": "Time-travel — as-of: a company's facts at a given month (edit ticker/asof)",
        "aql": """// AS-OF snapshot: one company's facts valid at @asof (YYYYMM). Edit ticker / asof.
LET ticker = "aapl"
LET asof = 201806
FOR e IN relations
  FILTER e.ticker == ticker AND e.validFrom <= asof AND e.validTo > asof
  LIMIT 300
  RETURN e""",
    },
    {
        "key": "tt_current_company",
        "name": "Time-travel — currently-valid (open-ended) facts for a company (edit ticker)",
        "aql": """// Facts still valid as of the latest filing (validTo == NEVER_EXPIRES). Edit ticker.
LET ticker = "aapl"
FOR e IN relations
  FILTER e.ticker == ticker AND e.validTo == 999912
  LIMIT 300
  RETURN e""",
    },
    {
        "key": "tt_diff_company",
        "name": "Time-travel — diff: facts that appeared between two months (edit ticker/a/b)",
        "aql": """// Facts valid as-of @b but NOT as-of @a (appeared). Edit ticker / a / b (YYYYMM).
LET ticker = "aapl"
LET a = 201406
LET b = 202406
LET aset = (FOR x IN relations FILTER x.ticker == ticker AND x.validFrom <= a AND x.validTo > a
              RETURN CONCAT(x._from, "|", x.type, "|", x._to))
FOR e IN relations
  FILTER e.ticker == ticker AND e.validFrom <= b AND e.validTo > b
    AND CONCAT(e._from, "|", e.type, "|", e._to) NOT IN aset
  LIMIT 300
  RETURN e""",
    },
    {
        "key": "tt_backward_looking",
        "name": "Time-travel — backward-looking assertions for a company (edit ticker/lag)",
        "aql": """// Facts a company's filings assert about periods >= @lag years earlier (backward-looking /
// historical references; formal restatements are a subset). Edit ticker / lag (years).
LET ticker = "etr"
LET lag = 3
FOR e IN relations
  FILTER e.ticker == ticker AND e.startDate != null
    AND (e.year - TO_NUMBER(SUBSTRING(e.startDate, 0, 4))) >= lag
  LIMIT 300
  RETURN e""",
    },
    {
        "key": "tt_bitemporal_known_from",
        "name": "Time-travel — facts about a period first known from later filings (edit ticker/period/knownFrom)",
        "aql": """// BITEMPORAL: facts about fiscal @period (YYYY) that a company reported only in filing
// year >= @knownFrom — i.e. knowledge that arrived later. Edit ticker / period / knownFrom.
LET ticker = "amzn"
LET period = "2020"
LET knownFrom = 2022
FOR e IN relations
  FILTER e.ticker == ticker AND e.startDate != null
    AND SUBSTRING(e.startDate, 0, 4) == period AND e.year >= knownFrom
  LIMIT 300
  RETURN e""",
    },
]


def install_saved_queries(vp_id):
    ensure_collection("_queries")
    ensure_collection("_viewpointQueries", edge=True)
    ensure_collection("_editor_saved_queries")
    query_keys, editor_keys = set(), set()
    queries = SAVED_QUERIES + (TEMPORAL_SAVED_QUERIES if TEMPORAL else [])
    for q in queries:
        qkey = slug(f"{GRAPH}_{q['key']}")
        query_keys.add(qkey)
        qid = upsert_doc("_queries", qkey, {
            "name": q["name"], "title": q["name"], "graphId": GRAPH,
            "queryText": q["aql"], "bindVariables": {},
        })
        upsert_edge("_viewpointQueries", slug(f"{vp_id}_{qkey}"), vp_id, qid)
        # Also expose in the global AQL editor sidebar (different collection/fields).
        ekey = slug(f"finreflectkg_{q['key']}")
        editor_keys.add(ekey)
        upsert_doc("_editor_saved_queries", ekey, {
            "name": q["name"], "title": q["name"],
            "content": q["aql"], "value": q["aql"],
            "bindVariables": {}, "databaseName": DB,
        })
    # Self-heal: drop any query retired from SAVED_QUERIES (e.g. the removed
    # circular-dependencies query) so re-runs don't leave stale docs behind.
    reconcile_namespace("_queries", query_keys, edge_coll="_viewpointQueries")
    reconcile_editor_queries(editor_keys)
    print(f"saved queries: {len(queries)} in _queries + _editor_saved_queries"
          f"{f' (incl. {len(TEMPORAL_SAVED_QUERIES)} time-travel)' if TEMPORAL else ''}")


# --------------------------------------------------------------------------- #
# Canvas actions — right-click a selected node to expand. Bind @nodes. RETURN p
# (full path) so the start node, edge, and neighbour all render. Derived from the
# relationship motifs in the saved queries above.
# --------------------------------------------------------------------------- #
def action_name(types, base):
    """Compose the display name '[<types>] <base>'. The Visualizer shows EVERY
    canvas action on EVERY node's right-click menu (it does not filter by node
    type), so the bracketed applicable-type list is the analyst's only cue for
    which node types an action is meaningful on. Use ["*"] for actions that apply
    to any node. `types` are the LPG `Node.type` values the traversal is rooted
    on, stored verbatim in `applicableTypes` so name and field never drift."""
    return f"[{', '.join(types)}] {base}"


# Each action carries `types` (the Node.type values it is designed for — the
# root/right-clicked node, ["*"] for any) and a `base` name; install_canvas_actions
# composes the `[types] base` display name and stores `applicableTypes`.
CANVAS_ACTIONS = [
    {
        "key": "expand_all_1hop",
        "types": ["*"],
        "base": "Expand: all neighbors (1 hop)",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 ANY node relations
  LIMIT 50
  RETURN p""",
    },
    {
        "key": "expand_all_2hop",
        "types": ["*"],
        "base": "Expand: 2-hop neighborhood",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e IN 1..2 ANY node relations
  LIMIT 100
  RETURN e""",
    },
    {
        "key": "expand_discloses_out",
        "types": ["ORG"],
        "base": "Expand: metrics this discloses",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "discloses" AND e._toType == "FIN_METRIC"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_discloses_in",
        "types": ["FIN_METRIC"],
        "base": "Expand: who discloses this",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 INBOUND node relations
    FILTER e.type == "discloses" AND e._fromType == "ORG"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_operates_in",
        "types": ["ORG"],
        "base": "Expand: operates in (geographies)",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "operates_in" AND e._toType == "GPE"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_has_stake_in",
        "types": ["ORG"],
        "base": "Expand: companies this has a stake in",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "has_stake_in"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_stakeholders_in",
        "types": ["COMP", "FIN_INST", "ORG"],
        "base": "Expand: who has a stake in this",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 INBOUND node relations
    FILTER e.type == "has_stake_in"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_depends_on",
        "types": ["ORG"],
        "base": "Expand: depends on",
        "aql": """WITH Node
FOR node IN @nodes
  FOR v, e, p IN 1..1 OUTBOUND node relations
    FILTER e.type == "depends_on" AND e._toType == "ORG"
    LIMIT 50
    RETURN p""",
    },
    {
        "key": "expand_negatively_impacted_by",
        "types": ["FIN_METRIC", "ORG"],
        "base": "Expand: negatively impacted by",
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
    action_keys = set()
    for a in CANVAS_ACTIONS:
        akey = slug(f"{GRAPH}_{a['key']}")
        action_keys.add(akey)
        name = action_name(a["types"], a["base"])
        aid = upsert_doc("_canvasActions", akey, {
            "name": name, "description": name, "graphId": GRAPH,
            "applicableTypes": a["types"],
            "queryText": a["aql"], "bindVariables": {"nodes": []},
        })
        upsert_edge("_viewpointActions", slug(f"{vp_id}_{akey}"), vp_id, aid)
    reconcile_namespace("_canvasActions", action_keys, edge_coll="_viewpointActions")
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

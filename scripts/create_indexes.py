"""Create the vertex-centric and lookup indexes, post-load.

Run AFTER the bulk import completes (building indexes on populated collections
is far faster than maintaining them during insert).
"""

import time

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")

# (collection, fields, name) — all persistent indexes.
INDEXES = [
    # Node-anchored VCIs: engaged by direct edge queries with a bound _from/_to.
    ("relations", ["_from", "type", "_toType"], "vci_from_type_totype"),
    ("relations", ["_to", "type", "_fromType"], "vci_to_type_fromtype"),
    ("Node", ["name"], "node_name"),
    ("Node", ["type"], "node_type"),
    # Optional temporal/company slice — comment out if not needed by benchmarks.
    ("relations", ["ticker", "year"], "rel_ticker_year"),
    # Type-anchored (label-rooted) access path — added 2026-07-22 (M5/G6). The two
    # node-anchored VCIs above require a bound start node; label-wide aggregations
    # ("all :ORG operating in > N :GPE") have none, so without a type-leading index
    # they scan the full edge collection. These prune such filters to the matching
    # slice (operates_in/ORG/GPE = 1.79% of edges): est. cost 119,966,595 -> 465,
    # ~1.9s vs. timing out. Only direct edge-collection queries use them (not pattern
    # traversals). See docs/PRD.md §4.2 and docs/nl-graphrag.md.
    ("relations", ["type", "_fromType", "_toType"], "vci_type_fromtype_totype"),
    ("relations", ["type", "_toType", "_fromType"], "vci_type_totype_fromtype"),
]


def create(collection, fields, name):
    body = {
        "type": "persistent",
        "fields": fields,
        "name": name,
        "unique": False,
        "sparse": False,
        "inBackground": False,  # exclusive build; POC DB has no live traffic
    }
    t0 = time.time()
    status, resp = req(
        "POST", f"/_api/index?collection={collection}", body, db=DB, timeout=3600
    )
    dt = time.time() - t0
    if status in (200, 201):
        state = "created" if resp.get("isNewlyCreated") else "exists"
        print(f"{collection}.{name} {fields}: {state} ({dt:.1f}s)")
    else:
        raise SystemExit(f"index {name} failed: {status} {resp}")


if __name__ == "__main__":
    for c, f, n in INDEXES:
        create(c, f, n)
    print("indexing complete")

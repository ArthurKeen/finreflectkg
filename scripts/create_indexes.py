"""Create the vertex-centric and lookup indexes, post-load.

Run AFTER the bulk import completes (building indexes on populated collections
is far faster than maintaining them during insert).
"""

import time

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")

# (collection, fields, name) — all persistent indexes.
INDEXES = [
    ("relations", ["_from", "type", "_toType"], "vci_from_type_totype"),
    ("relations", ["_to", "type", "_fromType"], "vci_to_type_fromtype"),
    ("Node", ["name"], "node_name"),
    ("Node", ["type"], "node_type"),
    # Optional temporal/company slice — comment out if not needed by benchmarks.
    ("relations", ["ticker", "year"], "rel_ticker_year"),
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

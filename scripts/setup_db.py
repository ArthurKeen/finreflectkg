"""Provision the FinReflectKG database and its collections (idempotent).

Creates database `FinReflectKG` (from .env ARANGO_DB) plus:
  Node       — document collection
  relations  — edge collection
  chunks     — document collection

Secondary indexes are created separately, post-load (scripts/create_indexes.py).
"""

from arango import ENV, req

DB = ENV.get("ARANGO_DB", "FinReflectKG")
# Optional database-creation options (per-build, via env):
#   ARANGO_DB_SHARDING="single"  -> create a OneShard database
#   ARANGO_REPLICATION_FACTOR=2  -> default replication for collections in the db
#   ARANGO_WRITE_CONCERN=1
SHARDING = ENV.get("ARANGO_DB_SHARDING")  # e.g. "single" for OneShard
REPLICATION_FACTOR = ENV.get("ARANGO_REPLICATION_FACTOR")
WRITE_CONCERN = ENV.get("ARANGO_WRITE_CONCERN")
# ARANGO_SMART=1 -> create the database only; the SmartGraph (create_smart_graph.py)
# creates the smart-sharded Node/relations/chunks instead of these plain ones.
SMART = ENV.get("ARANGO_SMART")

COLLECTIONS = [
    ("Node", 2),       # type 2 = document
    ("relations", 3),  # type 3 = edge
    ("chunks", 2),
]


def _db_options():
    opts = {}
    if SHARDING:
        opts["sharding"] = SHARDING
    if REPLICATION_FACTOR:
        opts["replicationFactor"] = int(REPLICATION_FACTOR)
    if WRITE_CONCERN:
        opts["writeConcern"] = int(WRITE_CONCERN)
    return opts


def ensure_database():
    status, body = req("GET", "/_api/database")
    existing = body.get("result", [])
    if DB in existing:
        print(f"database {DB}: exists")
        return
    payload = {"name": DB}
    opts = _db_options()
    if opts:
        payload["options"] = opts
    status, body = req("POST", "/_api/database", payload)
    if status in (200, 201):
        print(f"database {DB}: created (options={opts or 'defaults'})")
    else:
        raise SystemExit(f"failed to create database {DB}: {status} {body}")


def ensure_collection(name, ctype):
    status, body = req(
        "POST", "/_api/collection", {"name": name, "type": ctype}, db=DB
    )
    if status in (200, 201):
        print(f"collection {name}: created (type {ctype})")
    elif body.get("errorNum") == 1207:  # duplicate name
        print(f"collection {name}: exists")
    else:
        raise SystemExit(f"failed to create collection {name}: {status} {body}")


if __name__ == "__main__":
    ensure_database()
    if SMART:
        print("ARANGO_SMART set: database only — smart collections created by "
              "create_smart_graph.py")
    else:
        for name, ctype in COLLECTIONS:
            ensure_collection(name, ctype)
    print("provisioning complete")

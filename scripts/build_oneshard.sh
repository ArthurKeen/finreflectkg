#!/usr/bin/env bash
# Build the FinReflectKgOneShard database — a true OneShard build of the same
# data as FinReflectKG (sharding: "single", all collections on one DBServer).
#
# Reuses the parameterized pipeline; assumes data/staging/full already exists
# (produced by scripts/preprocess.py). Imports one-way from local staging rather
# than dump/restore, so only one WAN direction is paid for. Idempotent.
#
# Usage:
#   ./scripts/build_oneshard.sh                 # full build (import + index + graph + validate)
#   THREADS=16 ./scripts/build_oneshard.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PY:-.venv/bin/python}"
[[ -x "$PY" ]] || PY="python3"

# --- per-build configuration (overrides .env via arango.py env-overlay) -------
export ARANGO_DB="${ARANGO_DB:-FinReflectKgOneShard}"
export ARANGO_DB_SHARDING="single"                       # => OneShard database
export ARANGO_REPLICATION_FACTOR="${ARANGO_REPLICATION_FACTOR:-1}"  # match FinReflectKG baseline
export ARANGO_GRAPH="${ARANGO_GRAPH:-FinReflectKG}"      # graph name inside the new db
export THREADS="${THREADS:-16}"

echo ">>> target db: $ARANGO_DB  (sharding=$ARANGO_DB_SHARDING, rf=$ARANGO_REPLICATION_FACTOR)"

stage() { echo; echo "=== $* ==="; }

stage "1/5 provision OneShard database + collections"
"$PY" scripts/setup_db.py

stage "2/5 bulk import (Node, chunks, relations) from data/staging/full"
env THREADS="$THREADS" ./scripts/import_full.sh

stage "3/5 indexes (VCIs + lookups)"
"$PY" scripts/create_indexes.py

stage "4/5 named graph"
"$PY" scripts/create_graph.py

stage "5/5 validate counts + VCI usage"
"$PY" scripts/validate.py

stage "OneShard placement check"
"$PY" scripts/check_sharding.py

echo
echo "=== FinReflectKgOneShard build complete ==="

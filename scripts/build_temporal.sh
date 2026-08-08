#!/usr/bin/env bash
# Build FinReflectKgTemporal — a OneShard time-travel build (G9/M8, docs/PRD.md §4.8).
#
# Same Node/relations as the baseline, PLUS numeric valid-time fields
# (validFrom/validTo, YYYYMM ints) on every relations edge and an MDI temporal
# index — enabling as-of / current / diff queries. OneShard co-locates the
# non-index-accelerated temporal traversals on one DBServer (P0 spike: the MDI
# engages on direct-edge as-of but not in p.edges[*] traversals).
#
# `chunks` are skipped by default (time-travel needs no source text); set
# IMPORT_CHUNKS=1 to include them for GraphRAG-over-time. Reuses the local
# `data/staging/full` artifacts; idempotent (deterministic keys + on-duplicate
# ignore), so it is safe to re-run.
#
# Usage:
#   ./scripts/build_temporal.sh
#   IMPORT_CHUNKS=1 THREADS=8 ./scripts/build_temporal.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PY="${PY:-.venv/bin/python}"; [[ -x "$PY" ]] || PY="python3"

# --- per-build configuration (overrides .env via arango.py env-overlay) -------
export ARANGO_DB="${ARANGO_DB:-FinReflectKgTemporal}"
export ARANGO_DB_SHARDING="single"                                 # => OneShard database
export ARANGO_REPLICATION_FACTOR="${ARANGO_REPLICATION_FACTOR:-1}"
export ARANGO_GRAPH="${ARANGO_GRAPH:-FinReflectKgTemporal}"
export ARANGO_TEMPORAL=1                                           # build the MDI + composite VCIs
export THREADS="${THREADS:-16}"
export BATCH="${BATCH:-16777216}"                                 # 16 MB
IMPORT_CHUNKS="${IMPORT_CHUNKS:-0}"

echo ">>> target db: $ARANGO_DB  (OneShard, rf=$ARANGO_REPLICATION_FACTOR, graph=$ARANGO_GRAPH, chunks=$IMPORT_CHUNKS)"
stage() { echo; echo "=== $* ==="; }

imp() {  # collection  relative-file-under-data/staging
  echo ">>> import $1 <- $2"
  ARANGO_DB="$ARANGO_DB" scripts/import.sh "$1" "$2" --threads "$THREADS" --batch-size "$BATCH" 2>&1 \
    | grep -E '^(created|warnings|updated|ignored|cannot|error)' || true
}

stage "0/5 augment relations with validFrom/validTo (YYYYMM)"
"$PY" scripts/augment_temporal.py

stage "1/5 provision OneShard database + collections"
"$PY" scripts/setup_db.py

stage "2/5 import Node + relations(temporal) (chunks=$IMPORT_CHUNKS)"
imp Node full/nodes.jsonl
if [[ "$IMPORT_CHUNKS" == "1" ]]; then imp chunks full/chunks.jsonl; fi
for f in data/staging/temporal/relations/*.json; do
  imp relations "temporal/relations/$(basename "$f")"
done

stage "3/5 indexes (base VCIs + MDI temporal + composite validFrom VCIs)"
"$PY" scripts/create_indexes.py

stage "4/5 named graph"
"$PY" scripts/create_graph.py

stage "5/5 validate (counts + temporal coverage + MDI usage + as-of spot check)"
"$PY" scripts/validate_temporal.py

echo; echo "=== FinReflectKgTemporal build complete ==="

#!/usr/bin/env bash
# Build the FinReflectKgSmart database — a Disjoint SmartGraph (smart attribute
# `ticker`) of the same FinReflectKG data, so each company's nodes, edges, and
# source-text chunks co-locate on one shard (Design 2; see
# docs/smartgraph-build-brief.md and docs/multi-distribution-plan.md §5).
#
# Reuses the parameterized pipeline. Idempotent + resumable: every stage tolerates
# re-running (deterministic keys, --on-duplicate ignore, exists-checks). Requires
# ArangoDB Enterprise (SmartGraph) and all 103 parquet shards present locally.
#
# Does NOT touch FinReflectKG / FinReflectKgOneShard or any aga_*/benchmark_*
# collections — everything goes in the FinReflectKgSmart database.
#
# Usage:
#   ./scripts/build_smart.sh                  # full build
#   THREADS=8 ./scripts/build_smart.sh        # tune import parallelism
#   SKIP_PREPROCESS=1 ./scripts/build_smart.sh  # reuse data/staging/smart
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PY:-.venv/bin/python}"
[[ -x "$PY" ]] || PY="python3"

# --- per-build configuration (overrides .env via arango.py env-overlay) -------
export ARANGO_DB="${ARANGO_DB:-FinReflectKgSmart}"
export ARANGO_GRAPH="${ARANGO_GRAPH:-FinReflectKgSmart}"
export ARANGO_SMART=1                                     # db-only setup; graph makes smart colls
export ARANGO_SMART_ATTRIBUTE="${ARANGO_SMART_ATTRIBUTE:-ticker}"
export ARANGO_NUM_SHARDS="${ARANGO_NUM_SHARDS:-9}"
export ARANGO_REPLICATION_FACTOR="${ARANGO_REPLICATION_FACTOR:-2}"
export THREADS="${THREADS:-16}"

# smart staging layout for import_full.sh
export STAGING="smart"
export NODES_FILE="nodes_smart.jsonl"
export CHUNKS_FILE="chunks_smart.jsonl"
export REL_DIR="relations_smart"

SMART_STAGE="data/staging/smart"
SKIP_PREPROCESS="${SKIP_PREPROCESS:-0}"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "error: $ROOT/.env not found — needed for ArangoDB connection details." >&2
  exit 1
fi

echo ">>> target db: $ARANGO_DB  (Disjoint SmartGraph, smart=$ARANGO_SMART_ATTRIBUTE, "
echo "    shards=$ARANGO_NUM_SHARDS, rf=$ARANGO_REPLICATION_FACTOR)"

stage() { echo; echo "=== $* ==="; }

stage "1/7 preprocess parquet -> smart JSONL"
if [[ "$SKIP_PREPROCESS" == "1" || -f "$SMART_STAGE/nodes_smart.jsonl" ]]; then
  echo "    reusing existing $SMART_STAGE (SKIP_PREPROCESS=$SKIP_PREPROCESS)"
else
  "$PY" scripts/preprocess_smart.py \
    --input "data/raw/data/train-*.parquet" \
    --out "$SMART_STAGE" --split-bytes 512MB
fi

stage "2/7 provision database (ARANGO_SMART=1: database only)"
"$PY" scripts/setup_db.py

stage "3/7 create Disjoint SmartGraph + smart collections"
"$PY" scripts/create_smart_graph.py

stage "4/7 bulk import (Node, chunks, relations) from $SMART_STAGE"
env THREADS="$THREADS" STAGING="$STAGING" NODES_FILE="$NODES_FILE" \
    CHUNKS_FILE="$CHUNKS_FILE" REL_DIR="$REL_DIR" ./scripts/import_full.sh

stage "5/7 indexes (VCIs + lookups)"
"$PY" scripts/create_indexes.py

stage "6/7 validate (counts + smart attrs + shard locality)"
"$PY" scripts/validate_smart.py

stage "7/7 placement / sharding check"
"$PY" scripts/check_sharding.py

echo
echo "=== FinReflectKgSmart build complete ==="

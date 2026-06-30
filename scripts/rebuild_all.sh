#!/usr/bin/env bash
# Rebuild the entire FinReflectKG ArangoDB database from scratch, end to end.
#
# Runs every pipeline stage in order against the connection in .env, so the
# database can be recreated anywhere with a single command. Every stage is
# idempotent (deterministic keys, --on-duplicate ignore, exists-checks), so a
# partial/interrupted run is safe to re-run.
#
#   1. download      fetch the 103 parquet shards from HuggingFace
#   2. preprocess    parquet -> JSONL (Node / chunks / relations splits)
#   3. setup_db      create database + collections
#   4. import_full   bulk arangoimport of all collections
#   5. create_indexes  build VCIs + lookup indexes
#   6. validate      reconcile counts + VCI sanity checks
#   7. create_graph  named graph FinReflectKG (collection manifest)
#   8. install_visualizer  Graph Visualizer theme + saved queries + canvas actions
#
# Usage:
#   ./scripts/rebuild_all.sh                 # full rebuild
#   THREADS=8 ./scripts/rebuild_all.sh       # tune import parallelism
#   SKIP_DOWNLOAD=1 ./scripts/rebuild_all.sh # reuse already-downloaded parquet
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PY:-.venv/bin/python}"
THREADS="${THREADS:-16}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-0}"

if [[ ! -x "$PY" ]]; then
  echo "error: python interpreter '$PY' not found or not executable." >&2
  echo "       create the venv first, or set PY=/path/to/python." >&2
  exit 1
fi
if [[ ! -f "$ROOT/.env" ]]; then
  echo "error: $ROOT/.env not found — needed for ArangoDB connection details." >&2
  exit 1
fi

stage() {  # number  description  -- command...
  local num="$1" desc="$2"; shift 2
  [[ "$1" == "--" ]] && shift
  local start=$SECONDS
  echo
  echo "==================================================================="
  echo ">>> stage $num: $desc"
  echo "==================================================================="
  "$@"
  echo "    (stage $num done in $((SECONDS - start))s)"
}

OVERALL_START=$SECONDS

if [[ "$SKIP_DOWNLOAD" == "1" ]]; then
  echo ">>> stage 1: download — SKIPPED (SKIP_DOWNLOAD=1)"
else
  stage 1 "download parquet shards" -- "$PY" scripts/download.py
fi

stage 2 "preprocess parquet -> JSONL" -- \
  "$PY" scripts/preprocess.py \
    --input "data/raw/data/train-*.parquet" \
    --out data/staging/full --split-bytes 512MB

stage 3 "provision database + collections" -- "$PY" scripts/setup_db.py

stage 4 "bulk import" -- env THREADS="$THREADS" ./scripts/import_full.sh

stage 5 "create indexes" -- "$PY" scripts/create_indexes.py

stage 6 "validate (reconcile + VCI check)" -- "$PY" scripts/validate.py

stage 7 "create named graph FinReflectKG" -- "$PY" scripts/create_graph.py

stage 8 "install Graph Visualizer theme + queries + actions" -- "$PY" scripts/install_visualizer.py

echo
echo "=== rebuild complete in $((SECONDS - OVERALL_START))s ==="

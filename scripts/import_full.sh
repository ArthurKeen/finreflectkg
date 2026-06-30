#!/usr/bin/env bash
# Full import: Node, then chunks, then every relations split file.
# Idempotent (--on-duplicate ignore + deterministic keys). Logs throughput.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

THREADS="${THREADS:-16}"
BATCH="${BATCH:-16777216}"   # 16 MB

# Staging layout — defaults match the baseline/OneShard build; override for the
# SmartGraph build, e.g.:
#   STAGING=smart NODES_FILE=nodes_smart.jsonl CHUNKS_FILE=chunks_smart.jsonl \
#   REL_DIR=relations_smart ./scripts/import_full.sh
STAGING="${STAGING:-full}"
NODES_FILE="${NODES_FILE:-nodes.jsonl}"
CHUNKS_FILE="${CHUNKS_FILE:-chunks.jsonl}"
REL_DIR="${REL_DIR:-relations}"

run() {  # collection  relative-file
  local start=$SECONDS
  echo ">>> importing $1 <- $2"
  scripts/import.sh "$1" "$2" --threads "$THREADS" --batch-size "$BATCH" 2>&1 \
    | grep -E '^(created|warnings|updated|ignored|cannot|error)' || true
  echo "    ($((SECONDS - start))s)"
}

run Node   "$STAGING/$NODES_FILE"
run chunks "$STAGING/$CHUNKS_FILE"
for f in "data/staging/$STAGING/$REL_DIR"/*.json; do
  run relations "$STAGING/$REL_DIR/$(basename "$f")"
done
echo "=== full import complete ==="

#!/usr/bin/env bash
# arangoimport one JSONL file (or glob) into a collection via the arangodb Docker image.
# Reads connection details from .env. Usage:
#   scripts/import.sh <collection> <relative-path-under-data/staging> [extra arangoimport args...]
# Example:
#   scripts/import.sh Node pilot/nodes.jsonl
#   scripts/import.sh relations 'full/relations/*.json' --threads 8
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Preserve any pre-set ARANGO_DB so a build can retarget the DB without editing
# .env, e.g. `ARANGO_DB=FinReflectKgOneShard ./scripts/import.sh ...`.
PRESET_DB="${ARANGO_DB:-}"
set -a; source "$ROOT/.env"; set +a
ARANGO_DB="${PRESET_DB:-$ARANGO_DB}"

COLLECTION="$1"; FILE="$2"; shift 2 || true

# Strip scheme from endpoint and map to ssl:// (https) for arangoimport.
HOST="${ARANGO_ENDPOINT#https://}"; HOST="${HOST#http://}"
case "$ARANGO_ENDPOINT" in
  https://*) EP="ssl://${HOST}:443" ;;
  http://*)  EP="tcp://${HOST}:8529" ;;
esac

IMAGE="${ARANGO_IMAGE:-arangodb:3.12}"

docker run --rm \
  -e ARANGO_PASSWORD="$ARANGO_PASSWORD" \
  -v "$ROOT/data/staging:/data:ro" \
  "$IMAGE" \
  arangoimport \
    --server.endpoint "$EP" \
    --server.database "$ARANGO_DB" \
    --server.username "$ARANGO_USER" \
    --server.password "$ARANGO_PASSWORD" \
    --collection "$COLLECTION" \
    --file "/data/$FILE" \
    --type jsonl \
    --progress true \
    --on-duplicate ignore \
    "$@"

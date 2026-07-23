#!/usr/bin/env bash
# Launch the arango-cypher-py Workbench UI + service against FinReflectKG for a demo.
#
#   ./scripts/demo_workbench.sh
#
# Starts:
#   - backend  (FastAPI service)  on http://localhost:8001  (the Vite proxy target)
#   - frontend (React/Vite UI)    on http://localhost:5173  <- open this in a browser
#
# Connection + LLM come from FinReflectKG/.env (ARANGO_ENDPOINT/USER/PASSWORD + a key).
# Requires the sibling arango-cypher-py checkout with its .venv311 + ui/node_modules.
# Ctrl-C stops both.
set -euo pipefail

FRKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACP="${ARANGO_CYPHER_DIR:-/Users/arthurkeen/code/arango-cypher-py}"
VENV="${ACP}/.venv311"                      # falls back to FinReflectKG/.venv311 if absent
[ -x "${VENV}/bin/python" ] || VENV="${FRKG}/.venv311"

[ -f "${FRKG}/.env" ]            || { echo "missing ${FRKG}/.env"; exit 1; }
[ -f "${ACP}/main.py" ]          || { echo "missing ${ACP}/main.py (set ARANGO_CYPHER_DIR)"; exit 1; }
[ -d "${ACP}/ui/node_modules" ]  || { echo "run 'npm install' in ${ACP}/ui first"; exit 1; }

# Load FinReflectKG connection + LLM keys, map to the service's env var names.
set -a; . "${FRKG}/.env"; set +a
export ARANGO_URL="${ARANGO_ENDPOINT}" \
       ARANGO_USER="${ARANGO_USER:-root}" \
       ARANGO_PASSWORD="${ARANGO_PASSWORD}" \
       ARANGO_DB="${ARANGO_DB:-FinReflectKG}" \
       ARANGO_CYPHER_WORKBENCH=1 \
       LLM_PROVIDER="${LLM_PROVIDER:-openai}" \
       HOST=127.0.0.1 PORT=8001

echo ">>> backend  -> http://localhost:8001  (db=${ARANGO_DB}, llm=${LLM_PROVIDER})"
( cd "${ACP}" && exec "${VENV}/bin/python" main.py ) &
BACK=$!

echo ">>> frontend -> http://localhost:5173  (open this)"
( cd "${ACP}/ui" && exec npm run dev ) &
FRONT=$!

trap 'echo; echo "stopping..."; kill "${BACK}" "${FRONT}" 2>/dev/null || true' INT TERM
echo ">>> Ctrl-C to stop both."
wait

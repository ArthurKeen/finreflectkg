#!/usr/bin/env bash
# Assemble a ServiceMaker-compatible .tar.gz for Container Manager → Packages.
#
# The package must be self-contained and this repo is not: demo/api.py resolves
# scripts/ as a SIBLING (ROOT = parent.parent, then sys.path.insert(ROOT/"scripts")).
# So the tree is reassembled preserving that relationship rather than flattened —
# flattening builds fine and fails at import time inside the platform.
#
#   ./deploy/package.sh                    -> target/finreflectkg-timetravel-1.0.0.tar.gz
#   ./deploy/package.sh 1.2.0              -> stamps that version
#   ./deploy/package.sh 1.2.0 --with-env   -> bakes .env in (needed to deploy)
#
# CREDENTIALS. The platform does not inject them — a deployed service uses whatever
# it was packaged with. --with-env includes .env, and THE ARCHIVE IS THEN A SECRET:
# a .tar.gz is one command from plaintext. *.tar.gz is gitignored for exactly this
# reason; do not attach one to a ticket or paste it into chat either.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="finreflectkg-timetravel"
VERSION="${1:-1.0.0}"
WITH_ENV=0; [ "${2:-}" = "--with-env" ] && WITH_ENV=1
OUT="$REPO/target"
STAGE="$(mktemp -d)/$NAME"
trap 'rm -rf "$(dirname "$STAGE")"' EXIT

mkdir -p "$STAGE/demo" "$STAGE/scripts" "$OUT"
cp -R "$REPO/demo/." "$STAGE/demo/"
cp "$REPO/scripts/arango.py" "$STAGE/scripts/arango.py"
cp "$REPO/deploy/service_main.py" "$STAGE/main.py"
sed "s/^version = .*/version = \"$VERSION\"/" "$REPO/deploy/pyproject.toml" > "$STAGE/pyproject.toml"

# Things that would only bloat or leak: the local run helper, caches, and any env
# file that rode in with the copy. Stripped BEFORE --with-env re-adds one
# deliberately — the other order would delete the file the flag exists to include.
rm -f "$STAGE/demo/screenshot.sh" "$STAGE/demo/requirements.txt"
find "$STAGE" \( -name '__pycache__' -o -name '*.pyc' -o -name '.env' -o -name '*.env' \) \
     -exec rm -rf {} + 2>/dev/null || true
if [ "$WITH_ENV" = "1" ]; then
  [ -f "$REPO/.env" ] || { echo "--with-env but no .env at repo root" >&2; exit 1; }
  cp "$REPO/.env" "$STAGE/.env"
  echo "⚠  baking .env into the package — the archive is now a secret"
fi

tar -czf "$OUT/$NAME-$VERSION.tar.gz" -C "$(dirname "$STAGE")" "$NAME"
echo "✓ $OUT/$NAME-$VERSION.tar.gz  ($(du -h "$OUT/$NAME-$VERSION.tar.gz" | cut -f1))"
echo
echo "  Container Manager → Packages. Metadata to supply:"
echo "     file name          $NAME"
echo "     version            $VERSION"
echo "     service URL path   finreflectkg"
echo "     base image         arangodb/py13base:latest"
echo
tar -tzf "$OUT/$NAME-$VERSION.tar.gz" | head -8 | sed 's/^/     /'

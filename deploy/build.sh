#!/usr/bin/env bash
# Build (and optionally push) the BYOC image for the time-travel demo.
#
#   ./deploy/build.sh                          # build locally
#   ./deploy/build.sh --with-env               # bake .env in (needed to deploy)
#   ./deploy/build.sh --push ghcr.io/you/img   # build and push
#
# --platform linux/amd64 is not optional. This repo is developed on arm64 and the
# BYOC docs name the arch mismatch as a known deployment failure: an arm64 image
# pushes without complaint and then will not start.
#
# CREDENTIALS. The platform does not inject them — a deployed service uses whatever
# the image was built with. --with-env copies .env into the image, which means THE
# IMAGE IS THEN A SECRET: layers are trivially extractable, so treat it exactly like
# the .env file inside it. Pushing one is gated behind an explicit acknowledgement
# rather than left to memory at the wrong moment.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${TAG:-finreflectkg-timetravel:latest}"
WITH_ENV=0; PUSH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --with-env) WITH_ENV=1; shift ;;
    --push)     PUSH=1; TAG="${2:?usage: --push <registry/image:tag>}"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# The Dockerfile always COPYs deploy/.env-or-empty/ so the layer graph is identical
# either way; the directory is populated only when asked.
STAGE="$REPO/deploy/.env-or-empty"
rm -rf "$STAGE"; mkdir -p "$STAGE"
if [ "$WITH_ENV" = "1" ]; then
  [ -f "$REPO/.env" ] || { echo "--with-env but no .env at repo root" >&2; exit 1; }
  cp "$REPO/.env" "$STAGE/.env"
  echo "⚠  baking .env into the image — the image is now a secret"
fi
trap 'rm -rf "$STAGE"' EXIT

docker build --platform linux/amd64 \
  --label "finreflectkg.contains-credentials=$WITH_ENV" \
  -f "$REPO/deploy/Dockerfile" -t "$TAG" "$REPO"
echo "✓ built $TAG (linux/amd64)"
docker image inspect "$TAG" --format "  arch: {{.Architecture}}/{{.Os}}  credentials: {{index .Config.Labels \"finreflectkg.contains-credentials\"}}"

if [ -n "$PUSH" ]; then
  if [ "$WITH_ENV" = "1" ] && [ "${I_KNOW_THIS_IMAGE_HAS_SECRETS:-}" != "yes" ]; then
    echo >&2
    echo "REFUSING to push: this image contains .env." >&2
    echo "  Anyone who can pull it can read the database password." >&2
    echo "  If the registry is private and that is intended:" >&2
    echo "     I_KNOW_THIS_IMAGE_HAS_SECRETS=yes ./deploy/build.sh --with-env --push $TAG" >&2
    exit 1
  fi
  docker push "$TAG"
  echo "✓ pushed $TAG — paste this URL into Container Manager → Containers"
fi

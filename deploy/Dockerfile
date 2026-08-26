# BYOC image for the FinReflectKG time-travel demo.
#
# Platform contract: HTTP server on port 8000, must answer "/". Container Manager
# handles routing, auth and network isolation.
#
# Built on the platform's own hardened base rather than a stock python image: it is
# pre-scanned and matches what ServiceMaker produces. py13base, not py12base —
# Python 3.13 is the documented standard runtime and py13base IS on Docker Hub even
# though the public servicemaker repo's imagelist still names only the 3.12 images.
# py12base also ships no uv at all.
#
# ARCHITECTURE. Build with --platform linux/amd64. An arm64 image pushes without
# complaint and then does not start, which is the documented BYOC failure on
# M-series Macs. deploy/build.sh always passes the flag; do not omit it by hand.
FROM arangodb/py13base:latest

WORKDIR /service
USER user

# py13base ships uv on PATH and has no pip in the venv. Install against
# /home/user/constraints.txt so nothing we add floats a version away from what the
# pre-scanned base pins — the same thing ServiceMaker's prepareproject.sh does.
# This is the same pyproject.toml deploy/package.sh ships in the .tar.gz, so both
# deployment paths install an identical dependency set and cannot drift.
COPY --chown=user:user deploy/pyproject.toml /service/pyproject.toml
# `. /home/user/.local/bin/env` first: uv lives in ~/.local/bin, which a non-login
# RUN shell does not have on PATH. Without it this fails as a bare exit 127.
RUN . /home/user/.local/bin/env \
 && . /home/user/the_venv/bin/activate \
 && UV_HTTP_TIMEOUT=3600 uv pip install \
      -c /home/user/constraints.txt \
      -r /service/pyproject.toml

# demo/api.py resolves scripts/ as a sibling (ROOT = parent.parent, then
# sys.path.insert(ROOT/"scripts")), so the layout must be preserved. Only the one
# helper the service actually imports is copied — not the whole ETL toolchain.
COPY --chown=user:user demo/              /service/demo/
COPY --chown=user:user scripts/arango.py  /service/scripts/arango.py

# Credentials. The platform does NOT inject them (confirmed with Emmet Allen,
# 2026-08-26): a deployed service reads whatever the image was built with. So
# `deploy/build.sh --with-env` copies .env in, and without that flag no secret is
# present.
#
# THE IMAGE IS THEN THE SECRET. Layers are trivially extractable — `docker save`
# plus untar — so a credential-bearing image must be treated exactly like the .env
# file it contains: never pushed to a public registry, never shared, and the
# database password rotated if it escapes. build.sh refuses to push one without an
# explicit acknowledgement.
ARG WITH_ENV=0
COPY --chown=user:user deploy/.env-or-empty/ /service/

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000

# /api/years returns module constants and touches no database. That is deliberate
# and differs from the gdelt service, which health-checks a DB-backed endpoint: this
# demo runs against a REMOTE cluster where a single query has ranged 203 ms to 20 s,
# so a DB-touching probe on a 4 s timeout would flap and mark a healthy service dead.
# The trade-off is that this cannot detect a bad baked credential — verify that once
# at build time by curling /api/tickers (see deploy/README.md), not on every probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/years',timeout=4)" || exit 1

CMD ["/bin/bash", "-lc", ". /home/user/the_venv/bin/activate && exec python -m uvicorn demo.api:app --host 0.0.0.0 --port 8000 --log-level warning"]

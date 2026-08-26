# BYOC deployment — FinReflectKG Time-Travel demo

Packages the demo UI (`demo/api.py` + `demo/static/`) as an ArangoDB **BYOC** service so
it runs on the platform instead of a presenter's laptop. Two artifact shapes are
supported; both are verified working.

Live (deployed by Emmet Allen, 2026-08-26):
<https://20hin6od.rnd.pilot.arango.ai/_service/uds/_global/finreflect/>

---

## The two shapes

| | Command | Artifact | Use when |
|---|---|---|---|
| **Container image** | `./deploy/build.sh` | `finreflectkg-timetravel:latest` | You control a registry; you want the exact runtime pinned |
| **Code package** | `./deploy/package.sh` | `target/finreflectkg-timetravel-1.0.0.tar.gz` (~138 KB) | Container Manager → Packages builds it for you |

Both produce a service listening on **port 8000** at the **root path**.

## Runtime contract

Four constraints the platform imposes, and how this service meets them:

1. **Port 8000, root path.** `deploy/service_main.py` runs uvicorn on `0.0.0.0:8000`.
   Not configurable at deploy time — the platform assumes it.
2. **Base image `arangodb/py13base:latest`** (Python 3.13.13, ships `uv`).
   `py12base` does **not** ship `uv`; do not substitute it.
3. **Constraints file.** `uv pip install -c /home/user/constraints.txt` — the platform
   pins its own transitive versions and an unconstrained install can drift off them.
4. **Path-prefix stripping.** The service is published under
   `/_service/uds/_global/<app>/` (or `/_service/uds/_db/<db>/<app>/`) and envoy strips
   that prefix before the request arrives. The **server** therefore sees clean paths —
   but the **browser** does not. Every browser-facing URL must be relative.

### Why the URLs are relative (the one non-obvious part)

`demo/static/app.js` derives a `serviceBase` from `location.pathname` and prefixes every
API call with it. It deliberately does *not* use `document.baseURI`: baseURI drops the
last path segment, so a service reached **without** its trailing slash
(`…/finreflect`, no `/`) would resolve one directory too high and 404. The `.`-in-leaf
test distinguishes a file leaf (`index.html`) from a directory leaf served bare.

The static asset refs in `index.html` (`style.css`, `app.js`, `vendor/…`) are plain
relative and *do* still assume the trailing slash — Container Manager serves it that way.

`amd64` is forced (`--platform linux/amd64`) in both scripts: the platform runs x86 and
an arm64 image built on an Apple-silicon laptop fails to start there.

## Credentials — read this before deploying

**The platform does not inject database credentials.** A service authenticates with
whatever it was built with. Confirmed with Emmet; the JWT-forwarding path exists but is a
service-design choice, not something the platform does for you.

So there are two options, and the tradeoff is real:

```bash
./deploy/build.sh              # credential-free (default)
./deploy/build.sh --with-env   # bakes .env INTO THE IMAGE
```

- **Credential-free** is the default. The image boots and serves the static UI and
  `/api/years`; any endpoint that touches the database returns **503** naming the
  variables that are missing. Supply `ARANGO_ENDPOINT` / `ARANGO_USER` /
  `ARANGO_PASSWORD` at run time.
- **`--with-env`** bakes `.env` in, so the service works with **no environment
  variables passed at all** — which is the actual deployment condition. The cost:
  **the image artifact is now a secret.** Anyone who can pull it has the cluster
  password. `push` refuses unless `I_KNOW_THIS_IMAGE_HAS_SECRETS=yes` is set.

`package.sh` never includes `.env` — the code package is always credential-free, because
a `.tar.gz` is one command from plaintext.

## Verified paths

All five confirmed on 2026-08-26:

| Path | Result |
|---|---|
| Credential-free image, no env | Boots; static + `/api/years` 200; DB → 503 with the reason |
| Credential-free image + env vars | Full DB access |
| `--with-env` image, **no env passed** | Full DB access — the deployment condition |
| Code tarball extracted into a bare `py13base` | Full DB access |
| Live platform deployment | Serving, authenticated, real data through the prefix |

## Local iteration

```bash
.venv/bin/python -m uvicorn demo.api:app --port 8000   # no container
docker run -d -p 8000:8000 finreflectkg-timetravel:latest
```

## A defect this work surfaced

`scripts/arango.py:load_env()` read `.env` **unconditionally at import**, so the
credential-free image exited 1 before serving anything — including endpoints that touch
no database. `.env` is now optional and an unset endpoint raises `NotConfigured` at
*call* time (→ 503) rather than killing the process at import. This was a latent bug well
beyond BYOC: the app could never run from environment variables alone.

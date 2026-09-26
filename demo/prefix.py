"""Strip the platform mount prefix before routing.

On the Arango platform a BYOC service is mounted at
``/_service/uds/_db/<db>/<instance>/`` and the ingress forwards requests with the
prefix intact, while the FastAPI routes stay at ``/``, ``/api`` and ``/static``.

This removes the prefix *the Starlette way*: ``scope["path"]`` keeps the full URL
path and the prefix is appended to ``scope["root_path"]``. Starlette's router then
routes on ``path`` minus ``root_path``, and ``Mount``/``StaticFiles`` extend
``root_path`` as they descend. Shortening ``path`` directly — the older ASGI idiom
— breaks ``StaticFiles`` on Starlette >= 0.33.

With no prefix configured it is a no-op, so running locally is unchanged.

Pattern adapted from project-sentinel, arango-ontoextract and gdelt-market-impact,
which solved this first; the comment above is the part worth carrying, not the code.

NOTE for this repo: the August BYOC notes (PRD §4.9) claimed envoy STRIPS the prefix
before the service sees it. That is wrong for a `_db`-mounted UDS service — the prefix
arrives intact and the app must strip it, which is what this middleware does. The
client-side relative-URL work in demo/static/app.js is still required and independent:
it fixes what the BROWSER resolves, this fixes what the SERVER routes.
"""
from __future__ import annotations

import os

from starlette.types import ASGIApp, Receive, Scope, Send

PREFIX_ENV = "SERVICE_URL_PATH_PREFIX"


def normalize_prefix(raw: str | None) -> str:
    """``" /a/b/ "`` -> ``"/a/b"``; empty or None -> ``""`` (no prefix)."""
    value = (raw or "").strip()
    if not value:
        return ""
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/")


def configured_prefix() -> str:
    return normalize_prefix(os.environ.get(PREFIX_ENV))


class StripServicePrefixMiddleware:
    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = normalize_prefix(prefix)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self.prefix:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == self.prefix or path.startswith(self.prefix + "/"):
            scope = dict(scope)
            scope["root_path"] = scope.get("root_path", "") + self.prefix
        await self.app(scope, receive, send)


def with_prefix(app: ASGIApp, prefix: str | None = None) -> ASGIApp:
    """`app` wrapped for a mount prefix; unchanged when none is configured."""
    resolved = configured_prefix() if prefix is None else normalize_prefix(prefix)
    return StripServicePrefixMiddleware(app, resolved) if resolved else app

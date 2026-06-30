"""Shared ArangoDB HTTP helpers driven by .env. No external deps beyond stdlib."""

import json
import os
import pathlib
import ssl
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        env[key.strip()] = val
    # Real environment overrides .env file values, so a single .env can be
    # retargeted per build, e.g. `ARANGO_DB=FinReflectKgOneShard python ...`.
    for key, val in os.environ.items():
        if key.startswith("ARANGO_") or key == "HUGGINGFACE_DATASET":
            env[key] = val
    return env


ENV = load_env()
ENDPOINT = ENV["ARANGO_ENDPOINT"].rstrip("/")
USER = ENV.get("ARANGO_USER", "root")
PASSWORD = ENV.get("ARANGO_PASSWORD", "")
VERIFY_SSL = ENV.get("ARANGO_VERIFY_SSL", "true").lower() == "true"


def _ctx():
    if VERIFY_SSL:
        return None
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def req(method, path, body=None, db=None, timeout=120):
    """Call the ArangoDB REST API. `path` starts with /_api/...; `db` scopes it."""
    base = f"{ENDPOINT}/_db/{db}" if db else ENDPOINT
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    import base64

    tok = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    r.add_header("Authorization", f"Basic {tok}")
    try:
        with urllib.request.urlopen(r, context=_ctx(), timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

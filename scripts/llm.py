"""Pluggable LLM helper for the NL->AQL and GraphRAG evaluators (M5).

Provider + credentials come from the environment (real env overrides .env file):
  LLM_PROVIDER      anthropic | openai   (default: auto-detect from whichever key is set)
  ANTHROPIC_API_KEY / ANTHROPIC_MODEL    (default model: claude-sonnet-4-5)
  OPENAI_API_KEY    / OPENAI_MODEL       (default model: gpt-4o)

No SDK dependency -- calls the HTTP APIs directly via urllib, mirroring arango.py.
If no key is configured, `available()` is False and callers fall back to a dry-run
(they print the assembled prompt instead of calling a model), so the whole pipeline
is runnable without credentials.
"""

import json
import os
import urllib.request

from arango import ENV  # ENV already merges the .env file


def _get(key, default=None):
    return os.environ.get(key) or ENV.get(key) or default


def provider():
    p = _get("LLM_PROVIDER")
    if p:
        return p.lower()
    if _get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _get("OPENAI_API_KEY"):
        return "openai"
    return None


def available():
    p = provider()
    return bool(p and _get(f"{p.upper()}_API_KEY"))


def model():
    p = provider()
    if p == "anthropic":
        return _get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    if p == "openai":
        return _get("OPENAI_MODEL", "gpt-4o")
    return None


def _post(url, headers, body, timeout):
    data = json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        r.add_header(k, v)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())


def complete(system, user, max_tokens=1500, temperature=0.0, timeout=90):
    """Return the model's text completion, or raise RuntimeError if unavailable."""
    p = provider()
    if not available():
        raise RuntimeError("no LLM configured; set ANTHROPIC_API_KEY or OPENAI_API_KEY")
    if p == "anthropic":
        out = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": _get("ANTHROPIC_API_KEY"),
             "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {"model": model(), "max_tokens": max_tokens, "temperature": temperature,
             "system": system, "messages": [{"role": "user", "content": user}]},
            timeout)
        return "".join(b.get("text", "") for b in out.get("content", [])).strip()
    if p == "openai":
        out = _post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {_get('OPENAI_API_KEY')}",
             "content-type": "application/json"},
            {"model": model(), "max_tokens": max_tokens, "temperature": temperature,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}]},
            timeout)
        return out["choices"][0]["message"]["content"].strip()
    raise RuntimeError(f"unknown LLM provider: {p}")

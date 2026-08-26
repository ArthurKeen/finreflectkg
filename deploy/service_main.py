#!/usr/bin/env python3
"""BYOC entrypoint. ServiceMaker runs `python main.py` from the package root.

The platform contract is an HTTP server on port 8000 answering "/", so host and port
are fixed here rather than read from argv or PORT: demo/README.md documents starting
this app via the uvicorn CLI on 8080, which is neither the contract port nor bound on
an interface the Container Manager can reach.

demo/api.py resolves `scripts/` as a SIBLING (ROOT = parent.parent, then
sys.path.insert(ROOT/"scripts")), so this file must sit at the package root with
demo/ and scripts/ beside it. deploy/package.sh assembles exactly that shape.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402

from demo.api import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

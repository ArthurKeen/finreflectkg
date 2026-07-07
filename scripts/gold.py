"""Parse the NL/Cypher/AQL gold set from docs/cypher-queries.md.

Dependency-free (stdlib only) so it can be imported from both the 3.9 REST-helper
scripts (nl_eval.py) and the 3.11 arango-cypher-py integration (cypher_eval.py)
without dragging in the local `arango.py` module (which shadows python-arango's
`arango` package).
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "cypher-queries.md"


def parse_gold(path=DOC):
    """Extract [{n, title, nl, cypher, aql}] from the queries markdown."""
    lines = path.read_text().splitlines()
    entries, cur = [], None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^##\s+(\d+)\.\s+(.*)$", line)
        if m:
            if cur:
                entries.append(cur)
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(),
                   "nl": "", "cypher": "", "aql": ""}
            i += 1
            continue
        if cur is not None and line.startswith("**NL:**"):
            buf = [line[len("**NL:**"):]]
            while '"*' not in buf[-1] and i + 1 < len(lines):
                i += 1
                buf.append(lines[i])
            text = " ".join(s.strip() for s in buf)
            q = re.search(r'\*"(.*)"\*', text)
            cur["nl"] = (q.group(1) if q else text).strip()
            i += 1
            continue
        if cur is not None and line.strip() in ("```cypher", "```aql"):
            lang = line.strip().strip("`")
            block = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                block.append(lines[i])
                i += 1
            cur[lang] = "\n".join(block).strip()
            i += 1
            continue
        i += 1
    if cur:
        entries.append(cur)
    return entries

"""GraphRAG over FinReflectKG (M5 / G6).

Pipeline (no vector search -- that's a phase-2 non-goal; entity linking uses the
`node_name` index):

  1. entity-link  -- resolve seed entity name(s) to Node ids via the name index
                     (seeds given with --entity, or extracted from the question by
                     the LLM when one is configured)
  2. retrieve     -- gather a typed neighborhood with DIRECT edge queries (the VCI
                     fast path), both directions, around each seed
  3. ground       -- join each edge to its source-text `chunks` record (the reason
                     text was co-located per company in the SmartGraph build)
  4. synthesize   -- an LLM answers the question CITING the grounded facts; without
                     a key, the assembled grounded context is printed (dry-run)

Defaults to `FinReflectKgSmart` (text co-located with each company's subgraph).

Usage:
  .venv/bin/python scripts/graphrag.py -q "Where does Apple operate?" --entity aapl
  .venv/bin/python scripts/graphrag.py -q "What does Apple disclose?" --entity aapl --db FinReflectKG
  .venv/bin/python scripts/graphrag.py -q "..."          # LLM extracts seeds (needs key)
"""

import argparse
import json
import pathlib

import llm
from arango import ENV, req

ROOT = pathlib.Path(__file__).resolve().parent.parent


def resolve(db, name, k=5):
    """Resolve a name to Node candidates, best first.

    On the Disjoint SmartGraph a company appears many times (its own subgraph root
    plus duplicated references inside other companies' subgraphs). The real root has
    a smart `_key` prefixed with its own ticker (`aapl:...`), so rank that first,
    then prefer ORG/COMP types. The prefix test is a harmless no-op on the baseline
    (md5 keys), where the type ranking still applies.
    """
    name = name.strip().lower()
    rank = """
        LET rootMatch = STARTS_WITH(n._key, CONCAT(@name, ':')) ? 0 : 1
        LET typePri = n.type == 'ORG' ? 0 : (n.type == 'COMP' ? 1 : 2)
        SORT rootMatch, typePri"""
    _, r = req("POST", "/_api/cursor", {"query": f"""
        FOR n IN Node FILTER n.name == @name {rank} LIMIT @k
          RETURN {{id: n._id, name: n.name, type: n.type}}""",
        "bindVars": {"name": name, "k": k}}, db=db, timeout=60)
    hits = r.get("result", [])
    if not hits:
        _, r = req("POST", "/_api/cursor", {"query": f"""
            FOR n IN Node FILTER n.name LIKE @pat {rank} LIMIT @k
              RETURN {{id: n._id, name: n.name, type: n.type}}""",
            "bindVars": {"name": name, "pat": f"%{name}%", "k": k}}, db=db, timeout=60)
        hits = r.get("result", [])
    return hits


def neighborhood(db, node_id, name, k=30):
    """Typed 1-hop facts around node_id, each grounded with its source-text chunk."""
    q = """
    LET out = (FOR e IN relations FILTER e._from == @id LIMIT @k
        LET o = DOCUMENT(e._to) LET ch = DOCUMENT('chunks', e.chunkKey)
        RETURN {subject: @name, rel: e.type, object: o.name, objectType: o.type,
                dir: 'out', ticker: e.ticker, year: e.year,
                text: ch.text ? SUBSTRING(ch.text, 0, 260) : null})
    LET inb = (FOR e IN relations FILTER e._to == @id LIMIT @k
        LET s = DOCUMENT(e._from) LET ch = DOCUMENT('chunks', e.chunkKey)
        RETURN {subject: s.name, rel: e.type, object: @name, objectType: s.type,
                dir: 'in', ticker: e.ticker, year: e.year,
                text: ch.text ? SUBSTRING(ch.text, 0, 260) : null})
    RETURN APPEND(out, inb)"""
    _, r = req("POST", "/_api/cursor",
               {"query": q, "bindVars": {"id": node_id, "name": name, "k": k}},
               db=db, timeout=120)
    res = r.get("result", [])
    return res[0] if res else []


def extract_seeds(nl):
    """Ask the LLM for entity names in the question (company names -> tickers)."""
    out = llm.complete(
        "Extract the named entities (companies, regulators, metrics, places) from the "
        "question as a comma-separated list. Map company names to their stock ticker in "
        "lowercase (Apple -> aapl). Output ONLY the list.",
        nl, max_tokens=100)
    return [s.strip().lower() for s in out.replace("\n", ",").split(",") if s.strip()]


def format_context(facts):
    lines = []
    for i, f in enumerate(facts, 1):
        arrow = f"{f['subject']} -[{f['rel']}]-> {f['object']}" if f["dir"] == "out" \
            else f"{f['subject']} -[{f['rel']}]-> {f['object']}"
        when = f" ({f['ticker']} {f['year']})" if f.get("year") else ""
        src = f'\n     source: "{f["text"]}"' if f.get("text") else ""
        lines.append(f"[{i}] {arrow}{when}{src}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--question", required=True)
    ap.add_argument("--entity", nargs="*", help="seed entity name(s); else LLM extracts them")
    ap.add_argument("--db", default="FinReflectKgSmart")
    ap.add_argument("-k", "--fanout", type=int, default=30, help="edges per direction per seed")
    args = ap.parse_args()

    seeds = args.entity
    if not seeds:
        if not llm.available():
            raise SystemExit("no --entity given and no LLM to extract seeds; "
                             "pass --entity <name> or configure a key.")
        seeds = extract_seeds(args.question)
    print(f"db={args.db}  question={args.question!r}\nseeds: {seeds}\n")

    facts, linked = [], []
    for s in seeds:
        hits = resolve(args.db, s)
        if not hits:
            print(f"  [unresolved] {s}")
            continue
        top = hits[0]
        linked.append(top)
        print(f"  linked {s!r} -> {top['id']} ({top['type']}) [{len(hits)} candidate(s)]")
        facts += neighborhood(args.db, top["id"], top["name"], args.fanout)

    facts = [f for f in facts if f.get("object") or f.get("subject")]
    print(f"\nretrieved {len(facts)} grounded facts "
          f"({sum(1 for f in facts if f.get('text'))} with source text)\n")

    context = format_context(facts)
    if not llm.available():
        print("[no LLM configured -- dry-run: assembled GraphRAG context below]\n")
        print(context[:4000])
        out = ROOT / "data" / "graphrag_context.json"
        out.write_text(json.dumps({"db": args.db, "question": args.question,
                                   "linked": linked, "facts": facts}, indent=2))
        print(f"\nwrote {out}")
        return

    system = ("You answer questions about companies using ONLY the provided knowledge-graph "
              "facts, each with a source-text snippet. Cite facts by their [n] index. If the "
              "facts don't answer the question, say so.")
    user = f"Question: {args.question}\n\nKnowledge-graph facts:\n{context}\n\nAnswer (with [n] citations):"
    print(f"[{llm.provider()}:{llm.model()}] synthesizing...\n")
    print("----- answer -----\n" + llm.complete(system, user, max_tokens=800))


if __name__ == "__main__":
    main()

"""GraphRAG answer-synthesis rubric over a handful of questions (M5 / G6).

Closes the "GraphRAG answer synthesis quality (cited answers) — a small rubric over
a handful of questions" item in nl-graphrag.md. Reuses scripts/graphrag.py's
link -> retrieve -> ground -> synthesize pipeline and scores each answer on a
deterministic rubric (no LLM-as-judge — the checks below are mechanical):

  linked            seed entity resolved to a Node
  facts / grounded  # grounded facts retrieved / # carrying co-located source text
  answered          LLM returned a non-empty answer
  cited             answer cites at least one fact by [n]
  citations_valid   every cited [n] index is within 1..#facts (no hallucinated cites)
  abstained         answer states the facts don't cover the question
                    (expected True for the deliberately out-of-scope question)

Runs under the main .venv (REST helper + llm.py), against FinReflectKgSmart where
each company's source text is co-located with its subgraph.

  .venv/bin/python scripts/graphrag_rubric.py
  .venv/bin/python scripts/graphrag_rubric.py --db FinReflectKgSmart -k 30
"""

import argparse
import json
import pathlib
import re

import graphrag
import llm

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (question, [seed tickers], in_scope) — the last one is expected to be out-of-scope
# so a faithful model should abstain rather than fabricate.
QUESTIONS = [
    ("Where does Apple operate?", ["aapl"], True),
    ("What financial metrics does Apple disclose?", ["aapl"], True),
    ("What products or segments does Apple report?", ["aapl"], True),
    ("Who does Cincinnati Financial hold a stake in?", ["cinf"], True),
    ("What is Apple's policy on deep-sea mining rights?", ["aapl"], False),
]

_CITE = re.compile(r"\[(\d+)\]")
_ABSTAIN = re.compile(r"don't|do not|cannot|can't|not (?:answer|address|cover|detailed|"
                      r"provided|contain)|no .*facts|insufficient", re.I)


def score(q, seeds, in_scope, db, k):
    linked = []
    facts = []
    for s in seeds:
        hits = graphrag.resolve(db, s)
        if hits:
            linked.append(hits[0])
            facts += graphrag.neighborhood(db, hits[0]["id"], hits[0]["name"], k)
    facts = [f for f in facts if f.get("object") or f.get("subject")]
    n_facts = len(facts)
    n_grounded = sum(1 for f in facts if f.get("text"))

    answer = ""
    if llm.available() and facts:
        answer = graphrag.synthesize(q, graphrag.format_context(facts))
    cited = _CITE.findall(answer)
    cited_idx = [int(c) for c in cited]
    citations_valid = all(1 <= c <= n_facts for c in cited_idx) if cited_idx else None
    abstained = bool(_ABSTAIN.search(answer)) if answer else None

    return {
        "question": q, "seeds": seeds, "in_scope": in_scope,
        "linked": bool(linked), "linked_to": [x["id"] for x in linked],
        "facts": n_facts, "grounded": n_grounded,
        "answered": bool(answer), "cited": bool(cited_idx),
        "n_citations": len(cited_idx), "citations_valid": citations_valid,
        "abstained": abstained, "answer": answer,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="FinReflectKgSmart")
    ap.add_argument("-k", "--fanout", type=int, default=30)
    args = ap.parse_args()

    if not llm.available():
        print("WARNING: no LLM configured — answers will be empty; run with a key for the "
              "full rubric.\n")
    else:
        print(f"llm={llm.provider()}:{llm.model()}  db={args.db}  fanout={args.fanout}\n")

    rows = [score(q, seeds, in_scope, args.db, args.fanout) for q, seeds, in_scope in QUESTIONS]

    print(f"{'#':>2}  {'lnk':>3} {'facts':>5} {'grnd':>4} {'ans':>3} {'cite':>4} "
          f"{'valid':>5} {'abst':>4}  question")
    for i, r in enumerate(rows, 1):
        def mark(v):
            return "-" if v is None else ("Y" if v else "n")
        print(f"{i:>2}  {mark(r['linked']):>3} {r['facts']:>5} {r['grounded']:>4} "
              f"{mark(r['answered']):>3} {mark(r['cited']):>4} {mark(r['citations_valid']):>5} "
              f"{mark(r['abstained']):>4}  {r['question'][:46]}")

    # Rubric pass criteria: in-scope answers must link, ground, answer, cite validly;
    # the out-of-scope question must abstain rather than fabricate.
    def passed(r):
        if r["in_scope"]:
            return (r["linked"] and r["grounded"] > 0 and r["answered"]
                    and r["cited"] and r["citations_valid"] is not False)
        return r["answered"] and r["abstained"]

    n_pass = sum(1 for r in rows if passed(r))
    print(f"\nrubric: {n_pass}/{len(rows)} pass")

    out = ROOT / "data" / "graphrag_rubric.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"db": args.db, "fanout": args.fanout,
         "llm": llm.provider(), "llm_model": llm.model(),
         "passed": n_pass, "total": len(rows),
         "criteria": "in-scope: linked+grounded+answered+cited+citations_valid; "
                     "out-of-scope: answered+abstained",
         "results": rows}, indent=2))
    print(f"wrote {out}")

    # Print full answers for manual review (faithfulness is a human call).
    print("\n===== answers (for manual faithfulness review) =====")
    for i, r in enumerate(rows, 1):
        print(f"\n[{i}] {r['question']}  (in_scope={r['in_scope']}, "
              f"facts={r['facts']}, grounded={r['grounded']})")
        print(r["answer"] or "(no answer)")


if __name__ == "__main__":
    main()

# Prior GraphRAG rubric record (superseded 2026-08-13)

The `data/graphrag_rubric.json` that backed the PRD's "answer synthesis **5/5**" claim
(§4.6 / G6 / M5) was produced under a provider that is no longer usable. Its summary
metadata, recovered before the file was regenerated:

| field | value |
|---|---|
| `db` | `FinReflectKgSmart` |
| `fanout` | 30 |
| `llm` | `anthropic` |
| `llm_model` | `claude-sonnet-4-5` |
| `passed` / `total` | **5 / 5** |
| `criteria` | in-scope: linked+grounded+answered+cited+citations_valid; out-of-scope: answered+abstained |

The per-question `results` array was not preserved — `scripts/graphrag_rubric.py` writes
the JSON in place, and the re-run overwrote it before a copy was taken.

## Why it was re-run

`ANTHROPIC_API_KEY` was revoked (401 `authentication_error` on every model), so the 5/5
figure is not reproducible on the current configuration. `.env` now pins
`LLM_PROVIDER=openai`; the re-run under `openai` / `gpt-4o` scores **4/5**.

## What changed in the score

The regression is a **false abstention**, not a retrieval failure:

> Q4 "Who does Cincinnati Financial hold a stake in?" — 60 facts retrieved, all 60
> grounded, citations valid — but the model answered *"the provided facts do not specify
> any companies or entities in which Cincinnati Financial holds a stake."*

The facts were present and grounded; the model declined to use them. The same CINF
relationship returns **219 rows** through the NL→Cypher path, so this is a synthesis
behaviour difference between providers, not missing data.

**Demo implication:** use the Apple questions for the GraphRAG half of beat 8 (all pass);
do not use the CINF stake question there. CINF remains the right entity for the
NL→Cypher half.

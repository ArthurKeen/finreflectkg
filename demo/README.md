# FinReflectKG — Time-Travel demo visualizer

A lightweight, **local, live** demo of the FinReflectKG time-travel layer (G9/§4.8), served
against the `FinReflectKgTemporal` database. Fresh build (FastAPI + Cytoscape.js), no framework
build step.

## What it shows (v1.3)
- **DVR time-slider** — scrub 2014→2024 and the company's subgraph **crossfades** between years,
  DVR-style. The whole decade arrives in one `/api/timeline` payload; the union of all years is laid
  out **once** with stable positions, so scrubbing is pure client-side (no fetch, no relayout). The
  company node is **pinned at the centre**; facts fade in / out as they appear / disappear.
- **Depth** control (1 = direct-facts star / 2–3 = connected context). The view is always a
  *connected* neighbourhood of the company — no free-floating concept↔concept islands.
- **Valid / Reported time toggle** — *valid* = what **held** at mid-year (`validFrom`/`validTo`);
  *reported* = what the filing **asserted** that year (`year`, transaction time). The bitemporal
  (P3) axis, made interactive.
- **Legend = type filters** — click a legend swatch to show / hide that entity type.
- **Top-N PageRank filter** (Influence panel) — restrict the graph to the most globally-influential
  entities at the current anchor year.
- **Influence over time** — top entities by GAE PageRank at the anchor year nearest the slider
  (`gae_pr_2014/2019/2020/2024`).
- **Company explorer + diffs** — year-over-year *appeared / disappeared* facts (vs 2014) and
  **backward-looking disclosures** (facts a filing asserts about periods ≥3 years earlier).

## Run
```bash
# from the repo root (connection comes from .env; DB = FinReflectKgTemporal)
.venv/bin/python -m uvicorn demo.api:app --port 8080
# then open http://localhost:8080  (try tickers: aapl, msft, amzn, … any of the 743)
```

## Endpoints (backend)
`GET /api/years` · `GET /api/tickers` · `GET /api/timeline?ticker=&depth=&clean=&axis=` (all years, one payload) ·
`GET /api/asof?ticker=&year=&limit=&depth=&clean=` · `GET /api/influence?year=&top=` ·
`GET /api/prranks?year=&top=` · `GET /api/diff?ticker=&from=&to=` · `GET /api/backward?ticker=&lag=`

## Notes
- Read-only; uses the stdlib REST helper (`scripts/arango.py`) driven by `.env`.
- Cytoscape.js is **vendored** at `demo/static/vendor/cytoscape.min.js` — fully offline, no CDN.
- The as-of canvas shows a connected neighbourhood of the company (depth 1 = a clean star), capped
  at ~140 facts for readability and always island-free (the header shows *shown / total · depth*).
- **Cleaned/Raw toggle** (header): Cleaned drops junk placeholders + skolemizes generic hubs to
  per-company bnodes (dashed green); Raw shows the graph as extracted (shared hubs + junk diamonds).

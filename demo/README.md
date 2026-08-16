# FinReflectKG — Time-Travel demo visualizer

A lightweight, **local, live** demo of the FinReflectKG time-travel layer (G9/§4.8), served
against the `FinReflectKgTemporal` database. Fresh build (FastAPI + Cytoscape.js), no framework
build step.

## What it shows (v1)
- **Time-slider as-of view** — scrub 2014→2024; a company's subgraph re-renders at that instant
  (valid-time `validFrom`/`validTo`). The company node is **pinned at the centre** and the change
  between years **animates** (survivors glide, facts fade in / out). A **Depth** control (1 = direct
  facts / 2–3 = connected context) trades readability for reach; the view is always a *connected*
  neighbourhood of the company, so there are no free-floating concept↔concept islands.
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
`GET /api/years` · `GET /api/tickers` · `GET /api/asof?ticker=&year=&limit=&depth=&clean=` ·
`GET /api/influence?year=&top=` · `GET /api/diff?ticker=&from=&to=` · `GET /api/backward?ticker=&lag=`

## Notes
- Read-only; uses the stdlib REST helper (`scripts/arango.py`) driven by `.env`.
- Cytoscape.js is **vendored** at `demo/static/vendor/cytoscape.min.js` — fully offline, no CDN.
- The as-of canvas shows a connected neighbourhood of the company (depth 1 = a clean star), capped
  at ~140 facts for readability and always island-free (the header shows *shown / total · depth*).
- **Cleaned/Raw toggle** (header): Cleaned drops junk placeholders + skolemizes generic hubs to
  per-company bnodes (dashed green); Raw shows the graph as extracted (shared hubs + junk diamonds).

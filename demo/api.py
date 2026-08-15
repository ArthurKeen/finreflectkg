"""FinReflectKG Time-Travel demo — FastAPI backend (live against FinReflectKgTemporal).

Serves the custom demo visualizer (G9/§4.8): time-slider as-of subgraphs, influence-over-time
(GAE PageRank per anchor year), and a company explorer (year-over-year diff + backward-looking
disclosures). Generic-mention junk placeholders are excluded so the graph reflects the cleaned
topology. Read-only; uses the stdlib REST helper (scripts/arango.py) — no extra DB deps.

Run:  .venv/bin/uvicorn demo.api:app --reload --port 8080   (then open http://localhost:8080)
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from arango import req  # scripts/arango.py (stdlib-only REST helper driven by .env)

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

DB = "FinReflectKgTemporal"
ANCHORS = [2014, 2019, 2020, 2024]   # years with a materialized GAE PageRank (gae_pr_<year>)
YEAR_MIN, YEAR_MAX = 2014, 2024

app = FastAPI(title="FinReflectKG Time-Travel Demo")


def aql(query, bind=None, timeout=60):
    st, b = req("POST", "/_api/cursor", {"query": query, "bindVars": bind or {}}, db=DB, timeout=timeout)
    if st not in (200, 201):
        raise HTTPException(status_code=502, detail=f"AQL {st}: {b.get('errorMessage')}")
    return b.get("result", [])


_flagged_ids = None


def flagged_ids():
    """Cached set of flagged node _ids (generic-mention + junk placeholder), so the as-of
    sample can surface flagged-touching edges first without per-edge DOCUMENT lookups."""
    global _flagged_ids
    if _flagged_ids is None:
        _flagged_ids = aql("FOR n IN Node FILTER n.isGenericMention == true OR n.isJunkPlaceholder == true RETURN n._id")
    return _flagged_ids


@app.get("/api/years")
def years():
    return {"min": YEAR_MIN, "max": YEAR_MAX, "anchors": ANCHORS}


@app.get("/api/tickers")
def tickers():
    """All companies, most-connected first (for the picker)."""
    return aql("FOR e IN relations COLLECT tk = e.ticker WITH COUNT INTO c SORT c DESC RETURN tk")


@app.get("/api/asof")
def asof(ticker: str, year: int, limit: int = 150, clean: bool = True):
    """A company's subgraph valid as-of mid-<year>.

    clean=True (default): drop junk-placeholder edges and skolemize generic-mention hubs into
    per-company blank nodes (bnodes/bn_<ticker>_<role>). clean=False: the RAW graph as extracted
    (shared generic hubs + junk placeholders shown) — the 'before' of the cleaning story.
    """
    t = year * 100 + 6
    rows = aql("""
        LET flagged = @flagged
        FOR e IN relations
          FILTER e.ticker == @tk AND e.validFrom <= @t AND e.validTo > @t
          SORT (e._to IN flagged OR e._from IN flagged) ? 0 : 1   /* surface flagged-touching edges first */
          LIMIT @lim
          LET df = DOCUMENT(e._from)  LET dt = DOCUMENT(e._to)
          RETURN {f: e._from, fn: df.name, ft: df.type, fj: df.isJunkPlaceholder, fg: df.isGenericMention, fr: df.roleLemma,
                  t: e._to, tn: dt.name, tt: dt.type, tj: dt.isJunkPlaceholder, tg: dt.isGenericMention, tr: dt.roleLemma,
                  rel: e.type}""",
        {"tk": ticker, "t": t, "lim": limit, "flagged": flagged_ids()})
    total = aql("RETURN LENGTH(FOR e IN relations FILTER e.ticker==@tk AND e.validFrom<=@t AND e.validTo>@t RETURN 1)",
                {"tk": ticker, "t": t})[0]

    def endpoint(idv, name, typ, junk, gen, role):  # -> (id, label, type, is_bnode, is_junk)
        if clean and gen and role:
            return f"bnodes/bn_{ticker}_{role}", role, role.upper(), True, False
        return idv, name, typ, False, bool(junk)

    nodes, edges = {}, []
    for r in rows:
        fid, fn, ft, fb, fj = endpoint(r["f"], r["fn"], r["ft"], r.get("fj"), r.get("fg"), r.get("fr"))
        tid, tn, tt, tb, tj = endpoint(r["t"], r["tn"], r["tt"], r.get("tj"), r.get("tg"), r.get("tr"))
        if clean and (fj or tj):
            continue  # drop junk-placeholder edges
        nodes.setdefault(fid, {"id": fid, "label": fn, "type": ft, "bnode": fb, "junk": fj})
        nodes.setdefault(tid, {"id": tid, "label": tn, "type": tt, "bnode": tb, "junk": tj})
        edges.append({"source": fid, "target": tid, "label": r["rel"]})
    return {"ticker": ticker, "year": year, "clean": clean, "nodes": list(nodes.values()),
            "edges": edges, "shown": len(edges), "total": total}


@app.get("/api/influence")
def influence(year: int, top: int = 15):
    """Top entities by GAE PageRank at the anchor year nearest <year>."""
    anchor = min(ANCHORS, key=lambda a: abs(a - year))
    rows = aql(f"""FOR r IN gae_pr_{anchor} SORT r.rank DESC LIMIT @top
          LET n = DOCUMENT(CONTAINS(r.id, '/') ? r.id : CONCAT('Node/', r.id))
          RETURN {{name: n.name, type: n.type, rank: r.rank}}""", {"top": top})
    return {"anchor": anchor, "rows": rows}


@app.get("/api/diff")
def diff(ticker: str, frm: int = Query(..., alias="from"), to: int = 2024, limit: int = 40):
    """Facts that appeared / disappeared for a company between two years (by fact identity)."""
    ta, tb = frm * 100 + 6, to * 100 + 6

    def side(anchor_t, other_t):
        return aql("""
            LET other = (FOR e IN relations FILTER e.ticker==@tk AND e.validFrom<=@ot AND e.validTo>@ot
                          RETURN CONCAT(e._from,'|',e.type,'|',e._to))
            FOR e IN relations FILTER e.ticker==@tk AND e.validFrom<=@at AND e.validTo>@at
              AND CONCAT(e._from,'|',e.type,'|',e._to) NOT IN other
              LET df=DOCUMENT(e._from) LET dt=DOCUMENT(e._to)
              FILTER df.isJunkPlaceholder!=true AND dt.isJunkPlaceholder!=true
              LIMIT @lim RETURN {from: df.name, rel: e.type, to: dt.name}""",
            {"tk": ticker, "at": anchor_t, "ot": other_t, "lim": limit})

    return {"ticker": ticker, "from": frm, "to": to,
            "appeared": side(tb, ta), "disappeared": side(ta, tb)}


@app.get("/api/backward")
def backward(ticker: str, lag: int = 3, limit: int = 25):
    """Backward-looking disclosures: facts a filing asserts about periods >= lag years earlier."""
    return aql("""
        FOR e IN relations
          FILTER e.ticker==@tk AND e.startDate!=null
            AND (e.year - TO_NUMBER(SUBSTRING(e.startDate,0,4))) >= @lag
          SORT (e.year - TO_NUMBER(SUBSTRING(e.startDate,0,4))) DESC
          LIMIT @lim
          LET df=DOCUMENT(e._from) LET dt=DOCUMENT(e._to)
          RETURN {filed: e.year, period: e.startDate, from: df.name, rel: e.type, to: dt.name}""",
        {"tk": ticker, "lag": lag, "lim": limit})


app.mount("/", StaticFiles(directory=str(pathlib.Path(__file__).resolve().parent / "static"), html=True))

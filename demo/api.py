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
def asof(ticker: str, year: int, limit: int = 140, clean: bool = True, depth: int = 1):
    """A company's subgraph valid as-of mid-<year>, as a depth-bounded neighborhood of the
    company node — so the view is always connected (no free-floating concept<->concept islands).

    depth=1 (default): the company's direct facts (a clean star). depth>=2: also facts among
    those neighbors, still reachable from the company. clean=True: drop junk placeholders and
    skolemize generic-mention hubs into per-company bnodes; clean=False: the RAW extraction.
    """
    t = year * 100 + 6
    flagged = flagged_ids()

    if depth <= 1:
        # one round-trip for total + focal (the company = highest-degree endpoint), one for the star
        meta = aql("""LET es = (FOR e IN relations FILTER e.ticker==@tk AND e.validFrom<=@t AND e.validTo>@t
                                   RETURN [e._from, e._to])
                      RETURN {total: LENGTH(es),
                              focal: FIRST(FOR p IN es FOR s IN p COLLECT id = s WITH COUNT INTO c
                                             SORT c DESC LIMIT 1 RETURN id)}""",
                   {"tk": ticker, "t": t})[0]
        total, focal = meta["total"], meta["focal"]
        if not focal:
            return {"ticker": ticker, "year": year, "clean": clean, "depth": depth,
                    "focal": None, "nodes": [], "edges": [], "shown": 0, "total": total}
        rows = aql("""
            LET flagged = @flagged
            FOR e IN relations
              FILTER e.ticker == @tk AND e.validFrom <= @t AND e.validTo > @t
                 AND (e._from == @focal OR e._to == @focal)   /* incident to the company -> pure star */
              SORT (e._to IN flagged OR e._from IN flagged) ? 0 : 1
              LIMIT @lim
              LET df = DOCUMENT(e._from) LET dt = DOCUMENT(e._to)
              RETURN {f:e._from, fn:df.name, ft:df.type, fj:df.isJunkPlaceholder, fg:df.isGenericMention, fr:df.roleLemma,
                      t:e._to, tn:dt.name, tt:dt.type, tj:dt.isJunkPlaceholder, tg:dt.isGenericMention, tr:dt.roleLemma,
                      rel:e.type}""",
            {"tk": ticker, "t": t, "lim": limit, "flagged": flagged, "focal": focal})
    else:
        # depth>=2: pull the ticker's as-of edges once; derive total + focal + adjacency in Python,
        # then reveal more of the neighborhood reachable from the company. Keep edges with BOTH
        # endpoints within <depth> hops, take the flagged-first top (a bigger budget the deeper you
        # go), then hard-filter to the focal's connected component so truncation can't strand an
        # island. Done in Python because an `e._from IN keep` AQL filter would use the edge index to
        # fetch those nodes' edges GLOBALLY, and neighbors include supernodes (net income ~60k) ->
        # a full-graph blowup + timeout.
        flagged_set = set(flagged)
        triples = aql("""FOR e IN relations FILTER e.ticker==@tk AND e.validFrom<=@t AND e.validTo>@t
                           RETURN {f:e._from, t:e._to, rel:e.type}""", {"tk": ticker, "t": t})
        total = len(triples)
        if not triples:
            return {"ticker": ticker, "year": year, "clean": clean, "depth": depth,
                    "focal": None, "nodes": [], "edges": [], "shown": 0, "total": 0}
        deg, adj = {}, {}
        for e in triples:
            deg[e["f"]] = deg.get(e["f"], 0) + 1
            deg[e["t"]] = deg.get(e["t"], 0) + 1
            adj.setdefault(e["f"], set()).add(e["t"])
            adj.setdefault(e["t"], set()).add(e["f"])
        focal = max(deg, key=deg.get)
        keep, frontier = {focal}, {focal}
        for _ in range(depth):
            nxt = set()
            for n in frontier:
                nxt |= adj.get(n, set())
            nxt -= keep
            keep |= nxt
            frontier = nxt
            if len(keep) > 800:
                break
        fk = lambda e: 0 if (e["f"] in flagged_set or e["t"] in flagged_set) else 1
        cand = sorted((e for e in triples if e["f"] in keep and e["t"] in keep), key=fk)
        cand = cand[: limit + (depth - 1) * 60]           # deeper reveals more (the density knob)
        # keep only what's reachable from the company over the chosen edges -> no truncation islands
        nadj = {}
        for e in cand:
            nadj.setdefault(e["f"], set()).add(e["t"])
            nadj.setdefault(e["t"], set()).add(e["f"])
        reach, frontier = {focal}, [focal]
        while frontier:
            n = frontier.pop()
            for m in nadj.get(n, ()):
                if m not in reach:
                    reach.add(m); frontier.append(m)
        sel = [e for e in cand if e["f"] in reach and e["t"] in reach]
        ids = list({e["f"] for e in sel} | {e["t"] for e in sel})
        docs = {}
        if ids:
            for row in aql("""FOR id IN @ids LET n = DOCUMENT(id)
                                RETURN {id: id, name:n.name, type:n.type, junk:n.isJunkPlaceholder,
                                        gen:n.isGenericMention, role:n.roleLemma}""", {"ids": ids}):
                docs[row["id"]] = row
        rows = [{"f":e["f"], "fn":docs.get(e["f"],{}).get("name"), "ft":docs.get(e["f"],{}).get("type"),
                 "fj":docs.get(e["f"],{}).get("junk"), "fg":docs.get(e["f"],{}).get("gen"), "fr":docs.get(e["f"],{}).get("role"),
                 "t":e["t"], "tn":docs.get(e["t"],{}).get("name"), "tt":docs.get(e["t"],{}).get("type"),
                 "tj":docs.get(e["t"],{}).get("junk"), "tg":docs.get(e["t"],{}).get("gen"), "tr":docs.get(e["t"],{}).get("role"),
                 "rel":e["rel"]} for e in sel]

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
    return {"ticker": ticker, "year": year, "clean": clean, "depth": depth, "focal": focal,
            "nodes": list(nodes.values()), "edges": edges, "shown": len(edges), "total": total}


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

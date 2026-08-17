// FinReflectKG Time-Travel demo — frontend (DVR timeline). Talks to the FastAPI backend (demo/api.py).
// The whole decade for a company comes down in ONE /api/timeline payload; the union of all years is
// laid out once with stable positions, so scrubbing the slider is a pure crossfade (no fetch, no
// relayout) — DVR-smooth. Legend clicks, the valid/reported axis, and the Top-N PageRank slider are
// all visibility filters on top of that.
const TYPE_COLORS = {
  FIN_METRIC: '#5b8def', FIN_INST: '#7c6cf0', ORG: '#e0a34a', COMP: '#c9902f',
  GPE: '#4ec98a', PRODUCT: '#e46a6a', RISK_FACTOR: '#d9534f', SEGMENT: '#4bb7c9',
  PERSON: '#c86fd0', FIN_MARKET: '#3fa7ff', SUPPLIER: '#b9772e', CUSTOMER: '#a76fd0',
  EVENT: '#e8b04b', SECTOR: '#38b2ac', MACRO_CONDITION: '#8a97ad', ORG_REG: '#d94fb0',
  LOGISTICS: '#6fa8dc', ECON_IND: '#66c2a5', LITIGATION: '#e07a5f',
};
const LEGEND_TYPES = ['FIN_METRIC', 'FIN_INST', 'ORG', 'GPE', 'PRODUCT', 'RISK_FACTOR', 'SEGMENT', 'PERSON', 'FIN_MARKET'];
const colorFor = (t) => TYPE_COLORS[t] || '#8a97ad';
const $ = (s) => document.querySelector(s);
const j = (u) => fetch(u).then((r) => r.json());
const edgeKey = (e) => `${e.source}~${e.label}~${e.target}`;

let cy, ticker = 'aapl', year = 2018, clean = true, depth = 1, axis = 'valid';
let timeline = null;                 // { focal, years: { Y: {nodeIds:Set, edgeIds:Set, total} } }
let focalId = null;
let hidden = new Set();              // node types switched off via the legend
let prTopN = 0;                      // 0 = off; otherwise show only the top-N PageRank entities
let prSet = null;                    // Set of node ids allowed by the PR filter (or null = off)
let prOrder = {};                    // anchor year -> [node ids ranked by PageRank]
let anchors = [2014, 2019, 2020, 2024];
const infCache = {}, diffCache = {};

function initCy() {
  cy = cytoscape({
    container: $('#cy'), wheelSensitivity: 0.3,
    style: [
      { selector: 'node', style: {
        'background-color': 'data(color)', 'label': 'data(label)', 'color': '#cfd8e6',
        'font-size': '9px', 'text-wrap': 'wrap', 'text-max-width': '84px',
        'width': 'mapData(deg,1,25,14,46)', 'height': 'mapData(deg,1,25,14,46)',
        'text-valign': 'bottom', 'text-margin-y': '2px', 'border-width': 0, 'min-zoomed-font-size': 6,
        'transition-property': 'opacity, background-color, width, height', 'transition-duration': '260ms' } },
      { selector: 'node.company', style: {
        'background-color': '#ffffff', 'border-color': '#5b8def', 'border-width': 4,
        'font-size': '15px', 'color': '#ffffff', 'font-weight': 'bold',
        'width': 56, 'height': 56, 'z-index': 30, 'min-zoomed-font-size': 0 } },
      { selector: 'node.bnode', style: {
        'border-color': '#4ec98a', 'border-width': 2, 'border-style': 'dashed', 'shape': 'round-rectangle' } },
      { selector: 'node.junk', style: {
        'background-color': '#e46a6a', 'border-color': '#e46a6a', 'shape': 'diamond', 'opacity': 0.9 } },
      { selector: '.off', style: { 'opacity': 0, 'events': 'no', 'text-opacity': 0 } },
      { selector: 'edge', style: {
        'width': 1, 'line-color': '#31405c', 'target-arrow-color': '#31405c',
        'target-arrow-shape': 'triangle', 'arrow-scale': 0.7, 'curve-style': 'bezier',
        'label': 'data(label)', 'font-size': '7px', 'color': '#576a82',
        'text-rotation': 'autorotate', 'opacity': 0.8, 'min-zoomed-font-size': 7,
        'transition-property': 'opacity, line-color', 'transition-duration': '260ms' } },
    ],
  });
}

const nearestAnchor = (y) => anchors.reduce((a, b) => (Math.abs(b - y) < Math.abs(a - y) ? b : a), anchors[0]);

async function rebuild() {
  $('#meta').textContent = 'building timeline…';
  const d = await j(`/api/timeline?ticker=${ticker}&depth=${depth}&clean=${clean}&axis=${axis}&limit=140`);
  focalId = d.focal;
  const unionN = new Map(), unionE = new Map(), years = {};
  for (const [Y, yd] of Object.entries(d.years)) {
    const nset = new Set(), eset = new Set();
    yd.nodes.forEach((n) => { unionN.set(n.id, n); nset.add(n.id); });
    yd.edges.forEach((e) => { const k = edgeKey(e); unionE.set(k, e); eset.add(k); });
    years[Y] = { nodeIds: nset, edgeIds: eset, total: yd.total };
  }
  timeline = { focal: d.focal, years };
  if (!focalId || unionN.size === 0) { cy.elements().remove(); $('#meta').textContent = `no facts for ${ticker}`; return; }

  const deg = {};
  unionE.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });

  cy.elements().remove();
  const els = [];
  unionN.forEach((n) => {
    const cls = ['off'];   // born hidden; renderYear reveals the current year
    if (n.id === focalId && !n.bnode) cls.push('company');
    if (n.bnode) cls.push('bnode');
    if (n.junk) cls.push('junk');
    els.push({ group: 'nodes', data: { id: n.id, label: n.label, type: n.type, color: colorFor(n.type), deg: deg[n.id] || 1 }, classes: cls.join(' ') });
  });
  unionE.forEach((e) => els.push({ group: 'edges', data: { id: edgeKey(e), source: e.source, target: e.target, label: e.label }, classes: 'off' }));
  cy.add(els);

  const focal = cy.getElementById(focalId);
  if (focal.nonempty()) focal.unlock();
  const N = cy.nodes().length;
  cy.layout({
    name: 'cose', animate: true, animationDuration: 600, randomize: true, fit: false,
    nodeRepulsion: 20000, idealEdgeLength: 95, edgeElasticity: 120, gravity: 0.35,
    numIter: N > 450 ? 700 : 1200, nodeOverlap: 26, componentSpacing: 140, coolingFactor: 0.96, padding: 40,
  }).one('layoutstop', () => {
    if (focal.nonempty()) focal.lock();
    updatePrSet();
    renderYear();
    cy.fit(cy.nodes().not('.off'), 55);
    if (focal.nonempty()) cy.center(focal);
  }).run();
}

function updatePrSet() {
  if (!prTopN) { prSet = null; return; }
  const order = prOrder[nearestAnchor(year)] || [];
  prSet = new Set(order.slice(0, prTopN));
  if (focalId) prSet.add(focalId);       // the company itself always stays
}

// Pure client-side crossfade to the given year — no network, no relayout.
function renderYear() {
  if (!timeline) return;
  const ys = timeline.years[String(year)];
  if (!ys) return;
  cy.batch(() => {
    cy.nodes().forEach((n) => {
      const id = n.id();
      const on = ys.nodeIds.has(id) && !hidden.has(n.data('type')) && (!prSet || prSet.has(id));
      n.toggleClass('off', !on);
    });
    cy.edges().forEach((e) => {
      const on = ys.edgeIds.has(e.id()) && !e.source().hasClass('off') && !e.target().hasClass('off');
      e.toggleClass('off', !on);
    });
  });
  const shown = cy.edges().not('.off').length;
  const axisLbl = axis === 'valid' ? 'as of' : 'as reported';
  $('#meta').textContent = `${shown} of ${ys.total.toLocaleString()} facts · depth ${depth} · ${axisLbl} ${year}` + (clean ? '' : ' · RAW');
  window.__frkg = { focal: focalId, year, axis, depth, visNodes: cy.nodes().not('.off').length, visEdges: shown, prTopN };
}

async function loadInfluence() {
  const anchor = nearestAnchor(year);
  $('#infhdr').textContent = `PageRank · ${anchor}`;
  if (!infCache[anchor]) infCache[anchor] = await j(`/api/influence?year=${anchor}&top=15`);
  $('#influence').innerHTML = infCache[anchor].rows
    .map((r) => `<li>${r.name} <span class="t">${r.type}</span></li>`).join('');
}

async function loadDiff() {
  const base = 2014;
  $('#diffhdr').textContent = `${year} vs ${base}`;
  if (year === base) { $('#appeared').innerHTML = '<li class="empty">pick another year</li>'; $('#disappeared').innerHTML = ''; return; }
  const key = `${ticker}|${year}`;
  if (!diffCache[key]) diffCache[key] = await j(`/api/diff?ticker=${ticker}&from=${base}&to=${year}&limit=25`);
  const d = diffCache[key];
  const fmt = (xs) => xs.length
    ? xs.map((x) => `<li title="${x.from} —${x.rel}→ ${x.to}">${x.to}</li>`).join('')
    : '<li class="empty">none</li>';
  $('#appeared').innerHTML = fmt(d.appeared);
  $('#disappeared').innerHTML = fmt(d.disappeared);
}

async function loadBackward() {
  const d = await j(`/api/backward?ticker=${ticker}&lag=3&limit=20`);
  $('#backward').innerHTML = d.length
    ? d.map((x) => `<li><span class="yr">filed ${x.filed} → ${x.period}</span> <b>${x.to}</b> <span class="t">(${x.rel})</span></li>`).join('')
    : '<li class="empty">none</li>';
}

async function ensurePrOrder() {   // prefetch PageRank rankings for each anchor (for the Top-N filter)
  await Promise.all(anchors.map(async (a) => {
    if (!prOrder[a]) prOrder[a] = (await j(`/api/prranks?year=${a}&top=300`)).ids;
  }));
}

// ---- side panels (debounced so slider scrubbing stays smooth) ----
let sideT;
function scheduleSide() { clearTimeout(sideT); sideT = setTimeout(() => { loadInfluence(); loadDiff(); }, 140); }
let rafPending = false;
function scheduleRender() { if (rafPending) return; rafPending = true; requestAnimationFrame(() => { rafPending = false; updatePrSet(); renderYear(); }); }

function onSlider(v) { year = +v; $('#yearlbl').textContent = year; scheduleRender(); scheduleSide(); }

async function refreshTicker() { infCacheClear(); await rebuild(); loadInfluence(); loadDiff(); loadBackward(); }
function infCacheClear() { for (const k in diffCache) delete diffCache[k]; }

(async function () {
  initCy();
  const yrs = await j('/api/years');
  anchors = yrs.anchors || anchors;
  const yr = $('#year'); yr.min = yrs.min; yr.max = yrs.max;
  const tks = await j('/api/tickers');
  $('#tickers').innerHTML = tks.map((t) => `<option value="${t}">`).join('');
  $('#legend').innerHTML = '<span class="lbl">filter:</span>' + LEGEND_TYPES
    .map((t) => `<span data-type="${t}" title="click to show / hide ${t}"><i style="background:${colorFor(t)}"></i>${t}</span>`).join('');
  $('#legend').querySelectorAll('span[data-type]').forEach((el) => {
    el.addEventListener('click', () => {
      const t = el.dataset.type;
      if (hidden.has(t)) { hidden.delete(t); el.classList.remove('legoff'); }
      else { hidden.add(t); el.classList.add('legoff'); }
      renderYear();
    });
  });
  $('#ticker').value = ticker;

  yr.addEventListener('input', (e) => onSlider(e.target.value));
  $('#ticker').addEventListener('change', (e) => { const v = e.target.value.trim().toLowerCase(); if (v) { ticker = v; refreshTicker(); } });
  $('#depth').addEventListener('change', (e) => { depth = +e.target.value; rebuild(); });
  $('#axis').addEventListener('change', (e) => { axis = e.target.value; rebuild(); });
  $('#clean').addEventListener('change', (e) => { clean = e.target.checked; rebuild(); });
  $('#pr').addEventListener('input', (e) => {
    prTopN = +e.target.value;
    $('#prlbl').textContent = prTopN ? prTopN : 'all';
    scheduleRender();
  });

  await rebuild();
  loadInfluence(); loadDiff(); loadBackward();
  ensurePrOrder();   // background: warm the PageRank rankings so the Top-N slider is instant
})();

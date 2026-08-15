// FinReflectKG Time-Travel demo — frontend. Talks to the FastAPI backend (demo/api.py).
const TYPE_COLORS = {
  FIN_METRIC: '#5b8def', FIN_INST: '#7c6cf0', ORG: '#e0a34a', COMP: '#c9902f',
  GPE: '#4ec98a', PRODUCT: '#e46a6a', RISK_FACTOR: '#d9534f', SEGMENT: '#4bb7c9',
  PERSON: '#c86fd0', FIN_MARKET: '#3fa7ff', SUPPLIER: '#b9772e', CUSTOMER: '#a76fd0',
  EVENT: '#e8b04b', SECTOR: '#38b2ac', MACRO_CONDITION: '#8a97ad', ORG_REG: '#d94fb0',
  LOGISTICS: '#6fa8dc', ECON_IND: '#66c2a5', LITIGATION: '#e07a5f',
};
const colorFor = (t) => TYPE_COLORS[t] || '#8a97ad';
const $ = (s) => document.querySelector(s);
const j = (u) => fetch(u).then((r) => r.json());

let cy, ticker = 'aapl', year = 2018, clean = true;

function initCy() {
  cy = cytoscape({
    container: $('#cy'), wheelSensitivity: 0.3,
    style: [
      { selector: 'node', style: {
        'background-color': 'data(color)', 'label': 'data(label)', 'color': '#cfd8e6',
        'font-size': '9px', 'text-wrap': 'wrap', 'text-max-width': '78px',
        'width': 'mapData(deg,1,25,13,44)', 'height': 'mapData(deg,1,25,13,44)',
        'text-valign': 'bottom', 'text-margin-y': '2px', 'border-width': 0 } },
      { selector: 'node.company', style: {
        'background-color': '#ffffff', 'border-color': '#5b8def', 'border-width': 4,
        'font-size': '14px', 'color': '#ffffff', 'font-weight': 'bold',
        'width': 54, 'height': 54, 'z-index': 20 } },
      { selector: 'node.bnode', style: {
        'border-color': '#4ec98a', 'border-width': 2, 'border-style': 'dashed', 'shape': 'round-rectangle' } },
      { selector: 'node.junk', style: {
        'background-color': '#e46a6a', 'border-color': '#e46a6a', 'shape': 'diamond', 'opacity': 0.9 } },
      { selector: 'edge', style: {
        'width': 1, 'line-color': '#31405c', 'target-arrow-color': '#31405c',
        'target-arrow-shape': 'triangle', 'arrow-scale': 0.7, 'curve-style': 'bezier',
        'label': 'data(label)', 'font-size': '7px', 'color': '#576a82',
        'text-rotation': 'autorotate', 'opacity': 0.85 } },
    ],
  });
}

async function loadGraph() {
  const d = await j(`/api/asof?ticker=${ticker}&year=${year}&limit=150&clean=${clean}`);
  const deg = {};
  d.edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
  const els = [];
  d.nodes.forEach((n) => {
    const cls = [];
    if (n.label === ticker && !n.bnode) cls.push('company');
    if (n.bnode) cls.push('bnode');
    if (n.junk) cls.push('junk');
    els.push({ data: { id: n.id, label: n.label, type: n.type, color: colorFor(n.type), deg: deg[n.id] || 1 }, classes: cls.join(' ') });
  });
  d.edges.forEach((e, i) => els.push({ data: { id: 'e' + i, source: e.source, target: e.target, label: e.label } }));
  cy.elements().remove();
  cy.add(els);
  cy.layout({ name: 'cose', animate: false, nodeRepulsion: 9000, idealEdgeLength: 72, padding: 34 }).run();
  $('#meta').textContent = `${d.shown} of ${d.total.toLocaleString()} facts · as of mid-${year}` + (clean ? '' : ' · RAW (uncleaned)');
}

async function loadInfluence() {
  const d = await j(`/api/influence?year=${year}&top=15`);
  $('#infhdr').textContent = `PageRank · ${d.anchor}`;
  $('#influence').innerHTML = d.rows
    .map((r) => `<li>${r.name} <span class="t">${r.type}</span></li>`).join('');
}

async function loadDiff() {
  const base = 2014;
  $('#diffhdr').textContent = `${year} vs ${base}`;
  if (year === base) { $('#appeared').innerHTML = '<li class="empty">pick another year</li>'; $('#disappeared').innerHTML = ''; return; }
  const d = await j(`/api/diff?ticker=${ticker}&from=${base}&to=${year}&limit=25`);
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

const refreshAll = () => { loadGraph(); loadInfluence(); loadDiff(); loadBackward(); };
const refreshYear = () => { loadGraph(); loadInfluence(); loadDiff(); };

let debounce;
function onSlider(v) { year = +v; $('#yearlbl').textContent = year; clearTimeout(debounce); debounce = setTimeout(refreshYear, 180); }

(async function () {
  initCy();
  const yrs = await j('/api/years');
  const yr = $('#year'); yr.min = yrs.min; yr.max = yrs.max;
  const tks = await j('/api/tickers');
  $('#tickers').innerHTML = tks.map((t) => `<option value="${t}">`).join('');
  $('#legend').innerHTML = ['FIN_METRIC', 'FIN_INST', 'ORG', 'GPE', 'PRODUCT', 'RISK_FACTOR', 'SEGMENT', 'PERSON', 'FIN_MARKET']
    .map((t) => `<span><i style="background:${colorFor(t)}"></i>${t}</span>`).join('');
  $('#ticker').value = ticker;
  yr.addEventListener('input', (e) => onSlider(e.target.value));
  $('#ticker').addEventListener('change', (e) => { const v = e.target.value.trim().toLowerCase(); if (v) { ticker = v; refreshAll(); } });
  $('#clean').addEventListener('change', (e) => { clean = e.target.checked; loadGraph(); });
  refreshAll();
})();

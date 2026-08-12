# Data-quality issue: generic-mention conflation ("supplier" super-hubs)

**Status:** Identified 2026-08-12 · **deferred** (revisit in a few days) · not yet actioned
**Owner:** Arthur Keen
**Severity:** high for analytics / GraphRAG / visualization correctness; **not** an ETL bug
(the defect is upstream in the source extraction — our ETL faithfully loaded it).
**Related:** [PRD.md](PRD.md) §4.1 (node identity), §8 (non-goal: entity resolution);
the `arango-entity-resolution` project (the coreference/ER fix, Phase 3 below).

---

## TL;DR

The knowledge graph conflates **anonymous, indefinite mentions** ("a supplier", "our
customers", "a third party") into **single shared nodes**, because node identity is
`hash(name | type)` and the "name" is a bare common noun. So **680 unrelated companies all
point at one `supplier` node** — asserting, falsely, that they share a supplier. The correct
model is **one anonymous node per mention** — exactly an **RDF blank node (bnode) /
skolemized instance**. This fabricates connectivity, inflates centrality of meaningless
nodes, and corrupts graph analytics (PageRank, community detection, k-hop), GraphRAG, and the
visualizer. Fix is phased and **non-destructive**: (1) detect + flag, (2) skolemize into
per-company blank nodes, (3) coreference/ER to named entities where possible.

---

## Evidence (measured on `FinReflectKG`, 2026-08-12)

Cross-company **fan-in** is the tell — how many *distinct companies* (`ticker`) point at ONE
node. A real shared entity is pointed at by a handful; a generic-mention hub by hundreds.

| generic node | type | in-degree | **distinct companies** |
|---|---|---:|---:|
| supplier | COMP | 4,580 | **680** |
| subsidiary | SEGMENT | 5,163 | **677** |
| third party | COMP | 2,166 | 530 |
| customer | COMP | 2,117 | 458 |
| vendor | COMP | 1,247 | 399 |
| competitor | COMP | 892 | 384 |
| distributor | COMP | 1,509 | 289 |
| partner | COMP | 498 | 218 |
| contractor | COMP | 284 | 135 |
| client | COMP | 398 | 81 |
| borrower | COMP | 87 | 45 |

Aggregate (narrow 15-word role lexicon only): **242 hub nodes, ~27,879 in-edges**. A fuller
detector (below) will catch materially more (phrases, plurals, mistyped variants).

Two compounding symptoms:
- **Inconsistent typing.** The same word is smeared across many types — `customer` appears as
  COMP, PERSON, SEGMENT, GPE, FIN_METRIC, RISK_FACTOR, ORG, CUSTOMER, … (13 types). One concept
  → many hubs.
- **Proper types bypassed.** The schema *has* `SUPPLIER`/`CUSTOMER` types, but the extractor
  defaulted anonymous mentions to COMP/ORG: `supplier`[SUPPLIER] = 18 in-degree vs
  `supplier`[COMP] = 4,580.

### Reproduce
```bash
# per-name fan-in
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0,"scripts"); from arango import req
q=lambda s: req("POST","/_api/cursor",{"query":s},db="FinReflectKG",timeout=90)[1].get("result")
print(q("""LET names=["supplier","customer","competitor","vendor","client","subsidiary",
 "distributor","partner","third party","contractor","reseller","borrower"]
FOR nm IN names FOR n IN Node FILTER n.name==nm
  LET indeg=LENGTH(FOR e IN relations FILTER e._to==n._id RETURN 1)
  LET tks  =LENGTH(FOR e IN relations FILTER e._to==n._id COLLECT t=e.ticker RETURN t)
  FILTER indeg>5 SORT tks DESC
  RETURN {name:nm,type:n.type,in_degree:indeg,distinct_companies:tks}"""))
PY
```

---

## Diagnosis

Each `X --depends_on--> supplier` means *"X depends on **some** supplier"* — an existentially
quantified, **anonymous** entity. In RDF:

```
:AMD  :depends_on [ a :Supplier ] .     # blank node #1
:CINF :depends_on [ a :Supplier ] .     # blank node #2  (a DIFFERENT anonymous supplier)
```

The current LPG instead assigns **one shared key** `Node/hash("supplier"|"COMP")` to all of
them — the modeling error. This is the textbook KG-construction defect **"conflation of
generic / indefinite mentions"** (a coreference failure): the extractor pulled indefinite noun
phrases as if they were named entities and neither (a) resolved coreference to a real named
entity, (b) skolemized the anonymous ones, nor (c) typed them consistently.

**Root cause is upstream** in Domyn's FinReflectKG extraction. Our ETL is correct given the
input: `_key = hash(name|type)` is the right identity rule for *named* entities; it just
inherits the conflation for *generic* ones.

### Critical nuance — do NOT over-correct
There are **two** kinds of high-fan-in hubs; only one is wrong:
- **Legitimate shared referents** — `net income`, `revenue`, `china`, `gdp`. High fan-in, but
  genuinely the same thing across companies. This shared layer is the *value* of the KG. **Keep.**
- **Spurious generic hubs** — `supplier`, `customer`, `competitor`. Not the same referent. **Split.**

So the discriminator is **not fan-in alone**. It is:

> **high cross-company fan-in  ∧  a named-entity type (ORG / COMP / PERSON / SUPPLIER / CUSTOMER)
> ∧  a common-noun / role name** (indefinite mention, not a proper name).

A `GPE` named "china" with huge fan-in is fine; a `COMP` named "supplier" is not. (Named-entity
type is what separates them — you expect a proper name there, not a role noun.)

---

## Impact

- **Fabricated connectivity** — AMD and Cincinnati Financial appear 2 hops apart via `supplier`.
- **Analytics corruption** — `supplier`/`customer` rank absurdly high in PageRank (this directly
  distorts the P4 temporal PageRank); community detection glues unrelated firms together; k-hop
  paths through these hubs are meaningless.
- **GraphRAG** — questions about suppliers/customers hit a nonsense super-hub instead of grounded,
  company-specific facts.
- **Visualizer** — misleading structure (the screenshot that surfaced this: cinf/amd/rsg/coo/vtrs
  all fanning into one `supplier`).

---

## Fix plan (phased, non-destructive)

### Phase 1 — Detect + flag  *(cheap, ~1 hour; do this first)*
Inventory the generic hubs with the discriminator above (role-noun lexicon **×** named-entity
type **×** high distinct-company fan-in, e.g. `distinct_companies >= 10`). Stamp
`isGenericMention: true` (a.k.a. `blankNodeCandidate`) on those `Node` docs. **Reversible**,
touches no edges. Immediately lets analytics / GraphRAG / the visualizer **exclude or
special-case** them (e.g. a "hide extraction artifacts" theme rule / query filter).
- Deliverable: `scripts/flag_generic_mentions.py` (detector + flag) + an inventory report.
- Build a curated role lexicon (supplier, customer, competitor, vendor, client, distributor,
  subsidiary, partner, contractor, reseller, borrower, lender, counterparty, auditor, employee,
  shareholder, third party, affiliate, …) and *also* catch by the fan-in heuristic to find ones
  the lexicon misses.

### Phase 2 — Skolemize into blank nodes  *(the real fix; derived + rebuildable)*
For each flagged node, **split the shared hub into per-mention anonymous instances** and rewire
its in-edges:
- **Grain:** per **(ticker, role)** is usually right — a company's "our suppliers" is one
  anonymous set → one `AMD:supplier` bnode. (Per-`chunk` if maximum fidelity is wanted.)
- **Key:** deterministic, e.g. `bnode:{ticker}:{normalizedRole}` → idempotent rebuild.
- **Type:** normalize to the proper role type (`SUPPLIER`/`CUSTOMER`/…), carry
  `label` (the surface noun), `isGenericMention: true`, and provenance.
- **Rewire:** repoint the offending in-edges from the shared hub to the per-company bnode.
- Do it as a **derived transform on a copy / overlay** (like the time-travel layer) so the
  source graph is untouched and the pass is rebuildable. Then re-run analytics to show the
  before/after.

### Phase 3 — Coreference / entity resolution  *(best, hardest; research-grade)*
Where the filing actually names the entity ("our supplier, **TSMC**"), resolve the generic
mention to the real named node; the truly-anonymous remainder stays as bnodes. This is a genuine
coref/ER task and is squarely where **`arango-entity-resolution`** applies. Also fold in the
**type-normalization** fix (COMP→SUPPLIER) here.

---

## Recommendation

Do **Phase 1 now-ish** (detect + flag) — an hour of work that immediately de-pollutes the P4
analytics and the visualizer and is a strong demo beat ("raw extraction has a textbook KG defect;
we detect it via cross-company fan-in and quarantine it"). Then **Phase 2** skolemization as a
proper derived pass. Hold the **GAE PageRank-per-year** run until after Phase 1 — the flag will
materially change the rankings (today `supplier` would rank near the top for the wrong reason).

Demo narrative this unlocks: *raw extraction defect → detect via cross-company fan-in → remodel as
skolemized blank nodes → before/after in the graph and in PageRank.* That showcases real
KG-modeling expertise, which lands well in a graph-database demo.

## Open decisions (for when you pick this up)
- Skolemization **grain**: per-(ticker, role) vs per-chunk?
- **In place vs overlay**: a derived `FinReflectKgClean` (or a flagged overlay) vs mutating a copy?
- **Scope**: just the ~dozen worst role nouns, or the full fan-in-detected set?
- Should this become a **PRD requirement** (it's currently under the §8 "entity resolution"
  non-goal) — promote to a scoped data-quality goal, or keep as a documented limitation?

# Project rules

These rules are maintained in `.agent/rules/` (mirrored in `.cursor/rules/` for Cursor). Edit them there — this file just imports them.

@.agent/rules/arango-frontend-rules.mdc
@.agent/rules/checkpoint-regularly.md
@.agent/rules/comprehensiveness-over-simplification.md
@.agent/rules/incremental-over-atomic.md
@.agent/rules/modularity-and-structure.md
@.agent/rules/read-before-write.md
@.agent/rules/surface-dont-guess.md
@.agent/rules/test-what-you-touch.md
@.agent/rules/ui-architecture.mdc
@.agent/rules/verify-before-done.md
@.agent/rules/wiring-over-deletion.md


---

# PROJECT: domyn

## Identity
- PROJECT_ID: domyn  (e.g. "my-api", "frontend-v2")
- PROJECT_TYPE: other
- PRD_FILE: docs/PRD.md
- TECH_STACK: TBD

## Dark factory operating mode
This project uses autonomous drift detection. Three skills are registered:
- `/prd-sync` — audit implementation against PRD requirements
- `/pattern-save` — capture a solved problem to shared memory
- `/pattern-search <problem>` — search shared memory before solving a problem

**Mandatory protocol:**
1. Before solving any non-trivial problem: run `/pattern-search <description>` first.
2. After fixing a drift gap or discovering a reusable technique: run `/pattern-save`.
3. At the end of any session that touched implementation files: run `/prd-sync`.

## PRD location
The PRD is at `docs/PRD.md`. It is the source of truth for what this system must do.
All implementation must be traceable to a requirement in the PRD.
If a requirement is missing from the PRD but exists in code, add it to the PRD.

## Drift policy
- A MISSING requirement is a bug, not a TODO.
- A TEST-ONLY requirement (tested but not implemented) is deceptive — fix it.
- A PARTIAL requirement must be tracked in drift_alerts until closed.
- Never mark a requirement IMPLEMENTED without a file:line reference.

## Shared ArangoDB memory
MCP server: arangodb-memory-mcp
Collections:
- shared_patterns: cross-project solutions (read via /pattern-search, write via /pattern-save)
- project_registry: this project's state and contribution count
- drift_alerts: open drift gaps for this project

## Session end checklist
Before ending any session:
- [ ] Run /prd-sync if any implementation files were modified
- [ ] Run /pattern-save for any technique worth sharing
- [ ] Check .prd-drift-queue for queued change alerts

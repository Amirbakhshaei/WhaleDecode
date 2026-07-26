---
name: audit-explainability
description: Use when making any non-trivial change (3+ files, schema change, graph edit, port change, or any behavioral change). Enforces change reports with why/what/risks/verified, diff-driven reasoning, Architecture Decision Notes for boundary changes, and strict separation of refactors from feature work.
---

## When to Apply

Every non-trivial change. A change is non-trivial if it:
- Touches 3+ files
- Changes a Pydantic schema
- Adds/modifies a graph node or edge
- Changes a port interface
- Modifies Telegram formatting or guardrails
- Alters deployment configuration
- Touches user data (schemas, persistence, privacy)

## 1. Change Report Format

Every non-trivial change MUST be accompanied by a change report in this standard format:

```markdown
## Change: <short description>

### Why
- <product or engineering driver — reference user request, issue, or ADR>

### What Files
| File | Change | Risk |
|------|--------|------|
| `graphs/event_investigation.py` | Added `enrich_token` node | Low — deterministic |
| `schemas/reports.py` | Added `token_info` to `ReasoningReport` | Medium — breaks Format node |
| `nodes/enrichment.py` | Implemented `enrich_token` | Low — new node, no callers yet |

### Risks
- <Anything that could break: downstream consumers, data loss, performance regression>

### How Verified
- `ruff check .` — pass
- `mypy src` — pass
- `pytest tests/graphs/test_event_investigation.py -xvs` — 12 passed, 0 failed
- `pytest tests/unit/test_reports.py -xvs` — 3 passed, 0 failed
- Manual: ran `python -c "from schemas.reports import ReasoningReport; print(ReasoningReport(**test_data).model_dump_json())"`
```

## 2. Diff-Driven Reasoning

Before writing a change report, use the Git MCP to produce the evidence:

- `git diff --stat` — what files changed
- `git diff` — the actual diff
- `git log --oneline -5` — recent context if working in a branch

The change report's "What Files" and "Risks" sections must be grounded in the actual diff, not in what you planned to write.

## 3. Architecture Decision Notes (ADNs) for Boundary Changes

Any change that touches a boundary between layers (domain ↔ application, application ↔ adapter, new port, new graph) MUST produce an Architecture Decision Note in `docs/adr/<number>-<title>.md`.

ADR format:
```markdown
# ADR-<number>: <title>

**Date:** <date>
**Status:** Proposed | Accepted | Deprecated

## Context
<What problem required this architectural change?>

## Decision
<What we decided to do>

## Consequences
<Positive and negative tradeoffs — cite specific files/lines>

## Alternatives Considered
<What else we considered and why we rejected it>
```

ADR numbers increment. See existing ADRs in `docs/adr/` if any.

## 4. No Silent Refactors

- A "refactor" commit touches ONLY structure, NEVER behavior.
- A "feature" commit touches ONLY behavior, NEVER structure beyond what the feature needs.
- If a change must both refactor and add a feature → two commits: `refactor: rename X to Y` then `feat: add Z to Y`.
- In pull requests: separate commits per concern, or two separate PRs.

## 5. Verification

- [ ] Change report written (why + what files + risks + how verified)?
- [ ] Diff-driven: report matches actual `git diff`?
- [ ] Boundary change → ADR created in `docs/adr/`?
- [ ] Refactor and feature in separate commits?

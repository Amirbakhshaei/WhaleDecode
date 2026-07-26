---
name: intelligence-workflow
description: Use before multi-file changes, graph/workflow edits, architecture decisions, or investigating a problem. Enforces sequential-thinking, tool-based investigation, multi-step plans for graph edits, and scope discipline between product features and engineering improvements.
---

## When to Apply

- Before any change touching 3+ files
- Before editing a LangGraph graph (nodes, edges, state)
- Before changing a port interface or adding a new adapter
- When investigating a bug, performance issue, or unexpected behavior
- When planning a sprint/feature increment

## 1. Use sequential-thinking Before Multi-File Changes

Before writing code across >1 file, use the `sequential-thinking` MCP to lay out:

1. **Goal** — What behavior change is requested in user terms
2. **Current state** — What the affected files look like now (read them first)
3. **Proposed changes per file** — For each file: what changes, why, risk level
4. **Schema impact** — Does any Pydantic model change? If so, what downstream consumers break?
5. **Test plan** — Which existing tests need updating, which new tests are needed
6. **Rollback** — How to revert without data loss

Output the thinking trace in the change report (see audit-explainability skill).

## 2. Investigate With Tools Before Concluding

When investigating a bug or unexpected behavior, use tools in this order:

1. **Read** the affected code path
2. **Git** MCP — `git log --oneline -20` for recent changes, `git diff HEAD~1` for the diff, `git blame` on the suspicious lines
3. **Read** the test files that cover this path
4. **Run** the relevant test: `pytest tests/path/to/test.py -xvs`
5. **If still unclear** — add a minimal reproduction script in `jobs/scripts/`, run it, inspect the output
6. **Only then** conclude and propose a fix

Never skip to "the fix is obviously X" without running through steps 1-5.

## 3. Multi-Step Plans for Graph/Workflow Edits

LangGraph graphs have a state machine structure (nodes + edges + checkpoints). A safe edit follows this protocol:

```
Step 1: Read the graph file + state schema + every node file + edge definitions + tests
Step 2: sequential-thinking trace (see above)
Step 3: Write the node change or new node
Step 4: Update edge routing if topology changed
Step 5: Update state schema if node input/output changed
Step 6: Update graph output schema if the graph's return type changed
Step 7: Update callers (use-cases, tests)
Step 8: Run tests: pytest tests/graphs/test_affected_graph.py -xvs
Step 9: Run full lint + typecheck: ruff check . && mypy src
Step 10: Update test fixtures / eval datasets if schema changed
```

Each step is one atomic change. Commit after Step 8, not before.

## 4. Product Scope vs Engineering Improvement

Every change must answer: "Is this a product feature (user-visible) or an engineering improvement (non-user-visible)?"

- **Product features** — Must be gated by tier, have tests, have disclaimer, have a changelog entry
- **Engineering improvements** — Must be shipping as a separate PR/commit from product work. No "while I was there" refactors mixed with feature changes.

If a refactor touches the same files as a feature → two separate commits, two separate branches, or a clear "refactor first" commit before "feature" commit.

## 5. WhaleAgent MVP Scope Discipline

The v0.1 product scope is defined in `docs/architecture.md` section 1.1:
- Telegram bot, single VPS, Docker Compose, Postgres + Redis
- Three chains: Ethereum Mainnet, Base, Arbitrum One
- Free tier (3 wallets, 5 chat/day, daily briefing) + Paid tier (unlimited, instant alerts)
- 10 read-only tools, mockable providers
- No web dashboard, no API, no payments automation (manual admin grant)

When a request extends beyond this scope → flag it as "post-MVP" and slot into `docs/agents.md` section 13 TODOs. Don't implement it inline.

## Verification

- [ ] sequential-thinking used before >1 file changes?
- [ ] Investigation completed all 6 steps before concluding?
- [ ] Graph edit followed all 10 steps?
- [ ] Feature and refactor in separate commits?
- [ ] Change stays within v0.1 MVP scope?

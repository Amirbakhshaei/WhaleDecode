---
name: accuracy-discipline
description: Use before writing new code, editing existing code, or calling external APIs/library functions. Enforces read-before-write, run-tests-after-behavioral-change, verify-APIs-via-docs, typed Pydantic schemas, explicit TODOs, and fail-closed guarantees.
---

## When to Apply

Always. This is the baseline discipline for every change.

## Rules

### 1. Read Before Write

- Read the file(s) you intend to modify + their tests + their callers before making any edit.
- For class/functions you're extending, read the full file, not just the diff.
- For graphs: read the node, the state schema, the edge routing, AND at least one test file.

### 2. Never Invent APIs or Library Methods

- If you're unsure about a method name, signature, or import path → verify via:
  - The installed package's source in `site-packages/` or `node_modules/`
  - The official docs MCP (context7, fetch) for the library version in `pyproject.toml`
  - A REPL test: `python -c "import aiogram; print(dir(aiogram.Router))"`
- If you cannot verify, prefer a simpler approach you CAN verify.
- In schemas: never guess Pydantic field types or validators. Check `BaseModel`, `Field`, `validator`, `model_validator` signatures in the installed Pydantic version.

### 3. Typed Pydantic Schemas for Every Structured Output

- Every graph output, tool result, and Telegram message payload MUST be a typed Pydantic `BaseModel`.
- No raw dicts, no `Any`, no `**kwargs` in public interfaces.
- Tool args and results schemas live in `schemas/tools.py`.
- Graph state and output schemas live next to their graph in `graphs/`.

### 4. Run Tests After Behavioral Changes

After any change that affects behavior (not formatting, not comments):
```
ruff check .        # lint (must pass)
mypy src             # typecheck (must pass)
pytest               # full test suite (focused test at minimum)
```

If a focused test takes >10s, run the specific test file:
```
pytest tests/unit/path/to/test_file.py -xvs
```

### 5. Explicit TODOs Over Hidden Assumptions

When you encounter:
- A code path that could fail but has no error handling → add `# TODO(0.2): ...`
- A missing schema field that will be needed → add `# TODO(v2): ...`
- A hardcoded value that should be configurable → add `# TODO(config): ...`
- An incomplete test scenario → add `# TODO(test): ...`
- A known architecture debt (e.g., no port for something) → add `# TODO(arch): ...`

Every TODO must have a scope tag and a plan. No bare `# TODO`.

### 6. Fail Closed on Plan Gating, Auth, Disclaimers

| Guard | Behavior |
|-------|----------|
| Plan validation (tier limits, steps) | Fail closed → safe refusal with guidance, never silently truncate |
| Auth/tier check | Deny with message, never fall through to paid features |
| Financial-advice classifier | Hard refuse on hits, never silently pass |
| Disclaimer footer | Always appended, never optional |
| Overclaim detector | Override confidence down, never up |

Write the failure branch first, then the happy path.

### 7. Verification Checklist for Every Change

- [ ] Read the target file + its tests before editing?
- [ ] Any API/library call I made up instead of verifying?
- [ ] Every new output shaped as a Pydantic model, not a dict?
- [ ] `ruff check .` pass?
- [ ] `mypy src` pass?
- [ ] `pytest` pass for affected tests?
- [ ] Every uncovered corner case has a `# TODO` with scope tag?
- [ ] Failure paths written before happy paths?

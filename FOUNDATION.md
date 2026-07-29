# WhaleDecode — Foundation (Current State)

## 10-Bullet Summary

1. **Project name**: WhaleDecode (previously WhaleAgent internally — renaming aligned)
2. **Architecture**: Hexagonal — domain → application → adapters → entrypoints
3. **Stack**: Python 3.12, aiogram 3, SQLAlchemy 2 + asyncpg, LangGraph + Groq, Docker Compose
4. **CLI**: 5 commands — `bot`, `worker`, `migrate`, `seed`, `db-init` via Click
5. **Domain entities**: 8 Pydantic models (User, CuratedWallet, TrackedWallet, CandidateEvent, Alert, AgentRun, Briefing, AdminAuditLog)
6. **DB**: 8 SQLAlchemy ORM models, 2 Alembic migrations, async session, UnitOfWork with 8 repositories
7. **LLM**: LangGraph event investigation graph works (analyze → tools → report → score → guardrails → format), chat + briefing are stubs
8. **Chain**: DRPC HTTP provider with tenacity retries + MockChainProvider for testing (falls back to mock when DRPC key absent)
9. **Telegram**: 4 routers (common, wallet, chat, admin), throttling middleware, alert dispatcher, alert formatter
10. **Tests**: 25 unit tests passing (value objects, policies, repositories, seed)

## Current Gaps vs v1.0

| Area | Status | Phase |
|------|--------|-------|
| Chat investigation | STUB (returns placeholder) | Phase 1 |
| Briefing generation | STUB (returns placeholder) | Phase 5 |
| Worker | STUB (logs "not implemented") | Phase 2 |
| Polling/alerts | Not built | Phase 2 |
| Plan enforcement | Not built | Phase 1 |
| AEGIS guardrails | Minimal (just disclaimer append) | Phase 1 |
| RELAY formatter | Not built (only raw alert.py) | Phase 1 |
| Channel auto-publish | Not built | Phase 4 |
| Redis | Optional, no code uses it | Phase 3 |
| Payments | Manual admin grant only | Phase 3 |

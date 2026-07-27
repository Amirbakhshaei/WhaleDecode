# Changelog

## v0.1.0 (2026-07-26)

Initial release with all 11 phases complete.

### Features
- Domain: 11 entities, value objects (Address, Hash, Chain, Money), 8 repo ports, policies
- DB: SQLAlchemy 2.0 async ORM, Alembic migration, 8 repository implementations, UnitOfWork
- Chain: Mock chain provider, multi-provider failover, HTTP RPC client
- AI: LangGraph investigation graph (analyze → tools → report → score → guardrails → format)
- UI: Gradio web app with Dashboard, Wallets, Events, AI Chat tabs
- Bot: Telegram bot with throttling middleware, command routers
- Worker: arq queue + APScheduler cron for polling and daily briefing
- Tests: 25 unit tests (value objects, policies, repositories with SQLite)

### Infrastructure
- HuggingFace Space-ready (app.py + requirements.txt)
- Docker Compose for Postgres + Redis
- Makefile for common operations
- ruff + mypy linting

### Known Limitations
- Mock chain data when no ALCHEMY_API_KEY set
- Billing is stub-based
- Telegram commands are basic stubs
- No Kubernetes/Grafana yet

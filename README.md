# 🐋 WhaleDecode

AI Smart Money Agent — monitors whale wallets, detects on-chain events, investigates with LangGraph/Groq, and sends alerts.

## Quick Start

```bash
# 1. Clone and set up
cp .env.example .env
# Fill in at least: BOT_TOKEN, GROQ_API_KEY, DATABASE_URL, REDIS_URL

# 2. Install
make install        # or: pip install -r requirements.txt

# 3. Run Gradio UI (recommended)
make run-ui         # or: python app.py

# 4. Or run Telegram bot
make run-bot        # or: whaledecode bot
```

## Deployment

Deploy on HuggingFace Spaces: point to this repo, set secrets in Space settings, Spaces auto-detects `app.py`.

## Architecture

Hexagonal layering: `domain → application → adapters`. See `docs/architecture.md`.

## What's Built

| Phase | What |
|-------|------|
| 0 | Scaffold, settings, logging, CLI |
| 1 | Domain entities, ORM, migration, seed data |
| 2 | Repositories, UnitOfWork, session factory |
| 3 | Mock + multi-chain providers |
| 4 | LangGraph investigation graph |
| 5 | Application services, Gradio UI |
| 6 | Telegram bot routers + dispatcher |
| 7 | Background worker (arq + cron) |
| 8 | Docker, Makefile (ready) |
| 9 | Unit tests (25 passing) |

## Limits

- Mock chain data when `ALCHEMY_API_KEY` unset
- Gradio UI requires DB + Redis
- Telegram bot commands are stubs (use Gradio)

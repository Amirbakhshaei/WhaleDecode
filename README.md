# WhaleDecode

AI Smart Money Agent — monitors whale wallets, detects on-chain events, investigates with LangGraph/Groq, and sends Telegram alerts.

## Quick Start

```bash
# 1. Clone and set up
cp .env.example .env
# Fill in at least: BOT_TOKEN, GROQ_API_KEY, DATABASE_URL

# 2. Install
poetry install

# 3. Run migrations
poetry run whaledecode migrate

# 4. Start Telegram bot
poetry run whaledecode bot
```

## Running with Docker

```bash
# Start all services (Postgres + bot + worker)
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `whaledecode bot` | Start Telegram bot (polling mode) |
| `whaledecode worker` | Start background event polling + briefing worker |
| `whaledecode migrate` | Run Alembic database migrations |
| `whaledecode seed` | Seed database with curated wallets |
| `whaledecode db-init` | Create initial migration and apply it |

## What's Built

| Phase | What |
|-------|------|
| 0 | Scaffold, settings, logging, CLI |
| 1 | Domain entities, ORM, migration, seed data |
| 2 | Repositories, UnitOfWork, session factory |
| 3 | Multi-chain providers (ETH, Base, Arbitrum) |
| 4 | LangGraph investigation graph |
| 5 | Application services |
| 6 | Telegram bot routers + alert dispatcher |
| 7 | Background worker (pure asyncio + cron) |
| 8 | Docker, compose, Railway config |
| 9 | Unit tests (25 passing) |

## Deploy to Railway

1. **Push to GitHub** — Railway builds from your repo.

2. **Create a Railway project** from the repo. Railway auto-detects the Dockerfile.

3. **Set environment variables** in Railway dashboard:

   | Variable | Required | Description |
   |----------|----------|-------------|
   | `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
   | `GROQ_API_KEY` | Yes | Groq API key for LLM inference |
   | `DATABASE_URL` | Yes | Railway Postgres URL (set by Railway plugin) |
   | `ENV` | No | `production` (default: `dev`) |
   | `ADMIN_USER_IDS` | No | JSON array of admin Telegram user IDs |

4. **Add a Postgres plugin** — Railway will inject `DATABASE_URL` automatically.

5. **Run migrations** as a release command:
   ```bash
   whaledecode migrate
   ```
   Set this in Railway dashboard → Service → Settings → Release Command.

6. **Scale bot and worker separately** — Create two Railway services from the same repo:
   - **Bot service**: start command = `bot`
   - **Worker service**: start command = `worker`

   Each service gets the same env vars and Postgres plugin.

7. **Deploy** — Railway builds, runs the release command, then starts the service.

## Architecture

Hexagonal layering: `domain → application → adapters`. See `docs/architecture.md`.

## Limits

- Mock chain data when `DRPC_API_KEY` unset
- Bot runs in polling mode (no webhook)
- No per-user rate limiting enforced yet
- Alert scoring thresholds are preliminary

# WhaleDecode — Railway Deployment

## Prerequisites

- GitHub repo with your code pushed
- Railway account
- Telegram Bot Token (from @BotFather)
- Groq API Key (from console.groq.com)
- Postgres instance (Railway Postgres plugin)
- Telegram Channel (for auto-publishing, optional)

## Step 1: Create Railway Project

1. Go to [railway.app](https://railway.app) → New Project
2. Choose "Deploy from GitHub repo"
3. Select your WhaleDecode repo

## Step 2: Add Postgres Plugin

1. In your Railway project, click "New" → "Database" → "Add PostgreSQL"
2. Railway will inject `DATABASE_URL` automatically

## Step 3: Create Bot Service

1. Create a new Railway service from the same repo
2. Set start command: `whaledecode bot`
3. Add environment variables (see below)

## Step 4: Create Worker Service

1. Create a second Railway service from the same repo
2. Set start command: `whaledecode worker`
3. Add same environment variables

## Step 5: Set Release Command

In Railway dashboard → Bot Service → Settings → **Release Command**:
```
whaledecode migrate
```

This runs database migrations before each deploy.

## Step 6: Environment Variables

| Variable | Required | Value |
|----------|----------|-------|
| `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `GROQ_API_KEY` | Yes | Groq API key |
| `DATABASE_URL` | Yes | Injected by Railway Postgres plugin |
| `ENV` | No | `production` |
| `ADMIN_USER_IDS` | No | JSON array of admin Telegram user IDs |
| `DISCLAIMER_TEXT` | No | Custom disclaimer (has sensible default) |
| `CHANNEL_CHAT_ID` | No | Telegram channel chat_id for auto-publishing |
| `CHANNEL_PUBLISH_ENABLED` | No | `true` to enable channel publishing |

## Step 7: Enable Channel Publishing (Optional)

1. Add bot as admin to your Telegram channel
2. Set `CHANNEL_CHAT_ID` to your channel's chat_id (e.g., `-1001234567890` or `@channelname`)
3. Set `CHANNEL_PUBLISH_ENABLED=true`

## Architecture Notes

- **Bot service**: Handles user commands, chat, and callbacks. Single process.
- **Worker service**: Handles wallet polling, event processing, alert dispatch, briefings, and channel publishing.
- **Data**: Both services share the same Postgres database.
- **Release command**: `whaledecode migrate` runs Alembic migrations.

## Scaling

Railway scales each service independently. For v1.0:
- Bot: 512MB RAM, 0.5 CPU
- Worker: 1GB RAM, 1 CPU

## Monitoring

Railway provides:
- Resource usage graphs
- Deploy logs
- Rails-to-scale alerts

For structured logging, each log line includes: `timestamp`, `level`, `correlation_id`, `service`, `event`.

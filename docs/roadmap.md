# WhaleDecode — v1.0 Roadmap

## Product
Telegram-first AI smart-money intelligence.
Watches curated smart-money wallets on Base + Arbitrum, detects significant on-chain moves, decodes them into plain-English alerts, chat answers, and daily briefings.

## Grilling Decisions (28)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Chat vs Event graph | **Separate graphs** | Different pipelines, shared tools |
| 2 | Alert delivery | **Worker sends directly via Telegram API** | No queue dependency, simplest |
| 3 | Plan enforcement | **Middleware + use-case** | Auth in middleware, limits in use cases |
| 4 | AEGIS/RELAY | **Standalone services** | Injectable classes with DI |
| 5 | DB models | **Pydantic domain + SQLAlchemy ORM** | Keep current pattern, adapters convert |
| 6 | Model routing | **Strong model for everything + cost logging** | Add routing when costs matter |
| 7 | Worker architecture | **Hybrid APScheduler + asyncio** | Cron for briefings, loops for polling |
| 8 | Disclaimer | **Configurable via settings** | Default text, overridable via env |
| 9 | HUNTER/CURATOR | **Post-v1.0** | Manual seed only, discovery is growth |
| 10 | Plan entity | **Enum/constants module** | No DB table, Python objects |
| 11 | Alert callbacks | **Hybrid** — Risks pre-extracted, Explain/Related fresh LLM | Cost vs quality balance |
| 12 | Wallet polling | **Batch** — 50 addresses per eth_getLogs call | 4 calls vs 200 per cycle |
| 13 | Test approach | **Unit tests + graph smoke test with mocked LLM** | Skip DB integration for v1.0 |
| 14 | LLM client | **Keep ChatOpenAI + Groq base URL** | Works, already a dependency |
| 15 | Retries | **Tenacity everywhere** | Already a dependency, consistent |
| 16 | Seed data | **YAML file** | Human-readable, no code changes |
| 17 | Callback data | **Alert ID + action type** | Fits 64-byte limit, no Redis |
| 18 | Documentation | **README + docs/ + CHANGELOG** | Standard open-source structure |
| 19 | Message formatting | **HTML only** | Predictable escaping, already configured |
| 20 | Admin commands | **Namespaced** — `/admin stats`, `/admin grant` | Cleaner UX, less clutter |
| 21 | `/upgrade` | **Stub only** — "contact admin" | No payment automation in v1.0 |
| 22 | `/ask` + `/decode` | **Separate commands** — same graph, different context | Clear user intent paths |
| 23 | Briefing | **Hybrid** — DB raw data + LLM synthesis | Fast data, readable output |
| 24 | Alert template | **Single template with conditional sections** | Easiest to maintain |
| 25 | Alert toggle | **Boolean `alerts_enabled` on User** | Simplest, add preferences later |
| 26 | Deduplication | **DB constraint only** | Unique constraint is source of truth |
| 27 | Cost tracking | **Token counts + cost calculation** | `MODEL_PRICING` dict, ~10 lines |
| 28 | Checkpointer | **None for v1.0** | All graphs single-shot |

## Post-v1.0 Backlog (Do Not Build Now)

- [ ] HUNTER/CURATOR discovery pipeline (counterparty expansion + scoring)
- [ ] Telegram Stars payment automation + webhook
- [ ] Model routing (cheap vs strong per node)
- [ ] Redis checkpointer for conversation memory
- [ ] Per-user alert preferences (per-chain, per-event-type)
- [ ] Ethereum mainnet expansion
- [ ] Web mini-dashboard (Next.js)
- [ ] Solana adapter
- [ ] User wallet labeling / notes

---

## Phase 0 — Recon + Hardening Baseline

**Goal:** Align naming, clean structure, create docs, verify foundation.

### Tasks
- [ ] Rename all references from "WhaleAgent" to "WhaleDecode" (architecture.md, main.py docstrings, README)
- [ ] Create `docs/roadmap.md` (this file)
- [ ] Create `docs/v1-acceptance.md` — all 37 acceptance criteria as checklist
- [ ] Create `docs/agents.md` — agent roles (SENTINEL, ORION, MERIDIAN, LEDGER, AEGIS, RELAY)
- [ ] Create `FOUNDATION.md` — current truth (10-bullet summary)
- [ ] Create `domain/exceptions/` — custom exceptions (`PlanLimitExceeded`, `AlertSuppressed`, `InvalidChain`, `DedupeConflict`)
- [ ] Add `alerts_enabled: bool = True` to User entity + ORM model
- [ ] Verify all existing tests pass (`make test`)
- [ ] Verify lint/typecheck clean (`make pre-commit`)
- [ ] Add `DISCLAIMER_TEXT` to Settings with sensible default

### Files to create
`docs/roadmap.md`, `docs/v1-acceptance.md`, `docs/agents.md`, `FOUNDATION.md`, `domain/exceptions/__init__.py`

### Files to modify
User entity + ORM model (add `alerts_enabled`), README.md (rename), architecture.md (rename), settings.py (add DISCLAIMER_TEXT)

### DoD
- [ ] All 25 tests pass
- [ ] Lint + typecheck clean
- [ ] Docs exist with correct naming
- [ ] User has `alerts_enabled` field
- [ ] Disclaimer configurable via env

---

## Phase 1 — v0.2 First Real Decode Loop

**Goal:** Chat decode becomes real product value.

### Tasks
- [ ] **Plan system** — Create `config/tiers.py` with `PlanTier` enum, `PlanLimits` dataclass, hardcoded limits
- [ ] **ChatInvestigationGraph** — New graph in `adapters/llm_graph/graphs/chat_investigation.py` with nodes: tool_route → retrieve → analyze → format → guardrails
- [ ] **ChatInvestigationState** — `adapters/llm_graph/state/chat_investigation.py` TypedDict
- [ ] **Reasoner chat path** — `LangGraphReasoner.investigate_chat()` invokes `ChatInvestigationGraph`
- [ ] **Wire `/ask` command** — Rename `/chat` to `/ask`, add `/decode <tx_hash>` command in router
- [ ] **AEGIS service** — `adapters/llm_graph/guardrails/aegis.py` — `AegisGuardrail` class with `validate_output()`, `scrub_pii()`, `check_disclaimer()`
- [ ] **RELAY service** — `adapters/telegram/formatters/relay.py` — `RelayFormatter` class with `format_alert()`, `format_chat_response()`, `format_briefing()`
- [ ] **Plan enforcement** — Middleware checks `alerts_enabled`, use-cases check chat limits with atomic DB increments
- [ ] **Free chat limits** — `InvestigationService.chat()` increments `daily_chat_count`, checks against `PlanLimits`
- [ ] **Admin grant** — `/admin grant <tg_id> paid` works (verify existing implementation)

### Files to create
`config/tiers.py`, `adapters/llm_graph/graphs/chat_investigation.py`, `adapters/llm_graph/state/chat_investigation.py`, `adapters/llm_graph/guardrails/aegis.py`, `adapters/telegram/formatters/relay.py`

### Files to modify
`adapters/llm_graph/reasoner.py` (implement chat), `adapters/telegram/routers/chat.py` (rename to ask, add decode), `config/settings.py` (add DISCLAIMER_TEXT), `adapters/telegram/middleware/` (add plan check)

### DoD
- [ ] `/ask` returns structured investigation with disclaimer
- [ ] `/decode <tx>` works with focused decode path
- [ ] Free plan limits enforced (5 chats/day)
- [ ] AEGIS validates and scrubs outputs
- [ ] RELAY formats messages consistently
- [ ] Disclaimer on all AI outputs
- [ ] PRISM review passed

---

## Phase 2 — v0.3 Live Alerts from Curated Wallets

**Goal:** Automatic monitoring and alert loop.

### Tasks
- [ ] **Event normalizer** — `adapters/chain/normalizer.py` — converts raw RPC logs to `CandidateEvent`
- [ ] **SENTINEL rules** — `domain/policies/sentinel.py` — detection rules (large transfer, swap, first interaction, accumulation, multi-wallet confluence)
- [ ] **Polling job** — `jobs/poll_wallets.py` — batch `eth_getLogs` per chain, normalize to `CandidateEvent`, store in DB
- [ ] **Alert creator** — After `EventInvestigationGraph` completes, create `Alert` with dedupe_key, check plan for immediacy
- [ ] **Alert sender job** — `jobs/send_alerts.py` — polls pending alerts, formats via RELAY, dispatches via Telegram
- [ ] **`/alerts on|off`** — Toggle `alerts_enabled` on User
- [ ] **Alert callbacks** — Inline buttons: "Explain more", "Risks", "Related", "Ask follow-up". Handler in `routers/callbacks.py`
- [ ] **Idempotent sending** — DB unique constraint on `(user_id, dedupe_key)` for alerts
- [ ] **Worker entrypoint** — Implement `entrypoints/worker.py` with hybrid scheduler: APScheduler for cron jobs, asyncio loops for polling
- [ ] **Free vs Paid alert policy** — Free: hourly batch delivery. Paid: instant delivery on event detection

### Files to create
`adapters/chain/normalizer.py`, `domain/policies/sentinel.py`, `jobs/poll_wallets.py`, `jobs/send_alerts.py`, `adapters/telegram/routers/callbacks.py`

### Files to modify
`entrypoints/worker.py` (full implementation), `adapters/telegram/routers/chat.py` (add alerts on|off), `adapters/telegram/dispatcher.py` (add buttons support)

### DoD
- [ ] Mock or real curated-wallet event produces Telegram alert
- [ ] No duplicate alerts for same dedupe_key
- [ ] Callback follow-up (Explain/Risks/Related) works
- [ ] Free users get batched alerts, paid users get instant
- [ ] `/alerts on|off` toggles delivery
- [ ] Worker polls and sends without crashing
- [ ] PRISM review passed

---

## Phase 3 — v0.4 Production Runtime + Paid Readiness

**Goal:** Railway-ready, operable, chargeable skeleton.

### Tasks
- [ ] **Split entrypoints** — Verify `bot.py` and `worker.py` are clean, independent processes
- [ ] **Docker Compose** — Add Redis service as optional, verify bot+worker+db boot
- [ ] **Railway docs** — Create `docs/deploy.md` with Railway-specific instructions
- [ ] **Release/migrate flow** — Document `whaledecode migrate` as Railway release command
- [ ] **Env validation** — Settings validates all required fields on boot, clear error messages
- [ ] **`/status` command** — Show plan, tracked wallets count, alerts enabled, daily usage (chats used/limit)
- [ ] **`/upgrade` stub** — Show plan comparison + "contact admin to upgrade"
- [ ] **Usage tracking** — `daily_chat_count` and `daily_alert_count` on User, counter reset job at 00:00 UTC
- [ ] **Retries/timeouts** — `tenacity` on all LLM and RPC calls (verify existing usage)
- [ ] **Structured logs** — Verify structlog with correlation_id on every log line
- [ ] **Healthchecks** — Simple health script for Railway
- [ ] **Admin stats** — `/admin stats` shows user counts, plan distribution, alerts sent today
- [ ] **Safe error fallbacks** — Bot catches exceptions, returns user-friendly messages

### Files to create
`docs/deploy.md`, `docs/admin_playbook.md`

### Files to modify
`entrypoints/worker.py`, `docker-compose.yml`, `adapters/telegram/routers/common.py` (add /status, /upgrade)

### DoD
- [ ] Docker Compose boots bot+worker+postgres locally
- [ ] Docs clearly explain Railway deploy (2 services, Postgres plugin, release command)
- [ ] `/status` and `/upgrade` work with plan info
- [ ] Paid/free state visible and enforced
- [ ] Worker survives restart without alert storms
- [ ] QUILL audit passed

---

## Phase 4 — v0.5 Channel Auto-Publishing

**Goal:** High-signal events published to Telegram channel automatically.

### Tasks
- [ ] **Settings** — Add `CHANNEL_CHAT_ID`, `CHANNEL_PUBLISH_ENABLED`, `CHANNEL_MIN_SCORE`, `CHANNEL_MAX_POSTS_PER_DAY`, `CHANNEL_PUBLISH_INTERVAL_MINUTES`
- [ ] **ChannelPost entity** — `domain/entities/channel_post.py` with id, event_id, channel_chat_id, message_id, published_at
- [ ] **ChannelPost ORM model** — `adapters/db/models/channel_post.py` with unique constraint on (event_id, channel_chat_id)
- [ ] **ChannelPost repository** — `adapters/db/repositories/channel_post.py` with create, get_by_event, count_published_today
- [ ] **DB migration** — `alembic/versions/0003_channel_posts.py`
- [ ] **Channel formatter** — `adapters/telegram/formatters/channel.py` — public-facing format (redacted tx details, branded header, educational "What happened" section, disclaimer)
- [ ] **AEGIS content filter** — Enhanced `aegis.py` with public-post filter: block DUST_SPAM, ROUTINE_TRANSFER, scrub PII, reject score < threshold
- [ ] **Publish job** — `jobs/publish_channel.py` — runs every 30 minutes, polls recent high-score events, checks daily cap, publishes
- [ ] **Daily counter reset** — Channel post count resets at 00:00 UTC
- [ ] **Integration test** — Verify mock event produces formatted channel post

### Files to create
`domain/entities/channel_post.py`, `adapters/db/models/channel_post.py`, `adapters/db/repositories/channel_post.py`, `adapters/telegram/formatters/channel.py`, `jobs/publish_channel.py`, `alembic/versions/0003_channel_posts.py`

### Files to modify
`config/settings.py`, `adapters/llm_graph/guardrails/aegis.py`, `entrypoints/worker.py`

### Requirements
- Bot must be added as admin to the Telegram channel
- `CHANNEL_CHAT_ID` must be set in `.env`
- `CHANNEL_PUBLISH_ENABLED=true` to activate

### DoD
- [ ] Mock high-score event produces formatted channel post
- [ ] Daily cap (20 posts/day) enforced
- [ ] AEGIS blocks low-signal event types (DUST_SPAM, ROUTINE_TRANSFER)
- [ ] Published posts tracked in `channel_posts` table
- [ ] No duplicate events published
- [ ] Format includes branded header + disclaimer

---

## Phase 5 — v0.6 Briefing + Curation

**Goal:** Daily habit loop and admin wallet management.

### Tasks
- [ ] **BriefingGraph** — New graph in `adapters/llm_graph/graphs/briefing.py`: retrieve → analyze → format → guardrails
- [ ] **BriefingState** — `adapters/llm_graph/state/briefing.py` TypedDict with user_id, date, events, briefing
- [ ] **Reasoner briefing path** — `LangGraphReasoner.generate_briefing()` invokes `BriefingGraph`
- [ ] **`/briefing` command** — User requests briefing, system fetches tracked wallet activity from DB, synthesizes via BriefingGraph
- [ ] **Daily briefing job** — `jobs/daily_briefing.py` — generates briefings for all users at 07:30 UTC, stores in `briefings` table
- [ ] **Channel daily digest** — Extend `publish_channel.py` to generate a daily digest summary post from the day's events
- [ ] **Admin wallet management** — Add to admin router: `/admin wallet add <address> <chain> <label>`, `/admin wallet remove <id>`, `/admin wallet list`
- [ ] **Admin audit logging** — Ensure all admin actions (grant, wallet add/remove) logged to `admin_audit_logs` table
- [ ] **docs/channel_content_pillars.md** — Document channel content strategy
- [ ] **docs/launch_checklist.md** — Pre-launch checklist

### Files to create
`adapters/llm_graph/graphs/briefing.py`, `adapters/llm_graph/state/briefing.py`, `jobs/daily_briefing.py`, `docs/channel_content_pillars.md`, `docs/launch_checklist.md`

### Files to modify
`adapters/llm_graph/reasoner.py` (implement briefing), `adapters/telegram/routers/chat.py` (add /briefing), `adapters/telegram/routers/admin.py` (add wallet commands), `entrypoints/worker.py`, `jobs/publish_channel.py` (add digest)

### DoD
- [ ] User can request `/briefing` in bot
- [ ] Daily briefing generated for all users at 07:30 UTC
- [ ] Briefings stored in DB
- [ ] Admin can add/remove/list curated wallets
- [ ] All admin actions audited
- [ ] Channel can generate daily digest post
- [ ] PRISM review passed

---

## Phase 6 — v1.0 Hardening + Launch Freeze

**Goal:** First full version freeze.

### Tasks
- [ ] **Gap fill** — Verify all 37 v1.0 acceptance criteria pass (check against docs/v1-acceptance.md)
- [ ] **Graph smoke tests** — `tests/graphs/test_investigation.py` with mocked LLM responses
- [ ] **Plan gating tests** — `tests/unit/test_plan_gating.py` — free limit enforced, paid bypass works, throttle message format
- [ ] **Dedupe tests** — `tests/unit/test_dedupe.py` — same event not alerted twice, unique constraint enforced
- [ ] **Schema validation tests** — `tests/unit/test_schema_validation.py` — Pydantic models validate correctly, reject bad data
- [ ] **Golden message format tests** — Verify RELAY/Channel output format matches spec
- [ ] **Demo script** — `scripts/demo.sh` — seed → sample chat decode → sample event decode → sample alert → sample briefing → sample channel post
- [ ] **README update** — Architecture summary, local run, seed wallets, Railway deploy, admin playbook, known limitations
- [ ] **KNOWN_LIMITATIONS.md** — Honest list of current limitations (no payment automation, polling latency, 2 chains only, no discovery, English only)
- [ ] **CHANGELOG.md** — Final v1.0 entries with all changes since v0.1
- [ ] **Version bump** — `VERSION = "1.0.0"` in `__init__.py` and `pyproject.toml`
- [ ] **Final lint/typecheck** — `make pre-commit` clean
- [ ] **Final PRISM + QUILL full audit** — Architecture review, security review, acceptance checklist sign-off

### Files to create
`tests/graphs/test_investigation.py`, `tests/unit/test_plan_gating.py`, `tests/unit/test_dedupe.py`, `tests/unit/test_schema_validation.py`, `scripts/demo.sh`, `KNOWN_LIMITATIONS.md`

### Files to modify
`README.md`, `CHANGELOG.md`, `__init__.py` (version), `pyproject.toml` (version)

### DoD
- [ ] All 37 v1.0 acceptance criteria pass
- [ ] All tests green (unit, graph smoke, plan gating, dedupe, schema)
- [ ] Demo script runs end-to-end
- [ ] Lint + typecheck clean
- [ ] README complete with architecture, deploy, admin guide
- [ ] Founder can demo and charge
- [ ] No critical blockers remain
- [ ] Final PRISM + QUILL audit passed

---

## v1.0 Acceptance Criteria Checklist

See `docs/v1-acceptance.md` for the complete 37-criteria checklist.

---

## Execution Order

```
Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6
```

Each phase must pass its DoD before moving to the next.
Phases 4 (channel auto-publishing) is in scope per founder decision.
HUNTER/CURATOR discovery pipeline is deferred to post-v1.0.

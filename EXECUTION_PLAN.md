# WhaleDecode v1.0 — Execution Plan

Phase-by-phase implementation order. Each phase has a Definition of Done; do not proceed until DoD is met.

---

## Phase 0 — Recon + Hardening Baseline

**Goal:** Align naming, create docs, add foundational fields, verify CI.

### Step 0.1 — Rename WhaleAgent → WhaleDecode
- [ ] `src/whaledecode/main.py` — change docstring from "WhaleAgent" to "WhaleDecode"
- [ ] `docs/architecture.md` — replace all "WhaleAgent" → "WhaleDecode" (title, diagrams, text)
- [ ] `README.md` — update description
- [ ] `docs/agents.md` — create with agent roles table
- [ ] `docs/v1-acceptance.md` — create with 37+ acceptance criteria
- [ ] `FOUNDATION.md` — create with 10-bullet current-state summary

### Step 0.2 — Add `alerts_enabled` to User
- [ ] `src/whaledecode/domain/entities/user.py` — add `alerts_enabled: bool = True`
- [ ] `src/whaledecode/adapters/db/models/user.py` — add `alerts_enabled: Mapped[bool]`
- [ ] Create Alembic migration for new column

### Step 0.3 — Settings additions
- [ ] `src/whaledecode/config/settings.py` — add `DISCLAIMER_TEXT: str` with sensible default

### Step 0.4 — Domain exceptions
- [ ] Create `src/whaledecode/domain/exceptions/__init__.py` with:
  - `WhaleDecodeError` (base)
  - `PlanLimitError`
  - `AlertSuppressedError`
  - `InvalidChainError`
  - `DuplicateEventError`
  - `WalletNotFoundError`
  - `AdminOnlyError`
  - `LLMError`
  - `ChainProviderError`

### Step 0.5 — Verify CI
- [ ] Run `make pre-commit` (lint + typecheck + test)
- [ ] Fix any issues found

### DoD
- [ ] `make pre-commit` passes clean
- [ ] All docs created
- [ ] User has `alerts_enabled` field
- [ ] Disclaimer configurable via env

---

## Phase 1 — v0.2 First Real Decode Loop

**Goal:** `/ask` and `/decode` return real structured investigation answers.

### Step 1.1 — Plan system
- [ ] Create `src/whaledecode/config/tiers.py`:
  - `class PlanTier(Enum)` — FREE, PAID
  - `@dataclass class PlanLimits` — chat_per_day, max_wallets, alert_immediacy
  - `PLAN_LIMITS: dict[PlanTier, PlanLimits]` — hardcoded dict

### Step 1.2 — ChatInvestigationGraph
- [ ] Create `src/whaledecode/adapters/llm_graph/state/chat_investigation.py` — TypedDict with query, messages, summary, risk_score, thesis, evidence, tool_calls, disclaimer
- [ ] Create `src/whaledecode/adapters/llm_graph/graphs/chat_investigation.py` — StateGraph with nodes: tool_route → retrieve → analyze → format → guardrails
- [ ] Add to `graphs/__init__.py`

### Step 1.3 — Reasoner chat path
- [ ] `src/whaledecode/adapters/llm_graph/reasoner.py` — implement `investigate_chat()` to invoke `ChatInvestigationGraph`; implement `generate_briefing()` stub

### Step 1.4 — Wire bot commands
- [ ] `src/whaledecode/adapters/telegram/routers/chat.py`:
  - Rename `/chat` to `/ask`
  - Add `/decode <tx_hash>` command
  - Add `/briefing` command (stub → show "coming soon" message)
- [ ] Register new routers in `entrypoints/bot.py`

### Step 1.5 — AEGIS service
- [ ] Create `src/whaledecode/adapters/llm_graph/guardrails/aegis.py`:
  - `class AegisGuardrail`:
    - `validate_output(report) -> Report` — ensures disclaimer present, risk_score in [0,100], blocks empty theses
    - `scrub_pii(text) -> str` — removes Telegram usernames, emails from public output
    - `check_disclaimer(text) -> bool` — verifies disclaimer text is present
    - `filter_for_public(report) -> Report` — redacts internal details for channel publishing

### Step 1.6 — RELAY service
- [ ] Create `src/whaledecode/adapters/telegram/formatters/relay.py`:
  - `class RelayFormatter`:
    - `format_alert(event, report) -> str` — whale alert format with emojis, bold labels, risk score, thesis, disclaimer
    - `format_chat_response(report) -> str` — investigation answer format: summary, evidence bullets, disclaimer
    - `format_briefing(briefing) -> str` — daily briefing format
    - `format_channel_post(event, report) -> str` — public-facing format (redacted, branded)

### Step 1.7 — Plan enforcement
- [ ] `src/whaledecode/adapters/telegram/middleware/` — add `PlanMiddleware` that attaches plan info to handler data
- [ ] `src/whaledecode/application/services/investigation.py` — add chat limit check: increment `daily_chat_count`, raise `PlanLimitError` if exceeded
- [ ] `src/whaledecode/telegram/routers/chat.py` — catch `PlanLimitError` and return "You've used N/N chats today. Upgrade for more."

### Step 1.8 — Cost logging
- [ ] `src/whaledecode/config/models.py` — add `MODEL_PRICING: dict[str, float]` mapping model names to cost per 1K tokens
- [ ] `src/whaledecode/adapters/llm_graph/reasoner.py` — extract token counts from LLM responses, calculate cost, store in AgentRun

### DoD
- [ ] `/ask` returns structured investigation with disclaimer
- [ ] `/decode <tx>` works with focused decode
- [ ] Free limit: 5 chats/day enforced
- [ ] Admin grant bypasses limits
- [ ] AEGIS validates outputs (disclaimer, PII scrub)
- [ ] RELAY formats all outputs consistently
- [ ] AgentRun records tokens + cost

---

## Phase 2 — v0.3 Live Alerts from Curated Wallets

**Goal:** Automatic monitoring: wallets polled → events detected → alerts sent.

### Step 2.1 — Event normalizer
- [ ] Create `src/whaledecode/adapters/chain/normalizer.py`:
  - `normalize_log(raw_log, wallet) -> CandidateEvent` — converts RPC log to structured event
  - `dedupe_key(wallet_id, tx_hash, log_index) -> str` — deterministic key

### Step 2.2 — SENTINEL rules
- [ ] Create `src/whaledecode/domain/policies/sentinel.py`:
  - `class SentinelRule(Protocol)` — score events deterministically
  - `whale_transfer(event) -> float` — score +40 if value > $100k
  - `whale_swap(event) -> float` — score +35 if value > $50k
  - `new_contract_interaction(event) -> float` — score +20 if first interaction
  - `accumulation_burst(wallet_events) -> float` — score +25 if >3 txs in short window
  - `multi_wallet_confluence(events) -> float` — basic multi-wallet signal
  - `class SentinelEngine` — runs all rules, returns blended score

### Step 2.3 — Polling job
- [ ] Create `src/whaledecode/jobs/poll_wallets.py`:
  - `async def poll_wallets(uow_factory, chain_provider)`:
    - Load all active curated wallets per chain
    - Batch `eth_getLogs` (50 addresses per call)
    - Normalize logs → CandidateEvent
    - Check dedupe_key before insert
    - Store CandidateEvent with score from SentinelEngine
    - Enqueue high-score events → AgentRun

### Step 2.4 — Alert pipeline
- [ ] After `EventInvestigationGraph` produces report:
  - Create `Alert` with dedupe_key `{user_id}:{wallet_id}:{tx_hash}:{event_type}`
  - Check plan: free users get status "pending_batch", paid users get "pending_instant"
  - Store in DB

### Step 2.5 — Alert sender job
- [ ] Create `src/whaledecode/jobs/send_alerts.py`:
  - `async def send_alerts(uow_factory, bot, relay)`:
    - Poll pending alerts (paid: every 5s, free: every 60min batch)
    - Format via RELAY
    - Check `alerts_enabled` on User
    - Send via `bot.send_message()`
    - Mark as sent

### Step 2.6 — Alert commands
- [ ] `src/whaledecode/adapters/telegram/routers/chat.py`:
  - `/alerts` — show current alert settings + recent alerts
  - `/alerts on` — set `alerts_enabled = True`
  - `/alerts off` — set `alerts_enabled = False`

### Step 2.7 — Alert callback buttons
- [ ] Create `src/whaledecode/adapters/telegram/routers/callbacks.py`:
  - Inline keyboard on each alert: "Explain more" | "Risks" | "Related" | "Ask follow-up"
  - Callback data format: `alert:{alert_id}:{action}` (fits 64 bytes)
  - "Risks" → extract from existing `ReasoningReport`
  - "Explain more" / "Related" → trigger `ChatInvestigationGraph` with event context
  - "Ask follow-up" → prompt user to type follow-up question

### Step 2.8 — Worker entrypoint
- [ ] Implement `src/whaledecode/entrypoints/worker.py`:
  - Hybrid scheduler:
    - `asyncio` loop for polling (30s interval)
    - `asyncio` loop for alert sending (5s/60s interval)
    - APScheduler for cron jobs (daily reset at 00:00 UTC)
  - Handle graceful shutdown (SIGTERM → finish current cycle → exit)
  - Structured logs with correlation_id

### Step 2.9 — Deduplication
- [ ] DB already has unique constraint on `alerts(user_id, dedupe_key)`
- [ ] Before inserting alert, check if dedupe_key exists
- [ ] If duplicate, skip (AlertSuppressedError logged)

### DoD
- [ ] Mock curated-wallet event produces Telegram alert with callback buttons
- [ ] No duplicate alerts for same dedupe_key
- [ ] "Explain more" / "Risks" / "Related" callbacks work
- [ ] Free users get batched alerts, paid users get instant
- [ ] `/alerts on|off` toggles delivery
- [ ] Worker polls and sends without crashing

---

## Phase 3 — v0.4 Production Runtime + Paid Readiness

**Goal:** Railway-ready, operable, chargeable.

### Step 3.1 — Docker Compose
- [ ] Update `docker-compose.yml`:
  - Add optional Redis service (depends on `REDIS_URL` being set)
  - Verify bot+worker+postgres boot sequence
  - Add healthchecks for all services

### Step 3.2 — Railway docs
- [ ] Create `docs/deploy.md`:
  - Two services: bot + worker (same repo, different start commands)
  - Postgres plugin (injects `DATABASE_URL`)
  - Release command: `whaledecode migrate`
  - Required environment variables
  - Scaling notes

### Step 3.3 — Admin playbook
- [ ] Create `docs/admin_playbook.md`:
  - How to grant paid plan
  - How to add/remove curated wallets
  - How to view stats
  - How to restart services
  - How to verify alerts are flowing

### Step 3.4 — User commands
- [ ] `src/whaledecode/adapters/telegram/routers/common.py`:
  - `/status` — plan, tracked wallets count, alerts enabled, daily usage (N chats used today)
  - `/upgrade` — plan comparison table + "Contact @admin to upgrade"

### Step 3.5 — Usage tracking
- [ ] Daily counter reset job in worker:
  - At 00:00 UTC: SET `daily_chat_count = 0`, `daily_alert_count = 0` for all users

### Step 3.6 — Healthchecks
- [ ] Simple health endpoint or script that verifies:
  - Bot process alive
  - DB reachable

### Step 3.7 — Admin stats
- [ ] Extend `/admin` command:
  - Total users (free/paid)
  - Alerts sent today
  - Curated wallets count
  - Tracked wallets count
  - Last polling time

### Step 3.8 — Env validation
- [ ] `Settings.__init__` validates required fields on boot
- [ ] Clear error messages for missing env vars

### DoD
- [ ] Docker Compose boots bot+worker+postgres locally
- [ ] Railway deploy docs complete
- [ ] `/status` shows plan, tracked wallets, daily usage
- [ ] `/upgrade` shows plan comparison
- [ ] Admin stats command works
- [ ] Daily counters reset

---

## Phase 4 — v0.5 Channel Auto-Publishing

**Goal:** High-signal events auto-published to Telegram channel.

### Step 4.1 — Settings
- [ ] Add to `config/settings.py`:
  - `CHANNEL_CHAT_ID: str = ""`
  - `CHANNEL_PUBLISH_ENABLED: bool = False`
  - `CHANNEL_PUBLISH_INTERVAL_MINUTES: int = 30`
  - `CHANNEL_MIN_SCORE: float = 0.70`
  - `CHANNEL_MAX_POSTS_PER_DAY: int = 20`

### Step 4.2 — ChannelPost entity + model
- [ ] Create `domain/entities/channel_post.py`:
  - `class ChannelPost(BaseModel)` — id, event_id, channel_chat_id, message_id, published_at
- [ ] Create `adapters/db/models/channel_post.py`:
  - `class ChannelPostModel(Base)` — `channel_posts` table, unique(event_id, channel_chat_id)
- [ ] Create `adapters/db/repositories/channel_post.py`:
  - `create()`, `get_by_event()`, `count_published_today()`
- [ ] Create Alembic migration: `alembic/versions/0003_channel_posts.py`

### Step 4.3 — Channel formatter
- [ ] Create `adapters/telegram/formatters/channel.py`:
  - `format_channel_post(event, report) -> str`:
    - Public-facing format (redacted tx hash details)
    - Branded header: 🐋 WhaleDecode Alert
    - Educational "What happened" section
    - Chain and value info
    - Mandatory disclaimer footer
    - HTML-safe formatting

### Step 4.4 — AEGIS public filter
- [ ] Enhance `adapters/llm_graph/guardrails/aegis.py`:
  - `filter_for_public(report)`:
    - Block event types: DUST_SPAM, ROUTINE_TRANSFER
    - Block if score < `CHANNEL_MIN_SCORE`
    - Scrub PII (addresses truncated to 0x1234...abcd)
    - Reject if no disclaimer present

### Step 4.5 — Publish job
- [ ] Create `jobs/publish_channel.py`:
  - `async def publish_channel_events(uow_factory, bot, relay)`:
    - Run every 30 minutes
    - Query `CandidateEvent` WHERE `score >= CHANNEL_MIN_SCORE` AND `created_at > now - 2h`
    - Exclude events already in `channel_posts` table
    - Check `count_published_today() < CHANNEL_MAX_POSTS_PER_DAY`
    - For each qualifying event:
      - Look up associated AgentRun result
      - AEGIS `filter_for_public()`
      - RELAY `format_channel_post()`
      - `bot.send_message(chat_id=CHANNEL_CHAT_ID, ...)`
      - Record in `channel_posts` table

### Step 4.6 — Worker integration
- [ ] Add `publish_channel` to worker scheduler:
  - If `CHANNEL_PUBLISH_ENABLED` and `CHANNEL_CHAT_ID` set, start publish loop

### DoD
- [ ] Mock high-score event produces formatted channel post
- [ ] Daily cap (20 posts) enforced
- [ ] AEGIS blocks DUST_SPAM and ROUTINE_TRANSFER from channel
- [ ] Published posts tracked in DB
- [ ] No duplicate events published
- [ ] Format includes branded header + disclaimer

---

## Phase 5 — v0.6 Briefing + Curation

**Goal:** Daily habit loop and admin wallet management.

### Step 5.1 — BriefingGraph
- [ ] Create `adapters/llm_graph/state/briefing.py`:
  - `class BriefingState(TypedDict)` — user_id, date, events[], briefing, summary
- [ ] Create `adapters/llm_graph/graphs/briefing.py`:
  - Nodes: retrieve (fetch events from DB) → analyze (summarize) → format → guardrails

### Step 5.2 — Reasoner briefing path
- [ ] `adapters/llm_graph/reasoner.py` — implement `generate_briefing()`:
  - Fetch user's tracked wallet activity from DB
  - Invoke BriefingGraph
  - Store result in briefings table
  - Return formatted briefing

### Step 5.3 — `/briefing` command
- [ ] `adapters/telegram/routers/chat.py` — add `/briefing` handler:
  - Free users: get daily briefing (once per day)
  - Paid users: get on-demand briefing
  - Format via RELAY

### Step 5.4 — Daily briefing job
- [ ] Create `jobs/daily_briefing.py`:
  - Runs at 07:30 UTC daily
  - For each user with tracked wallets:
    - Generate briefing
    - Store in briefings table
    - Send to user via Telegram

### Step 5.5 — Channel daily digest
- [ ] Extend `jobs/publish_channel.py`:
  - At end of day (23:55 UTC): generate "Today's Top Events" digest post
  - List top N events of the day with brief summaries

### Step 5.6 — Admin wallet management
- [ ] Extend `adapters/telegram/routers/admin.py`:
  - `/admin wallet add <address> <chain> <label>` — add curated wallet
  - `/admin wallet remove <id>` — remove curated wallet
  - `/admin wallet list` — list all curated wallets
- [ ] Audit log all admin wallet actions

### Step 5.7 — Docs
- [ ] Create `docs/channel_content_pillars.md`
- [ ] Create `docs/launch_checklist.md`

### DoD
- [ ] `/briefing` returns structured daily summary
- [ ] Daily briefing sent to all users at 07:30 UTC
- [ ] Briefings stored in DB
- [ ] Admin can add/remove/list wallets
- [ ] All admin actions logged
- [ ] Channel daily digest generates

---

## Phase 6 — v1.0 Hardening + Launch Freeze

**Goal:** Everything solid, tested, documented, ready to charge.

### Step 6.1 — Acceptance checklist
- [ ] Run through all 42 criteria in `docs/v1-acceptance.md`
- [ ] Fix any gaps found

### Step 6.2 — Tests
- [ ] Create `tests/graphs/test_investigation.py` — smoke test with mocked LLM:
  - EventInvestigationGraph produces ReasoningReport
  - ChatInvestigationGraph produces valid response
  - BriefingGraph produces briefing
- [ ] Create `tests/unit/test_plan_gating.py`:
  - Free user blocked after 5 chats
  - Paid user allowed 50+ chats
  - Admin grant sets plan correctly
- [ ] Create `tests/unit/test_dedupe.py`:
  - Same event dedupe_key not inserted twice
  - Unique constraint enforced
- [ ] Create `tests/unit/test_schema_validation.py`:
  - Pydantic models validate correctly
  - Invalid data rejected

### Step 6.3 — Demo script
- [ ] Create `scripts/demo.sh`:
  - Seed wallets
  - Run sample `/ask` command (mock)
  - Run sample event decode
  - Show sample alert format
  - Show sample briefing format
  - Show sample channel post format
  - All output to stdout for verification

### Step 6.4 — Documentation finalize
- [ ] Update `README.md`:
  - Architecture summary (1 paragraph)
  - Quick start (cp .env → install → migrate → run)
  - Seed wallets
  - Railway deploy
  - Admin playbook reference
  - Known limitations
- [ ] Create `KNOWN_LIMITATIONS.md`:
  - No payment automation (manual admin grants)
  - Polling latency (30s+ for event detection)
  - 2 chains only (Base + Arbitrum)
  - No wallet discovery (curated only)
  - English only
  - No web dashboard
  - No Solana

### Step 6.5 — Version bump
- [ ] `src/whaledecode/__init__.py` — `VERSION = "1.0.0"`
- [ ] `pyproject.toml` — `version = "1.0.0"`
- [ ] `CHANGELOG.md` — final v1.0 entry with all changes

### Step 6.6 — Final CI
- [ ] `make pre-commit` — clean lint, typecheck, all tests pass

### Step 6.7 — Final audit
- [ ] PRISM review: architecture, bugs, boundary leaks
- [ ] QUILL audit: intent, files changed, product impact, risks, residual risks

### DoD
- [ ] All 42 v1.0 acceptance criteria pass
- [ ] All tests green
- [ ] Demo script runs end-to-end
- [ ] README complete
- [ ] Version bumped to 1.0.0
- [ ] No critical blockers remain
- [ ] Founder can demo and charge

---

## File Inventory Summary

### New Files (32)

| File | Phase | Purpose |
|------|-------|---------|
| `docs/roadmap.md` | 0 | Phase plan with grilled decisions |
| `docs/v1-acceptance.md` | 0 | Acceptance criteria checklist |
| `docs/agents.md` | 0 | Agent roles table |
| `FOUNDATION.md` | 0 | Current state summary |
| `domain/exceptions/__init__.py` | 0 | Custom exceptions |
| `config/tiers.py` | 1 | Plan enum + limits |
| `adapters/llm_graph/graphs/chat_investigation.py` | 1 | Chat LangGraph |
| `adapters/llm_graph/state/chat_investigation.py` | 1 | Chat state TypedDict |
| `adapters/llm_graph/guardrails/aegis.py` | 1 | AEGIS service class |
| `adapters/telegram/formatters/relay.py` | 1 | RELAY service class |
| `adapters/chain/normalizer.py` | 2 | Event normalizer |
| `domain/policies/sentinel.py` | 2 | SENTINEL rules engine |
| `jobs/poll_wallets.py` | 2 | Wallet polling job |
| `jobs/send_alerts.py` | 2 | Alert sender job |
| `adapters/telegram/routers/callbacks.py` | 2 | Alert callback handler |
| `docs/deploy.md` | 3 | Railway deploy guide |
| `docs/admin_playbook.md` | 3 | Admin operations guide |
| `domain/entities/channel_post.py` | 4 | ChannelPost entity |
| `adapters/db/models/channel_post.py` | 4 | ChannelPost ORM model |
| `adapters/db/repositories/channel_post.py` | 4 | ChannelPost repository |
| `adapters/telegram/formatters/channel.py` | 4 | Channel post formatter |
| `jobs/publish_channel.py` | 4 | Channel publish job |
| `alembic/versions/0003_channel_posts.py` | 4 | Migration |
| `adapters/llm_graph/graphs/briefing.py` | 5 | Briefing LangGraph |
| `adapters/llm_graph/state/briefing.py` | 5 | Briefing state TypedDict |
| `jobs/daily_briefing.py` | 5 | Daily briefing job |
| `docs/channel_content_pillars.md` | 5 | Channel content strategy |
| `docs/launch_checklist.md` | 5 | Pre-launch checklist |
| `tests/graphs/test_investigation.py` | 6 | Graph smoke tests |
| `tests/unit/test_plan_gating.py` | 6 | Plan limit tests |
| `tests/unit/test_dedupe.py` | 6 | Dedupe tests |
| `tests/unit/test_schema_validation.py` | 6 | Schema validation tests |
| `scripts/demo.sh` | 6 | Demo script |
| `KNOWN_LIMITATIONS.md` | 6 | Limitations doc |

### Modified Files (11)

| File | Phase | Change |
|------|-------|--------|
| `config/settings.py` | 0, 4 | Add DISCLAIMER_TEXT, channel settings |
| `domain/entities/user.py` | 0 | Add `alerts_enabled` |
| `adapters/db/models/user.py` | 0 | Add `alerts_enabled` column |
| `domain/ports/__init__.py` | 0 | Fix import order |
| `entrypoints/worker.py` | 0, 2, 4, 5 | Remove unused imports, implement, add jobs |
| `adapters/llm_graph/reasoner.py` | 1, 5 | Implement chat, implement briefing |
| `adapters/telegram/routers/chat.py` | 1, 2, 5 | /ask, /decode, /alerts, /briefing |
| `adapters/telegram/routers/admin.py` | 5 | Wallet management commands |
| `adapters/telegram/routers/common.py` | 3 | /status, /upgrade |
| `adapters/llm_graph/guardrails/aegis.py` | 4 | Public filter method |
| `docs/architecture.md` | 0 | Rename WhaleAgent → WhaleDecode |
| `README.md` | 0, 6 | Update description, finalize |
| `__init__.py` | 6 | Version 1.0.0 |
| `pyproject.toml` | 6 | Version 1.0.0 |
| `CHANGELOG.md` | 6 | Final v1.0 entry |

---

## Execution Rules

1. **Do not skip phases** — build in order
2. **DoD gates** — each phase must pass DoD before next phase
3. **No scope creep** — HUNTER/CURATOR, payments, Solana, Ethereum are post-v1.0
4. **PRISM review** — required after Phases 1, 2, 4, 5
5. **QUILL audit** — required after Phases 3, 6
6. **Cost discipline** — single strong model for v1.0, add routing when costs matter
7. **Redis is optional** — no Redis required for any v1.0 feature
8. **Channel auto-publishing** — bot must be channel admin, documented prerequisite

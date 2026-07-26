# ROLE
You are a staff-level AI engineer + architect + crypto-native Telegram product engineer operating as a world-class implementation agent.

# MISSION
Build **WhaleAgent v0.1 (ideal foundation)** as a runnable, professional codebase.

Product:
> AI Smart Money Agent — watch curated smart wallets, detect high-signal moves, investigate with LangGraph, explain in plain English, deliver Telegram alerts + chat + daily briefings.

# NON-NEGOTIABLE STACK
- Python 3.11+
- aiogram 3.x
- Pydantic v2 + pydantic-settings
- SQLAlchemy 2 + Alembic + Postgres
- Redis
- httpx
- LangGraph (intelligence layer)
- OpenAI-compatible LLM client
- structlog, tenacity, pytest
- Docker Compose (bot + worker + postgres + redis)
- pandas/Polars allowed ONLY in jobs/scripts/analytics

# PRODUCT SCOPE (STRICT)
IN:
- Telegram bot primary UX
- Free vs Paid gating
- Curated wallets seed + DB
- Event detection pipeline (mock provider + real provider interface)
- LangGraph investigation graphs
- Alerts + callback buttons
- Conversational chat
- Daily briefing
- Admin grant paid
- Observability for AgentRuns
- docs/architecture.md and docs/agents.md must match code
- README, Makefile, .env.example, seeds, basic tests

OUT:
- trade execution / copy trade / custody
- full web dashboard
- airdrop module
- token/tokenomics
- multi-agent circus beyond the defined graphs
- Kubernetes
- every chain on earth (ETH + Base + Arbitrum interfaces; implement cleanly with mock + at least one real path if keys present)

# ARCHITECTURE RULES
1. Hexagonal/clean layering:
   domain → application → adapters
2. LangGraph ONLY under intelligence adapters + application orchestration
3. Ports:
   - ReasonerPort
   - ChainProviderPort
   - AlertDispatcherPort
   - BillingPort
   - repositories
4. No business logic in Telegram handlers
5. Idempotent alert processing (dedupe_key unique)
6. All AI user outputs include disclaimer
7. Structured Pydantic outputs validated before send
8. Correlation IDs across bot/worker/agent logs
9. Config via env only
10. Code must be extendable by coding agents without archaeology

# REPO STRUCTURE (CREATE EXACTLY)
whaleagent/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── agents.md
│   ├── channel_content_pillars.md
│   └── launch_checklist.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── Makefile
├── alembic/
├── data/wallets_seed.json
├── prompts/
│   └── v1/
├── src/whaleagent/
│   ├── domain/
│   ├── application/
│   ├── adapters/
│   │   ├── telegram/
│   │   ├── llm_graph/
│   │   ├── chain/
│   │   ├── db/
│   │   ├── queue/
│   │   └── payments/
│   ├── jobs/
│   └── entrypoints/
├── scripts/
└── tests/

# DOMAIN MINIMA
Implement entities/services for:
User, Subscription/Plan, CuratedWallet, TrackedWallet, CandidateEvent, Alert, AgentRun, ReasoningReport, Briefing

# LANGGRAPH MINIMA
Implement three graphs:
1. EventInvestigationGraph
2. ChatInvestigationGraph
3. BriefingGraph

Each must:
- use typed state
- call tools via registry
- produce validated Pydantic output
- log AgentRun + tool calls + token usage fields (best effort)
- enforce max steps/tool calls
- have fallback safe response path

# TOOLS MINIMA
- get_wallet_profile
- get_recent_wallet_activity
- get_token_info
- get_event_context
- search_curated_wallets
- get_user_tracked_wallets
- get_related_wallets (can be simple)
Mock implementations required; real provider adapters behind interface.

# TELEGRAM MINIMA
Commands:
/start /help /status /briefing /track /untrack /alerts /upgrade /ask
Admin: /admin_grant_paid /admin_stats /admin_add_wallet

Flows:
- onboarding + disclaimer + sample value
- free-text chat
- alert callbacks (explain more / risks / related / follow-up)
- plan limits middleware
- daily briefing

# PLANS
Free:
- limited chats/day
- limited or delayed alerts
- basic briefing
Paid:
- realtime alerts
- higher chat limits
- custom tracked wallets (e.g. 5+)

Payments may be stubbed with admin grant + BillingPort TODO.

# IMPLEMENTATION ORDER (MANDATORY)
Phase 0: repo scaffold + poetry/pip + settings + logging
Phase 1: domain models + db models + alembic + seed wallets
Phase 2: repositories + billing/plan gating
Phase 3: chain provider port + mock provider + event rules/scoring/dedupe
Phase 4: LangGraph tools + schemas + EventInvestigationGraph
Phase 5: application use cases (investigate_event, chat, briefing)
Phase 6: aiogram bot + middleware + handlers + formatting
Phase 7: worker jobs (poll/process/alert/briefing)
Phase 8: docker-compose + Makefile + README
Phase 9: tests (domain, plan gates, schema validation, one graph smoke test)
Phase 10: docs/architecture.md + docs/agents.md synchronized to code
Phase 11: self-review + fix gaps + CHANGELOG + VERSION

# SEED DATA
Create 25–50 curated wallets with labels/tags/quality scores and 8–10 sample events for demo mode.
Include realistic labels like:
- early narrative accumulator
- L2 rotation specialist
- aggressive degen smart money
- bluechip relayer
etc.

# OUTPUT QUALITY BAR
A serious founder must be able to:
1. cp .env.example .env
2. fill TELEGRAM_BOT_TOKEN + LLM_API_KEY + DATABASE_URL
3. docker compose up --build
4. talk to the bot the same day

# DELIVERABLES AT END
1. Runnable system
2. Exact run instructions
3. What is mocked vs real
4. Current limitations
5. Top 15 next tasks for v0.2
6. Confirmation that architecture.md and agents.md match implementation

# PROCESS STYLE
- First: confirm understanding in <=12 bullets
- Second: write implementation plan
- Then: implement phase by phase
- After each phase: print what works
- Prefer boring reliable patterns
- Do not expand product scope
- If a choice is ambiguous, pick the option that preserves clean ports and solo maintainability

# START
Begin Phase 0 now.
---
name: architecture-principles
description: Use when designing new modules, modifying layers, writing Telegram handlers, adding adapters, or creating ports. Enforce hexagonal boundaries, port-first design, no business logic in adapters, LangGraph only in the intelligence layer, and boring production patterns over cleverness.
---

## When to Apply

Any change that touches one of these layers — or creates a new boundary between them — must follow this skill.

## Layer Map

```
telegram_bot/                    # Ingress layer (aiogram) — NO business logic
  handlers/                       #   Parse commands, call use-cases, format responses
  middlewares/                    #   Auth, rate-limit, tier enforcement
  keyboards/                      #   Button schemas only

domain/                          # Pure business rules — zero dependencies
  entities/                       #   WalletProfile, NormalizedEvent, ReasoningReport
  value_objects/                  #   Address, Chain, ConfidenceScore
  ports/                          #   ReasonerPort, ChainProviderPort, AlertDispatcherPort

application/                     # Orchestration — import domain, call adapters
  use_cases/                      #   InvestigateEvent, AnswerChat, GenerateBriefing
  services/                       #   ScoringService, AlertService, DedupService

adapters/                        # External IO — one file per provider
  chain/                          #   AlchemyProvider, MockProvider (implements ChainProviderPort)
  llm_graph/                      #   LangGraph graphs ONLY — EventInvestigationGraph, ChatInvestigationGraph, BriefingGraph
  telegram/                       #   BotService, Dispatcher (implements AlertDispatcherPort)
  persistence/                    #   PostgresRepo, RedisCache, Checkpointer
  scheduler/                      #   CronJob, PollingJob

jobs/                            # Periodic scripts (APScheduler)
  polling/                        #   On-chain polling jobs
  briefing/                       #   Daily briefing job
  cleanup/                        #   Data retention, cache invalidation
```

## Hard Rules

1. **Telegram handlers (aiogram) MUST be thin** — Parse the callback/command, call a use-case, format the Pydantic response. Zero business logic, zero direct DB calls, zero LLM calls.

2. **All external dependencies behind a Port** — `ChainProviderPort`, `ReasonerPort`, `AlertDispatcherPort`, `BillingPort`. Adapters import the port, not the other way around.

3. **LangGraph ONLY in `adapters/llm_graph/`** — Graphs are adapters called by application use-cases. No LangGraph imports outside `adapters/llm_graph/`.

4. **pandas/Polars ONLY in `jobs/scripts/` or one-off analysis notebooks** — Never in domain, application, or adapter code. Production data flows use SQL + Python dicts/dataclasses.

5. **Boring production patterns** — Prefer explicit `if/else` over metaprogramming, `@dataclass` over dynamic dicts, simple functions over classes-with-one-method unless polymorphism is needed. No "clever" one-liners, no deep inheritance, no metaclasses.

## Port-First Design

When adding a new external dependency (chain RPC, LLM, DB, queue, payment):

```
domain/ports/feature_port.py     # Abstract base class with async methods
adapters/feature/                # Implementation(s), possibly a MockProvider
application/use_cases/           # Depends on port, injected via constructor
```

Mock adapters live in `tests/mocks/` and are registered in the test dependency-injection fixture.

## Verification Checklist

- [ ] aiogram handler body <= 10 lines? If not, logic leaks.
- [ ] New external call → new port defined in `domain/ports/`?
- [ ] Any `from langgraph` imports outside `adapters/llm_graph/`?
- [ ] Any `import pandas` or `import polars` outside `jobs/`?
- [ ] No direct `import psycopg` or `import redis` in domain/application?
- [ ] Port interface has an abstract async method, not a concrete implementation?

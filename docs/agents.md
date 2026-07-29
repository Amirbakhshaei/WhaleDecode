# WhaleDecode — Agent Architecture

## Product Agents

| Agent | Role | Graph | When |
|-------|------|-------|------|
| **SENTINEL** | Event detection | None (deterministic rules) | Polling cycle |
| **ORION** | Event investigation / decode | EventInvestigationGraph | CandidateEvent → Alert |
| **MERIDIAN** | Chat investigation | ChatInvestigationGraph | User `/ask` or `/decode` |
| **LEDGER** | Daily briefing | BriefingGraph | Daily job or `/briefing` |
| **AEGIS** | Guardrails / trust | None (functions) | After every LLM output |
| **RELAY** | Telegram formatter | None (templates) | Before every Telegram send |
| **HUNTER** | Wallet discovery (post-v1.0) | None (batch job) | Nightly |
| **CURATOR** | Wallet scoring (post-v1.0) | None (batch job) | Nightly |

## Agent Descriptions

### SENTINEL
Deterministic detection rules that score raw on-chain events.
- Large buy/sell thresholds
- First interaction with token/protocol
- Accumulation bursts
- Multi-curated-wallet confluence
- Zero LLM — pure rules engine

### ORION
LangGraph-powered event investigation.
- Takes a CandidateEvent
- Enriches with on-chain data (logs, traces, token metadata)
- Produces ReasoningReport (thesis, risk, evidence, confidence)
- Entry point: EventInvestigationGraph

### MERIDIAN
LangGraph-powered chat investigation.
- Takes user query (wallet, token, tx)
- Decides which tools to call
- Answers with evidence + disclaimer
- Entry point: ChatInvestigationGraph

### LEDGER
LangGraph-powered daily briefing.
- Aggregates user's tracked wallet activity
- Synthesizes into daily summary
- Prioritizes high-signal events
- Entry point: BriefingGraph

### AEGIS
Guardrail stage applied to all LLM outputs.
- Validates disclaimer presence
- Scrubs PII from public outputs
- Blocks financial advice patterns
- Enforces risk score bounds
- Can rewrite/block unsafe outputs

### RELAY
Telegram message formatter.
- Converts structured reports to Telegram HTML
- Enforces 4096-char limit
- Truncates/scrolls long content
- Applies consistent formatting (emojis, bold labels)
- Single template with conditional sections

### HUNTER (Post-v1.0)
Candidate wallet discovery job.
- Counterparty expansion from curated wallets
- Repeated early-buy / high-signal heuristics
- Basic spam/bot filters

### CURATOR (Post-v1.0)
Wallet scoring job.
- Explainable score 0-100 per candidate
- reasons[] array for transparency
- Human review before adding to curated set

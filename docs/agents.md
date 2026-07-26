# WhaleAgent Agent System Specification

**Version:** 0.1.0  
**Status:** Draft — Implementation Phase  
**Owner:** WhaleDecode Team  
**Last Updated:** 2025-07-25

---

## 0. Executive Summary (8-Bullet System Overview)

- **Multi-graph LangGraph orchestration** — Three core graphs (`EventInvestigationGraph`, `ChatInvestigationGraph`, `BriefingGraph`) orchestrate event investigation, chat investigation, and daily briefings respectively.
- **Tool-first architecture** — 10+ read-only on-chain/off-chain tools (`get_wallet_profile`, `get_recent_wallet_activity`, `get_token_info`, `get_event_context`, `search_curated_wallets`, `get_user_tracked_wallets`, `get_related_wallets`, `get_basic_market_snapshot`, `retrieve_user_memory`, `write_user_memory`) — zero trade execution, zero private keys.
- **Multi-layer memory architecture** — Global curated knowledge (Postgres), wallet/event memory (Postgres + graph state), user prefs/tracked wallets (Postgres), conversation state (LangGraph checkpoint), all with retention/privacy policies.
- **Three-graph orchestration** — `EventInvestigationGraph` (event → `ReasoningReport` + `alert_worthiness`), `ChatInvestigationGraph` (user question + plan + memory → `ChatAnswer` with plan limits + safety refusals), `BriefingGraph` (top events + market context → `BriefingPackage` for Telegram + bot).
- **Structured output contracts** — Pydantic schemas for every graph output (`ReasoningReport`, `ChatAnswer`, `BriefingPackage`, `AlertWorthiness`, `ChatAnswer`, `BriefingPackage`) + Telegram Markdown formatter with button schemas.
- **Guardrails & safety** — Financial-advice classifier, prompt-injection defenses, address-poisoning cautions, overclaim detector, must-refuse categories (tax/legal/medical advice, trade execution, private keys), low-data graceful degradation.
- **Scoring & alert policy** — `alert_worthiness = f(confidence, novelty, wallet_quality, event_type, market_context)` with free vs paid tiers (delay, depth, volume caps), dedup/fatigue controls.
- **Cost/reliability controls** — Model routing matrix (fast/cheap vs deep/reasoning), timeouts/retries, fallback templates, per-plan budget caps, TTL caching per tool.

---

## 1. Architecture Overview

```mermaid
graph TB
    subgraph Ingress
        Webhook[Webhook: On-chain Events]
        Telegram[Telegram Bot / Webhook]
        Scheduler[Cron: Daily Briefing]
    end

    subgraph Orchestration
        EventGraph[EventInvestigationGraph]
        ChatGraph[ChatInvestigationGraph]
        BriefingGraph[BriefingGraph]
    end

    subgraph Tools
        Tools[Tool Registry<br/>10+ read-only tools]
    end

    subgraph Memory
        PG[(Postgres<br/>Global / Wallet / Event / User)]
        GraphState[LangGraph Checkpoint<br/>Short-term Conversation]
        Cache[Redis Cache<br/>Tool TTL]
    end

    subgraph Output
        Formatter[Telegram Formatter<br/>Markdown + Buttons]
        AlertEngine[Alert Engine<br/>Scoring + Dedup + Tier]
        BriefingOut[Briefing Publisher<br/>Channel + Bot]
    end

    Webhook --> EventGraph
    Telegram --> ChatGraph
    Scheduler --> BriefingGraph

    EventGraph --> Tools
    ChatGraph --> Tools
    BriefingGraph --> Tools

    EventGraph --> Memory
    ChatGraph --> Memory
    BriefingGraph --> Memory

    EventGraph --> AlertEngine
    EventGraph --> Formatter
    ChatGraph --> Formatter
    BriefingGraph --> BriefingOut
```

---

## 2. Core Graphs

### 2.1 EventInvestigationGraph

**Purpose:** Ingest normalized on-chain event + wallet profile → produce structured reasoning + alert worthiness score.

```mermaid
graph LR
    Input[NormalizedEvent + WalletProfile] --> Enrich[Enrichment Nodes\nget_wallet_profile\nget_recent_wallet_activity\nget_token_info\nget_event_context]
    Enrich --> Reason[Reasoning Node\nLLM Reasoning + Tool Calls]
    Reason --> Score[Scoring Node\nconfidence + novelty + wallet_quality + event_type + market_ctx]
    Score --> Report[ReasoningReport]
    Score --> Alert[AlertWorthiness\nscore + bool + tier]
    
    Report --> Formatter[TelegramFormatter]
    Alert --> AlertEngine[AlertEngine\nscore + tier + dedup]
    AlertEngine --> Formatter
```

**Input Schema:**
```python
class EventInvestigationInput(BaseModel):
    event: NormalizedEvent
    wallet_profile: WalletProfile
    market_context: Optional[MarketSnapshot] = None
    user_tier: UserTier = Field(default=UserTier.FREE)
```

**Output Schema:**
```python
class ReasoningReport(BaseModel):
    event_summary: str                          # 1-2 sentences, neutral tone
    wallet_context: WalletContext               # labels, history, notable patterns
    evidence: List[Evidence]                    # each: claim, evidence, source_tool, confidence
    reasoning_chain: List[ReasoningStep]        # step, reasoning, tool_calls, confidence
    risk_factors: List[RiskFactor]              # category, description, severity
    counterarguments: List[str]                 # steel-manned counterpoints
    confidence: ConfidenceScore                 # 0.0-1.0 with calibration bucket
    novelty_score: float                        # 0.0-1.0 vs recent history
    wallet_quality_score: WalletQualityScore    # labels, history, PnL proxy, cluster quality

class AlertWorthiness(BaseModel):
    score: float                                # 0.0-1.0 composite
    alert_worthy: bool                          # threshold per tier
    tier: AlertTier                             # FREE / PRO / WHALE
    reasons: List[str]                          # why triggered / suppressed
    dedup_key: str                              # dedup key for fatigue control
    ttl_seconds: int                            # alert TTL for dedup window
```

**Nodes:**
| Node | Type | Tools Called | Output |
|------|------|--------------|--------|
| `enrich_wallet` | ToolNode | `get_wallet_profile`, `get_recent_wallet_activity` | `WalletProfile` |
| `enrich_token` | ToolNode | `get_token_info` | `TokenInfo` |
| `enrich_event` | ToolNode | `get_event_context` | `EventContext` |
| `reason` | LLMNode (reasoning model) | `get_related_wallets`, `get_basic_market_snapshot`, `retrieve_user_memory` | `ReasoningChain` |
| `score` | ScoringNode | — | `AlertWorthiness` |
| `format_report` | FormatterNode | — | `TelegramMessage` |

---

### 2.2 ChatInvestigationGraph

**Purpose:** Answer user questions with plan-bounded reasoning, memory, and safety guardrails.

```mermaid
graph LR
    Input[UserQuestion + UserPlan + Memory + Refs] --> PlanCheck[PlanValidator\nmax_steps=5, refuse_unsafe]
    PlanCheck -->|valid| Execute[PlanExecutor\nLLM + Tool Loop]
    PlanCheck -->|invalid| Refuse[RefusalNode\nsafe refusal + guidance]
    Execute -->|tools| Tools[ToolNode\nread-only tools]
    Tools --> Execute
    Execute -->|done| Synthesize[SynthesizeNode\ncite evidence, disclaimers]
    Synthesize --> Output[ChatAnswer]
    Refuse --> Output
```

**Input Schema:**
```python
class ChatInvestigationInput(BaseModel):
    user_question: str
    user_plan: Optional[InvestigationPlan] = None
    conversation_memory: ConversationMemory
    referenced_events: List[EventRef] = []
    referenced_wallets: List[WalletRef] = []
    user_tier: UserTier = UserTier.FREE
```

**Output Schema:**
```python
class ChatAnswer(BaseModel):
    answer: str                                    # Telegram-ready markdown
    evidence_citations: List[EvidenceCitation]     # claim -> tool_call -> source
    follow_up_suggestions: List[FollowUpSuggestion] # buttons: explain_more, risks, related_wallets, ask_followup
    disclaimer: Disclaimer                         # short + long variants
    refused: bool
    refusal_reason: Optional[str]
    plan_steps_executed: int
    tool_calls_made: int
    confidence: float
```

**Plan Limits (Enforced by PlanValidator):**
| Tier | Max Steps | Max Tool Calls | Max Depth | Refuse Categories |
|------|-----------|----------------|-----------|-------------------|
| FREE | 3 | 5 | 2 | Trade execution, tax/legal/medical advice, private keys, guaranteed returns |
| PRO | 5 | 10 | 3 | Same + portfolio management |
| WHALE | 8 | 15 | 4 | Same |

**Refusal Categories (Must Refuse):**
- Trade execution / order placement
- Tax, legal, medical advice
- Private key / seed phrase handling
- Guaranteed returns / "guaranteed alpha"
- Wash trading / market manipulation guidance
- Sanctioned entity interaction guidance

---

### 2.3 BriefingGraph

**Purpose:** Produce daily/periodic briefing package from top events + optional market context.

```mermaid
graph LR
    Input[TimeWindow + MarketContext?] --> Select[EventSelector\ntop_k by score + novelty]
    Select --> Enrich[BatchEnrich\nwallet + token + context per event]
    Enrich --> Synthesize[BriefingSynthesizer\nLLM + templates]
    Synthesize --> Package[BriefingPackage\nchannel_version + bot_version]
    Package --> Publish[Publisher\nchannel + bot DM]
```

**Input Schema:**
```python
class BriefingInput(BaseModel):
    time_window: TimeWindow                          # e.g., last 24h
    market_context: Optional[MarketSnapshot] = None
    max_events: int = 10
    user_tier: UserTier = UserTier.FREE              # affects depth/volume
```

**Output Schema:**
```python
class BriefingPackage(BaseModel):
    channel_version: TelegramMessage                 # concise, scannable, buttons
    bot_version: TelegramMessage                     # detailed, expandable
    events_covered: List[EventSummary]
    market_summary: Optional[str]
    generated_at: datetime
    tier: UserTier
```

---

## 3. Tool Specification (v0.1)

| Tool | Description | Args Schema | Response Schema | AuthZ | Read-Only | Mock Status | Failure Modes | Cache TTL |
|------|-------------|-------------|-----------------|-------|-----------|-------------|---------------|-----------|
| `get_wallet_profile` | Enriched wallet profile: labels, tags, PnL proxy, cluster quality, first/last active, top tokens | `WalletProfileArgs(address: Address, chain: Chain)` | `WalletProfile(address, labels, tags, pnl_proxy, cluster_quality, first_seen, last_active, top_tokens, notable_counterparties)` | Public | ✅ | Mock v0 | RPC timeout, label provider down | 1h |
| `get_recent_wallet_activity` | Recent txns (last N/period) with decoded actions, counterparties, values | `WalletActivityArgs(address, chain, limit=50, since?)` | `WalletActivity(txns: List[DecodedTxn])` | Public | ✅ | Mock v0 | RPC lag, decoder gaps | 15m |
| `get_token_info` | Token metadata, liquidity, holders, deployer, verification status | `TokenInfoArgs(address, chain)` | `TokenInfo(address, symbol, name, decimals, verified, liquidity_usd, holder_count, deployer, deploy_tx, creation_time)` | Public | ✅ | Mock v0 | Unverified token, no liquidity | 4h |
| `get_event_context` | Enrich normalized event: block context, related txns, participants, historical precedents | `EventContextArgs(event_id, window_blocks=100)` | `EventContext(block, related_txns, participants, historical_precedents, mev_signals)` | Public | ✅ | Mock v0 | Reorg, missing traces | 30m |
| `search_curated_wallets` | Search curated wallet registry by label, tag, chain, activity | `CuratedWalletSearchArgs(query, labels?, tags?, chain?, min_activity?, limit=20)` | `CuratedWalletSearchResult(wallets: List[CuratedWallet])` | Internal | ✅ | Mock v0 | Stale labels | 24h |
| `get_user_tracked_wallets` | User's tracked wallet list with labels/notes | `UserTrackedWalletsArgs(user_id)` | `UserTrackedWallets(wallets: List[TrackedWallet])` | User-scoped | ✅ | Real | Auth failure | 5m |
| `get_related_wallets` | Simple clustering: deployer, funder, frequent counterparties, same-label cluster | `RelatedWalletsArgs(address, chain, max_degree=2, max_results=20)` | `RelatedWallets(related: List[RelatedWallet])` | Public | ✅ | Mock v0 | Cluster quality varies | 2h |
| `get_basic_market_snapshot` | Top movers, global vol, fear/greed, ETH/BTC price, gas | `MarketSnapshotArgs(chains?)` | `MarketSnapshot(eth_price, btc_price, gas_gwei, top_gainers, top_losers, volume_24h, fear_greed)` | Public | ✅ | Mock v0 | API rate limit | 5m |
| `retrieve_user_memory` | Retrieve user prefs, tracked wallets, conversation facts, preferences | `UserMemoryArgs(user_id, keys?)` | `UserMemory(prefs, tracked_wallets, facts, preferences)` | User-scoped | ✅ | Real | Auth, stale cache | 5m |
| `write_user_memory` | Write user fact/preference (explicit confirm, limited keys) | `WriteMemoryArgs(user_id, key, value, confirm=True)` | `WriteMemoryResult(success, key)` | User-scoped | ❌ (write) | Real | Auth, quota, validation | N/A (write-through) |

**AuthZ Model:**
- `Public` — No auth, rate-limited by IP/key
- `Internal` — Service-to-service token
- `User-scoped` — User JWT required, scoped to user_id

**Caching Strategy:**
- Read-only tools: Redis TTL per table above
- Write tools: Write-through to Postgres, invalidate user cache keys
- Cache keys: `tool:{name}:{hash(args)}`

**Failure Modes Handling:**
- Timeout → Retry (2x, exponential backoff) → Fallback to cached (stale-ok) → ToolError
- Auth failure → AuthError → Graph handles as refusal
- Data unavailable → ToolError with `data_unavailable=True` → Graph degrades gracefully (lower confidence)

---

## 4. Memory Architecture

```mermaid
graph TB
    subgraph Postgres[PostgreSQL - Persistent]
        GlobalKnowledge[Global Curated Knowledge\nlabels, token metadata, cluster defs]
        WalletMemory[Wallet Notes/Labels/Events\nper address + chain]
        EventMemory[Event Memory\nreasoning reports, scores, feedback]
        UserPrefs[User Preferences\nprefs, tracked wallets, tier]
        ConversationLog[Conversation Log\nfull history for audit]
    end

    subgraph GraphState[LangGraph Checkpoint - Short-term]
        ConvState[Conversation State\ncurrent plan, tool results, reasoning trace]
        BriefingState[Briefing State\nevents selected, drafts]
    end

    subgraph Redis[Redis - Cache]
        ToolCache[Tool Response Cache\nTTL per tool]
        UserCache[User Memory Cache\n5m TTL]
    end
```

### Memory Layers

| Layer | Storage | Retention | Privacy | Access Pattern |
|-------|---------|-----------|---------|----------------|
| Global Curated Knowledge | Postgres | Permanent | Public/Internal | Read-heavy, cached |
| Wallet Notes/Labels | Postgres | Permanent (user) / 2yr (internal) | User-private / Internal | Per-wallet lookup |
| Event Memory | Postgres | 2 years | Internal | Event_id lookup, time-window scans |
| User Preferences/Tracked | Postgres | User lifetime + 30d | User-private | User_id lookup, cached 5m |
| Conversation Short-term | LangGraph Checkpoint (Postgres) | 30 days | User-private | Thread_id checkpoint |

### Privacy Rules
- User private data (tracked wallets, notes, conversation) → User-scoped, encrypted at rest, deleted 30d after account deletion
- Internal curated data → Internal access only, no PII
- On-chain data → Public, cached per TTL
- No PII in logs, metrics, or traces

---

## 5. Prompts

### 5.1 System Prompt Principles
1. **Evidence-first** — Every claim cites a tool call or explicit "no data"
2. **Neutral tone** — No hype, no "alpha", no "gem", no "moon", no "undervalued"
3. **Uncertainty calibrated** — Explicit confidence, explicit unknowns
4. **Risk-forward** — Lead with risks, not upside
5. **User-sovereign** — User decides; we inform, never recommend trades
6. **Plan-bounded** — Chat graph refuses to exceed plan limits
7. **Privacy-respecting** — Never log private keys, never ask for them

### 5.2 Telegram Crypto Audience Style Guide
| Do | Don't |
|----|-------|
| "Wallet 0x123... accumulated 500k USDC from Binance over 48h" | "Whale accumulating massive USDC position 🐋" |
| "Token XYZ has $12k liquidity, deployer holds 40% supply" | "XYZ is a hidden gem with huge potential 💎" |
| "No on-chain evidence of insider accumulation" | "Smart money is secretly loading bags" |
| "Confidence: 0.65 (moderate) — limited txn history" | "High confidence this will 10x" |
| "Risks: low liquidity, deployer concentration, no audit" | "Minimal risk, huge upside" |

### 5.3 Anti-Hype Lexicon (Banned Phrases)
| Banned | Alternative |
|--------|-------------|
| "gem", "hidden gem", "moon", "moonshot" | "token with X characteristics" |
| "alpha", "alpha leak", "insider alpha" | "on-chain signal", "observable pattern" |
| "smart money", "whale" (as noun) | "wallet with X characteristics", "large holder" |
| "loading bags", "accumulating" (uncertain) | "net buyer of X over period Y" |
| "undervalued", "underpriced" | "trading below X metric" |
| "guaranteed", "certain", "will" | "possible", "probable", "evidence suggests" |
| "rug pull proof", "safe" | "no audit found", "deployer holds X%" |

### 5.4 Disclaimer Language
**Short (inline, every message):**
> Not financial advice. On-chain data only. DYOR.

**Long (detailed reports, briefings):**
> This analysis is based solely on publicly available on-chain data and does not constitute financial, investment, tax, or legal advice. On-chain data can be incomplete, mislabeled, or manipulated. Past behavior does not predict future results. Never share private keys. Consult qualified professionals for financial decisions.

### 5.5 Prompt Packing Rules
| Context | Included In | Token Budget |
|---------|-------------|--------------|
| System prompt | All graphs | ~2k tokens |
| User tier + prefs | All graphs | ~200 tokens |
| Conversation memory (last 6 turns) | ChatGraph | ~2k tokens |
| Referenced events/wallets | ChatGraph, EventGraph | ~3k tokens |
| Tool results (current turn) | Current turn only | ~4k tokens |
| Global knowledge snippets | As retrieved | ~1k tokens |

### 5.6 Versioning & Change Checklist
**Scheme:** `prompts/v{major}/graph_name/prompt_name_v{minor}.jinja2`

**Change Checklist (PR required):**
- [ ] Schema version bumped if output schema changes
- [ ] Eval dataset updated with 5+ new examples
- [ ] Offline eval passes (schema validity, evidence grounding, hype penalty)
- [ ] Online shadow test (10% traffic, 24h)
- [ ] Rollback plan documented

---

## 6. Guardrails & Safety

### 6.1 Financial Advice Classifier
**Rules-based + LLM classifier** — Runs on every LLM output before formatting.

| Category | Detection | Action |
|----------|-----------|--------|
| Explicit trade recommendation | "buy", "sell", "long", "short", "enter", "exit" + token + price/target | Strip + add disclaimer |
| Price target / prediction | "$X by Y date", "will reach", "target" | Strip + disclaimer |
| Portfolio allocation | "allocate X%", "position size" | Refuse + redirect |
| Guaranteed returns | "guaranteed", "risk-free", "sure thing" | Hard refuse |

### 6.2 Prompt Injection Defenses
- System prompt immutable per graph version
- User input sanitized: strip `<|im_start|>`, `<|im_end|>`, `<<SYS>>`, `### Instruction`
- Tool results wrapped in structured blocks, never raw-injected
- Plan validation rejects instructions to "ignore instructions", "output only", etc.

### 6.3 Address Poisoning Cautions
- `get_wallet_profile` and `get_recent_wallet_activity` flag `address_poisoning_risk: true` if:
  - Recent dust transfers from similar-looking addresses
  - First interaction with new counterparty matching user's address pattern
- Formatter adds ⚠️ badge + tooltip on affected addresses

### 6.4 Overclaim Detector
**Heuristics (runs post-LLM, pre-format):**
- Confidence > 0.9 with < 3 evidence citations → Downgrade confidence
- Claims "no risk" / "zero risk" → Flag, inject risk section
- Single-source claims presented as fact → Add "single source" qualifier
- Contradiction between evidence and claim → Flag contradiction

### 6.5 Must-Refuse Categories (Hard Refusal)
| Category | Response Template |
|----------|-------------------|
| Trade execution | "I can't execute trades or place orders. I can only analyze on-chain data." |
| Tax/legal/medical advice | "I'm not qualified to provide tax/legal/medical advice. Consult a professional." |
| Private keys/seeds | "Never share private keys or seed phrases. I cannot help with wallet recovery." |
| Guaranteed returns | "No investment returns are guaranteed. On-chain analysis shows patterns, not promises." |
| Sanctioned entities | "I cannot assist with interactions involving sanctioned entities." |
| Market manipulation | "I cannot provide guidance on wash trading, spoofing, or market manipulation." |

### 6.6 Low Data Graceful Degradation
| Data Availability | Confidence Cap | Output Adjustment |
|-------------------|----------------|-------------------|
| Full (wallet + token + event + market) | 1.0 | Full report |
| Wallet + event only | 0.75 | Add "limited token/market context" note |
| Event only | 0.5 | "Limited context — wallet profile unavailable" |
| Minimal (event only, no enrichment) | 0.3 | "Insufficient data for meaningful analysis" + raw event only |

---

## 7. Scoring & Alert Policy

### 7.1 Alert Worthiness Formula
```python
def calculate_alert_worthiness(
    confidence: float,           # 0.0-1.0 from reasoning
    novelty_score: float,        # 0.0-1.0 vs 30d history
    wallet_quality: WalletQualityScore,  # 0.0-1.0 composite
    event_type_weight: float,    # per event type table
    market_context_boost: float  # -0.1 to +0.1
) -> AlertWorthiness:
    base = (
        0.30 * confidence +
        0.25 * novelty_score +
        0.25 * wallet_quality.composite +
        0.15 * event_type_weight +
        0.05 * market_context_boost
    )
    # Tier thresholds
    tier_thresholds = {
        AlertTier.FREE: 0.70,
        AlertTier.PRO: 0.55,
        AlertTier.WHALE: 0.40
    }
    return AlertWorthiness(
        score=base,
        alert_worthy=base >= tier_thresholds[user_tier],
        tier=user_tier,
        reasons=build_reasons(...),
        dedup_key=f"{event_type}:{wallet_address}:{event_hash[:8]}",
        ttl_seconds=TIER_TTL[user_tier]
    )
```

### 7.2 Event Type Weights
| Event Type | Weight | Rationale |
|------------|--------|-----------|
| Large stablecoin transfer (>100k) | 0.8 | Low noise, high signal |
| New token deployment + deployer activity | 0.85 | High novelty, high risk |
| Whale accumulation (net buyer >500k) | 0.75 | Actionable pattern |
| Exchange withdrawal/whale deposit | 0.7 | Mixed signal |
| MEV / sandwich / arb | 0.4 | High noise |
| Routine transfer <10k | 0.2 | Low signal |
| Dust / spam | 0.05 | Noise |

### 7.3 Tier Differences
| Dimension | FREE | PRO | WHALE |
|-----------|------|-----|-------|
| Alert threshold | 0.70 | 0.55 | 0.40 |
| Alert delay | 30 min | 5 min | Real-time |
| Report depth | Summary only | Full reasoning | Full + related wallets |
| Daily alert cap | 5 | 50 | Unlimited |
| Briefing depth | Top 3 | Top 10 | Top 20 + custom |

### 7.4 Dedup / Fatigue Control
- **Dedup key:** `{event_type}:{wallet}:{event_hash_prefix}`
- **TTL:** FREE=4h, PRO=2h, WHALE=30m
- **Frequency cap per wallet:** FREE=2/day, PRO=10/day, WHALE=50/day
- **User-level fatigue:** If user dismisses 3 alerts from same wallet in 24h → auto-mute 24h

---

## 8. Formatter Contract

### 8.1 Telegram Markdown Rules
- **MarkdownV2** escaping: `_ * [ ] ( ) ~ ` > # + - = | { } . !`
- **Character limits:** Message ≤ 4096 chars, Caption ≤ 1024 chars
- **Scannable layout:** Header → Key metrics (bullet) → Reasoning (collapsed) → Buttons

### 8.2 Message Templates

**Event Alert (Channel Version — Concise):**
```
🔔 *Whale Alert* | `0x123...abc` | `USDC` | $2.4M

• *Action:* Net buyer — 2.4M USDC from Binance (3 txns, 4h)
• *Wallet:* "Binance Hot Wallet 14" • Cluster quality: 0.92
*History:* Net buyer 12/14 days • Top 5% USDC accumulator
• *Token:* USDC • $1.00 • Liq: $4.2B • Verified ✅
• *Context:* ETH $3,240 • Gas 12 gwei • Fear/Greed: 62 (Greed)
• *Confidence:* 0.78 (high) • Novelty: 0.65

[🔍 Explain More] [⚠️ Risks] [🔗 Related Wallets] [❓ Ask Follow-up]
```

**Chat Answer (Bot Version — Detailed):**
```
**Analysis: 0x123...abc USDC Activity**

*Summary:* Wallet 0x123...abc (labeled "Binance Hot Wallet 14") received 2.4M USDC from Binance over 3 transactions in the last 4 hours. Net flow: +2.4M USDC.

*Wallet Context:*
• Labels: Centralized Exchange, Binance, Hot Wallet
• Cluster quality: 0.92/1.0 (high-confidence CEX cluster)
• 30-day net USDC flow: +18.7M (consistent accumulator)
• Notable counterparties: Binance, Coinbase, Wintermute

*Evidence:*
1. `get_recent_wallet_activity` — 3 incoming USDC txns from Binance deposit addresses (0x283..., 0x504..., 0x8a1...) totaling 2.4M USDC [confidence: 0.95]
2. `get_wallet_profile` — Cluster quality 0.92, CEX label confirmed by 3 label providers [confidence: 0.90]
3. `get_token_info` — USDC verified, $4.2B liquidity, 1.2M holders [confidence: 1.0]

*Risks:*
• CEX hot wallet flows often reflect user deposits/withdrawals, not proprietary trading
• No evidence of directional betting — could be routine custody operations
• USDC is stablecoin; accumulation ≠ price speculation

*Counterarguments:*
• Could represent institutional custody inflow
• Consistent pattern over 14 days suggests systematic operation

*Confidence:* 0.78 (High) — Strong wallet labels, clear txn evidence, but intent ambiguous

Not financial advice. On-chain data only. DYOR.

[🔍 Explain More] [⚠️ Risks] [🔗 Related Wallets] [❓ Ask Follow-up]
```

### 8.3 Button Schemas
```python
class AlertButtons(BaseModel):
    explain_more: ButtonCallback = "explain_more:{event_id}"
    risks: ButtonCallback = "risks:{event_id}"
    related_wallets: ButtonCallback = "related_wallets:{wallet_address}"
    ask_followup: ButtonCallback = "ask_followup:{thread_id}"

class ChatButtons(BaseModel):
    explain_more: ButtonCallback = "explain_more:{claim_id}"
    risks: ButtonCallback = "risks:{claim_id}"
    related_wallets: ButtonCallback = "related_wallets:{wallet_address}"
    ask_followup: ButtonCallback = "ask_followup:{thread_id}"
```

---

## 9. Evals & Quality Bar

### 9.1 Good vs Bad Output Examples

**Good (Event Alert):**
```
🔔 Whale Alert | 0x123...abc | USDT | $1.2M
• Action: Net seller — 1.2M USDT to Binance (2 txns, 1h)
• Wallet: "Wintermute OTC" • Cluster: 0.88
• History: Net seller 8/10 days • Large USDT recycler
• Confidence: 0.82 • Novelty: 0.45
[Explain] [Risks] [Related] [Ask]
```
*Why good:* Neutral, evidence-cited, risk-forward, scannable, buttons.

**Bad (Event Alert):**
```
🚨 WHALE ALERT 🚨 0x123...abc DUMPING $1.2M USDT TO BINANCE!! 📉🐋
This massive whale is dumping bags — huge sell pressure incoming!
Smart money exiting — this could crash USDT peg! 💥
Confidence: 100% 💯
[Buy Dip] [Sell Now] [Moon Bag]
```
*Why bad:* Hype language, unverified claims ("dumping bags", "smart money"), fake confidence, dangerous buttons, no evidence.

**Good (Chat Answer):**
```
**Question:** "Is 0x123...abc a smart money wallet?"

**Answer:** Wallet 0x123...abc (labeled "Wintermute OTC") shows patterns consistent with professional market making:
• 30-day volume: $420M • Win rate (proxy): 0.58 • Sharpe (proxy): 1.2
• Cluster quality: 0.88 • Consistent counterparty set
• No evidence of insider timing — flows correlate with public market conditions

*Evidence:* [1] get_wallet_profile, [2] get_recent_wallet_activity, [3] get_related_wallets
*Confidence:* 0.72 (moderate) — Proxy metrics only, no PnL verification
*Risks:* Labels from 2/3 providers agree; PnL proxy imperfect

Not financial advice. On-chain data only. DYOR.
```

**Bad (Chat Answer):**
```
Yes! 0x123...abc is 100% smart money — Wintermute's main wallet! 🧠💰
They've made 58% returns consistently and always buy the bottom.
You should copy their trades for guaranteed alpha 📈
[Copy Trade] [Follow Wallet] [Get Alerts]
```
*Why bad:* Guaranteed returns claim, unverified PnL, trade execution CTA, hype language.

### 9.2 Offline Eval Dataset Format
```jsonl
{"input": {"event": {...}, "wallet_profile": {...}}, "expected_output": {"reasoning_report": {...}, "alert_worthiness": {...}}, "metadata": {"tier": "PRO", "event_type": "large_transfer"}}
{"input": {"user_question": "Is 0x123 smart money?", "user_plan": {...}, "memory": {...}}, "expected_output": {"answer": "...", "evidence_citations": [...], "refused": false}, "metadata": {"tier": "FREE"}}
```

### 9.3 Online Review Workflow (First 100 Alerts)
1. **Shadow mode** — Graph runs, outputs logged, no user delivery
2. **Human review** — 3 reviewers score each: schema_valid, evidence_grounded, hype_penalty, usefulness, contradiction
3. **Threshold** — ≥4/5 avg on all dims → graduate to 10% traffic
4. **Gradual rollout** — 10% → 50% → 100% over 7 days if metrics hold

### 9.4 Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Schema validity | 100% | Automated check |
| Evidence grounding | ≥0.85 | Citation recall vs claims |
| Hype penalty | 0 violations | Classifier + human spot |
| Usefulness (human) | ≥4.0/5.0 | Reviewer rating |
| Contradiction rate | <0.02 | Claim vs evidence check |
| Cost per accepted alert | <$0.10 | LLM tokens / accepted alert |

---

## 10. Cost & Reliability Controls

### 10.1 Model Routing Matrix
| Node / Task | Model | Max Tokens | Timeout | Retry |
|-------------|-------|------------|---------|-------|
| Event enrichment (tool calls) | gpt-4o-mini / gemini-1.5-flash | 4k | 10s | 2x |
| Reasoning (EventGraph) | gpt-4o / claude-3.5-sonnet | 16k | 30s | 1x |
| Scoring | Deterministic fn | — | 1s | — |
| Chat plan validation | gpt-4o-mini | 2k | 5s | 2x |
| Chat execution | gpt-4o / claude-3.5-sonnet | 16k | 45s | 1x |
| Chat synthesis | gpt-4o-mini | 4k | 10s | 2x |
| Briefing synthesis | gpt-4o / claude-3.5-sonnet | 32k | 60s | 1x |
| Formatting | gpt-4o-mini | 2k | 5s | 2x |
| Guardrails (classifier) | gpt-4o-mini / local | 1k | 2s | 3x |

### 10.2 Timeouts & Retries
- Tool calls: 10s timeout, 2 retries (exponential backoff 1s, 2s)
- LLM calls: Per matrix above, 1 retry
- Graph overall: 120s hard timeout → fallback template

### 10.3 Fallback Templates
**EventGraph failure:**
> "⚠️ Analysis temporarily unavailable for event {event_id}. Raw event: {summary}. Try again in a few minutes or ask the bot for details."

**ChatGraph failure:**
> "⚠️ I couldn't complete that analysis. Here's what I found so far: {partial_evidence}. You can ask a follow-up or try a simpler question."

**BriefingGraph failure:**
> "📊 Daily briefing delayed. Top events: {event_list}. Full briefing coming shortly."

### 10.4 Budget Caps (Per User / Day)
| Tier | Daily Token Budget | Daily Tool Call Budget | Alert Budget |
|------|-------------------|------------------------|--------------|
| FREE | 50k | 100 | 5 |
| PRO | 500k | 1,000 | 50 |
| WHALE | 2M | 5,000 | Unlimited |

### 10.5 Caching Policy
| Cache Key Pattern | TTL | Invalidation |
|-------------------|-----|--------------|
| `tool:get_wallet_profile:{addr}:{chain}` | 1h | On label update webhook |
| `tool:get_token_info:{addr}:{chain}` | 4h | On deploy update |
| `tool:get_basic_market_snapshot:{chains}` | 5m | Time-based |
| `user_memory:{user_id}` | 5m | On write_user_memory |
| `briefing:{date}:{tier}` | 24h | On regen |

---

## 11. Implementation Map

```
whaledecode/
├── graphs/
│   ├── __init__.py
│   ├── event_investigation.py      # EventInvestigationGraph
│   ├── chat_investigation.py       # ChatInvestigationGraph
│   └── briefing.py                 # BriefingGraph
├── nodes/
│   ├── __init__.py
│   ├── enrichment.py               # Enrichment nodes
│   ├── reasoning.py                # Reasoning LLM nodes
│   ├── scoring.py                  # Scoring nodes
│   ├── validation.py               # PlanValidator, Guardrails
│   ├── synthesis.py                # Synthesis nodes
│   └── formatting.py               # TelegramFormatter
├── tools/
│   ├── __init__.py
│   ├── registry.py                 # ToolRegistry
│   ├── wallet.py                   # get_wallet_profile, get_recent_wallet_activity
│   ├── token.py                    # get_token_info
│   ├── event.py                    # get_event_context
│   ├── curated.py                  # search_curated_wallets
│   ├── user.py                     # get_user_tracked_wallets, retrieve_user_memory, write_user_memory
│   ├── network.py                  # get_related_wallets, get_basic_market_snapshot
│   └── base.py                     # BaseTool, ToolResult, ToolError
├── schemas/
│   ├── __init__.py
│   ├── events.py                   # NormalizedEvent, EventContext
│   ├── wallet.py                   # WalletProfile, WalletActivity
│   ├── token.py                    # TokenInfo
│   ├── reports.py                  # ReasoningReport, AlertWorthiness, ChatAnswer, BriefingPackage
│   ├── tools.py                    # Tool args/response schemas
│   ├── memory.py                   # UserMemory, ConversationMemory
│   └── formatting.py               # TelegramMessage, ButtonCallback
├── prompts/
│   └── v1/
│       ├── event_investigation/
│       │   ├── system.jinja2
│       │   ├── reasoning.jinja2
│       │   └── scoring.jinja2
│       ├── chat_investigation/
│       │   ├── system.jinja2
│       │   ├── plan_validation.jinja2
│       │   ├── reasoning.jinja2
│       │   └── synthesis.jinja2
│       └── briefing/
│           ├── system.jinja2
│           ├── synthesis.jinja2
│           └── channel_template.jinja2
├── memory/
│   ├── __init__.py
│   ├── postgres.py                 # PostgresMemoryStore
│   ├── graph_checkpoint.py         # LangGraph PostgresSaver
│   └── redis_cache.py              # ToolCache, UserCache
├── guardrails/
│   ├── __init__.py
│   ├── financial_advice.py         # Classifier + stripper
│   ├── injection.py                # Prompt injection defenses
│   ├── overclaim.py                # Overclaim detector
│   └── refusal.py                  # Refusal templates
├── scoring/
│   ├── __init__.py
│   ├── alert_worthiness.py         # Scoring function
│   ├── event_weights.py            # Event type weights
│   └── tier_policy.py              # Tier thresholds
├── formatting/
│   ├── __init__.py
│   ├── telegram.py                 # MarkdownV2 formatter
│   ├── templates.py                # Message templates
│   └── buttons.py                  # Button schemas
├── evals/
│   ├── __init__.py
│   ├── dataset.py                  # EvalDataset loader
│   ├── offline.py                  # Offline evaluator
│   ├── online.py                   # Online shadow evaluator
│   └── metrics.py                  # Metric calculators
├── config/
│   ├── __init__.py
│   ├── models.py                   # Model routing config
│   ├── tiers.py                    # Tier definitions
│   └── caching.py                  # Cache TTL config
└── main.py                         # Entry points: webhook, bot, scheduler
```

### 11.1 Coding Standards for Adding a Tool
1. **Define schemas** in `schemas/tools.py` — `ToolNameArgs`, `ToolNameResult`
2. **Implement tool** in `tools/{domain}.py` — inherit `BaseTool`, implement `async def execute(args) -> ToolResult`
3. **Register** in `tools/registry.py` — `ToolRegistry.register(GetWalletProfileTool())`
4. **Add mock** in `tools/mocks.py` for v0 development
5. **Write eval cases** in `evals/dataset/{tool_name}.jsonl`
6. **Add to graph** where needed — import from registry, not directly
7. **Update caching config** in `config/caching.py`
8. **Run typecheck + lint + offline eval** before PR

---

## 12. Instructions for Future Coding Agents

### 12.1 Safe Modification Protocol
1. **Read first** — Read the graph, node, tool, prompt, or schema you're modifying + its tests
2. **Minimal diff** — Change one thing at a time; prefer new node/tool/prompt version over editing in place
3. **Schema version bump** — If output schema changes, bump minor version in schema + prompt version
4. **Run evals** — `make eval-offline` must pass before PR
5. **Shadow test** — Deploy to 10% traffic, monitor 24h metrics
6. **Rollback ready** — Previous graph version deployed alongside; feature flag for instant rollback

### 12.2 Required Tests Before Prompt/Graph Changes
| Change Type | Required Tests |
|-------------|----------------|
| System prompt | Offline eval (10 cases) + hype classifier pass |
| Reasoning prompt | Offline eval (20 cases) + evidence grounding ≥0.85 |
| Tool addition | Unit test + mock + eval dataset (5 cases) |
| Scoring formula | Golden dataset (50 events) + tier threshold verification |
| Formatter template | Render test (5 variants) + char limit check + button schema valid |
| Guardrail rule | Adversarial test set (20 injections) + refusal accuracy ≥0.95 |

### 12.3 Definition of Done
- [ ] Typecheck passes (`mypy --strict`)
- [ ] Lint passes (`ruff check .`)
- [ ] Unit tests pass (`pytest tests/unit`)
- [ ] Offline eval passes thresholds
- [ ] Integration test passes (`pytest tests/integration`)
- [ ] Docs updated (`docs/agents.md` if architecture changes)
- [ ] Changelog entry
- [ ] Deployed to staging + shadow verified

---

## 13. Open TODOs & Research Questions

| ID | Area | Question | Status |
|----|------|----------|--------|
| R-01 | Wallet Clustering | How to validate cluster quality without ground truth? | Research |
| R-02 | Label Confidence | How to combine multi-source labels into calibrated confidence? | Research |
| R-03 | Novelty Scaling | How to compute novelty at scale (10k+ events/day) without full pairwise? | Design |
| R-04 | PnL Proxy | Can we build a credible on-chain PnL proxy without CEX data? | Research |
| R-05 | Prompt Injection | Formal red-team evaluation of current defenses | Planned |
| R-06 | Multi-chain Context | How to normalize cross-chain event context for reasoning? | Design |
| R-07 | User Memory Privacy | Differential privacy for aggregated user pattern learning? | Research |
| R-08 | Cost Optimization | Optimal model routing for reasoning vs tool-calling nodes | Experiment |
| R-09 | Alert Fatigue ML | Learn per-user fatigue model from dismiss/engage signals | Backlog |
| R-10 | Briefing Personalization | Per-user briefing ranking vs global ranking | Backlog |

---

## 14. Maintenance Rules

1. **This document is the source of truth** for agent behavior. Code must match specs here.
2. **Version bump** — Any behavioral change → bump `docs/agents.md` version + date
3. **Eval gate** — No graph/prompt change merges without offline eval pass
4. **Drift detection** — Weekly: sample 20 production outputs, score against rubric
5. **Schema registry** — All Pydantic schemas in `schemas/` — single source of truth
6. **Prompt registry** — All prompts in `prompts/v{major}/` — versioned with graph
7. **Tool registry** — All tools registered in `tools/registry.py` — no direct imports
8. **Incident log** — Every production issue → add to `INCIDENTS.md` with root cause + fix
9. **Dependency updates** — Monthly: review model versions, tool API versions, schema compatibility

---

## 15. Persona Registry — OpenCode Agent Personas

**Location**: `.opencode/agents/` (markdown agent definitions) + `prompts/v1/agents/` (canonical prompt files)

**Version**: 1.0  
**Status**: Active — Implemented  
**Last Updated**: 2026-07-25

---

### 15.1 Overview

WhaleAgent defines 12 agent personas organized into four layers:

| Layer | Personas | Purpose |
|-------|----------|---------|
| **Operating Modes** (Tab-switchable) | ATLAS, FORGE | Primary agents for architect vs implementer workflows |
| **Quality Gates** (Tab-switchable) | PRISM, QUILL | Review and audit |
| **Learning & Research** (@-invocable) | MENTOR, SCOUT | Teaching and dependency research |
| **WhaleAgent System** (@-invocable) | SENTINEL, ORION, MERIDIAN, LEDGER, AEGIS, RELAY | System-level agent roles matching the three-graph architecture |

**Constitution**: All personas operate under the [WhaleAgent OpenCode Constitution](#151-whaledecode-opencode-constitution).

---

### 15.2 WhaleAgent OpenCode Constitution

```
1) Accuracy over speed claims
2) Architecture.md and agents.md are law
3) LangGraph = intelligence brain only
4) No custody/execution/financial-advice features
5) Prefer small auditable diffs
6) Prove with tests/shell when behavior changes
7) Explain uncertainty explicitly
8) Protect solo-founder maintainability
```

---

### 15.3 Mode A — ATLAS (Architect)

| Field | Value |
|-------|-------|
| **Role** | OpenCode Architect |
| **Type** | Primary agent (Tab-switchable) |
| **Prompt** | `prompts/v1/agents/atlas.txt` |
| **MCPs** | filesystem, memory, sequential-thinking, fetch, git |
| **Allowed** | docs, ADRs, diagrams, interfaces |
| **Denied** | Large drive-by code rewrites |
| **Color** | `#4A90D9` |
| **Temperature** | 0.1 |

**System Prompt Summary**: Design first. Protect hexagonal boundaries. LangGraph is intelligence-only behind ports. Prefer boring, replaceable, VPS-friendly architecture. Output: decisions, diagrams, interfaces, ADRs, and an implementation plan for FORGE. Do not dump large feature code unless asked.

---

### 15.4 Mode B — FORGE (Implementer)

| Field | Value |
|-------|-------|
| **Role** | OpenCode Implementer |
| **Type** | Primary agent (Tab-switchable) |
| **Prompt** | `prompts/v1/agents/forge.txt` |
| **MCPs** | All S-tier (filesystem, git, shell, fetch, sequential-thinking, memory, sqlite) + postgres |
| **Allowed** | Code, tests, migrations |
| **Rule** | Small vertical slices only |
| **Color** | `#50C878` |
| **Temperature** | 0.3 |

**System Prompt Summary**: Build the next vertical slice against architecture.md and agents.md. Keep handlers thin, domain clean, LangGraph behind ReasonerPort. Write tests for behavior you add. After changes: show how to run/verify. No product scope expansion.

---

### 15.5 Mode C — PRISM (Reviewer / Accuracy)

| Field | Value |
|-------|-------|
| **Role** | OpenCode Reviewer |
| **Type** | Primary agent (Tab-switchable) |
| **Prompt** | `prompts/v1/agents/prism.txt` |
| **MCPs** | git, filesystem, shell, sequential-thinking |
| **Job** | Review diff only, find bugs/boundary violations/missing tests |
| **Color** | `#FF6B6B` |
| **Temperature** | 0.1 |

**System Prompt Summary**: Review the current diff like a principal engineer. Priority: correctness, architecture boundaries, async/jobs safety, plan gating, alert idempotency, prompt/tool safety, missing tests. Output findings by severity with file references. Do not redesign the product. Do not praise filler.

---

### 15.6 Mode D — QUILL (Auditor / Explainability)

| Field | Value |
|-------|-------|
| **Role** | OpenCode Auditor |
| **Type** | Primary agent (Tab-switchable) |
| **Prompt** | `prompts/v1/agents/quill.txt` |
| **MCPs** | git, filesystem, memory, shell |
| **Job** | Produce audit reports, risk notes, "what changed and why", architecture compliance |
| **Color** | `#9B59B6` |
| **Temperature** | 0.1 |

**System Prompt Summary**: Produce an explainable audit of the latest changes. Use git diff/log and code reading. Report: intent, files, architecture impact, product impact, risks, verification, residual risks, compliance with architecture.md/agents.md. Assume the founder wants to learn and stay in control.

---

### 15.7 MENTOR (Learning Coach)

| Field | Value |
|-------|-------|
| **Role** | OpenCode Learning Coach |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/mentor.txt` |
| **MCPs** | filesystem, git, shell, sqlite, webfetch |
| **Job** | Teach by tracing real code paths, running examples |
| **Color** | `#F39C12` |
| **Temperature** | 0.5 |

**System Prompt Summary**: Teach by tracing real code paths, running examples, and contrasting amateur vs pro patterns. Use `/explain`, `/why`, `/trace`, `/quiz`, `/amateur-check` style responses. Always point to exact files and runtime behavior.

---

### 15.8 SCOUT (Research Agent)

| Field | Value |
|-------|-------|
| **Role** | OpenCode Research Agent |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/scout.txt` |
| **MCPs** | filesystem, shell, git, webfetch, websearch |
| **Job** | Verify library APIs, version constraints, recommended patterns |
| **Color** | `#1ABC9C` |
| **Temperature** | 0.2 |

**System Prompt Summary**: Verify library APIs, version constraints, and recommended patterns for aiogram, LangGraph, SQLAlchemy, Pydantic, Redis, Postgres, Docker. Use docs/fetch/shell inspection. Distinguish known vs assumed. Return implementation guidance with sources/confidence.

---

### 15.9 SENTINEL (Deterministic Detection)

| Field | Value |
|-------|-------|
| **Role** | WhaleAgent detection stage |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/sentinel.txt` |
| **Job** | Rules-based event scoring, zero LLM |
| **Color** | `#E74C3C` |
| **Temperature** | 0.0 |

**System Prompt Summary**: Deterministic detection only. Rules-based classification of on-chain events. No LLM reasoning, no probabilistic output. Output structured CandidateEvent with deterministic score. Every detection must be explainable by citing the exact rule matched.

---

### 15.10 ORION (EventInvestigationGraph Investigator)

| Field | Value |
|-------|-------|
| **Role** | WhaleAgent event investigator |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/orion.txt` |
| **Job** | Investigate on-chain events via LangGraph |
| **Color** | `#2E86C1` |
| **Temperature** | 0.2 |

**System Prompt Summary**: EventInvestigationGraph investigator. Enrich (wallet, token, event context) → Reason (LLM + tool loop) → Score (deterministic alert_worthiness) → Report (ReasoningReport). Evidence-first, neutral tone, risk-forward. Every claim must cite a tool call.

---

### 15.11 MERIDIAN (ChatInvestigationGraph Concierge)

| Field | Value |
|-------|-------|
| **Role** | WhaleAgent chat concierge |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/meridian.txt` |
| **Job** | Answer user questions with plan-bounded reasoning |
| **Color** | `#27AE60` |
| **Temperature** | 0.3 |

**System Prompt Summary**: ChatInvestigationGraph concierge. PlanValidate → Execute (LLM + tool loop) → Synthesize → Output. Enforces tier-based plan limits (FREE: 3 steps, PRO: 5, WHALE: 8). Must-refuse categories enforced. Evidence-first, neutral tone.

---

### 15.12 LEDGER (BriefingGraph Editor)

| Field | Value |
|-------|-------|
| **Role** | WhaleAgent briefing editor |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/ledger.txt` |
| **Job** | Produce daily briefing packages |
| **Color** | `#8E44AD` |
| **Temperature** | 0.3 |

**System Prompt Summary**: BriefingGraph editor. Select top events → Batch enrich → Synthesize → Publish. Tier-aware depth (FREE: top 3, PRO: top 10, WHALE: top 20 + custom). Never fabricate data — exclude on failure. Briefings are informational only.

---

### 15.13 AEGIS (Guardrail / Trust Policy)

| Field | Value |
|-------|-------|
| **Role** | WhaleAgent guardrail stage |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/aegis.txt` |
| **Job** | Guardrail enforcement, overrides all user-facing output |
| **Color** | `#E67E22` |
| **Temperature** | 0.0 |

**System Prompt Summary**: AEGIS authority overrides all user-facing outputs. No message reaches the user without passing AEGIS. Checks: financial-advice classifier, prompt-injection defense, overclaim detector, disclaimer injection, anti-hype lexicon enforcement, budget enforcement. Output: pass / reject / modify / log.

---

### 15.14 RELAY (Telegram Formatter)

| Field | Value |
|-------|-------|
| **Role** | WhaleAgent Telegram formatter |
| **Type** | Subagent (@-invocable) |
| **Prompt** | `prompts/v1/agents/relay.txt` |
| **Job** | Format structured output for Telegram, no new claims |
| **Color** | `#3498DB` |
| **Temperature** | 0.1 |

**System Prompt Summary**: Telegram formatter (no new claims). Format structured agent output into Telegram MarkdownV2 messages. Character limits: 4096 per message. Scannable layout, disclaimer footer mandatory. Button schemas for explain_more, risks, related_wallets, ask_followup.

---

### 15.15 Persona Invocation & Governance

| Persona | Invocation | Governed By |
|---------|-----------|-------------|
| ATLAS | Tab-switch / @atlas | Constitution Articles 2, 3, 5, 7, 8 |
| FORGE | Tab-switch / @forge | Constitution Articles 1, 2, 5, 6, 7 |
| PRISM | Tab-switch / @prism | Constitution Articles 1, 2, 5, 6 |
| QUILL | Tab-switch / @quill | Constitution Articles 2, 7, 8 |
| MENTOR | @mentor | Constitution Articles 7, 8 |
| SCOUT | @scout | Constitution Articles 1, 7 |
| SENTINEL | @sentinel | Architecture.md, agents.md, scoring policy |
| ORION | @orion | agents.md §2.1, §5, §7 |
| MERIDIAN | @meridian | agents.md §2.2, §5, §6 |
| LEDGER | @ledger | agents.md §2.3, §5 |
| AEGIS | @aegis | agents.md §6, §5.4, constitutional override |
| RELAY | @relay | agents.md §8, formatting contract |

**AEGIS Authority Override**: AEGIS is the only persona with edit:allow on user-facing output content. If AEGIS rejects or modifies a message, the rejecting agent must log the AEGIS action record. No persona may bypass AEGIS.

### 15.16 File Layout

```
.opencode/
├── config.json              # Primary agent registrations (ATLAS, FORGE)
├── agents/
│   ├── atlas.md             # Mode A — Architect
│   ├── forge.md             # Mode B — Implementer
│   ├── prism.md             # Mode C — Reviewer
│   ├── quill.md             # Mode D — Auditor
│   ├── mentor.md            # Learning coach
│   ├── scout.md             # Research agent
│   ├── sentinel.md          # WhaleAgent — deterministic detection
│   ├── orion.md             # WhaleAgent — EventInvestigationGraph
│   ├── meridian.md          # WhaleAgent — ChatInvestigationGraph
│   ├── ledger.md            # WhaleAgent — BriefingGraph
│   ├── aegis.md             # WhaleAgent — Guardrail/Trust
│   └── relay.md             # WhaleAgent — Telegram formatter
prompts/
└── v1/
    └── agents/
        ├── atlas.txt
        ├── forge.txt
        ├── prism.txt
        ├── quill.txt
        ├── mentor.txt
        ├── scout.txt
        ├── sentinel.txt
        ├── orion.txt
        ├── meridian.txt
        ├── ledger.txt
        ├── aegis.txt
        └── relay.txt
```

---

*End of Specification*
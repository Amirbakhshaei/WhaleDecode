# Feature Specification: Pioneer Edge Intelligence (WhaleDecode V2)

**Feature Branch**: `001-pioneer-edge-intelligence`

**Created**: 2026-10-01

**Status**: Draft

**Input**: User description: "Use PROMPT_BUILD_PIONEER.md as the foundational specification. Extract all requirements, architecture, and user stories."

**Source document**: `PROMPT_BUILD_PIONEER.md` — "Master Blueprint: WhaleDecode Enterprise Edge & Deep Intelligence (V2 Pioneer)". Dual-topology on-chain whale intelligence: sub-30ms edge gatekeeper plus deep analytics engine, four proprietary heuristics (LAR, counterparty classification, NVS, stealth accumulation), viral Telegram/X distribution, all on $0.00/month infrastructure.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Breaking Whale Alert in Seconds (Priority: P1)

A crypto trader following smart money receives a rich, actionable Telegram alert within seconds of a Tier-1 whale executing a large on-chain move (e.g., a fund absorbing $1.4M of spot ETH into cold storage), including entity identity, flow size, conviction signal, analyst thesis, and a link to verify on-chain.

**Why this priority**: This is the core value loop — raw chain events become trusted alpha faster than the user could find them manually. Without it nothing else matters.

**Independent Test**: Send a synthetic high-value whale transfer through ingress and confirm a formatted alert arrives in the Telegram channel; send a known-noise transfer (exchange hot wallet, MEV bot) and confirm nothing arrives and no expensive processing occurs.

**Acceptance Scenarios**:

1. **Given** a tracked whale wallet executes a qualifying move at or above the value floor, **When** the chain webhook fires, **Then** the follower receives a structured alert (entity, network, flow amount, USD value, narrative tag, impact metric, thesis, explorer link, bot handle) within ~30 seconds of ingress.
2. **Given** a transfer originates from a known-toxic address (major exchange hot wallet, MEV sandwich bot, bridge router), **When** the webhook fires, **Then** the event is dropped in under ~1ms-equivalent fast path with no alert and no persistent write.
3. **Given** a transfer below the $50,000 value floor, **When** the webhook fires, **Then** the event is dropped before any AI synthesis is invoked.
4. **Given** the same chain transaction is delivered twice (webhook retry), **When** both deliveries ingress, **Then** only one alert is ever produced (idempotent on chain + tx hash + log index).

---

### User Story 2 - Deep Trade Intelligence, Not Just Alerts (Priority: P1)

A power user reading an alert understands *why the trade matters*: how much of the pool's liquidity it absorbed, where the tokens went next (cold vault vs. lending vs. exchange deposit), which narrative it belongs to, and what the desk's thesis is — plus a visual card summarizing the flow.

**Why this priority**: Raw amounts are a commodity; conviction classification and impact scoring are the institutional edge that drives follows and retention.

**Independent Test**: Feed a known high-impact swap and a known stealth inflow through enrichment and verify the impact verdict, counterparty label, narrative tag, and generated visual card match expected values.

**Acceptance Scenarios**:

1. **Given** an enriched swap with known USD value and pool liquidity, **When** impact is computed, **Then** a move absorbing ≥5% of pool liquidity is labeled High Market Impact and a move <1% is labeled Low Friction Inflow.
2. **Given** a whale outflow to a destination address, **When** the destination is classified, **Then** the alert states one of: cold/fresh accumulation, lending/collateral deployment, exchange distribution warning, or DEX absorption — and the thesis reflects the conviction implication.
3. **Given** a token with a 24h volume spike in a tracked narrative sector, **When** the narrative score is computed, **Then** the alert carries the correct narrative tag (e.g., AI agents, RWA/yield, DeFi primitive, meme, L2 infra, macro settlement).
4. **Given** a qualifying alpha event, **When** distribution renders, **Then** a 1200×675 high-contrast card is attached showing entity, flow, USD volume, impact gauge, and narrative badge.

---

### User Story 3 - Viral Growth on X Without Paywalls (Priority: P2)

A casual X (Twitter) user who has never heard of WhaleDecode sees a hook tweet in their feed ("while retail dumped, 3 funds absorbed $42M…"), taps into the thread for proof, bookmarks it, and follows the linked Telegram channel for real-time alerts.

**Why this priority**: Telegram serves existing followers; X threads are the top-of-funnel growth engine. The link-free-root + daily-leaderboard format is the documented viral mechanism.

**Independent Test**: Trigger the daily recap job on fixture data and verify a link-free root hook plus proof replies plus Telegram CTA are published as a thread, and that no root post contains a URL.

**Acceptance Scenarios**:

1. **Given** the daily recap time is reached, **When** the job runs, **Then** it publishes a "Smart Money Inflow Leaderboard" thread covering the top 3 tokens accumulated by tracked entities over the prior 24h.
2. **Given** a root hook post is published, **When** inspected, **Then** it contains no URL and follows curiosity-gap → data-proof → punchy-insight structure with a bookmark call to action.
3. **Given** the thread completes, **When** the final reply is inspected, **Then** it invites readers to the Telegram alpha channel for real-time alerts.

---

### User Story 4 - Stealth Accumulation Detection (Priority: P2)

A fund-savvy follower gets warned about split-order accumulation — a whale spreading buys across sub-wallets in small tranches from one funding source — before the price move makes it obvious.

**Why this priority**: Single-tx alerts miss deliberate obfuscation; this heuristic catches the highest-conviction behavior (patient stacking) competitors miss.

**Independent Test**: Inject a fixture set of sub-floor transfers from one funding source inside a 6-hour window plus a control set from unrelated sources, and verify only the former raises a stealth-accumulation flag.

**Acceptance Scenarios**:

1. **Given** multiple transfers under the value floor share one funding source inside a rolling 6-hour window, **When** evaluated, **Then** the system flags a stealth-accumulation signal aggregating the tranches.
2. **Given** small transfers from unrelated funding sources, **When** evaluated, **Then** no stealth signal is raised.

---

### User Story 5 - Interactive Follower Bot (Priority: P3)

A Telegram user opens the bot, runs `/start`, browses tracked whales with `/whales`, and subscribes to a specific entity or token with `/track` so they only get pinged about what they care about.

**Why this priority**: Broadcast is one-to-many; subscriptions create retention and let the channel stay high-signal while individuals go deep.

**Independent Test**: In a test chat, run `/start`, `/whales`, and `/track <entity>` and verify correct responses and that a subsequent qualifying event for that entity reaches the subscriber.

**Acceptance Scenarios**:

1. **Given** a new user opens the bot, **When** they send `/start`, **Then** they receive onboarding (what the bot does, how to subscribe).
2. **Given** a user sends `/whales`, **When** processed, **Then** they receive the curated tracked-entity list.
3. **Given** a user sends `/track` for a supported entity, **When** that entity makes a qualifying move, **Then** the user receives a direct notification.

---

### User Story 6 - Zero-Cost Operation With Graceful Failover (Priority: P3)

The operator runs the whole pipeline for $0/month: edge stays within free request/CPU/storage budgets, price/oracle and AI calls stay within free rate limits, and when a primary provider fails or rate-limits the system transparently falls back without losing qualifying alerts.

**Why this priority**: Cost overrun kills the project; resilience keeps the "never miss alpha" promise when free providers throttle.

**Independent Test**: Simulate primary oracle/AI/RPC failures and rate-limit responses, then verify alerts still complete via fallback and no paid tier is ever invoked.

**Acceptance Scenarios**:

1. **Given** the primary market-data oracle fails or rate-limits, **When** enrichment runs, **Then** it completes via the secondary oracle with no alert lost.
2. **Given** the primary AI synthesis service fails or rate-limits, **When** thesis generation runs, **Then** it completes via the fallback model.
3. **Given** a data RPC endpoint returns errors or 429s, **When** backend lookups run, **Then** requests rotate to the next healthy endpoint.
4. **Given** a normal operating day within free-tier budgets, **When** usage is tallied, **Then** request counts, storage reads/writes, and AI call rates remain within the documented free allowances and zero paid services are called.

---

### User Story 7 - One-Command Deploy and Prove-It Test (Priority: P3)

A new operator (or CI job) can provision the database, seed clean whale and blacklist data, sync webhook watchlists, deploy the edge worker, register the Telegram webhook, launch the analytics engine, and run a full-spectrum end-to-end stress test proving the four pipeline guarantees.

**Why this priority**: Without a reproducible runbook the system is unmaintainable; the E2E suite is the contract that fast-path, floor-gating, synthesis, and idempotency all hold.

**Independent Test**: Run the documented 7-step runbook top to bottom in a staging environment and confirm each step succeeds and the stress suite reports all four guarantees green.

**Acceptance Scenarios**:

1. **Given** a fresh environment, **When** the operator runs database migration plus seed steps, **Then** curated wallets and blacklist entries exist and are queryable.
2. **Given** seeded wallets, **When** webhook sync runs, **Then** the remote webhook provider watches exactly the curated set across the covered networks.
3. **Given** the full pipeline is deployed, **When** the synthetic stress suite runs, **Then** it verifies: toxic txs terminate on the fast path with zero persistent writes; sub-floor noise never invokes AI; qualifying alpha produces a synthesized Telegram alert; duplicate replays are dropped by idempotency.

---

### Edge Cases

- What happens when a webhook arrives with an invalid or missing signature? → Reject without processing; acknowledge nothing that implies acceptance, log minimally.
- What happens when AI synthesis times out on both primary and fallback? → Deliver a template-structured alert with raw metrics (never drop qualifying alpha for lack of prose).
- What happens when pool liquidity data is unavailable for an impact computation? → Mark impact "unknown", still deliver the alert with available fields.
- What happens when an address appears on both the curated and blacklist sets? → Blacklist wins (never alert on toxic flow).
- What happens when EVM address casing varies (`0xAbC…` vs `0xabc…`)? → Normalize to lowercase before matching; Solana addresses keep native casing.
- What happens when a burst of webhooks exceeds edge CPU/time budget? → Heavy work is deferred off the hot path; ingress always acknowledges immediately and queues deep work.
- What happens when the daily leaderboard has fewer than 3 qualifying tokens? → Publish a shorter thread rather than fabricating entries.
- How does the system handle chain reorganizations or replaced transactions? → Idempotency key includes log position so distinct fills are distinct; re-orged duplicates collapse to one alert.

## Requirements *(mandatory)*

### Functional Requirements

**Edge ingress & gating**

- **FR-001**: System MUST acknowledge every inbound chain webhook immediately (HTTP 200-class) after signature validation and defer all heavy work off the hot response path.
- **FR-002**: System MUST cryptographically verify every webhook (signing secret / HMAC, timing-safe comparison) and reject unverifiable deliveries without further processing.
- **FR-003**: System MUST drop events from known-toxic addresses (major exchange hot wallets, MEV sandwich bots, bridge/cross-chain routers) on an in-memory fast path before any database or network call.
- **FR-004**: System MUST drop events below the $50,000 USD value floor before invoking any AI synthesis.
- **FR-005**: System MUST deduplicate deliveries idempotently on (chain + transaction hash + log index) so retries never double-alert.
- **FR-006**: System MUST normalize EVM addresses to lowercase for matching and preserve native casing for Solana addresses.
- **FR-007**: System MUST persist qualifying-event records for audit (what was kept, what was dropped and why) within free-tier storage budgets by filtering noise before writes.
- **FR-008**: System MUST route qualifying events into two lanes: an instant breaking-alert lane and a deep-profile lane forwarded to the analytics engine.

**Deep intelligence**

- **FR-009**: System MUST compute a Liquidity Absorption Ratio (swap USD value ÷ pool liquidity USD × 100) for swaps and label ≥5% High Market Impact and <1% Low Friction Inflow.
- **FR-010**: System MUST classify the counterparty destination of whale flows into at minimum: cold/fresh accumulation, lending/collateral deployment, exchange distribution, DEX absorption — and surface the label plus its conviction implication in the alert.
- **FR-011**: System MUST score and tag each qualifying event with a narrative category (at minimum: AI/agents, RWA/yield, DeFi primitive, meme, L2 infra, macro settlement) driven by trailing-24h sector volume behavior.
- **FR-012**: System MUST detect stealth accumulation: multiple sub-floor transfers from one funding source inside a rolling 6-hour window raise an aggregated signal.
- **FR-013**: System MUST track a curated set of at most ~50 low-churn whale wallets across the covered networks (Ethereum, Arbitrum, Base, Solana) and ignore all other senders.
- **FR-014**: System MUST generate an analyst thesis for each qualifying alert (what happened, what it signals, what to watch) via AI synthesis with automatic fallback to a secondary model on failure/rate-limit.
- **FR-015**: System MUST generate a 1200×675 dark-theme visual flow card per qualifying event (entity, flow arrow, USD volume, impact gauge, narrative badge) attachable to Telegram and X posts.

**Distribution**

- **FR-016**: System MUST deliver breaking alerts to Telegram in the structured S-tier format (entity, network, conviction, executed flow, narrative, impact, thesis, explorer link, bot handle).
- **FR-017**: System MUST publish a daily Smart Money Inflow Leaderboard thread (top 3 accumulated tokens, 24h window) on a fixed daily schedule, with a link-free root hook post following curiosity-gap → data-proof → insight structure.
- **FR-018**: System MUST append a Telegram-channel call-to-action as the final reply of every automated thread.
- **FR-019**: System MUST support Telegram bot commands `/start`, `/track`, and `/whales` for onboarding, subscription, and directory listing.

**Cost & resilience**

- **FR-020**: System MUST operate entirely on verified free-tier services ($0/month); no paid API tier may be required for normal operation.
- **FR-021**: System MUST fail over automatically across market-data oracles, AI models, and data RPC endpoints (round-robin with health/rate-limit awareness) without losing qualifying alerts.
- **FR-022**: System MUST restrict webhook intake filters to swap/transfer-type activity and curated senders so noise never enters the pipeline.

**Operability**

- **FR-023**: System MUST provide a reproducible runbook: idempotent DB migration, clean whale + blacklist seeding, webhook watchlist sync, secret configuration, edge deploy, Telegram webhook registration, analytics-engine launch.
- **FR-024**: System MUST provide a synthetic end-to-end stress suite proving the four pipeline guarantees (fast-path toxic drop with zero writes; sub-floor drop before AI; qualifying alpha → synthesized Telegram alert; duplicate replay dropped).

### Key Entities

- **WhaleTransaction**: A single on-chain move under watch; attributes: chain/network, tx hash, log index, sender, destination, token, amount, USD value, block time, raw payload reference.
- **CuratedWallet**: A tracked smart-money entity; attributes: address, chain, label (person/fund/desk), tier, narratives of interest, active flag.
- **BlacklistedAddress**: A known-toxic sender/router (exchange hot wallet, MEV bot, bridge); attributes: address, chain, category, reason, added date. Takes precedence over curated set.
- **IdempotencyRecord**: Proof a delivery was processed; attributes: idempotency key (chain+txHash+logIndex hash), first-seen time, outcome (alerted/dropped + reason).
- **EnrichedAlphaEvent**: A qualifying move plus intelligence; attributes: source transaction, USD value, impact ratio + verdict, counterparty label, narrative tag + score, conviction signal, thesis text, visual card reference.
- **StealthAccumulationSignal**: An aggregated pattern; attributes: funding source, window start/end, tranche count, total USD, involved sub-wallets, linked transactions.
- **VisualCard**: A rendered social asset; attributes: dimensions (1200×675), theme, entity/token marks, flow summary, impact gauge, narrative badge, image buffer reference.
- **AlertDelivery**: A distribution attempt; attributes: channel (Telegram broadcast/DM, X post), payload, scheduled/sent time, status, provider response.
- **LeaderboardRecap**: A daily rollup; attributes: date window, ranked tokens with inflow totals, top-3 breakdowns, thread post references.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Followers receive alerts for qualifying whale moves (≥$50k) within 30 seconds of webhook ingress at least 99% of the time.
- **SC-002**: At least 99.5% of deliveries from known-toxic senders produce no alert and no persistent write.
- **SC-003**: At least 99% of sub-floor (<$50k) deliveries never trigger AI synthesis.
- **SC-004**: Zero duplicate alerts from retried deliveries — every (chain, tx, log-index) triple alerts at most once.
- **SC-005**: At least 95% of qualifying alerts carry a correct impact verdict, counterparty label, and narrative tag against a labeled fixture set.
- **SC-006**: A new follower can understand any alert without external context — 9 out of 10 sampled alerts contain entity, size, impact, thesis, and a verifiable explorer link.
- **SC-007**: The daily leaderboard thread publishes every day with a link-free root post and a closing Telegram invite, with no fabricated entries on thin days.
- **SC-008**: Monthly infrastructure spend remains $0.00 with all usage inside documented free-tier allowances.
- **SC-009**: During a simulated primary-provider outage (oracle, AI, or RPC), 100% of qualifying fixture events still produce alerts via fallback with no data-shape regression.
- **SC-010**: A new operator completes the full runbook (migrate → seed → sync → deploy → register → launch → stress-test green) in under 60 minutes following only the written steps.

## Assumptions

- Covered networks for v1 are Ethereum, Arbitrum, Base (EVM webhooks) and Solana; other chains are out of scope until the pipeline is proven.
- Curated set is capped at ~50 low-churn Tier-1 entities (funds, desks, notable persons); list curation/attribution is an operator task, not automated discovery.
- Value floor is fixed at $50,000 USD for v1; per-token or per-entity floors are future work.
- Stealth window is a fixed 6-hour rolling window; tuning per entity is future work.
- Narrative taxonomy is the six categories in the source blueprint; new narratives require operator configuration.
- Telegram is the primary real-time channel; X is top-of-funnel growth with link-free root posts to respect free-tier/API constraints.
- AI-generated thesis text is editorial assistance, not financial advice; alerts carry the bot-handle attribution and explorer link for verification.
- Constitution file (`.specify/memory/constitution.md`) is an unratified placeholder template and imposes no additional shelved constraints on this spec.
- Existing repo scaffolding (`apps/cloudflare-worker`, `apps/backend-docker`) is reused; this spec does not prescribe internal file layouts beyond required behaviors.

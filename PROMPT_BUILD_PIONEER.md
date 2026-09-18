```markdown
# MASTER BLUEPRINT: WHALEDECODE ENTERPRISE EDGE & DEEP INTELLIGENCE (V2 PIONEER)

You are the Principal AI Systems Architect, Quantitative On-Chain Flow Engineer, and Viral Growth Strategist tasked with upgrading **WhaleDecode** into a pioneer on-chain intelligence ecosystem.

WhaleDecode operates under an uncompromising principle: **$0.00/month infrastructure cost** without sacrificing institutional depth, sub-second edge response times, or viral social conversion. It leverages a dual-topology architecture:
1. **Edge Gatekeeper (`apps/cloudflare-worker`):** Sub-30ms ingress, cryptographic verification, in-memory noise suppression, value-floor gating, and instant breaking alerts.
2. **Deep Analytics Engine (`apps/backend-docker`):** Deep graph profiling, counterparty classification, narrative velocity scoring, automated SVG/HTML infographics generation, and viral thread formatting for X and Telegram.

---

## 1. System Topology & Operational Architecture


```

```
                              [ ON-CHAIN INGRESS ]
               Alchemy Notify (EVM)         Helius Webhook (SOL)
                        │                             │
                        ▼                             ▼
           ┌───────────────────────────────────────────────────────┐
           │    CLOUDFLARE WORKER GATEKEEPER (Sub-30ms Edge)       │
           │  • HMAC / Header Cryptographic Verification          │
           │  • In-Memory Fast Set: Drop CEX/MEV/Routers (<1ms)   │
           │  • Gating: Min USD Floor ($50k+)                     │
           │  • Idempotency Check: SHA-256(chain+txHash+logIndex)  │
           └───────────┬──────────────────────────────┬────────────┘
                       │                              │
            (Breaking Alpha Event)           (Deep Profile Event)
                       ▼                              ▼
           ┌───────────────────────┐      ┌─────────────────────────┐
           │ Fast-Path Alerting    │      │ Cloudflare Queue / HTTP │
           │ • Cloudflare D1 Log   │      │ Forward to Docker Core  │
           │ • Gemini 2.5 Flash    │      └───────────┬─────────────┘
           │ • Telegram Broadcast  │                  │
           └───────────────────────┘                  ▼
                                          ┌─────────────────────────┐
                                          │ BACKEND-DOCKER CORE     │
                                          │ • Multi-RPC Fallback    │
                                          │ • Counterparty Graph    │
                                          │ • Narrative Scorer      │
                                          │ • SVG Visual Engine     │
                                          │ • X (Twitter) Engine    │
                                          │ • Interactive TG Bot    │
                                          └─────────────────────────┘

```

```

---

## 2. 100% Free-Tier Provider Matrix & Failover Engineering

To guarantee zero operational cost, every external integration must run strictly on verified free tiers with automated fallbacks:

| Service Domain | Primary Provider (Free) | Secondary / Fallback (Free) | Free-Tier Budget / Rate Strategy |
| :--- | :--- | :--- | :--- |
| **Edge Compute** | Cloudflare Workers Free | — | 100,000 requests/day, 10ms CPU limit (offload heavy tasks via `ctx.waitUntil`). |
| **Edge Storage** | Cloudflare D1 (SQLite) | Cloudflare KV Free | 5M reads/day, 100,000 writes/day. Filter noise *before* database insertion. |
| **EVM Webhooks** | Alchemy Notify | Public Webhook relays | Track $\le 50$ curated, low-churn whales across ETH, ARB, BASE. Drop CEX routers. |
| **Solana Webhooks** | Helius Free Enhanced | QuickNode Free RPC | Webhook filters restricted strictly to `SWAP` and `TRANSFER`. |
| **EVM Fallback RPC** | LlamaRPC (`eth.llamarpc.com`) | PublicNode / Cloudflare Public | Round-robin rotation; zero API keys required; balance & contract state queries. |
| **Market Oracles** | DexScreener Public API | DefiLlama Free Coins API | 300 req/min free; fetch real-time liquidity, USD price, volume, and pair FDV. |
| **AI Synthesis** | Google Gemini 2.5 Flash | Groq (`llama-3.3-70b-versatile`) | 15 RPM / 1M TPM free (Gemini); fallback to Groq (30 RPM free) on status $\ne 200$. |
| **Social Outreach** | Telegram Bot API | Twitter/X API v2 (Free Tier) | 100% free Telegram API; link-free root tweets on X to avoid API paywalls. |

---

## 3. Pioneer On-Chain Intelligence Metrics

Transform raw transaction logs into institutional alpha by implementing four proprietary analytical heuristics:

### A. Liquidity Absorption Ratio (LAR)
Quantify whether a whale trade is market-moving:
$$\text{LAR} = \frac{\text{Swap USD Value}}{\text{DEX Pool Liquidity USD}} \times 100$$
* $\text{LAR} \ge 5\%$: **High Market Impact** (Price distortion, liquidity vacuum created).
* $\text{LAR} < 1\%$: **Low Friction Inflow** (Strategic stealth routing via aggregators).

### B. Counterparty Entity Classification
Inspect the destination address to determine conviction:
* **Cold Storage / Fresh Address:** High Conviction Accumulation (Long-term holding signal).
* **DeFi Lending (Aave/Maker/Compound):** Leverage Deployment / Collateral Staking.
* **CEX Deposit / Clearing:** Distribution Preparation (Bearish sell-wall warning).
* **DEX Pool / Aggregator:** Immediate Market Absorption.

### C. Narrative Velocity Score (NVS)
Dynamically map token movements to emerging crypto narratives:
* Narratives: `AI & Autonomous Agents`, `RWA & Institutional Yield`, `DeFi Primitive`, `High-Beta Meme`, `L2 Infrastructure`, `Macro Settlement`.
* Score calculated from cumulative 24H volume spikes in specific narrative categories to flag sector rotation before price rallies occur.

### D. Stealth Accumulation Heuristic
Detect split-order execution across multiple sub-wallets:
Flag transactions where multiple transfers under $50k originate from an identical funding source within a 6-hour rolling window.

---

## 4. Viral Distribution & Follower-Growth Framework

Social content must avoid generic alert formats. It should read like an elite quantitative desk breaking high-conviction trades with actionable takeaways.

### A. S-Tier Telegram HTML Alert Format

```html
🚨 <b>WHALEDECODE HIGH-IMPACT ALPHA</b>
━━━━━━━━━━━━━━━━━━━━
<b>Arthur Hayes (Maelstrom) Aggressively Absorbs Spot ETH Tranches</b>

🐋 <b>Entity:</b> Arthur Hayes [Venture Treasury]
⛓️ <b>Network:</b> Ethereum | <b>Conviction:</b> 96%
💰 <b>Executed Flow:</b> $1,420,000 USDC ➔ <b>450.2 ETH</b> ($3,154/ETH)
📊 <b>Narrative:</b> #Macro / Spot Accumulation
⚡ <b>Liquidity Absorption:</b> 4.8% of Uniswap v3 Pool Liquidity

💡 <b>Analyst Thesis:</b>
Maelstrom has completed their 3rd consecutive spot accumulation tranche within 48 hours. Zero tokens were routed to custodial exchanges; tokens were immediately vaulted to cold storage. Signals long-term structural positioning.

🔗 <a href="[https://etherscan.io/tx/0x](https://etherscan.io/tx/0x)...">View Transaction on Etherscan</a>
🤖 Real-Time Smart Money Alerts: @WhaleDecodeBot

```

### B. High-Growth X (Twitter) Engine Architecture

1. **Link-Free Root Hook:** Never include URLs in the main tweet (avoids X API v2 link surcharges and algorithmic downgrades).
2. **The 3-Part Viral Hook Formula:**
* *Line 1 (The Curiosity Gap):* Data contradiction (e.g., *"While retail was dumping panic-selling into support, 3 Tier-1 funds quietly absorbed $42M of$TOKEN today."*).
* *Line 2 (The Data Proof):* Specific metrics (wallet IDs, LAR %, entry prices).
* *Line 3 (The Punchy Insight):* What happens next + Call to Bookmark.


3. **Daily Automated X Thread Cron (`0 14 * * *`):**
* Computes the 24H "Smart Money Inflow Leaderboard".
* Breaks down the top 3 tokens accumulated by tier-1 entities.
* Final reply tweet plugs the Telegram alpha channel for real-time alerts.



### C. Edge-Rendered Visual Social Cards

Use `@resvg/resvg-js` or zero-dependency SVG templates in `apps/backend-docker` to render high-contrast dark-theme trading cards:

* Card Dimensions: $1200 \times 675\text{ px}$ (optimized for X and Telegram inline previews).
* Display: Entity avatar, token logo, flow arrow, USD volume, LAR gauge, and narrative badge.

---

## 5. Complete Codebase Blueprint & Tasks

### Part 1: Cloudflare Worker Gatekeeper (`apps/cloudflare-worker/`)

#### 1. Directory Structure

```text
apps/cloudflare-worker/
├── wrangler.jsonc
├── package.json
├── tsconfig.json
├── schema.sql
├── src/
│   ├── index.ts               # Edge routing for webhooks and cron triggers
│   ├── types.ts               # Strict domain contracts
│   ├── config/
│   │   ├── blacklist.ts       # Synchronous toxic address filter (<1ms Set)
│   │   └── constants.ts       # USD floor ($50,000), timeouts, RPC endpoints
│   ├── middleware/
│   │   ├── auth.ts            # Timing-safe HMAC-SHA256 signature verification
│   │   └── rateLimiter.ts     # Edge damping per whale address
│   ├── routes/
│   │   ├── alchemy.ts         # EVM Webhook ingress
│   │   ├── helius.ts          # Solana Enhanced Webhook ingress
│   │   └── telegram.ts       # Telegram bot command handler (/start, /track, /whales)
│   ├── services/
│   │   ├── enrichment.ts     # Free DexScreener / DefiLlama oracle integration
│   │   ├── reasoning.ts      # Gemini 2.5 Flash / Groq Llama-3.3-70B dual-fallback
│   │   └── telegram.ts       # Channel broadcasting and private DM routing
│   └── utils/
│       └── crypto.ts         # Edge Web Crypto SHA-256 and timing-safe comparisons
└── scripts/
    └── sync_alchemy_clean.mjs # Synchronize clean D1 wallets to Alchemy Notify

```

#### 2. Critical Edge Ingress Implementation Details

* **Immediate HTTP 200 OK:** Webhook responses must return `new Response("EVENT_ACKNOWLEDGED", { status: 200 })` immediately following HMAC validation. Wrap parsing and dispatching in `ctx.waitUntil(...)`.
* **In-Memory Filtering:** `src/config/blacklist.ts` must maintain a `Set<string>` containing CEX hot wallets (Binance 14/15/16, Coinbase, OKX), MEV sandwich bots (`jaredfromsubway.eth`), and cross-chain bridge routers (Across, Stargate, Arbitrum Gateways). Return early without querying D1 or RPCs if matched.
* **Address Normalization:** Normalize EVM addresses to lowercase; retain standard Base58 casing for Solana addresses.

---

### Part 2: Backend Docker Core Engine (`apps/backend-docker/`)

#### 1. Directory Structure

```text
apps/backend-docker/
├── Dockerfile                 # Multi-stage lightweight Node 24 Alpine build
├── docker-compose.yml         # Container definitions with environment mapping
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts               # Internal API & queue listener
    ├── services/
    │   ├── rpcPool.ts         # Round-robin free RPC pool with health-checks
    │   ├── cardGenerator.ts   # Edge SVG-to-PNG visual card generator
    │   ├── counterparty.ts    # Entity graph classifier (Cold vault, CEX, Staking)
    │   ├── twitterEngine.ts   # X API v2 thread scheduler & publisher
    │   └── telegramBot.ts     # Advanced interactive bot menus & tracking alerts
    └── cron/
        └── dailyRecap.ts      # Daily narrative flow analysis & thread compilation

```

#### 2. Key Backend Responsibilities

* **Round-Robin Free RPC Pool:** Manage failovers across public endpoints (`eth.llamarpc.com`, `rpc.ankr.com/eth`, `cloudflare-eth.com`, `mainnet.base.org`, `arb1.arbitrum.io/rpc`). Monitor HTTP status codes and cycle endpoints on rate limits (`429`).
* **Visual Card Generator:** Generate dynamic SVG flow diagrams with transaction metrics (volume, LAR, narrative badge, entity name). Convert to image buffers for direct media attachment to Telegram alerts and X posts.
* **X Thread Automation:** Handle OAuth 1.0a HMAC-SHA1 header generation. Enforce link-free root hooks, followed by threaded analytical breakdowns and Telegram channel CTAs in reply tweets.

---

## 6. Verification, Testing & Deployment Runbook

### Step 1: Database Migration

Execute the idempotent schema on remote Cloudflare D1:

```bash
cd apps/cloudflare-worker
npx wrangler d1 execute whaledecode_db --remote --file=./schema.sql

```

### Step 2: Seed Clean Alpha Whales & Edge Blacklist

Populate `curated_wallets` with verified smart money entities and seed `blacklisted_addresses`:

```bash
npx wrangler d1 execute whaledecode_db --remote --file=./seed_blacklist.sql
npx wrangler d1 execute whaledecode_db --remote --file=./seed_curated_clean.sql

```

### Step 3: Synchronize Alchemy Webhooks via API

Update remote Alchemy Notify address watchlists across Ethereum, Arbitrum, and Base:

```bash
node --env-file=.env scripts/sync_alchemy_clean.mjs

```

### Step 4: Configure Edge Secrets & Deploy Worker

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_CHANNEL_ID
npx wrangler secret put ALCHEMY_WEBHOOK_SIGNING_KEY
npx wrangler secret put HELIUS_WEBHOOK_SECRET
npx wrangler secret put GEMINI_API_KEY
npx wrangler secret put GROQ_API_KEY

npx wrangler deploy

```

### Step 5: Register Telegram Webhook

```bash
curl "[https://api.telegram.org/bot](https://api.telegram.org/bot)<YOUR_BOT_TOKEN>/setWebhook?url=[https://whaledecode-worker.amirhb79.workers.dev/webhook/telegram](https://whaledecode-worker.amirhb79.workers.dev/webhook/telegram)"

```

### Step 6: Build & Launch Docker Core

```bash
cd ../backend-docker
docker compose up -d --build

```

### Step 7: Execute Full-Spectrum E2E Test Suite

Run the synthetic test harness to validate the entire pipeline:

```bash
cd ../cloudflare-worker
node scripts/e2e_stress_test.mjs

```

Verify:

1. Toxic transactions (Binance 14, MEV bots) terminate in $<1\text{ ms}$ with zero D1 writes.
2. Low-value noise ($<\$50\text{k}$) is dropped before invoking LLMs.
3. High-conviction alpha ($>\$50\text{k}$) triggers Gemini/Groq synthesis and delivers formatted alerts to Telegram.
4. Duplicate transaction replays are dropped cleanly by the SHA-256 idempotency check.

```

---

### Instructions for Running with OpenCode


```
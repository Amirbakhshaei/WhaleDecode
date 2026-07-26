---
name: crypto-product-safety
description: Use when writing user-facing analysis output, implementing alerting, designing tool schemas, building chain adapters, or modifying guardrails. Enforces no-custody/no-execution policy, disclaimer path, idempotent alerts with dedup keys, mockable chain providers, and evidence-based reasoning contracts.
---

## When to Apply

Any code path that:
- Produces user-facing text (Telegram messages, alerts, briefings)
- Defines or implements a tool in `tools/`
- Implements a chain provider in `adapters/chain/`
- Handles alert scoring, dedup, or delivery
- Modifies guardrails or refusal logic

## 1. No Custody, No Execution, No "Guaranteed Alpha"

**Hard rules in `docs/agents.md` section 6.5:**

- No trade execution, order placement, or swap functionality
- No private key / seed phrase handling — never ask for them, never log them
- No guaranteed returns claims — "guaranteed", "risk-free", "sure thing" are hard-refused
- No financial, tax, legal, or medical advice
- No sanctioned entity interaction guidance
- No market manipulation guidance (wash trading, spoofing)

**Tool design rule:** Every tool in `tools/` must be auditable as read-only. If a tool writes data (e.g., `write_user_memory`), it must require explicit user confirmation and have a `confirm=True` parameter.

## 2. All User-Facing AI Outputs Need Disclaimer Path

Every graph output that reaches a user MUST include the disclaimer. The `ChatAnswer` and `ReasoningReport` schemas have a `disclaimer` field — it must always be populated:

- **Short** (inline, every message): `"Not financial advice. On-chain data only. DYOR."`
- **Long** (detailed reports, briefings): Full disclaimer from `docs/agents.md` section 5.4

The disclaimer is appended by the formatter node, never by the LLM. Never skip it.

## 3. Idempotent Alerts / Dedup Keys

Every alert MUST have a deterministic `dedup_key`. From `docs/agents.md` section 7.4:

```python
dedup_key = f"{event_type}:{wallet_address}:{event_hash[:8]}"
ttl_seconds = TIER_TTL[user_tier]  # FREE=4h, PRO=2h, WHALE=30m
```

Before delivering an alert, check Redis for the dedup_key:
- Hit within TTL → suppress (increment counter, do not send)
- Miss or expired → send, write dedup_key with TTL

Implementation in `services/alert_service.py` must use Redis `SETEX` with `NX` for atomic dedup.

## 4. Mockable Chain Providers

Every chain provider must implement the port interface from `domain/ports/` and have a corresponding `MockProvider` in `tests/mocks/`. From `docs/architecture.md` port-first design:

```
adapters/chain/
  alchemy_provider.py     # Implements ChainProviderPort (production)
  mock_provider.py         # Implements ChainProviderPort (tests + dev)
```

Mock providers return deterministic data from fixture files. No real RPC calls in tests.

## 5. Evidence-Based Reasoning Contracts

Every output from the reasoning engine must follow the contract in `docs/agents.md` section 5.1:

1. **Evidence-first** — Every claim cites a tool call or explicit "no data"
2. **Neutral tone** — No hype, no "alpha", no "gem", no "moon", no "undervalued"
3. **Uncertainty calibrated** — Explicit confidence, explicit unknowns
4. **Risk-forward** — Lead with risks, not upside
5. **User-sovereign** — User decides; we inform, never recommend trades

The `ReasoningReport`, `ChatAnswer`, and `BriefingPackage` Pydantic models enforce this structurally (evidence list, confidence score, risk_factors, disclaimer fields).

## 6. Anti-Hype Enforcement

From `docs/agents.md` section 5.3, these phrases are banned in bot output:

- "gem", "hidden gem", "moon", "moonshot"
- "alpha", "alpha leak", "insider alpha"
- "smart money", "loading bags"
- "undervalued", "underpriced"
- "guaranteed", "certain", "will" (as prediction)
- "rug pull proof", "safe" (without qualification)

The `guardrails/financial_advice.py` classifier + `guardrails/overclaim.py` detector enforce this post-LLM. If a replacement is needed, use the "Alternative" column from the style guide table.

## Verification

- [ ] No trade execution, no private keys, no guaranteed returns in any tool/schema?
- [ ] Disclaimer populated on every output path?
- [ ] Every alert has a deterministic dedup_key + Redis TTL check?
- [ ] Chain provider can be swapped with MockProvider in tests?
- [ ] All claims cite tool calls or explicit "no data"?
- [ ] Output scanned for banned phrases (anti-hype lexicon)?

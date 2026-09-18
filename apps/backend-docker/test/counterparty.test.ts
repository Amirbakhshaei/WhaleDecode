import assert from "node:assert/strict";
import { test } from "node:test";
import { classifyCounterparty, computeLar, detectStealth, classifyNarrative, entityLabel } from "../src/services/counterparty.js";
import { initDb, insertEvent, closeDb } from "../src/db.js";
import type { WorkerEvent } from "../src/types.js";

function ev(over: Partial<WorkerEvent> = {}): WorkerEvent {
  return {
    idempotencyKey: "k",
    chain: "ethereum",
    txHash: "0xtx",
    logIndex: 0,
    fromAddress: "0x0716a17fbaee714f1e6ab0f9d59edbc5f09815c0",
    toAddress: "0x1111111254eeb25477b68fb85ed929f73a960582",
    assetSymbol: "ETH",
    amount: "10",
    usdValue: 500_000,
    actionType: "swap",
    wallet: { address: "0x0716a17fbaee714f1e6ab0f9d59edbc5f09815c0", label: "", category: "Smart Money", chain: "ethereum" },
    enrichment: { priceUsd: 3000 },
    ...over,
  };
}

test("counterparty classification is evidence-based", () => {
  assert.equal(classifyCounterparty(ev({ toAddress: "0x21a31ee1afc51d94c2efccaa2092ad1028285549" })).kind, "cex");
  assert.equal(classifyCounterparty(ev({ toAddress: "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2" })).kind, "defi");
  assert.equal(classifyCounterparty(ev({ toAddress: "0x1111111254eeb25477b68fb85ed929f73a960582" })).kind, "dex");
  assert.equal(classifyCounterparty(ev({ toAddress: "0x1234567890123456789012345678901234567890" })).kind, "unknown");
  const coldByCategory = classifyCounterparty(ev({
    toAddress: "0x1234567890123456789012345678901234567890",
    wallet: { address: "0x1", label: "Jump Trading Reserve", category: "Reserve Vault", chain: "ethereum" },
  }));
  assert.equal(coldByCategory.kind, "cold");
});

test("unknown counterparty is NOT reported as cold", () => {
  const r = classifyCounterparty(ev({
    toAddress: "0x9999999999999999999999999999999999999999",
    wallet: { address: "0x2", label: "Fresh Wallet", category: "Unknown", chain: "ethereum" },
  }));
  assert.equal(r.kind, "unknown");
  assert.equal(r.conviction, "unknown");
});

test("LAR math", () => {
  assert.equal(computeLar(2_000_000, 100_000), 5);
  assert.equal(computeLar(10_000_000, 50_000), 0.5);
  assert.equal(computeLar(undefined, 100), null);
  assert.equal(computeLar(0, 100), null);
});

test("stealth flags sub-50k with >=1 sibling", () => {
  initDb(":memory:");
  const now = Date.now();
  insertEvent({
    idempotency_key: "sib1", chain: "ethereum", tx_hash: "0xs", log_index: 0,
    from_address: "0xfunderx", to_address: "0xd", asset_symbol: "ETH", token_address: null,
    amount: "1", usd_value: 30_000, action_type: "transfer", wallet_address: "0xw",
    wallet_label: "", wallet_category: "", price_usd: 1, liquidity_usd: null,
    volume_24h: null, fdv: null, narrative: null, received_at: now - 3600_000,
  });
  const r = detectStealth(ev({ usdValue: 30_000, fromAddress: "0xfunderx", idempotencyKey: "probe" }), now);
  assert.equal(r.flagged, true);
  assert.equal(r.siblings, 1);
  assert.equal(r.maxUsd, 50_000);
  closeDb();
});

test("narrative fallback for unknown symbols is High-Beta Meme", () => {
  assert.equal(classifyNarrative("WIFCOIN"), "High-Beta Meme");
  assert.equal(classifyNarrative("TAO"), "AI & Autonomous Agents");
  assert.equal(classifyNarrative("ARB"), "L2 Infrastructure");
});

test("entityLabel uses worker label then known map then truncation", () => {
  assert.equal(entityLabel(ev({ wallet: { address: "0x3", label: "My Whale", category: "", chain: "ethereum" } })), "My Whale");
  assert.equal(entityLabel(ev()), "Arthur Hayes / Maelstrom");
  assert.equal(entityLabel(ev({ fromAddress: "0xabc1234567890abc1234567890abc1234567890" })), "0xabc1…7890");
});

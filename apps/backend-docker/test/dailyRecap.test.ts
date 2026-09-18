import assert from "node:assert/strict";
import { test } from "node:test";
import { msUntilNext14Utc } from "../src/cron/dailyRecapCron.js";
import { buildRecap } from "../src/cron/dailyRecap.js";
import { initDb, closeDb, insertEvent } from "../src/db.js";
import type { StoredEvent } from "../src/db.js";

test("cron fires at 14:00 UTC next day if past 14:00", () => {
  const now = new Date("2026-09-17T15:30:00Z");
  const ms = msUntilNext14Utc(now);
  assert.equal(ms, 22.5 * 3600_000);
});

test("cron fires later today if before 14:00", () => {
  const now = new Date("2026-09-17T09:00:00Z");
  assert.equal(msUntilNext14Utc(now), 5 * 3600_000);
});

test("recap returns null with no events", () => {
  initDb(":memory:");
  assert.equal(buildRecap(Date.now()), null);
});

test("recap compiles leaderboard, top tokens, thread", () => {
  initDb(":memory:");
  const now = Date.now();
  const e = (over: Partial<StoredEvent>): StoredEvent => ({
    idempotency_key: over.idempotency_key!, chain: "ethereum", tx_hash: "0xt", log_index: 0,
    from_address: "0xf", to_address: "0xt", asset_symbol: "ETH", token_address: null,
    amount: "1", usd_value: 100_000, action_type: "swap", wallet_address: "0xw",
    wallet_label: "Whale One", wallet_category: "Smart Money", price_usd: 1, liquidity_usd: null,
    volume_24h: null, fdv: null, narrative: "Macro Settlement", received_at: now,
    ...over,
  });
  insertEvent(e({ idempotency_key: "r1", asset_symbol: "ETH", usd_value: 1_000_000, wallet_address: "0xw1", wallet_label: "Whale One" }));
  insertEvent(e({ idempotency_key: "r2", asset_symbol: "ETH", usd_value: 500_000, wallet_address: "0xw1", wallet_label: "Whale One" }));
  insertEvent(e({ idempotency_key: "r3", asset_symbol: "AIUSDC", usd_value: 200_000, wallet_address: "0xw2", wallet_label: "Whale Two", narrative: "AI & Autonomous Agents", received_at: now - 2 * 3600_000 }));
  const recap = buildRecap(now);
  assert.ok(recap);
  assert.equal(recap!.eventCount, 3);
  assert.equal(recap!.totalUsd, 1_700_000);
  assert.equal(recap!.topAccumulated[0]!.assetSymbol, "ETH");
  assert.equal(recap!.leaderboard[0]!.label, "Whale One");
  assert.ok(recap!.threadText.length >= 2);
  assert.ok(recap!.threadText[recap!.threadText.length - 1]!.includes("@WhaleDecodeBot"));
  closeDb();
});

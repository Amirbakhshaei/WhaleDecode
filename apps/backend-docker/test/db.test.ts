import assert from "node:assert/strict";
import { test, beforeEach, afterEach } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { initDb, closeDb, insertEvent, eventExists, eventsSince, narrativeVelocity, stealthSiblings, countEvents } from "../src/db.js";
import type { StoredEvent } from "../src/db.js";

function baseEvent(over: Partial<StoredEvent> = {}): StoredEvent {
  const now = Date.now();
  return {
    idempotency_key: "k1",
    chain: "ethereum",
    tx_hash: "0xabc",
    log_index: 0,
    from_address: "0xfunder",
    to_address: "0xdest",
    asset_symbol: "ETH",
    token_address: null,
    amount: "10",
    usd_value: 100000,
    action_type: "swap",
    wallet_address: "0xwhale",
    wallet_label: "Test Whale",
    wallet_category: "Smart Money",
    price_usd: 3000,
    liquidity_usd: 2_000_000,
    volume_24h: 5_000_000,
    fdv: 10_000_000,
    narrative: "Macro Settlement",
    received_at: now,
    ...over,
  };
}

beforeEach(() => { initDb(join(tmpdir(), `wd-test-${Date.now()}-${Math.random().toString(36).slice(2)}.db`)); });
afterEach(() => { closeDb(); });

test("insertEvent is idempotent by idempotencyKey", () => {
  assert.equal(insertEvent(baseEvent()), true);
  assert.equal(insertEvent(baseEvent()), false);
  assert.equal(countEvents(), 1);
  assert.equal(eventExists("k1"), true);
  assert.equal(eventExists("nope"), false);
});

test("narrativeVelocity compares 24h vs prev24h", () => {
  const now = Date.now();
  const h = 3600_000;
  insertEvent(baseEvent({ idempotency_key: "a1", narrative: "AI & Autonomous Agents", usd_value: 300, received_at: now - 2 * h }));
  insertEvent(baseEvent({ idempotency_key: "a2", narrative: "AI & Autonomous Agents", usd_value: 100, received_at: now - 30 * h }));
  insertEvent(baseEvent({ idempotency_key: "a3", narrative: "DeFi Primitive", usd_value: 500, received_at: now - 40 * h }));
  const v = narrativeVelocity(now);
  const ai = v.find((x) => x.narrative === "AI & Autonomous Agents");
  assert.ok(ai);
  assert.equal(ai.volume24h, 300);
  assert.equal(ai.volumePrev24h, 100);
  assert.equal(ai.velocityPct, 200);
  const defi = v.find((x) => x.narrative === "DeFi Primitive");
  assert.ok(defi);
  assert.equal(defi.volume24h, 0);
  assert.equal(defi.volumePrev24h, 500);
});

test("stealthSiblings counts sub-50k transfers from same funder within 6h", () => {
  const now = Date.now();
  insertEvent(baseEvent({ idempotency_key: "s0", usd_value: 40_000, received_at: now - 1 * 3600_000 }));
  insertEvent(baseEvent({ idempotency_key: "s1", usd_value: 49_999, received_at: now - 2 * 3600_000 }));
  insertEvent(baseEvent({ idempotency_key: "s2", usd_value: 60_000, received_at: now - 3 * 3600_000 }));
  insertEvent(baseEvent({ idempotency_key: "s3", usd_value: 30_000, received_at: now - 7 * 3600_000 }));
  assert.equal(stealthSiblings("ethereum", "0xfunder", now - 6 * 3600_000, "probe"), 2);
  assert.equal(stealthSiblings("ethereum", "0xfunder", now - 6 * 3600_000, "s1"), 1);
  assert.equal(stealthSiblings("ethereum", "0xotherfunder", now - 6 * 3600_000, "s1"), 0);
});

test("eventsSince filters by window and sorts by usd desc", () => {
  const now = Date.now();
  insertEvent(baseEvent({ idempotency_key: "e1", usd_value: 10, received_at: now - 1000 }));
  insertEvent(baseEvent({ idempotency_key: "e2", usd_value: 999, received_at: now - 2000 }));
  const rows = eventsSince(now - 5000, now);
  assert.equal(rows.length, 2);
  assert.equal(rows[0]!.idempotency_key, "e2");
});

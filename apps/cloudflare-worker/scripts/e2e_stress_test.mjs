import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { build } from "esbuild";

const bundle = await build({ entryPoints: ["src/index.ts"], bundle: true, write: false, format: "esm", platform: "browser" });
const { default: worker } = await import("data:text/javascript;base64," + Buffer.from(bundle.outputFiles[0].text).toString("base64"));

const SECRET = "test-secret";
const HAYES = "0x0716a17fbaee714f1e6ab0f9d59edbc5f09815c0";
const VITALIK = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045";
const BINANCE14 = "0x28c6c06298d514db089934071355e5743bf21d60";
const TX = "0x" + "ab".repeat(32);

const curated = new Map([
  [HAYES, { address: HAYES, chain: "ethereum", label: "Arthur Hayes / Maelstrom", category: "Smart Money" }],
  [VITALIK, { address: VITALIK, chain: "ethereum", label: "vitalik.eth", category: "Notable Whale" }],
]);
const events = new Map();
const cooldowns = new Map();
const deliveries = new Map();
const alerts = new Map();
let writes = 0;
let telegramCalls = 0;
let geminiCalls = 0;

const D1 = {
  prepare(sql) {
    return {
      bind(...p) {
        return {
          async first() {
            if (sql.includes("FROM curated_wallets WHERE address")) return curated.get(p[0]) ?? null;
            if (sql.includes("FROM candidate_events WHERE chain")) return events.get(`${p[0]}|${p[1]}|${p[2]}`) ? { 1: 1 } : null;
            if (sql.includes("FROM whale_cooldowns WHERE")) {
              for (const [k, v] of cooldowns) if (k.startsWith(`${p[0]}|${p[1]}|`)) return { event_key: v };
              return null;
            }
            return null;
          },
          async all() { return { results: [] }; },
          async run() {
            if (sql.startsWith("INSERT OR IGNORE INTO candidate_events")) {
              const key = sql.includes("idempotency_key") ? `${p[1]}|${p[2]}|${p[3]}` : `${p[0]}|${p[1]}|${p[2]}`;
              if (events.has(key)) return { meta: { changes: 0 } };
              writes++;
              events.set(key, true);
              return { meta: { changes: 1 } };
            }
            if (sql.includes("INTO whale_cooldowns")) {
              const k = `${p[0]}|${p[1]}|day`;
              if (cooldowns.has(k)) return { meta: { changes: 0 } };
              writes++;
              cooldowns.set(k, p[2]);
              return { meta: { changes: 1 } };
            }
            if (sql.includes("INTO alert_deliveries") || sql.includes("INTO alerts")) { writes++; return { meta: { changes: 1 } }; }
            if (sql.startsWith("UPDATE")) { writes++; return { meta: { changes: 1 } }; }
            return { meta: { changes: 0 } };
          },
        };
      },
    };
  },
};

const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  const u = String(url);
  if (u.includes("coins.llama.fi")) return Response.json({ coins: { "coingecko:ethereum": { price: 3000, timestamp: Date.now() / 1000, confidence: 1 } } });
  if (u.includes("generativelanguage")) {
    geminiCalls++;
    const thesis = { headline: "Hayes absorbs large ETH tranche with conviction", intent: "ACCUMULATION", narrative: "Macro", analysis: "Observed flow only. Counterparty unknown. Size is large relative to typical transfers.", confidenceScore: 0.85, socialHook: "Whale flow detected" };
    return Response.json({ candidates: [{ content: { parts: [{ text: JSON.stringify(thesis) }] } }] });
  }
  if (u.includes("api.groq.com")) return Response.json({ choices: [{ message: { content: "{}" } }] });
  if (u.includes("api.telegram.org")) { telegramCalls++; return Response.json({ ok: true, result: { message_id: 1 } }); }
  if (u.includes("dexscreener")) return new Response("{}", { status: 404 });
  return new Response("{}", { status: 404 });
};

const env = { DB: D1, ALCHEMY_WEBHOOK_SIGNING_KEY: SECRET, HELIUS_WEBHOOK_SECRET: "helius-test", GEMINI_API_KEY: "g", GROQ_API_KEY: "q", TELEGRAM_BOT_TOKEN: "t", TELEGRAM_CHANNEL_ID: "1" };
const sign = (b) => createHmac("sha256", SECRET).update(b).digest("hex");
async function postAlchemy(payload) {
  const body = JSON.stringify(payload);
  const pending = [];
  const t0 = performance.now();
  const res = await worker.fetch(new Request("https://w/webhook/alchemy", { method: "POST", headers: { "x-alchemy-signature": sign(body), "content-type": "application/json" }, body }), env, { waitUntil(p) { pending.push(p); } });
  const ms = performance.now() - t0;
  const text = await res.text();
  await Promise.all(pending);
  return { res, text, ms };
}
const act = (from, value, hash = TX) => ({ fromAddress: from, toAddress: "0x0000000000000000000000000000000000000001", value: String(value), asset: "ETH", hash, category: "external" });

// auth fail-closed
{
  const r = await worker.fetch(new Request("https://w/webhook/alchemy", { method: "POST", body: "{}" }), {}, { waitUntil() {} });
  assert.equal(r.status, 401, "unsigned must 401");
  const r2 = await worker.fetch(new Request("https://w/webhook/alchemy", { method: "POST", headers: { "x-alchemy-signature": "00".repeat(32) }, body: "{}" }), env, { waitUntil() {} });
  assert.equal(r2.status, 401, "bad sig must 401");
  console.log("PASS auth fail-closed");
}
// 1. toxic
{
  const w0 = writes, t0 = telegramCalls;
  const { res, text, ms } = await postAlchemy({ network: "ETH_MAINNET", activity: [act(BINANCE14, 500)] });
  assert.equal(res.status, 200); assert.equal(text, "EVENT_ACKNOWLEDGED"); assert.ok(ms < 30, `ack ${ms.toFixed(1)}ms < 30ms`);
  assert.equal(writes, w0, "toxic: zero D1 writes"); assert.equal(telegramCalls, t0, "toxic: zero telegram");
  console.log(`PASS toxic filter (${ms.toFixed(1)}ms, 0 writes, 0 alerts)`);
}
// 2. noise
{
  const w0 = writes, t0 = telegramCalls, g0 = geminiCalls;
  const { res, ms } = await postAlchemy({ network: "ETH_MAINNET", activity: [act(VITALIK, 0.0833)] });
  assert.equal(res.status, 200); assert.ok(ms < 30);
  assert.equal(writes, w0, "noise: zero D1 writes"); assert.equal(telegramCalls, t0, "noise: zero telegram"); assert.equal(geminiCalls, g0, "noise: zero LLM");
  console.log(`PASS below-threshold gating (${ms.toFixed(1)}ms, 0 writes, 0 LLM)`);
}
// 3. alpha
{
  const w0 = writes, t0 = telegramCalls;
  const { res, ms } = await postAlchemy({ network: "ETH_MAINNET", activity: [act(HAYES, 416.7)] });
  assert.equal(res.status, 200); assert.ok(ms < 30);
  assert.ok(writes > w0, "alpha: D1 commit"); assert.equal(geminiCalls, 1, "alpha: thesis extracted"); assert.ok(telegramCalls > t0, "alpha: telegram delivered");
  console.log(`PASS high-conviction alpha (${ms.toFixed(1)}ms, D1+LLM+telegram)`);
}
// 4. replay
{
  const w0 = writes, t0 = telegramCalls;
  const { res } = await postAlchemy({ network: "ETH_MAINNET", activity: [act(HAYES, 416.7)] });
  assert.equal(res.status, 200);
  assert.equal(writes, w0, "replay: zero duplicate writes"); assert.equal(telegramCalls, t0, "replay: zero duplicate dispatch");
  console.log("PASS idempotency replay (0 duplicates)");
}
globalThis.fetch = realFetch;
console.log("E2E 4/4 PASS");

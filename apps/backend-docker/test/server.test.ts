import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import http from "node:http";
import { initDb, closeDb } from "../src/db.js";
import { createServer } from "../src/server.js";

process.env.DEEP_ENGINE_SECRET = "test-secret-123";

let server: http.Server;
let baseUrl = "";

before(async () => {
  initDb(":memory:");
  server = createServer();
  await new Promise<void>((r) => server.listen(0, () => r()));
  const addr = server.address() as { port: number };
  baseUrl = `http://127.0.0.1:${addr.port}`;
});

after(async () => {
  await new Promise<void>((r) => server.close(() => r()));
  closeDb();
});

async function call(method: string, path: string, body?: unknown, auth?: string): Promise<{ status: number; json: any }> {
  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: { "content-type": "application/json", ...(auth ? { authorization: auth } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, json: text ? JSON.parse(text) : null };
}

const ev = {
  idempotencyKey: "int-1",
  chain: "ethereum" as const,
  txHash: "0xint",
  logIndex: 3,
  fromAddress: "0x0716a17fbaee714f1e6ab0f9d59edbc5f09815c0",
  toAddress: "0x21a31ee1afc51d94c2efccaa2092ad1028285549",
  assetSymbol: "ETH",
  amount: "450.2",
  usdValue: 1_420_000,
  actionType: "swap",
  wallet: { address: "0x0716a17fbaee714f1e6ab0f9d59edbc5f09815c0", label: "Arthur Hayes / Maelstrom", category: "Venture Treasury", chain: "ethereum" as const },
  enrichment: { priceUsd: 3154, liquidityUsd: 30_000_000, volume24h: 900_000_000, fdv: null },
  reasoning: { headline: "h", intent: "i", narrative: "Macro Settlement", analysis: "a", confidenceScore: 0.96, socialHook: "hook" },
};

test("GET /health is open", async () => {
  const r = await call("GET", "/health");
  assert.equal(r.status, 200);
  assert.equal(r.json.ok, true);
});

test("POST /internal/events requires bearer secret", async () => {
  assert.equal((await call("POST", "/internal/events", ev)).status, 401);
  assert.equal((await call("POST", "/internal/events", ev, "Bearer wrong")).status, 401);
});

test("POST /internal/events validates payload", async () => {
  const r = await call("POST", "/internal/events", { idempotencyKey: "x" }, "Bearer test-secret-123");
  assert.equal(r.status, 422);
  assert.ok(Array.isArray(r.json.details) && r.json.details.length > 0);
});

test("POST /internal/events accepts, dedups, returns intel", async () => {
  const r = await call("POST", "/internal/events", ev, "Bearer test-secret-123");
  assert.equal(r.status, 202);
  assert.equal(r.json.status, "accepted");
  assert.equal(r.json.counterparty.kind, "cex");
  assert.equal(r.json.counterparty.conviction, "distribution");
  assert.ok(r.json.lar !== null && r.json.lar < 5);
  const dup = await call("POST", "/internal/events", ev, "Bearer test-secret-123");
  assert.equal(dup.status, 200);
  assert.equal(dup.json.status, "duplicate");
});

test("POST /internal/recap requires auth and returns recap or empty", async () => {
  assert.equal((await call("POST", "/internal/recap", {})).status, 401);
  const r = await call("POST", "/internal/recap", {}, "Bearer test-secret-123");
  assert.equal(r.status, 200);
  assert.ok(["ok", "empty"].includes(r.json.status));
});

test("unknown routes 404", async () => {
  assert.equal((await call("GET", "/nope")).status, 404);
});

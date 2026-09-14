import { Hono } from "hono";
import type { Env } from "../types";
import { passesGate, computeUsdValue } from "../domain/eventGate";
import { getPriceUsdc } from "../services/priceOracle";

export const heliusRouter = new Hono<{ Bindings: Env }>();

export async function extractCandidateEvents(body: unknown): Promise<Array<{ chain: string; tx_hash: string; log_index: number; asset?: string; value_usd?: number; raw_json: unknown }>> {
  const payload = body as Record<string, unknown> | null;
  if (!payload) return [];
  const tx = (payload.transaction || payload.tx || {}) as Record<string, unknown>;
  const hash = String(tx.hash ?? payload.signature ?? payload.tx_hash ?? "unknown");
  const chain = String(payload.chain ?? "SOL");

  const candidates: Array<{ chain: string; tx_hash: string; log_index: number; asset?: string; value_usd?: number; raw_json: unknown }> = [];

  const native = Array.isArray(payload.nativeTransfers) ? payload.nativeTransfers : [];
  for (let i = 0; i < native.length; i++) {
    const t = native[i] as Record<string, unknown>;
    const fromAddr = String(t.fromUserAccount ?? t.from ?? "");
    const toAddr = String(t.toUserAccount ?? t.to ?? "");
    const lamports = Number(t.amount ?? 0);
    const solPrice = await getPriceUsdc("SOL");
    const usd = lamports / 1e9 * (solPrice > 0 ? solPrice : 150.0);
    candidates.push({
      chain,
      tx_hash: hash,
      log_index: i,
      asset: "SOL",
      value_usd: usd,
      raw_json: { from: fromAddr, to: toAddr, lamports, source: "native" },
    });
  }

  const token = Array.isArray(payload.tokenTransfers) ? payload.tokenTransfers : [];
  for (let i = 0; i < token.length; i++) {
    const t = token[i] as Record<string, unknown>;
    const mint = String(t.mint ?? t.tokenMint ?? "");
    const amountRaw = Number(t.tokenAmount ?? t.amount ?? 0);
    const price = await getPriceUsdc(mint || "TOKEN");
    candidates.push({
      chain,
      tx_hash: hash,
      log_index: native.length + i,
      asset: mint ? mint.slice(0, 10) + "..." : "TOKEN",
      value_usd: price > 0 ? amountRaw * price : 0,
      raw_json: { mint, amountRaw, source: "spl", from: t.fromUserAccount, to: t.toUserAccount },
    });
  }

  // DEX interactions via instructions
  const instructions = Array.isArray(payload.instructions) ? payload.instructions : [];
  for (let i = 0; i < instructions.length; i++) {
    const inst = instructions[i] as Record<string, unknown>;
    const prog = String(inst.programId ?? inst.program ?? "");
    if (prog && (prog.includes("dex") || prog.includes("swap") || prog.includes("raydium") || prog.includes("orca") || prog.includes("jupiter"))) {
      candidates.push({
        chain,
        tx_hash: hash,
        log_index: native.length + token.length + i,
        asset: "DEX",
        value_usd: 0,
        raw_json: { programId: prog, source: "dex_instruction" },
      });
    }
  }

  return candidates;
}

heliusRouter.post("/", async (c) => {
  const body = await c.req.json().catch(() => ({}));
  const events = await extractCandidateEvents(body);

  // Deduplication on (chain, tx_hash, log_index) via D1
  const db = (c.env as Env).DB;
  const inserted: string[] = [];
  for (const ev of events) {
    if (await passesGate({ chain: ev.chain, raw_json: ev.raw_json as Record<string, unknown> })) {
      try {
        await db.prepare(
          `INSERT OR IGNORE INTO candidate_events (chain, tx_hash, log_index, event_type, raw_json, value_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?)`
        ).bind(ev.chain, ev.tx_hash, ev.log_index, ev.asset ?? "unknown", JSON.stringify(ev.raw_json), ev.value_usd ?? 0, "pending").run();
        inserted.push(ev.tx_hash);
      } catch (e) {
        console.error("helius_dedup_insert_failed", String(e));
      }
    }
  }

  return c.json({ ok: true, source: "helius", parsed: events.length, inserted: inserted.length, events: events.slice(0, 5).map(e => ({ chain: e.chain, tx_hash: e.tx_hash, log_index: e.log_index, asset: e.asset })) });
});

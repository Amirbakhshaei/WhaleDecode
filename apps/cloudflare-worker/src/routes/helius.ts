import { Hono } from "hono";
import type { Env } from "../types";
import { readBody } from "../middleware/auth";
import { verifySecret } from "../utils/crypto";
import { isBlacklisted } from "../config/blacklist";
import { MIN_USD } from "../config/constants";
import { extractCandidateEvents } from "../services/heliusEvents";
import { logger } from "../utils/logger";

export const heliusRouter = new Hono<{ Bindings: Env }>();
export { extractCandidateEvents };

heliusRouter.post("/", async (c) => {
  let raw: string;
  try {
    raw = await readBody(c.req.raw);
  } catch {
    return c.text("body_too_large", 413);
  }
  const secret = c.env.HELIUS_WEBHOOK_SECRET;
  const provided = c.req.header("authorization")?.replace(/^Bearer /i, "") ?? c.req.header("x-helius-signature");
  if (!await verifySecret(provided, secret)) return c.text("invalid_signature", 401);
  c.executionCtx.waitUntil(processHelius(raw, c.env).catch((e) => logger.error("helius_pipeline_failed", { stage: "INGRESS", error: String(e) })));
  return c.text("EVENT_ACKNOWLEDGED", 200);
});

async function processHelius(raw: string, env: Env): Promise<void> {
  let body: unknown = null;
  try {
    body = JSON.parse(raw);
  } catch {
    return;
  }
  const events = await extractCandidateEvents(body);
  for (const ev of events) {
    const detail = ev.raw_json as Record<string, unknown>;
    const from = String(detail.from ?? "");
    const to = String(detail.to ?? "");
    if (isBlacklisted(from) || isBlacklisted(to)) continue;
    if (!Number.isFinite(ev.value_usd) || (ev.value_usd ?? 0) < MIN_USD) continue;
    await env.DB.prepare(
      "INSERT OR IGNORE INTO candidate_events (chain, tx_hash, log_index, from_address, to_address, asset_symbol, event_type, raw_json, value_usd, usd_value, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'accepted')",
    ).bind(ev.chain, ev.tx_hash, ev.log_index, from, to, ev.asset ?? "", ev.asset ?? "unknown", JSON.stringify(ev.raw_json), ev.value_usd ?? 0, ev.value_usd ?? 0).run();
  }
}

import type { HandlerCtx, WorkerEvent } from "./types.js";
import { json } from "./config.js";
import { insertEvent, eventExists, countEvents, closeDb } from "./db.js";
import { classifyCounterparty, classifyNarrative, computeLar, detectStealth } from "./services/counterparty.js";
import { generateCard } from "./services/cardGenerator.js";
import { buildRecap } from "./cron/dailyRecap.js";
import { publishEventToTelegram } from "./services/telegramBot.js";

const CHAINS = new Set(["ethereum", "arbitrum", "base", "solana"]);

function validateEvent(raw: unknown): { ok: true; ev: WorkerEvent } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  const b = (raw ?? {}) as Record<string, unknown>;
  const need = (k: string): unknown => {
    if (b[k] === undefined || b[k] === null || b[k] === "") errors.push(`missing ${k}`);
    return b[k];
  };
  need("idempotencyKey"); need("txHash"); need("assetSymbol"); need("fromAddress"); need("toAddress");
  const chain = need("chain");
  if (typeof chain !== "string" || !CHAINS.has(chain)) errors.push("chain must be ethereum|arbitrum|base|solana");
  const usd = Number(b.usdValue);
  if (!Number.isFinite(usd)) errors.push("usdValue must be a number");
  const wallet = b.wallet as Record<string, unknown> | undefined;
  if (!wallet || typeof wallet !== "object") errors.push("wallet object required");
  const enr = b.enrichment as Record<string, unknown> | undefined;
  if (!enr || typeof enr !== "object" || !Number.isFinite(Number(enr?.priceUsd))) errors.push("enrichment.priceUsd required");
  if (errors.length) return { ok: false, errors };
  return { ok: true, ev: raw as WorkerEvent };
}

export async function handleEvent(_req: HandlerCtx["req"], res: HandlerCtx["res"], body: string): Promise<void> {
  let raw: unknown;
  try { raw = JSON.parse(body); } catch { return json(res, 400, { error: "invalid json" }); }
  const v = validateEvent(raw);
  if (!v.ok) return json(res, 422, { error: "validation failed", details: v.errors });

  const ev = v.ev;
  if (eventExists(ev.idempotencyKey)) {
    return json(res, 200, { status: "duplicate", idempotencyKey: ev.idempotencyKey });
  }

  const nowMs = Date.now();
  const narrative = ev.reasoning?.narrative ?? classifyNarrative(ev.assetSymbol);
  const cp = classifyCounterparty(ev);
  const lar = computeLar(ev.enrichment.liquidityUsd, ev.usdValue);
  const stealth = detectStealth(ev, nowMs);

  const inserted = insertEvent({
    idempotency_key: ev.idempotencyKey,
    chain: ev.chain,
    tx_hash: ev.txHash,
    log_index: ev.logIndex ?? 0,
    from_address: (ev.fromAddress || "").toLowerCase(),
    to_address: (ev.toAddress || "").toLowerCase(),
    asset_symbol: ev.assetSymbol,
    token_address: ev.tokenAddress ?? null,
    amount: String(ev.amount),
    usd_value: Number(ev.usdValue),
    action_type: ev.actionType ?? "transfer",
    wallet_address: (ev.wallet?.address || "").toLowerCase(),
    wallet_label: ev.wallet?.label ?? "",
    wallet_category: ev.wallet?.category ?? "",
    price_usd: Number(ev.enrichment?.priceUsd ?? 0),
    liquidity_usd: ev.enrichment?.liquidityUsd ?? null,
    volume_24h: ev.enrichment?.volume24h ?? null,
    fdv: ev.enrichment?.fdv ?? null,
    narrative,
    received_at: nowMs,
  });

  if (!inserted) return json(res, 200, { status: "duplicate", idempotencyKey: ev.idempotencyKey });

  const card: Buffer = generateCard(ev, { lar, counterparty: cp, narrative, stealth });
  const published = await publishEventToTelegram(ev, { lar, counterparty: cp, narrative, stealth, card });

  return json(res, 202, {
    status: "accepted",
    idempotencyKey: ev.idempotencyKey,
    narrative,
    lar,
    counterparty: cp,
    stealth,
    telegramPublished: published,
    totalEvents: countEvents(),
  });
}

export async function handleRecap(req: HandlerCtx["req"], res: HandlerCtx["res"], _body: string): Promise<void> {
  void req;
  const recap = buildRecap(Date.now());
  if (!recap) return json(res, 200, { status: "empty", message: "no events in last 48h" });
  return json(res, 200, { status: "ok", recap });
}

export function shutdownDb(): void { closeDb(); }

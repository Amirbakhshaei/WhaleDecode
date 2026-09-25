import type { Flow } from "../config/constants";
import type { Env, WhaleActivity } from "../types";
import { enrich } from "./enrichment";
import { isBlacklisted } from "../config/blacklist";
import { idempotencyKey } from "../utils/crypto";
import { reason } from "./reasoning";
import { broadcast } from "./telegram";
import { claimCooldown } from "../middleware/rateLimiter";
import { MIN_USD } from "../config/constants";
import { extractActivities } from "./extract";
import { logger } from "../utils/logger";

export async function processAlchemy(raw: string, env: Env): Promise<void> {
  const payload = safeParse(raw);
  const activities = extractActivities(payload);
  const network = String((payload as Record<string, unknown> | null)?.network ?? "ETH_MAINNET");
  for (const activity of activities) {
    const flow = await buildFlow(activity, network, env);
    if (!flow) continue;
    if (flow.usdValue < MIN_USD) {
      logger.info("TRANSACTION_GATED_BELOW_FLOOR", { stage: "GATED", chain: flow.chain, txHash: flow.txHash, whale: flow.wallet.label, usdValue: flow.usdValue, threshold: MIN_USD });
      await forward(flow, env);
      continue;
    }
    await dispatch(flow, env);
  }
}

function safeParse(raw: string): unknown {
  try { return JSON.parse(raw); } catch { return null; }
}

async function buildFlow(activity: WhaleActivity, network: string, env: Env): Promise<Flow | null> {
  const chain = chainFrom(network);
  const rawFrom = String(activity.fromAddress ?? "");
  const rawTo = String(activity.toAddress ?? "");
  const from = chain === "solana" ? rawFrom : rawFrom.toLowerCase();
  const to = chain === "solana" ? rawTo : rawTo.toLowerCase();
  if (!from || !to) return null;
  if (isBlacklisted(from) || isBlacklisted(to)) {
    logger.warn("TRANSACTION_DROPPED_BLACKLIST", { stage: "BLACKLIST", chain, from, to });
    return null;
  }
  const wallet = await findWallet(env, from, to);
  if (!wallet) return null;
  const symbol = String(activity.asset ?? "ETH").toUpperCase();
  const tokenAddress = typeof activity.tokenAddress === "string" ? activity.tokenAddress : undefined;
  const enrichment = await enrich(chain, symbol, tokenAddress);
  if (!enrichment) return null;
  const amount = Number(activity.value);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  const usdValue = amount * enrichment.priceUsd;
  const txHash = String(activity.hash ?? "");
  if (!/^0x[0-9a-f]{64}$/i.test(txHash)) return null;
  const logIndex = Number(activity.logIndex ?? 0);
  return {
    idempotencyKey: await idempotencyKey(chain, txHash, logIndex),
    chain,
    txHash,
    logIndex,
    fromAddress: from,
    toAddress: to,
    assetSymbol: symbol,
    tokenAddress,
    amount,
    usdValue,
    actionType: ["TRANSFER", "SWAP", "STAKE", "UNSTAKE"].includes(String(activity.category ?? "TRANSFER").toUpperCase()) ? String(activity.category ?? "TRANSFER").toUpperCase() as Flow["actionType"] : "TRANSFER",
    wallet,
    enrichment,
  };
}

function chainFrom(network: string): Flow["chain"] {
  return network === "ARB_MAINNET" ? "arbitrum" : network === "BASE_MAINNET" ? "base" : "ethereum";
}

async function findWallet(env: Env, ...addresses: string[]): Promise<Flow["wallet"] | null> {
  for (const address of addresses.filter(Boolean)) {
    const row = await env.DB.prepare("SELECT address, chain, COALESCE(label, address) AS label, COALESCE(category, 'Whale') AS category FROM curated_wallets WHERE address = ? AND is_active = 1 AND (is_exchange = 0 OR is_exchange IS NULL) AND (is_mev = 0 OR is_mev IS NULL) LIMIT 1").bind(address).first<{ address: string; chain: string; label: string; category: string }>();
    if (row) return { address: row.address, chain: normalizeChain(row.chain), label: row.label, category: row.category };
  }
  return null;
}

function normalizeChain(chain: string): Flow["chain"] {
  const lower = (chain ?? "").toLowerCase();
  return lower === "arbitrum" || lower === "base" || lower === "solana" ? lower : "ethereum";
}

async function dispatch(flow: Flow, env: Env): Promise<void> {
  const duplicate = await env.DB.prepare("SELECT 1 FROM candidate_events WHERE chain = ? AND tx_hash = ? AND log_index = ?").bind(flow.chain, flow.txHash, flow.logIndex).first();
  if (duplicate) {
    logger.debug("TRANSACTION_DEDUPED", { stage: "DEDUP", chain: flow.chain, txHash: flow.txHash });
    return;
  }
  const key = await idempotencyKey(flow.chain, flow.txHash, flow.logIndex);
  const claimed = await env.DB.prepare("INSERT OR IGNORE INTO candidate_events (idempotency_key, chain, tx_hash, log_index, from_address, to_address, asset_symbol, token_address, raw_value, event_type, action_type, raw_json, value_usd, usd_value, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'accepted')").bind(key, flow.chain, flow.txHash, flow.logIndex, flow.fromAddress, flow.toAddress, flow.assetSymbol, flow.tokenAddress ?? null, flow.amount, flow.actionType, flow.actionType, JSON.stringify({ from: flow.fromAddress, to: flow.toAddress, asset: flow.assetSymbol, amount: flow.amount, token: flow.tokenAddress ?? null }), flow.usdValue, flow.usdValue).run();
  if (!claimed.meta.changes) {
    logger.debug("TRANSACTION_DEDUPED", { stage: "DEDUP", chain: flow.chain, txHash: flow.txHash });
    return;
  }
  flow.idempotencyKey = key;
  if (!await claimCooldown(env, flow.chain, flow.wallet.address, key)) {
    logger.debug("TRANSACTION_DEDUPED", { stage: "DEDUP", chain: flow.chain, txHash: flow.txHash, reason: "cooldown" });
    return;
  }
  flow.reasoning = await reason(flow, env);
  logger.info("AI_REASONING_COMPLETE", { stage: "AI_REASONING", chain: flow.chain, txHash: flow.txHash, whale: flow.wallet.label, intent: flow.reasoning.intent, usdValue: flow.usdValue });
  await env.DB.prepare("INSERT OR IGNORE INTO alerts (idempotency_key, chain, tx_hash, headline, intent, narrative, reasoning, social_hook, body_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").bind(key, flow.chain, flow.txHash, flow.reasoning.headline, flow.reasoning.intent, flow.reasoning.narrative, flow.reasoning.analysis, flow.reasoning.socialHook, flow.reasoning.analysis).run();
  await broadcast(env, flow);
  logger.info("ALPHA_ALERT_SYNTHESIZED", { stage: "ALERT", chain: flow.chain, txHash: flow.txHash, whale: flow.wallet.label, headline: flow.reasoning.headline, intent: flow.reasoning.intent, usdValue: flow.usdValue });
  await env.DB.prepare("UPDATE alerts SET telegram_sent = 1 WHERE idempotency_key = ?").bind(key).run();
  await forward(flow, env);
}

async function forward(flow: Flow, env: Env): Promise<void> {
  if (!env.DEEP_ENGINE_URL || !env.DEEP_ENGINE_SECRET) return;
  await fetch(`${env.DEEP_ENGINE_URL.replace(/\/$/, "")}/internal/events`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${env.DEEP_ENGINE_SECRET}` },
    body: JSON.stringify(flow),
    signal: AbortSignal.timeout(2500),
  }).catch((e) => logger.error("deep_engine_forward_failed", { error: String(e) }));
}

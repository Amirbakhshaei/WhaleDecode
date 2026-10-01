import type { Flow } from "../config/constants";
import type { Env, WhaleActivity } from "../types";
import { enrich } from "./enrichment";
import { isBlacklisted } from "../config/blacklist";
import { idempotencyKey } from "../utils/crypto";
import { reason } from "./reasoning";
import { broadcast } from "./telegram";
import { claimCooldown } from "../middleware/rateLimiter";
import { MIN_CONFIDENCE_TO_PUBLISH, TOKEN_DEDUPE_WINDOW_SEC, chainMinUsd, isTreasuryLike } from "../config/constants";
import { extractActivities } from "./extract";
import { logger } from "../utils/logger";

// Thesis so hedged it admits ignorance is not signal — never broadcast it.
const HEDGED_THESIS_RE = /motive remains (uncertain|ambiguous)|without additional context|remains unclear|purpose .*not disclosed|exact motive remains/i;

export async function processAlchemy(raw: string, env: Env): Promise<void> {
  const payload = safeParse(raw);
  const activities = extractActivities(payload);
  const network = String((payload as Record<string, unknown> | null)?.network ?? "ETH_MAINNET");
  for (const activity of activities) {
    const flow = await buildFlow(activity, network, env);
    if (!flow) continue;
    if (flow.usdValue < chainMinUsd(flow.chain)) {
      logger.info("TRANSACTION_GATED_BELOW_FLOOR", { stage: "GATED", chain: flow.chain, txHash: flow.txHash, whale: flow.wallet.label, usdValue: flow.usdValue, threshold: chainMinUsd(flow.chain) });
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
  if (!wallet) {
    logger.info("TRANSACTION_DROPPED_UNKNOWN_WALLET", { stage: "GATED", chain, from, to, txHash: String(activity.hash ?? "") });
    return null;
  }
  const symbol = String(activity.asset ?? "ETH").toUpperCase();
  // ponytail: alchemy nests the token contract at rawContract.address, not tokenAddress
  const rawContract = activity.rawContract as { address?: unknown } | undefined;
  const tokenAddress = typeof activity.tokenAddress === "string" ? activity.tokenAddress
    : typeof rawContract?.address === "string" ? rawContract.address : undefined;
  const actionType = ["TRANSFER", "SWAP", "STAKE", "UNSTAKE"].includes(String(activity.category ?? "TRANSFER").toUpperCase()) ? String(activity.category ?? "TRANSFER").toUpperCase() as Flow["actionType"] : "TRANSFER";
  // Treasury/cold/DAO ops are internal bookkeeping, not market alpha — only
  // swaps out of them carry signal. Kills the DAO-treasury TRANSFER spam.
  if (actionType !== "SWAP" && isTreasuryLike(wallet.label, wallet.category)) {
    logger.info("TRANSACTION_DROPPED_TREASURY_INTERNAL", { stage: "GATED", chain, txHash: String(activity.hash ?? ""), whale: wallet.label, actionType });
    return null;
  }
  const enrichment = await enrich(chain, symbol, tokenAddress);
  if (!enrichment) {
    logger.info("TRANSACTION_DROPPED_NO_PRICE", { stage: "ORACLE", chain, txHash: String(activity.hash ?? ""), asset: symbol, token: tokenAddress ?? null });
    return null;
  }
  const amount = Number(activity.value);
  if (!Number.isFinite(amount) || amount <= 0) {
    logger.info("TRANSACTION_DROPPED_INVALID_VALUE", { stage: "GATED", chain, txHash: String(activity.hash ?? "") });
    return null;
  }
  const usdValue = amount * enrichment.priceUsd;
  // ponytail: a transfer can't exceed the token's FDV, and 20x pool depth on
  // a non-swap means the DexScreener pair is the wrong contract (ALPHA dupes).
  if (enrichment.fdv && usdValue > enrichment.fdv) {
    logger.info("TRANSACTION_DROPPED_IMPLAUSIBLE_VALUATION", { stage: "ORACLE", chain, txHash: String(activity.hash ?? ""), asset: symbol, usdValue, fdv: enrichment.fdv });
    return null;
  }
  if (actionType !== "SWAP" && enrichment.liquidityUsd && enrichment.liquidityUsd > 0 && usdValue > enrichment.liquidityUsd * 20) {
    logger.info("TRANSACTION_DROPPED_IMPLAUSIBLE_VALUATION", { stage: "ORACLE", chain, txHash: String(activity.hash ?? ""), asset: symbol, usdValue, liquidityUsd: enrichment.liquidityUsd });
    return null;
  }
  const txHash = String(activity.hash ?? "");
  if (!/^0x[0-9a-f]{64}$/i.test(txHash)) {
    logger.info("TRANSACTION_DROPPED_INVALID_HASH", { stage: "GATED", chain, txHash });
    return null;
  }
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
    actionType,
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
  // Token-level dedupe: same token re-alerted within the window (the 2x ALPHA
  // double-post came from two treasuries moving the same token). One headline
  // per token per hour — the second leg is context, not a new alert.
  const tokenKey = (flow.tokenAddress ?? flow.assetSymbol ?? "").toLowerCase();
  if (tokenKey) {
    const recent = await env.DB.prepare(
      `SELECT 1 FROM candidate_events WHERE chain = ? AND (lower(token_address) = ? OR (token_address IS NULL AND lower(asset_symbol) = ?)) AND created_at >= datetime('now', '-${TOKEN_DEDUPE_WINDOW_SEC} seconds') LIMIT 1`,
    ).bind(flow.chain, tokenKey, tokenKey).first().catch(() => null);
    if (recent) {
      logger.debug("TRANSACTION_DEDUPED", { stage: "DEDUP", chain: flow.chain, txHash: flow.txHash, reason: "token_cooldown" });
      return;
    }
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
  // Post-LLM publish gates: low conviction, internal ops, or a thesis that
  // admits ignorance never reaches the channel — stored, not broadcast.
  if (flow.reasoning.confidenceScore < MIN_CONFIDENCE_TO_PUBLISH) {
    logger.info("TRANSACTION_GATED_LOW_CONVICTION", { stage: "GATED", chain: flow.chain, txHash: flow.txHash, confidence: flow.reasoning.confidenceScore, threshold: MIN_CONFIDENCE_TO_PUBLISH });
    await env.DB.prepare("UPDATE candidate_events SET status = 'skipped' WHERE idempotency_key = ?").bind(key).run().catch(() => null);
    await forward(flow, env);
    return;
  }
  if (flow.reasoning.intent === "INTERNAL" || flow.reasoning.intent === "TRANSFER" || flow.reasoning.narrative === "Internal") {
    logger.info("TRANSACTION_GATED_INTERNAL_OPS", { stage: "GATED", chain: flow.chain, txHash: flow.txHash, intent: flow.reasoning.intent });
    await env.DB.prepare("UPDATE candidate_events SET status = 'skipped' WHERE idempotency_key = ?").bind(key).run().catch(() => null);
    await forward(flow, env);
    return;
  }
  if (HEDGED_THESIS_RE.test(flow.reasoning.analysis) && flow.reasoning.confidenceScore < 0.75) {
    logger.info("TRANSACTION_GATED_HEDGED_THESIS", { stage: "GATED", chain: flow.chain, txHash: flow.txHash, confidence: flow.reasoning.confidenceScore });
    await env.DB.prepare("UPDATE candidate_events SET status = 'skipped' WHERE idempotency_key = ?").bind(key).run().catch(() => null);
    await forward(flow, env);
    return;
  }
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

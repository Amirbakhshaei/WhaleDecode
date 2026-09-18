import type { Flow } from "../config/constants";
import type { Env } from "../types";

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}
export async function sendMessage(env: Env, chat: string | number, text: string): Promise<number> {
  const token = env.TELEGRAM_BOT_TOKEN || env.BOT_TOKEN;
  if (!token || !chat) throw new Error("telegram_not_configured");
  const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_id: chat, text, parse_mode: "HTML", link_preview_options: { is_disabled: true } }), signal: AbortSignal.timeout(4000),
  });
  const data = await response.json() as { ok?: boolean; result?: { message_id: number } };
  if (!response.ok || !data.ok || !data.result) throw new Error(`telegram_failed_${response.status}`);
  return data.result.message_id;
}
export function formatAlert(event: Flow): string {
  const thesis = event.reasoning;
  if (!thesis) throw new Error("missing_thesis");
  const explorer = { ethereum: "https://etherscan.io/tx/", arbitrum: "https://arbiscan.io/tx/", base: "https://basescan.org/tx/", solana: "https://solscan.io/tx/" }[event.chain];
  const lar = event.actionType === "SWAP" && (event.enrichment.liquidityUsd ?? 0) > 0 ? `${(event.usdValue / event.enrichment.liquidityUsd! * 100).toFixed(2)}% (pool snapshot estimate)` : "Unavailable / not a verified swap";
  return `<b>WHALEDECODE HIGH-IMPACT ALPHA</b>\n\n<b>${escapeHtml(thesis.headline)}</b>\n\n<b>Entity:</b> ${escapeHtml(event.wallet.label)} [${escapeHtml(event.wallet.category)}]\n<b>Network:</b> ${event.chain} | <b>Conviction:</b> ${Math.round(thesis.confidenceScore * 100)}% (model estimate)\n<b>Observed flow:</b> $${event.usdValue.toLocaleString("en-US", { maximumFractionDigits: 0 })} (${event.amount} ${escapeHtml(event.assetSymbol)})\n<b>Intent (inferred):</b> ${thesis.intent}\n<b>Narrative:</b> ${thesis.narrative}\n<b>Liquidity absorption:</b> ${lar}\n\n<b>Analyst thesis:</b>\n${escapeHtml(thesis.analysis)}\n\n<a href="${explorer}${encodeURIComponent(event.txHash)}">View transaction</a>\nReal-time monitoring by @WhaleDecodeBot`;
}
export async function broadcast(env: Env, event: Flow): Promise<void> {
  const channel = env.TELEGRAM_CHANNEL_ID || env.CHANNEL_CHAT_ID;
  const subscribers = await env.DB.prepare("SELECT DISTINCT user_id FROM tracked_wallets WHERE chain = ? AND address IN (?, ?) LIMIT 50").bind(event.chain, event.fromAddress, event.toAddress).all<{ user_id: number }>();
  const targets = new Set([channel, ...(subscribers.results ?? []).map((row) => String(row.user_id))].filter(Boolean));
  if (!targets.size) throw new Error("telegram_not_configured");
  for (const target of targets) {
    const claim = await env.DB.prepare("INSERT OR IGNORE INTO alert_deliveries (event_key, destination, status) VALUES (?, ?, 'sending')").bind(event.idempotencyKey, target).run();
    if (!claim.meta.changes) continue;
    try {
      const messageId = await sendMessage(env, target, formatAlert(event));
      await env.DB.prepare("UPDATE alert_deliveries SET status = 'sent', message_id = ? WHERE event_key = ? AND destination = ?").bind(messageId, event.idempotencyKey, target).run();
    } catch {
      await env.DB.prepare("UPDATE alert_deliveries SET status = 'uncertain' WHERE event_key = ? AND destination = ?").bind(event.idempotencyKey, target).run();
      throw new Error("telegram_delivery_uncertain");
    }
  }
}

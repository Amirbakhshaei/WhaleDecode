import { telegramBotToken, telegramChannelId } from "../config.js";
import { publishThread } from "./twitterEngine.js";
import type { WorkerEvent } from "../types.js";
import type { EventIntel } from "./cardGenerator.js";

const API = () => `https://api.telegram.org/bot${telegramBotToken()}`;

async function tg(method: string, payload: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  if (!telegramBotToken()) return null;
  try {
    const res = await fetch(`${API()}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export async function sendTelegramMessage(chatId: string, text: string): Promise<boolean> {
  const r = await tg("sendMessage", { chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true });
  return r !== null && r.ok === true;
}

export async function sendTelegramPhoto(chatId: string, caption: string, card: Buffer): Promise<boolean> {
  const fd = new FormData();
  fd.append("chat_id", chatId);
  fd.append("caption", caption);
  fd.append("parse_mode", "HTML");
  fd.append("document", new Blob([new Uint8Array(card)], { type: "image/svg+xml" }), "whale-card.svg");
  try {
    const res = await fetch(`${API()}/sendDocument`, { method: "POST", body: fd });
    const j = (await res.json()) as { ok?: boolean };
    return j.ok === true;
  } catch {
    return false;
  }
}

export function menuKeyboard(): Array<Array<{ text: string; callback_data: string }>> {
  return [
    [{ text: "🐋 Top Whales", callback_data: "menu_top" }, { text: "📈 Narratives", callback_data: "menu_narratives" }],
    [{ text: "⚡ Live Alerts", callback_data: "menu_alerts" }, { text: "❓ Help", callback_data: "menu_help" }],
  ];
}

export async function sendServiceMenu(chatId: string): Promise<boolean> {
  const r = await tg("sendMessage", {
    chat_id: chatId,
    text: "🤖 <b>WhaleDecode Deep Engine</b>\nSelect a service:",
    parse_mode: "HTML",
    reply_markup: { inline_keyboard: menuKeyboard() },
  });
  return r !== null && r.ok === true;
}

export function formatEventMessage(ev: WorkerEvent, intel: EventIntel): string {
  const lar = intel.lar === null ? "n/a" : `${intel.lar}% of pool liquidity`;
  const stealth = intel.stealth.flagged ? `\n🥷 <b>Stealth:</b> ${intel.stealth.siblings + 1} sub-$50k tranches from same funder (6h)` : "";
  return [
    `🚨 <b>WHALEDECODE DEEP ALERT</b>`,
    `━━━━━━━━━━━━━━━━━━━━`,
    `🐋 <b>Entity:</b> ${ev.wallet?.label || "Unknown"} [${ev.wallet?.category || "Wallet"}]`,
    `⛓️ <b>Network:</b> ${ev.chain} | <b>Conviction:</b> ${intel.counterparty.conviction}`,
    `💰 <b>Flow:</b> $${Number(ev.usdValue).toLocaleString()} ${ev.assetSymbol} → ${intel.counterparty.detail}`,
    `📊 <b>Narrative:</b> ${intel.narrative}`,
    `⚡ <b>Liquidity Absorption:</b> ${lar}`,
    stealth,
    ``,
    `💡 <b>Thesis:</b> ${ev.reasoning?.analysis ?? "Deep graph analysis in progress."}`,
    `🤖 Real-Time Smart Money Alerts: @WhaleDecodeBot`,
  ].filter((l) => l !== undefined).join("\n");
}

export async function publishEventToTelegram(ev: WorkerEvent, intel: EventIntel & { card: Buffer }): Promise<boolean> {
  let sent = false;
  const channel = telegramChannelId();
  if (channel) {
    sent = await sendTelegramPhoto(channel, formatEventMessage(ev, intel), intel.card);
    if (!sent) sent = await sendTelegramMessage(channel, formatEventMessage(ev, intel));
  }
  const hook = ev.reasoning?.socialHook;
  if (hook) {
    try { await publishThread([hook]); } catch { /* X optional */ }
  }
  return sent;
}

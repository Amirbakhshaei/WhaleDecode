// Channel alert formatter (ported from backend channel_formatter.py).
// Renders HTML for Telegram parse_mode=HTML. Strips raw hex so addresses/hashes
// never leak into trader-facing lines.

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

const HEX_TOKEN = /0x[0-9a-fA-F]{4,}(?:\.{2,}[0-9a-fA-F]{0,4})?/g;
const SPOILER_HEX = /\|\|0x[0-9a-fA-F]{4,}(?:\|{2}|[^|]*\|{2})/g;

function stripHex(text: string): string {
  return text
    .replace(SPOILER_HEX, "")
    .replace(HEX_TOKEN, "")
    .split("\n")
    .map((l) => l.split(/\s+/).join(" ").trim())
    .join("\n")
    .replace(/^\s*|\s*$/g, "")
    .replace(/^\|+|\|+$/g, "");
}

const EXPLORERS: Record<string, string> = {
  ethereum: "https://etherscan.io",
  arbitrum: "https://arbiscan.io",
  base: "https://basescan.org",
  bsc: "https://bscscan.com",
};

function explorer(chain: string): string {
  return EXPLORERS[chain.toLowerCase()] || "https://etherscan.io";
}

function truncateHash(tag: string): string {
  tag = String(tag);
  if (tag.length <= 12) return tag;
  return `${tag.slice(0, 6)}…${tag.slice(-4)}`;
}

function riskBadge(risk: number): string {
  if (risk >= 0.7) return "🔴 HIGH";
  if (risk >= 0.4) return "🟡 MODERATE";
  return "🟢 LOW";
}

export function buildAlertText(
  event: Record<string, unknown>,
  result: Record<string, unknown>,
  botUsername: string,
): string {
  const raw = (event.raw_json as Record<string, unknown>) || {};
  const chain = String(event.chain || "ETH").toLowerCase();
  const chainLabel = chain.charAt(0).toUpperCase() + chain.slice(1);
  const valueUsd = Number(raw.value_usd || 0);
  const asset = escapeHtml(String(raw.symbol || raw.symbol || "UNKNOWN"));
  const amount = Number(raw.amount || 0);
  const action = String(event.event_type || "TRANSFER").toUpperCase();
  const risk = Number(result.risk_score || 0);

  const profile = escapeHtml(stripHex(String(result.fundamental_summary || "High-value institutional entity.")));
  const context = escapeHtml(stripHex(String(result.technical_summary || "Off-exchange liquidity positioning.")));
  const impact = escapeHtml(stripHex(String(result.bias_summary || "Reduces immediate exchange-held supply.")));

  const from = String(raw.from || "");
  const to = String(raw.to || "");
  const tx = String(event.tx_hash || "");
  const fromLabel = from ? escapeHtml(truncateHash(from)) : "Unknown Wallet";
  const toLabel = to ? escapeHtml(truncateHash(to)) : "Unknown Wallet";
  const bot = botUsername.replace(/^@/, "") || "whaledecodebot";
  const trackLink = `https://t.me/${bot}?start=track_${from}`;
  const analyzeLink = `https://t.me/${bot}?start=analyze_${tx}`;

  const actionLine =
    chain === "ethereum"
      ? `👇 <b>WhaleDecode Platform Actions:</b>\n🕵️‍♂️ <a href="${trackLink}">Track This Entity</a> | 💬 <a href="${analyzeLink}">Ask AI About Tx</a>`
      : `👇 <b>WhaleDecode Platform Actions:</b>\n⚡ <a href="${trackLink}">Auto-Track Wallet</a> | 💬 <a href="${analyzeLink}">Deep Dive Tx</a>`;

  if (chain === "ethereum") {
    return (
      `🐋 <b>STRATEGIC ${action} | ${chainLabel}</b>\n` +
      `━━━━━━━━━━━━━━━━━━━━━━\n` +
      `💰 <b>Total Value:</b> <b>$${valueUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD</b>\n` +
      `🪙 <b>Asset:</b> ${asset}${amount ? ` (${amount.toLocaleString()} ${asset})` : ""}\n` +
      `🛣️ <b>Flow:</b> <code>${fromLabel}</code> ➔ <code>${toLabel}</code>\n` +
      `🎯 <b>Conviction Score:</b> ${Math.round(risk * 100)}/100\n\n` +
      `🧠 <b>Agentic Synthesis:</b>\n` +
      `• <b>Entity:</b> ${profile}\n` +
      `• <b>Context:</b> ${context}\n` +
      `• <b>Impact:</b> ${impact}\n\n` +
      `${actionLine}`
    );
  }

  return (
    `⚡ <b>SMART MONEY ${action} | ${chainLabel}</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━━━\n` +
    `💰 <b>Total Value:</b> <b>$${valueUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD</b>\n` +
    `🪙 <b>Asset:</b> ${asset}\n` +
    `🎯 <b>Conviction Score:</b> ${Math.round(risk * 100)}/100\n\n` +
    `🧠 <b>Agentic Synthesis:</b>\n` +
    `• <b>Profile:</b> ${profile}\n` +
    `• <b>Impact:</b> ${impact}\n\n` +
    `${actionLine}`
  );
}

export function buildBriefingText(summary: string): string {
  return (
    `🐋 <b>WhaleDecode Daily Briefing</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n` +
    escapeHtml(summary) +
    `\n\n<i>Not financial advice. DYOR.</i>`
  );
}

export { explorer };

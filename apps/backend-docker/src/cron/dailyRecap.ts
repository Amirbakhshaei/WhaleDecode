import { eventsSince, narrativeVelocity } from "../db.js";
import { publishThread, isXPublishEnabled } from "../services/twitterEngine.js";
import { sendTelegramMessage } from "../services/telegramBot.js";
import { telegramChannelId } from "../config.js";

export interface DailyRecap {
  generatedAt: string;
  windowHours: number;
  totalUsd: number;
  eventCount: number;
  topNarratives: Array<{ narrative: string; volume24h: number; volumePrev24h: number; velocityPct: number }>;
  topAccumulated: Array<{ assetSymbol: string; usdValue: number; entities: number }>;
  leaderboard: Array<{ label: string; chain: string; usdValue: number; events: number }>;
  threadText: string[];
}

export function buildRecap(nowMs: number): DailyRecap | null {
  const events = eventsSince(nowMs - 24 * 3600_000, nowMs);
  if (events.length === 0) return null;

  const byAsset = new Map<string, { usd: number; wallets: Set<string> }>();
  const byWallet = new Map<string, { label: string; chain: string; usd: number; events: number }>();
  for (const e of events) {
    if (e.action_type !== "transfer" && e.action_type !== "swap") continue;
    const a = byAsset.get(e.asset_symbol) ?? { usd: 0, wallets: new Set<string>() };
    a.usd += e.usd_value;
    a.wallets.add(e.wallet_address);
    byAsset.set(e.asset_symbol, a);
    const w = byWallet.get(e.wallet_address) ?? { label: e.wallet_label || e.wallet_address.slice(0, 10), chain: e.chain, usd: 0, events: 0 };
    w.usd += e.usd_value;
    w.events++;
    byWallet.set(e.wallet_address, w);
  }

  const topAccumulated = [...byAsset.entries()]
    .map(([assetSymbol, v]) => ({ assetSymbol, usdValue: Math.round(v.usd), entities: v.wallets.size }))
    .sort((x, y) => y.usdValue - x.usdValue)
    .slice(0, 3);

  const leaderboard = [...byWallet.values()]
    .map((v) => ({ label: v.label, chain: v.chain, usdValue: Math.round(v.usd), events: v.events }))
    .sort((x, y) => y.usdValue - x.usdValue)
    .slice(0, 5);

  const velocity = narrativeVelocity(nowMs).slice(0, 3);
  const fmtM = (n: number) => (n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : `$${(n / 1_000).toFixed(0)}K`);

  const threadText: string[] = [];
  if (topAccumulated.length > 0) {
    threadText.push(
      `While retail chased headlines, smart money moved ${fmtM(events.reduce((s, e) => s + e.usd_value, 0))} across ${events.length} tracked whale flows in 24h.\n\nTop accumulation:\n${topAccumulated.map((t, i) => `${i + 1}. ${t.assetSymbol} — ${fmtM(t.usdValue)} by ${t.entities} tier-1 entities`).join("\n")}\n\nBookmark this. 🧵`,
    );
  }
  if (velocity.length > 0) {
    threadText.push(
      `Narrative velocity, 24h vs prev 24h:\n${velocity.map((v) => `• ${v.narrative}: ${fmtM(v.volume24h)} (${v.velocityPct >= 0 ? "+" : ""}${v.velocityPct}%)`).join("\n")}\n\nRotation is visible before price moves.`,
    );
  }
  if (leaderboard.length > 0) {
    threadText.push(
      `24h smart money leaderboard:\n${leaderboard.map((l, i) => `${i + 1}. ${l.label} (${l.chain}) — ${fmtM(l.usdValue)}`).join("\n")}\n\nReal-time alerts on Telegram: @WhaleDecodeBot`,
    );
  }

  return {
    generatedAt: new Date(nowMs).toISOString(),
    windowHours: 24,
    totalUsd: Math.round(events.reduce((s, e) => s + e.usd_value, 0)),
    eventCount: events.length,
    topNarratives: velocity,
    topAccumulated,
    leaderboard,
    threadText,
  };
}

export async function runDailyRecap(nowMs = Date.now()): Promise<DailyRecap | null> {
  const recap = buildRecap(nowMs);
  if (!recap) return null;
  if (isXPublishEnabled() && recap.threadText.length > 0) {
    try { await publishThread(recap.threadText); } catch { /* X optional */ }
  }
  const channel = telegramChannelId();
  if (channel && recap.threadText.length > 0) {
    await sendTelegramMessage(channel, `<b>📊 Daily WhaleDecode Recap</b>\n\n${recap.threadText.join("\n\n—\n\n")}`);
  }
  return recap;
}

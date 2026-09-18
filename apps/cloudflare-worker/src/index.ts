import { Hono } from "hono";
import type { Env } from "./types";
import { alchemyRouter } from "./routes/alchemy";
import { heliusRouter } from "./routes/helius";
import { telegramRouter } from "./routes/telegram";

const app = new Hono<{ Bindings: Env }>();

app.get("/", (c) => c.text("WhaleDecode Edge Worker Live"));

app.route("/webhook/alchemy", alchemyRouter);
app.route("/webhook/helius", heliusRouter);
app.route("/webhook/telegram", telegramRouter);

app.notFound((c) =>
  c.json({ error: "not_found", path: c.req.path }, 404),
);

app.onError((err, c) => {
  console.error("worker_error", { message: String(err?.message ?? err) });
  return c.json(
    { error: "internal_error", message: String(err?.message ?? err) },
    500,
  );
});

export default app;

// ponytail: daily 24h leaderboard + link-free X hook (cron: 0 14 * * *)
export async function scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
  try {
    const rows = await env.DB.prepare("SELECT c.label, e.chain, e.asset_symbol, e.usd_value FROM candidate_events e LEFT JOIN curated_wallets c ON c.address = e.from_address WHERE e.created_at >= datetime('now', '-1 day') ORDER BY e.usd_value DESC LIMIT 5").all<{ label: string | null; chain: string; asset_symbol: string; usd_value: number }>();
    const top = rows.results ?? [];
    if (top.length === 0) return;
    const total = top.reduce((sum, r) => sum + (r.usd_value || 0), 0);
    const lines = top.map((r) => `• ${(r.label || "Whale").replace(/[<>&]/g, "")}: $${Math.round(r.usd_value).toLocaleString("en-US")} ${String(r.asset_symbol || "").replace(/[<>&]/g, "")} on ${r.chain}`).join("\n");
    const text = `While retail was panic-selling, smart money deployed $${(total / 1e6).toFixed(1)}M across ${top.length} narratives today. Complete on-chain flow breakdown:\n\n${lines}\n\nReal-time alerts: @WhaleDecodeBot`;
    const token = env.TELEGRAM_BOT_TOKEN || env.BOT_TOKEN;
    const chat = env.TELEGRAM_CHANNEL_ID || env.CHANNEL_CHAT_ID;
    if (token && chat) {
      ctx.waitUntil(fetch(`https://api.telegram.org/bot${token}/sendMessage`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_id: chat, text, link_preview_options: { is_disabled: true } }) }).then(() => undefined).catch((e) => console.error("rollup_failed", String(e))));
    }
  } catch (e) {
    console.error("scheduled_handler_failed", String(e));
  }
}

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

function escapeDigest(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

// ponytail: daily 24h rollup (cron: 0 14 * * *). Reports only what the query
// saw — deduped per token, distinct asset/chain counts, no invented retail
// behavior ("panic-selling") or "narratives" the rows don't contain.
async function scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
  try {
    const rows = await env.DB.prepare(
      "SELECT COALESCE(c2.label, c1.label, 'Whale') AS label, e.chain AS chain, e.asset_symbol AS asset_symbol, MAX(e.usd_value) AS usd_value FROM candidate_events e LEFT JOIN curated_wallets c1 ON c1.address = e.from_address LEFT JOIN curated_wallets c2 ON c2.address = e.to_address WHERE e.created_at >= datetime('now', '-1 day') AND e.status = 'accepted' GROUP BY e.chain, COALESCE(e.token_address, e.asset_symbol) ORDER BY usd_value DESC LIMIT 5",
    ).all<{ label: string | null; chain: string; asset_symbol: string; usd_value: number }>();
    const top = rows.results ?? [];
    if (top.length === 0) return;
    const total = top.reduce((sum, r) => sum + (r.usd_value || 0), 0);
    const assets = new Set(top.map((r) => (r.asset_symbol || "").toUpperCase())).size;
    const chains = new Set(top.map((r) => r.chain)).size;
    const lines = top.map((r) => `• ${escapeDigest(r.label || "Whale")} — <b>$${Math.round(r.usd_value).toLocaleString("en-US")}</b> ${escapeDigest(String(r.asset_symbol || ""))} on ${escapeDigest(r.chain)}`).join("\n");
    const text = `🐋 <b>Whale flows · last 24h</b>\n<b>$${(total / 1e6).toFixed(1)}M</b> across <b>${assets} asset${assets === 1 ? "" : "s"}</b> on <b>${chains} chain${chains === 1 ? "" : "s"}</b>:\n\n${lines}\n\n<i>Real-time alerts by @WhaleDecodeBot</i>`;
    const token = env.TELEGRAM_BOT_TOKEN || env.BOT_TOKEN;
    const chat = env.TELEGRAM_CHANNEL_ID || env.CHANNEL_CHAT_ID;
    if (token && chat) {
      ctx.waitUntil(fetch(`https://api.telegram.org/bot${token}/sendMessage`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_id: chat, text, parse_mode: "HTML", link_preview_options: { is_disabled: true } }) }).then(() => undefined).catch((e) => console.error("rollup_failed", String(e))));
    }
  } catch (e) {
    console.error("scheduled_handler_failed", String(e));
  }
}

export default {
  fetch: (request: Request, env: Env, ctx: ExecutionContext) => app.fetch(request, env, ctx),
  scheduled,
};

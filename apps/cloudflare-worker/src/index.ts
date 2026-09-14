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

// ponytail: Cloudflare Cron Trigger catch-up (* * * * *)
export async function scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
  // ponytail: 60s fallback poller — light RPC check if webhook heartbeats lapse
  try {
    const db = env.DB;
    const wallets = await db.prepare("SELECT address, chain FROM curated_wallets WHERE is_active = 1 LIMIT 10").all() as { results?: Array<{ address: string; chain: string }> };
    const targets = (wallets.results ?? []);
    if (targets.length === 0) return;
    const { multiFailoverFetch } = await import("./services/rpcRouter");
    const cfg = { primary: env.DRPC_URL || "https://ethereum-rpc.publicnode.com", backup: env.DRPC_URL_SECONDARY || env.DRPC_URL || "https://ethereum-rpc.publicnode.com", timeoutMs: 4000 };
    for (const w of targets) {
      try {
        // Lightweight block signature / balance check for curated address
        await multiFailoverFetch(cfg, { jsonrpc: "2.0", method: "eth_getBalance", params: [w.address, "latest"], id: 1 });
        // If succeeds, address is active; log for audit (no full event creation to keep lazy)
        console.log("scheduled_poll_ok", { address: w.address, chain: w.chain, cron: event.cron });
      } catch (e) {
        console.error("scheduled_poll_fail", { address: w.address, error: String(e) });
      }
    }
  } catch (e) {
    console.error("scheduled_handler_failed", String(e));
  }
}

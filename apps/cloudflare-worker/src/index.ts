import { Hono } from "hono";
import type { Env } from "./env";
import { alchemyWebhook } from "./routes/webhook";
import { handleScheduled } from "./scheduled";
import { loadConfig } from "./config";
import { drain } from "./pipeline";

const app = new Hono<{ Bindings: Env }>();

app.get("/", (c) => c.text("WhaleDecode Worker is running!"));

app.get("/health", (c) => c.json({ ok: true }));

app.post("/webhook/alchemy", alchemyWebhook);

// Manual backlog drain (e.g. triggered by a monitor or cron outside CF).
app.post("/drain", async (c) => {
  const cfg = loadConfig(c.env);
  const processed = await drain(c.env.DB, cfg, 20);
  return c.json({ ok: true, processed });
});

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<Response> {
    return app.fetch(request, env, ctx);
  },
  async scheduled(
    controller: ScheduledController,
    env: Env,
    _ctx: ExecutionContext,
  ): Promise<void> {
    await handleScheduled(controller, env);
  },
};

import { Hono } from "hono";
import type { Env } from "../types";
import { alchemyAuth, readBody } from "../middleware/auth";
import { processAlchemy } from "../services/pipeline";
import { logger } from "../utils/logger";

export const alchemyRouter = new Hono<{ Bindings: Env }>();

alchemyRouter.post("/", async (c) => {
  let raw: string;
  try {
    raw = await readBody(c.req.raw);
  } catch {
    return c.text("body_too_large", 413);
  }
  if (!await alchemyAuth(raw, c.req.header("x-alchemy-signature"), c.env)) {
    return c.text("invalid_signature", 401);
  }
  c.executionCtx.waitUntil(processAlchemy(raw, c.env).catch((e) => logger.error("alchemy_pipeline_failed", { stage: "INGRESS", error: String(e) })));
  logger.info("WEBHOOK_INGRESS_RECEIVED", { stage: "INGRESS", ip: c.req.header("cf-connecting-ip") ?? undefined });
  return c.text("EVENT_ACKNOWLEDGED", 200);
});

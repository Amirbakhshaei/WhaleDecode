import { timingSafeEqual } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";

export const PORT = Number(process.env.PORT ?? 8787);
export const DB_PATH = process.env.DB_PATH ?? "./data/core.db";

export function xPublishEnabled(): boolean {
  return process.env.X_PUBLISH_ENABLED === "true";
}

export function telegramBotToken(): string {
  return process.env.TELEGRAM_BOT_TOKEN ?? "";
}

export function telegramChannelId(): string {
  return process.env.TELEGRAM_CHANNEL_ID ?? "";
}

export function deepEngineSecret(): string {
  return process.env.DEEP_ENGINE_SECRET ?? "";
}

export function bearerAuth(req: IncomingMessage, res: ServerResponse): boolean {
  const secret = deepEngineSecret();
  const expected = Buffer.from(`Bearer ${secret}`);
  const got = Buffer.from(req.headers.authorization ?? "");
  const ok = secret.length > 0 && expected.length === got.length && timingSafeEqual(expected, got);
  if (!ok) {
    res.writeHead(401, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "unauthorized" }));
  }
  return ok;
}

export function json(res: ServerResponse, status: number, payload: unknown): void {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

import http from "node:http";
import { initDb } from "./db.js";
import { PORT, json, bearerAuth } from "./config.js";
import { handleEvent, handleRecap } from "./routes.js";
import { startRecapCron } from "./cron/dailyRecapCron.js";

export function createServer(): http.Server {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const chunks: Buffer[] = [];
    for await (const c of req) chunks.push(c as Buffer);
    const body = Buffer.concat(chunks).toString("utf8");
    try {
      if (req.method === "GET" && url.pathname === "/health") {
        return json(res, 200, { ok: true, uptime: process.uptime() });
      }
      if (req.method === "POST" && url.pathname === "/internal/events") {
        if (!bearerAuth(req, res)) return;
        return await handleEvent(req, res, body);
      }
      if (req.method === "POST" && url.pathname === "/internal/recap") {
        if (!bearerAuth(req, res)) return;
        return await handleRecap(req, res, body);
      }
      return json(res, 404, { error: "not found" });
    } catch (err) {
      return json(res, 500, { error: err instanceof Error ? err.message : "internal error" });
    }
  });
}

export function main(): void {
  initDb(process.env.DB_PATH ?? "./data/core.db");
  startRecapCron();
  createServer().listen(PORT, () => console.log(`whaledecode-core listening on :${PORT}`));
  for (const sig of ["SIGINT", "SIGTERM"] as const) {
    process.on(sig, () => process.exit(0));
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();

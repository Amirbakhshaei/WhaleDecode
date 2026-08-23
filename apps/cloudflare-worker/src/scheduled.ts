import type { ScheduledController } from "@cloudflare/workers-types";
import type { Env } from "./env";
import { loadConfig } from "./config";
import * as repo from "./db";
import { drain } from "./pipeline";
import { generateBriefing } from "./llm";
import { TelegramClient } from "./telegram";
import { buildBriefingText } from "./format";

const DAY = 86400;

export async function handleScheduled(
  controller: ScheduledController,
  env: Env,
): Promise<void> {
  const cfg = loadConfig(env);
  const db = env.DB;
  const now = Math.floor(Date.now() / 1000);

  switch (controller.cron) {
    case "*/5 * * * *":
      await drain(db, cfg, 20);
      break;

    case "0 3 * * *":
      await repo.purgeStale(db, now - 3 * DAY);
      break;

    case "0 8 * * *": {
      const events = await repo.listRecentPublished(db, now - DAY, 20);
      if (!events.length) break;
      const summary = await generateBriefing(
        events.map((e) => ({
          chain: e.chain,
          score: e.score,
          raw_json: e.raw_json,
        })),
        cfg,
      );
      if (cfg.channelPublishEnabled && cfg.channelChatId) {
        const tg = new TelegramClient(cfg);
        await tg.sendMessage(cfg.channelChatId, buildBriefingText(summary));
      }
      break;
    }
  }
}

import type { Env } from "../types";

export async function claimCooldown(env: Env, chain: string, address: string, key: string): Promise<boolean> {
  const result = await env.DB.prepare("INSERT OR IGNORE INTO whale_cooldowns (chain, address, day, event_key) VALUES (?, ?, date('now'), ?)").bind(chain, address, key).run();
  if (result.meta.changes > 0) return true;
  const existing = await env.DB.prepare("SELECT event_key FROM whale_cooldowns WHERE chain = ? AND address = ? AND day = date('now')").bind(chain, address).first<{ event_key: string }>();
  return existing?.event_key === key;
}

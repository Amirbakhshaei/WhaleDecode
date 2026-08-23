import type { D1Database } from "@cloudflare/workers-types";
import type { CuratedWallet } from "./types";

export async function findCuratedWallet(
  db: D1Database,
  address: string,
): Promise<CuratedWallet | null> {
  const row = await db
    .prepare(
      "SELECT address, chain, label, tags FROM curated_wallets WHERE address = ? AND is_active = 1 LIMIT 1",
    )
    .bind(address.toLowerCase())
    .first<CuratedWallet>();
  return row ?? null;
}

export async function addTrackedWallet(
  db: D1Database,
  userId: number,
  address: string,
  chain?: string,
): Promise<void> {
  await db
    .prepare(
      "INSERT OR IGNORE INTO tracked_wallets (user_id, address, chain) VALUES (?, ?, ?)",
    )
    .bind(userId, address.toLowerCase(), chain ?? null)
    .run();
}

export async function removeTrackedWallet(
  db: D1Database,
  userId: number,
  address: string,
): Promise<void> {
  await db
    .prepare("DELETE FROM tracked_wallets WHERE user_id = ? AND address = ?")
    .bind(userId, address.toLowerCase())
    .run();
}

export async function listTrackedWallets(
  db: D1Database,
  userId: number,
): Promise<{ address: string; chain: string | null }[]> {
  const res = await db
    .prepare(
      "SELECT address, chain FROM tracked_wallets WHERE user_id = ? ORDER BY id DESC",
    )
    .bind(userId)
    .all<{ address: string; chain: string | null }>();
  return res.results ?? [];
}

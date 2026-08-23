-- WhaleDecode D1 schema for the Cloudflare Worker edge gateway.
-- SQLite notes:
--  * INTEGER PRIMARY KEY AUTOINCREMENT (no SERIAL).
--  * Unix-second timestamps via strftime('%s','now').

CREATE TABLE IF NOT EXISTS curated_wallets (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  address    TEXT NOT NULL,
  chain      TEXT NOT NULL,
  label      TEXT NOT NULL DEFAULT '',
  tags       TEXT NOT NULL DEFAULT '[]',
  is_active  INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_curated_addr_chain ON curated_wallets(address, chain);

CREATE TABLE IF NOT EXISTS tracked_wallets (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  address    TEXT NOT NULL,
  chain      TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tracked_user_addr ON tracked_wallets(user_id, address);

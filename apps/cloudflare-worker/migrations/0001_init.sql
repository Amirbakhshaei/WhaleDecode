-- WhaleDecode D1 schema (ported from backend Postgres models).
-- SQLite notes:
--  * Use INTEGER PK AUTOINCREMENT (no SERIAL).
--  * Timestamps are unix seconds via strftime('%s','now').
--  * Dedupe via UNIQUE(dedupe_key) + INSERT OR IGNORE.
--  * No FOR UPDATE SKIP LOCKED: claim uses UPDATE ... WHERE id = (SELECT ...) RETURNING.

CREATE TABLE IF NOT EXISTS curated_wallets (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  address    TEXT NOT NULL,
  chain      TEXT NOT NULL,
  label      TEXT NOT NULL DEFAULT '',
  tags       TEXT NOT NULL DEFAULT '[]',
  is_active  INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_curated_addr_chain ON curated_wallets(address, chain);

CREATE TABLE IF NOT EXISTS candidate_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet_id     INTEGER,
  chain         TEXT NOT NULL,
  tx_hash       TEXT NOT NULL,
  log_index     INTEGER NOT NULL DEFAULT 0,
  block_number  INTEGER NOT NULL DEFAULT 0,
  event_type    TEXT NOT NULL DEFAULT 'TRANSFER',
  raw_json      TEXT NOT NULL DEFAULT '{}',
  score         REAL NOT NULL DEFAULT 0,
  dedupe_key    TEXT NOT NULL UNIQUE,
  status        TEXT NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  published_at  INTEGER,
  campaign_id   INTEGER,
  created_at    INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  updated_at    INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_ce_status ON candidate_events(status, created_at);

CREATE TABLE IF NOT EXISTS campaigns (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet_id         INTEGER,
  chain             TEXT,
  first_event_id    INTEGER,
  telegram_message_id INTEGER,
  window_start      INTEGER,
  created_at        INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger_type TEXT,
  trigger_ref_id INTEGER,
  graph_name   TEXT,
  status       TEXT,
  input_json   TEXT,
  output_json  TEXT,
  latency_ms    INTEGER,
  created_at   INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  admin_id   INTEGER NOT NULL DEFAULT 0,
  action     TEXT,
  target_type TEXT,
  target_id  TEXT,
  diff_json  TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

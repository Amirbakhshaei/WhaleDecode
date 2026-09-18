-- Core D1 schema for WhaleDecode Edge (Cloudflare Worker)
-- ponytail: minimal tables matching backend db models + indices from spec

CREATE TABLE IF NOT EXISTS curated_wallets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  address TEXT NOT NULL,
  chain TEXT NOT NULL DEFAULT 'ETH',
  label TEXT,
  category TEXT,
  quality_score REAL DEFAULT 0.0,
  tier TEXT DEFAULT 'tier1',
  is_active INTEGER DEFAULT 1,
  is_exchange INTEGER DEFAULT 0,
  is_mev INTEGER DEFAULT 0,
  tags TEXT DEFAULT '',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (address, chain)
);

CREATE TABLE IF NOT EXISTS tracked_wallets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  address TEXT NOT NULL,
  chain TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, address, chain)
);

CREATE TABLE IF NOT EXISTS candidate_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT UNIQUE,
  chain TEXT NOT NULL,
  tx_hash TEXT NOT NULL,
  log_index INTEGER DEFAULT 0,
  from_address TEXT DEFAULT '',
  to_address TEXT DEFAULT '',
  asset_symbol TEXT DEFAULT '',
  token_address TEXT,
  raw_value REAL DEFAULT 0,
  event_type TEXT,
  action_type TEXT,
  raw_json TEXT,
  value_usd REAL DEFAULT 0.0,
  usd_value REAL DEFAULT 0.0,
  score REAL DEFAULT 0.0,
  conviction REAL DEFAULT 0.0,
  status TEXT DEFAULT 'pending',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (chain, tx_hash, log_index)
);

CREATE TABLE IF NOT EXISTS wallet_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  address TEXT NOT NULL,
  chain TEXT NOT NULL DEFAULT 'ETH',
  profile_json TEXT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (address, chain)
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT UNIQUE,
  user_id INTEGER,
  chain TEXT,
  tx_hash TEXT,
  title TEXT,
  headline TEXT,
  intent TEXT,
  narrative TEXT,
  reasoning TEXT,
  social_hook TEXT,
  body_text TEXT,
  severity TEXT DEFAULT 'medium',
  telegram_sent INTEGER DEFAULT 0,
  x_posted INTEGER DEFAULT 0,
  published_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  delivered_at DATETIME
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_chat_id INTEGER UNIQUE,
  tier TEXT DEFAULT 'free',
  quota_remaining INTEGER DEFAULT 10,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_type TEXT,
  payload_json TEXT,
  result_json TEXT,
  duration_ms INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indices required by spec (step 2)
CREATE INDEX IF NOT EXISTS idx_candidate_events_tx_chain ON candidate_events (tx_hash, chain);
CREATE INDEX IF NOT EXISTS idx_curated_wallets_addr_chain ON curated_wallets (address, chain);
CREATE INDEX IF NOT EXISTS idx_alerts_published ON alerts (published_at);
CREATE INDEX IF NOT EXISTS idx_tracked_wallets_user ON tracked_wallets (user_id);
CREATE TABLE IF NOT EXISTS blacklisted_addresses (
  address TEXT PRIMARY KEY,
  reason TEXT,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_blacklist_addr ON blacklisted_addresses(address);

CREATE INDEX IF NOT EXISTS idx_wallet_profiles_addr_chain ON wallet_profiles (address, chain);
CREATE INDEX IF NOT EXISTS idx_events_usd_val ON candidate_events(usd_value DESC);
CREATE INDEX IF NOT EXISTS idx_events_created ON candidate_events(created_at);

-- Edge idempotency + per-wallet daily cooldown + delivery ledger
CREATE TABLE IF NOT EXISTS whale_cooldowns (
  chain TEXT NOT NULL,
  address TEXT NOT NULL,
  day TEXT NOT NULL,
  event_key TEXT NOT NULL,
  PRIMARY KEY (chain, address, day)
);

CREATE TABLE IF NOT EXISTS alert_deliveries (
  event_key TEXT NOT NULL,
  destination TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'sending',
  message_id INTEGER,
  PRIMARY KEY (event_key, destination)
);

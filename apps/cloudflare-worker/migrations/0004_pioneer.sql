-- Pioneer reconciliation: tier + spec tables (self-contained for migration path).
ALTER TABLE curated_wallets ADD COLUMN tier TEXT DEFAULT 'tier1';
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_idem ON candidate_events(idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_idem ON alerts(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_candidate_events_tx_chain ON candidate_events (tx_hash, chain);
CREATE INDEX IF NOT EXISTS idx_events_usd_val ON candidate_events(usd_value DESC);
CREATE INDEX IF NOT EXISTS idx_events_created ON candidate_events(created_at);

-- Phase 1 hardening: add blacklist table + curated_wallets flags
-- ponytail: minimal D1 migration; applies to whaledecode_db

ALTER TABLE curated_wallets ADD COLUMN is_exchange INTEGER DEFAULT 0;
ALTER TABLE curated_wallets ADD COLUMN is_mev INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS blacklisted_addresses (
  address TEXT PRIMARY KEY,
  reason TEXT,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_blacklisted_address ON blacklisted_addresses(address);

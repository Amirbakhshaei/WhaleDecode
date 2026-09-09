-- Solana pipeline support: Base58 pubkeys (32-44 chars), 88-char signatures,
-- SPL token delta accounting, and Solana-specific profile metrics.

ALTER TABLE curated_wallets ALTER COLUMN address TYPE VARCHAR(64);
ALTER TABLE wallet_profiles ALTER COLUMN address TYPE VARCHAR(64);
ALTER TABLE onchain_events ALTER COLUMN tx_hash TYPE VARCHAR(128);

ALTER TABLE wallet_profiles
    ADD COLUMN IF NOT EXISTS sol_primary_dex VARCHAR(32),
    ADD COLUMN IF NOT EXISTS pump_fun_snipes INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS jito_tip_frequency FLOAT DEFAULT 0.0;

-- Add missing columns from schema reference to curated_wallets
ALTER TABLE curated_wallets ADD COLUMN category TEXT DEFAULT '';
ALTER TABLE curated_wallets ADD COLUMN quality_score REAL DEFAULT 0.0;

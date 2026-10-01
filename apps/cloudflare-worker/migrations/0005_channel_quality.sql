-- Channel quality: token-level dedupe + rollup support (one headline per token/hour).
CREATE INDEX IF NOT EXISTS idx_candidate_token_time ON candidate_events(chain, token_address, created_at);
CREATE INDEX IF NOT EXISTS idx_candidate_status_time ON candidate_events(status, created_at);

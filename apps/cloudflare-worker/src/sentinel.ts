// Sentinel pre-score (ported from backend domain/policies/sentinel.py).
// Now receives a REAL value_usd (priced at ingestion) so whales actually score.

export const WHALE_TRANSFER_THRESHOLD_USD = 100_000;
export const WHALE_SWAP_THRESHOLD_USD = 50_000;
export const SUPER_WHALE_TRANSFER_THRESHOLD_USD = 50_000_000;
export const CURATED_WALLET_BONUS = 10;

export function scoreBaseValue(usdValue: number): number {
  if (usdValue >= SUPER_WHALE_TRANSFER_THRESHOLD_USD) return 60;
  if (usdValue >= 10_000_000) return 50;
  if (usdValue >= 1_000_000) return 45;
  if (usdValue >= WHALE_TRANSFER_THRESHOLD_USD) return 35;
  return 0;
}

export interface SentinelInput {
  event_type: string;
  value_usd: number;
  wallet_id: number;
  curated_wallet_ids: Set<number>;
  recent_count?: number;
  wallets_in_tx?: number;
}

export function sentinelScore(e: SentinelInput): number {
  let score = 0;
  if (e.event_type === "TRANSFER") score += scoreBaseValue(e.value_usd);
  if (e.event_type === "SWAP" && e.value_usd >= WHALE_SWAP_THRESHOLD_USD) score += 35;
  if (e.event_type === "CONTRACT_INTERACTION") score += 20;
  if (e.event_type === "APPROVE" && e.value_usd >= 1_000_000) score += 15;
  if (e.curated_wallet_ids.has(e.wallet_id)) score += CURATED_WALLET_BONUS;
  if ((e.recent_count ?? 0) >= 3) score += 25;
  else if ((e.recent_count ?? 0) >= 2) score += 10;
  if ((e.wallets_in_tx ?? 0) >= 2) score += 30;
  return Math.min(score, 100);
}

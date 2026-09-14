// ponytail: domain math from conviction.py + scoring.py; no I/O
export const POOL_IMPACT_FLAG_THRESHOLD = 0.015;
export const COORDINATION_WINDOW_MINUTES = 60;
export const COORDINATION_MIN_WALLETS = 2;
export const BASE_CONVICTION_SCORE = 30;
export const WIN_RATE_BONUS = 20;
export const SYNDICATE_BONUS = 40;
export const MEV_PENALTY = 100;
export const MAX_CONVICTION_SCORE = 100;

export const TIER_THRESHOLDS: Record<string, number> = {
  free: 0.70,
  pro: 0.55,
  whale: 0.40,
};

export function poolImpactRatio(tradeUsd: number, poolTvlUsd: number): number {
  if (poolTvlUsd <= 0) return 0.0;
  return Math.abs(tradeUsd) / poolTvlUsd;
}

export function calculateAlertWorthiness(
  confidence: number,
  noveltyScore: number,
  walletQuality: number,
  eventTypeWeight: number,
  marketContextBoost = 0.0,
): number {
  const base = 0.30 * confidence + 0.25 * noveltyScore + 0.25 * walletQuality + 0.15 * eventTypeWeight + 0.05 * marketContextBoost;
  return Math.max(0.0, Math.min(1.0, base));
}

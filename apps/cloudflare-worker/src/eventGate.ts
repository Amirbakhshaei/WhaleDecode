// Event gate: the mandatory whale floor (ported from backend domain/services/event_gate.py).
// Unlike the backend worker, the CF pipeline prices events at ingestion, so
// value_usd is real here and the floor actually lets whales through.

export const MIN_WHALE_THRESHOLD_USD = 50_000;
export const MIN_INVESTIGATION_SCORE = 65; // 0.65 sentinel score
export const CHANNEL_MIN_SCORE = 50;
export const CHANNEL_MIN_VALUE_USD = 50_000;

export interface GateInput {
  score: number; // sentinel score 0..100
  valueUsd: number;
}

/** Pre-LLM gate: event must clear the $50k floor AND a 65 sentinel score. */
export function shouldInvestigate(input: GateInput): boolean {
  if (!(input.valueUsd >= MIN_WHALE_THRESHOLD_USD)) return false;
  if (input.score < MIN_INVESTIGATION_SCORE) return false;
  return true;
}

/** Channel publish floor (after investigation). */
export function passesChannelFloor(
  riskScore: number, // 0..1
  valueUsd: number,
): boolean {
  if (valueUsd < CHANNEL_MIN_VALUE_USD) return false;
  if (riskScore * 100 < CHANNEL_MIN_SCORE) return false;
  return true;
}

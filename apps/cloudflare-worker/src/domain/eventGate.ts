// ponytail: deterministic pre-LLM filter; keeps $50k floor from event_gate.py
export const MIN_WHALE_THRESHOLD_USD = 50_000.0;
export const DEFAULT_INVESTIGATION_FLOOR_USD = 25_000.0;
import { getPriceUsdc } from "../services/priceOracle";

export const STABLECOINS = new Set(["USDC","USDT","DAI","FRAX","TUSD","USDP","FDUSD"]);

export interface CandidateEvent {
  chain: string;
  raw_json: Record<string, unknown>;
}

export async function computeUsdValue(candidate: CandidateEvent, unitPrice = 0.0): Promise<number> {
  const raw = candidate.raw_json || {};
  const tokenAmount = Number((raw as any).token_amount ?? (raw as any).amount ?? 0);
  const asset = String((raw as any).asset ?? (raw as any).symbol ?? (raw as any).tokenSymbol ?? "").toUpperCase();
  if (unitPrice > 0.0) return tokenAmount * unitPrice;
  if (STABLECOINS.has(asset)) return tokenAmount;
  const price = await getPriceUsdc(asset);
  if (price > 0.0) return tokenAmount * price;
  const prior = Number((raw as any).value_usd ?? 0.0);
  return prior || 0.0;
}

export async function passesGate(candidate: CandidateEvent, unitPrice = 0.0): Promise<boolean> {
  const val = await computeUsdValue(candidate, unitPrice);
  return val >= MIN_WHALE_THRESHOLD_USD;
}

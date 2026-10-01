export type Chain = "ethereum" | "arbitrum" | "base" | "solana";
// ponytail: single source of truth for publish floors — mirrors backend
// alert_policy.py ($500k ETH / $75k ARB / $30k BASE). The old flat $50k let
// $54k treasury dust through as HIGH-IMPACT.
export const MIN_USD = 50_000;
export const CHAIN_MIN_USD: Record<Chain, number> = {
  ethereum: 500_000,
  arbitrum: 75_000,
  base: 30_000,
  solana: 50_000,
};
export function chainMinUsd(chain: string): number {
  return CHAIN_MIN_USD[(chain as Chain).toLowerCase() as Chain] ?? MIN_USD;
}
// LLM conviction below this never broadcasts — a 45% coin-flip is not alpha.
export const MIN_CONFIDENCE_TO_PUBLISH = 0.7;
// Same token re-alert suppression (the 2x ALPHA double-post).
export const TOKEN_DEDUPE_WINDOW_SEC = 3600;
// DexScreener pairs thinner than this are unreliable for pricing (fake ALPHA pools).
export const MIN_LIQUIDITY_USD = 25_000;
// Treasury/cold/internal wallets are ops, not market alpha (unless swapping).
export const TREASURY_KEYWORDS = [
  "treasury",
  "dao",
  "vault",
  "reserve",
  "custody",
  "multisig",
  "foundation",
  "comptroller",
  "governance",
  "cold",
  "storage",
];
export function isTreasuryLike(label: string, category: string): boolean {
  const text = `${label} ${category}`.toLowerCase();
  return TREASURY_KEYWORDS.some((k) => text.includes(k));
}
export const MAX_BODY_BYTES = 1_048_576;
export const NETWORKS: Record<string, Chain> = { ETH_MAINNET: "ethereum", ARB_MAINNET: "arbitrum", BASE_MAINNET: "base" };
export function normalizeAddress(address: string, chain: Chain): string {
  return chain === "solana" ? address : address.toLowerCase();
}
export function validAddress(address: string, chain: Chain): boolean {
  return chain === "solana" ? /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address) : /^0x[a-fA-F0-9]{40}$/.test(address);
}
export interface Wallet {
  address: string;
  chain: Chain;
  label: string;
  category: string;
}
export interface Flow {
  idempotencyKey: string;
  chain: Chain;
  txHash: string;
  logIndex: number;
  fromAddress: string;
  toAddress: string;
  assetSymbol: string;
  tokenAddress?: string;
  amount: number;
  usdValue: number;
  actionType: "TRANSFER" | "SWAP" | "STAKE" | "UNSTAKE";
  wallet: Wallet;
  enrichment: { priceUsd: number; liquidityUsd?: number; volume24h?: number; fdv?: number };
  reasoning?: Thesis;
}
export interface Thesis {
  headline: string;
  intent: "ACCUMULATION" | "DISTRIBUTION" | "FARMING" | "ROTATION" | "INTERNAL" | "TRANSFER";
  narrative: "AI" | "RWA" | "DeFi" | "Meme" | "Layer 2" | "Macro" | "Internal";
  analysis: string;
  confidenceScore: number;
  socialHook: string;
}

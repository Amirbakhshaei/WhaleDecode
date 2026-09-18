export type Chain = "ethereum" | "arbitrum" | "base" | "solana";
export const MIN_USD = 50_000;
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
  intent: "ACCUMULATION" | "DISTRIBUTION" | "FARMING" | "ROTATION";
  narrative: "AI" | "RWA" | "DeFi" | "Meme" | "Layer 2" | "Macro";
  analysis: string;
  confidenceScore: number;
  socialHook: string;
}

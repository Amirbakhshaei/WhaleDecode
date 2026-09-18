import type { IncomingMessage, ServerResponse } from "node:http";

export type Chain = "ethereum" | "arbitrum" | "base" | "solana";

export interface WalletMeta {
  address: string;
  label: string;
  category: string;
  chain: Chain;
}

export interface Enrichment {
  priceUsd: number;
  liquidityUsd?: number;
  volume24h?: number;
  fdv?: number;
}

export interface Reasoning {
  headline: string;
  intent: string;
  narrative: string;
  analysis: string;
  confidenceScore: number;
  socialHook?: string;
}

export interface WorkerEvent {
  idempotencyKey: string;
  chain: Chain;
  txHash: string;
  logIndex: number;
  fromAddress: string;
  toAddress: string;
  assetSymbol: string;
  tokenAddress?: string;
  amount: string | number;
  usdValue: number;
  actionType: string;
  wallet: WalletMeta;
  enrichment: Enrichment;
  reasoning?: Reasoning;
}

export interface HandlerCtx {
  req: IncomingMessage;
  res: ServerResponse;
  url: URL;
  body: string;
}

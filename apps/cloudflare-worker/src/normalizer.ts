import type { PriceOracle } from "./priceOracle";

export const TRANSFER_EVENT_SIGNATURE =
  "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";

export interface AlchemyEvent {
  network?: string;
  fromAddress?: string;
  toAddress?: string;
  category?: string;
  asset?: string;
  value?: string;
  contractAddress?: string;
  blockNumber?: string;
  hash?: string;
  logIndex?: string;
  rawContract?: { decimals?: number; symbol?: string; name?: string };
  log?: { address?: string; topics?: string[]; data?: string };
  [key: string]: unknown;
}

export interface CandidateInsert {
  wallet_id: number;
  chain: string;
  tx_hash: string;
  log_index: number;
  block_number: number;
  event_type: string;
  value_usd: number;
  raw_json: Record<string, unknown>;
  dedupe_key: string;
  score: number;
}

const NETWORK_MAP: Record<string, string> = {
  ETH_MAINNET: "ethereum",
  ETH: "ethereum",
  ARB_MAINNET: "arbitrum",
  ARBITRUM: "arbitrum",
  BASE_MAINNET: "base",
  BASE: "base",
};

export function mapNetwork(network: string | undefined): string {
  if (!network) return "ethereum";
  return NETWORK_MAP[network.toUpperCase()] || network.toLowerCase();
}

function toNumber(v: string | number | undefined): number {
  if (v === undefined || v === null) return 0;
  if (typeof v === "number") return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

/** Build a priced candidate_event row from an Alchemy TRANSFER webhook event. */
export async function normalizeAlchemyEvent(
  event: AlchemyEvent,
  walletId: number,
  oracle: PriceOracle,
): Promise<CandidateInsert | null> {
  const chain = mapNetwork(event.network);
  const txHash = event.hash || "";
  const logIndex = toNumber(event.logIndex);
  const blockNumber = toNumber(event.blockNumber);
  const contract = (event.contractAddress || event.log?.address || "").toLowerCase();
  const decimals = toNumber(event.rawContract?.decimals) || 18;
  const rawValue = event.value || "0";
  const tokenAmount = toNumber(rawValue); // base units
  const from = (event.fromAddress || "").toLowerCase();
  const to = (event.toAddress || "").toLowerCase();
  const symbol = (event.rawContract?.symbol || event.asset || "UNKNOWN").toUpperCase();

  if (!txHash || !contract) return null;

  const { valueUsd } = await oracle.priceTransfer(contract, chain, tokenAmount, decimals);

  const raw_json: Record<string, unknown> = {
    address: contract,
    from,
    to,
    value: rawValue,
    decimals,
    symbol,
    asset: symbol,
    token: symbol,
    amount: tokenAmount / 10 ** decimals,
    value_usd: valueUsd,
    tx_hash: txHash,
    log_index: logIndex,
    block_number: blockNumber,
    topics: event.log?.topics || [],
    data: event.log?.data || "0x0",
  };

  return {
    wallet_id: walletId,
    chain,
    tx_hash: txHash,
    log_index: logIndex,
    block_number: blockNumber,
    event_type: "TRANSFER",
    value_usd: valueUsd,
    raw_json,
    dedupe_key: `${walletId}:${txHash}:${logIndex}`,
    score: 0,
  };
}

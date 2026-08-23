// USD pricing for on-chain tokens via DeFiLlama + CoinGecko.
// Ported from backend adapters/pricing/oracle.py. Crucially, this is wired into
// BOTH ingestion and the publish gate here — the backend forgot to pass the
// oracle to the worker, which is why every event was silently skipped.

const DEFILLAMA_PRICE_URL =
  "https://coins.llama.fi/prices/current/{chain_id}:{contract_address}";
const DEFILLAMA_HISTORICAL_URL =
  "https://coins.llama.fi/prices/historical/{unix_ts}/{chain_id}:{contract_address}";
const COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list";

const CHAIN_TO_DEFILLAMA: Record<string, string> = {
  ethereum: "ethereum",
  eth: "ethereum",
  mainnet: "ethereum",
  bsc: "bsc",
  bnb: "bsc",
  polygon: "polygon",
  matic: "polygon",
  arbitrum: "arbitrum",
  arbitrum_one: "arbitrum",
  base: "base",
  avalanche: "avax",
  avax: "avalanche",
  optimism: "optimism",
  op: "optimism",
};

const STABLECOINS = new Set([
  "USDC", "USDT", "DAI", "FRAX", "TUSD", "USDP", "FDUSD", "USDE", "USDS",
]);

interface PriceCacheEntry {
  price: number;
  symbol: string;
}

export class PriceOracle {
  constructor(
    private kv: KVNamespace,
    private fetchFn: typeof fetch = fetch,
    private ttlSeconds = 300,
  ) {}

  async getPriceUsd(contract: string, chain: string): Promise<number> {
    const [price, symbol] = await this.priced(contract, chain);
    // Stablecoins without a price feed are treated as $1.
    if (price === 0 && symbol && STABLECOINS.has(symbol.toUpperCase())) return 1;
    return price;
  }

  async getSymbol(contract: string, chain: string): Promise<string> {
    const [, symbol] = await this.priced(contract, chain);
    return symbol;
  }

  private async priced(
    contract: string,
    chain: string,
  ): Promise<[number, string]> {
    contract = (contract || "").trim().toLowerCase();
    if (!contract) return [0, ""];
    const key = `px:${chain.toLowerCase()}:${contract}`;
    const cached = await this.kv.get(key);
    if (cached) {
      try {
        const e = JSON.parse(cached) as PriceCacheEntry;
        return [e.price, e.symbol];
      } catch {
        /* fall through */
      }
    }
    const chainId = CHAIN_TO_DEFILLAMA[chain.toLowerCase()];
    if (!chainId) return [0, ""];
    try {
      const url = DEFILLAMA_PRICE_URL.replace("{chain_id}", chainId).replace(
        "{contract_address}",
        contract,
      );
      const res = await this.fetchFn(url);
      if (!res.ok) return [0, ""];
      const payload = (await res.json()) as {
        coins?: Record<string, { price?: number; symbol?: string }>;
      };
      const coin = payload.coins?.[`${chainId}:${contract}`];
      if (!coin) return [0, ""];
      let price = Number(coin.price || 0);
      const symbol = String(coin.symbol || "").toUpperCase();
      if (symbol && STABLECOINS.has(symbol)) price = 1;
      const entry: PriceCacheEntry = { price, symbol };
      await this.kv.put(key, JSON.stringify(entry), {
        expirationTtl: this.ttlSeconds,
      });
      return [price, symbol];
    } catch {
      return [0, ""];
    }
  }

  /** Price a token transfer amount to USD. Returns 0 when price is unknown. */
  async priceTransfer(
    contract: string,
    chain: string,
    tokenAmount: number,
    decimals: number,
  ): Promise<{ valueUsd: number; symbol: string }> {
    const unit = await this.getPriceUsd(contract, chain);
    const symbol = await this.getSymbol(contract, chain);
    if (unit <= 0) return { valueUsd: 0, symbol };
    return { valueUsd: (tokenAmount / 10 ** decimals) * unit, symbol };
  }
}

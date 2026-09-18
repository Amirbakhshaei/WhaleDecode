import type { Chain, Flow } from "../config/constants";

const STABLES: Record<string, Record<string, string>> = {
  ethereum: {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0xdc035d45d973e3ec169d2276ddab16f1e407384f": "USDS",
    "0x6c3ea9036406852006290770bedfcaba0e23a0e8": "PYUSD",
  },
  arbitrum: { "0xaf88d065e77c8cc2239327c5edb3a432268e5831": "USDC", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": "USDT" },
  base: { "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC" },
  solana: { "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC", "Es9vMFrzaCERmJfrF4H2FYD9aJg7qAWMZFPb5gV8kX7": "USDT" },
};

export async function enrich(chain: Chain, symbol: string, token?: string): Promise<Flow["enrichment"] | null> {
  const address = chain === "solana" ? token : token?.toLowerCase();
  if (address && STABLES[chain]?.[address] === symbol.toUpperCase()) return { priceUsd: 1 };
  try {
    if (address) {
      const response = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${encodeURIComponent(address)}`, { signal: AbortSignal.timeout(2500) });
      if (!response.ok) return null;
      const data = await response.json() as { pairs?: Array<{ chainId: string; baseToken?: { address: string }; priceUsd?: string; liquidity?: { usd: number }; volume?: { h24: number }; fdv?: number }> };
      const pairs = (data.pairs ?? []).filter((pair) => pair.chainId === chain && (chain === "solana" ? pair.baseToken?.address : pair.baseToken?.address.toLowerCase()) === address && Number(pair.priceUsd) > 0);
      pairs.sort((a, b) => (b.liquidity?.usd ?? 0) - (a.liquidity?.usd ?? 0));
      const pair = pairs[0];
      if (!pair || !Number.isFinite(Number(pair.priceUsd))) return null;
      return { priceUsd: Number(pair.priceUsd), liquidityUsd: pair.liquidity?.usd, volume24h: pair.volume?.h24, fdv: pair.fdv };
    }
    if (symbol !== (chain === "solana" ? "SOL" : "ETH")) return null;
    const coin = `coingecko:${chain === "solana" ? "solana" : "ethereum"}`;
    const response = await fetch(`https://coins.llama.fi/prices/current/${coin}`, { signal: AbortSignal.timeout(2500) });
    if (!response.ok) return null;
    const data = await response.json() as { coins?: Record<string, { price: number; timestamp: number; confidence?: number }> };
    const price = data.coins?.[coin];
    if (!price || !Number.isFinite(price.price) || price.price <= 0 || !Number.isFinite(price.timestamp) || Math.abs(Date.now() / 1000 - price.timestamp) > 3600 || (price.confidence ?? 1) < 0.9) return null;
    return { priceUsd: price.price };
  } catch { return null; }
}

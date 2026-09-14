// ponytail: fetch from free APIs; HARD_PRICES only as emergency fallback
export const HARD_PRICES: Record<string, number> = {
  SOL: 150.0, ETH: 3200.0, USDC: 1.0, USDT: 1.0, DAI: 1.0,
};

const COINGECKO_IDS: Record<string, string> = {
  SOL: "solana", ETH: "ethereum", USDC: "usd-coin", USDT: "tether", DAI: "dai",
  BTC: "bitcoin", WBTC: "wrapped-bitcoin",
};

export async function getPriceUsdc(tokenSymbolOrAddress: string, chain?: string): Promise<number> {
  const key = (tokenSymbolOrAddress || "").toUpperCase();
  // Try free CoinGecko simple price (no key, rate-limited but sufficient for edge)
  try {
    const cgId = COINGECKO_IDS[key] || COINGECKO_IDS[key.replace(/^0x/, "")];
    if (cgId) {
      const resp = await fetch(
        `https://api.coingecko.com/api/v3/simple/price?ids=${cgId}&vs_currencies=usd`,
        { signal: AbortSignal.timeout(4000) }
      );
      if (resp.ok) {
        const d = (await resp.json()) as Record<string, { usd?: number }>;
        if (d[cgId]?.usd && d[cgId].usd > 0) return d[cgId].usd;
      }
    }
    // Fallback: crypto compare public price endpoint for common symbols
    const ccResp = await fetch(
      `https://min-api.cryptocompare.com/data/price?fsym=${key}&tsyms=USD`,
      { signal: AbortSignal.timeout(4000) }
    );
    if (ccResp.ok) {
      const d = (await ccResp.json()) as { USD?: number };
      if (d.USD && d.USD > 0) return d.USD;
    }
  } catch {
    // degrade to hardcoded
  }
  return HARD_PRICES[key] ?? 0.0;
}

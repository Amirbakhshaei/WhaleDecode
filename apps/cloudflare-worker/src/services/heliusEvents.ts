import { getPriceUsdc } from "./priceOracle";

export async function extractCandidateEvents(body: unknown): Promise<Array<{ chain: string; tx_hash: string; log_index: number; asset?: string; value_usd?: number; raw_json: unknown }>> {
  const payload = body as Record<string, unknown> | null;
  if (!payload) return [];
  const tx = (payload.transaction || payload.tx || {}) as Record<string, unknown>;
  const hash = String(tx.hash ?? payload.signature ?? payload.tx_hash ?? "unknown");
  const chain = String(payload.chain ?? "solana");
  const candidates: Array<{ chain: string; tx_hash: string; log_index: number; asset?: string; value_usd?: number; raw_json: unknown }> = [];
  const native = Array.isArray(payload.nativeTransfers) ? payload.nativeTransfers : [];
  for (let i = 0; i < native.length; i++) {
    const t = native[i] as Record<string, unknown>;
    const fromAddr = String(t.fromUserAccount ?? t.from ?? "");
    const toAddr = String(t.toUserAccount ?? t.to ?? "");
    const lamports = Number(t.amount ?? 0);
    const solPrice = await getPriceUsdc("SOL");
    const usd = lamports / 1e9 * (solPrice > 0 ? solPrice : 150.0);
    candidates.push({ chain, tx_hash: hash, log_index: i, asset: "SOL", value_usd: usd, raw_json: { from: fromAddr, to: toAddr, lamports, source: "native" } });
  }
  const token = Array.isArray(payload.tokenTransfers) ? payload.tokenTransfers : [];
  for (let i = 0; i < token.length; i++) {
    const t = token[i] as Record<string, unknown>;
    const mint = String(t.mint ?? t.tokenMint ?? "");
    const amountRaw = Number(t.tokenAmount ?? t.amount ?? 0);
    const price = await getPriceUsdc(mint || "TOKEN");
    candidates.push({ chain, tx_hash: hash, log_index: native.length + i, asset: mint ? `${mint.slice(0, 10)}...` : "TOKEN", value_usd: price > 0 ? amountRaw * price : 0, raw_json: { mint, amountRaw, source: "spl", from: t.fromUserAccount, to: t.toUserAccount } });
  }
  return candidates;
}

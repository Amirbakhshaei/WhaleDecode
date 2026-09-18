import type { Chain } from "../types.js";

interface Endpoint { url: string; failures: number; cooldownUntil: number }

const PUBLIC_RPCS: Record<Chain, string[]> = {
  ethereum: ["https://eth.llamarpc.com", "https://rpc.ankr.com/eth", "https://cloudflare-eth.com", "https://rpc.mevblocker.io"],
  arbitrum: ["https://arb1.arbitrum.io/rpc", "https://arbitrum.llamarpc.com"],
  base: ["https://mainnet.base.org", "https://base.llamarpc.com"],
  solana: ["https://api.mainnet-beta.solana.com"],
};

const COOLDOWN_MS = 60_000;
const TIMEOUT_MS = 8_000;

export class RpcPool {
  private pools: Record<Chain, Endpoint[]>;
  private cursor: Record<Chain, number> = { ethereum: 0, arbitrum: 0, base: 0, solana: 0 };

  constructor() {
    this.pools = Object.fromEntries(
      (Object.keys(PUBLIC_RPCS) as Chain[]).map((c) => [
        c,
        PUBLIC_RPCS[c].map((url) => ({ url, failures: 0, cooldownUntil: 0 })),
      ]),
    ) as Record<Chain, Endpoint[]>;
  }

  private pick(chain: Chain): Endpoint | null {
    const eps = this.pools[chain] ?? [];
    const now = Date.now();
    for (let i = 0; i < eps.length; i++) {
      const ep = eps[(this.cursor[chain] + i) % eps.length];
      if (ep && ep.cooldownUntil <= now) {
        this.cursor[chain] = (this.cursor[chain] + i + 1) % eps.length;
        return ep;
      }
    }
    return null;
  }

  private penalize(ep: Endpoint): void {
    ep.failures++;
    ep.cooldownUntil = Date.now() + COOLDOWN_MS;
  }

  async call<T>(chain: Chain, method: string, params: unknown[]): Promise<T> {
    const body = JSON.stringify({ jsonrpc: "2.0", id: 1, method, params });
    for (;;) {
      const ep = this.pick(chain);
      if (!ep) throw new Error(`all rpc endpoints cooling down for ${chain}`);
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
      try {
        const r = await fetch(ep.url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body,
          signal: ctrl.signal,
        });
        if (r.status === 429 || r.status >= 500) { this.penalize(ep); continue; }
        const j = (await r.json()) as { result?: T; error?: { message: string } };
        if (j.error) { this.penalize(ep); continue; }
        return j.result as T;
      } catch {
        this.penalize(ep);
      } finally {
        clearTimeout(t);
      }
    }
  }
}

export const rpcPool = new RpcPool();

// ponytail: lightweight multi-RPC router (no ethers; native fetch only)
export interface RPCConfig {
  primary: string;
  backup: string;
  timeoutMs?: number;
}

export async function rcpFetch<T = unknown>(endpoint: string, payload: unknown, timeoutMs = 4000): Promise<T> {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`RPC ${res.status}`);
  const data = (await res.json()) as T;
  if ((data as any)?.error) throw new Error(`RPC error: ${(data as any).error.message || JSON.stringify((data as any).error)}`);
  return data;
}

export async function multiRaceFetch<T = unknown>(cfg: RPCConfig, payload: unknown): Promise<T> {
  const endpoints = [cfg.primary, cfg.backup].filter(Boolean);
  let lastErr: Error | null = null;
  for (const url of endpoints) {
    try {
      return await rcpFetch<T>(url, payload, cfg.timeoutMs ?? 4000);
    } catch (e) {
      lastErr = new Error(String(e));
    }
  }
  throw lastErr ?? new Error("all_rpc_failed");
}

export async function multiFailoverFetch<T = unknown>(cfg: RPCConfig, payload: unknown, retries = 2): Promise<T> {
  const endpoints = [cfg.primary, cfg.backup].filter(Boolean);
  let lastErr: Error | null = null;
  for (let r = 0; r <= retries; r++) {
    for (const url of endpoints) {
      try {
        const res = await rcpFetch<T>(url, payload, cfg.timeoutMs ?? 4000);
        return res;
      } catch (e) {
        lastErr = new Error(String(e));
        // exponential backoff: 200ms * r
        if (r < retries) await new Promise((res) => setTimeout(res, 200 * (r + 1)));
      }
    }
  }
  throw lastErr ?? new Error("all_rpc_failed");
}

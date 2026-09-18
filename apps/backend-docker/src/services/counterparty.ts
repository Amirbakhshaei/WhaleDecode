import type { WorkerEvent } from "../types.js";
import { stealthSiblings } from "../db.js";

export interface CounterpartyClass {
  kind: "cold" | "cex" | "defi" | "dex" | "unknown";
  detail: string;
  conviction: "high" | "leverage" | "distribution" | "absorption" | "unknown";
}

const CEX = new Set([
  "0x21a31ee1afc51d94c2efccaa2092ad1028285549",
  "0xdfd5293d8e347dfe59e90efd55b2956a1343963d",
  "0x56eddb7aa87536c09ccc2793473599fd21a8b17f",
  "0xf977814e90da44bfa03b6295a0616a897441acec",
  "0x503828976d22510aad0201ac7ec88293211d23da",
  "0x2c8fbb630289363ac80705a1a61273f76fd5a161",
  "0xd6216fc19db775df9774a6e33526131da7d19a2c",
]);

const LENDING = new Set([
  "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",
]);

const DEX = new Set([
  "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",
  "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
  "0x1111111254eeb25477b68fb85ed929f73a960582",
]);

export const KNOWN_LABELS: Record<string, string> = {
  "0xd8da6bf26964af9d7eed9e03e53415d37aa96045": "vitalik.eth",
  "0x0716a17fbaee714f1e6ab0f9d59edbc5f09815c0": "Arthur Hayes / Maelstrom",
  "0x641ce4240508eae5dcaeffe991f80941d683ad64": "Dragonfly Capital",
  "0x9e78926c462212fee4ff14c9a274b851177bcee2": "Delphi Digital",
  "0x47ac0fb4f2d84898e4d9e7b4dab3c24507a6d503": "Jump Trading Reserve",
};

const COLD_HINT = /cold|vault|reserve|treasury|custody/i;

export function entityLabel(ev: WorkerEvent): string {
  const from = (ev.fromAddress || "").toLowerCase();
  return ev.wallet?.label || KNOWN_LABELS[from] || `${from.slice(0, 6)}…${from.slice(-4)}`;
}

export function classifyCounterparty(ev: WorkerEvent): CounterpartyClass {
  const to = (ev.toAddress || "").toLowerCase();
  const walletCat = ev.wallet?.category ?? "";
  if (CEX.has(to)) return { kind: "cex", detail: "CEX deposit address", conviction: "distribution" };
  if (LENDING.has(to)) return { kind: "defi", detail: "DeFi lending market deposit", conviction: "leverage" };
  if (DEX.has(to)) return { kind: "dex", detail: "DEX pool / aggregator router", conviction: "absorption" };
  if (COLD_HINT.test(walletCat) || COLD_HINT.test(ev.wallet?.label ?? "")) {
    return { kind: "cold", detail: "Cold storage / custody destination", conviction: "high" };
  }
  return { kind: "unknown", detail: "Unknown counterparty (no on-chain evidence)", conviction: "unknown" };
}

export function computeLar(liquidityUsd: number | undefined, usdValue: number): number | null {
  if (!liquidityUsd || liquidityUsd <= 0) return null;
  return Number(((usdValue / liquidityUsd) * 100).toFixed(2));
}

export interface StealthResult { flagged: boolean; siblings: number; windowHours: number; maxUsd: number }

export function detectStealth(ev: WorkerEvent, nowMs: number): StealthResult {
  const usd = Number(ev.usdValue);
  const sub50k = usd > 0 && usd < 50_000;
  const siblings = stealthSiblings(ev.chain, ev.fromAddress, nowMs - 6 * 3600_000, ev.idempotencyKey);
  return { flagged: sub50k && siblings >= 1, siblings, windowHours: 6, maxUsd: 50_000 };
}

export const NARRATIVES = [
  "AI & Autonomous Agents", "RWA & Institutional Yield", "DeFi Primitive",
  "High-Beta Meme", "L2 Infrastructure", "Macro Settlement",
] as const;

const NARRATIVE_HINTS: Array<[RegExp, string]> = [
  [/^(ai|agent|fetc?h|tao|render|akr|virtual|grt)$/i, "AI & Autonomous Agents"],
  [/^(ondo|tokenized|rwa|buidl|mkr|sky)$/i, "RWA & Institutional Yield"],
  [/^(eth|weth|steth|usdc|usdt|dai|wbtc|frxeth)$/i, "Macro Settlement"],
  [/^(uni|aave|comp|crv|cvx|ldo|pendle|ena)$/i, "DeFi Primitive"],
  [/^(arb|op|strk|mnt|base|zora)$/i, "L2 Infrastructure"],
];

export function classifyNarrative(symbol: string): string {
  for (const [re, n] of NARRATIVE_HINTS) if (re.test(symbol)) return n;
  return "High-Beta Meme";
}
